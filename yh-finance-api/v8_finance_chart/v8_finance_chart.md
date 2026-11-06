# `GET /v8/finance/chart/{symbol}`

> **Data de atualização:** 2026-11-06 · **bateria anônima de 37 chamadas** contra `query1.finance.yahoo.com` (canônica do app · mínima · sem parâmetros · bordas de `interval` (inválido, `2h`, `4h`, `90m`, `1m` com janelas) · bordas de `range` (inválido ecoado) · `period1/period2` (válidos, invertidos, isolados, com `range`) · `events` (canônico, `div`, `capitalGain`, inválido) · `includePrePost` (`true`/`TRUE`/`1`) · `includeAdjustedClose=false` · `formatted=false` · crumb garbage · `symbol` na query · HEAD/POST · sem User-Agent) · captura de referência: META diário (meta de 29 campos) · **contrato do cliente** extraído do build SvelteKit de produção (o loader de histórico de preços da página `/chart`: defaults, cache de store e achatamento da resposta).

---

O endpoint do **gráfico**: devolve a série OHLCV (open/high/low/close/volume) com `adjclose`, eventos corporativos (dividendos, splits) e um `meta` rico do subjacente — é o dado por trás de todas as telas de gráfico do site e o **único endpoint da família de cotações que é anônimo de verdade**: **não requer cookie `A3` nem crumb** (crumb errado na query é simplesmente ignorado; o bootstrap de `fc.yahoo.com` é desnecessário). A exigência é só o **User-Agent de navegador** (`curl`/`Python-urllib` → `429 Edge: Too Many Requests`). O envelope é `{"chart":{"result":[…],"error":null}}` — topo próprio, `error` preenchido nos erros reais (404 de símbolo delistado, 400 de parâmetro, 422 de janela). Diferenças críticas para os irmãos: o `symbol` **não vai só no path** — o app o **replica na query** (o path vence em divergência); os defaults do **servidor** são `interval=1m` + `range=1d` (sem nenhum parâmetro); `POST` responde **411 Length Required** em HTML da borda (não 405); e a escala de ganho/perda não se aplica — aqui o contrato é de séries temporais.

| | |
| :--- | :--- |
| Método | `GET` — `HEAD` responde `200` · `POST` → **`405` Method Not Allowed** ou **`411` Length Required** em HTML da borda (rotaciona por deploy) |
| Hosts | `query1` · `query2` (`.finance.yahoo.com` — backend identificado pelo header `x-envoy-decorator-operation: finance-chart-api--mtls-production-use1.finance-k8s:4080/*` — serviço próprio, distinto do `finance-quote-api` dos irmãos) |
| Caminho | `/v8/finance/chart/{symbol}` — `/v8/finance/chart` **sem symbol** → `404` `Not Found` em **texto puro** (11 B, sem envelope) |
| Autenticação | **❌ Nenhuma** — anônimo por definição: `crumb` na query é aceito e **ignorado** (garbage → `200` idêntico); sem cookie, sem crumb, tudo responde `200` com dados |
| User-Agent | Agente de navegador obrigatório — `curl` default/`Python-urllib` → `429 Edge: Too Many Requests` (23 B, texto puro) |
| Cache de borda | **política rotaciona por deploy**: `private, no-cache, no-store` (2026-11-05) ou `public, max-age=10, stale-while-revalidate=20` (2026-11-06 — o mesmo intervalo com 1wk/2y deu o mesmo header) — em ambos, `content-type: application/json;charset=utf-8` |
| Payload típico | mínima (`interval=1d&range=1mo`): 3,7 KB · 1 ano diário: 28,5 KB (252 pontos) · `1m&7d`: 220 KB (2.492 pontos) · cadeia integral `getAllData`: ~870 KB · `sem nada`: 14,6 KB (152 pontos de 1m) |

## Autenticação e User-Agent

**Não há autenticação** — o único da família de cotações sem o par `A3`+`crumb`: o `crumb` presente na query (mesmo garbage) é aceito e ignorado, e a resposta idêntica sai sem cookie algum. O que a edge inspeciona é o **User-Agent**: perfil de navegador obrigatório, `Python-urllib`/`curl` default → `429` de 23 bytes texto puro. Sem cookie: sem identidade, sem quota — o endpoint não consome quota de identidade alguma.

