#!/usr/bin/env python3
"""Aggregate Amp thread spend across recent threads.

Enumerates threads with `amp threads list --json`, queries active ones with
`amp threads usage --details --start/--end`, and prints a markdown report of
daily (and, for top spenders, hourly) cost per thread with model/tier mix.

The server limits usage queries to 60 per hour account-wide, so this script
spends a strict call budget (default 50): one daily-window call per thread,
most-recently-updated first, then hourly-window calls for the biggest
spenders with whatever budget remains. On a rate-limit error it stops
querying and reports partial results.

Requires only the Python stdlib and a logged-in `amp` CLI.
"""

import argparse
import json
import re
import subprocess
import threading
from datetime import datetime, timedelta, timezone

ANSI_RE = re.compile(r"\x1b\[[0-9;<=>?]*[A-Za-z]|\x1b.")
COST_RE = re.compile(r"^Cost: \$([0-9,]+(?:\.[0-9]+)?)", re.M)
TOKENS_RE = re.compile(r"^Total tokens: ([0-9,]+)", re.M)
REQUESTS_RE = re.compile(r"^Requests: ([0-9,]+)", re.M)
MODEL_ROW_RE = re.compile(
    r"^\| (?!Model \|)(?!--- )([^|]+?) \| ([0-9,]+) \| [0-9,]+ \| [0-9,]+ \| "
    r"\$([0-9,]+(?:\.[0-9]+)?) \|$"
)

# Model name substring (lowercase) -> tier, checked in order. Usage output
# shows only the model name, and GPT-5.6 Sol serves BOTH high (xhigh effort)
# and medium (medium effort) tiers, so it cannot be split from cost data
# alone; confirm a Sol thread's actual mode from the thread itself. GLM-5.2
# is the low tier; its "(Sub Discount)" variant is subagent traffic.
# When a model shows up as unknown(...), verify against a thread of known
# mode and extend this table.
TIER_BY_MODEL = {
    "fable 5": "ultra",
    "gpt-5.6 sol": "high/med",
    "sub discount": "subagent",
    "glm": "low",
    # Luna handles per-thread housekeeping (title generation etc.) at
    # negligible cost in every mode; it is not a tier.
    "luna": "overhead",
}


class RateLimited(Exception):
    pass


class Budget:
    """Thread-safe call budget that trips permanently on rate-limit."""

    def __init__(self, calls):
        self.remaining = calls
        self.tripped = False
        self.lock = threading.Lock()

    def take(self):
        with self.lock:
            if self.tripped or self.remaining <= 0:
                return False
            self.remaining -= 1
            return True

    def trip(self):
        with self.lock:
            self.tripped = True


def amp(args, timeout=180):
    proc = subprocess.run(
        ["amp", *args], capture_output=True, text=True, timeout=timeout
    )
    out = ANSI_RE.sub("", proc.stdout)
    err = ANSI_RE.sub("", proc.stderr)
    if "limited to 60 requests" in out or "limited to 60 requests" in err:
        raise RateLimited("server usage-query rate limit (60/hour) reached")
    if proc.returncode != 0:
        raise RuntimeError(f"amp {' '.join(args)}: {err.strip()[:200]}")
    return out


def to_float(s):
    return float(s.replace(",", ""))


def to_int(s):
    return int(s.replace(",", ""))


def tier_of(model_name):
    low = model_name.lower()
    for key, tier in TIER_BY_MODEL.items():
        if key in low:
            return tier
    return f"unknown({model_name})"


def parse_details(text):
    cost = COST_RE.search(text)
    tokens = TOKENS_RE.search(text)
    requests = REQUESTS_RE.search(text)
    in_models = False
    models = []
    for line in text.splitlines():
        if line.startswith("## "):
            in_models = line.strip() == "## Models"
            continue
        if in_models:
            m = MODEL_ROW_RE.match(line)
            if m:
                name = m.group(1).strip()
                models.append(
                    {
                        "model": name,
                        "requests": to_int(m.group(2)),
                        "cost": to_float(m.group(3)),
                        "tier": tier_of(name),
                    }
                )
    return {
        "cost": to_float(cost.group(1)) if cost else 0.0,
        "tokens": to_int(tokens.group(1)) if tokens else 0,
        "requests": to_int(requests.group(1)) if requests else 0,
        "models": sorted(models, key=lambda m: -m["cost"]),
    }


