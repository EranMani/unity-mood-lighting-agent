"""
main.py — the actual entry point. Ties together unity_bridge, tools, agent,
judge.

v2 loop (promoted from the README's v1/v2 split, decided live with Eran):
run the lighting agent -> judge the result -> if it passed, stop; if not,
feed the judge's own notes back into the next attempt so the agent knows
WHY it failed, not just that it failed -> retry, up to MAX_ATTEMPTS -> give
up and report the last judgement if still failing. Each retry re-reads the
CURRENT live scene state (get_scene_context()), not the original state —
attempt 2 builds on whatever attempt 1 actually left in the scene.

Usage:
    uv run python src/unity_mood_lighting_agent/main.py "your task here"
    uv run python src/unity_mood_lighting_agent/main.py
    (prompts for the task if not given as an argument)
"""

import asyncio
import sys

from agents import Runner
from dotenv import load_dotenv

from unity_mood_lighting_agent.agent import agent, get_scene_context
from unity_mood_lighting_agent.judge import judge_mood_match

load_dotenv()

MAX_ATTEMPTS = 3


async def run(task: str) -> str:
    feedback = ""  # judge's notes from the previous failed attempt, if any

    for attempt in range(1, MAX_ATTEMPTS + 1):
        prompt = f"Current scene objects:\n{get_scene_context()}\n\nTask: {task}"
        if feedback:
            prompt += (
                f"\n\nA previous attempt did not achieve this mood. Judge feedback: {feedback}\n"
                "Adjust your approach based on this feedback."
            )

        result = await Runner.run(agent, prompt)
        passed, judgement = await judge_mood_match(task)

        print(
            f"[attempt {attempt}/{MAX_ATTEMPTS}] agent: {result.final_output} | "
            f"judge score={judgement.mood_match_score} passed={passed}"
        )

        if passed:
            return f"Success on attempt {attempt}: {judgement.notes}"

        feedback = judgement.notes
        if attempt == MAX_ATTEMPTS:
            return f"Gave up after {MAX_ATTEMPTS} attempts. Last judge score={judgement.mood_match_score}: {judgement.notes}"

    raise AssertionError("unreachable: loop always returns on its last iteration")


def main() -> None:
    task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else input("Task: ")
    output = asyncio.run(run(task))
    print(output)


if __name__ == "__main__":
    main()