```bash
# Chamada canônica do app web (o loader envia o symbol no PATH e duplicado na query):
curl -s -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36" \
  "https://query1.finance.yahoo.com/v8/finance/chart/AAPL?events=capitalGain%7Cdiv%7Csplit&formatted=true&includeAdjustedClose=true&interval=1d&range=1y&symbol=AAPL&userYfid=true"

# Chamada mínima — apenas interval e range (o servidor faz o resto):
curl -s -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0" \
  "https://query1.finance.yahoo.com/v8/finance/chart/AAPL?interval=1d&range=1mo"

# Sem NENHUM parâmetro: o servidor devolve 1 dia de candles de 1 minuto
curl -s -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0" \
  "https://query1.finance.yahoo.com/v8/finance/chart/AAPL"
```

## Parâmetros da requisição

### Parâmetro de path

| Parâmetro | Tipo | Obrigatório | Comportamento e Casos de Borda |
| :--- | :---: | :---: | :--- |
| `{symbol}` | string | **Sim** | **Case-insensitive** (`aapl` → `meta.symbol: "AAPL"`). Símbolo inexistente → **`404` com envelope** `{"chart":{"result":null,"error":{"code":"Not Found","description":"No data found, symbol may be delisted"}}}` — diferente do irmão de opções (que devolve `200` zerado) e do path sem símbolo (que é `404` em texto puro). O app web **replica o símbolo na query** (`symbol=`) — em divergência, **o path vence** (`path MSFT + symbol=AAPL` → `meta.symbol: "MSFT"`). |

### Parâmetros de query

