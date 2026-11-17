"""
v0, step 3: structured output.
Same tool as step 2 (still hardcoded, no real Unity connection), but the
agent's final answer is now a typed Pydantic object instead of free text —
Day 3's structured outputs + constrained decoding.

Deliberately NOT adding position/rotation fields yet: the tool doesn't know
those values, so asking the model to report them would just be inventing
plausible-looking numbers into a typed object. Schema here only covers what
the tool actually returns.
"""

import asyncio

from agents import Agent, Runner, function_tool
from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()


@function_tool
def list_scene_objects() -> list[str]:
    """Return the complete list of object names currently in the Unity scene."""
    return ["Floor", "Cube", "Main Camera"]


class SceneReport(BaseModel):
    """Structured report of what's currently in the scene."""

    scene_objects: list[str] = Field(
        description="The exact list of object names returned by the scene-inspection tool."
    )
    object_count: int = Field(
        description="How many objects are in scene_objects. Must match its length."
    )


agent = Agent(
    name="MoodLightingAgent",
    instructions=(
        "You are an assistant that will eventually light Unity scenes to match "
        "a requested mood (e.g. horror, cozy, cheerful). You have a tool that "
        "lets you inspect what objects currently exist in the scene — use it "
        "whenever the user asks about the scene's contents. Report back exactly "
        "what the tool returns, do not add or assume any objects it didn't list."
    ),
    model="gpt-5.4-mini",
    tools=[list_scene_objects],
    output_type=SceneReport,
)


async def main() -> None:
    result = await Runner.run(agent, "What objects are in the scene?")
    report = result.final_output  # now a SceneReport instance, not a string
    print(type(report))
    print(report)
    print("objects:", report.scene_objects)
    print("count:", report.object_count)


if __name__ == "__main__":
    asyncio.run(main())
