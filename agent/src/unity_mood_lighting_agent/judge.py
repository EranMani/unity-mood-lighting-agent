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
    2026-11-20 — this reframes/replaces the old 'notes' field, which was
    positioned last and explicitly 'debugging only, not branched on',
    exactly backwards from this technique."""

    reasoning: str = Field(description="Describe what the image actually shows FIRST, before scoring — lighting, color, contrast, what does/doesn't support the requested mood. This is what the score below should be grounded in.")
    mood_match_score: int = Field(description="0-10, overall match to the requested mood.")
    dominant_color_temp: str = Field(description="warm, neutral, or cool.")
    contrast_level: str = Field(description="low, medium, or high.")


judge_agent = Agent(
    name="MoodJudgeAgent",
    instructions=(
        "You are given a screenshot of a Unity scene and the mood it was "
        "supposed to achieve (e.g. 'horror', 'cozy'). IMPORTANT SCOPE: this "
        "product controls ONLY lighting and rendering (light placement/"
        "color/intensity, color grading, vignette, fog, skybox) — it NEVER "
        "adds, removes, or changes scene geometry, props, or decorations. "
        "Score how well the LIGHTING AND ATMOSPHERE serve the requested "
        "mood GIVEN the existing geometry, not whether the scene literally "
        "contains objects a real version of that mood might have (do NOT "
        "deduct for missing decorations, furniture, debris, crowds, or "
        "props — those would require changing geometry, which is out of "
        "scope and not this agent's job). If the existing geometry is "
        "fundamentally incompatible with the mood (e.g. a sci-fi room for "
        "'medieval castle'), say so in reasoning, but still score based on "
        "how far lighting alone pushes the atmosphere in the right "
        "direction, not on content it structurally cannot add. Be a strict, "
        "honest critic on what IS in scope — do not assume the task "
        "succeeded just because lighting changed; judge the actual "
        "atmosphere, contrast, and color story the lighting produced. "
        "Write the 'reasoning' field FIRST and let it describe what you "
        "actually see (lighting, color, contrast, what does/doesn't "
        "support the mood ATMOSPHERICALLY) before you decide the score — "
        "don't write the score first and justify it afterward."
    ),
    model="gpt-5.4-mini",
    output_type=MoodJudgement,
)


def _image_to_data_url(path: str) -> str:
    return image_to_data_url(path)


async def judge_mood_match(mood_task: str) -> tuple[bool, MoodJudgement]:
    """Captures the CURRENT live Game view and scores it against mood_task.
    Returns (passed, judgement) — passed is plain code deciding from
    mood_match_score, not the agent's own opinion of pass/fail."""
    capture = capture_game_view()
    image_url = _image_to_data_url(capture.path)

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
