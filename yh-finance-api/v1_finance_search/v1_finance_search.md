# Engenharia Reversa — Endpoint `GET /v1/finance/search`

Requisição ❌ `Anônimo` — sem cookie, sem crumb, sem qualquer credencial. Método `GET`; hosts válidos `query1.finance.yahoo.com` / `query2.finance.yahoo.com` (o staging `iquery-stage.finance.yahoo.com` é referenciado pelo bundle mas não é alcançável publicamente). A única exigência da borda é `User-Agent` de navegador — UA genérico (`python-requests` default) devolve `429` texto puro da edge.

O endpoint é o **motor de busca universal do aplicativo**: uma única chamada resolve, em paralelo, símbolos de instrumentos, empresas privadas (Crunchbase), notícias, listas/screeners pré-definidos, relatórios de pesquisa e atalhos de navegação. É o typeahead de cada caixa de busca do site — cabeçalho (`ybar`), dock inferior, comparador, tela cheia e filtros do screener — além do resolvedor de logos por nome de empresa. A resposta é um envelope **plano** (sem wrapper de domínio no sucesso), com categorias independentes e um painel de telemetria interna de 11 temporizadores de subsistemas.

---

## 1. Visão geral e papel no aplicativo

O módulo de busca vive fora do bundle SvelteKit: é um script **webcore** autônomo (`srchjs`), carregado em todas as páginas, que escaneia `<form>` marcados com o atributo `data-finsrch` e os transforma em caixas de typeahead. O HTML real marca dois forms por página — o cabeçalho com `data-finsrch="researchReports"` (`#ybar-sf`, `action="/lookup"`) e o dock inferior com `data-finsrch="quote"`. O bundle SvelteKit participa por duas vias: um wrapper de componente (`Autocomplete`) que delega ao mesmo objeto global `window.FinSearch` com configuração estendida, e os filtros do research-hub, que mapeiam campos de screener para variantes desse wrapper. Um quarto consumidor independente monta a URL na mão para resolver logos de provedores.

| Contexto de Uso | Arquivo Base / Chunk | Identificador / Função Lógica | Como chama |
| :--- | :--- | :--- | :--- |
| Caixa de busca do cabeçalho (`ybar`) | `webcore/srchjs/1.2.50/js/finSearch.modern.js` | FinSearchJS (classe `ot`), contexto `researchReports` | `V()` monta URL, host sorteado query1/query2, `fetch` cors + `credentials: "include"` |
| Caixa de busca do dock inferior | `webcore/srchjs/1.2.50/js/finSearch.modern.js` | FinSearchJS, contexto `quote` | idem |
| Wrapper de autocomplete (comparador, tela cheia, screener, holders) | `chunks/Autocomplete.[hash].js` | componente `$e` → `window.FinSearch.initSearchForm({searchConfig})` | variantes `all` / `compare` / `quote` / `researchReports` / `instituationalHolders` / `screener` |
| Filtros do screener (research-hub) | `chunks/FiltersSelector.[hash].js` | mapa `f` de id de filtro → variante (`top_fund_holder_names` → `instituationalHolders`; `ticker`/`exchange` → `screener`) | via Autocomplete com `includeTypes = assetType` |
| Resolução de logos de provedores | `chunks/providerLogos.[hash].js` | `as` (`fetchSearchData`) | `new URL("https://query2.finance.yahoo.com/v1/finance/search")` hardcoded, `fetch` sem credentials |

```js
// HTML real das paginas — os dois forms que o FinSearchJS captura:
<form role="search" id="ybar-sf" action="/lookup" method="get" data-finsrch="researchReports" ...>
<form data-finsrch="quote" role="search" class="dock-srch" ...>
```

### 1.1 Arquitetura de referência

1. **Camada de Apresentação / Captura:** FinSearchJS (`webcore/srchjs/1.2.50/js/finSearch.modern.js`) — escaneia forms `data-finsrch`, anexa listeners de input com debounce e renderiza as listas de sugestão.
2. **Camada de Montagem:** `V` (mesmo arquivo) — injeta `q`/`lang`/`region` + o preset do contexto (`B`), serializa apenas primitivos e sorteia o host do pool.
3. **Camada de Transporte / Fetch:** `Y` (mesmo arquivo) — `fetch` com `mode: "cors"`, `credentials: "include"` e timeout de 1500 ms; fallback para `XMLHttpRequest` com `withCredentials`.
4. **Camada de Recomendações:** `W` / `$` / `fetchStockStoryTopPicks` (mesmo arquivo) — endpoints irmãos (`/v1/finance/trending`, `/v1/finance/screener/predefined/saved`, `/v1/finance/stockstories/top-weekly-high-quality-tickers`) que alimentam o estado inicial da caixa vazia (não fazem parte deste endpoint).

### 1.2 Ciclo de vida

```
[ Keystroke no input do form data-finsrch ]
                    │
                    ▼
[ Debounce — atributo data-debounce do form, default 150 ms ]
                    │
                    ▼
[ handleInput: trim; vazio → recomendações em cache, zero rede ]
                    │
                    ▼
[ fetchSuggestions: encodeURIComponent(query) → V({type, query, config}) ]
                    │
                    ▼
[ V: base {q, lang, region} + preset B[type] + overrides do config ]
  (só string/number/boolean entram na querystring; objetos descartados)
                    │
                    ▼
[ Y: fetch cors + credentials include — timeout 1500 ms (XHR como fallback) ]
                    │
                    ▼
[ Resposta carimbrada com timestamp do DISPATCH no cliente ]
                    │
                    ▼
[ deliverSearchResults: descarta resposta se timestamp < lastResultsTimestamp ]
  (deduplicação de respostas fora de ordem por keystroke)
                    │
                    ▼
[ Render por categorias do contexto — P[type] = [nav, quotes, news, lists...] ]
```

### 1.3 Otimizações do loader

- **Debounce configurável por DOM:** o intervalo vem do atributo `data-debounce` do form (default 150 ms quando ausente) — cada caixa pode ter seu próprio ritmo.
- **Deduplicação de corrida por timestamp:** o transporte carimba `Date.now()` do momento do dispatch na resposta; `deliverSearchResults` descarta qualquer resposta cujo timestamp seja anterior ao último entregue — keystrokes rápidos não renderizam resultados velhos por cima dos novos.
- **Timeout curto e único tentativa:** 1500 ms para autocomplete (o usuário digita de novo em segundos; retry não vale a rede) — os endpoints de recomendação usam 2000 ms.
- **Fallback de transporte:** se `window.fetch` não existir, o mesmo `Y` reenvia por `XMLHttpRequest` com `withCredentials = true` e `n.timeout`.
- **Estado inicial sem rede:** recomendações (trending) podem ser injetadas por props pelo wrapper SvelteKit — a caixa vazia renderiza sem nenhuma chamada a este endpoint; só a digitação dispara rede.
- **Sem cache de resultados de busca:** nenhuma store memoíza respostas por query — o cache é exclusivo do edge (`max-age=600`).

---

## 2. Especificação do Protocolo Wire (Request)

### 2.1 Linha de requisição

