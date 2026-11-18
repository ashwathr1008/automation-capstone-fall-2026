# LanM model adaptation

These utilities train real LoRA adapters for Qwen3.5-4B and Qwen3.5-9B. The base weights remain frozen while small learned matrices change model behavior. One adapter per size supports thinking off and on at inference. Domain-context retrieval is a separate feature that leaves weights unchanged.

The repository includes source, pinned dependencies, profile templates and compact training results. It does **not** include model weights, learned adapters, generated training records, private research state, credentials or raw benchmark traces. A new clone must provision and train its own adapters. Local inference uses Windows with an NVIDIA GPU; training uses WSL Ubuntu and CUDA. The recorded recipe used a 16GB RTX 4090 Laptop GPU.

## Historical training evidence

Both sizes completed one epoch on 366 training examples, with 46 optimizer steps and 47 fixed validation examples on 18 November 2026. Held-out assistant-token loss changed from 0.657008 to 0.273220 for 4B, and from 0.653120 to 0.269904 for 9B. These losses measure fit to domain responses; they are not workflow-completion rates or scientific-accuracy scores. [training-results.json](training-results.json) records settings, metrics and artifact hashes.

Exact original trainer, corpus-builder, setup/export source and compact provenance are preserved in [recipes/2026-11-18](recipes/2026-11-18/manifest.json). These snapshots retain their original directory assumptions for audit. Active utilities generalize workspace setup and GPU handoff while preserving training hyperparameters and token masking. Do not combine new code hashes with the original benchmark.

## Prepare a fresh clone

Restore the starter research workspace using the [root setup instructions](../README.md). From the repository root in PowerShell:

```powershell
python local-training/prepare_workspace.py
python local-training/prepare_lanm_training.py
python -m unittest discover -s local-training/tests -v
python local-inference/provision.py
python local-inference/provision-9b.py
```

The initializer preserves existing files. It creates benchmark configuration under `benchmark-results/local-comparison` and adds example app profiles only when a research workspace directory already exists. The corpus builder uses tracked library assets and isolated synthetic projects; it never reads live databases, chats or benchmark cases. See [DATASET.md](DATASET.md). Provisioners download and hash-check the pinned Windows runtime and Q4_K_M bases without starting servers.

In WSL Ubuntu, change to **your clone's directory**, then run:

```bash
export LANM_TRAINING_RUNTIME_ROOT=/var/tmp/lanm-training
bash local-training/bootstrap_env.sh
PY="$LANM_TRAINING_RUNTIME_ROOT/.venv/bin/python"
"$PY" local-training/provision_training.py --model both
"$PY" local-training/verify_token_masks.py
"$PY" local-training/train_lanm.py --size 4B --prepare-only --output local-training/runs/preflight-4b
"$PY" local-training/train_lanm.py --size 9B --prepare-only --output local-training/runs/preflight-9b
"$PY" local-training/export_adapter.py --size 4B --synthetic-check
"$PY" local-training/export_adapter.py --size 9B --synthetic-check
```

Bootstrap installs `environment-lock.txt` into a dedicated environment and records installed versions separately. Official training revisions are pinned in `base-lineage.json`; downloads verify available publisher hashes. Official and GGUF conversion revisions identify different repositories, with recorded same-family/release lineage. Synthetic exports contain zero-valued tensors for conversion checks and cannot pass trained-artifact validation.

## Train and export

Stop inference servers and benchmark jobs before releasing the GPU. `--gpu-ready` explicitly confirms that handoff for this invocation. No historical benchmark marker is required. Training additionally refuses to start when less than 80% of GPU memory is free.

```bash
"$PY" local-training/verify_gpu_runtime.py --gpu-ready
"$PY" local-training/train_lanm.py --size 4B --precision qlora4 --gpu-ready
"$PY" local-training/export_adapter.py --size 4B
"$PY" local-training/train_lanm.py --size 9B --precision qlora4 --gpu-ready
"$PY" local-training/export_adapter.py --size 9B
```

Both sizes use one epoch, batch size 1, accumulation 8, context 4096, rank/alpha 16, learning rate 0.0001 and seed 42. QLoRA uses a quantized base with bf16 computation. Only decoder attention `q/k/v/o_proj` and MLP `gate/up/down_proj` adapters train. Vision, MTP, embeddings and output heads remain frozen. The recorded hardware required a QLoRA compromise; the [Unsloth guide](https://unsloth.ai/docs/models/qwen3.5/fine-tune) recommends bf16 LoRA for Qwen3.5 when memory permits.

Oversized records fail instead of truncating answers. Loss covers assistant answer/tool-call tokens and end-of-message tokens, excluding prompts, tool observations and empty thinking delimiters. Original runs used PyTorch attention and reference causal-convolution fallbacks. Accumulation used microbatch-mean scaling; globally supervised-token-weighted scaling was not established. Historical results retain these limitations.

Completed run directories are immutable. Resume requires matching checkpoint, code, data, base, tokenizer and settings. Deliberate retraining needs a fresh `--output`, passed to export with `--run`. Standard serving/registration targets `runs/qwen-4b-lanm` and `runs/qwen-9b-lanm`, so it will not silently select a later rerun. Fixed seeds do not guarantee bit-identical GPU results.

## Register and use trained models

After both actual adapters finish, return to PowerShell:

```powershell
python local-training/register_trained_profiles.py
python local-training/register_trained_profiles.py --run
./local-training/start-trained-qwen.ps1 -Size 4B
python local-training/check_platform_integration.py --size 4B --run
./local-training/stop-trained-qwen.ps1 -Size 4B
./local-training/start-trained-qwen.ps1 -Size 9B
python local-training/check_platform_integration.py --size 9B --run
./local-training/stop-trained-qwen.ps1 -Size 9B
```

The first registration command previews changes. Registration checks actual nonzero learned adapters, data identity and export lineage before adding trained profiles. It refuses to replace different existing profiles and accepts `--benchmark-dir` and `--app-profiles` for explicit destinations. Restart an already-running platform to load new choices. Start only the selected model when timing comparisons.

Trained aliases are `qwen3.5-4b-lanm` on port 18082 and `qwen3.5-9b-lanm` on 18083. Serving attaches a separate f16 adapter to the pinned base with llama.cpp b12323. The smoke verifies the sole loaded adapter at scale 1 and a real read-only LanM tool call. It does not replace the broader workflow benchmark.

## Evaluate and inspect

Install plotting support into your chosen application/evaluation Python environment:

```powershell
python -m pip install -e "./platform[evaluations]"
python local-training/post_training_queue.py
```

Queue preparation makes no model requests. Review its generated plan before adding `--run`; execution requires both trained adapters and account access where applicable. The queue retains failures, verifies resume identities and runs local servers sequentially. See [evaluation instructions](../platform/evaluations/README.md) for provider runs, summaries, figures and answer review. Reports stay outside Git. Original strict and clarified-task results remain separate: 16 workflow templates repeated three times per configuration are not independent scientific tasks.

The fresh-clone queue includes all eight local configurations: 384 original attempts plus 24 clarified-method attempts. It does not assume the base measurements already exist. Hosted configurations are run separately with `compare.py --workflows` and `clarified_method.py`, each with `--repeat 3 --timeout 300` and the same explicit profiles file. The historical 216-attempt continuation queue is preserved in the recipe archive.

CPU setup/guard tests require no models, account or GPU:

```powershell
python -m unittest discover -s local-training -p "test_*.py" -v
```
