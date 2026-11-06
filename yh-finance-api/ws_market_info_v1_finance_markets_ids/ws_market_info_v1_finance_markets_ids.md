# `GET /ws/market-info/v1/finance/markets/ids`

> **Data de atualização:** 2026-10-20 · constantes deste endpoint validadas ao vivo contra `query1.finance.yahoo.com` (2026-10-19, ~18:45–19:45 UTC — ~190 requisições em seis fases (A–C3); o envelope finance.result com ordem de chaves fixa, os 4 módulos com listas completas (24/37/6/44), a normalização de `modules`, a regra de pareamento lang×region (14 locales com listas próprias + default), a flag StepStone (+4 intercalados no default, +3 nos demais locales — FPACEPE só no en-US) e o contrato dos dois clientes oficiais (right rail + hub loader) verificados na mesma janela · mesma data ~22:08 UTC: revalidação de 48 claims — 48/48, com o `OPTIONS` agora expondo `Allow` (corrigido abaixo) e os tamanhos de módulo único medidos por módulo).

---


Catálogo de ids por módulo: o endpoint resolve **listas de tickers** — `commodities`, `currencies`, `bonds` e `world_indices` — para os blocos de mercado do site. Não devolve cotação nenhuma (para isso existem o [marketSummary](v6_finance_quote_marketSummary.md) e o [quote v7](v7_finance_quote.md)): cada módulo é um objeto `{type, quoteType, tickers[]}` cujo array alimenta a **etapa seguinte** do consumidor, que cota o lote no [`quote` v7](v7_finance_quote.md) (`loadQuote`). É o primeiro endpoint `/ws/` do documento — o serviço **market-info**, o MESMO do [markettime](v6_finance_markettime.md), cujo id de implantação no envoy rotaciona entre `-baseline-` e `-production-` — e o envelope volta a ser `finance.result/error` de estilo v6. Dois consumidores: (1) o **right rail da página de gráficos**, que pede apenas `modules=commodities,currencies`, corta 5 tickers de cada lista e cota o lote; (2) o **loader `loadMarketsIds`** do hub de mercados, que pede **um módulo dinâmico por vez** — derivado da categoria da URL (`world-indices`, `commodities`, `bonds`, `currencies`) — acrescenta a flag `enableFtseStepStoneIndices` quando a feature de sessão está ativa e cota os tickers no loadQuote aplicando os nomes de exibição StepStone. `bonds` e `world_indices` são capacidade latente para o right rail: nenhum dos dois é pedido fora do hub.

| | |
| :--- | :--- |
| Método | `GET` — aceita também `HEAD` e `OPTIONS` (o `OPTIONS` responde `200` com `Allow: HEAD,GET,OPTIONS`, como nos demais endpoints); demais métodos → `405` com corpo no envelope `finance` |
| Hosts | `query1` · `query2` (`.finance.yahoo.com` — ambos servem o mesmo backend, identificado pelo header de resposta `x-envoy-decorator-operation: finance-market-info-api--mtls-baseline-production-usw2.finance-k8s:4080/*` — o MESMO serviço market-info do [markettime](v6_finance_markettime.md), com o id de implantação rotacionando entre `mtls-baseline-production-usw2` e `mtls-production-usw2` observado em janelas distintas; respostas byte a byte idênticas) |
| Caminho | `/ws/market-info/v1/finance/markets/ids` |
| Autenticação | Anônima — responde `200` sem cookie e sem crumb; `crumb` errado na query ou no header `x-crumb` é aceito e ignorado |
| User-Agent | Agente de navegador obrigatório — `curl`/`Python-urllib` e afins recebem `429 Edge: Too Many Requests` |
| Cache de borda | `public, max-age=3600, stale-while-revalidate=3600` — janela total de ~2 h por URL, **o mais longo do documento** (supera os 60 min do [quoteType](v1_finance_quoteType.md)); `Vary: Origin,Accept-Encoding` |
| Payload típico | 38 B (result vazio) · 147–497 B (módulo único: bonds 147 · currencies 341 · commodities 375 · world_indices 497) · 679 B (right rail: 2 módulos) · 1,2 KB (catálogo completo) |

