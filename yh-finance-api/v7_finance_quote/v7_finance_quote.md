# `GET /v7/finance/quote`

> **Data de atualização:** 2026-10-20 · constantes deste endpoint validadas ao vivo contra `query1.finance.yahoo.com` (2026-10-18, sessão autenticada A3+Crumb — classes de borda ALTSYMBOL/NONE, campos sob pedido e comportamento de logos/lang verificados na mesma data · revalidação completa em 2026-10-19 pós-mercado: 33/33 na bateria de auth/pacotes + diagnósticos de lote/lang/logos).

---


Motor de cotações universal do Yahoo Finance: devolve **qualquer conjunto arbitrário de símbolos em uma única chamada**, misturando livremente as nove classes com preço do banco global — `EQUITY`, `ETF`, `MUTUALFUND`, `MONEYMARKET`, `CRYPTOCURRENCY`, `CURRENCY`, `FUTURE`, `INDEX` e `OPTION` — mais duas classes de borda observadas ao vivo: `ALTSYMBOL` (alias de contrato sem nome próprio — ex.: `CT=F`, que aponta para o algodão `CTX26.NYM`) e `NONE` (esqueleto de símbolos deslistados/adquiridos — ex.: `TWTR`, `ATVI`), ambas detalhadas no bloco 3. A classe do vocabulário do cliente `PRIVATE_COMPANY` não resolveu em nenhum teste (nota no bloco 3). É o inverso operacional do [marketSummary](v6_finance_quote_marketSummary.md): aqui não há curadoria do servidor — **quem escolhe os símbolos é o chamador**. Alimenta o seed do streamer de tempo real (seção 8), o portfólio, o comparador multi-símbolo, as âncoras do painel de mercados e a página de cotações. A projeção da resposta é **polimórfica por `quoteType`**: cada item recebe o pacote de campos da sua classe, com tolerância silenciosa — campos pedidos que não existirem para a classe são omitidos, nunca rejeitados. Diferença crítica para o marketSummary: a autenticação **é obrigatória** — sem o par Cookie (`A3`) + `crumb`, a resposta é `401 Unauthorized`.

| | |
| :--- | :--- |
| Método | `GET` — aceita também `HEAD` e `OPTIONS` (o `OPTIONS` responde `200` com `Allow: HEAD,GET,OPTIONS`); demais métodos → `405` |
| Hosts | `query1` · `query2` (`.finance.yahoo.com` — espelhos idênticos; o transporte sorteia entre os dois, `Math.random` — constantes do [marketSummary](v6_finance_quote_marketSummary.md); `iquery` é o host fixo de chamadas selecionadas e `iquery-stage` o de ambientes internos) |
| Caminho | `/v7/finance/quote` |
| Autenticação | **Obrigatória** — Cookie `A3` + `crumb` (vetor query string **ou** header `x-crumb`); falta de qualquer um dos dois → `401` |
| User-Agent | Agente de navegador obrigatório — `curl`/`Python-urllib` e afins recebem `429 Edge: Too Many Requests` |
| Cache de borda | `public, max-age=1, stale-while-revalidate=9` — janela total de ~10 s por URL |
| Payload típico | 4,3 KB (1 símbolo, pacote completo formatted=true) · ~28–30 KB (lote de 30, projetado) · ~93–128 KB (lote de 30, pacote completo, conforme as classes do lote) |

## Autenticação e User-Agent

O handshake é o mesmo pipeline comum às APIs de dados, mas aqui **não é opcional**: cookie sem crumb → `401`; crumb sem cookie → `401`; ambos errados ou ausentes → `401`. O crumb aceita dois vetores — anexado à query string (padrão da maioria dos chamadores) ou enviado como header `x-crumb` (vetor do gráfico); qualquer um dos dois fecha a sessão, desde que acompanhado do cookie.

```bash
# 1. Capturar o Cookie A3 de sessão
curl -s -c cookies.txt "https://fc.yahoo.com" > /dev/null

# 2. Emitir o token Crumb casado com o cookie (OBRIGATÓRIO neste endpoint)
CRUMB=$(curl -s -b cookies.txt "https://query1.finance.yahoo.com/v1/test/getcrumb")

# 3. Consultar — crumb na query string
curl -s -b cookies.txt \
  -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/138.0.0.0" \
  "https://query1.finance.yahoo.com/v7/finance/quote?symbols=AAPL,PETR4.SA,BTC-USD,^GSPC&formatted=false&crumb=${CRUMB}"

# Vetor alternativo — crumb no header (mesma resposta):
curl -s -b cookies.txt \
  -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/138.0.0.0" \
  -H "x-crumb: ${CRUMB}" \
  "https://query1.finance.yahoo.com/v7/finance/quote?symbols=AAPL&formatted=false"
```

## Estrutura do endpoint — parâmetros, campos comuns e tipos de ativo

Estrutura declarativa pura (JSON5 comentado), sem nenhuma função ou lógica executável de JavaScript: parâmetros da requisição, campos comuns a todos os ativos e cada grupo por id, com a explicação de cada campo ao lado.

