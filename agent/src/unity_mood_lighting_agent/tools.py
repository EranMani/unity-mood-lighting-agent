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
    check_position_within_bounds,
    check_rotation_aims_at_geometry,
    compute_look_at_rotation,
    count_lights,
    create_light as _create_light,
    delete_object as _delete_object,
    get_light_properties,
    get_scene_bounds,
    list_available_skyboxes,
    list_scene_transforms,
)
from unity_mood_lighting_agent.unity_bridge import set_skybox as _set_skybox
from unity_mood_lighting_agent.unity_bridge import set_color_adjustments as _set_color_adjustments
from unity_mood_lighting_agent.unity_bridge import set_ambient as _set_ambient
from unity_mood_lighting_agent.unity_bridge import set_fog as _set_fog
from unity_mood_lighting_agent.unity_bridge import set_light_properties as _set_light_properties
from unity_mood_lighting_agent.unity_bridge import set_object_transform as _set_object_transform
from unity_mood_lighting_agent.unity_bridge import set_vignette as _set_vignette

MAX_LIGHTS = 10  # per README v0 guardrail plan: "total light count stays under a cap"
# Bumped from 6 live with Eran: the sci-fi thriller mood test hit the cap
# and the agent explicitly said it wanted one more "lurking" light but
# couldn't add it - 6 was too tight for a real, observed case (needed 7).
# 10 gives real headroom above anything asked for so far while still being
# a real bound, not "no cap" - the cap exists to stop runaway light spam,
# not to block legitimate setups.

AGENT_LIGHT_PREFIX = "AgentLight_"
# Ground rule set by Eran: the agent may add/remove its OWN lights, never
# the scene's original lights. Tagging happens in CODE at creation time
# (create_light/create_light_near below prepend this, unconditionally),
# not by asking the agent to follow a naming convention — this project
# has already hit "trust the LLM to follow an instruction exactly" bugs
# twice (step 13's rotation sign, step 25's name-vs-id mixup), so anything
# that must be reliable goes through code, not a prompt request.


def _merge_axis(current: float, new: float | None) -> float:
    return new if new is not None else current


def _resolve_target(objects, target: str):
    """Resolve `target` to its ObjectTransform — by instance_id (the
    documented, expected form) or, failing that, by exact name match.
    Guardrail for a real observed bug: the LLM occasionally sends an
    object's human-readable name instead of its instance_id (e.g.
    "Point Light (3)") even though it has the correct id in context —
    schema/type checking can't catch this since a name is still a valid
    string. This is input resolution, not a retry: whichever form the
    model sends, we deterministically resolve it to the real id here,
    once, before any tool proceeds."""
    match = next((o for o in objects if o.instance_id == target), None)
    if match is not None:
        return match
    return next((o for o in objects if o.name == target), None)


def _check_within_bounds(position: tuple[float, float, float]) -> str | None:
    """Shared bounds guardrail (planned in the original v0 list, never
    built until now) — returns a rejection message if position is
    outside the scene's real bounding box on any axis, None if it's
    fine. Called from every write path that places/moves something
    (same 'one shared check, can't be missed by a future tool' reasoning
    as _apply_transform_with_guardrail's rotation check)."""
    check = check_position_within_bounds(position)
    if check.within:
        return None
    b = check.bounds
    return (
        f"Rejected: position {position} is outside the scene's real bounding box "
        f"(x: {b.min_x:.1f} to {b.max_x:.1f}, y: {b.min_y:.1f} to {b.max_y:.1f}, "
        f"z: {b.min_z:.1f} to {b.max_z:.1f}). Pick a position inside the actual room/level geometry."
    )


