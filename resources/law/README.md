# Law and guidance corpus (runtime assets)

These files are loaded at runtime to ground the LLM layers. They are **not**
examples — a deployment without them runs "law-grounded" review with no law
text, which is why `/api/health` reports `law_loaded` and the server warns at
startup when they are missing.

| File | What |
|------|------|
| `the_law-english_translation.txt` | Prevention of Cruelty to Animals Law (Experiments on Animals), 5754-1994 — English translation used in prompts |
| `the_law.txt` | Same law, Hebrew original |
| `national-guidance-2025-he.pdf` | National Council general guidance for filling the request form, 2025 update (Hebrew) |
