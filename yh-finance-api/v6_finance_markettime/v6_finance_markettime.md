# `GET /v6/finance/markettime`

> **Data de atualização:** 2026-10-20 · constantes deste endpoint validadas ao vivo contra `query1.finance.yahoo.com` (2026-10-18, domingo ~03:00 UTC — mercados fechados; 31 regiões, 44 locales e todos os campos de item verificados na mesma janela; a contagem regressiva `duration` não é observável nessa janela e está documentada pelo código dos dois clientes oficiais · mesma data, 03:33 UTC: segunda janela com as 31 regiões revalidadas, ordem de chegada dos campos confirmada única, e material complementar cotejado — mapa de classes `hE` 9→3 do SvelteKit, `duration` com valores string arredondados ao minuto acima, e captura de terça 2026-09-29 do usuário cross-validada contra as sessões do bloco 4 · 2026-10-19, ~21:51–21:57 UTC, pós-mercado US: revalidação completa — 31/31 regiões, localização íntegra, suíte do usuário 20/20 e `duration` observada ao vivo em 13 mercados WILL_OPEN/WILL_CLOSE, com o arredondamento ao minuto acima confirmado caso a caso).

---


Relógio de pregão do Yahoo Finance: devolve **o estado de um único mercado de ações** — aberto ou fechado, o instante de geração, a próxima abertura e o próximo fechamento (com feriados locais já descontados) e uma frase de exibição pronta e localizada. É o dado por trás da pílula "market time" do dock de cotações (loader React, bloco 6) e do banner de status das páginas de notícias (elemento webcore `fin-market-time`, bloco 6) — **não devolve cotações**: para preços existem o [marketSummary](v6_finance_quote_marketSummary.md) e o [quote v7](v7_finance_quote.md). O mercado devolvido é escolhido **exclusivamente pelo `region`** (31 mercados, bloco 4) — um item, sempre. Não há seleção por símbolo, bolsa ou fuso: `symbol`, `venue`, `exchange`, `timezone`, `market`, `id` e afins são ignorados (bloco 1). Contrastes com os endpoints irmãos: o `region` aqui tem tabela própria muito mais ampla que as 14 do [marketSummary](v6_finance_quote_marketSummary.md) (31 vs 14), e o `lang` reconhecido é o mesmo conjunto, mas apenas 11 locales têm strings de exibição próprias — o resto ecoa e permanece em inglês.

| | |
| :--- | :--- |
| Método | `GET` — aceita também `HEAD` e `OPTIONS` (este expõe `Allow: HEAD,GET,OPTIONS`); demais métodos → `405` |
| Hosts | `query1` · `query2` (`.finance.yahoo.com` — ambos servem o mesmo backend, identificado pelo header de resposta `x-envoy-decorator-operation: finance-market-info-api--mtls-production-usw2.finance-k8s:4080/*`) |
| Caminho | `/v6/finance/markettime` |
| Autenticação | Anônima — responde `200` sem cookie e sem crumb; crumb errado, ausente ou em outro vetor é igualmente aceito e ignorado |
| User-Agent | Agente de navegador obrigatório — `curl`/`Python-urllib` e afins recebem `429 Edge: Too Many Requests` |
| Cache de borda | `public, max-age=60, stale-while-revalidate=60` — janela total de ~120 s por URL; o campo `time` congela no instante de geração (prova no bloco 3) |
| Payload típico | ~0,4 KB (item único completo, 438 B observado em `en-US`) |

## Autenticação e User-Agent

A requisição é anônima, como no marketSummary: todas as combinações de cookie/crumb devolvem `200` com corpo idêntico — o loader React envia cookies por `credentials: "include"` (pipeline comum às APIs de dados), mas **não envia crumb**; o webcore das notícias envia cookies e nada mais. Nenhum dos dois vetores de crumb é necessário.

```bash
# Chamada canônica (webcore de notícias — só lang e region):
curl -s -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/138.0.0.0" \
  "https://query1.finance.yahoo.com/v6/finance/markettime?lang=en-US&region=US"

# Chamada do loader React (fidelidade — formatted e key entram na query, sem efeito):
curl -s -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/138.0.0.0" \
  "https://query1.finance.yahoo.com/v6/finance/markettime?formatted=true&key=finance&lang=pt-BR&region=BR"
```

