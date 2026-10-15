@echo off
chcp 65001 >nul
setlocal
set PYTHONUTF8=1
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 goto try_py
goto try_python
:try_py
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" >nul 2>nul
if errorlevel 1 goto try_python
py -3 app.py
goto finished
:try_python
where python >nul 2>nul
if errorlevel 1 goto missing
python -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" >nul 2>nul
if errorlevel 1 goto missing
python app.py
goto finished
:missing
echo.
echo 请先安装 Python 3.11 或以上版本，再重新双击本文件。
echo 官方下载：https://www.python.org/downloads/windows/
echo 安装时勾选 Add python.exe to PATH；不需要 Docker 或 Git。
echo.
pause
exit /b 1
:finished
echo.
echo 管理后台已退出。如出现错误，请保留本窗口中的错误信息。
pause
