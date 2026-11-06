# Engenharia Reversa — Scout AI (Yahoo Finance): Promenade API e MAD v2

Chat (Promenade): 🔑 `Cookie (A3)` — crumb não participa de nenhuma rota; sem cookie, `POST /sessions` responde **400** `missing_identity` e `POST /chat` também responde **400** `missing_identity` (revalidado 2026-11-06, com e sem `X-Sas-Enforce-Quota: 1`; nas capturas de set/out-2026 o `/chat` caía no regime de quota com **429** `quota_exceeded` — a precedência identidade×quota não é estável entre deploys, §7). Com o `A3` de `fc.yahoo.com` ambas respondem **2xx** (`201` na criação, `200` no chat). Escrita de estado de sessão exige identidade logada: `PATCH` responde **403** `Anonymous sessions cannot be updated`. Análises MAD (`/ws/mad/v2/analyst/*`, `/ws/mad/v2/articles_ddq/*`, `/ws/mad/v2/themes` GET): ❌ `Anônimo` ok — o gate é só nas escritas. Escrita de temas e insights de portfólio (`from-articles`, `/v2/daily_brief/*`, `/v2/portfolio_ddq/faqs`, `/v2/watchlist_insights/*`): 🔑 `Token de Assinatura` (JWT no header `x-txn-token`) — sem o header, **401**. Família `/ws/mad/v2/chat`: **410 Gone** (aposentada). Métodos GET/POST/PATCH; hosts válidos `promenade-api.search.yahoo.com`, `query1.finance.yahoo.com`, `query2.finance.yahoo.com` e `finance.yahoo.com` (proxy XHR).

> Escopo: Promenade API (chat) + MAD v2 (AI Analyst, Dig Deeper, temas e insights de portfólio) — especificação única no esqueleto do template mestre; o mapa rota → seção está no §1.

## 1. Visão geral e papel no aplicativo

O **Scout** é o assistente de IA do Yahoo Finance: chat financeiro com *grounding* em notícias e dados, perguntas de continuação, ações sugeridas e histórico de sessões. Ao redor dele, o mesmo subsistema de IA expõe quatro superfícies complementares: o **AI Analyst** (análises por ativo), o **Dig Deeper** (perguntas encadeadas em artigos), os **temas** do AI Playground e os **insights de portfólio** — todas servidas por dois backends distintos.

O backend do chat é a **Promenade API**, operada no domínio de busca do Yahoo (`promenade-api.search.yahoo.com`). O bundle carrega o host como constante do serviço `scout`, com uma variante de desenvolvimento:

```js
// chunks/[cliente-scout].[hash].js — constantes de host
const ia = "https://promenade-api.search.yahoo.com";
const aa = "https://dev-promenade-api.search.yahoo.com";
```

As análises (AI Analyst, Dig Deeper, temas, insights de portfólio) usam o serviço **MAD** (Market Analysis & Data) no domínio `query1.finance.yahoo.com`, roteado pelas chaves de serviço `finance`/`financeProd`/`financeStage` (§2.2).

Mapa de rotas e seções deste documento:

| Endpoint | Host | Método | Auth | Descrição | Seção |
| :--- | :--- | :---: | :--- | :--- | :---: |
| `/sessions` | Promenade | POST | 🔑 Cookie A3 | Criação de sessão de chat | §2.1 |
| `/chat` | Promenade | POST | 🔑 Cookie A3 | Mensagem — JSON completo ou SSE | §2.1, §4.2, §5.3 |
| `/chat/seeds` | Promenade | POST | 🔑 Cookie A3 | Resposta semeada com cache por identidade | §2.1, §4.4 |
| `/sessions/{id}/messages` | Promenade | GET | 🔑 Cookie A3 | Histórico paginado por cursor | §2.1, §4.3 |
| `/sessions/{id}` | Promenade | GET | 🔑 Cookie A3 | Metadados e títulos derivados | §2.1, §5.1 |
| `/sessions` | Promenade | GET | 🔑 identidade logada | Lista de sessões | §2.1 |
| `/sessions/{id}` (`PATCH`, `POST …/delete`) | Promenade | PATCH/POST | 🔑 sessão logada | Escrita restrita | §2.1 |
| `/sessions/{id}/active-stream` | Promenade | GET | 🔑 Cookie A3 | Sondagem de stream em andamento | §2.1 |
| `/chat/resume/{stream_id}` | Promenade | GET | 🔑 Cookie A3 | Replay do stream por `last_event_id` | §2.1 |
| `/feedback` | Promenade | POST | 🔑 Cookie A3 | Avaliação 👍/👎 de resposta | §2.1, §5.2 |
| `/xhr/dynamic-seeded-questions` | finance.yahoo.com | GET | ❌ Anônimo | Catálogo de perguntas sugeridas | §3.1, §5.4 |
| `/ws/mad/v2/analyst/symbol/{symbol}` | query1/query2 | GET | ❌ Anônimo | AI Analyst por ativo, 8 seções | §3.2, §5.5 |
| `/ws/mad/v2/analyst/ect` | query1 | GET | ❌ Anônimo | Insights de transcrições de earnings | §3.2 |
| `/ws/mad/v2/articles_ddq/{uuid}/questions[/{questionId}]` | query1 | GET | ❌ Anônimo | Dig Deeper de artigos | §3.3, §5.6 |
| `/ws/mad/v2/chat` (família) | query1 | POST/GET | — | **410 Gone** — chat aposentado | §3.4, §7 |
| `/ws/mad/v2/themes` (família GET) | query1 | GET | ❌ Anônimo | Temas, tickers, grafo | §3.5, §5.7 |
| `/ws/mad/v2/themes/from-articles` | query1 | POST | 🔑 x-txn-token | Grafo de temas por artigos | §3.5 |
| `/ws/mad/v2/themes/portfolio/feed` | query1 | POST/GET | ❌ Anônimo | Feed de temas do portfólio | §3.5 |
| `/v2/daily_brief/*`, `/v2/portfolio_ddq/faqs`, `/v2/watchlist_insights/*` | query1 | GET | 🔑 x-txn-token | Insights de portfólio | §3.5 |
| `/ws/mad/v2/screener/nls` e legados | query1 | POST | 🔑 sessão logada | Screener NLS (rota dormente no frontend) | §3.4 |

O produto tem, ainda, duas peças com contratos distintos: o chat em si (rotas `/sessions` e `/chat` no host Promenade, mais o par de retomada `/sessions/{id}/active-stream` + `/chat/resume/{stream_id}`) e o **catálogo de perguntas sugeridas** servido pelo proxy XHR público do próprio `finance.yahoo.com`, usado para pré-aquecer a conversa com perguntas geradas por *workflows* editoriais e de dados.

### 1.1 Arquitetura de referência

1. **Config de serviços** — mapa `scout`/`scoutDev`/`finance`/`financeProd`/`financeStage` → host, servido pelo HTML em blocos `data-sveltekit-fetched` (§2.2).
2. **Camada de Loader / Gateway:** loaders MAD (`chunks/[loadTickerAnalysisForSymbol].[hash].js`, `chunks/[loadDigDeeperQuestions].[hash].js`, `chunks/[loadChatResponse].[hash].js`, `chunks/[loadChatRateLimits].[hash].js`) — sanitizam inputs, validam UUIDs e flags, resolvem a chave de serviço e despacham a requisição.
3. **Camada de Transporte / Fetch:** `fetchService` (`chunks/[quoteUtil].[hash].js`) — resolve host por chave de serviço, aplica `credentials: "include"`, `crumb` default `false`, `disableDefaultQueries` e gerencia timeouts/`AbortSignal`.
4. **Camada de Cliente / Apresentação:** cliente do Scout (`chunks/[cliente-scout].[hash].js`) — criação de sessão, corpo do `/chat`, cabeçalho de quota, parser SSE e extração de resultados — consumido por `chunks/[AiAnalystSheet].[hash].js`, `chunks/[Dock].[hash].js`, `chunks/[DigDeeperAiSheet].[hash].js` e `nodes/[playground].[hash].js`.

### 1.2 Ciclo de vida do chat

```
[ Bootstrap anônimo: GET fc.yahoo.com → cookie A3 (+ A1/A1S) ]
                    │
                    ▼
[ POST /sessions {"tenant":"finance"} ] → 201 {session_id}
                    │
                    ▼
[ POST /chat {message, session_id, tenant} ]
      ├── sem Accept especializado ──► 200 application/json (resposta completa)
      └── Accept: text/event-stream ──► 200 text/event-stream (eventos do §5.3)
                    │
                    ▼
[ (opcional) GET /sessions/{id}/active-stream → {active, stream_id, resume_url} ]
                    │
                    ▼
[ (opcional) GET /chat/resume/{stream_id}?last_event_id=0 → replay do stream ]
                    │
                    ▼
[ GET /sessions/{id}/messages?tenant=finance → histórico ]
                    │
                    ▼
[ (opcional) POST /feedback {rating, ...} → avaliação da resposta ]
```

### 1.3 Otimizações do loader

- **Resposta semeada (cache server-side):** com `enableSeededCaching: true`, o cliente troca `POST /chat` por `POST /chat/seeds` com `ttl: 5` — a resposta volta pronta em JSON (§2.1).
- **Sanitização de entrada pré-fetch:** os guards do Dig Deeper validam `uuid`/`questionId` por regex RFC 4122 antes de qualquer requisição; o AI Analyst valida o símbolo contra a allowlist do cliente (§3.2) antes de carregar a página.
- **Validação de persistência local:** o histórico do Dock valida o id da última conversa por `/^[\w-]{1,64}$/` antes de reutilizá-lo; as carteiras salvas do Playground validam o shape (`id`/`name`/`holdings` com `ticker`/`weight`) na leitura e na escrita.
- **Modo silencioso / Tratamento gracioso de erro:** falhas do fetch do AI Analyst e do Dig Deeper são engolidas com log de telemetria e retorno `null` — a UI segue sem o dado; o sondador de stream ativo trata sessão inexistente como `{active: false}`.
- **Retomada de stream:** o par `active-stream` + `resume` recupera a resposta em curso sem repetir a pergunta quando o cliente sai da página durante a geração (§2.1).

## 2. Especificação do Protocolo Wire (Request)

### 2.1 Linha de requisição por rota

**Chat (Promenade):**

```http
POST /sessions HTTP/2
Host: promenade-api.search.yahoo.com

{"tenant":"finance"}
```

```http
POST /chat HTTP/2
Host: promenade-api.search.yahoo.com

{"message":"...","session_id":"...","tenant":"finance"}
```

```http
POST /chat/seeds HTTP/2
Host: promenade-api.search.yahoo.com

{"message":"What is NASDAQ?","tenant":"finance","ttl":5}
```

```http
GET /sessions/{session_id}/messages?tenant=finance&limit=100&cursor={next_cursor} HTTP/2
Host: promenade-api.search.yahoo.com
```

```http
GET /sessions/{session_id}?tenant=finance HTTP/2
Host: promenade-api.search.yahoo.com
```

```http
GET /sessions?tenant=finance HTTP/2
Host: promenade-api.search.yahoo.com
```

```http
PATCH /sessions/{session_id}?tenant=finance HTTP/2
Host: promenade-api.search.yahoo.com

{"pinned":true}
```

```http
DELETE /sessions/{session_id}?tenant=finance HTTP/2
Host: promenade-api.search.yahoo.com
```

```http
POST /sessions/{session_id}/delete?tenant=finance HTTP/2
Host: promenade-api.search.yahoo.com
```

```http
GET /sessions/{session_id}/active-stream?tenant=finance HTTP/2
Host: promenade-api.search.yahoo.com
```

```http
GET /chat/resume/{stream_id}?last_event_id=0&tenant=finance HTTP/2
Host: promenade-api.search.yahoo.com
Accept: text/event-stream
```

```http
POST /feedback HTTP/2
Host: promenade-api.search.yahoo.com

{"tenant":"finance","session_id":"...","message_id":"...","rating":1,"fields":{"reason":"..."},"feedback":"..."}
```

A query `tenant` é **obrigatória** em todas as rotas de sessão (§7): sem ela, **400** `{"code":"invalid_request","message":"Request validation failed: /tenant: Required"}`. O corpo do `/chat` completo construído pelo cliente:

```js
// chunks/[cliente-scout].[hash].js — construtor do payload do /chat
const g = {
  context: (r == null ? undefined : r.trim()) || undefined,
  idempotency_key: c ? undefined : i,
  message: d,
  session_id: c ? undefined : l,
  tenant: m,
  ttl: c ? X : undefined,
  variant: (h == null ? undefined : h.trim()) || undefined
};
```

Com `enableSeededCaching: true`, o cliente desvia o POST:

```js
// chunks/[cliente-scout].[hash].js — seleção da rota de envio
const v70 = u ? "/chat/seeds" : "/chat";
// ... ttl: u ? vLN5 : undefined   (vLN5 = 5)
// ... vO3["X-Sas-Enforce-Quota"] = "1";   (quando enforceQuota ativo)
```

**Campo `seed_auth` (novo no build de 2026-11-05 — só no modo seeds):** o corpo do `/chat/seeds` passou a carregar o token de autorização da semente, resolvido do catálogo de perguntas sugeridas (§5.4):

```js
// chunks/[cliente-scout].[hash].js — build atual: corpo do /chat com seed_auth
I = { context: (r?.trim()) || undefined, idempotency_key: a ? void 0 : u, message: d,
      seed_auth: a ? vt(w, r, v) : void 0, session_id: a ? void 0 : i,
      tenant: m, ttl: a ? Tt : void 0, variant: (v?.trim()) || undefined };
// vt(t, e, o) = seed_auth_contexts[e.trim()][o.trim() || "base"]  — o lookup direto no
// catálogo §5.4: o cliente pega o token da pergunta sugerida (contexto "ticker:AAPL",
// base "base") e o transporta no corpo — autorização da semente no fio
```

O orquestrador de retomada sonda e consome:

```js
// chunks/[cliente-scout].[hash].js — sessão de retomada
const { streamId: n, sessionId: s, environment: i = "prod", tenant: d = vLSFinance } = p65;
```

**Análises (MAD):**

```http
GET /ws/mad/v2/analyst/symbol/AAPL?lang=en-US&region=US HTTP/2
Host: query1.finance.yahoo.com
```

```http
GET /ws/mad/v2/analyst/ect?transcript_id={id}|event_id={uuid} HTTP/2
Host: query1.finance.yahoo.com
```

```http
GET /ws/mad/v2/articles_ddq/{uuid}/questions HTTP/2
Host: query1.finance.yahoo.com
```

```http
GET /ws/mad/v2/articles_ddq/{uuid}/questions/{questionId} HTTP/2
Host: query1.finance.yahoo.com
```

```http
POST /ws/mad/v2/themes HTTP/2 /themes/tickers /themes/{themeUuid} /themes/symbol/{ticker} /themes/graph
Host: query1.finance.yahoo.com
```

```http
POST /ws/mad/v2/themes/from-articles HTTP/2
Host: query1.finance.yahoo.com

{"article_uuids":["..."],"grain":"parent","topic_type":"ALL","limit":6,"tickers_per_theme":8,"article_max_age_hours":48,"ticker_min_relevance":0.1,"min_support":0.3}
```

```http
POST /ws/mad/v2/themes/portfolio/feed HTTP/2
Host: query1.finance.yahoo.com

{"holdings":[{"ticker":"AAPL","weight":5000},{"ticker":"NVDA","weight":3000}],"grain":"parent","limit":6,"narrate":true,"topic_type":"ALL"}
```

```http
GET /ws/mad/v2/themes/portfolio/feed?portfolio_id={id}&grain=parent&limit=6&narrate=true&topic_type=ALL HTTP/2
Host: query1.finance.yahoo.com
```

```http
GET /v2/daily_brief/analysis HTTP/2
Host: query1.finance.yahoo.com
```

```http
GET /v2/daily_brief/portfolio_insights/analysis?pfId={pfId} HTTP/2
Host: query1.finance.yahoo.com
```

```http
GET /v2/portfolio_ddq/faqs?question={q}&questionId={qid}&pfId={pfId} HTTP/2
Host: query1.finance.yahoo.com
```

```http
GET /xhr/dynamic-seeded-questions?symbol=AAPL&limit=5 HTTP/2
Host: finance.yahoo.com
```

Carregadores de referência (paths e chaves, verbatim do bundle):

```js
// chunks/[loadTickerAnalysisForSymbol].[hash].js — path do AI Analyst
const vF2 = (p2) => `/ws/mad/v2/analyst/symbol/${p2}`;
// ... key: v4 ? "financeStage" : "financeProd",
// ... debug_flag: `${v4}`
```

```js
// chunks/[loadDigDeeperQuestions].[hash].js — paths do Dig Deeper
pathname: `/ws/mad/v2/articles_ddq/${p55.uuid}/questions`,
pathname: `/ws/mad/v2/articles_ddq/${p57.uuid}/questions/${p57.questionId}`,
```

```js
// chunks/[loadDigDeeperQuestions].[hash].js — chave de serviço com staging
const v = async (n) => {
  const t = await k(n);
  return A(t, "enableForceDDQStaging") ? "financeStage" : "finance";
};
```

O chat aposentado (`/ws/mad/v2/chat`) — todas as variantes respondem **410** `{"detail": "The chat API has been retired."}`; o contrato do carregador que o invoca (POST com `chat_version`/`use_fargate`, corpo `{question, symbol?, initial_context?}`, polling de `/question/{id}`, constantes `5000/1000/1000/5/60/429/3`) permanece documentado porque sobrevive no bundle; o default `chat_version = "v11"` vive como export `D` em `chunks/[room_service].[hash].js`, importado pelo carregador e aplicado em `chatVersion||v`. O adaptador do chat de artigo (§3.3) alterna a versão: `v14` sob a flag `enableDigDeeperArticleChat`, `v11` caso contrário — e na v14 o `initial_context` vai como **JSON** `{"article_uuids":["…"]}`; na v11, como texto plano (`Article UUID: …
Title: …
Summary: …`). O carregador de rate limit da mesma família tem gate duplo no cliente:

```js
// chunks/[loadChatRateLimits].[hash].js — gate duplo do rate_limit aposentado
const v169 = (v166 = v168.getPageConfig()) != null && !!v166.enableQSPAiAnalystSheetChat;
const v170 = v167 == null ? undefined : v167.isWebview;
const v171 = Be(v167, "enableDigDeeperArticleChat") && !v170;
const v173 = v167.authed === "1";
// pathname: "/ws/mad/v2/chat/rate_limit", perfLabel: "loadChatRateLimits",
// query: {}, timeout: 3e3  — só executa com authed === "1" e um gate ativo
```

### 2.2 Hosts válidos

O mapa de serviços não é constante estática da camada: a resolução é `config.getState().services` no *runtime*, e o config chega embutido no HTML em blocos `data-sveltekit-fetched`, produzidos por uma chamada interna a `/xhr/config?name=services` (cache `data-ttl="120"`):

```json
{
  "finance":         {"host": "query1.finance.yahoo.com", "serverKey": "finance", "timeout": 3000, "client": {"timeout": 15000}},
  "financeProd":     {"host": "query1.finance.yahoo.com", "serverKey": "financeProd", "timeout": 3000},
  "financeStage":    {"host": "iquery-stage.finance.yahoo.com", "serverKey": "financeStage", "timeout": 3000},
  "financeInternal": {"host": "iquery.finance.yahoo.com", "serverKey": "financeInternal", "timeout": 3000},
  "preferences":     {"host": "graviton-home-gateway.media.yahoo.com", "serverKey": "preferences", "timeout": 3000},
  "community":       {"host": "yfc-server-query.finance.yahoo.com", "protocol": "https:", "pathname": "/"},
  "communityMedia":  {"host": "yfc-media.finance.yahoo.com", "protocol": "https:", "pathname": ""},
  "liveblog":        {"host": "finance.yahoo.com", "pathname": "/caas/content/article/loadMoreBlogPosts", "protocol": "https:"},
  "mail":            {"host": "apis.mail.yahoo.com", "protocol": "https:", "pathname": "/ws/v3/batch"},
  "jsapi":           {"host": "jsapi.login.yahoo.com", "protocol": "https:"},
  "syimg":           {"host": "s.yimg.com", "protocol": "https:", "pathname": "/"},
  "timeout": 3000,
  "ypfGateway":      {"host": "ypf-gateway.finance.yahoo.com", "protocol": "https:", "pathname": ""},
  "scout":           {"host": "promenade-api.search.yahoo.com", "protocol": "https:", "timeout": 30000},
  "scoutDev":        {"host": "dev-promenade-api.search.yahoo.com", "protocol": "https:", "timeout": 30000}
}
```

| Host | Papel | Evidência no Bundle |
| :--- | :--- | :--- |
| `https://promenade-api.search.yahoo.com` | Produção do chat (serviço `scout`) | `chunks/[cliente-scout].[hash].js`, `nodes/[playground].[hash].js` |
| `https://dev-promenade-api.search.yahoo.com` | Desenvolvimento do chat (serviço `scoutDev`) — não resolve na internet pública | `nodes/[playground].[hash].js` |
| `https://query1.finance.yahoo.com` | Produção principal das análises MAD (chaves `finance`/`financeProd`) | `chunks/[loadTickerAnalysisForSymbol].[hash].js`, `chunks/[loadDigDeeperQuestions].[hash].js` |
| `https://query2.finance.yahoo.com` | Rota secundária do AI Analyst (mesma resposta anônima) | `chunks/[loadTickerAnalysisForSymbol].[hash].js` |
| `https://iquery-stage.finance.yahoo.com` | Staging interno (chave `financeStage`) — conexão recusada fora da rede interna | `chunks/[loadChatRateLimits].[hash].js`, `nodes/[playground].[hash].js` |
| `https://finance.yahoo.com/xhr/...` | Proxy XHR do frontend (`/xhr/dynamic-seeded-questions`, `/xhr/config`) | `chunks/[loadDynamicSeededQuestions].[hash].js` |