```json5
{
  // ==========================================================================
  // 1 · PARÂMETROS DA REQUISIÇÃO
  // ==========================================================================
  request: {
    method: "GET",
    path: "/v7/finance/quote",
    params: {
      symbols: "AAPL,BTC-USD",        // OBRIGATÓRIO. Lista CSV de símbolos de QUALQUER classe,
                                        //   misturadas livremente na mesma chamada. O servidor
                                        //   normaliza para caixa alta (aapl → AAPL), preserva a
                                        //   ordem relativa dos símbolos distintos, REPLICA
                                        //   duplicatas (uma entrada no result por ocorrência,
                                        //   agrupadas — o cliente deduplica antes de enviar),
                                        //   COM EXCEÇÃO de CURRENCY: pares de moeda
                                        //   deduplicam para uma única entrada (EURUSD=X×7 →
                                        //   1 item; BTC-USD×2/GC=F×2 replicam — out/2026)
                                        //   e OMITE silenciosamente os inexistentes (sem erro,
                                        //   sem item fantasma — distinção de borda: deslistado
                                        //   conhecido → esqueleto quoteType NONE; alias de
                                        //   contrato → ALTSYMBOL; desconhecido total → omitido;
                                        //   ticker reciclado resolve o ativo NOVO — FB hoje é
                                        //   um ETF da ProShares; bloco 3). Ausente ou vazio → 400 "Missing
                                        //   required query parameter=symbols" (checado DEPOIS da
                                        //   autenticação: sem sessão, o 401 vem primeiro)
      fields: "shortName,…",          // Projeção da resposta (vocabulário na seção 5):
                                        //   AUSENTE ou VAZIO ("fields=") → pacote completo
                                        //     pré-definido da classe do ativo (33–90 campos/item,
                                        //     contagem por tipo na seção 7)
                                        //   LISTA CSV → núcleo de 24 campos (seção 2) + união dos
                                        //     pedidos que existirem no vocabulário da classe +
                                        //     satélites (marketCap puxa sharesOutstanding,
                                        //     impliedSharesOutstanding e currency)
                                        //   Desconhecidos ("bananaField") → 200, ignorados
                                        //   Incompatíveis com a classe (trailingPE em moeda) →
                                        //     omitidos no item, sem erro para o restante do lote
      formatted: "false",             // "true" = valores de mercado como { raw, fmt } (grandes
                                        //   somam "longFmt") · "false" = primitivos crus ·
                                        //   OMITIDO = "false" (primitivos) — ATENÇÃO: default
                                        //   INVERSO ao do [marketSummary](v6_finance_quote_marketSummary.md) (onde omitido
                                        //   equivale a true) · metadados nunca são embrulhados
      lang: "en-US",                  // Locale. Ecoa em "language" e localiza typeDisp (ja-JP →
                                        //   '資本'; pt-BR → 'Ação') E as strings fmt/longFmt dos
                                        //   valores formatados (en-US '59.853M' / '59,852,690' /
                                        //   '343.46' ↔ pt-BR '59.853Mi' / '59.852.690' /
                                        //   '343,46') — NÃO localiza shortName/longName
                                        //   (diferente do marketSummary) · default "en-US"
      region: "US",                   // Ecoa em "region" · default "US" · não muda a seleção
      crumb: "…",                     // Assinatura de sessão — vetor padrão (alternativa: header
                                        //   x-crumb). Obrigatório junto com o cookie A3
      corsDomain: "finance.yahoo.com",// Enviado pelo cliente (host da página) — aceito e INERTE
                                        //   (não ecoa, não muda nada)
      // Flags condicionais do cliente oficial (efeitos observados — seção 8):
      topPickThisMonth: "true",       // injeta stockPick{ID,Provider,Rating,URL,CTA} (EQUITY)
      checkUnusualOptionsActivity: "true", // injeta hasUnusualOptionsActivity (options); o bloco stockPick* materializa em EQUITY
      useLogoDevLogo: "true",         // com logoUrl na projeção: acrescenta logoUrlDarkMode e
                                        //   troca o provedor do logo — em vez de s.yimg.com/lb/
                                        //   brands/150x150_*.png, serve pelo proxy logo.dev:
                                        //   s.yimg.com/lo/mysterio/api/<hash>/finance/
                                        //   resizefill_w150_h150/<logo original> (hash distinto
                                        //   para o modo escuro)
      imgLabels: "logoUrl",           // rótulo do recurso de imagem — SEM efeito nos NOMES dos
                                        //   campos (logoUrl e companyLogoUrl voltam juntos com
                                        //   qualquer valor); o logo só materializa quando
                                        //   logoUrl/companyLogoUrl está na projeção fields
      imgHeights: "50",               // altura solicitada — aceito sem erro, porém INERTE nas
                                        //   validações de out/2026: a URL do logo não muda de
                                        //   dimensão (brand logos sempre 150x150_*.png; proxy
                                        //   mysterio sempre resizefill_w150_h150 — com 50, 100
                                        //   ou sem o trio img*; default 50 do cliente oficial)
      imgWidths: "50",                // largura solicitada — idem imgHeights (inerte na URL)
      enablePrivateCompany: "true",   // flags de empresa privada — presentes no código do cliente,
      mockPrivateCompany: "true",     //   porém NENHUM símbolo .PVT resolveu ao vivo (bloco 3);
      overnightPrice: "true",         //   overnightPrice/mockOvernightPrice sem efeito observado
      mockOvernightPrice: "true",     //   na sessão de validação (campos overnight* só com dados)
      // Ignorados silenciosamente: chaves desconhecidas (ex.: "appendUnderlyingQuote" — presente
      //   em versões antigas de documentação, sem efeito e sem referência neste bundle)
    },
  },

  // ==========================================================================
  // 2 · CAMPOS COMUNS A TODOS OS ATIVOS (as classes com preço + ALTSYMBOL)
  // ==========================================================================
  // Núcleo universal do pacote default (fields ausente) — presente em TODOS os tipos com
  // preço observados (interseção das 9 classes cotáveis, 28 campos; ALTSYMBOL segue o mesmo
  // núcleo MENOS shortName — e NONE devolve só um esqueleto, bloco 3). Com fields= presente,
  // o núcleo encolhe para 24 (saem shortName, currency e corporateActions; entram condicionais
  // por tipo: firstTradeDateMilliseconds — exceto MONEYMARKET — e priceHint — exceto
  // CRYPTOCURRENCY/FUTURE/ALTSYMBOL); variações por tipo no modo lista: FUTURE soma
  // contractSymbol e headSymbolAsString; CURRENCY mantém currency, regularMarketChangePercent
  // e fulldayChangePercent (mesmo padrão do [marketSummary](v6_finance_quote_marketSummary.md));
  // ALTSYMBOL perde também quoteSourceName. O restante da projeção é por adição (seção 1).
  "commonFields": [
    "symbol",                     // Ticker oficial normalizado em caixa alta (ex: 'AAPL', '^GSPC')
    "shortName",                  // Nome curto de exibição — NÃO localizado por lang; ausente
                                  //   em ALTSYMBOL e NONE (alias e deslistado não têm nome)
    "quoteType",                  // Classe do ativo ('EQUITY', 'ETF', 'MUTUALFUND', 'MONEYMARKET',
                                  //   'CRYPTOCURRENCY', 'CURRENCY', 'FUTURE', 'INDEX', 'OPTION',
                                  //   'ALTSYMBOL', 'NONE' — as duas de borda, bloco 3)
    "typeDisp",                   // Classe formatada e localizada por lang ('Equity', '資本', '指数')
    "market",                     // Identificador interno ('us_market', 'ccc_market', 'ccy_market',
                                  //   'us24_market', '<país>_market')
    "region",                     // Eco do region do pedido ('US')
    "language",                   // Eco do lang do pedido ('en-US')
    "currency",                   // Moeda da cotação (no pacote default de todos; no núcleo com
                                  //   fields=, só em CURRENCY ou como satélite de marketCap);
                                  //   pseudo-moeda 'USX' em contrato cotado em centavos (CT=F)
    "exchange",                   // Sigla da bolsa ou provedor ('NMS', 'CCC', 'CCY', 'SNP', 'OPR')
    "fullExchangeName",           // Nome por extenso da bolsa ('NasdaqGS', 'CCC', 'OPR')
    "marketState",                // Fase da sessão ('PREPRE', 'PRE', 'REGULAR', 'POST', 'POSTPOST',
                                  //   'CLOSED')
    "regularMarketPrice",         // Último preço da sessão regular (ou do último negócio)
    "regularMarketTime",          // Timestamp Epoch (segundos) do último negócio
    "fulldayPrice",               // Preço consolidado do dia inteiro (regular + estendido)
    "exchangeTimezoneName",       // Fuso horário IANA da bolsa ('America/New_York', 'UTC')
    "exchangeTimezoneShortName",  // Sigla do fuso ('EDT', 'UTC', 'BST')
    "gmtOffSetMilliseconds",      // Deslocamento em ms em relação ao UTC/GMT
    "priceHint",                  // Casas decimais sugeridas (2, 4)
    "sourceInterval",             // Intervalo da fonte em minutos (10, 15, 20)
    "exchangeDataDelayedBy",      // Atraso da cotação em minutos (0 = tempo real)
    "quoteSourceName",            // Fonte da cotação ('Delayed Quote', 'Free Realtime Quote',
                                  //   'CoinMarketCap')
    "customPriceAlertConfidence", // Confiança para alertas de preço ('LOW', 'NONE')
    "tradeable",                  // Booleano: executável via parceiros de corretagem
    "triggerable",                // Booleano: aceita alertas de preço/notificações
    "cryptoTradeable",            // Booleano: criptoativo negociável na plataforma
    "hasPrePostMarketData",       // Booleano: pré/pós-mercado disponível para o ativo
    "esgPopulated",               // Booleano: dados ESG populados — SÓ com formatted=false
                                  //   (AAPL: 90 campos em false vs 89 em true; par simétrico ao
                                  //   headSymbol/esgPopulated do [marketSummary](v6_finance_quote_marketSummary.md))
    "corporateActions",           // Ação corporativa pendente (ex: dividend/split agendado)
  ],

  // ==========================================================================
  // 3 · ATIVOS E SEUS CAMPOS ESPECÍFICOS (POR ID) — sobre o núcleo da seção 2
  // ==========================================================================
  "assetTypes": [
    {
      "id": "EQUITY",
      "tickerFormat": "[A-Z]{1,5} (ex: AAPL, MSFT, PETR4.SA, GOOGL)",
      "defaultPackageSize": 90,       // pacote sem fields= (formatted=false; 89 em true)
      "fields": [
        // — Sessão regular —
        "regularMarketOpen",          // abertura do dia
        "regularMarketDayHigh",       // máxima do dia
        "regularMarketDayLow",        // mínima do dia
        "regularMarketDayRange",      // faixa do dia ('mínima - máxima')
        "regularMarketPreviousClose", // fechamento anterior
        "regularMarketChange",        // variação absoluta do dia
        "regularMarketChangePercent", // variação percentual do dia
        "regularMarketVolume",        // volume do dia
        // — Médias móveis —
        "fiftyDayAverage",            // média móvel de 50 dias
        "fiftyDayAverageChange",      // distância absoluta até a MM50
        "fiftyDayAverageChangePercent", // distância percentual até a MM50
        "twoHundredDayAverage",       // média móvel de 200 dias
        "twoHundredDayAverageChange", // distância absoluta até a MM200
        "twoHundredDayAverageChangePercent", // distância percentual até a MM200
        // — Janela de 52 semanas —
        "fiftyTwoWeekHigh",           // máxima de 52 semanas
        "fiftyTwoWeekLow",            // mínima de 52 semanas
        "fiftyTwoWeekHighChange",     // distância absoluta até a máxima
        "fiftyTwoWeekHighChangePercent", // distância percentual até a máxima
        "fiftyTwoWeekLowChange",      // distância absoluta até a mínima
        "fiftyTwoWeekLowChangePercent", // distância percentual até a mínima
        "fiftyTwoWeekRange",          // faixa de 52 semanas ('mínima - máxima')
        "fiftyTwoWeekChangePercent",  // variação acumulada em 52 semanas
        // — Liquidez —
        "averageDailyVolume10Day",    // volume médio diário (10 dias)
        "averageDailyVolume3Month",   // volume médio diário (3 meses)
        // — Livro/leilão —
        "bid",                        // melhor oferta de compra
        "ask",                        // melhor oferta de venda
        "bidSize",                    // quantidade no lado da compra
        "askSize",                    // quantidade no lado da venda
        // — Pós-mercado (com dados; o pré materializa no horário correspondente) —
        "postMarketPrice",            // último preço do pós-mercado
        "postMarketChange",           // variação absoluta do pós-mercado
        "postMarketChangePercent",    // variação percentual do pós-mercado
        "postMarketTime",             // timestamp do último negócio estendido
        "fulldayChange",              // variação absoluta do dia inteiro
        "fulldayChangePercent",       // variação percentual do dia inteiro
        // — Valuation e fundamentos —
        "marketCap",                  // capitalização de mercado
        "sharesOutstanding",          // total de ações emitidas (satélite de marketCap)
        "impliedSharesOutstanding",   // ações em circulação implícitas (satélite de marketCap)
        "financialCurrency",          // moeda dos demonstrativos financeiros ('USD')
        "bookValue",                  // valor patrimonial por ação
        "priceToBook",                // múltiplo preço/valor patrimonial
        "trailingPE",                 // múltiplo P/L dos últimos 12 meses
        "forwardPE",                  // múltiplo P/L projetado (consenso)
        "priceEpsCurrentYear",        // preço / EPS do ano corrente
        "epsTrailingTwelveMonths",    // lucro por ação dos últimos 12 meses
        "epsForward",                 // EPS projetado (consenso)
        "epsCurrentYear",             // EPS estimado do ano corrente
        "beta",                       // beta sistemático vs mercado (sob pedido — fora do default)
        "targetPriceMean",            // preço-alvo médio dos analistas (materializa sob pedido)
        "targetPriceHigh",            // preço-alvo máximo dos analistas (sob pedido)
        "targetPriceLow",             // preço-alvo mínimo dos analistas (sob pedido)
        "sector",                     // setor GICS (sob pedido — 'Technology')
        "industry",                   // indústria GICS (sob pedido — 'Consumer Electronics')
        "morningstarSector",          // setor na taxonomia Morningstar (sob pedido)
        "morningstarIndustry",        // indústria Morningstar (sob pedido)
        "heldPercentInsiders",        // % detida por insiders (sob pedido)
        "heldPercentInstitutions",    // % detida por instituições (sob pedido)
        "sharesShort",                // ações vendidas a descoberto (sob pedido)
        "shortRatio",                 // days-to-cover do short (sob pedido)
        "allTimeHigh",                // máxima histórica (sob pedido — o par ATH/ATL materializa
        "allTimeLow",                 //   em EQUITY/ETF/CURRENCY/FUTURE/INDEX/MUTUALFUND/
                                        //   ALTSYMBOL; nunca em MONEYMARKET/OPTION)
        "averageAnalystRating",       // rating consolidado ('2.2 - Buy')
        // — Dividendos —
        "dividendYield",              // rendimento de dividendos (anualizado, %)
        "dividendRate",               // dividendo por ação do último período
        "trailingAnnualDividendRate", // dividendo anual dos últimos 12 meses
        "trailingAnnualDividendYield", // rendimento anual dos últimos 12 meses
        "exDividendDate",             // data ex-dividendo (sob pedido, epoch segundos)
        "dividendDate",               // data do próximo dividendo (epoch segundos)
        // — Calendário de resultados —
        "earningsTimestamp",          // próximo anúncio de resultados (epoch)
        "earningsTimestampStart",     // início da janela de anúncio
        "earningsTimestampEnd",       // fim da janela de anúncio
        "earningsCallTimestampStart", // início da teleconferência
        "earningsCallTimestampEnd",   // fim da teleconferência
        "isEarningsDateEstimate",     // booleano: data de resultados é estimativa
        // — Identidade —
        "longName",                   // razão social completa
        "displayName",                // nome de exibição alternativo ('Apple')
        "messageBoardId",             // id do fórum do ativo
        "firstTradeDateMilliseconds"  // estreia de negociação (epoch ms)
      ]
    },

    {
      "id": "ETF",
      "tickerFormat": "[A-Z]{2,4}(ex: SPY, IVVB11.SA, BOVA11.SA)",
      "defaultPackageSize": 80,
      "fields": [
        // Herda praticamente todo o bloco de sessão/médias/52w/livro/pós-mercado de EQUITY
        // (idem regularMarket*, fiftyDay*, twoHundredDay*, fiftyTwoWeek*, averageDaily*,
        //  bid/ask/bidSize/askSize, postMarket*, fullday*, bookValue, priceToBook,
        //  epsTrailingTwelveMonths, trailingPE, trailingAnnualDividend*). Específicos:
        "netAssets",                  // patrimônio líquido do fundo
        "netExpenseRatio",            // taxa de administração líquida anual
        "navPrice",                   // valor patrimonial por cota (sob pedido)
        "ytdReturn",                  // rentabilidade acumulada no ano (%)
        "trailingThreeMonthReturns",  // rentabilidade dos últimos 3 meses
        "trailingThreeMonthNavReturns", // idem sobre o NAV
        "yield",                      // rendimento do fundo em % (sob pedido — SPY 0.99)
        "dividendYield",              // rendimento de distribuições
        "displayName",                // nome de exibição ('S&P 500 ETF Trust')
        // NOTA (validado ao vivo): morningStar*, categoryName, fundInceptionDate,
        //   annualHoldingsTurnover, annualReportExpenseRatio, beta3Year e trailingYtdReturn
        //   NÃO materializam neste endpoint (vocabulário de outros serviços)
      ]
    },

    {
      "id": "MUTUALFUND",
      "tickerFormat": "[A-Z]{4,5}(ex: VFIAX, PTTAX)",
      "defaultPackageSize": 65,
      "fields": [
        // Fundo mútuo: SEM os campos de sessão intradiária (regularMarketOpen, DayHigh,
        // DayLow, DayRange, Volume) e SEM livro/leilão (bid/ask) — mantém PreviousClose,
        // Change, ChangePercent e as médias/52w/volumes médios. Específicos:
        "netAssets",                  // patrimônio líquido
        "netExpenseRatio",            // taxa de administração
        "ytdReturn",                  // rentabilidade no ano (%)
        "trailingThreeMonthReturns",  // rentabilidade de 3 meses
        "yield",                      // rendimento do fundo em % (sob pedido — VFIAX 1.05)
        "dividendsPerShare",          // dividendos por ação (sob pedido — VFIAX 5.6485)
        "bookValue", "priceToBook", "epsTrailingTwelveMonths", "trailingPE",
        "dividendRate", "dividendYield", "trailingAnnualDividendRate",
        "trailingAnnualDividendYield", "financialCurrency", "displayName"
      ]
    },

    {
      "id": "MONEYMARKET",
      "tickerFormat": "[A-Z]{4,5}(ex: SPAXX, VMFXX)",
      "defaultPackageSize": 33,       // o pacote mais enxuto de todas as classes
      "fields": [
        "netAssets",                  // patrimônio líquido do fundo
        "trailingAnnualDividendRate", // rendimento anual distribuído (juros)
        "displayName",                // nome de exibição
        "longName",                   // razão social do fundo
        "messageBoardId"              // id do fórum
        // Sem sessão intradiária, sem médias, sem 52 semanas, sem livro — só o núcleo + acima
      ]
    },

    {
      "id": "CRYPTOCURRENCY",
      "tickerFormat": "[A-Z0-9]+-[A-Z]+ (ex: BTC-USD, ETH-USD, SOL-USD)",
      "defaultPackageSize": 70,
      "fields": [
        // Sessão 24/7 (regularMarket* com dados contínuos), médias e 52w — mas SEM
        // livro/leilão: bid/ask/bidSize/askSize NUNCA existem em CRYPTOCURRENCY
        // (mesma regra do [marketSummary](v6_finance_quote_marketSummary.md)). Específicos:
        "circulatingSupply",          // moedas em circulação
        "totalSupply",                // oferta total
        "maxSupply",                  // oferta máxima (21000000 para BTC)
        "marketCap",                  // capitalização (preço x circulatingSupply)
        "volume24Hr",                 // volume financeiro em 24 horas
        "volumeAllCurrencies",        // volume consolidado em todas as moedas
        "fromCurrency",               // moeda base do par ('BTC')
        "toCurrency",                 // moeda de cotação com sufixo '=X' ('USD=X')
        "fromExchange",               // exchange de origem do par ('CCC') (sob pedido)
        "toExchange",                 // exchange de cotação ('CCY') (sob pedido)
        "cmcRank",                    // posição no ranking CoinMarketCap (sob pedido)
        "coinImageUrl",               // ícone da moeda (CoinMarketCap)
        "coinMarketCapLink",          // página da moeda no CoinMarketCap
        "lastMarket",                 // mercado do último negócio ('Coinbase')
        "logoUrl",                    // logotipo do ativo
        "startDate",                  // criação/listagem (epoch segundos)
        "allTimeHigh",                // máxima histórica (sob pedido)
        "allTimeLow"                  // mínima histórica (sob pedido — NÃO exclusivos de
                                      //   cripto: o par materializa em EQUITY, ETF, CURRENCY,
                                      //   FUTURE, INDEX, MUTUALFUND e ALTSYMBOL; nunca em
                                      //   MONEYMARKET/OPTION)
        // NOTA: fullyDilutedValue e volume24HrMarketCapPercent NÃO materializam (pedidos
        //   e ignorados) — divergem de documentação informal; validar antes de usar
      ]
    },

    {
      "id": "CURRENCY",
      "tickerFormat": "[A-Z]{6}=X (ex: EURUSD=X, USDBRL=X, BRL=X)",
      "defaultPackageSize": 61,
      "fields": [
        // Forex: sessão contínua, médias, 52w, volumes médios e livro/leilão presentes
        // (bid/ask com taxas reais; bidSize/askSize = 0). Sem campos exclusivos além do
        // currency do núcleo (moeda de cotação). ATENÇÃO (validado ao vivo): fromCurrency/
        // toCurrency são EXCLUSIVOS de CRYPTOCURRENCY — não materializam em CURRENCY nem
        // sob pedido explícito (mesma regra do [marketSummary](v6_finance_quote_marketSummary.md))
        "bid", "ask", "bidSize", "askSize",
        "regularMarketOpen", "regularMarketDayHigh", "regularMarketDayLow",
        "regularMarketDayRange", "regularMarketPreviousClose", "regularMarketChange",
        "regularMarketChangePercent", "regularMarketVolume",
        "fiftyDayAverage", "fiftyDayAverageChange", "fiftyDayAverageChangePercent",
        "twoHundredDayAverage", "twoHundredDayAverageChange", "twoHundredDayAverageChangePercent",
        "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "fiftyTwoWeekRange", "fiftyTwoWeekChangePercent",
        "fiftyTwoWeekHighChange", "fiftyTwoWeekHighChangePercent",
        "fiftyTwoWeekLowChange", "fiftyTwoWeekLowChangePercent",
        "averageDailyVolume10Day", "averageDailyVolume3Month",
        "fulldayChange", "fulldayChangePercent", "longName", "messageBoardId",
        "firstTradeDateMilliseconds"
      ]
    },

    {
      "id": "INDEX",
      "tickerFormat": "^[A-Z0-9]+ (ex: ^GSPC, ^BVSP) e locais (000001.SS, FTSEMIB.MI)",
      "defaultPackageSize": 61,
      "fields": [
        // Espelha exatamente o pacote de CURRENCY (61 campos, mesmíssima lista observada):
        // sessão, médias, 52w, volumes médios e livro/leilão — SEM marketCap, SEM
        // fundamentos, SEM fromCurrency/toCurrency
        "bid", "ask", "bidSize", "askSize",
        "regularMarketOpen", "regularMarketDayHigh", "regularMarketDayLow",
        "regularMarketDayRange", "regularMarketPreviousClose", "regularMarketChange",
        "regularMarketChangePercent", "regularMarketVolume",
        "fiftyDayAverage", "fiftyDayAverageChange", "fiftyDayAverageChangePercent",
        "twoHundredDayAverage", "twoHundredDayAverageChange", "twoHundredDayAverageChangePercent",
        "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "fiftyTwoWeekRange", "fiftyTwoWeekChangePercent",
        "fiftyTwoWeekHighChange", "fiftyTwoWeekHighChangePercent",
        "fiftyTwoWeekLowChange", "fiftyTwoWeekLowChangePercent",
        "averageDailyVolume10Day", "averageDailyVolume3Month",
        "fulldayChange", "fulldayChangePercent", "longName", "messageBoardId",
        "firstTradeDateMilliseconds"
      ]
    },

    {
      "id": "FUTURE",
      "tickerFormat": "[A-Z]+=F (ex: ES=F, CL=F, GC=F, ZN=F)",
      "defaultPackageSize": 66,
      "fields": [
        // Sessão, médias, 52w, volumes, livro/leilão + o bloco de contratos:
        "headSymbolAsString",         // cabeça da cadeia de contratos como string ('GC=F')
        "contractSymbol",             // booleano: é contrato individual (false no contínuo '=F')
        "underlyingSymbol",           // ativo-objeto do contrato ('GCZ26.CMX')
        "underlyingExchangeSymbol",   // símbolo-objeto com a bolsa ('GCZ26.CMX' — igual ao
                                      //   underlyingSymbol observado, não apenas a sigla 'CMX')
        "expireDate",                 // vencimento (epoch segundos)
        "expireIsoDate",              // vencimento em ISO 8601
        "openInterest",               // contratos em aberto
        // NOTA: strike NÃO existe para FUTURE (exclusivo de OPTION); prevSettlementDate,
        //   settlementDate, contractRange e headSymbol (booleano citado em doc informal)
        //   pedidos e NÃO materializam
        "bid", "ask", "bidSize", "askSize",
        "regularMarketOpen", "regularMarketDayHigh", "regularMarketDayLow",
        "regularMarketDayRange", "regularMarketPreviousClose", "regularMarketChange",
        "regularMarketChangePercent", "regularMarketVolume",
        "fiftyDayAverage", "fiftyDayAverageChange", "fiftyDayAverageChangePercent",
        "twoHundredDayAverage", "twoHundredDayAverageChange", "twoHundredDayAverageChangePercent",
        "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "fiftyTwoWeekRange", "fiftyTwoWeekChangePercent",
        "fiftyTwoWeekHighChange", "fiftyTwoWeekHighChangePercent",
        "fiftyTwoWeekLowChange", "fiftyTwoWeekLowChangePercent",
        "averageDailyVolume10Day", "averageDailyVolume3Month",
        "fulldayChange", "fulldayChangePercent", "firstTradeDateMilliseconds"
        // Sem longName nem messageBoardId no pacote default observado
      ]
    },

    {
      "id": "OPTION",
      "tickerFormat": "[A-Z]+\\d{6}[CP]\\d{8} (ex: AAPL261023C00340000)",
      "defaultPackageSize": 56,
      "fields": [
        "strike",                     // preço de exercício (340.000 → strike 340.0)
        "optionsType",                // 'Call' ou 'Put'
        "expireDate",                 // vencimento (epoch segundos)
        "expireIsoDate",              // vencimento ISO 8601 ('2026-10-23T00:00:00Z')
        "openInterest",               // contratos em aberto (5750)
        "underlyingSymbol",           // ativo-objeto ('AAPL')
        "displayName",                // nome descritivo ('AAPL Oct 2026 340.000 call')
        "longName",                   // descrição completa do contrato
        "bid", "ask",                 // livro sem tamanhos (bidSize/askSize ausentes)
        "regularMarketOpen", "regularMarketDayHigh", "regularMarketDayLow",
        "regularMarketDayRange", "regularMarketPreviousClose", "regularMarketChange",
        "regularMarketChangePercent", "regularMarketVolume",
        "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "fiftyTwoWeekRange",
        "fiftyTwoWeekHighChange", "fiftyTwoWeekHighChangePercent",
        "fiftyTwoWeekLowChange", "fiftyTwoWeekLowChangePercent",
        "fulldayChange", "fulldayChangePercent", "firstTradeDateMilliseconds"
        // Sem médias móveis (fiftyDay*/twoHundredDay*) e sem volumes médios — o mais
        // distante do pacote de EQUITY entre as classes derivativas. underlyingShortName
        // (citado em doc informal) pedido e NÃO materializa; contagem estável em 56 campos
        // em contratos líquidos ITM e OTM profundo; contratos expirados há mais tempo caem
        // do result como os inexistentes — vencidos há poucos dias AINDA resolvem com dados
        // congelados (AAPL261016C00340000, 3 dias após o vencimento, out/2026: OPTION, 55
        // campos, price 3.58; AAPL260918…/AAPL251219…/AAPL241018… já caem)
      ]
    },

    {
      "id": "ALTSYMBOL",
      "tickerFormat": "alias de contrato (ex: CT=F — aponta para o algodão CTX26.NYM)",
      "defaultPackageSize": 56,
      "fields": [
        // Alias sem identidade própria: shortName/longName/displayName NUNCA existem (nem
        // sob pedido); typeDisp vem como a literal 'ALTSYMBOL'; exchange 'NYM' ('NY
        // Mercantile'); currency 'USX' — pseudo-moeda de contrato cotado em centavos. O
        // pacote é o de mercado: regularMarket* SEM regularMarketOpen, médias 50/200 dias,
        // bloco de 52 semanas, volumes médios, fullday*, bid/ask sem tamanhos —
        // + underlyingSymbol apontando o contrato real; allTimeHigh/allTimeLow
        // materializam sob pedido (227.0 / 0.0 no CT=F). Sem postMarket*, sem
        // messageBoardId, sem longName
        "underlyingSymbol"            // contrato-objeto real ('CTX26.NYM' para CT=F)
      ]
    },

    {
      "id": "NONE",
      "tickerFormat": "deslistados/adquiridos (ex: TWTR, ATVI, SGEN, PXD, SIVB)",
      "defaultPackageSize": null,     // esqueleto de 11–13 campos — sem pacote de mercado
      "fields": [
        // Esqueleto devolvido para símbolos que existiram e saíram de negociação
        // (aquisição/delisting): SEM preço, SEM nome, SEM bolsa, SEM marketState, SEM fuso
        // — apenas symbol/quoteType/region/language + flags (tradeable, triggerable,
        // cryptoTradeable, esgPopulated, hasPrePostMarketData,
        // customPriceAlertConfidence, corporateActions). NADA materializa sob pedido
        // (shortName, regularMarketPrice e allTimeHigh testados — todos ausentes).
        // Variação observada: +financialCurrency em ex-empresas (ATVI, PXD, SGEN) e
        // +messageBoardId ocasional (SGEN). O desconhecido total (BBBY, DHI-BR,
        // INEXISTENTE9999XYZ) nem entra no result — omitido; e o ticker reciclado por
        // nova listagem resolve o ativo NOVO (FB hoje = ETF da ProShares, 70 campos).
        // Distinguir NONE (símbolo conhecido, sem dados) de omissão (desconhecido)
      ]
    },

    {
      "id": "PRIVATE_COMPANY",

      // Divergência registrada com honestidade: nenhuma chamada devolveu itens .PVT.
      // Testado em 2026-10-18 com os 8 símbolos STRIPE.PVT, OPENAI.PVT, SPACEX.PVT,
      // ANTHROPIC.PVT, XAI.PVT, CANVA.PVT, DATABRICKS.PVT, EPICGAMES.PVT — todos
      // retornam 200 com "result": [] (silêncio, sem erro), inclusive com as flags
      // enablePrivateCompany=true e mockPrivateCompany=true (que existem no código do
      // cliente, loadQuote.C6XUn82q.js). A classe permanece no vocabulário do cliente e em
      // documentação informal (latestImpliedValuation, fundingToDate, latestAmountRaised,
      // latestFundingDate, totalFundingRounds, latestShareClass — pacote de 41 campos
      // alegado), mas nenhum desses campos pôde ser validado ao vivo neste endpoint.
      "tickerFormat": "[A-Z]+.PVT (ex: STRIPE.PVT)",
      "defaultPackageSize": null,
      "fields": []
    }
  ]
}
```

