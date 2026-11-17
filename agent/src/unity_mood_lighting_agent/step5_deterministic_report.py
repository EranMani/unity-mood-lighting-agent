"""
v0, step 5: deterministic reporting instead of trusting LLM narration.

Step 4 asked the LLM to look at rich ObjectTransform data and narrow it down
to just names+count for the final SceneReport — that narrowing was model
JUDGMENT, not guaranteed-correct code. Fine for 3 objects, a real risk at
scale (a real Unity scene could have hundreds).

This step's point: "list the scene" has NO ambiguity and needs NO reasoning —
it's pure data transformation, so it doesn't need an agent at all. Skip
Runner.run and output_type entirely for this operation. Call the tool's
underlying function directly, build the report with plain code.

The agent/LLM isn't being thrown away — it's being saved for the part of
this project that actually needs judgment (deciding what lighting changes
achieve a requested mood, later). That's a real reasoning task with no single
correct answer. This is not.
"""

from pydantic import BaseModel, Field


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
    """Hardcoded scene data — later this is where the real Unity CLI/MCP call goes."""
    return [
        ObjectTransform(name="Floor", pos_x=0, pos_y=0, pos_z=0, rot_x=0, rot_y=0, rot_z=0),
        ObjectTransform(name="Cube", pos_x=0, pos_y=0.5, pos_z=0, rot_x=0, rot_y=0, rot_z=0),
        ObjectTransform(
            name="Main Camera", pos_x=0, pos_y=1, pos_z=-5, rot_x=15, rot_y=0, rot_z=0
        ),
    ]


class SceneReport(BaseModel):
    """Now carries the FULL per-object data through — no information thrown
    away, because nothing here requires an LLM to narrow it down."""

    objects: list[ObjectTransform]
    object_count: int


def build_scene_report() -> SceneReport:
    """Pure deterministic code. No model call. 100% correct, every time,
    regardless of whether the scene has 3 objects or 3,000."""
    transforms = _build_transforms()
    return SceneReport(objects=transforms, object_count=len(transforms))


def main() -> None:
    report = build_scene_report()
    print(report)
    print("object_count:", report.object_count)
    for obj in report.objects:
        print(" -", obj.name, "at", (obj.pos_x, obj.pos_y, obj.pos_z))


if __name__ == "__main__":
    main()
