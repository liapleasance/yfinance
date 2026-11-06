# Engenharia Reversa — Endpoint `GET /v1/finance/lookup`

Requisição exige ❌ `Anônimo` — nenhuma credencial. Cookie `A3` e `crumb` não são exigidos: o cliente oficial só anexa o `crumb` quando o token já existe no store da sessão, e o servidor o ignora (presente, ausente ou garbage devolvem corpo idêntico). A única exigência da borda é `User-Agent` de navegador (`python-requests`/`curl` → HTTP 429). Método `GET`; hosts válidos `query1` / `query2` / `iquery.finance.yahoo.com` — os três respondem `200` anônimo com payload idêntico.

---

## 1. Visão geral e papel no aplicativo

O endpoint devolve a página de resultados de uma busca textual de ativos: lista de instrumentos paginada (`documents`), cada um com popularidade (`rank`), classificação setorial quando existente (`industryName`/`industryLink`) e cotação inline opcional (`fetchPricingData`); acompanha um painel de contagens por tipo de ativo para o resultado inteiro (`lookupTotals`), usado para desenhar as abas de filtro e a paginação. É o motor da página de utilidade `/lookup` (tabela filtrável por tipo com abas, paginação e enriquecimento de notícias) e do fluxo de resolução de empresa privada na página de companhia.

| Contexto de Uso | Arquivo Base / Chunk | Identificador / Função Lógica | Como chama |
| :--- | :--- | :--- | :--- |
| Página `/lookup` (rota `/(app)/lookup/[[viewId]]`) | `nodes/143.[hash].js` | `load` → `lookupData` + `$e` (paginação) | `type` do `viewId` da URL; `s`/`b`/`c` viram `query`/`start`/`count` (default `count=25`); sem `s`, a página usa outro recurso e monta um envelope sintético |
| Página `/company/{symbol}` (rota `/(app)/company/[symbol]`) | `nodes/135.[hash].js` | `load` → resolução de empresa privada | `type: "private_company"` fixo, `query` do hash do símbolo; espera `documents.length === 1` para redirecionar |
| Fetcher único (gateway) | `chunks/loadLookup.[hash].js` | `It` (export `l`) | `query`/`type`/`start`/`count` + `formatted: true` + `fetchPricingData: true` + par condicional de feature flag |
| Transporte | `chunks/quoteUtil.[hash].js` | `Ue`/`ee` (export `f`) | host `query1`, `credentials: "include"`, `lang`/`region` default, `crumb` condicional, timeout 15 s |

```js
// chunks/loadLookup.[hash].js — It (export "l") — fetcher do /v1/finance/lookup
async function It(s, {
  query,
  type = "all",        // default do fetcher; a página valida o viewId antes
  start = 0,
  count = 20           // default do fetcher; a página /lookup envia 25
}) {
  if (!query) {
    // guarda client-side: string vazia nunca chega à rede
    return Promise.reject(new Error("Bad request for loadLookup"));
  }
  const n = await j_3(s);                     // session (parent() do evento)
  const a = r_2(n, "enablePrivateCompany");   // feature flag no array session.feature
  try {
    const o = await f_2(s, {                  // f_2 = Ue do quoteUtil (transporte)
      crumb: true,                            // anexa crumb APENAS se o store tem um
      pathname: "/v1/finance/lookup",
      perfLabel: "loadLookup",
      query: {
        query,
        type,
        start,
        count,
        formatted: true,                      // envelope {raw, fmt} nos preços
        fetchPricingData: true,               // 6 campos de cotação inline
        ...(a && {                            // spread condicional sob flag
          enablePrivateCompany: a,
          enableCb: false
        })
      }
    });
    if (!Array.isArray(o?.finance?.result)) {
      throw new Error("No lookup data found");
    }
    const [c] = o.finance.result;             // primeiro (e único) elemento
    return {
      ...(Object(c) === c ? c : {}),          // espalha o result[0]
      type                                    // reanexa o type pedido
    };
  } catch (data) {
    l_2(s, { query, type, start, count }, { data, perfLabel: "loadLookup" });
    return Promise.reject(new Error("No lookup data found"));
  }
}
```

### 1.1 Arquitetura de referência

1. **Camada de Página / Estado:** `nodes/143.[hash].js` (`/(app)/lookup/[[viewId]]`) — valida o `viewId` contra a lista local de tipos, lê `s`/`b`/`c` da URL, monta o objeto de dados e repassa ao componente de tabela.
2. **Camada de Loader / Gateway:** `It` (`chunks/loadLookup.[hash].js`) — guarda de `query` vazio, resolução da flag `enablePrivateCompany` na sessão, montagem da query string, rejeição unificada com log estruturado.
3. **Camada de Transporte / Fetch:** `Ue`/`ee` (`chunks/quoteUtil.[hash].js`) — resolve host do `serviceConfig` (`query1` por omissão), injeta `lang`/`region` default, anexa `crumb` condicional, `AbortController` com timeout de 15 000 ms, parse JSON com lançamento de erro tipado em `!ok`.
4. **Camada de Apresentação:** `nodes/143.[hash].js` — `DataTable` com colunas configuráveis, `DataTablePagination` (refetch por página), abas `Tabs` construídas de `lookupTotals`, enriquecimento de notícias por lista de símbolos.

### 1.2 Ciclo de vida

```
[ Rota /lookup?s=<query>&b=<start>&c=<count>&viewId=<tipo> ]
                    │
                    ▼
[ Flag enableQuoteLookup off → redirect 302 p/ a página de cotação ]
                    │
                    ▼
[ viewId fora da lista local de tipos → redirect 302 sem viewId ]
                    │
                    ▼
[ Sem query (s vazio) → recurso de ranking regional + envelope sintético ]
      └── Com query → It(loadLookup) → transporte quoteUtil
                                      │
                                      ▼
             [ GET /v1/finance/lookup (query1, timeout 15s) ]
                                      │
                                      ▼
             [ finance.result[0] → documents + lookupTotals ]
                                      │
                                      ▼
             [ Abas por tipo (contagens) + DataTable (documents) ]
                                      │
                                      ▼
             [ Paginação → refetch com novo start/count ]
             [ Notícias → lista "lookup"/"newsAll" dos símbolos ]
```

