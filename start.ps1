#requires -Version 5.1
<#
.SYNOPSIS
    WebSearch Lite 一键启动脚本（后端 API + 前端）。

.DESCRIPTION
    默认「生产模式」：构建过前端就直接用后端托管，只开一个地址。
    -Dev 模式：后端 + Vite 热更新开发服务器，改前端代码即时生效。

.PARAMETER Dev
    启动 Vite 开发服务器（端口 5173，/api 代理到后端）。

.PARAMETER Port
    后端端口，默认 8765。

.PARAMETER NoBrowser
    不自动打开浏览器。

.PARAMETER Rebuild
    强制重新构建前端。

.EXAMPLE
    .\start.ps1
    .\start.ps1 -Dev
    .\start.ps1 -Port 9000 -NoBrowser
#>
[CmdletBinding()]
param(
    [switch]$Dev,
    [int]$Port = 8765,
    [switch]$NoBrowser,
    [switch]$Rebuild
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$WebDir = Join-Path $Root 'web'
$DistIndex = Join-Path $WebDir 'dist\index.html'
$BaseUrl = "http://127.0.0.1:$Port"

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg) { Write-Host "  OK  $msg" -ForegroundColor Green }
function Write-Warn2($msg) { Write-Host "  !!  $msg" -ForegroundColor Yellow }
function Write-Err($msg) { Write-Host "  XX  $msg" -ForegroundColor Red }

function Find-Python {
    $candidates = @(
        (Join-Path $env:USERPROFILE '.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'),
        'python',
        'python3'
    )
    foreach ($candidate in $candidates) {
        if ($candidate -match '[\\/]') {
            if (Test-Path $candidate) { return $candidate }
        } else {
            $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
            if ($cmd) { return $cmd.Source }
        }
    }
    return $null
}

function Test-PortInUse([int]$p) {
    try {
        $conn = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction Stop
        return [bool]$conn
    } catch {
        return $false
    }
}

function Wait-HttpOk([string]$url, [int]$seconds = 40) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $res = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3
            if ($res.StatusCode -ge 200 -and $res.StatusCode -lt 500) { return $true }
        } catch {
            Start-Sleep -Milliseconds 400
        }
    }
    return $false
}

Write-Host ''
Write-Host '  WebSearch Lite 控制台' -ForegroundColor White
Write-Host '  ─────────────────────' -ForegroundColor DarkGray

# ---------- 1. Python ----------
Write-Step '检查 Python'
$python = Find-Python
if (-not $python) {
    Write-Err '找不到 Python。请安装 Python 3.11+ 或确认 DSH 运行时存在。'
    exit 1
}
Write-Ok $python

# ---------- 2. 前端依赖与产物 ----------
if ($Dev -or $Rebuild -or -not (Test-Path $DistIndex)) {
    Write-Step '检查前端构建环境'
    $pnpm = Get-Command pnpm -ErrorAction SilentlyContinue
    if (-not $pnpm) {
        $pnpm = Get-Command npm -ErrorAction SilentlyContinue
        if (-not $pnpm) {
            Write-Err '找不到 pnpm / npm。请安装 Node.js 18+。'
            exit 1
        }
        $pkgMgr = 'npm'
    } else {
        $pkgMgr = 'pnpm'
    }

    if (-not (Test-Path (Join-Path $WebDir 'node_modules'))) {
        Write-Warn2 "首次运行，安装前端依赖（$pkgMgr install）…"
        Push-Location $WebDir
        try { & $pkgMgr install } finally { Pop-Location }
        if ($LASTEXITCODE -ne 0) { Write-Err '依赖安装失败'; exit 1 }
    } else {
        Write-Ok '前端依赖已存在'
    }

    if ($Rebuild -or -not (Test-Path $DistIndex)) {
        if (-not $Dev) {
            Write-Step '构建前端（首次或强制）'
            Push-Location $WebDir
            try { & $pkgMgr build } finally { Pop-Location }
            if ($LASTEXITCODE -ne 0) { Write-Err '前端构建失败'; exit 1 }
            Write-Ok '构建完成'
        }
    }
}

