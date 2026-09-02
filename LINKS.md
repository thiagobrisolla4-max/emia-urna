# Urna EMIA — links de acesso

| O quê | URL |
|---|---|
| **Urna (sistema)** | https://emia-urna.onrender.com |
| **Painel da Comissão (admin)** | https://emia-urna.onrender.com/admin |
| **Portal da Família** (autoatendimento por telefone/e-mail/nome do filho) | https://emia-urna.onrender.com/acesso |
| **Resultados** (público, só depois da apuração) | https://emia-urna.onrender.com/resultados |
| **Dashboard Render** (logs, env vars, banco) | https://dashboard.render.com |
| **Repositório GitHub** (privado) | https://github.com/thiagobrisolla4-max/emia-urna |

O deploy é automático: `git push` na branch `main` → o Render builda e sobe
sozinho. Acompanhe em **Logs** no dashboard até aparecer
`Urna EMIA rodando na porta ...`.

Credenciais de acesso ao painel: variável `ADMIN_PASSWORD` no Render
(Environment). Só a Comissão sabe.

## Janela oficial de votação
31/08/2026 a **08/09/2026 (terça-feira), até 12h** — prazo prorrogado pela
Comissão Eleitoral (era 05/09/2026).

O sistema não encerra sozinho: a votação só fecha quando a Comissão clica
em "Encerrar votação agora" no painel. A data acima é o texto mostrado ao
eleitor e mora em `JANELA`, no topo do `server.js`.
