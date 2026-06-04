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

Execute o script de inicialização automática na pasta raiz do projeto:

```bash
.\run_local.ps1
```

### Navegue para modulo_p_gateway e execute:
```bash
cd modulo_p_gateway
uv run python mock_server.py &
uv run uvicorn main:app --reload --port 8000
```

Isso iniciará automaticamente:
1. Mock server gRPC nas portas 50051 (Server A) e 50052 (Server B)
2. Gateway FastAPI na porta 8000 (aguarda os servidores gRPC estarem prontos)

### Testando a Interface Web

Após iniciar o servidor, abra seu navegador e acesse:

```
http://localhost:8000
```

Você verá a interface interativa com 4 cards representando cada padrão de comunicação gRPC:

- **Unary**: 1 imagem → 1 resposta (Server A)
- **Server Streaming**: 1 imagem → múltiplas etapas (Server A)
- **Client Streaming**: múltiplas imagens → 1 resumo (Server B)
- **Bidirecional**: múltiplas imagens ↔ stream de previews (Server B)

### Testando via Swagger API

Também pode acessar a documentação interativa em:

```
http://localhost:8000/docs
```

E testar manualmente cada endpoint expandindo as rotas e clicando em "Try it out".