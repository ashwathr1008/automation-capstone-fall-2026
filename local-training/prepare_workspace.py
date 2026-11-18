"""Initialize local profile files from tracked templates without replacing user settings."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent
DEFAULT_BENCHMARK = WORKSPACE / "benchmark-results/local-comparison"


def initialize(benchmark_dir=DEFAULT_BENCHMARK, app_profiles=None):
    benchmark_dir = Path(benchmark_dir).resolve()
    if not benchmark_dir.is_relative_to(WORKSPACE / "benchmark-results"):
        raise ValueError("Benchmark configuration must stay under benchmark-results/")
    app_profiles = Path(app_profiles).resolve() if app_profiles else WORKSPACE / "research-data/model_profiles.json"
    sources = [(ROOT / "profiles.example.json", benchmark_dir / "profiles.json"),
               (ROOT / "analysis-configurations.example.json", benchmark_dir / "analysis-configurations.json")]
    if app_profiles.parent.is_dir():
        sources.append((WORKSPACE / "platform/model_profiles.example.json", app_profiles))
    results = []
    for source, target in sources:
        if target.exists():
            results.append({"path": str(target), "status": "preserved_existing"})
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(source.read_bytes())
        results.append({"path": str(target), "status": "created_from_template"})
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark-dir", type=Path, default=DEFAULT_BENCHMARK)
    parser.add_argument("--app-profiles", type=Path, help="Existing workspace directory plus model_profiles.json")
    args = parser.parse_args(argv)
    print(json.dumps({"files": initialize(args.benchmark_dir, args.app_profiles),
                     "note": "No models, credentials, training data or research database are created. Restore a research workspace first to install its optional app profiles."}, indent=2))


if __name__ == "__main__":
    main()
