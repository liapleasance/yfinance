# `GET /v6/finance/quote/marketSummary`

> **Data de atualização:** 2026-10-20 · constantes deste endpoint validadas ao vivo contra `query1.finance.yahoo.com` (sessão regular de 2026-10-16, 12:43 ET · revalidação completa em pós-mercado de 2026-10-19, ~17:16–17:30 ET: suíte 20/20 + ~95 verificações adicionais).

---


Painel de cotações instantâneas do Yahoo Finance: alimenta o dock de cotações da página inicial e os cartões de mercado da página de mercados. Devolve **listas curadas de instrumentos macro** — índices, taxas, commodities, moedas fiduciárias e criptomoedas — nas quatro classes de saída `INDEX`, `FUTURE`, `CURRENCY` e `CRYPTOCURRENCY`, escolhidas pelo servidor conforme `market` e `region` (constantes na seção 4, composição na seção 7). A categoria de exibição **Rates** não tem classe própria: os Treasury yields viajam como `INDEX` (`apiQuoteTypeEquivalent: "INDEX"`, bloco 3 abaixo) cujo `regularMarketPrice` é a **taxa percentual anual** (`^TNX` 5.098 = 5,098% a.a.). Ações (`EQUITY`) e títulos (bonds) não têm classe de saída nem valor de `market` neste endpoint. Não consulta símbolos arbitrários (o parâmetro `symbols` é ignorado; para isso existe `GET /v7/finance/quote`) nem séries históricas (`chart` / `spark`).

| | |
| :--- | :--- |
| Método | `GET` — aceita também `HEAD` e `OPTIONS` (o `OPTIONS` responde `200` com `Allow: HEAD,GET,OPTIONS`); demais métodos → `405` |
| Hosts | `query1` · `query2` (`.finance.yahoo.com` — pool público com **sorteio por chamada** no transporte, `Math.random`) · `iquery` serve como host fixo de chamadas selecionadas (chaves internas); ambientes internos (`int*`) e `?chartStage=true` usam `iquery-stage` |
| Caminho | `/v6/finance/quote/marketSummary` |
| Autenticação | Anônima — responde `200` sem cookie e sem crumb; credenciais presentes são aceitas e ignoradas |
| User-Agent | Agente de navegador obrigatório — `curl`/`Python-urllib` e afins recebem `429 Edge: Too Many Requests` |
| Cache de borda | `public, max-age=1, stale-while-revalidate=9` — janela total de ~10 s por URL |
| Payload típico | ~6–7 KB (cartão projetado com a base do cliente) a ~27–41 KB (dock global em dump, conforme dados e modo de formatação) |

## Autenticação e User-Agent

A requisição é anônima: o servidor responde `200` sem cookie e sem crumb — credenciais presentes não são validadas. O cliente oficial envia mesmo assim o par Cookie (`A3`) + `crumb`, por fidelidade ao pipeline comum às APIs de dados; aqui, aceito e ignorado (a exigência só existe em endpoints irmãos que requerem sessão).