| Categoria | Parâmetro | Tipo | Obrig. | Padrão (servidor) | Comportamento e Casos de Borda |
| :--- | :--- | :--- | :---: | :--- | :--- |
| **Janela** | `interval` | enum | Não | **`1m`** (sem nenhum parâmetro na query) | Granularidade das barras. Enum do servidor (retornado na própria mensagem de erro): **`[1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 4h, 1d, 5d, 1wk, 1mo, 3mo]`** — 14 valores (`4h` existe; `2h`, `6h`, `1y` não). Inválido (`abc`, `2h`) → **`400`** `{"code":"Bad Request","description":"Invalid input - interval=abc is not supported. Valid intervals: [...]"}`. **Janela máxima por granularidade**: `1m` aceita no máximo **8 dias** — exceder → **`422`** `{"code":"Unprocessable Entity","description":"1m data not available for startTime=… and endTime=…. Only 8 days worth of 1m granularity data are allowed…"}` (o único `422` da família). |
| **Janela** | `range` | enum | Não | **`1d`** (sem `range` e sem `periods`) | Recorte relativo: `1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max` (a lista íntegra vem em `meta.validRanges`). **Inválido não é rejeitado**: `range=2y2` devolve `200` com a string **ecoa** em `meta.range` e **1 único timestamp** (degradação degenerada, sem `400`). **Quando `period1`/`period2` estão presentes, o `range` vence** — os periods são ignorados (ver matriz de precedência). |
| **Janela** | `period1` / `period2` | int (epoch **s**) | Não | — (o app só envia em par) | Recorte absoluto por epoch em segundos. **Só funcionam em par**: `period2` sozinho → `200` com ~300 barras diárias terminando em `period2` (startDate implícito ~14 meses antes); `period1` sozinho → **`400`** `start date cannot be after end date` (o end implícito é `0`). **Invertidos (`p1 > p2`) → `400`** `{"code":"Bad Request","description":"Invalid input - start date cannot be after end date. startDate = 1701000000, endDate = 1700000000"}` — a única validação de datas explícita. Válidos → `meta.range` volta **vazio** (`""`) e o `dataGranularity` segue o `interval`. |
| **Eventos** | `events` | string (pipe) | Não | o app envia `"capitalGain\|div\|split"` | Eventos corporativos intercalados na série: `div` → bloco `events.dividends` (calendário `date`/`amount`), `split` → `events.splits` (`numerator`/`denominator`), `capitalGain` → `events.capitalGain` (só ativos que o publicam — AAPL diário não materializa). Separador `\|` (URL-encoded `%7C`); valor desconhecido (`zzz`) → **ignorado** (sem bloco `events`). O cliente oficial intercala os eventos **dentro** da lista de preços, ordenados por data. |
| **Formatação** | `formatted` | bool | Não | o app envia `true` | **No-op observado nos dados**: os indicadores chegam como primitivos crus nas duas formas (não existe `{raw, fmt}` nesta família); `priceHint` e o resto do `meta` idênticos. `TRUE` (caixa alta) aceito. |
| **Ajustes** | `includeAdjustedClose` | bool | Não | o app envia `true` | `true` → `indicators.adjclose[0].adjclose[]` acompanha o `quote[0]` (mesmo comprimento do `timestamp`); **`false` → o bloco `adjclose` inteiro desaparece** (verificado). |
| **Pré/pós** | `includePrePost` | bool | Não | `false` (o app não envia) | `true` (e `TRUE` — case-insensitive) **inclui barras de pré/pós-market** no intervalo intradiário (`5m&1d`: 97 pontos com `true` vs 32 sem). **`1` NÃO ativa** (32 pontos — sem coerção numérica, coerente com a família). Afeta também `meta.hasPrePostMarketData`? — não: esse campo é do subjacente, independente do parâmetro. |
| **Eco** | `symbol` | string | Não | — | **Duplicado do path pelo app** (fica no path E na query). Em divergência **o path vence** (`path MSFT + symbol=AAPL` → `meta.symbol: "MSFT"`). |
| **Sessão** | `userYfid` | bool | Não | o app envia `true` | No-op verificado (flag interna do Yahoo — `userYfid` de roteamento interno). |
| **Locale** | `lang` / `region` | string | Não | injetados pelo transporte (`en-US`/`US`) | **O fuso do `meta` é da BOLSA, não da região**: `region=BR` devolve `gmtoffset: -18000` / `exchangeTimezoneName: "America/New_York"` (EST de novembro) — nenhum campo do corpo é localizado; revalidado por DIFF completo (`pt-BR/BR` ≡ `en-US/US` ≡ sem lang/region — 32 campos no intradiário, a mínima com só `lang+region` devolve 1 dia de 1m, 205 barras). |
| **Auth** | `crumb` | string | Não | — | **Ignorado**: `crumb=garbage` → `200` idêntico. O chart é o único da família sem o par `A3`+crumb. |
| **Ignorados** | desconhecidos | qualquer | Não | — | Aceitos e descartados silenciosamente (padrão da família). |

### Matriz de precedência da janela

| Cenário | `interval` | `range` | `period1`/`period2` | Resultado |
| :--- | :--- | :---: | :---: | :--- |
| **Sem nada** | — | — | — | **1 dia de barras de 1m** (defaults do servidor: `interval=1m`, janela `1d`) — 152 pontos |
| **Mínima** | `1d` | `1mo` | — | 24 barras diárias |
| **Range relativo** | qualquer | `<enum>` | — | série do range na granularidade do interval |
| **Período absoluto** | qualquer | — | `p1` + `p2` | série exata do recorte; `meta.range` volta **vazio** (`""`) |
| **Ambos** (URL manual) | qualquer | `<enum>` | `p1` + `p2` | **`range` vence** — os periods são ignorados (verificado: `periods` de 10 dias + `range=1y` → 252 barras de 1 ano) |
| **`1m` com janela longa** | `1m` | `1y` | — | **`422`** — janela de 1m limitada a 8 dias |
| **Range inválido** | qualquer | `2y2` | — | **`200` degenerado**: `meta.range` ecoa a string, **1 único timestamp** |

## Estrutura da resposta

