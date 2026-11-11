"""Assemble the distributable ZIP from the freshly built EXE.

Produces: package/Ollama-Monitor-Windows-x64.zip
Containing the folder Ollama-Monitor/ with the EXE + config + empty data/logs
+ README.txt + LICENSE.txt.
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
PACKAGE = ROOT / "package"
STAGING = PACKAGE / "Ollama-Monitor"


def main() -> int:
    exe = DIST / "OllamaMonitor.exe"
    if not exe.exists():
        print("ERROR: dist/OllamaMonitor.exe not found. Run scripts/build.py first.", file=sys.stderr)
        return 1

    if STAGING.exists():
        shutil.rmtree(STAGING)
    (STAGING / "config").mkdir(parents=True)
    (STAGING / "data").mkdir()
    (STAGING / "logs").mkdir()

    shutil.copy2(exe, STAGING / "OllamaMonitor.exe")
    shutil.copy2(ROOT / "config" / "settings.json", STAGING / "config" / "settings.json")
    shutil.copy2(ROOT / "README.txt", STAGING / "README.txt")
    shutil.copy2(ROOT / "LICENSE.txt", STAGING / "LICENSE.txt")

    out_base = PACKAGE / "Ollama-Monitor-Windows-x64"
    if out_base.with_suffix(".zip").exists():
        out_base.with_suffix(".zip").unlink()
    shutil.make_archive(str(out_base), "zip", root_dir=str(PACKAGE), base_dir="Ollama-Monitor")

    z = out_base.with_suffix(".zip")
    print(f"ZIP OK -> {z}")
    print(f"Size: {z.stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
