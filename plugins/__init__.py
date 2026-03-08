"""
Jarvis Plugin System (Phase 6).

To create a plugin, add a Python file to the plugins/ directory.
The file must expose a module-level list named TOOLS, where each
item is a dict with the following keys:

  name              (str)      – unique tool identifier
  description       (str)      – shown to the LLM for tool selection
  parameters        (dict)     – JSON Schema object for tool arguments
  handler           (callable) – fn(config, **kwargs) -> str
  rate_limit_seconds(float)    – optional, default 0

Example plugin file (plugins/my_tool.py):

    def _my_handler(config, query: str = "") -> str:
        return f"Result for: {query}"

    TOOLS = [
        {
            "name": "my_tool",
            "description": "Does something useful.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Input query"},
                },
                "required": ["query"],
            },
            "handler": _my_handler,
            "rate_limit_seconds": 0,
        }
    ]

Plugins are discovered automatically at agent startup when
plugins.enabled: true is set in config.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Protocol, runtime_checkable


@runtime_checkable
class ToolContract(Protocol):
    """Protocol that all plugin tool dicts must satisfy."""
    name: str
    description: str
    parameters: Dict[str, Any]
    handler: Callable
