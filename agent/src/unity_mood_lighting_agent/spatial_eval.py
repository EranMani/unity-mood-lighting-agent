"""
spatial_eval.py — isolated spatial-reasoning diagnostic, NOT part of the
mood eval suite's pass/fail tally (see docs/mood-test-results.md,
2026-11-24: "kept separate ... since it tests an entirely different
capability and shouldn't blur two unrelated numbers together").

Prerequisite question before redesigning main.py's attempt loop into
phases (Eran's framing): does the model have genuine spatial reasoning
capability at all — given the scene's bounding box, object positions,
and a camera image — or is it only reciting lighting theory vocabulary
without being able to execute it as real tool calls? A dedicated MINIMAL
agent is used here (not the mood-lighting agent) specifically to
isolate this — reusing the full mood agent would leave genuine ambiguity
about whether a bad result means "no spatial skill" or "the archetype/
color/ambient instructions are drowning it out."

Every check here is deterministic (real pixels/real transforms, no LLM
judge) EXCEPT the one place that's inherently language: whether the
agent's stated REASONING actually matches the real geometry it produced.
That one narrow check uses a tiny separate structured call, not a
holistic quality judge like judge.py's MoodJudgement.
"""

import asyncio
import json
import math
from pathlib import Path

from agents import Agent, Runner
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from unity_mood_lighting_agent.tools import aim_light_at, set_object_transform
from unity_mood_lighting_agent.unity_bridge import (
    capture_game_view,
    check_rotation_aims_at_geometry,
    ensure_scene_ready,
    get_scene_bounds,
    image_to_data_url,
    list_scene_transforms,
    open_scene,
    restore_scene_baseline,
)

load_dotenv()

SCENE_PATH = "Assets/room/Cosmic_Retro_MessHall_Props_FREE/Demo_Scene/Cosmic_Retro_Mesa_Props_Free.unity"

# 4 target objects spanning different real positions in the room — chosen
# so the cross-case differentiation check (section 4 below) actually means
# something: a lazy "same spot every time" strategy must fail against at
# least some of these.
TARGET_OBJECTS = [
    "Cosmic_retro_mesa_arcade_machine_games",  # corner, near a wall
    "Cosmic_retro_mesa_table_small_square",  # central to the room
    "Cosmic_retro_mesa_bed_simple",  # opposite wall from the arcade machine
    "Cosmic_retro_mesa_vendor_snack",  # a third, distinct wall
]

MAX_REASONABLE_DISTANCE_FRACTION = 0.5  # of scene diagonal — catches "picked a spot nowhere near the target"
MIN_REASONABLE_DISTANCE = 0.3  # world units — catches "clipped inside the target's own geometry"


class SpatialDecision(BaseModel):
    """Structured output for the minimal spatial agent. reasoning FIRST,
    same reasoning-conditions-the-answer technique used everywhere else
    in this project (judge.py, agent.py's LightingDecision)."""

    reasoning: str = Field(
        description="Explain WHY you chose this exact position and rotation for the light — "
        "reference the real target object's position/size and the room's bounds, concretely."
    )
    light_used: str = Field(description="instance_id of the light you moved/aimed.")
    target_object: str = Field(description="instance_id of the object you aimed the light at.")


spatial_agent = Agent(
    name="SpatialPlacementAgent",
    instructions=(
        "You are given a Unity scene's real bounding box, every object's "
        "name/instance_id/position, and a camera screenshot. Your ONLY "
        "job: pick one of the scene's EXISTING lights, reposition it "
        "(set_object_transform) and aim it (aim_light_at) at the stated "
        "target object, so it would create a dramatic rim/key light on "
        "that object — a real light source near the object with a "
        "plausible angle, not clipped inside the object's own geometry "
        "and not left wherever it originally sat. Use the real "
        "coordinates you were given to reason about distance and "
        "direction, don't guess. This task is ONLY about light "
        "position/rotation — do not touch intensity, color, or any "
        "post-processing."
    ),
    model="gpt-5.4-mini",
    output_type=SpatialDecision,
    tools=[set_object_transform, aim_light_at],
)