```http
GET /v1/finance/search?q=Apple&lang=en-US&region=US&quotesCount=6&newsCount=4&enableFuzzyQuery=false&quotesQueryId=tss_match_phrase_query&multiQuoteQueryId=multi_quote_single_token_query&newsQueryId=news_cie_vespa&enableCb=true&enableNavLinks=true&enableEnhancedTrivialQuery=true&enableCulturalAssets=true&enableLogoUrl=true&enableLists=false&enableNcgNews=true HTTP/2
Host: query1.finance.yahoo.com
```

A rota não tem segmento de path variável — todo o contrato vive na querystring. A ordem dos parâmetros acima é a ordem de inserção real do construtor oficial (`q`, `lang`, `region`, depois os campos do preset do contexto, por fim os overrides do `config`).

### 2.2 Hosts válidos

| Host | Papel | Evidência no Bundle |
| :--- | :--- | :--- |
| `https://query1.finance.yahoo.com` | Pool de produção, sorteado por requisição | `webcore/srchjs/1.2.50/js/finSearch.modern.js` (`s.prod`, seletor `q`) |
| `https://query2.finance.yahoo.com` | Pool de produção, sorteado por requisição; host hardcoded do resolvedor de logos | idem (`s.prod`); `chunks/providerLogos.[hash].js` (`as`) |
| `https://iquery-stage.finance.yahoo.com` | Staging — selecionado quando `useStaging`/`enableStagingSearch` | `webcore/srchjs/1.2.50/js/finSearch.modern.js` (`s.stage`) |

O seletor de host é **aleatório uniforme por chamada** (`Math.floor(Math.random() * s[t].length)`), não round-robin nem failover. O staging recusa conexão fora da rede interna da operação (TCP recusado publicamente).

### 2.3 Cabeçalhos críticos da requisição

| Header | Valor exigido / recomendado | Efeito de ausência / erro |
| :--- | :--- | :--- |
| `User-Agent` | Perfil de browser recente | UA genérico (`python-requests` default) → `429` texto puro `Edge: Too Many Requests`; fingerprint TLS **não** é exigida (cliente HTTP puro + UA de browser responde 200) |
| `Accept` | `application/json` ou `*/*` | Tolerante — sem gating de Accept observado |
| `Cookie` | — | Ausência não altera a resposta (endpoint anônimo; a edge oferece `Set-Cookie: A1=...` na resposta, mas nenhum cookie é exigido na ida) |
| `x-crumb` | — | Sem efeito — o parâmetro `crumb` na query é integralmente ignorado (200 com crumb garbage) |
| `Origin` | `https://finance.yahoo.com` | Só relevante para CORS de browser (ver §8.4) |

```
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36
Accept: application/json
```

### 2.4 Timeouts do cliente oficial

| Medição | Valor | Fonte |
| :--- | :---: | :--- |
| Timeout do autocomplete | `1500 ms` | `webcore/srchjs/1.2.50/js/finSearch.modern.js` (default de `Y`) |
| Timeout dos endpoints de recomendação (irmãos) | `2000 ms` | idem (constante `timeout`, usada por `W`/`$`/stockStory) |
| Retry | 0 — tentativa única | `Y` não tem loop de retry; erro vira beacon de telemetria e rejeição |
| Cache TTL do edge | `max-age=600` + `stale-while-revalidate=180` | `cache-control` observado na resposta (ver §8.5) |

### 2.5 Exemplo de requisição completa

```bash
# Contexto all — a query completa que o FinSearchJS monta para "Apple":
curl -s \
  -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36" \
  -H "Accept: application/json" \
  "https://query1.finance.yahoo.com/v1/finance/search?q=Apple&lang=en-US&region=US&quotesCount=6&newsCount=4&enableFuzzyQuery=false&quotesQueryId=tss_match_phrase_query&multiQuoteQueryId=multi_quote_single_token_query&newsQueryId=news_cie_vespa&enableCb=true&enableNavLinks=true&enableEnhancedTrivialQuery=true&enableCulturalAssets=true&enableLogoUrl=true&enableLists=false&enableNcgNews=true"

# Contrato mínimo — apenas q (devolve o envelope com counts default do servidor):
curl -s \
  -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36" \
  "https://query1.finance.yahoo.com/v1/finance/search?q=AAPL"

# Modo multiquote — vírgula resolve símbolos exatos em lote (nav MULTIQUOTE na volta):
curl -s \
  -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36" \
  "https://query1.finance.yahoo.com/v1/finance/search?q=AAPL,MSFT"

# Filtro por classe (resolvedor de logos) — só EQUITY:
curl -s \
  -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36" \
  "https://query1.finance.yahoo.com/v1/finance/search?q=AAPL&lang=en-US&region=US&quotesCount=6&includeTypes=equity"
```

Nenhuma etapa de bootstrap de credencial é necessária — não há cookie a capturar nem crumb a emitir.

---

## 3. Parâmetros

