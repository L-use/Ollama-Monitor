@echo off
chcp 65001 >nul
title Ollama Monitor - 放行 4000 端口（局域网 + Tailscale 组网）

:: 自动提权
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo 正在请求管理员权限...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo ============================================================
echo   为 Ollama Monitor 放行 TCP 4000 端口
echo   适用：本机回环 / 局域网 / Tailscale 组网（所有网络类型）
echo ============================================================
echo.

:: 先删除同名旧规则，避免重复
netsh advfirewall firewall delete rule name="Ollama Monitor 4000" >nul 2>&1

:: 添加入站放行规则：TCP 4000，所有 profile（域/专用/公用）
netsh advfirewall firewall add rule name="Ollama Monitor 4000" dir=in action=allow protocol=TCP localport=4000 profile=any
if %errorLevel% neq 0 (
    echo.
    echo [失败] 未能添加规则，请检查是否有其他安全软件拦截。
    pause
    exit /b 1
)

:: 同时放行 Tailscale 专用的入站（保险起见，只对 Tailscale 的子网）
echo.
echo 正在确认规则...
netsh advfirewall firewall show rule name="Ollama Monitor 4000"

echo.
echo ============================================================
echo   完成！现在可以通过以下地址访问：
echo.
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"Tailscale" /c:"100."') do (
    echo    - Tailscale: http://%%a:4000
)
echo    - 本机:       http://127.0.0.1:4000
echo ============================================================
echo.
pause
