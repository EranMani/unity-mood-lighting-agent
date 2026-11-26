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
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from agents import Runner, trace
from dotenv import load_dotenv

from unity_mood_lighting_agent.agent import LightingDecision, Lever, agent, get_scene_context
from unity_mood_lighting_agent.judge import judge_mood_match
from unity_mood_lighting_agent.spatial_agent import ensure_spatial_breakdown, load_cached_spatial_breakdown
from unity_mood_lighting_agent.tools import cleanup_agent_lights
from unity_mood_lighting_agent.unity_bridge import (
    CONTRAST_SPREAD_FLOOR,
    P10_CEILING,
    capture_game_view,
    capture_scene_baseline,
    check_frame_contrast,
    check_frame_visibility,
    ensure_scene_ready,
    get_active_scene,
    get_ambient,
    get_baseline_brightness,
    get_color_adjustments,
    get_fog,
    get_light_properties,
    get_skybox,
    get_vignette,
    image_to_data_url,
    list_scene_transforms,
    open_scene,
    restore_scene_baseline,
)

load_dotenv()

MAX_ATTEMPTS = int(os.environ.get("MAX_ATTEMPTS_DIAGNOSTIC_OVERRIDE", 3))  # permanent default stays 3; override is a one-off diagnostic knob, not a config to leave set
REPO_ROOT = Path(__file__).resolve().parents[3]
LOG_PATH = REPO_ROOT / "mood_test_log.jsonl"

# Minimum fraction the attempt's own rendered p90 must exceed the
# scene's untouched baseline p90 by, for high-contrast moods only
# (2026-11-25, Eran's call). Found live: a horror attempt scored 4/10
# as "underexposed... reads like dimmed, not deliberately lit" while
# STILL passing the existing CONTRAST_SPREAD_FLOOR/P10_CEILING check
# (spread + dark-zone darkness were both fine) — measured its own p90
# at 44 against baseline p90=112, i.e. the "dominant key light" never
# actually got brighter than the room's own unlit ambient highlight.
# Spread/p10 catch "too flat" and "not dark enough"; neither catches
# "the supposedly dominant light never actually dominates," which is
# a third, independent failure mode. 1.05 (5% over baseline) is
# deliberately loose — this only needs to catch a key light that's
# net LOWER than or barely at the unlit baseline, not referee exact
# brightness taste.
#
# RECALIBRATED 2026-11-26, same camera-fix aftermath as the other two
# pixel-stat guardrails: after the camera fix, baseline p90 jumped to
# 145 (from 112), and EVERY confirmed-legible, genuinely good
# high-contrast eval result measured nowhere close to even the OLD
# ratio's new requirement (152.2) — horror p90=10, eerie_lab p90=3,
# noir p90=15, post_apocalyptic p90=24, all visually confirmed good.
# Root cause, deeper than a stale number: whole-frame p90 requires 10%
# of ALL pixels to be that bright — a tight, contained dramatic key
# light's pool (by design, covering a small fraction of the frame)
# essentially never moves a 90th-percentile statistic computed over the
# WHOLE frame, even when it's exactly the right, convincing look. Same
# "percentile stats can't see small salient highlights" limitation as
# CONTRAST_SPREAD_FLOOR and the visibility floor. 1.05 would reject
# every real good example by a wide margin, not a close one. Dropped to
# 0.15 (15% of baseline p90), clearing all 4 real confirmed-good
# examples' ratios (0.03-0.17) with the single highest (0.17,
# post_apocalyptic) landing just above it — still catches a key light
# that did essentially nothing (near-zero p90), but no longer vetoes
# legitimately contained, convincing lighting. A real fix (comparing
# brightness within the key light's own intended pool/ROI rather than
# the whole frame) would be more principled than any whole-frame
# percentile ratio — flagged for a future session, not solved here.
KEY_LIGHT_P90_LIFT_FLOOR = 0.15