| Parâmetro | Tipo | Obrigatório | Padrão | Validação Client-Side | Depende de Feature Flag? | Comportamento e casos de borda |
| :--- | :---: | :---: | :---: | :--- | :---: | :--- |
| `q` | string | Sim | — | `trim()` + `encodeURIComponent` antes de montar a URL | Não | Termo de busca. Ausente ou vazio → `400` `Missing required query parameter=q`. **Case-insensitive** (`aapl` ≡ `AAPL`). **Vírgula ativa o modo multiquote**: resolução exata de símbolos em lote (`AAPL,MSFT` → 2 quotes + `nav` `{navType: "MULTIQUOTE", symbols}`), sem tolerância a erros de digitação. **Espaços não fazem multiquote**: `AAPL MSFT NVDA` devolve count=0 (a frase inteira é o termo). Tolerância extrema a formato: 300 caracteres, `BRK.B`, `A/B`, espaço à esquerda e `^GSPC` (com encode) todos respondem 200. |
| `lang` | string | Não | `en-US` | — | Não | Injetado pelo montador (`window.finSearchContext.lang`). Efeito dominante: **seletor de idioma do subsistema de news** — `de-DE`/`fr-FR`/`es-ES`/`en-GB` devolvem notícias no idioma; `pt-BR` e `ja-JP` devolvem **zero notícias** (cobertura do índice de news, não erro). **O efeito exige o par coerente com `region`**: `lang=de-DE` com `region=US` devolve zero — só `de-DE`+`DE` materializa as notícias (idem `fr-FR`+`FR`, `es-ES`+`ES`, `en-GB`+`GB`). Valor inválido (`xx`) cai silenciosamente no default (`en-US`+`US`). |
| `region` | string | Não | `US` | — | Não | Injetado pelo montador. **Gate das notícias**: news só retornam com o par `lang`+`region` coerente e coberto (`en-US`+`US` → 8; `en-US`+`BR`/`en-US`+`DE` → **0**). **Ranking de quotes: sem efeito observado** — a posição de `PETR4.SA` em "Petrobras" (e de `VALE3.SA`/`ITUB4.SA`) é idêntica com `region=BR` e `region=US` (verificado; a alegação anterior de priorização por região não se reproduziu). Sem efeito em campos de instrumento. |
| `quotesCount` | int | Não | servidor devolve até 7 sem o parâmetro | — | Não | Limite **superior** do array `quotes` — mas o servidor impõe **cap duro de 7 itens no array total**: `quotesCount` de 25/50/100/1000 devolvem 7. Valores menores são respeitados. **Os CRUNCHBASE CONSUMEM SLOTS DO CAP** (teste controlado): `quotesCount=6` + `enableCb=true` (2 privados) → **5 instrumentos + 2 privados = 7**; `quotesCount=3` + 2 privados → 3+2 = 5 (abaixo do cap, count cheio); sem CBs, `quotesCount=6` → 6 instrumentos. O cap conta o array inteiro, não só os instrumentos. |
| `newsCount` | int | Não | ~6 sem o parâmetro | — | Não | Limite do array `news`; o retorno pode ser menor por deduplicação de disponíveis (`newsCount=4` → 3; `25` → 22; `100` → 46). `0` suprime news. |
| `listsCount` | int | Não | — | — | Não | Limite do array `lists`. A presença do parâmetro (com query que casa com listas, ex. `technology`) basta para a categoria aparecer — o gating por flag não se aplica aqui (ver `enableLists`). |
| `recommendCount` | int | Não | — | — | Não | **No-op observado**: consumidor enviado como 0, 4 ou 6 em nenhum caso materializou categoria alguma — o envelope de sucesso não tem seção de recomendações (as recomendações vêm de endpoint irmão `/v1/finance/trending`). |
| `researchReportsCount` | int | Não | — | — | Não | Enviado como `2` pelo wrapper de autocomplete com `enableResearchReports` ativo; observou-se retorno de 3 relatórios — limite superior, mesma semântica dos demais counts. |
| `screenerFieldCount` | int | Não | — | — | Não | Enviado como `10` pelos dois consumers do contexto institucional. Ver §8.3: o valor `10` combinado com o trio institucional do webcore e `enableCb=false` é o gatilho do `500`. |
| `enableCb` | bool | Não | `false` (ausente) | — | Não | **Injetor de empresas privadas (Crunchbase)**: `true` adiciona ao array `quotes` objetos com shape próprio (`index` UUID, `name`, `permalink`, `isYahooFinance: false`) — o array é polimórfico (§4.3). Ausente/`false` não injeta. |
| `enableNcgNews` | bool | Não | ligado | — | Não | **Chave-mestra do subsistema de news**: `false` zera `news` mesmo com `newsCount` alto; ausente ou `true` mantém. A cobertura por idioma ainda se aplica (ver `lang`). |
| `enableLogoUrl` | bool | Não | `false` (ausente) | — | Não | `true` popula o campo `logoUrl` dos quotes (CDN de marcas `s.yimg.com/lb/brands/`); `false`/ausente devolve o campo como `null` nos mesmos objetos. |
| `enableNavLinks` | bool | Não | ligado | — | Não | **Gate do `nav` observado** (teste controlado): `q=technology` devolve `nav` com 1 entrada sem a flag e com `=true`; com `=false` o `nav` volta **vazio** (`nav=[]`, inclusive com `listsCount` presente). A entrada de setor depende da semântica da query; a flag desliga a categoria. |
| `enableLists` | bool | Não | `false` | — | Não | **No-op server-side**: com `listsCount` presente, `lists` retorna idêntico com `enableLists=true` e com a flag ausente. |
| `enableCulturalAssets` | bool | Não | ligado | — | Não | Sem efeito observado no corpo — o temporizador interno `timeTakenForCulturalAssets` executa, mas nenhuma categoria muda entre `true`/`false` nas queries testadas. |
| `enableEnhancedTrivialQuery` | bool | Não | ligado | — | Não | Sem efeito observado no corpo (testado `false` contra ausente na mesma query — resposta equivalente). |
| `enableFuzzyQuery` | bool | Não | `false` | — | Não | `true` provoca **re-ranking sutil** dentro do array `quotes` (ordem de opções com prefixo igual se altera); a tolerância a erro de digitação do índice existe **independente** da flag — `Aple` retorna `APLE` com fuzzy ligado ou desligado. |
| `enableNews` | bool | Não | ligado | — | Não | Flag de supressão do contexto institucional — `false` zera a categoria news no cliente que a envia. |
| `enableQuotes` | bool | Não | ligado | — | Não | Flag de supressão do contexto institucional — `false` zera quotes na requisição do webcore. |
| `enableResearchReports` | bool | Não | `false` | — | Não | `true` ativa a categoria `researchReports` (3 relatórios para NVDA em uma query; presença depende do termo). |
| `enablePrivateCompany` | bool | Não | `false` | — | `enablePrivateCompany` | **No-op observado** no servidor — o controle efetivo de empresas privadas é `enableCb`; os consumers enviam ambos, só `enableCb` tem efeito. |
| `enableScreenerField` | bool | Não | `false` | — | Não | Ativa o subsistema `screenerFieldResults` — que retornou **vazio em todas as condições observadas** (ver §8.3). |
| `enableCccBoost` | bool | Não | `false` | — | `enableCccBoost` | Enviado como `true` pelo wrapper de autocomplete sob a feature flag homônima; nenhum efeito observado em resposta anônima. |
| `quotesQueryId` | string | Não | — | — | Não | Identificador do plano de query de símbolos — valor do bundle: `tss_match_phrase_query`. Valor inválido cai **silenciosamente no default** (mesma resposta, 200). |
| `multiQuoteQueryId` | string | Não | — | — | Não | Plano de query do modo multiquote — valor do bundle: `multi_quote_single_token_query`. Inválido idem. |
| `newsQueryId` | string | Não | — | — | Não | Plano de query de news — valor do bundle: `news_cie_vespa`. Inválido idem. |
| `screenerFieldName` | string | Não | — | — | Não | Nome do campo de screener para o contexto institucional — único valor observado no bundle: `top_fund_holder_names` (o mesmo id de filtro usado no research-hub). |
| `screenerFieldInstrumentType` | string | Não | — | — | Não | Tipo do instrumento do campo de screener. **Divergência entre consumers**: o webcore envia `institutional_interest`; o wrapper de autocomplete envia `equity`. A combinação do webcore com `screenerFieldCount=10` + `enableCb=false` produz `500` (§8.3). |
| `includeTypes` | string | Não | — | — | Não | Filtro de inclusão por classe do `quoteType` (lowercase): `equity` devolve só EQUITY (inclui BDRs/CEDEARs como `AAPL34.SA`, `AAPLC.BA`). Múltiplas classes por vírgula. |
| `excludeTypes` | string | Não | — | — | Não | Filtro de exclusão por classe: `equity,etf` remove ações e ETFs — sobram `OPTION`, `FUTURE` etc. Complementar ao `includeTypes`. |
| `crumb` | string | Não | — | — | Não | **Ignorado integralmente**: 200 idêntico com crumb válido, garbage e ausente. |
| *(qualquer outro)* | — | Não | — | — | — | Parâmetros desconhecidos (`foo=bar`) são descartados silenciosamente. |

---

## 4. Estrutura da Resposta

### 4.1 Envelope de sucesso — plano, sem wrapper de domínio

```json
{
  "quotes": [ { "symbol": "AAPL", "...": "..." } ],
  "news": [ { "uuid": "...", "title": "...", "...": "..." } ],
  "nav": [],
  "lists": [],
  "researchReports": [],
  "screenerFieldResults": [],
  "explains": [],
  "count": 10,
  "totalTime": 170,
  "timeTakenForQuotes": 420,
  "timeTakenForNews": 600,
  "timeTakenForAlgowatchlist": 0,
  "timeTakenForPredefinedScreener": 0,
  "timeTakenForCrunchbase": 400,
  "timeTakenForNav": 400,
  "timeTakenForResearchReports": 0,
  "timeTakenForQuestions": 0,
  "timeTakenForScreenerField": 0,
  "timeTakenForCulturalAssets": 750,
  "timeTakenForSearchLists": 0
}
```