`scout` e `scoutDev` são os únicos serviços com `timeout` próprio elevado (`30000`). `GET /xhr/config?name=services` responde **405** `GET method not allowed`; `POST` com corpo fora do schema interno responde **400** `{"message":"Schema mismatch for /xhr/config"}` — a rota é de uso do *loader* server-side do SvelteKit, não pública. Sem serviço conhecido, o fallback da camada de fetch é o par `query1.finance.yahoo.com`/`serverKey "finance"`. A reescrita `/xhr/service` por `serverKey` (gateada por `window._nimbus.ready`) continua na camada — chamadas externas diretas a `/xhr/service/...` recebem **404** HTML da borda ATS.

A resolução de ambiente do chat acontece no cliente:

```js
// chunks/[cliente-scout].[hash].js — seletor de serviço por ambiente
function L(t) {
  if (t === "nonprod") {
    return "scoutDev";
  } else {
    return "scout";
  }
}
```

O retorno é usado como `key` do serviço; a config fornece o host. A página AI Playground monta URLs do histórico **diretamente** com as constantes de host, contornando a camada (§9.4).

### 2.3 Cabeçalhos críticos da requisição

| Header | Valor exigido / recomendado | Efeito de ausência / erro |
| :--- | :--- | :--- |
| `Cookie` | `A3=<token>` (par anônimo de `fc.yahoo.com`, com `A1`/`A1S`) | Promenade: `400 missing_identity` em `/sessions` e rotas de sessão; `429 quota_exceeded` no `/chat`. MAD: irrelevante nas rotas anônimas; obrigatório o JWT em `x-txn-token` nas rotas gateadas |
| `Content-Type` | `application/json` (POST com corpo) | Schema do corpo rejeitado |
| `Accept` | livre no `/chat` — define a negociação: sem `text/event-stream` a resposta volta em JSON completo; com `text/event-stream` volta SSE | No `/chat/resume`, `Accept: text/event-stream` é **obrigatório** — sem ele, **406** `not_acceptable` |
| `X-Sas-Enforce-Quota` | `1` (opcional; flag `enforceQuota` do cliente) | Aplicação estrita de quota por identidade; sem login real, a rota responde com o mesmo `429 quota_exceeded` |
| `x-txn-token` | JWT (três segmentos) — `from-articles`, `/v2/daily_brief/*`, `/v2/portfolio_ddq/faqs`, `/v2/watchlist_insights/*` | **401** `Missing x-txn-token header` (ou `Authentication required. Missing or empty x-txn-token header.`); token não-JWT → **401** `Not enough segments`; JWT com assinatura inválida → **401** `...The specified key is an asymmetric key or x509 certificate…` — validação com **chave assimétrica** (família RS/EC/x509), não HMAC |
| `credentials` | `include` (cookies do domínio `.yahoo.com` acompanham todas as requisições) | Sem o jar, a identidade não chega ao Promenade |
| `crumb` / `x-crumb` | **não usados** — o Scout nunca ativa o crumb da camada (`crumb: false` por default; `disableDefaultQueries: true` em todas as chamadas, logo **nenhuma rota recebe `lang`/`region`**) | — |

Quando o chamador ativa o crumb (rotas fora do Scout), a camada o injeta na query **e** no header `x-crumb`, com três estratégias (`Array` → `push`, `Headers` → `set`, objeto → atribuição).

### 2.4 Timeouts do cliente oficial

| Medição | Valor | Fonte |
| :--- | :---: | :--- |
| Serviço `scout`/`scoutDev` (chat, JSON e SSE) | `30 000 ms` | Config de serviços + default da camada de stream (`Le = 3e4`) |
| Timeout padrão REST (chave `finance`) | `3 000 ms` server-side / `15 000 ms` client | Config de serviços (`timeout` / `client.timeout`) |
| POST do chat aposentado (`loadChatResponse`) | `5 000 ms` | `chunks/[loadChatResponse].[hash].js` (`at = 5e3`) |
| GET de pergunta do chat aposentado | `1 000 ms` default | idem (`rt = 1e3`) |
| Intervalo entre polls do chat aposentado | `1 000 ms` (até 60 polls / 5 erros consecutivos) | idem (`ot = 1e3`, `st = 5`, `it = 60`) |
| Retries do POST do chat aposentado | `3` (sem backoff) | idem (`lt = 3`) |
| Rate limit do chat aposentado | `3 000 ms` | `chunks/[loadChatRateLimits].[hash].js` (`timeout: 3e3`) |
| Dig Deeper (catálogo e resposta) | `30 000 ms` | `chunks/[loadDigDeeperQuestions].[hash].js` (`const $ = 3e4`) |
| Refill do rate limit (default client-side) | `3600 s` | `(s.time_to_refill) || 3600` → `Date.now() + f * 1e3` |

O consumo de stream usa controlador dedicado: `Accept: text/event-stream` forçado, `AbortSignal.any` unindo o sinal próprio de timeout ao sinal externo do chamador.

### 2.5 Exemplo de requisição completa

```bash
# 1. Bootstrap anônimo — o cookie A3 é o payload (regiões com barreira de
#    consentimento exigem resolver guce.yahoo.com antes)
curl -s -c cookies.txt "https://fc.yahoo.com" > /dev/null

# 2. Criar a sessão de chat (A3 acompanha via jar; crumb não é enviado)
curl -s -b cookies.txt -X POST "https://promenade-api.search.yahoo.com/sessions" \
  -H "Content-Type: application/json" \
  --data-raw '{"tenant":"finance"}'

# 3. Enviar a mensagem em streaming
curl -s -b cookies.txt -N -X POST "https://promenade-api.search.yahoo.com/chat" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  --data-raw '{"message":"What is the Dow?","session_id":"<session_id>","tenant":"finance"}'

# 4. Análise anônima (MAD) — sem cookie, sem crumb
curl -s "https://query1.finance.yahoo.com/ws/mad/v2/analyst/symbol/AAPL?lang=en-US&region=US"

# 5. Catálogo de perguntas sugeridas (proxy XHR público)
curl -s "https://finance.yahoo.com/xhr/dynamic-seeded-questions?symbol=AAPL&limit=5"
```

---

## 3. Parâmetros de Query e Payloads

### 3.1 Proxy XHR — `/xhr/dynamic-seeded-questions`

| Parâmetro | Tipo | Obrigatório | Padrão | Regex de Validação Client-Side | Depende de Feature Flag? | Comportamento e Casos de Borda |
| :--- | :---: | :---: | :---: | :--- | :---: | :--- |
| `symbol` | string | **Sim** | — | — | Não | Sem ele: **400** `{"message":"xhr.dynamic-seeded-questions: missing symbol"}`. Símbolo inexistente: **502** `{"message":"Request timed out"}` ou **200** com payload vazio — o símbolo falso nunca recebe perguntas populadas. O 502 não é exclusivo de símbolo inexistente: símbolos reais alternam entre **200** populado e **502** de forma estável por símbolo na mesma janela — timeout do *shard* de backend que atende o símbolo, não validação; tratar 502 como transitório |
| `limit` | int | Não | — | — | Não | Limita a lista (`limit=2` devolve 2 itens) |

O loader passa `isRelative: true`, resolvendo para o domínio da página. Resposta **200** anônima (§5.4).

### 3.2 AI Analyst — `/ws/mad/v2/analyst/symbol/{symbol}` e `/analyst/ect`

| Parâmetro | Tipo | Obrigatório | Padrão | Regex de Validação Client-Side | Depende de Feature Flag? | Comportamento e Casos de Borda |
| :--- | :---: | :---: | :---: | :--- | :---: | :--- |
| `{symbol}` (path) | string | **Sim** | — | allowlist do cliente (união de 5 listas, §6.2) | Não | Ticker sem URL-encode obrigatório — tickers com hífen funcionam direto (`BRK-B` está na allowlist). Inexistente no servidor: **404** `{"detail": "Symbol not found for ZZZZZZ"}` |
| `lang` / `region` | string | Não | — | — | Não | Enviados pelo app (`lang=en-US&region=US`), opcionais no servidor (200 sem eles) |
| `debug_flag` | string | Não | `"false"` | — | `enableTickerAnalysisStagingApi` | `"false"` em produção; `"true"` junto com a chave de staging (`financeStage`) — a combinação exige `ynet === "1"` e a flag |
| `event_id` \| `transcript_id` (ECT) | string/int | **exatamente um** | — | — | — | Exclusão mútua aplicada no **servidor**: sem parâmetros → **400** `{"detail": "One parameter required"}`; os dois → **400** `{"detail": "Only one parameter allowed: ['transcript_id', 'event_id']"}`; inexistente → **404** `{"detail": "No transcript insights found for transcript_id 99999999"}` |

A allowlist do cliente governa a UI, não a API: o servidor responde **200** para um ticker fora dela e 404 apenas para símbolo inexistente. A página `/ai/[symbol]/[section]` recusa com **404** os símbolos fora da união e redireciona os sem seção válida para `overview` (§9.6).

### 3.3 Dig Deeper — `/ws/mad/v2/articles_ddq/{uuid}/questions[/{questionId}]`

| Parâmetro | Tipo | Obrigatório | Padrão | Regex de Validação Client-Side | Depende de Feature Flag? | Comportamento e Casos de Borda |
| :--- | :---: | :---: | :---: | :--- | :---: | :--- |
| `{uuid}` (path) | UUID | **Sim** | — | RFC 4122 `[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}` + variante nula (validador em `chunks/[ramen_dining].[hash].js`) | Não | A validação de formato é client-side; a barreira real é a allowlist de provedores editoriais aplicada no **servidor** (§7): `Motley Fool` → **404** com a lista dos tiers aceitos, `Yahoo Finance` → **200**. A checagem antecede qualquer validação de `questionId` |
| `{questionId}` (path) | UUID | **Sim** na rota de resposta | — | idem | Não | Um `questionId` fabricado sobre artigo permitido responde **200** — a validação de conteúdo é da cadeia do artigo, não do formato do id |
| `type` (guard do cliente) | string | — | — | — | Não | O cliente só invoca com `article` e `personal-finance-article`; fora da lista, retorna `null` sem tocar a rede |

Nenhum parâmetro de query é enviado pelo cliente; a chave de serviço resolve o host. Artigo permitido sem perguntas geradas → **204 No Content** (sem corpo) nas duas rotas — a geração é assíncrona e o 204 é o estado "ainda não gerado"; o mesmo `uuid` passa a responder **200** com o catálogo completo minutos depois. **Estado em 2026-11-06:** a rota segue **viva no servidor** (revalidada: o catálogo do §5.6 respondeu 200 com os mesmos 4 `questionId`s) — mas os carregadores DDQ foram **removidos do bundle de 2026-11-05** (nenhuma menção a `articles_ddq` em `chunks/`/`nodes/`; o deep link `/__ai/scout/chat` saiu junto). É o inverso do "código fóssil" do §12.2: rota viva no wire sem cliente no bundle — o contrato continua válido para reimplementações diretas.

### 3.4 Chat aposentado e screener NLS

Família `/ws/mad/v2/chat`: `chat_version` (default `v11`), `use_fargate` (`"true"` só em ambiente interno com a flag ligada) na query, corpo `{question, symbol?, initial_context?}` — toda a família responde **410** antes de qualquer validação de parâmetro. Screener NLS: `POST` com corpo JSON (a consulta natural em `query`); a seleção da rota é condicionada às flags `enableScreenersNlsMad` (default `false` — dormente) e `enableScreenersNlsStaging`:

```js
// nodes/[research-hub].[hash].js — seleção de rota do screener NLS
function H_(r) {
  const e = Ye(r, "enableScreenersNlsStaging");
  return Ye(r, "enableScreenersNlsMad")
    ? { key: e ? "financeStage" : "financeProd",
        pathname: "/ws/mad/v2/screener/nls" }
    : { key: e ? "financeStage" : "financeProd",
        pathname: e ? "/v1/finance/screener/nls"
                    : "/ws/screeners/v1/finance/screener/nls", crumb: true };
}
```

Com a flag desligada (estado vivo), o app usa o caminho legado **com crumb**; ligada, migra para `/ws/mad/v2/screener/nls` sem crumb. No wire, as duas rotas existem no backend e exigem sessão logada (§7).

### 3.5 Temas — `/ws/mad/v2/themes` (família) e insights de portfólio

Carregadores e parâmetros:

| Carregador | Método | Path | Parâmetros |
| :--- | :--- | :--- | :--- |
| `loadThemeList` | GET | `/ws/mad/v2/themes` | `grain`, `limit`, `macro_only` ("true"), `q`, `order`, `topic_type` |
| `loadTickerList` | GET | `/ws/mad/v2/themes/tickers` | `grain`, `limit`, `q`, `topic_type` |
| `loadThemeTickers` | GET | `/ws/mad/v2/themes/{themeUuid}` | `grain`, `limit` |
| `loadTickerThemes` | GET | `/ws/mad/v2/themes/symbol/{ticker}` | `grain`, `limit`, `topic_type` |
| `loadWindowThemeGraph` | GET | `/ws/mad/v2/themes/graph` | `window`, `grain`, `limit`, `tickers_per_theme`, `topic_type` |
| `loadArticleThemeGraph` | POST | `/ws/mad/v2/themes/from-articles` | body JSON (abaixo) |
| `loadPortfolioFeed` | POST | `/ws/mad/v2/themes/portfolio/feed` | body JSON (abaixo) |
| `loadPortfolioFeed` | GET | `/ws/mad/v2/themes/portfolio/feed` | `portfolio_id`, `grain`, `limit`, `narrate` ("true"/"false"), `topic_type` |

Todos os carregadores usam `disableDefaultQueries: true` — a camada não injeta `lang`/`region`/crumb. Os paths com variável são codificados com `encodeURIComponent`. Exemplo canônico do carregador de lista:

```js
// nodes/[playground].[hash].js — loadThemeList
async function Jl(s, e) {
  const { env: t, grain: l, limit: n, macroOnly: r, q: o, order: i, topicType: a } = e;
  try {
    return await kt(s, {
      key: wt(t), pathname: $t,
      perfLabel: "loadThemeList",
      query: { grain: l, limit: n, macro_only: r ? "true" : void 0,
               q: o && o.trim() ? o.trim() : void 0, order: i,
               topic_type: Lt(a) },
      disableDefaultQueries: !0
    }) ?? null;
  } catch (f) {
    throw _t(s, e, { data: f, perfLabel: "loadThemeList" }), f;
  }
}
```

Validação do servidor (**422** FastAPI/Pydantic — valores inválidos revelam o esquema aceito; a camada de validação responde de forma independente do *handler*):

| Parâmetro | Rotas com validação | Regra server-side (mensagem 422) |
| :--- | :--- | :--- |
| `grain` | todas (query e body) | enum: `"Input should be 'storyline' or 'parent'"` — o enum tem **2** valores; um terceiro grain (`theme`) não existe no servidor |
| `order` | só `/themes` | pattern: `"String should match pattern '^(articles\|random)$'"` — `score` não é valor aceito (a página ordena por score client-side, seletor "Sort: Score*/Strength/Confidence") |
| `topic_type` | `/themes`, `/tickers`, `/symbol/{ticker}` | pattern: `"String should match pattern '(?i)^[A-Za-z]+$'"` — o servidor **não** enforceia o enum de 9 valores da página; o catálogo `EVENT/CONCEPT/CATEGORY/COMPANY/ENTITY/BRAND/PERSON/PLACE/ALL` é contrato de UI |
| `limit` | `/themes`, `/tickers`: ≤200; `/symbol/{ticker}`, `/{uuid}`: ≤100 | `ge=1` (`limit=0` → `greater_than_equal`), `int_parsing` (`limit="zz"`) |
| `macro_only` | — | aceita `false` também; o cliente só envia `"true"`, `void 0` caso contrário |
| `window` (grafo) | — | valores usados pela página: `1d`, `2d`, `5d`, `1w`, `2w` (default `1d`) |

`/{uuid}` não valida `topic_type` nem `order` — parâmetros não declarados no schema da rota são ignorados pelo gateway. Valores válidos progridem para o processamento, que responde **200** com o envelope da família (§5.7).

**Corpo de `POST /themes/from-articles`** (exige `x-txn-token`, §2.3; a validação do corpo **antecede** a checagem do token):

```js
// nodes/[playground].[hash].js — corpo do from-articles
{ method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ article_uuids: l, grain: n, topic_type: Lt(r),
                         limit: o, tickers_per_theme: i,
                         article_max_age_hours: a,
                         ticker_min_relevance: f, min_support: u }) }
```

| Campo | Conteúdo |
| :--- | :--- |
| `article_uuids` | Lista de UUIDs de artigos (mínimo 1 — **422** `too_short` em `body.article_uuids`) |
| `grain` | `storyline` \| `parent` |
| `topic_type` | Opcional; omitido quando vazio (`Lt` normaliza string vazia para `undefined`) |
| `limit`, `tickers_per_theme` | Paginação e largura do grafo |
| `article_max_age_hours` | Idade máxima dos artigos considerados |
| `ticker_min_relevance`, `min_support` | Cortes de relevância e suporte mínimo |

**Corpo e query de `/themes/portfolio/feed`** — duas variantes, com `holdings` no corpo ou com `portfolio_id` em query (defaults `grain: "parent"`, `limit: 6`, `narrate: true`; sem `x-txn-token` — payload válido alcança o handler anônimo):

```js
// nodes/[playground].[hash].js — loadPortfolioFeed (duas variantes)
async function en(s, e) {
  const { env: t, portfolioId: l, holdings: n, grain: r = "parent",
          limit: o = 6, narrate: i = !0, topicType: a } = e,
        f = Lt(a);
  try {
    return n && n.length
      ? await kt(s, { key: wt(t), pathname: `${$t}/portfolio/feed`,
                      perfLabel: "loadPortfolioFeed", disableDefaultQueries: !0 },
                 { method: "POST", headers: { "Content-Type": "application/json" },
                   body: JSON.stringify({
                     holdings: n.map((p) => ({ ticker: p.ticker, weight: p.weight })),
                     grain: r, limit: o, narrate: i,
                     ...f ? { topic_type: f } : {} }) }) ?? null
      : l ? await kt(s, { key: wt(t), pathname: `${$t}/portfolio/feed`,
                          perfLabel: "loadPortfolioFeed",
                          query: { portfolio_id: l, grain: r, limit: o,
                                   narrate: i ? "true" : "false", topic_type: f },
                          disableDefaultQueries: !0 }) ?? null
          : null;
  } catch (u) {
    throw _t(s, e, { data: u, perfLabel: "loadPortfolioFeed" }), u;
  }
}
```

**Dados de performance das posições (Top Movers da watchlist)** — `GET /ws/company-fundamentals/v11/finance/quoteSummary?formatted=true&modules=quotePerformanceOverview&symbols=…` com **crumb** (`perfLabel: "loadQuotePerformanceOverview"`) devolve `quotePerformanceOverview.performanceOverview` por símbolo (retornos de 5 dias/1 mês). **Insights de portfólio do Dig Deeper** — dispatcher distinto (`chunks/[index].[hash].js`, export `a`), sobre as chaves `financeProd`/`financeStage` e `credentials: "include"`:

```js
// chunks/[index].[hash].js — dispatcher do modo portfólio
function le(s, e) {
  return e.questionId === ft
    ? e.pfId ? Mt(s, e.pfId, { isWatchlist: e.isWatchlist }) : Ut(s)
    : Nt(s, { question: e.question, questionId: e.questionId, pfId: e.pfId });
}
```

- `questionId === "portfolio-analysis"` (constante com a pergunta pré-montada `{questionId: "portfolio-analysis", question: "Analyze my portfolio"}`): com `pfId` → `GET /v2/daily_brief/portfolio_insights/analysis` (query com `pfId`); sem `pfId` → `GET /v2/daily_brief/analysis`
- Outros `questionId` → `GET /v2/portfolio_ddq/faqs` (query `{question, questionId, pfId}`)
- Variantes de resumo: `GET /v2/daily_brief/portfolio_insights/summary`, `GET /v2/watchlist_insights/summary`, `GET /v2/watchlist_insights/analysis` (com `isWatchlist: true`) — todas com `{credentials: "include"}` e `supportsBackendParam: true`

## 4. Estrutura da Resposta

### 4.1 Envelope de sucesso

O Promenade não usa wrapper: `POST /sessions` devolve o objeto de sessão no raiz; `POST /chat` (JSON) devolve o envelope da conversa no raiz; rotas de sessão devolvem `{messages: [...]}`, `{sessions: [...], next_cursor}`, `{active: ...}`. O `/feedback` devolve o recibo no raiz.

```json
{
  "session_id": "01a0b16b-22c1-7864-90f8-02c4d6eba594",
  "title": null,
  "title_source": null,
  "pinned": false,
  "created_at": "2026-09-17T22:09:43.617Z",
  "updated_at": "2026-09-17T22:09:43.617Z"
}
```

```json
{
  "message_id": "95a83db0-cb71-43bb-bf62-1bc1560622fd",
  "content": "The Dow Jones, usually the Dow Jones Industrial Average or DJIA, is a U.S. stock market index made up of **30 large publicly traded companies**...",
  "citations": [],
  "suggestions": [],
  "follow_up_questions": [
    "How is a price-weighted index like the Dow calculated?",
    "Which companies are in the Dow Jones currently?",
    "How does the Dow differ from the S&P 500?"
  ],
  "suggested_actions": [
    {"action_id": "add-watchlist", "params": {"ticker": "DJI"}}
  ],
  "title": "Dow Jones Explanation",
  "metadata": {}
}
```

**Campos vazios são omitidos, não zerados** — `citations` e `suggestions` aparecem como vetores vazios, mas `follow_up_questions` e `suggested_actions` **não aparecem** quando não há conteúdo. Consumidores devem tratar ausência e vazio como equivalentes.

