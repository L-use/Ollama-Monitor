# Third-Party Notices

Ollama Monitor bundles or depends on the following open-source components.
Each is distributed under its own license; full license texts are available
at the linked upstream repositories.

## Python runtime dependencies

| Package      | Version (tested) | License                    | Purpose                     |
|--------------|------------------|----------------------------|-----------------------------|
| fastapi      | 0.162.3          | MIT                        | Web framework / API         |
| uvicorn      | 0.54.0           | BSD-3-Clause               | ASGI server                 |
| httpx        | 0.28.1           | BSD-3-Clause               | Async HTTP client (proxy)   |
| pyinstaller  | 6.22.3           | GPL-2.0 + bootloader exception | EXE packaging (build-time only) |

These packages are Python modules pulled in at runtime/build time. They are
NOT vendored into this repository; they are installed from PyPI via
`requirements.txt`. The EXE produced by PyInstaller embeds fastapi/uvicorn/httpx
and their transitive dependencies (starlette, pydantic, anyio, h11, sniffio,
idna, certifi, etc.), each under its respective permissive license.

## Bundled front-end assets

| Asset      | Version | License | Purpose            |
|------------|---------|---------|--------------------|
| Chart.js   | 4.4.9   | MIT     | Dashboard charts   |

Chart.js is bundled as `web/lib/chart.umd.js` so the dashboard works fully
offline (no CDN). It is Copyright the Chart.js contributors and licensed MIT.

## System tools (not bundled, detected at runtime)

- nvidia-smi — NVIDIA driver utility, used read-only to query GPU telemetry.
- Windows system libraries (kernel32) — accessed via ctypes for CPU/memory.

No user data is collected, transmitted, or shared with any third party by this
application.
