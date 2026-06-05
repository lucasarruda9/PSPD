import sys

def gerar(caminho: str) -> None:
    try:
        import numpy as np
        from pydicom.dataset import Dataset, FileMetaDataset
        from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, generate_uid
    except ImportError:
        sys.exit("Faltam dependencias: pip install pydicom numpy")

    ds = Dataset()

    # PHI que o Servidor A (Anonymizer) deve remover/substituir
    ds.PatientName = "DOE^JOHN"
    ds.PatientID = "PACIENTE-12345"
    ds.PatientBirthDate = "19800101"
    ds.PatientSex = "M"
    ds.PatientAge = "044Y"
    ds.StudyDate = "20240101"
    ds.SeriesDate = "20240101"
    ds.StudyDescription = "TC de Torax"
    ds.Modality = "CT"

    # Imagem: 512x512, 16 bits, ruido aleatorio (so para ter PixelData valido)
    linhas = colunas = 512
    ds.Rows = linhas
    ds.Columns = colunas
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0
    ds.SliceThickness = "1.25"
    pixels = (np.random.rand(linhas, colunas) * 65535).astype(np.uint16)
    ds.PixelData = pixels.tobytes()

    ds.SOPClassUID = CTImageStorage
    ds.SOPInstanceUID = generate_uid()
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()

    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = CTImageStorage
    meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.ImplementationClassUID = generate_uid()
    ds.file_meta = meta
    ds.is_little_endian = True
    ds.is_implicit_VR = False

    ds.save_as(caminho, write_like_original=False)
    print(f"Amostra DICOM gerada: {caminho} ({linhas}x{colunas}, 16-bit)")


if __name__ == "__main__":
    saida = sys.argv[1] if len(sys.argv) > 1 else "benchmarks/amostra.dcm"
    gerar(saida)
