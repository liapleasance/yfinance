# YH Finance QuoteSummary — Query Parameters & Composição Padrão por Página

**Data de atualização:** 23/10/2026

**Método:** extração literal do build oficial (`quoteUtil`, `hubSectors`, `217`, `house`, `Watchlist*`) +
sonda empírica anônima e autenticada (fc.yahoo.com → A3 → getcrumb → **51 requisições** contra
`query1`/`query2` em 23/10/2026). Cada afirmação marcada **[bundle]** vem do código; **[live]** foi
reproduzida no fio; **[prod]** reflete as feature flags da sessão real capturada no SSR do TSLA.

---

## GET /v10/finance/quoteSummary/{symbol}

Endpoint single. A query completa que o cliente oficial monta tem **14 chaves possíveis**; 3 são
fixas do transporte, 1 é fixa do loader, 5 dependem de flags de sessão e 2 vêm do compositor da página.

```json5
{
  // ==========================================================================
  // 1 · PARÂMETROS DA REQUISIÇÃO (v10) — todos, com origem e default
  // ==========================================================================

  request: {
    method: "GET",
    path: "/v10/finance/quoteSummary/{symbol}",

    params: {
      // ---- fixos (sempre vão, incondicionalmente) --------------------------
      modules: "…",              // LOADER · OBRIGATÓRIO · CSV deduplicado; ordenado quando
                                 //   enableQuoteSummaryCaching ON (ver bloco 4) [bundle+live]
                                 //   · só vão ao fio os módulos AUSENTES do store 'quote'
                                 //     (cache-first; m.length===0 → nem chama) [bundle]
      formatted: "true",         // LOADER · hardcoded "true" — o cliente nunca pede cru [bundle]
                                 //   · default do SERVIDOR também é formatted: omitido devolve
                                 //     {raw, fmt} [live]
      crumb: "…",                // TRANSPORTE · anexado na query em GET (crumb:true do loader);
                                 //   vetor alternativo: header x-crumb [bundle; live: falso → 401
                                 //   idêntico nos dois vetores]
      lang: "en-US",             // TRANSPORTE · searchParams.set com o valor da SESSÃO
      region: "US",              //   (sobrescreve o que veio na query; fallback "en-US"/"US";
                                 //   escape hatch interno: opção disableDefaultQueries) [bundle]
                                 //   · efeito real: localiza sectorDisp/industryDisp e o fmt
                                 //     numérico; pt-BR ESVAZIA longBusinessSummary sem fallback [live]

      // ---- flags condicionais do loader (lidas da sessão; vão na query só se ON) ----
      enableQSPExpandedEarnings: "true", // flag ON em prod [prod] → VAI na query E injeta os
                                         //   módulos earningsGaap + earningsNonGaap na lista [bundle]
      overnightPrice: "true",            // flag enableOvernight ON em prod [prod] → vai na query;
                                         //   só materializa dado quando o ativo tem sessão overnight
      enablePrivateCompany: "true",      // flag ON em prod [prod] → vai na query (variantes .PVT)
      mockPrivateCompany: "true",        // flag OFF em prod → parâmetro AUSENTE (aceito sem efeito) [live]
      mockOvernightPrice: "true",        // idem — AUSENTE em prod [live]
      dataVersion: "v2",                 // gerado SOMENTE sob enableMorningstarDataUpgrade [bundle];
                                         //   flag OFF em prod → parâmetro AUSENTE [prod+live C16]
                                         //   · a variante enableMorningStarTemplatesv3 NÃO EXISTE no build

      // ---- extras do compositor da página (só em classes/abas específicas) ----
      topPickThisMonth: "true",          // quoteType EQUITY + (enableQSPStockPicks OU
                                         //   enableQSPStockPicksRating) — Rating ON em prod →
                                         //   vai em TODA página de ação [prod+bundle]
      checkUnusualOptionsActivity: "true", // aba ∈ {options, options-volume, options-open-interest}
                                         //   + enableWorkspaceGtmOptionsSignal (ON em prod) — vale
                                         //   para EQUITY, ETF e INDEX [bundle; lista literal do build]

      // ---- aceitos e ignorados pelo servidor ---------------------------------
      //   qualquer chave desconhecida na query é aceita sem efeito [live: quoteTypesFilter,
      //   modulesFields e nomes arbitrários no v10 single → 200 payload idêntico]
    },
  },
}
```

