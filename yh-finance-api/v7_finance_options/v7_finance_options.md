# `GET /v7/finance/options/{symbol}`

> **Data de atualização:** 2026-11-06 · **Revalidação ao vivo dos query strings:** 97 chamadas ao endpoint + 8 de bootstrap, sessão anônima `A3` + `crumb`, UA de navegador (Chrome 131), 1,2 s entre chamadas, sem `5xx` · **Bateria autenticada original:** 2026-11-05 (~16 chamadas) · **Capturas cruzadas:** AAPL 2026-10-01→02 (POSTPOST, 22 expirações, 69 strikes, 65+59 contratos) e NVDA 2026-09-25 ~16:36 EDT (REGULAR, 79 strikes, com `date` explícito) · **Fonte estática:** build SvelteKit de produção (o loader da página de opções e a camada de transporte compartilhada).

---

## Resumo

A superfície **efetiva** de query strings é composta por **9 parâmetros**:

```text
date · formatted · straddle · strikeMin · strikeMax · getAllData · lang · region · crumb
```

Além deles, o servidor **aceita e ignora** `strike`, `corsDomain`, `symbols`, `fields`, `includePrePost`, `useYfid`, `interval`, `range`, `guccounter` e qualquer parâmetro desconhecido.

Três regras que costumam ser implementadas de forma errada:

1. **`strikeMin`/`strikeMax` não-numéricos também retornam `400`** (114 B), não só `date`. Ex.: `strikeMin=abc` → `Parameter=strikeMin has an invalid type`.
2. **`getAllData=true` NÃO sobrepõe um `date` específico.** Ele expande todas as expirações apenas quando `date` está **ausente** ou é `-1`. Com `date=<epoch válido>`, devolve **só aquela expiração**; com `date=0`/`-2`, devolve **uma entrada vazia** ecoando o valor.
3. **Parâmetros duplicados: a PRIMEIRA ocorrência vence** — vale para `date`, `formatted`, `straddle` e `crumb`. Não é “last wins”.

O modo strike do app (`strikeMin=strikeMax=<k>&getAllData=true`, **sem `date`**) funciona e devolve **uma entrada por vencimento**; o header `strikes` expande para a união de todas as expirações (`76` → `130` no AAPL de 2026-11-06). O modo straddle (`straddle=true`) funciona com `date`, com o modo strike e sozinho.

### Queries canônicas

```http
# Cadeia do vencimento mais próximo (canônica do app)
GET /v7/finance/options/AAPL?date=-1&formatted=true&straddle=false&lang=en-US&region=US&crumb=<CRUMB>

# Strike único em todos os vencimentos (o app remove o date)
GET /v7/finance/options/AAPL?formatted=true&straddle=false&strikeMin=160&strikeMax=160&getAllData=true&lang=en-US&region=US&crumb=<CRUMB>
```

---

Cadeia de opções de **um símbolo por chamada**: devolve o catálogo de expirações, a escala de strikes e os contratos (calls/puts) da expiração pedida — e traz o **quote completo do subjacente embutido** na mesma resposta (83–90 campos de cotação consolidada; 90 no AAPL de 2026-11-06, com as classes de borda: deslistado chega com `quoteType: NONE` e mudança de nome recente carrega `prevName`/`nameChangeDate`). É o dado da página de opções do site.

O handshake é em **2 passos obrigatórios** — Cookie `A3` + `crumb`; sem crumb a resposta é `401` com envelope de 89 B, e a **barra final é rejeitada com `404` em texto puro** (sem envelope JSON). A seleção é feita em DUAS camadas — o `symbol` no **path** escolhe o subjacente (não existe parâmetro de seleção por query) e o `date` (epoch em segundos) escolhe a expiração, com o literal `date=-1` (o valor que o próprio aplicativo web envia) resolvendo para a **primeira expiração futura**.

Há um segundo protocolo de leitura: pedido de strike único via `strikeMin`/`strikeMax` + `getAllData` SEM `date` — devolve **uma entrada por vencimento** (todas as expirações) e o header `strikes` se expande para a união de todas. O modo straddle (`straddle=true`) troca `calls/puts` por pares `{strike, call, put}` por strike. Existe um endpoint irmão distinto — `GET /v7/finance/options/analytics/{symbol}` — que devolve summaries de volume/interesse aberto e listas top-10 (aqui são a cadeia e os contratos).

| | |
| :--- | :--- |
| Método | `GET` — aceita também `HEAD` (`200` com crumb, corpo vazio; `401` sem) e `OPTIONS` (`200`, `Allow: HEAD,GET,OPTIONS`); `POST` → `405` |
| Hosts | `query1` · `query2` (`.finance.yahoo.com` — espelhos com o mesmo conteúdo: mesmo `200` e mesmas expirações; backend identificado pelo header `x-envoy-decorator-operation: finance-quote-api--mtls-production-use1.finance-k8s:4080/*`) |
| Caminho | `/v7/finance/options/{symbol}` — `/v7/finance/options/AAPL/` (barra final) → `404` `Not Found` em **texto puro**; `/v7/finance/options/` (sem symbol) → `404` **com envelope finance** (`code: "Not Found"`) — duas rejeições diferentes do mesmo status |
| Autenticação | **Obrigatória** — Cookie `A3` + `crumb` (vetor query string); sem crumb, crumb errado ou sem cookie → `401` com envelope `{"finance":{"result":null,"error":{"code":"Unauthorized","description":"Invalid Crumb"}}}` (89 B) |
| User-Agent | Agente de navegador obrigatório — `curl` default/`Python-urllib` e afins recebem `429 Edge: Too Many Requests` |
| Cache de borda | **`public, max-age=1, stale-while-revalidate=9`** no GET `200` (janela de borda de ~10 s) · `private, no-cache, no-store` no `HEAD` (nunca cacheável) · `max-age=0, private` + `Expires: -1` no `401` |
| Payload típico | **chamada mínima (só `{symbol}`+`lang`+`region`+`crumb`): 48,9 KB** — cadeia completa da primeira expiração futura, contrato com o esquema canônico de 15 campos em valores crus · **cadeia canônica AAPL (`date=-1`, `formatted=true`): 98,1 KB** (o invólucro `{raw, fmt, longFmt}` duplica o tamanho dos números) · **strike único + `getAllData`: 25,4 KB** (21 vencimentos) · **straddle: 102,1 KB** (76 pares) · **cadeia integral (`getAllData` com `date` ausente/`-1`): ~1,78 MB** (2.747 contratos, 21 vencimentos) · `date` sem contratos: 3,2 KB · símbolo sem cadeia: 1,9–2,6 KB · símbolo inexistente: **42 B** (`result: []`) |

## Autenticação e User-Agent

O handshake tem duas etapas. Primeiro, capturar o Cookie `A3`: um GET em `fc.yahoo.com` responde `404` **sem redirect** — o `Set-Cookie` na resposta é o payload (guardar com `-c`). Segundo, emitir o crumb casado com esse cookie em `v1/test/getcrumb`, mandando UA de navegador e `Referer` de finance.yahoo.com (sem eles a edge responde `429`). O crumb viaja na **query string** em GET; o vetor de header `x-crumb` também funciona sozinho em GET, mas quando a query está presente ela é a única que vale. Revalidação de 2026-11-06: `fc.yahoo.com` → `404` + `A3`; `getcrumb` → `200` com crumb de 11 caracteres; crumb válido **sem** o cookie `A3` → `401`; crumb duplicado → **primeira ocorrência vence**; `401 Invalid Crumb` em todas as combinações sem crumb válido; `429 Edge` por assinatura de User-Agent — o bloqueio é por agente, não por volume.

