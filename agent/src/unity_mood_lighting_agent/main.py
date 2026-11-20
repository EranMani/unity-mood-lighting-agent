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

from agents import Runner, trace
from dotenv import load_dotenv

from unity_mood_lighting_agent.agent import agent, get_scene_context
from unity_mood_lighting_agent.judge import judge_mood_match
from unity_mood_lighting_agent.tools import cleanup_agent_lights
from unity_mood_lighting_agent.unity_bridge import (
    capture_game_view,
    capture_scene_baseline,
    ensure_scene_ready,
    get_active_scene,
    image_to_data_url,
    open_scene,
    restore_scene_baseline,
)

load_dotenv()

MAX_ATTEMPTS = 3
LOG_PATH = Path(__file__).resolve().parents[3] / "mood_test_log.jsonl"


def _log_result(task: str, attempts_used: int, passed: bool, judgement, case_name: str | None = None) -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "case_name": case_name,  # None for ad-hoc main.py calls; set when run via eval.py
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


async def run(task: str, case_name: str | None = None, scene_path: str | None = None) -> str:
    if scene_path:
        active = get_active_scene()
        if active.path != scene_path:
            print(f"[scene] active scene '{active.path}' != requested '{scene_path}' — switching")
            open_scene(scene_path)
        else:
            print(f"[scene] already on '{scene_path}'")

    deleted = cleanup_agent_lights()
    if deleted:
        print(f"[cleanup] removed {len(deleted)} light(s) from a previous run: {deleted}")

    baseline = capture_scene_baseline()
    print(f"[baseline] {baseline['status']}")
    restore_scene_baseline()
    print("[scene] restored lights/probes/skybox/post-processing to captured baseline")
    readiness = ensure_scene_ready()
    print(
        f"[scene] ready: {readiness['light_count']} light(s) ({readiness['lights_fixed']} set to Realtime), "
        f"{readiness['probe_count']} probe(s) ({readiness['probes_fixed']} set to Realtime), "
        f"volume_created={readiness['volume_created']}, baseline_light_created={readiness['baseline_light_created']}"
    )

    feedback = ""  # judge's notes from the previous failed attempt, if any

    with trace(
        workflow_name="mood_lighting_agent",
        group_id=case_name,  # links repeated runs of the SAME case together in the dashboard
        metadata={"task": task, "case_name": case_name or "adhoc"},
    ) as t:
        print(f"[trace] https://platform.openai.com/traces/trace?trace_id={t.trace_id}")
        for attempt in range(1, MAX_ATTEMPTS + 1):
            prompt_text = f"Current scene objects:\n{get_scene_context()}\n\nTask: {task}"
            if feedback:
                prompt_text += (
                    f"\n\nA previous attempt did not achieve this mood. Judge feedback: {feedback}\n"
                    "Adjust your approach based on this feedback."
                )

            # Capture the CURRENT live state as a visual starting point —
            # same input_image pattern already proven in judge.py. Numeric
            # transforms alone are a weak signal for spatial/mood
            # reasoning (the original v0 tool list's own rationale for
            # capture_viewport, never wired to this agent until now, only
            # to the judge). Re-captured every attempt, same reasoning as
            # get_scene_context() re-reading fresh each time.
            capture = capture_game_view()
            image_url = image_to_data_url(capture.path)
            prompt = [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt_text},
                        {"type": "input_image", "image_url": image_url},
                    ],
                }
            ]

            result = await Runner.run(agent, prompt)
            passed, judgement = await judge_mood_match(task)

            print(
                f"[attempt {attempt}/{MAX_ATTEMPTS}] agent: {result.final_output} | "
                f"judge score={judgement.mood_match_score} passed={passed}"
            )

            if passed:
                _log_result(task, attempt, True, judgement, case_name)
                return f"Success on attempt {attempt}: {judgement.notes}"

            feedback = judgement.notes
            if attempt == MAX_ATTEMPTS:
                _log_result(task, attempt, False, judgement, case_name)
                return f"Gave up after {MAX_ATTEMPTS} attempts. Last judge score={judgement.mood_match_score}: {judgement.notes}"

    raise AssertionError("unreachable: loop always returns on its last iteration")


def main() -> None:
    args = sys.argv[1:]
    scene_path = None
    if args and args[0] == "--scene":
        scene_path = args[1]
        args = args[2:]
    task = " ".join(args) if args else input("Task: ")
    output = asyncio.run(run(task, scene_path=scene_path))
    print(output)


if __name__ == "__main__":
    main()