### 1.3 Otimizações do loader

- **Validação pré-rede do `viewId`:** a página rejeita tipos fora da lista local (`all`, `equity`, `mutualfund`, `etf`, `index`, `future`, `currency`, `cryptocurrency`, mais `private_company` sob flag) com redirect `302`, sem gastar rede.
- **Guarda de `query` vazia:** `It` rejeita antes do fetch — a rede nunca vê `query` vazia vinda do cliente oficial.
- **Parse defensivo de `start`/`count` da URL:** `parseInt` com fallback (`NaN` → `0` para `start`, `25` para `count`).
- **Sem cache de dados do endpoint:** não há store dedicado; cada paginação refaz a chamada. O `x-cache`/`x-cache-ttl` de 30–60 s que o transporte pode enviar é um modo do cliente genérico, não específico desta família.
- **Tratamento gracioso de erro:** toda falha colapsa numa única rejeição `"No lookup data found"` com log estruturado (`code: "loadLookup"`, status, url); a página renderiza estado de erro `500` local.

---

## 2. Especificação do Protocolo Wire (Request)

### 2.1 Linha de requisição

```http
GET /v1/finance/lookup?query=Apple&type=all&start=0&count=20&formatted=true&fetchPricingData=true&lang=en-US&region=US HTTP/2
Host: query1.finance.yahoo.com
```

### 2.2 Hosts válidos

| Host | Papel | Evidência |
| :--- | :--- | :--- |
| `https://query1.finance.yahoo.com` | Produção principal | default do `serviceConfig` (`finance`) em `chunks/quoteUtil.[hash].js` |
| `https://query2.finance.yahoo.com` | Rota secundária / fallback de alta disponibilidade | `200` anônimo com payload byte-idêntico ao `query1` |
| `https://iquery.finance.yahoo.com` | Rota interna — serve este endpoint publicamente | `200` anônimo com payload byte-idêntico ao `query1` |

### 2.3 Cabeçalhos críticos da requisição

| Header | Valor exigido / recomendado | Efeito de ausência / erro |
| :--- | :--- | :--- |
| `User-Agent` | Perfil de navegador recente | Obrigatório de fato: UA `python-requests`/`curl` → HTTP 429 `Edge: Too Many Requests` (texto puro, sem envelope) |
| `Accept` | `application/json` (recomendado) | `*/*` tolerado |
| `Cookie` | — | Não exigido; a primeira resposta pode devolver `Set-Cookie` de bootstrap (`A3`), que é dispensável para as chamadas seguintes |
| `crumb` | — | Não exigido e ignorado: presente, ausente ou garbage devolvem corpo idêntico |
| `Origin` | `https://finance.yahoo.com` | Opcional para leitura direta; controla apenas o CORS (ver §8.4) |
| `Referer` | `https://finance.yahoo.com/` | Opcional |

### 2.4 Timeouts do cliente oficial

| Medição | Valor | Fonte |
| :--- | :---: | :--- |
| Timeout padrão REST | `15 000 ms` | `const k = 15000` + `AbortController` em `chunks/quoteUtil.[hash].js` |
| Cache TTL HTTP (edge) | `max-age=300` + `stale-while-revalidate=120` | `cache-control` da resposta `200` |
| Cache TTL de erro | `max-age=0, private` | `cache-control` das respostas `400`/`500` |

### 2.5 Exemplo de requisição completa

```bash
# Sem handshake: o endpoint é anonimo — nao existe passo de cookie/crumb.
curl -s \
  -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36" \
  -H "Accept: application/json" \
  "https://query1.finance.yahoo.com/v1/finance/lookup?query=Apple&type=all&start=0&count=20&formatted=true&fetchPricingData=true&lang=en-US&region=US"
```

---

## 3. Parâmetros de Query

Legenda de "Disp.": **T** = sempre presente no contrato, **D** = sob demanda, **—** = não aplicável.

| Parâmetro | Tipo | Obrigatório | Padrão | Validação | Depende de Feature Flag? | Comportamento e Casos de Borda |
| :--- | :---: | :---: | :---: | :--- | :---: | :--- |
| `query` | string | **Sim** | — | — | Não | Texto de busca. Ausente ou vazio → `400` `Missing required query parameter=query`. Case-insensitive (`aPPle` ≡ `APPLE` ≡ `Apple`). Multi-palavra casa como frase (`apple inc` → 45 resultados). Espaços nas bordas tolerados. Até 300 caracteres aceitos sem erro (resultado vazio). Vírgula é literal — não existe modo multi-símbolo por vírgula (`AAPL,MSFT` → 0 resultados). Caracteres especiais de símbolo (`^`, `=`, `-`) casam literalmente (`^GSPC` → 1 resultado, `SAAPL=F` → 1). |
| `type` | string | Não | `all` | minúsculas exatas ou lista por vírgula | `enablePrivateCompany` (somente no cliente) | Seletor de tipo. Case-**sensitive**: `EQUITY`/`Equity`/`ALL` → `400` `Valid types: [equity, mutualfund, etf, index, currency, future, cryptocurrency]`. O seletor agregador `all` é aceito mas não aparece na mensagem de erro. Vírgula = **união** de tipos (`equity,etf` → documentos dos dois; ordem irrelevante; duplicata colapsada). `all` dentro de lista é descartado (`all,equity` ≡ `equity`). Espaço nas bordas é aparado (`" equity"` ≡ `equity`). `private_company` e `privateCompany` → `400` (ver §8.10). |
| `start` | int | Não | `0` | inteiro ≥ 0, ≤ 10000 | Não | Offset de paginação. Não-inteiro → `400` `Parameter=start has an invalid type`. Negativo → `400` `Start / count cannot be negative`. `> 10000` → `400` `Start cannot exceed 10000`. Além do fim do resultado → `200` com `documents: []`. |
| `count` | int | Não | `20` (servidor) — a página `/lookup` envia `25` | inteiro ≥ 0, ≤ 10000 | Não | Tamanho da página. `""` é tratado como ausente (default `20`). `0` → `200` vazio. Não-inteiro (`abc`, `1.5`) → `400` tipado. `-1` → `400` negativo. `> 10000` → `400` `Count cannot exceed 10000`. Valores na faixa alta com conjuntos de matches grandes são instáveis (ver §8.2). |
| `formatted` | bool | Não | `true` (cliente) / primitivo quando ausente | léxico: somente a palavra `true` (case-insensitive) | Não | `true`/`TRUE` → envelope `{raw, fmt}` nos campos de preço. `false`/`1`/`yes`/qualquer outro → primitivos. |
| `fetchPricingData` | bool | Não | `true` (cliente) | léxico idêntico ao `formatted` | Não | `true`/`TRUE` → acrescenta os 6 campos de cotação a cada documento. `false`/`1`/`garbage` → documento base sem preços (7 chaves). |
| `lang` | string | Não | `en-US` | — | Não | Idioma. Par `lang`+`region` correspondente a mercado não-US troca o corpus de busca (ver §4.4); sozinho não altera nada. |
| `region` | string | Não | `US` | — | Não | Região. Sozinha não altera o corpus; combinada com o `lang` do mesmo mercado, sim. |
| `crumb` | string | Não | — | — | Não | **No-op verificado**: `crumb=garbage` devolve corpo idêntico ao anônimo. O cliente oficial só envia quando o store já possui um token. |