O sucesso é um objeto raiz **plano**: as categorias (`quotes`, `news`, `nav`, `lists`, `researchReports`, `screenerFieldResults`), o array `explains` (vazio em todas as observações), o `count` (total de itens somando as categorias) e o painel de telemetria (`totalTime` + 11 `timeTakenFor*`, em milissegundos). Não há `finance.result` nem `error` no sucesso — o wrapper `finance` é exclusivo dos corpos de erro (§4.2). Os temporizadores revelam quais subsistemas internos o backend acionou para a query (por exemplo, `timeTakenForCrunchbase > 0` quando `enableCb=true` casou empresas privadas) e quais ficaram em zero.

### 4.2 Envelope de erro

Erros de validação e de método usam o wrapper genérico `finance`:

```json
{
  "finance": {
    "result": null,
    "error": {
      "code": "Bad Request",
      "description": "Missing required query parameter=q"
    }
  }
}
```

Duas classes de corpo de erro coexistem: erros de validação/método (400/405) em JSON com envelope `finance`, `content-type: application/json;charset=utf-8` e `cache-control: max-age=0, private`; e o erro 500 do subsistema institucional (§8.3) em **HTML puro** (página de error report do backend, `content-type: text/html;charset=utf-8`). Query sem correspondência **não é erro** — 200 com todas as categorias vazias e `count: 0`.

### 4.3 Polimorfismo do array `quotes`

O array `quotes` mistura dois shapes incompatíveis — instrumentos do Yahoo Finance e empresas privadas do Crunchbase (injetadas por `enableCb=true`):

```json
// Shape 1 — instrumento Yahoo Finance (isYahooFinance: true):
{
  "exchange": "NMS",
  "shortname": "Apple Inc.",
  "quoteType": "EQUITY",
  "symbol": "AAPL",
  "index": "quotes",
  "score": 516650.0,
  "typeDisp": "Equity",
  "longname": "Apple Inc.",
  "exchDisp": "NASDAQ",
  "sector": "Technology",
  "sectorDisp": "Technology",
  "industry": "Consumer Electronics",
  "industryDisp": "Consumer Electronics",
  "dispSecIndFlag": true,
  "logoUrl": "https://s.yimg.com/lb/brands/150x150_apple.png",
  "isYahooFinance": true
}

// Shape 2 — empresa privada Crunchbase (isYahooFinance: false):
{
  "index": "d8c1b54896db4e148d5bff7bdd4778d0",
  "name": "Apple Tree Partners",
  "permalink": "apple-tree-partners",
  "isYahooFinance": false
}
```

O discriminador é `isYahooFinance`: `true` → shape de instrumento completo (com `symbol`); `false` → registro do Crunchbase com `index` (UUID da base), `name` e `permalink` (slug da entidade) — **sem `symbol`, sem `exchange`, sem `quoteType`**. O cliente oficial renderiza os dois lado a lado na lista de símbolos; um reimplementador deve discriminar antes de acessar `symbol`.

---

## 5. Catálogo de campos

### 5.1 Objeto quote (instrumento)

Legenda de **Disp.**: `T` = sempre presente; `C` = presente por classe de instrumento; `D` = presença depende do dado.

| Campo | Disp. | Tipo | Descrição Funcional | Exemplo Real |
| :--- | :---: | :---: | :--- | :--- |
| `symbol` | T | `str` | Símbolo resolvido em caixa canônica | `"AAPL"` |
| `shortname` | T | `str` | Nome curto de exibição | `"Apple Inc."` |
| `quoteType` | T | `str` | Classe do instrumento — `EQUITY`, `ETF`, `FUTURE`, `OPTION`, `CRYPTOCURRENCY`... | `"EQUITY"` |
| `exchange` | T | `str` | Mic-code da bolsa emissora | `"NMS"` |
| `typeDisp` | T | `str` | Rótulo da classe para exibição | `"Equity"` |
| `index` | T | `str` | Marca da fonte do item | `"quotes"` |
| `score` | T | `float` | Score de ranking — escala com a aderência do termo (`AAPL` exato: ~2,58 × 10⁸; por nome `Apple`: ~5 × 10⁵; derivados: ~2 × 10⁴) | `516650.0` |
| `isYahooFinance` | T | `bool` | `true` para instrumento — o discriminador do polimorfismo | `true` |
| `longname` | D | `str` | Nome legal completo | `"Apple Inc."` |
| `exchDisp` | D | `str` | Nome de exibição da bolsa | `"NASDAQ"` |
| `sector` / `sectorDisp` | D | `str` | Setor da empresa | `"Technology"` |
| `industry` / `industryDisp` | D | `str` | Indústria da empresa | `"Consumer Electronics"` |
| `dispSecIndFlag` | D | `bool` | Se setor/indústria devem ser exibidos | `true` |
| `logoUrl` | D | `str` | Logo da marca — **só populado com `enableLogoUrl=true`**; `null` caso contrário | `"https://s.yimg.com/lb/brands/150x150_apple.png"` |

### 5.2 Objeto quote (empresa privada Crunchbase)

| Campo | Disp. | Tipo | Descrição Funcional | Exemplo Real |
| :--- | :---: | :---: | :--- | :--- |
| `index` | T | `str` | UUID do registro na base do Crunchbase | `"d8c1b54896db4e148d5bff7bdd4778d0"` |
| `name` | T | `str` | Nome da empresa privada | `"Apple Tree Partners"` |
| `permalink` | T | `str` | Slug da entidade | `"apple-tree-partners"` |
| `isYahooFinance` | T | `bool` | Sempre `false` — discriminador do polimorfismo | `false` |

### 5.3 Objeto news

| Campo | Disp. | Tipo | Descrição Funcional | Exemplo Real |
| :--- | :---: | :---: | :--- | :--- |
| `uuid` | T | `str` | Identificador universal da matéria (usado na URL canônica) | `"5f6e8554-d4a8-3f1c-bce8-2f5074e2e587"` |
| `title` | T | `str` | Manchete | `"Stock Market Today: ..."` |
| `publisher` | T | `str` | Veículo publicador | `"Investor's Business Daily"` |
| `link` | T | `str` | URL canônica da matéria no host | `"https://finance.yahoo.com/m/<uuid>/....html"` |
| `providerPublishTime` | T | `int` | Epoch de publicação em **segundos** | `1790887324` |
| `type` | T | `str` | Tipo do item — `STORY` observado | `"STORY"` |
| `thumbnail.resolutions[]` | D | `list` | Miniaturas — cada uma `{url, width, height, tag}` (tag `original` + resize) | `[{...140x140}, {...original}]` |
| `relatedTickers[]` | D | `list` | Símbolos citados na matéria | `["MU", "CL=F", "^GSPC", ...]` |

### 5.4 Objeto nav

