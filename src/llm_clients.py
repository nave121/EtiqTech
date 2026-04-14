import json
import logging
import os
import re
import time
from typing import Any, Dict, Generator, Optional

import requests

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(name)s] %(message)s")


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        logger.warning("Invalid %s, using default %s", key, default)
        return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        logger.warning("Invalid %s, using default %s", key, default)
        return default


def _thinking_enabled() -> bool:
    """Return True if extended thinking mode is enabled (default: off)."""
    return os.getenv("OLLAMA_THINK", "false").strip().lower() in ("1", "true", "yes")


def _ollama_headers() -> Dict[str, str]:
    """Return auth headers for Ollama API (empty dict if no key configured)."""
    api_key = os.getenv("OLLAMA_API_KEY", "").strip()
    if api_key:
        return {"Authorization": f"Bearer {api_key}"}
    return {}


class LLMError(RuntimeError):
    """Raised when an LLM provider call fails."""


def call_llm(
    prompt: str,
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> str:
    """
    Dispatch the prompt to the configured LLM provider and return the raw text response.
    """
    provider_name = (provider or os.getenv("LLM_PROVIDER", "ollama")).strip().lower()

    if provider_name == "ollama":
        return _call_ollama(
            prompt,
            model=model or os.getenv("OLLAMA_MODEL", "qwen3.5:35b"),
            temperature=temperature,
            max_tokens=max_tokens,
        )

    if provider_name == "openai":
        raise LLMError(
            "LLM_PROVIDER=openai not yet implemented. "
            "Set LLM_PROVIDER=ollama until OpenAI support is wired up."
        )

    raise LLMError(f"Unsupported LLM provider '{provider_name}'.")


def _log_ollama_stats(body: Dict[str, Any], wall_secs: float, label: str = "") -> None:
    """Log Ollama timing stats. Durations in body are nanoseconds."""
    ns = 1_000_000_000
    load_s    = body.get("load_duration", 0) / ns
    prompt_s  = body.get("prompt_eval_duration", 0) / ns
    eval_s    = body.get("eval_duration", 0) / ns
    tokens    = body.get("eval_count", 0)
    tps       = tokens / eval_s if eval_s > 0 else 0
    tag = f"ollama/{label}" if label else "ollama"
    logger.info(
        "← %s wall=%.2fs | load=%.2fs | prompt=%.2fs | gen=%.2fs | %d tokens | %.1f t/s",
        tag, wall_secs, load_s, prompt_s, eval_s, tokens, tps,
    )
    if load_s > 5:
        logger.warning("  !! model loaded from disk (load=%.1fs) — cold start", load_s)


def _call_ollama(
    prompt: str,
    *,
    model: str,
    temperature: Optional[float],
    max_tokens: Optional[int],
) -> str:
    base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    endpoint = f"{base_url}/api/generate"
    timeout = _env_float("OLLAMA_TIMEOUT_SECONDS", 120)

    if max_tokens is None:
        max_tokens = _env_int("LLM_MAX_TOKENS", 8192)
    payload: Dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "30m"),
        "think": _thinking_enabled(),
        "options": {
            "temperature": temperature if temperature is not None else _env_float("LLM_TEMPERATURE", 0.2),
            "num_ctx": _env_int("OLLAMA_NUM_CTX", 32768),
            "num_predict": max_tokens,
            "presence_penalty": _env_float("OLLAMA_PRESENCE_PENALTY", 1.5),
        },
    }
    # Don't force JSON format by default - let models with thinking (qwen3) work naturally.
    # Set OLLAMA_FORMAT=json to force JSON mode if needed.
    format_opt = os.getenv("OLLAMA_FORMAT", "").strip()
    if format_opt:
        payload["format"] = format_opt

    logger.info("→ ollama model=%s prompt_chars=%d keep_alive=%s think=%s", model, len(prompt), payload["keep_alive"], payload["think"])
    t0 = time.time()
    response = requests.post(endpoint, json=payload, headers=_ollama_headers(), timeout=timeout)
    elapsed = time.time() - t0
    if response.status_code != 200:
        raise LLMError(f"Ollama responded with HTTP {response.status_code}: {response.text}")

    try:
        body = response.json()
    except json.JSONDecodeError as exc:
        raise LLMError(f"Failed to parse Ollama response JSON: {exc}") from exc

    _log_ollama_stats(body, elapsed)

    text = body.get("response")
    if not isinstance(text, str) or not text.strip():
        # Surface the full body so callers can debug provider-side issues.
        raise LLMError(f"Ollama response missing or empty 'response' text payload: {body!r}")

    return text.strip()


