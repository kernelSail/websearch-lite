@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem 双击启动 WebSearch Lite 控制台（生产模式，单端口）
rem 需要开发热更新时：在 PowerShell 里执行  .\start.ps1 -Dev

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
set "CODE=%ERRORLEVEL%"

if not "%CODE%"=="0" (
  echo.
  echo 启动失败（退出码 %CODE%）。
  pause
)
endlocal
