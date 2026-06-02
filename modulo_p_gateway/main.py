from fastapi import FastAPI, HTTPException, UploadFile, File
import grpc
import time

import image_processing_pb2
import image_processing_pb2_grpc

app = FastAPI(title="Gateway Módulo P - Processamento de Imagem")

import os
GRPC_SERVER_A = os.getenv('GRPC_SERVER_A', 'localhost:50051')
GRPC_SERVER_B = os.getenv('GRPC_SERVER_B', 'localhost:50052')

@app.get("/")
def health_check():
    return {"status": "ok", "grpc_a": GRPC_SERVER_A, "grpc_b": GRPC_SERVER_B}

@app.post("/processar-imagem")
async def processar_imagem(arquivo: UploadFile = File(...)):
    # usar image_processing_pb2 e image_processing_pb2_grpc
    return {"mensagem": "troque para uma chama gRPC real"}

# falta implementar as 4 tipos de chamadas gRPC
# Unary, Server Streaming, Client Streaming, Bidirecional