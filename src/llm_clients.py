import ipaddress
import json
import logging
import os
import re
import time
from typing import Any, Dict, Generator, Optional
from urllib.parse import urlsplit

import requests

logger = logging.getLogger(__name__)  # library module: never configures the root logger (see server/app.py)


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


# ---------------------------------------------------------------------------
# Local-first gate (invariant: protocol data never leaves the machine by default)
# ---------------------------------------------------------------------------
_LOCAL_HOSTS = {"localhost", "host.docker.internal", "host.containers.internal", "gateway.docker.internal"}
# .local/.localhost/.home.arpa are IANA special-use; .svc/.cluster.local are Kubernetes; .internal and
# .lan are private-use *conventions* (not IANA-reserved) — revisit if a gTLD round ever delegates them.
_LOCAL_SUFFIXES = (".svc", ".svc.cluster.local", ".cluster.local", ".internal", ".local", ".localhost", ".lan", ".home.arpa")
REMOTE_LLM_FLAG = "ETIQTECH_ALLOW_REMOTE_LLM"


def is_remote_llm_url(url: str) -> bool:
    """True when the host is not loopback / private network / cluster-internal.

    Local (no opt-in needed): localhost, 127.0.0.1, ::1, docker/podman host aliases,
    RFC1918 / link-local / ULA IPs, single-label hostnames (k8s service names such as
    `ollama`), and *.svc / *.cluster.local / *.internal / *.local names.
    Everything else — public DNS names (ollama.com, api.openai.com) or public IPs — is remote.
    """
    host = (urlsplit(url).hostname or "").strip("[]").lower()
    if not host:
        return True  # unparsable -> treat as remote, fail closed
    if host in _LOCAL_HOSTS or host.endswith(_LOCAL_SUFFIXES):
        return False
    try:
        ip = ipaddress.ip_address(host)
        return not (ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_unspecified)
    except ValueError:
        pass
    return "." in host  # single-label hostname = cluster/LAN service name


def remote_llm_allowed() -> bool:
    return os.getenv(REMOTE_LLM_FLAG, "").strip().lower() in ("1", "true", "yes")


# Provider registry: env var holding the base URL, its default, and a capability matrix
# (rendered in docs/providers.md). Every provider's base URL goes through the same gate.
PROVIDERS: Dict[str, Dict[str, Any]] = {
    "ollama": {
        "base_url_env": "OLLAMA_BASE_URL", "base_url_default": "http://127.0.0.1:11434",
        "model_env": "OLLAMA_MODEL", "model_default": "qwen3.5:35b", "key_env": "OLLAMA_API_KEY",
        "streaming": True, "json_mode": True, "thinking": True, "two_step": True, "local_capable": True,
    },
    "openai": {  # any OpenAI-compatible /v1/chat/completions server: OpenAI, vLLM, LM Studio, llama.cpp, OpenRouter, Azure (via base URL)
        "base_url_env": "OPENAI_BASE_URL", "base_url_default": "https://api.openai.com/v1",
        "model_env": "OPENAI_MODEL", "model_default": None, "key_env": "OPENAI_API_KEY",
        "streaming": True, "json_mode": True, "thinking": False, "two_step": False, "local_capable": True,
    },
    "anthropic": {  # official SDK; always a remote service
        "base_url_env": "ANTHROPIC_BASE_URL", "base_url_default": "https://api.anthropic.com",
        "model_env": "ANTHROPIC_MODEL", "model_default": "claude-opus-5", "key_env": "ANTHROPIC_API_KEY",
        "streaming": True, "json_mode": False, "thinking": True, "two_step": False, "local_capable": False,
    },
}


def provider_name(provider: Optional[str] = None) -> str:
    name = (provider or os.getenv("LLM_PROVIDER", "ollama")).strip().lower()
    if name in ("openai-compatible", "openai_compatible", "vllm", "lmstudio", "openrouter"):
        name = "openai"
    if name not in PROVIDERS:
        raise LLMError(f"Unsupported LLM provider '{name}'. Known: {', '.join(PROVIDERS)}.")
    return name