### Semântica e casos de borda por parâmetro (v10)

| Parâmetro | Origem | Obrig. | Default | Comportamento e evidência |
| :--- | :--- | :---: | :--- | :--- |
| `{symbol}` (path) | URL | Sim | — | Case-insensitive; `%5E` e `^` cru → 200 [live]; trailing slash `/AAPL/` aceito [live]; charset do cliente `[a-zA-Z0-9^.$_+=*&:@~-]` (regex literal do build) — fora dele o loader rejeita antes de enviar; inexistente → 404 `Quote not found for symbol: X` [live]; `?symbol=` em query (sem barra no path) → **404 textual "Not Found"** [live]; com barra → 404 JSON finance [live] |
| `modules` | loader+compositor | Sim | — | CSV; case-insensitive (chave volta minúscula) [live]; duplicatas deduplicadas [live]; **espaço após vírgula não aparado** — `"price,%20summaryDetail"` devolve só `price` [live]; desconhecido/sem dado → descartado sem erro; todos descartados → 404 `No fundamentals data found for symbol: X` [live]; ordem no `result[0]` é do SERVIDOR (não a pedida) [live] |
| `formatted` | loader | Não | `true` (servidor) | Omitido → `{raw, fmt}` [live]; `"false"` → primitivos [live]; % chega em **fração** no `raw` [live]; campos sem dado: embrulhados vazios com `true`, omitidos com `false` |
| `lang` / `region` | transporte | Não | sessão (`en-US`/`US`) | `searchParams.set` sobrescreve [bundle]; `pt-BR`: `sectorDisp` → "Tecnologia", `longBusinessSummary` → `""` [live] |
| `crumb` | transporte | Sim* | — | Query (GET) ou header `x-crumb`; ausente/falso/vazio → 401 `finance.error` `Invalid Crumb` [live×3]; crumb válido via query → 200 [live] |
| `enableQSPExpandedEarnings` | loader (flag ON) | Não | ausente | Vai na query **e** injeta `earningsGaap`+`earningsNonGaap` [bundle]; em prod vai sempre [prod] |
| `overnightPrice` | loader (flag ON) | Não | ausente | Em prod vai sempre [prod]; payload só muda com dado overnight |
| `enablePrivateCompany` | loader (flag ON) | Não | ausente | Em prod vai sempre [prod]; necessário para variantes `.PVT` |
| `mockPrivateCompany` / `mockOvernightPrice` | loader (flag OFF) | Não | ausente | Aceitos sem efeito observável [live] |
| `dataVersion` | loader (flag OFF) | Não | ausente | `v2` só sob `enableMorningstarDataUpgrade` — **off em prod** [prod]; não confundir com `enableMorningstarFinancialsLaunch` (só gera status "launched/preview") [bundle] |
| `topPickThisMonth` | compositor | Não | ausente | Só EQUITY (flag Rating ON em prod) [bundle+prod] |
| `checkUnusualOptionsActivity` | compositor | Não | ausente | Só abas `options*` de qualquer classe [bundle] |

---

## GET /v11/finance/quoteSummary/

Variante batch (lote de **até 15** símbolos; barra final **faz parte da chamada** — sem ela → 502 HTML [live,
anônimo e autenticado]). O loader oficial usa o MESMO conjunto de parâmetros do v10 **menos** os flags de
mock/overnight/private/expanded — cravado no código: a query do batch é
`{formatted, modules, symbols, …dataVersion}` apenas [bundle].

