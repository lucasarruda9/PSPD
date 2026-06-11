package main

import (
    "bytes"
    "context"
    "fmt"
    "io"
    "io/ioutil"
    "log"
    "net"
    "os"
    "path/filepath"

    "github.com/google/uuid"
    "github.com/suyashkumar/dicom"
    "github.com/suyashkumar/dicom/pkg/tag"
    "google.golang.org/grpc"
    pb "pspd-servidores/proto"
)

const (
    PortaServidorB        = ":50052"
    DiretorioArquivos     = "dataset"
    ValorMaximoPixel16Bit = 65535
    ValorMinimoPixel      = 0
    IncrementoDeBrilho    = 2000
    CentroContraste16Bit  = 128
    FatorEscalaContraste  = 2
)

type serverB struct {
    pb.UnimplementedEnhancerServer
    pb.UnimplementedPipelineServer
}

func aplicarFiltrosImagemDicom(dadosOriginais []byte, aplicarContraste, aplicarBrilho, aplicarInversao bool) ([]byte, error) {
    dataset, err := dicom.Parse(bytes.NewReader(dadosOriginais), int64(len(dadosOriginais)), nil, dicom.SkipProcessingPixelDataValue())
    if err != nil {
        return nil, fmt.Errorf("falha ao interpretar os bytes do DICOM: %v", err)
    }

    elementoPixel, err := dataset.FindElementByTag(tag.PixelData)
    if err != nil {
        return dadosOriginais, nil
    }

    informacaoPixel := dicom.MustGetPixelDataInfo(elementoPixel.Value)
    if informacaoPixel.IntentionallySkipped || len(informacaoPixel.UnprocessedValueData) == 0 {
        return dadosOriginais, nil
    }
    bytesBrutosPixel := informacaoPixel.UnprocessedValueData
    maxPixel := 0
    minPixel := 65535
    for i := 0; i < len(bytesBrutosPixel)-1; i += 2 {
        valorPixel := int(uint16(bytesBrutosPixel[i]) | uint16(bytesBrutosPixel[i+1])<<8)
        if valorPixel > maxPixel { maxPixel = valorPixel }
        if valorPixel < minPixel { minPixel = valorPixel }
    }
    incrementoDeBrilho := (maxPixel - minPixel) / 4
    centroContraste := minPixel + (maxPixel-minPixel)/2
    fatorEscalaContraste := 2

    for i := 0; i < len(bytesBrutosPixel)-1; i += 2 {
        valorPixel := int(uint16(bytesBrutosPixel[i]) | uint16(bytesBrutosPixel[i+1])<<8)

        if aplicarContraste {
            valorPixel = centroContraste + (valorPixel-centroContraste)*fatorEscalaContraste
        }
        if aplicarBrilho {
            valorPixel = valorPixel + incrementoDeBrilho
        }
        if aplicarInversao {
            valorPixel = minPixel + (maxPixel - valorPixel)
        }

        if valorPixel > ValorMaximoPixel16Bit {
            valorPixel = ValorMaximoPixel16Bit
        }
        if valorPixel < ValorMinimoPixel {
            valorPixel = ValorMinimoPixel
        }
        bytesBrutosPixel[i] = byte(valorPixel & 0xFF)
        bytesBrutosPixel[i+1] = byte((valorPixel >> 8) & 0xFF)
    }

    var bufferEscrita bytes.Buffer
    if err := dicom.Write(&bufferEscrita, dataset); err != nil {
        return nil, fmt.Errorf("erro ao serializar o dataset DICOM modificado: %v", err)
    }

    return bufferEscrita.Bytes(), nil
}

// unário
func (s *serverB) Enhance(ctx context.Context, requisicao *pb.EnhanceRequest) (*pb.EnhanceResponse, error) {
    bytesModificados, err := aplicarFiltrosImagemDicom(
        requisicao.Slice.Data,
        requisicao.ApplyClahe,
        requisicao.ApplyNormalize,
        requisicao.ApplyDenoise,
    )
    if err != nil {
        log.Printf("[Erro B] Filtro Unario falhou: %v", err)
        return nil, err
    }

    requisicao.Slice.Data = bytesModificados

    resposta := &pb.EnhanceResponse{
        Slice:        requisicao.Slice,
        ProcessingMs: 0.0,
    }

    return resposta, nil
}