Duas formas: o atalho estático `{navName, navUrl}` (ex. `{"navName": "Technology", "navUrl": "https://finance.yahoo.com/sectors/technology/"}`) e a marca de multiquote `{navType: "MULTIQUOTE", symbols: [...]}` que acompanha o modo vírgula. O mapa de navegação do cliente (`G` no webcore) converte `navType`/`navName` em rotas internas (`MULTIQUOTE` → `/quotes/AAPL,MSFT`; `EARNINGS_CALENDAR` → `/calendar/earnings`; `CURRENCIES` → `/currencies`; `YF_HOMEPAGE` → `/`; etc.).

### 5.5 Objeto lists

| Campo | Tipo | Descrição Funcional | Exemplo Real |
| :--- | :---: | :--- | :--- |
| `index` / `id` | `str` | UUID da lista (duplicado nas duas chaves) | `"6666a1fc-9b01-4398-..."` |
| `title` | `str` | Título de exibição | `"Technology Mutual Funds"` |
| `canonicalName` | `str` | Nome canônico do screener pré-definido | `"TECHNOLOGY_MUTUAL_FUNDS"` |
| `score` | `float` | Score de aderência | `1.0` |
| `type` | `str` | `PREDEFINED_SCREENER` observado | `"PREDEFINED_SCREENER"` |
| `total` | `int` | Total de instrumentos na lista | `160` |
| `isPremium` | `bool` | Se a lista é premium | `false` |
| `iconUrl` | `str` | Ícone da lista (resize do CDN mysterio) | `"https://edgecast-img..."` |

### 5.6 Objeto researchReports

| Campo | Tipo | Descrição Funcional | Exemplo Real |
| :--- | :---: | :--- | :--- |
| `reportHeadline` | `str` | Manchete do relatório | `"US Large Cap Pick List - September 2026"` |
| `reportDate` | `int` | Epoch de publicação em **milissegundos** (não confundir com o `providerPublishTime` de news, que é em segundos) | `1788973241000` |
| `id` | `str` | Identificador do relatório no provedor | `"MS_LargeCapU.S.CorePickList_StockPicks_1788973241000"` |
| `provider` | `str` | Provedor do relatório | `"Morningstar"` |

### 5.7 Campos que não retornam

| Campo / Parâmetro Citado | Veredito | Comportamento Real |
| :--- | :--- | :--- |
| `recommend` (categoria) | Não existe no envelope | O cliente tem título de seção `TRENDING` para recomendações, mas os dados vêm do endpoint irmão `/v1/finance/trending` — este endpoint nunca devolve recomendações, e `recommendCount` não cria a categoria. |
| `explains` | Array sempre vazio | Presente no envelope de todas as respostas observadas, sem itens em nenhuma condição de query/flags testada. |
| `screenerFieldResults` | Subsistema morto | Array vazio em **todas** as condições observadas — com nome/tipo válidos, counts variados e query de institucional com vastos holders (§8.3). |
| `quartrId`, calendário, fuso | Fora de escopo | Metadados de instrumento além dos listados em §5.1 não fazem parte da resposta — o endpoint devolve dados de busca, não ficha completa de instrumento. |

---

## 6. Matriz de presença por contexto de consumidor

Legenda: `✅` = categoria populável pelo contexto (verificada ao vivo); `—` = suprimida/vazia nas condições testadas. Colunas = presets reais dos consumers (§3 e §9).

| Categoria | `all` (padrão do módulo) | `researchReports` (cabeçalho ybar) | `quote` (dock) | `instituationalHolders` (webcore) | `instituationalHolders` (Autocomplete) | `screener`/`compare` (Autocomplete) | providerLogos |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `quotes` | ✅ (6 pedidos; cap 7 conta os CBs — ex. `Apple`: 5+2) | ✅ (idem) | ✅ (8) | — (enableQuotes=false) | — (enableQuotes=false) | ✅ (includeTypes) | ✅ (6, sem CB) |
| `news` | ✅ (4) | ✅ (3) | — (enableNews ausente/`false`) | — (enableNews=false) | — (enableNews=false) | — (enableNews=false) | — (enableNews=false) |
| `nav` | ✅ (por semântica) | ✅ (por semântica) | ✅ (por semântica) | — (enableNavLinks=false) | — (enableNavLinks=false) | ✅ (por semântica) | — (enableNavLinks=false) |
| `lists` | — (enableLists=false) | ✅ (2) | — | — | — | — | — |
| `researchReports` | — | ✅ (3) | — | — | — | — | — |
| `screenerFieldResults` | — | — | — | **500 do servidor** (§8.3) | vazio (200) | — | — |
| CB no `quotes` | ✅ | ✅ | — (enableCb=false) | — | — | — | — (enablePrivateCompany=false) |

A categoria `nav` **obedece** ao gate `enableNavLinks` (teste controlado com `q=technology`: ausente/`true` → 1 entrada de setor; `false` → `nav` vazio, inclusive com `listsCount` presente). Quando habilitada, a entrada depende da semântica do termo (`technology` → setor; `AAPL,MSFT` → `MULTIQUOTE`).

---

## 7. Erros e códigos de status

| HTTP | `code` | `description` | Corpo | Causa |
| :---: | :--- | :--- | :--- | :--- |
| `400` | `Bad Request` | `Missing required query parameter=q` | JSON envelope `finance` | `q` ausente ou vazio — único erro de validação da rota. |
| `405` | `Method Not Allowed` | `HTTP 405 Method Not Allowed` | JSON envelope `finance` | `POST`/`PUT` na rota. **Sem header `Allow`** na resposta. |
| `429` | — | `Edge: Too Many Requests` (texto puro, 23 B) | texto | UA genérico sem perfil de browser (bloqueio de edge por header, não por JA3/JA4). |
| `500` | — | `HTTP Status 500 - Internal Server Error` | **HTML** (error report do backend) | Combinação exata do preset institucional do webcore: `enableScreenerField=true` + `screenerFieldName` + `screenerFieldInstrumentType=institutional_interest` + `screenerFieldCount=10` + `enableCb=false` (§8.3). |
| `200` | — | — | JSON com categorias vazias, `count: 0` | Termo sem nenhuma correspondência (lixo de teclado, frase multi-token sem match) — **omissão silenciosa, não erro**. |

---

## 8. Comportamentos empíricos

### 8.1 Requisitos de borda, WAF e anti-bot

- **Inspeção de User-Agent:** a edge rejeita UA genérico com `429` texto puro — independente de cookie, crumb ou qualquer outra credencial. UA de browser é a única exigência.
- **Fingerprint TLS não é exigida:** cliente HTTP puro (sem impersonation) + UA de browser responde `200` — o bloqueio é por header, não por JA3/JA4.
- **Headers internos da resposta:** `server: ATS`, `y-rid: <id de request>`, `x-envoy-upstream-service-time` e `x-envoy-decorator-operation: finance-search--mtls-production-usw2.finance-k8s:4080/*` — o upstream é o microsserviço **`finance-search`** (cluster usw2), atrás de proxy envoy com mTLS interno; o header aparece em toda resposta 200, não apenas em erros.
- **Cookie de borda:** a resposta 200 carrega `Set-Cookie: A1=...` — a edge oferece o cookie de rastreio da família A, mas nenhuma chamada subsequente o exige.

### 8.2 Comportamentos silenciosos

