#!/usr/bin/env python3
"""Report owner activity and long-running turns from `amp threads export`.

Requires only the Python stdlib and a logged-in `amp` CLI. Read-only;
QUEUE-BLIND is a proxy for delayed non-steering delivery, not queue inspection.
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone


def export(tid):
    proc = subprocess.run(
        ["amp", "threads", "export", tid],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if proc.returncode != 0:
        # CLI error output may contain transcript data or credentials.
        raise RuntimeError(f"amp threads export exited with status {proc.returncode}")
    return json.loads(proc.stdout)


def assistant_timestamp(message):
    timestamp = message.get("usage", {}).get("timestamp")
    return (
        datetime.fromisoformat(timestamp.replace("Z", "+00:00")) if timestamp else None
    )


def activity(messages, now, active_min, stale_min):
    last_asst_idx = next(
        (
            i
            for i in range(len(messages) - 1, -1, -1)
            if messages[i].get("role") == "assistant"
        ),
        None,
    )
    if last_asst_idx is None:
        return "NO-ASSISTANT-TURN", None, "thread never answered"
    asst = messages[last_asst_idx]
    asst_ts = assistant_timestamp(asst)
    state = asst.get("state", {})
    inbound = []
    tool_results = 0
    for message in messages[last_asst_idx + 1 :]:
        if message.get("role") != "user":
            continue
        content = message.get("content", [])
        if any(block.get("type") == "text" for block in content):
            sent = message.get("meta", {}).get("sentAt")
            inbound.append(
                datetime.fromtimestamp(sent / 1000, tz=timezone.utc)
                if sent is not None
                else None
            )
        tool_results += sum(block.get("type") == "tool_result" for block in content)
    age_min = (now - asst_ts).total_seconds() / 60 if asst_ts else None
    if state.get("type") != "complete":
        if age_min is not None and age_min > stale_min:
            return (
                "STREAMING",
                asst_ts,
                f"assistant message incomplete for {age_min:.0f} min",
            )
        return "WORKING", asst_ts, "assistant message in progress"
    if inbound:
        oldest = min((timestamp for timestamp in inbound if timestamp), default=asst_ts)
        if oldest is None:
            return "UNKNOWN", asst_ts, "inbound wait has no timestamp"
        wait_min = (now - oldest).total_seconds() / 60
        status = "UNANSWERED" if wait_min > stale_min else "WORKING"
        return (
            status,
            asst_ts,
            f"{len(inbound)} inbound message(s) waiting {wait_min:.0f} min",
        )
    if age_min is None:
        return "UNKNOWN", asst_ts, "last assistant message has no timestamp"
    if state.get("stopReason") == "tool_use":
        if tool_results == 0:
            if age_min > stale_min:
                return (
                    "WEDGED",
                    asst_ts,
                    f"tool call without result for {age_min:.0f} min",
                )
            return "WORKING", asst_ts, "tool call in flight"
        if age_min <= active_min:
            return (
                "WORKING",
                asst_ts,
                "tool results returned, next assistant message pending",
            )
        return (
            "WEDGED",
            asst_ts,
            f"last model activity {age_min:.0f} min ago, tool results present",
        )
    if age_min <= active_min:
        return "WORKING", asst_ts, "turn ended moments ago"
    return "IDLE", asst_ts, f"turn ended {age_min:.0f} min ago"


def classify(doc, now, active_min, stale_min, turn_max_hours=2):
    messages = doc["messages"]
    status, timestamp, why = activity(messages, now, active_min, stale_min)
    turn_messages = []
    for message in reversed(messages):
        if message.get("role") != "assistant":
            continue
        state = message.get("state", {})
        stop = state.get("stopReason")
        if state.get("type") == "complete" and stop and stop != "tool_use":
            break
        turn_messages.append(message)
    # Start at the first timestamp observed after the last completed turn,
    # not at that turn's end: idle time must not count as a running turn.
    started = next(
        (
            ts
            for message in reversed(turn_messages)
            if (ts := assistant_timestamp(message)) is not None
        ),
        None,
    )
    if started is not None:
        hours = (now - started).total_seconds() / 3600
        if hours > turn_max_hours:
            status += "+QUEUE-BLIND"
            why += f"; turn running {hours:.2f} hours, {len(turn_messages)} assistant messages"
    return status, timestamp, why


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--active-minutes", type=float, default=10)
    ap.add_argument("--stale-minutes", type=float, default=10)
    ap.add_argument("--turn-max-hours", type=float, default=2)
    ap.add_argument("threads", nargs="+")
    args = ap.parse_args()
    failed = False
    pacific = timezone(timedelta(hours=-7), "UTC-7")
    for tid in args.threads:
        try:
            doc = export(tid)
            status, timestamp, why = classify(
                doc,
                datetime.now(timezone.utc),
                args.active_minutes,
                args.stale_minutes,
                args.turn_max_hours,
            )
        except (
            OSError,
            subprocess.SubprocessError,
            ValueError,
            KeyError,
            TypeError,
            RuntimeError,
        ) as error:
            # Do not echo raw export content from parsing or subprocess errors.
            print(f"{tid} | ERROR | could not read export ({type(error).__name__})")
            failed = True
            continue
        last = (
            timestamp.astimezone(pacific).strftime("%Y-%m-%d %H:%M UTC-7")
            if timestamp
            else "-"
        )
        print(f"{tid} | {status} | last model {last} | {why}")
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
