@echo off
setlocal EnableDelayedExpansion

REM video_agent - Unified Development Environment Setup (Windows)
REM Uses uv to manage Python and dependencies automatically.

REM Ensure we are working in the script directory context
cd /d "%~dp0"

echo ==========================================================
echo   Initializing video_agent Development Environment...
echo ==========================================================
echo.

REM 1. Setup uv (Download if not present)
set "UV_CMD=uv"

REM Check if uv is in PATH
where uv >nul 2>&1
if !errorlevel! EQU 0 (
    echo [1/4] uv tool found in system PATH.
    goto :SKIP_DOWNLOAD
)

REM Check if uv is in current directory
if exist "uv.exe" (
    echo [1/4] uv tool found in current directory.
    set "UV_CMD=.\uv.exe"
    goto :SKIP_DOWNLOAD
)

REM If not found, download it
echo [1/4] Downloading uv tool...
echo.
echo Official installation guide: https://docs.astral.sh/uv/getting-started/installation/
echo.

REM Try official installation method (irm | iex)
echo Attempting to install uv via official script...
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

REM Check if installed to PATH or User directory
where uv >nul 2>&1
if !errorlevel! EQU 0 (
    echo uv installed successfully to PATH.
    set "UV_CMD=uv"
    goto :SKIP_DOWNLOAD
)

REM If official script failed or didn't add to PATH immediately, check standard locations or try fallback
if exist "%USERPROFILE%\.cargo\bin\uv.exe" (
    set "UV_CMD=%USERPROFILE%\.cargo\bin\uv.exe"
    echo uv installed to %USERPROFILE%\.cargo\bin\uv.exe
    goto :SKIP_DOWNLOAD
)

REM Fallback: Download standalone binary
echo Standard installation did not make 'uv' available immediately. Trying standalone download...
powershell -Command "try { Invoke-WebRequest -Uri 'https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip' -OutFile 'uv.zip' -ErrorAction Stop } catch { exit 1 }"

if !errorlevel! NEQ 0 (
    echo [Error] Failed to download uv.
    echo Please check your network connection.
    echo You can manually download uv from: https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip
    echo And extract 'uv.exe' to: "%~dp0"
    pause
    exit /b 1
)

echo Extracting uv...
powershell -Command "Expand-Archive -Path 'uv.zip' -DestinationPath '.' -Force"

if exist "uv-x86_64-pc-windows-msvc\uv.exe" (
    move /y "uv-x86_64-pc-windows-msvc\uv.exe" . >nul
    rmdir /s /q "uv-x86_64-pc-windows-msvc"
    set "UV_CMD=.\uv.exe"
)
if exist "uv.zip" del uv.zip

:SKIP_DOWNLOAD

REM 2. Create Virtual Environment
echo [2/4] Creating virtual environment (.venv)...
REM Create .venv in project root (two levels up from scripts/init_dev_env/)
%UV_CMD% venv "..\..\.venv" --python 3.12

if !errorlevel! NEQ 0 (
    echo Error: Failed to create virtual environment.
    pause
    exit /b 1
)

REM 3. Install Dependencies
echo [3/4] Installing dependencies (requirements.txt)...
%UV_CMD% pip install -r "..\..\requirements.txt" --python "..\..\.venv"

if !errorlevel! NEQ 0 (
    echo Error: Failed to install dependencies.
    pause
    exit /b 1
)

REM 4. Done
echo [4/4] Setup complete.

echo.
echo ==========================================================
echo   Setup Complete!
echo ==========================================================
echo.
echo Three manual steps:
echo   1. Run the /script-writer skill to write instances_prompt.yaml + script.yaml
echo   2. .venv\Scripts\python.exe -m agents.image.generator --project-dir "output\projects\title"
echo   3. .venv\Scripts\python.exe -m agents.video.generate --prompt "..." --image-urls "..."
echo.
echo Or open this project in your IDE (VS Code / PyCharm / Trae) and select
echo '.venv' as your Python interpreter.
echo.
pause
