# Urna EMIA — Eleição Conselho 2026-2028

Sistema de votação online para a eleição do Conselho da EMIA (biênio
2026-2028), segmentos Corpo Docente e Famílias. Atende aos requisitos
mínimos do item 3.4.1 do Edital: cadastro prévio de eleitores, credencial
individual por link, um voto por credencial, sigilo do voto (a tabela de
votos não guarda nenhuma referência a quem votou), apuração e auditoria pela
Comissão, e registro de ocorrências técnicas.

> **Nota (01/09/2026):** o deploy **já está feito** — site no ar em
> https://emia-urna.onrender.com , repo
> `github.com/thiagobrisolla4-max/emia-urna`, deploy automático no `git push`
> da branch `main`. Links em `LINKS.md`. A seção 1 abaixo fica como
> referência de como o ambiente foi montado.

## 1. Fazer o deploy no Render (passo a passo)

Isso leva uns 15 minutos. Você vai precisar de uma conta no GitHub e uma
conta no Render (render.com) — se não tiver, crie uma em cada, é gratuito
criar a conta (só o plano do servidor é pago).

### 1.1 Subir o código para o GitHub

1. Vá em [github.com/new](https://github.com/new), crie um repositório
   **privado** chamado `emia-urna` (mantenha privado — o código tem os
   nomes das candidatas e a lógica interna do sistema).
2. No terminal, dentro desta pasta (`SYNC\_PY\10_PROJETOS_ATIVOS\emia-urna`,
   em qualquer dispositivo onde o Syncthing já tenha sincronizado — PC Torre
   ou notebook), rode:
   ```
   git init
   git add .
   git commit -m "Urna EMIA - versao inicial"
   git branch -M main
   git remote add origin https://github.com/SEU-USUARIO/emia-urna.git
   git push -u origin main
   ```
   (troque `SEU-USUARIO` pelo seu usuário do GitHub — o GitHub mostra o
   comando exato certinho na página do repositório recém-criado, é só
   copiar de lá).

### 1.2 Criar o banco de dados no Render

1. Entre em [dashboard.render.com](https://dashboard.render.com).
2. Clique em **New +** → **PostgreSQL**.
3. Nome: `emia-urna-db`. Região: qualquer uma perto do Brasil (Oregon ou
   Ohio, nas opções gratuitas do Render, funcionam bem). Plano: **Free**
   está OK aqui, mesmo pagando pelo servidor web — o banco não precisa do
   plano pago pra durar as poucas semanas da eleição.
4. Clique em **Create Database**. Espere ficar "Available" (1-2 minutos).
5. Na página do banco, copie o valor de **Internal Database URL** (vamos
   usar no próximo passo).

### 1.3 Criar o serviço web

1. Clique em **New +** → **Web Service**.
2. Conecte sua conta do GitHub e escolha o repositório `emia-urna`.
3. Nome: `urna-emia` (isso vira parte do link público, tipo
   `urna-emia.onrender.com`).
4. Region: a mesma do banco.
5. Branch: `main`. Root Directory: deixe em branco.
6. Runtime: **Node**.
7. Build Command: `npm install`.
8. Start Command: `npm start`.
9. Plano: **Starter** (~US$7/mês) — não escolha o Free, pra evitar o
   servidor "dormir" e travar no primeiro acesso do dia.
10. Em **Environment Variables**, adicione:
    - `DATABASE_URL` = (cole o Internal Database URL copiado no passo 1.2)
    - `ADMIN_PASSWORD` = escolha uma senha forte só a Comissão vai saber
    - `SESSION_SECRET` = qualquer string aleatória longa (ex: gere uma em
      [1password.com/password-generator](https://1password.com/password-generator/)
      ou simplesmente digite 40 caracteres aleatórios)
11. Clique em **Create Web Service**. O Render vai buildar e subir
    automaticamente — acompanhe em **Logs**. Quando aparecer
    `Urna EMIA rodando na porta ...`, está no ar.
12. Sua urna está em `https://urna-emia.onrender.com` (ou o nome que você
    escolheu). Guarde esse link.

## 2. Teste obrigatório antes de abrir a votação oficial

O próprio Edital (item 3.4.1) exige testar a plataforma antes da abertura
oficial, registrando o teste em ata. Faça assim:

1. Acesse `https://SEU-LINK.onrender.com/admin` e entre com a
   `ADMIN_PASSWORD`.
2. Em **Importar eleitores**, cole 2-3 linhas de teste, por exemplo:
   ```
   Teste Docente,11900000000,docente
   Teste Familia,11900000001,familia
   ```
3. Clique em **Abrir votação agora**.
4. Baixe **credenciais.csv**, pegue os links de teste, abra em uma aba
   anônima e vote em cada um. Confirme que:
   - o voto é aceito;
   - tentar votar de novo com o mesmo link mostra "voto já registrado";
   - o painel mostra a participação subindo.
5. Volte ao painel e clique em **Encerrar votação agora**, depois em
   **Ver apuração detalhada** — confirme que os votos de teste aparecem
   certinhos.
6. **Registrem esse teste na ata da Comissão** (data, hora, quem participou,
   resultado do teste) — é isso que o Edital pede.
7. Depois do teste, clique em **Zerar dados de teste** no painel — isso
   apaga os eleitores/votos de teste, deixando o sistema limpo pra
   importação real. **Não pule esse passo**, ou os votos de teste vão
   aparecer misturados com os reais.

## 3. No dia de abrir a votação de verdade (31/08/2026)

1. Reúnam a lista real de eleitores aptos por segmento (a Comissão precisa
   ter validado essa lista antes — inclusive a regra de "1 voto por
   família", já que o sistema não sabe quais responsáveis são da mesma
   família, isso é responsabilidade da lista que vocês sobem).
2. No painel, cole a lista em **Importar eleitores**, no formato
   `nome,contato,segmento` (uma pessoa por linha; segmento é `docente` ou
   `familia` — o sistema aceita com ou sem acento/maiúsculas).
3. Baixe **credenciais.csv** e distribuam os links individuais por
   WhatsApp/e-mail, um por pessoa. **Nunca reenvie o mesmo link pra duas
   pessoas diferentes.**
4. Clique em **Abrir votação agora**.
5. Acompanhem a participação em tempo real no painel.

## 3.1 Instalador serial + Portal da Família (recomendado)

Em vez de montar a lista na mão, use o **`instalador.py`**. Ele lê as
planilhas de docentes e famílias (`DADOS Educadores EMIA.xlsx`,
`LISTA CONTATOS - Chácara do Jóquei.xlsx`, etc.), corrige encoding e lixo nos
nomes, normaliza telefones, **agrupa a família toda numa credencial só**
(irmãos + mãe/pai/avó = 1 voto), casa com as credenciais já existentes pra
não duplicar, e gera arquivos prontos pra colar no painel:

```
python instalador.py
# escreve ./saida_instalador/
#   A_chaves_para_tokens_existentes.tsv  -> painel: "Vincular chaves a credenciais já existentes"
#   B_novos_eleitores.tsv                -> painel: "Importar eleitores"
#   C_conferencia_familias.csv           -> conferência humana (Excel)
#   D..G_*.csv                           -> telefones suspeitos, possíveis duplicatas, conflitos
#   RESUMO.txt                           -> contagem + passo a passo
```

Requisitos: `pip install openpyxl pypdf`.

**Portal da Família — `/acesso`**: página pública onde o responsável digita
**um** dado (telefone, e-mail, ou o nome completo de um(a) estudante da
família) e é levado à cédula da família. Assim a Comissão manda **um link só**
(`/acesso`) no grupo/lista das famílias, em vez de um link por família. As
"chaves" (telefones, e-mails, nomes) são indexadas na tabela `voter_keys`,
que **nunca** se liga a `votes` — o sigilo do voto continua intacto. O portal
tem um liga/desliga no painel e um limite de tentativas por IP.

Quando a lista da EMIA Jabaquara (famílias) chegar: baixe o CSV atualizado
em `/admin`, substitua o `credenciais-emia.csv` local, adicione o arquivo
novo em `SRC_FAMILIA_XLSX` no topo do `instalador.py`, rode de novo e cole
os `A_`/`B_` outra vez — famílias já importadas não duplicam.

## 4. No encerramento (08/09/2026, terça, até 12h — prazo prorrogado; era 05/09)

1. Clique em **Encerrar votação agora** — a partir daí nenhum link
   funciona mais para votar.
2. Vejam a apuração em **Ver apuração detalhada**.
3. Cliquem em **Publicar resultados publicamente** quando a Comissão
   decidir divulgar (isso libera a página pública `/resultados` — sem
   login, sem nomes de eleitores, só os totais, como o Edital exige).
4. Baixem o **relatório final (.txt)** em Baixar relatório final — ele
   já vem no formato dos itens exigidos pelo Edital (item 7), pronto pra
   anexar na Ata de apuração.
5. Registrem tudo em Ata, como sempre.

## 4.1 Voto presencial nas EMIAs (opcional, além do link por celular)

Não é obrigatório nada especial: qualquer computador/tablet com navegador e
internet abre o mesmo site. Pra montar um ponto de voto presencial em uma
unidade:

1. Deixe um computador/tablet na recepção, com o navegador em **aba anônima**
   (evita que o histórico guarde o link de quem votou).
2. Um responsável da Comissão acessa `/admin/buscar` (dentro do painel
   admin), digita o nome de quem vai votar, clica em **Abrir cédula** (abre
   em nova aba) e entrega o aparelho pra pessoa votar sozinha.
3. Feche a aba depois de cada voto, antes do próximo eleitor.

Quem abre o link vê **quem** está votando (não em quem) — por isso precisa
ser sempre alguém de confiança da Comissão, igual a uma mesa de votação
física comum.

## 5. Notas técnicas (se algo der errado)

- **Sigilo do voto**: a tabela `votes` no banco não tem nenhuma coluna
  ligando um voto a um eleitor — é estrutural, não dá nem pra consultar
  isso mesmo com acesso direto ao banco.
- **Um voto por credencial**: cada link só funciona uma vez; não existe
  "trocar o voto" depois de enviado (decisão deliberada — ver o plano
  técnico, isso reforça o sigilo).
- **Se o Render reiniciar o servidor** (acontece raramente em deploys),
  a sessão de admin logada é perdida (basta logar de novo) — mas os dados
  no banco Postgres continuam intactos, nada se perde.
- **Ocorrências técnicas**: qualquer problema durante a votação, registrem
  no painel em "Ocorrências técnicas" — isso entra automaticamente no
  relatório final.
- Ligue para o suporte técnico (você) se `/admin` não abrir — o log de erro
  fica visível no painel **Logs** do Render.