def _apply_transform_with_guardrail(
    target: str,
    position: tuple[float, float, float] | None,
    rotation: tuple[float, float, float] | None,
    required_hit_name: str | None = None,
) -> str:
    """Shared apply+guardrail path for set_object_transform and
    aim_light_at — one write path, so the raycast guardrail (build log #13)
    always runs no matter which tool is calling it, instead of being
    re-implemented per tool and risking one copy missing it (exactly the
    bug create_light had before this refactor).

    required_hit_name (2026-11-24, Eran's call): when the CALLER actually
    knows what it's trying to hit (aim_light_at always does — it has an
    explicit aim_at_target), the guardrail should check for THAT object
    specifically, not merely "hits something, not empty space." Found live
    via the spatial eval: the old "hits anything" check happily approved a
    light aimed at the wrong object entirely (hit the bed instead of the
    requested arcade machine) because it never compared the hit against
    the actual intended target. When required_hit_name is given, hitting
    the WRONG object is now treated exactly the same as hitting nothing —
    both are a rejection. Plain set_object_transform calls with no implied
    target (just a free rotation, no specific aim-at intent) have nothing
    to compare against, so they keep the old "hits something" check by
    passing None here — there's no stricter check possible without a
    stated target.
    """
    current = _resolve_target(list_scene_transforms(), target)
    if current is None:
        return f"Error: no object with instance_id or name '{target}' found in the scene."
    target = current.instance_id

    position_for_check = position if position is not None else (current.pos_x, current.pos_y, current.pos_z)
    rotation_for_check = rotation if rotation is not None else (current.rot_x, current.rot_y, current.rot_z)

    if position is not None:
        bounds_error = _check_within_bounds(position_for_check)
        if bounds_error is not None:
            return bounds_error

    check = check_rotation_aims_at_geometry(position_for_check, rotation_for_check, self_id=target)
    if required_hit_name is not None:
        ok = check.hit and check.hit_name == required_hit_name
    else:
        ok = check.hit
    if not ok:
        if required_hit_name is not None and check.hit:
            return (
                f"Rejected: {target} at position={position_for_check} with rotation={rotation_for_check} "
                f"hits '{check.hit_name}', not the intended target '{required_hit_name}'. Recompute the "
                "rotation/position so it actually points at the real target, not just at something."
            )
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

    current = _resolve_target(list_scene_transforms(), target)
    if current is None:
        return f"Error: no object with instance_id or name '{target}' found in the scene."
    target = current.instance_id

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
    range: float | None = None,
    spot_angle: float | None = None,
    shadow_type: str | None = None,
    shadow_strength: float | None = None,
) -> str:
    """Set a Light's intensity, color (RGB, each 0-1, give all 3 together),
    bounce/indirect intensity, range, spot_angle, shadow_type, and/or
    shadow_strength. Omit any field to leave it unchanged. target is
    the instance_id from the scene context.

    Use color (RGB) for ALL tinting needs, warm, cool, toxic green,
    alien purple, neon, anything. There is also a color_temperature
    param (Kelvin) but don't use it: it only moves along the real
    blackbody curve (orange -> white -> blue, can't do green/purple/
    cyan at all), and it multiplies with color rather than adding, so
    touching both at once silently double-shifts and double-dims the
    light. RGB alone covers everything you need.

    range (Point/Spot only, world-space units the light reaches) is the
    lever that controls whether a light reads as a TIGHT CONTAINED POOL
    (small range) versus FLOODING THE WHOLE ROOM EVENLY (large range) —
    this is usually what separates a dramatic key light from a generic
    room fill. Size it relative to get_scene_bounds()'s diagonal, not a
    fixed number: a range anywhere near the room's own diagonal floods
    everything, a range a small fraction of it creates a real pool.

    spot_angle (Spot only, degrees, full cone width 1-179) controls beam
    width — narrow for a tight dramatic beam, wide for a broad soft wash.

    shadow_type is 'none', 'hard', or 'soft'. CRITICAL: a light created
    via create_light defaults to 'soft' already, but if you ever see
    'none' on a light you want to cast real shadow shape, set it
    explicitly — no amount of intensity or range alone produces a visible
    shadow if shadow_type is 'none', that is a hard requirement, not a
    style choice.

    shadow_strength (0-1) is a SEPARATE lever from shadow_type — it's how
    DARK the shadow actually renders (0=invisible, 1=full black), not
    whether a shadow exists at all. This is what actually separates a
    soft_ambient mood (shadows present but barely registering, e.g.
    0.2-0.4) from a noir mood (full-strength, near-black shadows, e.g.
    0.9-1.0) — shadow_type alone can't express that difference."""
    color = None
    if color_r is not None or color_g is not None or color_b is not None:
        if color_r is None or color_g is None or color_b is None:
            return "Error: give all three of color_r, color_g, color_b together, not just some."
        color = (color_r, color_g, color_b)

    current = _resolve_target(list_scene_transforms(), target)
    if current is None:
        return f"Error: no object with instance_id or name '{target}' found in the scene."
    target = current.instance_id

    # Guardrail (per README v0 plan: "intensity > 0 and below a sane max"):
    # a non-positive or absurd intensity is almost certainly a mistake, not
    # an intentional "turn the light off" — there's no tool for removing a
    # light, so a 0/negative intensity would just silently blind the scene
    # with no visual feedback explaining why.
    if intensity is not None and not (0 < intensity <= 20):
        return f"Rejected: intensity {intensity} is out of the sane range (0, 20]. Pick a smaller positive value."
    if bounce_intensity is not None and not (0 <= bounce_intensity <= 5):
        return f"Rejected: bounce_intensity {bounce_intensity} is out of the sane range [0, 5]."
    if range is not None and range <= 0:
        return f"Rejected: range {range} must be positive. Compare against get_scene_bounds()'s diagonal for a sensible size."
    if spot_angle is not None and not (1 <= spot_angle <= 179):
        return f"Rejected: spot_angle {spot_angle} is out of Unity's valid range [1, 179] degrees."
    if shadow_type is not None and shadow_type not in ("none", "hard", "soft"):
        return f"Rejected: shadow_type must be 'none', 'hard', or 'soft', got {shadow_type!r}."
    if shadow_strength is not None and not (0 <= shadow_strength <= 1):
        return f"Rejected: shadow_strength {shadow_strength} must be in [0, 1]."

    _set_light_properties(
        target=target,
        intensity=intensity,
        color=color,
        color_temperature=color_temperature,
        bounce_intensity=bounce_intensity,
        range=range,
        spot_angle=spot_angle,
        shadow_type=shadow_type,
        shadow_strength=shadow_strength,
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

    bounds_error = _check_within_bounds((pos_x, pos_y, pos_z))
    if bounds_error is not None:
        return bounds_error

    tagged_name = f"{AGENT_LIGHT_PREFIX}{name}"
    try:
        instance_id = _create_light(name=tagged_name, position=(pos_x, pos_y, pos_z), light_type=light_type)
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
            f"Created light '{tagged_name}' (instance_id={instance_id}) at ({pos_x}, {pos_y}, {pos_z}), "
            f"type={light_type}. WARNING: it has Unity's default rotation (0,0,0) and currently "
            "points at nothing in the scene. Use aim_light_at to point it at an existing object, "
            "or set_object_transform to rotate it manually, before it has any visible effect."
        )

    return f"Created light '{tagged_name}' (instance_id={instance_id}) at ({pos_x}, {pos_y}, {pos_z}), type={light_type}."


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
    light = _resolve_target(objects, light_target)
    if light is None:
        return f"Error: no object with instance_id or name '{light_target}' found in the scene."
    aim_at = _resolve_target(objects, aim_at_target)
    if aim_at is None:
        return f"Error: no object with instance_id or name '{aim_at_target}' found in the scene."

    rotation = compute_look_at_rotation(
        light_position=(light.pos_x, light.pos_y, light.pos_z),
        target_position=(aim_at.pos_x, aim_at.pos_y, aim_at.pos_z),
    )
    return _apply_transform_with_guardrail(light.instance_id, position=None, rotation=rotation, required_hit_name=aim_at.name)


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

    aim_at = _resolve_target(list_scene_transforms(), aim_at_target)
    if aim_at is None:
        return f"Error: no object with instance_id or name '{aim_at_target}' found in the scene."

    if offset_x == 0 and offset_y == 0 and offset_z == 0:
        return "Rejected: offset_x/y/z are all 0 — the light would be placed exactly at the target's position, giving no direction to aim toward."

    light_position = (aim_at.pos_x + offset_x, aim_at.pos_y + offset_y, aim_at.pos_z + offset_z)
    target_position = (aim_at.pos_x, aim_at.pos_y, aim_at.pos_z)

    bounds_error = _check_within_bounds(light_position)
    if bounds_error is not None:
        return bounds_error

    tagged_name = f"{AGENT_LIGHT_PREFIX}{name}"
    try:
        instance_id = _create_light(name=tagged_name, position=light_position, light_type=light_type)
    except ValueError as e:
        return f"Rejected: {e}"

    rotation = compute_look_at_rotation(light_position=light_position, target_position=target_position)
    check = check_rotation_aims_at_geometry(light_position, rotation, self_id=instance_id)
    if not check.hit:
        return (
            f"Created light '{tagged_name}' (instance_id={instance_id}) at {light_position}, aimed at "
            f"{aim_at_target}, type={light_type}. WARNING: even aimed at the target's position, the "
            "ray found no geometry — the offset may be too large (target itself might be out of "
            "raycast range) or something is blocking it. Check with set_object_transform/aim_light_at."
        )

    _set_object_transform(target=instance_id, position=None, rotation=rotation)
    return f"Created light '{tagged_name}' (instance_id={instance_id}) at {light_position}, aimed at {aim_at_target}, type={light_type}."


