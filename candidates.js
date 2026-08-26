// Lista final de candidatas, extraida de
// "Resultado_candidaturas_Conselho_EMIA_assinado.pdf" (assinado 19/08/2026).
// A fase de recursos (20-24/08/2026) ja passou; esta lista e definitiva.

const CANDIDATES = {
  docente: [
    { id: 'doc-1', name: 'Ligia Rosa dos Santos', unit: '' },
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