class ConsistencyCheck(BaseModel):
    """Narrow, factual check — NOT a holistic quality judge. Given the
    REAL computed geometry and the agent's own stated reasoning, does the
    text actually describe what really happened? Kept deliberately small
    in scope: this is a language-grounding check, not an aesthetic one."""

    consistent: bool = Field(description="True if the reasoning text accurately describes the real position/distance/direction relationship below.")
    note: str = Field(description="One sentence: what matches or what's fabricated/wrong.")


consistency_agent = Agent(
    name="SpatialReasoningConsistencyChecker",
    instructions=(
        "You will be given: (1) real computed facts about a light's final "
        "position relative to a target object (distance, direction), and "
        "(2) the agent's own stated reasoning for why it chose that "
        "position. Check ONLY whether the reasoning text is factually "
        "consistent with the real numbers — not whether the placement "
        "itself was a good creative choice, not style, just factual "
        "grounding. A reasoning that invents a distance/direction "
        "contradicting the real numbers is NOT consistent."
    ),
    model="gpt-5.4-mini",
    output_type=ConsistencyCheck,
)


def _build_scene_context() -> str:
    """Same spatial data agent.py's get_scene_context() feeds the mood
    agent, WITHOUT any mood/post-processing content — this agent's task
    has nothing to do with color grading, ambient, or archetypes."""
    scene = list_scene_transforms()
    bounds = get_scene_bounds()
    lines = [
        f"- {o.name} (instance_id={o.instance_id}, is_light={o.is_light}): "
        f"pos=({o.pos_x:.2f}, {o.pos_y:.2f}, {o.pos_z:.2f}), "
        f"rot=({o.rot_x:.1f}, {o.rot_y:.1f}, {o.rot_z:.1f})"
        for o in scene
    ]
    return (
        "Scene objects:\n" + "\n".join(lines) + "\n\n"
        f"Scene bounding box: x [{bounds.min_x:.1f}, {bounds.max_x:.1f}], "
        f"y [{bounds.min_y:.1f}, {bounds.max_y:.1f}], "
        f"z [{bounds.min_z:.1f}, {bounds.max_z:.1f}], diagonal={bounds.diagonal:.1f}"
    )


def _dist(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


async def run_case(target_name: str) -> dict:
    open_scene(SCENE_PATH)
    restore_scene_baseline(SCENE_PATH)
    ensure_scene_ready(SCENE_PATH)

    before = {o.instance_id: (o.pos_x, o.pos_y, o.pos_z) for o in list_scene_transforms() if o.is_light}

    scene_context = _build_scene_context()
    capture = capture_game_view()
    image_url = image_to_data_url(capture.path)
    prompt = [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": f"{scene_context}\n\nTarget object: {target_name}. Position and aim a light on it."},
                {"type": "input_image", "image_url": image_url},
            ],
        }
    ]
    result = await Runner.run(spatial_agent, prompt)
    decision: SpatialDecision = result.final_output

    after = list_scene_transforms()
    target_obj = next((o for o in after if o.name == target_name or o.instance_id == target_name), None)
    moved_light = None
    for o in after:
        if not o.is_light:
            continue
        before_pos = before.get(o.instance_id)
        after_pos = (o.pos_x, o.pos_y, o.pos_z)
        if before_pos is not None and _dist(before_pos, after_pos) > 0.01:
            moved_light = o
            break
    if moved_light is None:
        # Fell back to whatever light_used claims, in case the move was tiny
        moved_light = next((o for o in after if o.is_light and (o.instance_id == decision.light_used or o.name == decision.light_used)), None)

    bounds = get_scene_bounds()

    case_result = {
        "target": target_name,
        "reasoning": decision.reasoning,
        "moved_a_light": moved_light is not None,
    }

    if moved_light is None or target_obj is None:
        case_result.update({"error": "could not identify moved light or target object"})
        return case_result

    light_pos = (moved_light.pos_x, moved_light.pos_y, moved_light.pos_z)
    target_pos = (target_obj.pos_x, target_obj.pos_y, target_obj.pos_z)
    distance = _dist(light_pos, target_pos)

    in_bounds = (
        bounds.min_x <= light_pos[0] <= bounds.max_x
        and bounds.min_y <= light_pos[1] <= bounds.max_y
        and bounds.min_z <= light_pos[2] <= bounds.max_z
    )

    raycast = check_rotation_aims_at_geometry(
        position=light_pos,
        rotation=(moved_light.rot_x, moved_light.rot_y, moved_light.rot_z),
        self_id=moved_light.instance_id,
        max_distance=bounds.diagonal,
    )
    aims_at_target = raycast.hit and raycast.hit_name == target_obj.name

    max_reasonable = bounds.diagonal * MAX_REASONABLE_DISTANCE_FRACTION
    distance_sane = MIN_REASONABLE_DISTANCE <= distance <= max_reasonable

    case_result.update(
        {
            "light_position": light_pos,
            "light_rotation": (moved_light.rot_x, moved_light.rot_y, moved_light.rot_z),
            "target_position": target_pos,
            "distance_to_target": round(distance, 2),
            "in_bounds": in_bounds,
            "aims_at_target": aims_at_target,
            "raycast_hit_name": raycast.hit_name,
            "distance_sane": distance_sane,
            "deterministic_pass": in_bounds and aims_at_target and distance_sane,
        }
    )
    return case_result


