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

from unity_mood_lighting_agent.unity_bridge import capture_game_view, image_to_data_url

PASS_THRESHOLD = 6  # out of 10 — plain code decides this, not the LLM


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
        "shot, not that it's merely pointed the right way."
    ),
    model="gpt-5.4-mini",
    output_type=MoodJudgement,
)


def _image_to_data_url(path: str) -> str:
    return image_to_data_url(path)


async def judge_mood_match(mood_task: str, image_path: str | None = None) -> tuple[bool, MoodJudgement]:
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
    the main attempt loop."""
    capture_path = image_path if image_path is not None else capture_game_view().path
    image_url = _image_to_data_url(capture_path)

    input_message = [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": f"Requested mood: {mood_task}"},
                {"type": "input_image", "image_url": image_url},
            ],
        }
    ]
    result = await Runner.run(judge_agent, input_message)
    judgement: MoodJudgement = result.final_output
    passed = judgement.mood_match_score >= PASS_THRESHOLD
    return passed, judgement
