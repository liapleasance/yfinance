# `GET /v1/finance/quoteType/{symbol}`

> **Data de atualização:** 2026-10-20 · constantes deste endpoint validadas ao vivo contra `query1.finance.yahoo.com` (2026-10-19, segunda ~17:20 UTC — ~350 requisições em cinco fases; as 9 classes de cotação observáveis (EQUITY…NONE, incluindo OPTION e delistados), a precedência path×query, o sufixo `_lang_` do messageBoardId, o mapa `overnightPrice`→`us_ot_market`, o cache de borda de 1800+1800 s e o contrato dos dois clientes oficiais (loader SvelteKit + chartStatic) verificados na mesma janela · mesma data ~22:02 UTC: revalidação de 35 claims estruturais — 35/35, incl. precedência, listas, inertes, overnightPrice, classes e headers).

---


Cartão de identidade do instrumento: devolve **o tipo de cotação** (`quoteType` — a enum que dá nome a este endpoint), a bolsa, o fuso de pregão, o mercado YFT, o nome curto/longo e ids de integração (Quartr, message boards) — **nada de preços, volumes ou séries** (para isso existem o [marketSummary](v6_finance_quote_marketSummary.md) e o [quote v7](v7_finance_quote.md); módulos fundamentais são outro endpoint). É a chamada de **roteamento** da página de quote: o loader React decide QUAL página renderizar — abas, módulos e categoria de anúncio — a partir do `quoteType` devolvido aqui (bloco 6), antes de qualquer cotação existir; o cliente de gráfico do v8 usa a mesma chamada para montar o contexto de mercado do chart. É o único endpoint **v1** do documento, e isso se vê no envelope: `quoteType.result/error` (estilo v1), não o wrapper `finance.*` dos v6/v7 — que só reaparece no corpo do erro 400. Os dois clientes oficiais chamam **um símbolo por requisição**, mas o servidor aceita listas separadas por vírgula tanto no path quanto na query (`/AAPL,MSFT` → 2 itens; bloco 1) — capacidade não usada pelos clientes.

| | |
| :--- | :--- |
| Método | `GET` — aceita também `HEAD` e `OPTIONS` (este expõe `Allow: HEAD,GET,OPTIONS`); demais métodos → `405` |
| Hosts | `query1` · `query2` (`.finance.yahoo.com` — ambos servem o mesmo backend, identificado pelo header de resposta `x-envoy-decorator-operation: finance-quote-api--mtls-production-sg3.finance-k8s:4080/*`; o cliente de gráfico sorteia por chamada e mantém `iquery` para chamadas selecionadas — bloco 6) |
| Caminho | `/v1/finance/quoteType/{symbol}` (forma **path**, loader SvelteKit) · `/v1/finance/quoteType/?symbol={symbols}` (forma **query**, cliente de gráfico — a barra final é OBRIGATÓRIA: sem ela a rota não existe e devolve `404` texto puro) |
| Autenticação | Anônima — responde `200` sem cookie e sem crumb; crumb errado, ausente ou em outro vetor é igualmente aceito e ignorado |
| User-Agent | Agente de navegador obrigatório — `curl`/`Python-urllib` e afins recebem `429 Edge: Too Many Requests` |
| Cache de borda | `public, max-age=1800, stale-while-revalidate=1800` — janela total de ~60 min por URL, a segunda mais longa do documento (só o [markets/ids](ws_market-info_v1_finance_markets_ids.md) chega a 2 h); respostas byte a byte idênticas entre `query1` e `query2` |
| Payload típico | ~0,4 KB por item (398 B observado para `AAPL`, 377–430 B nas demais classes) |

## Autenticação e User-Agent

A requisição é anônima, como no [marketSummary](v6_finance_quote_marketSummary.md) e no [markettime](v6_finance_markettime.md): todas as combinações de cookie/crumb devolvem `200` com corpo idêntico. Os dois clientes oficiais enviam cookies por `credentials: "include"` (pipeline comum às APIs de dados), mas nenhum vetor de crumb é necessário ou validado.

