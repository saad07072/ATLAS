Set-Location $PSScriptRoot
Write-Host "===================================================================" -ForegroundColor Cyan
Write-Host "  ATLAS NEURAL CORE // BACKEND SERVICE" -ForegroundColor Cyan
Write-Host "  Starting on http://127.0.0.1:8000..." -ForegroundColor Cyan
Write-Host "===================================================================" -ForegroundColor Cyan
& "$PSScriptRoot\backend\.venv\Scripts\python.exe" -m uvicorn backend.app.main:app --reload --port 8000
