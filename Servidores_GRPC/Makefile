PROTO_FILE=medimg.proto

all: compile modules tidy

compile:
	export PATH="$$PATH:$$(go env GOPATH)/bin" && \
	protoc --go_out=. --go-grpc_out=. $(PROTO_FILE)
	@echo "Compilação realizada com sucesso"

modules:
	go get google.golang.org/grpc
	go get google.golang.org/protobuf

tidy:
	go mod tidy
	@echo "go.mod atualizado!"

run-a:
	go run servidores/servidor_a.go

run-b:
	go run servidores/servidor_b.go