```bash
# Forma path — loader SvelteKit (a query inteira é convenção do pipeline):
curl -s -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/138.0.0.0" \
  "https://query1.finance.yahoo.com/v1/finance/quoteType/AAPL?formatted=true&lang=en-US&region=US"

# Forma query — cliente de gráfico chartStatic (barra final obrigatória;
#   enablePrivateCompany=false é serializado mesmo falso — bloco 6):
curl -s -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/138.0.0.0" \
  "https://query1.finance.yahoo.com/v1/finance/quoteType/?symbol=AAPL&lang=en-US&region=US&enablePrivateCompany=false"

# Lista separada por vírgula (funciona nas duas formas; caixa é normalizada
#   e desconhecidos são silenciosamente descartados — bloco 1):
curl -s -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/138.0.0.0" \
  "https://query1.finance.yahoo.com/v1/finance/quoteType/?symbol=aapl,^GSPC,BTC-USD,ATVI"

# Delistado (ATVI/TWTR/SGEN/SIVB) → 200 com quoteType "NONE" (bloco 4);
#   símbolo jamais visto → 200 com result VAZIO (o 404 é fabricado pelo cliente):
curl -s -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/138.0.0.0" \
  "https://query1.finance.yahoo.com/v1/finance/quoteType/ZZZZZZZZ"

# Erro 400 real do servidor — sem símbulo nenhum (envelope finance, bloco 3):
curl -s -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/138.0.0.0" \
  "https://query1.finance.yahoo.com/v1/finance/quoteType/"
```

## Estrutura do endpoint — parâmetros, item de quoteType e constantes

Estrutura declarativa pura (JSON5 comentado), sem nenhuma função ou lógica executável de JavaScript: parâmetros da requisição (incluindo a dualidade path×query), o item devolvido com seus campos por classe, o envelope v1 e seus três caminhos de erro, o catálogo de classes de cotação com os campos de cada uma, o inventário de mercados e bolsas, e o contrato dos dois clientes oficiais.