```bash
# 1. Capturar o Cookie A3 de sessão
curl -s -c cookies.txt "https://fc.yahoo.com" > /dev/null

# 2. Emitir o token Crumb casado com o cookie (fidelidade ao cliente oficial;
#    o endpoint também responde sem este passo)
CRUMB=$(curl -s -b cookies.txt "https://query1.finance.yahoo.com/v1/test/getcrumb")

# 3. Consultar
curl -s -b cookies.txt \
  -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/138.0.0.0" \
  "https://query1.finance.yahoo.com/v6/finance/quote/marketSummary?fields=shortName,regularMarketPrice,regularMarketChange,regularMarketChangePercent&formatted=true&lang=en-US&region=US&crumb=${CRUMB}"

# Chamada anônima equivalente (mesma resposta):
curl -s -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/138.0.0.0" \
  "https://query1.finance.yahoo.com/v6/finance/quote/marketSummary?formatted=true&lang=en-US&region=US"
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
    path: "/v6/finance/quote/marketSummary",
    params: {
      region: "US",                     // Região do usuário. Padrão: "US". 14 suportadas (lista em
                                        //   REGION, seção 4) — regionalizam o dock global; demais
                                        //   valores caem silenciosamente no dock "US" · case-insensitive
      lang: "en-US",                    // Locale de exibição. Padrão: "en-US" (também para valores não
                                        //   reconhecidos). 34 locales reconhecidos (lista em LANG,
                                        //   seção 4): localiza shortName/typeDisp e ecoa em "language"
                                        //   — nunca muda a seleção de símbolos · independe de "formatted"
      market: null,                     // (omitido/vazio) → dock global regionalizado pelo "region".
                                        //   Com valor: 11 cartões-país + 6 categorias + 3 agregados
                                        //   (listas na seção 4). Case-insensitive ("us" == "US").
                                        //   Qualquer outro valor (ex.: "ALL", "BR", "JP", "BONDS")
                                        //   → 400 "invalid broad market region"
      fields: "shortName,…",            // Projeção da resposta (regras e vocabulário completo na seção 5):
                                        //   AUSENTE → exatamente o núcleo da seção 2 (34 campos), sem bloco de
                                        //             variação do dia (DayHigh/Low/Range/Volume só sob pedido
                                        //             ou em dump) — menos omissões por tipo (currency só em
                                        //             CURRENCY; priceHint só em INDEX/CURRENCY; esgPopulated
                                        //             só com formatted=false) + extras de FUTURE (contractSymbol,
                                        //             headSymbolAsString; + headSymbol com formatted=true)
                                        //             → ~31–34 campos/item
                                        //   VAZIO ("fields=") → dump do vocabulário do tipo com dados
                                        //             (59–70 campos/item)
                                        //   LISTA CSV → núcleo + união dos campos pedidos que existirem
                                        //             no vocabulário do tipo; desconhecidos ignorados
      formatted: "true",                // "true" = valores de mercado como { raw, fmt } (default, mesmo
                                        //   omitido) · "false" = primitivos crus · metadados nunca são
                                        //   embrulhados nos dois modos (detalhes na seção 6)
      noIndicesToFutureSwap: false,     // false = fora do pregão troca índice spot pelo futuro correspondente
                                        //   (mapeamento completo em indicesToFutureSwap, seção 4)
                                        //   · true = mantém os índices spot fixos em qualquer configuração
      enableFtseStepStoneIndices: "true", // Opcional/condicional: injeta o índice FTSE StepStone US
                                        //   Private Equity no cartão "US" (7 → 8 itens) — ver
                                        //   ftseStepStoneIndices na seção 4
      crumb: "…",                       // Assinatura de sessão anexada pelo cliente — aceita e IGNORADA
                                        //   neste endpoint (não exige autenticação)
      // Ignorados silenciosamente: "symbols", "count", "corsDomain", ".tsrc" e chaves desconhecidas
    },
  },

  // ==========================================================================
  // 2 · CAMPOS COMUNS A TODOS OS ATIVOS (INDEX, FUTURE, CURRENCY, CRYPTO)
  // ==========================================================================
  "commonFields": [
    // Núcleo sempre-presente no default (fields ausente) — comum aos 4 tipos de saída.
    // Vocabulário completo (84 campos, grupos compartilhados e exclusivos por tipo) na seção 5.
    "symbol",                     // Ticker oficial do ativo (ex: '^GSPC', 'ES=F', 'BRL=X', 'BTC-USD')
    "shortName",                  // Nome curto de exibição (ex: 'S&P 500', 'EUR/USD'); localizado por lang
    "longName",                   // Nome completo/oficial da empresa, par ou índice (nulo na maioria dos FUTURE)
    "quoteType",                  // Tipo do ativo ('INDEX', 'FUTURE', 'CURRENCY', 'CRYPTOCURRENCY')
    "typeDisp",                   // Classe formatada e localizada por lang ('Index', 'Futures', 'Índice')
    "market",                     // Identificador interno ('us_market', 'us24_market', 'ccy_market',
                                  //   'ccc_market', 'usir_market', '<país>_market')
    "region",                     // Eco do region do pedido (ex: 'US', 'BR')
    "language",                   // Eco do lang do pedido (pode vir normalizado — ver LANG, seção 4)
    "exchange",                   // Sigla da bolsa ou provedor (ex: 'SNP', 'CME', 'CCY', 'CCC', 'CGI')
    "fullExchangeName",           // Nome completo por extenso da bolsa de valores
    "regularMarketPrice",         // Preço atual ou valor do último fechamento registrado
    "regularMarketChange",        // Variação absoluta de preço em relação à sessão anterior
    "regularMarketChangePercent", // Variação percentual diária (+/- %)
    "regularMarketPreviousClose", // Preço de fechamento da sessão imediatamente anterior
    "fulldayPrice",               // Preço consolidado do dia inteiro (pregão regular + estendido)
    "fulldayChange",              // Variação absoluta do dia inteiro (omissa quando nula)
    "fulldayChangePercent",       // Variação percentual do dia inteiro (regular + estendido)
    "regularMarketTime",          // Timestamp Epoch (em segundos) do último negócio realizado
    "marketState",                // Fase da sessão ('PREPRE', 'PRE', 'REGULAR', 'POST', 'POSTPOST', 'CLOSED')
    "exchangeTimezoneName",       // Fuso horário IANA da bolsa (ex: 'America/New_York', 'America/Chicago')
    "exchangeTimezoneShortName",  // Sigla do fuso horário local (ex: 'EDT', 'EST', 'BRT', 'CDT')
    "gmtOffSetMilliseconds",      // Deslocamento em milissegundos em relação ao meridiano UTC/GMT
    "firstTradeDateMilliseconds", // Início de negociação (Epoch ms; negativo para datas pré-1970)
    "sourceInterval",             // Intervalo da fonte em minutos (ex: 10, 15)
    "exchangeDataDelayedBy",      // Tempo de atraso da cotação em minutos (0 = tempo real, 10/15 = delayed)
    "customPriceAlertConfidence", // Confiança para alertas de preço ('LOW', 'NONE')
    "tradeable",                  // Booleano: indica se o ativo permite execução de ordens via parceiros
    "triggerable",                // Booleano: indica se o ativo aceita alertas de preço e notificações
    "cryptoTradeable",            // Booleano: criptoativo negociável na plataforma
    "hasPrePostMarketData",       // Booleano: pré/pós-mercado disponível para o ativo
    "quoteSourceName",            // Fonte da cotação ('Delayed Quote', 'Free Realtime Quote') — entra
                                  //   no default quando há dado
    "priceHint",                  // Casas decimais sugeridas — entra no default em INDEX/CURRENCY
    "currency",                   // Moeda da cotação — entra no default em CURRENCY (sob pedido, sai nos 4)
    "esgPopulated"                // Booleano: dados ESG populados — entra no default só com formatted=false
  ],

  // ==========================================================================
  // 3 · ATIVOS E SEUS CAMPOS ESPECÍFICOS (POR ID)
  // ==========================================================================
  "assetTypes": [
    {
      "id": "INDEX",
      "market": "us_market",
      "tickerFormat": "diversificado (ex: ^GSPC, ^DJI, ^IXIC, ^BVSP, 000001.SS, DX-Y.NYB, FTSEMIB.MI, ^125904-USD-STRD, FPACEBOUS-USD-TR.FGI)",
      "fields": [
        "displayName",                // Nome de exibição alternativo (EXCLUSIVO de INDEX; ex: ^TNX
                                      //   materializa 'CBOE Interest Rate 10 Year T')
        "regularMarketDayHigh",       // Cotação máxima atingida pelo índice durante a sessão
        "regularMarketDayLow",        // Cotação mínima atingida pelo índice durante a sessão
        "regularMarketDayRange",      // Faixa de oscilação do dia ('mínima - máxima')
        "regularMarketVolume"         // Volume somado de ações negociadas que compõem o índice
                                      // Compartilhados aceitos: regularMarketOpen · bid/ask/bidSize/
                                      // askSize (inexistem em CRYPTOCURRENCY) · fiftyTwoWeek* ·
                                      // médias 50d/200d · messageBoardId · uuid (sob pedido explícito)
      ]
    },

    {
      "id": "FUTURE",
      "market": "us24_market",
      "tickerFormat": "[A-Z]+=F (ex: ES=F, NQ=F, CL=F, GC=F)",
      "fields": [
        "headSymbol",                 // Booleano: item é a cabeça da cadeia de contratos — entra no
                                      //   default só com formatted=true (par trocado com esgPopulated)
        "headSymbolAsString",         // Cabeça da cadeia como string (default de FUTURE; ex: 'ES=F')
        "contractSymbol",             // Booleano: confirma se o ticker é um contrato individual ativo —
                                      //   presente no default de FUTURE (e no núcleo do modo lista)
        "underlyingSymbol",           // Ticker do ativo subjacente atrelado (ex: 'ZTZ26.CBT' para ZT=F) —
                                      //   entra no núcleo do modo lista csv
        "underlyingExchangeSymbol",   // Bolsa do ativo-objeto do futuro
        "expireDate",                 // Timestamp Epoch (segundos) da data de vencimento do contrato
        "expireIsoDate",              // Vencimento do contrato em ISO 8601
        "openInterest",               // Total de contratos em aberto ainda não liquidados no mercado
        "regularMarketDayHigh",       // Preço máximo negociado do contrato na sessão
        "regularMarketDayLow",        // Preço mínimo negociado do contrato na sessão
        "regularMarketDayRange",      // Faixa diária de negociação ('mínima - máxima')
        "regularMarketVolume"         // Quantidade total de contratos futuros negociados na sessão
      ]
    },

    {
      "id": "CURRENCY",
      "market": "ccy_market",          // Identificador real no fio (não 'currencies_market')
      "tickerFormat": "[A-Z]{6}=X (ex: EURUSD=X, USDBRL=X, GBPUSD=X)",
      "fields": [                      // Sem campos EXCLUSIVOS — tudo abaixo é compartilhado
                                       //   (bid/ask/bidSize/askSize também existem em INDEX/FUTURE)
        "currency",                   // Moeda na qual o valor está expresso (ex: 'USD', 'BRL') — o
                                       //   único campo de moeda do grupo: fromCurrency/toCurrency são
                                       //   EXCLUSIVOS de CRYPTOCURRENCY e NÃO materializam aqui nem
                                       //   sob pedido explícito (validado ao vivo) · presente no default
                                       //   de CURRENCY e no seu núcleo csv; sob pedido materializa nos
                                       //   4 tipos
        "bid",                        // Melhor preço de oferta de compra no mercado interbancário
        "ask",                        // Melhor preço de oferta de venda no mercado interbancário
        "bidSize",                    // Quantidade de ordens/tamanho do lote no bid
        "askSize",                    // Quantidade de ordens/tamanho do lote no ask
        "regularMarketOpen",          // Taxa de abertura da sessão cambial
        "regularMarketDayHigh",       // Taxa cambial máxima atingida na sessão
        "regularMarketDayLow",        // Taxa cambial mínima atingida na sessão
        "regularMarketDayRange",      // Amplitude cambial da sessão ('mínima - máxima')
        "fiftyTwoWeekHigh",           // Cotação mais alta registrada nas últimas 52 semanas
        "fiftyTwoWeekLow",            // Cotação mais baixa registrada nas últimas 52 semanas
        "fiftyTwoWeekRange",          // Faixa de variação anual ('mínima - máxima')
        "fiftyTwoWeekChangePercent"   // Variação percentual acumulada em 1 ano (52 semanas)
      ]
    },

    {
      "id": "CRYPTOCURRENCY",
      "market": "ccc_market",
      "tickerFormat": "[A-Z0-9]+-[A-Z]+ (ex: BTC-USD, ETH-USD, SOL-USD)",
      "fields": [
        "fromCurrency",               // Código do criptoativo base (ex: 'BTC', 'ETH')
        "toCurrency",                 // Moeda de cotação do par, com sufixo '=X' (ex: 'USD=X' em BTC-USD)
        "currency",                   // Unidade monetária do valor exibido (ex: 'USD')
        "circulatingSupply",          // Quantidade de moedas/tokens em circulação no mercado
        "totalSupply",                // Oferta total de moedas/tokens
        "maxSupply",                  // Oferta máxima (ex: 21000000 para BTC)
        "marketCap",                  // Capitalização total de mercado (regularMarketPrice * circulatingSupply)
        "volume24Hr",                 // Volume financeiro movimentado nas últimas 24 horas
        "volumeAllCurrencies",        // Volume consolidado global convertendo todas as exchanges
        "lastMarket",                 // Mercado da última cotação (ex: 'Coinbase')
        "coinImageUrl",               // Ícone da moeda (CoinMarketCap) — vem junto dos campos de cripto
        "coinMarketCapLink",          // Página da moeda no CoinMarketCap
        "logoUrl",                    // Logotipo do ativo
        "regularMarketDayHigh",       // Preço máximo nas últimas 24 horas
        "regularMarketDayLow",        // Preço mínimo nas últimas 24 horas
        "regularMarketDayRange",      // Faixa de preço de 24 horas ('mínima - máxima')
        "startDate"                   // Timestamp Epoch da data de criação ou listagem da moeda
      ]
    },

    // ------------------------------------------------------------------------
    // CATEGORIA RATES / TREASURY YIELDS (taxas de juros e títulos)
    // ------------------------------------------------------------------------

    {
      "id": "RATES",

      // Detalhe de API: na resposta bruta do Yahoo, o campo 'quoteType' vem como 'INDEX'
      "apiQuoteTypeEquivalent": "INDEX",

      "market": "usir_market",          // US Index Rates — identificador real dos Treasury Yields na saída
                                        //   (os futuros de juros ZT=F/ZN=F deste mesmo grupo vêm com 'us24_market')

      // Exemplos reais do Yahoo Finance para taxas
      "tickerExamples": [
        "^IRX",   // 13-Week Treasury Bill (taxa de 13 semanas)
        "^FVX",   // 5-Year Treasury Note (taxa de 5 anos)
        "^TNX",   // 10-Year Treasury Note (taxa referência de 10 anos)
        "^TYX"    // 30-Year Treasury Bond (taxa de 30 anos)
      ],

      "fields": [
        // ---------------------------------------------------------------------
        // Campos Universais (com o significado adaptado para TAXAS)
        // ---------------------------------------------------------------------
        "symbol",                     // Ticker da taxa (ex: '^TNX', '^TYX')
        "shortName",                  // Nome abreviado do título (ex: '10-Yr Bond', '30-Yr Bond')
        "longName",                   // Nome completo da taxa (ex: 'Treasury Yield 10 Years',
                                      //   'CBOE Interest Rate 10 Year T Note')
        "quoteType",                  // Valor retornado pela API: sempre 'INDEX'
        "market",                     // Mercado: 'usir_market' (US Index Rates)
        "marketState",                // Fase da sessão ('PREPRE', 'PRE', 'REGULAR', 'POST', 'POSTPOST', 'CLOSED')
        "region",                     // Região de emissão ('US')
        "exchange",                   // Código da bolsa registradora ('CGI')
        "fullExchangeName",           // Nome por extenso da bolsa/índice ('Cboe Indices')
        "exchangeTimezoneName",       // Fuso horário IANA ('America/Chicago')
        "exchangeTimezoneShortName",  // Sigla do fuso ('CDT' / 'CST')
        "gmtOffSetMilliseconds",      // Deslocamento UTC em milissegundos (-18000000 para CDT)
        "exchangeDataDelayedBy",      // Atraso da taxa em minutos (15 — cotação delayed da Cboe)

        // ---------------------------------------------------------------------
        // Campos Numéricos de Cotação de Taxas
        // (Atenção: nestes campos, o número representa a taxa percentual de Yield em %)
        // ---------------------------------------------------------------------
        "regularMarketPrice",         // Taxa de juros anual atual em % (ex: 4.07 = 4,07% ao ano)
        "regularMarketChange",        // Variação absoluta da taxa em pontos percentuais (ex: +0.009)
        "regularMarketChangePercent", // Variação percentual sobre a taxa do dia anterior
        "regularMarketTime",          // Timestamp Epoch (em segundos) do último ajuste da taxa
        "regularMarketPreviousClose", // Taxa de fechamento do dia anterior (yield do dia anterior)
        "regularMarketDayHigh",       // Maior taxa de juros atingida durante a sessão
        "regularMarketDayLow",        // Menor taxa de juros atingida durante a sessão
        "regularMarketDayRange",      // Amplitude da taxa no dia ('mínima - máxima')

        // ---------------------------------------------------------------------
        // Campos Particulares de Títulos/Taxas
        // ---------------------------------------------------------------------
        "priceHint",                  // Precisão decimal: 4 casas em ^IRX/^FVX, 2 em ^TNX/^TYX
        "displayName",                // Materializado em ^TNX ('CBOE Interest Rate 10 Year T')
        "firstTradeDateMilliseconds", // Data de início histórico do registro do rendimento
                                      //   (pode ser anterior a 1970 — timestamps negativos)
        "tradeable",                  // Quase sempre false (não se compra o índice da taxa diretamente)
        "triggerable"                 // Booleano: permite alertas caso a taxa cruze um patamar (ex: bater 4,5%)
      ]
    }
  ]
}
```

