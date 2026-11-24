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
    delete_light,
    set_color_adjustments,
    set_fog,
    set_light_properties,
    set_object_transform,
    set_vignette,
)
from unity_mood_lighting_agent.unity_bridge import (
    get_color_adjustments,
    get_fog,
    get_light_properties,
    get_scene_bounds,
    get_vignette,
    list_scene_transforms,
)

agent = Agent(
    name="MoodLightingAgent",
    instructions=(
        "You adjust a Unity scene's lighting AND overall rendering to "
        "match a requested mood (e.g. 'horror', 'cozy'). You will be "
        "given the current scene's objects with their instance_id, "
        "position, and rotation, PLUS a screenshot of what the scene "
        "currently looks like — use the image to actually see the space "
        "(where shadows already fall, how open/enclosed it is, what mood "
        "it already reads as) rather than reasoning from coordinates "
        "alone. "
        "IMPORTANT SCOPE AND STRATEGY: you can ONLY control lighting and "
        "rendering — you cannot add, remove, or change geometry, props, "
        "or decorations. Some moods imply objects the scene doesn't have "
        "(e.g. 'festive' implying decorations, 'post-apocalyptic' "
        "implying visible wreckage) — you cannot add those objects, so "
        "your job is to sell the FEELING of the mood through atmosphere "
        "alone: color story, contrast, shadow shape, and light color/"
        "placement. Don't play it safe with moderate values when a mood "
        "is extreme — a genuinely post-apocalyptic or horror scene needs "
        "COMMITTED values (strong desaturation, harsh single-direction "
        "light with deep black shadows, heavy fog), not a timid nudge in "
        "the right direction. For 'colorful'/'festive'-type moods with no "
        "decorations available, create MULTIPLE lights in different "
        "saturated colors (not just one) to build a colorful atmosphere "
        "purely from light. Combine levers — individual lights AND "
        "color grading AND vignette AND fog together, not just one — "
        "this is usually what separates a mood that barely reads from "
        "one that clearly does. "
        "Use set_object_transform to move/rotate "
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
        "lights for selling a mood. If a light you created isn't working "
        "for the mood, use delete_light to remove it instead of leaving "
        "it in place and adding more on top — you can only delete lights "
        "you created yourself, never the scene's original lights. You "
        "don't have to provide every value each call — omit what you "
        "don't want to change."
    ),
    model="gpt-5.4-mini",
    tools=[
        set_object_transform,
        set_light_properties,
        create_light,
        create_light_near,
        delete_light,
        aim_light_at,
        set_color_adjustments,
        set_vignette,
        set_fog,
    ],
)


def get_scene_context() -> str:
    """Fetches the current scene state — independent of any task, this is
    the code-orchestrated 'find' step (not a tool the agent calls). This
    is ground truth re-read fresh every call, NOT memory — it has no
    history, it's just what Unity currently is. Includes current
    post-processing state (ColorAdjustments/Vignette/Fog) alongside
    object transforms: found live (Eran caught it) that without this, the
    agent reasoned about each render lever (lights, exposure, vignette,
    fog) in isolation, each individually 'reasonable for a tense mood,'
    and ended up stacking several darkening/desaturating effects on top
    of each other into an unreadable, overly flat result. Seeing what's
    ALREADY applied lets it reason about cumulative effect instead."""
    scene = list_scene_transforms()
    transforms_section = "\n".join(
        f"- {o.name} (instance_id={o.instance_id}): "
        f"pos=({o.pos_x}, {o.pos_y}, {o.pos_z}), "
        f"rot=({o.rot_x}, {o.rot_y}, {o.rot_z})"
        + (
            f", LIGHT intensity={(lp := get_light_properties(o.instance_id)).intensity}, "
            f"color=({lp.color_r}, {lp.color_g}, {lp.color_b}), "
            f"color_temperature={lp.color_temperature}K, "
            f"bounce_intensity={lp.bounce_intensity}"
            if o.is_light
            else ""
        )
        for o in scene
    )

    bounds = get_scene_bounds()
    bounds_section = (
        "Scene bounding box (real spatial grounding — any position you give to "
        "create_light/set_object_transform outside this range will be rejected):\n"
        f"- x: {bounds.min_x:.1f} to {bounds.max_x:.1f}\n"
        f"- y: {bounds.min_y:.1f} to {bounds.max_y:.1f}\n"
        f"- z: {bounds.min_z:.1f} to {bounds.max_z:.1f}"
    )

    color = get_color_adjustments()
    vignette = get_vignette()
    fog = get_fog()
    post_processing_section = (
        "Current scene-wide post-processing (these effects STACK with "
        "each other and with individual light changes — if several are "
        "already pushing the scene darker/colder/more desaturated, adding "
        "more on top often over-darkens and flattens the image instead of "
        "improving the mood; consider whether you should pull one lever "
        "back rather than pushing a different one further):\n"
        f"- ColorAdjustments: post_exposure={color.post_exposure}, contrast={color.contrast}, "
        f"saturation={color.saturation}, color_filter=({color.color_filter_r}, {color.color_filter_g}, {color.color_filter_b})\n"
        f"- Vignette: intensity={vignette.intensity}, smoothness={vignette.smoothness}\n"
        f"- Fog: enabled={fog.enabled}, density={fog.density}, "
        f"start_distance={fog.start_distance}, end_distance={fog.end_distance}, "
        f"color=({fog.color_r}, {fog.color_g}, {fog.color_b})"
    )

    return f"{transforms_section}\n\n{bounds_section}\n\n{post_processing_section}"
