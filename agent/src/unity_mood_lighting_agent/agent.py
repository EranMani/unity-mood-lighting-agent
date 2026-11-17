"""
agent.py — the one agent, with exactly one tool (set_object_transform).

Scene context (list_scene_transforms()) is injected into the prompt by
build_agent_input(), NOT fetched by the agent via a tool call — this is the
locked-in code-vs-agent split from step 5 / README: listing has no
ambiguity, so it's code's job; deciding what to change for a mood is the
agent's job.
"""

from agents import Agent

from unity_mood_lighting_agent.tools import set_object_transform
from unity_mood_lighting_agent.unity_bridge import list_scene_transforms

agent = Agent(
    name="MoodLightingAgent",
    instructions=(
        "You adjust a Unity scene's lighting to match a requested mood "
        "(e.g. 'horror', 'cozy'). You will be given the current scene's "
        "objects with their instance_id, position, and rotation. Use the "
        "set_object_transform tool to move/rotate objects toward the mood. "
        "You can change just one axis at a time if that's all that's needed "
        "— you don't have to provide all 3 position or rotation values."
    ),
    model="gpt-5.4-mini",
    tools=[set_object_transform],
)


def build_agent_input(task: str) -> str:
    """Injects current scene state as context, ahead of the agent running —
    this is the code-orchestrated 'find' step, not a tool the agent calls."""
    scene = list_scene_transforms()
    scene_lines = "\n".join(
        f"- {o.name} (instance_id={o.instance_id}): "
        f"pos=({o.pos_x}, {o.pos_y}, {o.pos_z}), "
        f"rot=({o.rot_x}, {o.rot_y}, {o.rot_z})"
        for o in scene
    )
    return f"Current scene objects:\n{scene_lines}\n\nTask: {task}"
