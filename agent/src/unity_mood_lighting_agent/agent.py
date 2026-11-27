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
    list_skyboxes,
    set_ambient,
    set_color_adjustments,
    set_fog,
    set_light_properties,
    set_object_transform,
    set_skybox,
    set_vignette,
)
from unity_mood_lighting_agent.unity_bridge import (
    get_active_scene,
    get_ambient,
    get_baseline_brightness,
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


class Lever(str, Enum):
    """Every category of change available this attempt — enum, not free
    text, specifically so LightingDecision can force an explicit
    per-lever accounting (2026-11-25, Eran's call): found live via a
    full-trace diagnostic that the agent kept reaching for the exact
    same 1-2 levers (intensity + global grading) attempt after attempt,
    never touching position/rotation/skybox even once across 5 attempts
    on the same case, DESPITE being told explicitly to 'try a different
    lever' when its score plateaued. Prose nudges alone didn't fix this.
    This enum doesn't teach what each lever does (that's in the
    instructions below) — it forces the agent to go through all of them
    explicitly, every attempt, rather than silently defaulting to a
    narrow habitual subset."""

    POSITION = "position"
    ROTATION = "rotation"
    INTENSITY = "intensity"
    FALLOFF_RANGE = "falloff_range"
    COLOR = "color"
    AMBIENT = "ambient"
    SKYBOX = "skybox"
    GLOBAL_GRADING = "global_grading"  # color_adjustments/vignette/fog together


class LeverUsage(BaseModel):
    """One lever's accounting for this attempt. changed=False still
    REQUIRES a real reason — 'I didn't need it' is a legitimate reason,
    silently skipping it is not possible with this schema."""

    lever: Lever
    changed: bool
    note: str = Field(description="If changed=True: what you did with this lever. If changed=False: why you judged it unnecessary THIS attempt — be honest, not just 'not needed'.")


class MoodBreakdown(BaseModel):
    """The agent's own concrete interpretation of the task, generated
    FIRST and before any tool calls — forces committing to a reading of
    the mood instead of reasoning loosely from the raw task string on
    every attempt."""

    strategy_archetype: StrategyArchetype = Field(description="Classify the mood into ONE archetype (see the ARCHETYPES section of your instructions for what each one means and which levers to use).")
    genre: str = Field(description="Short label for the mood, e.g. 'festive holiday party', 'noir detective', 'post-apocalyptic'.")
    target_contrast: ContrastLevel = Field(description="The contrast level this mood calls for.")
    key_visual_choices: str = Field(description="1-2 sentences: the specific color story and lighting approach that will sell this mood (e.g. 'warm key light + saturated red/green/gold accents, minimal fog, soft shadows').")
    target_key_fill_ratio: float = Field(
        description="2026-11-27: the key:fill INTENSITY ratio you're committing to, using the real photography/"
        "cinematography lighting-ratio convention (not a vague percentage) — e.g. 3.0 means your key light's real "
        "intensity should end up ~3x your fill's. Rough guide: ~2-3 for soft/low-contrast moods (soft_ambient, "
        "naturalistic), ~4-6 for medium-contrast (most restrained/desolate moods), ~7-10+ for high-contrast horror/"
        "noir/thriller. This is a number you commit to BEFORE setting light intensities, not a description of what "
        "you already did."
    )


class LightRole(str, Enum):
    """Studio-lighting role for a single light, EVERY light in the scene,
    every attempt (2026-11-26, Eran's call) — not a free-text description.
    Direct response to a real failure the new strict judge persona caught:
    the agent keeps producing scenes with small self-illuminating glows
    (a screen, a ceiling panel) while the room around them stays
    near-black, and prose instructions about 'key/fill/rim' alone weren't
    making it actually reason about which light is doing which job. Same
    fix pattern as the Lever enum: force explicit per-light accounting
    instead of hoping prose sticks.

    Deliberately NOT capped at one KEY per attempt (Eran's call) — some
    moods may genuinely want two strong competing keys (e.g. a double
    exposure or a two-source dramatic scene). Not enforced as a guardrail
    yet; observe real usage first, decide whether a cap is ever needed
    once there's real data, not a guess."""

    KEY = "key"  # the dominant light. Must visibly shape the SPACE around it (floor/wall gradient, real shadow falloff), not just glow at its own position.
    FILL = "fill"  # secondary, keeps shadows readable without flattening the key's drama. Roughly 10-30% of the key's intensity — never fully off, never competing with the key.
    RIM = "rim"  # edge/backlight separation, pulls a subject's silhouette off the background. Usually the weakest of the three in intensity.
    PRACTICAL = "practical"  # a light that exists to glow ITSELF (a screen, a sign, a lamp fixture) rather than to illuminate the room around it. Legitimate role, but does NOT count as lighting the scene — a frame with only PRACTICAL lights and a black room is the exact failure mode the judge now explicitly fails.
    UNUSED = "unused_this_attempt"  # exists in the scene, deliberately not touched or leaned on this attempt


class LightRoleAssignment(BaseModel):
    """One light's role for this attempt. Every light currently in the
    scene gets an entry — exhaustive, same as LeverUsage — specifically so
    main.py (and future tooling) can see how the agent is mapping the
    scene's lights, not just infer it from raw intensity/color numbers."""

    instance_id: str = Field(description="The light's instance_id from the scene context.")
    role: LightRole
    reasoning: str = Field(
        description="Why this role for this light. If role=KEY: describe HOW it shapes the geometry "
        "around it (what falls in its pool of light, where the falloff/shadow boundary lands) — "
        "'it's bright' is not an answer, 'it's a screen glowing in a dark room' is PRACTICAL, not KEY. "
        "If role=UNUSED: say why this light isn't needed for this mood, not just 'not needed'."
    )


class JudgeFeedbackAcknowledgment(BaseModel):
    """2026-11-27, Eran's call — direct fix for the suspected agent<->judge
    language gap: the judge's recommended_levers (judge.py) already use
    the SAME Lever/LightRole vocabulary this agent uses for itself, and
    main.py already puts them in attempt_history as plain prose — but
    nothing forced the agent to actually ENGAGE with each one, the same
    'prose nudges alone don't stick' problem that light_role_assignments
    and lever_accounting were both built to fix. One entry per
    recommendation the JUDGE gave after your LAST attempt (not a
    guardrail rejection, an actual judge call) — exhaustive, same
    forcing-function pattern as LeverUsage/LightRoleAssignment. Empty
    list is correct and expected on attempt 1, or any attempt whose
    predecessor never reached the judge."""

    lever: Lever | None = Field(default=None, description="Echo back the recommendation's lever, if it was a numeric/positional one (must match one the judge actually gave you).")
    suggested_role: LightRole | None = Field(default=None, description="Echo back the recommendation's role swap, if it was one instead of a lever — exactly one of lever/suggested_role should be set, matching the judge's own recommendation shape.")
    light_id: str | None = Field(default=None, description="Which light the recommendation named, if any (None for scene-wide levers like ambient/skybox/global_grading).")
    addressed: bool = Field(description="True if you actually acted on this recommendation this attempt (verified against the real scene diff, not just your intent). False is a legitimate answer if you deliberately overrode the judge's suggestion — say why in `note`.")
    note: str = Field(description="If addressed=True: what you actually did about it. If addressed=False: your real reason for not following it THIS attempt — 'I didn't get to it' is honest, a vague restatement of the recommendation is not.")


class LightingDecision(BaseModel):
    """Structured final output. Field order is generation order — same
    reasoning-first technique as judge.py's MoodJudgement, extended one
    step earlier: commit to mood_breakdown BEFORE reasoning about tool
    calls, then reason BEFORE summarizing. changes_summary is REQUIRED
    and must be non-trivial — this is what main.py logs into
    attempt_history for the next retry, a bare 'Done.' is not useful
    there and shouldn't be possible with a described required field.

    judge_feedback_acknowledgments (2026-11-27, Eran's call): placed
    BEFORE reasoning — explicitly engaging with the judge's last
    recommendations has to inform the plan, not describe it after the
    fact. This is the forcing-function half of closing the agent<->judge
    language gap; main.py's job is the other half (cross-checking
    addressed=True claims against the real diff, same principle already
    applied to lever_accounting).

    light_role_assignments (2026-11-26, Eran's call): placed right after
    reasoning, same forcing-function pattern as lever_accounting below,
    added for the same reason — prose instructions about key/fill/rim
    alone weren't making the agent actually reason about which light is
    doing which job. Not yet cross-verified against real render data the
    way lever_accounting is (that needs a per-light ROI brightness check,
    flagged for later) — for now this is a planning aid and a visibility
    tool, not a guardrail.

    lever_accounting (2026-11-25, Eran's call): placed AFTER reasoning
    so the per-lever checklist is informed by the plan, and BEFORE
    changes_summary so the summary has to stay consistent with what the
    checklist says actually happened. main.py also independently
    verifies this against REAL scene-state diffs — see
    docs/mood-test-results.md's note on why self-reported lever usage
    isn't trusted alone anymore."""

    mood_breakdown: MoodBreakdown
    judge_feedback_acknowledgments: list[JudgeFeedbackAcknowledgment] = Field(
        default_factory=list,
        description="One entry per recommendation the JUDGE gave after your last attempt (empty list if attempt 1 "
        "or your last attempt never reached the judge). Engage with EVERY recommendation it gave you, exhaustively "
        "— this is what proves you understood the feedback, not just read it.",
    )
    reasoning: str = Field(description="Given the mood_breakdown, the current scene state, and any previous attempt's score/feedback, explain what you are about to change and why. Write this BEFORE making tool calls.")
    light_role_assignments: list[LightRoleAssignment] = Field(
        description="EVERY light in the scene by the end of this attempt — every light from the scene "
        "context PLUS any you create this attempt via create_light — each assigned a LightRole with real "
        "reasoning. This is your studio-lighting plan, made explicit: decide which light is doing the "
        "KEY's work, which is FILL, which is RIM, which is just a PRACTICAL prop glow, and which you're "
        "genuinely not using. Plan this BEFORE making tool calls, same as reasoning — it should drive "
        "what you actually do with each light, not describe it after the fact."
    )
    lever_accounting: list[LeverUsage] = Field(
        description="EVERY lever in the Lever enum, every attempt, each marked changed=True/False with a real "
        "reason. Levers are NOT mutually exclusive — combining several in one attempt (e.g. position + "
        "falloff + skybox together) is the normal expected move, not an edge case. If a prior attempt's "
        "feedback said to try something different, this is where that actually has to show up as changed=True "
        "on a NEW lever, not just a reworded reason for skipping it again."
    )
    changes_summary: str = Field(description="After making your tool calls, concretely describe what you changed this attempt (which lights, which values, which post-processing levers) — specific enough that a reviewer could tell what happened without re-reading the scene. Never just 'Done' or similarly empty.")


agent = Agent(
    name="MoodLightingAgent",
    instructions=(
        "PERSONA: You are a world-class lighting director — decades across "
        "film and game production, known for mastering mood through light "
        "placement, color, and restraint. You don't settle for a timid, "
        "half-committed result.\n\n"
        "TASK: adjust a Unity scene's lighting and rendering to match a "
        "requested mood. You get the scene's objects (position, rotation, "
        "and for lights: intensity/color/color temperature) plus a "
        "screenshot of the current Game view — use the image to actually "
        "see the space, not just the numbers.\n\n"
        "SCOPE: lighting and rendering ONLY (lights, color grading, "
        "vignette, fog). No geometry/props/decorations. If a mood implies "
        "objects the scene lacks, sell the FEELING through atmosphere — "
        "missing props are out of scope, not a failure.\n\n"
        "ARCHETYPES: classify the mood's genre into one of these 4 — a "
        "compass for the feeling, not a fixed recipe:\n"
        "- RESTRAINED/THREAT (horror, noir, thriller, eerie lab): danger or "
        "tension, very high contrast, high key:fill ratio.\n"
        "- RESTRAINED/DESOLATE (post-apocalyptic, ruins, fog-bound empty "
        "places, no lurking threat): desolation without drama, MEDIUM "
        "contrast — pushing toward black reads as a broken render, not "
        "stronger desolation.\n"
        "- EXPANSIVE (festive, carnival, celebration): real color variety, "
        "not just one or two colors.\n"
        "- SOFT_AMBIENT (cozy, zen, dreamlike, romantic): low contrast, "
        "diffuse light, low key:fill ratio.\n"
        "- NATURALISTIC (golden hour, daylight, sunset): one directional "
        "sun-like source, realistic color temperature.\n\n"
        "THREE-POINT LIGHTING: build from KEY + FILL + RIM, not 'one light, "
        "kill everything else'. Commit to this explicitly per light in "
        "light_role_assignments, as a plan BEFORE tool calls:\n"
        "- KEY: the single dominant light. Decides color/direction/"
        "hardness; every other lever is built around it. Must visibly "
        "shape the SPACE around it (real floor/wall falloff gradient, a "
        "real shadow boundary), not just glow at its own position. SIZE "
        "ITS RANGE AGAINST THE SCENE DIAGONAL (given below) — at least "
        "25-40% of it, regardless of mood; smaller reads as 'a bright dot "
        "in the dark' no matter the intensity.\n"
        "- FILL: dimmer secondary light(s), target_key_fill_ratio sets the "
        "real key:fill INTENSITY ratio (standard photography/cinema "
        "convention) — ~2-3 for soft moods, ~4-6 medium-contrast, ~7-10+ "
        "for horror/noir/thriller. Never near 1:1 (flat) or fill=0 (reads "
        "as a flat dark wash, not 'more dramatic'). set_ambient is a "
        "SEPARATE, scene-wide lever (see below) — it still usually wants "
        "to go near 0 for dramatic moods regardless of your fill ratio.\n"
        "- RIM (optional, strong payoff when geometry allows): positioned "
        "behind/beside the subject, aimed back toward camera — traces an "
        "edge separating subject from a dark background. The most "
        "reliable way to make a dark scene read as deliberate, not just "
        "underlit.\n"
        "- PRACTICAL: a light that glows ITSELF (screen, sign, fixture) "
        "rather than illuminating the room. Legitimate, but never your "
        "only working light — a frame of small glowing props with the "
        "room itself near-black is a clear judge FAIL regardless of how "
        "atmospheric it looks.\n\n"
        "KEY LIGHT MUST BE VERIFIED, NOT ASSUMED: it only counts as "
        "dominant if the frame's measured BRIGHT zone clears this scene's "
        "untouched baseline brightness (reported below) by a real margin "
        "— a big intensity number means nothing if grading/vignette/fog "
        "eat the gain back down. A guardrail checks this before the judge "
        "call; if it rejects, push key intensity further, narrow its "
        "range (same intensity lands harder in a tighter pool), or ease "
        "off a global grading value that's flattening what the light "
        "already created — not just 'bigger number again'. A few "
        "deterministic checks also catch extreme failures (fully black/"
        "unreadable, or for high-contrast moods, no real brightness "
        "spread) — they're a safety net against degenerate results, not a "
        "style target; clearing them isn't the same as succeeding at the "
        "mood.\n\n"
        "RENDER PIPELINE ORDER: lights render FIRST — the only stage that "
        "creates LOCAL contrast (one area bright, another dark). Post-"
        "processing (exposure -> contrast -> saturation/color_filter -> "
        "vignette -> fog) applies after, as a chain where each stage "
        "transforms the previous stage's OUTPUT, not the original render "
        "— it reshapes the WHOLE frame globally and cannot invent new "
        "local contrast. Measured live on this scene: contrast=68 + "
        "saturation=-28 + color_filter together cut mean brightness 38 to "
        "~10 (survivable alone), but adding vignette=0.5 on top crushed "
        "it to ~0.4 (full black) — stages compound MULTIPLICATIVELY, not "
        "additively, so 2-3 'moderate' knobs stacked together is often "
        "far more severe than any one suggests alone. Decide light "
        "placement/intensity first (that's what defines the mood's real "
        "contrast), THEN add grading as a light finishing touch on top — "
        "not both escalating independently every retry without checking "
        "the combination.\n\n"
        "EXISTING LIGHTS ARE NOT A CONSTRAINT: the scene's original "
        "fixtures were placed by an artist for general room lighting, not "
        "your mood. If they can't serve the mood from where they sit, "
        "don't just retune their intensity — delete one (delete_light) or "
        "pull it near-zero and create_light_near a NEW light exactly "
        "where the mood needs one. A from-scratch light is equally valid, "
        "not a last resort.\n\n"
        "LEVER MENU — 8 independent, NOT mutually exclusive levers; "
        "combining several per attempt is normal. Pushing the same 1-2 "
        "levers harder when the score isn't moving is the single most "
        "common mistake — reach for a genuinely different lever, not a "
        "stronger version of the same one:\n"
        "- POSITION / ROTATION (set_object_transform, or aim_light_at for "
        "a precise look-at): where/which-way a light sits changes pool "
        "size, grazed surfaces, and shadow shape.\n"
        "- INTENSITY (set_light_properties): calibrate against the "
        "scene's baseline brightness reported below AND target_key_"
        "fill_ratio, not an arbitrary number.\n"
        "- FALLOFF_RANGE (set_light_properties' range/spot_angle): "
        "contained pool vs floods-the-room, independent of intensity.\n"
        "- COLOR (set_light_properties' color r/g/b): use for ALL "
        "tinting — warm, cool, toxic green, alien purple, neon. Leave "
        "color_temperature alone: it only moves along the real blackbody "
        "curve (orange->white->blue, no green/purple/cyan), and it "
        "MULTIPLIES with color rather than adding — touching both on one "
        "light silently double-dims it. RGB alone covers every mood.\n"
        "- AMBIENT (set_ambient): scene-wide uniform floor under every "
        "shadow, defaults to a flattening 1.0 — low (0.0-0.15) for "
        "dramatic moods, near-default for diffuse/soft ones.\n"
        "- SKYBOX (list_skyboxes, set_skybox): changes indoor ambient "
        "light color/intensity when ambient mode is Skybox-driven (check "
        "get_scene_context) — a real lever even indoors.\n"
        "- GLOBAL_GRADING (set_color_adjustments/set_vignette/set_fog "
        "together): scene-wide, stacks with every light change.\n\n"
        "TOOLS: shadow_type ('none'/'hard'/'soft') — create_light defaults "
        "to 'soft', but check existing lights' real shadow_type, some are "
        "'none'. Prefer create_light_near (anchors + pre-aims to an "
        "object) over create_light + aim_light_at, which you should only "
        "need when no object is a sensible anchor. delete_light only "
        "works on lights you created, never the scene's originals. Omit "
        "any parameter you don't want to change.\n\n"
        "OUTPUT: mood_breakdown first (archetype, genre, contrast, "
        "target_key_fill_ratio, visual approach), then "
        "judge_feedback_acknowledgments (one entry per recommendation the "
        "JUDGE gave after your LAST attempt — empty if this is attempt 1 "
        "or your last attempt never reached the judge; this has to "
        "actually inform the reasoning that follows, not just restate "
        "what you were told), then reasoning (your plan, grounded in "
        "current state and any prior feedback), then "
        "light_role_assignments, then lever_accounting (every Lever enum "
        "entry, changed or not, with a real reason — checked against real "
        "scene state, not taken on faith), then changes_summary (specific "
        "account of what you changed, never just 'Done')."
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
        list_skyboxes,
        set_skybox,
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
        f"- z: {bounds.min_z:.1f} to {bounds.max_z:.1f}\n"
        f"- SCENE DIAGONAL: {bounds.diagonal:.1f} world units, corner to corner. "
        "Use this directly to size a light's `range`: a KEY light's range should "
        "typically be AT LEAST 25-40% of this diagonal to visibly shape a "
        "meaningful portion of the room (reach the floor/walls with a real "
        "gradient) rather than only its own small local radius. A range much "
        "smaller than that, even at high intensity, reads as 'a bright dot in "
        "the dark' no matter how dramatic the mood calls for — this is a sizing "
        "rule, not a mood choice; it applies the same way to every archetype."
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

    baseline_brightness = get_baseline_brightness()
    brightness_section = (
        f"Scene's baseline render brightness (measured once, untouched scene, before any mood edits): "
        f"mean={baseline_brightness.mean_brightness}/255, p90={baseline_brightness.p90}/255. "
        "Use this as your calibration anchor for 'how bright is bright' in THIS scene's own units — "
        "for a genuinely dominant dramatic key light, the ATTEMPT's own rendered p90 should end up "
        "clearly, measurably above this baseline p90, not just relatively brighter than your other "
        "lights. An intensity number alone means nothing without this reference; this works even on "
        "a scene with no existing lights, where baseline would simply measure near-black."
        if baseline_brightness is not None
        else ""
    )

    return f"{transforms_section}\n\n{bounds_section}\n\n{post_processing_section}\n\n{spatial_section}\n\n{brightness_section}"