MAD: o AI Analyst devolve `{symbol_id, overview, rtr, earnings_transcripts_insights, financial_insights, holdings_insights, price_movement, options_analysis, news_summary}` no raiz; o Dig Deeper devolve `{articleId, questions}` e `{articleId, questionId, parentQuestionId, answer, followUpQuestions, sources}`; as rotas de temas devolvem o corpo do serviço.

### 4.2 Envelope de erro

O Promenade tem **três formas** de erro JSON, além de falha de borda sem corpo:

```json
{"code":"invalid_request","message":"Request validation failed: /: Expected object, received null","request_id":"24bf2312-..."}
```

```json
{"error":"missing_identity","message":"User identity required. Please log in."}
```

```json
{"error":"session_not_found","message":"Session not found"}
```

A cadeia de validação: **1)** schema do corpo (estilo Zod, JSON Pointer no `message`, `code: "invalid_request"`, sempre com `request_id`); **2)** identidade (`error: "missing_identity"`, sem `request_id`); **3)** regras de rota (idempotência, tenant, stream). A mensagem de identidade tem **duas variantes por rota**: `"User identity required. Please log in."` nas rotas de sessão/retomada (400/401) e `"User identity required."` (curta) no `/feedback` (401) — comparação exata de mensagem não é chave de rota.

MAD: os erros usam o formato FastAPI `{"detail": "..."}` — string simples (validações de negócio) ou lista de objetos Pydantic (`type`/`loc`/`msg`/`input`/`ctx` em validações de schema). O screener NLS legado usa o envelope `{"finance": {"result": null, "error": {"code": "...", "description": "..."}}}`.

### 4.3 Formatação de valores

As famílias deste documento **não aceitam `formatted`**: os valores são devolvidos como primitivos (textos Markdown, números, ISO-8601) — o realce é responsabilidade do cliente. Não há envelope `{raw, fmt}` em nenhuma rota.

### 4.4 Variantes suportadas

| Dimensão | Valores | Efeito na Resposta |
| :--- | :--- | :--- |
| `environment` (Promenade e MAD) | `prod` (default) / `nonprod` | Seleciona o serviço `scout`/`scoutDev` e `financeProd`/`financeStage` — host de desenvolvimento não resolve publicamente |
| Negociação do `/chat` | sem `Accept` especializado / `Accept: text/event-stream` | Resposta completa em JSON / streaming de eventos (§5.3) |
| `tenant` | `"finance"` | Escopo da identidade: valor desconhecido cai na barreira de identidade antes da resolução do tenant |
| `grain` (temas) | `storyline` \| `parent` | Enum server-side de 2 valores |
| `topic_type` (temas) | `EVENT`, `CONCEPT`, `CATEGORY`, `COMPANY`, `ENTITY`, `BRAND`, `PERSON`, `PLACE`, `ALL` | Enum de UI; o servidor aceita qualquer token alfabético case-insensitive |
| `order` (temas) | `articles` \| `random` | Enum server-side; ordenação por score é client-side |
| `window` (grafo de temas) | `1d`, `2d`, `5d`, `1w`, `2w` | Janela do grafo (default `1d`) |

## 5. Catálogo de Campos e Eventos

### 5.1 Objeto de sessão (`/sessions`, `/sessions/{id}`)

| Campo | Conteúdo |
| :--- | :--- |
| `session_id` | Identificador ordenado por tempo (prefixo monotônico entre sessões criadas em sequência) |
| `title` / `title_source` | Título gerado pelo servidor a partir da primeira pergunta (`"generated"`) — `null` na criação |
| `raw_title` | A pergunta original do usuário, preservada |
| `short_title` | Versão curta do título gerado |
| `pinned` | Estado de fixação; só mutável via `PATCH`, recusado para anônimo |
| `created_at` / `updated_at` | ISO-8601 com milissegundos e sufixo `Z` |

A listagem normalizada pelo parser do cliente produz `{session_id, title, isMessageLess, created_at, updatedAt}` — com `title` aparado e `isMessageLess` derivado de `title === ""`: sessões sem título **não são filtradas**. O parser descarta itens sem `session_id` e aplica `slice(0, 25)`.

### 5.2 Recibo do `/feedback`

`{"message_id", "rating", "recorded_at", "overwritten"}` — `overwritten: true` na reavaliação da mesma mensagem (trocar 👍 por 👎 sobrescreve o registro). O enum de `reason` é definido no servidor: **aceitos** `offensive`, `not_helpful`, `too_long`, `too_short`; **recusados** (entre outros): `inaccurate`, `inaccurate_or_irrelevant`, `outdated`, `irrelevant`, `harmful`, `unhelpful`, `helpful`, `misleading`, `other`, `off_topic`, `biased`, `slow`, `error`, `missing_sources`, `wrong_sources`, `spam` — o form `thumbs_down` rejeita valores fora da lista com **422** `not_accepted`. O `reason` é campo **aninhado** em `fields`: um `reason` plano no topo do corpo é ignorado pelo schema (plano → 200 silencioso; em `fields.reason` → validado). O feedback não consome quota de LLM e aceita `message_id` de qualquer conversa da própria identidade.

Distinto do `/feedback` da Promenade, `chunks/[scoutFeedback].[hash].js` declara formulários internos (host `yo`, inalcançável fora da rede Yahoo) para telemetria de satisfação via banner:

```js
// chunks/[scoutFeedback].[hash].js — formulários internos
ut = { url: "http://yo/yf-scout-feedback-form",
       fields: { answerText: "1413649535", pageUrl: "67365937",
                 prompt: "920528612", sessionId: "2100663677",
                 symbol: "1265081171" } }
ut2 = { url: "http://yo/yf-article-chat-feedback-form",
        fields: { pageUrl: "67365937", articleUuid: "1265081171", … } }
```

### 5.3 Eventos do stream (`/chat` com `Accept: text/event-stream`)

Ordem observada em uma pergunta financeira com *grounding* completo:

```
stream.start → status.update (n) → content.delta (n) → grounding.sources → follow_up.questions → actions.suggested → data → stream.end
```

| Evento | Payload (`data`) | Papel |
| :--- | :--- | :--- |
| `stream.start` | `{"message_id":"..."}` | Abre a mensagem do assistente |
| `status.update` | `{"status":"Understanding"}` | Etapas do *pipeline*; fixas iniciais: `Understanding`, `Planning`, `Retrieving`, `Generating` — seguidas de etapas dinâmicas por ativo, ex. `Pulling quarterly fundamentals for AAPL` |
| `content.delta` | `{"delta":"texto"}` | Fragmentos incrementais do Markdown final |
| `grounding.sources` | `{"grounding_sources":[{...}]}` | Fontes usadas (tabela abaixo); chega uma vez, antes das perguntas |
| `follow_up.questions` | `{"follow_up_questions":[...]}` | Perguntas de continuação (alternativa `suggestions` também tratada pelo parser) |
| `actions.suggested` | `{"actions":[{"action_id":"...","params":{...}}]}` | Ações sugeridas — o parser extrai `action_id`/`params` e descarta entradas sem `action_id` string |
| `stream.end` | `{"message_id":"...","citations":[],"suggestions":[],"metadata":{"usage":{...},"quota":{...}}}` | Fecha o stream com o balanço de uso e quota |
| `error` | `{"code":"...","message":"..."}` | Falha no meio do stream — com `code: "quota_exceeded"` e `treatQuotaExceededAsResult`, a falha vira resultado normal com `quotaExceeded: true` |
| `data` | `{"key":"data-chat-title","payload":{"title":"..."}}` | Evento genérico chave/payload; observado transportando o título gerado em perguntas curtas, entre os deltas e o `stream.end` — **no build de 2026-11-05 o evento não existe mais** (nenhuma variante de `chat-title` no bundle; o título chega pelo modo JSON/seeds e pelo `title` da sessão) |

O enquadramento é **id + data** — o tipo do evento **não** ocupa o campo SSE `event:`; ele vem **dentro** do JSON do `data`:

```
id: 1789683145569-0
data: {"event":"stream.start","data":{"message_id":"01a0b16d-994d-72ca-94aa-edb6f03cea07"}}

id: 1789683145621-0
data: {"event":"status.update","data":{"status":"Understanding"}}

id: 1789683146705-0
data: {"event":"content.delta","data":{"delta":"I"}}
```

O `id:` é um carimbo em milissegundos com sufixo de sequência (`-0`). **Resolução do discriminador (dupla via)** — o resolvedor aplica prioridade: primeiro o campo `event` dentro do JSON; na ausência, a linha `event:` do enquadramento — com exceção do valor genérico `message`, **descartado**:

```js
// chunks/[cliente-scout].[hash].js — resolvedor do discriminador de evento
const X = (e, t) => {
  const n = t === "message" ? "" : t,                         // linha event: SSE ("message" => vazio)
        r = (typeof e.event == "string" ? e.event : "") || n, // JSON primeiro, linha SSE como fallback
        s = e.data;
  return s && typeof s == "object" && !Array.isArray(s)
    ? { event: r, data: { ...s } } : { event: r, data: {} };
};
```

O enquadramento bruto só repassa objetos JSON válidos: `data` vazio ou fora de JSON é descartado; `null`/array/escalar caem em `{event, data: {}}` sem callback.

**Campos de cada fonte em `grounding.sources`** — fixados pelo parser do cliente com defaults `""`: fontes sem `title` **ou** sem `url` são descartadas; `provider` → `provider_name`, `pub_date` → `publish_time`, `url` → `cdn_url`; deduplicação por URL; o texto chega com entidades HTML (`&#39;`) sem decodificação pelo cliente:

```js
// chunks/[cliente-scout].[hash].js — parser de grounding_sources
const {
  provider: s = "",
  pub_date: i = "",
  snippet: d = "",
  summary: f = "",
  title: S = "",
  url: w = "",
  uuid: l = ""
} = r;
if (!S || !w) {
  return [];
}
```

O formato do **histórico** (`GET .../messages`) é próprio — `title/summary/url/favicon_url/site_name/reference_number` — diferente do formato do evento SSE (`provider/pub_date/snippet/summary/title/url/uuid`).

**`stream.end` — `metadata.usage` e `metadata.quota`** — `usage.calls[]` lista as chamadas de modelo do *pipeline* (modelos observados: `gpt-5.4-mini-2026-03-17` para planejamento/geração, `gpt-5.4-nano-2026-03-17` para auxiliares, `provider: "openai"`; pergunta curta sem busca executa 2 chamadas, com busca 5); `metadata.server_timing` (quando presente) detalha cada chamada com `per_call[]`, `total_server_time`, `total_wall_time`, `total_processing_time` e `source: "openai-processing-ms"`; o cliente procura `total_queue_time` nesse objeto (ausente no wire — contrato do cliente, presente na spec formal `StreamEndPayload`) e converte segundos → ms; `total_cost` existe apenas no contrato do cliente (`C(o.total_cost) ?? C(t.total_cost)`), nunca no wire. Campos da `quota`: `limit_tokens` (`100000`), `used_tokens`, `remaining_tokens`, `period_seconds` (`86400`, janela fixa de 24 h) e `reset_after_seconds` (float, tempo **restante** até a renovação) — o cliente extrai apenas os dois últimos e descarta valores não numéricos:

```js
// chunks/[cliente-scout].[hash].js — extração de quota
const t = n;
const r = C(t.remaining_tokens);
const s = C(t.reset_after_seconds);
if (r != null && s != null) {
  return {
    remainingTokens: r,
    resetAfterSeconds: s
  };
}
```

### 5.4 Catálogo de perguntas geradas (`dynamic_questions`)

```json
{
  "ts_ranked": false,
  "ts_arm_order": {},
  "dynamic_questions": [
    {
      "id": "7c298ddd-42a8-4756-b8e6-67ab73f12c58",
      "question_text": "What pressured AAPL's September-quarter gross margin outlook?",
      "entity_id": "753c0cb0-a9d9-4765-9a03-51574991381d",
      "question_type": "ticker",
      "priority": 2,
      "tags": {
        "sector": "technology",
        "sp_500": true,
        "ndx_100": true,
        "industry": "consumer-electronics",
        "signal_type": "earnings"
      },
      "additional_info": {
        "symbol": "AAPL",
        "category": "earnings",
        "seed_auth": {"base": "aIJ3MkZHdE396HVOMRlq5H8uocsDapKr/..."},
        "source_workflows": ["earnings_transcripts", "financial_insights"],
        "source_record_ids": {"earnings_transcripts": "3d97650b-c2d0-4082-9d12-915ede4a2781"},
        "seed_auth_contexts": {"ticker:AAPL": {"base": "SJrCfjFwT15ThscK+52sBSwjqzkYBci+..."}},
        "llm_refresh_interval_seconds": 604800
      },
      "created_at": "2026-09-11 06:55:43.734946+00:00",
      "expires_at": "2026-09-18 06:55:43.596603+00:00",
      "refresh_interval_seconds": 604800,
      "source": "dynamic"
    }
  ]
}
```

| Campo | Conteúdo |
| :--- | :--- |
| `id` / `entity_id` | Identificador da pergunta e do ativo (UUIDs) |
| `question_text` | A pergunta em inglês, pronta para o chat |
| `question_type` | `"ticker"` nas observações (o tipo `article` existe na montagem de contexto, §9.5) |
| `priority` | Ordenação editorial (observado 2 e 4) |
| `tags` | `sector`, `industry`, flags `sp_500`/`ndx_100`, `signal_type` (`earnings`, `news`, `insider_activity`, `analyst_ratings`, `price_movement`) |
| `additional_info.seed_auth` / `seed_auth_contexts` | Tokens de autorização da semente (base64), por base e por contexto (`ticker:AAPL`) |
| `source_workflows` / `source_record_ids` | *Workflows* geradores — os mesmos nomes das seções do AI Analyst (`earnings_transcripts`, `news_summary`, `financial_insights`) |
| `created_at` / `expires_at` / `refresh_interval_seconds` | Ciclo de vida: expiram e são regeradas (observado 604800 s = 7 dias) |
| `ts_ranked` / `ts_arm_order` | Metadados de ranqueamento por teste (Thompson sampling) |

O cliente valida apenas `Array.isArray(response.dynamic_questions)`; o consumidor da UI filtra itens com `id` e `question_text`, deduplica pelo texto e mapeia `{id, question_text}` → `{questionId, questionText}`.

### 5.5 Envelope do AI Analyst

| Campo | Tamanho | Conteúdo |
| :--- | :--- | :--- |
| `symbol_id` | — | UUID estável do ativo (`753c0cb0-a9d9-4765-9a03-51574991381d`) |
| `overview` | ~2.6 KB | Visão geral: `overview.tldr`, `overview.key_observations` (7 categorias) |
| `rtr` | ~2.7 KB | Ratings: `rtr_summary` com `tldr`, `viewpoint`, `price_target`, `ratings_summary`, `recent_upgrades`, `viewpoint_details` |
| `earnings_transcripts_insights` | ~30 KB | Transcrições: `earnings_analysis` com `tldr`, `teaser_tldr`, `key_insights`/`key_insights_structured` (12), `analyst_focus`, `qa_highlights`, `notable_quotes` (5); `fiscal_year`/`fiscal_period` |
| `financial_insights` | ~4.6 KB | Métricas: `tldr`, `categories` (`Valuation`, `Profitability`, `Growth Metrics`), `earnings_calendar` (3), `latest_earnings_metadata` (`fiscal_year`, `fiscal_period`, `period_end_date`, `earnings_disclosed_at`) |
| `holdings_insights` | ~2 KB | Insiders: `insiderActivity` com `highlights`, `key_takeaways`, `key_takeaways_structured` (5), `analysis_update_time` |
| `price_movement` | ~17 KB | Preço: `data` (beta, setor, benchmarks `SPX`/`XLK`, variações percentuais, `recent_news_articles`, `recent_analyst_upgrades_summary`), `query` original, `explanation` (`tldr`, `short_tldr`, `bottom_line`, `observations`), `show_insight` |
| `options_analysis` | ~1.5 KB | Opções: `pcr` (put/call ratio de volume e noional com `quote_date`), `key_takeaways` (`tldr`, `teaser`, `timeframe_insights`) |
| `news_summary` | ~7.8 KB | Notícias: `news_summary` (`tldr`, `summary`, `themes`, `key_events`, `dynamic_sections`), `articles_info` (10), `limit`, `min_score`, `newest_article_age_days` |

Envelope de governança comum de cada seção:

```json
{
  "trace_id": "c31c7b1d-2937-495b-9139-ca9ed8aa0112",
  "id": "c31c7b1d-2937-495b-9139-ca9ed8aa0112",
  "symbol_id": "753c0cb0-a9d9-4765-9a03-51574991381d",
  "created_at": "2026-09-17T20:15:45.413090+00:00",
  "updated_at": "2026-09-17T20:15:45.413090+00:00",
  "debug": {},
  "dynamic_questions": []
}
```

As seções são geradas por *workflows* independentes — os `created_at`/`updated_at` divergem entre si. O conteúdo textual chega em **Markdown**. O cliente mapeia os nomes do servidor para os nomes da UI:

```js
// chunks/[loadTickerAnalysisForSymbol].[hash].js — mapeamento server → UI
return {
  analystRatings: A == null ? undefined : A.rtr,
  earningsCallInsights: A == null ? undefined : A.earnings_transcripts_insights,
  earningsInsights: A == null ? undefined : A.financial_insights,
  insiderActivity: A == null ? undefined : A.holdings_insights,
  newsSummary: A == null ? undefined : A.news_summary,
  optionsAnalysis: A == null ? undefined : A.options_analysis,
  overview: A == null ? undefined : A.overview,
  priceMovement: A == null ? undefined : A.price_movement,
  symbol: R
};
```

### 5.6 Envelope do Dig Deeper

Catálogo (`/questions`) — captura real:

```json
{
  "articleId": "7ca8986b-1a73-44e9-859e-994b3c8cb976",
  "questions": [
    {"questionId": "1146b822-5cde-4e7c-9744-e0a22e580774",
     "question": "How much does private mortgage insurance typically cost?"},
    {"questionId": "14f4fad1-0991-486c-9121-dd6ae7ae09d2",
     "question": "What existing methods allow homeowners to drop mortgage insurance?"},
    {"questionId": "4e7af4bf-db07-495d-863b-e3f00f9209ba",
     "question": "What is the mortgage insurance policy change Pulte announced?"},
    {"questionId": "f7e8a615-31c4-46e3-9c22-06978232f068",
     "question": "How did mortgage insurance stocks react to this announcement?"}
  ]
}
```

Resposta (`/questions/{questionId}`) — captura real:

```json
{
  "articleId": "7ca8986b-1a73-44e9-859e-994b3c8cb976",
  "questionId": "4e7af4bf-db07-495d-863b-e3f00f9209ba",
  "parentQuestionId": "",
  "answer": "The Federal Housing Finance Agency's Bill Pulte announced a policy change aligning Fannie Mae and Freddie Mac rules to allow loan servicers to **proactively contact borrowers** when they're eligible to drop private mortgage insurance (PMI) [1].\\n\\n**Key Details:**\\n* Previously, only Freddie Mac ([FMCC](asset://quote/FMCC)) allowed servicers to proactively call borrowers about PMI eligibility\\n* Fannie Mae ([FNMA](asset://quote/FNMA)) required borrowers to initiate contact themselves\\n* The change allows servicers to notify homeowners when their home value has increased enough to qualify for PMI removal\\n\\nThis addresses a \"hidden cost\" issue where borrowers continued paying unnecessary PMI simply because they didn't know they qualified to drop it [1]. ...",
  "followUpQuestions": [
    {"questionId": "c665b94f-0179-4d36-b46b-d861621b5dc5",
     "question": "How much money could homeowners save by dropping PMI when eligible?"},
    {"questionId": "538d6255-fbd5-4dcf-b3e0-d00b80088c3e",
     "question": "What are the current requirements for removing private mortgage insurance?"},
    {"questionId": "bdffa3cd-6b8a-461a-8c19-15e336d7bcfc",
     "question": "How did mortgage insurance company stocks react to this announcement?"}
  ],
  "sources": ["bd64332e-d310-4d50-a024-8974a6c951d5"]
}
```

| Campo | Conteúdo |
| :--- | :--- |
| `articleId` | UUID do artigo (eco do path) |
| `questionId` | UUID da pergunta respondida |
| `parentQuestionId` | UUID da pergunta-pai na cadeia; string vazia nas perguntas de raiz |
| `answer` | Markdown com citações `[N]` e links `[TICKER](asset://quote/TICKER)` — e com **`\n` literais** (sequência de 2 caracteres, não newline real): o sanitizador `C()` do cliente os converte antes da renderização |
| `followUpQuestions` | Próximas perguntas da cadeia (mesmo formato do catálogo) |
| `sources` | UUIDs de ativos/notícias citados, na ordem das citações |

As `followUpQuestions` alimentam a cadeia navegável: cada `questionId` filho volta como nova pergunta da rota de resposta, e `parentQuestionId` liga o filho ao pai. `questions[].question` e os textos do catálogo são sanitizados com DOMPurify (`{KEEP_CONTENT: !0, RETURN_DOM: !1}`).

**Modo portfólio — normalização no cliente.** Os mesmos carregadores normalizam as respostas da família de insights (§3.5) para o envelope de pergunta/resposta acima, com `source: "llm"`:

| Resposta do servidor | Forma bruta | Envelope montado |
| :--- | :--- | :--- |
| `/v2/daily_brief/portfolio_insights/analysis` | `{hook_text, main_points: [{title, description}], watch_section: [], suggested_questions: []}` | `answer` montado com `**KEY UPDATES:**` (main points) e `**WHAT TO WATCH:**`; follow-ups com `questionId: "portfolio-followup-{i}"` |
| `/v2/portfolio_ddq/faqs` | `{faqs: [{answer}], suggested_questions: []}` | `answer` = `faqs[0].answer`; `parentQuestionId: "portfolio-analysis"`; follow-ups `{id}-followup-{i}` |
| `…/summary` (resumo) | `{summary, timestamp, portfolio: [], glance_insights: []}` | `{summaryInsight, timestamp, topPerformingTickers, glanceInsights}` — sem passar pelo envelope |