## Constantes padrão

Valores que vêm como padrão no próprio código fonte, organizados em constantes:

```json5
{
  // ==========================================================================
  // 4 · CONSTANTES PADRÃO DO ENDPOINT (valores nativos do código fonte)
  // ==========================================================================

  // Hosts espelhos que servem este endpoint — o picker do transporte (chartStatic.Bl5ArXnz.js, função Fl)
  // SORTEIA entre query1 e query2 a cada chamada (Math.random); o streamer de tempo real é o
  // único chamador que hardcoda query1; iquery é o host fixo de chamadas selecionadas
  // (financeInternal) e iquery-stage o de ambientes internos (int* · ?chartStage=true)
  "hosts": [
    "https://query1.finance.yahoo.com",   // pool público (sorteio; hardcoded no streamer)
    "https://query2.finance.yahoo.com"    // pool público (sorteio; função u do portfólio/cryptoTrade)
  ],

  // Tamanho máximo do lote enviado POR REQUISIÇÃO HTTP pelo cliente oficial
  // (loadQuote.C6XUn82q.js). Não é limite do servidor: lotes de 159 símbolos distintos
  // passam íntegros (151 itens = 159 − 8 tickers inválidos da amostra; validado ao vivo —
  // seção 7); é disciplina do cliente.
  "batchSize": 30,

  // Campos que o loadQuote anexa a TODA projeção pedida (acumulador de fields do loader
  // em loadQuote.C6XUn82q.js — somados após a filtragem de cache e deduplicados no Set final).
  // Garantia client-side: o servidor já devolve o núcleo-24 com qualquer fields=, então
  // estes 5 nunca faltam na prática. O trio fullday também vai ao fio INCONDICIONALMENTE
  // (empurrado junto com os 5 base após a triagem de cache); enableExtendedHours só amplia
  // a CHECAGEM de campos faltantes em itens cacheados (loaderBaseExtendedHours — Object.values
  // de EXTENDED_HOURS_FIELD_MAP, support_agent.Cd9DzWFk.js — mesmo mapa do [marketSummary](v6_finance_quote_marketSummary.md)):
  "loaderBaseFields": [
    "regularMarketTime", "regularMarketChange", "regularMarketChangePercent",
    "regularMarketPrice", "regularMarketVolume"
  ],
  "loaderBaseExtendedHours": ["fulldayPrice", "fulldayChange", "fulldayChangePercent"],

  // Campos ISENTOS da checagem de cache local do loadQuote: a presença/ausência deles no
  // cache NÃO dispara re-request (ticker/sparkline são aliases de UI calculados no
  // cliente). Um símbolo cacheado só volta ao fio quando FALTA algum campo pedido FORA
  // desta lista — o pacote de 9 abaixo é o exato do código (loadQuote.C6XUn82q.js):
  "cachePresenceFields": [
    "fromCurrency", "fromExchange", "headSymbolAsString", "toCurrency", "toExchange",
    "ticker", "sparkline", "underlyingExchangeSymbol", "underlyingSymbol"
  ],

  // Caracteres válidos de símbolo no cliente (regex Ze/Ne de 188.DvdQXGb3.js, exportada
  // como c_1 e aplicada após decodeURIComponent): símbolos que
  // contenham qualquer caractere FORA desta classe são descartados ANTES do envio
  // (aapl, ^GSPC, PETR4.SA, BTC-USD, EURUSD=X, ES=F, BRK-B — todos passam)
  "symbolCharClass": "[a-zA-Z0-9^.$_+=*&:@~-]",

  // Campos do SEED do streamer de tempo real (webcore/js/streamer.worker.*.js — array m do worker):
  // a semente inicial do WebSocket dispara GET /v7/finance/quote com estes 30
  // campos, em lotes de 30 símbolos ORDENADOS, apenas para símbolos ainda sem
  // exchangeTimezoneName no cache local, somente quando há crumb, com debounce de 500 ms
  "streamerSeedFields": [
    "currency", "fromCurrency", "toCurrency",
    "exchangeTimezoneName", "exchangeTimezoneShortName", "gmtOffSetMilliseconds",
    "regularMarketChange", "regularMarketChangePercent", "regularMarketPrice",
    "regularMarketTime",
    "preMarketChange", "preMarketChangePercent", "preMarketPrice", "preMarketTime",
    "priceHint",
    "postMarketChange", "postMarketChangePercent", "postMarketPrice", "postMarketTime",
    "extendedMarketChange", "extendedMarketChangePercent", "extendedMarketPrice",
    "extendedMarketTime",
    "overnightMarketChange", "overnightMarketChangePercent", "overnightMarketPrice",
    "overnightMarketTime",
    "fulldayPrice", "fulldayChange", "fulldayChangePercent"
  ],

  // URL literal do seed no fio (webcore/js/streamer.worker.*.js — template exato, com o & colado
  // no ?, crumb vazio serializado como string vazia e formatted herdado da flag da
  // sessão useFormattedSeeding; o servidor tolera o & inicial):
  "streamerSeedUrlTemplate":
    "https://query1.finance.yahoo.com/v7/finance/quote?&symbols=${symbols}&fields=${fields}&crumb=${crumb}&formatted=${formatted}&region=US&lang=en-US",

  // Campos base da PÁGINA DE COTAÇÕES (array D de 188.DvdQXGb3.js, servido pela função
  // ab(quoteType, category) — 34 campos; equivalentes anteriores: array W de security.*.js):
  // pedido para TODO quoteType/categoria via loadQuote; CRYPTOCURRENCY/summary soma cmcRank
  "quoteSummaryBaseFields": [
    "fiftyTwoWeekHigh", "fiftyTwoWeekLow",
    "fromCurrency", "fromExchange",
    "headSymbolAsString",
    "logoUrl",
    "longName", "shortName",
    "marketCap", "messageBoardId",
    "optionsType",
    "overnightMarketTime", "overnightMarketPrice", "overnightMarketChange",
    "overnightMarketChangePercent",
    "regularMarketTime", "regularMarketChange", "regularMarketChangePercent",
    "regularMarketOpen", "regularMarketPrice", "regularMarketSource", "regularMarketVolume",
    "postMarketTime", "postMarketPrice", "postMarketChange", "postMarketChangePercent",
    "preMarketTime", "preMarketPrice", "preMarketChange", "preMarketChangePercent",
    "toCurrency", "toExchange",
    "underlyingExchangeSymbol", "underlyingSymbol"
  ],

  // Campos fixos dos widgets de PORTFÓLIO (webcore/js/portfolio.*.js) e do modal de TRADE de
  // cripto (webcore/js/cryptoTrade.*.js) — os dois usam o mesmo construtor de URL (função u)
  "portfolioFields": [
    "longName", "shortName", "symbol",
    "regularMarketChange", "regularMarketChangePercent", "regularMarketPrice"
  ],
  "cryptoTradeFields": [
    "longName", "shortName", "symbol", "coinImageUrl", "fromCurrency"
  ],

  // Parâmetros-padrão do construtor de URL do portfólio/cryptoTrade (função u):
  // formatted=true incondicional · crumb anexado SÓ se não-vazio · lang/region da
  // sessão (finWebCore) com fallback en-US/US · corsDomain = host da página ·
  // fields anexado SÓ se array · timeout de 1500 ms · host sorteado
  "widgetUrlDefaults": {
    "formatted": "true",
    "langFallback": "en-US",
    "regionFallback": "US",
    "corsDomain": "window.location.host",
    "timeoutMs": 1500
  },

  // Flags de sessão que alteram a query do loadQuote (loadQuote.C6XUn82q.js):
  // enableExtendedHours  → anexa o trio fulldayPrice/fulldayChange/fulldayChangePercent
  //                        aos fields (herança do [marketSummary](v6_finance_quote_marketSummary.md))
  // enableQuoteCache / enableCGQuoteCaching / enableQuotePageQuoteCaching → envia os
  //                        headers x-cache: 1 e x-cache-ttl: 30000
  // useLogoDevLogo       → com logoUrl na projeção: acrescenta logoUrlDarkMode e troca o
  //                        provedor do logo para o proxy mysterio/logo.dev
  // imgLabels/imgHeights/imgWidths → logoUrl/50/50 (defaults enviados; dimensão hoje sem
  //                        efeito na URL devolvida — ver imgHeights na seção 1)
  // mockPrivateCompany / mockOvernightPrice / enablePrivateCompany / overnightPrice →
  //                        flags de teste/recurso anexadas quando ativas — DETALHE: a flag
  //                        de sessão do overnight chama-se enableOvernight, mas serializa
  //                        na query como overnightPrice=true (loadQuote.C6XUn82q.js)
  "loadQuoteSessionFlags": [
    "enableExtendedHours", "enableQuoteCache", "enableCGQuoteCaching",
    "enableQuotePageQuoteCaching", "useLogoDevLogo",
    "mockPrivateCompany", "mockOvernightPrice",
    "enablePrivateCompany", "overnightPrice"
  ],

  // Flags da página de cotações (208._QKNXuHf.js) que injetam Campos na resposta:
  // topPickThisMonth=true (EQUITY + flag de sessão enableQSPStockPicks*) →
  //   stockPick{ID, Provider, Rating, URL, CTA}
  // checkUnusualOptionsActivity=true (categoria options + flag) →
  //   hasUnusualOptionsActivity no item (o bloco stockPick* materializa em EQUITY, com
  //   topPickThisMonth — em OPTION só a flag de atividade incomum, validado out/2026)
  "quoteSummaryQueryFlags": {
    "topPickThisMonth": "true",              // → stockPick*
    "checkUnusualOptionsActivity": "true"    // → hasUnusualOptionsActivity + stockPick*
  }
}
```