## Constantes padrão

Valores nativos do código fonte (loader, transporte e componentes — extraídos do bundle e conferidos linha a linha) e, à parte, os **enums do servidor** aceitos nos parâmetros `market`/`region`/`lang`, que não existem como constantes no cliente e foram mapeados por validação ao vivo (20 valores de `market`, 14 de `region`, 34 de `lang`, confirmados um a um contra a API):

```json5
{
  // ==========================================================================
  // 4 · CONSTANTES PADRÃO DO ENDPOINT (valores nativos do código fonte)
  // ==========================================================================

  // Hosts do transporte de dados (chartStatic.Bl5ArXnz.js, função Fl): pool público query1+query2 com
  // SORTEIO por chamada (Math.random — não há "host padrão"; o streamer de tempo real é o
  // único chamador que hardcoda query1) · iquery.finance.yahoo.com é o host FIXO de chamadas
  // selecionadas (chave financeInternal no config das páginas) · iquery-stage serve
  // ambientes internos: subdomínio int*.finance.yahoo.com ou ?chartStage=true
  "hosts": {
    "poolPublico": [
      "https://query1.finance.yahoo.com",
      "https://query2.finance.yahoo.com"
    ],
    "hostFixo": "https://iquery.finance.yahoo.com",
    "stage": "https://iquery-stage.finance.yahoo.com"
  },

  // Campos padrão do loader loadMarketTime → valor do parâmetro "fields" (a projeção no fio
  // é sempre a BASE + o trio fullday — EXTENDED_HOURS_FIELD_MAP de support_agent.Cd9DzWFk.js,
  // reexportado como F por loadQuote.C6XUn82q.js; mesmo mapa de extendedHoursMapping, seção 8
  // — + os extras do chamador)
  "loadMarketTime": {
    "BASE": [
      "shortName",                    // Nome curto de exibição do ativo
      "regularMarketPrice",           // Último preço da sessão regular
      "regularMarketChange",          // Variação absoluta vs fechamento anterior
      "regularMarketChangePercent"    // Variação percentual vs fechamento anterior
    ],
    "FULLDAY": [
      // herda todos os campos de "BASE" e adiciona:
      "fulldayPrice",                 // Preço consolidado do dia inteiro (pregão regular + estendido)
      "fulldayChange",                // Variação absoluta do dia inteiro (regular + estendido)
      "fulldayChangePercent"          // Variação percentual do dia inteiro (regular + estendido)
    ]
  },

  // Valores aceitos pelo parâmetro "market" — 11 países + 6 categorias + 3 agregados.
  // ENUM DO SERVIDOR (mapeado por validação ao vivo; os agregados *_ALL também aparecem
  // como constantes do cliente na página de mercados). Case-insensitive ("us" == "US").
  // Qualquer outro valor (ex.: "ALL", "BR", "JP", "BONDS") → 400 "invalid broad market region".
  "marketCountries": [              // 11 cartões por país (6 itens cada)
    "US", "GB", "HK", "DE", "FR", "AU", "CA", "IT", "ES", "SG", "NZ"
  ],
  "marketCategories": [             // 6 cartões temáticos
    "EUROPE",                       // Europa
    "ASIA",                         // Ásia
    "CRYPTOCURRENCIES",             // Criptomoedas
    "RATES",                        // Juros do Tesouro americano: ^IRX (13 sem.) · ^FVX (5 a.) ·
                                    //   ^TNX (10 a.) · ^TYX (30 a.) + futuros ZT=F (2 a.) · ZN=F (10 a.)
                                    //   Títulos não têm cartão próprio: a seção «US Treasury Bonds» da
                                    //   página de mercados é este cartão RATES; a página de categoria
                                    //   bonds é servida por outro serviço (POST /v1/finance/visualization)
    "COMMODITIES",                  // Commodities
    "CURRENCIES"                    // Moedas
  ],
  "marketAggregates": [             // 3 agregados regionais (8 itens cada)
    "AMERICA_ALL",                  // Américas
    "EUROPE_ALL",                   // Europa ampliada
    "ASIA_ALL"                      // Ásia ampliada
  ],

  // "GLOBAL" = ausência (ou vazio) do parâmetro "market" no fio → dock global da home
  // (15 itens de dia; 16 na janela noturna com ^VIX — ver indicesToFutureSwap abaixo)
  "marketOmitted": "GLOBAL",

  // Valores aceitos pelo parâmetro "region" — ENUM DO SERVIDOR (validado ao vivo):
  // regionalizam o dock global (composição na seção 7); demais valores (JP, MX, KR, TW, XX…)
  //   caem silenciosamente no dock "US" · case-insensitive
  "region": {
    "DEFAULT": "US",
    "SUPPORTED": [
      "US", "BR", "HK", "CA", "SG", "ES", "IN", "GB", "CN", "FR", "IT", "AU", "DE", "NZ"
    ]
  },

  // Valores reconhecidos pelo parâmetro "lang" — ENUM DO SERVIDOR (validado ao vivo):
  // localizam shortName/typeDisp e ecoam em "language"; não reconhecidos (ex.: nl-NL, id-ID, pl-PL, ro-RO, cs-CZ, uk-UA, hu-HU, bg-BG
  // e valores livres) caem silenciosamente no default. Eco normalizado: pt → pt-BR ·
  // zh-CN/zh-HK/zh-SG → zh-Hant-HK · ar-EG/ar-SA → ar-QA. NUNCA muda a seleção de símbolos.
  "lang": {
    "DEFAULT": "en-US",
    "RECOGNIZED": [
      "en-US", "en-GB", "en-AU", "en-CA", "en-IN",
      "pt-BR", "pt-PT", "es-ES", "es-MX", "fr-FR", "fr-CA",
      "de-DE", "it-IT", "tr-TR", "ru-RU", "th-TH", "vi-VN", "he-IL",
      "sv-SE", "da-DK", "fi-FI", "nb-NO", "ms-MY", "hi-IN",
      "el-GR", "ko-KR", "ja-JP", "zh-Hant-TW",
      "pt", "zh-CN", "zh-HK", "zh-SG", "ar-EG", "ar-SA"
    ],
    // Exemplos observados: pt-BR -> "S&P500", "DOW JONES", typeDisp "Índice"/"Futuros";
    //   ja-JP -> "指数"/"先物"; zh-Hant -> "標普 500"/"指數"/"期貨";
    //   fr-FR -> "Indice"/"Contrats à terme"; de-DE/sv-SE/hi-IN -> mantêm "Index"/"Futures"
    //   Quirk observado: "ptbr" (sem hífen) também é reconhecido como pt-BR — normalização
    //   fuzzy do edge; valores como "xx-XX" caem no default.
  },

  // Troca de índices por futuros fora do pregão (os futuros CME, de sessão quase contínua,
  // refletem o movimento ao vivo enquanto os índices de caixa estão parados):
  "indicesToFutureSwap": {
    "^GSPC": "ES=F",                // S&P 500      → E-Mini S&P 500
    "^DJI":  "YM=F",                // Dow 30       → E-Mini Dow
    "^IXIC": "NQ=F",                // Nasdaq       → E-Mini Nasdaq
    "^RUT":  "RTY=F",               // Russell 2000 → E-Mini Russell
    // Gatilhos: região ≠ US fora da sessão regular · janela noturna (após POSTPOST, ~20:00 ET)
    //   troca também com region=US · durante REGULAR não há troca · noIndicesToFutureSwap=true
    //   desativa em qualquer configuração · docks regionais e cartões de outros países não
    //   trocam · a cauda fixa do cartão US (^TNX ^VIX GC=F) não é afetada
  },

  // Âncoras de resgate do cliente oficial — buscadas no GET /v7/finance/quote (fora de
  // smartphone/webview, só com "market" definido) e mescladas ao resultado quando ausentes
  // do cartão. "TLT" é um ETF (EQUITY): a interface pode exibir classes fora das 4 da saída.
  "anchors": {
    "US": ["BTC-USD", "CL=F"],
    "EUROPE": ["^STOXX50E"],
    "ASIA": ["^KS11"],
    "CRYPTOCURRENCIES": ["DOGE-USD"],
    "RATES": ["TLT"],
    "COMMODITIES": ["PL=F"],
    "CURRENCIES": ["HKD=X"]
  },

  // Cache local do cliente: chave "market || ALL", TTL 30 s (chamadas com cabeçalhos
  // x-cache: 1 · x-cache-ttl: 30000 quando a flag de sessão está ligada)
  "clientLocalCache": { "key": "market || ALL", "ttlMs": 30000 },

  // Índices de Private Equity FTSE StepStone — o endpoint expõe SOMENTE o US Private Equity,
  // injetado por enableFtseStepStoneIndices=true no cartão "US" (7 → 8 itens); sem a flag,
  // nenhum item .FGI aparece em variante alguma; nos demais cartões a flag não tem efeito
  // observado, e os demais contratos StepStone não são expostos por este endpoint
  "ftseStepStoneIndices": {
    "FPACEBOUS-USD-TR.FGI": "US Private Equity",
    "FPCPEXVM-USD-TR.FGI": "European Private Equity",
    "FPCPEXVA-USD-TR.FGI": "APAC Private Equity",
    "FPACEPE-USD-TR.FGI": "Global Private Equity"
  }
}
```

