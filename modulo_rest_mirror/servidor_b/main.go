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

const (
	PortaPadrao           = "9002"
	DiretorioArquivos     = "dataset"
	ValorMaximoPixel16Bit = 65535
	ValorMinimoPixel      = 0
	IncrementoDeBrilho    = 2000
	CentroContraste16Bit  = 128
	FatorEscalaContraste  = 2
)

type Slice struct {
	SliceID string `json:"slice_id"`
	Index   int32  `json:"index"`
	DataB64 string `json:"data_b64"`
}

type EnhanceRequest struct {
	SliceID        string `json:"slice_id"`
	Index          int32  `json:"index"`
	DataB64        string `json:"data_b64"`
	ApplyClahe     bool   `json:"apply_clahe"`
	ApplyDenoise   bool   `json:"apply_denoise"`
	ApplyNormalize bool   `json:"apply_normalize"`
}

type EnhanceResponse struct {
	SliceID      string  `json:"slice_id"`
	Index        int32   `json:"index"`
	DataB64      string  `json:"data_b64"`
	ProcessingMs float64 `json:"processing_ms"`
}

type ExamRequest struct {
	ExamID string `json:"exam_id"`
}

type UploadRequest struct {
	Slices []Slice `json:"slices"`
}

type ExamSummary struct {
	ExamID      string  `json:"exam_id"`
	TotalSlices int32   `json:"total_slices"`
	SlicesOk    int32   `json:"slices_ok"`
	TotalMs     float64 `json:"total_ms"`
}

type ProgressEvent struct {
	SliceID   string  `json:"slice_id"`
	Index     int32   `json:"index"`
	Stage     string  `json:"stage"`
	ElapsedMs float64 `json:"elapsed_ms"`
}

// percorre os pixels 16-bit aplicando contraste, brilho e/ou inversao. 
// Mesma logica do gRPC Server B.
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

	var bufferEscrita bytes.Buffer
	if err := dicom.Write(&bufferEscrita, dataset); err != nil {
		return nil, fmt.Errorf("erro ao serializar o dataset DICOM modificado: %v", err)
	}
	return bufferEscrita.Bytes(), nil
}

// unario: equivalente REST do Enhance.
func handleEnhance(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "metodo nao permitido", http.StatusMethodNotAllowed)
		return
	}

	var req EnhanceRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "json invalido: "+err.Error(), http.StatusBadRequest)
		return
	}

	dados, err := base64.StdEncoding.DecodeString(req.DataB64)
	if err != nil {
		http.Error(w, "base64 invalido: "+err.Error(), http.StatusBadRequest)
		return
	}

	saida, err := aplicarFiltrosImagemDicom(dados, req.ApplyClahe, req.ApplyNormalize, req.ApplyDenoise)
	if err != nil {
		log.Printf("[Erro B-REST] Filtro unario falhou: %v", err)
		http.Error(w, "falha ao filtrar: "+err.Error(), http.StatusUnprocessableEntity)
		return
	}

	escreverJSON(w, EnhanceResponse{
		SliceID:      req.SliceID,
		Index:        req.Index,
		DataB64:      base64.StdEncoding.EncodeToString(saida),
		ProcessingMs: 0.0,
	})
}

// os fluxos de streaming do gRPC (server e bidirecional) viram NDJSON no REST:
// uma linha JSON por item, com flush a cada item enviado.
func handleProcessExam(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "metodo nao permitido", http.StatusMethodNotAllowed)
		return
	}

	var req ExamRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "json invalido: "+err.Error(), http.StatusBadRequest)
		return
	}
	log.Printf("[Servidor B-REST] Buscando lote do Exame ID: %s", req.ExamID)

	w.Header().Set("Content-Type", "application/x-ndjson")
	flusher, _ := w.(http.Flusher)
	enc := json.NewEncoder(w)

	arquivosExame := []string{
		fmt.Sprintf("%s/fatia1.dcm", DiretorioArquivos),
		fmt.Sprintf("%s/fatia2.dcm", DiretorioArquivos),
	}

	for indice, caminhoArquivo := range arquivosExame {
		bytesOriginais, err := os.ReadFile(caminhoArquivo)
		if err != nil {
			log.Printf("[Aviso B-REST] Arquivo ausente, pulando: %s", caminhoArquivo)
			continue
		}
		bytesFiltrados, err := aplicarFiltrosImagemDicom(bytesOriginais, true, false, false)
		if err != nil {
			log.Printf("[Erro B-REST] Falha ao filtrar lote: %v", err)
			continue
		}
		_ = enc.Encode(EnhanceResponse{
			SliceID:      fmt.Sprintf("Fatia_Processada_%d", indice+1),
			Index:        int32(indice + 1),
			DataB64:      base64.StdEncoding.EncodeToString(bytesFiltrados),
			ProcessingMs: 0.0,
		})
		if flusher != nil {
			flusher.Flush()
		}
	}
}

