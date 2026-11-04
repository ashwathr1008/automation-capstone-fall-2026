"""Location and runtime settings. Live research data is excluded from Git."""
from pathlib import Path
import os
import shutil
import sysconfig

ROOT = Path(__file__).resolve().parents[2]
SOURCE_EVIDENCE = Path(__file__).resolve().parent / "data" / "source-evidence.zip"
UI_DIRECTORY = ROOT / "ui"
if not UI_DIRECTORY.is_dir():
    UI_DIRECTORY = Path(sysconfig.get_path("data")) / "share" / "lanm-platform" / "ui"

def data_directory():
    explicit = os.environ.get("LANM_DATA_DIR")
    if explicit:
        return Path(explicit).expanduser().resolve()
    if (ROOT / "pyproject.toml").is_file() and (ROOT / "ui").is_dir():
        return ROOT.parent / "research-data"
    user = Path(os.environ.get("USERPROFILE") or Path.home())
    return user / "ResearchData" / "LanMPlatform"

def source_archive(data_dir):
    """Prefer existing local archives, then use the bundled source evidence."""
    data_dir = Path(data_dir)
    for archive in (data_dir / "legacy" / "weeks1-3.zip",
                    data_dir.parent / "archive" / "weeks1-3.zip"):
        if archive.is_file():
            return archive
    return SOURCE_EVIDENCE

def codex_binary():
    explicit = os.environ.get("LANM_CODEX_BINARY")
    if explicit:
        return explicit
    found = shutil.which("codex")
    if found:
        return found
    user = Path(os.environ.get("USERPROFILE") or Path.home())
    candidates = sorted((user / ".vscode" / "extensions").glob("openai.chatgpt-*/bin/windows-x86_64/codex.exe"))
    return str(candidates[-1]) if candidates else "codex"

DEFAULT_MODEL = os.environ.get("LANM_MODEL", "gpt-6.1-sol")
