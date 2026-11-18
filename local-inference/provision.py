"""Fetch the pinned public runtime and model approved for this local benchmark."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent
ASSETS = [
    ("llama-b12323-bin-win-cuda-12.4-x64.zip", "https://github.com/ggml-org/llama.cpp/releases/download/b12323/llama-b12323-bin-win-cuda-12.4-x64.zip", "14ba88e9056f054fc32f329b7e98ad411a1775ff4d26bebe9ce7e4b8ff2ec310", 317261064),
    ("cudart-llama-bin-win-cuda-12.4-x64.zip", "https://github.com/ggml-org/llama.cpp/releases/download/b12323/cudart-llama-bin-win-cuda-12.4-x64.zip", "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6", 391443627),
    ("Qwen3.5-4B-Q4_K_M.gguf", "https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/e87f176479d0855a907a41277aca2f8ee7a09523/Qwen3.5-4B-Q4_K_M.gguf?download=true", "00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4", 2740937888),
]

def fetch(asset):
    name, url, expected, size = asset
    target = ROOT / name
    if not target.exists():
        partial = target.with_suffix(target.suffix + ".partial")
        print("Downloading " + name, flush=True)
        request = urllib.request.Request(url, headers={"User-Agent": "LanM-local-benchmark"})
        with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as output:
            while data := response.read(8 * 1024 * 1024):
                output.write(data)
        partial.replace(target)
    digest = hashlib.sha256()
    with target.open("rb") as stream:
        while data := stream.read(8 * 1024 * 1024):
            digest.update(data)
    if target.stat().st_size != size or digest.hexdigest() != expected:
        raise ValueError("Checksum or size mismatch for " + name)
    print("Verified " + name, flush=True)
    return {"file": name, "url": url, "sha256": digest.hexdigest(), "bytes": size}

if __name__ == "__main__":
    ROOT.mkdir(exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        assets = list(executor.map(fetch, ASSETS))
    runtime = ROOT / "llama-b12323"
    runtime.mkdir(exist_ok=True)
    for asset in assets:
        if asset["file"].endswith(".zip"):
            with zipfile.ZipFile(ROOT / asset["file"]) as archive:
                for info in archive.infolist():
                    if not (runtime / info.filename).resolve().is_relative_to(runtime.resolve()):
                        raise ValueError("Unsafe archive path")
                archive.extractall(runtime)
    manifest = {"model": "Qwen3.5-4B", "base_model": "Qwen/Qwen3.5-4B", "conversion_repository": "unsloth/Qwen3.5-4B-GGUF", "revision": "e87f176479d0855a907a41277aca2f8ee7a09523", "quantization": "Q4_K_M", "license": "Apache-2.0", "runtime": "llama.cpp b12323, Windows CUDA 12.4 x64", "assets": assets}
    (ROOT / "provenance.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print("Download, verification, and extraction complete", flush=True)
