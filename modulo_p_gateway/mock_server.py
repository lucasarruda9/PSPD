import grpc
from concurrent import futures
import time
import image_processing_pb2
import image_processing_pb2_grpc

# Mock Server gRPC para testes
class MockImageProcessor(image_processing_pb2_grpc.ImageProcessorServiceServicer):
    
    def ProcessarImagem(self, request, context):
        return image_processing_pb2.ImagemResponse(
            imagem_processada=b"imagem_tratada", formato_saida="png", tempo_ms=120.5, etapas_aplicadas=["Filtro Base"]
        )
    def ProcessarEtapas(self, request, context):
        etapas = ["Carregando DICOM", "Aplicando Realce", "Concluído"]
        for i, etapa in enumerate(etapas):
            yield image_processing_pb2.EtapaResponse(
                nome_etapa=etapa, imagem_parcial=b"img", tempo_etapa_ms=45.0, ultima_etapa=(i == 2)
            )
            time.sleep(0.3)
    def ProcessarLote(self, request_iterator, context):
        count = sum(1 for _ in request_iterator)
        return image_processing_pb2.LoteResponse(
            total_processadas=count, total_erros=0, tempo_total_ms=250.0, arquivos_processados=[f"img_{i}" for i in range(count)]
        )
    def ProcessarPreviewAoVivo(self, request_iterator, context):
        for req in request_iterator:
            yield image_processing_pb2.EtapaResponse(
                nome_etapa=f"Preview de: {req.nome_arquivo}", imagem_parcial=b"frame", tempo_etapa_ms=15.0, ultima_etapa=False
            )
def serve():
    servidor = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    image_processing_pb2_grpc.add_ImageProcessorServiceServicer_to_server(MockImageProcessor(), servidor)
    servidor.add_insecure_port('[::]:50051')
    servidor.start()
    print("Mock Server gRPC rodando na porta 50051...")
    servidor.wait_for_termination()
if __name__ == '__main__':
    serve()