> **Convenções verificadas:**
> - Parâmetros desconhecidos (`bogusParam`, `quotesCount`, `enableFuzzyQuery`) são silenciosamente ignorados — corpo idêntico ao da requisição sem eles.
> - `enablePrivateCompany` e `enableCb` (o par condicional do cliente oficial sob flag de sessão) não alteram o corpo da resposta em nenhum valor testado — ambos são no-ops.
> - O par `start`+`count` é validado em conjunto: cada um tem teto próprio de `10000` e piso compartilhado de `0` (negativo → mensagem única `Start / count cannot be negative`).

---

## 4. Estrutura da Resposta

### 4.1 Envelope de sucesso

```json
{
  "finance": {
    "result": [
      {
        "start": 0,
        "count": 20,
        "total": 20,
        "documents": [ { "...": "..." } ],
        "lookupTotals": {
          "all": 126, "equity": 53, "mutualfund": 11, "etf": 35,
          "index": 11, "currency": 0, "future": 6,
          "cryptocurrency": 10, "privateCompany": 0
        }
      }
    ],
    "error": null
  }
}
```

Formato do `result`: array com **um único objeto** de página. `start` e `count` ecoam os valores pedidos (`count` ausente → `20`); `total` espelha `documents.length` — é a contagem da página, **não** o total global do resultado. O total por tipo vive em `lookupTotals`, que descreve o corpus inteiro da query (imune ao `type` pedido) e tem `all` = soma das demais categorias. `lookupTotals` usa a chave `privateCompany` (camelCase) — a única chave do envelope fora do padrão snake/lowercase dos tipos.

### 4.2 Envelope de erro

```json
{
  "finance": {
    "result": null,
    "error": {
      "code": "Bad Request",
      "description": "Valid types: [equity, mutualfund, etf, index, currency, future, cryptocurrency]"
    }
  }
}
```

O envelope `finance` aparece tanto no sucesso quanto no erro de validação (`400` tipados, `405`). Fora dele há duas classes: o `429` da borda devolve **texto puro** (`Edge: Too Many Requests`, sem envelope), e o `500` tem duas formas — JSON tipado (`Internal Server Error` / `Server caught an exception`, ver §7) e página HTML de erro upstream intermitente (sem envelope). Erros `4xx`/`5xx` vêm com `cache-control: max-age=0, private`.

### 4.3 Regras `formatted=false` vs `formatted=true`

| Tipo de Dado | `formatted=false` | `formatted=true` |
| :--- | :--- | :--- |
| Preço / variação (`regularMarketPrice`, `fulldayPrice`, `*Change`) | `330.32` | `{"raw": 330.32, "fmt": "330.32"}` |
| Percentual (`regularMarketPercentChange`, `fulldayChangePercent`) | `-0.81` (já em unidades de %) | `{"raw": -0.81, "fmt": "-0.81%"}` — `raw` espelha o número impresso |
| `rank` | `516650` (inteiro) | permanece inteiro primitivo |
| `symbol`, `shortName`, `exchange`, `quoteType`, `industryName`, `industryLink` | string literal | permanecem strings sem envelope |

O toggle aplica-se somente aos 6 campos de preço/percentual; `rank` e os identificadores nunca são envolvidos. O parsing é léxico: somente a palavra `true` em qualquer capitalização ativa o envelope; `1`, `yes` e qualquer outro valor equivalem a `false`.

### 4.4 Variantes suportadas

| Dimensão | Valores Conhecidos | Efeito na Resposta |
| :--- | :--- | :--- |
| `type` | `all`, `equity`, `mutualfund`, `etf`, `index`, `currency`, `future`, `cryptocurrency`, lista por vírgula | Filtra `documents` (a união soma os tipos pedidos); `lookupTotals` permanece o do corpus inteiro, imune ao filtro |
| Corpus `lang`+`region` | `en-US`+`US` (default), `ja-JP`+`JP`, `de-DE`+`DE`, `en-GB`+`GB` | Par correspondente a um mercado não-US troca o índice de busca (`all` muda de `126` para `90` na query `Apple`); pares mistos (`ja-JP`+`US`, `en-US`+`JP`, `en-US`+`GB`, `en-US`+`BR`, `de-DE`+`US`, `pt-BR`+`US`) mantêm o corpus default |
| `fetchPricingData` | `true` / `false` | Liga/desliga os 6 campos de cotação por documento |

---

## 5. Catálogo de Campos e Módulos

### 5.0 Mecanismo de controle de projeção

- **Seletor:** não há `fields` nem `modules` — a projeção é um interruptor único (`fetchPricingData`) com efeito aditivo: base de 7 chaves + 6 chaves de preço. O `type` filtra quais entidades entram; não recorta colunas.

### 5.1 Catálogo detalhado

