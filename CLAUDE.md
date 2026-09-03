# Handoff — Urna EMIA (Eleição Conselho 2026-2028)

Leia este arquivo inteiro antes de mexer em qualquer coisa. Ele existe pra
uma sessão nova do Claude Code (rodando neste notebook, ou em qualquer outra
máquina) já saber exatamente onde isso parou.

## O que é isto

Sistema de votação online (urna eletrônica) pra eleição do Conselho da EMIA
(Escola Municipal de Iniciação Artística), biênio 2026-2028. Thiago é membro
da Comissão Eleitoral, autorizado a fazer a auditoria do processo.

Votação oficial: **31/08/2026 a 08/09/2026 (terça), até 12h** — prazo
prorrogado pela Comissão em 02/09/2026 (era 05/09). O texto do prazo
mostrado ao eleitor mora em `JANELA`, no topo do `server.js`; a votação só
encerra de fato quando a Comissão clica em "Encerrar votação agora".

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

Atualizado em **01/09/2026**. Links em `LINKS.md`.

> **02-03/09/2026 — LEIA `HANDOFF-JABAQUARA-CORRECAO.md` PRIMEIRO.** A votação
> foi aberta e prorrogada até 08/09 12h. A importação da Jabaquara foi feita
> com uma versão do `jabaquara.py` que juntava famílias diferentes por
> telefone/e-mail compartilhado; a força-tarefa de corrigir isso na produção
> (via `jaba_fix.py` — plano único: `FIX_remover.txt` /
> `FIX_remover_ANULANDO.txt` / `FIX_importar_tudo.tsv` — + a seção "Remover
> credencial" no `/admin`, agora com opção de anular o voto) está em
> andamento. Roteiro clicável para o Thiago em
> `_CORRECAO-JABAQUARA/PASSO-A-PASSO.html`; comunicados/ofício também nessa
> pasta. O resto desta seção está desatualizado (votação já abriu, docentes e
> todas as EMIAs já importados).

- **Deploy JÁ FEITO.** Site no ar em https://emia-urna.onrender.com , repo
  `github.com/thiagobrisolla4-max/emia-urna`, deploy automático no push da
  branch `main`. (O texto antigo dizia "falta deploy" — estava desatualizado.)
- **Votação ainda FECHADA** (`opened_at` não setado). Nenhum link `/votar`
  funciona pra votar até a Comissão clicar em "Abrir votação agora".
- **359 credenciais de família já importadas** no banco de produção
  (Perus 121, Parelheiros 93, Brasilândia 74, Flores 71). Os links **ainda
  não foram enviados** a ninguém (confirmado por Thiago em 01/09).
- **0 docentes importados** ainda.
- Código: `server.js`, `db.js`, `candidates.js`, `keys.js`, `public/style.css`.
  As bios das candidatas já estão em `candidates.js` e já têm botão que revela
  (`<details class="bio">` em `server.js`, estilo em `style.css`). O
  `fichas_eleiçao_conselho.pdf` é escaneado (sem texto) — não dá pra extrair
  bio de lá.

### Novidades desta sessão (01/09) — ainda NÃO deployadas / importadas

1. **Portal da Família (`/acesso`)** — página pública onde a pessoa digita
   um telefone, e-mail OU o nome completo de um(a) estudante da família e é
   levada à cédula da família. Um voto por família: irmãos e vários
   responsáveis (mãe/pai/avó) caem todos na MESMA credencial.
2. **Tabela nova `voter_keys`** (em `db.js`, criada sozinha no boot via
   `initSchema`) — indexa as "chaves de acesso". **Nunca referencia `votes`**;
   o sigilo continua estrutural. Normalização de chave mora em `keys.js`
   (fonte única da verdade, usada na importação e na busca). Ver comentário
   no topo de `keys.js`.
3. **Painel admin** ganhou: importação em formato TSV com chaves, caixa
   "Vincular chaves a credenciais já existentes", toggle liga/desliga do
   portal, e contadores de chaves indexadas.
4. **`instalador.py`** — instalador serial. Lê `DADOS Educadores EMIA.xlsx`
   (90 docentes), `LISTA CONTATOS - Chácara do Jóquei.xlsx` (571 linhas →
   504 famílias), + as listas de Flores/Perus/Brasilândia/Parelheiros, limpa
   encoding/lixo, agrupa famílias, casa com as 359 credenciais já existentes
   pra não duplicar, e gera em `./saida_instalador/` os arquivos prontos pra
   colar no painel (`A_*` = vincular chaves nos 359 tokens; `B_*` = importar
   90 docentes + 504 famílias novas). Ver `saida_instalador/RESUMO.txt`.

### O que falta (ordem)

1. `git push` da versão nova (cria `voter_keys` + `/acesso` no Render).
2. `python instalador.py` e conferir `saida_instalador/RESUMO.txt` +
   `C_conferencia_familias.csv` + `G_conflito_credencial_dupla.csv`.
3. No `/admin`: colar `B_novos_eleitores.tsv` em "Importar eleitores" e
   `A_chaves_para_tokens_existentes.tsv` em "Vincular chaves". **Não**
   clicar em "Zerar dados" (perde os 359).
4. Testar `/acesso` com telefones/nomes reais. Rodar o teste oficial do
   Edital, registrar em ata.
5. Falta chegar a **lista de famílias da EMIA Jabaquara** — Thiago aceita
   abrir a votação sem ela e adicionar depois (rodar o instalador de novo
   com o arquivo novo; famílias já importadas não duplicam).
6. Só então "Abrir votação agora".

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
  apertado. **Complemento (01/09):** com o Portal da Família (`/acesso`),
  a Comissão pode mandar só UM link genérico (`/acesso`) pras famílias, em
  vez de um link individual por família — a pessoa se identifica lá. O CSV
  individual continua existindo como plano B.
- **`voter_keys` liga contato → credencial, nunca → voto.** É o mesmo nível
  de exposição do CSV de credenciais que a Comissão já distribuiria na mão.
  Não "enfraquece" o sigilo — quem tem acesso ao banco já via
  `voters.display_name`. O que continua impossível é ligar credencial a voto.

## Onde isto vive

Este projeto está dentro de `SYNC\_PY\10_PROJETOS_ATIVOS\`, uma pasta
Syncthing ativa que sincroniza automaticamente entre o PC Torre e este
notebook (`node_modules` fica de fora do sync via `.stignore` na raiz de
`_PY` — depois de puxar mudanças aqui, rode `npm install` se ainda não tiver
rodado). Veja `SYNC\_PY\CLAUDE.md` pra contexto dos outros projetos vizinhos
nessa mesma pasta.

## Primeira coisa a fazer nesta sessão

Pergunte a Thiago em que ponto ele está (já fez `git push` da versão com
`/acesso`? já rodou o `instalador.py`? já colou os arquivos `A_`/`B_` no
painel? a votação já abriu? a lista da Jabaquara chegou?) antes de assumir
qualquer coisa. Confira o estado real: `curl https://emia-urna.onrender.com`
e o `git log`. O `saida_instalador/RESUMO.txt` (se existir localmente) tem o
passo a passo detalhado.
