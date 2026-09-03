require('dotenv').config();
const express = require('express');
const session = require('express-session');
const path = require('path');
const crypto = require('crypto');
const db = require('./db');
const { candidatesFor, candidateById, isValidSegment, SEGMENT_LABELS } = require('./candidates');

const PORT = process.env.PORT || 3000;
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || '';

// ---------- Janela oficial de votação ----------
// Fonte única da verdade para os textos de prazo mostrados ao eleitor. A
// lógica de abrir/encerrar continua sendo o clique da Comissão no painel
// (settings.opened_at / closed_at); isto aqui NÃO fecha nada sozinho — só
// informa o prazo e destaca a prorrogação. Se houver nova prorrogação,
// mude só este bloco e faça o deploy (o histórico do git serve de registro).
const JANELA = {
  inicio: '31/08/2026',
  fim: '08/09/2026',
  diaSemana: 'terça-feira',
  horaLimite: '12h',
  limiteISO: '2026-09-08T12:00:00-03:00', // 12h de Brasília (America/Sao_Paulo)
  // Data anterior, antes da prorrogação. Deixe '' se nunca houve prorrogação.
  prorrogadoDe: '05/09/2026',
};

function janelaTexto() {
  return `${JANELA.inicio} a ${JANELA.fim}, até ${JANELA.horaLimite}`;
}

// Aviso curto de prorrogação para as páginas que o eleitor vê.
function avisoProrrogacao() {
  if (!JANELA.prorrogadoDe) return '';
  return `<p class="warn"><strong>Prazo prorrogado:</strong> a votação foi
    estendida até <strong>${JANELA.fim} (${JANELA.diaSemana}), às
    ${JANELA.horaLimite}</strong> — antes era ${JANELA.prorrogadoDe}. Quem
    ainda não votou pode votar normalmente até lá.</p>`;
}

// Envolve uma rota async: erros vao para o middleware de erro em vez de
// derrubar o processo ou deixar a requisicao pendurada.
function ah(fn) {
  return (req, res, next) => fn(req, res, next).catch(next);
}

function safeEqual(a, b) {
  const bufA = Buffer.from(String(a));
  const bufB = Buffer.from(String(b));
  if (bufA.length !== bufB.length) return false;
  return crypto.timingSafeEqual(bufA, bufB);
}

const app = express();
app.use(express.urlencoded({ extended: true }));
app.use(express.static(path.join(__dirname, 'public')));
app.use(
  session({
    secret: process.env.SESSION_SECRET || 'troque-este-segredo',
    resave: false,
    saveUninitialized: false,
    cookie: { maxAge: 1000 * 60 * 60 * 8 },
  })
);

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

function page(title, body) {
  return `<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escapeHtml(title)} — Urna EMIA</title>
<link rel="stylesheet" href="/style.css">
</head>
<body>
<div class="wrap">
${body}
</div>
</body>
</html>`;
}

function requireAdmin(req, res, next) {
  if (req.session && req.session.isAdmin) return next();
  res.redirect('/admin');
}

// Rate limiter simples em memoria (o Render roda 1 instancia). Protege o
// Portal da Familia de alguem tentar "adivinhar" contatos em massa.
function makeRateLimiter(maxHits, windowMs) {
  const hits = new Map();
  return function limited(key) {
    const now = Date.now();
    const arr = (hits.get(key) || []).filter((t) => now - t < windowMs);
    arr.push(now);
    hits.set(key, arr);
    if (hits.size > 5000) { // faxina preguicosa
      for (const [k, v] of hits) if (!v.some((t) => now - t < windowMs)) hits.delete(k);
    }
    return arr.length > maxHits;
  };
}
// Tolerante: várias famílias podem sair do mesmo wi-fi (escola, prédio).
const acessoLimiter = makeRateLimiter(60, 15 * 60 * 1000);

function maskName(s) {
  return String(s || '')
    .split(/\s+/)
    .filter(Boolean)
    .map((w) => (w.length <= 2 ? w : w[0] + '•'.repeat(Math.min(w.length - 1, 4))))
    .join(' ');
}