| Campo | Disp. | Tipo | Descrição Funcional | Exemplo Real |
| :--- | :---: | :---: | :--- | :--- |
| `result[0].start` | T | `int` | Eco do `start` pedido | `0` |
| `result[0].count` | T | `int` | Eco do `count` pedido (default do servidor: `20`) | `20` |
| `result[0].total` | T | `int` | Contagem da página — espelho de `documents.length`, não o total global | `20` |
| `result[0].documents` | T | `list` | Página de instrumentos ordenada por `rank` decrescente | — |
| `result[0].lookupTotals` | T | `nested` | Contagens do corpus inteiro por tipo (imunes ao `type` pedido) + `all` (soma) + `privateCompany` | `{"all": 126, ...}` |
| `documents[].symbol` | T | `str` | Ticker do instrumento | `"AAPL"` |
| `documents[].shortName` | T | `str` | Nome curto da entidade | `"Apple Inc."` |
| `documents[].exchange` | T | `str` | Código da bolsa emissora | `"NMS"` |
| `documents[].quoteType` | T | `str` | Tipo do instrumento, **minúsculo** | `"equity"` |
| `documents[].rank` | T | `int` | Score de popularidade global do símbolo, estável entre queries distintas (o mesmo símbolo exibe o mesmo `rank` em queries diferentes); define a ordem decrescente da lista | `516650` |
| `documents[].industryName` | T\* | `str` | Setor da empresa — presente somente em `equity` com classificação setorial; exóticos sem setor e os demais tipos nunca o trazem | `"Technology"` |
| `documents[].industryLink` | T\* | `str` | URL da página de setor do app | `"https://finance.yahoo.com/sector/technology"` |
| `documents[].regularMarketPrice` | D | `obj` | Último preço do pregão regular (sob `fetchPricingData=true`) | `{"raw": 330.32, "fmt": "330.32"}` |
| `documents[].regularMarketChange` | D | `obj` | Variação absoluta do pregão regular | `{"raw": -2.70, "fmt": "-2.70"}` |
| `documents[].regularMarketPercentChange` | D | `obj` | Variação percentual do pregão regular, em unidades de % | `{"raw": -0.81, "fmt": "-0.81%"}` |
| `documents[].fulldayPrice` | D | `obj` | Preço do dia completo (inclui sessão estendida quando há) | `{"raw": 330.26, "fmt": "330.26"}` |
| `documents[].fulldayChange` | D | `obj` | Variação absoluta do dia completo | `{"raw": -2.54, "fmt": "-2.54"}` |
| `documents[].fulldayChangePercent` | D | `obj` | Variação percentual do dia completo, em unidades de % | `{"raw": -0.76, "fmt": "-0.76%"}` |

### 5.2 Campos que não retornam

| Campo / Parâmetro Citado | Veredito | Comportamento Real |
| :--- | :--- | :--- |
| `regularMarketChangePercent` | Nome não existe neste endpoint | O campo de percentual do pregão chama-se `regularMarketPercentChange` — a palavra `Percent` vem depois de `Market`. Reimplementações que assumam o nome inverso quebram silenciosamente. |
| `documents[].privateCompany` | Nunca populado em `documents` | O tipo privado existe apenas como chave de contagem (`lookupTotals.privateCompany`, sempre `0` nas observações); o seletor `type=private_company` é rejeitado com `400` (ver §8.10). |
| `lookupTotals.private_company` | Chave inexistente | A chave do painel é `privateCompany` (camelCase) — única exceção ao padrão de nomes do objeto. |

---

## 6. Matriz de presença por classe de ativo

Legenda: `✅` = presente na resposta para a classe; `—` = ausente (único uso permitido de `✅`).

