const { Pool } = require('pg');
const crypto = require('crypto');
const { indexKeys, lookupVariants } = require('./keys');

const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
  ssl: process.env.DATABASE_URL && process.env.DATABASE_URL.includes('localhost')
    ? false
    : { rejectUnauthorized: false },
});

async function initSchema() {
  await pool.query(`
    CREATE TABLE IF NOT EXISTS voters (
      id SERIAL PRIMARY KEY,
      token TEXT UNIQUE NOT NULL,
      segment TEXT NOT NULL CHECK (segment IN ('docente','familia')),
      display_name TEXT NOT NULL,
      contact TEXT,
      has_voted BOOLEAN NOT NULL DEFAULT FALSE,
      voted_at TIMESTAMPTZ,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    CREATE TABLE IF NOT EXISTS votes (
      id SERIAL PRIMARY KEY,
      segment TEXT NOT NULL CHECK (segment IN ('docente','familia')),
      candidate_id TEXT,
      cast_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    CREATE TABLE IF NOT EXISTS incidents (
      id SERIAL PRIMARY KEY,
      description TEXT NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    CREATE TABLE IF NOT EXISTS settings (
      key TEXT PRIMARY KEY,
      value TEXT
    );

    -- Chaves de acesso: telefone / e-mail / nome de estudante / nome de
    -- responsavel -> credencial. Usada pelo Portal da Familia (/acesso).
    -- NUNCA referencia votes. Ver comentario no topo de keys.js.
    CREATE TABLE IF NOT EXISTS voter_keys (
      id SERIAL PRIMARY KEY,
      voter_id INTEGER NOT NULL REFERENCES voters(id) ON DELETE CASCADE,
      key_norm TEXT NOT NULL,
      kind TEXT,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE (voter_id, key_norm)
    );
    CREATE INDEX IF NOT EXISTS voter_keys_key_norm_idx ON voter_keys (key_norm);
  `);
}

function newToken() {
  return crypto.randomBytes(9).toString('base64url');
}

// Indexa as chaves cruas de um eleitor (telefone/e-mail/nome). Idempotente:
// ON CONFLICT DO NOTHING pela UNIQUE(voter_id, key_norm).
async function insertVoterKeys(client, voterId, rawKeys) {
  let n = 0;
  for (const raw of rawKeys || []) {
    for (const k of indexKeys(raw)) {
      const kind = k.slice(0, 1) === 't' ? 'phone' : k.slice(0, 1) === 'e' ? 'email' : 'name';
      const r = await client.query(
        `INSERT INTO voter_keys (voter_id, key_norm, kind) VALUES ($1,$2,$3)
         ON CONFLICT (voter_id, key_norm) DO NOTHING`,
        [voterId, k, kind]
      );
      n += r.rowCount;
    }
  }
  return n;
}

async function importVoters(rows, opts = {}) {
  // rows: [{ name, contact, segment, keys? }]
  //   keys: array opcional de strings cruas (telefone/e-mail/nome) a indexar
  //   no Portal da Familia.
  // opts.replaceSegment: se setado (ex. 'docente'), APAGA todos os eleitores
  //   desse segmento ANTES de importar, na mesma transacao. Aborta (rollback)
  //   se algum eleitor desse segmento ja votou.
  const client = await pool.connect();
  const results = [];
  let removed = 0;
  try {
    await client.query('BEGIN');
    if (opts.replaceSegment) {
      const seg = opts.replaceSegment;
      const voted = await client.query(
        'SELECT count(*)::int AS n FROM voters WHERE segment = $1 AND has_voted = TRUE',
        [seg]
      );
      if (voted.rows[0].n > 0) {
        throw new Error(
          `${voted.rows[0].n} eleitor(es) do segmento "${seg}" ja votaram — substituicao abortada, nada foi alterado.`
        );
      }
      const del = await client.query('DELETE FROM voters WHERE segment = $1', [seg]);
      removed = del.rowCount; // voter_keys cai por ON DELETE CASCADE; votos sao anonimos
    }
    for (const row of rows) {
      let token = newToken();
      let voterId = null;
      for (let attempt = 0; attempt < 5 && voterId == null; attempt++) {
        try {
          const r = await client.query(
            'INSERT INTO voters (token, segment, display_name, contact) VALUES ($1,$2,$3,$4) RETURNING id',
            [token, row.segment, row.name, row.contact || null]
          );
          voterId = r.rows[0].id;
        } catch (e) {
          if (e.code === '23505') { // unique_violation on token, retry with a fresh one
            token = newToken();
          } else {
            throw e;
          }
        }
      }
      // Chaves implicitas: o proprio contato e o proprio nome sempre entram.
      const rawKeys = [row.contact, row.name, ...(row.keys || [])].filter(Boolean);
      const nKeys = await insertVoterKeys(client, voterId, rawKeys);
      results.push({ ...row, token, keysIndexed: nKeys });
    }
    await client.query('COMMIT');
  } catch (e) {
    await client.query('ROLLBACK');
    throw e;
  } finally {
    client.release();
  }
  return { results, removed };
}

