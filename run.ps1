param([int]$Port = 8765)

Set-Location $PSScriptRoot
python -m pip install -r requirements.txt --quiet
if (-not (Test-Path .env)) { Copy-Item .env.example .env }

Start-Job { Start-Sleep -Seconds 2; Start-Process "http://127.0.0.1:$using:Port" } | Out-Null
python -m uvicorn app.main:app --host 127.0.0.1 --port $Port
