@echo off
setlocal EnableExtensions DisableDelayedExpansion
title MathCyclus Question Bank

set "PROJECT_DIR=%~dp0"
pushd "%PROJECT_DIR%" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Cannot open the folder containing this launcher.
    pause
    exit /b 1
)
set "VENV_DIR=%CD%\.venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "MAIN_APP=%CD%\question_bank_app.py"
set "REQUIREMENTS=%CD%\requirements.txt"

echo ========================================================
echo              MathCyclus Question Bank
echo ========================================================
echo.

if not exist "%MAIN_APP%" (
    echo [ERROR] question_bank_app.py was not found.
    echo Keep this launcher in the project root folder.
    pause
    exit /b 1
)

if not exist "%REQUIREMENTS%" (
    echo [ERROR] requirements.txt was not found.
    pause
    exit /b 1
)

if not exist "%VENV_PYTHON%" (
    echo [1/3] First run: creating a Python 3.10 - 3.12 virtual environment...
    py -3.12 -m venv "%VENV_DIR%" >nul 2>&1
    if exist "%VENV_PYTHON%" goto :venv_ready

    py -3.11 -m venv "%VENV_DIR%" >nul 2>&1
    if exist "%VENV_PYTHON%" goto :venv_ready

    py -3.10 -m venv "%VENV_DIR%" >nul 2>&1
    if exist "%VENV_PYTHON%" goto :venv_ready

    echo [ERROR] Python 3.10 - 3.12 was not found.
    echo Install 64-bit Python 3.12 and select Python Launcher during setup.
    pause
    exit /b 1
)

:venv_ready
echo [2/3] Synchronizing locked dependencies...
"%VENV_PYTHON%" -m pip install --disable-pip-version-check --requirement "%REQUIREMENTS%"
if errorlevel 1 (
    echo.
    echo [ERROR] Dependency installation failed.
    echo On first run, confirm that the Python package index is reachable.
    pause
    exit /b 1
)

echo [3/3] Starting Streamlit...
echo The browser should open automatically. Close this window to stop the service.
echo.
"%VENV_PYTHON%" -m streamlit run "%MAIN_APP%" --server.port=8501 --server.headless=false
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [ERROR] The service stopped with exit code %EXIT_CODE%.
    pause
)

popd
exit /b %EXIT_CODE%