```json5
{
  // ==========================================================================
  // 2 · PARÂMETROS DA REQUISIÇÃO (v11) — todos
  // ==========================================================================

  request: {
    method: "GET",
    path: "/v11/finance/quoteSummary/",   // COM barra final [bundle; live: sem → 502 text/html]

    params: {
      symbols: "AAPL,MSFT",      // OBRIGATÓRIO · CSV ≤ 15 (16 → 400 quoteSummary "Max symbols
                                 //   requested exceeded the allowed limit") [live]
                                 //   · ausente → 400 finance "Missing required query
                                 //     parameter=symbols" [live]
                                 //   · cliente envia em CAIXA ALTA; servidor aceita minúsculo e o
                                 //     ECO volta maiúsculo [live]
                                 //   · inexistente → OMITIDO do eco e do result [live]
                                 //   · só inexistentes → 200 com symbols [] e result [] [live]
                                 //   · validação client-side antes do envio (mesma regex do v10):
                                 //     "Invalid symbol in quote summary batch request" [bundle]
      modules: "price,…",        // OBRIGATÓRIO · mesmo vocabulário/regras do v10; dedupe sempre,
                                 //   sort sob enableQuoteSummaryCaching [bundle]; ausente → 400
                                 //   finance "Missing required query parameter=modules" [live]
                                 //   · módulo pedido que não produz dado para UM símbolo do lote
                                 //     → elemento {errorResult:{code:"Not Found", description:
                                 //     "No fundamentals data found for any of the QuoteSummaryTypes=[]
                                 //     for symbol=X"}} com eco e paridade preservados [live]
      formatted: "true",         // fixo do loader; default do servidor = formatted [live]
      lang: "en-US",             // transporte, como no v10
      region: "US",              //
      crumb: "…",                // transporte; header x-crumb também vale [bundle]

      // ---- condicionais ----
      dataVersion: "v2",         // mesmo gatilho único do v10 (Morningstar upgrade); OFF em prod
                                 //   → ausente; aceito no lote [live: 200]

      // ---- do chamador "comparador" (NÃO presentes no build atual do cliente; o SERVIDOR
      //      aceita as três no núcleo v11 — cravado ao vivo) ----
      quoteTypesFilter: "equity",  // FILTRO REAL: elementos de outra classe são excluídos do eco E do
                                   //   result com paridade preservada (AAPL,SPY + equity → eco
                                   //   ["AAPL"]); no v10 single é aceito e IGNORADO [live×2]
      currency: "USD",             // aceito SEM conversão no fio (price continua USD) [live]
      modulesFields: "…",          // aceito sem efeito observável [live]

      // ---- aceitas no lote sem erro e SEM efeito; o cliente oficial NÃO as envia aqui [bundle] ----
      //   enablePrivateCompany · overnightPrice · mockPrivateCompany · mockOvernightPrice ·
      //   enableQSPExpandedEarnings (a injeção de earningsGaap/NonGaap só existe na variante single)
    },
  },
}
```

---

## 3 · QUEM INJETA O QUÊ (origem por camada)

```json5
{
  "transporte (house)": {
    "crumb": "query em GET (crumb:true) · header x-crumb alternativo",
    "lang/region": "searchParams.set(lang, session.lang||'en-US'); set(region, session.region||'US') — SOBRESCREVE",
    "escape": "opção interna disableDefaultQueries suprime lang/region",
    "headers internos": "o transporte REMOVE x-cache, x-cache-ttl, x-cache-swr do init antes do fetch (whitelist literal) — nunca chegam ao query1 [bundle]"
  },
  "loader (loadQuoteSummary)": {
    "formatted": "'true' fixo",
    "modules": "pedidos ∪ injeções de flag (bloco 4) · cache-first (store 'quote') · dedupe sempre · sort sob enableQuoteSummaryCaching",
    "flagsDeQuery": "mockPrivateCompany · mockOvernightPrice · enableQSPExpandedEarnings · enablePrivateCompany · overnightPrice · dataVersion — cada uma entra na query só se a flag da sessão estiver ON"
  },
  "compositor da página (Re)": {
    "modules": "base(5) ∪ mapa(quoteType×aba) ∪ injeções por aba/flag (bloco 5)",
    "queryExtras": "topPickThisMonth (EQUITY) · checkUnusualOptionsActivity (abas options*)"
  },
  "servidor": {
    "formatted": "default true",
    "modules": "case-insensitive · dedupe · descarte silencioso · 404 só se nada sobrar",
    "resposta": "camada própria quoteSummary.{result,error} — erros de parâmetro/método vêm na camada finance"
  }
}
```

---

## 4 · FLAGS DE SESSÃO → PARÂMETROS DE QUERY (tabela mestre)

Estado **[prod]** = sessão real capturada no SSR (TSLA, 23/10/2026 — 291 features).

