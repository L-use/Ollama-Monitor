# Ollama Monitor

一个开源的 Windows 本地模型监控系统，用于监控通过 [Ollama](https://ollama.com) 部署和运行的本地大语言模型。

轻量、离线、零依赖部署：解压 ZIP 后双击 `OllamaMonitor.exe` 即可启动，自动打开浏览器访问 `http://localhost:4000`。不依赖 Grafana / Prometheus / Docker，不需要安装 Python 或 Node.js。

---

## ✨ 功能

- **模型状态监控**：Ollama 在线/离线、已安装模型列表、正在运行的模型、参数规模、模型大小、上下文长度、显存占用、运行时长。
- **Token 消耗统计**（核心功能）：累计 / 每日 / 每模型 / 每次请求的输入、输出、总 Token 数，生成速度（tokens/s）、请求耗时、首 Token 等待时间（TTFT），以及趋势图。
- **全客户端请求监控**：内置兼容 Ollama 原生 API 的反向代理，把客户端 API 地址改成 `http://localhost:4000` 即可统计所有通过代理的请求（流式与非流式）。
- **GPU / CPU / 内存监控**：GPU 使用率、显存、温度、功耗（`nvidia-smi`）；CPU 与内存（Windows 系统接口）。无法获取的指标显示 `N/A`，绝不编造。
- **现代化深色仪表盘**：Grafana / Vercel 风格，响应式，全离线（本地 Chart.js，无 CDN）。
- **完整中英文切换**：`zh-CN` / `en-US`，独立语言资源文件，记住上次选择。
- **本地 SQLite 存储**：请求历史、硬件历史、用户配置，重启不丢失；支持历史清理与 CSV 导出；不上传任何数据。

## 🏗 架构

```
客户端 (Continue / Hermes / curl / ...)
        │   API 地址改为 http://localhost:4000
        ▼
┌─────────────────────────────┐
│   Ollama Monitor (端口 4000) │
│   • 仪表盘 UI               │
│   • 反向代理 + Token 统计    │
│   • SQLite 本地存储          │
│   • 硬件采样 (nvidia-smi 等) │
└──────────────┬──────────────┘
               │ 转发
               ▼
        Ollama (http://localhost:11434)
```

> ⚠️ **重要**：只有通过代理（`localhost:4000`）转发的请求才会被完整统计。客户端绕过代理、直接访问 `11434` 的请求无法计入历史。

## 🚀 快速开始（EXE）

1. 下载并解压 `Ollama-Monitor-Windows-x64.zip`。
2. 双击 `OllamaMonitor.exe`。
3. 程序自动检测 Ollama 状态、检查端口、启动本地服务并打开浏览器。
4. 访问 `http://localhost:4000`。

首次运行会在 EXE 同目录生成 `data/`（数据库）、`logs/`（日志）；`config/settings.json` 为默认配置。

### 程序自检行为

- Ollama 未运行：仪表盘显示「离线」，代理返回 `502`，不影响仪表盘使用。
- 4000 端口被占用：弹出明确错误并退出，**不会**静默更换端口。
- 重复启动：检测到已有实例时提示并退出。

## 🔌 客户端连接配置示例

把客户端的 Ollama API 地址改成代理地址即可被统计。

**Continue (config.yaml / config.json)**

```json
{ "models": [{ "provider": "ollama", "apiBase": "http://localhost:4000", "model": "qwen3.5:4b" }] }
```

**curl（流式）**

```bash
curl -N http://localhost:4000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3.5:4b","messages":[{"role":"user","content":"你好"}],"stream":true}'
```

**curl（非流式）**

```bash
curl http://localhost:4000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3.5:4b","messages":[{"role":"user","content":"你好"}],"stream":false}'
```

**OpenAI 兼容客户端（如部分前端）**

```bash
export OPENAI_BASE_URL=http://localhost:4000/v1   # 若客户端使用 /v1 前缀，代理同样转发
```

代理对 Ollama 所有端点透明转发（`/api/tags`、`/api/ps`、`/api/version`、`/api/generate`、`/api/embed`、`/api/pull` …），语义不变。

## 🛠 从源码构建

要求：Windows 10/11 x64，Python 3.10+。

```bash
# 1. 创建虚拟环境并安装依赖
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt

# 2. 直接运行（开发模式）
.venv\Scripts\python -m src.main

# 3. 打包成单文件 EXE
.venv\Scripts\python scripts\build.py
# 输出: dist\OllamaMonitor.exe
```

Windows 一键构建：双击 `scripts\build.bat`。

## 📡 内置 API（仪表盘使用）

| 端点 | 说明 |
|------|------|
| `GET /api/monitor/status` | Ollama 状态、已安装/运行中模型 |
| `GET /api/monitor/hardware` | GPU/CPU/内存实时快照 |
| `GET /api/monitor/hardware/history?minutes=N` | 硬件历史采样 |
| `GET /api/monitor/stats` | Token 汇总 / 每日 / 每模型 |
| `GET /api/monitor/requests?model=&date=&q=&page=&limit=` | 请求历史（支持筛选/搜索/分页） |
| `GET /api/monitor/requests/{id}` | 单次请求详情 |
| `DELETE /api/monitor/requests` | 清空历史 |
| `GET /api/monitor/export.csv` | CSV 导出 |
| `GET/POST /api/settings` | 读取/修改配置（语言、局域网访问等） |
| 其余 `/api/*` | 透明转发到 Ollama |

## ⚙️ 配置项（config/settings.json）

| 键 | 默认值 | 说明 |
|----|--------|------|
| `language` | `zh-CN` | 界面语言（`zh-CN` / `en-US`） |
| `ollama_url` | `http://127.0.0.1:11434` | Ollama 上游地址 |
| `listen_host` | `127.0.0.1` | 监听地址（默认仅本机） |
| `listen_port` | `4000` | 监听端口 |
| `lan_access` | `false` | 局域网访问开关（开启后监听 `0.0.0.0`，有安全提示） |
| `auto_open_browser` | `true` | 启动后自动打开浏览器 |
| `hardware_refresh_seconds` | `2.0` | 硬件采样间隔 |
| `history_retention_days` | `0` | 历史保留天数（`0` = 永久保留） |

## 🔒 安全与隐私

- 默认仅监听 `127.0.0.1`；局域网访问需显式开启并承担风险。
- **不保存**提示词与模型回答正文，只保存统计元数据（Token 数、耗时、模型名、状态等）。
- 数据全部保存在本机 SQLite，不上传云端。
- 代理有防死循环保护（上游地址固定指向 Ollama，绝不回指自身）。
- 处理流式中断、请求超时、端口冲突、数据库损坏（损坏时给出明确错误、回退默认配置）。

## 📁 项目结构

```
Ollama-Monitor/
├── src/                    # Python 后端
│   ├── main.py             # 入口：单实例锁、端口检查、启动浏览器
│   ├── app.py              # FastAPI 应用 + 路由
│   ├── proxy.py            # 反向代理 + Token 统计
│   ├── ollama_client.py    # Ollama API 客户端
│   ├── hardware.py         # GPU/CPU/内存采样
│   ├── db.py               # SQLite 持久化
│   └── config.py           # 路径与配置
├── web/                    # 前端（离线，无 CDN）
│   ├── index.html
│   ├── css/style.css
│   ├── js/app.js / i18n.js
│   ├── locales/zh-CN.json / en-US.json
│   └── lib/chart.umd.js    # 本地 Chart.js
├── scripts/build.py / build.bat
├── config/settings.json    # 默认配置
├── requirements.txt
└── LICENSE.txt / THIRD_PARTY_NOTICES.md
```

## 交付物

- `dist/OllamaMonitor.exe` — 单文件 Windows x64 可执行程序
- `Ollama-Monitor-Windows-x64.zip` — 最终分发包
- 完整源代码、README、依赖与许可证清单

## 许可证

MIT — 见 `LICENSE.txt`。第三方组件许可见 `THIRD_PARTY_NOTICES.md`。
