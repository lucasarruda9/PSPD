import sys
from pathlib import Path

import grpc

import medimg_pb2
import medimg_pb2_grpc

SERVIDOR_A = "localhost:50051" 
SERVIDOR_B = "localhost:50052"  
AMOSTRA = Path(__file__).resolve().parent.parent / "benchmarks" / "amostra.dcm"


def carregar_amostra() -> bytes:
    if not AMOSTRA.exists():
        sys.exit(
            f"Amostra DICOM nao encontrada em {AMOSTRA}.\n"
            "Gere com: python3 benchmarks/gerar_amostra_dicom.py benchmarks/amostra.dcm"
        )
    return AMOSTRA.read_bytes()


def teste_unary(dados: bytes) -> None:
    print("\n[1/4] Unary             -> Anonymizer.Anonymize")
    stub = medimg_pb2_grpc.AnonymizerStub(grpc.insecure_channel(SERVIDOR_A))
    req = medimg_pb2.AnonymizeRequest(
        slice=medimg_pb2.Slice(slice_id="amostra.dcm", index=1, data=dados)
    )
    resp = stub.Anonymize(req)
    print(
        f"  OK  modalidade={resp.metadata.modality} "
        f"{resp.metadata.rows}x{resp.metadata.columns} "
        f"tags_removidas={len(resp.metadata.removed_phi_tags)}"
    )


def teste_server_streaming(_dados: bytes) -> None:
    print("\n[2/4] Server streaming  -> Pipeline.ProcessExam")
    stub = medimg_pb2_grpc.PipelineStub(grpc.insecure_channel(SERVIDOR_B))
    req = medimg_pb2.ExamRequest(exam_id="EXAME-001")
    recebidos = 0
    for resp in stub.ProcessExam(req):
        recebidos += 1
        print(f"  <- slice {resp.slice.slice_id} ({len(resp.slice.data)} bytes)")
    print(f"  OK  {recebidos} slices recebidos")


def teste_client_streaming(dados: bytes) -> None:
    print("\n[3/4] Client streaming  -> Pipeline.UploadExam")
    stub = medimg_pb2_grpc.PipelineStub(grpc.insecure_channel(SERVIDOR_B))

    def gerar():
        for i in range(3):
            yield medimg_pb2.Slice(slice_id=f"fatia_{i}", index=i, data=dados)

    resp = stub.UploadExam(gerar())
    print(f"  OK  exam_id={resp.exam_id} slices_ok={resp.slices_ok}")


def teste_bidirecional(dados: bytes) -> None:
    print("\n[4/4] Bidirectional     -> Pipeline.LiveProcess")
    stub = medimg_pb2_grpc.PipelineStub(grpc.insecure_channel(SERVIDOR_B))

    def gerar():
        for i in range(3):
            yield medimg_pb2.Slice(slice_id=f"fatia_{i}", index=i, data=dados)

    eventos = 0
    for evento in stub.LiveProcess(gerar()):
        eventos += 1
        print(f"  <- [{evento.slice_id}] {evento.stage}")
    print(f"  OK  {eventos} eventos de progresso recebidos")


def main() -> None:
    dados = carregar_amostra()
    print(f"Amostra DICOM: {AMOSTRA.name} ({len(dados)} bytes)")
    teste_unary(dados)
    teste_server_streaming(dados)
    teste_client_streaming(dados)
    teste_bidirecional(dados)
    print("\nTodos os 4 tipos de chamada gRPC foram executados.")


if __name__ == "__main__":
    main()
