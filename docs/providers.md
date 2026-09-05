# LLM providers

EtiqTech talks to one provider at a time, selected by `LLM_PROVIDER` (default `ollama`) or
per upload from the UI. All three adapters expose the same two calls the review layers use
— `call_llm()` (full text) and `call_llm_stream()` (tokens for the SSE stream) — so the
browser experience is identical whichever provider is configured.

**Local-first applies to every provider.** Each provider's base URL goes through the same
gate: a public host is refused unless `ETIQTECH_ALLOW_REMOTE_LLM=1` is set, and the server
logs a warning when it is. HTTP redirects are never followed.

## Capability matrix

| provider | env | base URL default | streaming | JSON mode | thinking | two-step (think→structure) | can be local |
|---|---|---|---|---|---|---|---|
| `ollama` | `OLLAMA_BASE_URL`, `OLLAMA_MODEL` (`qwen3.5:35b`), `OLLAMA_API_KEY` (cloud only) | `http://127.0.0.1:11434` | yes (`/api/generate` stream) | yes (`OLLAMA_FORMAT=json`) | yes (`OLLAMA_THINK=1`) | yes (`OLLAMA_TWO_STEP=1`) | **yes — the default** |
| `openai` | `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `OPENAI_MODEL` (required), `OPENAI_JSON_MODE=1` | `https://api.openai.com/v1` | yes (SSE `data:` chunks) | yes (`response_format=json_object`, opt-in) | no | no (falls back to single call) | yes, with a `localhost`/LAN base URL: vLLM, LM Studio, llama.cpp server, OpenRouter-style gateways in-cluster |
| `anthropic` | `ANTHROPIC_API_KEY` (or `ANTHROPIC_AUTH_TOKEN`), `ANTHROPIC_MODEL` (`claude-opus-5`), `ANTHROPIC_BASE_URL` | `https://api.anthropic.com` | yes (SDK `messages.stream`) | no (prompt asks for JSON; parser tolerates prose around it) | model default (adaptive) | no | **no** — always remote |

Notes
- `anthropic` uses the official `anthropic` SDK (`pip install etiqtech[anthropic]`). No sampling
  parameters are sent (current Claude models reject them); `stop_reason: refusal` is surfaced as an
  LLM error for that theme, never silently swapped to another model.
- `openai` does not pin a default model: set `OPENAI_MODEL` to whatever your server serves.
- The UI lists only providers that are configured (credentials or base URL present) and marks
  remote ones; a remote provider without the opt-in flag is shown disabled.
- Governance: choosing a remote provider is the deployment's decision and must be reflected in
  its privacy notice (see PRIVACY.md guarantee 4).

## Adding a provider

Implement `_call_<name>()` and `_call_<name>_stream()` in `src/llm_clients.py`, register the
env names and capabilities in `PROVIDERS`, resolve the base URL through `gated_base_url()`,
and add a recorded-response contract test in `tests/test_providers.py`.
