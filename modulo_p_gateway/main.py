from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
import grpc

import service_pb2
import service_pb2_grpc

#inicializa o aplicativo FastAPI
app = FastAPI(title="Gateway Módulo P - Etapa 1") ##Muda aqui dps

#define o endereço do servidor gRPC
GRPC_SERVER_ADDRESS = 'localhost:50051'

#define a estrutura do JSON
class RestRequest(BaseModel):
    texto: str
    complexidade: int

#define uma estrutura contendo uma lista
class MultiRestRequest(BaseModel):
    pedidos: List[RestRequest]

#ROTAS DA API REST
#unary: cliente envia uma única mensagem para o servidor, que processa a mensagem e retorna uma única resposta
@app.post("/1-unary")
def teste_unary(req: RestRequest):
    try:
        #cria um canal de comunicação com o servidor gRPC e um stub para chamar os métodos definidos no serviço
        with grpc.insecure_channel(GRPC_SERVER_ADDRESS) as channel:
            stub = service_pb2_grpc.ProcessadorServiceStub(channel)
            grpc_request = service_pb2.DadosRequest(payload=req.texto, nivel_complexidade=req.complexidade)
            grpc_response = stub.ProcessarDados(grpc_request)
            return {"resultado": grpc_response.resultado, 
                    "tempo_ms": grpc_response.tempo_processamento_ms}
    except grpc.RpcError as e:
        #caso de erro na comunicação gRPC, captura a exceção e retorna um erro HTTP 500
        raise HTTPException(status_code=500, detail=str(e.details()))

#server streaming: cliente envia uma única mensagem para o servidor, que responde com uma sequencia de mensagens
@app.post("/2-server-streaming")
def teste_server_streaming(req: RestRequest):
    try:
        with grpc.insecure_channel(GRPC_SERVER_ADDRESS) as channel:
            stub = service_pb2_grpc.ProcessadorServiceStub(channel)
            grpc_request = service_pb2.DadosRequest(payload=req.texto, nivel_complexidade=req.complexidade)
            respostas = []
            for grpc_response in stub.ProcessarStreamServidor(grpc_request):
                respostas.append({"resultado": grpc_response.resultado, "tempo_ms": grpc_response.tempo_processamento_ms})
            return {"resultados_stream": respostas}
    except grpc.RpcError as e:
        raise HTTPException(status_code=500, detail=str(e.details()))

#cliente streaming: cliente envia uma sequência de mensagens para o servidor, 
#que processa cada mensagem e retorna uma resposta final após receber todas as mensagens do cliente
@app.post("/3-client-streaming")
def teste_client_streaming(req: MultiRestRequest):
    try:
        with grpc.insecure_channel(GRPC_SERVER_ADDRESS) as channel:
            stub = service_pb2_grpc.ProcessadorServiceStub(channel)
            def gerar_pedidos():
                for pedido in req.pedidos:
                    yield service_pb2.DadosRequest(payload=pedido.texto, nivel_complexidade=pedido.complexidade)
            grpc_response = stub.ProcessarStreamCliente(gerar_pedidos())
            return {"resultado_final": grpc_response.resultado, "tempo_ms": grpc_response.tempo_processamento_ms}
    except grpc.RpcError as e:
        raise HTTPException(status_code=500, detail=str(e.details()))

#bidirecional: cliente e servidor trocam mensagens em tempo real
@app.post("/4-bidirecional")
def teste_bidirecional(req: MultiRestRequest):
    try:
        with grpc.insecure_channel(GRPC_SERVER_ADDRESS) as channel:
            stub = service_pb2_grpc.ProcessadorServiceStub(channel)
            def gerar_pedidos():
                for pedido in req.pedidos:
                    yield service_pb2.DadosRequest(payload=pedido.texto, nivel_complexidade=pedido.complexidade)
            respostas = []
            for grpc_response in stub.ProcessarStreamBidirecional(gerar_pedidos()):
                respostas.append({"resultado": grpc_response.resultado, "tempo_ms": grpc_response.tempo_processamento_ms})
            return {"resultados_bidirecionais": respostas}
    except grpc.RpcError as e:
        raise HTTPException(status_code=500, detail=str(e.details()))