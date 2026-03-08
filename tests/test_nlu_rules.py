"""
Tests for NLU rule-based intent parsing.
Covers every pattern in RULES including the static-entity extension (Phase 1.3).
"""
from __future__ import annotations

import pytest
from services.nlu_agent.main import rule_based_parse


# ---------------------------------------------------------------------------
# Greet
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["hello", "hi there", "hey Jarvis", "good morning", "good evening"])
def test_greet(text):
    result = rule_based_parse(text)
    assert result is not None
    assert result[0] == "greet"
    assert result[2] == 0.9


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------

def test_weather_with_location():
    result = rule_based_parse("what's the weather in London")
    assert result is not None
    assert result[0] == "weather"
    assert result[1].get("location") == "London"


def test_weather_no_location():
    result = rule_based_parse("weather today")
    assert result is not None
    assert result[0] == "weather"


def test_temperature_with_location():
    result = rule_based_parse("temperature in New York")
    assert result is not None
    assert result[0] == "weather"
    assert "New York" in result[1].get("location", "")


# ---------------------------------------------------------------------------
# Light control
# ---------------------------------------------------------------------------

def test_light_turn_on():
    result = rule_based_parse("turn on the living room lights")
    assert result is not None
    assert result[0] == "light_control"
    assert "living room" in result[1].get("room", "").lower()


def test_light_turn_off():
    result = rule_based_parse("turn off bedroom lights")
    assert result is not None
    assert result[0] == "light_control"


def test_light_room_shorthand():
    result = rule_based_parse("kitchen lights on")
    assert result is not None
    assert result[0] == "light_control"
    assert result[1].get("room") == "kitchen"


# ---------------------------------------------------------------------------
# Reminder
# ---------------------------------------------------------------------------

def test_reminder():
    result = rule_based_parse("remind me to call John at 3pm")
    assert result is not None
    assert result[0] == "reminder"
    assert "call John" in result[1].get("task", "")
    assert "3pm" in result[1].get("time", "")


# ---------------------------------------------------------------------------
# Timer
# ---------------------------------------------------------------------------

def test_timer_minutes():
    result = rule_based_parse("set a timer for 5 minutes")
    assert result is not None
    assert result[0] == "timer"
    assert result[1].get("duration") == "5"


def test_timer_hours():
    result = rule_based_parse("timer 1 hour")
    assert result is not None
    assert result[0] == "timer"
    assert result[1].get("unit").startswith("hour")


# ---------------------------------------------------------------------------
# Time query
# ---------------------------------------------------------------------------

def test_time_query():
    for phrase in ["what time is it", "current time", "time now"]:
        result = rule_based_parse(phrase)
        assert result is not None, f"Expected time_query for '{phrase}'"
        assert result[0] == "time_query"


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "what's on my calendar",
    "check my schedule",
    "show my agenda",
    "next meeting",
    "upcoming events",
    "my agenda for today",
])
def test_calendar(text):
    result = rule_based_parse(text)
    assert result is not None, f"Expected calendar intent for '{text}'"
    assert result[0] == "calendar"


# ---------------------------------------------------------------------------
# System command — static entity (Phase 1.3)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "lock my pc",
    "lock my computer",
    "lock the screen",
    "lock workstation",
    "lock my screen",
])
def test_system_command_lock(text):
    result = rule_based_parse(text)
    assert result is not None, f"Expected system_command for '{text}'"
    assert result[0] == "system_command"
    assert result[1].get("command_id") == "lock_pc", f"Expected lock_pc entity for '{text}'"


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------

def test_cancel():
    for phrase in ["stop", "cancel", "never mind"]:
        result = rule_based_parse(phrase)
        assert result is not None
        assert result[0] == "cancel"


# ---------------------------------------------------------------------------
# No match
# ---------------------------------------------------------------------------

def test_no_match_returns_none():
    result = rule_based_parse("xyzzy frobble zork")
    assert result is None


def test_empty_returns_none():
    assert rule_based_parse("") is None
    assert rule_based_parse("   ") is None
