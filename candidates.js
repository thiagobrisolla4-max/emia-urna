// Lista final de candidatas, extraida de
// "Resultado_candidaturas_Conselho_EMIA_assinado.pdf" (assinado 19/08/2026).
// A fase de recursos (20-24/08/2026) ja passou; esta lista e definitiva.

const REAL_CANDIDATES = {
  docente: [
    {
      id: 'doc-1', name: 'Ligia Rosa dos Santos', unit: 'EMIA Jabaquara',
      bio: 'Pianista, cantora, artista, educadora musical, regente de corais infantis e de grupos vocais de mulheres, professora de piano e canto para crianças e adultos. Formadora de crianças e adultos na arte de tocar piano e do cantar há 47 anos. Formada em Licenciatura pela FAAM, fez especialização no Sistema Orff (Áustria-Salzburg), Kodaly (Hungria), Sistema Willems (Brasil), D’Alcroze (Brasil). Durante sua trajetória em educação foi pesquisadora da cultura da música e dança da Diáspora Africana das regiões do sudeste do Brasil, tais como jongo, congadas de São Paulo e de Minas Gerais, ciranda de Paraty, batuques, e do nordeste do Brasil, especificamente de Pernambuco, como coco, cirandas e maracatu. Atualmente leciona na EMIA como Artista Educadora, como professora de piano e Regente de coral Infantil, e já trabalhou no curso regular com os quartetos e duplas. Presidente da Associação Baobá de Canto Coral, que desenvolve projetos culturais para a comunidade negra da região Leste da cidade (Penha-Vila Matilde). Participa do Bloco Ilu Obá de Min, como percussionista, bloco composto por 400 mulheres negras que abre o Carnaval de São Paulo. Como cantora, atualmente participa do Coral Vozes Paulistanas, com o projeto Carmina Burana e a Nona Sinfonia de Beethoven.',
    },
    {
      id: 'doc-2', name: 'Carmem Soares', unit: 'EMIA Parelheiros',
      bio: 'Carmen Pinheiro da Silva é mestra em Arte Educação pela Unesp e possui bacharelado e licenciatura em Artes Cênicas pela Faculdade Paulista de Teatro. É atriz, diretora e professora de Teatro. Mora em Parelheiros e atua como professora na Associação Comunitária Pequeno Príncipe e na EMIA Parelheiros.',
    },
    {
      id: 'doc-3', name: 'Luciana de Lima Gabriel', unit: 'EMIA Jabaquara',
      bio: 'Atriz, artista educadora, produtora cultural e pesquisadora teatral. É mestre em Artes pela USP, bacharel em Artes Cênicas pela Unicamp e licenciada em Artes pela Faculdade IBRA. Atualmente se especializa em Neurociência na Educação pelo Instituto Singularidades. Integra o corpo docente da EMIA Jabaquara desde 2017. Desde 2021, integra o núcleo artístico da Cia. Madeirite Rosa, atuando e produzindo nos espetáculos da companhia.',
    },
    {
      id: 'doc-4', name: 'Maristely Souza da Silva', unit: 'EMIA Chácara do Jockey',
      bio: 'Arte-educadora com atuação desde 2016 em espaços culturais, organizações sociais e instituições de ensino. Formada em Produção Cultural e Artes Visuais, desenvolve e conduz oficinas e experiências artísticas para crianças, adolescentes, adultos e idosos.',
    },
    {
      id: 'doc-5', name: 'Juliana Rodrigues dos Santos', unit: 'EMIA Chácara do Jockey',
      bio: 'Percussionista e arte-educadora formada pela EMESP Tom Jobim, conhecida artisticamente como AfroJu Rodrigues, atua na pesquisa, criação e educação musical a partir das rítmicas africanas em diáspora. Integra a Funmilayo Afrobeat Orquestra e o podcast Calunguinha – O Cantador de Histórias. Participou de apresentações no Rock in Rio, Lollapalooza e projeto Tiny Desk, além de gravações para os álbuns Terreiro Urbano, Bitita – As Composições de Carolina Maria de Jesus, Canteiro de Raiz e o EP Ponta a Ponta. Foi percussionista da trilha sonora de Missing the Amazon, do The Guardian. Atualmente atua como educadora na EMIA.',
    },
  ],
  familia: [
    { id: 'fam-1', name: 'Marcia Cristina Nunes', unit: 'EMIA Jabaquara', bio: '' },
    { id: 'fam-2', name: 'Marina Dantas Oliveira Bortotti', unit: 'EMIA Chácara das Flores', bio: '' },
  ],
};

// Candidatos ficticios para teste com pessoas reais antes da eleicao oficial.
// Ativado apenas com a env var USE_TEST_CANDIDATES=true no Render - nunca
// editar REAL_CANDIDATES para isso, pra nao arriscar esquecer de reverter.
const TEST_CANDIDATES = {
  docente: [
    { id: 'doc-1', name: 'Dó Sustenido Ferreira', unit: 'EMIA Vila Sônica (teste)', bio: 'Candidato fictício para teste do sistema. Linguagem artística: Música.' },
    { id: 'doc-2', name: 'Arlequina Mascarada Reis', unit: 'EMIA Palco Real (teste)', bio: 'Candidata fictícia para teste do sistema. Linguagem artística: Teatro.' },
    { id: 'doc-3', name: 'Piruetta Saraiva Gomes', unit: 'EMIA Passo Firme (teste)', bio: 'Candidata fictícia para teste do sistema. Linguagem artística: Dança.' },
    { id: 'doc-4', name: 'Aquarela Pontilhista Nunes', unit: 'EMIA Tela Viva (teste)', bio: 'Candidata fictícia para teste do sistema. Linguagem artística: Artes Visuais.' },
    { id: 'doc-5', name: 'Bemol Contraponto Alves', unit: 'EMIA Vila Sônica (teste)', bio: 'Candidato fictício para teste do sistema. Linguagem artística: Música.' },
  ],
  familia: [
    { id: 'fam-1', name: 'Cenográfico Bambolê Costa', unit: 'EMIA Palco Real (teste)', bio: 'Candidato fictício para teste do sistema. Linguagem artística: Teatro.' },
    { id: 'fam-2', name: 'Giro e Meio Andrade', unit: 'EMIA Passo Firme (teste)', bio: 'Candidata fictícia para teste do sistema. Linguagem artística: Dança.' },
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
