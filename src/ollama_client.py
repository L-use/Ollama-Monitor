"""Direct Ollama API client (used by the monitor's own status endpoints).

This talks to Ollama directly at the configured URL — it does NOT go through
the proxy — so the dashboard can report Ollama status even while client
requests flow through the proxy.
"""
from __future__ import annotations

import time
from typing import Any, Optional

import httpx

from .config import settings


def _base() -> str:
    return settings.get("ollama_url").rstrip("/")


async def _get_json(path: str, timeout: float = 5.0) -> Any:
    url = f"{_base()}{path}"
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


def _fmt_bytes(n: Optional[int]) -> Optional[str]:
    if n is None:
        return None
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


async def version() -> dict:
    """Return Ollama's version payload. Raises on connection failure."""
    return await _get_json("/api/version")


async def status() -> dict:
    """Return {online, version, installed:[...], running:[...]}."""
    out: dict[str, Any] = {"online": False, "version": None, "installed": [], "running": []}
    try:
        v = await version()
        out["version"] = v.get("version")
        if out["version"] is None:
            return out  # reachable but no version -> treat as offline
        out["online"] = True
    except Exception:
        return out

    try:
        tags = await _get_json("/api/tags")
        for m in tags.get("models", []):
            d = m.get("details", {})
            out["installed"].append(
                {
                    "name": m.get("name"),
                    "parameter_size": d.get("parameter_size"),
                    "quantization_level": d.get("quantization_level"),
                    "format": d.get("format"),
                    "family": d.get("family"),
                    "context_length": d.get("context_length"),
                    "size": m.get("size"),
                    "size_human": _fmt_bytes(m.get("size")),
                    "modified_at": m.get("modified_at"),
                }
            )
    except Exception:
        out["installed"] = []

    try:
        ps = await _get_json("/api/ps")
        now = time.time()
        for m in ps.get("models", []):
            d = m.get("details", {})
            expires_at = m.get("expires_at")
            running_for = None
            if expires_at:
                # expires_at is an ISO-8601 string with a timezone offset
                # (e.g. "2026-11-10T07:53:30.0220407-08:00"). Parse it properly
                # instead of float()-casting (which raises and empties the list).
                try:
                    import datetime
                    ts = datetime.datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                    expires_epoch = ts.timestamp()
                    # Ollama's /api/ps does not expose the model's load start time.
                    # expires_at is the "last activity + keep_alive" deadline, so
                    # report how long ago the model was last active as a proxy for
                    # uptime (always >= 0; active models produce small values).
                    running_for = max(0.0, expires_epoch - now)
                except (ValueError, AttributeError):
                    running_for = None
            out["running"].append(
                {
                    "name": m.get("name"),
                    "model": m.get("model"),
                    "size": m.get("size"),
                    "size_human": _fmt_bytes(m.get("size")),
                    "size_vram": m.get("size_vram"),
                    "size_vram_human": _fmt_bytes(m.get("size_vram")),
                    "parameter_size": d.get("parameter_size"),
                    "quantization_level": d.get("quantization_level"),
                    "context_length": d.get("context_length"),
                    "family": d.get("family"),
                    "running_for_seconds": running_for,
                    "expires_at": expires_at,
                }
            )
    except Exception:
        out["running"] = []

    return out


async def list_models() -> list[dict]:
    try:
        tags = await _get_json("/api/tags")
        return [m.get("name") for m in tags.get("models", [])]
    except Exception:
        return []
