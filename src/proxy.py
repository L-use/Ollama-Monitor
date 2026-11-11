"""Reverse proxy with transparent Ollama-API compatibility and token accounting.

Clients point at http://localhost:4000 (this server). Every request is
forwarded verbatim to Ollama at the configured upstream URL. For the
completion endpoints (/api/chat, /api/generate) the final statistics payload
(prompt_eval_count, eval_count, *_duration, ...) is captured and written to
the local database. The original request/response semantics are preserved:
- stream=false -> full JSON response returned as-is
- stream=true  -> NDJSON streamed back chunk-by-chunk, unchanged

Only requests that flow THROUGH this proxy are recorded; clients that talk to
Ollama directly on 11434 are invisible to the monitor.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Optional

import httpx

from .config import settings
from .db import Database

NS_PER_SEC = 1_000_000_000
NS_PER_MS = 1_000_000

COMPLETION_PATHS = ("/api/chat", "/api/generate", "/v1/chat/completions")

# Hop-by-hop headers that must never be forwarded upstream.
_HOP_BY_HOP = {
    "host", "connection", "keep-alive", "proxy-authenticate",
    "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade",
}


def _upstream_url(path: str) -> str:
    return settings.get("ollama_url").rstrip("/") + "/" + path.lstrip("/")


def _forward_headers(request) -> dict[str, str]:
    h = {}
    for k, v in request.headers.items():
        lk = k.lower()
        if lk in _HOP_BY_HOP or lk.startswith("proxy-"):
            continue
        if lk == "content-length":
            continue  # httpx sets this from the body
        h[k] = v
    return h


def _parse_body(body: bytes) -> tuple[Optional[str], bool, dict]:
    """Return (model, stream, json_obj) parsed from the request body."""
    model = None
    stream = False
    obj: dict = {}
    try:
        obj = json.loads(body) if body else {}
        if isinstance(obj, dict):
            model = obj.get("model")
            stream = bool(obj.get("stream", False))
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass
    return model, stream, obj


def _build_record(
    model: Optional[str],
    stream: bool,
    status: str,
    stats: Optional[dict],
    error: Optional[str],
    ttft_ms: Optional[float],
    client: Optional[str],
    total_ms: float,
    detail: Optional[dict] = None,
) -> dict:
    stats = stats or {}
    prompt_tokens = stats.get("prompt_eval_count")
    completion_tokens = stats.get("eval_count")
    total_tokens = None
    if prompt_tokens is not None or completion_tokens is not None:
        total_tokens = int(prompt_tokens or 0) + int(completion_tokens or 0)

    eval_ns = stats.get("eval_duration")
    tps = None

    # Fallback: OpenAI-compatible streams don't carry eval_duration. Estimate
    # generation time as (total wall-clock time - time-to-first-token), which
    # is a reasonable proxy for the "decoding" phase.
    if eval_ns is None and completion_tokens:
        if ttft_ms is not None and total_ms is not None:
            gen_ms = total_ms - ttft_ms
            if gen_ms > 0:
                eval_ns = int(gen_ms * NS_PER_MS)
                try:
                    tps = round(float(completion_tokens) / (gen_ms / 1000.0), 2)
                except (ZeroDivisionError, TypeError, ValueError):
                    tps = None
        elif total_ms is not None and total_ms > 0:
            try:
                tps = round(float(completion_tokens) / (total_ms / 1000.0), 2)
            except (ZeroDivisionError, TypeError, ValueError):
                tps = None
    elif completion_tokens and eval_ns:
        try:
            tps = round(float(completion_tokens) / (float(eval_ns) / NS_PER_SEC), 2)
        except (ZeroDivisionError, TypeError, ValueError):
            tps = None

    # Server-side time-to-first-token (fallback when client timing unavailable):
    if ttft_ms is None:
        load_ns = stats.get("load_duration")
        prompt_ns = stats.get("prompt_eval_duration")
        if load_ns is not None or prompt_ns is not None:
            ttft_ms = round(((load_ns or 0) + (prompt_ns or 0)) / NS_PER_MS, 1)

    return {
        "created_at": time.time(),
        "model": model,
        "stream": stream,
        "status": status,
        "prompt_tokens": int(prompt_tokens) if prompt_tokens is not None else 0,
        "completion_tokens": int(completion_tokens) if completion_tokens is not None else 0,
        "total_tokens": int(total_tokens) if total_tokens is not None else 0,
        "prompt_eval_duration_ns": stats.get("prompt_eval_duration"),
        "eval_duration_ns": eval_ns,
        "total_duration_ns": stats.get("total_duration"),
        "load_duration_ns": stats.get("load_duration"),
        "tokens_per_sec": tps,
        "time_to_first_token_ms": ttft_ms,
        "error": error,
        "client": client,
        "detail": {
            **(detail or {}),
            "total_ms": round(total_ms, 1),
            "done_reason": stats.get("done_reason"),
        },
    }


def _extract_done_stats(obj: Any) -> Optional[dict]:
    """Normalize a completion response into Ollama-style stat fields.

    Handles the native Ollama shape (done + eval_count/prompt_eval_count) and
    the OpenAI-compatible shape (choices[] + usage{prompt_tokens,
    completion_tokens}). Returns None when no usable stats are present.
    """
    if not isinstance(obj, dict):
        return None
    # Native Ollama final object.
    if obj.get("done") is True:
        return obj
    # OpenAI-compatible: usage block, with/without a streaming chunk layout.
    usage = obj.get("usage")
    if isinstance(usage, dict):
        return {
            "prompt_eval_count": usage.get("prompt_tokens"),
            "eval_count": usage.get("completion_tokens"),
            "total_duration": _to_ns(usage.get("total_duration_ns"), usage.get("total_duration")),
            "eval_duration": _to_ns(usage.get("eval_duration_ns"), usage.get("eval_duration")),
            "load_duration": _to_ns(usage.get("load_duration_ns"), usage.get("load_duration")),
            "prompt_eval_duration": _to_ns(usage.get("prompt_eval_duration_ns"), usage.get("prompt_eval_duration")),
        }
    # Bare Ollama counts (some clients/versions omit the "done": true frame but
    # still attach eval counts to the last object).
    if obj.get("eval_count") is not None or obj.get("prompt_eval_count") is not None:
        return obj
    return None


def _to_ns(ns_value, seconds_value):
    """Pick a nanosecond figure from either a *_ns or a seconds field."""
    if ns_value is not None:
        try:
            return int(float(ns_value))
        except (TypeError, ValueError):
            return None
    if seconds_value is not None:
        try:
            return int(float(seconds_value) * NS_PER_SEC)
        except (TypeError, ValueError):
            return None
    return None


class Proxy:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._client: Optional[httpx.AsyncClient] = None

    async def start(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(300.0, connect=10.0), follow_redirects=False
        )

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _client_or_raise(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("proxy not started")
        return self._client

    async def forward(
        self,
        method: str,
        path: str,
        body: bytes,
        headers: dict,
        client_hint: Optional[str],
    ):
        """Returns a dict describing the outcome. Used by the route handlers."""
        is_completion = path.rstrip("/") in COMPLETION_PATHS and method.upper() == "POST"
        model, stream, _obj = _parse_body(body)
        client = _client_hint(headers, client_hint)

        if not is_completion:
            # Pure passthrough (tags, ps, version, pull, embed, ...) — no stats.
            return await self._passthrough(method, path, body, headers)

        return await self._forward_completion(
            method, path, body, headers, model, stream, client
        )

    async def _passthrough(self, method, path, body, headers) -> dict:
        client = self._client_or_raise()
        try:
            resp = await client.request(
                method, _upstream_url(path), content=body, headers=headers
            )
        except httpx.HTTPError as exc:
            return {
                "status_code": 502,
                "headers": {"content-type": "application/json"},
                "body": json.dumps({"error": f"Ollama unreachable: {exc.__class__.__name__}"}).encode(),
            }
        return {
            "status_code": resp.status_code,
            "headers": {"content-type": resp.headers.get("content-type", "application/json")},
            "body": resp.content,
        }

    async def _forward_completion(self, method, path, body, headers, model, stream, client) -> dict:
        client_http = self._client_or_raise()
        target = _upstream_url(path)
        start = time.monotonic()

        if stream:
            return await self._stream_completion(client_http, method, target, body, headers, model, client, start)

        # ---- non-streaming -------------------------------------------------
        try:
            resp = await client_http.request(method, target, content=body, headers=headers)
        except httpx.HTTPError as exc:
            err = f"Ollama unreachable: {exc.__class__.__name__}"
            self.db.insert_request(
                _build_record(model, False, "error", None, err, None, client, (time.monotonic() - start) * 1000)
            )
            return {
                "status_code": 502,
                "headers": {"content-type": "application/json"},
                "body": json.dumps({"error": err}).encode(),
            }

        data = resp.content
        if resp.status_code == 200:
            stats = None
            try:
                obj = json.loads(data)
                stats = _extract_done_stats(obj)
            except (json.JSONDecodeError, UnicodeDecodeError):
                stats = None
            status = "success" if stats is not None else "error"
            error = None if stats is not None else "response did not contain final statistics"
            self.db.insert_request(
                _build_record(model, False, status, stats, error, None, client, (time.monotonic() - start) * 1000)
            )
        else:
            self.db.insert_request(
                _build_record(
                    model, False, "error", None, f"HTTP {resp.status_code}", None,
                    client, (time.monotonic() - start) * 1000,
                )
            )

        return {
            "status_code": resp.status_code,
            "headers": {"content-type": resp.headers.get("content-type", "application/json")},
            "body": data,
        }

    async def _stream_completion(self, client_http, method, target, body, headers, model, client, start) -> dict:
        req = client_http.build_request(method, target, content=body, headers=headers)
        try:
            resp = await client_http.send(req, stream=True)
        except httpx.HTTPError as exc:
            err = f"Ollama unreachable: {exc.__class__.__name__}"
            self.db.insert_request(
                _build_record(model, True, "error", None, err, None, client, (time.monotonic() - start) * 1000)
            )
            return {
                "status_code": 502,
                "headers": {"content-type": "application/json"},
                "body": json.dumps({"error": err}).encode(),
            }

        buffer = bytearray()
        ttft_ms: Optional[float] = None
        first = True
        final_stats: Optional[dict] = None
        interrupted = False

        async def gen():
            nonlocal ttft_ms, first, final_stats, interrupted
            try:
                async for chunk in resp.aiter_raw():
                    if first and chunk:
                        ttft_ms = (time.monotonic() - start) * 1000
                        first = False
                    buffer.extend(chunk)
                    yield chunk
                # Stream completed cleanly.
                final_stats = self._parse_ndjson_done(bytes(buffer))
            except (asyncio.CancelledError, GeneratorExit):
                # Client disconnected / response task cancelled mid-stream.
                interrupted = True
                raise
            except Exception:
                interrupted = True
                raise
            finally:
                status = "interrupted" if interrupted else ("success" if final_stats else "error")
                error = None
                if interrupted:
                    error = "stream interrupted (client disconnected)"
                elif final_stats is None:
                    error = "no final statistics in stream"
                self.db.insert_request(
                    _build_record(model, True, status, final_stats, error, ttft_ms, client, (time.monotonic() - start) * 1000)
                )

        return {
            "status_code": resp.status_code,
            "headers": {"content-type": resp.headers.get("content-type", "application/x-ndjson")},
            "stream": gen(),
        }

    @staticmethod
    def _parse_ndjson_done(data: bytes) -> Optional[dict]:
        """Extract final statistics from a streamed completion response.

        Understands three wire formats:
          1. NDJSON (native /api/chat, /api/generate stream) — one JSON object
             per line; the final object has "done": true.
          2. SSE (OpenAI-compatible /v1/chat/completions stream) — lines are
             "data: {...}" (or "data: [DONE]"); the last real chunk carries the
             "usage" block.
          3. A bare JSON object with a "usage" block.

        Returns a dict normalized to Ollama-style stat fields, or None.
        """
        text = data.decode("utf-8", errors="replace")
        last_obj: Optional[dict] = None

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            obj = None
            # SSE frame: "data: {...}" or "data: [DONE]"
            if line.startswith("data:"):
                payload = line[len("data:"):].strip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    obj = json.loads(payload)
                except json.JSONDecodeError:
                    continue
            else:
                # NDJSON: bare JSON object per line.
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

            if not isinstance(obj, dict):
                continue
            last_obj = obj

            # Native Ollama final frame.
            if obj.get("done") is True:
                stats = _extract_done_stats(obj)
                if stats is not None:
                    return stats

        # Fall back to the last seen object if it carries usable stats
        # (covers endpoints/versions that omit an explicit "done" frame but
        # still attach counts or a "usage" block to the final chunk).
        if isinstance(last_obj, dict):
            stats = _extract_done_stats(last_obj)
            if stats is not None:
                return stats
        return None


def _client_hint(headers: dict, fallback: Optional[str]) -> Optional[str]:
    ua = headers.get("user-agent") or headers.get("User-Agent")
    if ua:
        return ua[:120]
    return fallback
