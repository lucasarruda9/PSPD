#!/usr/bin/env bash
set -euo pipefail

REGISTRY_PREFIX="pspd"
NAMESPACE="pspd"
PROJETO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

log "iniciando minikube"
minikube start --nodes 3 --driver=docker

log "habilitando métricas pro HPA"
minikube addons enable metrics-server

log "buildando imagens localmente para depois transferir ao cluster"
docker build -t "pspd-modulo-a-servidor:latest" -f "${PROJETO_ROOT}/Servidores_GRPC/Dockerfile.a" "${PROJETO_ROOT}/Servidores_GRPC"
docker build -t "pspd-modulo-b-servidor:latest" -f "${PROJETO_ROOT}/Servidores_GRPC/Dockerfile.b" "${PROJETO_ROOT}"

log "buildando imagem do gateway"
docker build -t "${REGISTRY_PREFIX}/modulo-p-gateway:latest" -f "${PROJETO_ROOT}/modulo_p_gateway/Dockerfile" "${PROJETO_ROOT}"

log "buildando imagens do espelho REST"
docker build -t "${REGISTRY_PREFIX}/modulo-rest-a:latest" -f "${PROJETO_ROOT}/modulo_rest_mirror/Dockerfile.a" "${PROJETO_ROOT}/modulo_rest_mirror"
docker build -t "${REGISTRY_PREFIX}/modulo-rest-b:latest" -f "${PROJETO_ROOT}/modulo_rest_mirror/Dockerfile.b" "${PROJETO_ROOT}"
docker build -t "${REGISTRY_PREFIX}/modulo-rest-mirror:latest" -f "${PROJETO_ROOT}/modulo_rest_mirror/gateway/Dockerfile" "${PROJETO_ROOT}/modulo_rest_mirror/gateway"

log "transferindo imagem pra os 3 nós"
minikube image load pspd-modulo-a-servidor:latest
minikube image load pspd-modulo-b-servidor:latest
minikube image load ${REGISTRY_PREFIX}/modulo-p-gateway:latest
minikube image load ${REGISTRY_PREFIX}/modulo-rest-a:latest
minikube image load ${REGISTRY_PREFIX}/modulo-rest-b:latest
minikube image load ${REGISTRY_PREFIX}/modulo-rest-mirror:latest

log "kubernetes"
kubectl apply -f "${PROJETO_ROOT}/infra/namespace.yaml"
kubectl apply -f "${PROJETO_ROOT}/infra/modulo-a.yaml"
kubectl apply -f "${PROJETO_ROOT}/infra/modulo-b.yaml"
kubectl apply -f "${PROJETO_ROOT}/infra/modulo-p.yaml"
kubectl apply -f "${PROJETO_ROOT}/infra/modulo-rest-mirror.yaml"
kubectl apply -f "${PROJETO_ROOT}/infra/hpa.yaml"
kubectl apply -f "${PROJETO_ROOT}/infra/monitoring.yaml"

sleep 5

kubectl get all -n "${NAMESPACE}"

echo "============================================="
echo "Gateway gRPC (P): $(minikube service modulo-p-gateway -n ${NAMESPACE} --url | head -n 1)"
echo "Gateway REST (P'): $(minikube service modulo-rest-mirror -n ${NAMESPACE} --url | head -n 1)"
echo "Prometheus: $(minikube service prometheus -n ${NAMESPACE} --url | head -n 1)"
echo "Grafana: $(minikube service grafana -n ${NAMESPACE} --url | head -n 1)"
echo "============================================="
