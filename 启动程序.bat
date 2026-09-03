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
set "INIT_WORKSPACE=%CD%\scripts\init_local_workspace.py"

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

if not exist "%INIT_WORKSPACE%" (
    echo [ERROR] scripts\init_local_workspace.py was not found.
    pause
    exit /b 1
)

if not exist "%VENV_PYTHON%" (
    echo [1/4] First run: creating a Python 3.10 - 3.12 virtual environment...
    goto :find_python
)

echo [1/4] Virtual environment found.

:venv_ready
echo [2/4] Synchronizing locked dependencies...
"%VENV_PYTHON%" -m pip install --disable-pip-version-check --requirement "%REQUIREMENTS%"
if errorlevel 1 (
    echo.
    echo [ERROR] Dependency installation failed.
    echo On first run, confirm that the Python package index is reachable.
    pause
    exit /b 1
)

echo [3/4] Preparing local workspace...
"%VENV_PYTHON%" "%INIT_WORKSPACE%" --skip-gitignore-check
if errorlevel 1 (
    echo.
    echo [ERROR] Local workspace initialization failed.
    pause
    exit /b 1
)

echo [4/4] Starting Streamlit...
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

:find_python
rem Prefer the Windows Python Launcher so a supported version is selected
rem even when another Python version appears first on PATH.
for %%V in (3.12 3.11 3.10) do (
    py -%%V -c "import sys; sys.exit(0 if sys.maxsize > 2**32 else 1)" >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_COMMAND=py -%%V"
        goto :create_venv
    )
)

rem A Python installation can be usable even if the optional Launcher was not
rem installed. Accept a supported, 64-bit interpreter available on PATH.
python -c "import sys; sys.exit(0 if (3, 10) <= sys.version_info[:2] <= (3, 12) and sys.maxsize > 2**32 else 1)" >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_COMMAND=python"
    goto :create_venv
)

echo [ERROR] A usable 64-bit CPython 3.10 - 3.12 was not found.
echo This launcher checked Python Launcher versions and the python command on PATH.
echo.
echo Open Command Prompt and run these commands to diagnose the installation:
echo   py --list
echo   py -3.12 --version
echo.
echo If py is not recognized or does not list Python 3.12, modify the official
echo Python 3.12 installation and select "Python Launcher" and "Add python.exe to PATH".
pause
exit /b 1

:create_venv
echo Using:
%PYTHON_COMMAND% --version
echo Creating the virtual environment...
%PYTHON_COMMAND% -m venv "%VENV_DIR%"
if errorlevel 1 (
    echo.
    echo [ERROR] Python was found, but the virtual environment could not be created.
    echo Read the error above. Common causes are a protected project folder,
    echo an incomplete Python installation, or security software blocking the operation.
    pause
    exit /b 1
)

if not exist "%VENV_PYTHON%" (
    echo.
    echo [ERROR] The virtual environment was created without Scripts\python.exe.
    echo Delete the incomplete .venv folder, then run this launcher again.
    pause
    exit /b 1
)
goto :venv_ready