| Campo | `equity` | `etf` | `mutualfund` | `index` | `future` | `currency` | `cryptocurrency` |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `symbol`, `shortName`, `exchange`, `quoteType`, `rank` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 6 campos de preço (`fetchPricingData=true`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `industryName` / `industryLink` | ✅ (somente com setor classificado) | — | — | — | — | — | — |

A presença de `industryName`/`industryLink` em `equity` é condicional à classificação setorial do emissor: listagens principais (`AAPL`, `APLE`, `AAPL.TO`) trazem; exóticos (`APCD.XD`, `AAPLC.BA`, `1AAPLM.XD`) não trazem. Nenhuma outra classe devolve esses campos em nenhuma condição.

---

## 7. Erros e códigos de status

| HTTP | `code` | `description` | Causa |
| :---: | :--- | :--- | :--- |
| `400` | `Bad Request` | `Missing required query parameter=query` | `query` ausente ou vazia (string nula colapsa no mesmo caso). |
| `400` | `Bad Request` | `Valid types: [equity, mutualfund, etf, index, currency, future, cryptocurrency]` | `type` desconhecido, com case errado (`EQUITY`, `Equity`, `ALL`) ou não listado (`private_company`, `privateCompany`, ` stock `). O agregador `all` é aceito apesar de ausente da mensagem. |
| `400` | `Bad Request` | `Parameter=count has an invalid type` / `Parameter=start has an invalid type` | Contador não-inteiro (`abc`, `1.5`). |
| `400` | `Bad Request` | `Start / count cannot be negative` | `start` ou `count` negativo — mensagem única para os dois parâmetros. |
| `400` | `Bad Request` | `Count cannot exceed 10000` / `Start cannot exceed 10000` | Teto de validação de cada parâmetro; valores exatamente `10000` passam na validação. |
| `405` | `Method Not Allowed` | `HTTP 405 Method Not Allowed` | `POST`/`PUT` em endpoint `GET`-only. A resposta **não traz header `Allow`**. `HEAD` é aceito (`200`, corpo vazio). |
| `429` | — (texto puro) | `Edge: Too Many Requests` | Duas causas: rate-limit da borda, e WAF de path traversal — a sequência `../` na query (`query=../`) dispara `429` mesmo com UA de navegador e volume baixo, enquanto a query normal responde `200` no mesmo instante. |
| `500` | `Internal Server Error` | `Server caught an exception` | **Classe determinística** (JSON com envelope `finance`): `count=9999`/`10000` combinado com conjunto de matches grande (≥ 10 000 verdadeiros) — reproduzido 5/5. A validação aceita `count` ≤ 10000, mas a execução explode na faixa alta. |
| `500` | — (corpo HTML, sem envelope) | — | **Classe intermitente** upstream (página de erro HTML de ~3 KB com `cache-control: max-age=0, private`): atinge requisições válidas aparentemente arbitrárias e não se reproduz em retentativa — tratar como transitório com 1 retry. |
| `200` | — | — | Página vazia legítima: `start` além do fim, `count=0` ou query sem matches devolvem `200` com `documents: []` e `total: 0` — nunca `404`. |

---

## 8. Comportamentos empíricos

### 8.1 Requisitos de borda, WAF e anti-bot

- **Inspeção de User-Agent:** a borda rejeita UAs genéricos (`python-requests`, `curl`, `Go-http-client`) com `429` texto puro — formato de navegador moderno é a única exigência do endpoint. Fingerprint TLS de browser não é exigido (stdlib `urllib` com UA de navegador responde `200`).
- **WAF de path traversal:** `query=../` → `429` mesmo com UA de navegador e volume baixo (2×), com a query normal respondendo `200` no mesmo instante — o discriminador entre o 429 de WAF e o de rate-limit.
- **Servidor de borda:** `Server: ATS`; a primeira resposta de uma sessão pode incluir `Set-Cookie` de bootstrap (`A3`), dispensável nas chamadas seguintes.
- **Upstream:** o header `x-envoy-decorator-operation` expõe `finance-search--mtls-production-usw2.finance-k8s:4080/*` em toda resposta `200` — o microserviço upstream que serve a família.

### 8.2 Comportamentos silenciosos

- **Página vazia é `200`, nunca `404`:** query sem matches, `count=0` ou `start` além do fim devolvem o envelope completo com `documents: []`, `total: 0` e `lookupTotals` zerado.
- **`total` não é o total global:** espelha `documents.length` da página (verificado: `start=50` de 53 → `total: 3`). O total global por tipo vive em `lookupTotals`; paginação deve computar o fim por `lookupTotals[type]`, não por `total`.
- **`lookupTotals.all` tem teto de exibição `10000`:** queries com mais de 10 000 matches (ex.: `Bank`, `S&P`) devolvem `all: 10000` — o valor para de crescer no teto.
- **`lookupTotals` supera `documents` entregues:** deltas de 1–3 contagens são sistemáticos (Apple: `equity: 53` → 52 entregues; Microsoft: `all: 113` → 112; Tesla: `all: 147` → 144) — matches contados no índice mas não entregues como documento, mesmo com `count` generoso.
- **Faixa alta de `count` é instável com match sets grandes:** validação aceita até `10000`, mas na prática a mesma célula alternou entre `200` cheio, `200` vazio e `500` JSON entre execuções na faixa ~3 000–9 999 (ex.: `Bank` + `count=8000` devolveu `0` documentos numa execução e `7 992` nas duas seguintes; `a` + `count=4000` devolveu `500` numa execução e `3 967` documentos nas duas seguintes). O `500` JSON é determinístico somente no extremo (`count=9999`/`10000` com matches ≥ 10 000, 5/5). Contrato prático: `count ≤ 2 000` é estável; a UI oficial usa `25`.
- **Vírgula em `type` é união:** `equity,etf` devolve documentos dos dois tipos somados (15+5), ordem irrelevante, duplicata colapsada; `all` em lista é descartado (`all,equity` ≡ `equity`).
- **`type` é case-sensitive mas tolera espaços nas bordas:** `" equity"` e `"equity "` equivalem a `equity`; o interior com case errado é rejeitado.
- **Query é case-insensitive e literal:** `aPPle` ≡ `APPLE` ≡ `Apple`; wildcard `*` é tratado como caractere comum (`apple*` ≡ `apple`); acentos são literais (`açúcar` → 0 resultados, sem erro).
- **Parâmetros no-op verificados por comparação de corpo:** `crumb` (garbage), `enableCb`, `enablePrivateCompany`, `quotesCount`, `enableFuzzyQuery` e params desconhecidos — corpo idêntico ao da requisição mínima.
- **`count=""` é tratado como ausente** (default `20` do servidor); `start` eco degenerado nos extremos: com 1 match, `start=9999` ecoa `count: 1` e `start=10000` ecoa `count: 0`, ambos com `documents: []` — os ecos de `count`/`total` não são contratuais nos extremos.

### 8.3 Volatilidade de campos intradiários

Os documentos carregam dois pares de cotação: `regularMarket*` (pregão regular) e `fullday*` (dia completo, incluindo sessão estendida quando o emissor a suporta). Fora do horário regular, o par `fullday*` continua populado enquanto o `regularMarket*` congela no último fechamento regular — são fontes distintas, não uma derivada da outra. Não há campos de book (`bid`/`ask`) nem `marketState` nesta família.

### 8.4 CORS

- `Access-Control-Allow-Origin` é fixo `https://finance.yahoo.com` — sem wildcard.
- Requisição com `Origin` estranho: o corpo é servido normalmente (`200`), porém **sem** o header `Access-Control-Allow-Origin` — o browser bloqueia a leitura, o servidor não filtra a resposta.
- Preflight (`OPTIONS` com `Origin` legítimo): `Access-Control-Allow-Headers: Content-Type, Origin, x-crumb, y-yf-enforce-crumb`; `Access-Control-Allow-Methods: GET, POST, PUT, DELETE, HEAD, OPTIONS`.
- Requisições sem header `Origin` (server-to-server) não recebem headers CORS — irrelevante para clientes não-browser.

### 8.5 Cache

| Header de Cache | Valor Observado | Observação |
| :--- | :--- | :--- |
| `cache-control` (200) | `public, max-age=300, stale-while-revalidate=120` | Respostas de sucesso |
| `cache-control` (4xx/5xx) | `max-age=0, private` | Erros não são cacheados |
| `etag` | ausente | Sem `If-None-Match`/`304` nesta família |

A non-determinismos de corpo entre gerações de cache da edge (células da faixa alta de `count` alternando cheio/vazio/500) é observável dentro da mesma janela — não contratar igualdade de corpo entre chamadas consecutivas grandes.

### 8.6 Relógio e unidades

- **Percentuais em unidades de %** nos dois pares (`regularMarketPercentChange`, `fulldayChangePercent`): `raw: -0.81` ↔ `fmt: "-0.81%"` — o `raw` espelha o número impresso; não multiplicar por 100.
- **`rank` é inteiro primitivo** mesmo com `formatted=true` — score de popularidade global do símbolo, não um offset de página.
- **`quoteType` em minúsculas** (`"equity"`, `"future"`) — conversão para maiúsculas é responsabilidade do cliente (a UI oficial aplica `.toUpperCase()` para tradução de rótulo).
- Não há timestamps nos documentos — nenhum campo de época nesta família.

### 8.7 Fluxo de credenciais no cliente

1. O transporte lê `stores.crumb.getCrumb()` — token disponível na sessão corrente.
2. Se a opção `crumb: true` estiver setada **e** houver token, o transporte anexa `?crumb=<token>` à URL (o header `x-crumb` é reservado para métodos não-GET, que não ocorrem nesta família).
3. Os cookies de sessão acompanham via `credentials: "include"` — ambos dispensáveis: o servidor não exige nem valida o par para este endpoint.

### 8.8 Paginação

A página oficial navega por `start` múltiplos de `count` (refetch completo a cada página). O fim do resultado para o tipo corrente é dado por `lookupTotals[<tipo>]` (`all` inclui todos); `documents` além do fim vazio. Não há cursor, token de continuação nem ordenação alternativa exposta — a ordem é fixa por `rank` decrescente.

### 8.9 Enriquecimento lateral (cliente)

Após receber `documents`, a página coleta `symbol` de cada item e dispara uma consulta de notícias por lista (`listName: "lookup"`, `queryRef: "newsAll"`) — tráfego adicional que pertence à página, não a este endpoint. Na primeira carga sem `query`, a página substitui a chamada por um recurso de ranking regional e monta um envelope sintético com `documents` desse outro recurso — o endpoint em si nunca recebe `query` vazia do cliente oficial.

### 8.10 Divergência bundle × servidor — `private_company`

O cliente oficial envia `type: "private_company"` no fluxo de resolução de empresa privada (`nodes/135.[hash].js`, rota `/company/{symbol}`), e a lista de abas da página `/lookup` inclui `private_company` sob a flag `enablePrivateCompany`. O servidor **rejeita** o tipo com `400` `Valid types: [...]` (verificado 2×) — o fluxo cliente colapsa no `catch` e degrada para redirect. A chave de contagem `lookupTotals.privateCompany` permanece presente no envelope (observada `0` em todas as queries), indicando capacidade planejada no índice mas seletor não habilitado na validação do servidor.

---

## 9. Referências do código-fonte (bundle)

### 9.1 Quem chama o endpoint e de onde vem o comportamento

| Arquivo | Imports | Papel / padrão de chamada |
| :--- | :--- | :--- |
| `chunks/loadLookup.[hash].js` | `f` de `quoteUtil.[hash].js`; `j`/`r`/`l` de `money.[hash].js` | `It` — fetcher único: guarda de query, flag `enablePrivateCompany`, montagem de query, espalhamento de `result[0]`, rejeição unificada |
| `nodes/143.[hash].js` | `l` de `loadLookup.[hash].js` | Página `/lookup` — `load` inicial + `$e` (paginação); abas de `lookupTotals`; enriquecimento de notícias |
| `nodes/135.[hash].js` | `l` de `loadLookup.[hash].js` | Página `/company/{symbol}` — resolução de empresa privada com `type: "private_company"` (rejeitado pelo servidor, §8.10) |
| `chunks/quoteUtil.[hash].js` | — | `Ue`/`ee` — transporte: host, `lang`/`region` default, `crumb` condicional, timeout, parse |

Importadores que **não** tocam o endpoint: `nodes/5.[hash].js`, `nodes/85.[hash].js`, `chunks/PfPrintTitle.[hash].js`, `chunks/Dock.[hash].js` (importam apenas a classe de diálogo de watchlist exportada pelo mesmo arquivo do fetcher) e `nodes/111.[hash].js` (import de efeito colateral).

### 9.2 Camada de serviço compartilhada

```js
// chunks/quoteUtil.[hash].js — ee (construtor de request do transporte)
async function ee(e, t, r) {
  if (t == null || !t.pathname) {
    const T = { message: "Bad request: pathname is required", status: 400 };
    a7(T, t);
    throw T;
  }
  const s = await e.parent();
  const { session, stores } = s;
  const i = stores.crumb.getCrumb();                    // token quando existir
  const o = s.serviceConfig ?? stores.config.getState()?.services;
  const u = o?.[t.key || "finance"] ?? {
    host: "query1.finance.yahoo.com",                   // host default da familia
    serverKey: "finance",
    client: { timeout: k }                              // k = 15000 ms
  };
  const l = {
    credentials: "include",                             // cookies acompanham (dispensaveis)
    method: "GET",
    mode: "cors",
    timeout: t.timeout ?? m,
    ...r
  };
  const f = {
    crumb: t.crumb ?? false,                            // It passa crumb: true
    host: undefined,
    isRelative: t.isRelative ?? false,
    pathname: t.pathname,                               // "/v1/finance/lookup"
    perfLabel: t.perfLabel || t.pathname,               // "loadLookup"
    protocol: t.protocol || "",
    query: t.query
  };
  if (!f.isRelative) {
    f.host = u.host;
  }
  const y = Ie(c ? f : Le(f, { serverKey: u?.serverKey }));  // SSR: /xhr/service + x-key
  if (!t.disableDefaultQueries) {
    y.searchParams.set("lang", session.lang || "en-US");     // default queries
    y.searchParams.set("region", session.region || "US");
  }
  if (f.crumb && i) {
    y.searchParams.set("crumb", i);                      // anexa so se houver token
  }
  const d = f.isRelative ? `${y.pathname}${y.search}` : y.toString();
  return { url: d, init: l, perfLabel: f.perfLabel ?? f.pathname ?? "", session };
}
```

### 9.3 Fluxo de credenciais no cliente

1. `stores.crumb.getCrumb()` no boot da sessão.
2. `It` pede `crumb: true`; o transporte anexa `?crumb=` **somente** se o store devolveu token.
3. `credentials: "include"` carrega cookies de sessão nativamente.
4. Servidor ignora ambos — o par nunca é validado nesta família.

### 9.4 Hosts e serialização

```js
// chunks/quoteUtil.[hash].js — Ie (URL) e ke (query object -> URLSearchParams)
function Ie(e) {
  let t;
  try {
    t = new URL(e.pathname ?? "", `${e.protocol || "https:"}//${e.host}`);
    if (e.query) {
      const r = ke(e.query);
      t.search = r.toString();
    }
  } catch (r) {
    ag(r, e);
  }
  return t;
}
function ke(e) {
  if (e instanceof URLSearchParams) {
    return e;
  }
  const t = new URLSearchParams();
  for (const [r, s] of Object.entries(e ?? {})) {
    if (s != null) {                                     // null/undefined nao serializam
      t.append(r, typeof s === "string" ? s : s.toString());
    }
  }
  return t;
}
```

### 9.5 Mapa resumido da cadeia

```
entry/app.[hash].js
  └── Rota /(app)/lookup/[[viewId]] → nodes/143.[hash].js
  │     ├── load() → It (chunks/loadLookup.[hash].js)
  │     │              └── Ue/ee (chunks/quoteUtil.[hash].js)
  │     │                       └── GET /v1/finance/lookup (query1, 15s)
  │     ├── $e() paginação → It (mesma cadeia)
  │     ├── abas: lookupTotals → Tabs
  │     ├── tabela: documents → DataTable/DataTablePagination
  │     └── notícias: lista "lookup"/"newsAll" (recurso lateral)
  └── Rota /(app)/company/[symbol] → nodes/135.[hash].js
        └── It({ type: "private_company" }) → 400 (§8.10) → catch → redirect
