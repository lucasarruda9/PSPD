#!/usr/bin/env bash
set -euo pipefail

GATEWAY_URL="${1:-http://localhost:8000}"
REQUISICOES=500
CONCORRENCIA=50
IMAGEM_TESTE="benchmarks/sample.png"

if [ ! -f "$IMAGEM_TESTE" ]; then
    python3 -c "
import os, struct, zlib, random
def png_minimo(w, h, path):
    def chunk(tag, data):
        c = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', c)
    raw = b''.join(b'\x00' + bytes([random.randint(0,255) for _ in range(w*3)]) for _ in range(h))
    compressed = zlib.compress(raw)
    with open(path, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n')
        f.write(chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)))
        f.write(chunk(b'IDAT', compressed))
        f.write(chunk(b'IEND', b''))
os.makedirs('benchmarks', exist_ok=True)
png_minimo(512, 512, 'benchmarks/sample.png')
"
fi

echo "Iniciando benchmark no Gateway ($GATEWAY_URL)..."
hey -n "$REQUISICOES" -c "$CONCORRENCIA" \
    -m POST \
    -H "Content-Type: multipart/form-data" \
    -D "$IMAGEM_TESTE" \
    "$GATEWAY_URL/processar-imagem" > benchmarks/resultado.txt 2>&1

echo "Resumo do Benchmark:"
grep -E "Requests/sec|Average|Fastest|Slowest|99%" benchmarks/resultado.txt || true
