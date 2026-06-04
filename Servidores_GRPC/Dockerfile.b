FROM golang:alpine AS builder

RUN apk add --no-cache protoc protobuf-dev make

ENV GO111MODULE=on
RUN go install google.golang.org/protobuf/cmd/protoc-gen-go@v1.28 \
    && go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@v1.2

WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download

COPY . .

RUN make compile

RUN go build -o servidor_b servidores/servidor_b.go

FROM alpine:latest
WORKDIR /app
COPY --from=builder /app/servidor_b .
EXPOSE 50052
CMD ["./servidor_b"]