```bash
# 1. Capturar o Cookie A3 (404 SEM redirect — o Set-Cookie é o payload)
curl -s -c cookies.txt "https://fc.yahoo.com" > /dev/null

# 2. Emitir o Crumb casado com o cookie
CRUMB=$(curl -s -b cookies.txt \
  -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36" \
  -H "Referer: https://finance.yahoo.com/" \
  "https://query1.finance.yahoo.com/v1/test/getcrumb")

# 3. Cadeia do vencimento mais próximo (canônica do app — date=-1 literal)
curl -s -b cookies.txt \
  -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36" \
  "https://query1.finance.yahoo.com/v7/finance/options/AAPL?date=-1&formatted=true&straddle=false&lang=en-US&region=US&crumb=${CRUMB}"

# 4. Visão de um strike (clique em um strike na página) — todos os vencimentos
curl -s -b cookies.txt \
  -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36" \
  "https://query1.finance.yahoo.com/v7/finance/options/AAPL?formatted=true&straddle=false&strikeMin=160&strikeMax=160&getAllData=true&lang=en-US&region=US&crumb=${CRUMB}"
```

## Parâmetros da requisição

### Parâmetro de path

| Parâmetro | Tipo | Obrigatório | Comportamento e Casos de Borda |
| :--- | :---: | :---: | :--- |
| `{symbol}` | string | **Sim** | O subjacente — URL-encoded quando preciso (`^GSPC` → `%5EGSPC`). **Case-insensitive**: `aapl` → `underlyingSymbol: "AAPL"` (normalização para caixa alta). ÚNICA seleção de ativo: não existe parâmetro de query que o troque (`symbols=MSFT` enviado junto devolve `underlyingSymbol: AAPL` — ignorado). SEM lote: `AAPL,MSFT` (vírgula no path) → **`200` com `result: []`** (42 B — vira um "símbolo" que não existe). Sem validação de formato no servidor: símbolo inexistente → **`200` com `result: []`** (42 B — nunca 4xx/5xx); deslistado (TWTR) → **`200`** com `quoteType: NONE`, `expirationDates: []` e `options[0] = {}` vazio; ativo sem cadeia pública no feed (PETR4.SA/B3, `^GSPC`) → **`200`** com arrays vazios e o **quote completo** do subjacente (o único conteúdo útil nesses casos; `^GSPC` = 1.885 B). |

### Parâmetros de query

| Categoria | Parâmetro | Tipo | Obrig. | Padrão | Comportamento e Casos de Borda |
| :--- | :--- | :--- | :---: | :--- | :--- |
| **Vencimento** | `date` | int | Não | `-1` no app (servidor: primeira futura) | Expiração pedida — **epoch em SEGUNDOS INTEIRO**, um valor DE `expirationDates`. **Ausente = o mesmo default**: a chamada mínima (sem `date`) devolveu `options[0].expirationDate ≡ expirationDates[0]` — primeira expiração futura. O literal **`-1` é a forma canônica do aplicativo** (vai LITERAL no fio no load inicial) com o mesmo efeito. `date=<epoch>` → cadeia daquele vencimento (a captura NVDA de 09-25 veio com `options[0]` em 10-02 ≠ `expirationDates[0]` em 09-25 — prova do parâmetro no fio). Casos de borda (todos verificados em 2026-11-05/06): **não-inteiro (`abc`, `1.5`) → `400`** com envelope `{"code":"Bad Request","description":"Parameter=date has an invalid type"}` (109 B) — **não é o único `400` da família**: `strikeMin`/`strikeMax` não-numéricos também retornam `400` (114 B; ver abaixo); **inteiro fora da lista (`0`, `-2`, `9999999999`) → `200`** com o envelope intacto (`expirationDates` e quote completos) mas `strikes: []` e `options[0] = {expirationDate: <o pedido>, hasMiniOptions: false, calls: [], puts: []}` — o valor é ECOADO (o `0` não é tratado como ausente), degradação graciosa. `date` específico **limita** o efeito de `getAllData` àquela expiração (ver abaixo). |
| **Formatação** | `formatted` | bool | Não | **ausente ≡ `false`** (o app envia `true` sempre) | Empacota os valores numéricos dos CONTRATOS em `{raw, fmt[, longFmt]}` (o quote embutido e `inTheMoney`/`currency`/`contractSymbol`/`contractSize` ficam crus de qualquer forma). **Parsing case-insensitive: `TRUE` ativa** (verificado). `formatted=false` ou **ausente** → **números crus no fio** (verificado: `strike: 160`, `lastPrice: 184.91`, `volume: 11` — sem invólucro) — e a chamada mínima preserva o esquema de 15 campos por contrato; a única omissão observada é **`volume`** (ausente quando não houve negociação no dia): 1 contrato em 146 na mínima de 2026-11-05 e 3 em 124 na captura de out/2026 — `lastTradeDate` permaneceu presente nesses casos. `longFmt` (formato longo) aparece em `volume`/`openInterest` (milhar) e em `lastTradeDate`/`expiration` (data e hora). O `volume` é **OMITIDO** (não nulo), não zerado. `formatted=true` praticamente dobra o payload; `1` **não** ativa (é `false`), `abc` também é `false`. |
| **Layout / Modo** | `straddle` | bool | Não | `false` (ausência ≡ false) | **MODO STRADDLE** — `true` troca `calls[]/puts[]` por `straddles[]`: um par por strike com o **strike FORA das pernas** — `{"strike": {"raw":110,"fmt":"110.00"}, "call": {…}, "put": {…}}` (76 pares em AAPL — não é um zip ingênuo de calls+puts). **As pernas são OPCIONAIS**: contagem varia por sessão (na captura de 2026-11-05, 5 pares sem `call` e 1 sem `put`). Parsing case-insensitive (**`TRUE` ativa**) e **sem coerção numérica: `straddle=1` NÃO ativa** (tratado como false — verificado); `abc` também é `false`. O aplicativo envia o valor como STRING (`"true"`/`"false"`). **Funciona com `date`** (40 straddles na 2ª expiração) **e com o modo strike** (21 entradas, 16 straddles para o strike 160). |
| **Faixa de strikes** | `strikeMin` / `strikeMax` | num | Não | — | Limites **inclusivos** da malha de strikes — **funcionam isolados** (verificado): `strikeMin=300` isolado → 41 calls de 300 a 415; `strikeMax=200` isolado → 12 calls de 110 a 200; em ambos a **malha `strikes` da raiz permanece COMPLETA** (76 — o recorte é nos contratos, nunca no header). **Range invertido (`min > max`) → `200` com `calls: []`/`puts: []`** (silêncio, não erro) e malha raiz intacta. No modo `getAllData` **sem `date` específico**, recortam os contratos de TODOS os vencimentos; com `date` específico, apenas daquela expiração. **Não-numéricos (`abc`) → `400` 114 B** (`Parameter=strikeMin has an invalid type`, ou `strikeMax`). Parsing numérico: aceita `160`, `160.0`, `+160`, `" 160"`, `0160`, `1.5`, `1e2`, `1e3`, `1e4`; `NaN` = sem filtro; `Infinity` em `strikeMin` = 0 contratos, em `strikeMax` = cadeia inteira. |
| **Ignorados** | `strike` (solto) | num | Não | — | **IGNORADO pelo servidor** (verificado: `strike=160` e `strike=187.5` isolados devolvem a cadeia completa — 71 calls, 110→415; até `strike=160&getAllData=true` devolve a cadeia integral sem recorte). O `strike` é parâmetro da **URL da PÁGINA** — o aplicativo o converte em `strikeMin=strikeMax` antes de chamar a API. O filtro real no fio exige o par + `getAllData`. |
| **Faixa de strikes** | `strikeMin` + `strikeMax` + `getAllData` | num + bool | Não | — | **MODO STRIKE ÚNICO** (o clique num strike da página): `strikeMin=strikeMax=<k>` **com `getAllData=true` e SEM `date`** — o aplicativo DELETA o `date` nesse modo. Resposta: **UMA ENTRADA POR VENCIMENTO** em `options[]` (21 entradas no teste, uma por `expirationDates`), cada uma com os contratos disponíveis naquele vencimento (15 entradas com call+put e 1 só com put; 31 contratos no total, 5 vencimentos sem o strike), e o header `strikes` se **EXPANDE para a união de todas as expirações** (76 → 130 em AAPL, mesma sessão, minutos de distância). O servidor também aceita `date=-1` com o mesmo resultado; com `date=<epoch>`, restringe àquela expiração (1 entrada; 3.441 B; 0 contratos se o strike não existir nela). Com `straddle=true` → 21 entradas e 16 straddles (26.139 B). |
| **Volume de dados** | `getAllData` | bool | Não | `false` (ausente ≡ false) | `true` → **expande todas as expirações apenas quando `date` está ausente ou é `-1`**. Com `date=<epoch>` → **só aquela expiração** (todos os strikes dela; 45.314 B na 2ª expiração do AAPL); com `date=0`/`-2` → **uma entrada vazia** ecoando o valor (3.199/3.194 B); com `date=abc` → **`400`** (a validação de `date` ocorre antes). Com `strikeMin=Max` (o padrão do app) devolve o strike nas 21 cadeias; **com `date=-1`/ausente e sem o par de strikes** devolve a CADEIA INTEGRAL — 1.778.513 B (~1,78 MB), 21 vencimentos, 2.747 contratos, 130 strikes (verificado em 2026-11-06). Léxico: **`abc` → tratado como false**; `1` **não** ativa; `TRUE` ativa. |
| **Localização** | `lang` | string | Não | injetado pelo transporte (`en-US`) | Da sessão do usuário; o transporte oficial injeta sempre. NÃO localiza nada na cadeia e **NÃO ecoa no quote embutido**: PETR4.SA pedido com `lang=pt-BR&region=BR` devolve `quote.language: "en-US"`/`quote.region: "US"` (campos internos do pacote de quote) — os `fmt` dos contratos também não mudam. |
| **Localização** | `region` | string | Não | injetado pelo transporte (`US`) | Idem `lang` — sem efeito observável na cadeia (os contratos são do mercado do símbolo). |
| **Sessão / Auth** | `crumb` | string | **Sim** | — | O token casado com o Cookie `A3` (emitido pelo `getcrumb`). Qualquer ausência/divergência → **`401` "Invalid Crumb"** (89 B). Em GET, o vetor usual é a query; o header `x-crumb` também é aceito sozinho, mas **em divergência o valor da QUERY é o único que vale** — verificado: query válido + `x-crumb` garbage → `200`; query garbage + `x-crumb` válido → **`401`** (o header não serve de fallback quando a query está presente). **Duplicata: primeira ocorrência vence.** |
| **Ignorados** | `corsDomain` | string | Não | — | Domínio usado pelo app web em outros serviços para resolução de CORS (`finance.yahoo.com`) — aqui **aceito e ignorado** (no-op verificado: resposta idêntica com e sem). O transporte da cadeia não o injeta. |
| **Ignorados** | `symbols` | string | Não | — | **IGNORADO** — parâmetro de lote de outro endpoint de cotações; aqui a seleção é o path (verificado: enviado com `MSFT`, `underlyingSymbol` continua AAPL). |
| **Ignorados** | *desconhecidos* | qualquer | Não | — | Aceitos e ignorados silenciosamente — nenhum parâmetro desconhecido produziu erro nas sondagens (`fields`, `includePrePost`, `useYfid`, `interval`, `range`, `guccounter`, `foo`, `baz` testados). |

