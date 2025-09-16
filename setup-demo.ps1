# setup-demo.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host ">> Projeto: $root" -ForegroundColor Cyan
if (-not (Test-Path "$root\manage.py")) { throw "Não encontrei manage.py aqui." }

# venv
if (-not (Test-Path "$root\.venv")) {
  Write-Host ">> Criando venv..." -ForegroundColor Cyan
  python -m venv .venv
}
Write-Host ">> Ativando venv..." -ForegroundColor Cyan
& "$root\.venv\Scripts\Activate.ps1"

# deps backend
if (Test-Path "$root\requirements.txt") {
  Write-Host ">> Instalando requirements.txt..." -ForegroundColor Cyan
  pip install -r requirements.txt
}
Write-Host ">> Garantindo waitress e cors-headers..." -ForegroundColor Cyan
pip install waitress django-cors-headers

# migrações
Write-Host ">> Migrações..." -ForegroundColor Cyan
python manage.py migrate

# superuser opcional
$ans = Read-Host "Criar superusuário agora? (s/N)"
if ($ans -match '^[sS]') {
  $u = Read-Host "Username"
  $e = Read-Host "Email"
  $p = Read-Host "Senha"
  $env:DJANGO_SUPERUSER_USERNAME = $u
  $env:DJANGO_SUPERUSER_EMAIL    = $e
  $env:DJANGO_SUPERUSER_PASSWORD = $p
  python manage.py createsuperuser --noinput
  Remove-Item Env:DJANGO_SUPERUSER_USERNAME,Env:DJANGO_SUPERUSER_EMAIL,Env:DJANGO_SUPERUSER_PASSWORD -ErrorAction SilentlyContinue
}

# frontend (raiz ou ./frontend)
$front = if (Test-Path "$root\package.json") { $root } elseif (Test-Path "$root\frontend\package.json") { "$root\frontend" } else { "" }
if ($front -ne "") {
  Write-Host ">> Frontend: $front" -ForegroundColor Cyan
  $envProd = Join-Path $front ".env.production"
  if (-not (Test-Path $envProd)) {
    "VITE_API_BASE_URL=http://127.0.0.1:8000" | Out-File -FilePath $envProd -Encoding UTF8 -Force
    Write-Host ">> Criei $envProd" -ForegroundColor Yellow
  }
  if (-not (Test-Path "$front\node_modules")) {
    Set-Location $front
    Write-Host ">> Instalando dependências do front (npm ci)..." -ForegroundColor Cyan
    npm ci
    Set-Location $root
  }
} else {
  Write-Warning "Não encontrei package.json (na raiz ou em .\frontend)."
}

Write-Host "`nSetup concluído. Agora use: Setup Demo.bat (1x) e Run Demo.bat (para rodar)." -ForegroundColor Green
