"""
agent.py — the lighting agent and its tools.

Scene context (list_scene_transforms()) is injected into the prompt by
get_scene_context(), NOT fetched by the agent via a tool call — this is the
locked-in code-vs-agent split from step 5 / README: listing has no
ambiguity, so it's code's job; deciding what to change for a mood is the
agent's job.

Structured output (2026-11-24, Eran's call): the agent itself now returns
LightingDecision instead of free text, same reasoning-first technique
already proven on the judge (judge.py's MoodJudgement). Field order is
generation order — mood_breakdown FIRST forces the agent to commit to a
concrete reading of the task (genre/contrast/visual choices) before it
reasons about what to change, then reasoning plans the actual tool calls,
then changes_summary is a REQUIRED account of what it did. This directly
fixes a real observed bug: the agent sometimes returned a bare "Done." as
its free-text final_output with zero description of what changed, which
made main.py's attempt_history (the judge-feedback-across-retries record)
useless for that attempt. A required structured field can't be empty.
"""

from enum import Enum

from agents import Agent
from pydantic import BaseModel, Field

from unity_mood_lighting_agent.spatial_agent import format_spatial_breakdown_for_prompt, load_cached_spatial_breakdown
from unity_mood_lighting_agent.tools import (
    aim_light_at,
    create_light,
    create_light_near,
    delete_light,
    set_ambient,
    set_color_adjustments,
    set_fog,
    set_light_properties,
    set_object_transform,
    set_vignette,
)
from unity_mood_lighting_agent.unity_bridge import (
    get_active_scene,
    get_ambient,
    get_color_adjustments,
    get_fog,
    get_light_properties,
    get_scene_bounds,
    get_vignette,
    list_scene_transforms,
)


class ContrastLevel(str, Enum):
    """Enum, not free text — deterministic for later analysis (e.g.
    correlating chosen contrast with pass/fail) and forces the agent to
    commit to one of three concrete readings instead of hedging."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class StrategyArchetype(str, Enum):
    """A small, closed set of lighting-strategy archetypes any mood can
    be classified into, instead of one generic rule set trying (and
    failing) to serve every mood, or a lookup table keyed by literal mood
    strings that only covers moods we've already enumerated. New/unseen
    moods still classify into one of these 4 via the agent's own
    reasoning — this is what makes it generalize."""

    RESTRAINED = "restrained"
    EXPANSIVE = "expansive"
    SOFT_AMBIENT = "soft_ambient"
    NATURALISTIC = "naturalistic"


class MoodBreakdown(BaseModel):
    """The agent's own concrete interpretation of the task, generated
    FIRST and before any tool calls — forces committing to a reading of
    the mood instead of reasoning loosely from the raw task string on
    every attempt."""

    strategy_archetype: StrategyArchetype = Field(description="Classify the mood into ONE archetype (see the ARCHETYPES section of your instructions for what each one means and which levers to use).")
    genre: str = Field(description="Short label for the mood, e.g. 'festive holiday party', 'noir detective', 'post-apocalyptic'.")
    target_contrast: ContrastLevel = Field(description="The contrast level this mood calls for.")
    key_visual_choices: str = Field(description="1-2 sentences: the specific color story and lighting approach that will sell this mood (e.g. 'warm key light + saturated red/green/gold accents, minimal fog, soft shadows').")


class LightingDecision(BaseModel):
    """Structured final output. Field order is generation order — same
    reasoning-first technique as judge.py's MoodJudgement, extended one
    step earlier: commit to mood_breakdown BEFORE reasoning about tool
    calls, then reason BEFORE summarizing. changes_summary is REQUIRED
    and must be non-trivial — this is what main.py logs into
    attempt_history for the next retry, a bare 'Done.' is not useful
    there and shouldn't be possible with a described required field."""

    mood_breakdown: MoodBreakdown
    reasoning: str = Field(description="Given the mood_breakdown, the current scene state, and any previous attempt's score/feedback, explain what you are about to change and why. Write this BEFORE making tool calls.")
    changes_summary: str = Field(description="After making your tool calls, concretely describe what you changed this attempt (which lights, which values, which post-processing levers) — specific enough that a reviewer could tell what happened without re-reading the scene. Never just 'Done' or similarly empty.")