## Vocabulário de fields

Vocabulário aceito pelo parâmetro `fields` — **129 campos observados ao vivo** (união dos pacotes default das 11 classes + materializáveis sob pedido + injeções por flag), organizados por lógica. O filtro é dinâmico por `quoteType`: peça a lista completa que o servidor devolve, por item, apenas os campos compatíveis com a classe (projeção tolerante — sem `400` para desconhecidos ou incompatíveis).

```json5
{
  // ==========================================================================
  // 5 · VOCABULÁRIO DE FIELDS — grupos por lógica (união observada: 129)
  // ==========================================================================

  // Núcleo universal — sempre presente (28 no pacote default; 24 quando fields= existe):
  //   ver seção 2 (commonFields)

  // Sessão regular — materializam com dados em todas as classes com pregão:
  "session": [
    "regularMarketOpen",                 // abertura
    "regularMarketDayHigh",              // máxima
    "regularMarketDayLow",               // mínima
    "regularMarketDayRange",             // faixa ('mínima - máxima')
    "regularMarketPreviousClose",        // fechamento anterior
    "regularMarketChange",               // variação absoluta
    "regularMarketChangePercent",        // variação percentual
    "regularMarketVolume"                // volume
  ],

  // Horários estendidos — pre/post do fluxo de ações; extended/overnight do feed
  // contínuo; fullday = consolidação do dia inteiro (o trio herda do marketSummary):
  "extendedHours": [
    "preMarketPrice", "preMarketChange", "preMarketChangePercent", "preMarketTime",
    "postMarketPrice", "postMarketChange", "postMarketChangePercent", "postMarketTime",
    "extendedMarketPrice", "extendedMarketChange", "extendedMarketChangePercent",
    "extendedMarketTime",
    "overnightMarketPrice", "overnightMarketChange", "overnightMarketChangePercent",
    "overnightMarketTime",
    "fulldayPrice", "fulldayChange", "fulldayChangePercent"
  ],

  // Médias móveis e janela de 52 semanas:
  "averages": [
    "fiftyDayAverage", "fiftyDayAverageChange", "fiftyDayAverageChangePercent",
    "twoHundredDayAverage", "twoHundredDayAverageChange", "twoHundredDayAverageChangePercent"
  ],
  "fiftyTwoWeek": [
    "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "fiftyTwoWeekRange", "fiftyTwoWeekChangePercent",
    "fiftyTwoWeekHighChange", "fiftyTwoWeekHighChangePercent",
    "fiftyTwoWeekLowChange", "fiftyTwoWeekLowChangePercent"
  ],
  "averageDailyVolume": [
    "averageDailyVolume10Day",            // volume médio (10 dias)
    "averageDailyVolume3Month"            // volume médio (3 meses)
  ],

  // Livro/leilão — INEXISTENTE em CRYPTOCURRENCY (mesma regra do marketSummary);
  // em OPTION vêm sem os tamanhos; em INDEX/CURRENCY os tamanhos são 0:
  "orderBook": [
    "bid",                                // melhor oferta de compra
    "ask",                                // melhor oferta de venda
    "bidSize",                            // quantidade no lado da compra
    "askSize"                             // quantidade no lado da venda
  ],

  // Exclusivos de EQUITY/ETF/fundos — valuation, fundamentos, dividendos, resultados:
  "fundamentals": [
    "marketCap",                          // capitalização (EQUITY e CRYPTOCURRENCY)
    "sharesOutstanding",                  // ações emitidas (EQUITY; satélite de marketCap)
    "impliedSharesOutstanding",           // ações implícitas (EQUITY; satélite de marketCap)
    "financialCurrency",                  // moeda dos demonstrativos ('USD')
    "bookValue",                          // valor patrimonial por ação
    "priceToBook",                        // P/valor patrimonial
    "trailingPE",                         // P/L trailing (EQUITY, ETF, MUTUALFUND)
    "forwardPE",                          // P/L projetado
    "priceEpsCurrentYear",                // preço/EPS ano corrente
    "epsTrailingTwelveMonths",            // EPS LTM
    "epsForward",                         // EPS projetado
    "epsCurrentYear",                     // EPS estimado do ano
    "beta",                               // beta sistemático
    "targetPriceMean", "targetPriceHigh", "targetPriceLow",  // preço-alvo dos analistas
    "averageAnalystRating",               // rating consolidado ('2.2 - Buy')
    "dividendYield", "dividendRate",
    "trailingAnnualDividendRate", "trailingAnnualDividendYield",
    "dividendDate",
    "earningsTimestamp", "earningsTimestampStart", "earningsTimestampEnd",
    "earningsCallTimestampStart", "earningsCallTimestampEnd",
    "isEarningsDateEstimate",
    // — classificação e estrutura acionária (EQUITY; só sob pedido — fora do default) —
    "sector",                             // setor GICS ('Technology')
    "industry",                           // indústria GICS ('Consumer Electronics')
    "morningstarSector",                  // setor na taxonomia Morningstar
    "morningstarIndustry",                // indústria Morningstar
    "heldPercentInsiders",                // % em mãos de insiders
    "heldPercentInstitutions",            // % em mãos de instituições
    "sharesShort",                        // short interest (ações vendidas a descoberto)
    "shortRatio",                         // days-to-cover do short
    "exDividendDate"                      // data ex-dividendo (epoch segundos)
  ],

  // Exclusivos de fundos (ETF/MUTUALFUND/MONEYMARKET):
  "funds": [
    "netAssets",                          // patrimônio líquido
    "netExpenseRatio",                    // taxa de administração líquida
    "navPrice",                           // valor patrimonial por cota (sob pedido)
    "ytdReturn",                          // rentabilidade no ano
    "trailingThreeMonthReturns",          // rentabilidade 3 meses
    "trailingThreeMonthNavReturns",       // idem sobre NAV (ETF)
    "yield",                              // rendimento do fundo em % (sob pedido — ETF/MUTUALFUND)
    "dividendsPerShare"                   // dividendos por ação (sob pedido — MUTUALFUND)
  ],

  // Exclusivos de CRYPTOCURRENCY:
  "crypto": [
    "circulatingSupply", "totalSupply", "maxSupply",
    "volume24Hr", "volumeAllCurrencies",
    "fromCurrency",                       // moeda base ('BTC')
    "toCurrency",                         // cotação com sufixo '=X' ('USD=X')
    "fromExchange",                       // exchange de origem do par ('CCC') (sob pedido)
    "toExchange",                         // exchange de cotação ('CCY') (sob pedido)
    "cmcRank",                            // ranking CoinMarketCap (sob pedido)
    "coinImageUrl", "coinMarketCapLink",  // ícone e link CoinMarketCap
    "lastMarket",                         // mercado do último negócio
    "logoUrl",                            // logotipo
    "startDate",                          // criação (epoch)
    "allTimeHigh", "allTimeLow"           // extremos históricos (sob pedido — NÃO
                                          //   exclusivos de cripto: o par materializa em
                                          //   EQUITY, ETF, CURRENCY, FUTURE, INDEX, MUTUALFUND
                                          //   e ALTSYMBOL; nunca em MONEYMARKET/OPTION)
  ],

  // Derivativos (FUTURE/OPTION):
  "derivatives": [
    "strike",                             // exercício (OPTION)
    "optionsType",                        // 'Call'/'Put' (OPTION)
    "expireDate", "expireIsoDate",        // vencimento
    "openInterest",                       // interesse aberto
    "underlyingSymbol",                   // ativo-objeto
    "underlyingExchangeSymbol",           // bolsa do ativo-objeto (FUTURE)
    "headSymbolAsString",                 // cabeça da cadeia ('GC=F') — FUTURE
    "contractSymbol"                      // bool contrato individual — FUTURE
  ],

  // Identidade/meta — presentes conforme a classe e a disponibilidade de dados:
  "identity": [
    "longName", "displayName", "messageBoardId", "firstTradeDateMilliseconds",
    "corporateActions"
  ],

  // Injetados por flags de query (ver constantes, seção 4):
  "injectedByFlags": {
    "topPickThisMonth / checkUnusualOptionsActivity": [
      "stockPickID", "stockPickProvider", "stockPickRating", "stockPickURL", "stockPickCTA"
    ],
    "checkUnusualOptionsActivity": ["hasUnusualOptionsActivity"],
    "useLogoDevLogo": ["companyLogoUrl", "logoUrl", "logoUrlDarkMode"]
    // logos SEM flag: logoUrl e companyLogoUrl materializam JUNTOS quando qualquer um deles
    //   está na projeção fields — o trio img* NÃO injeta campos, só dimensiona a URL
    //   (150x150 sem parâmetros; 50x50/100x100 conforme imgHeights/imgWidths);
    //   useLogoDevLogo acrescenta logoUrlDarkMode e troca o provedor para o proxy
    //   mysterio/logo.dev
  },

  // Pedidos e NÃO materializados (ignorados silenciosamente — divergem de documentação
  // informal; usar com validação própria): regularMarketSource (existe no código do
  // cliente, nunca voltou na resposta) · postMarketSource · fullyDilutedValue ·
  // volume24HrMarketCapPercent (cripto) · prevSettlementDate · settlementDate ·
  // contractRange (futuro) · strike em FUTURE · headSymbol (FUTURE) · underlyingShortName
  // (OPTION) · morningStarOverallRating · morningStarRiskRating · categoryName ·
  // fundInceptionDate · annualHoldingsTurnover · annualReportExpenseRatio · beta3Year ·
  // trailingYtdReturn (fundos) · fromCurrency/toCurrency em CURRENCY · displayName em
  // INDEX · stockPickProviderLogoURL · stockPickReason · família stockStory inteira
  // (stockStoryQuality, stockStoryIsTopSixThisWeek, stockStoryURL, stockStoryTopSixURL —
  // pedida pelo cliente 219, nunca devolvida) · aliases de UI/portfólio calculados no
  // cliente (sparkline, ticker, price, quantity, purchasePrice, dailyGain, totalGain) ·
  // vocabulário do quoteSummary (enterpriseValue, recommendationMean,
  // numberOfAnalystOpinions, shortPercentOfFloat) · allTimeHigh/allTimeLow em
  // MONEYMARKET/OPTION · toda a família PRIVATE_COMPANY
}
```

