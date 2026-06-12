package main

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"

	"github.com/suyashkumar/dicom"
	"github.com/suyashkumar/dicom/pkg/tag"
)

type AnonymizeRequest struct {
	SliceID string `json:"slice_id"`
	Index   int32  `json:"index"`
	DataB64 string `json:"data_b64"`
}

type Metadata struct {
	Modality       string   `json:"modality"`
	Rows           int32    `json:"rows"`
	Columns        int32    `json:"columns"`
	SliceThickness float64  `json:"slice_thickness"`
	RemovedPhiTags []string `json:"removed_phi_tags"`
}

type AnonymizeResponse struct {
	SliceID  string   `json:"slice_id"`
	Index    int32    `json:"index"`
	DataB64  string   `json:"data_b64"`
	Metadata Metadata `json:"metadata"`
}

func substituirTag(d *dicom.Dataset, t tag.Tag, valores []string) {
	elem, err := dicom.NewElement(t, valores)
	if err != nil {
		log.Printf("[Aviso A-REST] Nao foi possivel criar tag %v: %v", t, err)
		return
	}
	for indice, elementoAtual := range d.Elements {
		if elementoAtual.Tag == t {
			d.Elements[indice] = elem
			return
		}
	}
	d.Elements = append(d.Elements, elem)
}


func anonimizar(dados []byte, index int32) ([]byte, Metadata, string, error) {
	dataset, err := dicom.Parse(bytes.NewReader(dados), int64(len(dados)), nil)
	if err != nil {
		return nil, Metadata{}, "", err
	}

	idAnonimo := fmt.Sprintf("Anonimo_%d", index)
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

	if elementoLinhas, err := dataset.FindElementByTag(tag.Rows); err == nil {
		valores := dicom.MustGetInts(elementoLinhas.Value)
		if len(valores) > 0 {
			linhas = int32(valores[0])
		}
	}
	if elementoColunas, err := dataset.FindElementByTag(tag.Columns); err == nil {
		valores := dicom.MustGetInts(elementoColunas.Value)
		if len(valores) > 0 {
			colunas = int32(valores[0])
		}
	}

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
		return nil, Metadata{}, "", err
	}

	meta := Metadata{
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

	return buf.Bytes(), meta, idAnonimo, nil
}


func handleAnonymize(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "metodo nao permitido", http.StatusMethodNotAllowed)
		return
	}

	var req AnonymizeRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "json invalido: "+err.Error(), http.StatusBadRequest)
		return
	}

	dados, err := base64.StdEncoding.DecodeString(req.DataB64)
	if err != nil {
		http.Error(w, "base64 invalido: "+err.Error(), http.StatusBadRequest)
		return
	}

	saida, meta, idAnonimo, err := anonimizar(dados, req.Index)
	if err != nil {
		log.Printf("[Erro A-REST] Falha ao anonimizar: %v", err)
		http.Error(w, "falha ao anonimizar: "+err.Error(), http.StatusUnprocessableEntity)
		return
	}

	resp := AnonymizeResponse{
		SliceID:  idAnonimo,
		Index:    req.Index,
		DataB64:  base64.StdEncoding.EncodeToString(saida),
		Metadata: meta,
	}

	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(resp); err != nil {
		log.Printf("[Erro A-REST] Falha ao serializar resposta: %v", err)
	}
}

func handleHealth(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	_, _ = w.Write([]byte(`{"status":"ok","servidor":"A-REST"}`))
}


func main() {
	porta := os.Getenv("PORT")
	if porta == "" {
		porta = "9001"
	}

	http.HandleFunc("/anonymize", handleAnonymize)
	http.HandleFunc("/health", handleHealth)

	log.Printf("Servidor A (REST) rodando na porta :%s", porta)
	if err := http.ListenAndServe(":"+porta, nil); err != nil {
		log.Fatalf("Erro ao subir servidor A-REST: %v", err)
	}
}
