import grpc
import time
import image_processing_pb2
import image_processing_pb2_grpc

def executar_testes_b1():
    print("Conectando ao canal gRPC...")
    canal = grpc.insecure_channel('localhost:50051')
    stub = image_processing_pb2_grpc.ImageProcessorServiceStub(canal)
    print("\nTESTES")

    #1 unary teste
    print("\n1 - Teste Unary: ProcessarImagem")
    req_unary = image_processing_pb2.ImagemRequest(dados_imagem=b"dados", formato="png", nome_arquivo="raio_x.png")
    resp_unary = stub.ProcessarImagem(req_unary)
    print(f"Sucesso Unary! Tempo: {resp_unary.tempo_ms}ms")

    #2 server streaming teste
    print("\n2 - Teste Server Streaming: ProcessarEtapas")
    req_server = image_processing_pb2.ImagemRequest(dados_imagem=b"dados", formato="jpg", nome_arquivo="ressonancia.jpg")
    for resposta in stub.ProcessarEtapas(req_server):
        print(f"Etapa recebida: {resposta.nome_etapa}")

    #3 cliente streaming teste
    print("\n3 - Teste Client Streaming: ProcessarLote")
    def gerar_lote():
        for i in range(1, 4):
            yield image_processing_pb2.ImagemRequest(dados_imagem=b"dados", formato="png", nome_arquivo=f"fatia_{i}.png")
    resp_client = stub.ProcessarLote(gerar_lote())
    print(f"Sucesso Client Streaming! Processadas: {resp_client.total_processadas}")

    #4 biderecional streaming teste
    print("\n4 - Teste Bidirecional: ProcessarPreviewAoVivo")
    def gerar_stream():
        for i in range(1, 4):
            yield image_processing_pb2.ImagemRequest(dados_imagem=b"frame", formato="raw", nome_arquivo=f"frame_{i}.raw")
    for resposta in stub.ProcessarPreviewAoVivo(gerar_stream()):
        print(f"Preview recebido: {resposta.nome_etapa}")

if __name__ == '__main__':
    executar_testes_b1()