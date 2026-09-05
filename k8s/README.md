# Kubernetes manifests

| File | Role |
|------|------|
| `ethicchecker.yaml` | App Deployment + Service. **Default targets the in-cluster Ollama** (`http://ollama:11434`). |
| `ollama-local.yaml` | In-cluster Ollama Deployment/Service/PVC (`app=ollama`). |
| `network-policy.yaml` | Egress only to `app=ollama:11434` and DNS. Enforces local-first at the network layer. |
| `rbac.yaml` | ServiceAccount with no token automount. |
| `overlays/remote-llm/` | **Opt-in** patch for Ollama Cloud. Sends protocol text off-cluster; read its header first. |

```bash
kubectl apply -f k8s/rbac.yaml -f k8s/network-policy.yaml -f k8s/ollama-local.yaml -f k8s/ethicchecker.yaml
kubectl exec deploy/ollama -- ollama pull qwen3.5:35b
```

Authentication is not the app's job: put Cloudflare Access (or an equivalent
identity-aware proxy) in front of the Service and set `PROXY_FIX=1` so rate
limits are per user, not per proxy.