// Vincula chaves cruas a credenciais JA existentes, localizadas pelo token.
// pairs: [{ token, keys: [rawString, ...] }]
async function attachKeysByToken(pairs) {
  const client = await pool.connect();
  const out = { linked: 0, keysIndexed: 0, missing: [] };
  try {
    await client.query('BEGIN');
    for (const p of pairs) {
      const r = await client.query('SELECT id FROM voters WHERE token = $1', [p.token]);
      if (!r.rows[0]) { out.missing.push(p.token); continue; }
      const n = await insertVoterKeys(client, r.rows[0].id, p.keys || []);
      out.linked += 1;
      out.keysIndexed += n;
    }
    await client.query('COMMIT');
  } catch (e) {
    await client.query('ROLLBACK');
    throw e;
  } finally {
    client.release();
  }
  return out;
}

// Busca do Portal da Familia. Recebe o texto cru digitado, gera as variantes
// normalizadas e devolve os eleitores distintos que casam. Nunca toca em votes.
async function lookupByRawKey(rawQuery) {
  const variants = lookupVariants(rawQuery);
  if (!variants.length) return { ok: false, reason: 'vago', voters: [] };
  const r = await pool.query(
    `SELECT DISTINCT v.token, v.display_name, v.segment
       FROM voter_keys k JOIN voters v ON v.id = k.voter_id
      WHERE k.key_norm = ANY($1)
      ORDER BY v.display_name
      LIMIT 8`,
    [variants]
  );
  return { ok: true, voters: r.rows };
}

async function getVoterByToken(token) {
  const r = await pool.query('SELECT * FROM voters WHERE token = $1', [token]);
  return r.rows[0] || null;
}

// Remove uma credencial (e suas voter_keys, por ON DELETE CASCADE) a partir do
// token. Recusa se o eleitor JA VOTOU — para corrigir importacao errada sem
// arriscar mexer em quem ja participou. Nunca toca na tabela votes.
async function deleteVoterByToken(token) {
  const client = await pool.connect();
  try {
    await client.query('BEGIN');
    const r = await client.query(
      'SELECT id, display_name, has_voted FROM voters WHERE token = $1 FOR UPDATE',
      [token]
    );
    const v = r.rows[0];
    if (!v) {
      await client.query('ROLLBACK');
      return { ok: false, reason: 'not_found' };
    }
    if (v.has_voted) {
      await client.query('ROLLBACK');
      return { ok: false, reason: 'has_voted', display_name: v.display_name };
    }
    await client.query('DELETE FROM voters WHERE id = $1', [v.id]);
    await client.query('COMMIT');
    return { ok: true, display_name: v.display_name };
  } catch (e) {
    await client.query('ROLLBACK');
    throw e;
  } finally {
    client.release();
  }
}