| Flag de sessão | Parâmetro gerado na query | Efeito na lista `modules` | [prod] |
| :--- | :--- | :--- | :---: |
| `enableQSPExpandedEarnings` | `enableQSPExpandedEarnings=true` | + `earningsGaap`, `earningsNonGaap` | **ON** |
| `enableOvernight` | `overnightPrice=true` | — | **ON** |
| `enablePrivateCompany` | `enablePrivateCompany=true` | — | **ON** |
| `enableQuoteSummaryCaching` | *(nenhum)* | **ordena** o CSV de modules | **ON** |
| `enableCorporateActions` | *(nenhum)* | + `corporateActions` | **ON** |
| `enableQSPChartRangeTooltips` | *(nenhum)* | + `quoteUnadjustedPerformanceOverview` | **ON** |
| `enableEarningsTranscript` | *(nenhum)* | + `earningsCallTranscripts` (ou `…Latest`) em **toda** página | **ON** |
| `enableQSPLatestQuoteSummaryModules` | *(nenhum)* | variante `upgradeDowngradeHistoryLatest` no summary | **ON** |
| `enableQSPAnalysisGAAPToggle` | *(nenhum)* | aba analysis: + `earningsTrendGaap/NonGaap` + `earningsHistoryGaap/NonGaap` | **ON** |
| `enableTopCryptoAttr` | *(nenhum)* | CRYPTO summary: + `attribution` | **ON** |
| `enableQSPStockPicksRating` | `topPickThisMonth=true` (EQUITY) | — | **ON** |
| `enableWorkspaceGtmOptionsSignal` | `checkUnusualOptionsActivity=true` (abas options*) | — | **ON** |
| `enableMorningstarDataUpgrade` | `dataVersion=v2` | — | off |
| `mockPrivateCompany` | `mockPrivateCompany=true` | — | off |
| `mockOvernightPrice` | `mockOvernightPrice=true` | — | off |
| `enableQSPAboveTheFoldUpdates` / `enableQSPFullWidthChart` | *(nenhum)* | + `chartPreviousClose` | off / off |
| `enableQSPEarnings` | *(nenhum)* | + `corporateActions` (OR com a flag acima) | off |
| `enableQSPLiveEarningsBE` | *(nenhum)* | + `earningsCallAudios` | off |
| `enableQSPBelowTheFoldUpdates` | *(nenhum)* | EQUITY summary: + `assetProfile` | off |
| `enableQSPStockPicks` | `topPickThisMonth=true` (EQUITY) | — | off |
| `enableQSPSeasonality` | *(nenhum)* | (só fields do `/v7/finance/quote` — fora do escopo) | off |
| `enableQSPLatestEarningsCallTranscripts` | *(nenhum)* | variante `earningsCallTranscriptsLatest` | off |

> **Query base que TODA página de quote envia em prod (além de modules):**
> `formatted=true` · `crumb=…` · `lang=<sessão>` · `region=<sessão>` ·
> `enableQSPExpandedEarnings=true` · `overnightPrice=true` · `enablePrivateCompany=true` ·
> `topPickThisMonth=true` (só EQUITY). **Não** vão: `dataVersion`, `mock*`, `checkUnusualOptionsActivity` (fora de options*).

---

## 5 · QUERY PADRÃO DE CADA PÁGINA — composição efetiva de `modules`

**Fórmula [bundle]:** `modules = dedupe( BASE(5) ∪ mapa(quoteType,aba) ∪ injeções-do-loader ∪ injeções-do-compositor )`,
ordenada (`enableQuoteSummaryCaching` ON). No fio vão só os módulos ausentes do store (cache-first).

**PISO COMUM [prod]** — as 10 chaves que TODA página/aba/classe pede em prod:

```json5
"pisoComum": [
  "calendarEvents", "corporateActions", "earningsCallTranscripts", "earningsGaap",
  "earningsNonGaap", "financialsTemplate", "pageViews", "price",
  "quoteUnadjustedPerformanceOverview", "summaryDetail"
]
// = BASE(5) + corporateActions + earningsCallTranscripts (flag ON)
//   + earningsGaap/NonGaap (flag ON) + quoteUnadjustedPerformanceOverview (flag ON)
//   · chartPreviousClose ficaria no piso se AboveTheFoldUpdates/FullWidthChart estivessem ON (estão OFF)
//   · earningsCallAudios entraria com enableQSPLiveEarningsBE (OFF)
```