O sanitizador do `answer` também: converte os `\n` literais em newline, reescreve marcadores `*` em `•`, desfaz `**negrito**`/`*itálico*`, remove citações `[N],?` e colapsa espaços. Os links `[TICKER](asset://quote/TICKER)` são reescritos para URL absoluta do quote e os **tickers das holdings do portfólio são injetados como lista linkada** dentro dos parênteses do texto (`A(t, portfolio_tickers)`); URLs das fontes saem de `clickThroughUrl`/`providerContentUrl` com guarda https.

### 5.7 Catálogos de temas do bundle

**Catálogo estático dos 18 temas primários (cartões de navegação)** — os mesmos slugs usados como `topic` na navegação:

| slug | label | slug | label |
| :--- | :--- | :--- | :--- |
| `magnificent-7` | Magnificent 7 | `housing-market` | Housing Market |
| `tech` | Tech | `clean-energy` | Clean Energy |
| `crypto` | Crypto | `pharma-biotech` | Pharma & Biotech |
| `earnings` | Earnings | `enterprise-cloud` | Cloud & Enterprise |
| `economy` | Economy | `aerospace-defense` | Aerospace & Defense |
| `tariffs` | Tariffs | `stock-market-news` | Stock Market News |
| `oil-gas` | Oil & Gas | `futures-derivatives` | Futures & Derivatives |
| — | — | `cybersecurity` | Cybersecurity |
| — | — | `private-markets` | Private Markets |
| — | — | `travel` | Travel |
| — | — | `gambling` | Gambling |

Uma segunda tabela no chunk compartilhado `shopping_cart` mapeia classificações hierárquicas de artigos para slugs deste catálogo (`energy/oil-gas` → `oil-gas`, `technology/cybersecurity` → `cybersecurity`, ...).

**Catálogo canônico com UUIDs** (chunk `chunks/[catalogo-temas].[hash].js`) — associa cada slug a um **UUID canônico de tema** (chave usada em `theme_uuid` nas respostas), `batch` (gate de rollout: `enableAICuratedTopicsBatch1/2/3`), `legacyFallback` e metadados editoriais (`title`, `summary`, `ranking`). Perfis de ranking: `["relevance", "timeliness", "popularity", "balanced"]`. O catálogo tem **26 entradas** — os 18 slugs de navegação exceto `tech` e `housing-market` (sem UUID no objeto), mais 10 temas fora da navegação primária:

| slug | UUID canônico | batch | legacyFallback | title |
| :--- | :--- | :--- | :--- | :--- |
| `stock-market-news` | `b91043d9-16e2-3ed5-8afa-be244a57c20d` | 3 | sim | — |
| `crypto` | `db6571f9-2013-3f3f-b9bc-39f892dc9cfa` | 3 | sim | — |
| `earnings` | `17c8a063-8837-36a2-a356-e89dca993f8c` | 3 | sim | — |
| `tariffs` | `88cded20-a578-5211-bd82-ee150587bfbd` | 1 | não | — |
| `economy` | `ebfd068b-f287-3ff0-9857-bf6604bf0bf2` | 1 | não | — |
| `magnificent-7` | `43bef97d-c79c-3863-b885-2dc01d785047` | 1 | não | Magnificent 7 Stocks |
| `gambling` | `6f31b595-f8ff-3c3a-851e-cb6c2b6c0e92` | 2 | — | Gambling & Sports Betting |
| `travel` | `584e2ced-e2e1-3855-be04-47a39e1034b6` | 2 | — | Travel Stocks & Industry News |
| `oil-gas` | `1aa6cefd-078b-35d5-9b45-f671cbab0127` | 2 | sim | Oil & Gas |
| `futures-derivatives` | `94a4de58-eff1-359b-a949-8056ea6ea17f` | 3 | sim | Futures & Derivatives |
| `pharma-biotech` | `fcbb90b5-370f-32ab-b154-3905a8b6fd94` | 3 | sim | Pharma & Biotech |
| `enterprise-cloud` | `979e3baf-ef7d-3e04-a69d-825499e95b55` | 2 | — | Cloud & Enterprise Software |
| `aerospace-defense` | `ce844811-ca4c-3a30-b4b6-2e1b2bb865e4` | 2 | sim | Aerospace & Defense |
| `clean-energy` | `de52d180-2294-3891-81ca-a5d07620af05` | 3 | sim | Clean Energy & Climate |
| `cybersecurity` | `936fd2eb-9161-3d02-86ec-3dc63d50a9e4` | 3 | sim | — |
| `private-markets` | `ea0dbe5c-87a8-3479-97ab-e0bea85d58e4` | 2 | sim | Private Markets & Alternative Investments |
| `gaming` | `62e80c3b-30fb-31ad-8d12-426a9838a77a` | 3 | sim | Gaming & Esports |
| `strait-of-hormuz` | `17730d5f-f29f-32a3-96d4-1778d6521b94` | 2 | sim | Strait of Hormuz |
| `career` | `8319a740-358e-30a6-a9b3-568bb4ba3e47` | 3 | sim | Career |
| `luxury` | `12f3df20-352f-3d2b-98cb-7e735d942948` | 3 | sim | Luxury |
| `collectibles` | `b5dc2509-5164-3bd1-8da1-7cb76ba5cef5` | 3 | sim | Collectibles |
| `healthcare-insurance` | `e2af0f9c-6402-3f8e-97ba-b9a60e6aca5b` | 3 | sim | Healthcare & Insurance |
| `supply-chain-industrials` | `a460fc6b-3b9c-36b0-82c9-8454263b6c76` | 3 | sim | Supply Chain & Industrials |
| `social-media` | `9b4967d2-bb59-35ff-8cc0-615b5ef9616e` | 3 | sim | Social Media |
| `streaming-media` | `5ce1bf56-9dad-3e30-9592-82b91149184b` | 3 | sim | Streaming & Media |
| `financial-services` | `0745c292-ddd2-322f-8ab2-ffbfc09b7e63` | 3 | sim | — |

Sete entradas não têm `title` no bundle (`stock-market-news`, `crypto`, `earnings`, `tariffs`, `economy`, `cybersecurity`, `financial-services`) — o título visível vem do slug/label da navegação. Cuidado de extração: entradas curtas sem `title`/`summary` fazem janelas de regex sangrarem para o entry seguinte — a extração correta corta a janela no início do próximo `slug:{uuid:`. Os `summary` editoriais existem para 17 entradas (ex.: `oil-gas` — "Coverage of crude oil, natural gas, and the energy companies that produce and refine them."). `magnificent-7` é a única entrada com CTA dedicado: `dataCardCta: {type: "alphaSpaceCTA", filled: true, label: "Go Deeper with AlphaSpace", view: "mag-7", ncid: "100003572"}`, `dataCardTickers: [AAPL, MSFT, NVDA, GOOGL, AMZN, META, TSLA]` e `tickerCountOverride: 7`. A navegação `/markets/topic/{slug}` redireciona `crypto` → `/markets/crypto` e `housing-market` → `/real-estate/` (301 client-side, condicionados a feature flags).

**Envelope das rotas vivas (grain=parent)** — a lista devolve metadados agregados por tema; o detalhe por UUID devolve os tickers ranqueados com os artigos de suporte; o grafo abre com os contadores do recorte de artigos:

```json
{
  "grain": "parent",
  "count": 3,
  "total": 33,
  "themes": [
    {
      "theme_uuid": "43bef97d-c79c-3863-b885-2dc01d785047",
      "theme_label": "Magnificent 7",
      "grain": "parent",
      "macro_slug": "magnificent-7",
      "tickers": 181,
      "signal": 1196.5991,
      "theme_articles": 1524
    }
  ]
}
```

| Campo | Conteúdo |
| :--- | :--- |
| `total` / `count` | Total de temas do recorte e itens da página |
| `theme_uuid` / `macro_slug` | UUID canônico e slug de navegação — os dois identificadores convergem com o catálogo do bundle |
| `theme_label` | Rótulo do servidor (próprio — não copia o `title` do objeto curado do bundle) |
| `tickers` / `signal` / `theme_articles` | Contagem de tickers cobertos, sinal agregado e volume de artigos |

Detalhe por UUID (`GET /themes/{theme_uuid}`) — header do tema + `tickers[]`:

```json
{
  "theme_uuid": "43bef97d-c79c-3863-b885-2dc01d785047",
  "theme_label": "Magnificent 7",
  "grain": "parent",
  "macro_slug": "magnificent-7",
  "count": 5,
  "tickers": [
    {
      "ticker": "TSLA",
      "symbol_id": "5cb6c374-4010-4496-98fb-c4c1bfe52b5c",
      "mean_strength": 0.698492,
      "confidence": 0.9873,
      "score": 0.68965,
      "support": 156,
      "share": 0.211662,
      "rank": 1,
      "supporting_articles": [
        {"uuid": "443fed3f-ba2d-33c2-af3e-3afa1df9a5a5",
         "title": "Tesla Faces Q3 Delivery Test — JPMorgan Cuts Forecast...",
         "url": "https://..."}
      ]
    }
  ]
}
```

Sobrecarga de tipo em `tickers`: na lista (`/themes`) é **inteiro** (contagem); no detalhe (`/{themeUuid}`) é **array** de objetos — parsear pelo path, não pelo nome. O grafo (`GET /themes/graph`) abre com os contadores do recorte:

```json
{
  "grain": "parent",
  "topic_type": "ALL",
  "requested_articles": 743,
  "used_articles": 743,
  "articles_with_topics": 707,
  "articles_with_tickers": 743,
  "article_max_age_hours": null,
  "articles_filtered_by_recency": 0,
  "articles_skipped_invalid_display_time": 0,
  "count": 3
}
```

O feed de portfólio (`POST /themes/portfolio/feed` com `holdings`) devolve a narração e a exposição por tema — sem gate de `x-txn-token`:

```json
{
  "portfolio_id": null,
  "portfolio_name": "Custom portfolio",
  "grain": "parent",
  "holdings": 2,
  "pnl_today": 0.0,
  "summary": "Your portfolio tilts heavily toward the Magnificent 7...",
  "count": 6,
  "themes": [
    {
      "theme_uuid": "43bef97d-c79c-3863-b885-2dc01d785047",
      "theme_label": "Magnificent 7",
      "macro_slug": "magnificent-7",
      "exposure": 0.576517,
      "share": 0.21323,
      "pnl_today": 0.0,
      "rank": 1,
      "tickers": ["AAPL", "NVDA"],
      "articles": [{"uuid": "...", "title": "...", "url": "..."}]
    }
  ]
}
```

Com `portfolio_id` (GET), o mesmo envelope com `portfolio_id`/`portfolio_name` preenchidos — ids de carteira demo do Playground resolvem no servidor (`demo-megacap-tech` → `"Mega-cap Tech"`, 7 holdings); id desconhecido → **404** de posse (§7); sem `portfolio_id` → **422** `Field required`.

### 5.8 Catálogo de perguntas do painel vazio (Dock)

O Dock sorteia as sugestões do painel vazio em duas camadas: a **página** (`pageType`) escolhe o conjunto de headings e prompts, e — na página de cotação — o **tipo do ativo** (`quoteType`) escolhe o conjunto final. O token `{symbol}` é substituído pelo ticker de contexto; em opções é usado o subjacente:

```js
// chunks/[Dock].[hash].js — resolvedor por quoteType
const Zh = ({ symbol: o, quoteType: e, underlyingSymbol: t }) => {
  const n = e === "OPTION" && t ? t : o;
  if (n) return { headings: Af, prompts: e && jh[e] || Gh, tokens: { [Ie]: n } };
};
```

```js
// chunks/[Dock].[hash].js — resolvedor por página
const xh = {
  quote: Zh,
  "stock-picks": Jh,
  article: ({ isAiEligible: o }) => o ? { headings: Ph, prompts: Kh } : void 0,
  portfolios: ({ hasSeparatedWatchlists: o, isSignedIn: e }) =>
    e ? { headings: $s, prompts: o ? $h : Qh } : void 0,
  watchlists: ({ isSignedIn: o }) => o ? { headings: $s, prompts: Yh } : void 0
};
```

| Contexto | Prompts | Exemplo (`lead` / `detail`) |
| :--- | :---: | :--- |
| `EQUITY` | 22 | `Weigh {symbol}` / `against the S&P 500` |
| `INDEX` / `CUL_IDX` / `CUL_SUB_IDX` | 10 | `Name the index movers` / `lifting and dragging it` |
| `ETF` / `MUTUALFUND` | 11 | `Price {symbol} to own` / `fees and all` |
| `CRYPTOCURRENCY` | 8 | `Link macro trends` / `to {symbol}'s moves` |
| `CURRENCY` | 8 | `Tie rates to the pair` / `and where they point` |
| `FUTURE` | 7 | `Compare this contract` / `against nearby expirations` |
| `PRIVATE_COMPANY` | 8 | `Unpack the last round` / `and what it valued` |
| `quoteType` sem conjunto | 5 | `Break down {symbol}` / `and why it's moving` |
| Página de mercado (fallback) | 9 | `Show me today's movers` / `biggest gainers, losers` |
| `article` (`isAiEligible`) | 6 | `Sum up this article` / `in plain terms` |
| `portfolios` com watchlists separadas | 6 | `Check what's driving` / `my portfolio today, and why` |
| `portfolios` sem separação | 5 | `Find the biggest themes` / `across this list` |
| `watchlists` | 6 | `Scan my watchlist` / `and how it's doing today` |
| `stock-picks` | 5 | `Rank the catalysts` / `coming for this list` |

A exibição sorteia 1 heading e 3 prompts (`Rh = 3`) por Fisher–Yates a cada abertura do painel. Os headings seguem o mesmo padrão por contexto — mercado (7, ex. `"What's happening in the markets?"`), ativo (5, ex. `"Anything you want to know about {symbol}?"`) e artigo (5, ex. `"Want to go deeper on this?"`).

### 5.9 Modelos de IA do pipeline

Os modelos executam **integralmente server-side** — o bundle não contém nenhum runtime de modelo; o que chega ao cliente é apenas a contabilidade de tokens no `stream.end` (§5.3). Os identificadores são observados em `metadata.usage.model` (modelo top-level da resposta) e `metadata.usage.calls[]` (cada chamada do *pipeline* com `model`/`provider` próprios):

| Modelo | Papel observado | Evidência |
| :--- | :--- | :--- |
| `gpt-5.4-mini-2026-03-17` | Planejamento e geração das respostas com *grounding* — as chamadas de maior volume (`input_tokens` ~3.8k–14k, com `cache_read_tokens` expressivo) | `usage.calls[]`: 3 das 5 chamadas de uma pergunta com busca |
| `gpt-5.4-nano-2026-03-17` | Chamadas auxiliares do *pipeline* (classificação, etapas dinâmicas, títulos) e modelo top-level de respostas curtas | `usage.model` top-level; 2 das 5 chamadas de uma pergunta com busca; as 2 chamadas de uma pergunta sem busca |
| `provider: "openai"` | Provedor executante de todas as chamadas observadas | `usage.provider`, `usage.calls[].provider` e `server_timing.per_call[].source: "openai-processing-ms"` |

Contabilidade por chamada — campos observados no wire: `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_creation_tokens`, `embedding_tokens` (`0` nas observações) e `total_tokens` no agregado. Nenhuma pergunta observada executou chamada com `embedding_tokens > 0` — o *grounding* de notícias não usa embeddings no caminho do chat. Amostra real (pergunta com grounding, captura integral em §11.6): 3 chamadas `mini` + 2 `nano`, `total_tokens: 39791`, `cache_read_tokens: 25728` — o pipeline é intensivo em cache de prompt. Pergunta curta sem busca executa **2** chamadas; com busca, **5**. Verificação ao vivo independente: resposta de pergunta educacional reportou `total_tokens: 33588`, `model: gpt-5.4-nano-2026-03-17`, 5 chamadas e quota de `100000` tokens/24 h.

Custo e fila são **contrato do cliente, não do wire**: o cliente extrai `total_cost` (normalizado para `totalCostUsd`) e `total_queue_time` (convertido de segundos para ms) — nenhum dos dois foi observado no `stream.end` real; ambos constam na spec formal `StreamEndPayload`. O cliente também tolera o modo JSON: no fallback de histórico, o `usage` é lido da última mensagem `assistant` (`messages[].usage`) quando o `metadata` do envelope vem vazio.

```js
// chunks/[cliente-scout].[hash].js — extração de uso (custo em USD + fila)
function f24(vP51) {
  const { metadata: r } = vP51;
  if (r && typeof r == "object") {
    const vF202 = f20(r.usage);
    const vF19 = f19(r.server_timing);
    if (vF19 != null && vF202.totalQueueTime == null) {
      vF202.totalQueueTime = vF19;          // server_timing.total_queue_time (s → ms)
    }
    if (vF202.totalTokens != null || vF202.totalCostUsd != null || vF202.totalQueueTime != null) {
      return vF202;                          // totalCostUsd ← usage.total_cost
    }
  }
  // fallback do modo JSON: última mensagem assistant carrega usage próprio
  const { messages: o } = vP51;
  for (let v39 = (o || []).length - 1; v39 >= 0; v39--) {
    if (o[v39] && o[v39].role === "assistant") {
      const vF203 = f20(o[v39].usage);
      if (vF203.totalTokens != null || vF203.totalCostUsd != null) return vF203;
    }
  }
  return {};
}
```

Superfícies consumidoras de LLM (todas server-side, cada uma com *workflow* próprio — `trace_id`/`created_at` no MAD, `langfuseTracingUrl` no Playground):

| Superfície | Uso de modelo | Evidência |
| :--- | :--- | :--- |
| Chat Scout (`/chat`, `/chat/seeds`) | Pipeline de planejamento → busca → geração; títulos de sessão via evento `data-chat-title` | `usage.calls[]` do `stream.end` |
| Perguntas sugeridas (`dynamic_questions`) | Geração/regeneração periódica por *workflow* (`llm_refresh_interval_seconds: 604800`) com tokens de autorização por contexto | `source_workflows`/`seed_auth` do catálogo (§5.4) |
| AI Analyst (8 seções) | Geração assíncrona por *workflow* independente — os `created_at` divergem entre seções | envelope de governança (§5.5) |
| Dig Deeper | Geração assíncrona do catálogo e das respostas (o **204** é o estado "ainda não gerado") | §3.3 |
| Temas e feed de portfólio | Rótulos (`theme_label`) e narração (`summary` com `narrate: true`) gerados pelo serviço | §5.7 |
| Screener NLS | Tradução de consulta em linguagem natural para o screener (rota dormente) | §3.4 |
| Insights de portfólio (`daily_brief`/`portfolio_ddq`/`watchlist_insights`) | Geração sob identidade logada (gate JWT) | §3.5 |

Regra de parsing para reimplementações: os identificadores de modelo **não são contrato estável** — chegam como observação no `stream.end` e podem mudar sem aviso de versão; consumidores não devem chavear comportamento no nome do modelo, apenas agregá-lo para telemetria.

**Quem escolhe o modelo — ninguém no cliente.** O corpo do `/chat` não tem nenhum parâmetro de seleção de modelo (grep integral do cliente: `model` aparece apenas na extração de `usage`). A escolha é server-side, por etapa do *pipeline*; o campo `variant` do corpo é rótulo de experimento A/B (a telemetria do cliente o reporta como `tenant_variant`, default `"base"`), não seletor de modelo. O campo top-level `usage.model` variou entre capturas — `gpt-5.4-nano` em respostas com grounding, `gpt-5.4-mini` na recusa de escopo — sem que a forma da resposta mudasse: a semântica exata do top-level não é determinável pelo wire; o arranjo real do pipeline está em `calls[]`.

**Quota — por identidade, não por sessão.** O par `A3` carrega a janela de `period_seconds: 86400` compartilhada por **todas as sessões daquela identidade**: sessões múltiplas no mesmo jar consomem o mesmo balanço, e um novo bootstrap (`/renovar`, jar limpo) começa com `limit_tokens` cheio. O cliente só bloqueia no esgotamento — o gate client-side é `remainingTokens <= 0`, sem aviso anterior:

```js
// chunks/[cliente-scout].[hash].js — gate de quota do cliente
return !!p34 && p34.remainingTokens <= 0;
```

Custo por turno (observado ao vivo, identidade anônima): recusa de escopo ≈ **4.230 tokens** (2 chamadas); pergunta educacional com grounding ≈ **33–40 mil** (5 chamadas); pergunta de análise com grounding ≈ **52 mil** — a quota de 100.000 tokens da identidade anônima cobre **2–4 turnos com grounding**, não a sessão inteira. Consumidores devem exibir o balanço após cada turno e tratar `429`/`remainingTokens <= 0` como sinal de re-bootstrap.

## 6. Matrizes de presença

Legenda: `✅` = presente/observado para a variante; `—` = ausente/não observado (único uso permitido de `✅` e `—` nas regras de estilo).

### 6.1 Eventos SSE por tipo de pergunta

| Evento | Pergunta curta (sem busca) | Pergunta com grounding | Recusa de escopo |
| :--- | :---: | :---: | :---: |
| `stream.start` | ✅ | ✅ | ✅ |
| `status.update` (fixas) | ✅ | ✅ | ✅ |
| `status.update` (dinâmicas por ativo) | — | ✅ | — |
| `content.delta` | ✅ | ✅ | ✅ |
| `grounding.sources` | — | ✅ | — |
| `follow_up.questions` | — | ✅ | — |
| `actions.suggested` | — | ✅ | — |
| `data` (`data-chat-title`) | ✅ | — | — |
| `stream.end` (com `usage`/`quota`) | ✅ | ✅ | ✅ |

### 6.2 Seções do AI Analyst — `dynamic_questions` e dados