async function castVote(token, candidateId) {
  const client = await pool.connect();
  try {
    await client.query('BEGIN');
    const r = await client.query('SELECT * FROM voters WHERE token = $1 FOR UPDATE', [token]);
    const voter = r.rows[0];
    if (!voter) {
      await client.query('ROLLBACK');
      return { ok: false, reason: 'not_found' };
    }
    if (voter.has_voted) {
      await client.query('ROLLBACK');
      return { ok: false, reason: 'already_voted' };
    }
    const open = await isVotingOpenTx(client);
    if (!open) {
      await client.query('ROLLBACK');
      return { ok: false, reason: 'closed' };
    }
    await client.query(
      'INSERT INTO votes (segment, candidate_id) VALUES ($1,$2)',
      [voter.segment, candidateId || null]
    );
    await client.query(
      'UPDATE voters SET has_voted = TRUE, voted_at = now() WHERE id = $1',
      [voter.id]
    );
    await client.query('COMMIT');
    return { ok: true, segment: voter.segment };
  } catch (e) {
    await client.query('ROLLBACK');
    throw e;
  } finally {
    client.release();
  }
}

async function isVotingOpenTx(client) {
  const r = await client.query("SELECT key, value FROM settings WHERE key IN ('opened_at','closed_at')");
  const map = Object.fromEntries(r.rows.map((row) => [row.key, row.value]));
  return Boolean(map.opened_at) && !map.closed_at;
}

async function isVotingOpen() {
  const r = await pool.query("SELECT key, value FROM settings WHERE key IN ('opened_at','closed_at')");
  const map = Object.fromEntries(r.rows.map((row) => [row.key, row.value]));
  return Boolean(map.opened_at) && !map.closed_at;
}

async function setSetting(key, value) {
  await pool.query(
    'INSERT INTO settings (key, value) VALUES ($1,$2) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value',
    [key, value]
  );
}

async function clearSetting(key) {
  await pool.query('DELETE FROM settings WHERE key = $1', [key]);
}

async function getSettings() {
  const r = await pool.query('SELECT key, value FROM settings');
  return Object.fromEntries(r.rows.map((row) => [row.key, row.value]));
}

async function stats() {
  const aptos = await pool.query(
    "SELECT segment, count(*)::int AS total FROM voters GROUP BY segment"
  );
  const votantes = await pool.query(
    "SELECT segment, count(*)::int AS total FROM voters WHERE has_voted GROUP BY segment"
  );
  const resultados = await pool.query(
    "SELECT segment, candidate_id, count(*)::int AS total FROM votes GROUP BY segment, candidate_id"
  );
  return { aptos: aptos.rows, votantes: votantes.rows, resultados: resultados.rows };
}

async function listVoters() {
  const r = await pool.query(
    'SELECT token, segment, display_name, contact, has_voted, voted_at, created_at FROM voters ORDER BY segment, display_name'
  );
  return r.rows;
}

async function searchVotersByName(query) {
  const r = await pool.query(
    `SELECT token, segment, display_name, contact, has_voted, voted_at FROM voters
     WHERE display_name ILIKE '%' || $1 || '%'
     ORDER BY display_name LIMIT 25`,
    [query]
  );
  return r.rows;
}

async function addIncident(description) {
  await pool.query('INSERT INTO incidents (description) VALUES ($1)', [description]);
}

async function listIncidents() {
  const r = await pool.query('SELECT * FROM incidents ORDER BY created_at DESC');
  return r.rows;
}

async function resetTestData() {
  await pool.query('DELETE FROM votes');
  await pool.query('DELETE FROM voter_keys');
  await pool.query('DELETE FROM voters');
  await pool.query('DELETE FROM incidents');
  await pool.query("DELETE FROM settings WHERE key IN ('opened_at','closed_at','published')");
}

async function keyStats() {
  const r = await pool.query(
    `SELECT kind, count(*)::int AS total,
            count(DISTINCT voter_id)::int AS eleitores
       FROM voter_keys GROUP BY kind`
  );
  return r.rows;
}

module.exports = {
  pool,
  initSchema,
  importVoters,
  attachKeysByToken,
  lookupByRawKey,
  keyStats,
  getVoterByToken,
  deleteVoterByToken,
  castVote,
  isVotingOpen,
  setSetting,
  clearSetting,
  getSettings,
  stats,
  listVoters,
  searchVotersByName,
  addIncident,
  listIncidents,
  resetTestData,
};
