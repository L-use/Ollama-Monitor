"""One-shot Windows build: bundles Ollama Monitor into a single EXE.

Usage (from project root, inside the virtualenv):
    python scripts/build.py

Output: dist/OllamaMonitor.exe
"""
import sys
from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    args = [
        str(ROOT / "src" / "main.py"),
        "--name", "OllamaMonitor",
        "--onefile",
        "--console",
        "--clean",
        "--noconfirm",
        "--paths", str(ROOT),
        # Bundle the web UI (html/css/js/locales/chart.js) into the exe.
        "--add-data", f"{ROOT / 'web'};web",
    ]
    PyInstaller.__main__.run(args)
    exe = ROOT / "dist" / "OllamaMonitor.exe"
    if exe.exists():
        print(f"\nBUILD OK -> {exe}")
        return 0
    print("\nBUILD FAILED: dist/OllamaMonitor.exe not produced.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
