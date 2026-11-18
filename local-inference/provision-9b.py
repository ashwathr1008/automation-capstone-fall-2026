"""Download and verify the larger challenger; does not launch inference."""
import json
from provision import ROOT, fetch

REVISION = "3885219b6810b007914f3a7950a8d1b469d598a5"
ASSET = ("Qwen3.5-9B-Q4_K_M.gguf",
         "https://huggingface.co/unsloth/Qwen3.5-9B-GGUF/resolve/" + REVISION + "/Qwen3.5-9B-Q4_K_M.gguf?download=true",
         "03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8", 5680522464)

if __name__ == "__main__":
    asset = fetch(ASSET)
    manifest = {"model": "Qwen3.5-9B", "base_model": "Qwen/Qwen3.5-9B",
                "conversion_repository": "unsloth/Qwen3.5-9B-GGUF", "revision": REVISION,
                "quantization": "Q4_K_M", "license": "Apache-2.0",
                "runtime": "llama.cpp b12323, Windows CUDA 12.4 x64",
                "runtime_provenance": "provenance.json", "assets": [asset]}
    (ROOT / "provenance-9b.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print("9B download verified; server has NOT been started", flush=True)
