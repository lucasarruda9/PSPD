from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import grpc.aio
from pathlib import Path
import asyncio
import base64
import io
import json
import time
import os

import pydicom
from PIL import Image

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

def get_enhancer_stub():
    return medimg_pb2_grpc.EnhancerStub(_canal_b)

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

def _dicom_para_png_b64(dados: bytes):
    """Renderiza os pixels de um DICOM em PNG (base64) para preview; None se falhar."""
    try:
        import numpy as np
        ds = pydicom.dcmread(io.BytesIO(dados), force=True)
        arr = ds.pixel_array.astype("float32")
        vmin, vmax = None, None
        if 'WindowCenter' in ds and 'WindowWidth' in ds:
            wc = ds.WindowCenter
            ww = ds.WindowWidth
            if isinstance(wc, pydicom.multival.MultiValue): wc = float(wc[0])
            else: wc = float(wc)
            if isinstance(ww, pydicom.multival.MultiValue): ww = float(ww[0])
            else: ww = float(ww)
            vmin = wc - ww / 2.0
            vmax = wc + ww / 2.0
        if vmin is None or vmax is None:
            vmin = arr.min()
            vmax = arr.max()
        arr = np.clip(arr, vmin, vmax)
        arr -= vmin
        topo = float(vmax - vmin)
        if topo > 0:
            arr = arr / topo * 255.0
        imagem = Image.fromarray(arr.astype("uint8"))
        buf = io.BytesIO()
        imagem.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception as e:
        print(f"[preview] falha ao renderizar PNG: {e}")
        return None


def _phi(dados: bytes):
    """Extrai algumas tags de PHI de um DICOM, para mostrar o antes/depois."""
    try:
        ds = pydicom.dcmread(io.BytesIO(dados), force=True)
        return {
            "PatientName": str(ds.get("PatientName", "")),
            "PatientID": str(ds.get("PatientID", "")),
            "PatientBirthDate": str(ds.get("PatientBirthDate", "")),
            "StudyDate": str(ds.get("StudyDate", "")),
        }
    except Exception:
        return {}


def _series_uid(dados: bytes) -> str:
    """Le o SeriesInstanceUID do DICOM, usado como exam_id no server streaming."""
    try:
        ds = pydicom.dcmread(io.BytesIO(dados), force=True, stop_before_pixels=True)
        return str(ds.get("SeriesInstanceUID", ""))
    except Exception:
        return ""


@app.post("/api/unary/processar-imagem")
async def processar_imagem_unary(arquivo: UploadFile = File(...), preview: bool = False):
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
        
        resposta = {
            "tipo": "unary",
            "servidor": "A (Anonymizer)",
            "arquivo": resp.slice.slice_id,
            "tamanho_entrada_bytes": len(conteudo),
            "tamanho_saida_bytes": len(resp.slice.data),
            "metadados": {
                "modalidade": resp.metadata.modality,
                "resolucao": f"{resp.metadata.rows}x{resp.metadata.columns}",
                "tags_removidas": list(resp.metadata.removed_phi_tags)
            },
        }
        if preview:
            resposta["phi_antes"] = _phi(conteudo)
            resposta["phi_depois"] = _phi(resp.slice.data)
            resposta["preview_antes_b64"] = _dicom_para_png_b64(conteudo)
            resposta["preview_depois_b64"] = _dicom_para_png_b64(resp.slice.data)
            resposta["resultado_dcm_b64"] = base64.b64encode(resp.slice.data).decode("ascii")
        return resposta
    except grpc.aio.AioRpcError as e:
        raise HTTPException(status_code=503, detail=f"Erro gRPC: {e.details()}")

@app.post("/api/enhance/processar-imagem")
async def processar_enhance_unary(arquivo: UploadFile = File(...), preview: bool = False,
                                  contraste: bool = True, brilho: bool = False, inverter: bool = False):
    try:
        stub = get_enhancer_stub()
        conteudo = await arquivo.read()
        req = medimg_pb2.EnhanceRequest(
            slice=medimg_pb2.Slice(slice_id=arquivo.filename, index=1, data=conteudo),
            apply_clahe=contraste,
            apply_normalize=brilho,
            apply_denoise=inverter,
        )
        resp = await stub.Enhance(req)
        processado = resp.slice.data
        resposta = {
            "tipo": "enhance",
            "servidor": "B (Enhancer)",
            "arquivo": resp.slice.slice_id,
            "tamanho_entrada_bytes": len(conteudo),
            "tamanho_saida_bytes": len(processado),
        }
        if preview:
            resposta["preview_antes_b64"] = _dicom_para_png_b64(conteudo)
            resposta["preview_depois_b64"] = _dicom_para_png_b64(processado)
            resposta["resultado_dcm_b64"] = base64.b64encode(processado).decode("ascii")
        return resposta
    except grpc.aio.AioRpcError as e:
        raise HTTPException(status_code=503, detail=f"Erro gRPC: {e.details()}")

@app.post("/api/server-stream/processar-etapas")
async def processar_etapas_stream(arquivo: UploadFile = File(...), preview: bool = False):
    try:
        stub = get_pipeline_stub()
        conteudo = await arquivo.read()
        exam_id = _series_uid(conteudo) or arquivo.filename
        req = medimg_pb2.ExamRequest(exam_id=exam_id)
        
        async def gerar_respostas():
            async for resp in stub.ProcessExam(req):
                if preview:
                    yield json.dumps({
                        "slice_id": resp.slice.slice_id,
                        "bytes": len(resp.slice.data),
                        "png_b64": _dicom_para_png_b64(resp.slice.data),
                    }) + "\n"
                else:
                    yield f"Processado Slice [{resp.slice.slice_id}] - {len(resp.slice.data)} bytes\n"

        midia = "application/x-ndjson" if preview else "text/plain"
        return StreamingResponse(gerar_respostas(), media_type=midia)
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
async def processar_preview_bidirecional(arquivos: list[UploadFile] = File(...), preview: bool = False):
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
                if preview:
                    yield json.dumps({"slice_id": resp.slice_id, "stage": resp.stage, "png_b64": _dicom_para_png_b64(resp.data)}) + "\n"
                else:
                    yield f"[{resp.slice_id}] Etapa: {resp.stage}\n"
                
        midia = "application/x-ndjson" if preview else "text/plain"
        return StreamingResponse(ler_respostas(), media_type=midia)
    except grpc.aio.AioRpcError as e:
        raise HTTPException(status_code=503, detail=f"Erro gRPC: {e.details()}")