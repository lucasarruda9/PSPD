"""
Gateway P' (versao espelho REST/JSON do Modulo P).

Expoe os MESMOS 4 endpoints do gateway gRPC (mesmos paths e formatos de
resposta), mas conversa com os servidores A' (:9001) e B' (:9002) por HTTP/JSON
em vez de gRPC. O DICOM trafega em base64.
"""
import base64
import json
import os

import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

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

# Cliente HTTP persistente (reusa conexoes/keep-alive), criado no startup.
# Espelha a decisao do gateway gRPC de reusar canais -> comparativo justo.
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


@app.get("/", include_in_schema=False)
def index():
    return {"servico": "Gateway P' (REST mirror)", "servidor_a": REST_SERVER_A, "servidor_b": REST_SERVER_B}


@app.get("/health")
def health_check():
    return {"status": "ok", "rest_server_a": REST_SERVER_A, "rest_server_b": REST_SERVER_B}


# unary: encaminha 1 imagem para o A' (/anonymize) e devolve o resumo.
@app.post("/api/unary/processar-imagem")
async def processar_imagem_unary(arquivo: UploadFile = File(...)):
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
    return {
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


# os endpoints de streaming consomem o NDJSON do B' e repassam linha a linha.
@app.post("/api/server-stream/processar-etapas")
async def processar_etapas_stream(arquivo: UploadFile = File(...)):
    payload = {"exam_id": arquivo.filename}

    async def gerar_respostas():
        async with cliente.stream("POST", f"{REST_SERVER_B}/process-exam", json=payload, timeout=None) as resp:
            async for linha in resp.aiter_lines():
                if not linha.strip():
                    continue
                obj = json.loads(linha)
                tamanho = len(base64.b64decode(obj["data_b64"]))
                yield f"Processado Slice [{obj['slice_id']}] - {tamanho} bytes\n"

    return StreamingResponse(gerar_respostas(), media_type="text/plain")


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
async def processar_preview_bidirecional(arquivos: list[UploadFile] = File(...)):
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
                yield f"[{obj['slice_id']}] Etapa: {obj['stage']}\n"

    return StreamingResponse(ler_respostas(), media_type="text/plain")
