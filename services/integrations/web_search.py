"""Web search integration using DuckDuckGo (no API key required)."""
from __future__ import annotations

import logging
from typing import Any, Dict, List

LOG = logging.getLogger(__name__)


def search_web(query: str, max_results: int = 5) -> str:
    """Search the web via DuckDuckGo and return a summarised string."""
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results: List[Dict[str, Any]] = list(ddgs.text(query, max_results=max_results))
        if not results:
            return ""
        parts = []
        for i, r in enumerate(results[:max_results], 1):
            title = r.get("title", "")
            body = r.get("body", "")
            if title and body:
                parts.append(f"{i}. {title}: {body}")
            elif body:
                parts.append(f"{i}. {body}")
        return " ".join(parts)
    except ImportError:
        LOG.warning("duckduckgo-search not installed; pip install duckduckgo-search")
        return ""
    except Exception as e:
        LOG.warning("Web search failed: %s", e)
        return ""


def search_web_structured(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """Return structured search results."""
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        return [
            {"title": r.get("title", ""), "body": r.get("body", ""), "url": r.get("href", "")}
            for r in results
        ]
    except Exception as e:
        LOG.warning("Web search failed: %s", e)
        return []