```

### 9.6 Contrato do consumidor final

| Consumidor | Tipo | Props / Consumo | Fonte |
| :--- | :--- | :--- | :--- |
| Página `/lookup` | SvelteKit page | `lookupData { type, documents, lookupTotals }`; colunas com query: `symbol`, `shortName`, `lastPrice` (de `regularMarketPrice`), `industryName`, `quoteType`, `exchange`; colunas sem query (fallback do recurso de ranking): `symbol`, `shortName`, `lastPrice`, `regularMarketChange`, `regularMarketChangePercent` | `nodes/143.[hash].js` |
| Guard polimórfico de `quoteType` | leitura defensiva | `typeof R.quoteType === "string" ? R.quoteType : R.quoteType?.quoteType` — o servidor devolve string; o fallback objeto é defesa do cliente | `nodes/143.[hash].js` |
| Abas de tipo | UI | `lookupTotals[U]` com mapa `{ private_company: "privateCompany" }`; rótulo `LABEL_WITH_COUNT` com `count` do total | `nodes/143.[hash].js` |

---

## 10. Guia de reimplementação

### 10.1 Algoritmo

```
1. Iniciar cliente HTTP com User-Agent de navegador e timeout de 15 s.
2. Nao existe handshake: cookie e crumb sao dispensaveis (endpoint anonimo).
3. Construir a query: query (obrigatoria), type, start, count,
   formatted, fetchPricingData, lang, region.
