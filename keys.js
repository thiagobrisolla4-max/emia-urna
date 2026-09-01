// Normalizacao de "chaves de acesso" da familia/eleitor.
//
// Uma chave e qualquer coisa que uma pessoa pode digitar no Portal da Familia
// (/acesso) para chegar a credencial da sua familia: um telefone, um e-mail,
// o nome completo de um(a) estudante da familia, ou o nome de um responsavel.
//
// IMPORTANTE PARA O SIGILO: uma chave liga um CONTATO a uma CREDENCIAL
// (voters.token). Nunca liga a um voto — a tabela votes nao tem token nem
// referencia a voters. O sigilo do voto continua estrutural, igual ao resto
// do sistema. A tabela voter_keys tem exatamente o mesmo nivel de exposicao
// que o CSV de credenciais que a Comissao ja distribui manualmente.
//
// O instalador (instalador.py) NAO normaliza: ele so junta os valores crus
// (telefone com pontuacao, e-mail, nome). A normalizacao mora aqui, e este
// arquivo e a unica fonte da verdade — usado tanto na importacao quanto na
// busca do portal, pra garantir que "o que foi indexado" e "o que foi
// buscado" passem exatamente pela mesma regra.

function stripDiacritics(s) {
  return s.normalize('NFD').replace(/[̀-ͯ]/g, '');
}

// Palavras que sozinhas nao identificam ninguem — se o nome digitado so tiver
// isso, nao vale como chave (evita que "de souza" case com meio mundo).
const NAME_STOPWORDS = new Set([
  'de', 'da', 'do', 'das', 'dos', 'e', 'di', 'du', 'del', 'la', 'e_',
  'familia', 'fam', 'mae', 'pai', 'avo', 'avoo', 'avó', 'tia', 'tio', 'resp',
  'responsavel', 'crianca', 'aluno', 'aluna', 'estudante',
  // lixo comum em celula de e-mail/telefone que sobra sem "@"
  'nao', 'tem', 'naotem', 'sem', 'nenhum', 'nenhuma', 'null', 'none', 'na',
  'sim', 'x', 'xx', 'xxx', 'tel', 'email', 'celular', 'whatsapp', 'zap',
]);

// Recebe um valor cru e devolve { kind, key } normalizado, ou null se o valor
// nao serve como chave (curto demais, generico demais, etc.).
function normalizeKey(raw) {
  let s = String(raw == null ? '' : raw).trim();
  if (!s) return null;

  // --- e-mail ---
  if (s.includes('@')) {
    s = stripDiacritics(s).toLowerCase().replace(/\s+/g, '');
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(s)) return null;
    if (/^(nao|n)tem|sememail|^-+$/.test(s)) return null;
    return { kind: 'email', key: 'e:' + s };
  }

  // --- telefone (se tem digitos suficientes e pouca letra) ---
  const digitCount = (s.match(/\d/g) || []).length;
  const letterCount = (s.match(/[a-zA-ZÀ-ſ]/g) || []).length;
  if (digitCount >= 8 && digitCount >= letterCount) {
    let p = s.replace(/\D/g, '');
    if (p.length > 11 && p.startsWith('55')) p = p.slice(2); // tira DDI Brasil
    // Artefato comum do Excel: um "0" a mais no fim de um celular de 11 digitos.
    if (p.length === 12 && p.endsWith('0')) p = p.slice(0, 11);
    if (p.length > 11) p = p.slice(-11); // pega os ultimos 11
    if (p.length < 10) return null;
    return { kind: 'phone', key: 't:' + p };
  }

  // --- nome (de estudante ou responsavel) ---
  s = stripDiacritics(s).toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
  const toks = s.split(' ').filter((t) => t.length >= 2 && !NAME_STOPWORDS.has(t));
  if (toks.length < 2) return null; // exige nome + sobrenome, no minimo
  return { kind: 'name', key: 'n:' + toks.join(' ') };
}

// Variantes de uma chave usadas SO na busca do portal — assim uma pessoa que
// digita o celular sem o 9o digito (ou com ele) ainda encontra a credencial.
function lookupVariants(raw) {
  const base = normalizeKey(raw);
  if (!base) return [];
  const out = new Set([base.key]);
  if (base.kind === 'phone') {
    const p = base.key.slice(2);
    if (p.length === 11 && p[2] === '9') out.add('t:' + p.slice(0, 2) + p.slice(3)); // tira o 9
    if (p.length === 10) out.add('t:' + p.slice(0, 2) + '9' + p.slice(2)); // poe o 9
  }
  return [...out];
}

// Todas as chaves normalizadas a indexar para UM valor cru na importacao.
// (Para telefone, indexa com e sem o 9o digito, pra casar os dois formatos.)
function indexKeys(raw) {
  const base = normalizeKey(raw);
  if (!base) return [];
  return lookupVariants(raw);
}

module.exports = { normalizeKey, lookupVariants, indexKeys, stripDiacritics };
