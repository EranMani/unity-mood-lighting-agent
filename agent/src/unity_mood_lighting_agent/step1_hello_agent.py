"""
v0, step 1: the absolute minimum — one Agent, one Runner.run call.
No tools, no Unity connection yet. Just proving the harness works.
"""

import asyncio

from agents import Agent, Runner, function_tool
from dotenv import load_dotenv

load_dotenv()

@function_tool
def list_scene_objects() -> list[str]:
    """Return the names of all objects currently in the Unity scene."""
    return ["Floor", "Cube", "Main Camera"]

agent = Agent(
    name="MoodLightingAgent",
    instructions=(
        "You are an assistant that will eventually light Unity scenes to match "
        "a requested mood (e.g. horror, cozy, cheerful). You have a tool that "
        "lets you inspect what objects currently exist in the scene — use it "
        "whenever the user asks about the scene's contents."
    ),
    model="gpt-5.4-mini",
    tools=[list_scene_objects]
)


async def main() -> None:
    result = await Runner.run(agent, "What objects are in the scene?")
    print(result.final_output)




if __name__ == "__main__":
    asyncio.run(main())
