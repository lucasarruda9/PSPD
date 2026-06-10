import base64
import io
import json
import os

import httpx
import pydicom
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from PIL import Image

app = FastAPI(title="Gateway REST Mirror (Modulo P')", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

REST_SERVER_A = os.getenv("REST_SERVER_A", "http://localhost:9001")
REST_SERVER_B = os.getenv("REST_SERVER_B", "http://localhost:9002")

cliente: httpx.AsyncClient = None


@app.on_event("startup")
async def startup_event():
    global cliente
    cliente = httpx.AsyncClient(timeout=httpx.Timeout(60.0))
    print("✓ Cliente HTTP persistente inicializado")


@app.on_event("shutdown")
async def shutdown_event():
    if cliente:
        await cliente.aclose()


def b64(dados: bytes) -> str:
    return base64.b64encode(dados).decode("ascii")


def _dicom_para_png_b64(dados: bytes):
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


@app.get("/", include_in_schema=False)
def index():
    return {"servico": "Gateway P' (REST mirror)", "servidor_a": REST_SERVER_A, "servidor_b": REST_SERVER_B}


@app.get("/health")
def health_check():
    return {"status": "ok", "rest_server_a": REST_SERVER_A, "rest_server_b": REST_SERVER_B}

@app.post("/api/unary/processar-imagem")
async def processar_imagem_unary(arquivo: UploadFile = File(...), preview: bool = False):
    conteudo = await arquivo.read()
    payload = {"slice_id": arquivo.filename, "index": 1, "data_b64": b64(conteudo)}
    try:
        resp = await cliente.post(f"{REST_SERVER_A}/anonymize", json=payload)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=503, detail=f"Erro REST (A'): {e}")

    dados = resp.json()
    saida = base64.b64decode(dados["data_b64"])
    meta = dados["metadata"]
    resposta = {
        "tipo": "unary",
        "servidor": "A' (Anonymizer REST)",
        "arquivo": dados["slice_id"],
        "tamanho_entrada_bytes": len(conteudo),
        "tamanho_saida_bytes": len(saida),
        "metadados": {
            "modalidade": meta["modality"],
            "resolucao": f'{meta["rows"]}x{meta["columns"]}',
            "tags_removidas": meta["removed_phi_tags"],
        },
    }
    if preview:
        resposta["phi_antes"] = _phi(conteudo)
        resposta["phi_depois"] = _phi(saida)
        resposta["preview_antes_b64"] = _dicom_para_png_b64(conteudo)
        resposta["preview_depois_b64"] = _dicom_para_png_b64(saida)
        resposta["resultado_dcm_b64"] = dados["data_b64"]
    return resposta


def _series_uid(dados: bytes) -> str:
    try:
        ds = pydicom.dcmread(io.BytesIO(dados), force=True, stop_before_pixels=True)
        return str(ds.get("SeriesInstanceUID", ""))
    except Exception:
        return ""


@app.post("/api/server-stream/processar-etapas")
async def processar_etapas_stream(arquivo: UploadFile = File(...), preview: bool = False):
    conteudo = await arquivo.read()
    payload = {"exam_id": _series_uid(conteudo) or arquivo.filename}

    async def gerar_respostas():
        async with cliente.stream("POST", f"{REST_SERVER_B}/process-exam", json=payload, timeout=None) as resp:
            async for linha in resp.aiter_lines():
                if not linha.strip():
                    continue
                obj = json.loads(linha)
                dados_slice = base64.b64decode(obj["data_b64"])
                if preview:
                    yield json.dumps({
                        "slice_id": obj["slice_id"],
                        "bytes": len(dados_slice),
                        "png_b64": _dicom_para_png_b64(dados_slice),
                    }) + "\n"
                else:
                    yield f"Processado Slice [{obj['slice_id']}] - {len(dados_slice)} bytes\n"

    midia = "application/x-ndjson" if preview else "text/plain"
    return StreamingResponse(gerar_respostas(), media_type=midia)


@app.post("/api/enhance/processar-imagem")
async def processar_enhance_unary(arquivo: UploadFile = File(...), preview: bool = False,
                                  contraste: bool = True, brilho: bool = False, inverter: bool = False):
    conteudo = await arquivo.read()
    payload = {"slice_id": arquivo.filename, "index": 1, "data_b64": b64(conteudo),
               "apply_clahe": contraste, "apply_normalize": brilho, "apply_denoise": inverter}
    try:
        resp = await cliente.post(f"{REST_SERVER_B}/enhance", json=payload)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=503, detail=f"Erro REST (B'): {e}")

    dados = resp.json()
    saida = base64.b64decode(dados["data_b64"])
    resposta = {
        "tipo": "enhance",
        "servidor": "B' (Enhancer REST)",
        "arquivo": dados["slice_id"],
        "tamanho_entrada_bytes": len(conteudo),
        "tamanho_saida_bytes": len(saida),
    }
    if preview:
        resposta["preview_antes_b64"] = _dicom_para_png_b64(conteudo)
        resposta["preview_depois_b64"] = _dicom_para_png_b64(saida)
        resposta["resultado_dcm_b64"] = dados["data_b64"]
    return resposta


@app.post("/api/client-stream/processar-lote")
async def processar_lote_cliente(arquivos: list[UploadFile] = File(...)):
    slices = []
    for idx, arq in enumerate(arquivos):
        conteudo = await arq.read()
        slices.append({"slice_id": arq.filename, "index": idx, "data_b64": b64(conteudo)})

    try:
        resp = await cliente.post(f"{REST_SERVER_B}/upload-exam", json={"slices": slices})
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=503, detail=f"Erro REST (B'): {e}")

    dados = resp.json()
    return {
        "tipo": "client_streaming",
        "servidor": "B' (Pipeline REST)",
        "exam_id": dados["exam_id"],
        "total_enviados": len(arquivos),
        "slices_ok": dados["slices_ok"],
    }


@app.post("/api/bidirecional/preview-ao-vivo")
async def processar_preview_bidirecional(arquivos: list[UploadFile] = File(...), preview: bool = False):
    slices = []
    for idx, arq in enumerate(arquivos):
        conteudo = await arq.read()
        slices.append({"slice_id": arq.filename, "index": idx, "data_b64": b64(conteudo)})

    async def ler_respostas():
        async with cliente.stream("POST", f"{REST_SERVER_B}/live-process", json={"slices": slices}, timeout=None) as resp:
            async for linha in resp.aiter_lines():
                if not linha.strip():
                    continue
                obj = json.loads(linha)
                if preview:
                    png = _dicom_para_png_b64(base64.b64decode(obj["data_b64"])) if obj.get("data_b64") else None
                    yield json.dumps({"slice_id": obj["slice_id"], "stage": obj["stage"], "png_b64": png}) + "\n"
                else:
                    yield f"[{obj['slice_id']}] Etapa: {obj['stage']}\n"

    midia = "application/x-ndjson" if preview else "text/plain"
    return StreamingResponse(ler_respostas(), media_type=midia)
