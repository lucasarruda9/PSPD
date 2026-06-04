FROM python:3.12-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

COPY modulo_p_gateway/pyproject.toml .
RUN uv sync --no-dev

COPY Servidores_GRPC/medimg.proto ./proto/medimg.proto
RUN uv run python -m grpc_tools.protoc \
    -I./proto \
    --python_out=. \
    --grpc_python_out=. \
    proto/medimg.proto

COPY modulo_p_gateway/ .

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
