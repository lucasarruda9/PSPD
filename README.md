# Trabalho de PSPD
## Pipeline Distribuído de Processamento de Imagens Médicas (DICOM)

**Universidade de Brasília — FCTE — Engenharia de Software** <br>
**Disciplina: PSPD — Programação para Sistemas Paralelos e Distribuídos** <br>
**Professor: Fernando W. Cruz**

### Grupo

| Integrante | Matrícula | Frente de trabalho |
|---|---|---|
| Artur Mendonça Arruda | 231033737 | Infraestrutura DevOps — Docker, Kubernetes/Minikube e extras de infra |
| Ester Flores Lino da Silva | 202063201 | Qualidade, Benchmark & Relatório — versão REST/JSON e testes de carga |
| João Pedro Costa | 190030801 | Gateway & Web — Módulo P (web server / REST-API + gRPC Stub) |
| Lucas Mendonça Arruda | 231035464 | Microsserviços gRPC — arquivo `.proto` e servidores A e B |

---

## Sobre o trabalho

Construímos uma aplicação distribuída para **processamento de imagens médicas DICOM**, organizada em três módulos:

- **Módulo P (Gateway):** web server em Python/FastAPI que recebe as requisições HTTP do navegador e as repassa ao backend.
- **Módulo A (Anonimização):** servidor em Go que remove os dados de paciente (PHI) do arquivo DICOM.
- **Módulo B (Pipeline):** servidor em Go que aplica filtros de realce (contraste, brilho) nas imagens.

O backend contém os **4 tipos de comunicação gRPC** (unary, server streaming, client streaming e bidirecional). Para fins de comparação, o projeto traz **duas versões da mesma aplicação**:

- **Versão gRPC**: diálogo P ↔ A/B via gRPC (porta **8000**).
- **Versão REST/JSON** (espelho): mesma aplicação, com o diálogo P ↔ A/B via HTTP/JSON (porta **8001**).

```
Navegador ──HTTP──▶ Gateway P ──▶ Servidor A (anonimização)
                              └──▶ Servidor B (realce / pipeline)
```

---

## Pré-requisitos

- **Docker** e **Docker Compose** — para subir o ambiente. Guia oficial: https://docs.docker.com/engine/install/
- **curl** — usado nos testes e no benchmark:
  ```bash
  sudo apt install -y curl
  ```
- **ab (Apache Benchmark)** ou **hey** — gerador de carga do benchmark:
  ```bash
  sudo apt install -y apache2-utils
  ```
- **uv** — executa os scripts Python (geração de amostra e teste B.1) sem precisar instalar pacotes manualmente:
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
- **python3** — usado pelo script de download do dataset (já presente na maioria das distribuições Linux):
  ```bash
  sudo apt install -y python3
  ```
- **minikube** e **kubectl** — apenas para o deploy opcional em Kubernetes:
  - minikube: https://minikube.sigs.k8s.io/docs/start/
  - kubectl: https://kubernetes.io/docs/tasks/tools/

---

## Como rodar (Docker Compose)

Na raiz do projeto:

```bash
docker compose up --build
```

Isso sobe o ambiente completo (as duas versões de uma vez):