> **Convenções:**
> - A ordem dos parâmetros na query não importa **para parâmetros distintos**; em **duplicatas, a primeira ocorrência vence** (`date`, `formatted`, `straddle`, `crumb`). A ordem do aplicativo é `date` → `formatted` → `straddle` → `lang` → `region` → `crumb` (o transporte anexa os dois últimos DEPOIS dos params do chamador).
> - `date` e o grupo `strikeMin/Max+getAllData` são **excludentes no aplicativo** (o `date` é deletado no modo strike) — mas o servidor ACEITA os dois juntos. Com `date=-1`/ausente, `getAllData` expande todas as expirações; com `date=<epoch>`, devolve só aquela expiração; com `date=0`/`-2`, uma entrada vazia. `date=-1` + `strikeMin/Max` + `getAllData` → 21 entradas (25.416 B); `date=<epoch>` + o mesmo par → 1 entrada (3.441 B).
> - `straddle` coexiste com `date` (pares do vencimento pedido) **e com o modo strike** (16 straddles no strike 160); também funciona sozinho.
> - `-1` é um literal no fio (o servidor o interpreta; não é "parâmetro ausente" — e `date=0`/`-2` também não: são ecoados como pedidos).
> - Booleanos da query têm parsing **case-insensitive** (`TRUE`/`true`) e **sem coerção numérica** (`1` é false em TODOS: `formatted=1`, `straddle=1`, `getAllData=1` — cada um verificado).
> - Nenhum parâmetro provoca `500`: o pior caso real é o `400` de tipo de `date` (não-inteiro, 109 B) ou de `strikeMin`/`strikeMax` (não-numérico, 114 B).
> - Deduplique a query antes de enviar: concatenar parâmetros sem deduplicar é a causa mais comum de resultados inesperados.

### Matriz de conflito e precedência entre parâmetros

Cenários verificados nas baterias de 2026-11-05 e 2026-11-06:

| Cenário | `date` | `getAllData` | `strikeMin/Max` | `straddle` | Comportamento resultante |
| :--- | :---: | :---: | :---: | :---: | :--- |
| Cadeia canônica (padrão do app) | `-1` | — | — | `false` | **1 vencimento** (o mais próximo), `calls[]` + `puts[]` (98 KB) |
| Vencimento específico | `<epoch>` | — | — | `false` | **1 vencimento** correspondente ao timestamp (45 KB na 2ª expiração) |
| Straddle simples | `-1` | — | — | `true` | **1 vencimento**, contratos em `straddles[]` (76 pares; 102 KB) |
| Straddle + vencimento específico | `<epoch>` | — | — | `true` | **1 vencimento**, 40 straddles (47 KB na 2ª) |
| Strike único (multi-datas) | **ausente** | `true` | `min=max` | `false` | **todas as datas** de `expirationDates`, cada uma só o strike pedido (31 contratos); header `strikes` expande (130) |
| Strike único + `date=-1` | `-1` | `true` | `min=max` | `false` | **21 entradas**, mesmo resultado do modo sem `date` (25 KB) |
| Strike único + data específica | `<epoch>` | `true` | `min=max` | `false` | **1 entrada**; 0 contratos se o strike não existir naquela expiração (3,4 KB) |
| Strike + straddle | ausente | `true` | `min=max` | `true` | **21 entradas**, 16 straddles (26 KB) |
| Cadeia integral (dump total) | `-1`/ausente | `true` | — | `false` | **todos os vencimentos e todos os strikes** (~1,78 MB; 2.747 contratos) |
| `date` específico + `getAllData` | `<epoch>` | `true` | — | `false` | **1 vencimento**, todos os strikes dele (45 KB na 2ª) |
| `date` fora da lista + `getAllData` | `0`/`-2` | `true` | — | `false` | **1 entrada vazia**, valor ecoado (3,2 KB) |
| `date` inválido + `getAllData` | `abc` | `true` | — | `false` | **`400`** (validação de `date`; 109 B) |
| Filtro em vencimento único | `<epoch>` | — | `min/max` | `false` | apenas os contratos entre `min` e `max` **daquele vencimento** (9 calls de 300 a 320 no teste); `expirationDates` e malha raiz íntegras |
| Range invertido | qualquer | qualquer | `min > max` | qualquer | `200` silencioso: envelope, quote e `expirationDates` íntegros, `calls[]`/`puts[]` vazios |
| Parâmetros duplicados | qualquer | qualquer | qualquer | qualquer | **Primeira ocorrência vence** para `date`, `formatted`, `straddle` e `crumb` |

### Regras para implementadores de clientes