Abaixo, **só os EXTRAS** além do piso, por classe × aba (contagem final entre colchetes):

```json5
{
  // ==========================================================================
  // 5a · EQUITY  (topPickThisMonth=true em TODAS as abas)
  // ==========================================================================
  "EQUITY": {
    "summary":            [18] "defaultKeyStatistics, earnings, equityPerformance, esgScores, financialData, recommendationTrend, summaryProfile, upgradeDowngradeHistoryLatest",
    "key-statistics":     [12] "defaultKeyStatistics, financialData",
    "analysis":           [23] "earnings, earningsHistory, earningsHistoryGaap, earningsHistoryNonGaap, earningsTrend, earningsTrendGaap, earningsTrendNonGaap, financialData, indexTrend, industryTrend, recommendationTrend, sectorTrend, upgradeDowngradeHistory",
    "analyst-insights":   [13] "financialData, recommendationTrend, upgradeDowngradeHistory",
    "analyst-ratings":    [11] "upgradeDowngradeHistory",
    "balance-sheet":      [17] "balanceSheetHistory, balanceSheetHistoryQuarterly, cashflowStatementHistory, cashflowStatementHistoryQuarterly, earnings, incomeStatementHistory, incomeStatementHistoryQuarterly",
    "cash-flow":          [17] "idem balance-sheet",
    "financials":         [17] "idem balance-sheet",
    "holders":            [17] "fundOwnership, insiderHolders, insiderTransactions, institutionOwnership, majorDirectHolders, majorHoldersBreakdown, netSharePurchaseActivity",
    "insider-roster":     [17] "idem holders",
    "insider-transactions":[17] "idem holders",
    "details":            [16] "assetProfile, earnings, esgScores, financialData, insiderHolders, summaryProfile",
    "company360":         [12] "earnings, esgScores",
    "earnings-calls":     [12] "defaultKeyStatistics, equityPerformance",
    "latest-news":        [13] "defaultKeyStatistics, equityPerformance, financialData",
    "news":               [13] "idem latest-news",
    "press-releases":     [13] "idem latest-news",
    "sec-filing":         [12] "equityPerformance, secFilings",
    "sec-filings":        [12] "idem sec-filing",
    "events":             [11] "secFilings",
    "profile":            [12] "assetProfile, secFilings",
    "community":          [11] "summaryProfile",
    "sustainability":     [11] "esgScores",           // pedido e NUNCA devolvido (descartado) [live]
    // piso puro [10] — sem extras: chart, community-insights, company-insights, corporate-events,
    //   dividends, earnings, fair-value, hiring-trends, history, innovation, insider-sentiment,
    //   research-reports, seasonality
    "options":            [10] "— (mas + checkUnusualOptionsActivity=true)",
    "options-volume":     [10] "— (idem)",
    "options-open-interest":[10] "— (idem)",
  },

  // ==========================================================================
  // 5b · ETF  (sem topPickThisMonth)
  // ==========================================================================
  "ETF": {
    "summary":     [17] "assetProfile, defaultKeyStatistics, esgScores, fundPerformance, fundProfile, topHoldings, upgradeDowngradeHistoryLatest",
    "details":     [18] "assetProfile, defaultKeyStatistics, esgScores, fundPerformance, fundProfile, insiderHolders, summaryProfile, topHoldings",  // mapa literal tem assetProfile ×2 e esgScores ×2 (dedupe do cliente/servidor)
    "holdings":    [15] "assetProfile, defaultKeyStatistics, fundPerformance, fundProfile, topHoldings",
    "performance": [14] "assetProfile, defaultKeyStatistics, fundPerformance, fundProfile",
    "profile":     [14] "assetProfile, defaultKeyStatistics, fundProfile, topHoldings",
    "risk":        [13] "assetProfile, defaultKeyStatistics, fundPerformance",
    "latest-news": [12] "fundPerformance, fundProfile",
    "news":        [12] "idem latest-news",
    "press-releases":[12] "idem latest-news",
    "sec-filing":  [12] "fundPerformance, fundProfile",
    "sec-filings": [12] "idem sec-filing",
    // piso puro: chart, community, history, seasonality
    "options":     [10] "— (mas + checkUnusualOptionsActivity=true)",
    "options-volume": [10] "— (idem)",
    "options-open-interest": [10] "— (idem)",
  },

  // ==========================================================================
  // 5c · MUTUALFUND
  // ==========================================================================
  "MUTUALFUND": {
    "summary":       [17] "assetProfile, defaultKeyStatistics, esgScores, fundPerformance, fundProfile, topHoldings, upgradeDowngradeHistoryLatest",
    "details":       [18] "assetProfile, defaultKeyStatistics, esgScores, fundPerformance, fundProfile, insiderHolders, summaryProfile, topHoldings",  // esgScores ×2 no mapa
    "holdings":      [15] "assetProfile, defaultKeyStatistics, fundPerformance, fundProfile, topHoldings",
    "performance":   [14] "assetProfile, defaultKeyStatistics, fundPerformance, fundProfile",
    "profile":       [14] "assetProfile, defaultKeyStatistics, fundProfile, topHoldings",
    "purchase-info": [14] "assetProfile, defaultKeyStatistics, fundPerformance, fundProfile",
    "risk":          [13] "assetProfile, defaultKeyStatistics, fundPerformance",
    "latest-news":   [12] "fundPerformance, fundProfile",
    "news":          [12] "idem latest-news",
    "press-releases":[12] "idem latest-news",
    "sec-filing":    [12] "fundPerformance, fundProfile",
    "sec-filings":   [12] "idem sec-filing",
    "sustainability":[11] "esgScores",
    // piso puro: chart, community, history, seasonality
  },

  // ==========================================================================
  // 5d · demais classes
  // ==========================================================================
  "CRYPTOCURRENCY": {
    "summary":  [18] "assetProfile, attribution, defaultKeyStatistics, earnings, financialData, recommendationTrend, summaryProfile, upgradeDowngradeHistoryLatest",
    "details":  [12] "assetProfile, summaryProfile",
    "profile":  [12] "assetProfile, secFilings",
    // piso puro: chart, community, history, latest-news, news, seasonality
  },
  "FUTURE": {
    "summary":  [12] "futuresChain, upgradeDowngradeHistoryLatest",
    "details":  [11] "futuresChain",
    "futures":  [11] "futuresChain",
    // piso puro: chart, history, latest-news, news, seasonality
  },
  "INDEX": {
    "summary":   [11] "upgradeDowngradeHistoryLatest",
    "components":[11] "components",
    "details":   [12] "components, summaryProfile",
    // piso puro: chart, community, history, latest-news, news, seasonality
    "options":   [10] "— (mas + checkUnusualOptionsActivity=true)",
    "options-volume": [10] "— (idem)",
    "options-open-interest": [10] "— (idem)",
  },
  "PRIVATE_COMPANY": {
    "summary":  [17] "assetProfile, defaultKeyStatistics, fundingRounds, marks, relatedCompanies, summaryProfile, upgradeDowngradeHistoryLatest",
    "profile":  [11] "assetProfile",
  },
  "CUL_IDX / CUL_SUB_IDX": {   // universos customizados — sem símbolo público responde [bundle]
    "summary":    [12] "assetProfile, upgradeDowngradeHistoryLatest",
    "components": [11] "assetComponents",
    "profile":    [11] "assetProfile",
    // piso puro: chart, history, seasonality
  },
  "INDICATOR": {
    "summary":  [12] "summaryProfile, upgradeDowngradeHistoryLatest",
    "community":[11] "summaryProfile",
    "details":  [11] "summaryProfile",
    "history":  [11] "summaryProfile",
    "seasonality": [10] "—",
  },
  "CURRENCY / MONEYMARKET / OPTION": {
    "summary":  [11] "upgradeDowngradeHistoryLatest",
    // resto: piso puro (CURRENCY: chart, community, details, history, latest-news, news, seasonality;
    //        MONEYMARKET: chart, details; OPTION: chart, community, details, history, seasonality)
  },
}
```