## Autenticação e User-Agent

A requisição é anônima, como no [marketSummary](v6_finance_quote_marketSummary.md), no [markettime](v6_finance_markettime.md) e no [quoteType](v1_finance_quoteType.md): todas as combinações de cookie/crumb devolvem `200` com corpo idêntico — `crumb` inválido na query string ou no header `x-crumb` produz o mesmo corpo byte a byte. O loader do hub declara `crumb: false` (nunca envia credencial) e o right rail não envia headers além do padrão do transporte.

```bash
# Right rail da página de gráficos — os dois módulos fixos (sem crumb, sem formatted):
curl -s -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/138.0.0.0" \
  "https://query1.finance.yahoo.com/ws/market-info/v1/finance/markets/ids?lang=en-US&region=US&modules=commodities,currencies"

# Hub de mercados — módulo único por categoria + flag StepStone (loader loadMarketsIds):
curl -s -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/138.0.0.0" \
  "https://query1.finance.yahoo.com/ws/market-info/v1/finance/markets/ids?lang=en-US&region=US&modules=world_indices&enableFtseStepStoneIndices=true"

# Catálogo completo — modules AUSENTE (ou vazio, "modules=") devolve os 4 módulos:
curl -s -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/138.0.0.0" \
  "https://query1.finance.yahoo.com/ws/market-info/v1/finance/markets/ids?lang=en-US&region=US"

# Locale pareado — as listas mudam de COMPOSIÇÃO (bloco 4; BR reescreve na perspectiva BRL):
curl -s -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/138.0.0.0" \
  "https://query1.finance.yahoo.com/ws/market-info/v1/finance/markets/ids?lang=pt-BR&region=BR"

# Módulo desconhecido — 200 com result VAZIO, sem erro nenhum
#   (o erro "Invalid response from MarketsIds" é fabricado no cliente — bloco 6):
curl -s -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/138.0.0.0" \
  "https://query1.finance.yahoo.com/ws/market-info/v1/finance/markets/ids?lang=en-US&region=US&modules=GARBAGE"
```

## Estrutura do endpoint — parâmetros, módulos e constantes

Estrutura declarativa pura (JSON5 comentado), sem nenhuma função ou lógica executável de JavaScript: parâmetros da requisição, o envelope e o único caminho de erro do servidor, os quatro módulos com as listas completas do default en-US, a regra de pareamento lang×region com a matriz de locales, o contrato da flag StepStone e os dois clientes oficiais.

