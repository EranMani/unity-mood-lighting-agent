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
import re
import shutil
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
    check_frame_visibility,
    ensure_scene_ready,
    get_active_scene,
    image_to_data_url,
    open_scene,
    restore_scene_baseline,
)

load_dotenv()

MAX_ATTEMPTS = 3
REPO_ROOT = Path(__file__).resolve().parents[3]
LOG_PATH = REPO_ROOT / "mood_test_log.jsonl"
SCREENSHOTS_DIR = REPO_ROOT / "screenshots"


def _log_result(
    task: str,
    attempts_used: int,
    passed: bool,
    judgement,
    case_name: str | None = None,
    run_timestamp: datetime | None = None,
) -> None:
    ts = run_timestamp or datetime.now(timezone.utc)
    entry = {
        "timestamp": ts.isoformat(),
        "case_name": case_name,  # None for ad-hoc main.py calls; set when run via eval.py
        "task": task,
        "attempts_used": attempts_used,
        "passed": passed,
        "mood_match_score": judgement.mood_match_score,
        "dominant_color_temp": judgement.dominant_color_temp,
        "contrast_level": judgement.contrast_level,
        "notes": judgement.reasoning,
    }
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _log_guardrail_rejection(
    task: str,
    attempt: int,
    visibility,
    case_name: str | None = None,
    run_timestamp: datetime | None = None,
) -> None:
    """Separate from _log_result — this is a guardrail catch, not a judge
    score. No MoodJudgement exists here (judge was never called, that's
    the whole point — save the LLM call on a frame with nothing to
    score)."""
    ts = run_timestamp or datetime.now(timezone.utc)
    entry = {
        "timestamp": ts.isoformat(),
        "case_name": case_name,
        "task": task,
        "attempts_used": attempt,
        "passed": False,
        "guardrail_rejected": "visibility",
        "mean_brightness": visibility.mean_brightness,
        "pct_near_black": visibility.pct_near_black,
    }
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _slugify(task: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", task.lower()).strip("_")
    return slug[:40] or "adhoc"


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

    # Screenshot pair for visual before/after comparison — root-level
    # screenshots/<case>/ so they're easy to find outside the Python
    # package (Eran's call: root repo folder, not buried under agent/src).
    # Named by case_name when run through eval.py; ad-hoc main.py calls
    # fall back to a slug of the task text so they still get a folder.
    #
    # Each run gets its OWN timestamped subfolder (decided live with
    # Eran, 2026-11-23) — a plain overwrite was silently destroying
    # history (couldn't see run N's screenshots once run N+1 happened to
    # the same case). The timestamp is generated ONCE here and reused for
    # both the folder name and the mood_test_log.jsonl entry — same
    # value in both places means a screenshot folder can always be
    # matched back to its exact log row with no extra bookkeeping field.
    # Windows forbids ':' in filenames, so this uses a sanitized format,
    # not a raw ISO string.
    run_started_at = datetime.now(timezone.utc)
    timestamp_slug = run_started_at.strftime("%Y%m%dT%H%M%SZ")
    case_dir = SCREENSHOTS_DIR / (case_name or _slugify(task))
    shot_dir = case_dir / timestamp_slug
    shot_dir.mkdir(parents=True, exist_ok=True)
    latest_dir = case_dir / "latest"
    latest_dir.mkdir(parents=True, exist_ok=True)

    baseline_shot = capture_game_view(output_path=str(shot_dir / "baseline.png"))
    shutil.copyfile(baseline_shot.path, latest_dir / "baseline.png")
    print(f"[screenshot] baseline saved: {baseline_shot.path} (+ latest/)")

    feedback = ""  # judge's notes from the previous failed attempt, if any
    attempt_history: list[dict] = []  # every prior attempt's own summary + score, oldest first

    with trace(
        workflow_name="mood_lighting_agent",
        group_id=case_name,  # links repeated runs of the SAME case together in the dashboard
        metadata={"task": task, "case_name": case_name or "adhoc"},
    ) as t:
        print(f"[trace] https://platform.openai.com/traces/trace?trace_id={t.trace_id}")
        for attempt in range(1, MAX_ATTEMPTS + 1):
            prompt_text = f"Current scene objects:\n{get_scene_context()}\n\nTask: {task}"
            if attempt_history:
                history_lines = "\n".join(
                    f"- Attempt {h['attempt']}: you did \u2014 {h['action']} \u2192 judge score {h['score']}/10. "
                    f"Judge said: {h['notes']}"
                    for h in attempt_history
                )
                prompt_text += f"\n\nPrevious attempts this run (oldest first):\n{history_lines}"
                scores = [h["score"] for h in attempt_history]
                if len(scores) >= 2 and scores[-1] <= scores[-2]:
                    prompt_text += (
                        "\n\nNOTE: your score did NOT improve (or got worse) on the last "
                        "attempt despite the change you made. Pushing the same lever "
                        "harder is not working \u2014 try a DIFFERENT lever this time (e.g. if "
                        "you've been adding/intensifying lights, try color grading/vignette/"
                        "fog instead, or vice versa; or change composition \u2014 fewer, more "
                        "deliberate color choices instead of more lights)."
                    )
            if feedback:
                prompt_text += (
                    f"\n\nThe scene just went nearly black/unreadable. {feedback}"
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

            # Guardrail: check the ACTUAL rendered pixels before paying
            # for the judge LLM call. Found live that per-field clamps
            # can't catch this — a compound stack of individually
            # "reasonable" changes (exposure+vignette+fog+lights) can
            # still render to near-black. Code decides this, not an LLM,
            # same split as everywhere else in this project.
            post_attempt_capture = capture_game_view()
            visibility = check_frame_visibility(post_attempt_capture.path)
            if not visibility.visible:
                print(
                    f"[guardrail] frame unreadable after attempt {attempt}/{MAX_ATTEMPTS} "
                    f"(mean_brightness={visibility.mean_brightness}/255, "
                    f"pct_near_black={visibility.pct_near_black}%) — skipping judge call"
                )
                feedback = (
                    f"Your last change made the scene nearly completely black/unreadable "
                    f"(mean brightness {visibility.mean_brightness}/255, "
                    f"{visibility.pct_near_black}% of pixels near-black). This is NOT a valid "
                    "interpretation of any mood — the scene's content must still be visible. "
                    "Pull back exposure/vignette/fog/light intensity until content is visible "
                    "again, then re-apply the mood more moderately — commit to the mood through "
                    "color/contrast/shadow shape, not by erasing the image."
                )
                if attempt == MAX_ATTEMPTS:
                    _log_guardrail_rejection(task, attempt, visibility, case_name, run_started_at)
                    result_shot = capture_game_view(output_path=str(shot_dir / "result.png"))
                    shutil.copyfile(result_shot.path, latest_dir / "result.png")
                    print(f"[screenshot] result saved: {result_shot.path} (+ latest/)")
                    return (
                        f"Gave up after {MAX_ATTEMPTS} attempts. Final attempt was rejected by "
                        f"the visibility guardrail (frame unreadable: "
                        f"mean_brightness={visibility.mean_brightness}/255)."
                    )
                continue  # skip the judge entirely, retry without burning that call

            passed, judgement = await judge_mood_match(task)
            feedback = ""  # guardrail message (if any) consumed by this attempt, clear it

            print(
                f"[attempt {attempt}/{MAX_ATTEMPTS}] agent: {result.final_output} | "
                f"judge score={judgement.mood_match_score} passed={passed}"
            )

            if passed:
                _log_result(task, attempt, True, judgement, case_name, run_started_at)
                result_shot = capture_game_view(output_path=str(shot_dir / "result.png"))
                shutil.copyfile(result_shot.path, latest_dir / "result.png")
                print(f"[screenshot] result saved: {result_shot.path} (+ latest/)")
                return f"Success on attempt {attempt}: {judgement.reasoning}"

            attempt_history.append(
                {
                    "attempt": attempt,
                    "action": result.final_output,
                    "score": judgement.mood_match_score,
                    "notes": judgement.reasoning,
                }
            )
            if attempt == MAX_ATTEMPTS:
                _log_result(task, attempt, False, judgement, case_name, run_started_at)
                result_shot = capture_game_view(output_path=str(shot_dir / "result.png"))
                shutil.copyfile(result_shot.path, latest_dir / "result.png")
                print(f"[screenshot] result saved: {result_shot.path} (+ latest/)")
                return f"Gave up after {MAX_ATTEMPTS} attempts. Last judge score={judgement.mood_match_score}: {judgement.reasoning}"

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
