# Handoff — Correção das credenciais da EMIA Jabaquara

**Escrito em 02/09/2026, fim do dia.** Para a próxima sessão do Claude Code
e para o Thiago retomarem amanhã. Leia isto inteiro antes de mexer.

Contexto geral do projeto: `CLAUDE.md`. Este arquivo cobre **só** a força-tarefa
de corrigir a importação da Jabaquara, que ficou pela metade hoje.

---

## 1. TL;DR — onde paramos

- A votação está **no ar** (`https://emia-urna.onrender.com`), prazo
  **prorrogado até 08/09/2026 (terça), 12h**. Só encerra quando a Comissão
  clicar em "Encerrar votação agora".
- As **754 credenciais corretas** da Jabaquara estão em
  `saida_instalador/JABAQUARA_bloco_01..13.tsv` (geradas pelo `jabaquara.py`).
- O Thiago **já colou os blocos ANTIGOS** (geração ~730, antes da correção de
  merge) no `/admin`. A produção tem hoje ≈ **725 credenciais da Jabaquara**,
  e dentro delas:
  - **24 "merges errados"** — 1 credencial reunindo 2+ famílias sem parentesco
    (juntadas por um telefone/e-mail compartilhado, erro da planilha da
    secretaria). Foi o que gerou o relato de uma família que via na cédula o
    nome de outra família desconhecida.
  - **~58 duplicatas** — famílias com 2 credenciais (bloco colado 2×).
  - **~60–87 famílias faltando** — pelo menos um bloco não foi colado.
  - **5 merges já votaram** e **1 caso de voto dobrado real** (ver §5).
- Ferramenta de correção pronta: **`jaba_fix.py`**. Ela lê o CSV da produção e
  gera os arquivos pra colar de volta. **Nada foi aplicado ainda** — o Thiago
  parou antes de colar.

---

## 2. A causa raiz (bug de verdade, corrigido no código)

`group_families()` (no `instalador.py`) usa union-find: une **duas linhas de
aluno que compartilhem QUALQUER telefone ou e-mail**. A planilha da Jabaquara
(`Contatos alunos EMIA Jabaquara.xlsx`, 874 alunos) só tem nome do aluno,
telefone e e-mail — sem coluna de responsável — e vários registros de
famílias diferentes trazem um contato em comum (número digitado errado, avó,
motorista, mesmo primeiro nome colado na linha errada). Resultado: famílias
sem parentesco caíam na mesma credencial = mesmo voto.

**Correção no código** (commit `36a226b`): `jabaquara.py` ganhou
`split_unrelated_families()` — depois do agrupamento, reagrupa as linhas de
cada família por **conexão de nome** (sobrenome de criança OU responsável
completo em comum). Linhas ligadas só por telefone/e-mail viram credenciais
separadas. Isso levou de 730 → **754 credenciais limpas**.
`JABAQUARA_desmembradas.csv` documenta os 24 desmembramentos.

---

## 3. O que já está deployado (todos os commits no `main`, Render OK)

| Commit | O quê |
|---|---|
| `a699016` | Prorrogação até 08/09; bloco `JANELA` no topo do `server.js`; avisos de prazo nas páginas |
| `1ea780d` | `/acesso` reescrito p/ famílias **E** docentes |
| `d51193d` | `jabaquara.py`: extrai nome de responsável do campo telefone |
| `36a226b` | `split_unrelated_families()` + **`db.deleteVoterByToken()`** + seção **"Remover credencial"** no `/admin` (cola tokens, em lote; recusa quem já votou; nunca toca em `votes`) |
| `4686a0e` / `7f6d9f3` | `jaba_fix.py` — plano de correção; só age em credencial **confirmada** como Jabaquara (contato bate com telefone/e-mail da lista), nunca por nome só |
| `5cb9fd9` | `/admin/credenciais.csv` agora tem coluna **`criado_em`** (ISO). `jaba_fix.py --desde AAAA-MM-DD` usa isso como sinal 100% confiável. Nova seção "FAMÍLIAS SEM CORRESPONDÊNCIA" + `FIX_faltando.tsv` |

---

