require('dotenv').config();
const express = require('express');
const session = require('express-session');
const path = require('path');
const crypto = require('crypto');
const db = require('./db');
const { candidatesFor, candidateById, isValidSegment, SEGMENT_LABELS } = require('./candidates');

const PORT = process.env.PORT || 3000;
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || '';

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

// ---------- Eleitor ----------

app.get('/', (req, res) => {
  res.send(page('Urna EMIA', `
    <h1>Urna Eletrônica — Conselho EMIA</h1>
    <p>Este é o sistema de votação da eleição do Conselho da Escola Municipal
    de Iniciação Artística (biênio 2026-2028).</p>
    <p>Para votar, use o link individual enviado pela Comissão Eleitoral
    (algo como <code>/votar/SEU-CODIGO</code>). Não existe uma página de
    votação genérica — cada credencial é pessoal e intransferível.</p>
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
    return res.send(page('Votação fechada', `
      <h1>Votação não está aberta</h1>
      <p>A votação ainda não começou ou já foi encerrada pela Comissão
      Eleitoral. Guarde este link para usar durante o período oficial de
      votação (31/08 a 05/09/2026, até 12h).</p>
    `));
  }
  const candidates = candidatesFor(voter.segment);
  const options = candidates.map((c) => `
    <label class="candidate">
      <input type="radio" name="candidate_id" value="${escapeHtml(c.id)}" required>
      <span><strong>${escapeHtml(c.name)}</strong>${c.unit ? ` — ${escapeHtml(c.unit)}` : ''}</span>
    </label>
    ${c.bio ? `<details class="bio"><summary>Ver currículo</summary><p>${escapeHtml(c.bio)}</p></details>` : ''}
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

  const statusVotacao = settings.closed_at
    ? `Encerrada em ${new Date(Number(settings.closed_at)).toLocaleString('pt-BR')}`
    : settings.opened_at
      ? `Aberta desde ${new Date(Number(settings.opened_at)).toLocaleString('pt-BR')}`
      : 'Não iniciada';

  res.send(page('Painel da Comissão', `
    <h1>Painel da Comissão Eleitoral</h1>
    <form method="post" action="/admin/logout" style="display:inline"><button>Sair</button></form>

    <h2>Status da votação</h2>
    <p>${escapeHtml(statusVotacao)}</p>
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
    <p>Cole uma lista, uma pessoa por linha, no formato:
    <code>nome,contato,segmento</code> (segmento = <code>docente</code> ou <code>familia</code>).</p>
    <form method="post" action="/admin/importar">
      <textarea name="csv" rows="8" style="width:100%" placeholder="Maria Silva,11999999999,docente
João Souza,joao@email.com,familia"></textarea>
      <button type="submit">Importar e gerar credenciais</button>
    </form>

    <h2>Lista de eleitores e credenciais</h2>
    <p><a href="/admin/credenciais.csv">Baixar lista completa (CSV) para distribuição</a> —
    <a href="/admin/buscar">Buscar eleitor por nome (urna física / atendimento presencial)</a></p>

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

app.post('/admin/importar', requireAdmin, ah(async (req, res) => {
  const raw = (req.body.csv || '').trim();
  const lines = raw.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  const rows = [];
  const errors = [];
  for (const line of lines) {
    const parts = line.split(',').map((p) => p.trim());
    if (parts.length < 3) { errors.push(`Linha ignorada (formato incorreto): ${line}`); continue; }
    const [name, contact, segmentRaw] = parts;
    const segNorm = segmentRaw.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
    let segment = null;
    if (segNorm.startsWith('doc')) segment = 'docente';
    else if (segNorm.startsWith('fam')) segment = 'familia';
    if (!segment) { errors.push(`Segmento inválido (linha ignorada): ${line}`); continue; }
    rows.push({ name, contact, segment });
  }
  const imported = rows.length ? await db.importVoters(rows) : [];
  res.send(page('Importação concluída', `
    <h1>Importação concluída</h1>
    <p>${imported.length} eleitor(es) importado(s).</p>
    ${errors.length ? `<p class="warn">${errors.length} linha(s) com problema:</p><ul>${errors.map((e) => `<li>${escapeHtml(e)}</li>`).join('')}</ul>` : ''}
    <p><a href="/admin/painel">Voltar ao painel</a> —
    <a href="/admin/credenciais.csv">Baixar credenciais</a></p>
  `));
}));

app.get('/admin/credenciais.csv', requireAdmin, ah(async (req, res) => {
  const voters = await db.listVoters();
  const host = req.protocol + '://' + req.get('host');
  const lines = ['nome,segmento,contato,link,ja_votou'];
  for (const v of voters) {
    lines.push([
      csvEscape(v.display_name),
      v.segment,
      csvEscape(v.contact || ''),
      `${host}/votar/${v.token}`,
      v.has_voted ? 'sim' : 'nao',
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
