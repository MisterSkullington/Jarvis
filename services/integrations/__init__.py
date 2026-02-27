# Integrations: home_assistant, web_apis, calendar, system_control, web_search

from .home_assistant import (
    set_light_state,
    get_light_state,
    set_climate,
    get_climate,
    lock_control,
    activate_scene,
    media_control,
)
from .web_apis import get_weather, get_news
from .calendar import get_next_events
from .system_control import run_system_command
from .web_search import search_web, search_web_structured

__all__ = [
    "set_light_state",
    "get_light_state",
    "set_climate",
    "get_climate",
    "lock_control",
    "activate_scene",
    "media_control",
    "get_weather",
    "get_news",
    "get_next_events",
    "run_system_command",
    "search_web",
    "search_web_structured",
]
