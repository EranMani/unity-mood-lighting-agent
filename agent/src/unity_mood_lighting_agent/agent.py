"""
agent.py — the lighting agent and its tools.

Scene context (list_scene_transforms()) is injected into the prompt by
get_scene_context(), NOT fetched by the agent via a tool call — this is the
locked-in code-vs-agent split from step 5 / README: listing has no
ambiguity, so it's code's job; deciding what to change for a mood is the
agent's job.
"""

from agents import Agent

from unity_mood_lighting_agent.tools import (
    aim_light_at,
    create_light,
    create_light_near,
    set_color_adjustments,
    set_fog,
    set_light_properties,
    set_object_transform,
    set_vignette,
)
from unity_mood_lighting_agent.unity_bridge import list_scene_transforms

agent = Agent(
    name="MoodLightingAgent",
    instructions=(
        "You adjust a Unity scene's lighting AND overall rendering to "
        "match a requested mood (e.g. 'horror', 'cozy'). You will be "
        "given the current scene's objects with their instance_id, "
        "position, and rotation. Use set_object_transform to move/rotate "
        "objects, set_light_properties to change a light's intensity, "
        "color, color temperature (Kelvin — lower is warmer), and "
        "bounce/indirect intensity. To add a new light: PREFER "
        "create_light_near over create_light whenever you know which "
        "existing object the light should illuminate — give it an xyz "
        "offset (your choice, based on lighting role: e.g. above and "
        "behind for a key light, to the side for a rim light) relative "
        "to that object, and it creates the light pre-aimed, so it can't "
        "end up pointing at nothing. Only use plain create_light (then "
        "aim_light_at afterward) when no single object makes sense as an "
        "anchor. Beyond individual lights, you also control the WHOLE "
        "scene's rendering: set_color_adjustments for overall color "
        "grading/exposure/contrast/saturation/tint (affects everything at "
        "once, not one light), set_vignette for darkened frame edges "
        "(tension/isolation/horror), and set_fog for depth/mystery or to "
        "obscure distant detail. These often matter as much as individual "
        "lights for selling a mood. You don't have to provide every value "
        "each call — omit what you don't want to change."
    ),
    model="gpt-5.4-mini",
    tools=[
        set_object_transform,
        set_light_properties,
        create_light,
        create_light_near,
        aim_light_at,
        set_color_adjustments,
        set_vignette,
        set_fog,
    ],
)


def get_scene_context() -> str:
    """Fetches the current scene state — independent of any task, this is
    the code-orchestrated 'find' step (not a tool the agent calls)."""
    scene = list_scene_transforms()
    return "\n".join(
        f"- {o.name} (instance_id={o.instance_id}): "
        f"pos=({o.pos_x}, {o.pos_y}, {o.pos_z}), "
        f"rot=({o.rot_x}, {o.rot_y}, {o.rot_z})"
        for o in scene
    )
