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