1. **Serialização booleana:** envie sempre literais `true`/`false` em minúsculas — o servidor NÃO faz coerção numérica (`formatted=1`, `straddle=1`, `getAllData=1` são todos `false`) e aceita caixa alta (`TRUE` ativa).
2. **Precedência de erro 400:** `date` não-inteiro (`abc`, `1.5`) → `400`/109 B; `strikeMin`/`strikeMax` não-numéricos → `400`/114 B (`Parameter=strikeMin has an invalid type`, ou `strikeMax`). `formatted`, `straddle` e `getAllData` com valores inválidos degradam para `false` em `200 OK` com dados vazios ou default.
3. **Consumo de banda:** para pipelines automatizados, **omita `formatted`** (ou envie `false`) — corta ~50% do tráfego e do parsing (98 KB → 49 KB na cadeia canônica) sem perder nenhum campo.
4. **Crumb: query é o único vetor confiável em divergência.** O header `x-crumb` sozinho É aceito (verificado: `200`), mas quando a query está presente ela é a única que vale — query garbage + header válido → `401`. Recomendação prática: sempre `?crumb=` na URL, como os clientes oficiais fazem em GET.
5. **Deduplique a query:** a primeira ocorrência vence; não concatene parâmetros sem remover duplicatas.
6. **Não envie `strike` solto:** ele é ignorado; use `strikeMin`/`strikeMax` (e `getAllData=true` para todos os vencimentos).
7. **`lang`/`region`:** mantenha `en-US`/`US` por compatibilidade; não há efeito observável no conteúdo.
8. **Fallback de host:** `query2` é espelho de `query1` (mesmo conteúdo, mesmo `200`); use como fallback.

### Receitas de consulta (spider)

| Objetivo | Query | Payload medido |
|---|---|---|
| Cadeia do vencimento mais próximo | `?date=-1&formatted=false&lang=en-US&region=US&crumb=<CRUMB>` | ~49 KB (`formatted=false`) |
| Expiração específica | `?date=<epoch>&formatted=true&lang=en-US&region=US&crumb=<CRUMB>` | 45.314 B na 2ª expiração (`formatted=true`) |
| Cadeia integral | `?getAllData=true&date=-1&formatted=true&lang=en-US&region=US&crumb=<CRUMB>` | 1.778.513 B (`formatted=true`) |
| Strike único em todos os vencimentos | `?strikeMin=<k>&strikeMax=<k>&getAllData=true&formatted=true&lang=en-US&region=US&crumb=<CRUMB>` (sem `date`) | 25.416 B (`formatted=true`) |
| Straddles | `?straddle=true&...` (com `date` ou com o modo strike) | 47.330 B (2ª) / 102.074 B (76 pares) |

Para pipelines, troque `formatted=true` por `false` e espere ~50% do payload; os valores acima são os medidos com `formatted=true`, exceto a primeira linha, que já usa `formatted=false`.

## Estrutura do endpoint — parâmetros, cadeia e contratos

Estrutura declarativa pura (JSON5 comentado), sem nenhuma função ou lógica executável de JavaScript: parâmetros, o envelope `optionChain` (de topo próprio — a camada `finance` só aparece nos ERROS e no `400` de validação), o contrato de opção e os dois modos alternativos de leitura.

