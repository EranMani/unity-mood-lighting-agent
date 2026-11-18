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
import os
import subprocess
import tempfile

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


# Guardrail: checks a CANDIDATE rotation without ever applying it to the
# live object (no flicker, no revert-on-fail round trip). Takes the
# candidate position/rotation as plain numbers, lets Unity's own
# Quaternion.Euler (ZXY order, Unity's real convention) compute the forward
# vector — we deliberately do NOT reimplement that trig in Python, since
# getting the rotation convention wrong by hand is exactly the bug class
# this guardrail exists to catch (see build log #13). The ray ignores the
# light's own collider (if any) so it doesn't just hit itself at distance 0.
#
# HOW THIS AVOIDS TOUCHING THE REAL OBJECT: nothing below ever reads or
# writes any GameObject's actual transform. `origin`/`rot`/`direction` are
# just numbers computed in memory — "IF something were at this position
# with this rotation, which way would it face." Physics.RaycastAll only
# needs an origin point + a direction to fire a ray; it doesn't know or
# care whether any real object in the scene actually has that position/
# rotation. So this is a pure "what-if" query against the scene's existing
# colliders — the light itself sits completely untouched while this runs.
# Only set_object_transform() below (called separately, after this check
# passes) ever actually moves/rotates the real GameObject.
_RAYCAST_CANDIDATE_SCRIPT = """
var origin = new UnityEngine.Vector3(__POS_X__f, __POS_Y__f, __POS_Z__f);
var rot = UnityEngine.Quaternion.Euler(__ROT_X__f, __ROT_Y__f, __ROT_Z__f);
var direction = rot * UnityEngine.Vector3.forward;
var hits = UnityEngine.Physics.RaycastAll(origin, direction, __MAX_DIST__f);
foreach (var h in hits) {
  if (h.collider.gameObject.GetEntityId().ToString() == "__SELF_ID__") continue;
  return new { hit = true, hit_name = h.collider.gameObject.name, distance = h.distance };
}
return new { hit = false, hit_name = (string)null, distance = (float)0 };
""".strip()


class RaycastResult(BaseModel):
    """Result of firing a ray from a candidate position/rotation."""

    hit: bool = Field(description="True if the ray hit any collider other than self.")
    hit_name: str | None = Field(default=None, description="Name of the object hit, if any.")
    distance: float = Field(default=0.0, description="Distance to the hit, if any.")


def check_rotation_aims_at_geometry(
    position: tuple[float, float, float],
    rotation: tuple[float, float, float],
    self_id: str,
    max_distance: float = 100.0,
) -> RaycastResult:
    """Guardrail check for a CANDIDATE position+rotation, before it's ever
    applied to the live object. Computes the forward vector via Unity's own
    Quaternion.Euler (not reimplemented in Python) and raycasts from there,
    ignoring self_id so the light doesn't hit its own collider. Deterministic,
    no LLM involved, same script-eval pattern as list_scene_transforms()."""
    script = (
        _RAYCAST_CANDIDATE_SCRIPT.replace("__POS_X__", str(position[0]))
        .replace("__POS_Y__", str(position[1]))
        .replace("__POS_Z__", str(position[2]))
        .replace("__ROT_X__", str(rotation[0]))
        .replace("__ROT_Y__", str(rotation[1]))
        .replace("__ROT_Z__", str(rotation[2]))
        .replace("__SELF_ID__", self_id)
        .replace("__MAX_DIST__", str(max_distance))
    )
    result = subprocess.run(
        [
            UNITY_EXE,
            "command",
            "script",
            "eval",
            script,
            "--result-only",
            "--project-path",
            PROJECT_PATH,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    raw = json.loads(result.stdout)
    return RaycastResult(**raw)


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


class CaptureResult(BaseModel):
    """Result of a game_view capture — what the judge agent will look at."""

    path: str = Field(description="Absolute path to the saved PNG.")
    width: int
    height: int


def capture_game_view(output_path: str | None = None) -> CaptureResult:
    """Capture the Game view (actual rendered scene, not editor gizmos/grid)
    as a PNG. This is what a judge agent should see, not `scene_view` or
    `editor_window`. Defaults to a fresh temp file if output_path isn't
    given. Deterministic wrapper around the Unity CLI call — scoring the
    image is the agent's job, not this function's."""
    if output_path is None:
        fd, output_path = tempfile.mkstemp(suffix=".png", prefix="mood_capture_")
        os.close(fd)

    result = subprocess.run(
        [
            UNITY_EXE,
            "command",
            "capture game_view",
            "--output-path",
            output_path,
            "--project-path",
            PROJECT_PATH,
            "--result-only",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    raw = json.loads(result.stdout)
    return CaptureResult(path=raw["savedPath"], width=raw["width"], height=raw["height"])
