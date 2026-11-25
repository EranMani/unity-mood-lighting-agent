"""
spatial_agent.py — the scene's spatial "ground base," Eran's architecture
call (2026-11-24): a dedicated agent that analyzes a scene's geometry
ONCE and produces a reusable menu of good lighting-anchor candidates,
separate from the lighting agent that decides what mood-specific
technique to apply at each one.

Deliberately MOOD-BLIND (a design pushback this project settled on
before building this): this agent never sees the user's mood query. It
only reasons about geometry — which objects are compact/isolated (good
single dramatic highlights) vs large/central (good broad fill
candidates) vs near a wall (good rim/side-light candidates). Mixing
mood judgment in here would duplicate the archetype/contrast-target
reasoning agent.py's LightingDecision already owns, and would make this
NOT cacheable per-scene (every mood would need its own spatial call,
defeating the entire point of a one-time "ground base").

Cached per scene, same pattern as unity_bridge.py's scene_baselines:
computed once, reused across every mood and every attempt. NO tools —
this is pure analysis, it never moves anything, so it's a single cheap
call, not a multi-turn tool loop. The lighting agent still owns all
actual tool calls (set_object_transform/aim_light_at/set_light_
properties) and full creative freedom to deviate from these
suggestions — this is advisory context, like a richer get_scene_context(),
not a replacement for the lighting agent's own judgment.

Sequencing note (important, sync/async split): ensure_spatial_breakdown()
is ASYNC (it may call the LLM on a cache miss) and must be awaited ONCE
near the top of main.py's run(), before the attempt loop starts. Reading
it back inside the per-attempt loop goes through
load_cached_spatial_breakdown() instead — a plain SYNC disk read, never
an agent call — so it can live inside agent.py's (sync) get_scene_context()
without needing a nested event loop. By the time any attempt runs, the
cache is guaranteed to already exist on disk.
"""

import json
import os

from agents import Agent, Runner
from pydantic import BaseModel, Field

from unity_mood_lighting_agent.unity_bridge import (
    capture_game_view,
    get_scene_bounds,
    image_to_data_url,
    list_scene_transforms,
)

_SPATIAL_DIR = os.path.join(os.path.dirname(__file__), "data", "spatial_breakdowns")


def _spatial_path_for_scene(scene_path: str) -> str:
    """Same safe-filename convention as unity_bridge._baseline_path_for_scene."""
    safe_name = "".join(c if c.isalnum() else "_" for c in scene_path)
    return os.path.join(_SPATIAL_DIR, f"{safe_name}.json")


class SpatialAnchor(BaseModel):
    """One candidate lighting anchor point — purely geometric traits,
    no mood language at all. The lighting agent cross-references this
    with its own mood/archetype knowledge to pick which anchor and
    which technique actually fits the requested mood."""

    anchor_object: str = Field(description="instance_id of the scene object this anchor is based on.")
    anchor_name: str = Field(description="Human-readable name of the anchor object, for readability in logs/prompts.")
    traits: str = Field(
        description="Geometric traits only, no mood words: is it compact/isolated (good single "
        "dramatic highlight) or large/central (good broad fill) or near a wall/corner (good "
        "rim/side-light)? Roughly how much open space surrounds it for a light to sit in."
    )
    suggested_light_position_x: float = Field(description="World-space X where a light could plausibly sit near this anchor, outside its own geometry.")
    suggested_light_position_y: float = Field(description="World-space Y where a light could plausibly sit near this anchor, outside its own geometry.")
    suggested_light_position_z: float = Field(description="World-space Z where a light could plausibly sit near this anchor, outside its own geometry.")


class SpatialBreakdown(BaseModel):
    """Structured output for the spatial agent. reasoning FIRST, same
    technique used everywhere else in this project (judge.py,
    agent.py's LightingDecision)."""

    reasoning: str = Field(description="Your overall read of the room's layout and spatial opportunities, before listing anchors.")
    anchors: list[SpatialAnchor] = Field(description="3-6 candidate lighting anchors spanning DIFFERENT parts of the room, not clustered together.")


