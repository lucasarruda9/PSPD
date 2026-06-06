#!/usr/bin/env python3
"""
Baixa uma serie DICOM da colecao Pseudo-PHI-DICOM-Data do TCIA (REST API / NBIA),
extrai os slices e prepara as entradas dos testes:

  benchmarks/dataset/                      -> todos os slices (client/bidi)
  benchmarks/dataset/fatia1.dcm, fatia2.dcm -> lidos pelo Pipeline.ProcessExam
  benchmarks/amostra.dcm                   -> 1 slice (unary / server-stream)

Usa SO a biblioteca padrao (urllib + zipfile) - nao precisa de pip.

Uso:
    python3 benchmarks/baixar_tcia.py

Variaveis de ambiente (opcionais):
    TCIA_API         forca uma base de API (tentada antes das padroes)
    TCIA_COLLECTION  colecao (default: Pseudo-PHI-DICOM-Data)
    TCIA_SERIE       SeriesInstanceUID especifico (default: 1a serie util)

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
    with urllib.request.urlopen(req, timeout=180) as r:
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
                erros.append(f"{base} (format={'json' in extra}) -> HTTP {e.code}")
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
                print(f"API TCIA: {base}  ({len(series)} series)")
                return base, series
            erros.append(f"{base} -> lista vazia")
    sys.exit("Nao consegui listar series no TCIA. Tentativas:\n  " + "\n  ".join(erros))


def escolher_serie(series) -> str:
    uid = os.getenv("TCIA_SERIE")
    if uid:
        print(f"Serie (via TCIA_SERIE): {uid}")
        return uid
    # prefere uma serie com >= 2 imagens (para os fluxos de streaming)
    for s in series:
        if int(s.get("ImageCount", 0)) >= 2:
            print(f"Serie: {s['SeriesInstanceUID']} ({s.get('ImageCount')} imagens)")
            return s["SeriesInstanceUID"]
    uid = series[0]["SeriesInstanceUID"]
    print(f"Serie: {uid}")
    return uid


def baixar_serie(base: str, uid: str) -> list[str]:
    url = f"{base}/getImage?" + urllib.parse.urlencode({"SeriesInstanceUID": uid})
    print("Baixando ZIP da serie...")
    conteudo = http_get(url)
    if os.path.isdir(DIR_DATASET):
        shutil.rmtree(DIR_DATASET)
    os.makedirs(DIR_DATASET, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
        nomes = [n for n in z.namelist() if not n.endswith("/")]
        z.extractall(DIR_DATASET)
    arquivos = sorted(os.path.join(DIR_DATASET, n) for n in nomes)
    print(f"{len(arquivos)} slice(s) extraido(s) em {DIR_DATASET}/")
    return arquivos


def preparar_entradas(arquivos) -> None:
    if not arquivos:
        sys.exit("A serie veio vazia.")
    # 1 slice -> amostra do unary/server-stream
    shutil.copyfile(arquivos[0], AMOSTRA)
    print(f"Amostra (unary): {AMOSTRA}")
    # 2 slices -> fatia1/fatia2, lidos pelo ProcessExam no servidor B
    for i in range(min(2, len(arquivos))):
        destino = os.path.join(DIR_DATASET, f"fatia{i + 1}.dcm")
        shutil.copyfile(arquivos[i], destino)
        print(f"Server-stream: {destino}")


def main() -> None:
    base, series = descobrir_series()
    uid = escolher_serie(series)
    arquivos = baixar_serie(base, uid)
    preparar_entradas(arquivos)
    print("\nPronto. Entradas preparadas para unary, server-stream e client/bidi.")


if __name__ == "__main__":
    main()