> **Notas da composição:**
> - `upgradeDowngradeHistoryLatest` no summary vem da injeção do compositor sob `enableQSPExpandedEarnings`
>   + `enableQSPLatestQuoteSummaryModules` (ambas ON) — vale para **todas as classes**; com as flags off
>   viraria `upgradeDowngradeHistory`. A aba `analysis` de EQUITY usa o canônico do MAPA (não é a injeção).
> - `esgScores` (EQUITY/ETF/MF summary+details+sustainability+company360) e `assetComponents` (CUL) são
>   ENVIADOS e **nunca materializam** — o servidor descarta sem erro [live]; com a flag de cache a lista
>   pedida continua maior que o `result[0]`.
> - Override por símbolo: `^FPMI` tem mapa próprio (summary = components+summaryProfile) [bundle].
> - `quoteFields` (projeção `/v7/finance/quote`) existe só para CRYPTO summary (`…comuns + cmcRank`) —
>   fora do escopo quoteSummary, citado aqui só para completar o mapa.

---

## 6 · CHAMADORES FORA DO QSP (mesmos endpoints, outra query padrão)

```json5
{
  "gatewayWs": "/ws/company-fundamentals/v11/finance/quoteSummary  (SEM barra final no código; aceita com) [bundle]",
  "WatchlistInsights": {
    "modules": "quotePerformanceOverview (fixo) — nome AUSENTE do vocabulário '59 nomes' do relatório anterior; materializa no v10 single e no gateway [live]",
    "lotes": "15",
    "query": "formatted=true · lang · region · symbols — sem crumb na query montada [bundle]"
  },
  "WatchlistRecentNews": {
    "modules": "earningsCallTranscripts (fixo)",
    "janela": "slice(0,100) símbolos [bundle]",
    "lotes": "15 (variante interna com 25) [bundle]"
  },
  "loaderBatch (ne→H)": "array de símbolos no loadQuoteSummary → v11 com formatted/crumb/lang/region/modules(dedupe+sort) · SEM as flags de mock/overnight/private/expanded [bundle]",
  "variante ws do comparador": "o 'loadComparison' com getCeo/quoteDetail/morningstarFinancials/quoteTrailingReturns + quoteTypesFilter/currency/modulesFields NÃO EXISTE no build atual — mas o SERVIDOR materializa o quarteto nos três caminhos e aceita as três chaves [live]"
}
```