**Recortes prontos de `fields`** — o servidor devolve o núcleo-24 em qualquer recorte; os cortes abaixo são pontos de partida comuns (o loader oficial ainda somaria os 5 campos base — seção 4):

```bash
# Preço essencial
fields=regularMarketPrice,regularMarketChange,regularMarketChangePercent

# Identidade e logo (logoUrl puxa companyLogoUrl junto; dimensionar com imgHeights/imgWidths)
fields=shortName,longName,logoUrl,currency,fullExchangeName

# Sessões estendidas (pre/post/fullday/overnight só materializam com dados da janela vigente)
fields=regularMarketPrice,preMarketPrice,preMarketChange,postMarketPrice,postMarketChange,overnightMarketPrice,fulldayPrice

# Faixa de 52 semanas e volume
fields=fiftyTwoWeekHigh,fiftyTwoWeekLow,regularMarketVolume,averageDailyVolume3Month
```

## Resposta e erros

Envelope de sucesso, envelope de erro e regras de formatação dos valores:

```json5
{
  // ==========================================================================
  // 6 · ENVELOPE DA RESPOSTA
  // ==========================================================================
  "sucesso": {
    "quoteResponse": {
      "result": [ "/* array de itens de cotação, um por símbolo RESOLVIDO — vocabulário na seção 5 */" ],
      "error": null
    }
  },

  "erro": {
    "finance": {
      "result": null,
      "error": {
        "code": "Unauthorized",             // 401 — falta cookie, crumb (ou ambos são inválidos)
        "description": "User is unable to access this feature - https://bit.ly/yahoo-finance-api-feedback"
      }
    }
  },

  // 400 — symbols ausente ou vazio (checado DEPOIS da autenticação):
  "erroBadRequest": {
    "finance": {
      "result": null,
      "error": {
        "code": "Bad Request",
        "description": "Missing required query parameter=symbols"
      }
    }
  },

  // Regras de formatação dos valores:
  "formattedTrue": {
    "regularMarketPrice": { "raw": 343.46, "fmt": "343.46" },
    "marketCap": { "raw": 5012516765696, "fmt": "5.013T", "longFmt": "5,012,516,765,696" },
    "impliedSharesOutstanding": { "raw": 14594180000, "fmt": "14.594B",
                                  "longFmt": "14,594,180,000" }
    // campos de grande magnitude somam "longFmt"
  },
  "formattedFalse": {
    "regularMarketPrice": 343.46,           // primitivos crus
    "marketCap": 5012516765696
  },
  "formattedOmitido": "equivale a false (primitivos) — default INVERSO ao marketSummary",
  "metadados": "cru nos DOIS modos",        // strings (symbol, marketState…), inteiros
                                            //   (priceHint, gmtOffSetMilliseconds,
                                            //   sourceInterval) e booleanos seguem crus
}
```

