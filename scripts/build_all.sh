#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

python3 build_bench.py
python3 build_ue5_lumen.py
python3 build_ue5_lumen_fast.py
python3 build_ue5_lumen_realtime.py
python3 build_pathtracer.py
python3 build_3dgs_splat.py

ls -lh sb3/*.sb3