def _snapshot_lever_state() -> dict:
    """Real scene-state snapshot for deterministic lever-usage diffing
    (2026-11-25, Eran's call) — we no longer trust the agent's own
    self-reported lever_accounting alone, since its changes_summary has
    been caught diverging from reality before (see docs/mood-test-
    results.md). Captures everything a Lever category could touch."""
    lights = {}
    for o in list_scene_transforms():
        if not o.is_light:
            continue
        lp = get_light_properties(o.instance_id)
        lights[o.instance_id] = {
            "pos": (round(o.pos_x or 0.0, 3), round(o.pos_y or 0.0, 3), round(o.pos_z or 0.0, 3)),
            "rot": (round(o.rot_x or 0.0, 1), round(o.rot_y or 0.0, 1), round(o.rot_z or 0.0, 1)),
            "intensity": round(lp.intensity, 4),
            "color": (round(lp.color_r or 0.0, 3), round(lp.color_g or 0.0, 3), round(lp.color_b or 0.0, 3)),
            "range": round(lp.range, 3) if lp.range is not None else None,
            "spot_angle": round(lp.spot_angle, 2) if lp.spot_angle is not None else None,
        }
    color = get_color_adjustments()
    vignette = get_vignette()
    fog = get_fog()
    return {
        "lights": lights,
        "ambient": round(get_ambient().intensity, 4),
        "skybox": get_skybox().path,
        "color_adjustments": color.model_dump(),
        "vignette": vignette.model_dump(),
        "fog": fog.model_dump(),
    }


def _diff_levers(before: dict, after: dict) -> set[str]:
    """Which Lever categories genuinely changed between two snapshots —
    pure value comparison, no LLM, no trusting anyone's self-report.
    A newly created light counts as a position/rotation change too
    (2026-11-25, fixed same day it was found live) — placing a brand
    new light IS a spatial decision, it shouldn't need a REDUNDANT
    separate move of an existing light just to satisfy the transform
    guardrail below."""
    changed = set()
    before_lights = before["lights"]
    after_lights = after["lights"]
    all_light_ids = set(before_lights) | set(after_lights)
    for light_id in all_light_ids:
        b = before_lights.get(light_id)
        a = after_lights.get(light_id)
        if b is None:
            changed.add("position")  # a light was created this attempt — its placement IS a spatial decision
            changed.add("rotation")
            continue
        if a is None:
            continue  # a light was deleted this attempt — nothing to diff
        if b["pos"] != a["pos"]:
            changed.add("position")
        if b["rot"] != a["rot"]:
            changed.add("rotation")
        if b["intensity"] != a["intensity"]:
            changed.add("intensity")
        if b["range"] != a["range"] or b["spot_angle"] != a["spot_angle"]:
            changed.add("falloff_range")
        if b["color"] != a["color"]:
            changed.add("color")
    if before["ambient"] != after["ambient"]:
        changed.add("ambient")
    if before["skybox"] != after["skybox"]:
        changed.add("skybox")
    if (
        before["color_adjustments"] != after["color_adjustments"]
        or before["vignette"] != after["vignette"]
        or before["fog"] != after["fog"]
    ):
        changed.add("global_grading")
    return changed


GRADING_SEVERITY_FLOOR = 3.9  # see _grading_severity docstring for calibration