## Vocabulário de fields

Vocabulário completo aceito pelo parâmetro `fields` — 84 campos conhecidos, projetados por adição ao núcleo da seção 2. Três modos: **ausente** → o núcleo da seção 2 puro, sem bloco de variação do dia (DayHigh/Low/Range/Volume só vêm sob pedido, como satélites, ou no dump) — ~31–34 campos/item conforme tipo e modo; **vazio** (`fields=`) → dump do vocabulário do tipo com dados (59–70 campos/item); **lista csv** → núcleo reduzido (26–30 campos por tipo: caem longName, regularMarketChange, regularMarketChangePercent, regularMarketPreviousClose, fulldayChange e fulldayChangePercent — em CURRENCY os dois *ChangePercent permanecem — e FUTURE ganha contractSymbol, headSymbolAsString e underlyingSymbol) + união dos campos pedidos que existirem no vocabulário do tipo (desconhecidos ignorados).

```json5
{
  // ==========================================================================
  // 5 · VOCABULÁRIO DE FIELDS — grupos compartilhados e exclusivos por tipo
  // ==========================================================================
  // Par trocado por modo de formatação: "headSymbol" só materializa com formatted=true ·
  //   "esgPopulated" só com formatted=false (nos defaults e nos dumps).
  // Campos satélites (família High ↔ família Low, MESMO lado — observado estável em
  //   dados saudáveis, 8 ativos × 4 tipos, out/2026):
  //   • pedir qualquer membro de {fiftyTwoWeekHigh, fiftyTwoWeekHighChange,
  //     fiftyTwoWeekHighChangePercent} traz os outros dois + regularMarketDayHigh
  //     (+ priceHint em FUTURE/CRYPTOCURRENCY, onde ele não é núcleo); a família
  //     {fiftyTwoWeekLow, …LowChange, …LowChangePercent} espelha com regularMarketDayLow;
  //   • regularMarketDayHigh/Low puxam a família 52w do mesmo lado;
  //   • fiftyTwoWeekRange puxa as duas famílias + Day{High,Low,Range} + priceHint;
  //     regularMarketDayRange puxa as duas famílias + fiftyTwoWeekRange + Day{High,Low};
  //   • "marketCap" puxa "currency"; "logoUrl" ↔ "coinImageUrl" formam um par
  //     bidirecional — coinImageUrl NÃO acompanha os demais campos de cripto;
  //   • fiftyTwoWeekChangePercent e os demais campos não têm satélites;
  //   • fallback de dado quebrado: com o lado pedido nulo/stalado, o complementar
  //     materializa no lugar (observado em EURUSD=X, out/2026: 52wHigh pedido volta
  //     null e o lado Low vem com valores de snapshot antigo).

  // Demais campos comuns aos 4 tipos (além do núcleo da seção 2) — sob demanda:
  "sharedByAllTypes": [
    "regularMarketOpen",                 // abertura do dia
    "regularMarketDayHigh",              // máxima do dia
    "regularMarketDayLow",               // mínima do dia
    "regularMarketDayRange",             // faixa do dia ('mínima - máxima')
    "regularMarketVolume",               // volume do dia
    "fiftyDayAverage",                   // média móvel de 50 dias
    "fiftyDayAverageChange",             // distância absoluta até a MM50
    "fiftyDayAverageChangePercent",      // distância percentual até a MM50
    "twoHundredDayAverage",              // média móvel de 200 dias
    "twoHundredDayAverageChange",        // distância absoluta até a MM200
    "twoHundredDayAverageChangePercent", // distância percentual até a MM200
    "fiftyTwoWeekHigh",                  // máxima de 52 semanas
    "fiftyTwoWeekLow",                   // mínima de 52 semanas (satélite de fiftyTwoWeekHigh)
    "fiftyTwoWeekHighChange",            // distância absoluta até a máxima
    "fiftyTwoWeekHighChangePercent",     // distância percentual até a máxima
    "fiftyTwoWeekLowChange",             // distância absoluta até a mínima
    "fiftyTwoWeekLowChangePercent",      // distância percentual até a mínima
    "fiftyTwoWeekChangePercent",         // variação acumulada em 52 semanas
    "fiftyTwoWeekRange",                 // faixa de 52 semanas ('mínima - máxima')
    "averageDailyVolume10Day",           // volume médio diário (10 dias)
    "averageDailyVolume3Month",          // volume médio diário (3 meses)
    "corporateActions",                  // ação corporativa pendente
    "uuid"                               // identificador universal — SÓ sob pedido explícito
  ],

  // Aceitos por 3 dos 4 tipos:
  "withoutCryptocurrency": [             // INDEX, FUTURE, CURRENCY (inexistem em CRYPTOCURRENCY)
    "bid",                               // melhor oferta de compra
    "ask",                               // melhor oferta de venda
    "bidSize",                           // quantidade no lado da compra (0 ou omisso quando nulo)
    "askSize"                            // quantidade no lado da venda (0 ou omisso quando nulo)
  ],
  "withoutFuture": [                     // INDEX, CURRENCY, CRYPTOCURRENCY (inexiste em FUTURE)
    "messageBoardId"                     // id do fórum do ativo
  ],

  // Exclusivos de cada tipo (somam-se aos conjuntos acima):
  "exclusiveByType": {
    "INDEX": [
      "displayName"                      // nome de exibição alternativo (ex: ^TNX →
                                         //   'CBOE Interest Rate 10 Year T')
    ],
    "FUTURE": [
      "headSymbol",                      // bool: item é a cabeça da cadeia de contratos
      "headSymbolAsString",              // cabeça da cadeia como string (ex: 'ES=F')
      "contractSymbol",                  // item é contrato individual de futuro (bool)
      "underlyingSymbol",                // ativo-objeto do contrato (ex: 'ZTZ26.CBT')
      "underlyingExchangeSymbol",        // bolsa do ativo-objeto
      "expireDate",                      // vencimento do contrato (epoch segundos)
      "expireIsoDate",                   // vencimento em ISO 8601
      "openInterest"                     // interesse aberto do contrato
    ],
    "CURRENCY": [],                      // sem exclusivos — apenas os conjuntos comuns
    "CRYPTOCURRENCY": [
      "circulatingSupply",               // moedas em circulação
      "totalSupply",                     // oferta total
      "maxSupply",                       // oferta máxima (ex: 21000000 para BTC)
      "volume24Hr",                      // volume em 24 horas
      "volumeAllCurrencies",             // volume somado em todas as moedas
      "coinImageUrl",                    // ícone da moeda (CoinMarketCap)
      "coinMarketCapLink",               // página da moeda no CoinMarketCap
      "fromCurrency",                    // moeda de origem do par (ex: 'BTC')
      "toCurrency",                      // moeda de destino do par, com sufixo '=X' (ex: 'USD=X')
      "lastMarket",                      // mercado da última cotação (ex: 'Coinbase')
      "logoUrl",                         // logotipo do ativo
      "marketCap",                       // valor de mercado
      "startDate"                        // data de criação (epoch)
    ]
  },

  // Composição e totais do vocabulário por tipo:
  //   INDEX          = comum + withoutCryptocurrency + withoutFuture + exclusive.INDEX  → 63
  //   FUTURE         = comum + withoutCryptocurrency + exclusive.FUTURE                 → 69
  //   CURRENCY       = comum + withoutCryptocurrency + withoutFuture                    → 62
  //   CRYPTOCURRENCY = comum + withoutFuture + exclusive.CRYPTOCURRENCY                 → 71
  //   União total    = 84 campos conhecidos = 36 (default, união dos tipos) + 48 (sob demanda)
  // Notas:
  //   preMarket*/postMarket* NÃO existem no vocabulário — o pós-mercado aparece só como
  //   marketState/hasPrePostMarketData · spark/sparkline não são campos deste endpoint
  //   (a mini-curva da interface vem de GET /v7/finance/spark)
}
```