| HTTP | Quando | Corpo |
| :---: | :--- | :--- |
| `400` | `symbols` ausente ou vazio (com sessão válida) | `Bad Request` · `Missing required query parameter=symbols` |
| `401` | sem Cookie A3, sem crumb, par descasado ou crumb errado | `Unauthorized` · `User is unable to access this feature - https://bit.ly/yahoo-finance-api-feedback` |
| `405` | método não permitido (`POST` e demais) | `Method Not Allowed` · `HTTP 405 Method Not Allowed` |
| `429` | User-Agent bloqueado | `Edge: Too Many Requests` (texto puro) |

Exemplo de item (`formatted=true`, recortado — `fields=shortName,regularMarketPrice,marketCap,trailingPE`):

```json
{
  "symbol": "AAPL",
  "quoteType": "EQUITY",
  "typeDisp": "Equity",
  "marketState": "REGULAR",
  "currency": "USD",
  "regularMarketPrice": { "raw": 343.46, "fmt": "343.46" },
  "regularMarketTime": { "raw": 1792285343, "fmt": "9:02PM UTC" },
  "marketCap": { "raw": 5012516765696, "fmt": "5.013T", "longFmt": "5,012,516,765,696" },
  "sharesOutstanding": { "raw": 14594180000, "fmt": "14.594B", "longFmt": "14,594,180,000" },
  "trailingPE": { "raw": 39.38761, "fmt": "39.39" },
  "exchangeTimezoneName": "America/New_York",
  "priceHint": 2,
  "quoteSourceName": "Free Realtime Quote"
}
```

