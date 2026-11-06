## YH Finance API Specification

![Yahoo Finance](https://upload.wikimedia.org/wikipedia/commons/9/9f/Yahoo%21_Finance_logo.svg)

**Data de atualização:** 19/10/2026

---

### GET /v10/finance/quoteSummary/{symbol}

Endpoint do sumário por aba da página de quote: devolve, para um único símbolo (no PATH), blocos
temáticos chamados **modules** — `price`, `summaryDetail`, `financialData`, `calendarEvents`,
`earningsGaap`, `recommendationTrend`, etc. É a evolução modular do antigo quoteSummary: em vez de
uma projeção plana de fields (como no `/v7/finance/quote`), cada module é um objeto aninhado
completo, com a lógica de apresentação do servidor (gráficos de earnings, tendências de
recomendação, posições de holders). O cliente oficial é único — o loader `loadQuoteSummary` — que
também despacha a variante batch (`v11`, `?symbols=`) quando recebe um array de símbolos; esta
seção documenta a variante single, e a segunda metade deste arquivo documenta a variante batch.

Exige **autenticação dupla** (cookie de sessão + crumb), como o `/v7/finance/quote`. O envelope de
sucesso é de topo próprio — `quoteSummary.result` como array de um elemento, SEM chave `symbol` na
raiz (o símbolo é implícito na URL; a identidade vai DENTRO do módulo `price`/`quoteType`) — e a
camada `finance` só aparece nos envelopes de erro. O servidor responde **formatted por default**
(diferente do `/v7/finance/quote`, que devolve primitivos sem o parâmetro), os percentuais chegam
em **fração decimal** no `raw` (o `fmt` já vem em %), e a ordem das chaves dos módulos NÃO segue a
ordem pedida — é determinada pelo servidor (estável para o mesmo conjunto de módulos; ver bloco 2).

| | |
| :--- | :--- |
| Método | `GET` — `HEAD` exige a MESMA credencial do GET (200, corpo vazio, cache `private, no-cache, no-store`; sem crumb → `401`) e `OPTIONS` é anônimo (200, `Allow: HEAD,GET,OPTIONS`; corpo negociado pelo `Accept` — WADL integral, bloco 5b); `POST` → `405` com envelope de erro e SEM header `Allow` |
| Hosts | `query1` · `query2` (`.finance.yahoo.com` — espelhos idênticos; query1 é o padrão do cliente) |
| Caminho | `/v10/finance/quoteSummary/{symbol}` — símbolo no PATH, case-insensitive (`aapl` resolve como `AAPL`), percent-encoded (`%5EGSPC`); `?symbol=` na QUERY → `404` com corpo TEXTUAL (bloco 5); com barra final (`?symbol=` após `/`) o mesmo 404 vira JSON com envelope `finance` |
| Autenticação | **Obrigatória e dupla** — cookie de sessão (`A3`) **e** crumb, na query (`?crumb=`) ou no header (`x-crumb`); faltando qualquer um dos dois → `401 Unauthorized` (`Invalid Crumb`) |
| User-Agent | Agente de navegador obrigatório — `Python-urllib` recebe `429 Edge: Too Many Requests` |
| Accept | Ausente ou `application/json` → `200`; `text/plain` → `406` com envelope de erro |
| Cache de borda | `public, max-age=1, stale-while-revalidate=9` — janela total de ~10 s por URL |
| Content-Type | `application/json;charset=utf-8` |

```json5
{
  // ==========================================================================
  // 1 · PARÂMETROS DA REQUISIÇÃO
  // ==========================================================================

  // Linha de requisição canônica (a que o loader do cliente envia):
  //
  //   curl -s \
  //     -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36" \
  //     -b "A3=…" \
  //     "https://query1.finance.yahoo.com/v10/finance/quoteSummary/AAPL?formatted=true&modules=price,summaryDetail&lang=en-US&region=US&crumb=…"

  request: {
    method: "GET",
    path: "/v10/finance/quoteSummary/{symbol}",
    params: {
      symbol: "AAPL",              // PATH · OBRIGATÓRIO · percent-encoded e case-insensitive
                                   //   (aapl == AAPL) · índices com ^ cru ou %5E · aceita os
                                   //   caracteres especiais dos tickers (. - = _ +) — BRK-B,
                                   //   BRL=X, PETR4.SA respondem no mesmo formato
                                   //   · trailing slash (/AAPL/) aceito
                                   //   · símbolo na QUERY (?symbol=) NÃO é roteado → 404
                                   //     com corpo textual (bloco 5)
                                   //   · inexistente → 404 "Quote not found for symbol: X"
                                   //     (bloco 5)
      modules: "price,…",          // OBRIGATÓRIO · lista CSV de módulos (bloco 2)
                                   //   · ausente ou vazio → 400 "Missing required query
                                   //     parameter=modules" (camada finance)
                                   //   · case-insensitive (PRICE → price)
                                   //   · duplicatas deduplicadas (price,price,summaryDetail
                                   //     → 2 módulos)
                                   //   · nome desconhecido ou módulo sem dado para o
                                   //     símbolo → descartado SEM erro; a chamada só falha
                                   //     (404 "No fundamentals data found for symbol: X")
                                   //     quando NENHUM módulo restante produz dado
                                   //   · espaço após a vírgula NÃO é aparado — " summaryDetail"
                                   //     (com espaço) não resolve e é descartado
      formatted: "true",           // DEFAULT DO SERVIDOR é formatted — omitido devolve os
                                   //   valores como {raw, fmt} (DIFERENTE do v7/finance/quote,
                                   //   cujo default devolve primitivos) · "false" primitiviza
                                   //   os valores de mercado (regras e exceções no bloco 5)
      lang: "en-US",               // INJETADOS PELO TRANSPORTE com os valores da SESSÃO
      region: "US",                //   (searchParams.set — sobrescrevem a query montada pelo
                                   //   loader) — localizam campos de perfil (bloco 6)

      // ---- flags condicionais (o cliente só as envia com a feature flag acesa) ----
      enableQSPExpandedEarnings: "true", // além de ir na query, faz o loader INJETAR os
                                         //   módulos earningsGaap + earningsNonGaap na lista
                                         //   (o upgradeDowngradeHistory da aba Analysis é do
                                         //   compositor da página, não deste loader)
      overnightPrice: "true",            // feature enableOvernight — habilita os dados da
                                         //   sessão overnight no módulo price (efeito depende
                                         //   de o ativo TER dado overnight; sem dado observado)
                                         //   · no contrato do servidor: default false (WADL,
                                         //     bloco 5b)
      enablePrivateCompany: "true",      // feature homônima — variantes de empresa privada
                                         //   · no contrato do servidor: default TRUE (WADL, bloco 5b)
      mockPrivateCompany: "true",        // resposta simulada de empresa privada (mock)
      mockOvernightPrice: "true",        // preço overnight simulado (mock)
      dataVersion: "v2",                 // enviado pelo loader sob a flag de sessão
                                         //   enableMorningstarDataUpgrade — dataset
                                         //   Morningstar atualizado; sem a flag, ausente.
                                         //   Gatilho ÚNICO: um segundo flag citado em
                                         //   auditoria anterior (enableMorningStar-
                                         //   Templatesv3) NÃO existe no código atual do
                                         //   cliente — verificação literal do fonte
                                         //   · no contrato do servidor: default "v1" e enum
                                         //     validado v1|v2 → 400 fora dele (WADL, bloco 5b)

      // Chaves desconhecidas na query são aceitas e ignoradas silenciosamente
      // (o valor dos módulos não muda).
    },
  },
}
```

Semântica e casos de borda por parâmetro:

| Parâmetro | Tipo | Obrigatório | Padrão | Comportamento e Casos de Borda |
| :--- | :--- | :---: | :--- | :--- |
| `{symbol}` (path) | string | Sim | — | Percent-encoded, case-insensitive; `^` cru ou `%5E`; aceita `.` `-` `=` `_` `+`; trailing slash aceito. Na QUERY (`?symbol=`) não é roteado → `404` textual (com barra final na path, o 404 vira JSON com envelope `finance`). Inexistente → `404` com `quoteSummary.error` `"Quote not found for symbol: X"`. |
| `modules` | CSV | Sim | — | Ausente/vazio → `400` (camada finance). Case-insensitive; duplicatas deduplicadas; desconhecido ou sem dado para o símbolo → **descartado silenciosamente**; `404 "No fundamentals data found for symbol: X"` só quando nenhum módulo restante produz dado. Espaço após vírgula não é aparado. |
| `formatted` | bool | Não | `true` (servidor) | Default do servidor é **formatted** — omitido devolve `{raw, fmt}`; cravado no WADL do OPTIONS (`xs:boolean`, default `true` — bloco 5b). `false` primitiviza os valores de mercado; campos sem dado são omitidos (com `true` materializam como wrappers vazios — bloco 5). |
| `lang` / `region` | string | Não | sessão (`en-US`/`US`) | Injetados pelo transporte com os valores da sessão (`searchParams.set` — sobrescrevem a query). Localizam `sectorDisp`/`industryDisp` (perfil) e a formatação numérica de campos sempre-embrulhados; NÃO localizam `shortName`/`longName` do `price` (bloco 6). |
| `enableQSPExpandedEarnings` | flag | Não | — | Vai na query E faz o loader injetar `earningsGaap` + `earningsNonGaap` na lista de módulos. |
| `overnightPrice` | bool | Não | `false` (servidor) | Habilita dados overnight no módulo `price` (feature `enableOvernight`) — só materializa quando o ativo tem dado overnight; declarado no WADL do OPTIONS (bloco 5b). |
| `enablePrivateCompany` | bool | Não | `true` (servidor) | Variantes de empresa privada (`.PVT` responde 200 com e sem a flag); o WADL declara default `true` — `.PVT` sem dado continua `404` com `true`, `false` e default. |
| `mockPrivateCompany` / `mockOvernightPrice` | flag | Não | — | Flags de simulação (mock) — aceitas sem efeito observado no payload. |
| `dataVersion` | string | Não | `v1` (servidor) | `v2` enviado sob a flag de sessão `enableMorningstarDataUpgrade` (dataset Morningstar atualizado; gatilho ÚNICO — o loader faz `flag ? {dataVersion:"v2"} : {}`); sem ela, ausente. O servidor VALIDA o enum: fora de `v1, v2` → `400` `"dataVersion must be one of v1, v2"` na camada `quoteSummary` (bloco 5b). |
| `earningsCorporateActionsEnabled` | bool | Não — o cliente oficial não envia | `false` (servidor) | Existe SÓ no contrato do servidor (WADL do OPTIONS, bloco 5b); com/sem em `calendarEvents,price` o corpo é idêntico para AAPL. |

> **Convenções:**
> - Chaves desconhecidas na query string são ignoradas silenciosamente.
> - A **ordem das chaves dos módulos** no `result[0]` não é a ordem pedida: é determinada pelo
>   servidor, é a MESMA para símbolos diferentes quando o conjunto pedido é o mesmo (SPY e AAPL
>   com 7 módulos comuns devolveram a sequência idêntica) e muda conforme o conjunto pedido —
>   não é uma sequência global única (bloco 2).
> - A **contagem de chaves dentro de cada módulo flutua** com a disponibilidade de dado
>   (pré/pós-mercado, campos de outras classes como `strikePrice`/`openInterest` no `price`)
>   e com `formatted` — os números do bloco 2 são indicativos.
> - Percentuais (ex.: `regularMarketChangePercent`, margens, retornos) chegam em **fração
>   decimal** no `raw` (0.0058 = 0.58%) — o `fmt` já vem em percentual.

#### Vocabulário de módulos

```json5
{
  // ==========================================================================
  // 2 · VOCABULÁRIO DE MÓDULOS (cada module é um objeto aninhado completo)
  // ==========================================================================
  // 60 nomes materializam no fio em alguma classe — os 53 originais do universo
  // do app + upgradeDowngradeHistoryLatest (cravado na composição live da página
  // sustainability) + earningsCallTranscriptsLatest (composto pela página de
  // quote sob enableQSPLatestEarningsCallTranscripts) + o quarteto do comparador
  // getCeo/quoteDetail/morningstarFinancials/quoteTrailingReturns (descoberto na
  // auditoria de funções: é a lista da constante un do loadComparison, o
  // 3º chamador da variante ws — e materializa TAMBÉM no v10 single e no v11
  // batch, idênticos byte-a-byte entre os três endpoints) + quotePerformance-
  // Overview (módulo da watchlist, documentado nas notas do cliente como módulo
  // do gateway ws — e materializa TAMBÉM no v10 single e no lote); as contagens de
  // chaves são as observadas
  // (AAPL/SPY/INTC formatted=false salvo indicação) e flutuam com
  // disponibilidade de dado e com formatted.

  "catalogo": {
    // ---- identidade, preço e métricas --------------------------------------
    "price": ["36 chaves — cotação da aba: pre/postMarket*, regularMarketPrice/Time/Change/",
              "  DayHigh/DayLow/Volume, currency, shortName, longName, quoteType, symbol,",
              "  exchangeName, marketState, fiftyTwoWeek*, averageDailyVolume*Path…"],
    "summaryDetail": ["63-64 chaves (formatted=true, SPY/INTC) — previousClose/open, dayLow/dayHigh",
              "  (+ aliases regularMarket*), dividendRate/Yield, exDividendDate, payoutRatio,",
              "  fiveYearAvgDividendYield, beta, trailingPE/forwardPE, volume +",
              "  averageVolume/averageVolume10days/averageDailyVolume10Day, bid/ask + tamanhos,",
              "  marketCap, nonDilutedMarketCap, yield, ytdReturn/qtdReturn, totalAssets,",
              "  fiftyTwoWeekLow/High, allTimeHigh/allTimeLow, fulldayPrice/Change/ChangePercent,",
              "  priceToSalesTrailing12Months, fiftyDayAverage, twoHundredDayAverage,",
              "  trailingAnnualDividend*, navPrice, currency + campos de cripto (fromCurrency,",
              "  volume24Hr, circulatingSupply, maxSupply…), tradeable, fullyDilutedValue"],
    "defaultKeyStatistics": ["61 chaves (formatted=true, INTC) — enterpriseValue, forwardPE,",
              "  profitMargins, floatShares, sharesOutstanding, sharesShort* (3),",
              "  dateShortInterest, sharesPercentSharesOut, heldPercent*, shortRatio,",
              "  shortPercentOfFloat, beta, impliedSharesOutstanding, morningStar*, category,",
              "  bookValue, priceToBook, ytdReturn/qtdReturn/beta3Year/totalAssets/yield",
              "  (bloco de FUNDO, vazio em equity), fundFamily, fundInceptionDate, legalType,",
              "  threeYear/fiveYearAverageReturn, lastFiscalYearEnd, nextFiscalYearEnd,",
              "  mostRecentQuarter, earningsQuarterlyGrowth, netIncomeToCommon, trailingEps,",
              "  forwardEps, pegRatio, lastSplitFactor/Date, enterpriseToRevenue/Ebitda,",
              "  52WeekChange, SandP52WeekChange, lastDividendValue/Date, lastCapGain,",
              "  annualHoldingsTurnover + bloco .PVT (latestFundingDate, latestAmountRaised,",
              "  latestImpliedValuation, latestShareClass, leadInvestor, fundingToDate,",
              "  totalFundingRounds) — presente como template vazio em equity"],
    "financialData": ["30 chaves — currentPrice, target*Price (High/Low/Mean/Median),",
              "  recommendationMean/Key, numberOfAnalystOpinions, totalCash, totalDebt,",
              "  debtToEquity, currentRatio, quickRatio, totalRevenue, revenuePerShare,",
              "  revenueGrowth, grossProfits, *Margins, ebitda, earningsGrowth,",
              "  freeCashflow, operatingCashflow, returnOn*, financialCurrency"],
    "quoteType": ["13 chaves — MÓDULO LEGADO (mesmo nome do serviço /v1/finance/quoteType):",
              "  exchange, quoteType, symbol, underlyingSymbol, shortName, longName,",
              "  firstTradeDateEpochUtc, timeZoneFullName, timeZoneShortName, uuid,",
              "  messageBoardId, gmtOffSetMilliseconds, maxAge"],

    // ---- quarteto do comparador (Research Hub /compare) ----------------------
    // Descobertos na auditoria de funções do loader: só o loadComparison os pede
    // (via variante ws), mas o servidor os resolve nos TRÊS endpoints com o
    // MESMO corpo (cravado ws == v10 == v11 em AAPL).
    "getCeo": ["2 chaves — officers (lista com EXATAMENTE 1 registro: maxAge, name, age,",
              "  title, yearBorn, fiscalYear, exercisedValue, unexercisedValue) + maxAge —",
              "  o CEO vigente (AAPL: 'Mr. John  Ternus', 'CEO & Director', nasc. 1976)"],
    "quoteDetail": ["9 chaves — recorte de estrutura acionária + juros curtos: maxAge,",
              "  floatShares, sharesOutstanding, sharesShort, heldPercentInsiders,",
              "  heldPercentInstitutions, shortRatio, shortPercentOfFloat, beta — é um",
              "  subconjunto compacto do defaultKeyStatistics (sem os blocos de fundo e",
              "  sem .PVT)"],
    "morningstarFinancials": ["30 chaves — métricas Morningstar TTM/trimestrais no formato",
              "  {asOfDate, periodType 'TTM', reportedValue {raw, fmt}}: financialCurrency,",
              "  maxAge, trailingPE/ForwardPERatio/PBRatio/PSRatio/EVToEBITDARatio,",
              "  trailingEnterpriseValue, DilutedEPS/BasicEPS, ForwardDividend(+Yield),",
              "  TotalRevenue, OperatingExpense/Income/Margin, GrossProfit/Margin,",
              "  FreeCashFlow, Operating/InvestingCashFlow, ROA/ROIC, ProfitMargin,",
              "  PriceToFCFRatio, ReceivableTurnover, CapitalExpenditure + blocos",
              "  quarterlyDilutedEPS1YrGrowth, quarterlyRevenueGrowthYoY,",
              "  quarterlyInventory — dataVersion=v2 NÃO muda o corpo (cravado com/sem)"],
    "quoteTrailingReturns": ["2 chaves — maxAge + trailingReturns {asOfDate, ytd, oneWeek,",
              "  oneMonth, threeMonth, oneYear, threeYear, fiveYear, tenYear} (fração",
              "  raw + fmt %) — retornos acumulados do preço (AAPL: 1y 34.91%,",
              "  10y 1,202.77%)"],

    // ---- perfil -------------------------------------------------------------
    "assetProfile": ["26-34 chaves (formatted=true) — address1/2, city, state, zip,",
              "  country, phone, website, industry, sector, sectorDisp, industryDisp,",
              "  longBusinessSummary, fullTimeEmployees, companyOfficers (lista — pay",
              "  sempre-embrulhado), irWebsite, executiveTeam + bloco de GOVERNANÇA:",
              "  auditRisk, boardRisk, compensationRisk, shareHolderRightsRisk, overallRisk,",
              "  governanceEpochDate, compensationAsOfEpochDate"],
    "summaryProfile": ["19 chaves — o recorte de perfil sem governança: address*, city,",
              "  state, zip, country, phone, website, industry(+Key/Disp), sector(+Key/Disp),",
              "  longBusinessSummary, fullTimeEmployees, companyOfficers, irWebsite,",
              "  executiveTeam, maxAge"],

    // ---- demonstrações financeiras (cada uma = lista anual/quarterly) --------
    "incomeStatementHistory": ["2 chaves — incomeStatementHistory (lista anual) + maxAge"],
    "incomeStatementHistoryQuarterly": ["2 chaves — idem em base trimestral"],
    "balanceSheetHistory": ["2 chaves — balanceSheetStatements (lista anual) + maxAge"],
    "balanceSheetHistoryQuarterly": ["2 chaves — idem em base trimestral"],
    "cashflowStatementHistory": ["2 chaves — cashflowStatements (lista anual) + maxAge"],
    "cashflowStatementHistoryQuarterly": ["2 chaves — idem em base trimestral"],
    "financialsTemplate": ["2-3 chaves — marcador de template contábil do símbolo:",
              "  code ('N'/'B'), codeV2 (quando há), maxAge"],

    // ---- earnings ------------------------------------------------------------
    "earnings": ["5 chaves — variante LEGADO da metodologia DEFAULT do símbolo: maxAge,",
              "  earningsChart, financialsChart, financialCurrency, defaultMethodology"],
    "earningsGaap": ["5 chaves — série GAAP: earningsChart (quarterly com actual/estimate/",
              "  fiscalQuarter/calendarQuarter/difference/surprisePct/periodEndDate/",
              "  reportedDate + currentQuarterEstimate* + earningsDate + isEarningsDateEstimate),",
              "  financialsChart (yearly/quarterly com revenue/earnings/profitMargin),",
              "  financialCurrency, defaultMethodology"],
    "earningsNonGaap": ["5 chaves — MESMA estrutura; estimates divergem da série GAAP",
              "  (AAPL: 1.77112 vs 1.76993; surprisePct 4.45 vs 4.52)"],
    "earningsHistory": ["3 chaves — history (surprises por quarter), defaultMethodology, maxAge"],
    "earningsHistoryGaap": ["3 chaves — history na série GAAP"],
    "earningsHistoryNonGaap": ["3 chaves — history na série Non-GAAP"],
    "earningsTrend": ["3 chaves — trend (estimativas por período), defaultMethodology, maxAge"],
    "earningsTrendGaap": ["3 chaves — trend na série GAAP"],
    "earningsTrendNonGaap": ["3 chaves — trend na série Non-GAAP"],
    "earningsCallTranscripts": ["2 chaves — transcripts (lista: title, fiscalYear, fiscalPeriod,",
              "  date, updated, transcriptId, type 'IN_HOUSE'/'RAW', eventId, eventType, url,",
              "  s3Url, maxAge) + maxAge — histórico completo (AAPL: 64 desde 2010)"],
    "earningsCallTranscriptsLatest": ["2 chaves — MESMA estrutura do canônico; janela RECENTE",
              "  (AAPL: 12 entradas vs 64 no canônico) — variante composta pela página",
              "  de quote sob enableQSPLatestEarningsCallTranscripts; coexiste com o",
              "  canônico quando ambos são pedidos"],
    "earningsCallAudios": ["2 chaves — audios + maxAge"],

    // ---- desempenho ------------------------------------------------------------
    "equityPerformance": ["4 chaves — maxAge, benchmark {symbol, shortName},",
              "  performanceOverview (asOfDate, fiveDaysReturn…tenYearTotalReturn, maxReturn),",
              "  performanceOverviewBenchmark — desempenho com preços AJUSTADOS"],
    "quotePerformanceOverview": ["4 chaves — MESMA família da equityPerformance: maxAge,",
              "  benchmark {symbol, shortName}, performanceOverview (asOfDate,",
              "  fiveDaysReturn, oneMonthReturn, threeMonthReturn, sixMonthReturn,",
              "  ytdReturnPct, oneYearTotalReturn, twoYearTotalReturn — wrappers",
              "  {raw, fmt}), performanceOverviewBenchmark (idem sem os retornos de",
              "  1/2 anos) — módulo da watchlist do gateway ws que materializa",
              "  TAMBÉM no v10 single e no lote v11"],
    "quoteUnadjustedPerformanceOverview": ["4 chaves — MESMA estrutura com preços",
              "  NÃO ajustados (os dois coexistem na mesma resposta; divergem nos retornos",
              "  longos e maxReturn é idêntico)"],
    "chartPreviousClose": ["3 chaves — lastBarTimestamp, range (1d/5d/1mo/3mo/6mo/1y…), maxAge"],

    // ---- tendências de consenso ----------------------------------------------
    "industryTrend": ["3 chaves — maxAge, symbol (o próprio ticker), estimates (lista)"],
    "indexTrend": ["3 chaves — idem (estimates do índice de referência; symbol ^GSPC)"],
    "sectorTrend": ["3 chaves — idem (estimates do setor)"],

    // ---- recomendações --------------------------------------------------------
    "recommendationTrend": ["2 chaves — trend (period 0m/-1m/-2m/-3m com strongBuy, buy,",
              "  hold, sell, strongSell) + maxAge"],
    "upgradeDowngradeHistory": ["2 chaves — history (epochGradeDate, firm, toGrade, fromGrade,",
              "  action reit/main/init/up/down, priceTargetAction, currentPriceTarget,",
              "  priorPriceTarget) + maxAge"],
    "upgradeDowngradeHistoryLatest": ["2 chaves — MESMO shape do upgradeDowngradeHistory",
              "  (history + maxAge; alvos numéricos plain) — nome pedido pela página",
              "  sustainability oficial; materializa em AAPL (ex.: MoffettNathanson,",
              "  Loop Capital, JP Morgan com priceTargetAction Raises/Lowers)"],

    // ---- holders ---------------------------------------------------------------
    "institutionOwnership": ["2 chaves — ownershipList + maxAge"],
    "fundOwnership": ["2 chaves — ownershipList (fundos) + maxAge"],
    "majorHoldersBreakdown": ["5 chaves — insidersPercentHeld, institutionsPercentHeld,",
              "  institutionsFloatPercentHeld, institutionsCount, maxAge"],
    "majorDirectHolders": ["2 chaves — holders + maxAge"],
    "insiderHolders": ["2 chaves — holders + maxAge"],
    "insiderTransactions": ["2 chaves — transactions + maxAge"],
    "netSharePurchaseActivity": ["14 chaves — period, buyInfoCount/Shares, sellInfo*,",
              "  netInfoCount/Shares/PercentInsiderShares, totalInsiderShares…"],

    // ---- calendário e corporativo ----------------------------------------------
    "calendarEvents": ["4 chaves — maxAge, earnings (earningsDate, earningsCallDate,",
              "  isEarningsDateEstimate, earningsAverage/Low/High, revenueAverage/Low/High),",
              "  exDividendDate, dividendDate"],
    "corporateActions": ["2 chaves — corporateActions (lista) + maxAge"],
    "secFilings": ["2 chaves — filings (epoch, type, title, link) + maxAge"],
    "pageViews": ["4 chaves — shortTermTrend/midTermTrend/longTermTrend ('DOWN'/'NONE'…), maxAge"],
  },

  // ---- módulos exclusivos por classe (só materializam nelas) -------------------
  "exclusivosPorClasse": {
    "fundProfile": ["ETF + MUTUALFUND (15 chaves em SPY) — styleBoxUrl, family, categoryName, legalType,",
              "  managementInfo, feesExpensesInvestment (+ variante *Cat), initInvestment/,",
              "  initIraInvestment/initAipInvestment, subseqInvestment/…, brokerages"],
    "fundPerformance": ["ETF + MUTUALFUND — fundCategoryName, performanceOverview(+Cat),",
              "  trailingReturns/Nav/Cat, annualTotalReturns (returns + returnsCat, série",
              "  histórica anual), pastQuarterlyReturns, riskOverviewStatistics(+Cat) com",
              "  alpha/beta/rSquared/stdDev/sharpeRatio/treynorRatio por período"],
    "topHoldings": ["ETF + MUTUALFUND — cash/stock/bond/other/preferred/convertiblePosition,",
              "  holdings (top 10: symbol, holdingName, holdingPercent), equityHoldings,",
              "  bondHoldings, bondRatings, sectorWeightings (11 setores)"],
    "futuresChain": ["FUTURE — futures (lista de contratos, ex.: GCZ26.CMX…GCZ29.CMX) +",
              "  futuresChainDetails (por contrato: language, exchangeName, underlying…,",
              "  shortName, longName, expireDate/IsoDate, symbol)"],
    "components": ["INDEX — components (lista de componentes; ^GSPC → []) + maxAge"],
    "attribution": ["CRYPTOCURRENCY — providers (lista: name, url, openUrlExternally;",
              "  BTC-USD → Coinbase, CoinMarketCap) + maxAge"],
    "fundingRounds": ["PRIVATE_COMPANY — fundingRoundList (date, issuePrice, amountRaised,",
              "  …) + maxAge"],
    "marks": ["PRIVATE_COMPANY — markList (date, shareClass, price, fund, filingLink…) + maxAge"],
    "relatedCompanies": ["PRIVATE_COMPANY — relatedCompanyList (symbol, name,",
              "  estimatedValuation) + maxAge"],
    "assetComponents": ["índices customizados (CUL_IDX/CUL_SUB_IDX no mapa do cliente) —",
              "  não materializa em equity/index comuns (descartado)",
              "  · fechamento: a família CUL existe no enum de fio do protocolo",
              "  (CUL_IDX 43 · CUL_SUB_IDX 44 · CUL_ASSET 45) mas NENHUM símbolo público",
              "  CUL_* responde: 12 candidatos literais (CUL_IDX, CUL_SUB_IDX, CUL_ASSET,",
              "  TOP_IDX, YF_IDX…) em quoteType → 200 com result VAZIO; em v7/quote e",
              "  search (31 queries + buscas literais) → 0 resultados; em chart → 404",
              "  'No data found, symbol may be delisted'; em quoteSummary → 404 'Quote not",
              "  found for symbol: CUL_IDX' (erro de SÍMBOLO, distinto do 'No fundamentals",
              "  data found' de módulo). Símbolos CUL são universos customizados sem",
              "  acesso público — a composição do cliente é executável, mas o módulo fica",
              "  sem corpo observável no fio aberto"],
  },

  // ---- nomes pedidos pelo cliente que não produzem dado no fio ------------------
  // esgScores entra nas composições do cliente (EQUITY.summary, ETF/MUTUALFUND
  // details, sustainability) e NUNCA materializa — fechamento 360°:
  // · sozinho → 404 'No fundamentals data found for symbol' (idêntico com
  //   dataVersion=v2 e sem dataVersion — flag enableMorningstarDataUpgrade
  //   off em prod; confirmado em fonte de 23/10/2026)
  // · acompanhado → descartado sem erro (esgScores,earnings → só earnings)
  // · A PRÓPRIA página sustainability oficial pede esgScores na composição de 18
  //   módulos com flags enablePrivateCompany/enableQSPExpandedEarnings/
  //   overnightPrice (data-url embutida no SSR) — o servidor devolve 200 com 17
  //   módulos e descarta o esgScores silenciosamente
  // · v11 batch: 15 EQUITY ESG-heavy + 10 outras classes (ETF/INDEX/CRYPTO/
  //   CURRENCY/FUTURE/PVT) → 200 com errorResult por elemento, com e sem
  //   dataVersion=v2
  // No fio o comportamento é indistinguível de um nome desconhecido:
  "semDadoNoFio": ["esgScores"],

  // ---- regras de resolução da lista ----------------------------------------------
  "resolucao": {
    "case": "insensível — PRICE e price resolvem o mesmo módulo (a chave volta em caixa baixa)",
    "duplicatas": "deduplicadas pelo servidor (price,price,summaryDetail → 2 módulos)",
    "espaco": "NÃO aparado — 'price,%20summaryDetail' devolve só price",
    "descarte": ["nome desconhecido OU módulo sem dado para o símbolo → descartado sem erro;",
                 "  a chamada inteira 404a só quando nenhum módulo restante produz dado",
                 "  (SPY pedindo 17 módulos devolveu 10 — 7 descartados sem erro)"],
  },

  // ---- ordem das chaves -----------------------------------------------------------
  // A ordem NÃO segue a ordem pedida. É determinada pelo servidor e é ESTÁVEL para o
  // mesmo conjunto de módulos — SPY e AAPL com o mesmo conjunto devolvem a MESMA
  // sequência — mas VARIA conforme o conjunto pedido (não é uma sequência global única).
  // Dois exemplos observados (sequência de materialização):
  "ordemExemplo34Modulos": [
    "assetProfile", "recommendationTrend", "cashflowStatementHistory", "indexTrend",
    "quoteUnadjustedPerformanceOverview", "defaultKeyStatistics", "industryTrend",
    "incomeStatementHistory", "fundOwnership", "earningsGaap", "summaryDetail",
    "insiderHolders", "calendarEvents", "upgradeDowngradeHistory", "chartPreviousClose",
    "price", "balanceSheetHistory", "earningsTrend", "earningsNonGaap", "secFilings",
    "institutionOwnership", "majorHoldersBreakdown", "balanceSheetHistoryQuarterly",
    "earningsHistory", "majorDirectHolders", "summaryProfile", "netSharePurchaseActivity",
    "insiderTransactions", "sectorTrend", "incomeStatementHistoryQuarterly",
    "cashflowStatementHistoryQuarterly", "earnings", "corporateActions", "financialData"
  ],
  "ordemExemplo7Modulos": [
    "assetProfile", "summaryDetail", "pageViews", "price",
    "quoteUnadjustedPerformanceOverview", "defaultKeyStatistics", "corporateActions"
  ],
  "notaOrdem": ["nas duas amostras assetProfile abre a resposta; de resto as posições",
                "  relativas mudam entre conjuntos — consumidor NÃO deve depender de posição"],

  // ---- matriz empírica classe×módulo ----------------------------------------
  // Sonda definitiva [live, 23/10/2026]: UMA chamada por classe pedindo TODOS os
  // 62 nomes conhecidos de uma vez (AAPL · SPY · BTC-USD · ^GSPC · USD=X · GC=F);
  // o servidor mesmo diz o que materializa. PVT é derivado do mapa do cliente
  // (não há símbolo .PVT público). MUTUALFUND não foi sondado — usar ETF como proxy
  // (mesmo conjunto de exclusivos: fundProfile, fundPerformance, topHoldings).
  //
  // Resultado: 62 nomes → 57 materializam ao vivo em alguma classe + 3 exclusivos
  // de empresa privada (PVT, só no mapa) = 60 podem materializar; 2 NUNCA voltam
  // publicamente (esgScores, assetComponents — descartados silenciosamente em
  // TODAS as classes). Materializaram por classe: EQUITY 51 · ETF 15 · CRYPTO 13 ·
  // INDEX 11 · FUTURE 10 · CURRENCY 9 (contagem inclusiva dos módulos comuns).
  //
  // Legenda: ● = materializou ao vivo · ○ = só no mapa do cliente (PVT, sem fio
  // público) · · = descartado nesta classe · ✗ = nunca materializa publicamente.
  "matrizClasseModulo": {
    "identidade/preço/resumo": {
      "price":                            "EQ ● · ETF ● · CRY ● · IDX ● · CUR ● · FUT ● · PVT ·",
      "summaryDetail":                    "EQ ● · ETF ● · CRY ● · IDX ● · CUR ● · FUT ● · PVT ·",
      "defaultKeyStatistics":             "EQ ● · ETF ● · CRY ·  · IDX ● · CUR ·  · FUT ·  · PVT ○",
      "financialData":                    "EQ ● · ETF ·  · CRY ·  · IDX ·  · CUR ·  · FUT ·  · PVT ·",
      "quoteType (legado)":               "EQ ● · ETF ● · CRY ● · IDX ● · CUR ● · FUT ● · PVT ·",
      "quotePerformanceOverview":         "EQ ● · ETF ● · CRY ● · IDX ● · CUR ● · FUT ● · PVT ·",
    },
    "quarteto do comparador": {
      "getCeo":                           "EQ ● · ETF ·  · CRY ·  · IDX ·  · CUR ·  · FUT ·  · PVT ·",
      "quoteDetail":                      "EQ ● · ETF ·  · CRY ·  · IDX ·  · CUR ·  · FUT ·  · PVT ·",
      "morningstarFinancials":            "EQ ● · ETF ·  · CRY ·  · IDX ·  · CUR ·  · FUT ·  · PVT ·",
      "quoteTrailingReturns":             "EQ ● · ETF ·  · CRY ● · IDX ● · CUR ● · FUT ● · PVT ·",
    },
    "perfil": {
      "assetProfile":                     "EQ ● · ETF ● · CRY ● · IDX ·  · CUR ·  · FUT ·  · PVT ○",
      "summaryProfile":                   "EQ ● · ETF ● · CRY ● · IDX ·  · CUR ·  · FUT ·  · PVT ○",
    },
    "demonstrações": {
      "incomeStatementHistory":           "EQ ● · (demais classes: descartado)",
      "incomeStatementHistoryQuarterly":  "EQ ● · (demais classes: descartado)",
      "balanceSheetHistory":              "EQ ● · (demais classes: descartado)",
      "balanceSheetHistoryQuarterly":     "EQ ● · (demais classes: descartado)",
      "cashflowStatementHistory":          "EQ ● · (demais classes: descartado)",
      "cashflowStatementHistoryQuarterly": "EQ ● · (demais classes: descartado)",
      "financialsTemplate":              "EQ ● · (demais classes: descartado)",
    },
    "earnings": {
      "earnings":                         "EQ ● · (demais classes: descartado)",
      "earningsGaap":                     "EQ ● · (demais classes: descartado)",
      "earningsNonGaap":                  "EQ ● · (demais classes: descartado)",
      "earningsHistory":                  "EQ ● · (demais classes: descartado)",
      "earningsHistoryGaap":              "EQ ● · (demais classes: descartado)",
      "earningsHistoryNonGaap":            "EQ ● · (demais classes: descartado)",
      "earningsTrend":                    "EQ ● · (demais classes: descartado)",
      "earningsTrendGaap":                "EQ ● · (demais classes: descartado)",
      "earningsTrendNonGaap":             "EQ ● · (demais classes: descartado)",
      "earningsCallTranscripts":          "EQ ● · (demais classes: descartado)",
      "earningsCallTranscriptsLatest":    "EQ ● · (demais classes: descartado)",
      "earningsCallAudios":               "EQ ● · (demais classes: descartado)",
    },
    "desempenho": {
      "equityPerformance":                "EQ ● · ETF ● · CRY ● · IDX ● · CUR ● · FUT ● · PVT ·",
      "quoteUnadjustedPerformanceOverview": "EQ ● · ETF ● · CRY ● · IDX ● · CUR ● · FUT ● · PVT ·",
      "chartPreviousClose":              "EQ ● · ETF ● · CRY ● · IDX ● · CUR ● · FUT ● · PVT ·",
    },
    "tendências": {
      "industryTrend":                    "EQ ● · (demais classes: descartado)",
      "indexTrend":                       "EQ ● · (demais classes: descartado)",
      "sectorTrend":                      "EQ ● · (demais classes: descartado)",
    },
    "recomendações": {
      "recommendationTrend":              "EQ ● · (demais classes: descartado)",
      "upgradeDowngradeHistory":          "EQ ● · (demais classes: descartado)",
      "upgradeDowngradeHistoryLatest":    "EQ ● · (demais classes: descartado)",
    },
    "holders": {
      "institutionOwnership":             "EQ ● · (demais classes: descartado)",
      "fundOwnership":                    "EQ ● · (demais classes: descartado)",
      "majorDirectHolders":               "EQ ● · (demais classes: descartado)",
      "majorHoldersBreakdown":            "EQ ● · (demais classes: descartado)",
      "insiderHolders":                   "EQ ● · (demais classes: descartado)",
      "insiderTransactions":              "EQ ● · (demais classes: descartado)",
      "netSharePurchaseActivity":         "EQ ● · (demais classes: descartado)",
    },
    "calendário/corporativo": {
      "calendarEvents":                   "EQ ● · ETF ·  · CRY ·  · IDX ·  · CUR ·  · FUT ·  · PVT ·",
      "corporateActions":                 "EQ ● · ETF ● · CRY ● · IDX ● · CUR ● · FUT ● · PVT ·",
      "secFilings":                       "EQ ● · (demais classes: descartado)",
      "pageViews":                        "EQ ● · ETF ● · CRY ● · IDX ·  · CUR ·  · FUT ·  · PVT ·",
    },
    "exclusivos por classe": {
      "fundProfile":                      "ETF ● · MUTUALFUND ● · (demais: descartado)",
      "fundPerformance":                  "ETF ● · MUTUALFUND ● · (demais: descartado)",
      "topHoldings":                      "ETF ● · MUTUALFUND ● · (demais: descartado)",
      "futuresChain":                     "FUT ● · (demais: descartado)",
      "components":                       "IDX ● · (demais: descartado)",
      "attribution":                      "CRY ● · (demais: descartado)",
      "fundingRounds":                    "PVT ○ · (demais: descartado — sem símbolo público)",
      "marks":                            "PVT ○ · (demais: descartado — sem símbolo público)",
      "relatedCompanies":                 "PVT ○ · (demais: descartado — sem símbolo público)",
    },
    "nunca materializa publicamente": {
      "esgScores":                         "EQ ✗ · ETF ✗ · CRY ✗ · IDX ✗ · CUR ✗ · FUT ✗ · PVT ✗",
      "assetComponents":                   "EQ ✗ · ETF ✗ · CRY ✗ · IDX ✗ · CUR ✗ · FUT ✗ · PVT ✗",
    },
  },

  "notasMatriz": [
    "O servidor tem MUITO mais do que as páginas pedem: a aba EQUITY mais rica usa 23",
    "  módulos, mas 51 existem para ações (o quarteto do comparador, GAAP/Non-GAAP,",
    "  variantes Latest etc. não estão em nenhuma composição de aba do cliente atual).",
    "calendarEvents NÃO é garantido: está na BASE_5 que o cliente pede em toda página,",
    "  mas o servidor o DESCARTA para ETF/INDEX/FUTURE/CURRENCY (fundo/índice não tem",
    "  calendário de earnings) — o 'piso comum' descreve o que é PEDIDO, não o",
    "  materializado para não-EQUITY.",
    "quoteTrailingReturns cobre quase todas as classes (exceto ETF); em EQUITY quem",
    "  cobre é equityPerformance.",
    "PVT: as linhas marcadas ○ na coluna PVT da matriz (defaultKeyStatistics,",
    "  assetProfile, summaryProfile — que a composição PRIVATE_COMPANY do cliente",
    "  pede; fundingRounds, marks, relatedCompanies — exclusivos da classe) derivam",
    "  do mapa do cliente, não do fio (não há símbolo .PVT público para cravar —",
    "  a classe privada provavelmente aceita mais do que esses 6).",
    "Sozinho, um módulo descartado para a classe produz 404 'No fundamentals data",
    "  found' (ex.: pedir só fundProfile para AAPL); acompanhado, é descartado sem erro.",
  ],
}
```

#### Composições por aba do cliente oficial

```json5
{
  // ==========================================================================
  // 3 · MAPA quoteType → ABA → MÓDULOS (o que a página de quote pede)
  // ==========================================================================
  // Composição da PÁGINA de quote por quoteType (literal, chave → abas → módulos).
  // Abas com lista vazia recebem só a base do cliente (ver nota). TODAS as linhas
  // abaixo constam no mapa literal da página — verificação linha a linha contra o
  // código do cliente (as que uma auditoria anterior marcou como "paywall" —
  // key-statistics, earnings-calls, purchase-info — ESTÃO no mapa da página). O
  // cliente deduplica a lista (o mapa literal contém duplicatas em ETF.details —
  // assetProfile ×2, esgScores ×2 — e MUTUALFUND.details — esgScores ×2).

  "quoteModules": {
    "EQUITY": {
      // ---- composição da PÁGINA (literal) -----------------------------------
      "summary": ["summaryProfile", "financialData", "recommendationTrend", "earnings",
                  "equityPerformance", "summaryDetail", "defaultKeyStatistics",
                  "calendarEvents", "esgScores"],
      "analysis": ["upgradeDowngradeHistory", "recommendationTrend", "financialData",
                   "earningsHistory", "earningsTrend", "earnings", "industryTrend",
                   "indexTrend", "sectorTrend"],
      "holders": ["institutionOwnership", "fundOwnership", "majorDirectHolders",
                  "majorHoldersBreakdown", "insiderTransactions", "insiderHolders",
                  "netSharePurchaseActivity"],
      "profile": ["assetProfile", "secFilings", "calendarEvents"],
      "details": ["earnings", "financialData", "insiderHolders", "summaryProfile",
                  "assetProfile", "esgScores"],
      "financials": ["financialsTemplate", "incomeStatementHistory", "cashflowStatementHistory",
                     "balanceSheetHistory", "incomeStatementHistoryQuarterly",
                     "cashflowStatementHistoryQuarterly", "balanceSheetHistoryQuarterly",
                     "earnings"],
      "news/latest-news/press-releases": ["equityPerformance", "calendarEvents",
                                          "defaultKeyStatistics", "financialData"],
      "earnings": ["earningsCallTranscripts"],
      "community": ["summaryProfile"],
      "company360": ["esgScores", "earnings"],
      "sustainability": ["esgScores"],
      "events": ["secFilings", "calendarEvents"],   // a ÚNICA destas abas com 2 módulos
      "sec-filing/sec-filings": ["secFilings", "equityPerformance", "calendarEvents"],
      "key-statistics": ["defaultKeyStatistics", "financialData", "summaryDetail",
                         "calendarEvents"],
      "earnings-calls": ["earningsCallTranscripts", "equityPerformance", "calendarEvents",
                         "defaultKeyStatistics"],
      // abas vazias da página (chart, dividends, history, innovation, options,
      //   seasonality) → só a base do cliente (ver nota)
    },
    "ETF": {
      "summary": ["summaryDetail", "defaultKeyStatistics", "assetProfile", "topHoldings",
                  "fundPerformance", "fundProfile", "esgScores"],
      "details": ["insiderHolders", "summaryProfile", "assetProfile", "esgScores",
                  "defaultKeyStatistics", "assetProfile", "topHoldings", "fundPerformance",
                  "fundProfile", "esgScores"],   // literal — duplicatas assetProfile ×2, esgScores ×2
      "holdings": ["assetProfile", "defaultKeyStatistics", "fundPerformance", "fundProfile",
                   "summaryDetail", "topHoldings"],
      "performance": ["assetProfile", "defaultKeyStatistics", "fundPerformance", "fundProfile",
                      "summaryDetail"],
      "risk": ["assetProfile", "fundPerformance", "defaultKeyStatistics", "summaryDetail"],
      "profile": ["defaultKeyStatistics", "assetProfile", "fundProfile", "topHoldings"],
      "news": ["fundPerformance", "fundProfile"],
      // abas vazias (chart, community, history, options, seasonality) → base
    },
    "MUTUALFUND": {
      "summary": ["defaultKeyStatistics", "assetProfile", "topHoldings", "fundPerformance",
                  "fundProfile", "esgScores"],
      "details": ["insiderHolders", "summaryProfile", "assetProfile", "esgScores",
                  "defaultKeyStatistics", "topHoldings", "fundPerformance", "fundProfile",
                  "esgScores"],   // literal — duplicata esgScores ×2
      "holdings/performance/risk": ["três abas com listas distintas entre si, iguais às do ETF"],
      "sustainability": ["esgScores"],
      "purchase-info": ["assetProfile", "fundProfile", "defaultKeyStatistics",
                        "summaryDetail", "fundPerformance"],   // literal da página (seção funds)
      // abas vazias (chart, community, history, seasonality) → base
    },
    "CRYPTOCURRENCY": { "summary": ["summaryProfile", "financialData", "recommendationTrend",
                                    "earnings", "summaryDetail", "defaultKeyStatistics",
                                    "calendarEvents", "assetProfile"],
                        "details": ["summaryProfile", "assetProfile"],
                        "profile": ["assetProfile", "secFilings", "calendarEvents"] },
    "FUTURE": { "summary/futures/details": ["futuresChain"] },
    "INDEX": { "details": ["summaryProfile", "components"], "components": ["components"],
               "profile": ["assetProfile"] },
    "PRIVATE_COMPANY": { "summary": ["defaultKeyStatistics", "assetProfile", "fundingRounds",
                                     "marks", "summaryProfile", "relatedCompanies"],
                         "profile": ["assetProfile"] },
    "CUL_IDX/CUL_SUB_IDX": { "components": ["assetComponents"], "summary": ["assetProfile"],
                             "profile": ["assetProfile"] },
    "INDICATOR": { "summary/details/community/history": ["summaryProfile"] },
    "CURRENCY/MONEYMARKET/OPTION": { "summary": [] },
  },
  "nota": ["CRYPTOCURRENCY ainda projeta quoteFields próprios na aba summary (ponte com o",
           "  v7: campos comuns + cmcRank); as abas com lista vazia compõem só a base do",
           "  cliente (price, summaryDetail, pageViews, financialsTemplate, calendarEvents) —",
           "  constante literal do cliente.",
           "  · Verificação literal linha a linha: key-statistics, earnings-calls (EQUITY) e",
           "  purchase-info (MUTUALFUND) constam no mapa da página (uma auditoria anterior",
           "  as marcava como paywall-only — INCORRETO). sec-filing/sec-filings já pedem",
           "  equityPerformance na própria página ([secFilings, equityPerformance,",
           "  calendarEvents]) — só events fica com 2 módulos. holders/performance/risk",
           "  têm listas distintas entre si (6/5/4 módulos).",
           "  · Cravo live (página sustainability AAPL): a data-url SSR pede 18 módulos —",
           "  base + corporateActions, earningsCallTranscripts, earningsGaap,",
           "  earningsNonGaap, equityPerformance, esgScores (nunca devolvido),",
           "  financialData, quoteUnadjustedPerformanceOverview, recommendationTrend,",
           "  summaryDetail, summaryProfile, upgradeDowngradeHistoryLatest — com flags",
           "  enablePrivateCompany/enableQSPExpandedEarnings/overnightPrice; o servidor",
           "  devolve 17 e o esgScores some sem erro"],
}
```

#### Constantes padrão

```json5
{
  // ==========================================================================
  // 4 · CONSTANTES DO ENDPOINT
  // ==========================================================================

  "hosts": [
    "https://query1.finance.yahoo.com",   // Host padrão
    "https://query2.finance.yahoo.com"    // Espelho secundário — mesmo conteúdo
  ],

  "defaults": {
    "formatted": "true",     // DEFAULT DO SERVIDOR — omitido devolve {raw, fmt} (diferente do v7)
    "lang": "en-US",         // valor do transporte/sessão
    "region": "US"
  },

  // Envelope: SUCESSO em camada própria; ERROS divididos em duas camadas:
  "envelope": {
    "sucesso": "quoteSummary.result (array de 1 elemento, SEM symbol na raiz) + error: null",
    "errosCamadaFinance": ["401 Invalid Crumb · 400 Missing required query parameter=modules ·",
                           "  405 Method Not Allowed · 406 Not Acceptable — SEMPRE sem dado"],
    "errosCamadaQuoteSummary": ["404 Quote not found / No fundamentals data found — erros de DADO"],
    "foraDeEnvelope": ["404 do ?symbol= em query responde corpo textual 'Not Found' (não JSON)",
                        "  — MAS com barra final na path a mesma chamada devolve o 404 em JSON",
                        "  com envelope finance {code 'Not Found', description 'HTTP 404 Not",
                        "  Found'} — cravado nas duas formas"]
  },

  "cache": "public, max-age=1, stale-while-revalidate=9 — resposta em cache pode ter ~10 s de atraso",
  "contentType": "application/json;charset=utf-8",
}
```

#### Resposta e erros

```json5
{
  // ==========================================================================
  // 5 · RESPOSTA E ERROS
  // ==========================================================================

  "sucesso": {
    "status": 200,
    "corpo": ["quoteSummary.result — array com EXATAMENTE 1 elemento; as chaves do elemento",
              "  são os módulos materializados (ordem do servidor, bloco 2); error: null;",
              "  NÃO há chave symbol na RAIZ — a identidade do ativo vai DENTRO dos módulos",
              "  (price.symbol, quoteType.symbol)"],
    "formatado": ["com formatted=true (ou omitido) cada valor de mercado vem como {raw, fmt}",
                  "  (e longFmt em números grandes)"],
    "cru": ["com formatted=false os valores vêm primitivos (344.52, não {raw: 344.52, fmt: '344.52'})"],
    "fracao": ["percentuais chegam em FRAÇÃO decimal no raw (0.0058 = 0.58%); o fmt já vem em %"],
  },

  // Campos SEM dado se comportam de forma diferente em cada modo:
  "camposSemDado": {
    "formattedTrue": ["materializam de três formas observadas: {} · {raw: null, fmt: null} · null",
                      "  — por isso a contagem de chaves do módulo É MAIOR com formatted=true"],
    "formattedFalse": ["são OMITIDOS do módulo (a chave não existe)"],
  },

  // Exceção à primitivização: campos de remuneração dentro de
  // assetProfile.companyOfficers (totalPay, exercisedValue, unexercisedValue)
  // permanecem {raw, fmt, longFmt} em QUALQUER formatted:
  "sempreEmbrulhado": "assetProfile.companyOfficers[].totalPay/exercisedValue/unexercisedValue",

  "semCrumbOuCookie": {
    "status": 401,
    "corpo": { "finance": { "result": null,
                            "error": { "code": "Unauthorized", "description": "Invalid Crumb" } } },
    "nota": "crumb falso e crumb vazio → o mesmo 401; o crumb também é aceito no header x-crumb"
  },

  "semModules": {
    "status": 400,
    "corpo": { "finance": { "result": null,
                            "error": { "code": "Bad Request",
                                       "description": "Missing required query parameter=modules" } } },
    "nota": "modules= vazio devolve o mesmo 400"
  },

  "simboloNaQuery": {
    "status": 404,
    "duasFormas": {
      "semBarra": { "content-type": "text/html", "corpo": "Not Found",
                    "nota": "?symbol=AAPL não é roteado — 404 com corpo TEXTUAL simples, SEM envelope JSON" },
      "comBarra": { "content-type": "application/json;charset=utf-8",
                    "corpo": { "finance": { "result": null,
                                            "error": { "code": "Not Found",
                                                       "description": "HTTP 404 Not Found" } } },
                    "nota": "mesma chamada com barra final na path — o 404 vira JSON com envelope finance" }
    }
  },

  "simboloInexistente": {
    "status": 404,
    "corpo": { "quoteSummary": { "result": null,
                                 "error": { "code": "Not Found",
                                            "description": "Quote not found for symbol: GARBAGEXYZ" } } }
  },

  "nenhumModuloComDado": {
    "status": 404,
    "corpo": { "quoteSummary": { "result": null,
                                 "error": { "code": "Not Found",
                                            "description": "No fundamentals data found for symbol: AAPL" } } },
    "nota": ["acontece com nome de módulo desconhecido sozinho, com módulo sem dado para a",
             "  classe do símbolo sozinho, ou quando TODOS os pedidos forem descartados"]
  },

  "post": {
    "status": 405,
    "corpo": { "finance": { "result": null,
                            "error": { "code": "Method Not Allowed",
                                       "description": "HTTP 405 Method Not Allowed" } } },
    "allow": "a resposta 405 NÃO traz header Allow"
  },

  "head": { "status": 200, "corpo": "vazio (0 bytes)",
            "credencial": "OBRIGATÓRIA como no GET — anônimo → 401 (corpo vazio); cache private, no-cache, no-store" },
  "options": { "status": 200, "allow": "HEAD,GET,OPTIONS", "anonimo": true,
               "cache": "private, no-cache, no-store",
               "corpo": "NEGOCIADO pelo Accept — ver bloco 5b (WADL integral)" },

  "borda": {
    "uaNaoNavegador": "429 Edge: Too Many Requests (Python-urllib)",
    "acceptTextPlain": "406 com envelope finance (code 'Not Acceptable')",
  }
}
```

#### WADL do OPTIONS (negociação por Accept)

```json5
{
  // ==========================================================================
  // 5b · WADL DO OPTIONS — a auto-descrição XML que o próprio servidor publica
  // ==========================================================================

  // O OPTIONS entra na rota ANONIMAMENTE (sem cookie e sem crumb) e devolve
  // Allow: HEAD,GET,OPTIONS com cache private, no-cache, no-store. O CORPO é
  // NEGOCIADO pelo header Accept:
  //
  //   Accept: application/vnd.sun.wadl+xml → 200 + WADL integral (XML)
  //   Accept: */* (ou ausente)             → 200 + o MESMO WADL integral
  //   Accept: application/json             → 200 + corpo VAZIO (0 bytes) com
  //                                          content-type application/json —
  //                                          um cliente que pede JSON nunca
  //                                          vê o WADL
  //
  // O WADL vem com content-type application/vnd.sun.wadl+xml, vary: Origin e
  // last-modified com a hora corrente do servidor (gerado por requisição).
  // O framework está declarado no próprio XML: Jersey 2.33. O <resource path>
  // ECOA o símbolo pedido (OPTIONS de /BRK-B devolve
  // path="v10/finance/quoteSummary/BRK-B").

  wadl: {
    // conteúdo VERBATIM devolvido para /v10/finance/quoteSummary/AAPL
    base: "http://finance-company-fundamentals-api-production.finance-k8s.media.yahoo.cloud:443/",
    resource: "v10/finance/quoteSummary/AAPL",
    methodId: "getQuoteSummaryV9Formatted",   // nome do handler Java no backend
    grammars: "vazio (nenhum esquema publicado)",
    resposta: "representation única application/json;charset=utf-8",
    params: [                                  // na ordem do XML
      { nome: "modules", xs: "xs:string", default: "—" },       // único SEM default
      { nome: "lang", xs: "xs:string", default: "en-US" },
      { nome: "region", xs: "xs:string", default: "US" },
      { nome: "formatted", xs: "xs:boolean", default: "true" },  // crava o default
      { nome: "earningsCorporateActionsEnabled", xs: "xs:boolean", default: "false" },
      { nome: "enablePrivateCompany", xs: "xs:boolean", default: "true" },
      { nome: "overnightPrice", xs: "xs:boolean", default: "false" },
      { nome: "dataVersion", xs: "xs:string", default: "v1" },
    ],
    foraDoContrato: ["crumb — a autenticação é filtro do framework, fora do recurso declarado",
                     "mockPrivateCompany e mockOvernightPrice (enviados pelo cliente, não declarados)",
                     "enableQSPExpandedEarnings (a injeção de módulos é do lado do cliente)"],
  },

  // O único param com enum VALIDADO no servidor — e o 400 usa a camada
  // quoteSummary (DIFERENTE do 400 de modules ausente, que usa a finance):
  dataVersionInvalido: {
    status: 400,
    corpo: { quoteSummary: { result: null,
                             error: { code: "Bad Request",
                                      description: "dataVersion must be one of v1, v2" } } },
    "verificado": "nas DUAS variantes (v10 e v11); dataVersion=v2 é aceito e não muda o corpo",
  },

  // Params só-do-servidor declarados no WADL (o cliente oficial NÃO os envia):
  novosNoContrato: {
    earningsCorporateActionsEnabled: "com/sem em calendarEvents,price — corpo idêntico para AAPL",
    overnightPrice: "declarado default false — em AAPL/price o conjunto de chaves não muda",
    enablePrivateCompany: "default TRUE do servidor — STRIPE.PVT sem dado → 404 com true, false e default",
  },
}
```

#### Efeito do locale

```json5
{
  // ==========================================================================
  // 6 · SEMÂNTICA DA LOCALIZAÇÃO (lang/region do transporte)
  // ==========================================================================

  // O par afeta os campos de TEXTO dos módulos de perfil e a formatação
  // numérica dos campos sempre-embrulhados; os nomes do price não mudam:
  "efeito": {
    "sectorDisp": "LOCALIZADO — 'Technology' → 'Tecnologia' no pt-BR",
    "industryDisp": "LOCALIZADO — 'Consumer Electronics' → 'Eletrônicos de consumo'",
    "fmtNumericos": ["LOCALIZADO em campos sempre-embrulhados — '16.76M'/'16,759,518' →",
                     "  '16,76Mi'/'16.759.518' no pt-BR (companyOfficers[].totalPay)"],
    "longBusinessSummary": ["ESVAZIADO quando não há tradução — pt-BR devolve string vazia",
                            "  (NÃO faz fallback para o texto em inglês)"],
    "price.shortName": "INVARIANTE — 'Apple Inc.' em todo locale",
    "price.longName": "INVARIANTE — idem",
    "price.currency": "INVARIANTE — 'USD'",
  },

  "regra": {
    "par": "efeito verificado com o par (lang=pt-BR, region=BR) vs (en-US, US)",
    "price": "price.shortName idêntico nas quatro combinações testadas (pt-BR/en-US × BR/US)",
    "invalido": "lang/region inválidos seguem o fallback padrão da família (conteúdo do default)"
  }
}
```

#### Notas do cliente oficial

```json5
{
  // ==========================================================================
  // 7 · COMPORTAMENTO DO CLIENTE OFICIAL (loader loadQuoteSummary)
  // ==========================================================================

  "loader": {
    "guardaDeSimbolo": ["valida o símbolo ANTES de enviar — aceita [a-zA-Z0-9^.$_+=*&:@~-];",
                        "  qualquer outro caractere (incluindo /) rejeita a chamada no cliente"],
    "cachePrimeiro": ["store 'quote' — para cada módulo pedido, o que já está em cache para o",
                      "  símbolo é usado SEM rede; só os módulos ausentes vão na query"],
    "merge": "resposta = {…módulosEmCache, …módulosDoFio} — o que veio do fio sobrescreve",
    "injecaoDeModulos": ["sob feature flags o cliente ADICIONA módulos à lista:",
                         "  enableQSPChartRangeTooltips → quoteUnadjustedPerformanceOverview ·",
                         "  enableQSPAboveTheFoldUpdates/enableQSPFullWidthChart → chartPreviousClose ·",
                         "  enableQSPEarnings/enableCorporateActions → corporateActions ·",
                         "  enableQSPExpandedEarnings → earningsGaap + earningsNonGaap",
                         "  (o upgradeDowngradeHistory da aba Analysis é composto pela página)"],
    "composicaoPelaPagina": ["o compositor da página de quote (categoria × quoteType) acrescenta à",
                         "  LISTA de módulos — argumento do loader, não chave nova de query:",
                         "  aba summary + enableQSPExpandedEarnings → upgradeDowngradeHistory",
                         "  (ou upgradeDowngradeHistoryLatest sob enableQSPLatestQuote-",
                         "  SummaryModules) · enableQSPLiveEarningsBE → earningsCallAudios ·",
                         "  flags de série → earningsTrendGaap/NonGaap + earningsHistory-",
                         "  Gaap/NonGaap · enableEarningsTranscript → earningsCallTranscripts",
                         "  (ou …Latest sob enableQSPLatestEarningsCallTranscripts) ·",
                         "  enableTopCryptoAttr (CRYPTO, summary) → attribution ·",
                         "  enableQSPBelowTheFoldUpdates (EQUITY, summary) → assetProfile"],
    "flagsDaPagina": ["a página de quote oficial carrega a família QSP no contexto:",
                      "  enableQSPExpandedEarnings, enableQSPLatestQuoteSummaryModules,",
                      "  enableQSPAnalysisGAAPToggle, enableQSPLiveEarnings,",
                      "  enableQuoteSummaryCaching, enableCorporateActions, enableOvernight,",
                      "  enablePrivateCompany, enableQSPChartRangeTooltips…"],
    "lista": "deduplicada sempre; ORDENADA quando a flag de cache de quoteSummary está acesa",
    "queryFixa": ["formatted: \"true\" sempre — o cliente nunca pede o modo cru;",
                  "  crumb: true — o transporte anexa o crumb na query (GET) e sobrescreve",
                  "  lang/region com os valores da sessão (searchParams.set)"],
    "falha404ComCache": ["em 404, se ALGUM módulo pedido estava em cache, o loader devolve o",
                         "  que tem em cache em vez de propagar o erro"],
    "cacheHttp": ["sob a flag de cache (enableQuoteSummaryCaching) o loader constrói um",
                  "  objeto headers {x-cache: '1', x-cache-ttl: '30000'} (TTL 30000 ms = 30 s,",
                  "  constante interna; sem x-cache-swr neste loader, ao contrário do",
                  "  loadQuoteType que inclui swr 6 h) e o repassa ao transporte — que os",
                  "  APAGA antes do fetch: a função de whitelist do transporte (em",
                  "  house.TAnG6qia.js) lista ['x-cache','x-cache-ttl','x-cache-swr'] e remove",
                  "  exatamente esses nomes do init de saída — os headers NUNCA chegam ao",
                  "  query1 (contrato interno do app; no sentido oposto, a resposta pode",
                  "  trazer x-cache-serve/x-cache-key-suffix, lidos pelo gravador de",
                  "  performance do cliente)"],
    "inventarioDeFuncoes": ["o arquivo do loader (hubSectors.ByGGzE3V.js no fonte",
                  "  de 23/10/2026) tem 13 funções top-level + 4 constantes de string/objecto;",
                  "  as letras dos exports do minifier SÃO FRÁGEIS (mudam a cada recompilação)",
                  "  — o inventário abaixo descreve por SIGNIFICADO, e em parênteses a letra",
                  "  observada no fonte de 23/10/2026:",
                  "  · 4 funções no caminho de fio (exportadas):",
                  "    - loadQuoteSummary (exportada como l) — entry point ÚNICO do single",
                  "      (v10) e DESPACHO do lote (v11): ao receber array de símbolos chama",
                  "      a função batch interna H — despacho é inline, não uma função",
                  "      exportada separada (auditorias anteriores citavam 'R()' que NÃO",
                  "      existe no fonte atual como função — era confusão com a constante",
                  "      R importada de loadModularBlockStream);",
                  "    - dataVersion generator (exportada como g) — gatilho ÚNICO",
                  "      enableMorningstarDataUpgrade (sem useTemplatesV3 — flag inexistente",
                  "      confirmada: 0 hits no fonte);",
                  "    - enableMorningstarDataUpgrade check (exportada como i) — alimenta a",
                  "      g() e a k();",
                  "    - status Morningstar (exportada como k, local N) — 'launched' quando",
                  "      enableMorningstarFinancialsLaunch também ON, 'preview' se só",
                  "      enableMorningstarDataUpgrade ON, null caso contrário.",
                  "  · 2 funções internas (não exportadas, só usadas no arquivo do loader):",
                  "    - dedupe/sort (local _) — Array.from(new Set(e)).sort() só quando",
                  "      enableQuoteSummaryCaching ON; caso contrário só dedupe implícito",
                  "      via Set; (auditorias anteriores citavam 'Q()' como dedupe/sort —",
                  "      INCORRETO: Q no fonte atual é a regex de validação de símbolo,",
                  "      importada de quoteUtil.LKSUtO0H.js e usada em symbol.match(Q));",
                  "    - dispatcher batch (local H) — monta a chamada v11 a partir do",
                  "      array de símbolos recebido por loadQuoteSummary.",
                  "  · helpers consumidos por OUTROS módulos (exportados mas NÃO viram query",
                  "    aqui): useUpgradedData (exportada como f, local B) ·",
                  "    enableFinancialsDTV2 check (exportada como a, local ae) · bucket check",
                  "    (exportada como h, local re) · função de pie chart de setores (b, c,",
                  "    d, e, ie, ce — para a view do Hub Sectors, nada a ver com fio).",
                  "    NOTA: useTemplatesV3 NÃO existe mais no fonte atual (substituído",
                  "    pelo par enableMorningstarDataUpgrade + enableMorningstarFinancials-",
                  "    Launch + enableFinancialsDTV2).",
                  "  · os fluxos de screener (/v1/finance/screener/predefined/saved, scrId",
                  "    most_actives) e de calendar-events (/ws/screeners/v1/finance/calendar-",
                  "    events) vivem em OUTROS módulos do cliente (initializeDock, finChart-",
                  "    RightRail, isResolvedEmpty — URLs cravadas neles), não no loader.",
                  "  · constantes do arquivo (letras FRÁGEIS, descritas por significado):",
                  "    - 'EQIPQ' (exportada como D, local ee) — dataIds de dividendTimeSeries",
                  "      em outro módulo do cliente;",
                  "    - '2026-11-09' (exportada como j, local te) — rótulo formatDateUTC",
                  "      no toggle de preview de financials (era M no snapshot de 19/10 —",
                  "      a letra mudou com o minifier no fonte atual);",
                  "    - 'yfqsp-ms-fin-optin' (exportada como M, local V) — NOME de bucket",
                  "      para o feature-gate de opt-in dos financials Morningstar (novo no",
                  "      fonte atual, era inexistente no snapshot de 19/10);",
                  "    - 3e4 = 30000 (local G, não exportada) — TTL em ms do header",
                  "      x-cache-ttl que NÃO chega ao fio (vide cacheHttp acima);",
                  "    - objeto headers {x-cache:1, x-cache-ttl:'30000'} (local M, não",
                  "      exportada) — passado ao transporte sob enableQuoteSummaryCaching e",
                  "      apagado pela whitelist antes do fetch (era 'T' no snapshot de 19/10",
                  "      — no fonte atual a letra T não é exportada por este arquivo)."],
  },

  // O MESMO loader serve as duas variantes: recebendo um ARRAY de símbolos,
  // ele despacha a variante batch (v11) — segunda seção deste arquivo:
  "despachoBatch": "array de símbolos no argumento → GET /v11/finance/quoteSummary/?symbols=…",
  "varianteGatewayWs": ["TRÊS chamadores usam o caminho gateway /ws/company-fundamentals/v11/",
                        "  finance/quoteSummary (sem barra final; aceita também com) em vez",
                        "  do núcleo: (1) WatchlistInsights (loadQuotePerformanceOverview) —",
                        "  modules=quotePerformanceOverview em lotes de 15; (2) Watchlist-",
                        "  RecentNews (loadEarningsCallTranscripts) — modules=earningsCall-",
                        "  Transcripts, janela de 100 símbolos fatiada em lotes de 15;",
                        "  (3) loadComparison — a página /compare do Research Hub: 6 módulos",
                        "  da constante un (price, assetProfile, getCeo, quoteDetail,",
                        "  morningstarFinancials, quoteTrailingReturns), lote de até 4",
                        "  (slice(0,4)), dataVersion via g() e TRÊS chaves próprias:",
                        "  quoteTypesFilter=equity, currency (moeda do cookie de conversão)",
                        "  e modulesFields (literal do código, com espaço após a vírgula:",
                        "  'totalRevenue,psRatio,inventories, ytdChangePercent'). Crumb igual",
                        "  em todos. Cravado no fio: mesmo envelope de eco, 401 'Invalid",
                        "  Crumb' sem crumb, descarte silencioso de módulo desconhecido,",
                        "  mesmo teto de 15 símbolos (16 → 400 'Max symbols requested",
                        "  exceeded the allowed limit') — e a barra final TAMBÉM é aceita",
                        "  neste caminho (ao contrário do núcleo v11, que a exige)"]
}
```

---

### GET /v11/finance/quoteSummary/

A variante **batch** do quoteSummary: devolve, em uma única resposta, os módulos de fundamentals
de **até 15 símbolos**. O símbolo NÃO participa do path — vai na query `symbols` (CSV) — e cada
resultado é um elemento do array `quoteSummary.result`. É o mesmo loader do cliente oficial
(`loadQuoteSummary`) despachando o lote: quando recebe um array de símbolos, ele monta esta
chamada (perfLabel `loadQuoteSummaryBatch`) em vez da variante single.

Dois detalhes de contrato que não existem no v10: a **barra final do caminho faz parte da
chamada** (sem ela o endpoint responde `502` com página HTML, não JSON) e o envelope de sucesso
tem **TRÊS chaves** — `symbols` (ECO dos símbolos resolvidos), `result` e `error`. O eco é o que
ancora o mapeamento símbolo → elemento: `symbols[i]` ↔ `result[i]`, em paridade 1:1. Os
elementos NÃO carregam a identidade do símbolo, e o eco contém SOMENTE os símbolos que
existem no servidor — um símbolo válido cuja lista de módulos não produz NENHUM dado não é
filtrado: volta no eco com um elemento `errorResult` na paridade (lote `XOM,BTC-USD,SPY` com
`modules=esgScores` → eco `['XOM','BTC-USD','SPY']` e 3 × `{errorResult: {code: 'Not Found',
description: 'No fundamentals data found for any of the QuoteSummaryTypes=[] for symbol=…'}}`
— a descrição expõe a lista resolvida VAZIA). Com um lote `AAPL,GARBAGEXYZ` o eco volta
`['AAPL']` com 1 elemento no `result`, e um lote só de inexistentes responde `200` com
`symbols: []` e `result: []`.

| | |
| :--- | :--- |
| Método | `GET` — `HEAD` se comporta como o GET sem corpo (anônimo → `401`; com credencial e sem `symbols` → `400`; com query completa → 200, corpo vazio) e `OPTIONS` é anônimo (200, `Allow: HEAD,GET,OPTIONS`; corpo negociado pelo `Accept` — WADL próprio do lote, bloco 9); `POST` → `405` com envelope de erro e SEM header `Allow` |
| Hosts | `query1` · `query2` (espelhos idênticos; query1 é o padrão do cliente) |
| Caminho | `/v11/finance/quoteSummary/` — **com barra final** (o cliente oficial sempre a envia; sem a barra → `502` HTML; com segmento extra após a barra (`/v11/finance/quoteSummary/AAPL`) → `404` JSON com envelope `finance` — a rota do lote não aceita símbolo no path) |
| Autenticação | **Obrigatória e dupla** — cookie de sessão (`A3`) + crumb, como no v10 (query ou header `x-crumb`); anônimo → `401 Unauthorized` (`Invalid Crumb`) |
| User-Agent | Agente de navegador obrigatório — `Python-urllib` recebe `429 Edge: Too Many Requests` |
| Accept | Ausente ou `application/json` → `200`; `text/plain` → `406` com envelope de erro |
| Cache de borda | `public, max-age=1, stale-while-revalidate=9` |
| Content-Type | `application/json;charset=utf-8` |

```json5
{
  // ==========================================================================
  // 8 · PARÂMETROS DA REQUISIÇÃO (v11)
  // ==========================================================================

  // Linha de requisição canônica (a que o loader do cliente envia no lote):
  //
  //   curl -s \
  //     -H "User-Agent: Mozilla/5.0 …" -b "A3=…" \
  //     "https://query1.finance.yahoo.com/v11/finance/quoteSummary/?formatted=true&modules=price,financialData&symbols=AAPL,MSFT&lang=en-US&region=US&crumb=…"

  request: {
    method: "GET",
    path: "/v11/finance/quoteSummary/",   // barra final faz parte da chamada oficial
                                          //   — sem ela → 502 (página HTML)
    params: {
      symbols: "AAPL,MSFT",        // OBRIGATÓRIO · CSV de até 15 símbolos (bloco 9)
                                   //   · ausente → 400 "Missing required query parameter=symbols"
                                   //     (camada finance)
                                   //   · case-insensitive no servidor (aapl,msft resolve);
                                   //     o cliente oficial envia TUDO em caixa alta e o ECO
                                   //     volta em caixa alta
                                   //   · símbolo inexistente/sem dado → OMITIDO do array
                                   //     silenciosamente — some do ECO e do result (o
                                   //     paridade 1:1 do eco nunca quebra)
                                   //   · aceita mistura de classes na mesma chamada
                                   //     (equity, cripto, índice, câmbio, futuro)
      modules: "price,…",          // OBRIGATÓRIO · o mesmo vocabulário do v10 (bloco 2) —
                                   //   mesmas regras de case/dedupe/descarte; módulo
                                   //   desconhecido ou sem dado é descartado de TODOS os
                                   //   elementos; ausente → 400 (camada finance)
      formatted: "true",           // o cliente envia sempre "true" — mesmo default do
                                   //   servidor do v10 ({raw, fmt} quando omitido)
      lang: "en-US",               // injetados pelo transporte com os valores da SESSÃO,
      region: "US",                //   como no v10
      dataVersion: "v2",           // aceito no lote (Morningstar) — o cliente o envia com a
                                   //   flag enableMorningstarDataUpgrade (gatilho ÚNICO no
                                   //   código atual; ver nota do v10)

      // As demais flags do v10 são ACEITAS no lote sem erro (enablePrivateCompany,
      // mockPrivateCompany, mockOvernightPrice, overnightPrice — cravado no fio,
      // payload inalterado); o cliente oficial NÃO as envia no batch — só na
      // variante single. enableQSPExpandedEarnings também é aceita, mas NÃO injeta
      // earningsGaap/NonGaap no lote — a injeção de módulos do cliente só acontece
      // na variante single (cravado: lote com a flag devolve só o módulo pedido).

      // Chaves do comparador (o 3º chamador ws, loadComparison, as envia neste
      // caminho — e o núcleo v11 também as aceita, cravado no fio):
      quoteTypesFilter: "equity",  // FILTRO REAL por quoteType no lote: elementos cuja
                                   //   classe NÃO casa são EXCLUÍDOS do eco e do result
                                   //   (SPY com 'equity' → eco []; AAPL,SPY com 'equity'
                                   //   → eco ['AAPL'] com paridade preservada) — o valor
                                   //   é GENÉRICO (SPY com 'etf' fica, AAPL com 'etf'
                                   //   some); o cliente só envia 'equity';
                                   //   NO v10 SINGLE a chave é aceita e IGNORADA
      currency: "USD",             // aceita SEM conversão no fio (price continua USD) —
                                   //   a conversão é feita no cliente com a moeda do
                                   //   cookie (cravado: EUR devolve USD $347.36)
      modulesFields: "totalRevenue,psRatio,inventories, ytdChangePercent",
                                   // aceita sem efeito observável (cravado com/sem sobre
                                   //   os módulos do comparador e sobre price/quoteDetail);
                                   //   literal do código, com espaço após a vírgula

      // Chaves desconhecidas na query são aceitas e ignoradas silenciosamente.
    },
  },
}
```

Semântica e casos de borda por parâmetro (v11):

| Parâmetro | Tipo | Obrigatório | Padrão | Comportamento e Casos de Borda |
| :--- | :--- | :---: | :--- | :--- |
| `symbols` | CSV | Sim | — | Até **15** símbolos — 16 ou mais → `400` `"Max symbols requested exceeded the allowed limit"` (camada quoteSummary). 1 símbolo é aceito (eco de 1). Case-insensitive (eco volta em caixa alta); inexistente → omitido do eco E do result. Ordem dos elementos = ordem pedida. |
| `modules` | CSV | Sim | — | Mesmo vocabulário e regras do v10 (bloco 2). Ausente → `400` (camada finance). |
| `formatted` | bool | Não | `true` (servidor) | Mesmo comportamento do v10 (bloco 5). |
| `lang` / `region` | string | Não | sessão (`en-US`/`US`) | Injetados pelo transporte, como no v10. |
| `dataVersion` | string | Não | `v1` (servidor) | `v2` (Morningstar) aceito no lote — mesmo gatilho único do v10 (`enableMorningstarDataUpgrade`); enum validado: fora de `v1, v2` → `400` `"dataVersion must be one of v1, v2"` na camada `quoteSummary`. |
| `enablePrivateCompany` · `overnightPrice` · `mockPrivateCompany` · `mockOvernightPrice` | flag | Não | — | Aceitas no lote **sem erro** (cravado no fio, payload inalterado) — mas o cliente oficial NÃO as envia no batch, só na variante single. |
| `enableQSPExpandedEarnings` | flag | Não | — | Aceita no lote, porém NÃO injeta `earningsGaap`/`earningsNonGaap` (a injeção de módulos do cliente só acontece na variante single — cravado no fio: lote com a flag devolve só o módulo pedido). |
| `quoteTypesFilter` | string | Não | — | **Filtro REAL por quoteType** (cravado): elementos cuja classe não casa são EXCLUÍDOS do eco e do result com paridade preservada (`AAPL,SPY` + `equity` → eco `["AAPL"]`; valor genérico — `etf` mantém SPY e exclui AAPL). O cliente oficial só envia `equity` (loadComparison). **No v10 single é aceita e IGNORADA.** |
| `currency` | string | Não | `""` (servidor) | Aceita SEM conversão no fio (AAPL + `currency=EUR` → price continua `USD`/`$`/347.36) — a conversão é feita no cliente; declarado no WADL do lote com default vazio. |
| `modulesFields` | CSV | Não | — | Aceita sem efeito observável (cravado com/sem nos módulos do comparador e em price/quoteDetail). Literal do código traz um espaço após a vírgula (`inventories, ytdChangePercent`) e o servidor aceita mesmo assim. |

> **Convenções (v11):**
> - **Mapeamento por ECO**: `quoteSummary.symbols[i]` ↔ `quoteSummary.result[i]` em paridade
>   1:1. O eco contém SOMENTE os símbolos resolvidos (em caixa alta) — um lote
>   `AAPL,GARBAGEXYZ` devolve `symbols: ["AAPL"]` com 1 elemento, e um lote só de
>   inexistentes devolve `200` com `symbols: []` e `result: []` (sem erro). Consumidores
>   devem parear eco↔elemento (zip), nunca assumir 1 elemento por símbolo pedido.
> - A ordem dos elementos segue a ordem de `symbols` pedida (pedir `MSFT,AAPL` devolve
>   Microsoft na posição 0 e Apple na posição 1).
> - Chaves desconhecidas na query string são ignoradas silenciosamente.

#### Resposta e erros (v11)

```json5
{
  // ==========================================================================
  // 9 · RESPOSTA E ERROS (v11)
  // ==========================================================================

  "sucesso": {
    "status": 200,
    "corpo": ["quoteSummary — envelope com TRÊS chaves: symbols (ECO), result, error",
              "  · symbols: array com os símbolos RESOLVIDOS, em caixa alta, na ordem pedida",
              "  · result: array em PARIDADE 1:1 com o eco; cada elemento é um objeto cujas",
              "    chaves são os módulos materializados (ordem do servidor do v10, bloco 2)",
              "  · os elementos NÃO identificam o símbolo — o pareamento é symbols[i]↔result[i]"],
    "elementoSemDado": ["símbolo válido cujos módulos não produzem dado → elemento",
              "  {errorResult: {code 'Not Found', description 'No fundamentals data found",
              "  for any of the QuoteSummaryTypes=[] for symbol=X'}} — a descrição expõe a",
              "  lista resolvida vazia; eco e paridade preservados (esgScores em lote:",
              "  15 EQUITY ESG-heavy + 10 outras classes → errorResult, com e sem",
              "  dataVersion=v2)"],
    "loteVazioDeDado": ["só inexistentes → 200 com symbols [] e result [] (error nulo)"],
  },

  "loteMaximo": {
    "limite": 15,                  // observado: 15 símbolos → 200 com 15 elementos
    "status": 400,                 // 16 símbolos → 400
    "corpo": { "quoteSummary": { "result": null,
                                 "error": { "code": "Bad Request",
                                            "description": "Max symbols requested exceeded the allowed limit" } } },
    "nota": "erro de limite vem na camada quoteSummary — diferente dos erros de parâmetro ausente, que vêm na camada finance"
  },

  "semSymbols": {
    "status": 400,
    "corpo": { "finance": { "result": null,
                            "error": { "code": "Bad Request",
                                       "description": "Missing required query parameter=symbols" } } }
  },

  "semModules": {
    "status": 400,
    "corpo": { "finance": { "result": null,
                            "error": { "code": "Bad Request",
                                       "description": "Missing required query parameter=modules" } } }
  },

  "semCrumbOuCookie": {
    "status": 401,
    "corpo": { "finance": { "result": null,
                            "error": { "code": "Unauthorized", "description": "Invalid Crumb" } } }
  },

  "post": {
    "status": 405,
    "corpo": { "finance": { "result": null,
                            "error": { "code": "Method Not Allowed",
                                       "description": "HTTP 405 Method Not Allowed" } } },
    "allow": "a resposta 405 NÃO traz header Allow"
  },

  "head": { "status": 200, "corpo": "vazio (0 bytes)",
            "matriz": ["anônimo → 401 (corpo vazio)",
                       "com credencial e SEM symbols → 400 (corpo vazio — o mesmo 400 do GET)",
                       "com credencial + query completa → 200 (cache private, no-cache, no-store)"] },
  "options": { "status": 200, "allow": "HEAD,GET,OPTIONS", "anonimo": true,
               "cache": "private, no-cache, no-store",
               "corpo": ["NEGOCIADO pelo Accept — com */* ou application/vnd.sun.wadl+xml devolve o",
                         "WADL próprio do lote (framework Jersey 2.33; resource v11/finance/quoteSummary/",
                         "com barra; method id getQuoteSummary; 8 params: symbols, modules, lang, region,",
                         "formatted=true, quoteTypesFilter, currency, dataVersion=v1); com application/json",
                         "→ corpo vazio (0 bytes), content-type application/json"] },

  "borda": {
    "semBarraFinal": "GET /v11/finance/quoteSummary (sem a barra) → 502 com página HTML (não JSON)",
    "segmentoExtra": "GET /v11/finance/quoteSummary/AAPL (segmento após a barra) → 404 JSON com envelope finance",
    "uaNaoNavegador": "429 Edge: Too Many Requests (Python-urllib)",
    "acceptTextPlain": "406 com envelope finance (code 'Not Acceptable')",
    "cache": "public, max-age=1, stale-while-revalidate=9"
  }
}
```

#### Notas do cliente oficial (v11)

```json5
{
  // ==========================================================================
  // 10 · COMPORTAMENTO DO CLIENTE OFICIAL (loader loadQuoteSummaryBatch)
  // ==========================================================================

  "loader": {
    "despacho": ["o MESMO loadQuoteSummary do v10: recebendo um ARRAY de símbolos, ele",
                 "  monta esta chamada com perfLabel loadQuoteSummaryBatch"],
    "gatewayWs": ["a mesma chamada batch existe no caminho /ws/company-fundamentals/v11/",
                  "  finance/quoteSummary — SEM barra final (aceita também com); mesma",
                  "  autenticação, mesmo envelope de eco e mesmo descarte silencioso;",
                  "  três chamadores: os dois componentes de watchlist (lotes de 15,",
                  "  modules=quotePerformanceOverview ou earningsCallTranscripts) e o",
                  "  loadComparison da página /compare — detalhes e chaves próprias no",
                  "  bloco 7 (varianteGatewayWs)"],
    "validacoesAntesDeEnviar": [
      "lote vazio → erro no cliente ('Need symbols to load quote summary batch')",
      "símbolo fora do charset permitido ou vazio → erro no cliente",
      "  ('Invalid symbol in quote summary batch request')",
    ],
    "symbols": ["juntados por vírgula e CONVERTIDOS para caixa alta antes de enviar;",
                "  no consumo, o cliente pareia o ECO com o result (zip symbols↔result)"],
    "modules": "deduplicados; ordenados quando a flag de cache de quoteSummary está acesa",
    "queryFixa": ["formatted: \"true\" sempre; crumb: true (query, no GET);",
                  "  lang/region da sessão entram pelo transporte"],
    "parse": ["exige quoteSummary.result como Array — qualquer outra forma é tratada como",
              "  resposta vazia (erro 'Empty response') e propagada ao chamador"],
    "cacheHttp": ["sob a flag de cache o loader passa headers {x-cache: 1, x-cache-ttl: 30000}",
                  "  ao transporte — que os REMOVE antes do fetch (whitelist do transporte",
                  "  em house.TAnG6qia.js: ['x-cache','x-cache-ttl','x-cache-swr']); NUNCA",
                  "  chegam ao query1 — detalhe no bloco 7 (cacheHttp)"],
  }
}
```


