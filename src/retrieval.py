"""Local retrieval over the grounding corpus (Phase 2).

Design (see docs/dev-log 2026-09-05, step 10): a plain embedding index with metadata
filtering and a lexical fallback, behind one small class, so a graph RAG engine can
replace it later without touching the prompt code. No new dependencies.

- Corpus: every resources/corpus/*.jsonl record (schema in scripts/build_law_corpus.py).
- Embeddings: Ollama /api/embed with EMBED_MODEL (default qwen3-embedding, multilingual:
  a Hebrew query retrieves English guidance). Goes through the same local-first gate
  as the LLM calls — protocol-derived queries never leave the machine either.
- Cache: output/retrieval_cache/<model>-<corpus-hash>.json (gitignored; embeddings are
  model-specific). Rebuilt when the corpus or model changes.
- Fallback: when embeddings are unavailable, a token-overlap (BM25-lite) search over the
  same records, so grounding degrades to "keyword-matched" rather than "none".
- Failure: search() never raises; it returns [] and records `last_error` so callers can
  surface a notice and fall back to today's ungrounded behaviour.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import threading
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests

from .llm_clients import LLMError, _env_float, ollama_base_url

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = ROOT / "resources" / "corpus"
CACHE_DIR = Path(os.getenv("RETRIEVAL_CACHE_DIR", ROOT / "output" / "retrieval_cache"))
_TOKEN = re.compile(r"\w+", re.UNICODE)


def grounding_enabled() -> bool:
    """Retrieval-grounded prompts are opt-in until the Phase 2 eval gate says otherwise."""
    return os.getenv("ETIQTECH_GROUNDING", "").strip().lower() in ("1", "true", "yes")


@dataclass
class Hit:
    record: Dict[str, Any]
    score: float
    method: str  # "embedding" | "lexical"

    @property
    def id(self) -> str:
        return self.record["id"]


def _tokens(text: str) -> List[str]:
    return [t.lower() for t in _TOKEN.findall(text) if len(t) > 1]


def load_corpus(corpus_dir: Path = CORPUS_DIR) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for path in sorted(corpus_dir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
    return records


def _corpus_hash(records: Iterable[Dict[str, Any]]) -> str:
    h = hashlib.sha256()
    for r in records:  # everything that is embedded must be in the key, or a title edit serves stale vectors
        h.update(r["id"].encode()); h.update(r.get("title", "").encode("utf-8")); h.update(r["text"].encode("utf-8"))
    return h.hexdigest()[:16]


def embed_texts(texts: List[str], *, model: Optional[str] = None) -> List[List[float]]:
    """Embed via Ollama. Raises LLMError on any failure (gate, HTTP, shape)."""
    model = model or os.getenv("EMBED_MODEL", "qwen3-embedding")
    url = f"{ollama_base_url()}/api/embed"
    timeout = _env_float("EMBED_TIMEOUT_SECONDS", 600)
    resp = requests.post(url, json={"model": model, "input": texts}, timeout=timeout, allow_redirects=False)
    if resp.status_code != 200:
        raise LLMError(f"embed endpoint returned HTTP {resp.status_code}")
    vectors = resp.json().get("embeddings")
    if not isinstance(vectors, list) or len(vectors) != len(texts):
        raise LLMError("embed endpoint returned an unexpected shape")
    return vectors


class Retriever:
    """search(query, k, doc_types, species) -> List[Hit]; never raises."""

    def __init__(self, records: Optional[List[Dict[str, Any]]] = None, *, embed_model: Optional[str] = None,
                 cache_dir: Path = CACHE_DIR):
        self.records = records if records is not None else load_corpus()
        self.embed_model = embed_model or os.getenv("EMBED_MODEL", "qwen3-embedding")
        self.cache_dir = Path(cache_dir)
        self._vectors: Optional[List[List[float]]] = None
        self._norms: Optional[List[float]] = None  # corpus vector norms, computed once per index load
        self._lock = threading.Lock()
        self.last_error: Optional[str] = None
        self._failed_at: float = 0.0
        self._df = Counter()
        self._doc_tokens = [Counter(_tokens(f"{r['title']} {r['text']}")) for r in self.records]
        for c in self._doc_tokens:
            self._df.update(c.keys())
        self._avg_len = (sum(sum(c.values()) for c in self._doc_tokens) / len(self._doc_tokens)) if self.records else 1

    # -- index -------------------------------------------------------------
    def _cache_path(self) -> Path:
        safe_model = re.sub(r"[^A-Za-z0-9_.-]", "_", self.embed_model)
        return self.cache_dir / f"{safe_model}-{_corpus_hash(self.records)}.json"

    def _ensure_vectors(self) -> bool:
        if self._vectors is not None:
            return True
        if time.monotonic() - self._failed_at < _env_float("RETRIEVAL_RETRY_SECONDS", 60):
            return False  # recent failure: stay lexical for a while instead of retrying per query
        with self._lock:
            if self._vectors is not None:
                return True
            path = self._cache_path()
            if path.exists():
                try:
                    self._set_vectors(json.loads(path.read_text()))
                    return True
                except (OSError, ValueError, TypeError):
                    pass  # unreadable/partial/garbage cache: rebuild below
            try:
                vectors: List[List[float]] = []
                for i in range(0, len(self.records), 16):  # small batches keep memory and timeouts sane
                    vectors.extend(embed_texts([f"{r['title']}\n{r['text']}" for r in self.records[i:i + 16]], model=self.embed_model))
                self._set_vectors(vectors)
            except (LLMError, requests.RequestException, ValueError) as exc:
                self._failed_at = time.monotonic()
                self.last_error = f"embedding index unavailable ({type(exc).__name__})"
                logger.warning("retrieval: %s — falling back to lexical search", self.last_error)
                return False
            try:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(f".{os.getpid()}.tmp")  # atomic replace: no reader ever sees a partial file
                try:
                    tmp.write_text(json.dumps(self._vectors))
                    os.replace(tmp, path)
                finally:
                    tmp.unlink(missing_ok=True)
            except OSError:
                logger.info("retrieval: index cache not writable at %s (read-only FS?) — kept in memory", self.cache_dir)
            return True

    def _set_vectors(self, vectors: List[List[float]]) -> None:
        ok = isinstance(vectors, list) and len(vectors) == len(self.records) and all(
            isinstance(v, list) and v and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v) for v in vectors)
        if not ok or len({len(v) for v in vectors}) != 1:
            raise ValueError("cached vector shape does not match corpus")  # routes through the loader's fallback
        self._vectors = vectors
        self._norms = [math.sqrt(sum(x * x for x in v)) or 1e-9 for v in vectors]

    def build_index(self) -> bool:
        """Eagerly build (or load) the embedding index. Returns False if it fell back to lexical."""
        return self._ensure_vectors()

    # -- filtering -----------------------------------------------------------
    @staticmethod
    def _matches(record: Dict[str, Any], doc_types: Optional[List[str]], species: Optional[List[str]]) -> bool:
        if doc_types and record.get("doc_type") not in doc_types:
            return False
        if species:
            rec_species = record.get("species") or []
            if rec_species and not set(rec_species) & set(species):  # species-agnostic records always match
                return False
        return True

    # -- search --------------------------------------------------------------
    def search(self, query: str, *, k: int = 6, doc_types: Optional[List[str]] = None,
               species: Optional[List[str]] = None) -> List[Hit]:
        if not self.records or not query.strip():
            return []
        candidates = [i for i, r in enumerate(self.records) if self._matches(r, doc_types, species)]
        if not candidates:
            return []
        if self._ensure_vectors():
            try:
                qv = embed_texts([query], model=self.embed_model)[0]
                nq = math.sqrt(sum(x * x for x in qv)) or 1e-9
                # ponytail: pure-Python dot products; switch to a numpy matmul + .npy cache past ~2k records
                scored = [(sum(a * b for a, b in zip(qv, self._vectors[i])) / (nq * self._norms[i]), i) for i in candidates]
                scored.sort(reverse=True)
                return [Hit(self.records[i], round(s, 4), "embedding") for s, i in scored[:k]]
            except (LLMError, requests.RequestException, ValueError, IndexError) as exc:
                self.last_error = f"query embedding failed ({type(exc).__name__})"
                logger.warning("retrieval: %s — lexical fallback for this query", self.last_error)
        return self._lexical(query, candidates, k)

    def _lexical(self, query: str, candidates: List[int], k: int) -> List[Hit]:
        # ponytail: BM25 (k1=1.5, b=0.75) over title+text; enough for a few thousand records
        q = _tokens(query)
        n = len(self.records)
        scored = []
        for i in candidates:
            doc = self._doc_tokens[i]
            dl = sum(doc.values())
            s = 0.0
            for t in q:
                if t in doc:
                    idf = math.log(1 + (n - self._df[t] + 0.5) / (self._df[t] + 0.5))
                    tf = doc[t]
                    s += idf * (tf * 2.5) / (tf + 1.5 * (0.25 + 0.75 * dl / self._avg_len))
            if s > 0:
                scored.append((s, i))
        scored.sort(reverse=True)
        return [Hit(self.records[i], round(s, 4), "lexical") for s, i in scored[:k]]


_default: Optional[Retriever] = None
_default_lock = threading.Lock()


def get_retriever() -> Retriever:
    global _default
    with _default_lock:
        if _default is None:
            _default = Retriever()
        return _default


def format_grounding_block(hits: List[Hit], *, max_chars_per_hit: int = 700) -> str:
    """Numbered [Gn] references the model can cite; each carries its source URL."""
    if not hits:
        return ""
    lines = ["Grounding references (cite as [G1], [G2], ... where they support a finding):"]
    for n, h in enumerate(hits, 1):
        text = h.record["text"]
        if len(text) > max_chars_per_hit:
            text = text[:max_chars_per_hit].rsplit(" ", 1)[0] + " …"
        lines.append(f"[G{n}] {h.record['title']}\nSource: {h.record['url']}\n{text}\n")
    return "\n".join(lines)


def grounding_refs(hits: List[Hit]) -> List[Dict[str, Any]]:
    """Metadata attached to a theme result so the UI/print can show sources (escaped there)."""
    return [
        {"ref": f"G{n}", "id": h.id, "title": h.record["title"], "url": h.record["url"],
         "doc_type": h.record.get("doc_type"), "license": h.record.get("license"), "method": h.method}
        for n, h in enumerate(hits, 1)
    ]
