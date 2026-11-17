"""
main.py — the actual entry point. Ties together unity_bridge, tools, agent.

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

load_dotenv()


async def run(task: str) -> str:
    messages = [
        {"role": "user", "content": f"Current scene objects:\n{get_scene_context()}"},
        {"role": "user", "content": task},
    ]
    result = await Runner.run(agent, messages)
    return result.final_output


def main() -> None:
    task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else input("Task: ")
    output = asyncio.run(run(task))
    print(output)


if __name__ == "__main__":
    main()
