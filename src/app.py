"""FastAPI application: dashboard API + Ollama reverse proxy + static UI."""
from __future__ import annotations

import asyncio
import csv
import io
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from . import hardware as hw
from . import ollama_client as oc
from .config import settings, web_dir, db_path
from .db import Database
from .proxy import Proxy

LATEST_HARDWARE: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = app.state.db
    proxy = app.state.proxy
    await proxy.start()
    task = asyncio.create_task(_sampler_loop(db))
    app.state.sampler = task
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await proxy.stop()
        db.flush()
        db.close()


async def _sampler_loop(db: Database) -> None:
    last_prune = 0.0
    while True:
        interval = float(settings.get("hardware_refresh_seconds") or 1.0)
        try:
            snap = await asyncio.to_thread(hw.sample_all)
            LATEST_HARDWARE.update(snap)
            g = snap["gpu"]
            m = snap["memory"]
            db.insert_hardware(
                {
                    "created_at": snap["ts"],
                    "gpu_util": g.get("util"),
                    "gpu_mem_used": g.get("mem_used"),
                    "gpu_mem_total": g.get("mem_total"),
                    "gpu_temp": g.get("temp"),
                    "gpu_power": g.get("power"),
                    "cpu_util": snap.get("cpu_util"),
                    "mem_total": m.get("total_bytes"),
                    "mem_used": m.get("used_bytes"),
                }
            )
            # Retention pruning (only when configured), every 5 minutes.
            if time.time() - last_prune > 300:
                last_prune = time.time()
                db.prune_old(int(settings.get("history_retention_days") or 0))
        except Exception:
            pass
        await asyncio.sleep(interval)


def create_app() -> FastAPI:
    db = Database(db_path())
    proxy = Proxy(db)

    app = FastAPI(title="Ollama Monitor", version=__version__, lifespan=lifespan)
    app.state.db = db
    app.state.proxy = proxy

    # ---------------------------------------------------------------- monitor API
    @app.get("/api/monitor/status")
    async def monitor_status():
        return await oc.status()

    @app.get("/api/monitor/hardware")
    async def monitor_hardware():
        snap = await asyncio.to_thread(hw.sample_all)
        LATEST_HARDWARE.update(snap)
        return snap

    @app.get("/api/monitor/hardware/history")
    async def monitor_hardware_history(minutes: int = 30):
        minutes = max(1, min(int(minutes), 24 * 60))
        rows = db.recent_hardware(seconds=minutes * 60)
        return {"samples": rows}

    @app.get("/api/monitor/stats")
    async def monitor_stats():
        s = db.summary()
        latest = db.latest_success()
        s["avg_tps"] = db.avg_tps()
        s["latest_tps"] = latest["tokens_per_sec"] if latest else None
        s["per_model"] = db.per_model()
        s["daily"] = db.daily()
        return s

    @app.get("/api/monitor/requests")
    async def monitor_requests(
        model: Optional[str] = None,
        date: Optional[str] = None,
        q: Optional[str] = None,
        page: int = 1,
        limit: int = 20,
    ):
        page = max(1, page)
        limit = max(1, min(limit, 200))
        return db.list_requests(model=model, date=date, q=q, page=page, limit=limit)

    @app.delete("/api/monitor/requests")
    async def monitor_clear_requests():
        n = db.clear_requests()
        return {"deleted": n}

    @app.get("/api/monitor/requests/{rid}")
    async def monitor_request_detail(rid: int):
        row = db.get_request(rid)
        if row is None:
            return Response(status_code=404, content='{"error":"not found"}',
                            media_type="application/json")
        return row

    @app.get("/api/monitor/models")
    async def monitor_models():
        return {"models": db.distinct_models()}

    @app.get("/api/monitor/export.csv")
    async def monitor_export():
        rows = db.list_requests(limit=100000, page=1)["items"]
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(
            [
                "id", "time", "model", "stream", "status",
                "prompt_tokens", "completion_tokens", "total_tokens",
                "tokens_per_sec", "total_duration_ns", "eval_duration_ns",
                "load_duration_ns", "time_to_first_token_ms", "error", "client",
            ]
        )
        for r in rows:
            w.writerow(
                [
                    r["id"],
                    time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["created_at"])),
                    r["model"],
                    bool(r["stream"]),
                    r["status"],
                    r["prompt_tokens"],
                    r["completion_tokens"],
                    r["total_tokens"],
                    r["tokens_per_sec"],
                    r["total_duration_ns"],
                    r["eval_duration_ns"],
                    r["load_duration_ns"],
                    r["time_to_first_token_ms"],
                    r["error"],
                    r["client"],
                ]
            )
        csv_text = buf.getvalue()
        return Response(
            content=csv_text,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=ollama-monitor-export.csv"},
        )

    @app.get("/api/settings")
    async def get_settings():
        return settings.as_dict()

    @app.post("/api/settings")
    async def post_settings(request: Request):
        try:
            payload = await request.json()
        except Exception:
            return Response(status_code=400, content='{"error":"invalid json"}',
                            media_type="application/json")
        changed = {}
        for k, v in payload.items():
            if k in ("language", "auto_open_browser"):
                settings.set(k, v)
                changed[k] = v
            elif k == "lan_access":
                settings.set(k, bool(v))
                changed[k] = bool(v)
        settings.save()
        return {"ok": True, "changed": changed, "settings": settings.as_dict()}

    # ---------------------------------------------------------------- Ollama proxy
    @app.api_route(
        "/api/{path:path}",
        methods=["GET", "POST", "DELETE", "PUT", "PATCH", "OPTIONS", "HEAD"],
    )
    async def proxy_route(request: Request, path: str):
        body = await request.body()
        headers = proxy_hdrs(request)
        client_hint = request.client.host if request.client else None
        result = await proxy.forward(
            request.method, f"/api/{path}", body, headers, client_hint
        )
        if "stream" in result:
            return StreamingResponse(
                result["stream"],
                status_code=result["status_code"],
                headers=result["headers"],
                media_type=result["headers"].get("content-type"),
            )
        return Response(
            content=result["body"],
            status_code=result["status_code"],
            headers=result["headers"],
            media_type=result["headers"].get("content-type"),
        )

    # OpenAI-compatible passthrough (/v1/models, /v1/chat/completions, ...).
    @app.api_route(
        "/v1/{path:path}",
        methods=["GET", "POST", "DELETE", "PUT", "PATCH", "OPTIONS", "HEAD"],
    )
    async def proxy_route_v1(request: Request, path: str):
        body = await request.body()
        headers = proxy_hdrs(request)
        client_hint = request.client.host if request.client else None
        result = await proxy.forward(
            request.method, f"/v1/{path}", body, headers, client_hint
        )
        if "stream" in result:
            return StreamingResponse(
                result["stream"],
                status_code=result["status_code"],
                headers=result["headers"],
                media_type=result["headers"].get("content-type"),
            )
        return Response(
            content=result["body"],
            status_code=result["status_code"],
            headers=result["headers"],
            media_type=result["headers"].get("content-type"),
        )

    # ---------------------------------------------------------------- static UI
    app.mount("/", StaticFiles(directory=str(web_dir()), html=True), name="ui")

    return app


def proxy_hdrs(request: Request) -> dict:
    from .proxy import _forward_headers
    return _forward_headers(request)


app = create_app()