def gated_base_url(provider: str) -> str:
    """Resolve the provider's base URL and enforce the local-first gate before any request is built.

    Raises LLMError (nothing is sent) when the endpoint is remote and the operator has
    not set ETIQTECH_ALLOW_REMOTE_LLM=1. The flag is the explicit, informed opt-in.
    """
    spec = PROVIDERS[provider]
    url = os.getenv(spec["base_url_env"], spec["base_url_default"]).rstrip("/")
    if is_remote_llm_url(url) and not remote_llm_allowed():
        # The URL goes to the server log only; LLMError text can reach the browser.
        logger.error("Refusing LLM call: %s host %r is not local and %s is not set",
                     spec["base_url_env"], urlsplit(url).hostname, REMOTE_LLM_FLAG)
        raise LLMError(
            f"LLM endpoint is not local/cluster-internal and {REMOTE_LLM_FLAG} is not set; "
            "refusing to send protocol text off this machine."
        )
    return url


def ollama_base_url() -> str:
    return gated_base_url("ollama")


def local_first_status(provider: Optional[str] = None) -> Dict[str, Any]:
    """For startup logging and /api/health: where would protocol text go?"""
    try:
        name = provider_name(provider)
    except LLMError:
        name = "ollama"
    spec = PROVIDERS[name]
    url = os.getenv(spec["base_url_env"], spec["base_url_default"]).rstrip("/")
    remote = is_remote_llm_url(url)
    return {"provider": name, "ollama_host": urlsplit(url).hostname, "host": urlsplit(url).hostname,
            "remote": remote, "remote_allowed": remote_llm_allowed()}


def provider_configured(name: str) -> bool:
    """A provider is offered in the UI when its credentials/base URL are configured."""
    spec = PROVIDERS[name]
    if name == "ollama":
        return True
    if name == "anthropic":
        return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))
    return bool(os.getenv(spec["key_env"]) or os.getenv(spec["base_url_env"]))


def provider_default_model(name: str) -> Optional[str]:
    spec = PROVIDERS[name]
    return os.getenv(spec["model_env"]) or spec["model_default"]


def estimate_tokens(text: str) -> int:
    # ponytail: chars/4, calibrated 2026-09-05 against qwen3.6 prompt_eval_count on a real
    # Layer 3 prompt (113,069 chars -> 27,658 tokens = 4.09 chars/token) and a Layer 2 theme
    # prompt (4.23). Slightly conservative on purpose; swap in a tokenizer if the guard misfires.
    return len(text) // 4


