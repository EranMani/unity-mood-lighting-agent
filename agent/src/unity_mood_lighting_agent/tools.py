"""
tools.py — the agent's tool(s).

Per the locked-in design decision: the agent gets exactly ONE tool,
set_object_transform. Finding/listing objects is NOT a tool — that stays
code-orchestrated (list_scene_transforms() is called before the agent runs,
its result injected as context). See README "Code vs. agent, the actual
rule" and learning_steps/step5 for why.

Single-axis edits: the Unity CLI's set_transform has no per-axis update —
it's all 3 position values or none, same for rotation. So this tool reads
the object's CURRENT transform first, merges in only the axis/axes actually
given, and sends the complete triple. Costs one extra read call per write,
acceptable at this scene size.
"""

from agents import function_tool

from unity_mood_lighting_agent.unity_bridge import check_rotation_aims_at_geometry, list_scene_transforms
from unity_mood_lighting_agent.unity_bridge import set_object_transform as _set_object_transform


def _merge_axis(current: float, new: float | None) -> float:
    return new if new is not None else current


@function_tool
def set_object_transform(
    target: str,
    pos_x: float | None = None,
    pos_y: float | None = None,
    pos_z: float | None = None,
    rot_x: float | None = None,
    rot_y: float | None = None,
    rot_z: float | None = None,
) -> str:
    """Move and/or rotate a scene object by its instance_id (from the scene
    context you were given). Give only the axis/axes you actually want to
    change — any axis you omit keeps its current value. You do not need to
    provide all 3 position or all 3 rotation values."""
    any_position = pos_x is not None or pos_y is not None or pos_z is not None
    any_rotation = rot_x is not None or rot_y is not None or rot_z is not None
    if not any_position and not any_rotation:
        return "Error: give at least one position or rotation axis to change."

    current = next((o for o in list_scene_transforms() if o.instance_id == target), None)
    if current is None:
        return f"Error: no object with instance_id {target} found in the scene."

    position = None
    if any_position:
        position = (
            _merge_axis(current.pos_x, pos_x),
            _merge_axis(current.pos_y, pos_y),
            _merge_axis(current.pos_z, pos_z),
        )

    rotation = None
    if any_rotation:
        rotation = (
            _merge_axis(current.rot_x, rot_x),
            _merge_axis(current.rot_y, rot_y),
            _merge_axis(current.rot_z, rot_z),
        )

    # Guardrail (locked in after build log #13's noon-sunlight bug): a
    # rotation that points the light at nothing — not even the room's own
    # geometry — is almost certainly a reasoning error (wrong axis/sign/
    # convention), not an intentional choice. Checked on the CANDIDATE
    # values, before anything is applied to the live object.
    if any_rotation:
        assert rotation is not None  # set above, any_rotation guarantees this
        position_for_check = position if position is not None else (current.pos_x, current.pos_y, current.pos_z)
        check = check_rotation_aims_at_geometry(position_for_check, rotation, self_id=target)
        if not check.hit:
            return (
                f"Rejected: rotation {rotation} for {target} points at nothing in the scene "
                "(no geometry within range). This usually means the rotation convention/sign is "
                "wrong, not that this is genuinely the intended direction. Re-check the axis "
                "values — remember Unity's +X rotation tilts the forward vector based on a "
                "specific convention, don't assume it matches intuition."
            )

    _set_object_transform(target=target, position=position, rotation=rotation)
    return f"Moved/rotated {target}: position={position}, rotation={rotation}"
