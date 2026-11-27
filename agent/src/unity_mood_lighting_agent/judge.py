"""
judge.py — v1's judge: a SEPARATE agent that scores a screenshot against the
original mood task. This is the automated visual-feedback loop the README
has been pointing at since build log #13 (the noon-sunlight bug that only a
human looking at the Editor caught).

Structured output (not free text) per the README's v1 plan — code reads
mood_match_score and decides pass/fail, same code-decides/LLM-judges split
as the rotation guardrail and everywhere else in this project. The judge
agent's job is ONLY to produce the score; deciding what counts as a pass is
this module's job (judge_mood_match()), not the agent's.
"""

from agents import Agent, Runner
from pydantic import BaseModel, Field

from unity_mood_lighting_agent.agent import Lever, LightRole
from unity_mood_lighting_agent.unity_bridge import capture_game_view, image_to_data_url

PASS_THRESHOLD = 6  # out of 10 — plain code decides this, not the LLM


class LeverRecommendation(BaseModel):
    """One concrete next-step suggestion for the NEXT attempt, in the
    exact same vocabulary the lighting agent already tracks for itself
    (Lever enum, LightRole enum) — 2026-11-27, Eran's call, direct fix
    for the judge/agent translation gap: the judge's prose critique
    ('shadows too soft', 'reads as orderly') was accurate but never told
    the agent which lever to pull, so the agent had to re-derive that
    every attempt. Now the judge is handed the real post-attempt scene
    state (role assignments + real light values + global grading) and
    must name a specific lever or role swap instead of just describing
    the pixels again.

    Direction only, no target numbers (Eran's call) — the judge isn't
    re-deriving physics, the lighting agent decides magnitude. Exactly
    one of `lever`/`suggested_role` should be set: a recommendation is
    either 'change this numeric/positional lever' or 'reassign this
    light's studio role' (e.g. 'this light is better positioned to be
    the KEY than the one currently playing it'), never both."""

    light_id: str | None = Field(
        default=None,
        description="Which light (by instance_id, from the scene state you were given) this applies to. "
        "None for scene-wide levers (ambient/skybox/global_grading) with no single light involved.",
    )
    lever: Lever | None = Field(
        default=None,
        description="Set this for a numeric/positional suggestion (intensity, falloff_range, position, rotation, "
        "color, ambient, skybox, global_grading). Leave unset if this recommendation is a role swap instead.",
    )
    suggested_role: LightRole | None = Field(
        default=None,
        description="Set this INSTEAD of `lever` when the fix is reassigning which light plays which studio role "
        "(e.g. the light currently FILL would serve better as KEY given its position/range) — not a numeric change.",
    )
    direction: str = Field(
        description="Direction only, e.g. 'increase', 'decrease', 'narrow range', 'reposition closer to the subject', "
        "'reassign to this role' — never a target number, that's the lighting agent's call."
    )
    reason: str = Field(description="Why this specific lever/role change addresses a real problem named in `reasoning` above.")


class MoodJudgement(BaseModel):
    """Structured score for how well the LIGHTING serves a requested
    mood. reasoning is deliberately FIRST — same chain-of-thought-in-
    output technique as reasoning-then-answer: generating the
    description of what the image actually shows before committing to
    numbers lets that description condition the scores.

    2026-11-27, Eran's call — major redesign, direct fix for a real,
    repeated failure: the old single holistic `mood_match_score` kept
    getting swamped by scene CONTENT/geometry impressions ("staged",
    "tidy", "showroom") despite an explicit instruction not to score
    content — a soft prose rule couldn't stop a holistic vibe-based
    number from absorbing a holistic vibe-based impression. Fix is
    structural, not a stronger instruction: score 4 explicit
    LIGHTING-ONLY craft axes (contrast_execution, color_story_execution,
    shadow_structure, key_light_dominance), each answerable from
    lighting alone regardless of what's being lit, and compute
    `mood_match_score` from those four in CODE (judge_mood_match()),
    not as its own free judgment — there is structurally no field left
    for a content vibe to attach to. `content_ceiling_note` is the
    one place content/geometry observations are explicitly invited,
    and it NEVER affects the score — this project's product is a
    lighting QA tool for already-modeled scenes (Eran's call), and a
    lighting QA tool that fails you for the level designer's asset
    choices is a bad lighting QA tool."""

    reasoning: str = Field(description="Describe what the image actually shows FIRST, before scoring any axis below — lighting, color, contrast, shadow structure. This is what every score below should be grounded in.")
    contrast_execution: int = Field(description="0-10: does the actual brightness spread (dark zones vs bright zones) match what this mood's contrast level calls for? Judge the SPREAD itself, not whether the room 'feels' right overall.")
    color_story_execution: int = Field(description="0-10: does the color temperature/palette actually support the mood's intended feeling (warm/cool/saturated/desaturated, as appropriate)? Judge the COLOR CHOICES, not the room's content.")
    shadow_structure: int = Field(description="0-10: is there a real key/fill/rim structure — a visible falloff gradient, a real shadow boundary shaping the space — or does it read as 'a few small bright dots in the dark' / 'the lights were turned down'? This is the axis that catches the small-self-illuminating-props failure mode (a monitor/screen/sign glow is NOT the room being lit).")
    key_light_dominance: int = Field(description="0-10: does the key light's bright zone genuinely clear this scene's own untouched baseline brightness (given in scene state), or does it just look locally brighter than your other lights while still being dim overall?")
    content_ceiling_note: str | None = Field(
        default=None,
        description="If the scene's own geometry/art style/props structurally cap how far this mood could EVER read regardless of lighting (e.g. a bright, clean, stylized low-poly room can't look 'ravaged' no matter how harsh the light), say so here, specifically. This field is informational ONLY — it is never read for scoring, never affects any axis above or the computed mood_match_score. Leave None if content isn't the limiting factor.",
    )
    dominant_color_temp: str = Field(description="warm, neutral, or cool.")
    contrast_level: str = Field(description="low, medium, or high.")
    mood_match_score: int = Field(
        default=0,
        description="LEAVE AS 0 — this is computed by code from the four craft axes above (contrast_execution, "
        "color_story_execution, shadow_structure, key_light_dominance), not something you decide yourself. Any "
        "value you put here is discarded and overwritten.",
    )
    recommended_levers: list[LeverRecommendation] = Field(
        default_factory=list,
        description="If NOT passing (your craft axes average below 6): 1-4 concrete next-step suggestions, grounded in the real scene "
        "state you were given (light role assignments + real per-light values + global grading), in the lighting "
        "agent's own lever/role vocabulary — not a restatement of `reasoning`. If passing, leave empty.",
    )