// Faz o parse do textarea de importacao. Aceita dois formatos por linha:
//   - CSV legado:  nome,contato,segmento
//   - TSV com chaves: display_name <TAB> segmento <TAB> contato <TAB> chave;chave;...
// Devolve { rows: [{name, contact, segment, keys}], errors: [] }
function parseImport(raw) {
  const lines = String(raw || '').split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  const rows = [];
  const errors = [];
  const normSeg = (v) => {
    const s = String(v || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
    if (s.startsWith('doc')) return 'docente';
    if (s.startsWith('fam')) return 'familia';
    return null;
  };
  for (const line of lines) {
    if (/^(nome|display_name|nome_da_familia)\b/i.test(line)) continue; // cabecalho
    if (line.includes('\t')) {
      const [name, segRaw, contact, keysRaw] = line.split('\t').map((p) => (p || '').trim());
      const segment = normSeg(segRaw);
      if (!name || !segment) { errors.push(`Linha ignorada (nome/segmento): ${line}`); continue; }
      const keys = (keysRaw || '').split(';').map((k) => k.trim()).filter(Boolean);
      rows.push({ name, contact: contact || '', segment, keys });
    } else {
      const parts = line.split(',').map((p) => p.trim());
      if (parts.length < 3) { errors.push(`Linha ignorada (formato incorreto): ${line}`); continue; }
      const [name, contact, segRaw] = parts;
      const segment = normSeg(segRaw);
      if (!segment) { errors.push(`Segmento invalido (linha ignorada): ${line}`); continue; }
      rows.push({ name, contact, segment, keys: [] });
    }
  }
  return { rows, errors };
}

// ---------- Eleitor ----------

app.get('/', (req, res) => {
  res.send(page('Urna EMIA', `
    <h1>Urna Eletrônica — Conselho EMIA</h1>
    <p>Este é o sistema de votação da eleição do Conselho da Escola Municipal
    de Iniciação Artística (biênio 2026-2028).</p>
    <p>Período oficial de votação: <strong>${janelaTexto()}</strong>.</p>
    ${avisoProrrogacao()}
    <p>Para votar, use o link individual enviado pela Comissão Eleitoral
    (algo como <code>/votar/SEU-CODIGO</code>). Não existe uma página de
    votação genérica — cada credencial é pessoal e intransferível.</p>
    <p><strong>Não recebeu ou perdeu seu link?</strong> Famílias e docentes
    podem acessar <a href="/acesso">/acesso</a> e informar um telefone, e-mail,
    o próprio nome completo ou o nome completo de um(a) estudante da família
    para chegar à cédula certa.</p>
    <p><a href="/resultados">Ver resultados</a> (disponível após a apuração).</p>
  `));
});

app.get('/votar/:token', ah(async (req, res) => {
  const voter = await db.getVoterByToken(req.params.token);
  if (!voter) {
    return res.status(404).send(page('Credencial inválida', `
      <h1>Credencial não encontrada</h1>
      <p>Esse link não corresponde a nenhuma credencial cadastrada.
      Confira o link recebido ou entre em contato com a Comissão Eleitoral.</p>
    `));
  }
  if (voter.has_voted) {
    return res.send(page('Voto já registrado', `
      <h1>Voto já registrado</h1>
      <p>Sua credencial já foi utilizada em ${new Date(voter.voted_at).toLocaleString('pt-BR')}.
      Cada eleitor vota apenas uma vez. Se você acha que isso é um erro,
      procure a Comissão Eleitoral.</p>
    `));
  }
  const open = await db.isVotingOpen();
  if (!open) {
    const s = await db.getSettings();
    const encerrada = Boolean(s.closed_at);
    return res.send(page('Votação fechada', encerrada
      ? `<h1>Votação encerrada</h1>
         <p>A votação foi encerrada pela Comissão Eleitoral em
         ${new Date(Number(s.closed_at)).toLocaleString('pt-BR')}. Não é mais
         possível registrar votos por este link.</p>`
      : `<h1>Votação ainda não começou</h1>
         <p>A votação ainda não foi aberta pela Comissão Eleitoral. Guarde
         este link para o período oficial de votação
         (${janelaTexto()}).</p>
         ${avisoProrrogacao()}`));
  }
  const candidates = candidatesFor(voter.segment);
  const options = candidates.map((c) => `
    <label class="candidate">
      <input type="radio" name="candidate_id" value="${escapeHtml(c.id)}" required>
      ${c.photo ? `<img class="cand-foto" src="${escapeHtml(c.photo)}" alt="Foto de ${escapeHtml(c.name)}" width="76" height="95" loading="lazy">` : ''}
      <span class="cand-info"><strong>${escapeHtml(c.name)}</strong>${c.unit ? `<span class="cand-unit">${escapeHtml(c.unit)}</span>` : ''}</span>
    </label>
    ${c.bio ? `<details class="bio"><summary>Ver biografia de ${escapeHtml(c.name)}</summary><p>${escapeHtml(c.bio)}</p></details>` : ''}
  `).join('');
  const avisoFamilia = voter.segment === 'familia'
    ? '<p class="warn">Atenção, famílias: o voto é por família — apenas um(a) responsável deve votar por família (Edital, item 3.4.1). Confirmem entre vocês quem vai votar antes de usar este link.</p>'
    : '';
  res.send(page('Votar', `
    <h1>Cédula — ${escapeHtml(SEGMENT_LABELS[voter.segment])}</h1>
    <p>Eleitor(a): <strong>${escapeHtml(voter.display_name)}</strong></p>
    <p class="warn">Seu voto é secreto. O sistema não guarda nenhuma ligação
    entre sua identidade e o candidato escolhido.</p>
    ${avisoFamilia}
    <form method="post" action="/votar/${escapeHtml(req.params.token)}">
      ${options}
      <label class="candidate">
        <input type="radio" name="candidate_id" value="" required>
        <span><strong>Voto em branco</strong></span>
      </label>
      <button type="submit">Confirmar voto</button>
    </form>
    <p class="warn">Atenção: o voto é definitivo. Não é possível trocar depois de enviado.</p>
  `));
}));

app.post('/votar/:token', ah(async (req, res) => {
  const voter = await db.getVoterByToken(req.params.token);
  if (!voter) return res.status(404).send(page('Erro', '<h1>Credencial não encontrada</h1>'));

  const candidateId = req.body.candidate_id || null;
  if (candidateId && !candidateById(voter.segment, candidateId)) {
    return res.status(400).send(page('Erro', '<h1>Candidata inválida para este segmento</h1>'));
  }

  const result = await db.castVote(req.params.token, candidateId);
  if (!result.ok) {
    if (result.reason === 'already_voted') {
      return res.send(page('Voto já registrado', '<h1>Este voto já havia sido registrado.</h1>'));
    }
    if (result.reason === 'closed') {
      return res.send(page('Votação fechada', '<h1>A votação não está aberta no momento.</h1>'));
    }
    return res.status(400).send(page('Erro', '<h1>Não foi possível registrar o voto.</h1>'));
  }
  res.send(page('Voto registrado', `
    <h1>Voto registrado com sucesso</h1>
    <p>Obrigado por participar da eleição do Conselho da EMIA.</p>
    <p>Registrado em: ${new Date().toLocaleString('pt-BR')}</p>
  `));
}));

// ---------- Portal de acesso à votação (autoatendimento) ----------
// UM link só (/acesso) para TODO MUNDO que vota — famílias e docentes — que
// não recebeu ou perdeu o link individual. A pessoa digita um dado
// (telefone, e-mail, o próprio nome, ou o nome de um(a) estudante da família)
// e é levada à sua cédula. Um voto por família: se a família tem mais de um
// estudante ou mais de um responsável, todos caem na MESMA credencial. Quem é
// docente E responsável por estudante e consta nas duas listas tem as duas
// credenciais (uma em cada segmento).

function acessoForm(msg, valor) {
  return `
    <h1>Acesso à votação — Conselho EMIA</h1>
    ${avisoProrrogacao()}
    <p>Esta página é para <strong>todo mundo que vai votar</strong> — famílias
    <strong>e docentes</strong> — que não recebeu ou perdeu o link individual.
    Digite <strong>um</strong> dos dados abaixo e o sistema leva você à sua
    cédula:</p>
    <ul>
      <li>seu <strong>telefone</strong> (celular) cadastrado na EMIA, ou</li>
      <li>seu <strong>e-mail</strong> cadastrado, ou</li>
      <li>seu <strong>nome completo</strong> (serve para docentes), ou</li>
      <li>o <strong>nome completo</strong> de um(a) estudante da sua família.</li>
    </ul>
    ${msg || ''}
    <form method="post" action="/acesso">
      <input type="text" name="q" required autofocus autocomplete="off"
        placeholder="Ex.: 11 98765-4321  •  nome@email.com  •  seu nome completo  •  nome do(a) estudante"
        value="${escapeHtml(valor || '')}">
      <button type="submit">Buscar minha cédula</button>
    </form>
    <p>Na tela seguinte aparece o <strong>segmento</strong> (Corpo Docente ou
    Famílias) e um trecho do nome, para você confirmar que é a sua credencial
    antes de abrir a cédula.</p>
    <p class="warn">No segmento <strong>Famílias</strong> o voto é por família:
    <strong>apenas um(a) responsável</strong> vota e, mesmo com mais de um(a)
    filho(a) na EMIA, é <strong>um único voto</strong> — combinem entre vocês
    quem vota. <strong>Docentes</strong> votam individualmente; quem é docente e
    também responsável por estudante e consta nas duas listas pode votar nos
    dois segmentos (uma vez em cada).</p>
    <p class="muted">Seu voto é secreto. O sistema usa seus dados só para te
    levar à cédula certa — não há nenhuma ligação entre você e o voto que for
    registrado.</p>
  `;
}

app.get('/acesso', ah(async (req, res) => {
  const s = await db.getSettings();
  if (s.portal_off === '1') {
    return res.send(page('Acesso', `
      <h1>Autoatendimento indisponível</h1>
      <p>Use o link individual enviado pela Comissão Eleitoral, ou procure a
      Comissão para receber o seu.</p>`));
  }
  res.send(page('Acesso à votação', acessoForm()));
}));

app.post('/acesso', ah(async (req, res) => {
  const s = await db.getSettings();
  if (s.portal_off === '1') return res.redirect('/acesso');

  const ip = (req.headers['x-forwarded-for'] || req.ip || '').split(',')[0].trim();
  if (acessoLimiter(ip)) {
    return res.status(429).send(page('Muitas tentativas', `
      <h1>Muitas tentativas</h1>
      <p>Aguarde alguns minutos e tente de novo, ou procure a Comissão
      Eleitoral para receber seu link individual.</p>`));
  }

  const q = (req.body.q || '').trim();
  const r = await db.lookupByRawKey(q);
  if (!r.ok) {
    return res.send(page('Acesso à votação', acessoForm(
      `<p class="warn">Digite um telefone completo (com DDD), um e-mail
       completo, o seu nome e sobrenome, ou o nome e sobrenome de um(a)
       estudante.</p>`, q)));
  }
  if (r.voters.length === 0) {
    return res.send(page('Acesso à votação', acessoForm(
      `<p class="warn">Não encontramos ninguém com esse dado. Tente outro
       telefone/e-mail cadastrado, o seu nome completo (docentes) ou o nome
       completo do(a) estudante. Se nada funcionar, fale com a Comissão
       Eleitoral.</p>`, q)));
  }
  const host = req.protocol + '://' + req.get('host');
  const cards = r.voters.map((v) => `
    <div class="candidate" style="display:block">
      <p style="margin:.2rem 0"><strong>${escapeHtml(SEGMENT_LABELS[v.segment] || v.segment)}</strong>
      — ${escapeHtml(maskName(v.display_name))}</p>
      <a href="${host}/votar/${escapeHtml(v.token)}"><button type="button">Abrir minha cédula</button></a>
    </div>
  `).join('');
  res.send(page('Sua cédula', `
    <h1>Encontramos sua credencial</h1>
    ${r.voters.length > 1
      ? '<p>Mais de uma credencial casou com esse dado (por exemplo, quem é docente <em>e</em> responsável por estudante). Confira o segmento e escolha a que você quer usar agora:</p>'
      : '<p>Confira o segmento e o trecho do nome abaixo e abra sua cédula.</p>'}
    ${cards}
    <p class="warn">Se não parece ser a sua credencial, volte e tente com
    outro dado. Em caso de dúvida, procure a Comissão Eleitoral.</p>
    <p><a href="/acesso">← tentar outro dado</a></p>
  `));
}));

// ---------- Resultados públicos ----------

app.get('/resultados', ah(async (req, res) => {
  const settings = await db.getSettings();
  if (!settings.published) {
    return res.send(page('Resultados', `
      <h1>Resultados</h1>
      <p>Os resultados ainda não foram publicados pela Comissão Eleitoral.</p>
    `));
  }
  res.send(page('Resultados', await renderResultsHtml()));
}));

async function renderResultsHtml() {
  const { aptos, votantes, resultados } = await db.stats();
  const aptosMap = Object.fromEntries(aptos.map((r) => [r.segment, r.total]));
  const votantesMap = Object.fromEntries(votantes.map((r) => [r.segment, r.total]));

  let html = '<h1>Resultados — Conselho EMIA 2026-2028</h1>';
  for (const segment of ['docente', 'familia']) {
    const total_aptos = aptosMap[segment] || 0;
    const total_votantes = votantesMap[segment] || 0;
    const rows = resultados.filter((r) => r.segment === segment);
    const brancos = rows.find((r) => r.candidate_id === null)?.total || 0;
    const porCandidata = candidatesFor(segment).map((c) => {
      const total = rows.find((r) => r.candidate_id === c.id)?.total || 0;
      return { ...c, total };
    }).sort((a, b) => b.total - a.total);

    html += `<h2>${escapeHtml(SEGMENT_LABELS[segment])}</h2>`;
    html += `<p>Eleitores aptos: ${total_aptos} — Votantes: ${total_votantes} (${
      total_aptos ? Math.round((total_votantes / total_aptos) * 100) : 0
    }%) — Votos em branco: ${brancos}</p>`;
    html += '<table><thead><tr><th>Candidata</th><th>Votos</th><th>Situação</th></tr></thead><tbody>';
    porCandidata.forEach((c, i) => {
      const situacao = i === 0 ? 'Titular' : i === 1 ? 'Suplente' : '—';
      html += `<tr><td>${escapeHtml(c.name)}</td><td>${c.total}</td><td>${situacao}</td></tr>`;
    });
    html += '</tbody></table>';
  }
  return html;
}

// ---------- Admin ----------

app.get('/admin', (req, res) => {
  if (req.session.isAdmin) return res.redirect('/admin/painel');
  res.send(page('Admin', `
    <h1>Comissão Eleitoral — acesso</h1>
    <form method="post" action="/admin/login">
      <label>Senha da Comissão
        <input type="password" name="password" required autofocus>
      </label>
      <button type="submit">Entrar</button>
    </form>
  `));
});

app.post('/admin/login', (req, res) => {
  if (ADMIN_PASSWORD && safeEqual(req.body.password || '', ADMIN_PASSWORD)) {
    req.session.isAdmin = true;
    return res.redirect('/admin/painel');
  }
  res.status(401).send(page('Admin', `
    <h1>Senha incorreta</h1>
    <p><a href="/admin">Tentar novamente</a></p>
  `));
});

app.post('/admin/logout', (req, res) => {
  req.session.destroy(() => res.redirect('/admin'));
});

app.get('/admin/painel', requireAdmin, ah(async (req, res) => {
  const { aptos, votantes } = await db.stats();
  const settings = await db.getSettings();
  const aptosMap = Object.fromEntries(aptos.map((r) => [r.segment, r.total]));
  const votantesMap = Object.fromEntries(votantes.map((r) => [r.segment, r.total]));
  const incidents = await db.listIncidents();
  const kstats = await db.keyStats();
  const kmap = Object.fromEntries(kstats.map((r) => [r.kind, r]));
  const portalOff = settings.portal_off === '1';

  const statusVotacao = settings.closed_at
    ? `Encerrada em ${new Date(Number(settings.closed_at)).toLocaleString('pt-BR')}`
    : settings.opened_at
      ? `Aberta desde ${new Date(Number(settings.opened_at)).toLocaleString('pt-BR')}`
      : 'Não iniciada';

  const limiteMs = Date.parse(JANELA.limiteISO);
  const passouDoLimite = Number.isFinite(limiteMs)
    && Date.now() > limiteMs && settings.opened_at && !settings.closed_at;
  const linhaProrrogacao = JANELA.prorrogadoDe
    ? `<br><em>Prorrogação registrada: prazo anterior era ${JANELA.prorrogadoDe}.</em>`
    : '';
  const avisoPassouLimite = passouDoLimite
    ? '<p class="warn"><strong>Atenção:</strong> já passou do horário-limite oficial e a votação continua aberta. Encerre a votação e faça a apuração.</p>'
    : '';

  res.send(page('Painel da Comissão', `
    <h1>Painel da Comissão Eleitoral</h1>
    <form method="post" action="/admin/logout" style="display:inline"><button>Sair</button></form>

    <h2>Status da votação</h2>
    <p>${escapeHtml(statusVotacao)}</p>
    <p>Janela oficial: <strong>${janelaTexto()}</strong>
      (limite: ${JANELA.fim} ${JANELA.diaSemana}, ${JANELA.horaLimite} de Brasília).
      ${linhaProrrogacao}</p>
    ${avisoPassouLimite}
    <p class="muted">A votação não fecha sozinha — ela só encerra quando a
    Comissão clicar em "Encerrar votação agora".</p>
    <form method="post" action="/admin/abrir" style="display:inline">
      <button ${settings.opened_at ? 'disabled' : ''}>Abrir votação agora</button>
    </form>
    <form method="post" action="/admin/encerrar" style="display:inline">
      <button ${settings.closed_at || !settings.opened_at ? 'disabled' : ''}>Encerrar votação agora</button>
    </form>

    <h2>Participação</h2>
    <table><thead><tr><th>Segmento</th><th>Aptos</th><th>Votantes</th><th>%</th></tr></thead><tbody>
      ${['docente', 'familia'].map((s) => {
        const a = aptosMap[s] || 0; const v = votantesMap[s] || 0;
        return `<tr><td>${escapeHtml(SEGMENT_LABELS[s])}</td><td>${a}</td><td>${v}</td><td>${a ? Math.round((v / a) * 100) : 0}%</td></tr>`;
      }).join('')}
    </tbody></table>

    <h2>Apuração</h2>
    <p><a href="/admin/apuracao">Ver apuração detalhada</a> —
    <a href="/admin/relatorio.txt">Baixar relatório final (.txt)</a></p>
    <form method="post" action="/admin/publicar">
      <button ${settings.published ? 'disabled' : ''}>Publicar resultados publicamente</button>
    </form>
    ${settings.published ? '<p>Resultados já publicados em /resultados.</p>' : ''}

    <h2>Importar eleitores</h2>
    <p>Uma pessoa/família por linha. Dois formatos aceitos:</p>
    <ul>
      <li><code>nome,contato,segmento</code> (simples), ou</li>
      <li><code>nome[TAB]segmento[TAB]contato[TAB]chave;chave;chave</code>
      (com chaves de acesso — é o que o <code>instalador.py</code> gera nos
      arquivos <code>B_novos_eleitores.tsv</code>).</li>
    </ul>
    <p>As <em>chaves</em> são telefones, e-mails e nomes de estudantes/responsáveis
    que levam ao Portal da Família (<code>/acesso</code>). O próprio nome e o
    próprio contato já viram chave automaticamente.</p>
    <form method="post" action="/admin/importar">
      <textarea name="csv" rows="8" style="width:100%" placeholder="Maria Silva,11999999999,docente
Família de João e Ana Souza&#9;familia&#9;11988887777&#9;11988887777;joao@email.com;João Pedro Souza;Ana Clara Souza"></textarea>
      <label style="display:block;margin:.6em 0">
        <input type="checkbox" name="replace_docente" value="1">
        <strong>Substituir os docentes</strong>: apaga os docentes já cadastrados
        antes de importar (use ao reenviar a lista de docentes corrigida).
        Não afeta as famílias. Bloqueado se algum docente já votou.
      </label>
      <button type="submit">Importar e gerar credenciais</button>
    </form>

    <h2>Vincular chaves a credenciais já existentes</h2>
    <p>Para as credenciais que já foram geradas antes (arquivo
    <code>A_chaves_para_tokens_existentes.tsv</code> do instalador). Uma por
    linha: <code>TOKEN[TAB]chave;chave;chave</code>. Não gera credencial nova,
    só acrescenta chaves de acesso. Rodar de novo é seguro (não duplica).</p>
    <form method="post" action="/admin/vincular-chaves">
      <textarea name="pares" rows="6" style="width:100%" placeholder="B3PLmdWNz27g&#9;11957569998;maria@email.com;Pedro Henrique Antunes"></textarea>
      <button type="submit">Vincular chaves</button>
    </form>

    <h2>Portal da Família (/acesso)</h2>
    <p>Chaves indexadas:
      <strong>${kmap.phone?.total || 0}</strong> telefones,
      <strong>${kmap.email?.total || 0}</strong> e-mails,
      <strong>${kmap.name?.total || 0}</strong> nomes
      — cobrindo <strong>${Math.max(kmap.phone?.eleitores || 0, kmap.email?.eleitores || 0, kmap.name?.eleitores || 0)}</strong> credenciais.</p>
    <p>Status: <strong>${portalOff ? 'DESLIGADO' : 'LIGADO'}</strong>
      (<a href="/acesso" target="_blank" rel="noopener">abrir /acesso</a>)</p>
    <form method="post" action="/admin/portal-toggle">
      <button type="submit">${portalOff ? 'Ligar' : 'Desligar'} o portal</button>
    </form>

    <h2>Lista de eleitores e credenciais</h2>
    <p><a href="/admin/credenciais.csv">Baixar lista completa (CSV) para distribuição</a> —
    <a href="/admin/buscar">Buscar eleitor por nome (urna física / atendimento presencial)</a></p>

    <h2>Remover credencial (corrigir importação errada)</h2>
    <p>Cole os <strong>tokens</strong> das credenciais a apagar, um por linha (o
    token é o final do link <code>/votar/…</code>, visível no CSV de
    credenciais). Serve para desfazer uma credencial que juntou famílias
    diferentes por engano: apague a errada e depois reimporte as certas em
    "Importar eleitores".</p>
    <p>Sem a caixa marcada, <strong>uma credencial que já votou não é apagada</strong>
    (aparece na lista de recusadas).</p>
    <form method="post" action="/admin/remover-credencial"
      onsubmit="return confirm('Apagar as credenciais dos tokens colados?');">
      <textarea name="tokens" rows="5" style="width:100%" placeholder="B3PLmdWNz27g&#10;7tAZsbP9jtp5"></textarea>
      <label style="display:block;margin:.6em 0">
        <input type="checkbox" name="anular_voto" value="1">
        <strong>Anular também o voto já registrado</strong> por essas credenciais.
        Use SÓ para desfazer credencial defeituosa que agrupou famílias
        distintas — registre em ata e avise as famílias para votarem de novo
        com o link novo. O voto anulado não volta.
      </label>
      <button type="submit">Remover credenciais</button>
    </form>

    <h2>Ocorrências técnicas</h2>
    <form method="post" action="/admin/ocorrencia">
      <input type="text" name="description" placeholder="Descreva a ocorrência" style="width:70%" required>
      <button type="submit">Registrar</button>
    </form>
    <ul>
      ${incidents.map((i) => `<li>${new Date(i.created_at).toLocaleString('pt-BR')} — ${escapeHtml(i.description)}</li>`).join('') || '<li>Nenhuma ocorrência registrada.</li>'}
    </ul>

    <h2>Zona de teste</h2>
    <p class="warn">Isso apaga TODOS os eleitores, votos e ocorrências. Use apenas
    para limpar dados de teste antes de importar a lista real de eleitores.
    Faça isso <strong>antes</strong> de distribuir as credenciais oficiais.</p>
    <form method="post" action="/admin/zerar" onsubmit="return confirm('Tem certeza? Isso apaga tudo.');">
      <button type="submit">Zerar dados de teste</button>
    </form>
  `));
}));

app.get('/admin/buscar', requireAdmin, ah(async (req, res) => {
  const q = (req.query.q || '').trim();
  const host = req.protocol + '://' + req.get('host');
  const results = q.length >= 2 ? await db.searchVotersByName(q) : [];
  const rows = results.map((v) => `
    <tr>
      <td><strong>${escapeHtml(v.display_name)}</strong><br><span class="muted">${escapeHtml(SEGMENT_LABELS[v.segment])}</span></td>
      <td>${v.has_voted
        ? `<span class="warn" style="display:inline-block">Já votou em ${new Date(v.voted_at).toLocaleString('pt-BR')}</span>`
        : `<a href="${host}/votar/${escapeHtml(v.token)}" target="_blank" rel="noopener"><button type="button">Abrir cédula</button></a>`
      }</td>
    </tr>
  `).join('');
  res.send(page('Buscar eleitor', `
    <h1>Buscar eleitor — urna física / atendimento presencial</h1>
    <p>Use esta tela na recepção da EMIA: digite o nome de quem vai votar
    presencialmente, clique em <strong>Abrir cédula</strong> (abre em nova aba)
    e entregue o computador/tablet para a pessoa votar sozinha. Feche a aba
    depois, antes de atender a próxima pessoa.</p>
    <form method="get" action="/admin/buscar">
      <input type="text" name="q" placeholder="Digite pelo menos 2 letras do nome" value="${escapeHtml(q)}" autofocus>
      <button type="submit">Buscar</button>
    </form>
    ${q.length >= 2 ? `
      <table><thead><tr><th>Eleitor(a)</th><th>Ação</th></tr></thead><tbody>
        ${rows || '<tr><td colspan="2">Nenhum eleitor encontrado com esse nome.</td></tr>'}
      </tbody></table>
    ` : ''}
    <p><a href="/admin/painel">Voltar ao painel</a></p>
  `));
}));

app.post('/admin/abrir', requireAdmin, ah(async (req, res) => {
  await db.setSetting('opened_at', String(Date.now()));
  res.redirect('/admin/painel');
}));

app.post('/admin/encerrar', requireAdmin, ah(async (req, res) => {
  await db.setSetting('closed_at', String(Date.now()));
  res.redirect('/admin/painel');
}));

app.post('/admin/publicar', requireAdmin, ah(async (req, res) => {
  await db.setSetting('published', '1');
  res.redirect('/admin/painel');
}));

app.post('/admin/remover-credencial', requireAdmin, ah(async (req, res) => {
  const tokens = String(req.body.tokens || '')
    .split(/\r?\n/).map((t) => t.trim()).filter(Boolean);
  const anular = req.body.anular_voto === '1';
  const removidas = [];
  const removidasComAnulacao = [];
  const jaVotaram = [];
  const naoAchadas = [];
  for (const t of tokens) {
    if (anular) {
      const r = await db.removeVoterAndAnnulVote(t);
      if (!r.ok) { naoAchadas.push(t); continue; }
      if (r.hadVoted) {
        removidasComAnulacao.push(
          `${t} — ${r.display_name}` + (r.voteAnnulled ? ' (voto anulado)' : ' (SEM voto correspondente para anular — conferir)'));
      } else {
        removidas.push(`${t} — ${r.display_name}`);
      }
    } else {
      const r = await db.deleteVoterByToken(t);
      if (r.ok) removidas.push(`${t} — ${r.display_name}`);
      else if (r.reason === 'has_voted') jaVotaram.push(`${t} — ${r.display_name}`);
      else naoAchadas.push(t);
    }
  }
  const bloco = (titulo, arr) => (arr.length
    ? `<p class="warn">${titulo}:</p><ul>${arr.map((x) => `<li>${escapeHtml(x)}</li>`).join('')}</ul>`
    : '');
  res.send(page('Remoção de credenciais', `
    <h1>Remoção de credenciais</h1>
    <p>${removidas.length + removidasComAnulacao.length} credencial(is) removida(s)${anular ? `, ${removidasComAnulacao.length} com anulação de voto` : ''}.</p>
    ${bloco('Removidas (não tinham voto)', removidas)}
    ${bloco('Removidas COM voto anulado', removidasComAnulacao)}
    ${bloco('Mantidas porque já votaram (marque "anular o voto" para removê-las)', jaVotaram)}
    ${bloco('Tokens não encontrados', naoAchadas)}
    <p><a href="/admin/painel">Voltar ao painel</a></p>
  `));
}));

app.post('/admin/importar', requireAdmin, ah(async (req, res) => {
  const { rows, errors } = parseImport(req.body.csv || '');
  const replaceSegment = req.body.replace_docente ? 'docente' : null;

  if (replaceSegment && rows.length === 0) {
    return res.status(400).send(page('Importação não feita', `
      <h1>Nada foi alterado</h1>
      <p class="warn">Você marcou "substituir os docentes" mas não colou nenhuma
      linha. Cole a lista corrigida de docentes e envie de novo.</p>
      <p><a href="/admin/painel">Voltar ao painel</a></p>
    `));
  }

  let imported = [];
  let removed = 0;
  if (rows.length || replaceSegment) {
    const r = await db.importVoters(rows, { replaceSegment });
    imported = r.results;
    removed = r.removed;
  }
  const totalKeys = imported.reduce((s, r) => s + (r.keysIndexed || 0), 0);
  res.send(page('Importação concluída', `
    <h1>Importação concluída</h1>
    ${removed ? `<p class="warn">${removed} docente(s) que já estavam cadastrados foram removidos antes de importar. As famílias não foram tocadas.</p>` : ''}
    <p>${imported.length} eleitor(es) importado(s). ${totalKeys} chave(s) de acesso indexada(s).</p>
    ${errors.length ? `<p class="warn">${errors.length} linha(s) com problema:</p><ul>${errors.map((e) => `<li>${escapeHtml(e)}</li>`).join('')}</ul>` : ''}
    <p><a href="/admin/painel">Voltar ao painel</a> —
    <a href="/admin/credenciais.csv">Baixar credenciais</a></p>
  `));
}));

app.post('/admin/vincular-chaves', requireAdmin, ah(async (req, res) => {
  // Uma linha por credencial ja existente:  TOKEN <TAB> chave;chave;chave
  const lines = String(req.body.pares || '').split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  const pairs = [];
  const errors = [];
  for (const line of lines) {
    const cut = line.indexOf('\t') >= 0 ? line.indexOf('\t') : line.indexOf(',');
    const token = (cut >= 0 ? line.slice(0, cut) : line).trim();
    const keysRaw = cut >= 0 ? line.slice(cut + 1) : '';
    if (!token) { errors.push(`Linha sem token: ${line}`); continue; }
    const keys = keysRaw.split(';').map((k) => k.trim()).filter(Boolean);
    pairs.push({ token, keys });
  }
  const out = pairs.length ? await db.attachKeysByToken(pairs) : { linked: 0, keysIndexed: 0, missing: [] };
  res.send(page('Chaves vinculadas', `
    <h1>Chaves vinculadas</h1>
    <p>${out.linked} credencial(is) atualizada(s), ${out.keysIndexed} chave(s) nova(s) indexada(s).</p>
    ${out.missing.length ? `<p class="warn">${out.missing.length} token(s) não encontrado(s):</p><ul>${out.missing.map((t) => `<li>${escapeHtml(t)}</li>`).join('')}</ul>` : ''}
    ${errors.length ? `<p class="warn">${errors.length} linha(s) com problema:</p><ul>${errors.map((e) => `<li>${escapeHtml(e)}</li>`).join('')}</ul>` : ''}
    <p><a href="/admin/painel">Voltar ao painel</a></p>
  `));
}));

app.get('/admin/credenciais.csv', requireAdmin, ah(async (req, res) => {
  const voters = await db.listVoters();
  const host = req.protocol + '://' + req.get('host');
  const lines = ['nome,segmento,contato,link,ja_votou,criado_em'];
  for (const v of voters) {
    lines.push([
      csvEscape(v.display_name),
      v.segment,
      csvEscape(v.contact || ''),
      `${host}/votar/${v.token}`,
      v.has_voted ? 'sim' : 'nao',
      v.created_at ? new Date(v.created_at).toISOString() : '',
    ].join(','));
  }
  res.setHeader('Content-Type', 'text/csv; charset=utf-8');
  res.setHeader('Content-Disposition', 'attachment; filename="credenciais-emia.csv"');
  res.send(lines.join('\n'));
}));

function csvEscape(s) {
  const str = String(s ?? '');
  return /[",\n]/.test(str) ? `"${str.replace(/"/g, '""')}"` : str;
}

app.get('/admin/apuracao', requireAdmin, ah(async (req, res) => {
  res.send(page('Apuração', await renderResultsHtml()));
}));

app.get('/admin/relatorio.txt', requireAdmin, ah(async (req, res) => {
  const { aptos, votantes, resultados } = await db.stats();
  const settings = await db.getSettings();
  const incidents = await db.listIncidents();
  const aptosMap = Object.fromEntries(aptos.map((r) => [r.segment, r.total]));
  const votantesMap = Object.fromEntries(votantes.map((r) => [r.segment, r.total]));

  let out = 'RELATORIO FINAL - ELEICAO CONSELHO EMIA 2026-2028\n';
  out += `Gerado em: ${new Date().toLocaleString('pt-BR')}\n`;
  out += `Abertura da votacao: ${settings.opened_at ? new Date(Number(settings.opened_at)).toLocaleString('pt-BR') : 'nao registrada'}\n`;
  out += `Encerramento da votacao: ${settings.closed_at ? new Date(Number(settings.closed_at)).toLocaleString('pt-BR') : 'nao registrado'}\n\n`;

  for (const segment of ['docente', 'familia']) {
    const total_aptos = aptosMap[segment] || 0;
    const total_votantes = votantesMap[segment] || 0;
    const rows = resultados.filter((r) => r.segment === segment);
    const brancos = rows.find((r) => r.candidate_id === null)?.total || 0;
    out += `== ${SEGMENT_LABELS[segment].toUpperCase()} ==\n`;
    out += `Eleitores aptos: ${total_aptos}\n`;
    out += `Votantes: ${total_votantes}\n`;
    out += `Votos validos: ${total_votantes - brancos}\n`;
    out += `Votos em branco: ${brancos}\n`;
    out += `Votos nulos: nao se aplica (votacao por selecao, sem preenchimento livre)\n`;
    const porCandidata = candidatesFor(segment).map((c) => ({
      ...c, total: rows.find((r) => r.candidate_id === c.id)?.total || 0,
    })).sort((a, b) => b.total - a.total);
    porCandidata.forEach((c, i) => {
      out += `  ${c.name}: ${c.total} voto(s) ${i === 0 ? '(titular)' : i === 1 ? '(suplente)' : ''}\n`;
    });
    out += '\n';
  }

  out += '== OCORRENCIAS TECNICAS ==\n';
  out += incidents.length
    ? incidents.map((i) => `${new Date(i.created_at).toLocaleString('pt-BR')} - ${i.description}`).join('\n')
    : 'Nenhuma ocorrencia registrada.';
  out += '\n';

  res.setHeader('Content-Type', 'text/plain; charset=utf-8');
  res.setHeader('Content-Disposition', 'attachment; filename="relatorio-final-emia.txt"');
  res.send(out);
}));

app.post('/admin/ocorrencia', requireAdmin, ah(async (req, res) => {
  if (req.body.description) await db.addIncident(req.body.description);
  res.redirect('/admin/painel');
}));

app.post('/admin/zerar', requireAdmin, ah(async (req, res) => {
  await db.resetTestData();
  res.redirect('/admin/painel');
}));

app.post('/admin/portal-toggle', requireAdmin, ah(async (req, res) => {
  const s = await db.getSettings();
  await db.setSetting('portal_off', s.portal_off === '1' ? '0' : '1');
  res.redirect('/admin/painel');
}));

// Middleware de erro: qualquer excecao async cai aqui em vez de derrubar o
// processo ou travar a requisicao. Isso importa numa eleicao ao vivo — um
// erro transitorio de banco nao pode tirar o site do ar pra todo mundo.
app.use((err, req, res, next) => {
  console.error('Erro na requisicao:', err);
  if (res.headersSent) return next(err);
  res.status(500).send(page('Erro', `
    <h1>Erro temporário</h1>
    <p>Algo deu errado ao processar sua solicitação. Tente novamente em
    alguns instantes. Se o problema continuar, avise a Comissão Eleitoral.</p>
  `));
});

// ---------- Start ----------

db.initSchema()
  .then(() => {
    app.listen(PORT, () => {
      console.log(`Urna EMIA rodando na porta ${PORT}`);
    });
  })
  .catch((err) => {
    console.error('Falha ao iniciar (schema do banco):', err);
    process.exit(1);
  });
