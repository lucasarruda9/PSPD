#!/usr/bin/env python3
"""
Baixa varias series DICOM da colecao Pseudo-PHI-DICOM-Data do TCIA (REST API /
NBIA), junta os slices em benchmarks/dataset/ e prepara as entradas dos testes:

  benchmarks/dataset/                      -> todos os slices (client/bidi)
  benchmarks/dataset/fatia1.dcm, fatia2.dcm -> lidos pelo Pipeline.ProcessExam
  benchmarks/amostra.dcm                   -> 1 slice (unary)

Usa SO a biblioteca padrao (urllib + zipfile) - nao precisa de pip.

Uso:
    python3 benchmarks/baixar_tcia.py            # baixa TCIA_SERIES series
    TCIA_SERIES=5 python3 benchmarks/baixar_tcia.py

Variaveis de ambiente (opcionais):
    TCIA_API         forca uma base de API (tentada antes das padroes)
    TCIA_COLLECTION  colecao (default: Pseudo-PHI-DICOM-Data)
    TCIA_SERIES      quantas series baixar (default: 3)
    TCIA_SERIE       baixa apenas esta serie (SeriesInstanceUID)

O script tenta varias bases conhecidas do TCIA e usa a primeira que responder
JSON. Dataset sob licenca TCIA (Creative Commons) - citar a fonte no relatorio.
"""
import io
import json
import os
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile

COLECAO = os.getenv("TCIA_COLLECTION", "Pseudo-PHI-DICOM-Data")
QTD_SERIES = int(os.getenv("TCIA_SERIES", "3"))
DIR_DATASET = "benchmarks/dataset"
AMOSTRA = "benchmarks/amostra.dcm"

# Bases candidatas da API do TCIA (a primeira que responder JSON e usada).
BASES = [b for b in [
    os.getenv("TCIA_API"),
    "https://services.cancerimagingarchive.net/nbia-api/services/v1",
    "https://services.cancerimagingarchive.net/services/v4/TCIA/query",
    "https://services.cancerimagingarchive.net/nbia-api/services/v2",
] if b]


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "pspd-benchmark"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


def descobrir_series():
    """Tenta as bases candidatas; retorna (base_que_funcionou, lista_de_series)."""
    erros = []
    for base in BASES:
        for extra in ({"format": "json"}, {}):
            params = {"Collection": COLECAO, **extra}
            url = f"{base}/getSeries?" + urllib.parse.urlencode(params)
            try:
                corpo = http_get(url)
            except urllib.error.HTTPError as e:
                erros.append(f"{base} -> HTTP {e.code}")
                continue
            except Exception as e:
                erros.append(f"{base} -> {e}")
                continue
            try:
                series = json.loads(corpo)
            except json.JSONDecodeError:
                erros.append(f"{base} -> resposta nao-JSON: {corpo[:60]!r}")
                continue
            if series:
                print(f"API TCIA: {base}  ({len(series)} series na colecao)")
                return base, series
            erros.append(f"{base} -> lista vazia")
    sys.exit("Nao consegui listar series no TCIA. Tentativas:\n  " + "\n  ".join(erros))


def baixar_serie(base: str, uid: str, prefixo: str) -> list[str]:
    """Baixa uma serie e extrai os slices em DIR_DATASET com nome prefixado."""
    url = f"{base}/getImage?" + urllib.parse.urlencode({"SeriesInstanceUID": uid})
    conteudo = http_get(url)
    arquivos = []
    with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
        for nome in z.namelist():
            if nome.endswith("/"):
                continue
            destino = os.path.join(DIR_DATASET, f"{prefixo}_{os.path.basename(nome)}")
            with z.open(nome) as src, open(destino, "wb") as dst:
                dst.write(src.read())
            arquivos.append(destino)
    return sorted(arquivos)


def main() -> None:
    base, series = descobrir_series()

    serie_unica = os.getenv("TCIA_SERIE")
    if serie_unica:
        escolhidas = [{"SeriesInstanceUID": serie_unica}]
    else:
        com_imagens = [s for s in series if int(s.get("ImageCount", 0)) >= 1]
        escolhidas = (com_imagens or series)[:QTD_SERIES]

    if os.path.isdir(DIR_DATASET):
        shutil.rmtree(DIR_DATASET)
    os.makedirs(DIR_DATASET, exist_ok=True)

    todos = []
    for k, s in enumerate(escolhidas, 1):
        uid = s["SeriesInstanceUID"]
        print(f"[{k}/{len(escolhidas)}] baixando serie {uid} ({s.get('ImageCount', '?')} imagens)...")
        todos += baixar_serie(base, uid, f"s{k}")

    if not todos:
        sys.exit("As series vieram vazias.")
    print(f"\nTotal: {len(todos)} slice(s) em {DIR_DATASET}/")

    # 1 slice -> amostra do unary
    shutil.copyfile(todos[0], AMOSTRA)
    print(f"Amostra (unary): {AMOSTRA}")
    # 2 fatias DISTINTAS (primeira e a do meio) -> ProcessExam (server-stream)
    fatias = [todos[0], todos[len(todos) // 2]] if len(todos) > 1 else [todos[0], todos[0]]
    for i, origem in enumerate(fatias, 1):
        destino = os.path.join(DIR_DATASET, f"fatia{i}.dcm")
        shutil.copyfile(origem, destino)
        print(f"Server-stream: {destino}  (de {os.path.basename(origem)})")

    print("\nPronto. Entradas preparadas para unary, server-stream e client/bidi.")


if __name__ == "__main__":
    main()