## Resposta e erros

Envelope de sucesso, envelope de erro e regras de formatação dos valores:

```json5
{
  // ==========================================================================
  // 6 · ENVELOPE DA RESPOSTA
  // ==========================================================================
  "sucesso": {
    "marketSummaryResponse": {
      "result": [ "/* array de itens de cotação — vocabulário na seção 5 */" ],
      "marketCategoryLongName": "US",   // Nome longo da categoria do cartão (eco do market:
                                        //   'US', 'UK', 'Hong Kong', 'Singapore', 'EUROPE'…)
                                        //   · null no dock global (sem "market")
      "error": null
    }
  },

  "erro": {
    "finance": {
      "result": null,
      "error": {
        "code": "Bad Request",
        "description": "invalid broad market region"
      }
    }
  },

  // Regras de formatação dos valores:
  "formattedTrue": {
    "regularMarketPrice": { "raw": 7744.06, "fmt": "7,744.06" },
    "marketCap": { "raw": 1654360768512, "fmt": "1.654T", "longFmt": "1,654,360,768,512" }
    // campos de grande magnitude somam "longFmt"
  },
  "formattedFalse": {
    "regularMarketPrice": 7744.06       // primitivos crus
  },
  "metadados": "cru nos DOIS modos",    // strings (symbol, marketState…), inteiros (priceHint,
                                        //   gmtOffSetMilliseconds, sourceInterval) e booleanos seguem
                                        //   crus nos dois modos — o envelope {raw, fmt} aplica-se
                                        //   apenas aos valores de mercado
}
```

