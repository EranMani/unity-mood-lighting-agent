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


class LightingDecision(BaseModel):
    """Structured final output. Field order is generation order — same
    reasoning-first technique as judge.py's MoodJudgement, extended one
    step earlier: commit to mood_breakdown BEFORE reasoning about tool
    calls, then reason BEFORE summarizing. changes_summary is REQUIRED
    and must be non-trivial — this is what main.py logs into
    attempt_history for the next retry, a bare 'Done.' is not useful
    there and shouldn't be possible with a described required field.

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
        "shadow types, and global grading you use to sell each mood.\n\n"
        "THREE-POINT LIGHTING (classic film/game lighting-director "
        "structure — use it, don't improvise a flat substitute): for any "
        "THREAT/DRAMATIC mood, build from KEY + FILL + RIM, not just "
        "'one light, kill everything else'. Your light_role_assignments "
        "output field is where you commit to this explicitly, per light "
        "— write it as a real plan BEFORE your tool calls, not a "
        "description of what you already did:\n"
        "- KEY: the single dominant light. Decides the mood's color, "
        "direction, and hardness. This is what the scene's other levers "
        "(position/rotation/range/color) should be built around. It "
        "must visibly shape the SPACE around it — a real falloff "
        "gradient on the floor/walls, a real shadow boundary — not just "
        "glow brightly at its own position while everything nearby "
        "stays black. SIZE ITS RANGE AGAINST THE SCENE DIAGONAL (given "
        "in your scene context) — at least 25-40% of it. This is a "
        "physical sizing rule, not a mood decision: it applies whether "
        "the mood is dramatic or soft, and a range far below this reads "
        "as 'a bright dot in the dark' regardless of how high the "
        "intensity is.\n"
        "- FILL: a much dimmer secondary light (or the scene's OTHER "
        "existing lights, retuned) — roughly 10-30% of the key's "
        "intensity, never fully off. Its job is to keep the shadow side "
        "of the frame barely readable so the eye can still tell what "
        "it's looking at. Pulling fill all the way to zero does not read "
        "as 'more dramatic' — it reads as a flat, undifferentiated dark "
        "wash, which is a worse result, not a stronger one, and is "
        "exactly the 'dimmed, not deliberately lit' failure this project "
        "has seen before. Ambient (a separate, uniform, scene-wide lever, "
        "see below) still usually wants to go near zero for a dramatic "
        "mood — that's not the same lever as a fill light's controlled, "
        "directional, partial lift.\n"
        "- RIM (optional, strong mood payoff when geometry allows it): a "
        "light positioned behind or to the side of the subject/area, "
        "aimed back toward camera-ish, that traces a thin edge of light "
        "separating the subject from a dark background — the single "
        "most reliable way to make a dark scene still read as deliberate "
        "and composed rather than just underlit.\n"
        "- PRACTICAL: a light that exists to glow ITSELF (a screen, a "
        "sign, a fixture) rather than to illuminate the room around it. "
        "A legitimate thing to have, but it does NOT substitute for a "
        "KEY — a frame where the only visible light sources are small "
        "glowing props, while the floor/walls/room around them stay "
        "near-pure black, is the exact failure mode the judge now "
        "explicitly and strictly fails, no matter how 'atmospheric' it "
        "looks at a glance. If you tag something PRACTICAL, it should "
        "NOT be your only light doing real work this attempt.\n\n"
        "DECISIVE KEY LIGHT, VERIFIED NOT ASSUMED: a key light only "
        "counts as genuinely dominant if the frame's own measured "
        "BRIGHT zone ends up clearly above this scene's untouched "
        "baseline brightness (reported below) — intensity being a big "
        "number, or the key being brighter than your OTHER lights, is "
        "NOT sufficient if grading/vignette/fog end up eating that gain "
        "back down to at or below the room's own unlit highlight. This "
        "is now a real guardrail (not just instructions), rejecting "
        "before the judge call if the rendered bright zone doesn't clear "
        "the baseline by a real margin — if you get that feedback, the "
        "fix is usually: push key intensity further, narrow its range so "
        "the SAME intensity lands harder in a tighter pool, or ease off "
        "a global grading value that's quietly flattening what the "
        "light already created, not just 'try a bigger number again'.\n\n"
        "One concrete fact, not a style prescription: for a genuinely "
        "dramatic/high-contrast mood, the key needs to clearly dominate "
        "— pull set_ambient's intensity down toward 0 too "
        "(it's a uniform fill applied everywhere regardless of any "
        "light's range, and sits at a flattening 1.0 by default — a dark "
        "zone cannot read as genuinely dark while it's high, no matter "
        "what any individual light does). Calibrate your key light's "
        "actual intensity against the scene's baseline render brightness "
        "(reported separately below) — a number like '2.0' means nothing "
        "on its own, what matters is whether your attempt's own rendered "
        "p90 ends up clearly above the baseline's p90, not just higher "
        "than your other lights' values. Three deterministic checks run "
        "on every attempt purely to catch EXTREME failures on either "
        "side — a frame gone fully black/unreadable, (only for "
        "high-contrast moods) a frame so flat it has no real brightness "
        "variation or has a wide variation but its dark zone still "
        "isn't actually dark, OR (also high-contrast only) a frame whose "
        "bright zone never actually exceeded the untouched baseline "
        "despite passing the other two. They are a safety net against "
        "degenerate results, not a style prescription — clearing them is "
        "not the same as succeeding at the mood. Push as boldly as you "
        "judge the mood actually needs.\n\n"
        "RENDER PIPELINE ORDER (Eran's call, 2026-11-25, measured live on "
        "this exact scene): lights render FIRST -- that's the ONLY stage "
        "that can create LOCAL contrast, one area genuinely bright, "
        "another genuinely dark. Post-processing (set_color_adjustments' "
        "post_exposure, then contrast, then saturation/color_filter, then "
        "set_vignette, then set_fog) applies AFTER, as a chain where each "
        "stage transforms the OUTPUT of the one before it, not the "
        "original render. It reshapes the WHOLE frame globally (vignette "
        "included -- positional, not content-aware) -- it CANNOT "
        "invent new local contrast between two areas. This means: "
        "- Lights are your drama mechanism (where it's bright vs dark). "
        "Grading is a light-touch global finishing pass on top, not how "
        "you create drama. If grading alone is doing the mood's heavy "
        "lifting, it will crush the WHOLE frame instead of making one "
        "area pop. "
        "- Moderate individual grading values are deceptive: measured "
        "live on this scene, contrast=68 + saturation=-28 + color_filter "
        "together already cut mean brightness 38 to ~10 (not "
        "catastrophic alone), but adding vignette=0.5 ON TOP of that "
        "crushed it to ~0.4 (essentially full black) -- each stage "
        "compounds MULTIPLICATIVELY on the previous stage's already-"
        "darkened output, not additively on the original image. 2-3 "
        "'moderate' knobs stacked together is often far more severe than "
        "any one of them suggests in isolation. "
        "- Practical order: decide your light placement/intensity first "
        "(that's what actually defines the mood's contrast), THEN add a "
        "light-touch grading pass on top to unify tone -- not the "
        "other way around, and not both escalating independently every "
        "retry without checking what the combination already does.\n\n"
        "EXISTING LIGHTS ARE NOT A CONSTRAINT (Eran's call, 2026-11-25): "
        "found live that the agent reliably retunes the scene's original "
        "fixtures attempt after attempt and never once calls create_light "
        "or create_light_near, exactly the same narrow-habit pattern as "
        "sticking to 1-2 levers — treating what already exists as the "
        "fixed universe instead of one option among several. The "
        "existing fixtures' positions were placed by an artist for "
        "general room lighting, not for your mood. If they can't serve "
        "the mood from where they sit, don't just retune their intensity "
        "— delete one (delete_light) or simply ignore it (pull it near-"
        "zero) and create_light_near a NEW light exactly where the mood "
        "needs one. A from-scratch light is a completely normal, "
        "equally-valid move, not a last resort.\n\n"
        "LEVER MENU: you have 8 independent levers, and they are NOT "
        "mutually exclusive — combining several per attempt is the "
        "normal, expected move, not an edge case (e.g. reposition a "
        "light AND widen its falloff AND swap the skybox AND tighten "
        "global grading, all in the same attempt, if the mood calls for "
        "it). Pushing the same 1-2 levers harder across every attempt, "
        "when the score isn't moving, is the single most common mistake "
        "— if a lever isn't working, reach for a genuinely DIFFERENT "
        "one, not a stronger version of the same one:\n"
        "- POSITION: set_object_transform's position args. Where a "
        "light physically sits changes everything about pool size and "
        "what surfaces it grazes — this is rarely the same as wherever "
        "the scene's original artist happened to leave a fixture.\n"
        "- ROTATION: set_object_transform's rotation args, or aim_light_at "
        "for a precise look-at. Which direction a light faces determines "
        "what it actually illuminates and what shadow shapes result.\n"
        "- INTENSITY: set_light_properties' intensity. Calibrate against "
        "the scene's baseline render brightness reported below, not an "
        "arbitrary number.\n"
        "- FALLOFF_RANGE: set_light_properties' range/spot_angle. "
        "Contained pool vs floods-the-room, independent of intensity.\n"
        "- COLOR: set_light_properties' color (r,g,b, each 0-1). Use "
        "color for ALL light tinting, warm, cool, toxic green, alien "
        "purple, neon, anything. Leave color_temperature alone (do not "
        "set it) — it only moves along the real-world blackbody curve "
        "(orange -> white -> blue), it CANNOT produce green/purple/cyan "
        "tints at all, and it multiplies with color rather than adding, "
        "so touching both on the same light silently double-shifts and "
        "double-dims it (confirmed live 2026-11-26: this crushed a scene "
        "dark even at normal intensity). RGB covers everything "
        "color_temperature can do and far more — no creative mood needs "
        "it.\n"
        "- AMBIENT: set_ambient. The scene-wide uniform floor under "
        "every shadow — see the dedicated note on this below.\n"
        "- SKYBOX: list_skyboxes then set_skybox. Changes indoor ambient "
        "light color/intensity on scenes where ambient mode is "
        "Skybox-driven (check get_scene_context), not just a visible "
        "backdrop — a real, usable lever even indoors.\n"
        "- GLOBAL_GRADING: set_color_adjustments/set_vignette/set_fog "
        "together, scene-wide, stacks with every light change.\n\n"
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
        "outcome), then lever_accounting (every lever in the Lever enum, "
        "marked changed or not with a real reason each — this is checked "
        "against the real scene state, not just taken on faith), then "
        "changes_summary (a specific, concrete account of what you "
        "changed this attempt)."
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