O mesmo lote com `formatted=false` (primitivos; `esgPopulated` presente):

```json
{
  "symbol": "AAPL",
  "regularMarketPrice": 343.46,
  "regularMarketTime": 1792285343,
  "marketCap": 5012516765696,
  "trailingPE": 39.38761,
  "esgPopulated": false,
  "marketState": "REGULAR"
}
```

Item de opção (`formatted=false`, pacote default de 56 campos, recortado):

```json
{
  "symbol": "AAPL261023C00340000",
  "shortName": "AAPL Oct 2026 340.000 call",
  "quoteType": "OPTION",
  "typeDisp": "Option",
  "market": "us24_market",
  "marketState": "CLOSED",
  "exchange": "OPR",
  "fullExchangeName": "OPR",
  "strike": 340.0,
  "optionsType": "Call",
  "expireDate": 1792713600,
  "expireIsoDate": "2026-10-23T00:00:00Z",
  "openInterest": 5750,
  "underlyingSymbol": "AAPL",
  "regularMarketPrice": 7.0,
  "regularMarketChange": 0.0,
  "bid": 6.9,
  "ask": 7.1,
  "tradeable": false,
  "triggerable": false
}
```

## Pacote default por tipo

Sem `fields=`, cada classe recebe um pacote pré-definido distinto — **33 a 90 campos por item nas classes com preço** (o esqueleto NONE dos deslistados traz 11-13; contagem em `formatted=false`; uma a menos em `formatted=true` pela troca de `esgPopulated`; ±1 por campo condicional sem dado no momento — ver nota no bloco). A composição por tipo está no bloco 3; abaixo, as contagens observadas e o comportamento do lote:

```json5
{
  // ==========================================================================
  // 7 · PACOTE DEFAULT POR TIPO (fields ausente — contagens ao vivo 2026-10-18)
  // ==========================================================================
  // Contagens-BASE: ±1 campo por omissão de dados no momento da chamada — ex.:
  // quoteSourceName em OPTION oscilou entre 55 e 56 campos em chamadas seguidas
  // (mesma tolerância do [marketSummary](v6_finance_quote_marketSummary.md)).
  "defaultPackageSize": {
    "EQUITY": 90,          // o pacote mais completo (fundamentos + valuation + livro)
    "ETF": 80,             // herda quase tudo de EQUITY + bloco de fundo
    "CRYPTOCURRENCY": 70,  // bloco de cripto + marketCap, SEM livro/leilão
    "FUTURE": 66,          // bloco de contratos + sessão + livro
    "MUTUALFUND": 65,      // fundos SEM sessão intradiária e SEM livro
    "CURRENCY": 61,        // sessão + médias + 52w + livro
    "INDEX": 61,           // lista idêntica à de CURRENCY
    "OPTION": 56,          // derivativo SEM médias móveis e SEM tamanhos de livro
    "ALTSYMBOL": 56,       // alias de contrato — pacote de mercado sem NENHUM campo de identidade
    "MONEYMARKET": 33,     // o pacote mais enxuto com preço — núcleo + 5 campos
    "NONE": null,          // deslistados — esqueleto de 11-13 campos, SEM preço/nome/bolsa
    // formatted=true: contagem -1 (esgPopulated só existe com formatted=false)
  },

  // ==========================================================================
  // COMPORTAMENTO DO LOTE (validado ao vivo)
  // ==========================================================================
  "lote": {
    "classesMisturadas": true,     // as 11 classes observadas na MESMA chamada HTTP (9 com
                                   //   preço + ALTSYMBOL + NONE) — cada item com o pacote/
                                   //   quoteType da sua classe
    "ordem": "preservada",         // a ordem relativa dos símbolos resolvidos espelha a do
                                   //   pedido (pedidos: AAPL,SPY,BTC-USD,… → retorno idem)
    "caixa": "normalizada",        // símbolos minúsculos voltam em CAIXA ALTA (aapl → AAPL)
    "duplicatas": "replicadas",     // UMA entrada no result por ocorrência do symbols,
                                   //   agrupadas por símbolo (AAPL,AAPL,MSFT → AAPL,AAPL,MSFT)
                                   //   — EXCEÇÃO: CURRENCY deduplica para uma única entrada
                                   //   (EURUSD=X,EURUSD=X,EURUSD=X → 1 item; USDBRL=X×7 → 1;
                                   //   BTC-USD×2 e GC=F×2 replicam — validado out/2026);
                                   //   o cliente oficial deduplica ANTES de enviar
    "inexistentes": "omitidos",    // caem fora do result silenciosamente — o lote não falha
                                   //   (lote AAPL,INEXISTENTE9999XYZ,PETR4.SA → 2 itens, 200)
    "limiteServidor": null,        // NENHUM limite observado: 30/31/50/100/150/175 símbolos
                                   //   reais passam íntegros (175 pedidos → 173 itens = 2
                                   //   tickers inválidos da amostra caídos + duplicatas
                                   //   replicadas, não corte; revalidado out/2026 com 159
                                   //   distintos → 151 itens = 159 − 8 inválidos) · o 30 é
                                   //   disciplina do CLIENTE (batchSize, seção 4), não
                                   //   contrato do servidor
    "loteCliente": 30              // divisão em lotes de até 30 símbolos por requisição HTTP,
                                   //   paralelos, resultados mesclados — ver seção 8
  }
}
```

## Notas do cliente oficial

```json5
{
  // ==========================================================================
  // 8 · COMPORTAMENTO DO CLIENTE OFICIAL (5 chamadores no bundle)
  // ==========================================================================

  // — loadQuote (loadQuote.C6XUn82q.js): o carregador canônico usado pela página de
  //   cotações, comparador, painéis e âncoras do marketSummary —
  //   1. descarta símbolos com caracteres fora da classe symbolCharClass (seção 4)
  //   2. deduplica, converte para CAIXA ALTA e ORDENA os símbolos
  //   3. deduplica e ORDENA os fields; anexa SEMPRE os 5 campos base + o trio fullday
  //      (loaderBaseFields — seção 4; o trio vai ao fio mesmo sem enableExtendedHours,
  //      que só amplia a checagem de campos faltantes em itens cacheados)
  //   4. fatia em lotes de 30 (batchSize) e dispara em paralelo
  //   5. query: fields (CSV) · formatted=true INCONDICIONAL · imgLabels=logoUrl ·
  //      imgHeights=50 · imgWidths=50 · flags de sessão ativas · crumb via transporte
  //   6. mescla os resultados num dicionário indexado pelo symbol, preservando o
  //      que já existia no cache local de quotes (com force=false)
  "loadQuote": {
    "formatted": "true",
    "batchSize": 30,
    "sortSymbols": true,           // e caixa alta
    "sortFields": true,
    "fulldayTrioAlwaysOnWire": true,   // enableExtendedHours só afeta a checagem de cache
    "cacheHeaders": { "x-cache": "1", "x-cache-ttl": "30000" }
  },

  // — streamer.worker.js: o SEED do WebSocket de tempo real — só dispara com crumb na
  //   sessão; seleciona símbolos ainda sem exchangeTimezoneName no cache local; ordena;
  //   lotes de 30; XHR com withCredentials; debounce de 500 ms; a resposta alimenta o
  //   mesmo cache (handleQuoteRequest) que o streamer atualiza em tempo real depois
  "streamerSeed": {
    "requiresCrumb": true,
    "fields": "streamerSeedFields (30 — seção 4)",
    "batchSize": 30,
    "debounceMs": 500,
    "url": "streamerSeedUrlTemplate (seção 4) — com o & colado no ?",
    "formatted": "useFormattedSeeding ?? false"   // flag da sessão do streamer
  },

  // — portfólio e modal de cripto (função u dos dois módulos): construtor enxuto —
  //   host SORTEADO entre query1/query2 · formatted=true · crumb só se não-vazio ·
  //   lang/region da sessão com fallback · corsDomain=host da página · fields só se
  //   array · timeout 1500 ms · consome quoteResponse.result direto
  "widgets": {
    "hosts": "sorteio query1/query2",
    "fields": "portfolioFields (6) · cryptoTradeFields (5) — seção 4",
    "timeoutMs": 1500
  },

  // — gráfico (finChartRightRail): usa o VETOR ALTERNATIVO de crumb — header x-crumb
  //   em vez de query string; símbolos em caixa alta; fields conforme flag de sessão;
  //   sem formatted/lang/region na query
  "chartRightRail": { "crumbVector": "header x-crumb", "uppercase": true },

  // — âncoras do [marketSummary](v6_finance_quote_marketSummary.md) (loadMarketTime): os resgates de âncora daquele endpoint
  //   (BTC-USD, CL=F, TLT, ^STOXX50E, ^KS11, DOGE-USD, PL=F, HKD=X) vêm DAQUI:
  //   fields = shortName, longName, regularMarketPrice, regularMarketChange,
  //   regularMarketChangePercent + trio fullday + extras do chamador · formatted=true ·
  //   lang/region da sessão · erros não-críticos engolidos (catch → null)
  "marketSummaryAnchors": {
    "fields": ["shortName", "longName", "regularMarketPrice", "regularMarketChange",
               "regularMarketChangePercent", "+trio fullday", "+extras"],
    "criticalErrors": false
  },

  // — página de cotações (208._QKNXuHf.js): resolve os fields por quoteType/categoria
  //   (base de 34 — seção 4; CRYPTOCURRENCY/summary soma cmcRank), anexa condicionais
  //   (stockStory, quartrId, firstTradeDateMilliseconds) e injeta as flags de query
  //   topPickThisMonth (EQUITY) e checkUnusualOptionsActivity (options) — os campos
  //   stockPick*/hasUnusualOptionsActivity materializam no item como resposta
  "quoteSummaryPage": {
    "fields": "quoteSummaryBaseFields (34) + cmcRank em CRYPTO/summary",
    "condicionais": ["stockStory", "quartrId", "firstTradeDateMilliseconds"],
    "queryFlags": "quoteSummaryQueryFlags (seção 4)"
  }
}
```

**Contrato do carregador** — `loadQuote(ctx, { symbols, fields, silent, force, imgLabels, imgHeights, imgWidths, query, perfKey, cache })`; símbolos já presentes no cache local retornam do cache (com `force=false`) e só os fields faltantes são pedidos ao servidor — os 9 campos de `cachePresenceFields` (seção 4) são isentos dessa checagem e nunca disparam re-request; erro em qualquer lote reprojeta a promessa inteira (`Bad request for loadQuote` quando `symbols` ou `fields` vazios). Retorno: dicionário indexado pelo símbolo em caixa alta, com os itens do servidor mesclados sobre o cache.

## Limites e políticas de uso

| Aspecto | Comportamento |
| :--- | :--- |
| User-Agent | Obrigatório agente de navegador: `Python-urllib/3.x` e o `curl` default recebem `429 Edge: Too Many Requests` — bloqueio por assinatura de agente, não por volume (mesma política do [marketSummary](v6_finance_quote_marketSummary.md)). |
| Autenticação | Cookie `A3` + `crumb` **obrigatórios** (vetor query ou header `x-crumb`) — renováveis pelo handshake fc.yahoo.com → getcrumb; sessão expirada renovada pelo próprio transporte com 401 de gatilho. |
| Tamanho do lote | Nenhum limite observado no servidor (175 símbolos reais íntegros, URL de ~1,1 KB); o cliente oficial disciplina em lotes de 30 por requisição. |
| Projeção | `fields` com até ~5,5 KB de texto (500 entradas) → `200` (mesma tolerância do marketSummary). |
| Qualidade de dados | Símbolos inexistentes caem em silêncio (`result` sem o item, `error: null`); campos pedidos sem dado para a classe/item são omitidos — nunca rejeitados. |