def context_budget_warning(prompt: str, *, label: str, num_ctx: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Return an SSE-shaped warning event when a prompt is close to overflowing num_ctx.

    Ollama silently truncates prompts that exceed num_ctx - num_predict, which
    degrades the review without any error. Callers yield the returned dict to the
    client (and log it); None means the prompt fits comfortably.
    """
    num_ctx = num_ctx if num_ctx is not None else _env_int("OLLAMA_NUM_CTX", 32768)
    num_predict = _env_int("LLM_MAX_TOKENS", 8192)
    available = max(num_ctx - num_predict, 1)
    est = estimate_tokens(prompt)
    if est < 0.85 * available:
        return None
    overflow = est > available
    truncates_prompt = est >= num_ctx
    # Measured 2026-09-05 (Ollama 0.32, qwen3.6): the prompt is truncated only when it
    # exceeds num_ctx itself; below that it is sent whole, but prompt + num_predict
    # no longer fit, so generation is cut short or early context is shifted out.
    if truncates_prompt:
        consequence = "Ollama WILL truncate the prompt — review quality is degraded. "
    elif overflow:
        consequence = "Prompt + max output exceed the window — the answer may be cut short or lose early context. "
    else:
        consequence = "Approaching the limit. "
    msg = (
        f"{label}: prompt is ~{est} tokens vs ~{available} available "
        f"(num_ctx={num_ctx}, num_predict={num_predict}). "
        + consequence
        + "Raise OLLAMA_NUM_CTX or shorten the protocol."
    )
    logger.warning("context budget: %s", msg)
    return {
        "type": "warning",
        "code": "context_budget",
        "label": label,
        "estimated_prompt_tokens": est,
        "available_tokens": available,
        "num_ctx": num_ctx,
        "overflow": overflow,
        "truncates_prompt": truncates_prompt,
        "message": msg,
    }


def call_llm(
    prompt: str,
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    num_ctx: Optional[int] = None,
) -> str:
    """
    Dispatch the prompt to the configured LLM provider and return the raw text response.
    """
    name = provider_name(provider)
    resolved_model = model or provider_default_model(name)
    if not resolved_model:
        raise LLMError(f"No model configured for provider '{name}' (set {PROVIDERS[name]['model_env']}).")
    if name == "ollama":
        return _call_ollama(prompt, model=resolved_model, temperature=temperature, max_tokens=max_tokens, num_ctx=num_ctx)
    if name == "openai":
        return _call_openai_compat(prompt, model=resolved_model, temperature=temperature, max_tokens=max_tokens)
    return _call_anthropic(prompt, model=resolved_model, max_tokens=max_tokens)


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
    num_ctx: Optional[int] = None,
) -> str:
    base_url = ollama_base_url()
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
            "num_ctx": num_ctx if num_ctx is not None else _env_int("OLLAMA_NUM_CTX", 32768),
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
    response = requests.post(endpoint, json=payload, headers=_ollama_headers(), timeout=timeout, allow_redirects=False)
    elapsed = time.time() - t0
    if response.status_code != 200:
        raise LLMError(f"Ollama responded with HTTP {response.status_code}")  # status only, never the body (PRIVACY.md guarantee 3)

    try:
        body = response.json()
    except json.JSONDecodeError as exc:
        raise LLMError(f"Failed to parse Ollama response JSON: {exc}") from exc

    _log_ollama_stats(body, elapsed)

    text = body.get("response")
    if not isinstance(text, str) or not text.strip():
        raise LLMError("Ollama response missing or empty 'response' text payload")

    return text.strip()


def call_llm_two_step(
    prompt: str,
    *,
    provider: Optional[str] = None,
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
    if provider_name(provider) != "ollama":
        # Two-step is Ollama-specific; fall back gracefully — with the caller's provider, not the env default.
        return call_llm(prompt, provider=provider, model=model, temperature=temperature, max_tokens=max_tokens)

    resolved_model = model or os.getenv("OLLAMA_MODEL", "qwen3.5:35b")
    base_url = ollama_base_url()
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
    resp1 = requests.post(endpoint, json=step1_payload, headers=_ollama_headers(), timeout=timeout, allow_redirects=False)
    elapsed1 = time.time() - t0
    if resp1.status_code != 200:
        raise LLMError(f"Ollama (step 1) responded with HTTP {resp1.status_code}")  # status only, never the body (PRIVACY.md guarantee 3)

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
    resp2 = requests.post(endpoint, json=step2_payload, headers=_ollama_headers(), timeout=timeout, allow_redirects=False)
    elapsed2 = time.time() - t2
    if resp2.status_code != 200:
        raise LLMError(f"Ollama (step 2) responded with HTTP {resp2.status_code}")  # status only, never the body (PRIVACY.md guarantee 3)

    try:
        body2 = resp2.json()
    except json.JSONDecodeError as exc:
        raise LLMError(f"Failed to parse Ollama step-2 response: {exc}") from exc

    _log_ollama_stats(body2, elapsed2, label="two-step[2]")

    text = (body2.get("message") or {}).get("content")
    if not isinstance(text, str) or not text.strip():
        raise LLMError("Ollama two-step step-2 returned empty content")

    return text.strip()


def call_llm_stream(
    prompt: str,
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    num_ctx: Optional[int] = None,
) -> Generator[str, None, None]:
    """
    Dispatch the prompt to the configured LLM provider and yield tokens as they stream.
    """
    name = provider_name(provider)
    resolved_model = model or provider_default_model(name)
    if not resolved_model:
        raise LLMError(f"No model configured for provider '{name}' (set {PROVIDERS[name]['model_env']}).")
    if name == "ollama":
        yield from _call_ollama_stream(prompt, model=resolved_model, temperature=temperature, max_tokens=max_tokens, num_ctx=num_ctx)
    elif name == "openai":
        yield from _call_openai_compat_stream(prompt, model=resolved_model, temperature=temperature, max_tokens=max_tokens)
    else:
        yield from _call_anthropic_stream(prompt, model=resolved_model, max_tokens=max_tokens)


def _call_ollama_stream(
    prompt: str,
    *,
    model: str,
    temperature: Optional[float],
    max_tokens: Optional[int],
    num_ctx: Optional[int] = None,
) -> Generator[str, None, None]:
    """Stream tokens from Ollama API."""
    base_url = ollama_base_url()
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
            "num_ctx": num_ctx if num_ctx is not None else _env_int("OLLAMA_NUM_CTX", 32768),
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
    response = requests.post(endpoint, json=payload, headers=_ollama_headers(), timeout=timeout, allow_redirects=False, stream=True)
    if response.status_code != 200:
        raise LLMError(f"Ollama responded with HTTP {response.status_code}")  # status only, never the body (PRIVACY.md guarantee 3)

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


# ---------------------------------------------------------------------------
# OpenAI-compatible adapter (/v1/chat/completions). Covers OpenAI, Azure (via base URL),
# OpenRouter, and local servers such as vLLM, LM Studio and llama.cpp — the local ones
# pass the gate without the opt-in flag.
# ---------------------------------------------------------------------------
_KNOWN_STREAM_ERRORS = frozenset({
    "rate_limit_exceeded", "rate_limit_error", "insufficient_quota", "context_length_exceeded",
    "invalid_request_error", "server_error", "overloaded_error", "timeout", "model_not_found",
})


def _openai_headers() -> Dict[str, str]:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    return {"Authorization": f"Bearer {key}"} if key else {}


def _openai_payload(prompt: str, model: str, temperature: Optional[float], max_tokens: Optional[int], stream: bool) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature if temperature is not None else _env_float("LLM_TEMPERATURE", 0.2),
        "max_tokens": max_tokens if max_tokens is not None else _env_int("LLM_MAX_TOKENS", 8192),
        "stream": stream,
    }
    if os.getenv("OPENAI_JSON_MODE", "").strip().lower() in ("1", "true", "yes"):
        payload["response_format"] = {"type": "json_object"}
    return payload


def _call_openai_compat(prompt: str, *, model: str, temperature: Optional[float], max_tokens: Optional[int]) -> str:
    endpoint = f"{gated_base_url('openai')}/chat/completions"
    timeout = _env_float("OLLAMA_TIMEOUT_SECONDS", 300)
    logger.info("→ openai-compat model=%s prompt_chars=%d", model, len(prompt))
    t0 = time.time()
    resp = requests.post(endpoint, json=_openai_payload(prompt, model, temperature, max_tokens, False),
                         headers=_openai_headers(), timeout=timeout, allow_redirects=False)
    if resp.status_code != 200:
        logger.warning("openai-compat HTTP %s (%d-byte body not logged)", resp.status_code, len(resp.text or ""))
        raise LLMError(f"OpenAI-compatible endpoint responded with HTTP {resp.status_code}")
    try:
        body = resp.json()
        text = body["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"OpenAI-compatible response had an unexpected shape: {type(exc).__name__}") from exc
    usage = body.get("usage") or {}
    logger.info("← openai-compat wall=%.2fs | %s tokens", time.time() - t0, usage.get("completion_tokens", "?"))
    if not isinstance(text, str) or not text.strip():
        raise LLMError("OpenAI-compatible response contained no text")
    return text.strip()


def _call_openai_compat_stream(prompt: str, *, model: str, temperature: Optional[float], max_tokens: Optional[int]) -> Generator[str, None, None]:
    endpoint = f"{gated_base_url('openai')}/chat/completions"
    timeout = _env_float("OLLAMA_TIMEOUT_SECONDS", 300)
    logger.info("→ openai-compat/stream model=%s prompt_chars=%d", model, len(prompt))
    resp = requests.post(endpoint, json=_openai_payload(prompt, model, temperature, max_tokens, True),
                         headers=_openai_headers(), timeout=timeout, stream=True, allow_redirects=False)
    if resp.status_code != 200:
        logger.warning("openai-compat/stream HTTP %s (body not logged)", resp.status_code)
        raise LLMError(f"OpenAI-compatible endpoint responded with HTTP {resp.status_code}")
    for line in resp.iter_lines():
        if not line:
            continue
        line = line.decode("utf-8", errors="replace") if isinstance(line, bytes) else line
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except ValueError:
            continue
        if isinstance(chunk, dict) and chunk.get("error"):
            # gateways report rate limits / overflow mid-stream without closing; never pass that off as "done"
            err = chunk["error"] if isinstance(chunk["error"], dict) else {}
            raw = str(err.get("type") or err.get("code") or "")
            kind = raw if raw in _KNOWN_STREAM_ERRORS else "error"  # provider-controlled field: whitelist, never echo
            logger.warning("openai-compat/stream error event: %s", kind)
            raise LLMError(f"OpenAI-compatible stream reported an error ({kind})")
        try:
            token = ((chunk.get("choices") or [{}])[0].get("delta") or {}).get("content")
        except (AttributeError, IndexError, TypeError):
            continue
        if token:
            yield token


# ---------------------------------------------------------------------------
# Anthropic adapter — official SDK (optional dependency: pip install etiqtech[anthropic]).
# Always remote, so it only runs with ETIQTECH_ALLOW_REMOTE_LLM=1. Sampling parameters are
# not sent (rejected by current Claude models); adaptive thinking is the model default.
# ---------------------------------------------------------------------------
def _anthropic_client():
    base_url = gated_base_url("anthropic")  # the remote gate decides first, whether or not the SDK is installed
    try:
        import anthropic  # noqa: WPS433 — optional dependency
    except ImportError as exc:
        raise LLMError("LLM_PROVIDER=anthropic needs the 'anthropic' package: pip install 'etiqtech[anthropic]'") from exc
    # The SDK's default HTTP client follows redirects; every other adapter refuses them, so must this one.
    return anthropic.Anthropic(
        base_url=base_url,
        timeout=_env_float("OLLAMA_TIMEOUT_SECONDS", 300),
        http_client=anthropic.DefaultHttpxClient(follow_redirects=False),
    )


def _anthropic_kwargs(prompt: str, model: str, max_tokens: Optional[int]) -> Dict[str, Any]:
    return {
        "model": model,
        "max_tokens": max_tokens if max_tokens is not None else _env_int("LLM_MAX_TOKENS", 8192),
        "messages": [{"role": "user", "content": prompt}],
    }


def _call_anthropic(prompt: str, *, model: str, max_tokens: Optional[int]) -> str:
    client = _anthropic_client()
    logger.info("→ anthropic model=%s prompt_chars=%d", model, len(prompt))
    t0 = time.time()
    try:
        message = client.messages.create(**_anthropic_kwargs(prompt, model, max_tokens))
    except Exception as exc:  # SDK error classes are only importable when the SDK is
        logger.warning("anthropic call failed: %s (message not logged: SDK errors can carry response bodies)", type(exc).__name__)
        raise LLMError(f"Anthropic API call failed: {type(exc).__name__}") from exc
    if getattr(message, "stop_reason", None) == "refusal":
        raise LLMError("Anthropic model refused the request (stop_reason=refusal)")
    text = "".join(getattr(b, "text", "") for b in message.content if getattr(b, "type", "") == "text")
    logger.info("← anthropic wall=%.2fs | stop=%s", time.time() - t0, getattr(message, "stop_reason", None))
    if not text.strip():
        raise LLMError("Anthropic response contained no text")
    return text.strip()


def _call_anthropic_stream(prompt: str, *, model: str, max_tokens: Optional[int]) -> Generator[str, None, None]:
    client = _anthropic_client()
    logger.info("→ anthropic/stream model=%s prompt_chars=%d", model, len(prompt))
    try:
        with client.messages.stream(**_anthropic_kwargs(prompt, model, max_tokens)) as stream:
            for text in stream.text_stream:
                if text:
                    yield text
            final = stream.get_final_message()
    except LLMError:
        raise
    except Exception as exc:
        logger.warning("anthropic stream failed: %s", type(exc).__name__)
        raise LLMError(f"Anthropic API stream failed: {type(exc).__name__}") from exc
    if getattr(final, "stop_reason", None) == "refusal":
        raise LLMError("Anthropic model refused the request (stop_reason=refusal)")