```json5
{
  "chart": {
    "result": [{
      // ── META (29 campos) ──
      "meta": {
        "currency": "USD",                 // moeda do subjacente
        "symbol": "META",                  // eco do path, caixa alta
        "exchangeName": "NMS",             // bolsa curta
        "fullExchangeName": "NasdaqGS",    // bolsa longa
        "instrumentType": "EQUITY",        // EQUITY/ETF/INDEX/CRYPTOCURRENCY/…
        "firstTradeDate": 1337347800,      // epoch s — listagem original
        "regularMarketTime": 1790280001,   // epoch s — último tick
        "hasPrePostMarketData": true,      // o subjacente tem pré/pós
        "gmtoffset": -14400,               // offset ATUAL da bolsa (s: EDT -4h; EST -18000)
        "timezone": "EDT",                 // abreviação vigente
        "exchangeTimezoneName": "America/New_York",  // IANA — sempre da bolsa
        "regularMarketPrice": 777.59,      // último preço
        "regularMarketChangePercent": 4.501,
        "fulldayPrice": 775.75,            // preço do dia completo (regular + pós)
        "fulldayChange": 31.55, "fulldayChangePercent": 4.24,
        "fiftyTwoWeekHigh": 779.819, "fiftyTwoWeekLow": 520.26,
        "regularMarketDayHigh": 779.819, "regularMarketDayLow": 743.006,
        "regularMarketVolume": 34646511,
        "longName": "Meta Platforms, Inc.", "shortName": "Meta Platforms, Inc.",
        "chartPreviousClose": 545.83,      // fechamento ANTES da 1ª barra da série
        "priceHint": 2,                    // casas decimais de exibição
        "currentTradingPeriod": {          // janelas pre/regular/post do DIA (epoch s)
          "pre": {"timezone":"EDT","start":…,"end":…},
          "regular": {…}, "post": {…}
        },
        "dataGranularity": "1d",           // eco do interval efetivo
        "range": "1y",                     // eco do range efetivo ("" com periods; ecoa inválido)
        "validRanges": ["1d","5d","1mo","3mo","6mo","1y","2y","5y","10y","ytd","max"],
        // ── SÓ NO INTRADIÁRIO (verificado na chamada mínima 1m/1d) ──
        "previousClose": 344.17,      // fechamento anterior (separado do chartPreviousClose)
        "scale": 3,                    // fator de escala do preço
        "tradingPeriods": [            // plural: janelas pre/regular/post POR DIA
          [{"timezone":"EST","start":…,"end":…,"gmtoffset":-18000}]]
      },
      // ── SÉRIE ──
      "timestamp": [1787319000, 1787578200, …],   // epoch s, um por barra
      "indicators": {
        "quote": [{                                 // UMA entrada; arrays paralelos ao timestamp
          "open":  [743.1, …], "high": [746.5, …],
          "low":   [740.2, …], "close": [745.2, …],
          "volume":[19574482, …]                    // null nas barras sem pregão
        }],
        "adjclose": [{ "adjclose": [743.1, …] }]    // some por inteiro com includeAdjustedClose=false
      },
      // ── EVENTOS (só com events=; SEM o parâmetro o bloco inteiro não vem) ──
      "events": {
        "dividends": { "1787418000": {"amount": 0.525, "date": 1787418000}, … },
        //  dicionário CHAVEADO POR EPOCH (92 dividendos no AAPL range=max)
        "splits":    { "1598880600": {"date": 1598880600, "numerator": 4,
                        "denominator": 1, "splitRatio": "4:1"}, … }
        //  5 splits históricos no AAPL (o 4:1 de 31/08/2020 é real)
        // "capitalGain": { … } — bloco só para quem publica distribuições
        //   (fundos); ações (AAPL) devolvem vazio mesmo com range=max
      }
      // barras sem pregão: os arrays guardam null nas posições correspondentes
    }],
    "error": null
  }
}
```

## Como o aplicativo oficial consome o endpoint