| Seção | `dynamic_questions` populadas | Objeto esquelético possível |
| :--- | :---: | :---: |
| `overview` | ✅ | — |
| `rtr` | ✅ | — |
| `earnings_transcripts_insights` | — | — |
| `financial_insights` | ✅ | — |
| `holdings_insights` | — | ✅ |
| `price_movement` | — | — |
| `options_analysis` | — | ✅ (`{"options_data": {}, "options_window_data": {}}`) |
| `news_summary` | ✅ | — |

Allowlist do cliente do AI Analyst (união validada por `EA = (C) => q.includes(C)`):

| Lista | Tamanho observado | Papel |
| :--- | :--- | :--- |
| 1ª | 6 | Cobertura premier: `F`, `HOOD`, `META`, `NVDA`, `SNAP`, `UBER` |
| 2ª | ~90 | Large caps (`AAPL`, `AMZN`, `GOOGL`, `MSFT`, `NVDA`, `TSLA`, ...) |
| 3ª | ~130 | Mid caps e tópicos de destaque (`PLTR`, `SOFI`, `RIVN`, `COIN`, ...) |
| 4ª | ~400 | Cobertura ampla S&P (`A`, `ABT`, `ACN`, ..., `ZTS`) |
| 5ª | ~180 | Small caps e recentes (`ACHR`, `BMNR`, `CRCL`, `IONQ`, `LUNR`, `SMR`, ...) |

### 6.3 Categorias de insight por ticker (`TickerAIInsight`)

| Categoria | Pergunta i18n |
| :--- | :--- |
| `earnings-call-insights` | `WHAT_WERE_TAKEAWAYS_FROM_TICKERS_EARNINGS_CALL` |
| `earnings-insights` | `WHAT_DO_TICKERS_FINANCIALS_AND_KEY_STATISTICS_REVEAL` |
| `insider-activity` | `WHAT_ARE_RECENT_INSIDER_TRANSACTIONS_FOR_TICKER` |
| `news-summary` | `WHATS_HAPPENING_WITH_TICKER_TODAY` |
| `price-movement` | `WHY_IS_TICKER_MOVING` |

Os títulos das seções por categoria vêm do registro exportado por `chunks/[room_service].[hash].js` (`newsSummary` → `NEWS_HEADLINES`, `insiderActivity` → `RECENT_TRANSACTIONS`, `earningsInsights` → `FINANCIALS`, `earningsCallInsights` → `EARNINGS_CALLS_SUMMARY`, `priceMovement` → `WHY_IS_TICKER_MOVING`); a mesma chave `WHATS_HAPPENING_WITH_TICKER_TODAY` é reusada pelo `AiAnalystHybridBanner`. As categorias também estão registradas em `chunks/[configs].[hash].js` (registro central). O CTA embutido aparece quando a categoria está definida e não é `summary`, com atribuição `POWERED_BY YAHOO_SCOUT`.

---

## 7. Erros e códigos de status

| HTTP | Forma do corpo | `code` / `detail` | Causa e rota |
| :---: | :--- | :--- | :--- |
| `400` | `{"code":"invalid_request","message":"Request validation failed: /<ponteiro>: <motivo>","request_id":"..."}` | `invalid_request` | Schema do corpo (estilo Zod, JSON Pointer): corpo ausente (`/: Expected object, received null`), `tenant` ausente (`/tenant: Required`), `message` vazia (`/message: Message cannot be empty`), `idempotency_key` não-UUID (`/idempotency_key: Invalid uuid`), `last_event_id` ausente (`/last_event_id: Required`). Sempre com `request_id`; roda **antes** da checagem de identidade. Promenade |
| `400` | `{"error":"missing_identity","message":"User identity required. Please log in."}` | `missing_identity` | Sem cookie de identidade — `/sessions`, rotas de sessão, retomada **e o `/chat` com corpo válido** (revalidado 2026-11-06, com e sem `X-Sas-Enforce-Quota: 1`). Variante **curta** (`"User identity required."`) no `/feedback` com **401**. Nas capturas de set/out-2026 o `/chat` sem cookie caía no regime de quota (`429`) — a precedência identidade×quota não é estável entre deploys; consumidores devem tratar os dois como "refazer bootstrap" |
| `400` | `{"detail": "One parameter required"}` | FastAPI | `/ws/mad/v2/analyst/ect` sem `transcript_id`/`event_id` |
| `400` | `{"detail": "Only one parameter allowed: ['transcript_id', 'event_id']"}` | FastAPI | ECT com os dois identificadores — exclusão mútua aplicada no servidor |
| `400` | `{"message":"xhr.dynamic-seeded-questions: missing symbol"}` | proxy | `/xhr/dynamic-seeded-questions` sem `symbol` |
| `400` | `{"message":"Schema mismatch for /xhr/config"}` / `GET method not allowed` (`405`) | proxy | `/xhr/config?name=services` fora do uso interno do loader |
| `400` | `{"detail": "portfolio_id or holdings required"}` | FastAPI | `POST /themes/portfolio/feed` com corpo vazio |
| `401` | `{"detail": "Missing x-txn-token header"}` | FastAPI | `from-articles` sem o header JWT |
| `401` | `{"detail": "Authentication required. Missing or empty x-txn-token header."}` | FastAPI | `/v2/daily_brief/*`, `/v2/portfolio_ddq/faqs`, `/v2/watchlist_insights/*` anônimos |
| `401` | `{"detail": "Token verification failed: Invalid token format: Not enough segments"}` | FastAPI | Header presente, token fora do formato JWT |
| `401` | `{"detail": "Token verification failed: Unexpected error during token verification: The specified key is an asymmetric key or x509 certificate…"}` | FastAPI | JWT de três segmentos com assinatura inválida — validação com **chave assimétrica** (família RS/EC/x509), não HMAC |
| `401` | `{"finance": {"error": {"code": 401, "description": "UNAUTHORIZED"}}}` | envelope `finance` | `POST /ws/mad/v2/screener/nls` anônimo (rota MAD v2) |
| `401` | `{"finance": {"result": null, "error": {"code": "lambda-error", "description": "User is not logged in"}}}` | envelope `finance` | `POST /ws/screeners/v1/finance/screener/nls?crumb=…` anônimo (rota legada) |
| `403` | `{"error":"forbidden","message":"Anonymous sessions cannot be updated"}` | `forbidden` | `PATCH /sessions/{id}` com `A3` anônimo — escrita de estado exige identidade logada |
| `403` | `{"error":"forbidden","message":"Anonymous sessions cannot be deleted"}` | `forbidden` | `POST /sessions/{id}/delete` anônimo — a sessão continua acessível após a recusa |
| `403` | Página HTML `Access Denied` da borda ATS | — | `DELETE /sessions/{id}` — método bloqueado no gateway |
| `404` | `{"error":"session_not_found","message":"Session not found"}` | `session_not_found` | Sessão inexistente nas rotas de leitura — shape distinto do `not_found` genérico, sem `request_id`; o parâmetro de **path** não passa pela validação de schema (`GET /sessions/zzz/messages` → mesmo 404) |
| `404` | `{"error":"stream_not_found","message":"Stream not found or expired"}` | `stream_not_found` | `/chat/resume/{stream_id}` inexistente/expirado (sob tráfego acumulado, a borda devolve o 404 com corpo vazio) |
| `404` | `{"code":"not_found","message":"Not found.","request_id":"..."}` | `not_found` | Método errado (`GET /chat`) e rota inexistente — não há 405; ambos se confundem no mesmo 404 |
| `404` | `{"detail": "Symbol not found for ZZZZZZ"}` | FastAPI | AI Analyst com símbolo inexistente |
| `404` | `{"detail": "No transcript insights found for transcript_id 99999999"}` | FastAPI | ECT com identificador sem insights |
| `404` | `{"detail": "Article skipped: Skipped: provider 'Motley Fool' not in allowed tiers (Yahoo Finance, Yahoo Personal Finance, Tier 1, or Tier 2)"}` | FastAPI | Dig Deeper — artigo de provedor fora da allowlist editorial (a checagem antecede a validação de `questionId`) |
| `404` | `{"detail": "unknown portfolio_id: 'abc123' (no holdings supplied)"}` | FastAPI | `GET /themes/portfolio/feed` com `portfolio_id` inexistente — a posse é validada contra a identidade da requisição |
| `406` | `{"error":"not_acceptable","message":"Accept: text/event-stream header is required"}` | `not_acceptable` | `/chat/resume` sem `Accept: text/event-stream` — header **obrigatório** nesta rota |
| `409` | `{"error":"duplicate_request","message":"A request with this idempotency_key was already processed","session_id":"...","user_message_id":"...","message_id":"..."}` | `duplicate_request` | `POST /chat` repetido com a mesma `idempotency_key` — o `session_id` devolvido é o da **primeira** execução; o cliente distingue pelo par status 409 + `error` e converte em exceção dedicada |
| `410` | `{"detail": "The chat API has been retired."}` | FastAPI | Toda a família `/ws/mad/v2/chat` (POST, POST/{sessionId}, GET, GET `question/{uuid}`, `rate_limit`) — idêntico anônimo e com `A3`, com e sem `chat_version`; a aposentadoria é anterior a qualquer validação de parâmetro |
| `422` | `{"detail": "Input should be 'storyline' or 'parent'"}` (enum) / `"String should match pattern ..."` (pattern) / lista Pydantic `[{type, loc, msg, input, ctx}]` | FastAPI | Temas: `grain` fora do enum, `order` fora de `^(articles\|random)$`, `topic_type` fora de `(?i)^[A-Za-z]+$`, `limit` fora de `1..200/100`; `from-articles` com `article_uuids: []` (`too_short`) — a validação do corpo antecede a checagem do `x-txn-token` |
| `422` | `{"error": "not_accepted", "message": "Field 'reason' on form 'thumbs_down': Value 'inaccurate' is not one of the accepted values."}` | `not_accepted` | `/feedback` com `reason` fora do enum do servidor |
| `429` | `{"code":"quota_exceeded","message":"Token quota exceeded","request_id":"..."}` | `quota_exceeded` | `POST /chat` sem cookie de identidade — **regime observado nas capturas de set/out-2026** (forma estável, sem `retry-after`); em 2026-11-06 esse caso passou a responder `400 missing_identity` (§7), com e sem `X-Sas-Enforce-Quota: 1`. O `429` permanece documentado porque o mesmo corpo chega como evento `error` com `code: "quota_exceeded"` dentro do stream quando a quota da identidade se esgota |
| `429` | `{"message":"Request timed out"}` | proxy | `/xhr/dynamic-seeded-questions` — timeout do *shard* de backend que atende o símbolo; alternância estável por símbolo com respostas 200 populadas; tratar como transitório |
| `500` | `{"detail": "Internal Server Error"}` | FastAPI | Handler das famílias MAD **intermitente** (observado em `/themes/{uuid}`: 200 e 500 alternam para a mesma requisição válida) — re-tentar; diferente do 500 vazio de borda, este tem corpo FastAPI |
| `500` | corpo vazio (sem `request_id`, sem `content-type`) | — | Falha de borda intermitente do Promenade — observada em `POST /sessions`, `GET …/messages`, `POST /feedback`, em janelas alternadas com o contrato estável; a repetição devolve o contrato documentado. Distinção prática: 5xx **sem corpo** é re-tentável com backoff curto; 5xx **com corpo** é falha persistente do handler |

O `/chat/resume` com `last_event_id=zzz` mostra a assimetria de validação: o parâmetro de query **obrigatório** não é validado quanto ao tipo — passa pelo schema e progride para o `404` de stream inexistente (ao contrário do `idempotency_key` do corpo, que devolve `400 Invalid uuid`). Mensagem só com espaços (`"   "`) **passa** o schema do `/chat` — chega ao modelo e volta como recusa de escopo (§8.2) com o parâmetro `q` vazio no link de redirecionamento.

## 8. Comportamentos empíricos

### 8.1 Requisitos de borda

- A borda responde com `server: ATS` em todas as famílias; as respostas do Promenade trazem `cache-control: private` (nenhuma rota cacheável em borda).
- **Transporte sem compressão** — com `gzip` e com `identity`, o stream (e o `POST /chat` em modo JSON) chega **sem `Content-Encoding`** e com `Transfer-Encoding: chunked`: a borda não comprime a resposta do Scout mesmo quando o cliente oferece compressão — consumidores do `text/event-stream` leem os eventos como texto puro.
- O `POST /chat` em modo JSON traz o header `Age` (segundos) sem que haja cache de POST: cada resposta carrega um `message_id` novo. O `Age` é da camada de borda, não sinal de resposta reaproveitada.
- Demais headers observados no `/chat`: `vary: Origin`, `access-control-allow-credentials: true`, `strict-transport-security`, `x-content-type-options: nosniff`, `x-xss-protection` com report para `csp.search.yahoo.com`, `referrer-policy: no-referrer-when-downgrade`. O proxy XHR devolve `cache-control: private, no-cache, max-age=0`. O AI Analyst devolve `cache-control: max-age=300, public`.

### 8.2 Comportamentos silenciosos

- **Campos vazios são omitidos, não zerados** no envelope do `/chat` em JSON (§4.1) — tratar ausência e `[]` como equivalentes.
- **Campos fora do schema são tolerados**: `POST /chat` com `symbol: "AAPL"` no corpo responde **200** com o envelope normal — o servidor ignora o que não declara.
- **`session_id` não é `required` no `/chat`** — ausente, o servidor cria a conversa ad-hoc e gera o `title`, mas o `session_id` criado não é devolvido no corpo nem no header observado (`X-Promenade-Session-Id` vazio). O app web **nunca** usa esse caminho: sempre cria a sessão antes.
- **`session_id` não tem validação de formato no servidor**: `"zzz"` passa pelo schema e vira **404** `session_not_found` (ao contrário do `idempotency_key`, que devolve `400 Invalid uuid`).
- **`maxLength` de `message` é client-side**: 4.097 caracteres passam pelo schema e seguem para a regra de rota; 3.272 caracteres são aceitos (200 normal). `minLength: 1` é server-side. Sessões são **múltiplas por identidade** — dois `POST /sessions` seguidos devolvem 201 distintos e ambos aceitam chat em paralelo.
- **`ttl` não é validado no `/chat`**: string passa pelo schema e é ignorada.
- **Cursor de paginação opaco e tolerante**: `cursor=zzz` responde **200** com a primeira página, sem erro; `limit=1` devolve exatamente 1 mensagem + `next_cursor`.
- **Listagem vazia para anônimo**: `GET /sessions?tenant=finance` devolve `{"sessions":[],"next_cursor":null}` com `A3` anônimo mesmo após criar e conversar — o *listing* é alimentado pela identidade logada. As sessões anônimas continuam acessíveis unitariamente pelo `session_id` (títulos e histórico).
- **Sondagem graciosa**: `/sessions/{id}/active-stream` com sessão inexistente responde **200** `{"active":false}` — a exceção da família.
- **Allowlist do AI Analyst governa a UI, não a API**: o servidor responde **200** para tickers fora da união do cliente e 404 apenas para símbolo inexistente (§6.2).
- **`topic_type` é contrato de UI**: o servidor aceita qualquer token alfabético case-insensitive; o enum de 9 valores da página não é enforceado.
- **Cache da semente é por identidade**: a mesma pergunta voltou a semear com `cached: false` entre identidades diferentes.
- **Recusa de escopo**: perguntas fora do domínio financeiro ("What is 2+2?") recebem resposta de recusa com link para o produto de busca da Yahoo:

```
I can't answer that, but [Scout.com](https://scout.yahoo.com/chat?q=What%20is%201%2B1%3F%20Just%20the%20number.&fr=yfin&fr2=p:finance,m:chat) can help with more topics.
```

  Os parâmetros `fr=yfin` e `fr2=p:finance,m:chat` identificam a origem. Conselhos diretos de investimento são evitados pelo assistente ("I can't judge whether Apple is a good investment, but I can summarize the long-term setup...").

### 8.3 Volatilidade de estado

- **Quota pode ficar negativa** quando o consumo excede o limite — captura com `{"limit_tokens":100000,"used_tokens":131363,"remaining_tokens":-31363,"reset_after_seconds":86362.63}`. `period_seconds` é inteiro (`86400`, janela fixa de 24 h); `reset_after_seconds` é float com casas decimais (tempo **restante**).
- **Geração de perguntas assíncrona (Dig Deeper)**: artigo permitido pode responder **204** e passar a **200** minutos depois; o cliente trata qualquer resposta sem `questions` como `null`.
- **502 por shard no proxy de perguntas**: símbolos reais alternam entre 200 populado e 502 `Request timed out` de forma estável por símbolo na mesma janela — timeout do shard que atende o símbolo, não validação.
- **Backend de temas intermitente**: a mesma requisição válida alterna entre **200** com envelope e **500** `{"detail": "Internal Server Error"}` (observado em `/themes/{uuid}` no mesmo dia) — o handler do serviço de temas oscila; re-tentar resolve quando transitório, e as validações 422 permanecem de pé em ambos os estados. Distinção da falha de borda do Promenade: aqui o 500 **tem corpo** FastAPI.
- **Camadas independentes na família `themes`**: a validação Pydantic (422) responde mesmo quando o *handler* falha — o schema é revelável independentemente do estado do processamento.

### 8.4 CORS

`vary: Origin` com `access-control-allow-credentials: true` — a borda trata a origem antes do upstream. Não há preflight documentado para clientes fora do domínio Yahoo.

### 8.5 Cache

| Rota | `cache-control` | Observação |
| :--- | :--- | :--- |
| Promenade (todas as rotas) | `private` | Nenhuma rota cacheável em borda |
| Proxy XHR (`/xhr/*`) | `private, no-cache, max-age=0` | — |
| AI Analyst (`/ws/mad/v2/analyst/symbol/{symbol}`) | `public, max-age=300` | Com `server: ATS` |
| `/xhr/config?name=services` | `data-ttl="120"` (bloco `data-sveltekit-fetched`) | TTL declarado no HTML, não no header |

### 8.6 Relógio e unidades

- Timestamps de sessão/mensagem: **ISO-8601 com milissegundos e sufixo `Z`** (`2026-09-17T22:09:43.617Z`).
- `created_at`/`updated_at` das seções do AI Analyst: ISO-8601 com microssegundos e offset `+00:00`.
- `created_at`/`expires_at` do catálogo de perguntas: formato de banco (`2026-09-11 06:55:43.734946+00:00` — espaço em vez de `T`).
- `id:` do enquadramento SSE: carimbo em **milissegundos** com sufixo de sequência (`-0`).
- `session_id`/`message_id`/`stream_id`: identificadores ordenados por tempo (prefixo monotônico entre registros criados em sequência).
- `period_seconds`: inteiro; `reset_after_seconds`: float; `refresh_interval_seconds`/`llm_refresh_interval_seconds`: segundos inteiros (604800 = 7 dias).
- O texto das fontes chega com entidades HTML (`&#39;`) sem decodificação pelo cliente; o `answer` do Dig Deeper chega com `\n` literais (sequência de 2 caracteres) — o sanitizador `C()` os converte.

## 9. Referências do código-fonte (bundle)

### 9.1 Quem chama as rotas e de onde vem o comportamento

| Arquivo | Papel / padrão de chamada |
| :--- | :--- |
| `chunks/[cliente-scout].[hash].js` | Cliente do Scout: criação de sessão, corpo do `/chat`, cabeçalho de quota, parser SSE (resolução dupla do discriminador), extração de `grounding_sources`/`follow_up`/`actions`/`usage`/`quota`, limpeza de citações, sondagem e retomada; erros dedicados `ScoutQuotaExceededError`, `ScoutDuplicateRequestError`, `ScoutNoActiveStreamError` |
| `chunks/[quoteUtil].[hash].js` | `fetchService` — resolve `config.getState().services[key]` → host, `crumb` default `false`, `credentials: "include"`, `disableDefaultQueries`, reescrita `/xhr/service` por `serverKey` gateada por `window._nimbus.ready` |
| `chunks/[loadTickerAnalysisForSymbol].[hash].js` | Loader do AI Analyst: path `/ws/mad/v2/analyst/symbol/{symbol}`, chaves `financeProd`/`financeStage`, `debug_flag`, allowlists de símbolos, mapeamento dos campos da resposta, renderizadores Markdown |
| `chunks/[loadCGCustomStoryList].[hash].js` | Resolvedor de fontes do *Nexus Gateway* (`getCustomStoryList`, `assetLookups`) usado pelo Dig Deeper e pelo modo portfólio |
| `chunks/[loadDigDeeperQuestions].[hash].js` | Carregadores `loadDigDeeperQuestions`/`loadDigDeeperAnswer`, sanitização DOMPurify, renumeração de citações, transform de links com guarda `asset://`, chave `finance`/`financeStage`, constante `portfolio-analysis` |
| `chunks/[loadChatResponse].[hash].js` | Carregador `loadChatResponse` do chat aposentado: POST, query `chat_version`/`use_fargate`, corpo `{question, symbol, initial_context}`, polling da rota de pergunta |
| `chunks/[loadChatRateLimits].[hash].js` | Carregador de `/ws/mad/v2/chat/rate_limit` (aposentada), gates `authed`/`enableQSPAiAnalystSheetChat`/`enableDigDeeperArticleChat`, helpers de `remaining`/`time_to_refill` |
| `chunks/[loadDynamicSeededQuestions].[hash].js` | Loader do catálogo de perguntas: `GET /xhr/dynamic-seeded-questions` com `isRelative: true`, query `symbol`/`limit` |
| `chunks/[ramen_dining].[hash].js` | Validação de UUID usada nos guards do Dig Deeper (regex RFC 4122 + variante nula) |
| `nodes/[playground].[hash].js` | Página AI Playground (`/ai-playground`): hosts Promenade literais, aliases de telemetria Langfuse, construção de `context`, persistência de variantes, oito carregadores da família `themes`, valores de `window`/`topic_type` |
| `nodes/[ai-analyst-route].[hash].js` | Rota `/ai/[symbol]/[section]` do AI Analyst (webview; flags `enableQSPAiAnalystSheet` + `enableQSPAiAnalystSheetWebview`) |
| `nodes/[transcript].[hash].js` | Página da transcrição de earnings call: carregador `/ws/mad/v2/analyst/ect`, loader `/xhr/transcript`, gate `enableEarningsTranscript` |
| `nodes/[research-hub].[hash].js` | Screener do research-hub com integração Scout e seleção de rota NLS (`enableScreenersNlsMad`/`enableScreenersNlsStaging`) |
| `nodes/[config-default].[hash].js` | Config default da página com a flag `enableTxnToken: false` |
| `entry/[app].[hash].js` | Manifesto de rotas (`/(app)/ai/[symbol]/[section]`, `/ai-playground`) e constantes de prefixo (`__ai`, `__data.json`) |