# ---------- 3. 端口 ----------
Write-Step "检查端口 $Port"
if (Test-PortInUse $Port) {
    if (Wait-HttpOk "$BaseUrl/api/overview" 4) {
        Write-Warn2 "端口 $Port 已有服务在运行，直接复用"
        if (-not $NoBrowser) { Start-Process $BaseUrl }
        Write-Host ''
        Write-Host "  已有服务：$BaseUrl" -ForegroundColor Green
        Write-Host '  如需重启，请先关闭占用该端口的进程。' -ForegroundColor DarkGray
        Write-Host ''
        exit 0
    }
    Write-Err "端口 $Port 被占用但无响应，请换端口： .\start.ps1 -Port 9000"
    exit 1
}
Write-Ok "端口 $Port 可用"

# ---------- 4. 启动 ----------
$env:PYTHONPATH = Join-Path $Root 'src'
$backendProc = $null
$devProc = $null

try {
    if ($Dev) {
        Write-Step "启动后端 API（$BaseUrl）"
        $backendProc = Start-Process -FilePath $python `
            -ArgumentList '-m', 'websearch_lite.server' `
            -WorkingDirectory $Root -PassThru -WindowStyle Hidden
        if (-not (Wait-HttpOk "$BaseUrl/api/overview" 40)) {
            Write-Err '后端启动超时，请检查数据库或依赖。'
            exit 1
        }
        Write-Ok '后端就绪'

        Write-Step '启动前端开发服务器（http://127.0.0.1:5173）'
        $pnpmCmd = (Get-Command pnpm -ErrorAction SilentlyContinue)
        if (-not $pnpmCmd) {
            Write-Err '开发模式需要 pnpm。'
            exit 1
        }
        if (-not $NoBrowser) {
            Start-Job -ArgumentList 'http://127.0.0.1:5173' { param($u) Start-Sleep -Seconds 4; Start-Process $u } | Out-Null
        }
        Write-Host ''
        Write-Host "  前端（热更新）: http://127.0.0.1:5173" -ForegroundColor Green
        Write-Host "  后端 API      : $BaseUrl" -ForegroundColor DarkGray
        Write-Host '  按 Ctrl+C 停止' -ForegroundColor DarkGray
        Write-Host ''
        Push-Location $WebDir
        try { & $pnpmCmd.Source 'dev' } finally { Pop-Location }
    } else {
        if (-not $NoBrowser) {
            Start-Job -ArgumentList $BaseUrl { param($u) Start-Sleep -Seconds 3; Start-Process $u } | Out-Null
        }
        Write-Host ''
        Write-Host "  控制台地址: $BaseUrl" -ForegroundColor Green
        Write-Host '  按 Ctrl+C 停止' -ForegroundColor DarkGray
        Write-Host ''
        Write-Step '启动服务'
        if ($NoBrowser) { & $python -m websearch_lite.server --port $Port } else { & $python -m websearch_lite.server --port $Port --open }
    }
} finally {
    if ($backendProc -and -not $backendProc.HasExited) {
        Write-Host ''
        Write-Host '  正在停止后端…' -ForegroundColor DarkGray
        Stop-Process -Id $backendProc.Id -Force -ErrorAction SilentlyContinue
    }
    if ($devProc -and -not $devProc.HasExited) {
        Stop-Process -Id $devProc.Id -Force -ErrorAction SilentlyContinue
    }
    Get-Job -ErrorAction SilentlyContinue | Where-Object { $_.State -eq 'Running' } | Stop-Job -ErrorAction SilentlyContinue
    Remove-Job -Job (Get-Job -ErrorAction SilentlyContinue) -Force -ErrorAction SilentlyContinue
    Write-Host '  已退出' -ForegroundColor DarkGray
}