def _grading_severity(snapshot: dict) -> float:
    """Heuristic estimate of how hard the combined post-processing chain
    is being pushed, BEFORE any render/screenshot — pure arithmetic on
    the decision's own numbers, free, and catches a crush before paying
    for a render+vision guardrail call at all (2026-11-25, Eran's call
    on the pipeline-compounding finding).

    Calibrated against exactly ONE measured case on this scene (not a
    validated formula across many scenes — tune the floor if it over/
    under-triggers elsewhere): neutral grading measured mean=38.4;
    post_exposure=-0.35 + contrast=68 + saturation=-28 + a moderate
    color_filter together (severity ~2.5 by this formula) already cut
    it to ~9.9 (74% loss) with NO vignette involved yet; adding
    vignette=0.5 on top (severity ~3.25) crushed it to ~0.4 (near-total
    black). Floor set to 2.6, just above that ~2.5 first-drop point and
    below the ~3.25 full-crush point — deliberately checked against a
    REAL legitimate attempt too (horror attempt 1 on the real baseline,
    the closest-to-passing attempt all session, severity ~1.88 by this
    formula) to avoid false-positiving on a genuinely decent combo.

    RECALIBRATED 2026-11-26 after the camera near-clip-plane fix (see
    docs/unity-lighting-rendering-concepts.md) changed this scene's
    real baseline brightness enough that the 2.6 floor above started
    false-positive rejecting genuinely good eval results: eerie_lab
    (confirmed legible via direct visual check, severity=2.72),
    post_apocalyptic (confirmed legible, severity=2.98), noir
    (confirmed legible, severity=2.81) were all being rejected despite
    looking fine. Re-ran this same empirical crush-point test on the
    now-fixed camera: pushing grading further to severity~4.0 produced
    a genuinely flatter/darker result (mean=2.5, numerically almost
    identical to eerie_lab's good 2.2 — these two pixel stats alone
    can't tell them apart, a real metric limitation, not a tuning
    problem), and severity~5.0 was an unambiguous crush (mean=0.4).
    First pass raised the floor to 3.3 — turned out still too tight: a
    live eval re-run showed the agent's own later-attempt escalations
    landing at severity 3.36-3.65 (naturally pushing harder when an
    earlier attempt's score didn't improve), all BELOW the empirically-
    confirmed ambiguous point (~3.98) and comfortably below the
    confirmed crush point (~5.0) — meaning real attempts were being
    pre-render-rejected without ever finding out if they'd have
    rendered fine. Raised again to 3.9, directly tied to the measured
    ambiguous point rather than a guess, so only attempts in the
    genuinely-likely-to-crush zone get stopped before paying for a
    render. Revisit if a confirmed-crushed frame ever measures below
    3.9 in practice.

    color_adjustments: contrast/50 and |saturation|/50 (both roughly
    0-100 in this project's range) plus |post_exposure| (roughly -2..2)
    plus average color_filter deviation from white, all additive
    because each one is a SEPARATE multiplicative pass in the real
    pipeline (see agent.py's RENDER PIPELINE ORDER instructions) —
    stacking them is what compounds, this sum is a proxy for that."""
    ca = snapshot["color_adjustments"]
    v = snapshot["vignette"]
    color_filter_deviation = (
        abs(1 - ca.get("color_filter_r", 1.0))
        + abs(1 - ca.get("color_filter_g", 1.0))
        + abs(1 - ca.get("color_filter_b", 1.0))
    ) / 3
    return (
        abs(ca.get("post_exposure", 0.0))
        + ca.get("contrast", 0.0) / 50
        + abs(ca.get("saturation", 0.0)) / 50
        + v.get("intensity", 0.0) * 1.5
        + color_filter_deviation
    )


def _light_creation_diff(before: dict, after: dict) -> tuple[set[str], set[str]]:
    """Separate from _diff_levers (2026-11-25, Eran's hypothesis,
    confirmed with real data): light count is its own axis, distinct
    from which PARAMETERS of an existing light changed. Returns
    (created_ids, deleted_ids) — found live that across every attempt in
    2 full eval runs, this was ALWAYS (set(), set()): the agent never
    once called create_light, only ever retuned the scene's original 2
    fixtures, exactly the same narrow-habit pattern as the lever gap."""
    before_ids = set(before["lights"])
    after_ids = set(after["lights"])
    return after_ids - before_ids, before_ids - after_ids