---

## 7 · CONFERÊNCIA EMPÍRICA (amostra das 51 requisições, 23/10/2026)

| # | Teste | Resultado |
| :--- | :--- | :--- |
| 1 | 401 sem/falso crumb (query e header) — envelope finance exato | ✓ |
| 2 | POST → 405 finance, sem Allow (v10 e v11); OPTIONS → 200 `Allow: HEAD,GET,OPTIONS`; HEAD auth → 200 vazio | ✓ |
| 3 | `?symbol=` sem barra → 404 **textual**; com barra → 404 JSON finance | ✓ |
| 4 | v11 sem barra → 502 text/html (anônimo e autenticado) | ✓ |
| 5 | cache de borda `public, max-age=1, stale-while-revalidate=9`; `ct=application/json;charset=utf-8` | ✓ |
| 6 | UA Python-urllib → 429 `Edge: Too Many Requests` | ✓ |
| 7 | modules: case-insensitive, dedupe, espaço não aparado, descarte silencioso, 404 "No fundamentals data found" | ✓ |
| 8 | formatted default `{raw, fmt}`; `false` primitivo; % em fração; ordem das chaves = servidor | ✓ |
| 9 | esgScores sozinho → 404; acompanhado → descartado | ✓ |
| 10 | quarteto `getCeo/quoteDetail/morningstarFinancials/quoteTrailingReturns` materializa no v10 | ✓ |
| 11 | `quotePerformanceOverview` e variantes `…Latest` materializam no v10 | ✓ |
| 12 | v11: eco↔result 1:1, 15 ok / 16 → 400 `Max symbols…` (quoteSummary), ausentes → 400 finance | ✓ |
| 13 | v11: só inexistentes → 200 `[]`; errorResult com `QuoteSummaryTypes=[]`; minúsculo → eco maiúsculo | ✓ |
| 14 | v11: `quoteTypesFilter=equity` filtra de verdade; `currency=EUR` sem conversão; `modulesFields` no-op | ✓ |
| 15 | v10: `quoteTypesFilter`/`modulesFields` aceitos e ignorados | ✓ |
| 16 | `pt-BR`: `sectorDisp` localizado; `longBusinessSummary` esvaziado | ✓ |
| 17 | `^GSPC` cru e `%5E`; `/AAPL/`; `quoteType` legado; query2 espelho | ✓ |