## Estrutura do endpoint — parâmetros, item de mercado e constantes

Estrutura declarativa pura (JSON5 comentado), sem nenhuma função ou lógica executável de JavaScript: parâmetros da requisição, o item de mercado devolvido, o envelope, a tabela de mercados por região, o vocabulário de localização e o contrato dos dois clientes oficiais.

```json5
{
  // ==========================================================================
  // 1 · PARÂMETROS DA REQUISIÇÃO
  // ==========================================================================
  request: {
    method: "GET",
    path: "/v6/finance/markettime",
    params: {
      region: "US",                    // Seleciona O mercado devolvido (um item). Padrão: "US".
                                       //   31 mercados válidos (tabela MARKETS, bloco 4) ·
                                       //   case-insensitive ("br" == "BR", "jP" == "JP") ·
                                       //   vazio ≡ ausente · qualquer outro valor (CH, ZA, CL, CO,
                                       //   PE, SA, AE, ID, PH, IE, AT, BE, PL, CZ, HU, RO, XX, ZZ,
                                       //   300 caracteres, símbolos) cai silenciosamente no mercado
                                       //   "us" · ÚNICO seletor — nenhum outro parâmetro muda o item
      lang: "en-US",                   // Locale de exibição. Padrão: "en-US" (idem para não
                                       //   reconhecidos). Localiza "name" e "message" (só 11 locales
                                       //   têm strings próprias — lista em LOCALIZATION, bloco 5) e
                                       //   ecoa no envelope "finance.lang" e no header
                                       //   "content-language" (mesmo quando NÃO localiza: ja-JP ecoa
                                       //   e permanece em inglês). Normaliza aliases (bloco 5).
                                       //   NUNCA muda o mercado devolvido
      formatted: "true",               // INERTE — true ≡ false ≡ omitido (comparados byte a byte;
                                       //   a resposta é integral de strings, nada a formatar). O
                                       //   loader React envia "true" por convenção do pipeline
      key: "finance",                  // Eco do cliente — chave do config de serviços (roteamento
                                       //   de host/nimbus no lado do chamador, bloco 6). O servidor
                                       //   ignora o valor: key=outra-chave → mesma resposta
      // — tolerados e ignorados (todos → 200, mesma resposta):
      //   market, markets, id, ids, symbol, country, venue, exchange, timezone,
      //   yfit_market_id, crumb (correto ou errado) e qualquer parâmetro desconhecido
    },
  },

  // ==========================================================================
  // 2 · ITEM DE MERCADO (finance.marketTimes[0].marketTime[0])
  // ==========================================================================
  commonFields: {                    // ORDEM DE CHEGADA no wire (única em 31+37 capturas dominicais
                                       //   + 13 com contagem em out/2026): id, name, status,
                                       //   yfit_market_id, close, duration (quando há contagem —
                                       //   entre close e message, NÃO no fim), message, open,
                                       //   yfit_market_status, time, timezone — abaixo, os campos
                                       //   estão agrupados por função (identidade → sessão →
                                       //   fuso); note close ANTES de open na ordem crua
    "id": "us",                        // Identificador do mercado — país ISO em minúsculas ("us",
                                       //   "br", "gb"…), espelho do region pedido (quando válido)
    "yfit_market_id": "us_market",     // Id interno YFT do mercado ("<país>_market"); espaço que
                                       //   inclui também usir_market/us24_market (cartão RATES do
                                       //   [marketSummary](v6_finance_quote_marketSummary.md)) — mas aqui só o mercado-país é endereçável
    "name": "U.S. markets",            // Nome de exibição, localizado por lang (tabela de 18
                                       //   mercados com nome próprio; os 13 restantes devolvem o
                                       //   LITERAL "U.S. markets" — que também se localiza!
                                       //   region=JP&lang=pt-BR → "Mercados dos EUA" — bloco 4)
    "status": "closed",                // Estado do pregão em minúsculas — "closed"/"open". É o
                                       //   campo que o webcore compara === "open" (bloco 6)
    "yfit_market_status": "YFT_MARKET_CLOSED",
                                       // Enum canônica YFT — 9 valores observáveis no código dos
                                       //   clientes: YFT_MARKET_{CLOSED, CLOSED_EARLY, HOLIDAY,
                                       //   WILL_CLOSE, WILL_CLOSE_EARLY, WILL_CLOSE_LATE, WILL_OPEN,
                                       //   WILL_OPEN_EARLY, WILL_OPEN_LATE} — mapeada no cliente
                                       //   (statusMaps, bloco 6: classMap hE do SvelteKit +
                                       //   iconMap j do webcore). NÃO localiza
    "open": "2026-10-19T13:30:00Z",    // Abertura da sessão de referência — ISO 8601 UTC. Nos
                                       //   estados WILL_*/open aponta a PRÓXIMA sessão (feriado-
                                       //   aware: capturada num domingo, Hong Kong já apontava
                                       //   terça — 19/10 feriado local; IN pulou a terça local
                                       //   de feriado e apontou quarta, a +29,9 h — out/2026);
                                       //   em YFT_MARKET_CLOSED recém-fechado aponta a sessão
                                       //   RECÉM-ENCERRADA (US às seg 21:53Z, 1,9 h pós-close) —
                                       //   o ponteiro rola na virada do dia LOCAL (europ. ainda
                                       //   na segunda exibiam a sessão passada; Istambul/Moscou/
                                       //   Atenas/Helsinque já na terça exibiam WILL_OPEN)
    "close": "2026-10-19T20:00:00Z",   // Fechamento da mesma sessão de referência — ISO 8601 UTC (16:00 EDT
                                       //   para "us"; fechamentos com minutos ímpares são reais: AU 05:12Z,
                                       //   GR/NO 14:20Z, HK 08:10Z — leilões de fechamento)
    "message": "U.S. markets closed",  // Frase de exibição PRONTA (não é template): localizada por
                                       //   lang, com o tempo restante embutido quando há contagem
                                       //   ("…in 2 hours 30 minutes" — reescrito localmente pelos
                                       //   clientes, bloco 6). Estado "closed" de fim de semana não
                                       //   embute contagem
    "time": "2026-10-18T02:57:46Z",    // Instante de GERAÇÃO no servidor — sempre igual ao header
                                       //   Date da resposta (6/6 na revalidação out/2026) e congela
                                       //   no cache de borda (rajada de 6 chamadas à mesma URL
                                       //   devolveu 3 gerações com o mesmo time repetido em 3
                                       //   delas — 52→52→52 intercalado com gerações novas;
                                       //   header age: 0→40 na janela original, ausente na
                                       //   revalidação)
    "timezone": [{                     // Fuso do mercado — array de 1 elemento (formato Yahoo
      "dst": "true",                  //   herdado do v6): horário de verão ATIVO como STRING
      "gmtoffset": "-14400",           //   Offset em segundos como STRING ("-14400" = UTC-4)
      "short": "EDT",                 //   Abreviação vigente (com DST aplicado)
      "$text": "America/New_York"     //   Identificador IANA do fuso do pregão
    }],
    "duration": [{ "hrs": "2", "mins": "30" }],
                                       // [def: contagem regressiva] Valores como STRINGS
                                       //   decimais (mesma regra de gmtoffset/dst), parseadas
                                       //   pelos dois clientes (parseInt de [0].hrs/[0].mins).
                                       //   ARREDONDADA PARA O MINUTO ACIMA — confirmado ao vivo
                                       //   em 13 mercados (out/2026: AU 1h09/1h04 · NZ 6h09 ·
                                       //   JP 2h09 · HK 3h39 · TR/IL 8h34–54 · GR 9h34 —
                                       //   sempre ceil contra open−time; e terça 2026-09-29,
                                       //   time 03:24:55Z → abertura 13:00:00Z, 9 h 35 m 05 s
                                       //   → {"hrs":"9","mins":"36"}). REGRA: materializa
                                       //   se E só se o estado é WILL_OPEN/WILL_CLOSE (ou
                                       //   open) — as janelas de domingo não a mostravam porque
                                       //   todos os mercados estavam em CLOSED (a leitura
                                       //   antiga "todo evento a >17 h" era artefato dessa
                                       //   correlação; WILL_OPEN observado até 9 h 34 de
                                       //   antecedência); quando presente, a mensagem embute
                                       //   o tempo restante e o webcore considera o estilo
                                       //   "ativo" (status === "open" || duration truthy)
  },

  // ==========================================================================
  // 3 · ENVELOPE DA RESPOSTA
  // ==========================================================================
  responseEnvelope: {
    "finance": {
      "version": 5,                    // Versão do schema — constante em todas as sondagens
      "lang": "en-US",                 // Eco do lang pedido (posição após normalizar; content-language
                                       //   do header acompanha)
      "meta": [{ "status": "success" }],
                                       // Bloco meta padrão v6
      "marketTimes": [                 // Sempre 1 elemento em 37 capturas; ambos os clientes leem
        { "marketTime": [ /* item do bloco 2 */ ] }
                                       //   o índice [0] dos DOIS níveis
      ],
      "error": null                    // Vetor de erro previsto pelos dois clientes (finance.error →
                                       //   setError) — NUNCA materializou: nenhum input patológico
                                       //   (region de 300 caracteres, símbolos, injeção, params
                                       //   duplicados ou vazios) produziu 4xx/5xx
    }
  },

  // ==========================================================================
  // 4 · MERCADOS POR REGIÃO — ENUM DO SERVIDOR (validado ao vivo, 2026-10-18)
  // ==========================================================================
  // region → mercado devolvido. 31 válidos; demais valores → "us". Sessões abaixo capturadas num
  // domingo ~03:00 UTC (próximo pregão; HK salta para terça por feriado local de 19/10).
  MARKETS: [
    // — 18 mercados com nome próprio (en-US):
    { region: "US", id: "us",  name: "U.S. markets",      tz: "America/New_York",              open: "13:30Z", close: "20:00Z" },
    { region: "BR", id: "br",  name: "Brazil markets",    tz: "America/Sao_Paulo",             open: "13:00Z", close: "20:00Z" },
    { region: "GB", id: "gb",  name: "UK markets",        tz: "Europe/London",                 open: "07:00Z", close: "15:30Z" },
    { region: "DE", id: "de",  name: "German markets",    tz: "Europe/Berlin",                 open: "07:00Z", close: "15:30Z" },
    { region: "FR", id: "fr",  name: "France markets",    tz: "Europe/Paris",                  open: "07:00Z", close: "15:30Z" },
    { region: "IT", id: "it",  name: "Italia markets",    tz: "Europe/Rome",                   open: "07:00Z", close: "15:30Z" },
    { region: "ES", id: "es",  name: "Spain markets",     tz: "Europe/Madrid",                 open: "07:00Z", close: "15:30Z" },
    { region: "HK", id: "hk",  name: "Hong Kong markets", tz: "Asia/Hong_Kong",                open: "01:30Z", close: "08:10Z" },
    { region: "JP", id: "jp",  name: "*",                 tz: "Asia/Tokyo",                    open: "00:00Z", close: "06:30Z" },
    { region: "KR", id: "kr",  name: "Korea markets",     tz: "Asia/Seoul",                    open: "00:00Z", close: "06:00Z" },
    { region: "TW", id: "tw",  name: "Taiwan markets",    tz: "Asia/Taipei",                   open: "01:00Z", close: "05:30Z" },
    { region: "AU", id: "au",  name: "Australia markets", tz: "Australia/Sydney",              open: "23:00Z", close: "05:12Z" },
    { region: "CA", id: "ca",  name: "Canada markets",    tz: "America/Toronto",               open: "13:30Z", close: "20:00Z" },
    { region: "IN", id: "in",  name: "India markets",     tz: "Asia/Kolkata",                  open: "03:45Z", close: "10:00Z" },
    { region: "CN", id: "cn",  name: "China markets",     tz: "Asia/Shanghai",                 open: "01:30Z", close: "07:00Z" },
    { region: "MX", id: "mx",  name: "Mexico markets",    tz: "America/Mexico_City",           open: "13:30Z", close: "20:00Z" },
    { region: "SG", id: "sg",  name: "Singapore markets", tz: "Asia/Singapore",                open: "01:00Z", close: "09:00Z" },
    { region: "AR", id: "ar",  name: "Argentina markets", tz: "America/Argentina/Buenos_Aires", open: "14:00Z", close: "20:00Z" },
    { region: "NZ", id: "nz",  name: "New Zealand markets", tz: "Pacific/Auckland",            open: "21:00Z", close: "04:00Z" },

    // — 13 mercados com id/tz próprios e nome no LITERAL "U.S. markets" ("*"):
    { region: "SE", id: "se",  name: "*", tz: "Europe/Stockholm",   open: "07:00Z", close: "15:30Z" },
    { region: "TR", id: "tr",  name: "*", tz: "Europe/Istanbul",    open: "06:30Z", close: "15:00Z" },
    { region: "RU", id: "ru",  name: "*", tz: "Europe/Moscow",      open: "06:30Z", close: "16:00Z" },
    { region: "IL", id: "il",  name: "*", tz: "Asia/Jerusalem",     open: "06:50Z", close: "14:30Z" },
    { region: "MY", id: "my",  name: "*", tz: "Asia/Kuala_Lumpur",  open: "01:00Z", close: "09:00Z" },
    { region: "TH", id: "th",  name: "*", tz: "Asia/Bangkok",       open: "03:00Z", close: "09:30Z" },
    { region: "VN", id: "vn",  name: "*", tz: "Asia/Bangkok",       open: "02:00Z", close: "08:00Z" },
    { region: "PT", id: "pt",  name: "*", tz: "Europe/Lisbon",      open: "08:00Z", close: "16:30Z" },
    { region: "GR", id: "gr",  name: "*", tz: "Europe/Athens",      open: "07:30Z", close: "14:20Z" },
    { region: "DK", id: "dk",  name: "*", tz: "Europe/Copenhagen",  open: "07:00Z", close: "15:00Z" },
    { region: "NO", id: "no",  name: "*", tz: "Europe/Oslo",        open: "07:00Z", close: "14:20Z" },
    { region: "FI", id: "fi",  name: "*", tz: "Europe/Helsinki",    open: "07:00Z", close: "15:30Z" },
    // "name": "*" = devolve o literal "U.S. markets" (en-US) — que se LOCALIZA como o nome dos
    //   EUA (region=SE&lang=pt-BR → "Mercados dos EUA"): o fallback é a chave de tradução do
    //   mercado US, não um nome próprio do mercado em questão. Quirk confirmado em JP/SE/TR/IL/
    //   RU/TH/DK/FI/NO/PT/GR/VN/MY com lang nativa (ja-JP, sv-SE, tr-TR, he-IL, ru-RU, th-TH,
    //   da-DK, fi-FI, nb-NO, pt-PT, el-GR, vi-VN, ms-MY) e com pt-BR — e TAMBÉM na message
    //   com contagem (out/2026: TR/RU/IL/GR/FI/TH/VN/MY devolvem "U.S. markets open in 8 hours
    //   34 minutes" para os próprios horários, enquanto os mercados nomeados — SG/TW/CN/KR —
    //   exibem o nome próprio: "Singapore markets open in…").
    // VN compartilha Asia/Bangkok com TH (quirk de fuso do servidor).

    // — fallback: CH, ZA, CL, CO, PE, SA, AE, ID, PH, IE, AT, BE, PL, CZ, HU, RO,
    //   XX, ZZ, vazio, símbolos e qualquer valor livre → mercado "us"
  ],

  // ==========================================================================
  // 5 · LOCALIZAÇÃO (name/message) — ENUM DO SERVIDOR (validado ao vivo)
  // ==========================================================================
  LOCALIZATION: {
    LOCALIZED: [                       // 12 locales com strings próprias (pares name/message):
      "en-US",                         //   "U.S. markets"/"U.S. markets closed"
      "pt-BR",                         //   "Mercados dos EUA"/"Mercados dos EUA fechados";
                                       //     no mercado BR: "Mercados do Brazil"/"…fechados"
                                       //     (grafia inglesa "Brazil" dentro da string pt-BR);
                                       //     com contagem: "Mercados do Brazil abrem em
                                       //     9 horas 36 minutos" (números reescritos pelo tick
                                       //     local, bloco 6)
      "es-ES",                         //   "Mercados de EE. UU."/"…cerrados" (espaçamento próprio)
      "es-MX", "es-AR",                //   "Mercados de los EE.UU."/"…cerrados"
      "fr-FR",                         //   "Marchés américains"/"Marchés américains clôturés"
      "fr-CA",                         //   "Marchés des États-Unis"/"…sont fermés"
      "de-DE",                         //   "Märkte in den USA"/"…sind geschlossen"
      "it-IT",                         //   "I mercati degli Stati Uniti"/"…hanno chiuso"
      "zh-Hant-HK",                    //   "美國股市"/"美國股市已收市" (HK: "香港股市已收市")
      "zh-Hant-TW",                    //   "美國市場"/"美國市場已收盤" (TW: "台灣市場已收盤")
      "ko-KR",                         //   "미국 시장"/"미국 시장은 마감했습니다" (KR: "한국 시장…")
    ],
    ECHO_WITHOUT_STRINGS: [            // 20 locales: ecoam em finance.lang/content-language e
      "ja-JP", "ru-RU", "ar-QA",       //   permanecem em INGLÊS ("U.S. markets closed")
      "he-IL", "th-TH", "vi-VN", "hi-IN", "tr-TR",
      "sv-SE", "da-DK", "fi-FI", "nb-NO", "ms-MY",
      "en-GB", "en-AU", "en-CA", "en-IN", "en-SG", "pt-PT"
    ],
    NORMALIZATIONS: {                  // Alias de entrada → forma canônica (eco + strings):
      "pt": "pt-BR",                   // case-insensitive: "PT-br"/"pt_br" → pt-BR
      "zh-CN": "zh-Hant-HK",           // idem zh-HK e zh-SG — e AQUI TAMBÉM zh-TW
                                       //   (divergência do [marketSummary](v6_finance_quote_marketSummary.md): lá zh-TW permanece zh-Hant-TW)
      "ar": "ar-QA",                   // idem ar-EG e ar-SA
      "en": "en-US", "es": "es-ES", "fr": "fr-FR",
      "de": "de-DE", "ja": "ja-JP", "ko": "ko-KR",
    },
    NOT_RECOGNIZED: [                  // → en-US silencioso (eco E content-language en-US):
      "id-ID", "nl-NL", "pl-PL", "cs-CZ", "hu-HU", "ro-RO",
      "uk-UA", "bg-BG", "ca-ES", "eu-ES", "gl-ES", "xx-XX", "<livre>",
    ],
    // Amostras de mercado próprio localizado: pt-BR/BR "Mercados do Brazil" ·
    //   es-MX/MX "Mercados de México" · fr-FR/FR "Marchés français" · de-DE/DE "Deutsche Märkte" ·
    //   it-IT/IT "I mercati dell'Italia" · zh-Hant-HK/HK "香港股市" · ko-KR/KR "한국 시장" ·
    //   zh-Hant-TW/TW "台灣市場" · fr-CA/CA "Marchés du Canada"
  },

  // ==========================================================================
  // 6 · CLIENTE OFICIAL — dois chamadores independentes
  // ==========================================================================
  officialClient: {

    // — LOADER REACT (chunks/loadMarketTime.C0rrqByT.js, export ee→"a"): a pílula "market time"
    //   do dock e o componente MarketTime.Ut-wQPuj.js
    "loaderReact": {
      "callers": [
        "initializeDock — busca NÃO forçada na inicialização do dock + poller de 5 min FORÇADO",
        "MarketTime (componente) — busca FORÇADA no mount quando o store está vazio",
      ],
      "query": {                       // construída pelo transporte comum (approval.BsApzrJF.js, apiFetch/_i):
        "formatted": "true",           //   inerte (bloco 1)
        "key": "finance",              //   chave do config de serviços da página → host
        "lang": "da sessão",           //   en-US se ausente — o transporte REESCREVE lang/region
        "region": "da sessão",         //   da sessão em toda chamada (disableDefaultQueries=false)
      },
      "serviceConfig": {               // config de serviços da página (__data.json):
        "finance":    { host: "query1.finance.yahoo.com", serverKey: "finance",    timeout: 3000, clientTimeout: 15000 },
        // fallback do helper quando a chave não existe no config: query1 + timeout 15 s
        "nimbus":     "quando window._nimbus.ready, o caminho é reescrito para /xhr/service<path> + x-key=serverKey (gateway interno)",
      },
      "skipLogic": "status do store em OPEN ou TO_OPEN → NÃO busca (retorna null), salvo force=true",
      "responseHandling": "finance.error → setError (null) · marketTimes[0].marketTime[0] → initMarketTime",
      "store": {                       // local_gas_station, serviço "marketTime":
        "fields": "duration[0].hrs/mins (parseInt), message, yfit_market_status→status, time",
        "poller": 300000,              // 5 min (initMarketTimePolling, registrado pelo initializeDock;
                                       //   clearInterval no erro do dock)
      },
      "deadCode": {                    // headers do ramo de cache — MORTOS neste build:
        "x-cache": "1",                // o gate é !ak && enableMarketTimeCache, e ak é o hardcoded
        "x-cache-ttl": "30000",        //   TRUE do bundle (support_agent.Cd9DzWFk.js: ak = !0):
      },                               //   os headers NUNCA são enviados (e o servidor os ignora)
      "localCountdown": {              // componente MarketTime.Ut-wQPuj.js:
        "tick": "primeiro timeout = (60 − getUTCSeconds(time)) × 1000 + 200 ms — alinhado ao limite de minuto do campo time do servidor; cadência fixa de 60000 ms (6e4) a partir daí",
        "behavior": "decrementa mins/hrs localmente e REESCREVE a mensagem por regex (troca os números do countdown), sem re-request",
        "compact": "espaço+hours→'h', espaço+minutes→'m' na exibição",
        "fallback": "MARKET_TIME_EMPTY_MSG quando não há mensagem",
      },
    },

    // — WEBCORE (s.yimg.com/uc/finance/webcore/js/marketTime.<hash>.{mjs,js}): o banner de
    //   status das páginas de notícias — elemento DOM #market-time-article (fin-market-time)
    "webcore": {
      "url": "query1…/v6/finance/markettime?lang=<finWebCore.lang||en-US>&region=<finWebCore.region||US>",
      "regionDerivation": "window.finWebCore.region é DERIVADO do lang na inicialização da página: substring após o último hífen (en-US→US, pt-BR→BR)",
      "transport": "fetch credentials:'include' (ou XHR withCredentials quando fetch desabilitado) · GET · timeout 1000 ms · sem crumb · sem headers extras",
      "poll": { "interval": 60000, "firstCall": "imediata",
                "refetch": "nos limites de minuto da contagem (mins 0/59), no fim da contagem e após 15 ticks stale; exceção → força novo ciclo" },
      "domFlags": {                    // lidos do elemento #market-time-article:
        "fetchDisabled|fin-fetch-disabled": "desabilita o fetch (mantém o último estado)",
        "updateStyle|fin-update-style": "habilita troca de cor/ícone quando o status muda",
      },
      "activeRule": "status === 'open' || duration truthy → estilo ativo",
      "statusMaps": {                 // DOIS mapas nativos INDEPENDENTES — semânticas distintas
                                       //   (classe do loader ≠ ícone do webcore); não são cópias
                                       //   a manter sincronizadas:
        "classMap": {                  // SvelteKit: support_agent.Cd9DzWFk.js — enum aj
                                       //   (CLOSED=0, OPEN=1, TO_OPEN=2) + const cE, exportados
                                       //   como {aj, ai}; importados pelo loader
                                       //   (loadMarketTime) e pelo componente (MarketTime):
          "enum": { "CLOSED": 0, "OPEN": 1, "TO_OPEN": 2 },
          "map": {
            "YFT_MARKET_CLOSED": 0,          "YFT_MARKET_CLOSED_EARLY": 0, "YFT_MARKET_HOLIDAY": 0,
            "YFT_MARKET_WILL_CLOSE": 1,      "YFT_MARKET_WILL_CLOSE_EARLY": 1, "YFT_MARKET_WILL_CLOSE_LATE": 1,
            "YFT_MARKET_WILL_OPEN": 2,       "YFT_MARKET_WILL_OPEN_EARLY": 2, "YFT_MARKET_WILL_OPEN_LATE": 2,
          },
          "uso": "skipLogic do loader (OPEN/TO_OPEN → não busca) e armamento do timer do componente",
        },
        "iconMap": {                   // webcore marketTime.{js,mjs} — const j, seletor de
                                       //   ícone fin-icon. Valores INTENCIONALMENTE diferentes
                                       //   do classMap: HOLIDAY→3 (não 0) e as famílias
                                       //   WILL_OPEN↔WILL_CLOSE trocam 1↔2:
          "map": {
            "YFT_MARKET_CLOSED": 0,          "YFT_MARKET_CLOSED_EARLY": 0, "YFT_MARKET_HOLIDAY": 3,
            "YFT_MARKET_WILL_OPEN": 1,       "YFT_MARKET_WILL_OPEN_EARLY": 1, "YFT_MARKET_WILL_OPEN_LATE": 1,
            "YFT_MARKET_WILL_CLOSE": 2,      "YFT_MARKET_WILL_CLOSE_EARLY": 2, "YFT_MARKET_WILL_CLOSE_LATE": 2,
          },
          "icons": {                   // mapa do webcore (fin-icon):
            "0": "eclipse",            // fechado
            "3": "capitol",            // feriado
            "1": "halfSun",            // pré-abertura (WILL_OPEN)
            "2": "sun",               // aberto indo fechar (WILL_CLOSE)
            "DEFAULT": "live",
          },
          "uso": "ícone/cor do banner webcore (updateStyle)",
        },
      },
      "colors": { "activeMarketColor": "#ff7b12", "style": "activeMarketColor quando ativo, tertiaryColor quando inativo" },
      "getMessage": "reescreve o countdown da mensagem com hrs/mins locais (regex sobre o primeiro grupo numérico)",
      "beacon": "finMarketTime",
    },
  },
}
```

