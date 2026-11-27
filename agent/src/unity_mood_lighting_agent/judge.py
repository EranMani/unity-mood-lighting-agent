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
    """Structured score for how well a captured scene matches a mood task.
    reasoning is deliberately FIRST — same chain-of-thought-in-output
    technique as reasoning-then-answer: generating the description of
    what the image actually shows before committing to a number lets
    that description condition the score, instead of the model jumping
    straight to a number with no deliberation. Decided live with Eran,
    2026-11-23 — this reframes/replaces the old 'notes' field, which was
    positioned last and explicitly 'debugging only, not branched on',
    exactly backwards from this technique."""

    reasoning: str = Field(description="Describe what the image actually shows FIRST, before scoring — lighting, color, contrast, what does/doesn't support the requested mood. This is what the score below should be grounded in.")
    mood_match_score: int = Field(description="0-10, overall match to the requested mood.")
    dominant_color_temp: str = Field(description="warm, neutral, or cool.")
    contrast_level: str = Field(description="low, medium, or high.")
    recommended_levers: list[LeverRecommendation] = Field(
        default_factory=list,
        description="If NOT passing (score < 6): 1-4 concrete next-step suggestions, grounded in the real scene "
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
        "You are being asked to sign off on this shot; if you wouldn't "
        "actually approve it for a real game, you don't pass it. "
        "IMPORTANT SCOPE: this product controls ONLY lighting and "
        "rendering (light placement/color/intensity, color grading, "
        "vignette, fog, skybox) -- it NEVER adds, removes, or changes "
        "scene geometry, props, or decorations. Score how well the "
        "LIGHTING AND ATMOSPHERE serve the requested mood GIVEN the "
        "existing geometry, not whether the scene literally contains "
        "objects a real version of that mood might have (do NOT deduct "
        "for missing decorations, furniture, debris, crowds, or props -- "
        "those would require changing geometry, which is out of scope "
        "and not this agent's job). If the existing geometry is "
        "fundamentally incompatible with the mood (e.g. a sci-fi room for "
        "'medieval castle'), say so in reasoning, but still score based on "
        "how far lighting alone pushes the atmosphere in the right "
        "direction, not on content it structurally cannot add. "
        "CRITICAL CALIBRATION: do not confuse a merely DIM, evenly-lit, "
        "flat scene for a DRAMATIC one. A cold/blue color temperature "
        "alone is not drama -- real drama requires visible shadow shape "
        "(parts of the frame clearly darker than others from an actual "
        "light direction, not just a uniform dark wash), a readable "
        "light source doing work, and enough brightness that the eye can "
        "still tell what it's looking at. If the frame reads as 'the "
        "lights were turned down' rather than 'this was deliberately and "
        "dramatically lit', that is a LOW score for any mood that calls "
        "for tension, horror, or drama (regardless of color temperature "
        "or how 'moody' it feels on a glance) -- score the CONTRAST field "
        "honestly too; if you'd call the actual contrast low or medium, "
        "a high-drama mood should not be scoring 6+. "
        "SPECIFIC FAILURE MODE TO WATCH FOR (caught live, do not repeat "
        "this mistake): small self-illuminating props -- a monitor glow, "
        "an arcade screen, a ceiling panel's own emissive surface -- are "
        "NOT the same as the ROOM being lit. If the floor, walls, and "
        "most of the geometry around those props stay near-pure black "
        "with no real gradient or shadow falloff, that is an "
        "underexposed/undershot scene, not 'isolated pools of light', "
        "even if it superficially looks atmospheric at a glance. A real "
        "key light should visibly shape the SPACE around it, not just "
        "glow by itself while everything nearby stays black. A scene "
        "where you could only describe 'a few small bright dots' and "
        "nothing else is a clear FAIL (well below 6), not a borderline "
        "pass, no matter how appropriately cold or 'ominous' the color "
        "feels. "
        "Write the 'reasoning' field FIRST and let it describe what you "
        "actually see (lighting, color, contrast, what does/doesn't "
        "support the mood ATMOSPHERICALLY) before you decide the score -- "
        "the score MUST follow from what reasoning actually describes; if "
        "your own reasoning lists several real problems (underexposed, "
        "collapses to near-black, weak shadow separation, not cinematic), "
        "the score cannot be a 6+ pass just because the mood direction "
        "was roughly right -- a pass means you'd actually approve this "
        "shot, not that it's merely pointed the right way. "
        "SCENE STATE (2026-11-27, Eran's call): you will also be given "
        "this attempt's real scene state -- every light's role assignment "
        "(key/fill/rim/practical/unused) and its REAL intensity/range/ "
        "color, plus global grading/ambient/skybox. Use these REAL "
        "numbers, not guesses from pixels alone, to ground any fix you "
        "recommend. If you fail the shot, fill `recommended_levers` with "
        "1-4 concrete next steps in the lighting agent's own vocabulary: "
        "either a numeric/positional lever (intensity, falloff_range, "
        "position, rotation, color, ambient, skybox, global_grading) on a "
        "named light, or a ROLE swap (e.g. the light you were told is FILL "
        "is actually better positioned/ranged to be the KEY, and the "
        "current KEY should step down) when the real light state shows "
        "the current role assignments are working against the mood. "
        "Direction only (increase/decrease/narrow/widen/reposition/"
        "reassign) -- never a target number, that's the lighting agent's "
        "job, not yours. This is a DIAGNOSIS, not a restatement of "
        "`reasoning` -- each entry must name a specific lever or role "
        "change that would plausibly fix a specific problem you already "
        "described above."
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
    passed = judgement.mood_match_score >= PASS_THRESHOLD
    return passed, judgement