- **Cap duro de 7 no array `quotes`:** para queries de altíssima correspondência (`A`, `US`, `SPDR`, `S&P`), `quotesCount` de 25/50/100/1000 devolvem **exatos 7 itens** em todos os casos — o limite do servidor é 7, não o valor pedido. O dock pede 8 e recebe no máximo 7.
- **`count` é a soma das categorias:** `count` = quotes + news + nav + lists + researchReports (+ CBs incluídos no quotes) — total de resultados do envelope, não de quotes.
- **Multiquote por vírgula é modo exato:** `q=AAPL,MSFT` devolve os dois símbolos exatos + `nav` `MULTIQUOTE` com os símbolos — sem ranking difuso. Espaço como separador **não** funciona (`AAPL MSFT NVDA` → count=0); `+` também não.
- **Case-insensitivity do termo:** `aapl` e `AAPL` devolvem o mesmo conjunto, na mesma ordem.
- **Cobertura de news pelo par `lang`+`region`:** pares coerentes e cobertos devolvem notícias no idioma (`de-DE`+`DE` → 6; `fr-FR`+`FR` → 6; `es-ES`+`ES` → 6; `en-GB`+`GB` → 6; `en-US`+`US` → 4–8); `pt-BR`+`BR` e `ja-JP`+`JP` devolvem **zero** (o índice não cobre o idioma); e qualquer par **incoerente** (`de-DE`+`US`, `en-US`+`BR`, `en-US`+`DE`) também devolve zero — o gate é o par, não o `lang` sozinho.
- **Locale inválido cai no default:** `lang=xx` + `region=ZZ` respondem 200 com o mesmo comportamento do default.
- **Tolerância de formato do termo:** 300 caracteres, `BRK.B`, `A/B`, espaço à esquerda, `^GSPC` — todos 200 (vazio quando não casam). A vírgula, porém, muda o modo de query (multiquote exato).
- **No-ops verificáveis no servidor:** `enableLists`, `enablePrivateCompany`, `enableCulturalAssets`, `enableEnhancedTrivialQuery`, `recommendCount`, `crumb`, `quotesQueryId`/`newsQueryId`/`multiQuoteQueryId` inválidos, e qualquer parâmetro desconhecido — nenhum altera o corpo em relação à linha de base da mesma query.
- **Query sem correspondência:** 200 com `quotes/news/nav/lists/researchReports/screenerFieldResults` vazios e `count: 0` — o tratamento de "não encontrado" é responsabilidade do cliente.

### 8.3 O `500` do preset institucional do webcore

O preset `instituationalHolders` do webcore (§9.3) produz `500` **determinístico** quando enviado como está no bundle: `enableScreenerField=true` + `screenerFieldName=top_fund_holder_names` + `screenerFieldInstrumentType=institutional_interest` + `screenerFieldCount=10` + `enableCb=false` → HTML de error report do backend (`HTTP Status 500 - Internal Server Error`, `server: ATS`, upstream `finance-search`). O isolamento é cirúrgico — **qualquer** das mutações abaixo devolve 200:

| Mutação | Status |
| :--- | :---: |
| `screenerFieldCount=5` (resto idêntico) | 200 |
| `screenerFieldCount=11` (resto idêntico) | 200 |
| `screenerFieldInstrumentType=equity` (valor do Autocomplete) | 200 |
| `enableCb=true` ou ausente | 200 |
| flag `enableScreenerField` sem `screenerFieldName`/`screenerFieldInstrumentType` | 200 |

O wrapper de autocomplete, que usa o **mesmo** contexto com `screenerFieldInstrumentType="equity"` (não `institutional_interest`), responde 200 — os dois consumers do mesmo recurso divergem no valor do tipo de instrumento, e só a combinação do webcore explode. Independentemente de 200 ou 500, `screenerFieldResults` voltou **vazio em toda condição observada** — o subsistema está funcionalmente morto no deployment atual: o research-hub (filtro `top_fund_holder_names`) o invoca via Autocomplete e recebe array vazio.

### 8.4 CORS

O preflight `OPTIONS` devolve `Access-Control-Allow-Origin: https://finance.yahoo.com` (origem fixa, não `*`), `Access-Control-Allow-Credentials: true` e `Access-Control-Allow-Headers: Content-Type, Origin, x-crumb, y-yf-enforce-crumb`. Requisição GET com `Origin` estranho é **respondida sem nenhum header CORS** — a edge entrega o corpo ao cliente HTTP, mas o browser bloqueia a leitura por ausência de `Access-Control-Allow-Origin`. O preflight tem `cache-control: private, no-cache, no-store`. O `vary` da resposta GET inclui `Origin` (duas vezes) — a variante por origem sustenta o CORS restrito.

### 8.5 Cache

| Header de Cache | Valor Observado | Observação |
| :--- | :--- | :--- |
| `cache-control` (GET 200) | `public, max-age=600, stale-while-revalidate=180` | 10 min de fresco + 3 min de stale-revalidate — coerente com typeahead de conteúdo quente |
| `cache-control` (400/405/HEAD/OPTIONS) | `max-age=0, private` / `private, no-cache, no-store` | Erros e metadados de verbo não são cacheados |
| `vary` | `Origin,Origin,Accept-Encoding` | Duplicação de `Origin` observada; sustenta o CORS restrito |
| `age` | presente (ex. `3`) | Resposta servida do cache de edge em re-leitura imediata |
| `etag` | ausente | Não suporta `If-None-Match`/304 |

### 8.6 Telemetria interna (painel `timeTakenFor*`)

O backend expõe 11 temporizadores que revelam a ativação de subsistemas por query: `timeTakenForQuotes`, `timeTakenForNews`, `timeTakenForCrunchbase` (> 0 quando `enableCb` casa privadas), `timeTakenForCulturalAssets`, `timeTakenForNav`, `timeTakenForSearchLists`, `timeTakenForPredefinedScreener`, `timeTakenForAlgowatchlist`, `timeTakenForResearchReports`, `timeTakenForQuestions`, `timeTakenForScreenerField` — todos em milissegundos, com `totalTime` agregado. Valores zero indicam subsistema não acionado para a query; o painel é a assinatura do fan-out interno do microsserviço `finance-search`.

---

## 9. Referências do código-fonte (bundle)

### 9.1 Quem chama o endpoint e de onde vem o comportamento

| Arquivo | Imports | Papel / padrão de chamada |
| :--- | :--- | :--- |
| `webcore/srchjs/1.2.50/js/finSearch.modern.js` | — (webcore autônomo, IIFE) | FinSearchJS — captura forms `data-finsrch`, presets `B`, montagem `V`, transporte `Y`; expõe `window.FinSearch` e `window.finSearchContext`. |
| `chunks/Autocomplete.[hash].js` | `window.FinSearch` (global) | Wrapper SvelteKit de autocomplete — variantes estendidas e params extras (`researchReportsCount`, `enableCccBoost`, `includeTypes`, `useStaging`). |
| `chunks/FiltersSelector.[hash].js` | Autocomplete | Filtros do research-hub — mapa id de filtro → variante + assetType → `includeTypes`. |
| `chunks/providerLogos.[hash].js` | — | `as` (`fetchSearchData`) — resolvedor de logos com URL hardcoded em query2 e `includeTypes`/`excludeTypes`. **Nota de drift entre builds**: em builds mais recentes este função foi consolidada no chunk `local_offer.[hash].js` (o chunk `providerLogos` não existe mais; a função — ali `f44` — é byte a byte a mesma do §9.6). |