// streaming de servidor
func (s *serverB) ProcessExam(requisicao *pb.ExamRequest, stream pb.Pipeline_ProcessExamServer) error {
    log.Printf("[Servidor B] Processando Exame ID: %s", requisicao.ExamId)

    caminhoPasta := filepath.Join(DiretorioArquivos, requisicao.ExamId)
    arquivos, err := os.ReadDir(caminhoPasta)
    if err != nil {
        return fmt.Errorf("exame nao encontrado: %s", requisicao.ExamId)
    }

    for indice, entrada := range arquivos {
        if entrada.IsDir() {
            continue
        }
        caminhoArquivo := filepath.Join(caminhoPasta, entrada.Name())
        bytesOriginais, err := ioutil.ReadFile(caminhoArquivo)
        if err != nil {
            log.Printf("[Aviso B] Arquivo ausente, pulando: %s", caminhoArquivo)
            continue
        }

        bytesFiltrados, err := aplicarFiltrosImagemDicom(bytesOriginais, true, false, false)
        if err != nil {
            return err
        }

        respostaStreaming := &pb.EnhanceResponse{
            Slice: &pb.Slice{
                SliceId: entrada.Name(),
                Index:   int32(indice + 1),
                Data:    bytesFiltrados,
            },
            ProcessingMs: 0.0,
        }

        if err := stream.Send(respostaStreaming); err != nil {
            return err
        }
    }

    return nil
}

// streaming de cliente
func (s *serverB) UploadExam(stream pb.Pipeline_UploadExamServer) error {
    idExame := uuid.New().String()
    caminhoPasta := filepath.Join(DiretorioArquivos, idExame)
    _ = os.MkdirAll(caminhoPasta, 0755)

    recebidas := 0
	for {
        fatiaRecebida, err := stream.Recv()
        if err == io.EOF {
            resumoFinal := &pb.ExamSummary{
                ExamId:      idExame,
                TotalSlices: int32(recebidas),
                SlicesOk:    int32(recebidas),
                TotalMs:     0.0,
            }
            return stream.SendAndClose(resumoFinal)
        }
        if err != nil {
            return err
        }
        nomeArquivo := fmt.Sprintf("fatia_%d.dcm", fatiaRecebida.Index)
        if fatiaRecebida.SliceId != "" {
            nomeArquivo = fmt.Sprintf("%s.dcm", fatiaRecebida.SliceId)
        }
        destino := filepath.Join(caminhoPasta, nomeArquivo)
        _ = ioutil.WriteFile(destino, fatiaRecebida.Data, 0644)
        recebidas++
    }
}

// streaming bidirecional
func (s *serverB) LiveProcess(stream pb.Pipeline_LiveProcessServer) error {
    for {
        fatiaBruta, err := stream.Recv()
        if err == io.EOF {
            return nil 
        }
        if err != nil {
            return err
        }
        bytesTratados, err := aplicarFiltrosImagemDicom(fatiaBruta.Data, true, true, false)

        if err != nil {
            log.Printf("[Servidor B] Erro ao tratar fluxo ao vivo: %v", err)
            continue
        }

        fatiaBruta.Data = bytesTratados
        eventoProgresso := &pb.ProgressEvent{
            SliceId:   fatiaBruta.SliceId,
            Index:     fatiaBruta.Index,
            Stage:     "Filtros de Nitidez e Brilho Aplicados com Sucesso",
            ElapsedMs: 0.0,
            Data:      bytesTratados,
        }

        if err := stream.Send(eventoProgresso); err != nil {
            return err
        }
    }
}

func main() {
    escutadorRede, err := net.Listen("tcp", PortaServidorB)
    if err != nil {
        log.Fatalf("Falha ao escutar a porta %s: %v", PortaServidorB, err)
    }

    servidorGrpc := grpc.NewServer()
    instanciaServidorB := &serverB{}

    pb.RegisterEnhancerServer(servidorGrpc, instanciaServidorB)
    pb.RegisterPipelineServer(servidorGrpc, instanciaServidorB)

    log.Printf("Servidor B operando na porta %s", PortaServidorB)
    if err := servidorGrpc.Serve(escutadorRede); err != nil {
        log.Fatalf("Erro durante a execução do gRPC: %v", err)
    }
}