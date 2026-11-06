# Wakaru hazards (all observed on the real build, Wakaru CLI 1.14.0)

Wakaru (`--level standard`) un-minifies well but several rewrites change behaviour. Rust CLI 1.14.0 has no per-rule flags and `--level minimal` still does the class conversion, so the only safe handling is detection + fallback to the original code for that file.

| Hazard | What Wakaru does | Symptom | Detector |
|---|---|---|---|
| function -> class | ES5 constructor `function F(){}; F.prototype.x=...` becomes `class F` | `Class constructor F cannot be invoked without 'new'` (e.g. markdown-it `wt("commonmark",...)`); `F.call(this)` fails | scan: `new-classes`, `class-called-without-new`, `class-call-apply`; runtime |
| `__importDefault(x)` -> `x` | drops `.default` | `Class extends value [object Object] is not a constructor` | scan: `interop-helper` (pattern in ORIGINAL) |
| JSX output | emits JSX for `createElement`/jsx calls | not executable in a browser | scan: `jsx`; runtime |
| Inlined Babel helpers | helper bodies removed/inlined | strings like "@@toPrimitive must return a primitive value.", "@@iterator" disappear | scan: `strings-lost n` |
| Default params | `a===void 0&&(a=x)` -> `a=x` | `Function.length` changes (seen on floating-ui helpers and similar small chunks) | scan: INFO `function-length-drift` (about 100 files per build, harmless in practice); runtime caught approval |
| Parse/crash | Wakaru fails on a file | missing output | `_failures.txt`; file copied from ORIG |
| Import/export changes | rare | interface differs | scan: `imports-differ`/`exports-differ`; verify_pair |

Rules
- Scanner flags -> file goes to the fallback list. Runtime culprits -> append to the list and re-run.
- The scanner is not complete (approval was found only by runtime). Everything not flagged is "tested, not proven".
- Pre-built third-party libraries named `*.min.*` / `*.worker.*` are skipped by Wakaru (override: `WAKARU_SKIP_REGEX`); other vendor directories of the site are out of scope and never read. A size-based skip is NOT used: Wakaru handled every file of both builds (0 failures, 180 s timeout per file falls back to the original), and big files such as `Header` are app code worth reading.
- Do not hand-edit Wakaru output to repair it; use the original code.
- A fallback file is still renamed and prettified (stage 2) so readability is not lost.