### 9.2 Montador de URL — `V` integral

```js
// webcore/srchjs/1.2.50/js/finSearch.modern.js — V({type, query, config})
function V({ type = N, query, config }) {         // N = "all"
  const s = (({ type = N, query, config }) => {
    const s = window[v] || {};                  // v = "finSearchContext" (lang/region/strings)
    let i = {
      q: query,                                  // query JÁ encodeURIComponent'd pelo chamador
      lang: s.lang || "en-US",
      region: s.region || "US",
    };
    const { useStaging = false, ...rest } = config ?? {};   // useStaging NÃO vai para a query
    switch (type) {
      default:
      case N:   i = { ...i, ...B[N], ...rest }; break;      // preset + overrides
      case T:   i = { ...i, ...B[T], ...rest }; break;      // "quote"
      case R:   i = { ...i, ...B[R], ...rest }; break;      // "researchReports"
      case M:   i = { ...i, ...B[M] }; break;               // "instituationalHolders" (sem overrides!)
    }
    const a = [];
    for (const e in i) {                         // só string/number/boolean são serializados
      if (Object.prototype.hasOwnProperty.call(i, e)) {
        const t = i[e];
        if (typeof t === "string" || typeof t === "number" || typeof t === "boolean") {
          a.push(`${e}=${i[e]}`);                // template literal: true/false viram "true"/"false"
        }
      }
    }
    return `${q(useStaging) + n}?${a.join("&")}`; // host sorteado + path + querystring crua
  })({ type, query, config });
  return Y(s, {});                                // transporte com defaults (1500 ms)
}
```

### 9.3 Presets de contexto — `B` integral

```js
// webcore/srchjs/1.2.50/js/finSearch.modern.js — presets enviados por data-finsrch
const B = {
  all: {                                          // N — busca genérica
    quotesCount: 6, newsCount: 4, enableFuzzyQuery: false,
    quotesQueryId: "tss_match_phrase_query",
    multiQuoteQueryId: "multi_quote_single_token_query",
    newsQueryId: "news_cie_vespa",
    enableCb: true, enableNavLinks: true,
    enableEnhancedTrivialQuery: true, enableCulturalAssets: true,
    enableLogoUrl: true, enableLists: false, enableNcgNews: true,
  },
  researchReports: {                              // R — form do cabeçalho (#ybar-sf)
    quotesCount: 6, newsCount: 3, listsCount: 2, enableFuzzyQuery: false,
    quotesQueryId: "tss_match_phrase_query",
    multiQuoteQueryId: "multi_quote_single_token_query",
    newsQueryId: "news_cie_vespa",
    enableCb: true, enableNavLinks: true, enableEnhancedTrivialQuery: true,
    enableResearchReports: true, enableCulturalAssets: true,
    enableLogoUrl: true, enableLists: false, enableNcgNews: true,
  },
  quote: {                                        // T — form do dock inferior
    quotesCount: 8,
    quotesQueryId: "tss_match_phrase_query",
    multiQuoteQueryId: "multi_quote_single_token_query",
    enableCb: false, enableNavLinks: true, enableCulturalAssets: true,
    enableNews: false, enableResearchReports: false, enableLists: false,
  },
  instituationalHolders: {                        // M — preset que produz o 500 (§8.3)
    screenerFieldCount: 10, enableScreenerField: true,
    enableCb: false, enableNews: false, enableLists: false,
    enableQuotes: false, enableNavLinks: false, enableResearchReports: false,
    screenerFieldName: "top_fund_holder_names",
    screenerFieldInstrumentType: "institutional_interest",
  },
};
```

### 9.4 Transporte — `Y` (fetch com fallback XHR)

```js
// webcore/srchjs/1.2.50/js/finSearch.modern.js — Y, fluxo integral condensado
function Y(e, { timeout = 1500, errorMsg = "Search Autocomplete failed",
               beaconString = "finSearchAutocomplete", throwError = true }) {
  return new Promise((i, r) => {
    const l = Date.now();                        // carimbo do DISPATCH
    function successCb(t = {}) {
      t.timestamp = l;                            // injeta o timestamp NA RESPOSTA
      O("info", beaconString, { code: 200, surl: e });   // beacon de telemetria
      i(t);
    }
    function errorCb(t = {}) {
      t.status = t.status || 500; t.message = t.message || errorMsg;
      O("error", beaconString, { code: t.status, msg: t.message, surl: e });
      throwError ? r(t) : i(t);
    }
    if (window.fetch !== undefined) {
      // guarda de timeout manual: setTimeout marca a flag n e chama
      // errorCb({status: 502, message: "Autocomplete timeout"})
      window.fetch(e, { mode: "cors", credentials: "include" })
        .then(e => e.ok ? e.json() : Promise.reject({ status: e.status || 502,
                                                       message: e.statusText }))
        .then(successCb).catch(e => { if (!n) errorCb(e); });
    } else {
      // fallback: XMLHttpRequest com timeout e withCredentials = true
      const n = new window.XMLHttpRequest();
      n.open("GET", e, true); n.timeout = timeout; n.withCredentials = true;
      // onload: 2xx → JSON.parse → successCb; senão errorCb
    }
  });
}
// Consumo assincrono na classe ot:
//   fetchSuggestions: const o = await V({config, type, query: encodeURIComponent(t)});
//   deliverSearchResults: if (timestamp < this.lastResultsTimestamp) return;  // dedup fora de ordem
```

### 9.5 Wrapper de autocomplete — montagem do `searchConfig`

```js
// chunks/Autocomplete.[hash].js — variantes e params extras (delegados ao webcore)
const we = {                                      // mapa variante do componente → contexto webcore
  all: "all", compare: "quote", quote: "quote",
  researchReports: "researchReports",
  instituationalHolders: "instituationalHolders", // typo real do bundle
  screener: "quote",
};
let o = {
  enableCb: !X && enablePrivate,                 // X = flag enablePrivateCompany da sessão
  enableCulturalAssets, enableNavLinks,
  listsCount, quotesCount,                        // defaults do componente: 2 e 7
  recommendCount: 6, enableLists: false,
  ...(ie && { useStaging: ie }),                  // feature flag enableStagingSearch
  ...(X && { enablePrivateCompany: X, enableCb: false }),
  ...(ge && { enableCccBoost: true }),            // feature flag enableCccBoost
};
if (variant !== "quote") o = { ...o, newsCount, researchReportsCount: 2 };  // newsCount default 2
if (variant === "compare") {
  o.includeTypes = "equity"; o.recommendCount = 4; o.enableFuzzyQuery = false;
  o.enableEnhancedTrivialQuery = true; o.enableCulturalAssets = true;
  o.enableLogoUrl = true; o.enablePrivateCompany = false;
}
if (variant === "screener") {
  o.includeTypes = assetType;                    // equity | etf | index | mutualfund | future...
  o.recommendCount = 4; o.enableFuzzyQuery = false;
  o.enableEnhancedTrivialQuery = true; o.enableCulturalAssets = true;
  o.enableLogoUrl = true; o.enablePrivateCompany = false;
}
if (variant === "instituationalHolders") {
  o.screenerFieldCount = 10; o.enableScreenerField = true;
  o.enableNews = false; o.enableQuotes = false; o.enableNavLinks = false;
  o.screenerFieldName = "top_fund_holder_names";
  o.screenerFieldInstrumentType = "equity";      // diverge do webcore (institutional_interest)
  o.enablePrivateCompany = false;
}
if (Object.keys(customSearchConfig)) o = { ...o, ...customSearchConfig };
// ...window.FinSearch.initSearchForm({ formNode: y, ..., searchConfig: o, ... })

// chunks/FiltersSelector.[hash].js — mapa do research-hub:
const f = {
  ticker:            { variant: "screener",           placeholder: "SEARCH_TICKER" },
  top_fund_holder_names: { variant: "instituationalHolders", placeholder: "SEARCH_HOLDER" },
  "fund_name.keyword":   { variant: "instituationalHolders", placeholder: "SEARCH_HOLDER" },
  exchange:          { variant: "screener",           placeholder: "SEARCH_EXCHANGE" },
};
const _ = {                                       // assetType → valor de includeTypes
  equity: "equity", etf: "etf", index: "index", mutualfunds: "mutualfund",
  futures: "future",
  analyst_ratings: "equity,etf,index,mutualfund,future",
  technical_events: "equity,etf,index,mutualfund,future",
  top_holdings: "equity,etf,index,mutualfund,future",
};
```

