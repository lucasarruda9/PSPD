#!/usr/bin/env bash
set -euo pipefail

REGISTRY_PREFIX="pspd"
NAMESPACE="pspd"
PROJETO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

minikube start --nodes 3 --driver=docker --cpus=2 --memory=2048

minikube addons enable metrics-server
eval "$(minikube docker-env)"
docker build -t "${REGISTRY_PREFIX}/modulo-p-gateway:latest" \
    -f "${PROJETO_ROOT}/modulo_p_gateway/Dockerfile" "${PROJETO_ROOT}"

kubectl apply -f "${PROJETO_ROOT}/infra/namespace.yaml"
kubectl apply -f "${PROJETO_ROOT}/infra/modulo-p.yaml"
kubectl apply -f "${PROJETO_ROOT}/infra/hpa.yaml"
kubectl apply -f "${PROJETO_ROOT}/infra/monitoring.yaml"

kubectl wait --for=condition=ready pod \
    -l app=modulo-p-gateway -n "${NAMESPACE}" --timeout=120s

kubectl get all -n "${NAMESPACE}"

echo "Gateway gRPC: $(minikube service modulo-p-gateway -n ${NAMESPACE} --url)"
echo "Prometheus: $(minikube service prometheus -n ${NAMESPACE} --url)"
echo "Grafana: $(minikube service grafana -n ${NAMESPACE} --url)"
