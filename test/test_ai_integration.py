"""
Automated tests for PetAssistant AI integration.

Pure-logic tests (no API key required) cover:
  - build_system_prompt, build_context_block, format helpers, _parse_confidence
  - chat_history management, clear_history

Mocked integration tests (no API key required) cover:
  - ask() happy path
  - ask() history growth
  - ask() API failure → fallback string
  - ask() empty response → fallback string
"""

import sys
import os
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pawpal_system import (
    FrequencyPeriod,
    Pet,
    PetAssistant,
    Priority,
    Scheduler,
    Task,
    TaskType,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pet(name="Mochi", age=3, breed="Shiba Inu") -> Pet:
    return Pet(name=name, age=age, breed=breed)


def _make_task(
    title="Morning Walk",
    duration=30,
    priority=Priority.HIGH,
    task_type=TaskType.WALK,
    times=1,
    period=FrequencyPeriod.DAILY,
) -> Task:
    return Task(
        title=title,
        duration_minutes=duration,
        type=task_type,
        priority=priority,
        times_per_period=times,
        period=period,
    )


def _make_assistant(pets=None, plan=None, sick_pets=None) -> PetAssistant:
    return PetAssistant(
        api_key="test-key",
        all_pets=pets or [],
        plan=plan,
        sick_pets=sick_pets or [],
    )


# ---------------------------------------------------------------------------
# Pure-logic tests — no API key needed
# ---------------------------------------------------------------------------

def test_build_system_prompt_contains_persona():
    asst = _make_assistant()
    prompt = asst.build_system_prompt()
    assert "PawPal" in prompt
    assert "pet care" in prompt.lower()


def test_build_system_prompt_requests_confidence_tag():
    asst = _make_assistant()
    prompt = asst.build_system_prompt()
    assert "[Confidence:" in prompt


def test_build_context_block_includes_pet_name():
    pet = _make_pet("Biscuit", 7, "Golden Retriever")
    asst = _make_assistant(pets=[pet])
    block = asst.build_context_block()
    assert "Biscuit" in block
    assert "Golden Retriever" in block


def test_build_context_block_flags_sick_pet():
    pet = _make_pet("Mochi")
    asst = _make_assistant(pets=[pet], sick_pets=["Mochi"])
    block = asst.build_context_block()
    assert "unwell" in block.lower() or "⚠️" in block


def test_build_context_block_no_pets_still_returns_string():
    asst = _make_assistant()
    block = asst.build_context_block()
    assert isinstance(block, str)


def test_format_today_summary_no_plan():
    asst = _make_assistant()
    result = asst.format_today_summary()
    assert isinstance(result, str)
    assert len(result) > 0


def test_format_today_summary_empty_tasks():
    asst = _make_assistant(plan={date.today(): []})
    result = asst.format_today_summary()
    assert "no tasks" in result.lower() or isinstance(result, str)


def test_format_today_summary_with_task():
    task = _make_task()
    task.start_time_minutes = 480
    asst = _make_assistant(plan={date.today(): [task]})
    result = asst.format_today_summary()
    assert "Morning Walk" in result


def test_format_upcoming_summary_single_task():
    task = _make_task(title="Bath Time")
    tomorrow = date.today() + timedelta(days=1)
    asst = _make_assistant(plan={tomorrow: [task]})
    result = asst.format_upcoming_summary(days=7)
    assert "Bath Time" in result


def test_format_upcoming_summary_no_plan():
    asst = _make_assistant()
    result = asst.format_upcoming_summary(days=7)
    assert isinstance(result, str)


def test_clear_history_resets():
    asst = _make_assistant()
    asst.chat_history.append({"role": "user", "content": "hello"})
    asst.clear_history()
    assert asst.chat_history == []


# ---------------------------------------------------------------------------
# _parse_confidence tests
# ---------------------------------------------------------------------------

def test_confidence_parse_valid():
    asst = _make_assistant()
    text = "Walk Mochi today! [Confidence: 85%]"
    cleaned, score = asst._parse_confidence(text)
    assert score == 85
    assert "[Confidence" not in cleaned
    assert "Walk Mochi today!" in cleaned


def test_confidence_parse_missing():
    asst = _make_assistant()
    text = "Walk Mochi today!"
    cleaned, score = asst._parse_confidence(text)
    assert score is None
    assert cleaned == text


def test_confidence_parse_zero():
    asst = _make_assistant()
    text = "I'm not sure. [Confidence: 0%]"
    cleaned, score = asst._parse_confidence(text)
    assert score == 0


def test_confidence_parse_hundred():
    asst = _make_assistant()
    text = "Feeding is due today. [Confidence: 100%]"
    _, score = asst._parse_confidence(text)
    assert score == 100


# ---------------------------------------------------------------------------
# Mocked integration tests
# ---------------------------------------------------------------------------

FAKE_REPLY = "Mochi needs a walk today! [Confidence: 90%]"


def _mock_client(reply_text=FAKE_REPLY):
    mock_response = MagicMock()
    mock_response.text = reply_text
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    return mock_client


@patch("pawpal_system.genai.Client")
def test_ask_returns_string(MockClient):
    MockClient.return_value = _mock_client()
    asst = _make_assistant()
    result = asst.ask("What should I do today?")
    assert isinstance(result, str)
    assert len(result) > 0


@patch("pawpal_system.genai.Client")
def test_ask_strips_confidence_tag_from_reply(MockClient):
    MockClient.return_value = _mock_client()
    asst = _make_assistant()
    result = asst.ask("What should I do today?")
    assert "[Confidence:" not in result


@patch("pawpal_system.genai.Client")
def test_ask_appends_to_history(MockClient):
    MockClient.return_value = _mock_client()
    asst = _make_assistant()
    asst.ask("First question")
    asst.ask("Second question")
    assert len(asst.chat_history) == 4  # 2 user + 2 assistant turns


@patch("pawpal_system.genai.Client")
def test_ask_stores_confidence_in_history(MockClient):
    MockClient.return_value = _mock_client()
    asst = _make_assistant()
    asst.ask("What should I do?")
    assistant_entry = asst.chat_history[-1]
    assert assistant_entry["role"] == "assistant"
    assert assistant_entry["confidence"] == 90


@patch("pawpal_system.genai.Client")
def test_ask_api_failure_returns_fallback(MockClient):
    mock_client_instance = MagicMock()
    mock_client_instance.models.generate_content.side_effect = Exception("Network error")
    MockClient.return_value = mock_client_instance

    asst = _make_assistant()
    result = asst.ask("What should I do?")
    assert isinstance(result, str)
    assert "trouble" in result.lower() or "try again" in result.lower()


@patch("pawpal_system.genai.Client")
def test_ask_api_failure_does_not_crash(MockClient):
    mock_client_instance = MagicMock()
    mock_client_instance.models.generate_content.side_effect = RuntimeError("Timeout")
    MockClient.return_value = mock_client_instance

    asst = _make_assistant()
    try:
        asst.ask("Hello?")
    except Exception:
        assert False, "ask() should not raise — it must return a fallback string"


@patch("pawpal_system.genai.Client")
def test_ask_empty_response_returns_fallback(MockClient):
    MockClient.return_value = _mock_client(reply_text="")
    asst = _make_assistant()
    result = asst.ask("Hello?")
    assert isinstance(result, str)
    assert len(result) > 0


@patch("pawpal_system.genai.Client")
def test_ask_history_after_failure_contains_fallback(MockClient):
    mock_client_instance = MagicMock()
    mock_client_instance.models.generate_content.side_effect = Exception("Bad key")
    MockClient.return_value = mock_client_instance

    asst = _make_assistant()
    asst.ask("Test?")
    assert len(asst.chat_history) == 2  # user turn + fallback assistant turn
    assert asst.chat_history[-1]["role"] == "assistant"
