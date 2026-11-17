"""
v0, step 4: upgrade the tool itself to return real per-object data
(position + rotation), still hardcoded — no real Unity connection yet.

Deliberately did NOT also change the agent's final output_type (SceneReport
stays name+count only, same as step 3). This step's only job is proving the
TOOL can return structured per-object data. Wiring that data into the final
answer's schema is a separate step, once this is confirmed working.

Design note: position + rotation are flat fields on one object (ObjectTransform),
not split into two separate tools. Every GameObject has a Transform by
definition — splitting "where is it" from "what is it" would be over-
decomposing one entity's data, not separating two real capabilities (compare:
list_scene_objects vs capture_viewport ARE two real, different capabilities).
"""

import asyncio

from agents import Agent, Runner, function_tool
from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()


class ObjectTransform(BaseModel):
    """One scene object's identity + where it is, flat fields only."""

    name: str
    pos_x: float
    pos_y: float
    pos_z: float
    rot_x: float = Field(description="Rotation around the X axis, in degrees.")
    rot_y: float = Field(description="Rotation around the Y axis, in degrees.")
    rot_z: float = Field(description="Rotation around the Z axis, in degrees.")


def _build_transforms() -> list[ObjectTransform]:
    """The actual hardcoded data, kept separate so we can call it directly
    (for verification) without going through the @function_tool wrapper,
    which is no longer a plain callable once decorated."""
    return [
        ObjectTransform(name="Floor", pos_x=0, pos_y=0, pos_z=0, rot_x=0, rot_y=0, rot_z=0),
        ObjectTransform(name="Cube", pos_x=0, pos_y=0.5, pos_z=0, rot_x=0, rot_y=0, rot_z=0),
        ObjectTransform(
            name="Main Camera", pos_x=0, pos_y=1, pos_z=-5, rot_x=15, rot_y=0, rot_z=0
        ),
    ]


@function_tool
def list_object_transforms() -> list[ObjectTransform]:
    """Return every scene object's name, position, and rotation. Hardcoded for now."""
    return _build_transforms()


class SceneReport(BaseModel):
    """Same shape as step 3 — names + count only. Unchanged on purpose."""

    scene_objects: list[str] = Field(
        description="The exact list of object names returned by the tool."
    )
    object_count: int = Field(
        description="How many objects are in scene_objects. Must match its length."
    )


agent = Agent(
    name="MoodLightingAgent",
    instructions=(
        "You are an assistant that will eventually light Unity scenes to match "
        "a requested mood (e.g. horror, cozy, cheerful). You have a tool that "
        "lets you inspect every object's name, position, and rotation. Use it "
        "whenever the user asks about the scene. Report back exactly what the "
        "tool returns, do not add or assume anything it didn't list."
    ),
    model="gpt-5.4-mini",
    tools=[list_object_transforms],
    output_type=SceneReport,
)


async def main() -> None:
    # First, call the tool directly (no agent involved) so we can SEE the
    # actual structured data with our own eyes before trusting the agent's
    # report of it.
    print("--- direct tool call, bypassing the agent entirely ---")
    for obj in _build_transforms():
        print(obj)

    print("\n--- now via the agent ---")
    result = await Runner.run(agent, "What objects are in the scene?")
    report = result.final_output
    print(report)


if __name__ == "__main__":
    asyncio.run(main())