// client streaming -> array de slices num unico corpo.
func handleUploadExam(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "metodo nao permitido", http.StatusMethodNotAllowed)
		return
	}

	var req UploadRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "json invalido: "+err.Error(), http.StatusBadRequest)
		return
	}

	recebidas := int32(0)
	for _, fatia := range req.Slices {
		dados, err := base64.StdEncoding.DecodeString(fatia.DataB64)
		if err != nil {
			log.Printf("[Aviso B-REST] base64 invalido em %s, pulando", fatia.SliceID)
			continue
		}
		destino := fmt.Sprintf("%s/upload_fatia_%s.dcm", DiretorioArquivos, fatia.SliceID)
		_ = os.WriteFile(destino, dados, 0644)
		recebidas++
	}

	escreverJSON(w, ExamSummary{
		ExamID:      "Upload_Hospitalar_Registrado",
		TotalSlices: recebidas,
		SlicesOk:    recebidas,
		TotalMs:     0.0,
	})
}

// bidirecional -> array na entrada, NDJSON (eventos de progresso) na saida.
func handleLiveProcess(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "metodo nao permitido", http.StatusMethodNotAllowed)
		return
	}

	var req UploadRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "json invalido: "+err.Error(), http.StatusBadRequest)
		return
	}

	w.Header().Set("Content-Type", "application/x-ndjson")
	flusher, _ := w.(http.Flusher)
	enc := json.NewEncoder(w)

	for _, fatia := range req.Slices {
		dados, err := base64.StdEncoding.DecodeString(fatia.DataB64)
		if err != nil {
			log.Printf("[Aviso B-REST] base64 invalido em %s, pulando", fatia.SliceID)
			continue
		}
		if _, err := aplicarFiltrosImagemDicom(dados, true, true, false); err != nil {
			log.Printf("[Servidor B-REST] Erro ao tratar fluxo ao vivo: %v", err)
			continue
		}
		_ = enc.Encode(ProgressEvent{
			SliceID:   fatia.SliceID,
			Index:     fatia.Index,
			Stage:     "Filtros de Nitidez e Brilho Aplicados com Sucesso",
			ElapsedMs: 0.0,
		})
		if flusher != nil {
			flusher.Flush()
		}
	}
}

func handleHealth(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	_, _ = w.Write([]byte(`{"status":"ok","servidor":"B-REST"}`))
}

func escreverJSON(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(v); err != nil {
		log.Printf("[Erro B-REST] Falha ao serializar resposta: %v", err)
	}
}

// registra as rotas e sobe o servidor HTTP (porta padrao 9002).
func main() {
	porta := os.Getenv("PORT")
	if porta == "" {
		porta = PortaPadrao
	}

	http.HandleFunc("/enhance", handleEnhance)
	http.HandleFunc("/process-exam", handleProcessExam)
	http.HandleFunc("/upload-exam", handleUploadExam)
	http.HandleFunc("/live-process", handleLiveProcess)
	http.HandleFunc("/health", handleHealth)

	log.Printf("Servidor B (REST) rodando na porta :%s", porta)
	if err := http.ListenAndServe(":"+porta, nil); err != nil {
		log.Fatalf("Erro ao subir servidor B-REST: %v", err)
	}
}
