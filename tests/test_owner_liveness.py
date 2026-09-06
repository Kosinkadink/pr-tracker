import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / ".agents/skills/reporting-thread-usage/scripts/owner_liveness.py"
)
spec = importlib.util.spec_from_file_location("owner_liveness", SCRIPT)
owner_liveness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(owner_liveness)
NOW = datetime(2026, 9, 6, 20, tzinfo=timezone.utc)


def assistant(minutes=1, stop="tool_use", complete=True):
    return {
        "role": "assistant",
        "usage": {"timestamp": (NOW - timedelta(minutes=minutes)).isoformat()},
        "state": {"type": "complete" if complete else "streaming", "stopReason": stop},
    }


def user(minutes=1, kind="text"):
    return {
        "role": "user",
        "meta": {"sentAt": (NOW - timedelta(minutes=minutes)).timestamp() * 1000},
        "content": [{"type": kind}],
    }


@pytest.mark.parametrize(
    "messages, expected",
    [
        ([], "NO-ASSISTANT-TURN"),
        ([user()], "NO-ASSISTANT-TURN"),
        ([assistant()], "WORKING"),
        ([assistant(stop="end_turn")], "WORKING"),
        ([assistant(20, stop="end_turn")], "IDLE"),
        ([assistant(20, stop="end_turn"), user(15)], "UNANSWERED"),
        ([assistant(20, stop="end_turn"), user()], "WORKING"),
        ([assistant(20)], "WEDGED"),
        ([assistant(), user(kind="tool_result")], "WORKING"),
        ([assistant(20), user(kind="tool_result")], "WEDGED"),
        ([assistant(20, stop=None, complete=False)], "STREAMING"),
        ([assistant(stop=None, complete=False)], "WORKING"),
        ([{"role": "assistant", "state": {"type": "complete"}}], "UNKNOWN"),
    ],
)
def test_activity_states(messages, expected):
    assert owner_liveness.classify({"messages": messages}, NOW, 10, 10)[0] == expected


def test_tool_loop_without_any_ended_turn_is_queue_blind():
    messages = [assistant(1020 - i * 1019 / 2437) for i in range(2438)]
    status, timestamp, why = owner_liveness.classify(
        {"messages": messages}, NOW, 10, 10
    )
    assert status == "WORKING+QUEUE-BLIND"
    assert timestamp == NOW - timedelta(minutes=1)
    assert "17.00 hours, 2438 assistant messages" in why


@pytest.mark.parametrize(
    "age, limit, flagged", [(120, 2, False), (121, 2, True), (121, 3, False)]
)
def test_turn_duration_threshold(age, limit, flagged):
    doc = {"messages": [assistant(age), assistant()]}
    status, _, _ = owner_liveness.classify(doc, NOW, 10, 10, limit)
    assert ("QUEUE-BLIND" in status) == flagged


def test_idle_gap_and_previous_turn_are_excluded():
    doc = {"messages": [assistant(1000), assistant(900, "end_turn"), assistant()]}
    assert owner_liveness.classify(doc, NOW, 10, 10)[0] == "WORKING"


@pytest.mark.parametrize("stop", ["end_turn", "max_tokens"])
def test_completed_non_tool_stop_clears_flag(stop):
    doc = {"messages": [assistant(180), assistant(stop=stop)]}
    assert owner_liveness.classify(doc, NOW, 10, 10)[0] == "WORKING"


@pytest.mark.parametrize(
    "tail, expected, count",
    [
        ([assistant()], "WORKING", 2),
        ([assistant(20)], "WEDGED", 2),
        ([assistant(20, stop=None, complete=False)], "STREAMING", 2),
        ([user(20)], "UNANSWERED", 1),
        ([user(20), assistant()], "WORKING", 2),
    ],
)
def test_queue_blind_preserves_activity_and_ignores_inbound_boundaries(
    tail, expected, count
):
    doc = {"messages": [assistant(300, "end_turn"), assistant(180), *tail]}
    status, _, why = owner_liveness.classify(doc, NOW, 10, 10)
    assert status == expected + "+QUEUE-BLIND"
    assert f"3.00 hours, {count} assistant messages" in why


def test_inbound_counts_user_messages_not_text_blocks_or_system_text():
    inbound = user(15)
    inbound["content"].append({"type": "text"})
    doc = {
        "messages": [
            assistant(20),
            {"role": "system", "content": [{"type": "text"}]},
            inbound,
        ]
    }
    status, _, why = owner_liveness.classify(doc, NOW, 10, 10)
    assert status == "UNANSWERED"
    assert why == "1 inbound message(s) waiting 15 min"


def test_missing_inbound_timestamp_falls_back_to_last_model():
    doc = {"messages": [assistant(20), {"role": "user", "content": [{"type": "text"}]}]}
    assert owner_liveness.classify(doc, NOW, 10, 10)[0] == "UNANSWERED"


def test_cli_reports_pacific_time_and_continues_after_export_error(monkeypatch, capsys):
    def export(tid):
        if tid == "T-bad":
            raise ValueError("sensitive export content")
        return {"messages": [assistant(stop="end_turn")]}

    monkeypatch.setattr(owner_liveness, "export", export)
    monkeypatch.setattr(owner_liveness.sys, "argv", [str(SCRIPT), "T-bad", "T-good"])
    assert owner_liveness.main() == 1
    output = capsys.readouterr().out
    assert "T-bad | ERROR" in output
    assert "T-good |" in output
    assert "2026-09-06 12:59 UTC-7" in output
    assert "sensitive" not in output
