# Handoff — Urna EMIA (Eleição Conselho 2026-2028)

Leia este arquivo inteiro antes de mexer em qualquer coisa. Ele existe pra
uma sessão nova do Claude Code (rodando neste notebook, ou em qualquer outra
máquina) já saber exatamente onde isso parou.

## O que é isto

Sistema de votação online (urna eletrônica) pra eleição do Conselho da EMIA
(Escola Municipal de Iniciação Artística), biênio 2026-2028. Thiago é membro
da Comissão Eleitoral, autorizado a fazer a auditoria do processo.

Votação oficial: **31/08/2026 a 05/09/2026, até 12h**.

## Por que existe

O pedido original de Thiago foi "um HTML que circula na mão de muita gente"
pra servir de urna. Isso foi recusado tecnicamente: sem servidor central,
não dá pra impedir voto duplicado nem apurar — e o próprio Edital da eleição
(item 3.4.1) exige uma lista fechada de requisitos (cadastro prévio,
credencial individual, um voto por credencial, sigilo, auditoria pela
Comissão) que um arquivo estático não cumpre. Este projeto é a solução real:
Node + Express + PostgreSQL, hospedado publicamente.

Os documentos oficiais que fundamentam as regras (edital, regimento interno,
lista de candidatos aprovados) estão em
`SYNC\SYNC_cel\administracao_profissional\` — vale reler se qualquer regra
parecer ambígua, em vez de assumir.

## Estado atual (verifique se isso ainda bate antes de confiar cegamente)

- Código completo e funcional: `server.js`, `db.js`, `candidates.js`,
  `public/style.css`.
- **Testado ponta a ponta** com Postgres em memória (`pg-mem`), incluindo o
  fluxo HTTP completo via `fetch` real contra o `server.js` de verdade —
  não é teste teórico. Nesse processo foi encontrado e corrigido um bug real
  (`isVotingOpenTx` em `db.js` não selecionava a coluna `key`, o que faria
  todo voto real ser rejeitado silenciosamente mesmo com a votação aberta).
  Os scripts de teste não fazem parte do repositório (rodaram numa pasta
  temporária de scratch) — se for mexer na lógica de novo, vale recriar um
  teste parecido antes de confiar em mudanças no fluxo de voto.
- **Ainda NÃO foi feito o deploy.** Falta:
  1. Criar repositório no GitHub (privado) e dar `git push` — o commit
     inicial já existe localmente (`git log` mostra 1 commit).
  2. Seguir o passo a passo da seção 1 do `README.md` pra criar o banco e o
     serviço web no Render.
  3. Rodar o teste oficial exigido pelo Edital (seção 2 do README) e
     registrar em ata.
  4. Só depois disso, importar a lista real de eleitores e abrir a votação.

Se este arquivo estiver desatualizado em relação a isso (por exemplo, se o
deploy já foi feito), confie no que você observar no código/no Render, não
neste texto.

## Decisões de design que não devem ser revertidas sem entender o motivo

- **Sem substituição de voto** ("último voto vale"). O Edital permite isso,
  mas exigiria ligar eleitor → seu voto mais recente, o que quebra a
  separação total entre identidade e conteúdo do voto — que é o mecanismo
  real de sigilo do sistema (a tabela `votes` não tem NENHUMA coluna que
  aponte pra `voters`, de propósito).
- **PostgreSQL, não SQLite.** Web Services no Render têm disco efêmero por
  padrão — SQLite em arquivo seria apagado a cada deploy/restart.
- **Distribuição de credencial é manual** (a Comissão baixa um CSV e manda
  os links por WhatsApp/e-mail), não automática por e-mail — decisão de
  Thiago pra não depender de um serviço de envio de terceiro sob prazo
  apertado.

## Onde isto vive

Este projeto está dentro de `SYNC\_PY\10_PROJETOS_ATIVOS\`, uma pasta
Syncthing ativa que sincroniza automaticamente entre o PC Torre e este
notebook (`node_modules` fica de fora do sync via `.stignore` na raiz de
`_PY` — depois de puxar mudanças aqui, rode `npm install` se ainda não tiver
rodado). Veja `SYNC\_PY\CLAUDE.md` pra contexto dos outros projetos vizinhos
nessa mesma pasta.

## Primeira coisa a fazer nesta sessão

Pergunte a Thiago em que ponto ele está (ainda vai fazer o deploy? já fez?
já importou eleitores? a votação já abriu?) antes de assumir qualquer coisa
— isso muda completamente o que faz sentido fazer a seguir. Se ele disser
só "continua", comece lendo `README.md` inteiro e perguntando qual dos
passos da seção 1-4 ele já completou.