judge_agent = Agent(
    name="MoodJudgeAgent",
    instructions=(
        "PERSONA (2026-11-26, added after a real miscalibration): you are "
        "an elite video game lighting producer and cinematographer -- "
        "decades of experience across film lighting, color grading, and "
        "camera work, now directing lighting quality on AAA game scenes. "
        "You have a famously high bar and zero patience for mediocre "
        "lighting dressed up as 'moody' or 'atmospheric'. You've seen "
        "every trick a lazy lighting pass uses to fake drama -- turning "
        "everything down and calling it horror, crushing the whole frame "
        "to black and calling it noir -- and you call it out every time. "
        "You are being asked to sign off on this shot's LIGHTING; if the "
        "lighting craft wouldn't earn your approval, you don't pass it. "
        "SCOPE (2026-11-27, Eran's call, structural now, not just a rule): "
        "this product controls ONLY lighting and rendering (light "
        "placement/color/intensity, color grading, vignette, fog, "
        "skybox) on scenes someone ELSE already modeled -- it is a "
        "LIGHTING QA TOOL, not a scene designer, and it never adds, "
        "removes, or changes geometry, props, or decorations. Your 4 "
        "scored axes below (contrast_execution, color_story_execution, "
        "shadow_structure, key_light_dominance) are EACH a question "
        "about the LIGHT, answerable the same way regardless of what "
        "happens to be sitting in the room -- a toy-store-bright room "
        "and a grimy ruin can both get a 9/10 shadow_structure if the "
        "key/fill/rim craft is equally sharp in both. Content/geometry "
        "observations go ONLY in `content_ceiling_note`, which is never "
        "read for scoring -- do not let 'this room still looks staged/ "
        "clean/orderly/showroom-ish' leak into any of the 4 numeric "
        "axes; that sentence belongs in `content_ceiling_note`, full "
        "stop, even if it feels like the most important thing you "
        "noticed. "
        "CRITICAL CALIBRATION, PER AXIS: "
        "- contrast_execution: do not confuse a merely DIM, evenly-lit, "
        "flat scene for a high-contrast one. A cold/blue color "
        "temperature alone is not drama -- real contrast requires a "
        "measurable brightness SPREAD (parts of the frame clearly "
        "darker than others from an actual light direction, not just a "
        "uniform dark wash). If the frame reads as 'the lights were "
        "turned down' rather than 'deliberately and dramatically lit', "
        "score this LOW for any mood wanting tension/horror/drama, "
        "regardless of how 'moody' it feels on a glance. "
        "- shadow_structure (the axis that catches the single most "
        "common failure mode seen in this project): small "
        "self-illuminating props -- a monitor glow, an arcade screen, a "
        "ceiling panel's own emissive surface -- are NOT the same as "
        "the ROOM being lit. If the floor, walls, and most of the "
        "geometry around those props stay near-pure black with no real "
        "gradient or shadow falloff, that is underexposed/undershot "
        "lighting craft, not 'isolated pools of light', even if it "
        "superficially looks atmospheric. A real key light should "
        "visibly shape the SPACE around it. 'A few small bright dots "
        "and nothing else' is a clear LOW score here (well below 6), no "
        "matter how appropriately cold or 'ominous' the color feels. "
        "- key_light_dominance: a key only counts as dominant if its "
        "bright zone clears the scene's own untouched baseline "
        "brightness (given in scene state) by a real margin -- a big "
        "intensity NUMBER is not sufficient if grading/vignette/fog ate "
        "the gain back down. "
        "Write 'reasoning' FIRST, describing what you actually see, "
        "before scoring any axis -- each axis score MUST follow from "
        "what reasoning actually describes; if reasoning lists real "
        "lighting problems (underexposed, collapses to near-black, weak "
        "shadow separation), the matching axis cannot score 6+ just "
        "because the mood direction was roughly right. "
        "SCENE STATE (2026-11-27): you will also be given this attempt's "
        "real scene state -- every light's role assignment "
        "(key/fill/rim/practical/unused) and its REAL intensity/range/ "
        "color, plus global grading/ambient/skybox. Use these REAL "
        "numbers, not guesses from pixels alone, to ground both your "
        "axis scores and any fix you recommend. If your craft axes "
        "average below 6, fill `recommended_levers` with 1-4 concrete "
        "next steps in the lighting agent's own vocabulary: either a "
        "numeric/positional lever (intensity, falloff_range, position, "
        "rotation, color, ambient, skybox, global_grading) on a named "
        "light, or a ROLE swap (e.g. the light you were told is FILL is "
        "actually better positioned/ranged to be the KEY, and the "
        "current KEY should step down) when the real light state shows "
        "the current role assignments are working against the mood. "
        "Direction only (increase/decrease/narrow/widen/reposition/"
        "reassign) -- never a target number, that's the lighting agent's "
        "job, not yours. This is a DIAGNOSIS, not a restatement of "
        "`reasoning` -- each entry must name a specific lever or role "
        "change that would plausibly fix a specific problem you already "
        "described above. "
        "FULL PICTURE, NOT JUST PIXELS (2026-11-27): you also get the "
        "agent's own stated reasoning for this attempt (its intent, "
        "separate from your verdict), how it says it addressed YOUR OWN "
        "last recommendations (verified against the real scene diff, not "
        "self-report), and a once-per-scene spatial breakdown (geometry "
        "anchors with suggested light positions, mood-blind). You stay "
        "stateless every call -- no memory of your own past scores or "
        "reasoning, score this frame on its own merits -- but use this "
        "context to make SPATIALLY GROUNDED position/rotation "
        "recommendations instead of vague ones: if a key light's pool "
        "misses a real anchor the spatial breakdown names, recommend "
        "repositioning toward that anchor's suggested coordinates "
        "specifically, not just 'reposition it'. If the acknowledgments "
        "show your last recommendation was genuinely addressed and the "
        "problem persists anyway, that's a signal to recommend a "
        "DIFFERENT lever this time, not repeat the same advice."
    ),
    model="gpt-5.4-mini",
    output_type=MoodJudgement,
)


