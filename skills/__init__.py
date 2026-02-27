"""
J.A.R.V.I.S. skill/plugin system.

Each skill is a Python module in this directory that registers intent
handlers. The orchestrator loads skills dynamically at startup.

To create a skill:
1. Create a file in skills/ (e.g. skills/my_skill.py)
2. Define a SKILL_NAME, INTENTS list, and handler functions
3. Export a register(registry) function that adds handlers to the registry

Example:

    SKILL_NAME = "my_skill"
    INTENTS = ["my_intent"]

    def handle_my_intent(text, entities, config, mqtt_client, user):
        return "Response from my skill"

    def register(registry):
        registry["my_intent"] = handle_my_intent
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
from pathlib import Path
from typing import Any, Callable, Dict, Optional

LOG = logging.getLogger(__name__)

SkillHandler = Callable[..., str]
SkillRegistry = Dict[str, SkillHandler]


def load_skills() -> SkillRegistry:
    """Discover and load all skills from the skills/ package."""
    registry: SkillRegistry = {}
    skills_dir = Path(__file__).parent

    for finder, name, ispkg in pkgutil.iter_modules([str(skills_dir)]):
        if name.startswith("_"):
            continue
        try:
            module = importlib.import_module(f"skills.{name}")
            if hasattr(module, "register"):
                module.register(registry)
                skill_name = getattr(module, "SKILL_NAME", name)
                intents = list(registry.keys())
                LOG.info("Loaded skill: %s (intents: %s)", skill_name, intents)
            else:
                LOG.debug("Skill %s has no register() function, skipping", name)
        except Exception as e:
            LOG.warning("Failed to load skill %s: %s", name, e)

    return registry
