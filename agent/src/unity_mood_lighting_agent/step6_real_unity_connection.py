"""
v0, step 6: real Unity connection. Replaces step 5's hardcoded
_build_transforms() with an actual subprocess call to the Unity CLI's
`script eval`, reading real position/rotation data from the live Editor.

See docs/unity-cli-connection.md for how this command was found and tested
live before being wired in here.

Still deterministic code, no agent/LLM involved — this is still just the
"list the scene" operation, which step 5 established doesn't need judgment.
The only thing that changed is where the data comes from: real Unity instead
of a hardcoded list.
"""

import json
import subprocess

from pydantic import BaseModel, Field

UNITY_EXE = r"C:\Users\eranm\AppData\Local\Unity\bin\unity.exe"
PROJECT_PATH = r"D:\AI\MyProjects\unity-mood-lighting-agent\MoodLightingScene"

# Reads every root-level Transform's name/position/rotation. Root-level only
# (t.parent != null skipped) to match step 4/5's scope: top-level scene
# objects, not nested children.
_SCRIPT = """
var list = new System.Collections.Generic.List<object>();
foreach (var t in UnityEngine.Object.FindObjectsByType<UnityEngine.Transform>(UnityEngine.FindObjectsSortMode.None)) {
  if (t.parent != null) continue;
  var p = t.position; var r = t.eulerAngles;
  list.Add(new { name = t.gameObject.name, pos_x = p.x, pos_y = p.y, pos_z = p.z, rot_x = r.x, rot_y = r.y, rot_z = r.z });
}
return list;
""".strip()


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
    """Real data this time — runs script eval against the live Editor.
    Requires MoodLightingScene actually open in Unity right now."""
    result = subprocess.run(
        [
            UNITY_EXE,
            "command",
            "script",
            "eval",
            _SCRIPT,
            "--result-only",
            "--project-path",
            PROJECT_PATH,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    raw = json.loads(result.stdout)
    return [ObjectTransform(**entry) for entry in raw]


class SceneReport(BaseModel):
    """Same shape as step 5 — full per-object data, nothing discarded."""

    objects: list[ObjectTransform]
    object_count: int


def build_scene_report() -> SceneReport:
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