| HTTP | Quando | Corpo |
| :---: | :--- | :--- |
| `400` | `market` inválido | `Bad Request` · `invalid broad market region` |
| `405` | método não permitido | `Method Not Allowed` · `HTTP 405 Method Not Allowed` |
| `429` | User-Agent bloqueado | `Edge: Too Many Requests` (texto puro) |

Exemplo de item (`formatted=true`, recortado):

```json
{
  "symbol": "^GSPC",
  "shortName": "S&P 500",
  "longName": "S&P 500",
  "exchange": "SNP",
  "fullExchangeName": "SNP",
  "quoteType": "INDEX",
  "typeDisp": "Index",
  "market": "us_market",
  "region": "US",
  "language": "en-US",
  "marketState": "REGULAR",
  "regularMarketPrice": { "raw": 7744.06, "fmt": "7,744.06" },
  "regularMarketChange": { "raw": 25.120117, "fmt": "25.12" },
  "regularMarketChangePercent": { "raw": 0.3254348, "fmt": "0.33%" },
  "regularMarketPreviousClose": { "raw": 7718.94, "fmt": "7,718.94" },
  "regularMarketTime": { "raw": 1792096433, "fmt": "4:33PM EDT" },
  "exchangeTimezoneName": "America/New_York",
  "exchangeTimezoneShortName": "EDT",
  "priceHint": 2,
  "quoteSourceName": "Delayed Quote"
}
```

O mesmo item com `formatted=false`:

```json
{
  "symbol": "^GSPC",
  "shortName": "S&P 500",
  "regularMarketPrice": 7744.06,
  "regularMarketChange": 25.120117,
  "regularMarketChangePercent": 0.3254348,
  "regularMarketTime": 1792096433,
  "marketState": "REGULAR"
}
```

## Composição dos cartões

Curadoria do servidor, com a ordem preservada (a composição do dock global é dinâmica e varia entre observações — contagens de 5 a 16 itens por região observadas em out/2026, com US/BR estáveis nas revalidações; os cartões temáticos, agregados e por país são estáveis):

