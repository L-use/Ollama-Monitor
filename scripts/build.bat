@echo off
REM ============================================================
REM  Ollama Monitor - one-click Windows build
REM  Produces dist\OllamaMonitor.exe
REM ============================================================
setlocal
cd /d "%~dp0.."

echo [1/4] Locating Python...
set PY=
where py >nul 2>nul && (set PY=py -3) || (where python >nul 2>nul && set PY=python)
if "%PY%"=="" (
    echo ERROR: Python not found. Install Python 3.10+ from python.org first.
    pause
    exit /b 1
)

echo [2/4] Creating virtualenv...
if not exist .venv (
    %PY% -m venv .venv
    if errorlevel 1 ( echo ERROR: failed to create venv & pause & exit /b 1 )
)

echo [3/4] Installing dependencies...
.venv\Scripts\python.exe -m pip install --upgrade pip -q
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 ( echo ERROR: dependency install failed & pause & exit /b 1 )

echo [4/4] Building EXE with PyInstaller...
.venv\Scripts\python.exe scripts\build.py
if errorlevel 1 ( echo ERROR: build failed & pause & exit /b 1 )

echo.
echo Done!  dist\OllamaMonitor.exe
pause