4. Executar GET https://query1.finance.yahoo.com/v1/finance/lookup.
5. Se HTTP 429: backoff exponencial (base 2 s, max 5 tentativas).
6. Se HTTP 500: distinguir — JSON "Server caught an exception" com count
   na faixa alta e matches grandes e deterministico (reduzir count e
   retentar); HTML intermitente se resolve com 1 retry.
7. Parsear finance.result[0]: documents + lookupTotals.
8. Paginar por lookupTotals[<tipo>] — nunca por result[0].total
   (que espelha apenas a pagina corrente).
9. Cache local de 300 s (alinha ao max-age da edge) quando a query
   for de pagina estavel.
```

### 10.2 Regras de parsing indispensáveis

1. **Unwrap** de `{raw, fmt}` nos 6 campos de preço quando `formatted=true`; `rank` permanece inteiro.
2. **Nome do percentual do pregão é `regularMarketPercentChange`** — não `regularMarketChangePercent`; portar o nome exato.
3. **Percentuais já em unidades de %** — `raw: -0.81` corresponde a `-0.81%`; não multiplicar por 100.
4. **`total` ≠ total global** — é `documents.length` da página; o global vive em `lookupTotals`.
5. **`quoteType` em minúsculas** (`"equity"`); normalizar para caixa alta só na apresentação.
6. **Campos podem faltar** — `industryName`/`industryLink` existem só em equities classificados; preços existem só sob `fetchPricingData=true`; tratar ausência como `null`.
7. **Ordem por `rank` decrescente** — não reordenar por preço/alfabeto sem intenção explícita.
8. **`lookupTotals` pode superar os documentos entregues** (delta 1–3) e tem teto de exibição `10000` — não usar como exact-match de `documents`.
9. **Envelope duplo**: sucesso e erro de validação usam `finance`; o `429` da borda é texto puro; o `500` pode ser JSON tipado ou HTML upstream.
10. **`count` prático ≤ 2 000** — a validação aceita até `10000`, mas a faixa alta com matches grandes é instável (§8.2).

### 10.3 Implementação de referência

O código executável completo reside no arquivo companheiro `v1_finance_lookup.py`, no mesmo diretório deste documento. O trecho abaixo é o núcleo:

```python
import json
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

def lookup(query, type_="all", start=0, count=20,
           formatted=True, fetch_pricing_data=True,
           lang="en-US", region="US", timeout=15):
    """GET /v1/finance/lookup — anonimo, sem cookie/crumb."""
    if not query:
        raise ValueError("query obrigatoria")
    params = {
        "query": query,
        "type": type_,
        "start": str(start),
        "count": str(count),
        "formatted": "true" if formatted else "false",
        "fetchPricingData": "true" if fetch_pricing_data else "false",
        "lang": lang,
        "region": region,
    }
    url = ("https://query1.finance.yahoo.com/v1/finance/lookup?"
           + urllib.parse.urlencode(params))
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))

def unwrap(field):
    """Extrai o valor cru de {raw, fmt} (formatted=true)."""
    if isinstance(field, dict) and "raw" in field:
        return field["raw"]
    return field

if __name__ == "__main__":
    body = lookup("Apple", count=25)          # default da pagina /lookup
    page = body["finance"]["result"][0]
    for doc in page["documents"]:
        print(doc["symbol"], doc["quoteType"], doc["rank"],
              unwrap(doc.get("regularMarketPrice")))