```json5
{
  // ==========================================================================
  // 1 · PARÂMETROS DA REQUISIÇÃO
  // ==========================================================================
  request: {
    method: "GET",
    path: "/ws/market-info/v1/finance/markets/ids",
    params: {
      modules: "commodities,currencies", // Lista por vírgula selecionando as chaves de
                                         //   finance.result. Reconhecidos: commodities ·
                                         //   currencies · bonds · world_indices — tudo
                                         //   case-insensitive (Commodities ≡ COMMODITIES ≡
                                         //   cURRENCIES), espaços nas bordas trimados
                                         //   (" commodities " resolve; internos também:
                                         //   "commodities , currencies" resolve os DOIS) e
                                         //   duplicatas colapsam (commodities,Commodities
                                         //   → 1 chave). Valor desconhecido é OMITIDO
                                         //   silenciosamente: GARBAGE sozinho → 200 com
                                         //   result:{} (corpo de 38 B); currencies,GARBAGE,
                                         //   bonds → currencies+bonds; quase-sinônimos NÃO
                                         //   casam ("commodity"/"indices" → result vazio).
                                         //   AUSENTE ou VAZIO ("modules=") → catálogo
                                         //   completo, os 4 módulos. Param REPETIDO na URL
                                         //   (modules=commodities&modules=currencies) → só
                                         //   o PRIMEIRO vale. A ORDEM das chaves de result
                                         //   é FIXA do servidor (currencies → commodities →
                                         //   bonds → world_indices), nunca a ordem pedida
                                         //   (bloco 2)
      lang: "en-US",                    // Idioma. SOZINHO não altera as listas (pt-BR +
                                         //   region=US é byte a byte o default en-US); só
                                         //   produz efeito casado com region num locale
                                         //   suportado — a regra completa no bloco 4
      region: "US",                     // Região. Idem — sozinha não altera nada (en-US +
                                         //   region=BR ≡ baseline); case-insensitive
                                         //   (br ≡ BR, aceita minúscula como no [markettime](v6_finance_markettime.md))
      enableFtseStepStoneIndices: "true",
                                         // A flag do hub de mercados. Valor "true" — case-
                                         //   insensitive ("TRUE" também ativa; "false" ·
                                         //   "1" · "yes" · string vazia ≡ ausente). Aciona
                                         //   os índices de private equity StepStone no
                                         //   world_indices: +4 intercalados no default
                                         //   en-US (44→48) e +3 nos demais locales
                                         //   (44→47 em pt-BR — o FPACEPE "Global" só entra
                                         //   no default; bloco 5). SEM efeito em
                                         //   commodities/currencies/bonds (corpos byte a
                                         //   byte idênticos com e sem a flag)
      formatted: "true",                // INERTE — true ≡ false ≡ omitido (corpos byte a
                                         //   byte; não existe {raw,fmt} em módulo nenhum)
      count: "5",                       // INERTE — 5 ≡ 100 ≡ omitido (o right rail manda
                                         //   count só nos endpoints irmãos do array)
      crumb: "…",                       // INERTE — crumb inválido devolve 200 idêntico;
                                         //   x-crumb no header idem. Família sem
                                         //   enforcement de credencial
      // — qualquer parâmetro desconhecido é tolerado e ignorado (foo=bar: corpo
      //   idêntico byte a byte)
    },
  },

  // ==========================================================================
  // 2 · ENVELOPE E CAMINHOS DE ERRO
  // ==========================================================================
  envelope: {
    sucesso: {
      finance: {
        result: {
          // chaves = módulos pedidos RECONHECIDOS, na ordem FIXA do servidor:
          //   currencies → commodities → bonds → world_indices (pedir
          //   "commodities,currencies" devolve currencies PRIMEIRO — a ordem
          //   pedida é irrelevante, inclusive byte a byte entre pedidos
          //   espelhados); cada valor é o objeto de módulo do bloco 3
          "<modulo>": { type: "screener_payload", quoteType: "…", tickers: [] },
        },
        error: null,                    // null LITERAL em todo sucesso observado —
                                         //   inclusive com result:{} (módulo 100%
                                         //   desconhecido): entrada ruim NÃO é erro
      },
    },
    methodNotAllowed: {                 // POST/PUT/DELETE/PATCH → 405 — o ÚNICO status de
                                         //   erro do endpoint, no MESMO envelope finance:
      finance: { result: null, error: { code: "Method Not Allowed",
                                        description: "HTTP 405 Method Not Allowed" } },
    },
    erroFabricadoNoCliente: "o hub loader lança \"Invalid response from MarketsIds\" quando result vem vazio ou error vem preenchido — o servidor respondeu 200; o erro é local (bloco 6)",
    semErroDeEntrada: "não existe 400/404 por entrada: módulo desconhecido → result:{}; lang/region inválidos → default en-US; símbolos não são entrada deste endpoint",
  },

  // ==========================================================================
  // 3 · MÓDULOS — o item e suas listas (default en-US; fingerprint cur/com/bnd/wi = 24/37/6/44)
  // ==========================================================================
  modules: {                          // ORDEM DE CHEGADA no wire, idêntica nos 4 módulos:
                                       //   type → quoteType → tickers. Não existe {raw,fmt}
                                       //   nem campo condicional: os 3 campos vêm sempre
    currencies: {
      type: "screener_payload",       // UNIFORME nos 4 módulos — o valor declara que o lote
                                       //   alimenta o pipeline de quote estilo screener
                                       //   (loadQuote com fields; bloco 6)
      quoteType: "CURRENCY",          // A classe de cotação dos tickers do módulo — o mesmo
                                       //   espaço da enum do [quoteType](v1_finance_quoteType.md) (moedas → CCY)
      tickers: [                      // 24 itens, 23 ÚNICOS (EURJPY=X sai 2× — quirks abaixo)
        "EURUSD=X", "JPY=X", "GBPUSD=X", "AUDUSD=X", "NZDUSD=X", "EURJPY=X",
        "GBPJPY=X", "EURGBP=X", "EURCAD=X", "EURSEK=X", "EURCHF=X", "EURHUF=X",
        "EURJPY=X", "CNY=X", "HKD=X", "SGD=X", "INR=X", "MXN=X", "PHP=X",
        "IDR=X", "THB=X", "MYR=X", "ZAR=X", "RUB=X",
      ],
    },
    commodities: {
      type: "screener_payload",
      quoteType: "FUTURE",            // TODOS os tickers do módulo são futuros contínuos
                                       //   (=F) — inclusive os 4 de índice US e os 4 de
                                       //   Treasury que o BR depois corta (bloco 4)
      tickers: [                      // 37 itens: 4 índice US (ES YM NQ RTY) · 4 Treasury
                                       //   (ZB ZN ZF ZT) · 8 metais (GC MGC SI SIL PL HG
                                       //   PA) · 6 energia (CL HO NG RB BZ B0) · 7 grãos
                                       //   (ZC ZO KE ZR ZM ZL ZS) · 3 carnes (GF HE LE)
                                       //   · 6 softs (CC KC CT LBS OJ SB)
        "ES=F", "YM=F", "NQ=F", "RTY=F", "ZB=F", "ZN=F", "ZF=F", "ZT=F",
        "GC=F", "MGC=F", "SI=F", "SIL=F", "PL=F", "HG=F", "PA=F",
        "CL=F", "HO=F", "NG=F", "RB=F", "BZ=F", "B0=F",
        "ZC=F", "ZO=F", "KE=F", "ZR=F", "ZM=F", "ZL=F", "ZS=F",
        "GF=F", "HE=F", "LE=F",
        "CC=F", "KC=F", "CT=F", "LBS=F", "OJ=F", "SB=F",
      ],
    },
    bonds: {
      type: "screener_payload",
      quoteType: "INDEX",             // Os 4 Treasury yields viajam como INDEX — o cartão
                                       //   RATES do [marketSummary](v6_finance_quote_marketSummary.md) (^IRX ^FVX ^TNX ^TYX), cujo
                                       //   regularMarketPrice é a TAXA percentual
      tickers: [                      // 6 itens — os ÚNICOS 6, em todos os locales
                                       //   observados (bloco 4): 4 yields + 2 futuros de
                                       //   taxa que TAMBÉM estão em commodities
        "^IRX", "^FVX", "^TNX", "^TYX", "ZT=F", "ZN=F",
      ],
    },
    world_indices: {
      type: "screener_payload",
      quoteType: "INDEX",
      tickers: [                      // 44 itens (48 com a flag — bloco 5): Américas
                                       //   (^GSPC ^DJI ^IXIC ^NYA ^XAX ^BUK100P ^RUT ^VIX)
                                       //   · Europa (^FTSE ^GDAXI ^FCHI ^STOXX50E ^N100
                                       //   ^BFX MOEX.ME) · Ásia-Oceania (N225 ^HSI
                                       //   00001.SS 99001.SZ ^STI ^AXJO ^AORD ^BSESN
                                       //   ^JKSE ^KLSE ^NZ50 ^KS11 ^TWII) · LatAm
                                       //   (^GSPTSE ^BVSP ^MXX ^IPSA ^MERV) · Oriente
                                       //   Médio/África (^TA125.TA ^CASE30 ^JN0U.JO) ·
                                       //   bloco de fecho (DX-Y.NYB ^125904-USD-STRD
                                       //   ^XDB ^XDE 000001.SS ^N225 ^XDN ^XDA)
        "^GSPC", "^DJI", "^IXIC", "^NYA", "^XAX", "^BUK100P", "^RUT", "^VIX",
        "^FTSE", "^GDAXI", "^FCHI", "^STOXX50E", "^N100", "^BFX", "MOEX.ME",
        "N225", "^HSI", "00001.SS", "99001.SZ", "^STI", "^AXJO", "^AORD",
        "^BSESN", "^JKSE", "^KLSE", "^NZ50", "^KS11", "^TWII", "^GSPTSE",
        "^BVSP", "^MXX", "^IPSA", "^MERV", "^TA125.TA", "^CASE30", "^JN0U.JO",
        "DX-Y.NYB", "^125904-USD-STRD", "^XDB", "^XDE", "000001.SS", "^N225",
        "^XDN", "^XDA",
      ],
    },
  },
  quirksDasListas: {                  // idiossincrasias observadas nas listas do default
    duplicatasLiterais: "currencies carrega EURJPY=X DUAS vezes (posições 6 e 13 — 24 itens, 23 únicos); world_indices carrega o Nikkei em DUAS notações: N225 (sem circunflexo, posição 17) E ^N225 (posição 41) — o servidor não deduplica nenhuma das duas",
    grafiasDuplicadas: "00001.SS (5 dígitos) e 000001.SS (6 dígitos) coexistem em world_indices — duas grafias do Composto de Xangai; MOEX.ME é o único índice com sufixo de bolsa no id",
    intersecaoModulos: "ZT=F e ZN=F pertencem a commodities E bonds — quem agrega os dois módulos cota os mesmos 2 símbolos 2×; o right rail não sofre (só pede commodities)",
    sufixoFgi: "os StepStone são os únicos tickers com sufixo .FGI em todo o catálogo — e só materializam com a flag (bloco 5)",
  },

  // ==========================================================================
  // 4 · LOCALE — a regra de pareamento lang×region e a matriz de listas
  // ==========================================================================
  locale: {
    regra: "lang é normalizado para um LOCALE CANÔNICO e a region pedida precisa CASAR com a região dele — só então as listas do locale valem; qualquer combinação fora disso cai no DEFAULT en-US/US (24/37/6/44). Canônico: subtags extras são ignoradas (pt-BR-x-foo ≡ pt-BR); lang SEM subtag de região ganha a região-padrão da língua: pt→pt-BR · de→de-DE · fr→fr-FR · it→it-IT · es→es-ES · zh→zh-Hant-HK · en→en-US. Casamento case-insensitive nos DOIS lados (pt-BR+br ✓ · PT-BR+BR ✓)",
    foraDoPareamento: "de-DE+US · en-US+DE · pt-BR+DE · de-DE+BR · en-GB+US · en-GB+DE · pt-BR+PT · pt-PT+BR · pt-PT+PT · es+US · es+MX · en+GB · en+CA · en+SG · en+AU · en+IN · en+NZ · it+CH · zh+CN · zh+TW — TODOS byte a byte o default en-US",
    suportados: {                      // 14 locales com listas próprias + default — fingerprint (cur/com/bnd/wi):
      "en-US (default)": { fp: "24/37/6/44", quem: "qualquer par fora do pareamento — 46 combinações testadas caem aqui, INCLUSIVE ja-JP+JP e ko-KR+KR (veja divergências)" },
      "pt-BR":  { fp: "37/27/6/44", detalhe: "moedas na PERSPECTIVA BRL — 10 cruzes BRL* na frente (BRLUSD BRLEUR BRLGBP BRLJPY BRLARS BRLINR BRLCAD BRLSEK BRLCNY BRLAUD) e as formas curtas trocadas pelas longas (HKD=X→USDHKD=X · SGD=X→USDSGD=X · MXN=X→USDMXN=X · PHP=X→USDPHP=X · IDR=X→USDIDR=X · THB=X→USDTHB=X · MYR=X→USDMYR=X · ZAR=X→USDZAR=X · RUB=X→USDRUB=X; entram também CHF=X · AUDJPY=X · CAD=X); commodities SEM os 4 futuros de índice US (ES YM NQ RTY), os 4 de Treasury (ZB ZN ZF ZT), MGC=F e SIL=F; world_indices reordenado LatAm-primeiro (^BVSP ^IPSA ^MERV ^MXX abre a lista) com a troca ^BUK100P↔^NSEI" },
      "en-CA":  { fp: "29/20/6/44" },
      "en-GB":  { fp: "28/20/6/43" },
      "en-AU":  { fp: "28/18/6/44", detalhe: "perspectiva AUD — só AU tem AUDGBP=X e AUDNZD=X" },
      "en-NZ":  { fp: "28/18/6/44", detalhe: "mesmas CONTAGENS de en-AU com listas distintas: troca AUDGBP=X+AUDNZD=X por NZDUSD=X+NZDAUD=X — a perspectiva da moeda da casa decide" },
      "en-IN":  { fp: "27/20/6/44" },
      "en-SG":  { fp: "38/24/6/45", detalhe: "o maior catálogo de moedas do serviço (38)" },
      "es-ES":  { fp: "33/21/6/46" },
      "es-US":  { fp: "27/22/6/44", detalhe: "locale PRÓPRIO: region=US com listas em espanhol — distinto do default en-US/US" },
      "fr-FR":  { fp: "28/20/6/44" },
      "de-DE":  { fp: "27/20/6/44" },
      "it-IT":  { fp: "26/20/6/48" },
      "zh-Hant-HK": { fp: "26/20/6/47", detalhe: "a grafia curta zh-HK+HK resolve o MESMO corpo" },
    },
    divergenciasDaSecao3: "o pareamento NÃO herda o mapa de locales do [markettime](v6_finance_markettime.md): zh-TW/zh-Hant-TW aqui caem no DEFAULT (no [markettime](v6_finance_markettime.md) zh-TW→zh-Hant-HK); ja-JP e ko-KR não são suportados — os hubs JP/KR recebem as listas US apesar de JP/KR serem mercados válidos do [markettime](v6_finance_markettime.md) (31 regiões lá, 14 locales aqui)",
    invariantes: {
      bonds: "6 tickers IDÊNTICOS em todos os locales observados — o único módulo sem variação nenhuma",
      commodities: "só REMOÇÕES por locale (37 → 18–27), nunca acréscimos: cada locale corta do catálogo US (BR corta 10; DE/GB/FR/IT/HK cortam 17; ES corta 16)",
      currencies: "reescrita na PERSPECTIVA da moeda da casa (cruzes BRL*/AUD*/NZD* na frente; formas curtas HKD=X trocadas pelas longas USDHKD=X)",
      world_indices: "reordenação REGIONAL da lista + trocas pontuais (BR: ^BUK100P↔^NSEI; DE ±3; GB ±2; IT +10/−9; ES +10/−10; HK +14/−11 — diffs completos nas evidências marketsids-faseC.json)",
    },
  },

  // ==========================================================================
  // 5 · FLAG STEPSTONE (enableFtseStepStoneIndices)
  // ==========================================================================
  stepstone: {
    ativacao: "valor string \"true\" — case-insensitive (\"TRUE\" também ativa); \"false\" · \"1\" · \"yes\" · string vazia ≡ ausente (todas com 200 e o corpo do default)",
    noDefault_enUS: "world_indices 44→48 — os 4 índices de private equity FTSE/StepStone entram INTERCALADOS em âncoras fixas, NÃO no fim da lista: FPACEPE-USD-TR.FGI entre ^JN0U.JO e DX-Y.NYB (pos. 36) · FPACEBOUS-USD-TR.FGI entre DX-Y.NYB e ^125904-USD-STRD (pos. 38) · FPCPEXVM-USD-TR.FGI entre ^XDE e 000001.SS (pos. 42) · FPCPEXVA-USD-TR.FGI após ^XDA, na ÚLTIMA posição (pos. 47)",
    foraDoDefault: "+3 APENAS — FPACEPE-USD-TR.FGI (Global Private Equity) SÓ entra nas listas default/en-US: pt-BR 44→47 · en-GB 43→46 · es-ES 46→49 · it-IT 48→51 (as âncoras mudam com a lista do locale; nenhum locale já carrega .FGI sem a flag)",
    outrosModulos: "commodities · currencies · bonds — corpos byte a byte idênticos com e sem a flag, em TODOS os locales testados",
    nomesNoCliente: "o endpoint devolve SÓ os símbolos .FGI; os nomes de exibição são do CLIENTE — mapa pn de Sparkline.BC0BA4Gs.js (chave em toUpperCase): FPACEBOUS-USD-TR.FGI→\"US Private Equity\" · FPCPEXVM-USD-TR.FGI→\"European Private Equity\" · FPCPEXVA-USD-TR.FGI→\"APAC Private Equity\" · FPACEPE-USD-TR.FGI→\"Global Private Equity\"",
    origemDaFlag: "feature flag de SESSÃO (enableFtseStepStoneIndices — acesa no build vivo de 15/out/2026, nodes/149.DmXqzsEr.js); o hub lê do config de flags e serializa \"true\" na query SÓ quando acesa",
  },

  // ==========================================================================
  // 6 · CLIENTES OFICIAIS — o contrato completo
  // ==========================================================================
  officialClient: {

    // — RIGHT RAIL DA PÁGINA DE GRÁFICOS (chunks/finChartRightRail.C4PpSIrs.js):
    //   os cartões "Commodities" e "Currencies" ao lado do gráfico
    "rightRail": {
      "spec": {                        // o que este cliente envia de verdade:
        "path": "ws/market-info/v1/finance/markets/ids",
        "query": { lang: "chart.config.lang || \"en-US\"", region: "chart.config.region || \"US\"",
                   modules: "\"commodities,currencies\" — FIXO, sempre os dois" },
        "sem": "SEM formatted · SEM crumb · headers {} — o resolvedor é anônimo",
      },
      "acoplamento": "a spec ocupa a 4ª POSIÇÃO do array do orquestrador (Promise.all): [recent-quotes · trending · investment-ideas · ESTA · …screeners] — a resposta cai na 4ª variável do destructuring e é passada ao handler (mt) por acoplamento posicional, sem nenhum campo de tipo",
                                       //   (o trending da 2ª posição é o endpoint irmão
                                       //   [trending v1](v1_finance_trending.md), também
                                       //   sem acoplamento por tipo)
      "handler": "destructuring direto de finance.result.{commodities.tickers, currencies.tickers} → .slice(0, 5) de CADA lista → Promise.all das cotações dos 10 símbolos no pipeline de quote (campos do bloco de fields do right rail)",
      "capacidadeLatente": "bonds e world_indices NUNCA são pedidos por este cliente — são capacidade latente do endpoint; só o hub os consome (abaixo)",
    },

    // — HUB DE MERCADOS (chunks/loadTopAnalystRatings.C2A3seYS.js — função K, perfLabel
    //   "loadMarketsIds"; exportada via loadMarketsHubCategory): as tabelas por
    //   categoria de https://finance.yahoo.com/markets/
    "hubLoader": {
      "moduloDinamico": "UM módulo por chamada: modules: [<módulo da categoria>] — o mapa categoria-URL→módulo vive em support_agent.Cd9DzWFk.js (mapa de): world-indices→world_indices · commodities→commodities · bonds→bonds · currencies→currencies; aceita array (join \",\") OU string",
      "flag": "lida da SESSÃO (enableFtseStepStoneIndices do config de flags — via services/features) e injetada como query \"true\" SÓ quando acesa; desligada, o par simplesmente não entra na URL",
      "loader": "apiFetch (approval.BsApzrJF.js — o loader genérico): key \"finance\" → host query1.finance.yahoo.com (serverKey finance) · crumb: false (NUNCA envia credencial) · disableDefaultQueries: true (lang/region vêm explícitos na própria query, sem default automático)",
      "posProcessamento": "{tickers} = result[<módulo>] → loadQuote(symbols, fields) com os campos do hub → SE a flag está acesa: override de longName E shortName pelo mapa StepStone (m_1/Yr de Sparkline.BC0BA4Gs.js, chave em toUpperCase; predicado Wr casa os .FGI; detector auxiliar zr procura \"stepstone\" no nome)",
      "erroFabricado": "result vazio OU error preenchido → throw \"Invalid response from MarketsIds\" — o 200 com result:{} do servidor (módulo desconhecido) vira erro LOCAL do hub; critical=true repropaga, critical=false só loga",
      "quemNaoPassaAqui": "as categorias trending (loadTrendingTickers — o endpoint próprio está documentado em [trending v1](v1_finance_trending.md)) e as com scrIds (screener) do hub NÃO usam este endpoint; o mapa acima cobre as 4 categorias que usam",
    },
  },
}
```