def _image_to_data_url(path: str) -> str:
    return image_to_data_url(path)


async def judge_mood_match(
    mood_task: str, image_path: str | None = None, scene_state: str | None = None
) -> tuple[bool, MoodJudgement]:
    """Scores image_path against mood_task. Returns (passed, judgement) —
    passed is plain code deciding from mood_match_score, not the agent's
    own opinion of pass/fail.

    image_path should be the SAME capture the pre-judge guardrails
    (visibility/contrast) already scored — pass it in explicitly rather
    than taking a fresh capture_game_view() here. Found live (2026-11-25,
    Eran caught it from a saved result.png): the old behavior took its own
    independent capture, and main.py's final saved result.png was a FOURTH
    separate capture taken even later, after the judge call — three
    different screenshots of the same attempt could legitimately disagree,
    so a judged "4/10, underexposed" attempt could still save a crushed-
    black result.png that nothing ever actually scored. image_path=None
    falls back to a fresh capture only for standalone/ad-hoc use outside
    the main attempt loop.

    scene_state (2026-11-27, Eran's call): the same role-assignment +
    real-light-state text main.py already builds for the lighting agent's
    own attempt_history — handing the judge the REAL numbers (not just
    pixels) is what lets `recommended_levers` be grounded in actual scene
    state instead of guessed from the image alone. None for standalone/
    ad-hoc use where that context was never built."""
    capture_path = image_path if image_path is not None else capture_game_view().path
    image_url = _image_to_data_url(capture_path)

    prompt_text = f"Requested mood: {mood_task}"
    if scene_state is not None:
        prompt_text += f"\n\nThis attempt's real scene state:\n{scene_state}"

    input_message = [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": prompt_text},
                {"type": "input_image", "image_url": image_url},
            ],
        }
    ]
    result = await Runner.run(judge_agent, input_message)
    judgement: MoodJudgement = result.final_output

    # 2026-11-27, Eran's call — mood_match_score is COMPUTED here, not
    # trusted from the model's own field (see MoodJudgement's docstring
    # for why: a free holistic number kept absorbing content/geometry
    # impressions despite instructions not to). Equal-weighted average
    # of the 4 lighting-only craft axes, rounded — no tuned weighting
    # yet, observe real usage first before deciding any axis deserves
    # more weight than another, same caution already applied elsewhere
    # in this project (LightRole's no-cap decision, etc).
    judgement.mood_match_score = round(
        (
            judgement.contrast_execution
            + judgement.color_story_execution
            + judgement.shadow_structure
            + judgement.key_light_dominance
        )
        / 4
    )
    passed = judgement.mood_match_score >= PASS_THRESHOLD
    return passed, judgement