async def check_consistency(case_result: dict) -> dict:
    if "error" in case_result or not case_result.get("moved_a_light"):
        return {"consistent": None, "note": "skipped — no valid placement to check"}
    facts = (
        f"Target object: {case_result['target']} at {case_result['target_position']}.\n"
        f"Light's final position: {case_result['light_position']}.\n"
        f"Real distance from light to target: {case_result['distance_to_target']} units.\n"
        f"Light's rotation actually hits (raycast): {case_result['raycast_hit_name']}.\n\n"
        f"Agent's stated reasoning: {case_result['reasoning']}"
    )
    result = await Runner.run(consistency_agent, facts)
    check: ConsistencyCheck = result.final_output
    return {"consistent": check.consistent, "note": check.note}


async def main():
    results = []
    for target in TARGET_OBJECTS:
        print(f"\n=== Spatial case: {target} ===")
        case = await run_case(target)
        print(json.dumps(case, indent=2, default=str))
        consistency = await check_consistency(case)
        case["reasoning_consistent"] = consistency["consistent"]
        case["reasoning_note"] = consistency["note"]
        print(f"[consistency] {consistency}")
        results.append(case)

    # Cross-case differentiation: are the chosen positions actually
    # different, or the same lazy spot regardless of target? The exact
    # failure mode this test exists to catch (see mood-test-results.md).
    positions = [r["light_position"] for r in results if "light_position" in r]
    pairwise_distances = [
        _dist(positions[i], positions[j])
        for i in range(len(positions))
        for j in range(i + 1, len(positions))
    ]
    min_pairwise = min(pairwise_distances) if pairwise_distances else 0.0

    n_pass = sum(1 for r in results if r.get("deterministic_pass"))
    n_consistent = sum(1 for r in results if r.get("reasoning_consistent"))
    print("\n=== Spatial eval summary ===")
    for r in results:
        status = "PASS" if r.get("deterministic_pass") else "FAIL"
        print(f"{r['target']:45s} {status}  dist={r.get('distance_to_target')}  consistent={r.get('reasoning_consistent')}")
    print(f"\nDeterministic placement: {n_pass}/{len(results)} passed")
    print(f"Reasoning consistency:   {n_consistent}/{len(results)} consistent")
    print(f"Min pairwise distance across all chosen positions: {min_pairwise:.2f} "
          f"({'DIFFERENTIATED — not a repeated lazy spot' if min_pairwise > 0.5 else 'WARNING: positions suspiciously similar across different targets'})")

    log_path = Path(__file__).resolve().parents[3] / "spatial_eval_log.jsonl"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"results": results, "min_pairwise_distance": min_pairwise}, default=str) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