A página do Playground embute o cliente Scout completo — as constantes de host literais e os carregadores da família `themes` vivem no próprio node da página. Consumidores vivos do cliente do Scout:

| Consumidor | Arquivo (sem hash) | Papel |
| :--- | :--- | :--- |
| Painel AI Analyst da ficha de ativo | `chunks/[AiAnalystSheet].[hash].js` | Chat com contexto `ticker:` |
| Página AI Playground | `nodes/[playground].[hash].js` | Comparador de variantes do Scout |
| Dock da home | `chunks/[Dock].[hash].js` | Painel de chat, perguntas e retomada de stream |
| Banner de feedback | `chunks/[scoutFeedback].[hash].js` | Apenas o ícone (formulário externo) |

### 9.2 Camada de serviço compartilhada

```js
// chunks/[quoteUtil].[hash].js — mecanismo de erro da camada de fetch
//   sem pathname:  {"message":"Bad request: pathname is required"}
//   URL impossível: {"message":"Bad request: fetch URL could not be created"}
```

O `perfLabel` cai para o próprio `pathname` quando não informado; `isRelative: true` resolve para o domínio da página (usado pelo loader de perguntas sugeridas). O `crumb`, quando ativado pelo chamador, vai na query **e** no header `x-crumb`, com três estratégias de injeção (`Array` → `push`, `Headers` → `set`, objeto → atribuição) — o Scout nunca o ativa. O consumo de stream usa controlador dedicado: `Accept: text/event-stream` forçado, `AbortSignal.any` unindo o sinal próprio de timeout ao sinal externo do chamador, timeout default de 30 s — o mesmo `timeout: 30000` do serviço `scout` (§2.2).

O núcleo do builder de requisição (validação de `pathname`, fallback de serviço, injeção de locale/crumb) — verbatim:

```js
// chunks/[quoteUtil].[hash].js — builder da requisição (fetchService)
async function f13(p28, p29, p30) {
  if (p29 == null || !p29.pathname) {
    const vO = { message: "Bad request: pathname is required", status: 400 };
    f2(vO, p29);
    throw vO;
  }
  const v27 = await p28.parent();
  const { session: a, stores: n } = v27;
  const v28 = n.crumb.getCrumb();
  const v29 = v27.serviceConfig ?? n.config.getState()?.services;
  const vE = E(a, "disableServiceRewrite");
  const v30 = v29?.[p29.key || "finance"] ?? {
    host: "query1.finance.yahoo.com",           // fallback sem serviço conhecido
    serverKey: "finance",
    client: { timeout: vLN15000 },
  };
  const v31 = v30?.client?.timeout ?? vLN15000;
  const vO2 = {
    credentials: "include",                      // o jar .yahoo.com acompanha sempre
    method: "GET",
    mode: "cors",
    timeout: p29.timeout ?? v31,
    ...p30,
  };
  vO2.headers &&= f12(vO2.headers);
  const vO3 = {
    crumb: p29.crumb ?? false,                   // o Scout nunca ativa
    host: undefined,
    isRelative: p29.isRelative ?? false,
    pathname: p29.pathname,
    perfLabel: p29.perfLabel || p29.pathname,
    protocol: p29.protocol || "",
    query: p29.query,
  };
  if (!vO3.isRelative) {
    vO3.host = v30.host;
  }
  const vF8 = f8(
    vE ? vO3 : f9(vO3, { serverKey: v30?.serverKey }),   // reescrita /xhr/service
  );
  if (!vF8) {
    const vO4 = { message: "Bad request: fetch URL could not be created", status: 400 };
    f2(vO4, p29);
    throw vO4;
  }
  if (!p29.disableDefaultQueries) {              // o Scout passa true — sem lang/region
    vF8.searchParams.set("lang", a.lang || "en-US");
    vF8.searchParams.set("region", a.region || "US");
  }
  if (vO3.crumb && v28) {
    vF8.searchParams.set("crumb", v28);
    if (vO2.method !== "GET" && vO2.method !== "HEAD" && vO2.method !== "OPTIONS") {
      vO2.headers ||= {};
      if (Array.isArray(vO2.headers)) {
        vO2.headers.push(["x-crumb", v28]);
      } else if (vO2.headers instanceof Headers) {
        vO2.headers.set("x-crumb", v28);
      } else if (typeof vO2.headers == "object") {
        vO2.headers["x-crumb"] = v28;
      }
    }
  }
  const v32 = vO3.isRelative ? `${vF8.pathname}${vF8.search}` : vF8.toString();
  return { url: v32, init: vO2, perfLabel: vO3.perfLabel ?? vO3.pathname ?? "", session: a };
}
```

E o consumidor de stream (Accept forçado, `AbortSignal.any`, timeout 30 s):

```js
// chunks/[quoteUtil].[hash].js — fetch de stream
async function f16(p39, p40, p41, p42) {
  const { url: i, init: o, perfLabel: c, session: u } = await f13(p39, p40, p41);
  f11(u, c);
  const v42 = p42?.timeoutMs ?? o.timeout ?? vLN30000;      // 30 s default
  const v43 = new AbortController();
  const vSetTimeout2 = setTimeout(() => v43.abort(), v42);
  const vA2 = [v43.signal];
  if (p42 != null && p42.signal) {
    vA2.push(p42.signal);                                    // sinal externo do chamador
  }
  const v44 = new Headers(o.headers ?? {});
  v44.set("Accept", "text/event-stream");                    // forçado no stream
  const { timeout: g, ...P } = o;
  let v45;
  try {
    v45 = await p39.fetch(i, {
      ...P,
      headers: v44,
      signal: AbortSignal.any(vA2),                          // timeout ∪ chamador
    });
  } finally {
    clearTimeout(vSetTimeout2);
  }
  f14(p39, { url: i, init: o, perfLabel: c, session: u }, v45, v41, v40);
  return v45;
}
```

A camada expõe ainda o modo cache por headers **de pedido** (não de resposta): `{"x-cache": "1", "x-cache-ttl": "60000"}` enviados pelo cliente quando o modo cache está ativo.

### 9.3 Fluxo de credenciais no cliente

1. O bootstrap anônimo (`GET fc.yahoo.com`) emite o cookie `A3` (+ `A1`/`A1S`) para o domínio `.yahoo.com`.
2. `credentials: "include"` acompanha o jar em todas as chamadas — o `A3` é a única credencial necessária no Promenade.
3. O `crumb` nunca é injetado nas rotas do Scout (`crumb: false` por default da camada; nem query string, nem header `x-crumb`).
4. As rotas gateadas por `x-txn-token` não têm emissor no cliente — a flag `enableTxnToken` está desligada no config default da página.

Os cookies `B` (GUID de telemetria) e `GUC` (consentimento GDPR/CCPA) não são necessários em nenhuma rota. Em regiões com barreira de consentimento (`guce.yahoo.com`/`consent.yahoo.com`), clientes de navegador precisam resolver o redirect (POST do formulário com `agree`) antes de adquirir o `A3`; o bootstrap direto via `fc.yahoo.com` não passa pela barreira. A sentinel `MOCK_CRUMB` do bootstrap de crumb vive em `chunks/[initializePage].[hash].js`, não no cliente do Scout.

O ciclo completo do chat no cliente — criação de sessão, orquestrador e loop de eventos — verbatim:

```js
// chunks/[cliente-scout].[hash].js — criação de sessão
async function f28(p55, p56 = vLSFinance, p57 = "prod") {
  const v44 = await j(p55, {
      key: f13(p57),                       // f13 = seletor scout/scoutDev (§2.2)
      pathname: "/sessions",
      disableDefaultQueries: true,
    }, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tenant: p56 }),
    },
  );
  if (v44 == null || !v44.session_id) {
    throw new Error("Scout session error: no session_id returned");
  }
  return v44.session_id;
}
```

```js
// chunks/[cliente-scout].[hash].js — orquestrador do /chat (seeds, quota, 409)
async function f33(p68, p69, p70 = {}, p71) {
  const {
    context: n, environment: s = "prod", idempotencyKey: i, message: d,
    tenant: f = vLSFinance, enableSeededCaching: u = false,
    enforceQuota: w = false, treatQuotaExceededAsResult: _ = false, variant: p,
  } = p69;
  const v68 = performance.now();
  let v69 = u ? undefined : p69.sessionId;
  if (!u && !v69 && ((v69 = await f28(p68, f, s)), p71?.aborted)) {
    throw new DOMException("The operation was aborted.", "AbortError");
  }
  if (v69 && (p71 == null || !p71.aborted)) {
    p70.onSessionCreated?.call(p70, v69);
  }
  const v70 = u ? "/chat/seeds" : "/chat";
  const v71 = u ? "scout.chat.seeds" : "scout.chat";
  const vO2 = {
    context: (n?.trim()) || undefined,
    idempotency_key: u ? undefined : i,    // seeds não usam idempotência
    message: d,
    session_id: u ? undefined : v69,       // seeds não levam session_id
    tenant: f,
    ttl: u ? vLN5 : undefined,             // ttl = 5 somente em /chat/seeds
    variant: (p?.trim()) || undefined,
  };
  const vO3 = { "Content-Type": "application/json" };
  if (w) {
    vO3["X-Sas-Enforce-Quota"] = "1";      // quota estrita (§2.3)
  }
  const v72 = await L(p68, {
      disableDefaultQueries: true, key: f13(s), pathname: v70, perfLabel: v71,
    }, { method: "POST", headers: vO3, body: JSON.stringify(vO2) },
    { signal: p71 });
  if (!v72.ok) {
    const v73 = await v72.text().catch(() => "");
    let v74 = `Scout API error: ${v72.status}`;
    let v75;
    try { v75 = JSON.parse(v73); } catch { if (v73) v74 += ` — ${v73}`; }
    if (v75?.message) v74 = v75.message;
    throw v72.status === 409 && v75?.error === "duplicate_request"
      ? new C5(v74, v75.session_id, v75.message_id, v75.stream_id)  // ScoutDuplicateRequestError
      : new Error(v74);
  }
  // desvio JSON completo: content-type application/json → resposta pronta
  const v76 = (v72.headers.get("content-type") || "").includes("application/json");
  if (u && v76) {
    const v77 = await v72.json();
    const { result: E, sessionId: l } = f27(v77);   // seeds criam a sessão
    if (l && (p71 == null || !p71.aborted)) {
      p70.onSessionCreated?.call(p70, l);
    }
    return E;
  }
  if (!v72.body) throw new Error("No response body");
  // sessão nova pode chegar no header mesmo sem body JSON
  const v78 = v72.headers.get(vLSXPromenadeSessionId) || undefined;
  if (v78 && v78 !== v69 && (p71 == null || !p71.aborted)) {
    v69 = v78;
    p70.onSessionCreated?.call(p70, v78);
  }
  return f31({ body: v72.body, callbacks: p70, sessionId: v69,
               signal: p71, startTime: v68, treatQuotaExceededAsResult: _ });
}
```

```js
// chunks/[cliente-scout].[hash].js — loop de eventos SSE (consolidação)
const v47 = new Set(["grounding.sources", "follow_up.questions", "actions.suggested"]);
const v48 = new Set(["suggesting", "suggesting actions"]);   // pós-deltas = resposta completa
for await (const { event: S, data: c } of f12(e, vF2)) {
  const { session_id: E } = c;
  if (o != null && o.aborted) throw new DOMException("The operation was aborted.", "AbortError");
  if (typeof E == "string" && E !== vR3) {                    // sessão trocou no stream
    vR3 = E;
    t.onSessionCreated?.call(t, E);
  }
  if (vLS5 && f30(S, c)) vF3(true);                            // heurística de resposta completa
  if (S === "stream.start") { /* guard message_id */ }
  else if (S === "content.delta" && c.delta) {
    if (v55 === undefined) v55 = Math.round(performance.now() - n);  // timeToFirstToken
    vLS5 += c.delta;
    t.onContentDelta?.call(t, c.delta, f26(vLS5));             // texto limpo acumulado
  } else if (S === "follow_up.questions") vA2 = f22(c);
  else if (S === "actions.suggested") vA3 = f23(c);
  else if (S === "grounding.sources") { vA4 = f21(c); t.onGroundingSources?.call(t, vA4); }
  else if (S === "stream.end") { v56 = f24(c) ?? v56; v57 = f25(c) ?? v57; }  // usage + quota
  else if (S === "error") {
    if (c.code === "quota_exceeded") {
      if (!s) throw new C4(c.message || undefined);            // ScoutQuotaExceededError
      v58 = true;                                              // treatQuotaExceededAsResult
    } else {
      throw new Error(c.message || "Stream error");
    }
  }
}
```

A limpeza de citações (`f26`) aplica-se ao texto acumulado e ao modo JSON:

```js
// chunks/[cliente-scout].[hash].js — limpeza de referências [texto][N]
function f26(p53) {
  return p53.replace(/\[([^\]]*)\]\[\d+\]/g, "$1");
}
```

Telemetria de conversa do Dock — cada pergunta/resposta emite `chat_query`/`chat_complete` com o escopo do tenant (`{tenant_id: "finance", tenant_variant: <variant|base>, tenant_version: "1.0", turn_num, chat_id?, chat_origin?}`) e, no painel de prompt pré-definido, `slk` com o texto cortado em 500 caracteres.

### 9.4 Hosts e serialização

O cliente resolve o serviço por ambiente (`L(t)`, §2.2). A página AI Playground monta URLs do histórico **diretamente** com as constantes de host, contornando a camada:

```js
// nodes/[playground].[hash].js — constantes de host literais
const vLSHttpspromenadeapisea = "https://promenade-api.search.yahoo.com";
const vLSHttpsdevpromenadeapi = "https://dev-promenade-api.search.yahoo.com";
```

O contexto de conteúdo do `/chat` é construído pela aba ativa:

```js
// nodes/[playground].[hash].js — construção do context
function Ns(s, e) {
  const t = e.trim();
  if (!t || s === "default") {
    return "";
  } else if (s === "article") {
    return `article_uuid:${t}`;
  } else {
    return `ticker:${t}`;
  }
}
```

Aba de cotação → `context: "ticker:AAPL"`; aba de artigo → `article_uuid:{uuid}`; sem aba → sem `context`. As perguntas sugeridas (§5.4) carregam o mesmo esquema em `seed_auth_contexts` (`"ticker:AAPL"`).

### 9.5 Mapa resumido da cadeia

```
entry/[start].[hash].js
  └── chunks/[88].[hash].js (router SvelteKit)
        ├── chunks/[AiAnalystSheet].[hash].js
        │     └── chunks/[cliente-scout].[hash].js
        │           ├── POST promenade-api /sessions + /chat (JSON | SSE)
        │           ├── GET  /sessions/{id}/active-stream + /chat/resume/{stream_id}
        │           └── chunks/[quoteUtil].[hash].js (fetchService)
        ├── chunks/[DigDeeperAiSheet].[hash].js
        │     └── chunks/[loadDigDeeperQuestions].[hash].js
        │           ├── GET query1 /ws/mad/v2/articles_ddq/{uuid}/questions[/{qid}]
        │           └── chunks/[loadCGCustomStoryList].[hash].js (Nexus Gateway)
        ├── chunks/[Dock].[hash].js → chunks/[cliente-scout].[hash].js (painel da home)
        ├── nodes/[playground].[hash].js → família /ws/mad/v2/themes (8 carregadores)
        ├── chunks/[loadTickerAnalysisForSymbol].[hash].js → GET /ws/mad/v2/analyst/symbol/{symbol}
        └── nodes/[transcript].[hash].js → GET /ws/mad/v2/analyst/ect + /xhr/transcript
```

### 9.6 Contrato do consumidor final

- **`AiAnalystSheet`** importa apenas a função de chat e chama com `sessionId` corrente e callbacks de status/delta; enquanto o primeiro status do servidor não chega, a UI mostra textos de etapa locais: `["Reviewing your question...", "Fetching relevant sources...", "Analyzing the data...", "Putting it all together..."]`. O turno registra o modo escolhido (`useScoutApi`) derivado de `enableQSPAiAnalystSheetChatScoutApi` — com `A` ativo usa o cliente streaming do Scout; caso contrário, o POST com polling do chat aposentado (§3.4). A escolha do modo do turno:

```js
// chunks/[AiAnalystSheet].[hash].js — flags do chat e modo do turno
const Z = Qs(Se),
      ce = ht(Se, "enableQSPAiAnalystSheet"),
      re = ht(Se, "enableQSPAiAnalystSheetChatScoutApi"),
      Ae = ht(Se, "enableScoutStagingApi");
// ... t(44, A = f && re)   →  useScoutApi: A
```

**Renderização de LaTeX** — o `AiAnalystSheet` intercepta delimitadores `\[ ... \]` no conteúdo do modelo (WACC, Sharpe Ratio, EBITDA etc.) antes de renderizar o Markdown:

```js
// chunks/[AiAnalystSheet].[hash].js — tokens de fórmula
const Dr = "math", Mr = "mathInline",
      Rn = /\\\[([\s\S]*?)\\\]/g;
function Nr(r) { // "sanitizeMath" em fontes externas — mesmo código
  return r.trim().replace(/\n\s*/g, " ").replace(/[ \t]+/g, " ");
}
function On(r, e) {
  const t = Nr(r);
  return { display: e, raw: `\\[${t}\\]`, text: t, type: e ? Dr : Mr };
}
```

Pipeline: `Qn()` divide o texto ao redor dos blocos LaTeX (`matchAll(Rn)`); os trechos comuns passam pelo lexer GFM (`new Lexer({ gfm: true }).inlineTokens`); os blocos viram tokens `{type: "math" | "mathInline"}` com o corpo normalizado; `Or()`/`Un()` re-tokenizam parágrafos e listas recursivamente. Só o delimitador display `\[ \]` é tratado — não há pipeline para `$...$` inline.

**Marshaling unificado do streaming** — a folha converte os eventos SSE no **mesmo envelope da família aposentada**, para reutilizar a renderização: os `status.update` viram `additional_info.steps` com `{action: "scout-status-N", action_text, is_user_facing: true}`; os `grounding.sources` viram `answer.additional_info.references`; o texto acumulado vira `answer.text`; follow-ups do stream ganham ids client-side (`{sessionId}-scout-followup-{i}`). O envelope sintético:

```js
// chunks/[AiAnalystSheet].[hash].js — envelope sintético do streaming
const Y = (S, y = "", R = [], P = []) => ({
  additional_info: {steps: at(P)},
  answer: {additional_info: {references: R}, id: "", text: y},
  id: "", text: S
});
```

**Cancelamento por seção** — cada seção de chat tem um `AbortController` próprio (Map `id → controller`); navegar para fora aborta os streams em curso e a seção cancelada recebe banner próprio (`AI_SHEET_REQUEST_CANCELLED_*`). **Gráficos nas respostas** — `answer.chart_info[]` renderiza gráficos `line`/`bar` (Chart.js) com `datasets`, `data_point_count`, eixos `xAxis`/`yAxis` e flag `has_multiple_companies`. **Painel de depuração** — a folha expõe `QUESTION_ID` e `SESSION_ID` com cópia e link externo apontando para os paths da família aposentada (`/ws/mad/v2/chat/{sessionId}` e `/chat/question/{id}`). **Caching semeado condicional** — `enableSeededCaching` só é ligado quando o gatilho do turno é `dig-deeper-question`. **Fontes limitadas a 10** — `additional_info.references` passa por dedupe e corte antes de renderizar. **Catálogo de fallback** — sem `dynamic_questions`, a UI sorteia de um catálogo estático de 32 perguntas (ex.: `Any recent earnings surprises?`, `Are insiders buying or selling?`) com filtro por texto, aleatorização e máximo de 3.

**Banner de rate limit e telemetria** — `remaining === 0` → banner de erro com `refillTime` (default 3600 s formatado); `remaining <= 5` → aviso com contagem (i18n singular/plural). Eventos de analytics: `chat-answer-loaded`/`chat-answer-error`/`chat-rate-limit-error` e variantes `article-ddq-*` para o chat de artigo; o banner de sign-in aponta URL com `askAi=1` nos search params. O chunk do rate limit co-localiza, além do carregador, o wrapper do sheet (scroll anchoring por `data-section-id`, spacer dinâmico), o resumo colapsável de etapas ("Completed X steps" com `is_user_facing`) e os banners.

**Botão de entrada gateado pela allowlist** — o gatilho da ficha valida o símbolo pelo export do loader do AI Analyst (§6.2) antes de abrir o painel, com tooltip de onboarding (FeatureCue persistida) e eventos GA gateados por `enableScoutChatGaEvents`.

**AI Research Report — superfície de relatório por seções** — rota `/quote/[symbol]/research-reports`, gateada pela flag **`enableAiResearchReport`** **e** pela allowlist de símbolos do AI Analyst; a carga da página busca o conteúdo de IA via **quoteSummary com `modules: "ai"` e `aiModules: ["news_summary"]`** mais `suggestedChatQuestions` (§8); a página tem **duas abas** — AI Report e **Expert Reports** (premium: `premiumTierFeatures.researchReports`, paywall `qspReports`, lista de tamanho 25, provedores com logos Argus/Morningstar); módulo de relatório com abas (`AI_REPORT_AI_SECTIONS_LABEL`): seções `{title, updatedAt, markdown, sources, info}`; card de fontes em **tiers** com badges por provedor e tier de dados; tabela de **revisões de price targets** (`windowDays`, prior/current/change% com agregados all-raised/all-cut/mixed); **gauge de consenso** cruzando `financialData.recommendationKey` (Bullish/Neutral/Bearish), `regularMarketPrice` e `targets` (mean/low/high/count do quoteSummary); **cenários BEAR/BASE/BULL sobre holdings** (quantity, averagePricePerShare, currentMarketValue, totalGain/totalPercentGain, exposurePercent, userBaseCurrency) — consumindo o AI Analyst (`loadTickerAnalysisForSymbol`) e o quoteSummary (`loadQuoteSummary`) na mesma folha.

