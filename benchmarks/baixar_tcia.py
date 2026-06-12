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

BASES = [
    b for b in [
        os.getenv("TCIA_API"),
        "https://services.cancerimagingarchive.net/nbia-api/services/v1",
        "https://services.cancerimagingarchive.net/services/v4/TCIA/query",
        "https://services.cancerimagingarchive.net/nbia-api/services/v2",
    ]
    if b
]

def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "pspd-benchmark"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()

def descobrir_series():
    for base in BASES:
        for extra in ({"format": "json"}, {}):
            url = f"{base}/getSeries?" + urllib.parse.urlencode({"Collection": COLECAO, **extra})
            try:
                corpo = http_get(url)
                series = json.loads(corpo)
                if series:
                    print(f"API TCIA: {base} ({len(series)} series)")
                    return base, series
            except Exception:
                continue
    sys.exit("Falha ao listar series do TCIA.")

def baixar_serie(base: str, uid: str, subdir: str) -> list[str]:
    url = f"{base}/getImage?" + urllib.parse.urlencode({"SeriesInstanceUID": uid})
    conteudo = http_get(url)
    os.makedirs(subdir, exist_ok=True)
    arquivos = []
    with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
        validos = [n for n in z.namelist() if not n.endswith("/")]
        for nome in validos[:3]:
            destino = os.path.join(subdir, os.path.basename(nome))
            with z.open(nome) as src, open(destino, "wb") as dst:
                dst.write(src.read())
            arquivos.append(destino)
    return sorted(arquivos)

def main() -> None:
    base, series = descobrir_series()
    com_imagens = [s for s in series if int(s.get("ImageCount", 0)) >= 1]
    if not com_imagens:
        sys.exit("Nenhuma serie valida encontrada.")
    escolhida = com_imagens[0]

    if os.path.isdir(DIR_DATASET):
        shutil.rmtree(DIR_DATASET)
    os.makedirs(DIR_DATASET, exist_ok=True)

    uid = escolhida["SeriesInstanceUID"]
    subdir = os.path.join(DIR_DATASET, "serie01")
    print(f"Baixando 3 imagens da serie {uid} -> {subdir}/")
    todos = baixar_serie(base, uid, subdir)

    if not todos:
        sys.exit("Falha no download.")

    shutil.copyfile(todos[0], AMOSTRA)
    print(f"Amostra: {AMOSTRA}")

    for i, origem in enumerate(todos[:2], 1):
        destino = os.path.join(DIR_DATASET, f"fatia{i}.dcm")
        shutil.copyfile(origem, destino)

    print("Download finalizado. Dataset enxuto preparado.")

if __name__ == "__main__":
    main()