@function_tool
def set_color_adjustments(
    post_exposure: float | None = None,
    contrast: float | None = None,
    saturation: float | None = None,
    color_filter_r: float | None = None,
    color_filter_g: float | None = None,
    color_filter_b: float | None = None,
) -> str:
    """Set the scene's overall color grading (Global Volume's
    ColorAdjustments) — affects the WHOLE rendered image, not any single
    light. post_exposure shifts overall brightness (0 = unchanged,
    negative = darker). contrast and saturation are roughly -100 to 100
    (negative saturation desaturates toward grayscale, useful for
    horror/bleak moods; negative contrast flattens, positive punches up
    separation between light/dark). color_filter tints everything (give
    all 3 r/g/b together, each 0-1) — e.g. a cool blue filter for
    horror/sci-fi, warm amber for cozy. Omit any field to leave it
    unchanged."""
    color_filter = None
    if color_filter_r is not None or color_filter_g is not None or color_filter_b is not None:
        if color_filter_r is None or color_filter_g is None or color_filter_b is None:
            return "Error: give all three of color_filter_r, color_filter_g, color_filter_b together, not just some."
        color_filter = (color_filter_r, color_filter_g, color_filter_b)

    if contrast is not None and not (-100 <= contrast <= 100):
        return f"Rejected: contrast {contrast} is out of range [-100, 100]."
    if saturation is not None and not (-100 <= saturation <= 100):
        return f"Rejected: saturation {saturation} is out of range [-100, 100]."

    _set_color_adjustments(
        post_exposure=post_exposure,
        contrast=contrast,
        saturation=saturation,
        color_filter=color_filter,
    )
    return "Updated color grading (ColorAdjustments)."