**Superfícies consumidoras do Scout AI (mapa de imports)** — além das folhas principais: o painel de conteúdo relacionado de artigos embute o Dig Deeper (carregadores + PromptCard + feedback); o chunk de componentes do Dig Deeper carrega os textos de etapa próprios por modo (`REVIEWING_YOUR_PORTFOLIO`, `ANALYZING_THE_ARTICLE`, `ANALYZING_MARKET_CONDITIONS`, `CHECKING_OTHER_SOURCES`, `GENERATING_THE_RESPONSE`); as páginas de portfólio entram pelo botão "Analyze" — o clique abre a folha do Dock com `contentType: "portfolio"` e **pré-semeia a pergunta** `{questionId: "portfolio-analysis", question: "Analyze my portfolio"}`; com usuário autenticado e `scoutPrompt`, dispara o chat diretamente (telemetria `sec: "portfolio"`); o banner de insights da mesma superfície renderiza `{summaryInsight, glanceInsights}` com atribuição `POWERED_BY_YAHOO_SCOUT` e recarrega com `forceSkipCache` quando o token de resumo muda; métricas-chave de portfólio e o painel de watchlist consomem o dispatcher de insights (§3.5); insights de watchlist aparecem na rota da watchlist (`nodes/[watchlist-view]`); o insight por ticker (`TickerAIInsight`) é embutido em múltiplas páginas de quote (ficha e sub-rotas de análise/estatísticas); o suporte a perguntas dinâmicas usa **três registros por quoteType** — ETF (~101 tickers, flag `enableQSPDynamicQuestionsEtf`), INDEX (12 índices como `^GSPC`/`^VIX`, flag `enableQSPDynamicQuestionsIndex`) e MUTUALFUND (~90 fundos, flag `enableQSPDynamicQuestionsMutualFund`) — enquanto EQUITY usa a allowlist do AI Analyst (§6.2); fora das listas o ranqueamento das perguntas é `ts_ranked` (Thompson sampling), dentro é `random`.

- **`Dock`** importa quase todo o cliente — painel de chat da home, com helpers de formatação (`weekday`/`time` via `Intl.DateTimeFormat`), parser de perguntas de continuação e limpeza de citações. Persistência em `sessionStorage`:

  - `yf-scout-signin-handoff` — handoff para o fluxo de login (o gate de quota com login — `scout-quota-gate-signin` — leva à entrada de conta);
  - `yf-scout-last-chat` — última conversa, com validade de **30 minutos** (`30*60*1e3` ms) e id validado por `/^[\w-]{1,64}$/`;
  - `yf-dock-tab` — aba ativa do Dock (`scout-tab-active` quando é a do Scout).

  Identificadores de UI (`scout-fab-launcher`, `scout-quota-gate`, `scout-follow-up-pill`, `scoutSessionList`, `scout-chat-history-mode`); estado do chat com papéis `{User: "user", ScoutReply: "scoutReply"}`. Placeholder inicial do Playground: `"Thinking..."` (substituído pelo `status.update`) e `"Generating response..."` enquanto os deltas chegam.

- **`DigDeeperAiSheet`** importa o carregador de respostas e o dispatcher do modo portfólio no mesmo bloco; os objetos de payload/estado carregam `variant: "dig-deeper"` ao lado de `answer`, `questionId` e `sourcesCount` — o mesmo discriminador usado pelo `AiAnalystHybridBanner` em `dig-deeper-question`. Antes de renderizar, o cliente resolve as fontes e compacta as citações — a renumeração mantém apenas as fontes resolvidas e reindexa as citações de forma monotônica:

```js
// chunks/[loadDigDeeperQuestions].[hash].js — renumeração de citações
function G(n, t, r) {
  if (!(t != null && t.length) || !n)
    return { validSources: [], updatedAnswer: n || "" };
  const e = [], s = new Map;
  for (let a = 0; a < t.length; a++) {
    const i = t[a];
    if (r[i]) {
      const o = e.length + 1;
      e.push(i), s.set(a + 1, o);
    }
  }
  if (e.length === t.length)
    return { validSources: t, updatedAnswer: n };
  if (e.length === 0)
    return { validSources: [], updatedAnswer: n.replace(/\[\d+\]/g, "").replace(/\s{2,}/g, " ").trim() };
  const c = n.replace(/\[(\d+)\]/g, (a, i) => {
    const o = s.get(+i);
    return o ? `[${o}]` : "";
  }).replace(/\s{2,}/g, " ").trim();
  return { validSources: e, updatedAnswer: c };
}
```

  Se nenhuma fonte resolver, todas as citações `[N]` são removidas do texto. Os links `[FMCC](asset://quote/FMCC)` são convertidos pelo renderizador, com guarda de esquema:

```js
// chunks/[loadDigDeeperQuestions].[hash].js — transform de links (guarda asset://)
const s = /\[([^\]]+)\]\(([^)]+)\)/g;
let i = t.replaceAll(s, (l, a, u) => {
  if (u.startsWith("asset://") && !y.test(u))
    return l;                      // link asset:// não-quotável preservado como está
  const c = b(u, n), f = L(u, c);
  return `[${a}](${f})`;           // demais links reescritos pelo resolvedor
});
```

  

- **`AiAnalystSheet`/`TickerAIInsight`** — módulos satélite do sheet: `chunks/[TickerAIInsight].[hash].js` (três categorias de insight, §6.3) e o deep link nativo construído pelo módulo "Dig deeper" dos artigos (`chunks/[DigDeeperQuestions].[hash].js`) com `prompt` (corte em 500 caracteres) e `uuid` do artigo:

```js
// chunks/[DigDeeperQuestions].[hash].js — deep link do chat nativo
const q = new URLSearchParams({
  prompt: m.slice(0, 500)
});
const F = a == null ? undefined : a.contentId;
if (F) {
  q.set("uuid", F);
}
return `/__ai/scout/chat?${q}`;
```

  `GET /__ai/scout/chat?prompt=What+is+AAPL` com User-Agent de navegador responde **404** — o alvo é o webview do app (`enableArticleDdqNativeChat`). A navegação do menu da home aponta o produto standalone: `https://scout.yahoo.com/?fr=fp-more-sct&fr2=p:fp,m:more-sct`.

- **Página AI Playground** — deep-links com submissão automática: `question` (texto pré-preenchido), `autoSubmit` (com `"1"` submete no carregamento), `contentType` (`"quote"`/`"article"` validados), `contentId` (**caixa alta automática quando `contentType=quote`**, UUID preservado para artigo). Link gerado: `/ai-playground?autoSubmit=1&question={pergunta}` + `&contentType=quote&contentId=AAPL`. Persistência local:

  - `ai-playground-panels-v2` — painéis ativos com o par `{environment, variant}` por instância;
  - `yf.aiPlayground.savedPortfolios.v1` — carteiras salvas, validadas na leitura/escrita (`id` string, `name` string, `holdings` com `ticker` string e `weight` number).

  Três carteiras de demonstração pré-carregadas (`demo-megacap-tech` "Mega-cap Tech", `demo-balanced` "Balanced Blue-chip", `demo-energy-defense` "Energy & Defense"). Telemetria por painel: latência corrente/última, uso de tokens e dois links de auditoria construídos no cliente — o de tracing Langfuse aponta para `{nonprod ? langfuse-proxy-yf-scout-nonprod : langfuse-proxy-yf-scout-prod}/sessions/{session_id}` e um `debugUrl` de sessão. Rótulos de status normalizados contra `{"understanding", "planning", "retrieving", "suggesting actions", "suggesting"}` — rótulos fora do conjunto (os dinâmicos por ativo) seguem sem normalização.

### 9.7 Feature flags do Scout (catálogo do bundle)

| Flag | Papel indicado no código |
| :--- | :--- |
| `enableScoutQuoteEntryPoints` / `enableScoutQuoteLeafEntryPoints` | Entradas do Scout nas páginas de cotação e de folha de cotação |
| `enableScoutArticleEntryPoints` | Entradas em artigos |
| `enableScoutPortfolioEntryPoints` | Entradas em portfolio/watchlist |
| `enableScoutHomeDesktopEntryPoints` | Entradas na home desktop |
| `enableScoutChatCondensedWarnings` | Avisos condensados no chat |
| `enableScoutSuggestedActionAddToWatchlist` | Ação sugerida `add-watchlist` (§4.1) |
| `enableScoutAskAiLabel` | Rótulo "Ask AI" |
| `enableScoutUnifiedPanel` | Painel unificado do Dock |
| `enableScoutMwebFabLauncher` / `enableScoutMwebSplitButtonLauncher` | Botão flutuante (FAB) e botão dividido no mobile web |
| `enableScoutCSNDuringSSN` / `enableScoutSSNPersistence` | Comportamento do Scout durante o slide-in de notícias (SSN) |
| `enableScoutFeedbackApi` | Envio de feedback |
| `enableScoutStagingApi` | Uso da API de staging |
| `enableScoutStreamResume` | Retomada de stream (§2.1) |
| `enableScoutYnetQuotaEnforcement` | Aplicação de quota via `X-Sas-Enforce-Quota` (§2.3) |
| `enableAiResearchReport` | Página `/quote/[symbol]/research-reports` (§9.6) — com allowlist de símbolos |

O grupo AI Analyst usa o prefixo `enableQSPAiAnalyst*` (`Sheet`, `SheetChat`, `SheetChatScoutApi`, `SheetDynamicQuestionsTsRanked`, `SheetWebview`, `HybridChatBanner`) e o AlphaSpace o prefixo `enableAlphaSpace*`. O gateway de símbolos usa `enableTickerAnalysisStagingApi` (staging) e `enableTickerAIInsights`. O HTML do SSR não renderiza o componente Scout server-side — zero markup de botão/sheet/chat — mas carrega a configuração: o blob de feature flags (94 menções `enableQSP`), o mapa de serviços `scout`/`scoutDev` e o preload do `scoutFeedback` CSS. Seis flags citadas por fontes externas **não existem no bundle** — `...ChatScoutSeededCaching`, `...LoggedOutSeededQuestions`, `...ChatScoutFollowUpQuestions`, `...AnalysisDynamicQuestions`, `...ChatDebugModeInYnet`, `...ChatBypassAuthInYnet` — a funcionalidade correspondente existe no cliente por outros caminhos (ex.: `enableSeededCaching` é opção do payload do cliente Scout).

---

## 10. Guia de reimplementação

### 10.1 Algoritmo

```
1. Bootstrap: GET https://fc.yahoo.com (sem cookie) → cookie A3 (+ A1/A1S)
   [regiões com consentimento: resolver guce.yahoo.com antes]
2. POST https://promenade-api.search.yahoo.com/sessions
   corpo {"tenant":"finance"}, credentials: include → 201 {session_id}
3. POST .../chat  corpo {message, session_id, tenant}
   ├─ resposta application/json → envelope completo (§4.1)
   └─ Accept: text/event-stream → loop de eventos (§5.3):
        stream.start → guard message_id
        status.update → progresso
        content.delta → acumular texto
        grounding.sources → fontes
        follow_up.questions / actions.suggested → UI
        stream.end → usage/quota
4. [interrupção] GET .../sessions/{id}/active-stream?tenant=finance
   → active: true → GET .../chat/resume/{stream_id}?last_event_id=0&tenant=finance
5. [histórico] GET .../sessions/{id}/messages?tenant=finance&limit=100&cursor=...
6. [erros] 400 missing_identity → refazer bootstrap; 409 duplicate_request →
   reutilizar message_id da primeira execução; 429 quota_exceeded → esperar
   reset_after_seconds; 401/403 em escrita → exige sessão logada
```

### 10.2 Regras de parsing indispensáveis

1. **Discriminador do evento**: campo `event` **dentro** do JSON do `data`; a linha SSE `event:` é fallback e o valor `message` é descartado (§5.3).
2. **Payload**: só objeto JSON produz evento; `null`/array/escalar caem em `{event, data: {}}` sem callback.
3. **Campos vazios são omitidos** — `follow_up_questions` e `suggested_actions` podem não aparecer; tratar ausência e `[]` como equivalentes (§4.1).
4. **`grounding_sources` tem dois formatos**: histórico (`title/summary/url/favicon_url/site_name/reference_number`) e SSE (`provider/pub_date/snippet/summary/title/url/uuid`) — fontes sem `title` ou `url` são descartadas (§5.3).
5. **Citações**: o texto do `/chat` usa `[texto][N]` (reduzir ao texto, §9.6); o Dig Deeper usa `[N]` com renumeração pelas fontes resolvidas (§9.6).
6. **Credenciais casadas**: o `A3` do bootstrap é a identidade; `crumb` não participa de nenhuma rota do Scout.
7. **Quota**: `remaining_tokens` pode ficar **negativo**; `reset_after_seconds` é float (§8.3).
8. **Envelope duplo no JSON completo**: `suggestions`/`follow_up_questions` são nomes equivalentes; `metadata` só vem preenchido no `stream.end` do SSE.
9. **Cursor de paginação**: opaco base64 de um par estilo DynamoDB — `base64({"SK":"MSG#<message_id>","PK":"SESSION#<session_id>"})`; cursor inválido é **ignorado** (200 com a primeira página).
10. **5xx vazio é re-tentável**: 500 sem corpo e sem `request_id` é falha de borda — repetir com backoff curto devolve o contrato (§7); 5xx com corpo é falha persistente do handler.
11. **`/chat/resume` exige `Accept: text/event-stream`** — sem o header a rota responde 406 (§7), diferente da negociação do `/chat`.
12. **`\n` literais no `answer` do Dig Deeper**: o wire entrega o texto com escapes não resolvidos — converter antes da renderização (§5.6).

### 10.3 Implementação de referência

Dois códigos de referência, **somente stdlib** (`urllib` + `http.cookiejar` — Python 3.8+, zero dependências externas), cobrem todo o contrato deste documento. Ambos rodam em dois modos: subcomandos/flags para uso em lote (scripting) e REPL interativo sem argumentos. Os arquivos estão na **raiz da pasta `yahoo-scout/`** — `scout.py` (cliente consolidado, chat + MAD), `scout_chat.py` (chat dinâmico da Promenade), `scout-cli-v3.py` (iteração anterior) e `test_promenade_api_v2.py` (suíte de verificação).

O cliente consolidado `scout.py` — autossuficiente, um único jar de identidade e um único cliente para as duas famílias — reúne em um REPL conversacional todo o contrato deste documento: texto livre pergunta ao Scout (SSE) e todos os comandos ficam a um `/` de distância (chat: `/nova`, `/sse`, `/contexto`, `/historico`, `/info`, `/sessoes`, `/fixar`, `/seeds`, `/ativas`, `/retomar`, `/feedback`, `/quota`, `/renovar`, `/apagar`, `/exportar`; MAD: `/analista`, `/ddq`, `/ect`, `/transcricao`, `/perguntas`, `/temas`, `/tickers`, `/tema`, `/tema-simbolo`, `/grafo`, `/artigos-tema`, `/portfolio`, `/insights`, `/diario`, `/faqs`, `/watchlist`, `/screener`, `/screener-legado`; diagnóstico: `/json`, `/config`, `/deeplink`, `/aposentado`, `/rate-limit`):

```bash
python scout.py                                  # REPL — texto livre = pergunta
python scout.py -q "What is the Dow?"            # pergunta única (SSE) e sai
python scout.py -q "How is AAPL?" --json --contexto ticker:AAPL
python scout.py --analista NVDA --secao overview # kit MAD: relatório por seção
python scout.py --ddq 7ca8986b-1a73-44e9-859e-994b3c8cb976   # cadeia do Dig Deeper
python scout.py --temas                          # lista de temas (grain/limit/order/topic_type)
python scout.py --grafo 1d                       # grafo por janela
python scout.py --portfolio AAPL:5000,NVDA:3000  # feed de portfólio com holdings
python scout.py --perguntas NVDA                 # catálogo de perguntas
python scout.py --aposentado                     # família 410 completa
python scout.py --insights                       # gates JWT (401 anônimo)
python scout.py --config                         # sonda de serviços
```

`scout_chat.py` — chat dinâmico da Promenade API: cliente completo das 14 rotas (`/sessions`, `/chat` JSON e SSE, `/chat/seeds`, `/messages` com paginação por cursor, `/sessions/{id}`, `/sessions`, `/active-stream`, `/chat/resume`, `/feedback`, `/sessions/{id}/delete`, `/xhr/dynamic-seeded-questions`, sonda `/xhr/config?name=services`, método errado `GET /chat`, deep link `/__ai/scout/chat`); parser SSE fiel ao resolvedor duplo do cliente; REPL de conversa dinâmica com contexto (`ticker:AAPL`), streaming token-a-token, perguntas de continuação numeradas, feedback 👍/👎 com o enum do servidor, exportação da conversa e renovação de identidade (novo A3 = nova quota); retry do 500 vazio transiente em todas as rotas — inclusive no estabelecimento do stream — e tratamento dedicado de `quota_exceeded`, `missing_identity` e `session_not_found`.

```bash
python scout_chat.py                             # REPL — conversa dinâmica
python scout_chat.py -q "What is the Dow?"       # JSON completo
python scout_chat.py -q "How is AAPL?" --sse --contexto "ticker:AAPL"
python scout_chat.py -q "What is NASDAQ?" --seeds --json-bruto
python scout_chat.py --perguntas NVDA            # catálogo de perguntas
python scout_chat.py --config                    # sonda /xhr/config + GET /chat
python scout_chat.py --deeplink "What is AAPL"
```

### 10.4 Notas de portabilidade

- Cookie jar único por identidade; a renovação é refazer o bootstrap (`fc.yahoo.com`) quando `400 missing_identity` aparecer.
- `credentials: "include"` equivale a enviar o jar do domínio `.yahoo.com` em cada requisição — o `A3` é a única credencial necessária.
- O streaming não é comprimido pela borda (§8.1): ler o corpo como texto puro.
- O `crumb` das rotas REST de cotação não é reaproveitado pelo Scout — clientes que o injetam por hábito continuam funcionando (o servidor ignora).
- A retomada de stream (`active-stream` + `resume`) é o caminho de resiliência para clientes de longa duração; `last_event_id=0` retransmite tudo.
- `https://dev-promenade-api.search.yahoo.com` e os aliases de telemetria (`https://yo/langfuse-proxy-yf-scout-prod`/`-nonprod`) não resolvem na internet pública — internos.
- O Scout responde no idioma da pergunta (não há `content-language` nem parâmetro de idioma na requisição).

## 11. Apêndice — amostras JSON reais

### 11.1 `POST /sessions` — 201 Created

```json
{
  "session_id": "01a0b16b-22c1-7864-90f8-02c4d6eba594",
  "title": null,
  "title_source": null,
  "pinned": false,
  "created_at": "2026-09-17T22:09:43.617Z",
  "updated_at": "2026-09-17T22:09:43.617Z"
}
```

### 11.2 `GET /sessions/{session_id}?tenant=finance` — título derivado

```json
{
  "session_id": "01a0b16e-ab39-7f11-9bca-bc9325da0995",
  "title": "Apple's main business",
  "title_source": "generated",
  "raw_title": "What is Apple's main business?",
  "short_title": "Apple's main business",
  "pinned": false,
  "created_at": "2026-09-17T22:13:35.161Z",
  "updated_at": "2026-09-17T22:13:40.784Z"
}
```

No modo JSON do `/chat`, o `title` da resposta é o título gerado (`"Dow Jones Explanation"`, `"Simple acknowledgment"`).

### 11.3 `GET /sessions/{session_id}/messages` — histórico com grounding do histórico

```json
{
  "messages": [
    {
      "message_id": "01a0b16b-2522-731c-99e1-b7a092470128",
      "role": "user",
      "content": "In one sentence, what is Apple's main business?",
      "created_at": "2026-09-17T22:09:44.226Z"
    },
    {
      "message_id": "01a0b16b-2522-731c-99e1-b7a11f6bbad4",
      "role": "assistant",
      "content": "Apple's main business is designing, manufacturing, and selling consumer electronics like the iPhone, Mac, iPad, and wearables...",
      "created_at": "2026-09-17T22:09:48.778Z",
      "grounding_sources": [
        {
          "title": "AAPL Profile",
          "summary": "Company profile, sector, industry, and business description for AAPL.",
          "url": "https://finance.yahoo.com/quote/AAPL/profile/",
          "favicon_url": "https://s.yimg.com/pv/static/search_favicon/images/32x32_7c90c9e1fd8115b9_1777586777.png",
          "site_name": "finance.yahoo.com",
          "reference_number": 1
        }
      ]
    }
  ]
}
```

### 11.4 `POST /chat/seeds` — resposta semeada (envelope ampliado)

```json
{
  "seed_key": "088cdbe7b13b208d75e2b943ceda39938e9f2f794a762fd1d02ad9866301da05",
  "question": "What is the P/E ratio of MSFT?",
  "content": "Microsoft's trailing P/E ratio is **20.72** as of **2026-06-30**...",
  "citations": [],
  "grounding_sources": ["... 6 fontes ..."],
  "suggestions": ["... 3 perguntas ..."],
  "metadata": {},
  "cached": false,
  "session_id": "01a0b193-66a9-75ce-b74f-36588795c543",
  "message_id": "01a0b193-66a9-75ce-b74f-36588795c544",
  "title": "MSFT P/E ratio"
}
```

