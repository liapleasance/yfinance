# `GET /v1/finance/trending/{region}`

> **Data de atualização:** 2026-10-20 · constantes deste endpoint validadas ao vivo contra `query1.finance.yahoo.com` (2026-10-19, ~22:57–23:20 UTC — ~230 requisições em doze baterias A–L: os três modos de resposta com as bases de campo exaustivas, o modelo completo de satélites de `fields` (26 gatilhos testados um a um), o modelo do `quoteType` com varredura de limiar (counts 40–60, 100, 1000), o param oculto `minMarketCap` do WADL, `keyVersion` v2/v3 com as duas gerações de snapshot, a matriz de logos (brands × mysterio × `useLogoDevLogo`), as 37 regiões do path, os 4 caminhos de erro com corpo exato e o WADL integral do `OPTIONS`) · **revalidação REV-9** (2026-10-19, 23:31–23:46 UTC — ~95 requisições em oito baterias T/F/G/H, disparada pela verificação de tabelas externas do endpoint: modelo do `lang` REESCRITO — localização de `typeDisp`, `fmt` e abreviações confirmada ao vivo, contra o claim anterior de "não localiza nada"; gate da entrada `TEST` por lang efetivo en-US; casing `test`/`TEST` entre modos; `jobTimestamp: 0` transitório; pools ETF/CRYPTOCURRENCY reconfirmados via TW/BR/XX/ZZ; matriz completa modo × lang × quoteType) · **revalidação REV-10** (2026-10-19, ~23:55–00:15 UTC — ~60 requisições em quatro baterias H/campos/bases/http, disparada pela verificação das 2ªs tabelas externas (campos por classe + erros HTTP): `circulatingSupply` REABILITADO ao vocabulário — é CRYPTO-only (o doc o listava como ignorado — ERRO nosso); bases POR CLASSE descobertas (flat 31/28/28/28/27 · raw/fmt -1 · dumps 89/70/71/62/62 com campos exclusivos por classe); lista INTERNA de 57 itens exposta pelo `minMarketCap` presente (mesmo =0; publicada=53); mensagem do 400 do mmc completa ("…, 0 to disable"); NÃO existe 403 — 429 com DOIS corpos (Edge:… vs Too Many Requests\r\n); path traversal `../` → 429 WAF · `..` → 404 por normalização · `%252E` duplo-codificado → 200 vazio; burst 25×200 sem rate-limit) · as duas capturas do usuário (24/set e 1/out) reconciliadas como evidência da migração de comportamento `keyVersion` v2 — bloco 11 · scripts: `rev7_analyze.py` · `rev7_a{2,3,4,5,6}_*.py` · `rev7_b_params.py` · `rev7_c_protocol.py` · `rev7_d_details.py` · `rev7_e_edge.py` · `rev7_f_confirm.py` · `rev7_g_threshold.py` · `rev7_h_model.py` · `rev7_i_final.py` · `rev7_j_wadl.py` · `rev7_k_hidden.py` · `rev7_l_kv.py` · `rev9_tabelas.py` · `rev9b_followup.py` · `rev9c_lang_pools.py` · `rev9d_anomalia.py` · `rev9e_envelope.py` · `rev9f_classe.py` · `rev9g_diff.py` · `rev9h_fechamento.py` · `rev10b_campos.py` · `rev10c_bases.py` · `rev10_http.py`.

---

Lista de **trending tickers** por região — o índice de "mais vistos" que alimenta a caixa de busca, o right rail de gráficos e a página de trending do site. É o primeiro endpoint do documento servido pelo **user-analytics** (`finance-user-analytics-api`, Jersey 2.33 — revelado pelo WADL do `OPTIONS` e pelo header envoy `finance-user-analytics-api--mtls-production-usw2.finance-k8s:4080/*`), e é um **híbrido** singular no documento: um índice de símbolos pré-computado por um job de analytics (com `trendingScore` de ordenação) que, quando `useQuotes=true` entra na query, é **enriquecido sob demanda** com o payload de cotação — por isso o campo `fields` e as famílias de satélites lembram o [`quote` v7](v7_finance_quote.md), o `format=true` lembra o `formatted=true` do estilo v6 e o envelope é o `finance.result/error` clássico. Três consumidores: (1) o **loader `loadTrendingTickers`** (store `trendingTickers`, usado pelo hub de mercados, pelo componente do painel de trending e pelas páginas de comunidade); (2) o **right rail da página de gráficos** (a aba "Trending Tickers", `quoteType=EQUITY&count=5`); (3) a **caixa de busca `finSearch`** (os "recommendations" do dropdown e a seção trending de cripto, `count` 5/25). O endpoint atravessou uma **mudança de comportamento** entre 1/out e 19/out/2026 (o campo `keyVersion: "v2"` apareceu na resposta e o default deixou de devolver o snapshot completo — bloco 11): os dois JSONs que motivaram esta documentação são do comportamento pré-mudança, e tudo o que segue descreve o comportamento **v2 vigente**, com o legado anotado.

| | |
| :--- | :--- |
| Método | `GET` — aceita também `HEAD` e `OPTIONS` (o `OPTIONS` responde `200` com WADL `application/vnd.sun.wadl+xml` gerado por Jersey 2.33 declarando os 12 query params com defaults; o header `Allow: HEAD,GET,OPTIONS` foi observado de forma **intermitente** — 8/12 capturas na sessão, o resto das vezes o header vem ausente); demais métodos → `405` com corpo no envelope `finance` |
| Hosts | `query1` · `query2` (`.finance.yahoo.com` — ambos servem o mesmo backend, header de resposta `x-envoy-decorator-operation: finance-user-analytics-api--mtls-production-usw2.finance-k8s:4080/*`; respostas byte a byte idênticas em símbolos e metadados do job) |
| Caminho | `/v1/finance/trending/{region}` — a região é **path param** (case-insensitive, `us` ≡ `US`); barra final tolerada (`/US/`), segmento extra (`/US/extra`) → `404`, path sem região → `404` |
| Autenticação | Anônima — responde `200` sem cookie e sem crumb; `crumb` errado na query ou no header `x-crumb` é aceito e ignorado (o loader envia `crumb: true` pela query, mas não há enforcement) |
| User-Agent | Agente de navegador obrigatório — `curl`/`Python-urllib`/`python-requests` recebem `429 Edge: Too Many Requests`; UA **ausente/vazio/`Wget`** recebem `429 Too Many Requests\r\n` (corpo distinto, com CRLF) — NÃO existe 403 (REV-10) |
| Cache de borda | `public, max-age=300, stale-while-revalidate=30` — 5 min + 30 s por URL, o MESMO formato do `markettime` porém 2,5× mais longo (vs 10 s do [marketSummary](v6_finance_quote_marketSummary.md) · 120 s do [markettime](v6_finance_markettime.md) · 60 min do [quoteType](v1_finance_quoteType.md) · 2 h do [market-info](ws_market-info_v1_finance_markets_ids.md)); `Vary: Origin,Accept-Encoding` |
| Payload típico | 38 B (result vazio) · 576 B (índice de símbolos, 25 itens) · ~6,5 KB (right rail: 46 campos × 5) · ~7,9 KB (finSearch: 38 campos × 5) · ~19,8 KB (flat base-31 × 25) · ~25,2 KB (raw/fmt base-30 × 25) · ~44,3 KB (loader exato: 47 campos × 25) · ~63 KB / ~103 KB (dump `fields=` vazio de 89/88 campos × 25, flat/raw-fmt) |