```json5
{
  // ==========================================================================
  // 7 · COMPOSIÇÃO POR market E region (símbolos na ordem do servidor)
  // ==========================================================================

  // Dock global (sem "market") — regionalizado pelo "region":
  "dockGlobal": {
    "US (padrão)": "^GSPC ^DJI ^IXIC ^RUT CL=F GC=F SI=F EURUSD=X ^TNX GBPUSD=X JPY=X BTC-USD XRP-USD ^FTSE ^N225",
    "BR": "^BVSP ^MERV ^MXX CL=F GC=F BTC-USD XRP-USD ^GSPC ^DJI ^FTSE ^HSI ^N225 NQ=F ^BATSK EURBRL=X",
    "HK": "^HSI ^HSCE 000001.SS 000300.SS HKD=X HKDCNY=X ^DJI ^GSPC ^IXIC JPYHKD=X EURHKD=X GBPHKD=X CL=F GC=F BTC-USD XRP-USD",
    "CA": "^GSPTSE ^GSPC ^DJI CADUSD=X CL=F BTC-CAD XRP-CAD GC=F ^RUT ^TNX ^IXIC ^VIX ^FTSE ^N225 CADEUR=X",
    "SG": "^STI ^N225 ^HSI ^FTSE BTC-USD XRP-USD ^GSPC ^DJI ^IXIC GC=F CL=F ^TNX ^KLSE ^JKSE PSEI.PS",
    "ES": "^IBEX ^STOXX50E EURUSD=X BZ=F GC=F BTC-EUR XRP-EUR ^GDAXI ^FTSE ^GSPC ^DJI ^IXIC CL=F EURGBP=X SI=F ^N225",
    "IN": "^BSESN ^NSEI INR=X ^DJI ^IXIC BTC-INR XRP-INR ^HSI ^N225 EURINR=X GBPINR=X AEDINR=X INRJPY=X SGDINR=X",
    "GB": "^FTSE ^FTMC ^FTAI GBPEUR=X GBPUSD=X BTC-GBP XRP-GBP ^GSPC ^DJI CL=F GC=F ^N225 ^HSI ^GDAXI ^FCHI",
    "CN": "^HSI ^TWII 000001.SS 399106.SZ ^N225 ^DJI ^TNX CL=F GC=F",
    "FR": "^FCHI ^STOXX50E ^DJI EURUSD=X GC=F BTC-EUR XRP-EUR CL=F ^GDAXI ^FTSE ^IXIC ^GSPC ^N225 ^HSI GBPUSD=X",
    "IT": "FTSEMIB.MI ^DJI ^IXIC ^N225 CL=F BTC-EUR XRP-EUR GC=F EURUSD=X ^GSPC ^HSI ^STOXX50E EURGBP=X EURCHF=X EURCAD=X",
    "AU": "^AORD ^AXJO AUDUSD=X CL=F GC=F BTC-AUD XRP-AUD AUDEUR=X AUDNZD=X ^NZ50 ^NDX ^FTSE ^DJI ^GDAXI ^HSI ^N225",
    "DE": "^GDAXI ^STOXX50E ^DJI GC=F EURUSD=X BTC-EUR XRP-EUR CL=F ^MDAXI ^TECDAX ^SDAXI ^N225 ^FTSE ^FCHI ^IXIC",
    "NZ": "^NZ50 NZDUSD=X NZDEUR=X ^AORD ^AXJO CL=F GC=F ^NDX ^FTSE ^DJI ^GDAXI ^HSI ^N225 NZDJPY=X"
  },

  // Cartões temáticos (lang=en-US, region=US) — marketCategoryLongName na coluna "category":
  "cartoesTematicos": {
    "US": "7 itens · ^GSPC ^DJI ^IXIC ^RUT ^TNX ^VIX GC=F · category 'US'",
    "EUROPE": "6 itens · ^FTSE ^FCHI ^GDAXI ^N100 EURUSD=X GBP=X · category 'EUROPE'",
    "ASIA": "5 itens · 000001.SS ^N225 ^HSI ^AXJO JPY=X · category 'ASIA' — um 6º membro fantasma",
    "CRYPTOCURRENCIES": "6 itens · BTC-USD XRP-USD ETH-USD USDT-USD BNB-USD SOL-USD · category 'CRYPTOCURRENCIES'",
    "RATES": "6 itens · ^IRX ^FVX ^TNX ^TYX ZT=F ZN=F · category 'RATES'",
    "COMMODITIES": "6 itens · CL=F GC=F SI=F HG=F NG=F BZ=F · category 'COMMODITIES'",
    "CURRENCIES": "6 itens · EURUSD=X JPY=X GBP=X AUD=X CAD=X MXN=X · category 'CURRENCIES'"
    // Nota ASIA: o item fantasma ^ADOW (quoteType NONE, preço e market nulos) só aparece no
    //   dump com fields= vazio — no conjunto default ele é filtrado (por isso 5 itens)
  },

  // Agregados regionais (8 itens cada; devolvem longName em todos os itens):
  "agregados": {
    "AMERICA_ALL": "^GSPC ^DJI ^IXIC ^RUT ^VIX ^BVSP ^GSPTSE DX-Y.NYB",
    "EUROPE_ALL": "^FTSE ^FCHI ^GDAXI ^N100 ^STOXX50E ^125904-USD-STRD ^XDB ^XDE",
    "ASIA_ALL": "000001.SS ^N225 ^HSI ^AXJO ^KS11 ^BSESN ^XDN ^XDA"
  },

  // Cartões por país (6 itens cada):
  "cartoesPais": {
    "GB": "^FTSE GBPUSD=X GBPEUR=X ^FTMC ^FTAI GC=F · category 'UK'",
    "HK": "^HSI 000001.SS ^GSPC JPYHKD=X GBPHKD=X HKDCNY=X · category 'Hong Kong'",
    "DE": "^GDAXI ^STOXX50E ^DJI GC=F EURUSD=X BTC-EUR · category 'Germany'",
    "FR": "^FCHI ^STOXX50E ^DJI EURUSD=X GC=F BTC-EUR · category 'France'",
    "AU": "^AORD AUDUSD=X ^AXJO CL=F GC=F BTC-AUD · category 'Australia'",
    "CA": "^GSPTSE ^SPTTFS ^SPTTEN CADUSD=X BTC-CAD CL=F · category 'Canada'",
    "IT": "FTSEMIB.MI ^DJI ^IXIC ^N225 CL=F BTC-EUR · category 'Italy'",
    "ES": "^IBEX ^STOXX50E EURUSD=X CL=F GC=F BTC-EUR · category 'Spain'",
    "SG": "^STI ^N225 ^HSI ^FTSE BTC-USD ^KLSE · category 'Singapore'",
    "NZ": "^NZ50 NZDUSD=X ^AORD CL=F GC=F BTC-USD · category 'New Zealand'"
  }
}
```

**Variação temporal — a troca índices↔futuros** (mapeamento completo em `indicesToFutureSwap`, seção 4):

