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

command -v hey  >/dev/null || { echo "ERRO: 'hey' nao instalado (go install github.com/rakyll/hey@latest)"; exit 1; }
command -v curl >/dev/null || { echo "ERRO: 'curl' nao instalado"; exit 1; }

mkdir -p "$RESULTADOS"

# Amostra DICOM (mesma entrada para as duas versoes)
if [ ! -f "$AMOSTRA" ]; then
    echo "Gerando amostra DICOM..."
    python3 "$DIR/gerar_amostra_dicom.py" "$AMOSTRA"
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
    echo "  -> $nome: $REQUISICOES req, concorrencia $CONCORRENCIA"
    hey -n "$REQUISICOES" -c "$CONCORRENCIA" -m POST \
        -T "multipart/form-data; boundary=$BOUNDARY" \
        -D "$CORPO" \
        "$base$ENDPOINT" > "$RESULTADOS/${nome}.txt" 2>&1
    return 0
}

echo "== Benchmark gRPC vs REST (endpoint unary) =="
TEM_GRPC=0; TEM_REST=0
rodar "grpc" "$GRPC_URL" && TEM_GRPC=1 || true
rodar "rest" "$REST_URL" && TEM_REST=1 || true

# Extrai metricas do relatorio do hey e monta a tabela comparativa
campo() { grep -E "$2" "$1" 2>/dev/null | head -1 | awk -v c="$3" '{print $c}'; }
linha() {
    local nome="$1" f="$RESULTADOS/$1.txt"
    [ -f "$f" ] || { echo "| $nome | (sem dados) | - | - | - |"; return; }
    local rps avg p99 slow
    rps="$(campo "$f" 'Requests/sec' 2)"   # Requests/sec:\tNUM
    avg="$(campo "$f" 'Average:'     2)"   # Average:\tNUM secs
    slow="$(campo "$f" 'Slowest:'    2)"   # Slowest:\tNUM secs
    p99="$(campo "$f" '99% in'       3)"   # 99% in NUM secs
    echo "| $nome | ${rps:-?} | ${avg:-?} | ${p99:-?} | ${slow:-?} |"
}

TABELA="$RESULTADOS/comparativo.md"
{
    echo "# Comparativo gRPC vs REST - endpoint unary"
    echo
    echo "- Requisicoes: $REQUISICOES | Concorrencia: $CONCORRENCIA"
    echo "- Endpoint: \`$ENDPOINT\` | Amostra: \`amostra.dcm\`"
    echo
    echo "| Versao | Req/s | Media (s) | p99 (s) | Mais lenta (s) |"
    echo "|--------|-------|-----------|---------|----------------|"
    [ "$TEM_GRPC" = 1 ] && linha "grpc"
    [ "$TEM_REST" = 1 ] && linha "rest"
} > "$TABELA"

echo
cat "$TABELA"
echo
echo "Resultados brutos em: $RESULTADOS/"
rm -f "$CORPO"
