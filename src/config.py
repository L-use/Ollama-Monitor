"""Configuration and path resolution.

Ollama Monitor keeps user data (database, settings, logs) OUTSIDE the
executable bundle so that updates / restarts never lose history.

When frozen (PyInstaller onefile):
  - app_root()      -> directory containing the .exe  (data/config/logs live here)
  - resource_root() -> the temporary bundle dir (sys._MEIPASS) holding web/ assets
When running from source:
  both point at the project root.
"""
from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path
from typing import Any

APP_NAME = "Ollama Monitor"
APP_VERSION = "1.0.0"

DEFAULT_SETTINGS = {
    "language": "zh-CN",
    "ollama_url": "http://127.0.0.1:11434",
    "listen_host": "0.0.0.0",
    "listen_port": 4000,
    "lan_access": True,
    "auto_open_browser": True,
    "hardware_refresh_seconds": 1.0,
    "history_retention_days": 0,  # 0 = keep forever
}

_lock = threading.Lock()


def app_root() -> Path:
    """Directory where writable runtime data lives (next to the exe)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_root() -> Path:
    """Directory holding bundled read-only assets (web/)."""
    if getattr(sys, "frozen", False):
        bundle = getattr(sys, "_MEIPASS", None)
        if bundle:
            return Path(bundle)
    return app_root()


def config_dir() -> Path:
    return app_root() / "config"


def data_dir() -> Path:
    return app_root() / "data"


def logs_dir() -> Path:
    return app_root() / "logs"


def db_path() -> Path:
    return data_dir() / "monitor.db"


def settings_path() -> Path:
    return config_dir() / "settings.json"


def web_dir() -> Path:
    return resource_root() / "web"


def ensure_dirs() -> None:
    for d in (config_dir(), data_dir(), logs_dir()):
        d.mkdir(parents=True, exist_ok=True)


class Settings:
    """Thread-safe in-memory settings backed by settings.json."""

    def __init__(self) -> None:
        self._data: dict = dict(DEFAULT_SETTINGS)
        self._load()

    def _load(self) -> None:
        ensure_dirs()
        p = settings_path()
        try:
            if p.exists():
                raw = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    # Only accept known keys; keep defaults for anything missing.
                    for k in DEFAULT_SETTINGS:
                        if k in raw:
                            self._data[k] = raw[k]
        except (OSError, json.JSONDecodeError):
            # Corrupt settings: fall back to defaults, never crash startup.
            pass

    def save(self) -> None:
        with _lock:
            ensure_dirs()
            tmp = settings_path().with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, settings_path())

    def get(self, key: str, default: Any = None):
        with _lock:
            if default is not None:
                return self._data.get(key, default)
            return self._data.get(key, DEFAULT_SETTINGS.get(key))

    def set(self, key: str, value) -> None:
        with _lock:
            self._data[key] = value

    def update(self, values: dict) -> None:
        with _lock:
            for k, v in values.items():
                if k in DEFAULT_SETTINGS:
                    self._data[k] = v

    def as_dict(self) -> dict:
        with _lock:
            return dict(self._data)


settings = Settings()
