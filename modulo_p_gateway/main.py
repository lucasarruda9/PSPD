from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
import grpc
import time

import image_processing_pb2
import image_processing_pb2_grpc

app = FastAPI(title="Gateway Módulo P - Processamento de Imagem")

import os
GRPC_SERVER_A = os.getenv('GRPC_SERVER_A', 'localhost:50051')
GRPC_SERVER_B = os.getenv('GRPC_SERVER_B', 'localhost:50052')

def get_grpc_stub(target_server):
    canal = grpc.insecure_channel(target_server)
    return image_processing_pb2_grpc.ImageProcessorServiceStub(canal)
@app.get("/")
def health_check():
    return {"status": "ok", "grpc_a": GRPC_SERVER_A, "grpc_b": GRPC_SERVER_B}

# Endpoint para streaming unary
@app.post("/api/unary/processar-imagem")
async def processar_imagem_unary(arquivo: UploadFile = File(...)):
    stub = get_grpc_stub(GRPC_SERVER_A)
    conteudo = await arquivo.read()
    req = image_processing_pb2.ImagemRequest(
        dados_imagem=conteudo, formato=arquivo.filename.split('.')[-1], nome_arquivo=arquivo.filename
    )
    resp = stub.ProcessarImagem(req)
    return {"mensagem": "Sucesso", "tempo_ms": resp.tempo_ms}

# Endpoint para streaming servidor
@app.post("/api/server-stream/processar-etapas")
async def processar_etapas_stream(arquivo: UploadFile = File(...)):
    stub = get_grpc_stub(GRPC_SERVER_A)
    conteudo = await arquivo.read()
    req = image_processing_pb2.ImagemRequest(
        dados_imagem=conteudo, formato=arquivo.filename.split('.')[-1], nome_arquivo=arquivo.filename
    )
    def gerar_respostas_http():
        for resposta in stub.ProcessarEtapas(req):
            yield f"Etapa concluída: {resposta.nome_etapa}\n"
    return StreamingResponse(gerar_respostas_http(), media_type="text/plain")

# Endpoint para streaming cliente
@app.post("/api/client-stream/processar-lote")
async def processar_lote_cliente(arquivos: list[UploadFile] = File(...)):
    stub = get_grpc_stub(GRPC_SERVER_B)
    def gerar_stream_grpc():
        for arq in arquivos:
            yield image_processing_pb2.ImagemRequest(
                dados_imagem=arq.file.read(), formato=arq.filename.split('.')[-1], nome_arquivo=arq.filename
            )
    resp = stub.ProcessarLote(gerar_stream_grpc())
    return {"total_processadas": resp.total_processadas, "tempo_total_ms": resp.tempo_total_ms}

# Endpoint para streaming bidirecional
@app.post("/api/bidirecional/preview-ao-vivo")
async def processar_preview_bidirecional(arquivos: list[UploadFile] = File(...)):
    stub = get_grpc_stub(GRPC_SERVER_B)
    def gerar_stream_grpc():
        for arq in arquivos:
            yield image_processing_pb2.ImagemRequest(
                dados_imagem=arq.file.read(), formato=arq.filename.split('.')[-1], nome_arquivo=arq.filename
            )
    def ler_respostas_bidirecionais():
        for resposta in stub.ProcessarPreviewAoVivo(gerar_stream_grpc()):
            yield f"Preview atualizado: {resposta.nome_etapa}\n"
    return StreamingResponse(ler_respostas_bidirecionais(), media_type="text/plain")