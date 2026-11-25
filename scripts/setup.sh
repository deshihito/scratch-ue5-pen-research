#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

echo "=== 1. Downloading @turbowarp/scaffolding standalone runtime ==="
mkdir -p vendor/scaffolding
npm pack @turbowarp/scaffolding --pack-destination "$ROOT_DIR"
tar -xzf turbowarp-scaffolding-*.tgz -C vendor/scaffolding --strip-components=1
rm -f turbowarp-scaffolding-*.tgz

echo "=== 2. Checking Python + Playwright ==="
python3 --version
if ! python3 -c "import playwright" 2>/dev/null; then
  echo "Installing playwright Python package..."
  pip install playwright
  playwright install chromium
fi

echo "=== Setup complete! ==="
echo "Build all .sb3 files:  bash scripts/build_all.sh"
echo "Run a .sb3 headless:   python3 runner.py sb3/ue5_lumen_sdf.sb3 turbowarp out/preview.png"
