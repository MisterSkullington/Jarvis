"""
Tests for orchestrator dispatch_and_respond() with mocked integrations.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch
import time

import pytest

from services.orchestrator.main import dispatch_and_respond


@pytest.fixture(autouse=True)
def reset_rate_limit():
    """Reset the rate-limit timer before each test."""
    import services.orchestrator.main as orch
    orch._last_dangerous_action_time = 0.0
    yield


# ---------------------------------------------------------------------------
# Greet
# ---------------------------------------------------------------------------

def test_greet(mock_config):
    result = dispatch_and_respond("hello", {"intent": "greet", "entities": {}}, mock_config, MagicMock())
    assert "Sir" in result or "Good day" in result


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------

def test_weather(mock_config):
    with patch("services.integrations.web_apis.get_weather") as mock_weather:
        mock_weather.return_value = {"summary": "clear sky, 18°C", "location": "London"}
        result = dispatch_and_respond(
            "weather in London",
            {"intent": "weather", "entities": {"location": "London"}},
            mock_config,
            MagicMock(),
        )
    assert "London" in result or "18" in result or "clear" in result.lower()


def test_weather_no_location(mock_config):
    with patch("services.integrations.web_apis.get_weather") as mock_weather:
        mock_weather.return_value = {"summary": "partly cloudy, 12°C"}
        result = dispatch_and_respond(
            "what's the weather",
            {"intent": "weather", "entities": {}},
            mock_config,
            MagicMock(),
        )
    assert result  # just check it returns something


# ---------------------------------------------------------------------------
# Light control
# ---------------------------------------------------------------------------

def test_light_on(mock_config):
    with patch("services.integrations.home_assistant.set_light_state") as mock_light:
        mock_light.return_value = {"ok": True, "entity_id": "light.living_room"}
        result = dispatch_and_respond(
            "turn on the living room lights",
            {"intent": "light_control", "entities": {"action": "turn on", "room": "living room"}},
            mock_config,
            MagicMock(),
        )
    assert "living room" in result.lower() or "on" in result.lower()


def test_light_error(mock_config):
    with patch("services.integrations.home_assistant.set_light_state") as mock_light:
        mock_light.return_value = {"ok": False, "error": "HA unreachable"}
        result = dispatch_and_respond(
            "turn on lights",
            {"intent": "light_control", "entities": {"action": "turn on", "room": "bedroom"}},
            mock_config,
            MagicMock(),
        )
    assert result  # error message returned


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------

def test_calendar_with_events(mock_config):
    with patch("services.integrations.calendar.get_next_events") as mock_cal:
        mock_cal.return_value = [
            {"summary": "Team standup", "start": "20260310T090000"},
            {"summary": "Lunch with Alice", "start": "20260310T120000"},
        ]
        result = dispatch_and_respond(
            "what's on my calendar",
            {"intent": "calendar", "entities": {}},
            mock_config,
            MagicMock(),
        )
    assert "Team standup" in result
    assert "Lunch with Alice" in result


def test_calendar_empty(mock_config):
    with patch("services.integrations.calendar.get_next_events") as mock_cal:
        mock_cal.return_value = []
        result = dispatch_and_respond(
            "check my calendar",
            {"intent": "calendar", "entities": {}},
            mock_config,
            MagicMock(),
        )
    assert "clear" in result.lower() or "no" in result.lower() or "upcoming" in result.lower()


# ---------------------------------------------------------------------------
# System command
# ---------------------------------------------------------------------------

def test_system_command_lock(mock_config):
    with patch("services.integrations.system_control.run_system_command") as mock_cmd:
        mock_cmd.return_value = {"ok": True, "command_id": "lock_pc"}
        result = dispatch_and_respond(
            "lock my pc",
            {"intent": "system_command", "entities": {"command_id": "lock_pc"}},
            mock_config,
            MagicMock(),
        )
    assert "lock" in result.lower() or "Sir" in result


def test_system_command_unknown(mock_config):
    result = dispatch_and_respond(
        "do something",
        {"intent": "system_command", "entities": {}},
        mock_config,
        MagicMock(),
    )
    assert "not sure" in result.lower() or "which" in result.lower()


def test_system_command_error(mock_config):
    with patch("services.integrations.system_control.run_system_command") as mock_cmd:
        mock_cmd.return_value = {"ok": False, "error": "Access denied"}
        result = dispatch_and_respond(
            "lock my pc",
            {"intent": "system_command", "entities": {"command_id": "lock_pc"}},
            mock_config,
            MagicMock(),
        )
    assert "failed" in result.lower() or "Access denied" in result


# ---------------------------------------------------------------------------
# Reminder
# ---------------------------------------------------------------------------

def test_reminder(mock_config):
    mqtt_mock = MagicMock()
    result = dispatch_and_respond(
        "remind me to call John at 5pm",
        {"intent": "reminder", "entities": {"task": "call John", "time": "5pm"}},
        mock_config,
        mqtt_mock,
    )
    assert "call John" in result or "5pm" in result
    mqtt_mock.publish.assert_called_once()


# ---------------------------------------------------------------------------
# Timer
# ---------------------------------------------------------------------------

def test_timer(mock_config):
    mqtt_mock = MagicMock()
    result = dispatch_and_respond(
        "set timer for 10 minutes",
        {"intent": "timer", "entities": {"duration": "10", "unit": "min"}},
        mock_config,
        mqtt_mock,
    )
    assert "10" in result or "timer" in result.lower()
    mqtt_mock.publish.assert_called_once()


# ---------------------------------------------------------------------------
# Time query
# ---------------------------------------------------------------------------

def test_time_query(mock_config):
    result = dispatch_and_respond(
        "what time is it",
        {"intent": "time_query", "entities": {}},
        mock_config,
        MagicMock(),
    )
    assert ":" in result  # HH:MM format


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------

def test_cancel(mock_config):
    result = dispatch_and_respond(
        "cancel",
        {"intent": "cancel", "entities": {}},
        mock_config,
        MagicMock(),
    )
    assert "cancel" in result.lower()