agent = Agent(
    name="MoodLightingAgent",
    instructions=(
        "PERSONA: You are a world-class lighting director, a veteran of "
        "high-budget film and game productions, known across the industry "
        "for mastering mood through light placement, color theory, and "
        "restraint. You have strong opinions about what makes a lighting "
        "setup read as cheap versus convincing, and you do not settle for "
        "a timid, half-committed result. You are demanding of your own work.\n\n"
        "TASK: adjust a Unity scene's lighting and overall rendering to "
        "match a requested mood. You are given the scene's objects "
        "(instance_id, position, rotation, and for lights: intensity, "
        "color, color temperature) plus a screenshot of the current Game "
        "view — use the image to actually see the space (existing shadows, "
        "how open/enclosed it reads) rather than reasoning from numbers alone.\n\n"
        "SCOPE: you control ONLY lighting and rendering (individual lights, "
        "color grading, vignette, fog). You cannot add, remove, or move "
        "geometry, props, or decorations. When a mood implies objects the "
        "scene doesn't have (e.g. 'festive' implying decorations), your job "
        "is to sell the FEELING through atmosphere alone — you are not "
        "failing by lacking props that are out of scope.\n\n"
        "ARCHETYPES: before deciding what to change, classify the mood's "
        "genre into one of these 4 broad categories — this is a compass "
        "for the FEELING you're aiming for, not a fixed recipe. Use your "
        "own judgment and creativity as a lighting director for exactly "
        "how to achieve it with the tools available — there is no "
        "'correct' set of values.\n"
        "- RESTRAINED covers two different feelings depending on genre: "
        "THREAT/DRAMATIC (horror, noir, thriller, eerie lab — a sense of "
        "danger or tension, typically wants very high contrast) and "
        "DESOLATE/ATMOSPHERIC (post-apocalyptic, ruins, fog-bound places "
        "with no sense of lurking threat — desolation without drama, "
        "typically wants MEDIUM contrast, not very high; pushing it "
        "toward black reads as a broken render, not stronger desolation).\n"
        "- EXPANSIVE (festive, carnival, celebration, playful): typically "
        "wants real color variety, not just one or two colors.\n"
        "- SOFT_AMBIENT (cozy, zen, dreamlike, romantic): typically wants "
        "low contrast, diffuse light.\n"
        "- NATURALISTIC (golden hour, daylight, sunset): typically wants "
        "one directional, sun-like light source and realistic color "
        "temperature.\n\n"
        "CREATIVE FREEDOM: beyond the genre/contrast guidance above, you "
        "have real creative freedom in which lights, colors, ranges, "
        "shadow types, and global grading you use to sell each mood. One "
        "concrete fact, not a style prescription: for a genuinely "
        "dramatic/high-contrast mood, a SINGLE light needs to clearly "
        "dominate — pull the SCENE's other existing lights' intensity "
        "near-zero (not just lower), not left at a similar strength to "
        "your key light, and pull set_ambient's intensity down toward 0 "
        "too (it's a uniform fill applied everywhere regardless of any "
        "light's range, and sits at a flattening 1.0 by default — a dark "
        "zone cannot read as genuinely dark while it's high, no matter "
        "what any individual light does). Two deterministic checks run "
        "on every attempt purely to catch EXTREME failures on either "
        "side — a frame gone fully black/unreadable, or (only for "
        "high-contrast moods) a frame so flat it has no real brightness "
        "variation, OR has a wide variation but its dark zone still "
        "isn't actually dark. They are a safety net against degenerate "
        "results, not a style prescription — clearing them is not the "
        "same as succeeding at the mood. Push as boldly as you judge the "
        "mood actually needs.\n\n"
        "TOOLS: set_object_transform repositions/rotates a LIGHT (never "
        "geometry/props, those are out of scope per above). "
        "set_light_properties changes an existing light's "
        "intensity/color/color-temperature (Kelvin, lower = warmer)/bounce/"
        "range/spot_angle/shadow_type. range (Point/Spot) is how far the "
        "light reaches — small vs large changes whether it reads as a "
        "contained pool or floods the whole room, relative to "
        "get_scene_bounds()'s diagonal. spot_angle (Spot) is cone width, "
        "degrees. shadow_type ('none'/'hard'/'soft') is whether a light "
        "casts a shadow at all — create_light defaults new lights to "
        "'soft', but check get_scene_context's reported shadow_type on "
        "EXISTING lights, some may be 'none'. "
        "To add a light, prefer create_light_near (anchors and pre-aims it "
        "to a given object with an xyz offset) over plain create_light + "
        "aim_light_at, which you should only use when no single object is "
        "a sensible anchor. set_color_adjustments/set_vignette/set_fog "
        "control scene-wide rendering and matter as much as individual "
        "lights. If a light you created isn't serving the mood, delete_light "
        "it rather than leaving it and piling more on top — you can only "
        "delete lights you created, never the scene's originals. Omit any "
        "parameter you don't want to change.\n\n"
        "OUTPUT: produce mood_breakdown first (archetype, genre, contrast "
        "level, and visual approach before reasoning), then reasoning "
        "(your plan, grounded in the current state and any prior attempt's "
        "outcome), then changes_summary (a specific, concrete account of "
        "what you changed this attempt)."
    ),
    model="gpt-5.4-mini",
    output_type=LightingDecision,
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
        set_ambient,
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
            f"bounce_intensity={lp.bounce_intensity}, "
            f"range={lp.range}, spot_angle={lp.spot_angle}, "
            f"shadow_type={lp.shadow_type}"
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
    ambient = get_ambient()
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
        f"color=({fog.color_r}, {fog.color_g}, {fog.color_b})\n"
        f"- Ambient intensity: {ambient.intensity} (uniform fill applied to the WHOLE "
        "scene regardless of any individual light — Unity's default is 1.0; this is "
        "usually why a dark zone won't go near-black even with a light's range/"
        "intensity pulled right down. Low (0.0-0.15) for dramatic moods, near-default "
        f"for diffuse/soft ones.)"
    )

    spatial_breakdown = load_cached_spatial_breakdown(get_active_scene().path)
    spatial_section = (
        format_spatial_breakdown_for_prompt(spatial_breakdown)
        if spatial_breakdown is not None
        else ""  # no cache yet for this scene — main.py's run() ensures one exists before any attempt
    )

    return f"{transforms_section}\n\n{bounds_section}\n\n{post_processing_section}\n\n{spatial_section}"
