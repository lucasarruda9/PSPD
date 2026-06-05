from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import grpc.aio
from pathlib import Path
import asyncio
import time
import os

import medimg_pb2
import medimg_pb2_grpc

app = FastAPI(title="Gateway Módulo P - Processamento de Imagens DICOM", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

GRPC_SERVER_A = os.getenv('GRPC_SERVER_A', 'localhost:50051')
GRPC_SERVER_B = os.getenv('GRPC_SERVER_B', 'localhost:50052')

STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

_canal_a = None
_canal_b = None

def get_anonymizer_stub():
    return medimg_pb2_grpc.AnonymizerStub(_canal_a)

def get_pipeline_stub():
    return medimg_pb2_grpc.PipelineStub(_canal_b)

@app.on_event("startup")
async def startup_event():
    global _canal_a, _canal_b
    _canal_a = grpc.aio.insecure_channel(GRPC_SERVER_A, options=[('grpc.lb_policy_name', 'round_robin')])
    _canal_b = grpc.aio.insecure_channel(GRPC_SERVER_B, options=[('grpc.lb_policy_name', 'round_robin')])
    print("✓ Canais gRPC Assíncronos inicializados")

@app.on_event("shutdown")
async def shutdown_event():
    if _canal_a:
        await _canal_a.close()
    if _canal_b:
        await _canal_b.close()

@app.get("/", include_in_schema=False)
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))

@app.get("/health")
def health_check():
    return {"status": "ok", "grpc_server_a": GRPC_SERVER_A, "grpc_server_b": GRPC_SERVER_B}

@app.post("/api/unary/processar-imagem")
async def processar_imagem_unary(arquivo: UploadFile = File(...)):
    try:
        stub = get_anonymizer_stub()
        conteudo = await arquivo.read()
        
        req = medimg_pb2.AnonymizeRequest(
            slice=medimg_pb2.Slice(
                slice_id=arquivo.filename,
                index=1,
                data=conteudo
            )
        )
        resp = await stub.Anonymize(req)
        
        return {
            "tipo": "unary",
            "servidor": "A (Anonymizer)",
            "arquivo": resp.slice.slice_id,
            "tamanho_entrada_bytes": len(conteudo),
            "tamanho_saida_bytes": len(resp.slice.data),
            "metadados": {
                "modalidade": resp.metadata.modality,
                "resolucao": f"{resp.metadata.rows}x{resp.metadata.columns}",
                "tags_removidas": list(resp.metadata.removed_phi_tags)
            }
        }
    except grpc.aio.AioRpcError as e:
        raise HTTPException(status_code=503, detail=f"Erro gRPC: {e.details()}")

@app.post("/api/server-stream/processar-etapas")
async def processar_etapas_stream(arquivo: UploadFile = File(...)):
    try:
        stub = get_pipeline_stub()
        req = medimg_pb2.ExamRequest(exam_id=arquivo.filename)
        
        async def gerar_respostas():
            async for resp in stub.ProcessExam(req):
                yield f"Processado Slice [{resp.slice.slice_id}] - {len(resp.slice.data)} bytes\n"
        
        return StreamingResponse(gerar_respostas(), media_type="text/plain")
    except grpc.aio.AioRpcError as e:
        raise HTTPException(status_code=503, detail=f"Erro gRPC: {e.details()}")

@app.post("/api/client-stream/processar-lote")
async def processar_lote_cliente(arquivos: list[UploadFile] = File(...)):
    try:
        stub = get_pipeline_stub()
        
        async def gerar_stream_grpc():
            for idx, arq in enumerate(arquivos):
                conteudo = await arq.read()
                yield medimg_pb2.Slice(
                    slice_id=arq.filename,
                    index=idx,
                    data=conteudo
                )
                
        resp = await stub.UploadExam(gerar_stream_grpc())
        return {
            "tipo": "client_streaming",
            "servidor": "B (Pipeline)",
            "exam_id": resp.exam_id,
            "total_enviados": len(arquivos),
            "slices_ok": resp.slices_ok
        }
    except grpc.aio.AioRpcError as e:
        raise HTTPException(status_code=503, detail=f"Erro gRPC: {e.details()}")

@app.post("/api/bidirecional/preview-ao-vivo")
async def processar_preview_bidirecional(arquivos: list[UploadFile] = File(...)):
    try:
        stub = get_pipeline_stub()
        
        async def gerar_stream_grpc():
            for idx, arq in enumerate(arquivos):
                conteudo = await arq.read()
                yield medimg_pb2.Slice(
                    slice_id=arq.filename,
                    index=idx,
                    data=conteudo
                )
                
        async def ler_respostas():
            async for resp in stub.LiveProcess(gerar_stream_grpc()):
                yield f"[{resp.slice_id}] Etapa: {resp.stage}\n"
                
        return StreamingResponse(ler_respostas(), media_type="text/plain")
    except grpc.aio.AioRpcError as e:
        raise HTTPException(status_code=503, detail=f"Erro gRPC: {e.details()}")