```json5
{
  // ==========================================================================
  // 1 · PARÂMETROS DA REQUISIÇÃO
  // ==========================================================================
  request: {
    method: "GET",
    path: "/v1/finance/quoteType/{symbol}   OU   /v1/finance/quoteType/?symbol={symbols}",
    pathRules: {                      // a forma path é a do loader SvelteKit:
      "symbol": "o segmento final vira INTERNAMENTE o query param symbol — a prova é a mensagem do 400: \"Missing required query parameter=symbol\" quando o segmento falta",
      "multi": "lista por vírgula funciona TAMBÉM no path — /AAPL,MSFT devolve 2 itens",
      "precedencia": "path vence sobre a query quando ambos presentes: /MSFT?symbol=AAPL devolve MSFT; /AAPL?symbol=MSFT devolve AAPL",
      "barra_final": "/v1/finance/quoteType?symbol=AAPL (SEM barra) → 404 texto puro; /v1/finance/quoteType/ (barra vazia) → 400; // (segmento vazio) → 404",
    },
    params: {
      symbol: "AAPL",                 // Forma query — a do cliente de gráfico. OBRIGATÓRIO
                                       //   nessa forma (symbol= vazio → 400 "Missing required
                                       //   query parameter=symbol"). Case-insensitive
                                       //   (aapl/aApL → eco canônico "AAPL"). Lista por vírgula
                                       //   aceita: AAPL,MSFT,TSLA → 3 itens; A ORDEM é preservada
                                       //   e REPETIÇÕES também (50 pedidos → 50 itens; 200 → 200).
                                       //   Símbolos desconhecidos são DESCARTADOS da lista (não
                                       //   viram itens vazios): AAPL,ZZZZZZZZ,MSFT → 2 itens.
                                       //   Espaço NÃO é trimado dentro da lista ("AAPL, MSFT" →
                                       //   1 item — " MSFT" vira desconhecido). Barra no valor
                                       //   não divide nada (symbol=AAPL/MSFT → result vazio)
      formatted: "true",              // INERTE — true ≡ false ≡ omitido (corpos comparados
                                       //   byte a byte; nada a formatar: não existe {raw,fmt}
                                       //   em NENHUMA classe). O loader envia "true" por
                                       //   convenção do pipeline
      lang: "en-US",                  // Quase decorativo: NÃO localiza nome nenhum (7203.T é
                                       //   "TOYOTA MOTOR CORP" tanto em ja-JP quanto en-US;
                                       //   0005.HK inglês em zh-Hant-HK; PETR4.SA idêntico em
                                       //   pt-BR) e NÃO ecoa em header content-language. ÚNICO
                                       //   efeito observável: sufixo "_lang_<prefixo>" no
                                       //   messageBoardId (bloco 2) quando o lang tem hífen E
                                       //   não começa com "en": pt-BR → "_lang_pt",
                                       //   zh-Hant-HK E zh-Hant → "_lang_zh", es-MX → "_lang_es",
                                       //   PT-br → "_lang_pt" (case-insensitive), pt-BR-x-foo →
                                       //   "_lang_pt" (primeiro segmento), xx-XX → "_lang_xx"
                                       //   (desconhecido também ganha). SEM sufixo: en, en-US,
                                       //   en-GB, en-x-foo (en* nunca) e langs SEM hífen (pt, ja,
                                       //   zh, zz, ptbr, pt_br)
      region: "US",                   // SEM efeito observável — market/exchange/fuso idênticos
                                       //   para region=BR/GB/XX em AAPL; a resolução do símbolo
                                       //   é global (PETR4.SA resolve de qualquer região). O
                                       //   cliente de gráfico envia por fidelidade à sessão
      overnightPrice: "true",         // O ÚNICO parâmetro com efeito real no corpo: troca o campo
                                       //   "market" de "us_market" para "us_ot_market" — SOMENTE
                                       //   para EQUITY/ETF listados nos EUA (AAPL, TSLA, VOO
                                       //   mudam; PETR4.SA, 7203.T, 0005.HK, ES=F, GC=F, BTC-USD,
                                       //   EURUSD=X, ^GSPC e PRLAX NÃO mudam — mercados sem
                                       //   sessão overnight própria). +3 bytes no payload de AAPL
      enablePrivateCompany: "true",   // Gates de feature do cliente (bloco 6) — sem efeito
      mockPrivateCompany: "true",     //   observável em símbolos públicos: PRIVATE_COMPANY não é
      mockOvernightPrice: "true",     //   endereçável por símbolo público conhecido (SpaceX,
                                       //   OpenAI, Stripe, 2337207 → result vazio mesmo com as
                                       //   flags)
      // — tolerados e ignorados: crumb (correto ou errado) e qualquer parâmetro
      //   desconhecido
    },
  },

  // ==========================================================================
  // 2 · ITEM DE QUOTE TYPE (quoteType.result[i])
  // ==========================================================================
  commonFields: {                    // ORDEM DE CHEGADA no wire (EQUITY; demais classes
                                       //   seguem a mesma ordem menos os campos que não têm —
                                       //   bloco 4): symbol, quoteType, [quartrId], exchange,
                                       //   shortName, [longName], [messageBoardId],
                                       //   [underlying*], exchangeTimezoneName,
                                       //   exchangeTimezoneShortName, gmtOffSetMilliseconds,
                                       //   market, isEsgPopulated, hasSelerityEarnings,
                                       //   selerityIsGaap
    "symbol": "AAPL",                 // Eco CANÔNICO do pedido — caixa normalizada (aapl →
                                       //   "AAPL"); um item por símbolo resolvido
    "quoteType": "EQUITY",            // A enum que dá nome ao endpoint (catálogo no bloco 4) —
                                       //   é ela que roteia a página de quote no cliente
    "quartrId": "4742",               // [def: EQUITY] Id da empresa na integração Quartr
                                       //   (parceiro de conteúdo fundamentalista) — STRING
                                       //   numérica, presente em TODA equidade testada
                                       //   (AAPL 4742, TSLA 3706, VALE 4387, PETR4.SA 3989,
                                       //   BP.L 4359, MIRM 13686…). BDR herda o id da empresa:
                                       //   AAPL34.SA devolve o MESMO 4742 de AAPL. Nunca aparece
                                       //   em ETF/INDEX/CURRENCY/CRYPTO/FUTURE/MUTUALFUND/OPTION
    "exchange": "NMS",                // Bolsa — código curto proprietário (não MIC): NMS/NYQ/NGM
                                       //   (EUA), SAO, JPX, HKG, LSE, NSI, ASX, SHH, OSA, SNP,
                                       //   CGI (taxas), PVT (índices privados), PCX/BTS (ETFs),
                                       //   NAS (fundos), CME/CMX (futuros), CCC (cripto), CCY
                                       //   (moedas), OPR (opções) — inventário no bloco 5
    "shortName": "Apple Inc.",        // Nome curto de exibição (NÃO localiza — bloco 1 lang)
    "longName": "Apple Inc.",         // Nome longo (razão social); AUSENTE em FUTURE e NONE
    "messageBoardId": "finmb_24937",  // [condicional] Id do fórum histórico ("finmb_<n>") — some
                                       //   quando o instrumento nunca teve board (^FPMI) ou a
                                       //   classe não usa (FUTURE/OPTION). Recebe o sufixo
                                       //   "_lang_<prefixo>" com lang hífen não-en:
                                       //   lang=pt-BR → "finmb_24937_lang_pt" (única mutação de
                                       //   lang no endpoint; também aplica a delistados com
                                       //   board: SGEN → "finmb_34145_lang_pt")
    "underlyingSymbol": "ESZ26.CME",  // [def: FUTURE/OPTION] No FUTURE: contrato da frente COM
                                       //   bolsa sufixada (ES=F → "ESZ26.CME"; GC=F →
                                       //   "GCZ26.CMX" — bate com a tradução cur_* do [quote v7](v7_finance_quote.md)).
                                       //   No OPTION: o ATIVO-base puro ("SPY" em
                                       //   SPY261023C00600000) — mesma chave, semânticas
                                       //   diferentes por classe
    "underlyingExchangeSymbol": "ESZ26.CME",
                                       // [def: FUTURE] Espelho do underlyingSymbol (mesmo valor
                                       //   nas capturas); não existe em OPTION
    "headSymbol": "ES=F",             // [def: FUTURE] O próprio contrato contínuo (ES=F) —
                                       //   distintivo da classe
    "exchangeTimezoneName": "America/New_York",
                                       // Fuso IANA da BOLSA (não do instrumento): moedas →
                                       //   Europe/London, cripto → UTC, Treasury →
                                       //   America/Chicago (bloco 5)
    "exchangeTimezoneShortName": "EDT",
                                       // Abreviação vigente (com DST aplicado)
    "gmtOffSetMilliseconds": "-14400000",
                                       // Offset em milissegundos como STRING ("-14400000" =
                                       //   UTC-4) — tipo herdado do v6. CASO NONE: o valor é a
                                       //   STRING LITERAL "null" (delistados) — não é JSON null!
    "market": "us_market",            // Id de mercado YFT (inventário no bloco 5) — o mesmo
                                       //   espaço us_market/us24_market/usir_market do [marketSummary](v6_finance_quote_marketSummary.md)
                                       //   (cartão RATES) e do yfit_market_id do [markettime](v6_finance_markettime.md)
    "isEsgPopulated": false,          // BOOLEANO NATIVO — os três últimos campos são os únicos
    "hasSelerityEarnings": true,      //   valores não-string do endpoint (false em toda a
    "selerityIsGaap": true,           //   amostra exceto hasSelerityEarnings/selerityIsGaap
                                       //   true em parte das equidades US — AAPL e TSLA true;
                                       //   BRK-B, VALE, PETR4.SA false — presença de dados do
                                       //   fornecedor Selerity)
  },

  // ==========================================================================
  // 3 · ENVELOPE V1 E CAMINHOS DE ERRO
  // ==========================================================================
  envelope: {
    ok: {                             // 200 — sempre, para símbolo resolvido ou não:
      "quoteType": {
        "result": [ /* itens — 1 por símbolo resolvido */ ],
        "error": null,                // null em TODAS as respostas 200 observadas
      },
    },
    errors: {
      "400_BadRequest": {             // path com barra e NENHUM símbolo, ou symbol= vazio — o
                                       //   único caso que materializa o wrapper finance:
        "finance": {
          "result": null,
          "error": {
            "code": "Bad Request",
            "description": "Missing required query parameter=symbol",
          },
        },
      },
      "404_NotFound_texto": "rota inexistente (/v1/finance/quoteType SEM barra, //, base sozinha) — corpo TEXTO PURO \"Not Found\\r\\n\", não JSON",
                                       //   (o corpo cru tem uma linha em branco final)
      "200_result_vazio": {           // símbolo jamais visto (ZZZZZZZZ, 300 letras A, opção
                                       //   com strike inexistente) → 200, "result": [], error
                                       //   null. NÃO É ERRO no servidor — o 404 "Not Found"
                                       //   que o usuário vê é FABRICADO no cliente (bloco 6)
      },
    },
    multi: {                          // listas por vírgula (path OU query):
      "cardinalidade": "N itens para N símbolos resolvidos; repetições preservadas (50 → 50; 200 → 200 — nenhum limite observado)",
      "ordem": "a ordem do pedido é preservada entre os itens",
      "desconhecidos": "descartados silenciosamente — AAPL,ZZZZZZZZ,MSFT devolve 2 itens",
    },
  },

  // ==========================================================================
  // 4 · CATÁLOGO QUOTE_TYPES — campos por classe
  // ==========================================================================
  QUOTE_TYPES: {
    _regra: "toda classe parte dos 13 campos comuns (symbol, quoteType, exchange, shortName, longName, messageBoardId, exchangeTimezoneName, exchangeTimezoneShortName, gmtOffSetMilliseconds, market, isEsgPopulated, hasSelerityEarnings, selerityIsGaap) e ganha/perde conforme abaixo; observadas ao vivo as 9 primeiras",
    EQUITY: {                          // 14 campos — única classe com quartrId
      extras: ["quartrId"],
      exemplos: "AAPL (NMS) · PETR4.SA (SAO) · BP.L (LSE) · 7203.T (JPX) · VALE (NYQ) · BRK-B/BF-B (NYQ) · AAPL34.SA (BDR — herda quartrId) · RELIANCE.NS · WES.AX",
    },
    ETF: {                            // 13 campos — igual ao comum
      exemplos: "VOO (PCX) · ARKK (BTS) · BIL · GREK",
    },
    INDEX: {                          // 13 campos; messageBoardId condicional
      exemplos: "^GSPC (SNP) · ^BVSP (SAO) · ^VIX · ^N225 (OSA) · 000001.SS (SHH — o índice de Xangai como INDEX) · ^FPMI (PVT — SEM messageBoardId) · ^IRX/^FVX/^TYX/^TNX (CGI, usir_market — as Treasury do [marketSummary](v6_finance_quote_marketSummary.md))",
    },
    CURRENCY: {                       // 13 campos
      exemplos: "EURUSD=X · USDBRL=X (CCY, ccy_market, fuso Europe/London)",
    },
    CRYPTOCURRENCY: {                 // 13 campos — fuso UTC
      exemplos: "BTC-USD · ETH-USD (CCC, ccc_market)",
    },
    MUTUALFUND: {                     // 13 campos
      exemplos: "PRLAX (NAS)",
    },
    FUTURE: {                         // 14 campos — PERDE longName/messageBoardId/quartrId,
      extras: ["underlyingSymbol", "underlyingExchangeSymbol", "headSymbol"],
      remove: ["longName", "messageBoardId", "quartrId"],
      exemplos: "ES=F → underlying ESZ26.CME · GC=F → GCZ26.CMX · CL=F/CT=F (a tradução cur_* do [quote v7](v7_finance_quote.md) vem daqui) — CME/CMX, us24_market",
    },
    OPTION: {                         // 13 campos — PERDE messageBoardId; exchange OPR;
      extras: ["underlyingSymbol"],   //   market us24_market (opções negociam no mercado 24h)
      remove: ["messageBoardId"],
      exemplos: "SPY261023C00600000 → \"SPY Oct 2026 600.000 call\", underlyingSymbol \"SPY\" · put idem P · QQQ261023C00500000 — formato OCC SEM espaço (o COM espaço não resolve); vencidas AINDA resolvem (SPY261016C00600000 capturada 3 dias após o vencimento)",
    },
    NONE: {                           // delistados — 6 campos (+messageBoardId condicional):
      campos: ["symbol", "quoteType", "messageBoardId?", "gmtOffSetMilliseconds", "isEsgPopulated", "hasSelerityEarnings", "selerityIsGaap"],
      peculiaridades: "gmtOffSetMilliseconds = STRING LITERAL \"null\" · exchange/market/fuso/nomes AUSENTES · selerity* sempre false",
      exemplos: "ATVI · TWTR · SGEN (único com messageBoardId finmb_34145) · SIVB — o mesmo NONE de borda documentado no [quote v7](v7_finance_quote.md)",
    },
    _somenteNoCliente: {              // valores que o código dos clientes conhece mas NÃO foram
                                       //   observáveis ao vivo (nenhum símbolo público devolve):
      PRIVATE_COMPANY: "tabs summary/profile — habilitado por enablePrivateCompany (bloco 6); sondas SpaceX/OpenAI/Stripe/2337207 → result vazio",
      MONEYMARKET: "tabs summary/chart (pstCat pf-banking no mapa B)",
      INDICATOR: "tabs summary/chart",
      CUL_IDX: "tabs summary/chart/history/profile/components — índices customizados",
      CUL_SUB_IDX: "idem CUL_IDX",
      ECNQUOTE: "citado pelo validador do cliente junto com NONE como classe inválida para renderizar",
    },
  },

  // ==========================================================================
  // 5 · MERCADOS E BOLSAS (inventário observado)
  // ==========================================================================
  MARKETS: {
    _regra: "market é o id YFT do pregão do instrumento — o MESMO espaço do [marketSummary](v6_finance_quote_marketSummary.md) (usir/us24 no cartão RATES) e do [markettime](v6_finance_markettime.md) (yfit_market_id por país)",
    us_market:    { bolsas: "NMS NYQ NGM PCX BTS SNP PVT NAS", quem: "ações/ETFs/índices/fundos US — vira us_ot_market com overnightPrice=true (EQUITY/ETF apenas)" },
    us_ot_market: { bolsas: "—", quem: "mercado overnight dos EUA — SÓ materializa com o parâmetro overnightPrice=true em EQUITY/ETF US; nenhum outro mercado tem variante ot (br/jp/hk/us24/ccc/ccy testados — não mudam)" },
    us24_market:  { bolsas: "CME CMX OPR", quem: "futuros E opÇÕes — pregão quase contínuo; ^FPMI também" },
    usir_market:  { bolsas: "CGI", quem: "^IRX ^FVX ^TYX ^TNX — as Treasury yields do cartão RATES do [marketSummary](v6_finance_quote_marketSummary.md); fuso America/Chicago" },
    ccc_market:   { bolsas: "CCC", quem: "cripto — fuso UTC (o único pregão sem fuso nominal)" },
    ccy_market:   { bolsas: "CCY", quem: "moedas fiat — fuso Europe/London" },
    br_market:    { bolsas: "SAO", quem: "PETR4.SA · AAPL34.SA · ^BVSP" },
    jp_market:    { bolsas: "JPX OSA", quem: "7203.T · ^N225" },
    hk_market:    { bolsas: "HKG", quem: "0005.HK" },
    gb_market:    { bolsas: "LSE", quem: "BP.L" },
    in_market:    { bolsas: "NSI", quem: "RELIANCE.NS" },
    au_market:    { bolsas: "ASX", quem: "WES.AX" },
    cn_market:    { bolsas: "SHH", quem: "000001.SS" },
  },

  // ==========================================================================
  // 6 · CLIENTES OFICIAIS — o contrato completo
  // ==========================================================================
  officialClient: {

    // — LOADER SVELTEKIT (chunks/188.DvdQXGb3.js, função Te — loadQuoteType): alimenta o
    //   roteamento da página de quote e os cartões Top Analyst
    "loaderSvelteKit": {
      "symbolValidation": {           // ANTES de qualquer rede — rejeita localmente:
        "regex": "/[^a-zA-Z0-9^.$_+=*&:@~-]+/g sobre decodeURIComponent(symbol)",
        "onFail": "throw \"Bad request for loadQuoteType\" (nem chega a chamar o endpoint)",
        "urlDerivation": "símbolo da URL: params.symbol.replace(/\\?.*/, \"\").trim().toUpperCase()",
        "bugDoRegex": "a regex Ne carrega a flag /g — em JavaScript, test() com /g é STATEFUL (lastIndex persiste entre chamadas), então um símbolo INVÁLIDO pode passar na validação logo depois de um símbolo rejeitado (bug do cliente oficial, presente no bundle novo; reprodutores em node confirmam)",
      },
      "storeCache": {                 // cache de cliente EM VOLTA do endpoint:
        "read": "getQuoteSummary(symbol).quoteType — se já populado, NÃO chama a rede",
        "write": "updateQuote(symbol, {quoteSummary: {quoteType: item}}) no sucesso (modo não-silent) — esquenta o store para as próximas visitas",
      },
      "query": {                      // o que o loader envia de verdade:
        "fixo": "formatted=true",
        "condicionais": "mockPrivateCompany · mockOvernightPrice · enablePrivateCompany · overnightPrice — só entram quando as feature flags do config de serviços estão acesas (as duas primeiras são de mock/QA)",
        "semEfeito": "nos símbolos públicos todas são inertes (bloco 1) — o servidor só reage ao overnightPrice",
      },
      "cacheHeaders": {               // enviados SÓ com a flag enableQuoteTypeCaching —
                                       //   cache do CLIENTE, não da borda:
        "x-cache": "1",
        "x-cache-ttl": "60000 (60 s)",
        "x-cache-swr": "21600000 (6 h)",
      },
      "emptyResult": "result vazio (símbolo desconhecido) → throw LOCAL {message: \"Not Found\", status: 404} — é DAQUI que vem o 404 que o usuário vê; o servidor respondeu 200",
      "wrapperTopAnalyst": "Tt (188.DvdQXGb3.js): chama em modo silent=true; símbolo ausente → 404 \"Symbol is required\"; erros 404/500 propagados para a página de erro (error_1) — usos: TopAnalystCard · TopAnalystRatings · DataTable",
    },

    // — CLIENTE DE GRÁFICO (chartStatic.Bl5ArXnz.js — fetchQuoteType, classe do chart v8):
    //   contexto de mercado para o gráfico antes do /v8/finance/chart
    "chartStatic": {
      "url": "QUOTE_TYPE_PATH \"/v1/finance/quoteType/\" + query {symbol, lang (padrão en-US), region (padrão US), enablePrivateCompany (featureFlags.includes — serializado MESMO falso, \"false\")}",
      "host": "pool query1/query2 com Math.random POR CHAMADA · iquery como host fixo de chamadas selecionadas · iquery-stage quando hostname int* ou ?chartStage=true",
      "semSimbolo": "symbol vazio → fallback LOCAL {exchangeTimezoneName: \"America/New_York\", market: \"us_market\"} SEM rede (o gráfico desenha no fuso US)",
      "retry": "até 3 tentativas (default 3) em AbortError / \"Request Timeout\", decrementando o contador",
      "parse": "quoteType.result[0] || {} — result vazio vira objeto vazio, SEM 404 local (diferente do loader)",
    },

    // — ROTEAMENTO DA PÁGINA (mapas H/a3 do 188.DvdQXGb3.js): o quoteType devolvido AQUI
    //   escolhe abas e módulos da página de quote — a razão de ser do endpoint
    "pageRouting": {
      "mapa": "quoteType → {pstCat (categoria de anúncio), quoteModules (módulos quoteSummary por aba), tabs}",
      "tabs": {
        EQUITY: "summary news chart community key-statistics history profile financials analysis options holders sustainability company-insights events (14)",
        ETF: "summary news chart community history profile options holdings performance risk",
        MUTUALFUND: "summary news chart community history profile holdings performance risk purchase-info sustainability",
        CRYPTOCURRENCY: "summary news chart community history profile",
        CURRENCY: "summary news chart community history",
        INDEX: "summary news chart community history options components",
        FUTURE: "summary news chart history futures",
        OPTION: "summary chart history",
        MONEYMARKET: "summary chart",
        INDICATOR: "summary chart",
        PRIVATE_COMPANY: "summary profile",
        "CUL_IDX/CUL_SUB_IDX": "summary chart history profile components",
      },
      "overridePorSimbolo": "^FPMI → private-indices (tabs summary/profile/components) — o único caso de roteamento por símbolo e não por classe",
      "validador": "renderiza apenas com quoteType E exchange presentes, classe NÃO em ke=[\"ECNQUOTE\", \"NONE\"] e exchange YHD gated — NONE (delistado) é explicitamente não-página",
      "mapaF": "categoria do GRÁFICO: CRYPTOCURRENCY→CRYPTO · CURRENCY→CURRENCIES · ETF→ETF · MUTUALFUND→MUTUALFUND (consumido por StockTickerBlock/SimilarTo/RelatedTickers)",
    },
  },
}
```

