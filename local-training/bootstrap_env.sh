#!/usr/bin/env bash
set -euo pipefail
TRAINING_ROOT="$(cd "$(dirname "$0")" && pwd)"
RUNTIME_ROOT="${LANM_TRAINING_RUNTIME_ROOT:-$TRAINING_ROOT}"
export LANM_TRAINING_RUNTIME_ROOT="$RUNTIME_ROOT"
export UV_CACHE_DIR="$RUNTIME_ROOT/cache/uv"
export UV_PYTHON_INSTALL_DIR="$RUNTIME_ROOT/python"
export UV_PYTHON_BIN_DIR="$RUNTIME_ROOT/bin"
export HF_HOME="$RUNTIME_ROOT/cache/huggingface"
export XDG_CACHE_HOME="$RUNTIME_ROOT/cache"
export TORCH_HOME="$RUNTIME_ROOT/cache/torch"
export TRITON_CACHE_DIR="$RUNTIME_ROOT/cache/triton"
export TMPDIR="$RUNTIME_ROOT/tmp"
export UV_LINK_MODE=hardlink
export UV_CONCURRENT_DOWNLOADS=2
export UV_CONCURRENT_INSTALLS=1
mkdir -p "$TRAINING_ROOT/bin" "$RUNTIME_ROOT/bin" "$TMPDIR" "$UV_CACHE_DIR"
if [ ! -x "$TRAINING_ROOT/bin/uv" ]; then
  python3 "$TRAINING_ROOT/provision_training.py" --uv-only
fi
python3 "$TRAINING_ROOT/provision_training.py" --compiler-only
python3 "$TRAINING_ROOT/provision_training.py" --converter-only
if [ "$RUNTIME_ROOT" != "$TRAINING_ROOT" ]; then
  ln -sfn "$TRAINING_ROOT/bin/cc" "$RUNTIME_ROOT/bin/cc"
  ln -sfn "$TRAINING_ROOT/bin/cxx" "$RUNTIME_ROOT/bin/cxx"
fi
python3 -c 'import json,os,pathlib,sys; pathlib.Path(sys.argv[1]).write_text(json.dumps({"runtime_root":os.environ["LANM_TRAINING_RUNTIME_ROOT"],"reason":"Native WSL dependency/cache location avoids Windows filesystem latency; data, checkpoints and exports remain in workspace."},indent=2))' "$TRAINING_ROOT/runtime.json"
"$TRAINING_ROOT/bin/uv" python install 3.12
if [ ! -x "$RUNTIME_ROOT/.venv/bin/python" ]; then
  "$TRAINING_ROOT/bin/uv" venv --python 3.12 "$RUNTIME_ROOT/.venv"
fi
"$TRAINING_ROOT/bin/uv" pip sync --python "$RUNTIME_ROOT/.venv/bin/python" "$TRAINING_ROOT/environment-lock.txt"
"$TRAINING_ROOT/bin/uv" pip freeze --python "$RUNTIME_ROOT/.venv/bin/python" > "$TRAINING_ROOT/environment-installed.txt"
"$RUNTIME_ROOT/.venv/bin/python" -c 'import importlib.metadata,json,sys; print(json.dumps({"python":sys.version,"executable":sys.executable,"packages":{n:importlib.metadata.version(n) for n in ["torch","unsloth","unsloth_zoo","transformers","trl","peft","bitsandbytes","accelerate","datasets"]}},indent=2))' > "$TRAINING_ROOT/environment.json"
