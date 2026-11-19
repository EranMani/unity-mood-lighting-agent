"""
eval.py — the eval harness. NOT a tool, not part of the agent at all; this
is scaffolding that runs FROM OUTSIDE the agent, calling main.py's run()
once per case in eval_suite.json and tagging each result with that case's
name in mood_test_log.jsonl (so later runs of the same case are
comparable over time).

Scope decided live with Eran: single trial per case for v0 (one run per
mood, not N repeated trials). Real production eval setups often run each
case multiple times since LLM output isn't deterministic - that's the
next thing to add if scores look inconsistent run-to-run, not before.

Usage:
    uv run python src/unity_mood_lighting_agent/eval.py
        Runs every case in eval_suite.json, prints a summary at the end.
    uv run python src/unity_mood_lighting_agent/eval.py horror zen
        Runs only the named case(s).
"""

import asyncio
import json
import sys
from pathlib import Path

from unity_mood_lighting_agent.main import LOG_PATH, run

SUITE_PATH = Path(__file__).resolve().parent / "eval_suite.json"


def _load_suite() -> list[dict]:
    return json.loads(SUITE_PATH.read_text(encoding="utf-8"))


def _latest_per_case() -> dict[str, dict]:
    """Read mood_test_log.jsonl, keep only the most recent row per
    case_name (untagged/ad-hoc rows, case_name=None, are ignored here -
    this summary is specifically about the named eval suite)."""
    latest: dict[str, dict] = {}
    if not LOG_PATH.exists():
        return latest
    with open(LOG_PATH, encoding="utf-8") as f:
        for line in f:
            entry = json.loads(line)
            name = entry.get("case_name")
            if name:
                latest[name] = entry  # later lines overwrite earlier ones - log is append-only in time order
    return latest


def print_summary(case_names: list[str]) -> None:
    latest = _latest_per_case()
    print("\n--- Eval summary (latest result per case) ---")
    passed_count = 0
    for name in case_names:
        entry = latest.get(name)
        if entry is None:
            print(f"{name:20s} no result")
            continue
        status = "PASS" if entry["passed"] else "FAIL"
        passed_count += entry["passed"]
        print(f"{name:20s} {status}  score={entry['mood_match_score']}/10  attempts={entry['attempts_used']}")
    print(f"\n{passed_count}/{len(case_names)} passed")


async def run_suite(only: list[str] | None = None) -> None:
    suite = _load_suite()
    if only:
        suite = [c for c in suite if c["name"] in only]
        missing = set(only) - {c["name"] for c in suite}
        if missing:
            print(f"Unknown case name(s), skipping: {missing}")

    for case in suite:
        print(f"\n=== Running case: {case['name']} ===")
        output = await run(case["task"], case_name=case["name"])
        print(output)

    print_summary([c["name"] for c in suite])


if __name__ == "__main__":
    only_names = sys.argv[1:] or None
    asyncio.run(run_suite(only_names))
