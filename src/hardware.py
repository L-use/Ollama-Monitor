"""Hardware monitoring.

GPU  -> nvidia-smi (no third-party software required).
CPU  -> Windows GetSystemTimes via ctypes (stdlib only).
RAM  -> Windows GlobalMemoryStatusEx via ctypes (stdlib only).

Any metric that cannot be read is reported as None (rendered "N/A"),
never fabricated.
"""
from __future__ import annotations

import ctypes
import subprocess
import threading
import time
from ctypes import wintypes

# ---- Windows memory -----------------------------------------------------

class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_uint64),
        ("ullAvailPhys", ctypes.c_uint64),
        ("ullTotalPageFile", ctypes.c_uint64),
        ("ullAvailPageFile", ctypes.c_uint64),
        ("ullTotalVirtual", ctypes.c_uint64),
        ("ullAvailVirtual", ctypes.c_uint64),
        ("ullAvailExtendedVirtual", ctypes.c_uint64),
    ]


def _mem_status() -> MEMORYSTATUSEX:
    m = MEMORYSTATUSEX()
    m.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
        raise OSError("GlobalMemoryStatusEx failed")
    return m


def sample_memory() -> dict:
    m = _mem_status()
    total = int(m.ullTotalPhys)
    used = int(m.ullTotalPhys - m.ullAvailPhys)
    return {
        "total_bytes": total,
        "used_bytes": used,
        "available_bytes": int(m.ullAvailPhys),
        "percent": round(float(m.dwMemoryLoad), 1),
    }


# ---- Windows CPU --------------------------------------------------------

class FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


_last_cpu = {"idle": None, "total": None}
_cpu_lock = threading.Lock()


def _get_system_times():
    idle = FILETIME()
    kernel = FILETIME()
    user = FILETIME()
    ok = ctypes.windll.kernel32.GetSystemTimes(
        ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
    )
    if not ok:
        raise OSError("GetSystemTimes failed")
    def to64(ft: FILETIME) -> int:
        return (ft.dwHighDateTime << 32) | ft.dwLowDateTime
    idle64 = to64(idle)
    total64 = to64(kernel) + to64(user)
    return idle64, total64


def sample_cpu() -> float:
    """CPU usage percent since the previous call (first call returns 0.0)."""
    with _cpu_lock:
        idle, total = _get_system_times()
        prev_idle, prev_total = _last_cpu["idle"], _last_cpu["total"]
        _last_cpu["idle"], _last_cpu["total"] = idle, total
        if prev_idle is None or prev_total is None:
            return 0.0
        d_total = total - prev_total
        d_idle = idle - prev_idle
        if d_total <= 0:
            return 0.0
        return round(max(0.0, min(100.0, 100.0 * (1.0 - d_idle / d_total))), 1)


# ---- NVIDIA GPU ---------------------------------------------------------

_NVSMI = "nvidia-smi"
_gpu_lock = threading.Lock()
_gpu_cache = {"ts": 0.0, "data": None}
GPU_CACHE_TTL = 1.0


def _num(value: str):
    """Parse a numeric field; return None for 'N/A', '[N/A]', empty, etc."""
    if value is None:
        return None
    s = value.strip().strip("[]").strip()
    if not s or s.upper() in ("N/A", "NA", "NONE", "NOT SUPPORTED", "ERR"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def sample_gpu(refresh: bool = False) -> dict:
    """Query nvidia-smi (cached briefly). Returns dict of possibly-None values."""
    now = time.time()
    if not refresh and _gpu_cache["data"] is not None and (now - _gpu_cache["ts"]) < GPU_CACHE_TTL:
        return _gpu_cache["data"]

    with _gpu_lock:
        if not refresh and _gpu_cache["data"] is not None and (now - _gpu_cache["ts"]) < GPU_CACHE_TTL:
            return _gpu_cache["data"]
        data = _query_gpu()
        _gpu_cache["ts"] = time.time()
        _gpu_cache["data"] = data
        return data


def _query_gpu() -> dict:
    result: dict = {
        "name": None,
        "util": None,
        "mem_total": None,
        "mem_used": None,
        "mem_free": None,
        "temp": None,
        "power": None,
        "available": False,
    }
    query = (
        "name,utilization.gpu,memory.total,memory.used,memory.free,"
        "temperature.gpu,power.draw"
    )
    try:
        out = subprocess.run(
            [_NVSMI, f"--query-gpu={query}", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError:
        return result  # nvidia-smi not on PATH
    except Exception:
        return result

    if out.returncode != 0:
        return result

    line = out.stdout.strip().splitlines()[0] if out.stdout.strip() else ""
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < 7:
        return result

    result["available"] = True
    result["name"] = parts[0] or None
    result["util"] = _num(parts[1])
    result["mem_total"] = _num(parts[2])
    result["mem_used"] = _num(parts[3])
    result["mem_free"] = _num(parts[4])
    result["temp"] = _num(parts[5])
    result["power"] = _num(parts[6])
    return result


def sample_all() -> dict:
    """One combined hardware snapshot (cached GPU, fresh CPU/RAM)."""
    gpu = sample_gpu()
    return {
        "ts": time.time(),
        "gpu": gpu,
        "cpu_util": sample_cpu(),
        "memory": sample_memory(),
    }
