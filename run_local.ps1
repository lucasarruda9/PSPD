$ErrorActionPreference = "Stop"
$Root       = Split-Path -Parent $MyInvocation.MyCommand.Path
$GatewayDir = Join-Path $Root "modulo_p_gateway"
$ProtoDir   = Join-Path $Root "proto"
$ProtoFile  = Join-Path $ProtoDir "image_processing.proto"
Set-Location $GatewayDir

#1 Gera os stubs do protobuf
Write-Host "Gerando stubs do protobuf..."
uv run python -m grpc_tools.protoc `
    -I"$ProtoDir" `
    --python_out=. `
    --grpc_python_out=. `
    "$ProtoFile"
Write-Host "OK"

#2 Sobe o Mock gRPC em background
Write-Host "Iniciando Mock gRPC (portas 50051 e 50052)..."
$mockJob = Start-Job -ScriptBlock {
    param($dir)
    Set-Location $dir
    uv run python mock_server.py
} -ArgumentList $GatewayDir

Start-Sleep -Seconds 2
Write-Host "OK"

#3 Sobe o Gateway FastAPI
Write-Host ""
Write-Host "Iniciando Gateway FastAPI..."
Write-Host ""
Write-Host "Interface: http://localhost:8000"
Write-Host "API Docs:  http://localhost:8000/docs"
Write-Host "Health:    http://localhost:8000/health"
Write-Host ""

try {
    uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
} finally {
    Write-Host ""
    Write-Host "Encerrando Mock gRPC..."
    Stop-Job   $mockJob -ErrorAction SilentlyContinue
    Remove-Job $mockJob -ErrorAction SilentlyContinue}
