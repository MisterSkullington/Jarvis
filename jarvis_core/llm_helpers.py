"""
Shared LLM / Ollama helpers used across NLU, agent, and orchestrator services.
"""
from __future__ import annotations

import atexit
import logging
from typing import Any, Dict, List, Optional

import httpx

LOG = logging.getLogger(__name__)

_DEFAULT_SYSTEM_PROMPT = (
    "You are Jarvis, a highly intelligent personal assistant. "
    "Speak with dry British wit, address the user as 'Sir', and be concise."
)

# Module-level persistent HTTP client (connection-pooled).
# Created lazily on first use, closed at interpreter shutdown.
_http_client: Optional[httpx.Client] = None


def _get_http_client(timeout: float = 60) -> httpx.Client:
    """Return (or create) the module-level persistent httpx.Client."""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.Client(timeout=timeout)
        atexit.register(_close_http_client)
    return _http_client


def _close_http_client() -> None:
    global _http_client
    if _http_client is not None and not _http_client.is_closed:
        _http_client.close()
    _http_client = None


def get_honorific(config, default: str = "Sir") -> str:
    """Return the configured honorific (e.g. 'Sir'), falling back to *default*."""
    return getattr(getattr(config, "personality", None), "honorific", None) or default


def get_system_message(config) -> Dict[str, str]:
    """Return the Jarvis system message dict for Ollama calls."""
    prompt = (
        getattr(getattr(config, "personality", None), "system_prompt", None)
        or _DEFAULT_SYSTEM_PROMPT
    )
    return {"role": "system", "content": prompt}


def ollama_chat(
    messages: List[Dict[str, Any]],
    config,
    *,
    tools: Optional[List[Dict[str, Any]]] = None,
    timeout: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """
    POST to Ollama /api/chat and return the raw *message* dict, or None on failure.

    When *tools* is non-empty the payload includes the ``tools`` key, enabling
    native tool-calling on supported models (llama3.1, mistral-nemo, etc.).
    When *tools* is empty or None a plain chat call is made.

    Returns the full message dict so callers can inspect both ``content`` and
    ``tool_calls``.  For backwards-compat, callers that only want the text
    content should do ``(result or {}).get("content")``.

    Uses a module-level persistent httpx.Client for connection pooling.
    """
    if not getattr(config, "llm", None) or not getattr(config.llm, "enabled", True):
        return None

    url = f"{config.llm.base_url.rstrip('/')}/api/chat"
    t = timeout if timeout is not None else getattr(config.llm, "timeout_seconds", 60)

    payload: Dict[str, Any] = {
        "model": config.llm.model,
        "messages": messages,
        "stream": False,
    }
    if tools:
        payload["tools"] = tools

    try:
        client = _get_http_client(timeout=t)
        r = client.post(url, json=payload, timeout=t)
        r.raise_for_status()
        return r.json().get("message") or {}
    except Exception as exc:
        LOG.warning("Ollama chat failed: %s", exc)
        return None
