## YH Finance API Specification

![Yahoo Finance](https://upload.wikimedia.org/wikipedia/commons/9/9f/Yahoo%21_Finance_logo.svg)

**Data de atualização:** 19/10/2026

---

### GET /v1/finance/currencies

Catálogo de referência de moedas do Yahoo Finance: 154 itens com `{symbol, shortName, longName, localLongName}`,
usados pelo seletor de moeda dos fluxos de portfólio do cliente oficial. É um endpoint anônimo — responde
`200` sem cookie e sem crumb, e um `crumb` inválido na query é ignorado sem efeito. O envelope de sucesso é
de topo próprio (`currencies.result` como array) e NÃO usa a camada `finance` dos endpoints de leitura de
mercado; a camada `finance` só aparece nos envelopes de erro. A barra final é rejeitada com `404` em texto
puro (`Not Found`, sem envelope JSON). A localização do catálogo é dirigida pelo
`lang` SOZINHO — único campo sensível é `localLongName`. A ordem dos itens no fio NÃO é contratual: o
conteúdo é estável, mas a sequência varia entre requisições — o cliente oficial ordena por `longName`
antes de usar.

| | |
| :--- | :--- |
| Método | `GET` — aceita também `HEAD` (200, corpo vazio, cache `private, no-cache, no-store`) e `OPTIONS` (200, `Allow: HEAD,GET,OPTIONS`; corpo negociado pelo `Accept` — WADL integral com `*/*`/`application/vnd.sun.wadl+xml`, vazio com `application/json`); `POST` → `405` com envelope de erro e SEM header `Allow` |
| Hosts | `query1` · `query2` (`.finance.yahoo.com` — os dois ativos e com o mesmo conteúdo; `query1` é o padrão do cliente) |
| Caminho | `/v1/finance/currencies` — barra final rejeitada: `/v1/finance/currencies/` → `404` (ver bloco 4) |
| Autenticação | Anônima — 200 sem cookie e sem crumb; com cookie de sessão o conteúdo é idêntico · `crumb` é aceito e ignorado em TODAS as variantes: query (garbage ou **válido** de getcrumb) e header `x-crumb` (garbage ou válido), com ou sem cookie (endpoint sem enforcement) |
| User-Agent | Agente de navegador obrigatório — `Python-urllib` recebe `429 Edge: Too Many Requests` |
| Accept | Ausente ou `application/json` → `200`; `text/plain` → `406` com envelope de erro |
| Cache de borda | `public, max-age=3600, stale-while-revalidate=3600` (1 h) |
| Content-Type | `application/json;charset=utf-8` |

```json5
{
  // ==========================================================================
  // 1 · PARÂMETROS DA REQUISIÇÃO
  // ==========================================================================

  // Linha de requisição canônica (anônima):
  //
  //   curl -s \
  //     -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36" \
  //     "https://query1.finance.yahoo.com/v1/finance/currencies?lang=en-US&region=US"

  request: {
    method: "GET",
    path: "/v1/finance/currencies",
    params: {
      lang: "en-US",   // Dirige a localização de localLongName SOZINHO — não precisa de
                       //   region em par, nem presente no fio (verificado: só lang localiza)
                       //   · interpretação LENIENTE do servidor: case (PT-BR / pt-br),
                       //   underscore (pt_BR) e tag curta (pt) localizam como pt-BR ·
                       //   valor vazio (lang=) e inválido (xx-XX) → default en-US ·
                       //   chave duplicada → a PRIMEIRA ocorrência vence (ver bloco 5) ·
                       //   no cliente oficial, o valor que chega no fio é o da SESSÃO:
                       //   o transporte sobrescreve o query com searchParams.set
                       //   (ver bloco 6)
      region: "US",    // INDEPENDENTE da localização neste endpoint — sozinho não muda
                       //   nada e em par não altera o efeito do lang · ausente/inválido
                       //   → default do servidor (US) · também sobrescrito pelo
                       //   transporte com o valor da sessão

      // Chaves desconhecidas na query são aceitas e ignoradas silenciosamente
      // (verificado: foo=bar devolve o mesmo conteúdo).
    },
  },
}
```

Semântica e casos de borda por parâmetro:

| Parâmetro | Tipo | Obrigatório | Padrão | Comportamento e Casos de Borda |
| :--- | :--- | :---: | :--- | :--- |
| `lang` | string | Não | `en-US` (servidor) | Localiza **apenas `localLongName`** — e é o **`lang` sozinho** que dirige a localização (`lang=pt-BR&region=US` já localiza; ver bloco 5). Valor inválido cai no conteúdo do default. |
| `region` | string | Não | `US` (servidor) | Independente da localização neste endpoint: sozinho não altera nada e em par não modifica o efeito do `lang`. |
| `currency` | string | Não | `""` (servidor) | FILTRO da lista: `currency=USD` devolve só o item USD (mesma forma de 4 chaves — `shortName`/`longName`/`symbol`/`localLongName`); CSV NÃO suportado — `currency=BRL,USD` → `500` `Internal Server Error` (`Server caught an exception`); declarado no WADL do OPTIONS com default vazio. |

> **Convenções:**
> - Sem query nenhuma o servidor responde o **mesmo conteúdo** de `lang=en-US&region=US`
>   (154 itens) — os dois parâmetros têm default no servidor.
> - Chaves desconhecidas na query string são ignoradas silenciosamente (verificado:
>   `foo=bar` devolve o mesmo conteúdo).
> - `lang` é interpretado com **leniência**: `PT-BR`, `pt-br`, `pt_BR` e `pt` (tag
>   curta) localizam TODOS como pt-BR — normalização de case/underscore/prefixo no
>   servidor. Só caem no default en-US os valores vazios (`lang=`) e não
>   reconhecíveis (`xx-XX`).
> - Chave duplicada (`lang=pt-BR&lang=en-US`) → a **primeira ocorrência vence**
>   (resposta localizada em pt-BR).
> - A **ordem dos itens NÃO é contratual**: em 6 chamadas canônicas consecutivas o
>   conteúdo foi idêntico 6/6, mas a sequência variou (5 sequências distintas), com os
>   4 primeiros símbolos estáveis (`FJD MXN SCR CDF`). Consumidor que precisa de ordem
>   determinística deve ordenar no receptor — é o que faz o cliente oficial (bloco 6).

#### Constantes padrão

```json5
{
  // ==========================================================================
  // 2 · CONSTANTES PADRÃO DO ENDPOINT (valores nativos do serviço)
  // ==========================================================================

  "hosts": [
    "https://query1.finance.yahoo.com",   // Host padrão
    "https://query2.finance.yahoo.com"    // Espelho secundário — mesmo conteúdo
  ],

  "defaults": { "lang": "en-US", "region": "US" },  // sem query → mesmo conteúdo

  // Envelope de SUCESSO é de topo próprio — NÃO há camada finance:
  "envelope": {
    "sucesso": "currencies.result (array) + currencies.error: null",
    "erro": "a camada finance SÓ aparece em envelopes de erro (405/406)"
  },

  "contagem": 154,   // 154 itens, 154 símbolos únicos — verificado em todo locale

  // Invariantes do catálogo (verificado item a item nos 154):
  "invariantes": {
    "symbol": "≡ shortName em todos os itens",
    "longName": "invariante por locale — nome por extenso não muda com lang",
    "primitivo": "todas as chaves são strings simples — não há embrulho {raw, fmt} em parâmetro algum (formatted não tem efeito algum no corpo)"
  },

  // Curiosidades cravadas do catálogo (mesmas no en-US e no pt-BR):
  "curiosidades": {
    "ZMW": "longName não expandido — 'ZMW' igual ao símbolo",
    "SLE/SLL": "dois símbolos com o MESMO longName 'Sierra Leonean Leone'"
  }
}
```

#### Contrato do item

```json5
{
  // ==========================================================================
  // 3 · SHAPE DO ITEM DO CATÁLOGO
  // ==========================================================================

  // Cada item do array currencies.result tem EXATAMENTE 4 chaves, todas
  // strings primitivas (sem {raw, fmt}):
  "shapeDoItem": {
    "symbol":        "código da moeda — igual ao shortName (verificado nos 154)",
    "shortName":     "sigla — ex.: 'FJD'",
    "longName":      "nome por extenso, INVARIANTE por locale — ex.: 'Fijian Dollar'",
    "localLongName": "nome LOCALIZADO do lang — ex.: 'Dólar de Fiji' no pt-BR · é o ÚNICO campo sensível a locale"
  },

  // Exemplos reais do par pt-BR (verificados ao vivo):
  "exemplosPtBR": {
    "FJD": { "longName": "Fijian Dollar", "localLongName": "Dólar de Fiji" },
    "USD": { "longName": "US Dollar",     "localLongName": "Dólar norte-americano" },
    "BRL": { "longName": "Brazilian Real", "localLongName": "Real brasileiro" }
  }
}
```

#### Resposta e erros

```json5
{
  // ==========================================================================
  // 4 · RESPOSTA E ERROS
  // ==========================================================================

  "sucesso": {
    "status": 200,
    "corpo": "currencies.result (array de 154 itens) + currencies.error: null",
    "anonimo": "idêntico sem cookie e sem crumb"
  },

  "langRegionInvalidos": {
    "status": 200,
    "corpo": "conteúdo igual ao default en-US/US",
    "nota": "lang=xx-XX&region=ZZ devolve o catálogo em inglês — fallback do servidor"
  },

  "post": {
    "status": 405,
    "corpo": {
      "finance": {
        "result": null,
        "error": { "code": "Method Not Allowed", "description": "HTTP 405 Method Not Allowed" }
      }
    },
    "allow": "a resposta 405 NÃO traz header Allow — e usa a camada finance que o sucesso não tem"
  },

  "head": { "status": 200, "corpo": "vazio (0 bytes)",
            "cache": "private, no-cache, no-store (diferente do GET: max-age=3600)" },
  "options": { "status": 200, "allow": "HEAD,GET,OPTIONS", "cache": "private, no-cache, no-store",
               "corpo": "NEGOCIADO pelo Accept — com */* ou application/vnd.sun.wadl+xml devolve o WADL integral (framework Jersey 2.33; method id currencyInfo; params currency vazio, region=US, lang=en-US); com application/json → corpo vazio (0 bytes), content-type application/json" },

  "borda": {
    "uaNaoNavegador": "429 Edge: Too Many Requests (Python-urllib)",
    "acceptTextPlain": "406 com envelope finance (code 'Not Acceptable')",
    "cache": "public, max-age=3600, stale-while-revalidate=3600 — resposta em cache pode ter até 1 h de atraso",
    "barraFinal": "/v1/finance/currencies/ (com barra) → 404 text/html com corpo TEXTO PURO 'Not Found' — SEM envelope JSON (diferente do 405/406, que têm envelope) e cache-control: no-store (contraste com o 200: max-age=3600)",
    "crumb": "todas as variantes ignoradas: crumb garbage na query, crumb VÁLIDO (getcrumb) na query, header x-crumb (válido e garbage), com e sem cookie — sempre 200 com o mesmo conteúdo"
  },

  // A ordem dos itens varia entre requisições (verificado em 6 chamadas
  // consecutivas: conteúdo idêntico, 5 sequências distintas). NÃO interpretar
  // posição como dado — resolver por symbol.
  "ordemNaoContratual": {
    "conteudo": "estável — 6/6 chamadas com o mesmo conteúdo",
    "sequencia": "varia — transposições de posição observadas entre chamadas idênticas",
    "cabeca": "os 4 primeiros símbolos (FJD MXN SCR CDF) foram estáveis no período observado, sem valor de contrato"
  }
}
```

#### Efeito do locale (lang sozinho)

```json5
{
  // ==========================================================================
  // 5 · SEMÂNTICA DA LOCALIZAÇÃO — DIFERENTE DO PAR lang+region DOS DEMAS
  // ==========================================================================

  // Aqui o lang NÃO precisa de region em par (ao contrário de
  // /ws/market-info/v1/finance/markets/ids, onde o par é avaliado em conjunto):
  "regra": {
    "langSozinhoLocaliza": "lang=pt-BR&region=US → localLongName em português (verificado)",
    "langSemRegionNoFio": "só lang, SEM region na query → localiza igual (lang=pt-BR sozinho = catálogo pt-BR inteiro, 154 itens — verificado)",
    "leniente": "case (PT-BR / pt-br), underscore (pt_BR) e tag curta (pt) localizam TODOS como pt-BR — normalização do servidor antes do lookup",
    "regionIndependente": "lang=en-US&region=BR → catálogo em inglês, idêntico ao default (verificado)",
    "regionNaoMudaLang": "lang=pt-BR&region=BR → mesmo conteúdo de lang=pt-BR&region=US (verificado)",
    "invalido": "lang inválido → conteúdo do default en-US/US (verificado com xx-XX)",
    "vazio": "lang= (valor vazio) → conteúdo do default en-US/US (verificado)",
    "duplicada": "lang=pt-BR&lang=en-US → a PRIMEIRA ocorrência vence (resposta em pt-BR, verificada)"
  },

  // O que muda e o que não muda com o locale:
  "efeito": {
    "localLongName": "ÚNICO campo localizado",
    "symbol/shortName": "invariantes",
    "longName": "invariante — 'Fijian Dollar' em todo locale",
    "conjunto": "o mesmo 154 em todo locale — locale NÃO adiciona nem remove moedas"
  }
}
```

#### Notas do cliente oficial

```json5
{
  // ==========================================================================
  // 6 · COMPORTAMENTO DO CLIENTE OFICIAL (loader loadCurrencies)
  // ==========================================================================

  "loader": {
    "assinatura": "Vl(n, { reuseData = true, region = 'US', lang = 'en-US' }) — n é o load-event; NENHUM chamador passa o 2º argumento: são os defaults do loader que montam a query",
    "cachePrimeiro": "store 'currency' — com reuseData (default), getCurrencies().length > 0 devolve o cache sem rede",
    "parse": "currencies.result deve ser Array (checa a.constructor !== Array); caminho NÃO-Array devolve [] SEM log nenhum — só a falha de TRANSPORTE passa pelo logLoadError",
    "ordenacao": "sort por longName (localeCompare, tolerante a longName ausente) MUTA o array no lugar — o MESMO array ordenado é guardado na store E devolvido ao chamador",
    "falha": "silenciosa — log do erro com perfLabel loadCurrencies e retorno []",
    "crumb": "o loader não pede crumb — chamada anônima no fio (com cookie de sessão, o conteúdo é idêntico: verificado)"
  },

  // Inventário fechado de funções (auditoria integral): nenhuma outra função da
  // árvore do cliente emite /v1/finance/currencies — varredura completa.
  "inventarioDeFuncoes": {
    "Vl": "loadCurrencies — ÚNICA função que toca o endpoint (export 'l' do módulo updateLots)",
    "storeCurrency": "classe 'currency' (support_agent): getInitialState {currencies: []} · updateCurrencies (substitui o array) · getCurrencies (lê) — pass-through: NÃO re-ordena nem transforma",
    "loadStores": "plumbing puro — resolve as stores do contexto do componente, sem rede",
    "consumidoresReadOnly": "PfPrintTitle e PortfolioDetailTableContainer só LÊEM getCurrencies() — nunca disparam rede"
  },

  // Dois chamadores, ambos em onMount e com guarda de store vazia — o cache-first
  // do loader é reforçado no chamador (guarda dupla):
  "chamadores": {
    "updateLots": "onMount do formulário de lotes do portfólio: dispara se showCurrency && lista da store vazia",
    "addNewPortfolioButton": "onMount do botão de novo portfólio: dispara se a lista da store estiver vazia",
    "nota": "ambos passam só o load-event — nunca lang/region custom; no fio real, lang e region vêm da SESSÃO via transporte (sobrescrita)"
  },

  // Ponto decisivo do transporte: o loader monta query {lang, region}, mas o
  // transporte SOBRESCREVE os dois com os valores da SESSÃO (searchParams.set
  // lang/region, fallback en-US/US) — os defaults do loader só chegam ao fio
  // sem sessão:
  "transporte": {
    "sobrescrita": "lang e region do fio vêm da SESSÃO, não dos argumentos do loader",
    "host": "resolvido pelo config do serviço — default query1"
  }
}
```