## Autenticação e User-Agent

A requisição é anônima, como no [marketSummary](v6_finance_quote_marketSummary.md), no [markettime](v6_finance_markettime.md), no [quoteType](v1_finance_quoteType.md) e no [market-info](ws_market-info_v1_finance_markets_ids.md): todas as combinações de cookie A3/crumb devolvem `200` com corpo idêntico — crumb inválido na query string ou no header `x-crumb` produz o mesmo corpo byte a byte. O loader do hub envia `crumb: true` (a query ganha `crumb=…` via transporte quando o store tem valor), mas o endpoint não enforcementa credencial nenhuma. O User-Agent de navegador é obrigatório (bloqueio por assinatura de agente, não por volume).

```bash
# Índice puro de símbolos — o default v2 (WADL: count=20, useQuotes=false, fields="symbol"):
curl -s -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/138.0.0.0" \
  "https://query1.finance.yahoo.com/v1/finance/trending/US"

# Caixa de busca (finSearch, type quote) — fields 5 + useLogoDevLogo (logos mysterio p/ todos):
curl -s -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/138.0.0.0" \
  "https://query1.finance.yahoo.com/v1/finance/trending/US?count=5&useQuotes=true&fields=shortName,longName,logoUrl,regularMarketChangePercent,regularMarketPrice&region=US&lang=en-US&useLogoDevLogo=true"

# Loader do hub (loadTrendingTickers) — format=true (raw/fmt) + quoteType=ALL + lang/region/crumb do transporte:
curl -s -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/138.0.0.0" \
  "https://query1.finance.yahoo.com/v1/finance/trending/US?count=25&fields=logoUrl,longName,shortName,regularMarketChange,regularMarketChangePercent,regularMarketPrice,fulldayPrice,fulldayChange,fulldayChangePercent&format=true&useQuotes=true&quoteType=ALL&lang=en-US&region=US"

# Right rail de gráficos — formatted=true (INERTE — o trabalho é do useQuotes) + EQUITY + count=5:
curl -s -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/138.0.0.0" \
  "https://query1.finance.yahoo.com/v1/finance/trending/US?formatted=true&count=5&fields=symbol,longName,shortName,underlyingSymbol,regularMarketPrice,regularMarketChange,regularMarketChangePercent,fulldayPrice,fulldayChange,fulldayChangePercent&useQuotes=true&quoteType=EQUITY"

# Dump completo — fields= (string VAZIA) destrava a projeção de 89 campos:
curl -s -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/138.0.0.0" \
  "https://query1.finance.yahoo.com/v1/finance/trending/US?useQuotes=true&count=5&fields="
```

## Estrutura do endpoint — parâmetros, os três modos e as constantes

Estrutura declarativa pura (JSON5 comentado): os 12 parâmetros da requisição com os defaults **declarados no WADL do servidor**, o envelope e os quatro caminhos de erro, os três modos de resposta com as bases de campo exaustivas, o modelo de satélites do `fields`, o modelo do `quoteType`, os params ocultos (`minMarketCap`, `keyVersion`), a regra de logos, a semântica do job de analytics e os contratos dos três clientes oficiais.