@function_tool
def set_vignette(intensity: float, smoothness: float = 0.4) -> str:
    """Set the scene's vignette (darkened frame edges, drawing the eye to
    center) — a classic tension/horror/isolation tool. intensity is 0-1
    (0 = off, 1 = very strong). smoothness controls how gradual the
    falloff is (0 = hard edge, 1 = very soft). Adds the Vignette override
    to the scene's Volume profile automatically if it isn't there yet."""
    if not (0 <= intensity <= 1):
        return f"Rejected: intensity {intensity} is out of range [0, 1]."
    if not (0 <= smoothness <= 1):
        return f"Rejected: smoothness {smoothness} is out of range [0, 1]."

    _set_vignette(intensity=intensity, smoothness=smoothness)
    return f"Updated vignette: intensity={intensity}, smoothness={smoothness}."


@function_tool
def set_ambient(intensity: float) -> str:
    """Set the scene's ambient light intensity — a uniform fill applied to
    EVERY surface regardless of any individual light's position or range.
    Unity's default is 1.0. For a high-contrast/dramatic mood, this is
    often the real reason un-lit areas never read as genuinely dark: no
    matter how far you shrink a light's range or how low you set another
    light's intensity, this floor still applies everywhere. Pull it down
    toward 0 (0.0-0.15) for THREAT/DRAMATIC moods so your dark zones can
    actually go near-black. Leave it near its default for diffuse/soft
    moods where an even fill IS the desired look."""
    if intensity < 0:
        return f"Rejected: intensity {intensity} is negative."
    _set_ambient(intensity=intensity)
    return f"Updated ambient intensity to {intensity}."


