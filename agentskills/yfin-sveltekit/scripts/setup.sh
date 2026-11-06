#!/usr/bin/env bash
# usage: setup.sh <workdir>
# Copies the skill's scripts into <workdir>/tools (a writable place: installed skill folders may be read-only), installs the pinned
# dependencies there (npm ci) and checks that Node and a headless Chromium are usable. Prints "TOOLS=<path>" on success.
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="${1:?usage: setup.sh <workdir>}"
NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)"
if [ "$NODE_MAJOR" -lt 22 ]; then echo "ERROR: Node >= 22 is required (found: $(node -v 2>/dev/null || echo none))" >&2; exit 1; fi
mkdir -p "$WORK/tools"
if [ "$SRC" != "$(cd "$WORK/tools" && pwd)" ]; then
  (cd "$SRC" && tar --exclude=node_modules -cf - .) | (cd "$WORK/tools" && tar -xf -)
fi
cd "$WORK/tools"
if [ ! -d node_modules/@babel/parser ] || [ ! -x node_modules/@wakaru/cli/bin/wakaru ]; then
  PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm ci --no-audit --no-fund --loglevel=error
fi
chmod +x *.sh 2>/dev/null || true
echo "babel: $(node -p "require('./node_modules/@babel/parser/package.json').version")  prettier: $(node -p "require('./node_modules/prettier/package.json').version")  wakaru: $(node -p "require('./node_modules/@wakaru/cli/package.json').version")  playwright: $(node -p "require('./node_modules/playwright/package.json').version")"
if node --input-type=module -e "import('playwright').then(async ({chromium})=>{let b;try{b=await chromium.launch({headless:true,args:['--no-sandbox']})}catch(e){if(!/Executable doesn.t exist|playwright install/i.test(String(e&&e.message)))throw e;b=await chromium.launch({headless:true,channel:'chrome',args:['--no-sandbox']})}await b.close();})" >/dev/null 2>&1; then
  echo "CHROMIUM: ok"
else
  echo "CHROMIUM: UNAVAILABLE - runtime verification (runtime_cmp.mjs) cannot run. Try: PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers, a system Chrome (used automatically when the playwright download is absent), or 'npx playwright install chromium'. If it stays unavailable, the final report MUST say that the runtime check was not done." >&2
fi
echo "TOOLS=$(pwd)"