## Limites e políticas de uso

| Aspecto | Comportamento |
| :--- | :--- |
| User-Agent | Obrigatório agente de navegador: `Python-urllib/3.x` e o `curl` default recebem `429 Edge: Too Many Requests` — mesma política do [marketSummary](v6_finance_quote_marketSummary.md), do [quote v7](v7_finance_quote.md) e do [markettime](v6_finance_markettime.md) (bloqueio por assinatura de agente, não por volume). |
| Autenticação | Nenhuma — anônimo por definição; cookies/crumb presentes são aceitos e ignorados (nenhum vetor é exigido). |
| Erros | Três caminhos distintos: `400` envelope finance (só quando o símbolo falta inteiro — path com barra vazio ou `symbol=` vazio); `404` texto puro (rota errada — path sem barra final na forma query); `200` com `result: []` (símbolo desconhecido — o 404 é fabricado no cliente). |
| Cache | `public, max-age=1800, stale-while-revalidate=1800` — janela total de ~60 min por URL, a segunda mais longa do documento (vs 10 s do [marketSummary](v6_finance_quote_marketSummary.md) e 120 s do [markettime](v6_finance_markettime.md); o [markets/ids](ws_market-info_v1_finance_markets_ids.md) chega a 2 h); `Vary: Origin,Accept-Encoding` — lang/region/flags não variam a chave de cache no header (cada URL distinta tem sua entrada). |
| Cardinalidade | 1 item por símbolo resolvido; listas por vírgula aceitas nas duas formas (200 símbolos observados sem limite aparente, repetições preservadas); desconhecidos descartados silenciosamente. |
| Payload | ~0,4 KB por item (377–430 B) — empatado com o markettime como o menor do documento; para identificar um símbolo é a chamada mais barata possível (quote v7 devolve 1,6–4,3 KB pelo mesmo símbolo). |
| Idempotência | Total — nenhuma mutação de estado; a única variação de corpo por parâmetro é o `market` com `overnightPrice=true` e o sufixo `_lang_` do messageBoardId. |

---
