FROM golang:alpine AS builder

WORKDIR /app
COPY modulo_rest_mirror/go.mod ./
COPY modulo_rest_mirror/servidor_b ./servidor_b
RUN go mod tidy && go build -o servidor_b_rest ./servidor_b

FROM alpine:latest
WORKDIR /app
COPY --from=builder /app/servidor_b_rest .
COPY benchmarks/dataset /app/dataset
EXPOSE 9002
CMD ["./servidor_b_rest"]
