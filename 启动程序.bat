echo off
chcp 65001 >nul
title 高中数学题库管理助手
cd /d "%~dp0"

echo ========================================================
echo           高中数学题库管理助手 (Math Question Bank)
echo ========================================================
echo.
echo [1/2] 正在初始化环境...
echo [2/2] 启动 Streamlit 服务...
echo.
echo 浏览器即将自动打开...
echo 如需关闭程序，请直接关闭此命令行窗口。
echo.

:: 启动 Streamlit
streamlit run question_bank_app.py

:: 如果启动失败，尝试使用 python -m 方式
if %errorlevel% neq 0 (
    echo.
    echo 尝试使用 python -m streamlit 启动...
    python -m streamlit run question_bank_app.py
)

if %errorlevel% neq 0 (
    echo.
    echo [错误] 启动失败。
    echo 请确认已安装 streamlit (pip install streamlit)
    pause
)