```json5
{
  // ==========================================================================
  // 1 · PARÂMETROS DA REQUISIÇÃO (resumo — semântica completa na tabela acima)
  // ==========================================================================
  request: {
    method: "GET",
    path: "/v7/finance/options/{symbol}",   // symbol URL-encoded no path; SEM lote
    params: {
      date: -1,                        // epoch em SEGUNDOS inteiro ou -1 literal (= primeira futura)
                                       //   não-inteiro (abc, 1.5) → 400 "Parameter=date has an
                                       //   invalid type" (109 B) · inteiros fora da lista (0, -2, …)
                                       //   → 200 com o valor ECOADO e arrays vazios (0 não é "ausente")
                                       //   · com getAllData, date específico limita a 1 expiração
      formatted: "true",               // o app envia sempre; false ou AUSENTE → números crus;
                                       //   parsing case-insensitive (TRUE ativa); 1 NÃO ativa
      straddle: false,                 // true → straddles[{strike, call, put}] (sem calls/puts);
                                       //   pernas OPCIONAIS; case-insensitive (TRUE ativa); 1 NÃO ativa;
                                       //   funciona com date e com o modo strike
      strikeMin: 160,                  // MODO STRIKE ÚNICO (com strikeMax + getAllData, SEM date):
      strikeMax: 160,                  //   1 entrada de options[] POR VENCIMENTO e header strikes
      getAllData: true,                //   expandido (união de todas as expirações). Isolados também
                                       //   funcionam (recorte inclusivo nos contratos, malha raiz
                                       //   intacta; range invertido → arrays vazios).
                                       //   · getAllData + date ausente/-1 → CADEIA INTEGRAL
                                       //   · getAllData + date específico → SÓ aquela expiração
                                       //   · getAllData + date=0/-2 → 1 entrada vazia (valor ecoado)
                                       //   · getAllData=abc → false · não-numérico em strikeMin/Max → 400
      lang: "en-US",                   // da sessão (transporte); não ecoa no quote embutido
      region: "US",                    // idem
      crumb: "<token>",                // OBRIGATÓRIO — casado com o Cookie A3; em divergência com
                                       //   o header x-crumb, o valor da QUERY é o único que vale;
                                       //   duplicata: primeira ocorrência vence
      // tolerados e ignorados: strike solto, symbols=…, corsDomain, e qualquer desconhecido
    },
  },

  // ==========================================================================
  // 2 · ENVELOPE — optionChain (topo próprio; finance só nos ERROS e no 400)
  // ==========================================================================
  responseEnvelope: {
    "optionChain": {
      "result": [{                     // 1 elemento com cadeia; result: [] para símbolo inexistente
                                       //   (200, 42 B — NÃO é erro; o consumidor degrada)
        "underlyingSymbol": "AAPL",    // Eco do symbol do path
        "expirationDates": [1793923200, …, 1863475200],
                                       // TODAS as expirações com contratos listados — epoch em
                                       //   segundos, ordenado. AAPL: 21 datas (2026-11-06; da
                                       //   semanal 2026-11-06 até LEAPS 2029-01-19) · 22 na captura
                                       //   de out/2026 · alimenta o seletor de expiração da página ·
                                       //   VAZIO em símbolos sem cadeia e em deslistados
        "strikes": [110.0, …, 415.0],  // No modo date/-1: os strikes da cadeia do símbolo (AAPL:
                                       //   76 valores em 2026-11-06 · 69 na captura de out/2026 ·
                                       //   NVDA: 79; passos modais 5/15, decimais de leilão
                                       //   297.5/302.5 existem). No modo strike+getAllData: EXPANDE
                                       //   para a união de TODAS as expirações (130 no teste vs 76)
        "hasMiniOptions": false,       // Mini-contratos — false em TODOS os testes (ações, B3 e
                                       //   índice); nunca true observado
        "quote": { … },                // O PACOTE DE COTAÇÃO CONSOLIDADA DO SUBJACENTE EMBUTIDO —
                                       //   83–90 campos (90 no AAPL de 2026-11-06; POSTPOST traz
                                       //   postMarket*/fullday*; REGULAR não) — regularMarketPrice,
                                       //   marketState, faixa de 52 semanas, múltiplos, dividendos,
                                       //   volume — com as classes de borda: deslistado → quoteType
                                       //   NONE (esqueleto sem shortName); índice → INDEX; e os
                                       //   quirks preservados (prevName + nameChangeDate de mudança
                                       //   de nome recente). language/region do pacote NÃO ecoam
                                       //   lang/region pedidos. NOTA: o header da página NÃO lê
                                       //   daqui — o quote vem do pipeline comum; o payload carrega
                                       //   o quote por redundância
        "options": [                   // UMA entrada por expiração PEDIDA — ou UMA POR VENCIMENTO
                                       //   quando getAllData=true e o date está ausente/-1; com
                                       //   date específico + getAllData, apenas UMA entrada
          {
            "expirationDate": 1793923200,  // A expiração desta entrada (espelha o date pedido; nos
                                           //   símbolos sem cadeia/date sem contratos, espelha o
                                           //   pedido com arrays vazios; deslistado → {} VAZIO)
            "hasMiniOptions": false,
            "calls": [ /* contratos — bloco 3 */ ],   // AAPL 2026-11-06: 71 · captura out/2026: 65
            "puts":  [ /* contratos — bloco 3 */ ],   // AAPL 2026-11-06: 75 · captura out/2026: 59
            // "straddles": [ … ]        // SÓ com straddle=true (bloco 4) — aí calls/puts DESAPARECEM
          }
        ],
      },
      "error": null,                   // Vetor de erro do envelope próprio — null em todos os casos
                                       //   observados (os erros reais usam a camada finance — bloco 5)
    }
  },

  // ==========================================================================
  // 3 · CONTRATO DE OPÇÃO (calls[i] / puts[i]) — valores {raw, fmt, longFmt}
  // ==========================================================================
  contract: {
    // ORDEM DE CHEGADA no wire NÃO é contratual ENTRE SÍMBOLOS: a captura AAPL (10-02) ordena
    // percentChange, openInterest, strike, change, inTheMoney, impliedVolatility, volume,
    // contractSymbol, ask, lastTradeDate, expiration, currency, contractSize, bid, lastPrice —
    // a NVDA (09-25) troca ask↔contractSymbol e currency↔expiration. Consumidor que depende de
    // ordem deve ordenar; o aplicativo lê por NOME. calls[] e puts[] vêm ORDENADOS por strike
    // ascendente (verificado nas capturas). O exemplo abaixo está reordenado para leitura.
    "contractSymbol": "AAPL261002C00160000",
                                       // Identificador OCC: SYMBOL + YYMMDD + C/P + strike×1000 em
                                       //   8 dígitos (160.00 → 00160000). string única sem empacotar
    "strike": { "raw": 160.0, "fmt": "160.00" },
    "lastPrice": { "raw": 169.22, "fmt": "169.22" },
    "bid": { "raw": 168.75, "fmt": "168.75" },
    "ask": { "raw": 172.05, "fmt": "172.05" },
    "change": { "raw": -9.330002, "fmt": "-9.33" },
    "percentChange": { "raw": -5.225428, "fmt": "-5.23%" },
    "volume": { "raw": 4, "fmt": "4", "longFmt": "4" },
                                       // longFmt = separador de milhar ("24,645"); volume é OMITIDO
                                       //   quando não há negociação no dia — lastTradeDate pode
                                       //   permanecer de um trade anterior (puts de fundo de gama)
    "openInterest": { "raw": 1, "fmt": "1", "longFmt": "1" },
    "impliedVolatility": { "raw": 5.23437845703125, "fmt": "523.44%" },
                                       // DECIMAL ANUALIZADO — 1.0 = 100%: o fmt multiplica ×100 e
                                       //   anexa % (4.0938 → "409.38%"). Fundos de gama chegam a
                                       //   raw 6.12 (612.50%)
    "inTheMoney": true,                // Booleano CRUDO (não empacotado) — strike×(C:price>K | P:price<K)
    "lastTradeDate": { "raw": 1790879111, "fmt": "2026-10-01", "longFmt": "2026-10-01T18:25" },
                                       // Epoch em SEGUNDOS; fmt = data do trade; longFmt = data+hora
                                       //   (minuto) — o campo com TRÊS formas
    "expiration": { "raw": 1790899200, "fmt": "2026-10-02", "longFmt": "2026-10-02T00:00" },
                                       // Espelho do expirationDate da entrada, por contrato — o raw
                                       //   é 00:00Z do vencimento (na captura AAPL de out/2026 o
                                       //   postMarketTime do quote ficou 3 s antes desse marco)
    "currency": "USD",                 // string cruda
    "contractSize": "REGULAR",         // Enum (o outro valor do vocabulário OCC, "INDEX", não foi
                                       //   observado — nenhum índice expõe cadeia por aqui)
    // — campo OMITIDO sem negociação no dia: volume (lastTradeDate pode permanecer)
  },

  // ==========================================================================
  // 4 · MODOS DE LEITURA (baterias 2026-11-05/06)
  // ==========================================================================
  // 4a · STRIKE ÚNICO (sem date; getAllData=true):
  //   GET …/options/AAPL?formatted=true&straddle=false&strikeMin=160&strikeMax=160&getAllData=true&…
  //   → 200 com UMA ENTRADA DE options[] POR VENCIMENTO (21 no teste; expDates das entradas =
  //   expirationDates inteira), cada entrada com os contratos disponíveis (15 com call+put e 1
  //   só com put; 31 contratos no total; 5 vencimentos não listam 160) e o header strikes
  //   EXPANDIDO (130 = união de todas as expirações). É a resposta do CLIQUE num strike da página.
  //   Com date=-1, mesmo resultado; com date=<epoch>, apenas aquela expiração (1 entrada;
  //   3.441 B; 0 contratos se o strike não existir nela).
  // 4b · STRADDLE (straddle=true, com ou sem date):
  //   cada entrada de options[] TROCA calls/puts por:
  //   "straddles": [ { "strike": {"raw":110,"fmt":"110.00"},
  //                    "call": {…contrato…}, "put": {…contrato…} } ]
  //   76 pares no teste (1 por strike) — o STRIKE vem FORA das pernas, embutido no par (diferente
  //   de um zip ingênuo de calls[i]+puts[i]); as pernas são OPCIONAIS (contagem varia por sessão;
  //   5 sem call e 1 sem put na captura de 2026-11-05). Com date=<2ª>, 40 straddles; com o modo
  //   strike (strikeMin=Max+getAllData), 16 straddles (21 entradas; 26.139 B).

  // ==========================================================================
  // 5 · ERROS (baterias 2026-11-05/06: anônima + autenticada)
  // ==========================================================================
  errors: {
    "401": {                           // sem crumb / crumb errado / sem cookie — TODAS as combinações
      body: { "finance": { "result": null, "error": { "code": "Unauthorized", "description": "Invalid Crumb" } } },
      bytes: 89,                       // content-length constante nas sondagens
      headers: "content-type: application/json;charset=utf-8 · Cache-Control: max-age=0, private · Expires: -1 · Age: 0 · y-rid por request · server: ATS · vary: Origin",
      "HEAD": "mesmo 401 com content-length 89 (o crumb é exigido até em HEAD)",
    },
    "400": {                           // duas variantes de validação de tipo:
      "date": {
        body: { "finance": { "result": null, "error": { "code": "Bad Request", "description": "Parameter=date has an invalid type" } } },
        bytes: 109,                    // gatilho: date não-inteiro (abc, 1.5)
      },
      "strikeMin/strikeMax": {
        body: { "finance": { "result": null, "error": { "code": "Bad Request", "description": "Parameter=strikeMin has an invalid type" } } },
        bytes: 114,                    // gatilho: strikeMin/strikeMax não-numérico (abc)
      },
    },
    "429": "User-Agent de não-navegador → '429 Edge: Too Many Requests' (bloqueio por assinatura de agente, não por volume)",
    "404-texto": "/options/AAPL/ (barra final) → 'Not Found' em TEXTO PURO, sem envelope JSON",
    "404-envelope": "/options/ (sem symbol) → 404 COM envelope finance {code:'Not Found', description:'HTTP 404 Not Found…'} — duas rejeições distintas do mesmo status no mesmo caminho",
    "405": "POST → 405 (método não permitido)",
    "200-degradado": {                 // os outros "erros" devolvem 200 com degradação NO ENVELOPE:
      "symbol-inexistente": "ZZZZZZ → 200 em 42 B: {\"optionChain\":{\"result\":[],\"error\":null}} — result VAZIO, não é erro",
      "deslistado": "TWTR → 200: result[0] com underlyingSymbol TWTR, expirationDates [], strikes [], options[0] = {} (objeto VAZIO, nem expirationDate) e quote de classe **NONE** (o esqueleto de símbolos deslistados)",
      "sem-cadeia": "PETR4.SA (B3) e ^GSPC (índice) → 200 com expirationDates [], strikes [], options[0] {} e o quote do subjacente (83–90 campos em ações; 61 no ^GSPC; quoteType EQUITY/INDEX) — o quote embutido é o único conteúdo útil",
      "date-sem-contratos": "date futuro distante ou passado → 200 com expirationDates e quote INTACTOS, mas strikes: [] e options[0] = {expirationDate:<o pedido>, calls:[], puts:[]}",
    },
  },
}
```