spatial_agent = Agent(
    name="SpatialGroundBaseAgent",
    instructions=(
        "You are given a Unity scene's real bounding box, every object's "
        "name/instance_id/position, and a camera screenshot. Your ONLY "
        "job is spatial analysis — you have NO tools, you never move "
        "anything. Identify 3-6 good candidate anchor points for FUTURE "
        "lighting decisions, spanning DIFFERENT parts of the room (not "
        "all clustered in one corner). For each, describe its geometric "
        "traits only — compact/isolated vs large/central vs near a wall "
        "— and propose one concrete, real-coordinate position near it "
        "where a light could sit without clipping into its geometry. "
        "Do NOT mention or reason about mood, color, or atmosphere at "
        "all — this analysis must stay reusable across every mood a "
        "future user might ask for, not tailored to any one of them."
    ),
    model="gpt-5.4-mini",
    output_type=SpatialBreakdown,
)


def load_cached_spatial_breakdown(scene_path: str) -> SpatialBreakdown | None:
    """Pure sync disk read, NEVER calls the agent — safe to call from
    inside agent.py's sync get_scene_context(). Returns None if no cache
    exists yet (ensure_spatial_breakdown() hasn't run for this scene)."""
    path = _spatial_path_for_scene(scene_path)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return SpatialBreakdown(**json.load(f))


async def ensure_spatial_breakdown(scene_path: str) -> SpatialBreakdown:
    """Create-if-missing, cached per scene (Eran's call, 2026-11-24):
    geometry doesn't change between moods or attempts, so this runs the
    spatial agent AT MOST ONCE per scene, ever — every subsequent run
    against the same scene reads the cached JSON instead. ASYNC because
    a cache miss calls the LLM; must be awaited once near the top of
    main.py's run(), before the attempt loop (see module docstring)."""
    cached = load_cached_spatial_breakdown(scene_path)
    if cached is not None:
        return cached

    scene = list_scene_transforms()
    bounds = get_scene_bounds()
    lines = [
        f"- {o.name} (instance_id={o.instance_id}, is_light={o.is_light}): "
        f"pos=({o.pos_x:.2f}, {o.pos_y:.2f}, {o.pos_z:.2f})"
        for o in scene
    ]
    scene_context = (
        "Scene objects:\n" + "\n".join(lines) + "\n\n"
        f"Scene bounding box: x [{bounds.min_x:.1f}, {bounds.max_x:.1f}], "
        f"y [{bounds.min_y:.1f}, {bounds.max_y:.1f}], "
        f"z [{bounds.min_z:.1f}, {bounds.max_z:.1f}], diagonal={bounds.diagonal:.1f}"
    )
    capture = capture_game_view()
    image_url = image_to_data_url(capture.path)
    prompt = [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": scene_context},
                {"type": "input_image", "image_url": image_url},
            ],
        }
    ]
    result = await Runner.run(spatial_agent, prompt)
    breakdown: SpatialBreakdown = result.final_output

    os.makedirs(_SPATIAL_DIR, exist_ok=True)
    with open(_spatial_path_for_scene(scene_path), "w", encoding="utf-8") as f:
        f.write(breakdown.model_dump_json(indent=2))
    return breakdown


def format_spatial_breakdown_for_prompt(breakdown: SpatialBreakdown) -> str:
    """Render as the extra context block appended to get_scene_context()'s
    output — advisory, not a constraint (see module docstring)."""
    lines = [
        f"- {a.anchor_name} (instance_id={a.anchor_object}): {a.traits} "
        f"Suggested light position near it: ({a.suggested_light_position_x}, {a.suggested_light_position_y}, {a.suggested_light_position_z})."
        for a in breakdown.anchors
    ]
    return (
        "Spatial ground-base analysis (computed once for this scene, geometry-only, "
        "NOT mood-specific — cross-reference with your own archetype/mood judgment "
        "for which anchor and technique actually fits THIS task):\n"
        f"{breakdown.reasoning}\n" + "\n".join(lines)
    )
