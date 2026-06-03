package main

import (
	"context"
	"log"
	"net"
	"time"

	"google.golang.org/grpc"
	pb "pspd-servidores/proto"
)

type anonymizerServer struct {
	pb.UnimplementedAnonymizerServer
}

// unário
func (s *anonymizerServer) Anonymize(ctx context.Context, req *pb.AnonymizeRequest) (*pb.AnonymizeResponse, error) {
	time.Sleep(15 * time.Millisecond)
	meta := &pb.Metadata{
		Modality:          "CT", 
		Rows:              512,
		Columns:           512,
		SliceThickness:    1.25,
		RemovedPhiTags:    []string{"PatientName", "PatientID", "InstitutionName", "AnonymizedDate"},
	}
	log.Printf("[Servidor A] Fatia %s anonimizada com sucesso.", req.Slice.SliceId)

	return &pb.AnonymizeResponse{Slice: req.Slice, Metadata: meta,}, nil
}

func main() {
	lis, err := net.Listen("tcp", ":50051")
	if err != nil {
		log.Fatalf("Falha ao abrir porta 50051: %v", err)
	}
	s := grpc.NewServer()
	pb.RegisterAnonymizerServer(s, &anonymizerServer{})
	log.Println("Servidor A online na porta :50051")

	if err := s.Serve(lis); err != nil {
		log.Fatalf("Erro ao rodar Servidor A: %v", err)
	}
}