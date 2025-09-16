# run-demo.ps1
param([int]$FrontPort = 4173)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host ">> Projeto: $root" -ForegroundColor Cyan
if (-not (Test-Path "$root\manage.py")) { throw "Não encontrei manage.py aqui." }

# detecta frente
$front = if (Test-Path "$root\package.json") { $root } elseif (Test-Path "$root\frontend\package.json") { "$root\frontend" } else { "" }
if ($front -eq "") { throw "Não encontrei package.json (raiz ou .\frontend)." }

Write-Host ">> Lembrete: CORS/CSRF devem incluir http://127.0.0.1:$FrontPort" -ForegroundColor Yellow

# venv + deps mínimas + migra
if (-not (Test-Path "$root\.venv")) { python -m venv .venv }
& "$root\.venv\Scripts\Activate.ps1"
pip show waitress | Out-Null; if ($LASTEXITCODE -ne 0) { pip install waitress }
pip show django-cors-headers | Out-Null; if ($LASTEXITCODE -ne 0) { pip install django-cors-headers }
python manage.py migrate | Out-Null

# backend (nova janela)
$wsgiApp = "jurisdoc.wsgi:application"   # troque se seu projeto tiver outro nome
$backendCmd = "cd `"$root`"; .\.venv\Scripts\Activate.ps1; waitress-serve --port=8000 $wsgiApp"
Start-Process powershell -ArgumentList "-NoExit","-Command",$backendCmd | Out-Null
Write-Host ">> Backend: http://127.0.0.1:8000" -ForegroundColor Green

# frontend build + preview (nova janela)
Set-Location $front
if (-not (Test-Path "$front\node_modules")) { npm ci }
npm run build
$frontCmd = "cd `"$front`"; npm run preview -- --port $FrontPort"
Start-Process powershell -ArgumentList "-NoExit","-Command",$frontCmd | Out-Null
Write-Host ">> Frontend: http://127.0.0.1:$FrontPort" -ForegroundColor Green

Start-Process "http://127.0.0.1:$FrontPort"
Write-Host "`nTudo no ar! Feche as duas janelas para parar." -ForegroundColor Green
