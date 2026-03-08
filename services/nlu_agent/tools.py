"""
Tool registry for the Jarvis NLU agent (Phase 2).

Each tool entry has:
  name        – identifier used by the LLM
  description – shown to the LLM so it can decide when to call the tool
  parameters  – JSON Schema object describing the arguments
  handler     – callable(config, **kwargs) -> str  (returns text result)

Tools can also be contributed by plugins (see plugins/__init__.py).
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, List, Optional

LOG = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_REGISTRY: Dict[str, Dict[str, Any]] = {}

# Per-tool rate-limit tracker  {tool_name: last_called_timestamp}
_last_called: Dict[str, float] = {}


def register(
    name: str,
    description: str,
    parameters: Dict[str, Any],
    handler: Callable,
    rate_limit_seconds: float = 0.0,
) -> None:
    """Add or replace a tool in the registry."""
    _REGISTRY[name] = {
        "name": name,
        "description": description,
        "parameters": parameters,
        "handler": handler,
        "rate_limit_seconds": rate_limit_seconds,
    }


def get_ollama_tools(enabled: List[str]) -> List[Dict[str, Any]]:
    """Return Ollama-formatted tool definitions for the given enabled list."""
    result = []
    for name in enabled:
        if name not in _REGISTRY:
            continue
        t = _REGISTRY[name]
        result.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            },
        })
    return result


def execute(name: str, args: Dict[str, Any], config) -> str:
    """Execute a registered tool, respecting its rate limit. Returns result string."""
    if name not in _REGISTRY:
        return f"[Tool '{name}' not found]"
    tool = _REGISTRY[name]
    rl = tool.get("rate_limit_seconds", 0.0)
    if rl > 0:
        last = _last_called.get(name, 0.0)
        if time.time() - last < rl:
            remaining = int(rl - (time.time() - last))
            return f"[Rate limited — please wait {remaining}s before calling {name} again]"
    try:
        result = tool["handler"](config, **args)
        _last_called[name] = time.time()
        return str(result)
    except Exception as exc:
        LOG.warning("Tool '%s' raised an exception: %s", name, exc)
        return f"[Tool error: {exc}]"


# ---------------------------------------------------------------------------
# Built-in tool handlers
# ---------------------------------------------------------------------------

def _calendar_handler(config, limit: int = 5) -> str:
    from services.integrations.calendar import get_next_events
    events = get_next_events(limit=int(limit))
    if not events:
        return "No upcoming calendar events found."
    lines = [f"- {e.get('summary','Untitled')} at {e.get('start','unknown')}" for e in events]
    return f"{len(events)} upcoming event(s):\n" + "\n".join(lines)


def _weather_handler(config, location: str = "here") -> str:
    from services.integrations.web_apis import get_weather
    info = get_weather(location)
    return info.get("summary", "Weather data unavailable.")


def _news_handler(config, limit: int = 5) -> str:
    from services.integrations.web_apis import get_news
    data = get_news(limit=int(limit))
    headlines = data.get("headlines", [])
    if not headlines:
        return data.get("error", "No headlines available.")
    return "Top headlines:\n" + "\n".join(f"- {h}" for h in headlines)


def _light_handler(config, room: str = "living room", on: bool = True) -> str:
    from services.integrations.home_assistant import set_light_state
    result = set_light_state(room, bool(on))
    if result.get("ok"):
        state = "on" if on else "off"
        return f"Turned {state} the {room} lights."
    return f"Light control failed: {result.get('error', 'unknown error')}"


def _system_command_handler(config, command_id: str = "") -> str:
    allowed = getattr(config.safety, "allowed_system_commands", {})
    if command_id not in allowed:
        return f"Command '{command_id}' is not in the allowed list."
    from services.integrations.system_control import run_system_command
    result = run_system_command(command_id)
    if result.get("ok"):
        return f"Executed system command: {command_id}"
    return f"System command failed: {result.get('error')}"


def _describe_screen_handler(config) -> str:
    """Capture the screen and return a description via the vision service."""
    vision_url = getattr(getattr(config, "vision", None), "base_url", None)
    if not vision_url or not getattr(config.vision, "enabled", False):
        return "Vision service is not enabled. Set vision.enabled: true in config."
    import httpx
    try:
        with httpx.Client(timeout=30) as client:
            r = client.post(f"{vision_url.rstrip('/')}/capture_describe")
            if r.is_success:
                data = r.json()
                desc = data.get("description", "")
                ocr = data.get("ocr_text", "")
                parts = []
                if desc:
                    parts.append(f"Description: {desc}")
                if ocr:
                    parts.append(f"Text on screen: {ocr}")
                return "\n".join(parts) or "Nothing notable on screen."
    except Exception as exc:
        return f"Vision service error: {exc}"
    return "Vision service unavailable."


def _open_app_handler(config, app_name: str = "") -> str:
    """Open an application by name (desktop automation)."""
    if not getattr(getattr(config, "desktop", None), "enabled", False):
        return "Desktop automation is not enabled."
    from services.integrations.desktop_control import open_application
    result = open_application(app_name, config)
    return result.get("message", str(result))


def _search_web_handler(config, query: str = "") -> str:
    """Search the web using a local SearxNG instance (optional)."""
    search_url = getattr(getattr(config, "llm", None), "searxng_url", None) or ""
    if not search_url:
        return "Web search is not configured. Set llm.searxng_url in config."
    import httpx
    try:
        with httpx.Client(timeout=10) as client:
            r = client.get(search_url, params={"q": query, "format": "json"})
            if r.is_success:
                results = r.json().get("results", [])[:3]
                if not results:
                    return "No results found."
                snippets = [f"- {r.get('title','')}: {r.get('content','')[:200]}" for r in results]
                return "\n".join(snippets)
    except Exception as exc:
        return f"Search failed: {exc}"
    return "Search unavailable."


# ---------------------------------------------------------------------------
# Register all built-in tools at import time
# ---------------------------------------------------------------------------

register(
    "calendar",
    "Get the user's upcoming calendar events.",
    {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "Max number of events to return", "default": 5},
        },
    },
    _calendar_handler,
)

register(
    "weather",
    "Get the current weather for a location.",
    {
        "type": "object",
        "properties": {
            "location": {"type": "string", "description": "City or location name"},
        },
        "required": ["location"],
    },
    _weather_handler,
)

register(
    "news",
    "Get the latest news headlines.",
    {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "Number of headlines", "default": 5},
        },
    },
    _news_handler,
)

register(
    "light_control",
    "Turn smart home lights on or off in a given room.",
    {
        "type": "object",
        "properties": {
            "room": {"type": "string", "description": "Room name, e.g. 'living room', 'bedroom'"},
            "on": {"type": "boolean", "description": "True to turn on, false to turn off"},
        },
        "required": ["room", "on"],
    },
    _light_handler,
    rate_limit_seconds=30.0,
)

register(
    "system_command",
    "Execute an allowed system command such as locking the workstation.",
    {
        "type": "object",
        "properties": {
            "command_id": {"type": "string", "description": "Command ID from the allowed list, e.g. 'lock_pc'"},
        },
        "required": ["command_id"],
    },
    _system_command_handler,
    rate_limit_seconds=10.0,
)

register(
    "describe_screen",
    "Capture the current screen and return a description of what is visible.",
    {"type": "object", "properties": {}},
    _describe_screen_handler,
)

register(
    "open_application",
    "Open a desktop application by name.",
    {
        "type": "object",
        "properties": {
            "app_name": {"type": "string", "description": "Application name, e.g. 'notepad', 'chrome'"},
        },
        "required": ["app_name"],
    },
    _open_app_handler,
    rate_limit_seconds=5.0,
)

register(
    "search_web",
    "Search the web for information using a local SearxNG instance.",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
        },
        "required": ["query"],
    },
    _search_web_handler,
)


def load_plugins(config) -> int:
    """
    Discover and load tools from the plugins directory.
    Each plugin module must expose a list TOOLS of dicts with keys:
      name, description, parameters, handler, rate_limit_seconds (optional)
    Returns the number of tools loaded.
    """
    import importlib
    import sys as _sys
    from pathlib import Path

    plugins_path = getattr(getattr(config, "plugins", None), "plugins_path", "plugins")
    if not getattr(getattr(config, "plugins", None), "enabled", False):
        return 0

    path = Path(plugins_path)
    if not path.exists():
        return 0

    count = 0
    for pyfile in path.glob("*.py"):
        if pyfile.name.startswith("_"):
            continue
        try:
            spec_name = f"_jarvis_plugin_{pyfile.stem}"
            if spec_name in _sys.modules:
                mod = _sys.modules[spec_name]
            else:
                import importlib.util
                spec = importlib.util.spec_from_file_location(spec_name, pyfile)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                _sys.modules[spec_name] = mod
            for tool in getattr(mod, "TOOLS", []):
                register(
                    tool["name"],
                    tool["description"],
                    tool.get("parameters", {"type": "object", "properties": {}}),
                    tool["handler"],
                    tool.get("rate_limit_seconds", 0.0),
                )
                count += 1
                LOG.info("Loaded plugin tool: %s from %s", tool["name"], pyfile.name)
        except Exception as exc:
            LOG.warning("Failed to load plugin %s: %s", pyfile, exc)
    return count
