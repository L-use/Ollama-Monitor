"""Ollama Monitor entry point.

- single-instance guard (lock file + PID liveness)
- explicit port-conflict check (never silently switches ports)
- starts the FastAPI server, opens the browser, logs to logs/
- releases the lock and the port cleanly on shutdown
"""
from __future__ import annotations

import ctypes
import logging
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

from src.app import app
from src.config import (
    APP_NAME,
    APP_VERSION,
    ensure_dirs,
    logs_dir,
    data_dir,
    settings,
)

logger = logging.getLogger("ollama-monitor")


def _setup_logging() -> None:
    ensure_dirs()
    log_file = logs_dir() / "ollama-monitor.log"
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root.addHandler(sh)


def _show_error(title: str, message: str) -> None:
    print(f"\n[{title}]\n{message}\n", file=sys.stderr)
    try:
        ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)  # MB_ICONERROR
    except Exception:
        pass


def _pid_alive(pid: int) -> bool:
    """True if a process with this PID exists and is still active."""
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return False
    code = ctypes.c_ulong()
    ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(h)
    return bool(ok) and code.value == STILL_ACTIVE


def _acquire_lock():
    lockfile = data_dir() / ".lock"
    if lockfile.exists():
        try:
            pid = int(lockfile.read_text().strip())
            if pid != os.getpid() and _pid_alive(pid):
                return None, (
                    f"Another instance of {APP_NAME} is already running (PID {pid}).\n"
                    "Please close it before starting a new one."
                )
        except (ValueError, OSError):
            pass
    lockfile.write_text(str(os.getpid()), encoding="utf-8")
    return lockfile, None


def _release_lock(lockfile) -> None:
    try:
        if lockfile is not None and lockfile.exists():
            lockfile.unlink()
    except OSError:
        pass


def _port_in_use(host: str, port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((host, port))
    except OSError:
        return True
    finally:
        s.close()
    return False


def _open_browser(url: str) -> None:
    time.sleep(1.2)
    try:
        webbrowser.open(url)
    except Exception as exc:  # pragma: no cover
        logger.warning("Could not open browser: %s", exc)


def main() -> int:
    _setup_logging()
    ensure_dirs()

    lockfile, lock_err = _acquire_lock()
    if lock_err:
        _show_error(APP_NAME, lock_err)
        return 1

    host = str(settings.get("listen_host") or "127.0.0.1")
    port = int(settings.get("listen_port") or 4000)
    if settings.get("lan_access"):
        host = "0.0.0.0"

    # Prevent a proxy loop: refuse to start if the Ollama upstream points back
    # at this very server (same loopback address + same port).
    try:
        up = urlparse(str(settings.get("ollama_url") or ""))
        if up.port == port and (up.hostname or "") in ("127.0.0.1", "localhost", "0.0.0.0"):
            _show_error(
                APP_NAME,
                "Configuration error: ollama_url points to the monitor's own "
                f"port ({up.hostname}:{up.port}).\n\nThis would cause a proxy loop.\n"
                "Fix 'ollama_url' in config/settings.json and restart.",
            )
            _release_lock(lockfile)
            return 1
    except ValueError:
        pass

    if _port_in_use(host, port):
        _show_error(
            APP_NAME,
            f"Port {port} is already in use on {host}.\n\n"
            "Ollama Monitor will NOT switch ports automatically.\n"
            "Close the program using this port and try again.",
        )
        _release_lock(lockfile)
        return 1

    display_host = "127.0.0.1" if host == "0.0.0.0" else host
    url = f"http://{display_host}:{port}"

    print(f"\n{'=' * 56}")
    print(f"  {APP_NAME} v{APP_VERSION}")
    print(f"  Dashboard:  {url}")
    print(f"  Proxy:      {url}  ->  Ollama ({settings.get('ollama_url')})")
    print(f"  Log file:   {logs_dir() / 'ollama-monitor.log'}")
    print(f"{'=' * 56}\n")
    print("Press Ctrl+C to stop.\n")

    logger.info("Starting %s v%s on %s:%s", APP_NAME, APP_VERSION, host, port)

    if settings.get("auto_open_browser", True):
        threading.Thread(target=_open_browser, args=(url,), daemon=True).start()

    import uvicorn

    try:
        uvicorn.run(
            app,
            host=host,
            port=port,
            access_log=False,
            log_config=None,
            log_level="info",
        )
    except KeyboardInterrupt:
        logger.info("Shutdown requested.")
    except Exception as exc:
        logger.exception("Fatal error: %s", exc)
        _show_error(APP_NAME, f"Failed to start server:\n{exc}")
        _release_lock(lockfile)
        return 1
    finally:
        _release_lock(lockfile)

    logger.info("Stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
