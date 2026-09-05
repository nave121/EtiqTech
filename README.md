# EtiqTech

AI-powered ethics review pipeline for animal research protocols (IACUC).
Parses institutional HTML exports into structured JSON, lints against
Israeli animal welfare law, and optionally verifies with a local LLM.

> **Disclaimer**: This tool is provided **as-is** for research and educational
> purposes only. It is **not** a substitute for professional legal, veterinary,
> or regulatory advice. The authors accept no responsibility for decisions made
> based on its output. Always consult your institutional IACUC committee and
> qualified personnel before submitting or approving animal research protocols.

---

## Quick Start

### Docker (recommended)

```bash
docker build -t etiqtech .
docker run -p 4242:4242 etiqtech
```

Open http://localhost:4242 — upload an HTML protocol export and get instant results.

The image serves with `gunicorn -c gunicorn.conf.py`: **one worker, 16 threads**.
Sessions and rate-limit counters live in process memory, so the app must not be
run with several workers (the SSE stream would land on a process that never saw
the upload). Scale by running one container per replica; see `gunicorn.conf.py`
for the shared-store path if that ever changes.

To connect a local Ollama instance for LLM verification:

```bash
docker run -p 4242:4242 \
  -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
  etiqtech
```

### Local Python

```bash
pip install -r requirements.txt
python server/app.py
# → http://localhost:4242
```

### CLI

```bash
pip install -r requirements.txt

# Parse HTML to JSON
python src/html_to_json.py input.html output/parsed.json

# Lint (structural check)
python -m src.linter_renderer lint output/parsed.json --report output/report.json

# Lint (strict law profile)
python -m src.linter_renderer lint output/parsed.json --profile strict_law

# Render JSON back to RTL HTML
python -m src.linter_renderer render output/parsed.json --html output/rendered.html
```

---

## How It Works

EtiqTech reviews protocols in three layers:

| Layer | What | How | Required? |
|-------|------|-----|-----------|
| **Layer 1 — Linter** | Deterministic rule checks | 36+ rules checking structure, law compliance, AVMA euthanasia matrix | Yes |
| **Layer 2 — LLM Themes** | Semantic review across 12 themes | Dual-pass: blind review then reconciliation with linter findings | Optional (needs Ollama) |
| **Layer 3 — Human Eye** | Holistic adversarial review | Triggered when Layer 1/2 flag issues; dual-pass with cross-layer reconciliation | Auto-triggered |

### Linter Profiles

- `default` — structural gatekeeper. Use for "can I submit this?" checks.
- `strict_law` — ideal law alignment. Upgrades law-critical items to hard errors.

### LLM Verification Themes

`three_Rs_alternatives` · `N_and_justification` · `severity_monitoring_analgesia` · `euthanasia_and_endpoints` · `harm_benefit_analysis` · `sex_and_reuse` · `housing_and_husbandry` · `scientific_coherence` · `personnel_and_training` · `hazardous_agents` · `surgical_standards` · `writing_quality`

---

## Architecture

| Component | File | Description |
|-----------|------|-------------|
| Parser | `src/html_to_json.py` | HTML→JSON from institutional exports |
| Schema | `src/schema.py` | `IACUC_SCHEMA_V2` with `x_meta` rules per field |
| Linter + Renderer | `src/linter_renderer.py` | 36+ rules, 2 profiles, RTL HTML output |
| AVMA Matrix | `src/avma_matrix.py` | Species×method euthanasia validation (8 species) |
| LLM Layer 2 | `src/llm_agent.py` | 12-theme dual-pass verification |
| LLM Layer 3 | `src/llm_layer3.py` | Holistic adversarial review |
| LLM Client | `src/llm_clients.py` | Ollama adapter with timing stats |
| x_meta Catalog | `src/xmeta_catalog.py` | Grounded examples from approved fixtures |
| Golden Dataset | `src/golden_dataset.py` | 28 canonical test pairs |
| Web Server | `server/app.py` | Flask + SSE streaming on port 4242 |
| Web UI | `server/templates/` | RTL analyzer with real-time LLM progress |

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama server URL |
| `OLLAMA_MODEL` | `qwen3.5:35b` | Model for verification |
| `LLM_TEMPERATURE` | `0.2` | Sampling temperature |
| `LLM_MAX_TOKENS` | `8192` | Max output tokens |
| `OLLAMA_NUM_CTX` | `32768` | Context window size |
| `OLLAMA_TIMEOUT_SECONDS` | `120` | Request timeout |
| `OLLAMA_TWO_STEP` | `false` | Enable think-then-structure mode |
| `LAYER3_SAMPLING_RATE` | `0.10` | Fraction of clean protocols to spot-check |
| `FLASK_DEBUG` | `false` | Enable Flask debug mode |
| `SECRET_KEY` | (random) | Required in production |

---

## Testing

```bash
# Full suite (440 tests)
PYTHONPATH=. pytest tests/ -q

# E2E pipeline only
PYTHONPATH=. pytest tests/test_e2e_pipeline.py -v

# Batch lint all known-good fixtures
PYTHONPATH=. python scripts/batch_process.py examples/known-good/ --fail-on-error
```

---

## Runtime resources

- `resources/law/` — Israeli animal welfare law (Hebrew + English translation) and the 2025 national guidance PDF. Loaded at runtime; `/api/health` reports `law_loaded`.

## Examples

- `examples/known-good/` — approved fixtures for regression testing
- `examples/known-bad/` — fixtures with known issues
- `examples/head-to-head/` — paired bad/good versions with committee reasoning
- `examples/golden-dataset/` — 28 canonical test pairs (synthetic + adversarial)

---

## Roadmap

Short-term next steps for the public release:

- `TODO` Multi-provider LLM support: add pluggable providers beyond Ollama, including OpenAI, Claude, Gemini, and OpenRouter, with a unified config surface and provider-specific safety fallbacks.
- `TODO` Committee feedback loop: refine lint rules, prompts, scoring, and UX based on real review feedback from the committee so the tool becomes more precise and less noisy over time.
- `TODO` Authentication layer: add a proper auth boundary before any broader deployment, likely via reverse proxy or app-level login, with session protection and audit-friendly access control.

The aim is to keep the deterministic linter as the backbone, while making the LLM layer more portable, the review output more committee-aligned, and the deployment story safer.

---

## Security

EtiqTech runs **locally** with no authentication. Do not expose to the public
internet without an auth layer. No data is sent to external services.

See [SECURITY.md](SECURITY.md) for the full policy and threat model.

---

## License

[MIT](LICENSE)