@function_tool
def list_skyboxes() -> str:
    """List every available HDRI skybox (by id) with its mood-relevant
    metadata (environment indoor/outdoor, time_of_day, weather,
    light_type, contrast, sky_view). Call this BEFORE set_skybox to pick
    the right id — don't guess an id. An indoor scene with no visible
    sky through a window may see little VISIBLE change from a skybox
    swap, but ambient light color/intensity still updates since this
    scene's ambient mode is Skybox-driven."""
    options = list_available_skyboxes()
    lines = [
        f"- {o.id}: {o.display_name} ({o.environment}, {o.time_of_day}, {o.weather}, "
        f"light={o.light_type}, contrast={o.contrast}, sky_view={o.sky_view}) — {o.description}"
        for o in options
    ]
    return "\n".join(lines)


@function_tool
def set_skybox(
    skybox_id: str,
    exposure: float = 1.0,
    rotation: float = 0.0,
    tint_r: float | None = None,
    tint_g: float | None = None,
    tint_b: float | None = None,
) -> str:
    """Swap the scene's skybox to one of list_skyboxes()'s ids. exposure
    (default 1.0) scales overall sky brightness — lower for a darker,
    more oppressive mood; rotation (0-360 degrees) spins the HDRI,
    useful for moving a bright spot out of a bad position. This changes
    indoor ambient light color/intensity too (this scene's ambient mode
    is Skybox-driven), not just a visible backdrop.

    tint_r/tint_g/tint_b (each 0-1, give all three together, default
    neutral 0.5 each if omitted — 0.5 is the shader's NEUTRAL midpoint,
    NOT 0 or 1) color-shifts the whole sky AND the indoor ambient light
    it drives, on top of whichever HDRI is chosen — a real, nearly-free
    extra color lever: push toward red for an ominous/bloody sky, green
    for toxic/alien, etc., without needing a different HDRI at all."""
    if tint_r is not None or tint_g is not None or tint_b is not None:
        if tint_r is None or tint_g is None or tint_b is None:
            return "Error: give all three of tint_r, tint_g, tint_b together, not just some."
        tint = (tint_r, tint_g, tint_b)
    else:
        tint = None
    return _set_skybox(skybox_id=skybox_id, exposure=exposure, rotation=rotation, tint=tint)


@function_tool
def set_fog(
    enabled: bool | None = None,
    color_r: float | None = None,
    color_g: float | None = None,
    color_b: float | None = None,
    density: float | None = None,
    start_distance: float | None = None,
    end_distance: float | None = None,
) -> str:
    """Set the scene's fog (adds depth, obscures distant detail — useful
    for mystery/isolation/dreamlike moods, or to hide a room's limited
    size). color (give r/g/b together, each 0-1) tints the fog itself,
    not the lights. This scene uses Linear mode: start_distance is how
    far from the camera fog BEGINS to appear (nothing before it is
    foggy at all); end_distance is how far until fog reaches FULL
    strength (everything beyond is maximally fogged). CRITICAL: these
    are WORLD-SPACE DISTANCES, not arbitrary numbers — they only make
    sense relative to the actual room's size. If end_distance is larger
    than the room itself, nothing in view ever reaches full-strength fog
    and nothing stays clear either — the whole scene reads as a flat,
    washed-out haze instead of real depth (a bug Eran caught live). Good
    fog needs a real gradient: start_distance should be well INSIDE the
    room (so near objects stay clear), end_distance should be at or
    before the room's far edge (so far objects actually look obscured).
    This tool checks your values against the scene's real diagonal size
    and rejects distances that are clearly too large for this room.
    Omit any field to leave it unchanged."""
    color = None
    if color_r is not None or color_g is not None or color_b is not None:
        if color_r is None or color_g is None or color_b is None:
            return "Error: give all three of color_r, color_g, color_b together, not just some."
        color = (color_r, color_g, color_b)

    if density is not None and not (0 <= density <= 1):
        return f"Rejected: density {density} is out of range [0, 1] (this is Linear-mode fog — small values like 0.01-0.1 are typical)."

    # Guardrail (real bug Eran caught live): fog start/end distances only
    # mean anything relative to the room's actual scale. end_distance
    # bigger than the room's own diagonal means the fog never reaches
    # full strength anywhere visible — reads as flat haze, not depth.
    if start_distance is not None or end_distance is not None:
        bounds = get_scene_bounds()
        if end_distance is not None and end_distance > bounds.diagonal:
            return (
                f"Rejected: end_distance {end_distance} exceeds the scene's actual diagonal size "
                f"({bounds.diagonal:.1f}). Fog that never reaches full strength within the room reads "
                "as a flat wash, not real depth. Pick end_distance at or below the room's scale."
            )
        if start_distance is not None and end_distance is not None and start_distance >= end_distance:
            return f"Rejected: start_distance {start_distance} must be smaller than end_distance {end_distance}."

    _set_fog(
        enabled=enabled,
        color=color,
        density=density,
        start_distance=start_distance,
        end_distance=end_distance,
    )
    return "Updated fog settings."


