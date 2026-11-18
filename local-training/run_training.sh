#!/usr/bin/env bash
set -euo pipefail
TRAINING_ROOT="$(cd "$(dirname "$0")" && pwd)"
SIZE="${1:?Pass 4B or 9B}"
ATTEMPT="${2:?Pass an attempt number}"
case "$SIZE" in 4B|9B) ;; *) exit 2 ;; esac
case "$ATTEMPT" in ''|*[!0-9]*) exit 2 ;; esac
if [ "${3:-}" != "--gpu-ready" ]; then
  echo 'Stop inference/benchmarks and pass --gpu-ready as the third argument.' >&2
  exit 2
fi
RUNTIME_ROOT="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["runtime_root"])' "$TRAINING_ROOT/runtime.json")"
exec > "$TRAINING_ROOT/train-${SIZE,,}-attempt${ATTEMPT}.stdout.log" 2> "$TRAINING_ROOT/train-${SIZE,,}-attempt${ATTEMPT}.stderr.log"
exec "$RUNTIME_ROOT/.venv/bin/python" -u "$TRAINING_ROOT/train_lanm.py" --size "$SIZE" --precision qlora4 --gpu-ready
