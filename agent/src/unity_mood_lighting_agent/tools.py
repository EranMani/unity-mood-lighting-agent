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

from unity_mood_lighting_agent.unity_bridge import (
    check_rotation_aims_at_geometry,
    compute_look_at_rotation,
    count_lights,
    create_light as _create_light,
    get_light_properties,
    list_scene_transforms,
)
from unity_mood_lighting_agent.unity_bridge import set_light_properties as _set_light_properties
from unity_mood_lighting_agent.unity_bridge import set_object_transform as _set_object_transform

MAX_LIGHTS = 10  # per README v0 guardrail plan: "total light count stays under a cap"
# Bumped from 6 live with Eran: the sci-fi thriller mood test hit the cap
# and the agent explicitly said it wanted one more "lurking" light but
# couldn't add it - 6 was too tight for a real, observed case (needed 7).
# 10 gives real headroom above anything asked for so far while still being
# a real bound, not "no cap" - the cap exists to stop runaway light spam,
# not to block legitimate setups.


def _merge_axis(current: float, new: float | None) -> float:
    return new if new is not None else current


def _apply_transform_with_guardrail(
    target: str,
    position: tuple[float, float, float] | None,
    rotation: tuple[float, float, float] | None,
) -> str:
    """Shared apply+guardrail path for set_object_transform and
    aim_light_at — one write path, so the raycast guardrail (build log #13)
    always runs no matter which tool is calling it, instead of being
    re-implemented per tool and risking one copy missing it (exactly the
    bug create_light had before this refactor)."""
    current = next((o for o in list_scene_transforms() if o.instance_id == target), None)
    if current is None:
        return f"Error: no object with instance_id {target} found in the scene."

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

    return _apply_transform_with_guardrail(target, position, rotation)


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


@function_tool
def create_light(
    name: str,
    pos_x: float,
    pos_y: float,
    pos_z: float,
    light_type: str = "Point",
) -> str:
    """Create a NEW Light GameObject at the given position. Use this when
    the mood genuinely needs more light sources than currently exist (e.g.
    one dim directional light often can't produce real contrast/shadows —
    multiple lights with different roles, same idea as a photography/film
    key/fill/rim setup, may serve a mood better than endlessly tweaking one
    light). light_type is one of: Spot, Directional, Point, Rectangle,
    Disc, Pyramid, Box, Tube. Returns the new light's instance_id — use
    set_light_properties and set_object_transform on it afterward for
    intensity/color/rotation."""
    if count_lights() >= MAX_LIGHTS:
        return f"Rejected: scene already has {MAX_LIGHTS} lights (the cap). Adjust existing lights instead of adding more."

    try:
        instance_id = _create_light(name=name, position=(pos_x, pos_y, pos_z), light_type=light_type)
    except ValueError as e:
        return f"Rejected: {e}"

    # Guardrail (bug found live by Eran: new lights got Unity's default
    # rotation (0,0,0) and often pointed at nothing). Warn, don't auto-fix
    # or delete — the agent already has aim_light_at/set_object_transform
    # to fix it itself, and auto-deleting would need its own undo logic
    # for no real benefit over just telling the agent what's wrong.
    check = check_rotation_aims_at_geometry((pos_x, pos_y, pos_z), (0.0, 0.0, 0.0), self_id=instance_id)
    if not check.hit:
        return (
            f"Created light '{name}' (instance_id={instance_id}) at ({pos_x}, {pos_y}, {pos_z}), "
            f"type={light_type}. WARNING: it has Unity's default rotation (0,0,0) and currently "
            "points at nothing in the scene. Use aim_light_at to point it at an existing object, "
            "or set_object_transform to rotate it manually, before it has any visible effect."
        )

    return f"Created light '{name}' (instance_id={instance_id}) at ({pos_x}, {pos_y}, {pos_z}), type={light_type}."


@function_tool
def aim_light_at(light_target: str, aim_at_target: str) -> str:
    """Rotate a light (by instance_id) so it points directly at another
    scene object (by instance_id, from the scene context you were given).
    Use this after create_light, or on any existing light, when you know
    WHICH object the light should illuminate — if no specific object makes
    sense for the mood, pick the one you judge most central/relevant
    yourself. Computes the rotation via Unity's own LookRotation (not
    guessed), then applies it through the same guardrail as
    set_object_transform."""
    objects = list_scene_transforms()
    light = next((o for o in objects if o.instance_id == light_target), None)
    if light is None:
        return f"Error: no object with instance_id {light_target} found in the scene."
    aim_at = next((o for o in objects if o.instance_id == aim_at_target), None)
    if aim_at is None:
        return f"Error: no object with instance_id {aim_at_target} found in the scene."

    rotation = compute_look_at_rotation(
        light_position=(light.pos_x, light.pos_y, light.pos_z),
        target_position=(aim_at.pos_x, aim_at.pos_y, aim_at.pos_z),
    )
    return _apply_transform_with_guardrail(light_target, position=None, rotation=rotation)


@function_tool
def create_light_near(
    name: str,
    aim_at_target: str,
    offset_x: float,
    offset_y: float,
    offset_z: float,
    light_type: str = "Point",
) -> str:
    """Create a NEW light positioned relative to an EXISTING object
    (aim_at_target's instance_id), pre-aimed at that object — this is the
    preferred way to create a light when you know what it should
    illuminate, since it can't produce the 'light points at nothing' bug
    create_light can. YOU choose offset_x/y/z (relative to the target, in
    world units) based on lighting role/theory: e.g. above and slightly
    behind for a key light, to the side at the same height for a rim
    light, in front and low for an uplight. The offset is added to the
    target's position to get the light's actual position; the light is
    then rotated to face back at the target. Use create_light instead if
    the light shouldn't be tied to one specific object's position."""
    if count_lights() >= MAX_LIGHTS:
        return f"Rejected: scene already has {MAX_LIGHTS} lights (the cap). Adjust existing lights instead of adding more."

    aim_at = next((o for o in list_scene_transforms() if o.instance_id == aim_at_target), None)
    if aim_at is None:
        return f"Error: no object with instance_id {aim_at_target} found in the scene."

    if offset_x == 0 and offset_y == 0 and offset_z == 0:
        return "Rejected: offset_x/y/z are all 0 — the light would be placed exactly at the target's position, giving no direction to aim toward."

    light_position = (aim_at.pos_x + offset_x, aim_at.pos_y + offset_y, aim_at.pos_z + offset_z)
    target_position = (aim_at.pos_x, aim_at.pos_y, aim_at.pos_z)

    try:
        instance_id = _create_light(name=name, position=light_position, light_type=light_type)
    except ValueError as e:
        return f"Rejected: {e}"

    rotation = compute_look_at_rotation(light_position=light_position, target_position=target_position)
    check = check_rotation_aims_at_geometry(light_position, rotation, self_id=instance_id)
    if not check.hit:
        return (
            f"Created light '{name}' (instance_id={instance_id}) at {light_position}, aimed at "
            f"{aim_at_target}, type={light_type}. WARNING: even aimed at the target's position, the "
            "ray found no geometry — the offset may be too large (target itself might be out of "
            "raycast range) or something is blocking it. Check with set_object_transform/aim_light_at."
        )

    _set_object_transform(target=instance_id, position=None, rotation=rotation)
    return f"Created light '{name}' (instance_id={instance_id}) at {light_position}, aimed at {aim_at_target}, type={light_type}."