| Serviço | Acesso |
|---|---|
| Gateway **gRPC** (Módulo P) | http://localhost:8000 |
| Gateway **REST** (espelho P') | http://localhost:8001 |
| Servidores gRPC A / B | localhost:50051 / 50052 (usados pelo teste B.1) |
| Servidores REST A' / B' | apenas rede interna |

A interface web fica em **http://localhost:8000**, e a documentação interativa das APIs (Swagger) em **http://localhost:8000/docs** (gRPC) e **http://localhost:8001/docs** (REST).

Para encerrar o ambiente:

```bash
docker compose down
```

### Kubernetes (Minikube) — opcional

Os manifestos estão em [`infra/`](infra/). O provisionamento do cluster local é feito por um único script:

```bash
bash infra/scripts/setup-minikube.sh
```

Ele sobe um cluster Minikube com **3 nós**, builda e carrega as imagens dos seis serviços, aplica todos os módulos (gRPC e REST), o **autoscaling (HPA)** dos servidores A e B e o **monitoramento (Prometheus + Grafana)**. Ao final, imprime as URLs de acesso aos gateways e aos painéis.

> Requer **minikube** e **kubectl** instalados (ver Pré-requisitos).

---

## Baixar o dataset de imagens

As imagens de teste vêm da coleção **Pseudo-PHI-DICOM-Data** do **TCIA** (imagens reais com dados de paciente sintéticos, próprias para testar anonimização). Para baixar:

```bash
python3 benchmarks/baixar_tcia.py                  # 3 séries (padrão)
TCIA_SERIES=10 python3 benchmarks/baixar_tcia.py   # mais séries = mais imagens
```

Cada **série** é um exame com **várias fatias** (`.dcm`). O script baixa `TCIA_SERIES` séries e prepara:

- `benchmarks/dataset/serieNN/` — uma **pasta por exame**, com suas fatias;
- `benchmarks/amostra.dcm` — uma fatia avulsa (para o teste unary);
- `benchmarks/dataset/fatia1.dcm` e `fatia2.dcm` — fallback do Server Streaming.

> Os arquivos DICOM **não** vão para o repositório (são grandes e têm licença do TCIA). Caso não queira baixar, o benchmark gera uma amostra sintética automaticamente.

---

## Como testar

### 1. Pela interface web

Abra **http://localhost:8000**. No topo há um seletor **gRPC | REST** que escolhe qual backend a interface vai chamar, assim é possível comparar as duas versões na mesma tela.

Cada card representa um tipo de comunicação. Arraste um (ou mais) arquivo `.dcm` de `benchmarks/dataset/` para o card e clique em executar:

| Card | Módulo | Quantos arquivos |
|---|---|---|
| **Unary** | A (anonimização) | 1 arquivo |
| **Server Streaming** | B (pipeline) | 1 arquivo *(ver observação)* |
| **Client Streaming** | B (pipeline) | 2 ou mais |
| **Bidirecional** | B (pipeline) | 2 ou mais |

> **Observação sobre o Server Streaming:** ao subir uma fatia, o gateway lê o `SeriesInstanceUID` dela e o servidor B devolve em fluxo as **outras fatias do mesmo exame** (até 8), a partir de um índice que monta do `dataset/` no startup. Por isso a fatia enviada não volta sozinha — volta o exame ao qual ela pertence. Se a fatia não estiver no dataset, usa o fallback `fatia1.dcm`/`fatia2.dcm`.

O mesmo arquivo DICOM serve para qualquer card, só respeite a quantidade indicada.

No card **Unary**, o resultado mostra a imagem **antes e depois**, os **dados do paciente anonimizados** (ex.: `DOE^JOHN → Anonimo_1`) e um botão para **baixar o DICOM processado**. O **Server Streaming** exibe as fatias do exame já filtradas.

### 2. Benchmark (gRPC vs REST)

#### Local

Com o ambiente no ar:

```bash
bash benchmarks/run_benchmark.sh
```

O script mede o tempo de resposta das duas versões nos 4 endpoints, sob a mesma carga, e grava uma tabela em `benchmarks/resultados/comparativo.md`. Parâmetros podem ser ajustados por variáveis de ambiente, por exemplo:

```bash
REQUISICOES=500 CONCORRENCIA=50 bash benchmarks/run_benchmark.sh
```

#### Kubernetes(Minikube)

Para executar o benchmark com Minikube, você deve conectar o teste aos IPs isolados do cluster. Isso pode ser feito de três formas diferentes:

* **Forma 1 (Expondo as portas com Port-Forward):**
Se a rede do seu terminal não enxergar o IP interno do Minikube, você pode abrir **dois terminais auxiliares** e fazer um túnel direto para o seu `localhost`.
No terminal 1: `kubectl port-forward service/modulo-p-gateway -n pspd 8000:8000`
No terminal 2: `kubectl port-forward service/modulo-rest-mirror -n pspd 8001:8001`
Em seguida, volte ao terminal principal e rode o script puro: `bash benchmarks/run_benchmark.sh`

* **Forma 2 (Comando único em um terminal):**
Em vez de abrir terminais extras, passe as variáveis e injete as URLs dinamicamente na mesma linha usando o Minikube:
```bash
GRPC_URL=$(minikube.exe service modulo-p-gateway -n pspd --url | head -n 1 | tr -d '\r') \
REST_URL=$(minikube.exe service modulo-rest-mirror -n pspd --url | head -n 1 | tr -d '\r') \
bash benchmarks/run_benchmark.sh
```
*(No Linux/Mac puro, use apenas `minikube` em vez de `minikube.exe`)*

* **Forma 3 (Modificando o script base):**
Abra o arquivo `benchmarks/run_benchmark.sh` e altere manualmente as variáveis de URL no topo do arquivo para apontar para o IP e a porta que o minikube forneceu. Depois, rode o script normalmente.

### 3. Testes dos 4 tipos de chamada gRPC (Atividade B.1)

Com os servidores no ar e uma amostra disponível:

```bash
cd modulo_p_gateway
uv run python -m grpc_tools.protoc -I../Servidores_GRPC \
    --python_out=. --grpc_python_out=. ../Servidores_GRPC/medimg.proto
uv run python teste_grpc_b1.py
```

Esse teste executa, em sequência, os quatro tipos de comunicação gRPC contra os servidores reais.

---

## Estrutura do projeto

```
modulo_p_gateway/      Gateway P (Python/FastAPI) + interface web
Servidores_GRPC/       Servidores A e B em Go + arquivo medimg.proto
modulo_rest_mirror/    Versão espelho REST/JSON (gateway P' + servidores A'/B')
benchmarks/            Scripts de benchmark e de download/geração das amostras
infra/                 Manifestos Kubernetes e script de provisionamento
```

---

## Histórico de versão

| Versão | Data | Principais mudanças |
|---|---|---|
| 1.0 | 01/06/2026 | Backend gRPC (módulos P, A e B) e infraestrutura inicial (Docker e Kubernetes). |
| 1.1 | 04/06/2026 | Versão espelho REST/JSON (P', A', B') e primeiro benchmark gRPC vs REST. |
| 1.2 | 05/06/2026 | Dataset real do TCIA, benchmark dos 4 endpoints e seletor gRPC/REST na interface. Gateway gRPC assíncrono, isolamento das portas internas e headless services no Kubernetes. |
| 1.3 | 06/06/2026 | Otimização da infraestrutura: Minikube multi-nó, build e carregamento de todas as imagens e deploy completo (módulos, HPA e monitoramento) num único script. |
| 1.4 | 07/06/2026 | Preview do resultado na interface (antes/depois, paciente anonimizado e download); Server Streaming por `SeriesInstanceUID` (devolve as fatias do exame); dataset com múltiplas séries organizadas em pastas. |
