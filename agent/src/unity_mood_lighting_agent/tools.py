"""
tools.py — the agent's tools.

Originally locked in as exactly ONE tool (set_object_transform). Expanded
to add set_light_properties once the project moved past position/rotation
into intensity/color/color-temp/bounce — same code-vs-agent split still
applies (listing/reading stays code-orchestrated via list_scene_transforms(),
injected as context, not a tool call).

Single-axis edits: the Unity CLI's set_transform has no per-axis update —
it's all 3 position values or none, same for rotation. So this tool reads
the object's CURRENT transform first, merges in only the axis/axes actually
given, and sends the complete triple. Costs one extra read call per write,
acceptable at this scene size.
"""

from agents import function_tool

from unity_mood_lighting_agent.unity_bridge import check_rotation_aims_at_geometry, get_light_properties, list_scene_transforms
from unity_mood_lighting_agent.unity_bridge import set_light_properties as _set_light_properties
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

    # Guardrail (locked in after build log #13's noon-sunlight bug): if the
    # object's resulting direction points at nothing — not even the room's
    # own geometry — that's almost certainly a reasoning error, not an
    # intentional choice. Runs on ANY move that changes position and/or
    # rotation (not just rotation alone): moving a light to a new spot can
    # just as easily point its existing, unchanged rotation into empty
    # space from the new position. Checked on the CANDIDATE values, before
    # anything is applied to the live object.
    if any_position or any_rotation:
        position_for_check = position if position is not None else (current.pos_x, current.pos_y, current.pos_z)
        rotation_for_check = rotation if rotation is not None else (current.rot_x, current.rot_y, current.rot_z)
        check = check_rotation_aims_at_geometry(position_for_check, rotation_for_check, self_id=target)
        if not check.hit:
            return (
                f"Rejected: {target} at position={position_for_check} with rotation={rotation_for_check} "
                "would point at nothing in the scene (no geometry within range). If you just changed "
                "rotation, this usually means the rotation convention/sign is wrong — Unity's +X "
                "rotation tilts the forward vector based on a specific convention, don't assume it "
                "matches intuition. If you just changed position, the object's existing rotation may "
                "no longer point toward any geometry from the new spot."
            )

    _set_object_transform(target=target, position=position, rotation=rotation)
    return f"Moved/rotated {target}: position={position}, rotation={rotation}"


@function_tool
def set_light_properties(
    target: str,
    intensity: float | None = None,
    color_r: float | None = None,
    color_g: float | None = None,
    color_b: float | None = None,
    color_temperature: float | None = None,
    bounce_intensity: float | None = None,
) -> str:
    """Set a Light's intensity, color (RGB, each 0-1, give all 3 together),
    color temperature in Kelvin (lower=warmer, e.g. 1800=candle, 6500=cool
    daylight), and/or bounce/indirect intensity. Omit any field to leave it
    unchanged. target is the instance_id from the scene context."""
    color = None
    if color_r is not None or color_g is not None or color_b is not None:
        if color_r is None or color_g is None or color_b is None:
            return "Error: give all three of color_r, color_g, color_b together, not just some."
        color = (color_r, color_g, color_b)

    # Guardrail (per README v0 plan: "intensity > 0 and below a sane max"):
    # a non-positive or absurd intensity is almost certainly a mistake, not
    # an intentional "turn the light off" — there's no tool for removing a
    # light, so a 0/negative intensity would just silently blind the scene
    # with no visual feedback explaining why.
    if intensity is not None and not (0 < intensity <= 20):
        return f"Rejected: intensity {intensity} is out of the sane range (0, 20]. Pick a smaller positive value."
    if bounce_intensity is not None and not (0 <= bounce_intensity <= 5):
        return f"Rejected: bounce_intensity {bounce_intensity} is out of the sane range [0, 5]."

    _set_light_properties(
        target=target,
        intensity=intensity,
        color=color,
        color_temperature=color_temperature,
        bounce_intensity=bounce_intensity,
    )
    current = get_light_properties(target)
    return f"Updated light {target}: {current}"