### 9.6 Resolvedor de logos — `as` (`fetchSearchData`)

```js
// chunks/providerLogos.[hash].js — resolvedor independente (host fixo query2)
async function as({ lang, region }, t,
                  { quotesCount = 6, includeTypes, excludeTypes } = {}) {
  const o = new URL("https://query2.finance.yahoo.com/v1/finance/search");
  o.searchParams.set("q", t);
  o.searchParams.set("lang", lang);
  o.searchParams.set("region", region);
  o.searchParams.set("quotesCount", String(quotesCount));
  o.searchParams.set("enableCb", "false");
  o.searchParams.set("enableNews", "false");
  o.searchParams.set("recommendCount", "0");
  o.searchParams.set("enableLists", "false");
  o.searchParams.set("enableNavLinks", "false");
  o.searchParams.set("enableFuzzyQuery", "false");
  o.searchParams.set("enableCulturalAssets", "false");
  o.searchParams.set("enableResearchReports", "false");
  o.searchParams.set("enablePrivateCompany", "false");
  o.searchParams.set("quotesQueryId", "tss_match_phrase_query");
  o.searchParams.set("multiQuoteQueryId", "multi_quote_single_token_query");
  if (includeTypes) o.searchParams.set("includeTypes", includeTypes);
  if (excludeTypes) o.searchParams.set("excludeTypes", excludeTypes);
  const h = await fetch(o.toString());            // fetch simples, sem credentials
  if (!h.ok) throw new Error(`fetchSearchData failed: ${h.status} ${h.statusText}`);
  return h.json();
}
```

### 9.7 Mapa resumido da cadeia

```
entry/app + webcore (srchjs/1.2.50)
  ├── webcore/srchjs/1.2.50/js/finSearch.modern.js  (window.FinSearch)
  │     ├── forms data-finsrch: "researchReports" (#ybar-sf) e "quote" (dock)
  │     ├── V — montagem (q + lang/region + preset B[type])
  │     ├── q() — sorteio query1/query2 (stage: iquery-stage)
  │     └── Y — fetch cors/credentials/1500 ms → dedup por timestamp
  ├── chunks/Autocomplete.[hash].js  (window.FinSearch.initSearchForm)
  │     ├── variantes: all | compare | quote | researchReports | instituationalHolders | screener
  │     └── params extras: researchReportsCount=2, enableCccBoost, includeTypes=assetType
  ├── chunks/FiltersSelector.[hash].js
  │     └── filtros research-hub → ticker/exchange (screener) | top_fund_holder_names (holders)
  └── chunks/providerLogos.[hash].js
        └── as (fetchSearchData) — query2 fixo, includeTypes/excludeTypes
```

---

## 10. Guia de reimplementação

1. **Não implemente handshake de credencial** — a chamada é anônima; só o UA de browser é obrigatório.
2. **Debounce curto e dedup por timestamp** — replique 150 ms de debounce e descarte respostas cujo carimbo de dispatch seja anterior ao último renderizado; o typeahead naturalmente dispara corridas de requisições.
3. **Discrimine o polimorfismo de `quotes` antes de tudo** — teste `isYahooFinance`: `false` significa registro Crunchbase sem `symbol` (use `name`/`permalink`); acessar `symbol` cegamente quebra no primeiro registro privado.
4. **Não espere mais de 7 quotes** — o cap do servidor é 7; pedir `quotesCount` alto não muda nada. Use a vírgula (`q=AAPL,MSFT`) quando precisar de resolução exata em lote — é o modo multiquote, com `nav` `MULTIQUOTE` de volta.
5. **Para logos, envie `enableLogoUrl=true`** — o campo só é populado com a flag; combine com `includeTypes`/`excludeTypes` para restringir classes.
6. **News é chaveado por `enableNcgNews` e por cobertura de idioma** — `false` zera a categoria; `pt-BR`/`ja-JP` retornam vazio por lacuna do índice (de-DE/fr-FR/es-ES/en-GB têm notícias no idioma).
7. **Não dependa de `screenerFieldResults`** — o subsistema retorna vazio em todas as condições observadas; e evite replicar a combinação do webcore (`screenerFieldInstrumentType=institutional_interest` + `screenerFieldCount=10` + `enableCb=false`), que devolve 500 determinístico.
8. **Erros vêm em envelope `finance`, sucesso é plano** — trate o 400 de `q` ausente, o 405 de POST/PUT e o 429 de UA genérico antes de desempacotar categorias.
9. **Cacheie por querystring exata** — 10 min de edge-cache (`max-age=600`) sustentam cache local de typeahead; o `vary: Origin` exige atenção apenas em contexto de browser.
10. **Um host só basta** — query1 e query2 são intercambiáveis; o sorteio do cliente oficial é distribuição de carga, não failover obrigatório.

---

## 11. Apêndice — amostra real

A resposta crua do request canônico do consumidor oficial do cabeçalho (`/v1/finance/search?q=Apple&lang=en-US&region=US&quotesCount=6&newsCount=3&listsCount=2&enableFuzzyQuery=false&quotesQueryId=tss_match_phrase_query&multiQuoteQueryId=multi_quote_single_token_query&newsQueryId=news_cie_vespa&enableCb=true&enableNavLinks=true&enableEnhancedTrivialQuery=true&enableResearchReports=true&enableCulturalAssets=true&enableLogoUrl=true&enableLists=false&enableNcgNews=true`, host `query1`, contexto `researchReports`) acompanha este documento em `v1_finance_search.json` — resposta integral, sem edição de chaves nem reordenação, capturada com o conjunto de parâmetros exatamente como o FinSearchJS o envia para o form `#ybar-sf`.

---

*Referências dos arquivos analisados*

- `webcore/srchjs/1.2.50/js/finSearch.modern.js`
- `chunks/Autocomplete.[hash].js`
- `chunks/FiltersSelector.[hash].js`
- `chunks/providerLogos.[hash].js`


