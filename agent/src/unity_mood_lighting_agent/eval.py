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
        if entry.get("guardrail_rejected"):
            # No judge was ever called for this case's final attempt —
            # visibility guardrail rejected it, there is no mood_match_score.
            print(f"{name:20s} {status}  guardrail_rejected={entry['guardrail_rejected']}  attempts={entry['attempts_used']}")
        else:
            print(f"{name:20s} {status}  score={entry['mood_match_score']}/10  attempts={entry['attempts_used']}")
    print(f"\n{passed_count}/{len(case_names)} passed")


async def run_suite(only: list[str] | None = None, scene_path: str | None = None) -> None:
    """scene_path, if given via --scene, OVERRIDES every case's own scene
    (useful for a one-off ad-hoc run against a specific scene). Normally
    omitted — each case runs against the scene assigned to it in
    eval_suite.json (indoor moods -> Mess Hall, outdoor moods -> Forest;
    TestRoom dropped from eval scope entirely, decided live with Eran —
    bare plane+cube, no atmosphere to actually test a mood against)."""
    suite = _load_suite()
    if only:
        suite = [c for c in suite if c["name"] in only]
        missing = set(only) - {c["name"] for c in suite}
        if missing:
            print(f"Unknown case name(s), skipping: {missing}")

    for case in suite:
        case_scene = scene_path or case.get("scene")
        print(f"\n=== Running case: {case['name']} (scene: {case_scene}) ===")
        output = await run(case["task"], case_name=case["name"], scene_path=case_scene)
        print(output)

    print_summary([c["name"] for c in suite])


if __name__ == "__main__":
    args = sys.argv[1:]
    scene_arg = None
    if args and args[0] == "--scene":
        scene_arg = args[1]
        args = args[2:]
    only_names = args or None
    asyncio.run(run_suite(only_names, scene_path=scene_arg))