O `/chat/seeds` cria a sessão: `session_id`/`message_id` do par gerado acompanham a resposta, com o `title` derivado da pergunta e `cached: false` na primeira execução (nova chamada com a mesma mensagem devolve a versão em cache).

### 11.5 `GET /sessions/{id}/active-stream` — durante a geração

```json
{
  "active": true,
  "stream_id": "01a0b193-37b4-7a24-b40b-388fe35231dd",
  "message_id": "01a0b193-3781-737a-b6cc-2b869e1b6b33",
  "resume_url": "/chat/resume/01a0b193-37b4-7a24-b40b-388fe35231dd?last_event_id=0&tenant=finance"
}
```

Sem stream: `{"active":false}`.

### 11.6 `stream.end` — `usage` e `quota`

```json
{
  "message_id": "01a0b16e-c61d-7842-a86a-29387130f624",
  "citations": [],
  "suggestions": [],
  "metadata": {
    "usage": {
      "input_tokens": 39174,
      "output_tokens": 617,
      "embedding_tokens": 0,
      "cache_read_tokens": 25728,
      "cache_creation_tokens": 0,
      "total_tokens": 39791,
      "calls": [
        {"input_tokens": 3799, "output_tokens": 47, "cache_read_tokens": 3328, "model": "gpt-5.4-mini-2026-03-17", "provider": "openai"},
        {"input_tokens": 13896, "output_tokens": 309, "cache_read_tokens": 13440, "model": "gpt-5.4-mini-2026-03-17", "provider": "openai"},
        {"input_tokens": 14248, "output_tokens": 196, "cache_read_tokens": 8960, "model": "gpt-5.4-mini-2026-03-17", "provider": "openai"},
        {"input_tokens": 1652, "output_tokens": 46, "model": "gpt-5.4-nano-2026-03-17", "provider": "openai"},
        {"input_tokens": 5579, "output_tokens": 19, "model": "gpt-5.4-nano-2026-03-17", "provider": "openai"}
      ],
      "model": "gpt-5.4-nano-2026-03-17",
      "provider": "openai"
    },
    "quota": {"limit_tokens": 100000, "used_tokens": 4269}
  }
}
```

Captura da `quota` com os cinco campos completos e captura de quota excedida (negativa):

```json
{"limit_tokens":100000,"used_tokens":35530,"remaining_tokens":64470,"period_seconds":86400,"reset_after_seconds":86371.68883538246}
```

```json
{"limit_tokens":100000,"used_tokens":131363,"remaining_tokens":-31363,"reset_after_seconds":86362.63}
```

### 11.7 `409 duplicate_request` — idempotência

```json
{
  "error": "duplicate_request",
  "message": "A request with this idempotency_key was already processed",
  "session_id": "01a0b16d-bbd2-771a-a6fd-b95e3834e5d3",
  "user_message_id": "01a0b16d-bcef-7c76-ba82-7f9e4ad86999",
  "message_id": "01a0b16d-bcef-7c76-ba82-7f9f32b05993"
}
```

### 11.8 `POST /feedback` — recibo e rejeição de enum

```json
{"message_id": "01a0b507-904e-7e6c-9db5-4963a9522f4c", "rating": 1, "recorded_at": "2026-09-18T14:59:29.401Z", "overwritten": false}
```

```json
{"error": "not_accepted", "message": "Field 'reason' on form 'thumbs_down': Value 'inaccurate' is not one of the accepted values."}
```

### 11.9 `429 quota_exceeded` — sem cookie

```json
{"code":"quota_exceeded","message":"Token quota exceeded","request_id":"fd97b9eb-bb17-466a-8ae0-db426fdd6dba"}
```

### 11.10 Formas de erro do Promenade

```json
{"code":"invalid_request","message":"Request validation failed: /: Expected object, received null","request_id":"24bf2312-..."}
```

```json
{"error":"missing_identity","message":"User identity required. Please log in."}
```

```json
{"error":"session_not_found","message":"Session not found"}
```

```json
{"code":"not_found","message":"Not found.","request_id":"..."}
```

### 11.11 Formas de erro do MAD

```json
{"detail": "Symbol not found for ZZZZZZ"}
```

```json
{"detail": "Article skipped: Skipped: provider 'Motley Fool' not in allowed tiers (Yahoo Finance, Yahoo Personal Finance, Tier 1, or Tier 2)"}
```

```json
{"detail": "The chat API has been retired."}
```

```json
{"detail": "Authentication required. Missing or empty x-txn-token header."}
```

```json
{"detail": [{"type": "too_short", "loc": ["body", "article_uuids"],
             "msg": "List should have at least 1 item after validation, not 0",
             "input": [], "ctx": {"field_type": "L..."}}]}
```

```json
{"detail": "unknown portfolio_id: 'abc123' (no holdings supplied)"}
```

## 12. Metodologia — como reproduzir a engenharia reversa

Esta seção documenta o método usado para produzir o contrato acima, de forma reproduzível: captura do bundle → desofuscação integral → localização do cliente de rede → reconstrução do contrato → validação ao vivo → revalidação por diff.

### 12.1 Aquisição e desofuscação do bundle

1. **Capturar a totalidade real do código.** O bundler usa *code-splitting*: rotas não visitadas contêm módulos que nunca chegam ao disco de quem só navega. Capturar a matriz de rotas (cada página renderizada revela seus `nodes/` e `chunks/`) e o manifesto do downloader (SHA-256 por arquivo) — o HTML de `/quote/AAPL` embarca o `entry/start` + `entry/app` e o mapa de serviços; as rotas `/ai-playground` e `/ai/[symbol]/[section]` puxam os nodes das superfícies de IA. `_service-worker.js` na raiz lista o precache completo do app — atalho para o inventário.
2. **Desofuscar o corpus INTEIRO antes de analisar.** Saída do SvelteKit 2 + Vite: minificação terser/esbuild, sem ofuscação de string-array — Webcrack resolve (mecânica: unminify + renomeação). Por chunk: `npx webcrack <arquivo> -m --no-unpack` (a árvore SvelteKit não é bundle de módulos clássico: `--no-unpack` evita divisão falsa; `-m` renomeia locais). Varrer `chunks/` + `nodes/` inteiros com concorrência limitada e validar cada saída com `node --check` (Node ≥ 22 detecta ESM em `.js` — **não** usar `vm.Script`, que compila com goal de script e falha em todo módulo com `import`). O `entry/app` concentra `__vite__mapDeps`, o manifesto de rotas (`dictionary`/`nodes`/`matchers`) e o `Root` — extrair o dicionário de rotas para mapear node → rota.
3. **Manter procedência.** Bundle original intocável (forense); toda saída em árvore espelhada; citações verbatim anotadas com o chunk de origem.

### 12.2 Localizar o cliente de rede

- **Chunks nomeados preservam papéis** — `loadTickerAnalysisForSymbol`, `loadDigDeeperQuestions`, `loadChatResponse`, `loadChatRateLimits`, `loadDynamicSeededQuestions` são os loaders; o cliente do chat vive num chunk de nome não descritivo que migra entre deploys. Os nomes não são estáveis: re-resolver a cada build.
- **Âncoras que sobrevivem à minificação** (grep no corpus desofuscado): paths de rota (`/ws/mad/v2/`, `/sessions`, `/chat/seeds`), `perfLabel` (`loadChatResponse`, `scout.chat.resume`, `loadTickerAnalysisForSymbol`), feature flags (`enableScout*`, `enableQSP*`, `enableTxnToken`), strings de erro dedicadas (`ScoutQuotaExceededError`, `duplicate_request`, `Bad request: pathname is required`), hosts literais (`promenade-api.search.yahoo.com`) e chaves de serviço (`scout`/`scoutDev`/`financeProd`/`financeStage`).
- **Subir do consumidor para o cliente:** os consumidores (`AiAnalystSheet`, `Dock`, `DigDeeperAiSheet`, nodes de página) importam o chunk do cliente — `grep` pelo nome do arquivo revela a cadeia de imports e os exports usados (`l` = chat, `d` = sondagem, `r` = retomada, `S` = tenant...). Descer do cliente para a camada: o descritor `{key, pathname, query, timeout}` é passado ao `fetchService` (`quoteUtil`) — aí vivem os defaults (`credentials`, `crumb: false`, `disableDefaultQueries`, timeouts).
- **Separar contrato vivo de código fóssil:** código presente no bundle não implica rota viva — a família `/ws/mad/v2/chat` sobrevive inteira no cliente e responde **410**; flags default `false` (`enableScreenersNlsMad`, `enableTxnToken`) marcam rotas dormentes. O wire decide.

### 12.3 Reconstruir um contrato

Para cada rota, fechar a cadeia completa antes de documentar:

1. **Path + método + chave de serviço** — do descritor do loader (literal no bundle).
2. **Host** — resolver a chave no config de serviços embutido no HTML (`/xhr/config?name=services` chega nos blocos `data-sveltekit-fetched`); staging muda chave, não shape.
3. **Query/body** — do builder do loader: campos fixos, opcionais, defaults e normalizações (`Lt` → `undefined` quando vazio; `encodeURIComponent` nos paths com variável).
4. **Cabeçalhos especiais e gates** — condicionais de flag (`ynet === "1"`, `enableTickerAnalysisStagingApi`), gates de identidade (`authed === "1"`), headers extras (`X-Sas-Enforce-Quota`, `x-txn-token`).
5. **Parser da resposta** — a função que normaliza o envelope no cliente define o contrato mínimo: campos exigidos, descartados, renomeados, defaults (ex.: fontes sem `title`/`url` descartadas; `suggestions` ≡ `follow_up_questions`).
6. **Erros dedicados** — classes/ramos de exceção do cliente (`ScoutQuotaExceededError`, `409 duplicate_request`) revelam estados que o servidor produz.

### 12.4 Validação e prova

- **Provação por erro de schema (422)**: valores inválidos deliberados revelam o esquema server-side mesmo com o handler em falha — enum, pattern, teto por rota saem das mensagens Pydantic.
- **Contrastes controlados**: mesma requisição anônima × com `A3` × com header extra; mesmo símbolo em rotas irmã; par crumb cruzado quando aplicável. Uma diferença só entra no documento com o contraste que a isola.
- **Estados especiais como contrato**: 204 (geração assíncrona), 410 (aposentada), 403 (escrita anônima), 502 por shard — reproduzir antes de registrar.
- **Probes mínimos e reexecutáveis**: um script por família, stdlib, dois modos (REPL + subcomando), retry apenas nos erros declarados transitórios.
- **Revalidação por diff estrutural entre builds**: comparar manifestos (arquivos novos/removidos) e assinaturas (strings de contrato, constantes, grafos de import). Módulo migrou → atualizar a referência e re-ler o destino; assinatura e chamada inalteradas → revalidar com o probe e seguir. Sempre confrontar o documento contra o build novo **antes** de qualquer edição.

### 12.5 Armadilhas recorrentes

- **Nomes de chunk/node mudam a cada deploy** — cite papéis, não nomes, e re-resolve por âncora de string a cada build.
- **Extração de catálogos por regex sangra**: entradas curtas sem `title`/`summary` fazem a janela capturar o entry seguinte — cortar no início do próximo objeto delimitador (`slug:{uuid:`).
- **Escapes no wire**: o Dig Deeper entrega `\n` literais (2 caracteres); fontes chegam com entidades HTML não decodificadas — normalizar no cliente, não assumir texto pronto.
- **Ferramentas**: `node --check` para validar ESM; `vm.Script` não serve para módulos; scripts de renomeação/parse escritos via shell inline perdem escapes de regex (JSON → bash → JS) — escrever o script em arquivo antes de executar.
- **O download pode MISTURAR builds**: o bundle de 2026-11-05 carregava dois `entry/app.*.js` com hashes diferentes (o principal, importado pelo `start`, e um residual de outra navegação). Antes de indexar o dicionário, confirme qual `app` o `start.*.js` importa; chunks órfãos do build residual poluem greps globais (grep por âncora no app errado = falso negativo).
- **Rota viva sem cliente (o inverso do código fóssil)**: o Dig Deeper foi removido do frontend no build de 2026-11-05 e a rota `/ws/mad/v2/articles_ddq/*` continua viva no wire (§3.3) — ausência no bundle NÃO é aposentadoria de rota; o wire decide nos dois sentidos.
- **O bundle não é a verdade final**: ele mostra onde olhar e o que o cliente espera; o servidor sob requisições de borda determina o contrato real. Nenhuma afirmação entra no documento sem os dois lados (código lido + probe), e o que só existe no cliente é rotulado como contrato de cliente (ex.: `total_cost`, `total_queue_time`, `maxLength` de mensagem).
- **Modelos de IA são observação, não contrato**: os identificadores chegam no `stream.end` e mudam sem aviso (§5.9) — telemetria sim, chaveamento não.

---

*Referências dos arquivos analisados*

- `chunks/[cliente-scout].[hash].js` — cliente do Scout: criação de sessão, corpo do `/chat`, cabeçalho de quota, parser SSE (resolução dupla do discriminador de evento), eventos, extração de `grounding_sources`/`follow_up`/`actions`/`usage`/`quota`, limpeza de citações, tenant `"finance"`, mapeamento `scout`/`scoutDev`, sondagem `/sessions/{id}/active-stream` e retomada `/chat/resume/{stream_id}` com tratamento `409 duplicate_request`; erros dedicados `ScoutQuotaExceededError`, `ScoutDuplicateRequestError`, `ScoutNoActiveStreamError`
- `chunks/[quoteUtil].[hash].js` — camada de serviço compartilhada (`fetchService`): resolução `config.getState().services[key]` → host, `crumb` default `false`, `credentials: "include"`, `disableDefaultQueries` (sem `lang`/`region`), reescrita `/xhr/service` por `serverKey` gateada por `window._nimbus.ready`
- `chunks/[loadChatResponse].[hash].js` — carregador `loadChatResponse` do chat aposentado: POST, query `chat_version`/`use_fargate`, corpo `{question, symbol, initial_context}`, polling da rota de pergunta; default `chat_version = "v11"` (export `D`, residente em `chunks/[room_service].[hash].js`, importado como `{D as v}`)
- `chunks/[loadChatRateLimits].[hash].js` — carregador de `/ws/mad/v2/chat/rate_limit`, gates `authed`/`enableQSPAiAnalystSheetChat`/`enableDigDeeperArticleChat`, helpers de `remaining`/`time_to_refill`; co-localiza o wrapper do sheet (scroll anchoring por `data-section-id`), o resumo colapsável de etapas (`is_user_facing`), o banner de rate limit (erro em `remaining === 0`, aviso em `<= 5`) e o banner de sign-in (`askAi=1`)
- `chunks/[loadTickerAnalysisForSymbol].[hash].js` — loader do AI Analyst: path `/ws/mad/v2/analyst/symbol/{symbol}`, chaves `financeProd`/`financeStage`, `debug_flag`, allowlists de símbolos, mapeamento dos campos da resposta, renderizadores Markdown
- `chunks/[loadCGCustomStoryList].[hash].js` — resolvedor de fontes do *Nexus Gateway* (`getCustomStoryList`, `assetLookups`)
- `chunks/[utils].[hash].js` — catálogo de operações GraphQL do *Nexus Gateway* (`getCustomStoryList`, `getFinanceArticleContent`, `getFinanceTopicStream`, `getAuthorFeed`, ...)
- `chunks/[loadDigDeeperQuestions].[hash].js` — carregadores `loadDigDeeperQuestions` e `loadDigDeeperAnswer`, sanitização DOMPurify, renumeração de citações, transform de links com guarda `asset://`, chave `finance`/`financeStage`, constante `portfolio-analysis`
- `chunks/[ramen_dining].[hash].js` — validação de UUID usada nos guards do Dig Deeper (regex RFC 4122 + variante nula)
- `chunks/[catalogo-temas].[hash].js` — catálogo canônico de temas curados (26 slugs com UUID, batch, legacyFallback, title/summary/ranking) e redirects `/markets/topic/{slug}`
- `chunks/[AiAnalystSheet].[hash].js` — painel AI Analyst: consumo do chat (callbacks e textos de etapa locais), escolha streaming × não-streaming, renderização LaTeX (`math`/`mathInline`), eventos de analytics `answerLoaded`/`answerError` com `subsec: "chat"`
- `chunks/[Dock].[hash].js` — painel de chat da home: uso amplo do cliente, infraestrutura de sessão/quota/handoff (`sessionStorage`), catálogo de prompts do painel vazio (Fisher–Yates), paginação de sessões (`next_cursor`)
- `chunks/[TickerAIInsight].[hash].js` — categorias de insight por ticker (`earnings-call-insights`, `earnings-insights`, `insider-activity`) e campo `tickerAIInsights`
- `chunks/[AiAnalystHybridBanner].[hash].js` — banner de chat do quote (`WHATS_HAPPENING_WITH_TICKER_TODAY`, `dig-deeper-question`)
- `chunks/[AiResearchReport].[hash].js` — relatório de IA por seções: fontes em tiers com badges, tabela de revisões de price targets, gauge de consenso (`financialData.recommendationKey` × `targets`) e cenários BEAR/BASE/BULL sobre holdings; consome o AI Analyst e o quoteSummary na mesma folha
- `chunks/[AiAnalystSheetTriggerButton].[hash].js` — gatilho de entrada do painel: gate por símbolo via export do loader do AI Analyst, tooltip de onboarding (FeatureCue `aiAnalystSheetFeatureCueState`), telemetria GA gateada por `enableScoutChatGaEvents`
- `chunks/[sources].[hash].js` — dedupe/corte das referências (máx. 10), badges por provedor e componente de fontes compartilhado entre as folhas de IA
- `chunks/[related-content].[hash].js` — painel de conteúdo relacionado de artigos: embute o Dig Deeper (carregadores, PromptCard, feedback, dispatcher de insights)
- `chunks/[dig-deeper-artigo].[hash].js` — página do artigo + adaptador do chat de artigo sobre a família aposentada: seleção `chat_version` (`v14` com flag / `v11`), `initial_context` com `article_uuids` em JSON, conversão da resposta em envelope DDQ (`source: "llm"`, fontes com ids `ddq-chat-ref-{i}` quando sem uuid) e textos de etapa por modo (`ANALYZING_THE_ARTICLE` / `REVIEWING_YOUR_PORTFOLIO` / `ANALYZING_MARKET_CONDITIONS` / `CHECKING_OTHER_SOURCES` / `GENERATING_THE_RESPONSE`)
- `chunks/[portfolio-analyze-button].[hash].js` — botão "Analyze" das páginas de portfólio: `scoutPrompt`/`portfolioId`/`portfolioName`, telemetria `sec: "portfolio"`
- `chunks/[key-metrics].[hash].js` / `chunks/[watchlist-insights].[hash].js` — superfícies de portfólio/watchlist que consomem o dispatcher de insights (§3.5)
- `chunks/[dynamic-questions-support].[hash].js` — registros de suporte a perguntas dinâmicas por quoteType (ETF/INDEX/MUTUALFUND: flag + conjunto de tickers; ranqueamento `random` vs `ts_ranked`)
- `nodes/[research-reports].[hash].js` — rota `/quote/[symbol]/research-reports` com a flag `enableAiResearchReport` (§9.6)
- `nodes/[ticker-insight-pages].[hash].js` — páginas de quote e sub-rotas que embutem o `TickerAIInsight` (ficha e abas de análise/estatísticas)
- `chunks/[DigDeeperAiSheet].[hash].js` — sheet de artigo com `variant: "dig-deeper"`; modos artigo e portfólio; store de contexto do Dig Deeper (`questionMap`/`answerMap`/`sourcesMap`)
- `chunks/[DigDeeperQuestions].[hash].js` — módulo "Dig deeper" de artigos: cartões de pergunta com deep link `/__ai/scout/chat?prompt=...&uuid=...` no modo nativo de webview (`enableArticleDdqNativeChat`)
- `chunks/[scoutFeedback].[hash].js` — banner de feedback (formulários internos `http://yo/yf-scout-feedback-form` e `http://yo/yf-article-chat-feedback-form`)
- `chunks/[configs].[hash].js` — registro central de categorias de insight
- `chunks/[shopping_cart].[hash].js` / `chunks/[local_offer].[hash].js` / `chunks/[local_mall].[hash].js` — mapeamento de classificações editoriais para slugs de tema (`"energy/oil-gas": "oil-gas"` e pares irmãos), estado do chat (`role` `"user"`/`"scoutReply"`) e guardas de entrada do Scout
- `chunks/[initializePage].[hash].js` — bootstrap de crumb (sentinel `MOCK_CRUMB`)
- `chunks/[room_service].[hash].js` — default `chat_version = "v11"` (export `D`)
- `nodes/[playground].[hash].js` — página AI Playground (rota `/ai-playground`): hosts Promenade literais, aliases de telemetria Langfuse (`langfuse-proxy-yf-scout-prod`/`-nonprod`), construção de `context` (`ticker:`, `article_uuid:`), persistência de variantes, painéis lado a lado, oito carregadores da família `themes`, valores de `window`/`topic_type`, telemetria `langfuseTracingUrl`/`lastUsage`
- `nodes/[ai-analyst-route].[hash].js` — rota `/ai/[symbol]/[section]` do AI Analyst (webview; carrega o sheet via `enableQSPAiAnalystSheet` + `enableQSPAiAnalystSheetWebview`)
- `nodes/[transcript].[hash].js` — página da transcrição de earnings call: carregador `/ws/mad/v2/analyst/ect`, loader `/xhr/transcript`, gate `enableEarningsTranscript`
- `nodes/[research-hub].[hash].js` — screener do research-hub com integração Scout (`closeAskScout`) e seleção de rota NLS (`enableScreenersNlsMad`/`enableScreenersNlsStaging`)
- `nodes/[config-default].[hash].js` — config default da página com a flag `enableTxnToken: false`
- `entry/[app].[hash].js` — manifesto de rotas (`/(app)/ai/[symbol]/[section]`, `/ai-playground`) e constantes de prefixo (`__ai`, `__data.json`)