## Limites e políticas de uso

| Aspecto | Comportamento |
| :--- | :--- |
| User-Agent | Obrigatório agente de navegador: `Python-urllib/3.x` e o `curl` default recebem `429 Edge: Too Many Requests` — mesma política dos endpoints anteriores ([marketSummary](v6_finance_quote_marketSummary.md) · [quote v7](v7_finance_quote.md) · [markettime](v6_finance_markettime.md) · [quoteType](v1_finance_quoteType.md)) (bloqueio por assinatura de agente, não por volume). |
| Autenticação | Nenhuma — anônimo por definição; crumb na query ou no header `x-crumb`, válido ou não, é aceito e ignorado (o loader do hub declara `crumb: false`). |
| Erros | Um único caminho: `405` de método (envelope `finance` com `error`); entrada ruim NUNCA é erro — módulo desconhecido → `200` com `result: {}` (o "Invalid response from MarketsIds" é fabricado no cliente). |
| Cache | `public, max-age=3600, stale-while-revalidate=3600` — janela total de ~2 h por URL, **o mais longo do documento** (vs 10 s do [marketSummary](v6_finance_quote_marketSummary.md) · 120 s do [markettime](v6_finance_markettime.md) · 60 min do [quoteType](v1_finance_quoteType.md)); `Vary: Origin,Accept-Encoding`. |
| Cardinalidade | No máx. 4 módulos por resposta; listas de 6 (bonds) a 48 tickers (world_indices com flag no default); sem paginação, sem count, sem limite — as listas são configuração fixa por locale, não resultado de busca. |
| Payload | 38 B (result vazio) · 375–497 B (módulo único) · 679 B (right rail) · 1,2 KB (catálogo completo) — o catálogo inteiro custa menos que 1 item do [quote v7](v7_finance_quote.md). |
| Idempotência | Total — configuração estática por locale; as únicas mutações de corpo são o locale pareado (bloco 4) e a flag StepStone (bloco 5); `formatted`/`count`/`crumb`/desconhecidos não alteram nada. |