@function_tool
def delete_light(target: str) -> str:
    """Delete a light THIS AGENT previously created (by instance_id or
    name, from the scene context). Ground rule: the scene's ORIGINAL
    lights can never be deleted, only lights this agent itself added via
    create_light/create_light_near — this is enforced below, not just a
    suggestion. Use this when a light you created isn't working for the
    mood, instead of leaving it in place and stacking more on top."""
    current = _resolve_target(list_scene_transforms(), target)
    if current is None:
        return f"Error: no object with instance_id or name '{target}' found in the scene."
    if not current.name.startswith(AGENT_LIGHT_PREFIX):
        return (
            f"Rejected: '{current.name}' is one of the scene's original lights, not something "
            "this agent created — it cannot be deleted."
        )
    _delete_object(current.instance_id)
    return f"Deleted light '{current.name}' (instance_id={current.instance_id})."


def cleanup_agent_lights() -> list[str]:
    """Delete every light this agent has EVER created (identified by
    AGENT_LIGHT_PREFIX), before a new task starts. Deterministic,
    code-orchestrated, called once at the top of main.py's run() — not an
    agent tool, since 'clear what we added last time, every time' has
    exactly one correct answer, no judgment call involved (same Code vs.
    agent rule as list_scene_transforms()). Decided live with Eran: cross-
    session diff/history tracking (so the agent itself could reason about
    what to keep vs. remove) is parked for a later, persistent-memory
    phase of the project — this is the simple version for now, since each
    `main.py` call is still a fresh, memoryless session. Scene-original
    lights are never touched (same tag check as delete_light). Returns
    the names of whatever got deleted, for visibility."""
    deleted = []
    for obj in list_scene_transforms():
        if obj.name.startswith(AGENT_LIGHT_PREFIX):
            _delete_object(obj.instance_id)
            deleted.append(obj.name)
    return deleted


def reset_post_processing() -> None:
    """Reset ColorAdjustments/Vignette/Fog to a defined NEUTRAL baseline
    before a new task starts — same bug class as light-stacking, caught
    live by Eran: nothing was resetting post-processing between runs, so
    one mood's leftover grading (e.g. noir's saturation=-100, contrast=70,
    vignette=0.6) silently bled into the NEXT mood test, contaminating
    its starting point and likely a real contributor to the eval suite's
    run-to-run score inconsistency. NOTE: this is NOT the original
    imported pack's values — those were already overwritten by this
    session's many mood tests before anyone captured/recorded them, so
    the true original is unrecoverable. This defines a clean, documented,
    consistent baseline going forward instead: 0 exposure/contrast/
    saturation, no color tint, no vignette, fog off. Deterministic,
    code-orchestrated, same reasoning and call site as
    cleanup_agent_lights() — called once at the top of main.py's run()."""
    _set_color_adjustments(post_exposure=0.0, contrast=0.0, saturation=0.0, color_filter=(1.0, 1.0, 1.0))
    _set_vignette(intensity=0.0, smoothness=0.4)
    _set_fog(enabled=False, color=(1.0, 1.0, 1.0), density=0.0, start_distance=0.0, end_distance=100.0)
