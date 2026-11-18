# Local Qwen benchmark runtime

The source helpers in this directory provision and serve pinned local models. Downloaded weights, runtime binaries, logs, PID files and generated provenance stay local and are excluded from Git. These Windows CUDA helpers require a compatible NVIDIA GPU and driver; a fresh clone has no installed inference server.

From the repository root, download and verify the runtime and selected bases before starting them:

```powershell
python local-inference/provision.py
python local-inference/provision-9b.py
python local-training/prepare_workspace.py
```

Provisioning does not start a server. The profile initializer preserves existing settings and adds app examples only to an already-restored research workspace. The measurements below describe the original development laptop, not hardware requirements or a result from your machine.

- Base model: `Qwen/Qwen3.5-4B`, Apache-2.0.
- GGUF conversion: `unsloth/Qwen3.5-4B-GGUF`, revision `e87f176479d0855a907a41277aca2f8ee7a09523`, `Q4_K_M` (2,740,937,888 bytes).
- Runtime: official `ggml-org/llama.cpp` release `b12323`, version `0.9.0-dev`, commit `93cf736a8`, Windows x64 CUDA 12.4.
- Hardware: NVIDIA GeForce RTX 4090 Laptop GPU, 16,376 MiB VRAM, driver 621.01. The server appears in NVIDIA's compute-process list; total GPU memory used after the smoke test was about 4.05 GB.
- All downloaded artifacts were verified against publisher SHA-256 values. See `provenance.json` for exact URLs, sizes, and hashes.

Start/reuse the background server:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\local-inference\start-qwen.ps1
```

Use `http://127.0.0.1:18080/v1` and model ID `qwen3.5-4b`; no API key is configured. The server listens only on the loopback address. New starts restrict browser CORS origins to localhost. The application performs all tool execution; the inference server only returns model output.

The startup script sets 32,768 context tokens, one concurrent slot, all layers on GPU, flash attention, native Jinja tool parsing, reasoning off, temperature 0.2 and seed 42. It requested a 4,096-token output limit, but the running server's properties reported `n_predict=-1`; the original baseline cap was therefore unverified. Current platform profiles explicitly send `max_tokens=4096` per request. Thinking-on profiles also send the supported chat-template override. These choices must accompany benchmark results; a 4-bit 4B model is not representative of every Qwen3.5 model.

```powershell
python .\local-inference\smoke-test.py
powershell -NoProfile -ExecutionPolicy Bypass -File .\local-inference\stop-qwen.ps1
```

`smoke-test.json` records an actual two-request native tool-call cycle on a fictional lookup fixture. This is protocol validation, not a scientific benchmark. `server.stdout.log` and `server.stderr.log` contain runtime diagnostics. The stop script verifies the saved PID still belongs to this directory's executable before stopping it.

References: [Qwen model card](https://huggingface.co/Qwen/Qwen3.5-4B), [GGUF files](https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/tree/e87f176479d0855a907a41277aca2f8ee7a09523), [llama.cpp release](https://github.com/ggml-org/llama.cpp/releases/tag/b12323), [server documentation](https://github.com/ggml-org/llama.cpp/blob/b12323/tools/server/README.md).

## Larger 9B comparison

`Qwen3.5-9B-Q4_K_M.gguf` is also downloaded and verified. It is the Apache-2.0 Unsloth conversion at revision `3885219b6810b007914f3a7950a8d1b469d598a5`, 5,680,522,464 bytes. Exact download URL and hash are in `provenance-9b.json`. It uses the same portable runtime and generation settings, with its own port, PID file, and logs.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\local-inference\start-qwen-9b.ps1
python .\local-inference\smoke-test.py --port 18081 --model qwen3.5-9b --output smoke-test-9b.json
powershell -NoProfile -ExecutionPolicy Bypass -File .\local-inference\stop-qwen-9b.ps1
```

Its endpoint is `http://127.0.0.1:18081/v1`, model `qwen3.5-9b`. Run model comparisons sequentially; simultaneous GPU inference would contaminate timing results. Model loading is separate from per-request inference timing. These scripts do not automatically stop the other model's server. The platform also has optional domain-context profiles: these retrieve existing local text and guidance while leaving the downloaded weights unchanged. No training environment or training checkpoint is required.

The 9B server passed the same native tool-call smoke test in 1.187 seconds after a roughly 3.48-second model load. Both servers resident together used 10,386 MiB total GPU memory, leaving 5,663 MiB free. See `smoke-test-9b.json`; these figures describe this one smoke run, not the platform benchmark.