## Como o aplicativo oficial usa o endpoint

### Montagem da query (fonte estática)

No loader da página `/quote/[symbol]/options` a query é montada assim:

```js
const o = { date: e, formatted: "true", straddle: a };
i && (delete o.date, o.strikeMin = i, o.strikeMax = i, o.getAllData = true);
// ...
bl(n, { crumb: true, pathname: `/v7/finance/options/${s}`, query: o })
```

A camada de transporte compartilhada acrescenta:

```js
f.searchParams.set("lang", a.lang || "en-US");
f.searchParams.set("region", a.region || "US");
if (l.crumb && u) f.searchParams.set("crumb", u);
```

A URL da **página** também aceita `date`, `strike` e `straddle` — não são os parâmetros da API:

```js
const { date = -1, strike, straddle } = Object.fromEntries(url.searchParams.entries());
const dateInt = typeof date === "string" ? parseInt(date) : date;
loadOptions(n, { date: dateInt, isStraddle: straddle && straddle === "true", strike, symbol });
```

Ou seja: o `strike` da página é convertido em `strikeMin`/`strikeMax`; o `straddle` da página só ativa com a string exata `"true"` (diferente da API, que aceita `TRUE`).

### Comportamento

- **Uma chamada por interação**: a página pede a cadeia no carregamento (com `date=-1` quando o usuário não escolheu nada) e refaz a chamada a cada troca de vencimento, de strike ou de tab — **sem poller** (nenhuma sondagem periódica).
- **Seletor de expiração**: alimentado direto por `expirationDates`; trocar a data reescreve `date=<epoch>` na URL da página e **reseta** o strike escolhido.
- **Seletor de strike**: os valores vêm de `strikes` com uma sentinela local para "todos os strikes" — a sentinela não vai ao fio; escolher um strike específico entra no modo `strikeMin/Max + getAllData` (e o `date` sai da query).
- **Tabs CALLS/PUTS/STRADDLE**: o tab de straddle escreve `straddle=true` na URL da página; as tabelas leem os campos por NOME (a ordem do fio varia) com defaults locais quando o campo não veio.
- **Cache de cliente**: a última resposta fica em store por `symbol + date`; o modo strike nunca reaproveita cache (sempre refetch). O header da página (nome/preço do subjacente) vem do pipeline comum de quote — **não** do quote embutido neste payload.
- **Transporte**: `credentials: include` (cookie da sessão), timeout do config de serviços (15 s de fallback), crumb anexado automaticamente; headers de controle de cache nunca são enviados pelo cliente.

## Validação ao vivo (2026-11-06)

### Metodologia

- **Sessão:** `GET https://fc.yahoo.com/` → `404`, `Set-Cookie: A3=...`; depois `GET /v1/test/getcrumb` com UA de navegador e `Referer: https://finance.yahoo.com/` → `200`, crumb de 11 caracteres.
- **UA:** Chrome 131 no Windows; UA `curl/8.0.1` foi testado e recebeu `429`.
- **Hosts:** `query1` (principal) e `query2` (espelho).
- **Espaçamento:** 1,2 s entre chamadas; nenhuma chamada em paralelo.
- **Total:** 97 chamadas ao endpoint + 8 de bootstrap; nenhum `5xx` observado.
- **Comparação:** cada variante foi comparada com a canônica por status, bytes, número de expirações, strikes, opções, contratos, tipo de `strike` e idioma/região do quote.

> **Contexto das medições:** salvo indicação em contrário, cada linha usa a query canônica (`date=-1`, `formatted=true`, `straddle=false`, `lang=en-US`, `region=US`, `crumb` válido). As linhas “ausente (query mínima)” das tabelas de `date` e `formatted` vêm da query mínima (só `crumb`); diferenças de poucos bytes entre casos equivalentes são ruído intradiário.

### `date` — expiração

| Valor testado | Status | Bytes | Resultado |
|---|---:|---:|---|
| ausente (query mínima) | 200 | 48.909 | primeira expiração futura (`1793923200`), 71 calls / 75 puts |
| `-1` | 200 | 98.092 | idem (canônica do app) |
| `1793923200` (1ª expiração) | 200 | 98.086 | 71 calls / 75 puts |
| `1794182400` (2ª expiração) | 200 | 45.314 | 40 strikes (275–400), 35 calls / 30 puts |
| `0` | 200 | 3.195 | `strikes: []`, 1 entrada `options[0]` com `expirationDate: 0`, calls/puts vazios |
| `-2` | 200 | 3.196 | idem, ecoando `-2` |
| `9999999999` | 200 | 3.202 | idem, ecoando `9999999999` |
| `abc` | 400 | 109 | `Parameter=date has an invalid type` |
| `1.5` | 400 | 109 | idem |

### `formatted` — empacotamento dos números

| Valor | Status | Bytes | `strike` no 1º contrato |
|---|---:|---:|---|
| ausente (query mínima) | 200 | 48.909 | `float` (cru) |
| `false` | 200 | 48.911 | `float` |
| `true` | 200 | 98.092 | `dict` `{raw, fmt, longFmt}` |
| `TRUE` | 200 | 98.092 | `dict` |
| `1` | 200 | 48.910 | `float` (NÃO ativa) |
| `0` | 200 | 48.910 | `float` |
| `abc` | 200 | 48.911 | `float` |

### `straddle` — modo straddle

| Valor | Status | Bytes | Resultado |
|---|---:|---:|---|
| ausente | 200 | 98.092 | `calls[]` + `puts[]` |
| `false` | 200 | 98.092 | `calls[]` + `puts[]` |
| `true` | 200 | 102.074 | `straddles[]` com 76 pares; `calls`/`puts` ausentes |
| `TRUE` | 200 | 102.074 | idem |
| `1` | 200 | 98.092 | NÃO ativa; calls/puts |
| `0` | 200 | 98.092 | calls/puts |
| `abc` | 200 | 98.095 | calls/puts |

### `strikeMin` / `strikeMax` — faixa de strikes

Limites **inclusivos**, aplicados aos contratos da expiração selecionada; o header `strikes` da raiz **não é recortado** quando os parâmetros são usados isoladamente.

| Caso | Status | Bytes | Calls / Puts | Faixa dos calls | `strikes` da raiz |
|---|---:|---:|---|---|---|
| `strikeMin=160` | 200 | 90.421 | 66 / 68 | 160–415 | 76 (110–415) |
| `strikeMax=160` | 200 | 12.619 | 6 / 8 | 110–160 | 76 |
| `strikeMin=160&strikeMax=160` (sem `getAllData`) | 200 | 4.952 | 1 / 1 | 160–160 | 76 |
| `strikeMin=300&strikeMax=200` (invertido) | 200 | 3.657 | 0 / 0 | — | 76 |
| `strikeMin=-10&strikeMax=160` | 200 | 12.619 | 6 / 8 | 110–160 | 76 |
| `strikeMin=160.5&strikeMax=160.5` | 200 | 3.655 | 0 / 0 | — | 76 |
| `strikeMin=160&strikeMax=160&getAllData=true` | 200 | 25.416 | 15 / 16 | 160–160 | **130 (5–670)** |
| `date=-1` + `strikeMin=160&strikeMax=160&getAllData=true` | 200 | 25.416 | 15 / 16 | 160–160 | **130** |
| `strike=160` (solto) | 200 | 98.090 | 71 / 75 | 110–415 | 76 (IGNORADO) |

**Parsing numérico (verificado):**