- **Loader dedicado** (`loadPriceHistory`, página `/chart`): monta a query com os defaults `{events: "capitalGain|div|split", interval: "1d", range: "1y", formatted: true, includeAdjustedClose: true, userYfid: true}` e **só envia `period1/period2` quando os dois existem** — sem eles, envia `range=1y` e **omite `range` da query** quando há periods (o servidor, porém, dá precedência ao `range` se ambos chegarem).
- **Cache de store** por `symbol + interval + (period1+period2 | range)`: id idêntico → **retorno sem rede** (mesmo padrão do irmão de opções).
- **Achatamento**: a resposta é achatada em uma lista `prices[]` (timestamp descrescente na iteração) com os **eventos intercalados por data** dentro da série (dividendos/splits ganham uma entrada `{data: valor, type: "div"|"split"}` entre as barras) — barras com `open/high/low/close` não numéricos são **puladas** na montagem.
- **`crumb` nunca é enviado** pelo loader do gráfico — e o servidor ignora se enviado.
- **Meta para a UI**: `meta.firstTradeDate`, `meta.exchangeTimezoneName` (timezone das datas do gráfico) e `meta.regularMarketPrice` alimentam o cabeçalho e os eixos do gráfico.

## Erros e códigos de status (todos verificados)

| HTTP | Forma do corpo | Causa |
| :---: | :--- | :--- |
| `404` | **Texto puro** `Not Found` (11 B, sem envelope) | Path **sem o segmento do símbolo** (`/v8/finance/chart`) |
| `404` | `{"chart":{"result":null,"error":{"code":"Not Found","description":"No data found, symbol may be delisted"}}}` | Símbolo inexistente/delistado (⚠ diferente do irmão de opções, que devolve `200` zerado) |
| `400` | `{"chart":{"result":null,"error":{"code":"Bad Request","description":"Invalid input - interval=abc is not supported. Valid intervals: [1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 4h, 1d, 5d, 1wk, 1mo, 3mo]"}}}` | `interval` fora do enum — **a mensagem traz a lista íntegra dos 14 valores** |
| `400` | `{"chart":{…,"error":{"code":"Bad Request","description":"Invalid input - start date cannot be after end date. startDate = 1701000000, endDate = 1700000000"}}}` | `period1 > period2` (e `period1` **sozinho** — o end implícito é `0`) |
| `422` | `{"chart":{…,"error":{"code":"Unprocessable Entity","description":"1m data not available for startTime=… and endTime=…. Only 8 days worth of 1m granularity data are allowed to be fetched per request."}}}` | `interval=1m` com janela > 8 dias |
| `411` | HTML da borda (`Length Required`) | `POST` (não `405` — o método é rejeitado antes, por falta de length) |
| `429` | Texto puro `Edge: Too Many Requests` (23 B) | User-Agent de biblioteca |
| `200` | `meta.range` ecoa o valor inválido + **1 único timestamp** | `range` inexistente no enum (`2y2`) — degradação degenerada, sem `400` |

## Limites e políticas de uso

| Aspecto | Comportamento |
| :--- | :--- |
| Autenticação | **Nenhuma** — o único anônimo da família de cotações; `crumb` ignorado, sem quota de identidade, sem bootstrap. |
| User-Agent | Obrigatório (navegador) — biblioteca → `429 Edge` de 23 B. |
| Janelas | `1m` ≤ **8 dias** por requisição (`422` acima); `range` inválido não é rejeitado (eco degenerado); `range` vence sobre `periods` na mesma query. |
| Cache de borda | **`private, no-cache, no-store`** no `200` — nada cacheável (a série é recalculada por chamada; o `Age` não aparece). |
| Backend próprio | `finance-chart-api` (`x-envoy-decorator-operation`) — serviço separado do `finance-quote-api` dos irmãos; upstream rápido. |
| Volume | ~3,7 KB (1 mês diário) a ~220 KB (`1m&7d`); a cadeia integral por períodos cresce com a liquidez. |
| Precisão | `adjclose` acompanha dividendos (série ajustada ≠ `close` em datas ex-dividendo); `null` nas barras sem pregão (feriados no range); `meta.chartPreviousClose` é a âncora do retorno antes da 1ª barra. |
| Não observado | `filters` (param legado não enviado pelo app); efeito real de `formatted` (os indicadores são crus nas duas formas); `includePrePost` com `interval` diário (só faz sentido intradiário); `events=capitalGain` materializado (AAPL não publica no período). |
