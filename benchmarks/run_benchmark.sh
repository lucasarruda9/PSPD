set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

GRPC_URL="${GRPC_URL:-http://localhost:8000}"
REST_URL="${REST_URL:-http://localhost:8001}"
REQUISICOES="${REQUISICOES:-200}"
CONCORRENCIA="${CONCORRENCIA:-20}"
ENDPOINT="/api/unary/processar-imagem"

AMOSTRA="$DIR/amostra.dcm"
RESULTADOS="$DIR/resultados"
CORPO="$DIR/.corpo_multipart.bin"
BOUNDARY="----pspdbench$$"

command -v curl >/dev/null || { echo "ERRO: 'curl' nao instalado"; exit 1; }

# Detecta a ferramenta de carga disponivel
if command -v hey >/dev/null; then
    FERRAMENTA="hey"
    UNIDADE="s"
elif command -v ab >/dev/null; then
    FERRAMENTA="ab"
    UNIDADE="ms"
else
    echo "ERRO: instale 'hey' ou 'ab'. Ex.: sudo apt install -y apache2-utils"
    exit 1
fi

mkdir -p "$RESULTADOS"

# Amostra DICOM (mesma entrada para as duas versoes)
if [ ! -f "$AMOSTRA" ]; then
    echo "Gerando amostra DICOM..."
    uv run --with pydicom --with numpy "$DIR/gerar_amostra_dicom.py" "$AMOSTRA"
fi

# Monta uma vez o corpo multipart/form-data (campo 'arquivo')
{
    printf -- '--%s\r\n' "$BOUNDARY"
    printf 'Content-Disposition: form-data; name="arquivo"; filename="amostra.dcm"\r\n'
    printf 'Content-Type: application/dicom\r\n\r\n'
    cat "$AMOSTRA"
    printf '\r\n--%s--\r\n' "$BOUNDARY"
} > "$CORPO"

# Roda a carga contra um alvo, se ele estiver no ar (senao, pula)
rodar() {
    local nome="$1" base="$2"
    if ! curl -sf -o /dev/null --max-time 3 "$base/health"; then
        echo "  AVISO  $nome ($base) indisponivel - pulando."
        return 1
    fi
    echo "  -> $nome [$FERRAMENTA]: $REQUISICOES req, concorrencia $CONCORRENCIA"
    if [ "$FERRAMENTA" = "hey" ]; then
        hey -n "$REQUISICOES" -c "$CONCORRENCIA" -m POST \
            -T "multipart/form-data; boundary=$BOUNDARY" -D "$CORPO" \
            "$base$ENDPOINT" > "$RESULTADOS/${nome}.txt" 2>&1
    else
        ab -n "$REQUISICOES" -c "$CONCORRENCIA" \
            -T "multipart/form-data; boundary=$BOUNDARY" -p "$CORPO" \
            "$base$ENDPOINT" > "$RESULTADOS/${nome}.txt" 2>&1
    fi
    return 0
}

echo "== Benchmark gRPC vs REST (endpoint unary, ferramenta: $FERRAMENTA) =="
TEM_GRPC=0
TEM_REST=0
rodar "grpc" "$GRPC_URL" && TEM_GRPC=1 || true
rodar "rest" "$REST_URL" && TEM_REST=1 || true

# Extrai as metricas do relatorio (formato depende da ferramenta)
linha() {
    local nome="$1" f="$RESULTADOS/$1.txt"
    [ -f "$f" ] || { echo "| $nome | (sem dados) | - | - | - |"; return; }
    local rps avg p99 slow
    if [ "$FERRAMENTA" = "hey" ]; then
        rps="$(grep -E 'Requests/sec' "$f" | head -1 | awk '{print $2}')"
        avg="$(grep -E 'Average:' "$f" | head -1 | awk '{print $2}')"
        slow="$(grep -E 'Slowest:' "$f" | head -1 | awk '{print $2}')"
        p99="$(grep -E '99% in' "$f" | head -1 | awk '{print $3}')"
    else
        rps="$(grep -E 'Requests per second' "$f" | head -1 | awk '{print $4}')"
        avg="$(grep -E 'Time per request' "$f" | head -1 | awk '{print $4}')"
        p99="$(awk '/Percentage of the/{f=1} f && $1=="99%"{print $2; exit}' "$f")"
        slow="$(awk '/Percentage of the/{f=1} f && $1=="100%"{print $2; exit}' "$f")"
    fi
    echo "| $nome | ${rps:-?} | ${avg:-?} | ${p99:-?} | ${slow:-?} |"
}

TABELA="$RESULTADOS/comparativo.md"
{
    echo "# Comparativo gRPC vs REST - endpoint unary"
    echo
    echo "- Ferramenta: $FERRAMENTA | Requisicoes: $REQUISICOES | Concorrencia: $CONCORRENCIA"
    echo "- Endpoint: \`$ENDPOINT\` | Amostra: \`amostra.dcm\` | Tempos em $UNIDADE"
    echo
    echo "| Versao | Req/s | Media ($UNIDADE) | p99 ($UNIDADE) | Mais lenta ($UNIDADE) |"
    echo "|--------|-------|------------------|----------------|------------------------|"
    [ "$TEM_GRPC" = 1 ] && linha "grpc"
    [ "$TEM_REST" = 1 ] && linha "rest"
} > "$TABELA"

echo
cat "$TABELA"
echo
echo "Resultados brutos em: $RESULTADOS/"
rm -f "$CORPO"