| Valor | Status | Efeito |
|---|---:|---|
| `160`, `160.0`, `+160`, `" 160"`, `0160` | 200 | mesmo filtro (`>=160` / `<=160`) |
| `1.5` | 200 | aceito como 1.5; `strikeMin=1.5` mantém a cadeia inteira |
| `1e2` | 200 | aceito como 100; mantém a cadeia |
| `1e3` / `1e4` | 200 | aceito como 1000/10000; `strikeMin` acima da malha → 0 contratos |
| `NaN` | 200 | tratado como ausência de filtro (cadeia inteira) |
| `Infinity` em `strikeMin` | 200 | 0 contratos |
| `Infinity` em `strikeMax` | 200 | cadeia inteira |
| `abc` | **400** | `Parameter=strikeMin has an invalid type` (ou `strikeMax`; 114 B) |

### `getAllData` — volume de expirações

| Caso | Status | Bytes | `options[]` | Contratos |
|---|---:|---:|---:|---:|
| `getAllData=true` + `date=-1` | 200 | 1.778.513 | 21 | 1.433 calls + 1.314 puts = 2.747 |
| `getAllData=true` sem `date` | 200 | 1.778.478 | 21 | 2.747 |
| `getAllData=true` + `date=1794182400` (2ª exp.) | 200 | 45.314 | **1** | 35 calls + 30 puts |
| `getAllData=true` + `date=0` | 200 | 3.199 | **1** | 0 / 0, `expirationDate: 0` |
| `getAllData=true` + `date=-2` | 200 | 3.194 | **1** | 0 / 0, `expirationDate: -2` |
| `getAllData=true` + `date=abc` | **400** | 109 | — | validação de `date` ocorre antes |
| `getAllData=false` / ausente + `date=-1` | 200 | 98.092 | 1 | 71 / 75 |
| `getAllData=1` + strike pair | 200 | 4.950 | 1 | 1 / 1 (NÃO ativa) |
| `getAllData=TRUE` + strike pair | 200 | 25.414 | 21 | 15 / 16 (ativa) |
| `getAllData=abc` + strike pair | 200 | 4.950 | 1 | 1 / 1 (false) |

**Regra:** `getAllData=true` expande todas as expirações **apenas quando `date` está ausente ou é `-1`**. Com `date=<epoch válido>`, devolve **somente aquela expiração** (todos os strikes dela). Com `date=0`/`-2`, devolve **uma entrada vazia** ecoando o valor. No modo strike (sem `date`), devolve uma entrada por vencimento. Sem coerção numérica: `1` é `false`; `TRUE` ativa.

### `lang` / `region` — localização

| Caso | Status | Bytes | `quote.language` | `quote.region` |
|---|---:|---:|---|---|
| `lang=en-US&region=US` | 200 | 98.092 | `en-US` | `US` |
| `lang=pt-BR&region=BR` | 200 | 98.079 | `en-US` | `US` |
| `lang=xx&region=YY` | 200 | 98.079 | `en-US` | `US` |

**Regra:** aceitos, mas **sem efeito observável** na cadeia e no quote embutido; os `fmt` dos contratos também não mudam. O transporte do app injeta `en-US`/`US`.

### `crumb` — autenticação

| Caso | Status | Bytes | Resultado |
|---|---:|---:|---|
| query válida + cookie A3 | 200 | 98.085 | sucesso |
| header `x-crumb` válido, sem query | 200 | 98.085 | sucesso |
| query válida + header garbage | 200 | 98.085 | query vence |
| query garbage + header válido | **401** | 89 | `Invalid Crumb` |
| sem crumb | **401** | 89 | `Invalid Crumb` |
| crumb errado | **401** | 89 | `Invalid Crumb` |
| crumb válido **sem cookie A3** | **401** | 89 | `Invalid Crumb` |
| query válida seguida de garbage | 200 | 98.091 | primeira ocorrência vence |
| query garbage seguida de válida | **401** | 89 | primeira ocorrência vence |

### Booleanos: resumo

| Valor | `formatted` | `straddle` | `getAllData` |
|---|---|---|---|
| ausente | false | false | false |
| `true` | **true** | **true** | **true** |
| `TRUE` | **true** | **true** | **true** |
| `false` | false | false | false |
| `1` | false | false | false |
| `0` | false | false | false |
| `abc` | false | false | false |

**Regra:** envie sempre `true`/`false` em minúsculas. `1` **não** é `true`.

### Duplicatas: primeira ocorrência vence

| Query | Resultado observado |
|---|---|
| `date=1794182400&date=-1` | `options[0].expirationDate = 1794182400` (primeira) |
| `date=-1&date=1794182400` | `options[0].expirationDate = 1793923200` (primeira, `-1`) |
| `formatted=true&formatted=false` | números empacotados (primeira) |
| `formatted=false&formatted=true` | números crus (primeira) |
| `straddle=true&straddle=false` | `straddles[]` (primeira) |
| `straddle=false&straddle=true` | `calls[]`/`puts[]` (primeira) |
| `crumb=<válido>&crumb=GARBAGE` | 200 (primeira) |
| `crumb=GARBAGE&crumb=<válido>` | 401 (primeira) |

Isso é relevante para clientes que concatenam parâmetros sem deduplicar.

### Status, métodos e caminho

| Caso | Status | Bytes | Corpo/tipo |
|---|---:|---:|---|
| `GET` com crumb | 200 | 98.092 | JSON (`application/json;charset=utf-8`) |
| `HEAD` com crumb | 200 | 0 | `content-length: 0`, `private, no-cache, no-store` |
| `HEAD` sem crumb | 401 | 0 | `content-length: 89` |
| `OPTIONS` com crumb | 200 | 1.753 | WADL XML (`application/vnd.sun.wadl+xml`), `Allow: HEAD,GET,OPTIONS` |
| `POST` com crumb | 405 | 109 | `Method Not Allowed` |
| `/options/AAPL/` (barra final) | 404 | 11 | texto puro `Not Found` |
| `/options/` (sem symbol) | 404 | 91 | envelope `finance.error` |
| `GET` com UA `curl/8.0.1` | 429 | 23 | `Edge: Too Many Requests` |
| `query2` | 200 | 98.091 | espelho do `query1` |
| symbol minúsculo (`aapl`) | 200 | 98.091 | normaliza para `AAPL` |
| `^GSPC` (`%5EGSPC`) | 200 | 1.885 | sem cadeia; quote do índice |
| `AAPL,MSFT` no path | 200 | 42 | `result: []` |
| símbolo inexistente (`ZZZZZZ`; bateria 2026-11-05) | 200 | 42 | `result: []` |

> `ZZZZZZ` foi verificado na bateria de 2026-11-05; as demais linhas desta tabela foram revalidadas em 2026-11-06.

**Cache de borda:** `GET 200` → `public, max-age=1, stale-while-revalidate=9`; `401` → `max-age=0, private`; `HEAD` → `private, no-cache, no-store`.

### Payload e contagens (AAPL, 2026-11-06)

| Modo | Bytes | Expirações | `options[]` | Calls | Puts | Straddles | `strikes` |
|---|---:|---:|---:|---:|---:|---:|---:|
| canônico `date=-1&formatted=true` | 98.092 | 21 | 1 | 71 | 75 | 0 | 76 (110–415) |
| mínimo (só `crumb`) | 48.909 | 21 | 1 | 71 | 75 | 0 | 76 |
| `formatted=false` | 48.911 | 21 | 1 | 71 | 75 | 0 | 76 |
| `straddle=true` | 102.074 | 21 | 1 | 0 | 0 | 76 | 76 |
| `date=<2ª>&straddle=true` | 47.330 | 21 | 1 | 0 | 0 | 40 | 40 (275–400) |
| strike `160` + `getAllData` | 25.416 | 21 | 21 | 15 | 16 | 0 | 130 (5–670) |
| strike `160` + `straddle` + `getAllData` | 26.139 | 21 | 21 | 0 | 0 | 16 | 130 |
| `getAllData=true` + `date=-1` | 1.778.513 | 21 | 21 | 1.433 | 1.314 | 0 | 130 |

Contrato (15 campos): `contractSymbol`, `strike`, `currency`, `lastPrice`, `change`, `percentChange`, `volume`, `openInterest`, `bid`, `ask`, `contractSize`, `expiration`, `lastTradeDate`, `impliedVolatility`, `inTheMoney`. A ordem no wire varia entre símbolos; leia por nome. `volume` é **omitido** quando não há negociação no dia; `lastTradeDate` pode permanecer de um trade anterior.

