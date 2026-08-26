// Lista final de candidatas, extraida de
// "Resultado_candidaturas_Conselho_EMIA_assinado.pdf" (assinado 19/08/2026).
// A fase de recursos (20-24/08/2026) ja passou; esta lista e definitiva.

const REAL_CANDIDATES = {
  docente: [
    { id: 'doc-1', name: 'Ligia Rosa dos Santos', unit: 'EMIA Jabaquara' },
    { id: 'doc-2', name: 'Carmem Soares', unit: 'EMIA Parelheiros' },
    { id: 'doc-3', name: 'Luciana de Lima Gabriel', unit: 'EMIA Jabaquara' },
    { id: 'doc-4', name: 'Maristely Souza da Silva', unit: 'EMIA Chácara do Jockey' },
    { id: 'doc-5', name: 'Juliana Rodrigues dos Santos', unit: 'EMIA Chácara do Jockey' },
  ],
  familia: [
    { id: 'fam-1', name: 'Marcia Cristina Nunes', unit: 'EMIA Jabaquara' },
    { id: 'fam-2', name: 'Marina Dantas Oliveira Bortotti', unit: 'EMIA Chácara das Flores' },
  ],
};

// Candidatos ficticios para teste com pessoas reais antes da eleicao oficial.
// Ativado apenas com a env var USE_TEST_CANDIDATES=true no Render - nunca
// editar REAL_CANDIDATES para isso, pra nao arriscar esquecer de reverter.
const TEST_CANDIDATES = {
  docente: [
    { id: 'doc-1', name: 'Dó Sustenido Ferreira', unit: 'EMIA Vila Sônica (teste)' },
    { id: 'doc-2', name: 'Arlequina Mascarada Reis', unit: 'EMIA Palco Real (teste)' },
    { id: 'doc-3', name: 'Piruetta Saraiva Gomes', unit: 'EMIA Passo Firme (teste)' },
    { id: 'doc-4', name: 'Aquarela Pontilhista Nunes', unit: 'EMIA Tela Viva (teste)' },
    { id: 'doc-5', name: 'Bemol Contraponto Alves', unit: 'EMIA Vila Sônica (teste)' },
  ],
  familia: [
    { id: 'fam-1', name: 'Cenográfico Bambolê Costa', unit: 'EMIA Palco Real (teste)' },
    { id: 'fam-2', name: 'Giro e Meio Andrade', unit: 'EMIA Passo Firme (teste)' },
  ],
};

const CANDIDATES = process.env.USE_TEST_CANDIDATES === 'true' ? TEST_CANDIDATES : REAL_CANDIDATES;

const SEGMENT_LABELS = {
  docente: 'Corpo Docente',
  familia: 'Famílias',
};

function candidatesFor(segment) {
  return CANDIDATES[segment] || [];
}

function candidateById(segment, id) {
  return candidatesFor(segment).find((c) => c.id === id) || null;
}

function isValidSegment(segment) {
  return segment === 'docente' || segment === 'familia';
}

module.exports = { CANDIDATES, SEGMENT_LABELS, candidatesFor, candidateById, isValidSegment };
