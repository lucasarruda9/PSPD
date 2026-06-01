# PSPD - Gateway Módulo P (API REST -> gRPC)

Este repositório contém a implementação do Módulo P, que atua como um API Gateway. Ele recebe requisições HTTP (REST/JSON) externas e as traduz em chamadas gRPC para os Servidores Internos (Módulos A e B).

## Tecnologias Utilizadas
* **Linguagem:** Python 3
* **Framework Web:** FastAPI
* **Comunicação:** gRPC e Protocol Buffers

## Como rodar o projeto localmente

1. Instale e configure as dependências:
```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv -y
python3 -m venv venv
source venv/bin/activate
pip install fastapi uvicorn grpcio grpcio-tools pydantic

```

2. Rode o servidor Web (FastAPI):

```bash
cd modulo_p_gateway
python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. service.proto
uvicorn main:app --reload

```

3. Acesse:
```bash
http://localhost:8000/docs
```
## Onde mexer e o que alterar?

Mexer só no arquivo main e service, os outros 2 são gerados pelo service.proto. Além disso, sempre que mexer no service.proto, rodar:

```bash
python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. service.proto

```
Obs.: Nunca edite os arquivos `_pb2.py`.