### Limitações

- Testes com **AAPL** e alguns símbolos de borda (`^GSPC`, `AAPL,MSFT`; `ZZZZZZ` na bateria de 2026-11-05); não foi feita uma varredura exaustiva de todos os tickers.
- Números de bytes/contratos são **ponto no tempo** (mercado intraday; o cache de borda é de ~1 s).
- Não foi feito fuzzing exaustivo de **nomes** desconhecidos; foram testados representantes (`fields`, `includePrePost`, `useYfid`, `interval`, `range`, `guccounter`, `foo`, `baz`) e todos foram ignorados.
- Não foi testado `straddle=true` + `getAllData=true` **sem** filtro de strike (resposta potencialmente grande); o modo strike com straddle foi validado.
- Nenhum `5xx` foi observado; o pior caso é `400` de validação de tipo (`date` 109 B ou `strikeMin`/`strikeMax` 114 B).

### Anexo — evidências

- `probe_stage1.json` — 42 casos: canônica, `date`, `formatted`, `straddle`, `strikeMin/Max`, `getAllData`, `lang/region`, ignorados, duplicatas.
- `probe_stage2.json` — 27 casos: duplicatas com datas distintas, `strikeMin/Max` não-numéricos, combinações de strike+straddle, `crumb` query/header, métodos, path, `query2`, UA.
- `probe_stage3.json` — 16 casos: `date` específico, `Infinity`/`NaN`, `crumb` duplicado, straddle+strike, `getAllData` com `date=0`, crumb sem cookie.
- `probe_stage4.json` — 12 casos: `getAllData` com data específica/ausente/`0`/`-2`, parsing numérico (`1e2`, `1e4`, `+160`, espaço, `0160`, `NaN`, `Infinity`).

Nenhum cookie, crumb ou token é reproduzido neste documento; os valores aparecem como `<CRUMB>`. Os artefatos brutos em `%TEMP%` contêm o crumb efêmero da sessão de teste (não versionar).

## Limites e políticas de uso

| Aspecto | Comportamento |
| :--- | :--- |
| Autenticação | Obrigatória em 2 passos (Cookie `A3` via `fc.yahoo.com` + crumb via `getcrumb`, casados); qualquer combinação sem crumb válido → `401` com envelope `finance.error` de **89 B constantes** (`Invalid Crumb`) — revalidado em 2026-11-06. O `HEAD` também exige crumb. |
| User-Agent | Obrigatório agente de navegador: `curl` default e `Python-urllib` recebem `429 Edge: Too Many Requests` — bloqueio por assinatura de agente, não por volume. O `getcrumb` do pipeline pede UA + `Referer`. |
| Caminho | `/options/AAPL/` (barra final) → `404` **texto puro**; `/options/` (sem symbol) → `404` **com envelope finance**; `POST` → `405`. O symbol é SEMPRE o do path — `symbols=` é ignorado. |
| Seleção | Duas camadas: `{symbol}` no path (case-insensitive) + `date` (epoch s; `-1` literal do app = primeira expiração futura); o modo strike troca `date` por `strikeMin=strikeMax` + `getAllData` (uma entrada POR vencimento + header `strikes` expandido); `getAllData` sem date específico e sem o par de strikes devolve a cadeia INTEGRAL (~1,78 MB); com `date` específico, só aquela expiração; `straddle=true` troca `calls/puts` por pares `{strike, call, put}` com pernas opcionais. `date` não-inteiro (109 B) e `strikeMin/Max` não-numéricos (114 B) são os únicos `400` de validação da família. |
| Degradação graciosa | Símbolo inexistente → `200` com `result: []` (42 B); deslistado (TWTR) → classe `NONE` + `options[0] = {}`; símbolo sem cadeia pública (PETR4.SA/B3, `^GSPC`) → arrays vazios + quote completo do subjacente; `date` sem contratos → entrada vazia espelhando o pedido — **nunca 5xx observado**. |
| Payload | 98.092 B na cadeia canônica AAPL (2026-11-06; ~98 KB) · 48.909 B na mínima · 45.314 B na 2ª expiração · 25.416 B no strike único · 102.074 B em straddle · 1.778.513 B (~1,78 MB) na cadeia integral. Valores empacotados `{raw, fmt, longFmt}` com `formatted=true` (o app envia sempre); `formatted=false`/ausente → números crus. IV em decimal anualizado (1.0 = 100%); `longFmt` de milhar em `volume`/`openInterest`; **`volume` omitido** quando não há negociação no dia. |
| Ordem no wire | A ordem dos campos do contrato **varia entre símbolos** (AAPL 10-02 ≠ NVDA 09-25 em 2 trocas de posição) — trate como não contratual; o aplicativo lê por nome. `calls[]`/`puts[]` vêm ordenados por strike ascendente. |
| Cache de borda | GET `200` → **`public, max-age=1, stale-while-revalidate=9`** (janela de ~10 s por URL; `Age: 0` observado em rajadas); `HEAD` → `private, no-cache, no-store`; `401` → `max-age=0, private` + `Expires: -1`. |
| Cliente oficial | Uma chamada por interação (troca de expiração/strike/tab); cache de store por `symbol+date` no cliente (o modo strike sempre refetch); sem poller. |
| Não observado | `hasMiniOptions: true` e `contractSize: "INDEX"` (nenhum índice expõe cadeia por este endpoint — `^GSPC` devolve arrays vazios); erro real de símbolo inexistente (a degradação em `200` cobre o caso); `straddle=true` + `getAllData=true` sem filtro de strike. |

## Mudanças nesta revisão (2026-11-06)

| Item | Versão anterior (2026-11-05) | Versão atual (2026-11-06) |
|---|---|---|
| `400` | “o único `400` é `date` não-inteiro” | **Também** `strikeMin`/`strikeMax` não-numéricos → `400` 114 B (`Parameter=strikeMin has an invalid type`). |
| `getAllData` + `date` | “`getAllData` prevalece sobre `date`; com qualquer `date` devolve a cadeia integral” | Só expande todas as expirações com `date` **ausente ou `-1`**; com `date` específico, **1 expiração**; com `0`/`-2`, **1 entrada vazia**. |
| Duplicatas | não documentadas | **Primeira ocorrência vence** para `date`, `formatted`, `straddle` e `crumb`. |
| `straddle` + modo strike | “não sondado” | Funciona: 21 entradas e 16 straddles para `strike=160` (26.139 B). |
| `date` + modo strike | “não observado” | `date=-1` → 21 entradas; `date` específico → 1 entrada (3.441 B; 0 contratos se o strike não existir). |
| Parsing de `strikeMin/Max` | apenas “num” | Aceita `+160`, espaços, `0160`, `160.0`, `1.5`, `1e2`; `NaN` = sem filtro; `Infinity` em `strikeMin` = 0 contratos, em `strikeMax` = tudo; `abc` = `400`. |
| Medições | 99,7 KB canônica; 1.799.199 B integral | 98.092 B canônica; 1.778.513 B integral; 2.747 contratos; 76→130 strikes no modo strike. |
| Cobertura | ~16 chamadas | **97 chamadas + 8 de bootstrap**, 4 estágios, sem `5xx`; artefatos brutos em `%TEMP%\opencode\yfin-intel\probe_stage1..4.json`. |
| Exemplo de contrato | `contractSymbol` `AAPL261106C00160000` com `expiration` de 2026-10-02 (inconsistente) | `AAPL261002C00160000`, casando com o vencimento e os demais campos da captura. |
| Omissão de campos | “`volume` e `lastTradeDate` omitidos quando o contrato nunca negociou” | Só `volume` foi observado ausente (sem negociação no dia): 1/146 na mínima e 3/124 na captura de out/2026; `lastTradeDate` permaneceu. |
| Contagem do quote em índice | “83/90 campos” aplicado a PETR4.SA e `^GSPC` | 83–90 campos em ações; **61** no `^GSPC` (quoteType INDEX). |