## Limites e políticas de uso

| Aspecto | Comportamento |
| :--- | :--- |
| User-Agent | Obrigatório agente de navegador: `Python-urllib/3.x` e o `curl` default recebem `429 Edge: Too Many Requests` — bloqueio por assinatura de agente, não por volume (mesma política do [marketSummary](v6_finance_quote_marketSummary.md) e do [quote v7](v7_finance_quote.md)). |
| Autenticação | Nenhuma — anônimo por definição; cookies/crumb presentes são aceitos e ignorados (nenhum vetor é exigido). |
| Erros | Nenhum erro observável: todos os inputs patológicos (region de 300 caracteres, símbolos, injeção, params duplicados/vazios) → `200` com fallback "us"; o vetor `finance.error` nunca materializou nas sondagens. |
| Cache | `public, max-age=60, stale-while-revalidate=60` — o campo `time` congela na geração; clientes que precisam de relógio vivo devem reconsultar após 60 s (o webcore sonda a cada 60 s; o dock, a cada 5 min). |
| Cardinalidade | Sempre 1 mercado por resposta (70 capturas em duas janelas dominicais + ~60 na revalidação de out/2026); seleção múltipla não existe — `marketTimes` é envelope legado v6, lido no índice `[0]` pelos dois clientes. |
| Payload | ~0,4 KB por resposta — o menor endpoint do documento (vs 5,9–41 KB do marketSummary e 4,3–128 KB do quote). |
