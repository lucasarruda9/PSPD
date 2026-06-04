from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import grpc
from pathlib import Path
import asyncio
import time

import image_processing_pb2
import image_processing_pb2_grpc

app = FastAPI(title="Gateway Módulo P - Processamento de Imagem", version="1.0.0")

import os
#Permitir requisições do frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],)
GRPC_SERVER_A = os.getenv('GRPC_SERVER_A', 'localhost:50051')
GRPC_SERVER_B = os.getenv('GRPC_SERVER_B', 'localhost:50052')
STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
def get_grpc_stub(target_server: str):
    canal = grpc.insecure_channel(target_server)
    return image_processing_pb2_grpc.ImageProcessorServiceStub(canal)
def wait_for_grpc_servers(timeout: int = 10):
    start = time.time()
    while time.time() - start < timeout:
        try:
            stub_a = get_grpc_stub(GRPC_SERVER_A)
            stub_b = get_grpc_stub(GRPC_SERVER_B)
            print(f"✓ Conectado aos servidores gRPC")
            return True
        except Exception as e:
            print(f"Aguardando servidores gRPC... ({int(time.time() - start)}s)")
            time.sleep(0.5)
    print(f"Timeout ao conectar aos servidores gRPC após {timeout}s")
    return False
@app.on_event("startup")
async def startup_event():
    await asyncio.to_thread(wait_for_grpc_servers)

@app.get("/", include_in_schema=False)
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))
@app.get("/health")
def health_check():
    return {"status": "ok", "grpc_server_a": GRPC_SERVER_A, "grpc_server_b": GRPC_SERVER_B}

#Server A processa uma imagem e retorna o resultado final unary
@app.post("/api/unary/processar-imagem")
async def processar_imagem_unary(arquivo: UploadFile = File(...)):
    try:
        stub = get_grpc_stub(GRPC_SERVER_A)
        conteudo = await arquivo.read()
        req = image_processing_pb2.ImagemRequest(
            dados_imagem=conteudo, formato=arquivo.filename.split(".")[-1], nome_arquivo=arquivo.filename
    )
        resp = stub.ProcessarImagem(req)
        return {
            "tipo": "unary",
            "servidor": "A",
            "arquivo": arquivo.filename,
            "formato_saida": resp.formato_saida,
            "tempo_ms": resp.tempo_ms,
            "etapas_aplicadas": list(resp.etapas_aplicadas),
            "tamanho_entrada_bytes": len(conteudo),}
    except grpc.RpcError as e:
        raise HTTPException(status_code=503, detail=f"Erro gRPC: {e.details()}")

#Server A envia atualizações de progresso via stream
@app.post("/api/server-stream/processar-etapas")
async def processar_etapas_stream(arquivo: UploadFile = File(...)):
    try:
        stub = get_grpc_stub(GRPC_SERVER_A)
        conteudo = await arquivo.read()
        req = image_processing_pb2.ImagemRequest(
            dados_imagem=conteudo, formato=arquivo.filename.split(".")[-1], nome_arquivo=arquivo.filename
    )
        def gerar_respostas():
            for resp in stub.ProcessarEtapas(req):
                status = "CONCLUÍDO" if resp.ultima_etapa else "⟳ processando"
                yield f"[{resp.tempo_etapa_ms:.1f}ms] {resp.nome_etapa} — {status}\n"
        return StreamingResponse(gerar_respostas(), media_type="text/plain")
    except grpc.RpcError as e:
        raise HTTPException(status_code=503, detail=f"Erro gRPC: {e.details()}")

#Server B recebe múltiplas imagens via stream e retorna um resumo ao final
@app.post("/api/client-stream/processar-lote")
async def processar_lote_cliente(arquivos: list[UploadFile] = File(...)):
    try:
        stub = get_grpc_stub(GRPC_SERVER_B)
        def gerar_stream_grpc():
            for arq in arquivos:
                yield image_processing_pb2.ImagemRequest(
                    dados_imagem=arq.file.read(), formato=arq.filename.split(".")[-1], nome_arquivo=arq.filename,
            )
        resp = stub.ProcessarLote(gerar_stream_grpc())
        return {
            "tipo": "client_streaming",
            "servidor": "B",
            "total_processadas": resp.total_processadas,
            "total_erros": resp.total_erros,
            "tempo_total_ms": resp.tempo_total_ms,
            "arquivos_processados": list(resp.arquivos_processados),}
    except grpc.RpcError as e:
        raise HTTPException(status_code=503, detail=f"Erro gRPC: {e.details()}")

#Server B recebe um stream de imagens e retorna um stream de previews em tempo real
@app.post("/api/bidirecional/preview-ao-vivo")
async def processar_preview_bidirecional(arquivos: list[UploadFile] = File(...)):
    try:
        stub = get_grpc_stub(GRPC_SERVER_B)
        def gerar_stream_grpc():
            for arq in arquivos:
                yield image_processing_pb2.ImagemRequest(
                    dados_imagem=arq.file.read(), formato=arq.filename.split(".")[-1], nome_arquivo=arq.filename
            )
        def ler_respostas():
            for resp in stub.ProcessarPreviewAoVivo(gerar_stream_grpc()):
                yield f"[{resp.tempo_etapa_ms:.1f}ms] {resp.nome_etapa}\n"
        return StreamingResponse(ler_respostas(), media_type="text/plain")
    except grpc.RpcError as e:
        raise HTTPException(status_code=503, detail=f"Erro gRPC: {e.details()}")