def _describe_lever_diff(before: dict, after: dict) -> str:
    """Human-readable numeric diff for console output (2026-11-25, Eran
    asked to actually SEE the diffs between retries, not just category
    names) — real before -> after values per touched light/setting."""
    lines = []
    before_lights = before["lights"]
    after_lights = after["lights"]
    created, deleted = _light_creation_diff(before, after)
    for light_id in created:
        lines.append(f"    + created light {light_id}: {after_lights[light_id]}")
    for light_id in deleted:
        lines.append(f"    - deleted light {light_id}: {before_lights[light_id]}")
    for light_id in set(before_lights) & set(after_lights):
        b, a = before_lights[light_id], after_lights[light_id]
        field_diffs = [f"{k}: {b[k]} -> {a[k]}" for k in b if b[k] != a[k]]
        if field_diffs:
            lines.append(f"    light {light_id}: " + "; ".join(field_diffs))
    for key in ("ambient", "skybox"):
        if before[key] != after[key]:
            lines.append(f"    {key}: {before[key]} -> {after[key]}")
    for key in ("color_adjustments", "vignette", "fog"):
        b, a = before[key], after[key]
        field_diffs = [f"{k}: {b[k]} -> {a[k]}" for k in b if b.get(k) != a.get(k)]
        if field_diffs:
            lines.append(f"    {key}: " + "; ".join(field_diffs))
    return "\n".join(lines) if lines else "    (no scene-state change detected)"
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
    guardrail_name: str,
    details: dict,
    case_name: str | None = None,
    run_timestamp: datetime | None = None,
) -> None:
    """Separate from _log_result — this is a guardrail catch, not a judge
    score. No MoodJudgement exists here (judge was never called, that's
    the whole point — save the LLM call on a frame with nothing to
    score). guardrail_name/details generalized 2026-11-24 to cover both
    the visibility guardrail (near-black) and the contrast guardrail
    (too flat for a high-contrast mood), same shape, different checks."""
    ts = run_timestamp or datetime.now(timezone.utc)
    entry = {
        "timestamp": ts.isoformat(),
        "case_name": case_name,
        "task": task,
        "attempts_used": attempt,
        "passed": False,
        "guardrail_rejected": guardrail_name,
        **details,
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

    # Deterministic lever-usage tracking (2026-11-25, Eran's call): real
    # scene-state diffs, not the agent's own self-reported lever_accounting
    # — found live that self-reported changes_summary can diverge from
    # reality. prev_lever_snapshot starts as the true restored baseline;
    # levers_touched_this_run accumulates across every attempt and is fed
    # back into the NEXT attempt's prompt so "you've never tried X" is a
    # verified fact, not a guess.
    prev_lever_snapshot = _snapshot_lever_state()
    levers_touched_this_run: set[str] = set()

    # Spatial ground-base (Eran's call, 2026-11-24): create-if-missing,
    # cached per scene — geometry doesn't change between moods or
    # attempts, so this runs the spatial agent AT MOST ONCE per scene,
    # ever. Must happen here (awaited, before any attempt) rather than
    # lazily inside get_scene_context(), which is sync and called fresh
    # every attempt — see spatial_agent.py's module docstring.
    active_scene_path = get_active_scene().path
    spatial_cache_hit = load_cached_spatial_breakdown(active_scene_path) is not None
    spatial_breakdown = await ensure_spatial_breakdown(active_scene_path)
    print(
        f"[spatial] {'cache hit' if spatial_cache_hit else 'computed fresh'} — "
        f"{len(spatial_breakdown.anchors)} anchor(s)"
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
            if attempt == 1:
                prompt_text += (
                    "\n\nFIRST ATTEMPT STRATEGY (Eran's call, 2026-11-25): if this mood calls for "
                    "real drama/high contrast, don't start timid. Push your key light's intensity "
                    "to a deliberately exaggerated, borderline-too-bright peak on this first attempt "
                    "— overshoot on purpose. Pulling back down from too-bright, with real guardrail/"
                    "judge feedback telling you exactly how far, is a far easier search than guessing "
                    "how far to push up from too-dim, which is the failure pattern seen repeatedly "
                    "when attempts started conservative and either stayed timid or overcorrected into "
                    "near-black much later. This does not apply to soft/diffuse moods where a gentle "
                    "intensity genuinely is the right choice."
                )
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
                prompt_text += f"\n\n{feedback}"
            if levers_touched_this_run:
                never_touched = sorted({lv.value for lv in Lever} - levers_touched_this_run)
                prompt_text += (
                    f"\n\nVERIFIED lever usage so far this run (from real scene-state diffs, "
                    f"NOT self-report — your own lever_accounting has been caught diverging from "
                    f"reality before): touched = {sorted(levers_touched_this_run)}."
                )
                if never_touched:
                    prompt_text += (
                        f" NEVER touched this run = {never_touched}. If your score hasn't been "
                        "clearly improving, strongly consider one of these — a lever you haven't "
                        "tried yet is a real, unused option, not evidence it wouldn't help."
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
            decision: LightingDecision = result.final_output

            # Debug visibility: print what the agent actually did to every
            # LIGHT this attempt, BEFORE any guardrail can skip the rest of
            # the loop — previously this only printed after a guardrail
            # pass, so a rejected attempt's actual light values were
            # invisible in the logs, impossible to tell "did it even try
            # to dim the other lights" from "it tried and still failed."
            print(
                f"[attempt {attempt}/{MAX_ATTEMPTS}] agent archetype="
                f"{decision.mood_breakdown.strategy_archetype.value} "
                f"genre={decision.mood_breakdown.genre} "
                f"target_contrast={decision.mood_breakdown.target_contrast.value} "
                f"changes={decision.changes_summary}"
            )
            for o in list_scene_transforms():
                if o.is_light:
                    lp = get_light_properties(o.instance_id)
                    print(
                        f"  [light] {o.name}: intensity={lp.intensity} range={lp.range} "
                        f"shadow_type={lp.shadow_type} color=({lp.color_r:.2f},{lp.color_g:.2f},{lp.color_b:.2f})"
                    )

            # Deterministic lever-usage diff, same scene-reads as above —
            # independent of decision.lever_accounting's self-report.
            new_lever_snapshot = _snapshot_lever_state()
            attempt_levers = _diff_levers(prev_lever_snapshot, new_lever_snapshot)
            created_lights, deleted_lights = _light_creation_diff(prev_lever_snapshot, new_lever_snapshot)
            print(f"  [diff]\n{_describe_lever_diff(prev_lever_snapshot, new_lever_snapshot)}")
            levers_touched_this_run |= attempt_levers
            prev_lever_snapshot = new_lever_snapshot
            self_reported = {lu.lever.value for lu in decision.lever_accounting if lu.changed}
            mismatch = self_reported ^ attempt_levers
            print(
                f"  [levers] verified_changed={sorted(attempt_levers)} "
                f"self_reported_changed={sorted(self_reported)}"
                + (f" MISMATCH={sorted(mismatch)}" if mismatch else "")
            )

            # Pre-render grading-severity guardrail (2026-11-25, Eran's
            # call) — pure arithmetic on the values just diffed above, no
            # render/screenshot cost at all, catches a likely crush
            # before paying for ANY image capture or judge call. Direct
            # response to a live finding: compounding post-processing
            # (not undershooting lights) was what actually crushed
            # several attempts to full black this session.
            severity = _grading_severity(new_lever_snapshot)
            print(f"  [grading] severity={severity:.2f} (floor={GRADING_SEVERITY_FLOOR})")
            if severity >= GRADING_SEVERITY_FLOOR:
                print(
                    f"[guardrail] attempt {attempt}/{MAX_ATTEMPTS} grading severity "
                    f"{severity:.2f} >= floor {GRADING_SEVERITY_FLOOR} — rejected before "
                    "any render/judge call"
                )
                feedback = (
                    f"Your last attempt's combined post-processing (post_exposure, contrast, "
                    f"saturation, color_filter, vignette) scored a severity of {severity:.2f} on a "
                    f"scale where this scene has been measured to crush to near-total-black once "
                    f"combined severity passes roughly this range — even though no single value was "
                    "individually extreme. These stack MULTIPLICATIVELY (each stage transforms the "
                    "previous stage's already-darkened output), not additively. Pull back grading "
                    "significantly — if you need more drama, get it from light placement/intensity "
                    "instead, grading should be a light-touch finishing pass, not the primary "
                    "dramatic mechanism."
                )
                if attempt == MAX_ATTEMPTS:
                    _log_guardrail_rejection(
                        task, attempt, "grading_severity", {"severity": severity}, case_name, run_started_at,
                    )
                    result_shot = capture_game_view(output_path=str(shot_dir / "result.png"))
                    shutil.copyfile(result_shot.path, latest_dir / "result.png")
                    print(f"[screenshot] result saved: {result_shot.path} (+ latest/)")
                    return (
                        f"Gave up after {MAX_ATTEMPTS} attempts. Final attempt was rejected: "
                        f"grading severity {severity:.2f} too high (likely crush)."
                    )
                continue  # skip render/judge entirely, retry without burning either cost

            # Hard guardrail (2026-11-25, Eran's explicit call: "its a
            # must", not a stronger-worded prompt) — require a REAL
            # transform change every attempt, verified from the diff
            # above, not the agent's own say-so. Direct response to a
            # 5-attempt diagnostic that found the agent never once
            # touched position/rotation on its own, no matter how many
            # times prose told it to try something different.
            if "position" not in attempt_levers and "rotation" not in attempt_levers:
                print(
                    f"[guardrail] attempt {attempt}/{MAX_ATTEMPTS} changed no light's position or "
                    "rotation — rejected before judge call"
                )
                feedback = (
                    "Your last attempt did not move or rotate a single light (verified from real "
                    "scene state, not your own report) — this is now a hard requirement, not optional. "
                    "You MUST change at least one light's position or rotation this attempt, in "
                    "addition to whatever else you do. If the existing fixtures' positions genuinely "
                    "can't serve this mood, create_light/create_light_near a NEW light exactly where "
                    "the mood needs one instead of only retuning what's already there."
                )
                if attempt == MAX_ATTEMPTS:
                    _log_guardrail_rejection(
                        task, attempt, "no_transform_change", {}, case_name, run_started_at,
                    )
                    result_shot = capture_game_view(output_path=str(shot_dir / "result.png"))
                    shutil.copyfile(result_shot.path, latest_dir / "result.png")
                    print(f"[screenshot] result saved: {result_shot.path} (+ latest/)")
                    return (
                        f"Gave up after {MAX_ATTEMPTS} attempts. Final attempt was rejected: "
                        "no light position/rotation was ever changed."
                    )
                continue  # skip the judge entirely, retry without burning that call

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
                    _log_guardrail_rejection(
                        task, attempt, "visibility",
                        {"mean_brightness": visibility.mean_brightness, "pct_near_black": visibility.pct_near_black},
                        case_name, run_started_at,
                    )
                    # Save the EXACT frame the guardrail just scored (not a
                    # fresh re-capture — 2026-11-25 fix, see judge.py docstring).
                    shutil.copyfile(post_attempt_capture.path, shot_dir / "result.png")
                    shutil.copyfile(post_attempt_capture.path, latest_dir / "result.png")
                    print(f"[screenshot] result saved: {post_attempt_capture.path} (+ latest/)")
                    return (
                        f"Gave up after {MAX_ATTEMPTS} attempts. Final attempt was rejected by "
                        f"the visibility guardrail (frame unreadable: "
                        f"mean_brightness={visibility.mean_brightness}/255)."
                    )
                continue  # skip the judge entirely, retry without burning that call

            # Second deterministic guardrail, the OPPOSITE failure mode:
            # a frame that's visible (not near-black) but still flat/
            # uniform, no real brightness spread between a lit zone and a
            # dark zone. Only meaningful for moods that actually call for
            # high contrast — gated on the agent's own target_contrast,
            # never applied to soft_ambient/low-contrast moods where flat
            # IS the correct result. Calibrated against real reference
            # images, see check_frame_contrast()'s docstring.
            if decision.mood_breakdown.target_contrast.value == "high":
                contrast = check_frame_contrast(post_attempt_capture.path)
                if not contrast.has_real_contrast:
                    spread_ok = contrast.spread >= CONTRAST_SPREAD_FLOOR
                    p10_ok = contrast.p10 <= P10_CEILING
                    print(
                        f"[guardrail] frame failed contrast check after attempt "
                        f"{attempt}/{MAX_ATTEMPTS} (p10={contrast.p10}, p90={contrast.p90}, "
                        f"spread={contrast.spread}, spread_floor={CONTRAST_SPREAD_FLOOR}, "
                        f"p10_ceiling={P10_CEILING}) — skipping judge call"
                    )
                    if not spread_ok:
                        feedback = (
                            f"Your last change produced a frame with brightness spread={contrast.spread} "
                            f"(p10={contrast.p10}, p90={contrast.p90}/255) — too flat for a high-contrast "
                            f"mood, which needs at least {CONTRAST_SPREAD_FLOOR} spread between its darkest "
                            "and brightest zones. This usually means no single light is genuinely dominant "
                            "(push ONE light's intensity clearly above the room's baseline and shrink its "
                            "range to a tight pool) or global grading is flattening the differential the "
                            "lights created (ease off post_exposure/contrast/vignette/fog and let the light "
                            "itself create the contrast)."
                        )
                    else:
                        feedback = (
                            f"Your last change has a wide brightness spread ({contrast.spread}) but its "
                            f"darkest zone (p10={contrast.p10}/255) still isn't actually dark enough — a "
                            f"high-contrast mood needs its dark zone at or below {P10_CEILING}/255. A wide "
                            "spread from a generally bright, evenly-lit room with natural material variance "
                            "is NOT the same as real dramatic falloff. Pull back the OTHER lights' intensity/"
                            "range much further (near-off, not just dimmer) so large areas of the frame are "
                            "genuinely near-black, not just dimmer than your key light."
                        )
                    if attempt == MAX_ATTEMPTS:
                        _log_guardrail_rejection(
                            task, attempt, "contrast",
                            {"p10": contrast.p10, "p90": contrast.p90, "spread": contrast.spread},
                            case_name, run_started_at,
                        )
                        shutil.copyfile(post_attempt_capture.path, shot_dir / "result.png")
                        shutil.copyfile(post_attempt_capture.path, latest_dir / "result.png")
                        print(f"[screenshot] result saved: {post_attempt_capture.path} (+ latest/)")
                        return (
                            f"Gave up after {MAX_ATTEMPTS} attempts. Final attempt was rejected by "
                            f"the contrast guardrail (too flat for a high-contrast mood: spread="
                            f"{contrast.spread}, needed {CONTRAST_SPREAD_FLOOR}+)."
                        )
                    continue  # skip the judge entirely, retry without burning that call

                # Third deterministic guardrail, independent of the one
                # above (2026-11-25, found live): has_real_contrast can
                # be True — a real spread AND a genuinely dark zone —
                # while the "dominant key light" still never got
                # brighter than the room's own UNTOUCHED baseline. The
                # case that caught this: p10=3.0, p90=44.0, spread=41.0
                # (has_real_contrast=True, sailed through the check
                # above) against baseline p90=112.0 — the bright zone
                # was still dimmer than the unlit room, which is exactly
                # the "underexposed/dimmed, not deliberately lit"
                # complaint the judge gave it. Only runs when the check
                # above already passed (has_real_contrast was True);
                # if it failed, that guardrail already rejected/fed
                # back and we never reach here.
                baseline_brightness = get_baseline_brightness()
                if baseline_brightness is not None:
                    required_p90 = baseline_brightness.p90 * KEY_LIGHT_P90_LIFT_FLOOR
                    if contrast.p90 < required_p90:
                        print(
                            f"[guardrail] attempt {attempt}/{MAX_ATTEMPTS} key light never exceeded "
                            f"baseline brightness (p90={contrast.p90} < required {required_p90:.1f}, "
                            f"baseline_p90={baseline_brightness.p90}) — skipping judge call"
                        )
                        feedback = (
                            f"Your last change has real spread/darkness (p10={contrast.p10}, "
                            f"spread={contrast.spread}), but its BRIGHT zone (p90={contrast.p90}/255) "
                            f"never actually got brighter than this scene's own UNTOUCHED baseline "
                            f"(p90={baseline_brightness.p90}/255, {required_p90:.1f} required). A key light "
                            "that's supposedly 'dominant' but dimmer than the room's own unlit highlight "
                            "reads as 'the scene got dimmed', not 'a dramatic light was added' — this is "
                            "the exact failure a judge will call underexposed/flat. Push your key light's "
                            "intensity and/or narrow its range further so it genuinely outshines the "
                            "baseline in its own pool, and check whether global grading (post_exposure/"
                            "contrast/vignette) is eating the gain the light created."
                        )
                        if attempt == MAX_ATTEMPTS:
                            _log_guardrail_rejection(
                                task, attempt, "key_light_p90_lift",
                                {"p90": contrast.p90, "baseline_p90": baseline_brightness.p90, "required_p90": required_p90},
                                case_name, run_started_at,
                            )
                            shutil.copyfile(post_attempt_capture.path, shot_dir / "result.png")
                            shutil.copyfile(post_attempt_capture.path, latest_dir / "result.png")
                            print(f"[screenshot] result saved: {post_attempt_capture.path} (+ latest/)")
                            return (
                                f"Gave up after {MAX_ATTEMPTS} attempts. Final attempt was rejected: "
                                f"key light never exceeded baseline brightness (p90={contrast.p90}, "
                                f"needed {required_p90:.1f})."
                            )
                        continue  # skip the judge entirely, retry without burning that call

            passed, judgement = await judge_mood_match(task, image_path=post_attempt_capture.path)
            feedback = ""  # guardrail message (if any) consumed by this attempt, clear it

            print(
                f"[attempt {attempt}/{MAX_ATTEMPTS}] agent archetype={decision.mood_breakdown.strategy_archetype.value} "
                f"genre={decision.mood_breakdown.genre!r} "
                f"contrast={decision.mood_breakdown.target_contrast.value} "
                f"changes={decision.changes_summary} | "
                f"judge score={judgement.mood_match_score} passed={passed}"
            )

            if passed:
                _log_result(task, attempt, True, judgement, case_name, run_started_at)
                shutil.copyfile(post_attempt_capture.path, shot_dir / "result.png")
                shutil.copyfile(post_attempt_capture.path, latest_dir / "result.png")
                print(f"[screenshot] result saved: {post_attempt_capture.path} (+ latest/)")
                return f"Success on attempt {attempt}: {judgement.reasoning}"

            attempt_history.append(
                {
                    "attempt": attempt,
                    "action": decision.changes_summary,
                    "score": judgement.mood_match_score,
                    "notes": judgement.reasoning,
                }
            )
            if attempt == MAX_ATTEMPTS:
                _log_result(task, attempt, False, judgement, case_name, run_started_at)
                shutil.copyfile(post_attempt_capture.path, shot_dir / "result.png")
                shutil.copyfile(post_attempt_capture.path, latest_dir / "result.png")
                print(f"[screenshot] result saved: {post_attempt_capture.path} (+ latest/)")
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