- **Sessão regular (`REGULAR`)**: índices para todos — região e flag indiferentes (`market=US&region=BR` devolve `^GSPC ^DJI ^IXIC ^RUT ^TNX ^VIX GC=F`).
- **Região ≠ US fora da sessão regular**: `market=US` + `region` suportada ≠ `US` devolve a variante trocada (`ES=F YM=F NQ=F RTY=F ^TNX ^VIX GC=F`); com `region=US`, o pós-mercado ainda devolve índices. Regiões não suportadas caem no comportamento `US`.
- **Janela noturna**: com os índices em `POSTPOST` (após o fechamento do pós-mercado, ~20:00 ET), a troca vale também com `region=US` — no cartão `US` e no dock global, que sobe para **16 itens** com `^VIX` incluso (`ES=F YM=F NQ=F RTY=F CL=F GC=F SI=F EURUSD=X ^TNX ^VIX GBPUSD=X JPY=X BTC-USD XRP-USD ^FTSE ^N225`).
- `noIndicesToFutureSwap=true` **desativa** a troca em qualquer configuração — devolve os índices originais. Com `region=US` fora da janela noturna (sessão regular e pós-mercado) a flag é inerte: ausente, `false` ou `true` produzem respostas idênticas, com índices.
- **Docks regionais não trocam**: com `region=BR` (ou outra suportada), o dock devolve a lista regional própria; cartões de outros países (`GB`, `HK`, `EUROPE`, …) tampouco trocam. A cauda fixa do cartão US (`^TNX ^VIX GC=F`) não é afetada.
- Racional: os futuros CME (sessão quase contínua) refletem movimento ao vivo enquanto os índices de caixa estão parados — no pós-mercado para quem vê de fora dos EUA, na janela noturna para todos.
- O conjunto de campos é o mesmo para toda variante; a diferença está na composição de símbolos.

## Notas do cliente oficial

```json5
{
  // ==========================================================================
  // 8 · COMPORTAMENTO DO CLIENTE OFICIAL (dock da home e página de mercados)
  // ==========================================================================

  // Base fixa de fields enviada em toda chamada (+ extras do chamador anexados ao fim):
  "baseFields": [
    "shortName",
    "regularMarketPrice", "regularMarketChange", "regularMarketChangePercent",
    "fulldayPrice", "fulldayChange", "fulldayChangePercent"
  ],
  "formatted": "true",                  // incondicional
  "langRegionFallback": "en-US / US",   // valores da sessão sobrescrevem os do chamador no transporte

  // Tradução de exibição com horário estendido ligado (não altera a query):
  "extendedHoursMapping": {
    "regularMarketPrice": "fulldayPrice",
    "regularMarketChange": "fulldayChange",
    "regularMarketChangePercent": "fulldayChangePercent"
  },

  // Cache local e âncoras de resgate: ver seção 4 (clientLocalCache, anchors).
  // O carregador reaproveita o cache local quando a lista do bucket já existe, as âncoras da
  // categoria estão presentes e, com horas estendidas, todos os itens têm os campos fullday*.

  // Página de mercados: o cartão "RATES" só é pedido com region=US E lang=en-US (no código:
  // h=["COMMODITIES","CURRENCIES"] e RATES entra só quando a região É US e o lang É en-US —
  // nodes/94.sNWH2W9M.js); ordem de exibição default (support_agent.Cd9DzWFk.js): US · EUROPE ·
  // ASIA · CRYPTOCURRENCIES ·
  // RATES · COMMODITIES · CURRENCIES — com uma exceção codificada: region=HK + lang=zh-Hant-HK
  // usa a ordem alternativa US · ASIA · EUROPE · CURRENCIES · COMMODITIES · CRYPTOCURRENCIES ·
  // RATES · os agregados vêm como constantes do cliente: ["AMERICA_ALL","EUROPE_ALL","ASIA_ALL"]
  // · slugs de rota das categorias: RATES→"bonds", COMMODITIES→"commodities", CURRENCIES→
  // "currencies", *_ALL→"world-indices" (exibição «US Treasury Bonds»/«World Indices»)

  // A rota /(app)/(redirect)/rates NÃO é a categoria de mercados: é URL legada que redireciona
  // 301 para /personal-finance/mortgages/best/mortgage-rates/ (taxas de hipoteca).

  // sparkline NÃO é campo do payload: a mini-curva da interface vem de GET /v7/finance/spark.
  // Itens fantasma possíveis nos dumps (ex.: ^ADOW no cartão ASIA, quoteType NONE — seção 7).
}
```

**Contrato do carregador** — `loadMarketSummary(ctx, options)`; os defaults aplicam-se integralmente só quando o chamador não passa objeto de opções:

| Opção | Tipo | Default | Efeito |
| :--- | :--- | :--- | :--- |
| `lang` | string | sessão (`en-US`) | entra na query, mas o transporte sobrescreve com o `lang` da sessão — inerte no fio |
| `region` | string | sessão (`US`) | idem `lang`: sobrescrita pelo transporte com o valor da sessão |
| `market` | string | — | categoria enviada na query; também define a chave do cache local (`market \|\| "ALL"` — valor interno, nunca enviado à API; buckets conhecidos: `US`, `EUROPE`, `ASIA`, `RATES`, `COMMODITIES`, `CURRENCIES`, `CRYPTOCURRENCIES`, `AMERICA_ALL`, `EUROPE_ALL`, `ASIA_ALL`, `SG`, `ALL`) |
| `fields` | string[] | `[]` | extras anexados à base fixa na query (ex.: `["displayName"]` na página de mercados); o servidor projeta por adição (seção 5) |
| `loadDefaultSparklines` | bool | `false` | dispara sparklines (`GET /v7/finance/spark`) para os símbolos do resultado final |
| `critical` | bool | `true` | erro relançado ao chamador (a falha pode interromper o carregamento da rota) |
| `silent` | bool | `false` | não grava resultado/erro no cache local |
| `noIndicesToFutureSwap` | bool | `false` | repassado à query (seção 4) |
| `noAdditionalTickers` | bool | `false` | desativa os resgates de âncora (seção 4, `anchors`) |

No fio, `noIndicesToFutureSwap=false` só é serializado nas chamadas sem objeto de opções (a serialização descarta `undefined`/`null`), e `crumb` é anexado somente se houver crumb na sessão. Retorno: array de itens — payload do servidor com as âncoras mescladas e o item StepStone reposicionado para o fim — ou `null` em erro. O módulo do dock em smartphone inicializa com `market=US` e sparklines ligadas.

## Limites e políticas de uso

| Aspecto | Comportamento |
| :--- | :--- |
| User-Agent | Obrigatório agente de navegador: `Python-urllib/3.x` e o `curl` default recebem `429 Edge: Too Many Requests` — bloqueio por assinatura de agente, não por volume (rajadas de 15 requisições com UA de navegador passam sem limite perceptível, latência média ~240 ms). |
| Tamanho | URL com ~5,5 KB de `fields` (500 entradas) → `200`. |
| Qualidade de dados | Itens fantasma possíveis nas listas curadas (ex.: `^ADOW` no cartão `ASIA`, seção 7) · snapshots das famílias 52w podem vir stalados/inconsistentes — lado pedido nulo com o complementar materializando valores antigos (observado em `EURUSD=X`, out/2026). |
