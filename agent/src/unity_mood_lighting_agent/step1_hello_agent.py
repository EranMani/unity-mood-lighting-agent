"""
v0, step 1: the absolute minimum — one Agent, one Runner.run call.
No tools, no Unity connection yet. Just proving the harness works.
"""

import asyncio

from agents import Agent, Runner
from dotenv import load_dotenv

load_dotenv()

agent = Agent(
    name="MoodLightingAgent",
    instructions=(
        "You are an assistant that will eventually light Unity scenes to match "
        "a requested mood (e.g. horror, cozy, cheerful). For now, just say hello "
        "and confirm you're ready to help with Unity scene lighting."
    ),
    model="gpt-5.4-mini",
)


async def main() -> None:
    result = await Runner.run(agent, "Are you ready?")
    print(result.final_output)


if __name__ == "__main__":
    asyncio.run(main())
