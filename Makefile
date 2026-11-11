# Run the Dock server on a local Kubernetes cluster (kind). Free, no cloud needed.
# The desktop agent and Mac app keep running on the Mac as usual.
#
#   make up        # cluster + image + secret + deploy, all in one
#   make forward   # then: server at http://localhost:8000 (leave it running)
#   make smoke     # check it works
#   make down      # delete the cluster
#
# Needs: Docker Desktop running, kind, kubectl.  `make help` lists every target.

CLUSTER ?= echodock
NAMESPACE := echodock
IMAGE := dock-server:dev
PORT ?= 8000
INGRESS_NGINX_VERSION := controller-v1.15.1
# Always talk to the kind cluster, never whatever cluster kubectl points at.
KUBECTL := kubectl --context kind-$(CLUSTER) --namespace $(NAMESPACE)

.PHONY: help up image cluster load secret deploy forward smoke ingress logs status down

help:
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-9s %s\n", $$1, $$2}'

up: cluster image load secret deploy ## Everything: cluster, image, secret, deploy

image: ## Build the server image (dock-server:dev)
	docker build -t $(IMAGE) server

cluster: ## Create the kind cluster (skipped if it exists)
	@kind get clusters 2>/dev/null | grep -qx $(CLUSTER) \
	  && echo "Cluster $(CLUSTER) already exists." \
	  || kind create cluster --config deploy/kind/cluster.yaml --name $(CLUSTER)

load: ## Copy the image into the kind cluster
	kind load docker-image $(IMAGE) --name $(CLUSTER)

# The Secret is made from your environment, never from a committed file.
# Token: $DOCK_TOKEN, else .dock-token (same as scripts/start.sh).
# AWS keys for Bedrock (optional):
#   AWS=echodock-bedrock  keys from that AWS profile (a Bedrock-only IAM user; they don't expire)
#   AWS=1                 your current `aws login` keys (expire after about 15 minutes)
secret: ## Create/update the Secret (DOCK_TOKEN; AWS=<profile> adds Bedrock keys)
	@set -e; \
	token="$${DOCK_TOKEN:-$$(cat .dock-token 2>/dev/null || true)}"; \
	if [ -z "$$token" ]; then echo "No token: set DOCK_TOKEN or create .dock-token (openssl rand -hex 16 > .dock-token)"; exit 1; fi; \
	envfile=$$(mktemp); trap 'rm -f "$$envfile"' EXIT; chmod 600 "$$envfile"; \
	echo "DOCK_TOKEN=$$token" > "$$envfile"; \
	if [ "$(AWS)" = "1" ]; then \
	  aws configure export-credentials --format env-no-export >> "$$envfile" \
	    || { echo "Couldn't read AWS credentials. Run: aws login"; exit 1; }; \
	elif [ -n "$(AWS)" ]; then \
	  aws configure export-credentials --profile "$(AWS)" --format env-no-export >> "$$envfile" \
	    || { echo "Couldn't read the AWS profile '$(AWS)'. See README: Deploy on Kubernetes."; exit 1; }; \
	fi; \
	kubectl --context kind-$(CLUSTER) apply -f deploy/k8s/namespace.yaml >/dev/null; \
	$(KUBECTL) create secret generic dock-server-secrets --from-env-file="$$envfile" \
	  --dry-run=client -o yaml | $(KUBECTL) apply -f -; \
	if $(KUBECTL) get deployment dock-server >/dev/null 2>&1; then \
	  $(KUBECTL) rollout restart deployment/dock-server; fi

deploy: ## Apply the manifests and wait until the pod is ready
	@$(KUBECTL) get secret dock-server-secrets >/dev/null 2>&1 || { echo "Create the Secret first: make secret"; exit 1; }
	kubectl --context kind-$(CLUSTER) apply -k deploy/k8s
	$(KUBECTL) rollout status deployment/dock-server --timeout=180s

forward: ## Reach the server at http://localhost:8000 (PORT=... to change; Ctrl+C stops)
	@echo "Dock server: http://localhost:$(PORT)  (setup page: http://localhost:$(PORT)/setup)"
	@echo "Stop the local server first (scripts/start.sh also uses port 8000)."
	@# A port-forward is tied to one pod and stops when the pod is replaced
	@# (make secret, make deploy, crashes), so start it again each time.
	@while true; do \
	  $(KUBECTL) port-forward service/dock-server $(PORT):80; \
	  echo "Port-forward stopped (pod restarted?). Reconnecting..."; sleep 2; \
	  $(KUBECTL) rollout status deployment/dock-server --timeout=120s >/dev/null 2>&1 || true; \
	done

smoke: ## Health, MCP, auth and WebSocket checks against the cluster
	@set -e; \
	token=$$($(KUBECTL) get secret dock-server-secrets -o jsonpath='{.data.DOCK_TOKEN}' | base64 --decode); \
	$(KUBECTL) port-forward service/dock-server 18000:80 >/dev/null 2>&1 & pf=$$!; trap 'kill $$pf' EXIT; \
	for i in 1 2 3 4 5 6 7 8 9 10; do curl -s -o /dev/null http://localhost:18000/healthz && break; sleep 1; done; \
	uv run --project server python deploy/smoke_test.py --url http://localhost:18000 --token "$$token"

ingress: ## Optional: ingress-nginx + Ingress at http://localhost:8081
	kubectl --context kind-$(CLUSTER) apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/$(INGRESS_NGINX_VERSION)/deploy/static/provider/kind/deploy.yaml
	kubectl --context kind-$(CLUSTER) --namespace ingress-nginx wait --for=condition=ready pod \
	  --selector=app.kubernetes.io/component=controller --timeout=180s
	kubectl --context kind-$(CLUSTER) apply -k deploy/k8s/ingress
	@echo "Dock server: http://localhost:8081"

logs: ## Follow the server's log
	$(KUBECTL) logs -f deployment/dock-server

status: ## Show the pod, service and volume
	$(KUBECTL) get pods,services,pvc,ingress

down: ## Delete the kind cluster (and everything in it)
	kind delete cluster --name $(CLUSTER)
