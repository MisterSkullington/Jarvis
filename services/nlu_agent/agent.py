"""
Ollama tool-calling agent for the Jarvis NLU service (Phase 2).

Loop:
  1. Build messages: system prompt → RAG context → history → user message
  2. Call Ollama /api/chat with tool definitions
  3. If response has tool_calls → execute each, append tool results, loop
  4. If response has content → return as final answer
  5. Guard: max_iterations prevents infinite loops

Compatible with any Ollama model that supports tool calling
(llama3.1, llama3.2, phi3.5, mistral-nemo, qwen2.5, etc.).
Falls back gracefully when the model returns plain text instead of tool calls.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from jarvis_core import get_honorific, get_system_message, ollama_chat

LOG = logging.getLogger(__name__)

# Guard: load_plugins() is called once per process, not on every agent invocation
_plugins_loaded = False


def run_agent(
    text: str,
    session_id: Optional[str],
    config,
    memory=None,
) -> Tuple[str, List[str]]:
    """
    Run the tool-calling agent loop.

    Args:
        text:       The user's input.
        session_id: For memory/RAG lookup. May be None.
        config:     JarvisConfig instance.
        memory:     Optional JarvisMemory instance for RAG context.

    Returns:
        (response_text, tools_used_list)
    """
    global _plugins_loaded
    from services.nlu_agent.tools import get_ollama_tools, execute, load_plugins

    # Load plugin tools once per process lifetime
    if not _plugins_loaded:
        load_plugins(config)
        _plugins_loaded = True

    honorific = get_honorific(config)
    enabled_tools: List[str] = getattr(getattr(config, "agent", None), "tools", [])
    max_iter: int = getattr(getattr(config, "agent", None), "max_iterations", 5)
    ollama_tools = get_ollama_tools(enabled_tools)

    # Build initial message list
    messages: List[Dict[str, Any]] = [get_system_message(config)]

    if memory and session_id:
        try:
            context = memory.build_context(text, session_id)
            if context:
                messages.append({"role": "system", "content": f"Relevant context:\n{context}"})
            for turn in memory.get_recent_turns(session_id, limit=10):
                messages.append({"role": turn["role"], "content": turn["content"]})
        except Exception as exc:
            LOG.warning("Agent memory retrieval failed: %s", exc)

    messages.append({"role": "user", "content": text})

    tools_used: List[str] = []

    for iteration in range(max_iter):
        LOG.debug("Agent iteration %d/%d", iteration + 1, max_iter)
        msg = ollama_chat(messages, config, tools=ollama_tools)

        if msg is None:
            # Ollama unavailable — return personality fallback
            return (f"I'm afraid my reasoning engine is offline at the moment, {honorific}.", tools_used)

        tool_calls: List[Dict[str, Any]] = msg.get("tool_calls") or []
        content: str = (msg.get("content") or "").strip()

        if not tool_calls:
            # Model returned a final answer
            if content:
                return (content, tools_used)
            # Empty response — shouldn't happen, but guard it
            return (f"I'm not sure how to help with that, {honorific}.", tools_used)

        # Append the assistant's (possibly empty) message with tool_calls
        messages.append({
            "role": "assistant",
            "content": content,
            "tool_calls": tool_calls,
        })

        # Execute each tool and append results
        for tc in tool_calls:
            fn = tc.get("function") or {}
            tool_name: str = fn.get("name", "")
            raw_args = fn.get("arguments", {})

            # Ollama may return arguments as a JSON string or a dict
            if isinstance(raw_args, str):
                try:
                    raw_args = json.loads(raw_args)
                except Exception:
                    raw_args = {}

            LOG.info("Agent calling tool: %s(%s)", tool_name, raw_args)
            result = execute(tool_name, raw_args, config)
            tools_used.append(tool_name)

            messages.append({
                "role": "tool",
                "content": result,
            })

    # Max iterations reached — ask for a final synthesis
    messages.append({
        "role": "user",
        "content": "Please provide a final answer based on the tool results above.",
    })
    final = ollama_chat(messages, config)
    if final and final.get("content"):
        return (final["content"].strip(), tools_used)

    return (f"I gathered some information but couldn't synthesise a response, {honorific}.", tools_used)