## 4. PLANO PARA AMANHÃ (passo a passo)

### 4.1 Baixar o estado atual da produção

1. `/admin` → **"Baixar lista completa (CSV)"**. O navegador salva
   `credenciais-emia.csv` (provável pasta Downloads).
2. Copiar pra pasta do projeto com o nome que o script espera:
   ```powershell
   Copy-Item "$env:USERPROFILE\Downloads\credenciais-emia.csv" `
     "C:\Users\thiag\Desktop\emia-urna-RECUPERADO-2026-09-01\credenciais-producao.csv" -Force
   ```
3. Confirmar que veio completo (~1600+ linhas) e que tem a coluna
   `criado_em` preenchida (só terá se o deploy `5cb9fd9` já estava no ar
   quando as credenciais foram criadas — as da Jabaquara **já existiam antes**
   desse deploy, então `criado_em` estará preenchido de qualquer forma, é
   coluna do banco desde o início).

### 4.2 Rodar o `jaba_fix.py`

```
git pull
python jaba_fix.py --desde 2026-09-01
```
(`--desde 2026-09-01` = tudo que é família e foi criado de 01/09 em diante é
Jabaquara. Se der números estranhos, rodar sem a flag e comparar.)

Abrir `saida_instalador/FIX_relatorio.txt` e **conferir o cabeçalho**:
- `Dessas, identificadas como JABAQUARA` ≈ 725 ± . Se for ~950 → CSV errado
  (leu `credenciais-emia.csv` velho — ver §7).
- `RESULTADO: remover N, reimportar M, K faltando`.

### 4.3 Aplicar (só depois de conferir o relatório)

O `jaba_fix.py` agora gera **3 arquivos** (plano único, commits `17215a6` +
`0b7e8c5`):

1. `/admin` → **"Remover credencial"** → colar `FIX_remover.txt` →
   **NÃO marcar** a caixa → enviar. (Tokens sem voto.)
2. `/admin` → **"Remover credencial"** → colar `FIX_remover_ANULANDO.txt` →
   **MARCAR** "Anular também o voto já registrado" → enviar. (Merges/duplicatas
   que já votaram — o voto é anulado; a família revota com o link novo.)
3. `/admin` → **"Importar eleitores"** → colar `FIX_importar_tudo.tsv` →
   enviar. (Todas as credenciais limpas de uma vez: merges desfeitos +
   duplicatas + famílias que faltavam.)
4. Baixar o CSV de novo, `Copy-Item`, rodar `python jaba_fix.py --desde
   2026-09-01` outra vez. **Deve dar `Remover SEM voto 0 / Remover ANULANDO 0
   / importar 0`** — prova de que fechou.
5. **Ata:** registrar os votos anulados (lista "VOTOS QUE SERÃO ANULADOS" no
   relatório). **Avisar todas as famílias afetadas** (merge + duplicata) para
   (re)votar com o link novo até 08/09 12h.
6. Testar `/acesso` com nomes/telefones das famílias afetadas.

> Se "Remover credencial" com muitos tokens travar / der timeout, colar em
> blocos de ~150 tokens.
>
> `db.removeVoterAndAnnulVote()` acha o voto por `segment` + `cast_at ==
> voters.voted_at` (castVote grava os dois com o mesmo `now()`); fallback ±5s.

---

## 5. Pendências para a Comissão decidir em ata (NÃO automatizável)

`saida_instalador/FIX_votaram_resolver.txt` lista tudo com detalhe. Resumo:

- **5 merges que já votaram** — a credencial fundida registrou 1 voto e
  **não pode ser removida** (perderia o voto). Os nomes e as linhas prontas
  estão em `FIX_votaram_resolver.txt`. Para cada família do grupo que **não**
  foi quem votou, o arquivo traz a linha pronta pra importar à mão (token
  novo). Registrar ocorrência técnica no painel.
- **1 voto dobrado real** — uma família com **duas credenciais, as duas
  votaram** (aparece no `FIX_relatorio.txt` como "também votou — resolver na
  mão"). A Comissão precisa decidir em ata anular um dos votos (anotar o
  token do voto a desconsiderar na apuração).
- **~5 merges "não achei na produção"** — o `jaba_fix.py` não casou com
  nenhuma credencial (lista no `FIX_relatorio.txt`). Buscar cada nome no
  `/admin` ("Buscar eleitor por nome"); se existir como credencial fundida,
  pegar o token e colá-lo à mão em "Remover credencial", depois importar as
  peças correspondentes de `JABAQUARA_completo.tsv`. Pode ser que a `--desde`
  resolva isso automaticamente (a heurística antiga de contato falhava).

---

## 6. Arquivos (todos em `saida_instalador/`, que é gitignored — contêm PII)

| Arquivo | O quê |
|---|---|
| `JABAQUARA_bloco_01..13.tsv` | 754 credenciais corretas, 60 por bloco (o 13 tem menos) |
| `JABAQUARA_completo.tsv` | as 754 num arquivo só |
| `JABAQUARA_conferencia.csv` | conferência humana: turma, responsável parcial, alerta |
| `JABAQUARA_desmembradas.csv` | os 24 merges: credencial errada → credenciais certas |
| `JABAQUARA_revisar_irmaos.csv` | pares de famílias com mesmo sobrenome, p/ olho humano |
| `FIX_relatorio.txt` | (gerado pelo jaba_fix) o plano inteiro em texto |
| `FIX_tokens_para_remover.txt` | tokens → "Remover credencial" |
| `FIX_reimportar.tsv` | linhas → "Importar eleitores" |
| `FIX_faltando.tsv` | famílias que faltam → "Importar eleitores" |
| `FIX_votaram_resolver.txt` | casos que já votaram, p/ ata |

Textos prontos (raiz do repo, não versionados): `AVISO-FAMILIAS-JABAQUARA.txt`,
`OFICIO-COMISSAO-GESTAO-JABAQUARA.md`, `COMUNICADO-PRORROGACAO.txt`.

---

## 7. Notas de ambiente / armadilhas

- **Python**: rode sempre com `PYTHONUTF8=1` ou `set PYTHONUTF8=1` antes, senão
  o `print` quebra nos acentos no console do Windows. (No PowerShell:
  `$env:PYTHONUTF8=1`.)
- **Node**: não está no PATH desta máquina. Para checar sintaxe de `.js`:
  ```powershell
  $env:ELECTRON_RUN_AS_NODE=1
  & "C:\Users\thiag\AppData\Local\Programs\Microsoft VS Code\Code.exe" --check server.js
  ```
- **`jaba_fix.py` lê `credenciais-producao.csv`**; se não existir, cai em
  `credenciais-emia.csv` (que é uma cópia ANTIGA, pré-Jabaquara, de 953
  linhas — foi o que confundiu hoje). Sempre confira a 1ª linha do output:
  `produção: NNNN credenciais lidas de <arquivo>`.
- O `del`/`Copy-Item` no PowerShell: **não cole conteúdo de .txt no prompt**
  (o Thiago fez isso e viu um monte de erro vermelho — inofensivo, mas
  assustador). Abrir os relatórios com `notepad` ou no VS Code.
- **`git status`** mostra vários arquivos untracked que são de apoio/PII
  (`.ps1`, `.html`, `AUDITORIA_*.md`, `Image *.png`) — deixe como estão.

---

## 8. Se amanhã quiserem a abordagem "resetar tudo da Jabaquara"

Alternativa ao conserto cirúrgico: como as famílias da Jabaquara usam o link
genérico `/acesso` (nenhum link individual foi distribuído), **re-tokenizar é
invisível pra elas**. Daria pra:
1. `jaba_fix.py --desde 2026-09-01` lista TODOS os tokens Jabaquara não-votados.
2. Remover todos ("Remover credencial", em blocos).
3. Colar `JABAQUARA_bloco_01..13.tsv` inteiro de novo (agora a versão 754,
   já corrigida), **menos** as famílias que já votaram (essas mantêm a
   credencial atual — o `jaba_fix` sabe quais são).

É mais radical mas deixa o estado 100% limpo. O conserto cirúrgico do §4 é
menos invasivo e foi o escolhido hoje. Decidir com o Thiago.
