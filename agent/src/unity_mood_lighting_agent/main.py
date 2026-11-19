"""
main.py — the actual entry point. Ties together unity_bridge, tools, agent,
judge.

v2 loop (promoted from the README's v1/v2 split, decided live with Eran):
run the lighting agent -> judge the result -> if it passed, stop; if not,
feed the judge's own notes back into the next attempt so the agent knows
WHY it failed, not just that it failed -> retry, up to MAX_ATTEMPTS -> give
up and report the last judgement if still failing. Each retry re-reads the
CURRENT live scene state (get_scene_context()), not the original state —
attempt 2 builds on whatever attempt 1 actually left in the scene.

Every run appends one row to mood_test_log.jsonl (task, attempts, final
score, pass/fail, notes) — Eran asked for a persistent record of mood
test results after compiling docs/mood-test-results.md by hand from
conversation history once; this makes future runs self-documenting
instead of needing another manual pass.

Usage:
    uv run python src/unity_mood_lighting_agent/main.py "your task here"
    uv run python src/unity_mood_lighting_agent/main.py
    (prompts for the task if not given as an argument)
"""

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from agents import Runner
from dotenv import load_dotenv

from unity_mood_lighting_agent.agent import agent, get_scene_context
from unity_mood_lighting_agent.judge import judge_mood_match
from unity_mood_lighting_agent.tools import cleanup_agent_lights

load_dotenv()

MAX_ATTEMPTS = 3
LOG_PATH = Path(__file__).resolve().parents[3] / "mood_test_log.jsonl"


def _log_result(task: str, attempts_used: int, passed: bool, judgement) -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "task": task,
        "attempts_used": attempts_used,
        "passed": passed,
        "mood_match_score": judgement.mood_match_score,
        "dominant_color_temp": judgement.dominant_color_temp,
        "contrast_level": judgement.contrast_level,
        "notes": judgement.notes,
    }
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


async def run(task: str) -> str:
    deleted = cleanup_agent_lights()
    if deleted:
        print(f"[cleanup] removed {len(deleted)} light(s) from a previous run: {deleted}")

    feedback = ""  # judge's notes from the previous failed attempt, if any

    for attempt in range(1, MAX_ATTEMPTS + 1):
        prompt = f"Current scene objects:\n{get_scene_context()}\n\nTask: {task}"
        if feedback:
            prompt += (
                f"\n\nA previous attempt did not achieve this mood. Judge feedback: {feedback}\n"
                "Adjust your approach based on this feedback."
            )

        result = await Runner.run(agent, prompt)
        passed, judgement = await judge_mood_match(task)

        print(
            f"[attempt {attempt}/{MAX_ATTEMPTS}] agent: {result.final_output} | "
            f"judge score={judgement.mood_match_score} passed={passed}"
        )

        if passed:
            _log_result(task, attempt, True, judgement)
            return f"Success on attempt {attempt}: {judgement.notes}"

        feedback = judgement.notes
        if attempt == MAX_ATTEMPTS:
            _log_result(task, attempt, False, judgement)
            return f"Gave up after {MAX_ATTEMPTS} attempts. Last judge score={judgement.mood_match_score}: {judgement.notes}"

    raise AssertionError("unreachable: loop always returns on its last iteration")


def main() -> None:
    task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else input("Task: ")
    output = asyncio.run(run(task))
    print(output)


if __name__ == "__main__":
    main()
