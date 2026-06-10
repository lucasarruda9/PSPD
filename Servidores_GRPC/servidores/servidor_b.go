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
    "sort"
    "strings"

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
	//Se o arquivo tiver PixelData então não há imagem para filtrar retorna os dadosOriginais diretamente para 
	//economizar processamento e evitar que o dicom.Write corrompa metadados obscuros ao reescrever o arquivo
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
    centroContraste := minPixel + (maxPixel - minPixel) / 2
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

const MaxFatiasExame = 8 

var indiceExames = map[string][]string{}

func lerSeriesUID(dados []byte) string {
	ds, err := dicom.Parse(bytes.NewReader(dados), int64(len(dados)), nil)
	if err != nil {
		return ""
	}
	el, err := ds.FindElementByTag(tag.Tag{Group: 0x0020, Element: 0x000E})
	if err != nil {
		return ""
	}
	if strs, ok := el.Value.GetValue().([]string); ok && len(strs) > 0 {
		return strings.TrimSpace(strs[0])
	}
	return ""
}

func construirIndiceExames() {
	indiceExames = map[string][]string{}
	fatias := 0
	_ = filepath.WalkDir(DiretorioArquivos, func(caminho string, d os.DirEntry, err error) error {
		if err != nil || d.IsDir() {
			return nil
		}
		nome := strings.ToLower(d.Name())
		if !strings.HasSuffix(nome, ".dcm") || strings.HasPrefix(nome, "fatia") || strings.HasPrefix(nome, "upload_") {
			return nil
		}
		dados, err := os.ReadFile(caminho)
		if err != nil {
			return nil
		}
		if uid := lerSeriesUID(dados); uid != "" {
			indiceExames[uid] = append(indiceExames[uid], caminho)
			fatias++
		}
		return nil
	})
	for uid := range indiceExames {
		sort.Strings(indiceExames[uid])
	}
	log.Printf("[Servidor B] Indice: %d exame(s), %d fatia(s)", len(indiceExames), fatias)
}

func arquivosDoExame(examID string) []string {
	arquivos := indiceExames[examID]
	if len(arquivos) == 0 {
		return []string{
			filepath.Join(DiretorioArquivos, "fatia1.dcm"),
			filepath.Join(DiretorioArquivos, "fatia2.dcm"),
		}
	}
	if len(arquivos) > MaxFatiasExame {
		arquivos = arquivos[:MaxFatiasExame]
	}
	return arquivos
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

    // lê 
    arquivosExame := arquivosDoExame(requisicao.ExamId)

    for indice, caminhoArquivo := range arquivosExame {
        bytesOriginais, err := ioutil.ReadFile(caminhoArquivo)
        if err != nil {
            log.Printf("[Aviso B] Arquivo ausente na pasta local, pulando: %s", caminhoArquivo)
            continue
        }

        // Aplica um filtro automático padrão de contraste para o lote enviado em fluxo
        bytesFiltrados, err := aplicarFiltrosImagemDicom(bytesOriginais, true, false, false)
        if err != nil {
            return err
        }

        respostaStreaming := &pb.EnhanceResponse{
            Slice: &pb.Slice{
                SliceId: fmt.Sprintf("Fatia_Processada_%d", indice+1),
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
    quantidadeFatiasRecebidas := 0

	for {
        fatiaRecebida, err := stream.Recv()
        if err == io.EOF {
            resumoFinal := &pb.ExamSummary{
                ExamId:      "Upload_Hospitalar_Registrado",
                TotalSlices: int32(quantidadeFatiasRecebidas),
                SlicesOk:    int32(quantidadeFatiasRecebidas),
                TotalMs:     0.0,
            }
            return stream.SendAndClose(resumoFinal)
        }
        if err != nil {
            return err
        }
        baseName := strings.TrimSuffix(fatiaRecebida.SliceId, ".dcm")
        nomeDestinoArquivo := fmt.Sprintf("%s/upload_fatia_%s.dcm", DiretorioArquivos, baseName)
        _ = ioutil.WriteFile(nomeDestinoArquivo, fatiaRecebida.Data, 0644)

        quantidadeFatiasRecebidas++
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

    construirIndiceExames()

    servidorGrpc := grpc.NewServer()
    instanciaServidorB := &serverB{}

    pb.RegisterEnhancerServer(servidorGrpc, instanciaServidorB)
    pb.RegisterPipelineServer(servidorGrpc, instanciaServidorB)

    log.Printf("Servidor B operando na porta %s", PortaServidorB)
    if err := servidorGrpc.Serve(escutadorRede); err != nil {
        log.Fatalf("Erro durante a execução do gRPC: %v", err)
    }
}