```json5
{
  // ==========================================================================
  // 1 · PARÂMETROS DA REQUISIÇÃO (defaults = WADL do OPTIONS, Jersey 2.33)
  // ==========================================================================
  request: {
    method: "GET",
    path: "/v1/finance/trending/{region}",
    params: {
      count: "20",                     // Default 20 (WADL xs:int + empiria: sem o param
                                        //   vêm exatamente 20). 1..N exato; acima do
                                        //   tamanho da lista faz CAP no tamanho (a lista
                                        //   US tinha 53 itens na janela — count 100/250/
                                        //   1000 devolveram 53 e o campo count ecoou 53).
                                        //   0 e NEGATIVOS → 200 com result:[] (não é
                                        //   erro). NÃO-INTEIRO (abc · 2.5 · 1e3 · overflow
                                        //   de 64 bits) → 400 "Parameter=count has an
                                        //   invalid type". Vazio ("count=") → default 20
      useQuotes: "true",               // A chave do endpoint: "true" case-INSENSITIVE
                                        //   (true/TRUE/True ativam; "1" · "yes" · "false"
                                        //   · "0" · vazio NÃO ativam, apesar de xs:boolean
                                        //   no WADL). Liga o enriquecimento de cotação —
                                        //   sem ele a resposta é o índice puro de símbolos
                                        //   e fields/quoteType/format/lang ficam INERTES
      fields: "shortName,longName,regularMarketPrice",
                                        // Default "symbol" (WADL). Lista por vírgula de
                                        //   campos do enriquecimento — vocabulário e
                                        //   satélites no bloco 4. Sensível a CAIXA e
                                        //   grafia EXATAS (ShortName/SHORTNAME/shortname
                                        //   são ignorados); o trim é só nas BORDAS do
                                        //   valor inteiro (" shortName " resolve, mas
                                        //   "shortName, longName" ignora o longName pelo
                                        //   espaço interno); duplicatas colapsam; elementos
                                        //   vazios ("a,,b") pulam; desconhecidos são
                                        //   omitidos silenciosamente; param REPETIDO na
                                        //   URL → só o PRIMEIRO vale. STRING VAZIA
                                        //   ("fields=") → projeção COMPLETA de 89 campos
                                        //   (o "dump" — bloco 3); sem useQuotes → inerte
      format: "true",                   // Serialização {raw,fmt}: a string exata "true"
                                        //   (MINÚSCULA — TRUE/True/1/yes NÃO ativam, ao
                                        //   contrário do useQuotes). Troca a base flat-31
                                        //   pela base raw/fmt-30 e a ordem de chaves das
                                        //   quotes (bloco 3). Sem useQuotes → inerte
      formatted: "true",                // TOTALMENTE INERTE — true ≡ false ≡ omitido, em
                                        //   qualquer modo (o right rail manda formatted=
                                        //   true e o corpo é byte a byte o mesmo sem ele;
                                        //   NÃO é o "formatted" do estilo v6 — o parâmetro
                                        //   de verdade aqui é format, do loader)
      quoteType: "EQUITY",              // Default "" (WADL) ≡ sem filtro. Reconhecidos (case-
                                        //   insensitive): EQUITY · ETF · CRYPTOCURRENCY —
                                        //   qualquer OUTRO valor (CRYPTO · INDEX · CURRENCY
                                        //   · MUTUALFUND · FUTURE · OPTION · NONE · STOCK ·
                                        //   listas com vírgula/espaço · vazio) é IGNORADO e
                                        //   devolve a lista mista completa. SÓ tem efeito com
                                        //   useQuotes=true (no modo símbolos é inerte). O
                                        //   modelo completo — regional vs pools globais — no
                                        //   bloco 5
      lang: "en-US",                    // Default en-US (WADL). Modelo REESCRITO na REV-9 —
                                        //   o "NÃO localiza nada" da versão anterior estava
                                        //   ERRADO. QUATRO efeitos: (1) ECO do campo language
                                        //   das quotes com a canonicalização de sempre (pt→
                                        //   pt-BR · de→de-DE · zh→zh-Hant-HK · en→en-US ·
                                        //   desconhecido (xx) → en-US; case-insensitive);
                                        //   (2) LOCALIZA typeDisp, a classe por extenso da
                                        //   base (Equity→Ação/Aktie/資本/權益/股票 · Currency→
                                        //   Moeda/Währung/通貨/匯率/貨幣 · Cryptocurrency→
                                        //   Criptomoeda/Kryptowährung/暗号通貨/加密貨幣 · ETF
                                        //   não traduz — sigla universal; zh→vocabulário HK,
                                        //   zh-Hant-TW→vocabulário TW: 股票 vs 權益); (3) no
                                        //   modo format=true LOCALIZA os fmt — separadores
                                        //   decimal/milhar (en "262.45" · pt-BR/de-DE
                                        //   "262,45" · trendingScore "3,261.35%" vs
                                        //   "3.261,35%"), abreviações do marketCap (en
                                        //   "2.831T" · pt-BR "2,831Tri" · de-DE "2,831Bill."
                                        //   — alemão: Billion = trilhão) e o longFmt idem;
                                        //   ja-JP troca AM/PM por 午前/午後 ("4:00午後 EDT")
                                        //   enquanto pt-BR/de-DE mantêm "PM"; (4) efeito
                                        //   colateral de COMPOSIÇÃO: a entrada TEST (ETF) só
                                        //   é servida na lista mista quando o lang EFETIVO é
                                        //   exatamente en-US — en-GB, pt-BR, de-DE, ja-JP,
                                        //   es-ES, fr-FR, ko-KR, it-IT, zh-* a EXCLUEM (US:
                                        //   53→52 itens) nos DOIS modos e no dump; o gate é
                                        //   da ENTRADA, não da classe (TW não perde 0050.TW
                                        //   com pt-BR) e o pool quoteType=ETF o IGNORA
                                        //   (bloco 5). NÃO localiza shortName/longName/
                                        //   displayName/marketState/averageAnalystRating
                                        //   (idênticos em qualquer lang). No modo símbolos
                                        //   só o efeito (4) se manifesta (não há fmt nem
                                        //   typeDisp para localizar)
      useLogoDevLogo: "true",           // Default false (WADL). "true" case-insensitive
                                        //   (TRUE/True ativam; "1" NÃO). SÓ produz efeito
                                        //   com logoUrl EM fields: troca o catálogo estático
                                        //   de marcas (s.yimg.com/lb/brands/…, ~1/10 das
                                        //   quotes) pelo serviço LogoDev (s.yimg.com/lo/
                                        //   mysterio/api/…, ~9/10) E acrescenta
                                        //   logoUrlDarkMode (bloco 7)
      keyVersion: "v2",                 // Default v2 (WADL declara "", o servidor resolve v2;
                                        //   o campo keyVersion da resposta ecoa o servido).
                                        //   Aceita v2|v3 — qualquer outro valor → 400 com a
                                        //   lista permitida na mensagem ("Invalid keyVersion
                                        //   'v1': allowed values are [v2, v3]"). v3 serve
                                        //   uma geração de snapshot MAIS FRESCA (bloco 8)
      minMarketCap: "1000000000",       // Param OCULTO — não aparece em nenhum cliente do
                                        //   corpus, só no WADL. Filtra a lista pela capitali-
                                        //   zação MÍNIMA em USD; funciona nos DOIS modos
                                        //   (símbolos e quotes). Aceita inteiro não-negativo;
                                        //   abc/-1/2.5 → 400 "Invalid minMarketCap '…':
                                        //   expected a whole non-negative number"; vazio ≡
                                        //   sem filtro. Quirks no bloco 6
      imgLabels: "", imgWidths: "", imgHeights: "",
                                        // Declarados no WADL, INERTES — o trio img* do
                                        //   [quote v7](v7_finance_quote.md) aqui não altera
                                        //   nenhum URL de logo (corpos idênticos com/sem)
      crumb: "…",                       // INERTE — aceito e ignorado (query ou x-crumb)
      // — qualquer parâmetro desconhecido é tolerado e ignorado (foo=bar: corpo idêntico)
    },
  },

  // ==========================================================================
  // 2 · ENVELOPE E CAMINHOS DE ERRO
  // ==========================================================================
  envelope: {
    sucesso: {
      finance: {
        result: [ {                    // SEMPRE um array de 1 elemento (ou vazio — abaixo)
          count: 25,                   // ecoa o NÚMERO EFETIVO de quotes devolvidas (o
                                       //   cap da lista ou o corte do filtro), não o count
                                       //   pedido; count=0/negativo → nem chega aqui
          quotes: [],                  // as quotes do modo em questão (bloco 3)
          jobTimestamp: 1792447908695, // epoch-ms do TÉRMINO do job de analytics que gerou
                                       //   o snapshot (idêntico entre os 3 modos e entre
                                       //   regiões do mesmo job — US e TW divergiram 54 ms)
          startInterval: 202610192100, // YYYYMMDDHHMM em UTC, SEMPRE com MM=00: a hora de
                                       //   INÍCIO da janela do job — jobTimestamp cai na
                                       //   hora seguinte (~50–72 min depois; bloco 8)
          keyVersion: "v2",            // a versão do formato servido (eco do param; presente
                                       //   em TODO sucesso v2, até no result:[{count:0,…}]
                                       //   de filtro vazio — só some no result:[]
        } ],
        error: null,                   // null LITERAL em todo sucesso observado
      },
    },
    listaVazia: { finance: { result: [], error: null } },
                                       // 200 para: count=0 · count NEGATIVO · região sem
                                       // trending (JP, IN, KR, MX, ID, MY, TH, ZA, NL, SE,
                                       // CH, AT, BE, DK, FI, NO, PL, PT, TR…) · região
                                       // DESCONHECIDA (XX, ZZ, usa, "US " com espaço — 38 B
                                       // exatos). Note: result [] (array vazio), NÃO null
    notFound: { finance: { result: null, error: { code: "Not Found",
                   description: "HTTP 404 Not Found" } } },
                                       // path SEM região (/v1/finance/trending e /v1/
                                       //   finance/trending/) · segmento extra (/US/extra)
    badRequest: [                      // 3 mensagens distintas — todas com code "Bad
                                       //   Request" no envelope (REV-10):
      { description: "Parameter=count has an invalid type" },            // count não-inteiro (abc · 1.5)
      { description: "Invalid keyVersion 'v1': allowed values are [v2, v3]" }, // keyVersion
      { description: "Invalid minMarketCap 'abc': expected a whole non-negative number, 0 to disable" }, // minMarketCap — a mensagem INTEIRA termina em ", 0 to disable"
    ],
    tooManyRequests: {                 // REV-10: DOIS corpos distintos, texto puro CT text/html:
      ferramentas: "429 'Edge: Too Many Requests' — curl · Python-urllib · python-requests (UA reconhecido como ferramenta)",
      ausenteOuWget: "429 'Too Many Requests\\r\\n' (COM CRLF) — UA AUSENTE · UA vazio ('') · Wget — assinaturas sem 'Edge:'",
      nota: "NÃO existe 403/'Access denied' neste endpoint (testado UA ausente/vazio/curl/urllib/requests/Wget — tudo 429); burst moderado de 25 cache-miss não disparou 429 (25×200) — a política é por ASSINATURA de agente/WAF, não por volume no nível testado",
    },
    pathTraversal: {                   // REV-10 — a região como dot-segment:
      comBarra: "%2E%2E%2F (../) · ..%2F · %2E%2E%2F%2E%2E%2F → 429 'Edge: Too Many Requests' (bloqueio WAF do edge, corpo texto puro — mesma resposta do UA de ferramenta)",
      semBarra: "%2E%2E (..) · %2e%2e · .%2E → o edge NORMALIZA o dot-segment e a rota vira /v1/finance/trending (sem região) → 404 envelope",
      duploCodificado: "%252E%252E → o servidor decodifica UMA vez: a região vira a string literal '%2E%2E' — região DESCONHECIDA → 200 result:[]",
    },
    methodNotAllowed: { finance: { result: null, error: { code: "Method Not Allowed",
                   description: "HTTP 405 Method Not Allowed" } } },
                                       // POST/PUT/DELETE/PATCH — SEM Allow no 405
    options: "200 + WADL application/vnd.sun.wadl+xml (Jersey 2.33): resources base http://finance-user-analytics-api-production.finance-k8s.media.yahoo.cloud:443/, resource path v1/finance/trending/US, método GET com os 12 params tipados. Allow: HEAD,GET,OPTIONS intermitente (8/12 na sessão — às vezes o edge devolve o WADL sem o header)",
    ordemDeChecagem: "a tipagem do count/keyVersion/minMarketCap é checada ANTES da resolução da região (400 ganha de 404): /trending/US?count=abc → 400, não 404",
  },

  // ==========================================================================
  // 3 · OS TRÊS MODOS DE RESPOSTA (useQuotes × format)
  // ==========================================================================
  modos: {

    // — MODO SÍMBOLOS (default: useQuotes ausente/≠true) — o índice puro
    "simbolos": {
      quando: "useQuotes=false (default do WADL) · ausente · \"1\" · \"yes\" · vazio",
      quote: { symbol: "AMZN" },      // UM campo só — fields/format/quoteType inertes
                                       //   neste modo (minMarketCap e keyVersion FUNCIONAM;
                                       //   lang tem o efeito colateral (4) do gate do TEST)
                                       //   · o índice serve a entrada de teste MINÚSCULA
                                       //   ("test" no posto 53) — o enriquecimento de
                                       //   cotação do modo quotes a normaliza para "TEST"
                                       //   (uppercase, família v7) — única diferença de
                                       //   composição entre símbolos e quotes
      payload: "489 B com 20 símbolos · 576 B com 25",
    },

    // — MODO QUOTES FLAT (useQuotes=true, format≠"true") — o enriquecimento estilo v7
    "quotesFlat": {
      quando: "useQuotes=true com format ausente ou com valor ≠ \"true\"",
      base31: [                         // base do EQUITY: 31 campos SEMPRE presentes (ordem
                                       //   de wire). REV-10: a base é POR CLASSE —
                                       //   EQUITY 31 · ETF 28 (sem marketCap,
                                       //   sharesOutstanding, impliedSharesOutstanding)
                                       //   · CRYPTOCURRENCY 28 (sem sharesOutstanding,
                                       //   impliedSharesOutstanding, priceHint — mas
                                       //   COM marketCap) · CURRENCY 28 (= ETF) ·
                                       //   INDEX 27 (CURRENCY menos currency):
        "language", "region", "quoteType", "typeDisp", "quoteSourceName", "triggerable",
        "customPriceAlertConfidence", "trendingScore", "currency", "fulldayPrice",
        "regularMarketTime", "regularMarketPrice", "exchange", "market",
        "fullExchangeName", "marketState", "sharesOutstanding", "impliedSharesOutstanding",
        "sourceInterval", "exchangeDataDelayedBy", "exchangeTimezoneName",
        "exchangeTimezoneShortName", "gmtOffSetMilliseconds", "esgPopulated", "tradeable",
        "cryptoTradeable", "hasPrePostMarketData", "firstTradeDateMilliseconds",
        "priceHint", "marketCap", "symbol",
      ],                               // valores FLAT (números/strings soltos). O bloco
                                       //   currency/sharesOutstanding/impliedSharesOut-
                                       //   standing/marketCap SÓ existe no comportamento
                                       //   v2 — não vinha no pré-mudança (bloco 11).
                                       //   marketCap EQUITY/CRYPTO têm VALOR; nas
                                       //   classes que NÃO o incluem o campo é
                                       //   AUSENTE (nem null)
      satelites: "campos pedidos em fields e suas famílias somam a isto (bloco 4)",
    },

    // — MODO QUOTES RAW/FMT (useQuotes=true E format="true") — a serialização estilo v6
    "quotesRawFmt": {
      quando: "useQuotes=true & format=exatamente \"true\" (minúsculo)",
      base30: "a MESMA base (da classe) menos esgPopulated — 30/27/27/27/26 por classe — e esgPopulated é IRRECUPERÁVEL: pedir fields=esgPopulated neste modo não devolve o campo (o format=true o remove na serialização, não na projeção). Ordem de chaves DIFERENTE da flat (ordem do serializador v6: fullExchangeName → impliedSharesOutstanding → symbol → gmtOffSetMilliseconds → language → …); trendingScore vira {raw, fmt}",
    },

    // — o DUMP (fields= vazio) — projeção completa
    "dump": {
      quando: "useQuotes=true & fields= (string VAZIA — o default \"symbol\" do WADL não conta: fields PRESENTE e vazio)",
      campos: "POR CLASSE (REV-10): EQUITY 89 campos no modo flat (88 no raw/fmt — esgPopulated de novo) · ETF 70 · CRYPTOCURRENCY 71 · CURRENCY 62 · INDEX 62 — a base + TODO o vocabulário de uma vez: famílias 52w completas, pre/post market, bid/ask/sizes, volumes, EPS/dividendos/PE, medias 50d/200d, earnings timestamps, messageBoardId, displayName, averageAnalystRating, corporateActions… (inventário integral no script rev7_j_wadl.py). Campos EXCLUSIVOS por classe no dump: ETF +netAssets · +netExpenseRatio · +trailingThreeMonthNavReturns · +trailingThreeMonthReturns · +ytdReturn (a família de fundos — TEST os traz com valores reais, mais evidência de que é ETF de verdade) · CRYPTOCURRENCY +circulatingSupply · +maxSupply · +totalSupply · +volume24Hr · +volumeAllCurrencies · +coinImageUrl · +coinMarketCapLink · +fromCurrency · +toCurrency · +lastMarket · +startDate · +logoUrl (quirk: para CRYPTO o logoUrl do dump é a URL do coinmarketcap, igual ao coinImageUrl — NEM brands NEM mysterio). Campos condicionais aparecem por quote: dividendRate 1/5 · dividendsDate 2/5 · trailingPE 2/5 (só EPS>0) · earningsCallTimestamp* 4/5",
    },

    invariantesEntreModos: {
      job: "jobTimestamp · startInterval · keyVersion idênticos nos 3 modos (mesmo snapshot de analytics — o enriquecimento de cotação é que muda)",
      ordenacao: "quotes SEMPRE por trendingScore DESC (verificado em todas as capturas, com e sem filtros)",
      count: "o campo count ecoa o efetivo; result:[{count:0,quotes:[],jobTimestamp,…,keyVersion}] quando o FILTRO zera a lista (quoteType=ETF) — distinto do result:[] do count=0/região vazia",
    },
  },

  // ==========================================================================
  // 4 · VOCABULÁRIO DE fields E SATÉLITES (gatilhos testados 1 a 1)
  // ==========================================================================
  fieldsSatelites: {

    // — FAMÍLIAS: pedir um membro materializa os demais
    familias: {
      "regularMarketChange":       "→ +fulldayChange · +regularMarketPreviousClose (o change puxa o close anterior de que deriva)",
      "regularMarketChangePercent": "→ +fulldayChangePercent (par fixo)",
      "fulldayPrice":              "→ +preMarketPrice · +preMarketTime · +postMarketPrice · +postMarketTime (o preço estendido puxa os 4 do leilão)",
      "fulldayChange | fulldayChangePercent": "→ CASCATA-13: +regularMarketChange · +regularMarketChangePercent · +fulldayChange(Percent) · +regularMarketPreviousClose · +preMarket{Change,ChangePercent,Price,Time} · +postMarket{Change,ChangePercent,Price,Time} — o gatilho MAXIMAL (é por isso que o loader, que pede o trio fullday, recebe os 8 campos de leilão)",
      "logoUrl":                   "→ +companyLogoUrl (par sempre; logoUrlDarkMode só via useLogoDevLogo — bloco 7)",
      "fiftyTwoWeekHigh | regularMarketDayHigh": "→ família High-4: +regularMarketDayHigh · +fiftyTwoWeekHighChange · +fiftyTwoWeekHighChangePercent · +fiftyTwoWeekHigh (a MESMA coesão de famílias do [marketSummary](v6_finance_quote_marketSummary.md))",
      "fiftyTwoWeekLow | regularMarketDayLow": "→ família Low-4 (espelho da High)",
      "regularMarketDayRange | fiftyTwoWeekRange": "→ +AMBAS as famílias 4 + os 2 ranges (10 campos no total)",
      "epsTrailingTwelveMonths ↔ trailingPE": "par bidirecional (pedir um traz o outro)",
      "forwardPE":                 "→ +epsForward",
      "bookValue":                 "→ +priceToBook",
      "fiftyDayAverage":           "→ +fiftyDayAverageChange · +fiftyDayAverageChangePercent (família-3)",
      "preMarketPrice":            "→ +preMarketTime (par preço→carimbo)",
      "postMarketPrice":           "→ +postMarketTime",
    },

    // — CAMPOS SIMPLES (viram sozinhos, sem satélite): shortName · longName ·
    //   regularMarketOpen · regularMarketVolume · regularMarketPreviousClose · bid · ask ·
    //   displayName · averageAnalystRating · averageDailyVolume10Day · priceHint é base…
    //   circulatingSupply (REV-10: era listado como ignorado — ERRADO: é vocabulário
    //   CRYPTO-ONLY — fields=circulatingSupply materializa SÓ nas quotes
    //   CRYPTOCURRENCY (ETH-USD → 122148376) e é inerte nas demais classes,
    //   como no [quote v7](v7_finance_quote.md))

    // — DISPONIBILIDADE DOS CAMPOS-CHAVE POR CLASSE (REV-10, verificado em base /
    //   fields explícito / dump — a classe CURRENCY existe na lista US (MXN=X) e
    //   FUTURE nunca foi observada em nenhuma das 37 regiões do censo):
    //     campo                        EQUITY   ETF    CRYPTO   CURRENCY  INDEX
    //     symbol                       ✅base   ✅base  ✅base    ✅base    ✅base
    //     trendingScore                ✅base   ✅base  ✅base    ✅base    ✅base
    //     regularMarketPrice           ✅base   ✅base  ✅base    ✅base    ✅base
    //     regularMarketChangePercent   — (só via fields/dump, todas as classes)
    //     marketCap                    ✅base   —      ✅base    —         —
    //     sharesOutstanding            ✅base   —      —        —         —
    //     circulatingSupply            —        —      ✅fields/dump —    —

    // — FORA DO VOCABULÁRIO (pedidos e IGNORADOS):
    ignorados: [
      "underlyingSymbol",   // o right rail pede nos fields 10 — NUNCA volta para EQUITY/ETF/CRYPTO
                            //   do trending (é campo de FUTURE/OPTION do [quote v7](v7_finance_quote.md))
      "volume",             // o nome certo é regularMarketVolume
      "assetClass", "headSymbol", "contractSymbol",
      "logoUrlDarkMode",    // não é pedível — só o useLogoDevLogo=true o materializa
      "qualquerNomeInventado",
    ],

    regrasDeParse: {
      caixa: "case-SENSITIVE e grafia exata — ShortName · SHORTNAME · shortname são silenciosamente ignorados",
      trim: "só nas BORDAS do valor INTEIRO: \" shortName \" resolve; \"shortName, longName\" PERDE o longName (espaço interno após vírgula não é trimado)",
      duplicatas: "colapsam (shortName,shortName,longName ≡ shortName,longName)",
      vazios: "elementos vazios pulam (shortName,,longName resolve os dois)",
      desconhecidos: "omitidos no meio sem afetar os válidos (shortName,unknownX,longName resolve os dois)",
      separador: "vírgula é o único — shortName;longName é UM nome inválido (ignorado inteiro)",
      paramRepetido: "fields=a&fields=b → só o PRIMEIRO vale",
    },
  },

  // ==========================================================================
  // 5 · QUOTETYPE — o modelo regional vs pools globais
  // ==========================================================================
  quoteType: {
    ativacao: "SÓ com useQuotes=true — no modo símbolos o param é INERTE (ETF&count=25 sem useQuotes devolve a lista mista inteira)",
    reconhecidos: {
      EQUITY: "filtra a lista DA REGIÃO pelo tipo e o count corta o SUB-RANKING resultante (US hoje: 50 dos 53; TW: 4 dos 5). Case-insensitive (equity ≡ Equity — o hub de mercados manda \"equity\" minúsculo). REV-10: a FONTE depende do minMarketCap — sem mmc, filtra a lista PUBLICADA (50); com mmc PRESENTE (mesmo =0), filtra a INTERNA (EQUITY+mmc=0 → 54, com os 4 nano caps extras — bloco 6)",
      CRYPTOCURRENCY: "POOL GLOBAL — ignora a região do path por completo: US, TW, BR, AU e até regiões INEXISTENTES (XX, ZZ) devolvem o mesmo [ETH-USD]. Filter-THEN-slice: count=1 já devolve o #1 do pool de cripto (ETH-USD no posto 1, embora ocupe o posto 52 do ranking geral servido)",
      ETF: "POOL GLOBAL idem — toda região devolve o MESMO [TEST] (US, TW, BR e até regiões INEXISTENTES — XX, ZZ; a TW tem um ETF regional DE VERDADE, 0050.TW no posto 5, que o filtro IGNORA). TEST é um ETF real — a hidratação resolve shortName \"YieldMax TSLA Performance & Dis…\" — e não um fixture sintético como o nome sugere: os comportamentos atípicos (índice minúsculo \"test\", gate por lang, posto interno) são do pipeline de analytics, não do instrumento. O item só aparece quando count ≥ o posto INTERNO dele no pool: TEST serve no posto 53 da lista mas só aparece com count ≥ 57 (varredura 40–60: 0 até 56, 1 de 57 em diante — reconfirmado na REV-9) — o ranking interno do filtro não é o ranking servido. O pool do filtro IGNORA o gate do lang: quoteType=ETF&lang=pt-BR devolve [TEST] embora o lang ≠ en-US o exclua da lista mista (caminhos de backend distintos)",
    },
    ignorados: "todo o resto — CRYPTO (a forma curta!) · INDEX · CURRENCY · MUTUALFUND · FUTURE · OPTION · NONE · STOCK · MUTUAL · listas (EQUITY,ETF) · com espaço (EQUITY%20ETF) · vazio — devolve a lista MISTA completa sem filtro nenhum",
    composicao: "compõe com minMarketCap (EQUITY + minMarketCap=100B → 12 hoje, os 14 do filtro menos MXN=X e ETH-USD)",
    armadilha: "não confiar em quoteType para enumeração regional: os pools ETF/CRYPTOCURRENCY são globais e a lista de uma região específica só é fiel via EQUITY (ou sem filtro)",
  },

  // ==========================================================================
  // 6 · PARAMS OCULTOS — minMarketCap e keyVersion (só no WADL, em cliente nenhum)
  // ==========================================================================
  ocultos: {
    minMarketCap: {
      oQueFaz: "corta da lista os itens com capitalização abaixo do valor (em USD). Funciona nos DOIS modos — símbolos E quotes — e PRESERVA a ordenação por trendingScore DESC (varrido com minMarketCap=100B: 14 itens, todos DESC)",
      listaInterna: "DESCOBERTA REV-10 — o param presente MUDA A FONTE: sem ele, o default serve a lista PUBLICADA (53 itens na janela US); com ele (QUALQUER valor ≥ 0), a fonte passa a ser a lista INTERNA do job — 57 itens na janela US, com 4 nano caps que a publicada retém de fora (WORX · VVOS · SXTC · NCPL, todos EQUITY): mmc=0 → 57 · mmc=1 → 57 · mmc=2/1000 → 57 · mmc=1e9 → 46 · mmc=100B+EQUITY → 15. A mensagem do 400 (\"0 to disable\") diz que 0 desliga — na prática 0 EXPÕE a integral interna (não volta aos 53 da publicada). O quoteType enxerga a fonte que o mmc seleciona: EQUITY puro → 50 (publicada), EQUITY+mmc=0 → 54 (interna); os POOLS (ETF/CRYPTOCURRENCY) NÃO são afetados pelo mmc (ETF+mmc=0+count=5 → 0; o limiar ≥57 persiste). Nas outras regiões a interna ≡ publicada (TW+mmc=0 → 5; BR+mmc=0 → 1 — ^BVSP, marketCap null, passa)",
      validacao: "inteiro não-negativo: abc · -1 · 2.5 → 400 \"Invalid minMarketCap '…': expected a whole non-negative number, 0 to disable\" (mensagem INTEIRA com o sufixo — REV-10; DISTINTA do count, que dá \"Parameter=count has an invalid type\" — o count é xs:int do Jersey, o minMarketCap é string validada à mão; e o count aceita negativo, o minMarketCap não)",
      vazio: "minMarketCap= (VAZIO) ≡ sem filtro ≡ default — serve a PUBLICADA (53; distinto do mmc=0 que serve a INTERNA — 57)",
      quirkCapitalizacaoInterna: "o filtro usa uma capitalização INTERNA do pipeline que NÃO é o campo marketCap servido: com minMarketCap=100B passaram GME-WT (warrant, marketCap:null na resposta!) e MXN=X (CURRENCY, marketCap:null!) — itens SEM marketCap no payload cruzam o filtro; quem lê o campo devolvido para inferir o corte se engana",
    },
    keyVersion: {
      valores: "v2 | v3 — o default é v2 (o WADL declara \"\" e o servidor resolve v2; o campo keyVersion da resposta ecoa o servido)",
      invalido: "v1 · garbage → 400 \"Invalid keyVersion 'v1': allowed values are [v2, v3]\" — a mensagem EXPÕE a lista permitida",
      v3: "mesma FORMA de resposta (bases 31/30, satélites, dump 89 idênticos) mas uma GERAÇÃO DE SNAPSHOT MAIS FRESCA: na mesma janela de observação o v2 servia o job das 22:11 UTC e o v3 o job das 23:03 UTC (startInterval 21:00 vs 22:00) — símbolos já divergiam (STLD↔DDOG na cauda). Sem cliente do corpus usando; capacidade latente",
    },
  },

  // ==========================================================================
  // 7 · LOGOS — brands estáticos vs serviço LogoDev (mysterio)
  // ==========================================================================
  logos: {
    semUseLogoDevLogo: "logoUrl pedido → +companyLogoUrl, mas o VALOR só existe para as empresas com marca no catálogo estático (s.yimg.com/lb/brands/150x150_*.png) — ~1–4 das quotes (AMZN, MMM, ACN, NKE, MAT, AVGO…); as demais vêm SEM os campos de logo (a captura default de 1/out do usuário: 4/25 com logo)",
    comUseLogoDevLogo: "useLogoDevLogo=true (case-insensitive; \"1\" NÃO ativa) E logoUrl em fields → o par logoUrl+companyLogoUrl vem para ~9/10 das quotes via serviço LogoDev (s.yimg.com/lo/mysterio/api/<hash>/finance/resizefill_w150_h150/…) E acrescenta logoUrlDarkMode (a variante dark do mysterio) — o gatilho é o MESMO do cliente finSearch, que só serializa o param quando o fields inclui logoUrl",
    imgParams: "imgLabels/imgWidths/imgHeights (declarados no WADL) são INERTES — mesmos URLs com e sem o trio (como no [quote v7](v7_finance_quote.md), o tamanho é sempre 150×150)",
  },

  // ==========================================================================
  // 8 · O JOB DE ANALYTICS — jobTimestamp, startInterval e trendingScore
  // ==========================================================================
  job: {
    startInterval: "YYYYMMDDHHMM em UTC, SEMPRE com minutos 00 — a hora de INÍCIO da janela do job que gerou o snapshot (3 amostras independentes + 2 capturas do usuário, todas casando: job 21:02→si 20:00 · job 20:12→si 19:00 · job 22:11→si 21:00)",
    jobTimestamp: "epoch-ms do TÉRMINO do mesmo job — cai sempre na hora SEGUINTE à startInterval (~50–72 min depois dela, ou seja, 2–72 min dentro da hora seguinte). Estado transitório observado 2x na REV-9 (23:31 e ~23:41 UTC): janelas em que respostas FRESCAS (cache miss) vêm com jobTimestamp: 0 — quotes/count normais — e minutos depois o mesmo URL volta ao job anterior (leitura mid-write durante a promoção do job; no mesmo período o keyVersion=v3 serviu o job das 23:03 normalmente — não é outage geral)",
    cadencia: "jobs ~horários: o mesmo snapshot (jobTimestamp idêntico) é servido por todos os modos e URLs dentro da janela (cache max-age=300 + swr=30 — rajada de 6 chamadas: 1 geração só); US e TW saíram do MESMO job (jobTimestamps a 54 ms de distância — um único passe escreve as regiões)",
    trendingScore: {
      flat: "número solto (ex.: 32.61354380336889) — é a CHAVE de ordenação das quotes, sempre DESC",
      rawFmt: "{raw, fmt} no modo format=true — e o fmt é um QUIRK de formatação: fmt = raw×100 com separador de milhar e sufixo % (raw 32.61 → \"3,261.35%\") — o formatador trata o score como razão percentual. Quem consome o fmt deve DIVIDIR por 100 (ou ignorá-lo e usar raw); os 3 clientes oficiais nem pedem o campo",
    },
    dadosDeCotacao: "os campos de preço/nome das quotes são do MESMO pipeline de cotação do [quote v7](v7_finance_quote.md) (fonte mista — quoteSourceName \"Nasdaq Real Time Price\" para AMZN no dump, \"Delayed Quote\" nos demais), mas o snapshot de SÍMBOLOS e SCORES é do user-analytics: um refresh de cotação não muda o ranking nem o jobTimestamp",
  },

  // ==========================================================================
  // 9 · REGIÕES — o censo do path (37 testadas em 19/out/2026)
  // ==========================================================================
  regioes: {
    regra: "case-insensitive (us ≡ Us ≡ US — reconfirmado REV-9) · barra final tolerada · o region da QUERY é inerte PARA TUDO (REV-9: path=US?region=BR devolve a lista US E o campo region das quotes continua \"US\"; path=TW?region=TW idem — o param nem altera o campo homônimo dos itens) · o campo region das quotes é SEMPRE \"US\" (default do enrichment, não reflete a região do path NEM da query — TW devolve region:\"US\")",
    comLista: {                       // contagens dinâmicas por job — valores da janela:
      "US": "53 itens — 50 EQUITY + MXN=X (CURRENCY) + ETH-USD (CRYPTOCURRENCY) + TEST (ETF, no posto 53, minúsculo 'test' no índice de símbolos); bolsas NYQ 23 · NMS 13 · NGM 10 · NCM 3 · OQB/CCY/CCC/BTS 1 · com lang efetivo ≠ en-US: 52 itens (TEST excluída pelo gate do lang — bloco 1)",
      "TW": "5 itens — 4 EQUITY (1815.TWO 2327.TW 2409.TW 6770.TW) + 1 ETF (0050.TW)",
      "CA": "2 itens — AMZN + SPCX",
      "BR": "1 item — ^BVSP (INDEX)",
      "GB": "1 item — ^FTSE", "DE": "1 item — MU", "FR": "1 item — NVDA", "HK": "1 item — MU",
      "IT": "1 item — NVDA", "ES": "1 item — MU", "SG": "1 item — ^STI",
      "AU": "1 item — BTC-USD (CRYPTOCURRENCY)", "NZ": "1 item — BTH-USD",
    },
    resultVazio: "JP · IN · KR · MX · ID · MY · TH · ZA · NL · SE · CH · AT · BE · DK · FI · NO · PL · PT · TR — regiões VÁLIDAS sem lista de trending (result:[]) · e também qualquer região DESCONHECIDA (XX · ZZ · usa · \"US \" com espaço — indistinguível da região válida vazia)",
    semRegiao: "/v1/finance/trending e /v1/finance/trending/ → 404 (o único 404 do endpoint)",
    nota: "a cobertura de regiões diverge dos 31 mercados do [markettime](v6_finance_markettime.md) (lá JP/IN/KR existem) e dos 14 locales do [market-info](ws_market-info_v1_finance_markets_ids.md) — o trending cobre 13 regiões com lista no dia da medição; as listas regionais são de conteúdo misturado e peculiar (DE→MU, AU→BTC-USD — são os dados do job, não curadoria)",
  },

  // ==========================================================================
  // 10 · CLIENTES OFICIAIS — os três contratos completos
  // ==========================================================================
  officialClient: {

    // — LOADER loadTrendingTickers (chunks/loadTrendingTickers.CJx16Bjq.js, função l;
    //   perfLabel "loadTrendingTickers") — o store "trendingTickers" do hub:
    "loader": {
      "wire": "apiFetch (approval.BsApzrJF.js): pathname /v1/finance/trending/{session.region||\"US\"} · crumb: true (crumb na query via transporte, SE o store tem valor) · query: count (default 25) + fields = [logoUrl, longName, shortName, regularMarketChange, regularMarketChangePercent, regularMarketPrice, fulldayPrice, fulldayChange, fulldayChangePercent (…F_1 = Object.values(EXTENDED_HOURS_FIELD_MAP) de support_agent.Cd9DzWFk.js), …fields extras do chamador].join(\",\") + format=\"true\" + useQuotes=String(useQuotes) + quoteType (default \"ALL\") + lang/region da sessão injetados pelo transporte",
      "flags": "useLogoDevLogo=\"true\" só quando a feature de sessão enableLogoDevLogo está acesa; headers x-cache:\"1\" + x-cache-ttl:\"30000\" (30 s) só quando enableTrendingTickersCaching — INERTES no servidor (respostas idênticas com/sem; são controle de cache do lado do browser)",
      "store": "cache client-side: se trendingTickersStore já tem ≥count itens e force=false, NÃO chama a rede; updateTrendingTickers(result[0].quotes) no sucesso; setError(error) quando finance.error ou result ausente",
      "chamadoresComParams": [
        "hub de mercados (nodes/94.sNWH2W9M.js): { quoteType: \"equity\" (minúsculo — case-insensitive no servidor), silent: true, count: 20, force: true, critical: false } → seção trendingStocks",
        "painel de trending (chunks/aiFullDayBasis.CF3hk5yx.js): { silent: false } — tudo default (count 25, ALL, format, fields 9)",
        "páginas de comunidade (chunks/communityPages.C4_wMpfk.js): { } — defaults",
      ],
    },

    // — RIGHT RAIL DA PÁGINA DE GRÁFICOS (chunks/finChartRightRail.C4PpSIrs.js, spec
    //   na 2ª posição do orquestrador [recent-quotes · ESTA · investment-ideas · market-info · …]):
    "rightRail": {
      "wire": "path `v1/finance/trending` + (chart.config.region COM barra — \"/US\" no fallback) · query: formatted=\"true\" (INERTE no servidor — o que ativa o modo quotes é o useQuotes) · count=\"5\" · fields = zt+Kt = symbol,longName,shortName,underlyingSymbol,regularMarketPrice,regularMarketChange,regularMarketChangePercent,fulldayPrice,fulldayChange,fulldayChangePercent (10; underlyingSymbol nunca volta — bloco 4) · useQuotes=\"true\" · quoteType=\"EQUITY\"",
      "fetch": "m_1(`${g_1()}/${path}?${s_1(query)}`) — host sorteado no pool do chartStatic (query1/query2), SEM crumb/headers",
      "handler": "o.finance.result[0].quotes alimenta a seção TRENDING_TICKERS (\"Trending Tickers\", link /trending-tickers); os preços lidos FLAT (rest.fulldayPrice etc.)",
    },

    // — CAIXA DE BUSCA finSearch (webcore/srchjs/1.2.50/js/finSearch.modern.js, função W):
    "finSearch": {
      "wire": "`${host}/v1/finance/trending/{region}?` + URLSearchParams em ORDEM de inserção: count (default 5) → [SE fields: useQuotes=true → fields → region → lang → (useLogoDevLogo=true SÓ se fields inclui logoUrl)]. Sem format, sem quoteType, sem crumb; timeout 2000; beacon finSearchTrending; errorMsg \"Trending Tickers failed\"",
      "resposta": "finance.error preenchido → throw {status: 500} LOCAL; senão result[0].quotes",
      "chamadores": [
        "fetchRecommendations (type \"quote\" das páginas de cotação): fields \"shortName,longName,logoUrl,regularMarketChangePercent,regularMarketPrice\" (+\",fulldayPrice,fulldayChangePercent\" com enableExtendedHours) · region/lang do finSearchContext · useLogoDevLogo do config · count=recommendCount — É EXATAMENTE a URL da captura do usuário de 24/set (bloco 11)",
        "fetchTopCrypto (seção de cripto do dropdown): fields \"symbol,shortName,regularMarketPrice,regularMarketChangePercent,priceHint\"(+fullday) · count=25 FIXO — sem quoteType (a lista geral, não o pool CRYPTOCURRENCY do bloco 5)",
      ],
    },
  },

  // ==========================================================================
  // 11 · MIGRAÇÃO keyVersion v2 — o que mudou entre 1/out e 19/out/2026
  // ==========================================================================
  migracaoV2: {
    evidencia: "as duas capturas do usuário: 24/set (finSearch com useLogoDevLogo — 34 campos flat) e 1/out (format=true com fields 5 — 39 campos raw/fmt, count 25); ambas SEM keyVersion na resposta",
    oQueMudou: [
      "o DEFAULT (sem useQuotes) parou de servir o snapshot completo: as capturas pré-v2 de uma chamada sem params traziam 25 quotes com 39 campos raw/fmt; hoje o default serve SÓ {symbol} (o WADL declara fields=\"symbol\" como default — coerente com o novo desenho)",
      "count default caiu de 25 para 20 (WADL xs:int default=20; as capturas pré-v2 ecoavam 25)",
      "a base flat GANHOU o bloco currency · sharesOutstanding · impliedSharesOutstanding · marketCap (a captura de 24/set não os tinha: 34 campos vs 38 na replicação idêntica de hoje)",
      "keyVersion: \"v2\" passou a acompanhar TODO sucesso (e virou param de query com v2|v3)",
    ],
    compatibilidade: "as duas capturas continuam REPRODUZÍVEIS hoje com params explícitos: a de 24/set byte-a-byte em campos (a URL finSearch idêntica devolve +4 campos de base); a de 1/out com ZERO diff de conjunto de campos via count=25&useQuotes=true&format=true&fields=shortName,longName,logoUrl,regularMarketChange,regularMarketChangePercent&lang=en-US&region=US (39 campos exatos — reprodução verificada; só os VALORES mudam, a lista é do dia)",
    nota: "consumidores que liam o default completo (sem useQuotes) quebraram na migração; os três clientes do corpus já mandavam useQuotes=true e foram poupados",
  },
}
```

