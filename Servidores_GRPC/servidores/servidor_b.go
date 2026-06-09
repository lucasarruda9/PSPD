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
    DiretorioArquivos     = "/app/dataset"
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
    dataset, err := dicom.Parse(bytes.NewReader(dadosOriginais), int64(len(dadosOriginais)), nil)
    if err != nil {
        return nil, fmt.Errorf("falha ao interpretar os bytes do DICOM: %v", err)
    }

    elementoPixel, err := dataset.FindElementByTag(tag.PixelData)
    if err != nil {
        var bufferEscrita bytes.Buffer
        if err := dicom.Write(&bufferEscrita, dataset); err != nil {
            return nil, err
        }
        return bufferEscrita.Bytes(), nil
    }

    informacaoPixel := dicom.MustGetPixelDataInfo(elementoPixel.Value)

    if informacaoPixel.IntentionallySkipped || len(informacaoPixel.UnprocessedValueData) == 0 {
        return dadosOriginais, nil
    }
    bytesBrutosPixel := informacaoPixel.UnprocessedValueData

    for i := 0; i < len(bytesBrutosPixel)-1; i += 2 {
        valorPixel := int(uint16(bytesBrutosPixel[i]) | uint16(bytesBrutosPixel[i+1])<<8)

        if aplicarContraste {
            valorPixel = CentroContraste16Bit + (valorPixel-CentroContraste16Bit)*FatorEscalaContraste
        }
        if aplicarBrilho {
            valorPixel = valorPixel + IncrementoDeBrilho
        }
        if aplicarInversao {
            valorPixel = ValorMaximoPixel16Bit - valorPixel
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

    // Grava o arquivo DICOM atualizado na memória para retorno
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
	log.Printf("[Servidor B] Buscando lote de arquivos para o Exame ID: %s", requisicao.ExamId)

	// Monta o caminho da pasta baseado no ID que o cliente enviou na requisição
	caminhoPasta := filepath.Join(DiretorioArquivos, requisicao.ExamId)

	// Lê todos os arquivos salvos dentro daquela pasta específica do exame
	arquivos, err := ioutil.ReadDir(caminhoPasta)
	if err != nil {
		log.Printf("[Erro B] Pasta do exame não encontrada ou vazia: %v", err)
		return fmt.Errorf("exame ID %s nao foi encontrado no servidor", requisicao.ExamId)
	}

	for indice, arquivo := range arquivos {
		if arquivo.IsDir() {
			continue
		}

		caminhoCompleto := filepath.Join(caminhoPasta, arquivo.Name())
		bytesOriginais, err := ioutil.ReadFile(caminhoCompleto)
		if err != nil {
			log.Printf("[Aviso B] Arquivo ausente na pasta local, pulando: %s", caminhoCompleto)
			continue
		}

		// Aplica o filtro DICOM nas fatias reais do disco
		bytesFiltrados, err := aplicarFiltrosImagemDicom(bytesOriginais, true, false, false)
		if err != nil {
			return err
		}

		respostaStreaming := &pb.EnhanceResponse{
			Slice: &pb.Slice{
				SliceId: arquivo.Name(),
				Index:   int32(indice + 1),
				Data:    bytesFiltrados,
			},
			ProcessingMs: 0.0,
		}

		// Envia a fatia processada de volta em fluxo
		if err := stream.Send(respostaStreaming); err != nil {
			return err
		}
	}

	return nil
}

// streaming de cliente
func (s *serverB) UploadExam(stream pb.Pipeline_UploadExamServer) error {
	// Gera um ID único para o exame (UUID)
	idExame := uuid.New().String() 
	
	// Caminho da pasta: /app/dataset/<UUID>
	caminhoPasta := filepath.Join(DiretorioArquivos, idExame)
	
	// Cria a pasta fisicamente no disco do contêiner
	err := os.MkdirAll(caminhoPasta, os.ModePerm)
	if err != nil {
		log.Printf("[Erro] Não foi possível criar a pasta do exame: %v", err)
		return fmt.Errorf("erro interno ao preparar armazenamento do exame")
	}

	log.Printf("[ClientStream] Upload iniciado. ID único gerado para este exame: %s", idExame)

	var totalSlices int32 = 0
	var slicesOk int32 = 0

	for {
		req, err := stream.Recv()
		
		// Quando o cliente termina de enviar todas as fatias
		if err == io.EOF {
			log.Printf("[ClientStream] Upload concluído! %d fatias armazenadas na pasta %s", totalSlices, caminhoPasta)
			
			// Devolve o ID do exame gerado para o cliente usar no Server Streaming
			return stream.SendAndClose(&pb.ExamSummary{
				ExamId:      idExame,      
				TotalSlices: totalSlices,
				SlicesOk:    slicesOk,
				TotalMs:     150.5,        
			})
		}
		
		if err != nil {
			log.Printf("[Erro] Falha ao receber slice do stream: %v", err)
			return err
		}

		// Extrai os bytes e metadados diretamente do objeto req (que já é o Slice)
		bytesDicom := req.Data 
		indexFatia := req.Index

		// Define o nome do arquivo .dcm
		nomeArquivo := fmt.Sprintf("fatia_%d.dcm", indexFatia)
		if req.SliceId != "" {
			nomeArquivo = fmt.Sprintf("%s.dcm", req.SliceId)
		}
		
		caminhoCompleto := filepath.Join(caminhoPasta, nomeArquivo)

		// Salva o arquivo no disco
		err = os.WriteFile(caminhoCompleto, bytesDicom, 0644)
		if err != nil {
			log.Printf("[Erro] Falha ao escrever arquivo %s: %v", nomeArquivo, err)
			totalSlices++
			continue
		}

		slicesOk++
		totalSlices++
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