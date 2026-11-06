# SvelteKit build internals, verified on real finance.yahoo.com builds

The build describes itself. Before any renaming runs, `entry/app.<hash>.js` (+ the kit client chunk) already
declares the routes, the server loads, the matchers, the hydration global and the node table — this file is
the decoding of that self-description, with the evidence for every rule. `scripts/kit_intel.mjs <root> <outDir>`
turns it into `reports/KIT_INTEL.md` for any build; `scripts/routes_lib.mjs` implements the decoding used by
the pipeline. Everything here is static reading of `entry/` + `chunks/` only.

## The exports of entry/app.<hash>.js (B)

A raw (minified) file re-exports six names at the end, e.g. `export{he as dictionary,De as hooks,Le as
matchers,Te as nodes,Ae as root,Oe as server_loads}`. A prettified one has them as `export const ...`.
`nodes` = the lazy-import table; `dictionary` = the route table; `server_loads`, `matchers`, `hooks`, `root`
as below. The kit client chunk (the one `entry/start.<hash>.js` imports) is the CONSUMER of all of them —
when in doubt, read its `create_client` there (minified on a real build, e.g. `function Nt({nodes,server_loads,dictionary,matchers})`).

## dictionary: "route": [leaf, layouts, errors] (B: runtime + official generator source)

- **leaf** — the page node id, ENCODED when the page has a `+page.server.js` load: kit's own source writes
  the expression `~N` (bitwise NOT) and the site's minifier constant-folds it to `-N-1`. So `"~183"` and
  `"-184"` BOTH mean node 183 with a server load. The runtime proof (quoted from the kit client chunk of a
  real build): `function o(s){const c=s<0;return c&&(s=~s),[c,e[s]]}` — negative flag = has server load,
  node = `~value`. **`Math.abs(-184)` = 184 is the classic off-by-one**: on the real build node 184 is a
  different page (analysis), and `-198` -> 197 collides with `+198` -> 198.
- **layouts** — layout node ids BELOW the root layout. **The root layout (node 0) is implicit**: the runtime
  prepends it to every route (`layouts:[0,...f||[]]` in the kit client), so current dictionaries never list
  it and frequency-counting node 0 across the dictionary returns 0. Older formats listed it. Consequence
  for scoping: `@universal` must include node 0 by DETECTION (does the kit client contain `layouts:[0,`?),
  never by convention — see `detectImplicitRoot()` in routes_lib.mjs.
- **errors** — optional 3rd array: `+error` boundary node ids below the root error boundary. Node 1 is the
  implicit root error (`errors:[1,...d||[]]`). Holes (`,,`) in layouts/errors mean "no node at that nesting
  level" — they must not decode to 0.
- **server_loads** (separate export) — the ids of the LAYOUTS with a `+layout.server.js` load. Together with
  the leaf marker this decides which positions of a route's `__data.json` carry data (everything else is
  null/skip): a route with tree [root 0, layout 2, layout 39, leaf ~183] and server_loads [2] yields nodes
  `[null, <data>, null, <data>]` — exactly what a real /quote/AAPL download showed.

## The nodes array (B — with a real-build surprise)

`nodes` is indexed by node id: `nodes[i]` is a lazy `import()`. Slots normally point at `../nodes/i.<hash>.js`,
but on a real build TWO slots pointed at `../chunks/*.js` instead (Vite had fused those nodes into chunks —
`nodes[96]` was the kit-client chunk itself, and it was the leaf of a route). Parse the array POSITIONALLY
(`routes_lib.parseNodesArray`); a `../nodes/`-only regex silently loses every route whose leaf is such a slot.
Entries also carry their preload deps inline: `()=>r(()=>import(PATH).then(p=>p.X),__vite__mapDeps([i,j]),import.meta.url)`
— the `.then(...)` between the import and `__vite__mapDeps` broke naive regex matching (preloads were silently
never added before this was found).

## matchers: [param=name] (B)

Route keys like `/(app)/[page=markets]` are ONE route for many URLs; the matcher function decides. Real
values seen (re-derive per build with `kit_intel.mjs` — they are the site's, not the framework's):
`markets` accepted `["markets","mercados","marchés","märkte","mercati"]` — every localized market home hits
the same route. Practical effect: to scope "the markets pages", match the DICTIONARY KEY, not URLs. Another
seen: `investYear` accepting `["2026"]` (the route is retired by editing this array).

## The kit client chunk (B)

Found from `entry/start.<hash>.js` (`import{s as t}from"../chunks/<chunk>.js"`). It is the SvelteKit client
(`create_client`, router, hydration, link interception) and it carries:

- `__sveltekit_<id>` — the hydration global. Every server-rendered page's inline `<script>` sets it; the
  chunk reads it. If a downloaded HTML sets `__sveltekit_A` while the chunk reads `__sveltekit_B`, the HTML
  and the JS come from DIFFERENT builds (mixed download; the page will not hydrate). One grep, no execution —
  a legitimate user-directed check when the user asks why a downloaded page is blank.
- a 12-14 digit epoch-ms string (e.g. `"1793293387261"` -> 2026-10-29) — a build constant (H: the exact
  meaning is a hypothesis; the number is a build-scoped constant, not a hash of the files).

## hooks / reroute (B)

`hooks` (also exported by app.*.js) contains `reroute: ({url}) => string | void` — on the real build a whole
table of LEGACY URL rewrites (`select-plan` -> `/about/plans/select-plan`, `gold/alphaspace` -> ...). After
deobfuscation it reads as plain code: it is the site's own redirect map, more reliable than following HTTP
redirects, and it explains URL shapes the dictionary alone does not.

## devalue: the data wire format (B)

Server-load data (each `__data.json`, and the inline hydration `<script>` of every page) is serialised with
devalue: a root array where entry 0 is the payload and every number inside a container is a REFERENCE (an
index into that array) — literals always get their own entry. Special values arrive as `["Date",iso]`,
`["Set",[...]]`, `["Map",[k,v,...]]`, `["RegExp",src]`, `["Infinity"]`, `["-Infinity"]`, `["NaN"]`,
`["-0"]`, `["undefined"]`, `["bigint",digits]`. `scripts/decode_devalue.mjs <file>` decodes a payload the
user already has (never fetch one). Why a deobfuscator cares: the layout-2 server-load payload is the site's
own service table — every API host the client may call (`query1.finance.yahoo.com`, `yfc-server-query`,
`graviton-...`), which names the fetch sites you meet while reading the code. Decoding was cross-validated
against the literal object embedded in the page's hydration script (same hosts, same timeouts).

## Where this feeds the pipeline

- `routes_lib.mjs` — the single decoder (dictionary + nodes array + implicit-root detection) used by
  select_routes / annotate_routes / reports / kit_intel.
- `select_routes.mjs` — scoping with the corrected leaf decoding, the implicit root layout included when
  detected, preloads that actually attach, and holes that decode to nothing.
- `annotate_routes.mjs` — page nodes labelled `(server load)` when their leaf is negative; node 0 labelled
  as the implicit root layout when detected.
- `kit_intel.mjs` — `reports/KIT_INTEL.md`: this build's decoded self-description.
- `decode_devalue.mjs` — readable data payloads for the files the user provides, plus a static
  API URL/host inventory via `--api-map` (the layout-2 payload is the site's service table).

A last caution: these rules were verified against SvelteKit 2.x-era finance.yahoo.com builds (leaf `~N`
encoding, implicit node 0). If a future build changes format, the failure mode is visible, not silent:
`kit_intel.mjs` reports 0 routes / no dictionary, and the selftest re-checks the decoders against fixtures.
