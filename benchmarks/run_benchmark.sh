set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

GRPC_URL="${GRPC_URL:-http://localhost:8000}"
REST_URL="${REST_URL:-http://localhost:8001}"
REQUISICOES="${REQUISICOES:-200}"
CONCORRENCIA="${CONCORRENCIA:-20}"
N_SLICES="${N_SLICES:-3}"   

AMOSTRA="$DIR/amostra.dcm"
DATASET="$DIR/dataset"
RESULTADOS="$DIR/resultados"
CORPO_UNICO="$DIR/.corpo_unico.bin"
CORPO_MULTI="$DIR/.corpo_multi.bin"
BOUNDARY="----pspdbench$$"

command -v curl >/dev/null || { echo "ERRO: 'curl' nao instalado"; exit 1; }

# Detecta a ferramenta de carga disponivel
if command -v hey >/dev/null; then
    FERRAMENTA="hey"; UNIDADE="s"
elif command -v ab >/dev/null; then
    FERRAMENTA="ab"; UNIDADE="ms"
else
    echo "ERRO: instale 'hey' ou 'ab'. Ex.: sudo apt install -y apache2-utils"
    exit 1
fi

mkdir -p "$RESULTADOS"

if [ ! -f "$AMOSTRA" ]; then
    echo "Amostra ausente; gerando sintetica..."
    uv run --with pydicom --with numpy "$DIR/gerar_amostra_dicom.py" "$AMOSTRA"
fi

# Corpo multipart com 1 arquivo (campo 'arquivo') -> unary e server-stream
{
    printf -- '--%s\r\n' "$BOUNDARY"
    printf 'Content-Disposition: form-data; name="arquivo"; filename="amostra.dcm"\r\n'
    printf 'Content-Type: application/dicom\r\n\r\n'
    cat "$AMOSTRA"
    printf '\r\n--%s--\r\n' "$BOUNDARY"
} > "$CORPO_UNICO"

# Corpo multipart com varios arquivos (campo 'arquivos') -> client e bidi
mapfile -t SLICES < <(find "$DATASET" -maxdepth 1 -name '*.dcm' 2>/dev/null | sort | head -n "$N_SLICES")
if [ "${#SLICES[@]}" -lt 2 ]; then
    SLICES=("$AMOSTRA" "$AMOSTRA")   # fallback: repete a amostra
fi
{
    for f in "${SLICES[@]}"; do
        printf -- '--%s\r\n' "$BOUNDARY"
        printf 'Content-Disposition: form-data; name="arquivos"; filename="%s"\r\n' "$(basename "$f")"
        printf 'Content-Type: application/dicom\r\n\r\n'
        cat "$f"
        printf '\r\n'
    done
    printf -- '--%s--\r\n' "$BOUNDARY"
} > "$CORPO_MULTI"

ENDPOINTS=(
    "unary|/api/unary/processar-imagem|$CORPO_UNICO"
    "server_stream|/api/server-stream/processar-etapas|$CORPO_UNICO"
    "client_stream|/api/client-stream/processar-lote|$CORPO_MULTI"
    "bidirecional|/api/bidirecional/preview-ao-vivo|$CORPO_MULTI"
)

# Dispara a carga de um endpoint contra um alvo
rodar() {
    local versao="$1" base="$2" ep="$3" path="$4" corpo="$5"
    local out="$RESULTADOS/${versao}_${ep}.txt"
    if [ "$FERRAMENTA" = "hey" ]; then
        hey -n "$REQUISICOES" -c "$CONCORRENCIA" -m POST \
            -T "multipart/form-data; boundary=$BOUNDARY" -D "$corpo" \
            "$base$path" > "$out" 2>&1
    else
        ab -n "$REQUISICOES" -c "$CONCORRENCIA" \
            -T "multipart/form-data; boundary=$BOUNDARY" -p "$corpo" \
            "$base$path" > "$out" 2>&1
    fi
}

no_ar() { curl -sf -o /dev/null --max-time 3 "$1/health"; }

echo "== Benchmark gRPC vs REST (4 endpoints, ferramenta: $FERRAMENTA) =="
TEM_GRPC=0; TEM_REST=0
no_ar "$GRPC_URL" && TEM_GRPC=1 || echo "  AVISO  gRPC ($GRPC_URL) indisponivel."
no_ar "$REST_URL" && TEM_REST=1 || echo "  AVISO  REST ($REST_URL) indisponivel."

for item in "${ENDPOINTS[@]}"; do
    IFS='|' read -r ep path corpo <<< "$item"
    echo "  -> $ep ($REQUISICOES req, conc. $CONCORRENCIA)"
    [ "$TEM_GRPC" = 1 ] && rodar "grpc" "$GRPC_URL" "$ep" "$path" "$corpo"
    [ "$TEM_REST" = 1 ] && rodar "rest" "$REST_URL" "$ep" "$path" "$corpo"
done

# Extrai metricas do relatorio
campo() { grep -E "$2" "$1" 2>/dev/null | head -1 | awk -v c="$3" '{print $c}'; }
linha() {
    local ep="$1" versao="$2" f="$RESULTADOS/${2}_${1}.txt"
    [ -f "$f" ] || return
    local rps avg p99
    if [ "$FERRAMENTA" = "hey" ]; then
        rps="$(campo "$f" 'Requests/sec' 2)"
        avg="$(campo "$f" 'Average:' 2)"
        p99="$(grep -E '99% in' "$f" | head -1 | awk '{print $3}')"
    else
        rps="$(campo "$f" 'Requests per second' 4)"
        avg="$(campo "$f" 'Time per request' 4)"
        p99="$(awk '/Percentage of the/{f=1} f && $1=="99%"{print $2; exit}' "$f")"
    fi
    echo "| $ep | $versao | ${rps:-?} | ${avg:-?} | ${p99:-?} |"
}

TABELA="$RESULTADOS/comparativo.md"
{
    echo "# Comparativo gRPC vs REST - 4 endpoints"
    echo
    echo "- Ferramenta: $FERRAMENTA | Requisicoes: $REQUISICOES | Concorrencia: $CONCORRENCIA"
    echo "- Tempos em $UNIDADE | client/bidi com ${#SLICES[@]} arquivos por requisicao"
    echo
    echo "| Endpoint | Versao | Req/s | Media ($UNIDADE) | p99 ($UNIDADE) |"
    echo "|----------|--------|-------|------------------|----------------|"
    for item in "${ENDPOINTS[@]}"; do
        IFS='|' read -r ep _ _ <<< "$item"
        [ "$TEM_GRPC" = 1 ] && linha "$ep" "grpc"
        [ "$TEM_REST" = 1 ] && linha "$ep" "rest"
    done
} > "$TABELA"

echo
cat "$TABELA"
echo
echo "Resultados brutos em: $RESULTADOS/"
rm -f "$CORPO_UNICO" "$CORPO_MULTI"
