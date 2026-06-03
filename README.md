# PSPD - Pipeline de Processamento de Imagens Médicas

## Como Rodar Localmente (Docker)

Para rodar a infraestrutura de desenvolvimento contendo o Gateway gRPC, basta executar o comando abaixo na pasta raiz do projeto:

```bash
docker compose up --build
```

O servidor do Gateway (Módulo P) estará disponível em:
- **Swagger UI:** [http://localhost:8000/docs](http://localhost:8000/docs)

*(Ainda tá faltando os módulos A, B e REST Mirror serão adicionados futuramente ao `docker-compose.yml` quando seus respectivos códigos forem entregues).*

---

## Como Fazer Deploy no Kubernetes (Minikube)

Para provisionar o ambiente completo de produção (incluindo Prometheus, Grafana e Auto-scaling), execute:

```bash
bash infra/scripts/setup-cluster.sh
```

As URLs de acesso aos painéis de monitoramento serão exibidas no terminal ao final do script.

---

## Desenvolvimento Local

Se você precisar rodar ou debugar o Gateway localmente **fora do Docker**, o projeto usa o gerenciador de pacotes **`uv`** (mais rápido que pip).

1. **Instale o uv** na sua máquina (se não tiver):
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **Instale as dependências** na pasta `modulo_p_gateway`:
   ```bash
   cd modulo_p_gateway
   uv sync
   ```
   *(Isso criará automaticamente o ambiente virtual `.venv` e o arquivo `uv.lock` na sua máquina local).*

3. **Gere os stubs do gRPC:**
   ```bash
   uv run python -m grpc_tools.protoc -I../proto --python_out=. --grpc_python_out=. ../proto/image_processing.proto
   ```

4. **Rode o servidor:**
   ```bash
   uv run uvicorn main:app --reload --port 8000
   ```

## Como Testar a Aplicação Localmente

Após realizar a configuração do Desenvolvimento Local, você pode validar o funcionamento das comunicações gRPC e da API Web seguindo os passos abaixo:

### 1. Testes Iniciais do gRPC

Para validar os 4 tipos de chamadas gRPC (Unary, Server Streaming, Client Streaming e Bidirectional Streaming), utilizamos um servidor mock.

Abra dois terminais na pasta `modulo_p_gateway`:

**Terminal 1 (Servidor de Teste):**
Inicie o mock server que vai escutar as requisições gRPC:

```bash
uv run python mock_server.py
```

(O terminal ficará aguardando conexões na porta 50051).

**Terminal 2 (Cliente / Stub):**
Execute o script de testes para disparar as requisições:

```bash
uv run python teste_grpc_b1.py
```

Você verá no console as mensagens de "Sucesso" comprovando que as chamadas foram realizadas e os dados foram processados com êxito.

### 2. Testando a API Gateway (Módulo P)

Com o `mock_server.py` ainda rodando no Terminal 1, você pode testar a interface Web do Gateway que converte as chamadas REST em gRPC.

No Terminal 2, suba o servidor FastAPI:

```bash
uv run uvicorn main:app --reload --port 8000
```

Abra o seu navegador e acesse o painel interativo: http://localhost:8000/docs

Na interface do Swagger, expanda qualquer uma das rotas (ex: POST `/api/unary/processar-imagem`).

1. Clique no botão "Try it out" (Testar).
2. No campo de arquivo, clique em "Escolher arquivo" e selecione qualquer imagem do seu computador.
3. Clique no botão azul "Execute".
4. Observe na seção inferior ("Server response") o retorno com Code 200 e o JSON processado pelo backend gRPC!