def call_llm_two_step(
    prompt: str,
    *,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> str:
    """
    Two-step think-then-structure pattern for Qwen3 (opt-in via OLLAMA_TWO_STEP=1).

    Step 1: Free reasoning with thinking mode ON — generates a <think>...</think> block.
    Step 2: Structured JSON output with the reasoning as context, at temperature=0.

    Uses Ollama /api/chat for multi-turn conversation.
    Falls back to call_llm() if provider is not ollama.
    """
    provider_name = os.getenv("LLM_PROVIDER", "ollama").strip().lower()
    if provider_name != "ollama":
        # Two-step is Ollama-specific; fall back gracefully.
        return call_llm(prompt, model=model, temperature=temperature, max_tokens=max_tokens)

    resolved_model = model or os.getenv("OLLAMA_MODEL", "qwen3.5:35b")
    base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    endpoint = f"{base_url}/api/chat"
    timeout = _env_float("OLLAMA_TIMEOUT_SECONDS", 300)

    if max_tokens is None:
        max_tokens = _env_int("LLM_MAX_TOKENS", 8192)

    resolved_temp = temperature if temperature is not None else _env_float("LLM_TEMPERATURE", 0.2)

    base_options: Dict[str, Any] = {
        "num_ctx": _env_int("OLLAMA_NUM_CTX", 32768),
        "presence_penalty": _env_float("OLLAMA_PRESENCE_PENALTY", 1.5),
    }

    # --- Step 1: Free reasoning (extract <think>...</think> block) ---
    step1_payload: Dict[str, Any] = {
        "model": resolved_model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "30m"),
        "think": _thinking_enabled(),
        "options": {**base_options, "temperature": resolved_temp, "num_predict": max_tokens},
    }

    logger.info("→ ollama/two-step[1] model=%s prompt_chars=%d keep_alive=%s", resolved_model, len(prompt), step1_payload["keep_alive"])
    t0 = time.time()
    resp1 = requests.post(endpoint, json=step1_payload, headers=_ollama_headers(), timeout=timeout)
    elapsed1 = time.time() - t0
    if resp1.status_code != 200:
        raise LLMError(f"Ollama (step 1) responded with HTTP {resp1.status_code}: {resp1.text}")

    try:
        body1 = resp1.json()
    except json.JSONDecodeError as exc:
        raise LLMError(f"Failed to parse Ollama step-1 response: {exc}") from exc

    _log_ollama_stats(body1, elapsed1, label="two-step[1]")

    step1_content = (body1.get("message") or {}).get("content") or ""

    # Extract reasoning from <think>...</think> if present; otherwise use full content.
    think_match = re.search(r"<think(?:ing)?>(.*?)</think(?:ing)?>", step1_content, re.DOTALL | re.IGNORECASE)
    reasoning = think_match.group(1).strip() if think_match else step1_content.strip()

    # --- Step 2: Structured JSON output at temperature=0 ---
    step2_messages = [
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": f"<think>\n{reasoning}\n</think>"},
        {"role": "user", "content": "Based on my analysis above, here is the structured JSON verdict:"},
    ]

    step2_payload: Dict[str, Any] = {
        "model": resolved_model,
        "messages": step2_messages,
        "stream": False,
        "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "30m"),
        "think": _thinking_enabled(),
        "options": {**base_options, "temperature": 0, "num_predict": max_tokens},
    }

    logger.info("→ ollama/two-step[2] model=%s", resolved_model)
    t2 = time.time()
    resp2 = requests.post(endpoint, json=step2_payload, headers=_ollama_headers(), timeout=timeout)
    elapsed2 = time.time() - t2
    if resp2.status_code != 200:
        raise LLMError(f"Ollama (step 2) responded with HTTP {resp2.status_code}: {resp2.text}")

    try:
        body2 = resp2.json()
    except json.JSONDecodeError as exc:
        raise LLMError(f"Failed to parse Ollama step-2 response: {exc}") from exc

    _log_ollama_stats(body2, elapsed2, label="two-step[2]")

    text = (body2.get("message") or {}).get("content")
    if not isinstance(text, str) or not text.strip():
        raise LLMError(f"Ollama two-step step-2 returned empty content: {body2!r}")

    return text.strip()


def call_llm_stream(
    prompt: str,
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> Generator[str, None, None]:
    """
    Dispatch the prompt to the configured LLM provider and yield tokens as they stream.
    """
    provider_name = (provider or os.getenv("LLM_PROVIDER", "ollama")).strip().lower()

    if provider_name == "ollama":
        yield from _call_ollama_stream(
            prompt,
            model=model or os.getenv("OLLAMA_MODEL", "qwen3.5:35b"),
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return

    raise LLMError(f"Streaming not supported for provider '{provider_name}'.")


def _call_ollama_stream(
    prompt: str,
    *,
    model: str,
    temperature: Optional[float],
    max_tokens: Optional[int],
) -> Generator[str, None, None]:
    """Stream tokens from Ollama API."""
    base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    endpoint = f"{base_url}/api/generate"
    timeout = _env_float("OLLAMA_TIMEOUT_SECONDS", 300)

    if max_tokens is None:
        max_tokens = _env_int("LLM_MAX_TOKENS", 8192)
    payload: Dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": True,
        "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "30m"),
        "think": _thinking_enabled(),
        "options": {
            "temperature": temperature if temperature is not None else _env_float("LLM_TEMPERATURE", 0.2),
            "num_ctx": _env_int("OLLAMA_NUM_CTX", 32768),
            "num_predict": max_tokens,
            "presence_penalty": _env_float("OLLAMA_PRESENCE_PENALTY", 1.5),
        },
    }
    # Don't force JSON format by default - let models with thinking (qwen3) work naturally.
    format_opt = os.getenv("OLLAMA_FORMAT", "").strip()
    if format_opt:
        payload["format"] = format_opt

    logger.info("→ ollama/stream model=%s prompt_chars=%d keep_alive=%s think=%s", model, len(prompt), payload["keep_alive"], payload["think"])
    t0 = time.time()
    response = requests.post(endpoint, json=payload, headers=_ollama_headers(), timeout=timeout, stream=True)
    if response.status_code != 200:
        raise LLMError(f"Ollama responded with HTTP {response.status_code}: {response.text}")

    first_token = True
    for line in response.iter_lines():
        if line:
            try:
                data = json.loads(line)
                token = data.get("response", "")
                if token:
                    if first_token:
                        logger.info("← ollama/stream first token in %.2fs", time.time() - t0)
                        first_token = False
                    yield token
                if data.get("done"):
                    _log_ollama_stats(data, time.time() - t0, label="stream")
                    break
            except json.JSONDecodeError:
                continue
