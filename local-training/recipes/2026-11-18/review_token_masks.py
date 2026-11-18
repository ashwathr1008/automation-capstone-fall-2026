"""Independent CPU-only native-Jinja/Rust-tokenizer audit, without model weights.

This lightweight check complements the training environment's AutoTokenizer
preflight. It uses the same official tokenizer assets and native Jinja template.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
os.environ["CUDA_VISIBLE_DEVICES"] = ""
sys.path.insert(0, str(ROOT / "review-python"))

import tokenizers
from tokenizers import Tokenizer
from jinja2.sandbox import ImmutableSandboxedEnvironment
from train_lanm import encode_record, read_records, sha, write_json


class NativeTokenizer:
    def __init__(self, base):
        self.chat_template = (base / "chat_template.jinja").read_text(encoding="utf-8")
        self.backend = Tokenizer.from_file(str(base / "tokenizer.json"))
        self.eos_token_id = self.backend.token_to_id("<|im_end|>")
        self.pad_token_id = self.backend.token_to_id("<|endoftext|>")
        environment = ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True)
        # The HF renderer uses JSON rather than HTML-safe Jinja JSON escaping.
        environment.filters["tojson"] = lambda value, ensure_ascii=False, indent=None, separators=None, sort_keys=False: json.dumps(
            value, ensure_ascii=ensure_ascii, indent=indent, separators=separators, sort_keys=sort_keys)
        def fail(message):
            raise ValueError(message)
        environment.globals["raise_exception"] = fail
        self.template = environment.from_string(self.chat_template)

    def apply_chat_template(self, messages, **kwargs):
        assert not kwargs.pop("tokenize")
        return self.template.render(messages=messages, **kwargs)

    def __call__(self, text, add_special_tokens=False, return_offsets_mapping=True):
        assert not add_special_tokens and return_offsets_mapping
        encoded = self.backend.encode(text, add_special_tokens=False)
        return {"input_ids": encoded.ids, "offset_mapping": encoded.offsets}

    def decode(self, tokens):
        return self.backend.decode(tokens, skip_special_tokens=False)


def main():
    base = ROOT / "models" / "Qwen3.5-4B"
    other = ROOT / "models" / "Qwen3.5-9B"
    assets = ("tokenizer.json", "tokenizer_config.json", "chat_template.jinja")
    for name in assets:
        assert (base / name).read_bytes() == (other / name).read_bytes(), name
    tokenizer = NativeTokenizer(base)
    test = {"id": "independent-mask-proof", "messages": [
        {"role": "system", "content": "UNIQUE_SYSTEM_OBSERVATION"},
        {"role": "user", "content": "UNIQUE_USER_OBSERVATION"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "call-proof", "type": "function", "function": {
            "name": "project_state", "arguments": {"project_id": "independent-proof-project"}}}]},
        {"role": "tool", "name": "project_state", "tool_call_id": "call-proof", "content": "UNIQUE_TOOL_OBSERVATION"},
        {"role": "assistant", "content": "UNIQUE_ASSISTANT_ANSWER"}],
        "tools": [{"type": "function", "function": {"name": "project_state", "description": "UNIQUE_SCHEMA_OBSERVATION",
            "parameters": {"type": "object", "properties": {"project_id": {"type": "string"}}, "required": ["project_id"]}}}]}
    encoded = encode_record(tokenizer, test, 4096)
    supervised = tokenizer.decode([value for value in encoded["labels"] if value != -100])
    for masked in ("UNIQUE_SYSTEM_OBSERVATION", "UNIQUE_USER_OBSERVATION", "UNIQUE_TOOL_OBSERVATION", "UNIQUE_SCHEMA_OBSERVATION"):
        assert masked not in supervised, masked
    for learned in ("UNIQUE_ASSISTANT_ANSWER", "<function=project_state>", "independent-proof-project", "</parameter>", "</function>"):
        assert learned in supervised, learned
    assert encoded["labels"].count(248046) == 2
    assert encoded["labels"].count(248058) == encoded["labels"].count(248059) == 1
    assert 248068 not in encoded["labels"] and 248069 not in encoded["labels"]
    assert 248045 not in encoded["labels"] and 248044 not in encoded["labels"]
    try:
        encode_record(tokenizer, test, 10)
    except ValueError as error:
        assert "never truncate" in str(error)
    else:
        raise AssertionError("Overlong records must be rejected")

    counts = {}
    for split in ("train", "validation"):
        records = read_records(ROOT / "data" / (split + ".jsonl"))
        stats = []
        for row in records:
            item = encode_record(tokenizer, row, 4096)
            assistant_count = sum(message["role"] == "assistant" for message in row["messages"])
            call_count = sum(len(message.get("tool_calls", [])) for message in row["messages"])
            assert item["labels"].count(248046) == assistant_count, row["id"]
            assert item["labels"].count(248058) == item["labels"].count(248059) == call_count, row["id"]
            assert not {248044, 248045, 248068, 248069}.intersection(item["labels"]), row["id"]
            stats.append({"id": row["id"], "tokens": len(item["input_ids"]),
                          "supervised_tokens": sum(label != -100 for label in item["labels"])})
        counts[split] = {"rows": len(records), "sha256": sha(ROOT / "data" / (split + ".jsonl")),
            "tokens": sum(item["tokens"] for item in stats),
            "supervised_tokens": sum(item["supervised_tokens"] for item in stats),
            "longest": max(stats, key=lambda item: item["tokens"]), "overlong_rows": 0}
    report = {"status": "passed", "mode": "CPU native Jinja + Rust tokenizer with production encode_record",
        "tokenizers_version": tokenizers.__version__, "model_weights_loaded": False, "gpu_used": False,
        "tokenizer_assets_identical_4b_9b": True, "assets_sha256": {name: sha(base / name) for name in assets},
        "maximum_sequence_length": 4096, "truncation": False, "counts": counts,
        "verified_ids": {"assistant_end_supervised": 248046, "tool_open_supervised": 248058, "tool_close_supervised": 248059,
            "im_start_masked": 248045, "empty_think_open_masked": 248068, "empty_think_close_masked": 248069},
        "checks": ["all prompt/system/schema/tool observation sentinels masked", "assistant answer and tool arguments supervised",
            "native assistant-end and paired tool delimiters supervised in every record", "empty thinking/header tokens masked",
            "overlong example rejected", "all frozen rows fit without truncation"],
        "limitation": "Independent backend-level check; official AutoTokenizer and trainer-environment preflight remains a separate check."}
    write_json(ROOT / "independent-token-mask-check.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
