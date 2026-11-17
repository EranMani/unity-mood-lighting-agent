"""
unity_bridge.py — the current, live interface to Unity.

Consolidated from learning_steps/step6 (read) and step7 (write), which
remain in place as the record of how this was found/built/debugged. This
file is what the rest of the project actually imports going forward.

All deterministic, no agent/LLM here — reading/writing a transform by exact
name or ID has no ambiguity. See learning_steps/step5 for why that split
(code vs agent) was made.
"""

import json
import subprocess

from pydantic import BaseModel, Field

UNITY_EXE = r"C:\Users\eranm\AppData\Local\Unity\bin\unity.exe"
PROJECT_PATH = r"D:\AI\MyProjects\unity-mood-lighting-agent\MoodLightingScene"

# GetInstanceID() is obsolete in this Unity version (hard compile error).
# GetEntityId() replaces it, but the raw struct serializes to {} (no public
# fields) — .ToString() is required for a usable value.
_READ_SCRIPT = """
var list = new System.Collections.Generic.List<object>();
foreach (var t in UnityEngine.Object.FindObjectsByType<UnityEngine.Transform>()) {
  if (t.parent != null) continue;
  var p = t.position; var r = t.eulerAngles;
  list.Add(new { instance_id = t.gameObject.GetEntityId().ToString(), name = t.gameObject.name, pos_x = p.x, pos_y = p.y, pos_z = p.z, rot_x = r.x, rot_y = r.y, rot_z = r.z });
}
return list;
""".strip()


class ObjectTransform(BaseModel):
    """One scene object's identity + where it is, flat fields only."""

    instance_id: str = Field(description="GameObject entity ID — pass as --target to gameobject set_transform.")
    name: str
    pos_x: float
    pos_y: float
    pos_z: float
    rot_x: float = Field(description="Rotation around the X axis, in degrees.")
    rot_y: float = Field(description="Rotation around the Y axis, in degrees.")
    rot_z: float = Field(description="Rotation around the Z axis, in degrees.")


def list_scene_transforms() -> list[ObjectTransform]:
    """Read every root-level object's identity + transform from the live
    Editor. Requires MoodLightingScene open in Unity right now."""
    result = subprocess.run(
        [
            UNITY_EXE,
            "command",
            "script",
            "eval",
            _READ_SCRIPT,
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


def set_object_transform(
    target: str,
    position: tuple[float, float, float] | None = None,
    rotation: tuple[float, float, float] | None = None,
) -> None:
    """Move/rotate a GameObject by its instance_id (from
    list_scene_transforms()). Omit position or rotation to leave that
    channel unchanged, matching the Unity CLI's own behavior."""
    args = [
        UNITY_EXE,
        "command",
        "gameobject set_transform",
        "--target",
        target,
        "--project-path",
        PROJECT_PATH,
    ]
    if position is not None:
        args += ["--position", f"[{position[0]},{position[1]},{position[2]}]"]
    if rotation is not None:
        args += ["--rotation", f"[{rotation[0]},{rotation[1]},{rotation[2]}]"]

    subprocess.run(args, capture_output=True, text=True, check=True)
