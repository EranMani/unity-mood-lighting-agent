"""
agent.py — the lighting agent and its tools.

Scene context (list_scene_transforms()) is injected into the prompt by
get_scene_context(), NOT fetched by the agent via a tool call — this is the
locked-in code-vs-agent split from step 5 / README: listing has no
ambiguity, so it's code's job; deciding what to change for a mood is the
agent's job.
"""

from agents import Agent

from unity_mood_lighting_agent.tools import set_light_properties, set_object_transform
from unity_mood_lighting_agent.unity_bridge import list_scene_transforms

agent = Agent(
    name="MoodLightingAgent",
    instructions=(
        "You adjust a Unity scene's lighting to match a requested mood "
        "(e.g. 'horror', 'cozy'). You will be given the current scene's "
        "objects with their instance_id, position, and rotation. Use "
        "set_object_transform to move/rotate objects, and "
        "set_light_properties to change a light's intensity, color, color "
        "temperature (Kelvin — lower is warmer), and bounce/indirect "
        "intensity. You don't have to provide every value each call — "
        "omit what you don't want to change."
    ),
    model="gpt-5.4-mini",
    tools=[set_object_transform, set_light_properties],
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