def resolve_agent_mode(tid):
    """Read a thread's agentMode from its export.

    This is a local amp call, not a usage-API query, so it costs no budget,
    but export dumps the whole thread JSON and is slow for long threads.
    Only the extracted mode string ever leaves this function.
    """
    proc = subprocess.run(
        ["amp", "threads", "export", tid],
        capture_output=True, text=True, timeout=300,
    )
    if proc.returncode != 0:
        raise RuntimeError(ANSI_RE.sub("", proc.stderr).strip()[:200])
    mode = json.loads(proc.stdout).get("agentMode")
    if mode not in ("low", "medium", "high", "ultra"):
        raise RuntimeError(f"unexpected agentMode {mode!r}")
    return mode


def usage_call(budget, tid, start, end, details):
    if not budget.take():
        raise RateLimited("call budget exhausted")
    args = ["threads", "usage", tid, "--start", start, "--end", end]
    if details:
        args.insert(3, "--details")
    try:
        return amp(args)
    except RateLimited:
        budget.trip()
        raise


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hourly-window", type=float, default=1.0, metavar="HOURS")
    ap.add_argument("--daily-window", type=float, default=24.0, metavar="HOURS")
    ap.add_argument("--limit", type=int, default=200, help="threads to enumerate")
    ap.add_argument("--budget", type=int, default=50,
                    help="max usage-API calls this run (server limit: 60/hour)")
    ap.add_argument("--hourly-top", type=int, default=10,
                    help="fetch hourly cost only for this many top spenders")
    ap.add_argument("--min-cost", type=float, default=0.01,
                    help="hide threads below this daily cost")
    ap.add_argument("--resolve-modes", type=int, default=10, metavar="N",
                    help="split Sol high/med via thread export for the top N "
                         "spenders (0 to disable; slow for long threads)")
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    day_start = iso(now - timedelta(hours=args.daily_window))
    hour_start = iso(now - timedelta(hours=args.hourly_window))
    end = iso(now)
    budget = Budget(args.budget)

    threads = json.loads(
        amp(["threads", "list", "--json", "--limit", str(args.limit)])
    )
    cutoff = now - timedelta(hours=args.daily_window)
    active = sorted(
        (
            t
            for t in threads
            if t.get("updated")
            and datetime.fromisoformat(t["updated"].replace("Z", "+00:00"))
            >= cutoff
        ),
        key=lambda t: t["updated"],
        reverse=True,
    )

    # Phase 1: one daily-window details call per thread, newest first,
    # reserving budget for phase-2 hourly calls.
    reserve = min(args.hourly_top, max(0, args.budget - len(active)) + args.hourly_top)
    rows, errors, skipped = [], [], []
    for t in active:
        if budget.tripped or budget.remaining <= max(0, reserve):
            skipped.append(t)
            continue
        try:
            day = parse_details(
                usage_call(budget, t["id"], day_start, end, details=True)
            )
        except RateLimited as exc:
            errors.append(f"{t['id']}: {exc}")
            skipped.append(t)
            continue
        except Exception as exc:
            errors.append(f"{t['id']} ({t.get('title', '?')}): {exc}")
            continue
        top = day["models"][0] if day["models"] else None
        rows.append(
            {
                "id": t["id"],
                "title": t.get("title") or "(untitled)",
                "updated": t.get("updated", ""),
                "day_cost": day["cost"],
                "hour_cost": None,
                "day_requests": day["requests"],
                "day_tokens": day["tokens"],
                "models": day["models"],
                "top_model": top["model"] if top else "-",
                "tier": top["tier"] if top else "-",
            }
        )

    # Phase 2: hourly cost for the biggest daily spenders.
    rows.sort(key=lambda r: -r["day_cost"])
    for r in rows[: args.hourly_top]:
        if budget.tripped or r["day_cost"] == 0:
            continue
        try:
            text = usage_call(budget, r["id"], hour_start, end, details=False)
            m = COST_RE.search(text)
            r["hour_cost"] = to_float(m.group(1)) if m else 0.0
        except Exception as exc:
            errors.append(f"{r['id']} hourly: {exc}")

    # Phase 3: split ambiguous Sol high/med tiers by reading agentMode from
    # thread exports (no usage-API budget cost, but slow for long threads).
    for r in rows[: args.resolve_modes]:
        if r["tier"] != "high/med":
            continue
        try:
            r["tier"] = resolve_agent_mode(r["id"])
        except Exception as exc:
            errors.append(f"{r['id']} mode: {exc}")

    total_day = sum(r["day_cost"] for r in rows)
    known_hour = [r for r in rows if r["hour_cost"] is not None]
    total_hour = sum(r["hour_cost"] for r in known_hour)
    shown = [r for r in rows if r["day_cost"] >= args.min_cost]
    ultra = [
        r
        for r in rows
        if any(m["tier"] == "ultra" and m["cost"] > 0 for m in r["models"])
    ]
    used = args.budget - budget.remaining

    if args.as_json:
        print(
            json.dumps(
                {
                    "generated": end,
                    "hourly_window_hours": args.hourly_window,
                    "daily_window_hours": args.daily_window,
                    "total_day_cost": round(total_day, 2),
                    "total_hour_cost_top_spenders": round(total_hour, 2),
                    "hourly_covered_threads": len(known_hour),
                    "calls_used": used,
                    "rate_limited": budget.tripped,
                    "threads": rows,
                    "skipped_thread_ids": [t["id"] for t in skipped],
                    "errors": errors,
                },
                indent=2,
            )
        )
        return

    print(f"# Thread usage report - {end}")
    print()
    print(
        f"Windows: hourly = last {args.hourly_window:g}h, "
        f"daily = last {args.daily_window:g}h. "
        f"Queried {len(rows)} of {len(active)} active threads "
        f"({len(threads)} listed); API calls used: {used}/{args.budget}."
    )
    if budget.tripped:
        print()
        print("**WARNING: server rate limit (60 usage queries/hour) hit - "
              "results are partial. Rerun after the top of the next hour.**")
    if skipped:
        print()
        print(f"Skipped {len(skipped)} least-recently-updated threads to stay "
              f"in budget.")
    print()
    print(
        f"**TOTALS: last {args.daily_window:g}h ${total_day:.2f} | "
        f"last {args.hourly_window:g}h ${total_hour:.2f} "
        f"(top {len(known_hour)} spenders only)**"
    )
    print()
    print(f"| Thread | Title | {args.hourly_window:g}h $ | "
          f"{args.daily_window:g}h $ | Req | Top model (tier) |")
    print("| --- | --- | ---: | ---: | ---: | --- |")
    for r in shown:
        hour = f"{r['hour_cost']:.2f}" if r["hour_cost"] is not None else "-"
        print(
            f"| {r['id']} | {r['title'][:48]} | {hour} "
            f"| {r['day_cost']:.2f} | {r['day_requests']} "
            f"| {r['top_model']} ({r['tier']}) |"
        )
    hidden = len(rows) - len(shown)
    if hidden:
        hidden_cost = sum(
            r["day_cost"] for r in rows if r["day_cost"] < args.min_cost
        )
        print(f"| ... | {hidden} threads under ${args.min_cost:.2f} "
              f"| | {hidden_cost:.2f} | | |")
    print()
    print("## Flags")
    if ultra:
        for r in ultra:
            print(
                f"- ULTRA usage: {r['id']} ({r['title'][:48]}) "
                f"${r['day_cost']:.2f} in window - policy violation, "
                f"recommend immediate succession"
            )
    else:
        print("- No ultra-tier usage among queried threads.")
    for r in shown[:5]:
        print(
            f"- Top spender: {r['id']} ({r['title'][:48]}) "
            f"${r['day_cost']:.2f}/{args.daily_window:g}h, tier {r['tier']}"
        )
    for e in errors[:10]:
        print(f"- ERROR: {e}")
    if len(errors) > 10:
        print(f"- ... and {len(errors) - 10} more errors")


if __name__ == "__main__":
    main()
