"""Run from a source checkout without installation or a virtual environment."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from lanm_platform.server import main

if __name__ == "__main__":
    main()
