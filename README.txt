============================================================
  Ollama Monitor  —  Local LLM Monitor for Windows
  v1.0.0  (MIT License)
============================================================

[What is it]
  Monitors local large language models running through Ollama:
  - Model status (online/offline, installed, running, VRAM usage)
  - Token usage statistics (input/output/total, generation speed, trends)
  - All-client request monitoring (built-in reverse proxy)
  - GPU / CPU / Memory hardware monitoring
  - Dark dashboard with full Chinese/English switching

[How to use]
  1. Double-click OllamaMonitor.exe
  2. The program auto-checks Ollama, checks the port, starts the service,
     and opens your browser
  3. Visit http://localhost:4000

  On first run, these are created next to the executable:
    data\     -- local database (history; do not delete or history is lost)
    logs\     -- runtime logs
    config\settings.json -- configuration file

[Tracking client requests]
  Point your client's Ollama API address at http://localhost:4000.

  Native Ollama API:
    API Base: http://localhost:4000        (/api/chat, /api/generate, ...)
  OpenAI-compatible API:
    API Base: http://localhost:4000/v1     (/v1/models, /v1/chat/completions, ...)

  Note: only requests that pass through the :4000 proxy are recorded;
  requests that hit 11434 directly cannot be tracked.

[LAN access]
  LAN access is enabled by default (listens on 0.0.0.0). Other devices on the
  same network can reach it via this machine's IP:
    http://<this-machine-IP>:4000

  First-time use requires allowing port 4000 through the Windows firewall,
  otherwise LAN devices cannot connect.
  Security note: with LAN access enabled, other devices on your network can
  view the dashboard and call your Ollama models. Use only on trusted networks.
  To disable, set "lan_access" to false in config\settings.json and restart.

[FAQ]
  * Port already in use?
    The program shows an error and exits -- it never silently switches ports.
    Close the program occupying port 4000 and try again.
  * Ollama not running?
    The dashboard shows "Offline" and the proxy returns 502.
    It recovers automatically once Ollama is started.
  * History shows "Failed" / 0 tokens?
    Make sure the client sends requests to port 4000 (not directly to 11434).
    Click the icon on the far right of a history row to see the error detail.

[Privacy]
  All data stays on this machine and is never uploaded. Prompt text and
  model replies are NOT stored -- only statistics (token counts, durations,
  model names) are saved.

[Uninstall]
  Delete this folder.


============================================================
  Ollama Monitor  —  Windows 本地模型监控系统
  v1.0.0  (MIT 许可证)
============================================================

【是什么】
  监控本机通过 Ollama 运行的本地大语言模型：
  - 模型状态（在线/离线、已安装、运行中、显存占用）
  - Token 消耗统计（输入/输出/总量、生成速度、趋势图）
  - 全客户端请求监控（内置反向代理）
  - GPU / CPU / 内存硬件监控
  - 深色仪表盘，完整中英文切换

【怎么用】
  1. 双击 OllamaMonitor.exe
  2. 程序自动检查 Ollama、检查端口、启动服务并打开浏览器
  3. 浏览器访问 http://localhost:4000

  首次运行会在本目录生成：
    data\     —— 本地数据库（历史记录，请勿删除，否则历史丢失）
    logs\     —— 运行日志
    config\settings.json —— 配置文件

【统计客户端请求】
  把客户端的 Ollama API 地址改成 http://localhost:4000 即可。

  原生 Ollama 接口：
    API Base: http://localhost:4000        （/api/chat、/api/generate 等）
  OpenAI 兼容接口：
    API Base: http://localhost:4000/v1     （/v1/models、/v1/chat/completions 等）

  注意：只有通过 4000 端口代理转发的请求才会被统计；
  直接访问 11434 的请求无法计入历史。

【局域网访问】
  默认已开启局域网访问（监听 0.0.0.0），同一网络下其他设备可通过
  本机 IP 访问：
    http://<本机IP>:4000

  首次使用需在 Windows 防火墙放行 4000 端口，否则局域网设备无法连接。
  安全提示：开启局域网访问后，同网段其他设备可访问监控面板并调用
  你的 Ollama 模型，请仅在可信网络环境使用。如需关闭，把
  config\settings.json 中的 "lan_access" 改为 false 后重启。

【常见问题】
  * 端口被占用？
    程序会弹出错误并退出，不会自动换端口。请关闭占用 4000 端口的程序。
  * Ollama 没启动？
    仪表盘显示"离线"，代理返回 502。启动 Ollama 后自动恢复。
  * 请求历史显示"失败" / Token 为 0？
    确认客户端请求是发往 4000 端口（而非直连 11434）。
    详情可点历史记录最右列的图标查看具体错误。

【隐私】
  所有数据保存在本机，不上传云端。不保存提示词和回答正文，
  只保存 Token 数、耗时、模型名等统计信息。

【卸载】
  直接删除本目录即可。

============================================================
  完整文档与源码 / Full docs & source: see README.md or the repository
  许可证 / License: LICENSE.txt (MIT)
============================================================
