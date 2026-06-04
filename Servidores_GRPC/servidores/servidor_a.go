package main

import (
	"bytes"
	"context"
	"fmt"
	"log"
	"net"
	"time"

	"github.com/suyashkumar/dicom"
	"github.com/suyashkumar/dicom/pkg/tag"
	"google.golang.org/grpc"
	pb "pspd-servidores/proto"
)

type anonymizerServer struct {
	pb.UnimplementedAnonymizerServer
}

// se a coluna não existir, adiciona ela
func substituirTag(d *dicom.Dataset, t tag.Tag, valores []string) {
	elem, err := dicom.NewElement(t, valores)

	if err != nil {
		log.Printf("[Aviso A] Nao foi possivel criar tag %v: %v", t, err)
		return
	}
	for indice, elemento_atual := range d.Elements {
		if elemento_atual.Tag == t {
			d.Elements[indice] = elem
			return
		}
	}
	d.Elements = append(d.Elements, elem)
}

func (s *anonymizerServer) Anonymize(ctx context.Context, req *pb.AnonymizeRequest) (*pb.AnonymizeResponse, error) {
	startTime := time.Now()

	dataset, err := dicom.Parse(bytes.NewReader(req.Slice.Data), int64(len(req.Slice.Data)), nil)
	if err != nil {
		log.Printf("[Erro A] Falha ao parsear DICOM: %v", err)
		return nil, err
	}
	idAnonimo := fmt.Sprintf("Anonimo_%d", req.Slice.Index)
	substituirTag(&dataset, tag.PatientName, []string{idAnonimo})
	substituirTag(&dataset, tag.PatientID, []string{idAnonimo})
	substituirTag(&dataset, tag.PatientBirthDate, []string{"19000101"})
	substituirTag(&dataset, tag.PatientSex, []string{"O"})
	substituirTag(&dataset, tag.PatientAge, []string{"000Y"})
	substituirTag(&dataset, tag.EthnicGroup, []string{"Anonimizado"})
	substituirTag(&dataset, tag.StudyDate, []string{"20260101"})
	substituirTag(&dataset, tag.SeriesDate, []string{"20260101"})
	substituirTag(&dataset, tag.StudyDescription, []string{"Estudo Clinico Anonimizado"})
	substituirTag(&dataset, tag.Tag{Group: 0x0008, Element: 0x1080}, []string{"Removido"})

	var linhas int32 = 512
    var colunas int32 = 512
    
    // extrai linhas
    if elementoLinhas, err := dataset.FindElementByTag(tag.Rows); err == nil {
        valores := dicom.MustGetInts(elementoLinhas.Value)
        if len(valores) > 0 {
            linhas = int32(valores[0])
        }
    }

    // extrai colunas
    if elementoColunas, err := dataset.FindElementByTag(tag.Columns); err == nil {
        valores := dicom.MustGetInts(elementoColunas.Value)
        if len(valores) > 0 {
            colunas = int32(valores[0])
        }
    }
	// censura
	if pixelDataElement, err := dataset.FindElementByTag(tag.PixelData); err == nil {

		pixelInfo := dicom.MustGetPixelDataInfo(pixelDataElement.Value)
		if !pixelInfo.IntentionallySkipped && len(pixelInfo.Frames) > 0 {
			alturaTarja := int(linhas) / 8
			largura := int(colunas)
			limiteBytes := alturaTarja * largura * 2 
			
			if len(pixelInfo.UnprocessedValueData) > 0 {
				for i := 0; i < limiteBytes && i < len(pixelInfo.UnprocessedValueData); i++ {
					pixelInfo.UnprocessedValueData[i] = 0
				}
			}
		}
	}

	var buf bytes.Buffer
	if err := dicom.Write(&buf, dataset); err != nil {
		log.Printf("[Erro A] Erro ao gravar DICOM: %v", err)
		return nil, err
	}

	elapsed := time.Since(startTime).Seconds() * 1000
	meta := &pb.Metadata{
		Modality:       "CT",
		Rows:           linhas,
		Columns:        colunas,
		SliceThickness: 1.25,
		RemovedPhiTags: []string{
			"Patient ID", "Patient Name", "Patient Birth Date", "Patient Sex", 
			"Patient Age", "Ethnic Group", "Study Date", "Series Date", 
			"Study Description", "Admitting Diagnosis Description", "Burn-in Text",
		},
	}

	log.Printf("[Servidor A] DICOM Anonimizado: %s em %.2fms", idAnonimo, elapsed)
	req.Slice.Data = buf.Bytes()
	req.Slice.SliceId = idAnonimo

	return &pb.AnonymizeResponse{Slice: req.Slice, Metadata: meta}, nil
}

func main() {
	lis, err := net.Listen("tcp", ":50051")
	if err != nil { 
		log.Fatalf("Porta 50051 travada: %v", err) 
	}
	s := grpc.NewServer()
	pb.RegisterAnonymizerServer(s, &anonymizerServer{})
	log.Println("Servidor A rodando na porta :50051")
	if err := s.Serve(lis); err != nil {
		log.Fatalf("Erro ao rodar servidor: %v", err)
	}
}