```

### 10.4 Notas de portabilidade

- [ ] **Sem Cookie Jar:** o endpoint é anônimo — nenhuma gestão de sessão é necessária; `urllib`/`requests` puros bastam com UA de navegador.
- [ ] **Sem renovação de credencial:** não há 401 nesta família (a menos que enforcement futuro seja ativado server-side — tratar 401 como sinal de mudança de contrato, não de sessão expirada).
- [ ] **Retry:** backoff em `429`; em `500` HTML 1 retry; em `500` JSON reduzir `count` (determinístico).
- [ ] **Cache:** respeitar `max-age=300` da edge; chave de cache `(query, type, start, count, formatted, fetchPricingData, lang, region)`.
- [ ] **Fallback de host:** `query2` e `iquery` servem o mesmo contrato — alternância trivial de prefixo.
- [ ] **URL encoding:** a query é texto livre — percent-encode integral (`^`, `=`, `,`, acentos); a vírgula dentro de `query` é literal, dentro de `type` é separador de união.

---

## 11. Apêndice — amostras JSON reais

### 11.1 Resposta (`formatted=true`, `fetchPricingData=true`) — `Apple`, `type=all`, `count=25` (página oficial)

```json
{
  "finance": {
    "result": [
      {
        "start": 0,
        "count": 25,
        "total": 25,
        "documents": [
          {
            "industryName": "Technology",
            "symbol": "AAPL",
            "fulldayChangePercent": { "raw": -0.7627103924751282, "fmt": "-0.76%" },
            "regularMarketPercentChange": { "raw": -0.8107566237449646, "fmt": "-0.81%" },
            "regularMarketChange": { "raw": -2.699981689453125, "fmt": "-2.70" },
            "fulldayChange": { "raw": -2.53997802734375, "fmt": "-2.54" },
            "quoteType": "equity",
            "fulldayPrice": { "raw": 330.260009765625, "fmt": "330.26" },
            "regularMarketPrice": { "raw": 330.32000732421875, "fmt": "330.32" },
            "industryLink": "https://finance.yahoo.com/sector/technology",
            "rank": 516650,
            "exchange": "NMS",
            "shortName": "Apple Inc."
          },
          {
            "symbol": "SAAPL=F",
            "fulldayChangePercent": { "raw": -0.8831929564476013, "fmt": "-0.88%" },
            "regularMarketPercentChange": { "raw": -0.8831929564476013, "fmt": "-0.88%" },
            "regularMarketChange": { "raw": -2.970001220703125, "fmt": "-2.97" },
            "rank": 30161,
            "exchange": "CME",
            "fulldayChange": { "raw": -2.970001220703125, "fmt": "-2.97" },
            "shortName": "Apple Inc Stock Futures,Dec-202",
            "quoteType": "future",
            "fulldayPrice": { "raw": 333.30999755859375, "fmt": "333.31" },
            "regularMarketPrice": { "raw": 333.30999755859375, "fmt": "333.31" }
          }
        ],
        "lookupTotals": {
          "all": 126, "equity": 53, "mutualfund": 11, "etf": 35,
          "index": 11, "currency": 0, "future": 6,
          "cryptocurrency": 10, "privateCompany": 0
        }
      }
    ],
    "error": null
  }
}
```

*(Primeiros 2 documentos da resposta real de 25; a ordem de chaves é a do servidor. A resposta integral crua está no arquivo companheiro `v1_finance_lookup.json`.)*

### 11.2 Documento sem pricing (`fetchPricingData=false`) — mesmas chaves base

```json
{
  "exchange": "NMS",
  "industryLink": "https://finance.yahoo.com/sector/technology",
  "industryName": "Technology",
  "quoteType": "equity",
  "rank": 516650,
  "shortName": "Apple Inc.",
  "symbol": "AAPL"
}
```

### 11.3 Erro HTTP 400 — `query` ausente

```json
{
  "finance": {
    "result": null,
    "error": {
      "code": "Bad Request",
      "description": "Missing required query parameter=query"
    }
  }
}
```

### 11.4 Erro HTTP 400 — `type` inválido (case errado, desconhecido ou `private_company`)

```json
{
  "finance": {
    "result": null,
    "error": {
      "code": "Bad Request",
      "description": "Valid types: [equity, mutualfund, etf, index, currency, future, cryptocurrency]"
    }
  }
}
```

### 11.5 Erro HTTP 405 — `POST`

```json
{
  "finance": {
    "result": null,
    "error": {
      "code": "Method Not Allowed",
      "description": "HTTP 405 Method Not Allowed"
    }
  }
}
```

### 11.6 Erro HTTP 500 — classe determinística (`count=9999` com matches ≥ 10 000)

```json
{
  "finance": {
    "result": null,
    "error": {
      "code": "Internal Server Error",
      "description": "Server caught an exception"
    }
  }
}
```

### 11.7 Página vazia legítima (`start` além do fim) — HTTP 200

```json
{
  "finance": {
    "result": [
      {
        "start": 500,
        "count": 20,
        "total": 0,
        "documents": [],
        "lookupTotals": {
          "all": 126, "equity": 53, "mutualfund": 11, "etf": 35,
          "index": 11, "currency": 0, "future": 6,
          "cryptocurrency": 10, "privateCompany": 0
        }
      }
    ],
    "error": null
  }
}
```

---

*Referências dos arquivos analisados*

- `chunks/loadLookup.[hash].js` — fetcher `It` (export `l`) e classe de diálogo de watchlist (export `C`)
- `chunks/quoteUtil.[hash].js` — transporte `Ue`/`ee` (export `f`), construção de URL `Ie`/`ke`, timeout `k = 15000`
- `nodes/143.[hash].js` — página `/lookup` (rota `/(app)/lookup/[[viewId]]`): `load`, paginação `$e`, abas de `lookupTotals`, colunas da tabela
- `nodes/135.[hash].js` — página `/company/{symbol}` (rota `/(app)/company/[symbol]`): resolução de empresa privada com `type: "private_company"`
- `nodes/5.[hash].js`, `nodes/85.[hash].js`, `chunks/PfPrintTitle.[hash].js`, `chunks/Dock.[hash].js`, `nodes/111.[hash].js` — importadores do chunk sem consumo do endpoint
- `chunks/money.[hash].js` — `by` (sessão), `ue` (leitura de feature flag), `HS` (logger de erro estruturado)
- `entry/app.[hash].js` — tabela de rotas do SvelteKit