## Limites e políticas de uso

| Aspecto | Comportamento |
| :--- | :--- |
| User-Agent | Obrigatório agente de navegador: `Python-urllib/3.x` · `python-requests` · `curl` recebem `429 Edge: Too Many Requests`; UA **ausente/vazio/`Wget`** recebem `429 Too Many Requests\r\n` (corpo distinto com CRLF — REV-10) — mesma política dos demais endpoints ([marketSummary](v6_finance_quote_marketSummary.md) · [quote v7](v7_finance_quote.md) · [markettime](v6_finance_markettime.md) · [quoteType](v1_finance_quoteType.md) · [market-info](ws_market-info_v1_finance_markets_ids.md)) (bloqueio por assinatura de agente, não por volume — burst de 25 cache-miss: 25×200). |
| Autenticação | Nenhuma — anônimo por definição; crumb na query ou no header `x-crumb`, válido ou não, é aceito e ignorado (o loader envia `crumb: true`, sem enforcement). |
| Erros | Quatro caminhos + o WAF: `404` (path sem região / segmento extra / dot-segment sem barra `..` normalizado) · `400` ×3 (count não-inteiro · keyVersion inválido · minMarketCap inválido — a checagem de tipos vence a resolução da região; code `Bad Request` no envelope) · `405` de método (envelope `finance`, SEM Allow) · `429` (UA de ferramenta → `Edge: Too Many Requests`; UA ausente/vazio/Wget → `Too Many Requests\r\n`; path traversal `../` na região → `Edge: Too Many Requests` — WAF). NÃO há 403 nem 500/503 observados (~390 requisições no total). Lista vazia NÃO é erro: `result: []` para count 0/negativo, região sem trending, região desconhecida e região duplo-codificada (`%252E`). |
| Cache | `public, max-age=300, stale-while-revalidate=30` — 5,5 min de janela por URL em TODOS os modos; o snapshot de analytics muda no ritmo do job (~horário), então o cache na prática alinha com a cadência do dado. |
| Cardinalidade | count 1..tamanho da lista (publicada 53 / interna 57 na janela US de 19/out — a interna acessível via `minMarketCap` presente; cap automático); sem paginação; o pool completo EQUITY era 50 (54 na interna), CRYPTOCURRENCY 1 e ETF 1 (globais, não afetados pelo mmc); lista TW tinha 5 (interna ≡ publicada), BR 1 — o tamanho é dinâmico por região e por hora do job. |
| Payload | 38 B (vazio) · 576 B (índice 25 símbolos) · 6,5–7,9 KB (right rail / finSearch × 5) · 19,8–25,2 KB (bases flat/raw-fmt POR CLASSE 31-27/30-26 × 25) · 44,3 KB (loader 47 campos × 25) · 63 KB / 103 KB (dump EQUITY 89/88 × 25 — dumps menores nas outras classes: ETF 70 · CRYPTO 71 · CURRENCY/INDEX 62) — o enriquecimento custa 30–180× o índice puro: quem só precisa dos símbolos deve ficar no modo default. |
| Idempotência | Dentro da janela do job: total (mesmo jobTimestamp/símbolos/scores para toda URL igual); entre horas: a lista, os scores e o jobTimestamp mudam (ranking de analytics). `formatted`/`img*`/`crumb`/desconhecidos não alteram nada; `fields`/`format`/`useQuotes`/`quoteType`/`minMarketCap`/`keyVersion`/`lang`/`useLogoDevLogo`/`count` são os 10 params com efeito real. |
