# Deploying EtiqTech (Kubernetes, Argo CD)

Kustomize layout. Argo CD points at one overlay; nothing sensitive is in git.

| Path | Role |
|------|------|
| `base/` | App Deployment + Service, ServiceAccount (no token automount), local-first NetworkPolicy (egress only to `app=ollama:11434` and DNS). |
| `overlays/local-ollama/` | base + in-cluster Ollama on a GPU node. Privacy-complete: protocol text never leaves the cluster. |
| `overlays/prod-remote/` | **The Argo target.** base + remote LLM (Anthropic default, OpenAI-compatible optional), Secrets by reference, egress opened to 443, GHCR image. Protocol text goes to the provider. |
| `overlays/remote-llm/` | Ollama Cloud variant of the same idea. Read its header. |
| `../argocd/application.yaml` | Argo CD `Application`: repo `https://github.com/nave121/EtiqTech`, branch `main`, path `k8s/overlays/prod-remote`, namespace `etiqtech`, automated sync with prune and self-heal. |

## What you need before the first sync

1. **A cluster Argo CD can reach, with a namespace `etiqtech`.** The Application creates it (`CreateNamespace=true`); create it yourself if your Argo project forbids that.
2. **The image.** CI job `publish` pushes `ghcr.io/nave121/etiqtech:main` and `:sha-<short>` on every green push to `main`. The workflow token needs *Read and write* workflow permissions (repository → Settings → Actions → General), and no pre-existing package of the same name may sit unlinked under the owner (that is exactly what blocked the first three runs: two stale March packages, deleted 2026-09-13). The package created by Actions from this public repo is public, so no `imagePullSecret` is needed; if you make it private, add one to the ServiceAccount in `base/rbac.yaml`. Pin `newTag` in `overlays/prod-remote/kustomization.yaml` to a `sha-` tag for reproducible rollouts; `main` floats, and a new image under the same tag does not restart the pod by itself (`kubectl -n etiqtech rollout restart deploy/etiqtech`).
3. **Two Secrets in the namespace**, created out of band (keys must match `deployment-patch.yaml`):

   ```bash
   kubectl create namespace etiqtech
   kubectl -n etiqtech create secret generic etiqtech-app \
     --from-literal=SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
   kubectl -n etiqtech create secret generic etiqtech-llm \
     --from-literal=ANTHROPIC_API_KEY='sk-ant-...'        # or OPENAI_API_KEY
   ```

   `SECRET_KEY` is mandatory; the app refuses to start in production without it. Shape for External Secrets or Sealed Secrets is in `overlays/prod-remote/secrets.template.yaml`.
4. **The public origin.** Set `ALLOWED_ORIGINS` in `overlays/prod-remote/deployment-patch.yaml` to exactly `https://<your-host>` (scheme + host, no path, no trailing slash). With `PROXY_FIX=1` the app does not trust the forwarded Host header, so without this every upload is refused as cross-site. Commit that change; Argo syncs it.
5. **Auth and TLS in front of `Service etiqtech` (port 80 → 4242).** The app has no login by design. The reference pattern is Cloudflare Tunnel + Cloudflare Access; any identity-aware proxy works. The proxy must set `X-Forwarded-For` (one hop; `PROXY_FIX=1` trusts exactly one).
6. **The LLM decision, in writing.** `ETIQTECH_ALLOW_REMOTE_LLM=1` in the overlay is the informed opt-in: every uploaded protocol is sent to Anthropic or OpenAI. The app logs a WARNING at startup and `/api/health` reports `llm_local: false`. Tell your users; in the EU this is a data-processing conversation. To stay on-cluster instead, point the Application at `overlays/local-ollama` and provision a GPU node (~24 GB VRAM for `qwen3.5:35b`, then `kubectl -n etiqtech exec deploy/ollama -- ollama pull qwen3.5:35b`).

## Environment variables (what the overlay sets and what else exists)

| Variable | Set in prod-remote | Meaning |
|---|---|---|
| `SECRET_KEY` | Secret `etiqtech-app` | Flask session/CSRF key. Required. |
| `PROXY_FIX` | `1` | Trust one `X-Forwarded-*` hop. Only behind a proxy. |
| `ALLOWED_ORIGINS` | placeholder, **edit it** | Origins allowed to POST. Required with `PROXY_FIX`. Comma-separated. |
| `LLM_PROVIDER` | `anthropic` | `ollama` \| `openai` \| `anthropic`. |
| `ETIQTECH_ALLOW_REMOTE_LLM` | `1` | Opt-in to non-local LLM hosts. Unset = refused. |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` | Secret / `claude-opus-5` | Anthropic provider. `ANTHROPIC_BASE_URL` optional. |
| `OPENAI_API_KEY` / `OPENAI_MODEL` / `OPENAI_BASE_URL` | commented block | OpenAI-compatible provider. `OPENAI_MODEL` has no default. |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` / `OLLAMA_NUM_CTX` | base values | Ignored unless `LLM_PROVIDER=ollama`. |
| `LLM_TEMPERATURE` / `LLM_MAX_TOKENS` / `OLLAMA_TIMEOUT_SECONDS` | `0.2` / `8192` / `300` | Sampling and per-call timeout. Anthropic ignores sampling. |
| `ETIQTECH_FEEDBACK` | `0` | Thumbs up/down store (SQLite, metadata only). `1` needs a PVC mounted at `/app/output`, otherwise it is wiped on restart. |
| `ETIQTECH_LLM_DISABLED` | unset | `1` = linter-only demo mode, no LLM at all. |
| `ETIQTECH_GROUNDING` | unset (off) | Retrieval-grounded prompts. Off by default after the eval; see `docs/benchmarks.md`. |
| `LOG_LEVEL` | `INFO` | No protocol text is logged at any level. |
| `GUNICORN_THREADS` | default 64 | Max concurrent LLM streams. Keep `replicas: 1`: sessions and rate limits are in-process. |
| `RATELIMIT_ENABLED` | default on | `false` is refused in production. |

## Deploy

```bash
# 1. secrets (above), 2. edit ALLOWED_ORIGINS and pin newTag, commit, push
kubectl apply -f argocd/application.yaml
argocd app sync etiqtech && argocd app wait etiqtech --health
kubectl -n etiqtech port-forward svc/etiqtech 4242:80 &
curl -s localhost:4242/api/health      # expect law_loaded true, llm_enabled true, llm_local false, llm_remote_allowed true
python scripts/browser_smoke.py http://localhost:4242 examples/head-to-head/1/bad.html   # through the tunnel URL once Access is up
```

Startup logs must show exactly one WARNING about the remote LLM opt-in and nothing about the law text. If uploads return 403 "cross-origin request blocked", `ALLOWED_ORIGINS` does not match the origin the browser sends.

## Render locally

```bash
kubectl kustomize k8s/overlays/prod-remote
```
