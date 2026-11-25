<#
.SYNOPSIS
    Arranca o backend FastAPI e o frontend Vite em desenvolvimento local (Windows PowerShell).
#>
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $RepoRoot "backend"
$FrontendDir = Join-Path $RepoRoot "frontend"

Write-Host "==> A aplicar migrações Alembic no backend..." -ForegroundColor Cyan
Push-Location $BackendDir
try {
    & ".\.venv\Scripts\alembic.exe" upgrade head
} finally {
    Pop-Location
}

Write-Host "==> A arrancar backend FastAPI em http://127.0.0.1:8000 ..." -ForegroundColor Green
$backendProc = Start-Process -FilePath (Join-Path $BackendDir ".venv\Scripts\uvicorn.exe") `
    -ArgumentList "app.main:app", "--reload", "--host", "127.0.0.1", "--port", "8000" `
    -WorkingDirectory $BackendDir `
    -PassThru

Write-Host "==> A arrancar frontend Vite em http://localhost:5173 ..." -ForegroundColor Green
try {
    Push-Location $FrontendDir
    npm run dev
} finally {
    Pop-Location
    if ($backendProc -and !$backendProc.HasExited) {
        Write-Host "==> A parar backend FastAPI..." -ForegroundColor Yellow
        Stop-Process -Id $backendProc.Id -Force -ErrorAction SilentlyContinue
    }
}
