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
#
# Rule (locked in live with Eran after finding "Wall" had zero colliders
# anywhere, only its individual prop children did — aiming/raycasting at
# root-only objects silently missed real geometry):
#   - For each ROOT object: if it or any descendant has a Collider, emit
#     one entry per DIRECT CHILD of that root that itself has a Collider
#     (or the root itself, if the collider sits directly on the root with
#     no container level) — this is "one level below root," not the
#     absolute top, since collapsing a whole prop-container (e.g. "Asset"
#     holding 16 distinct props) to one point would throw away real,
#     individually meaningful objects.
#   - Second rule, same shape, for Light components specifically (found
#     live: a root named "Light" had NO Light component itself, just 2
#     Point Light children — set_light_properties failed on it with
#     "GameObject 'Light' has no component of type 'Light'" because the
#     first rule's "no collider anywhere -> keep root as-is" fallback
#     doesn't know about Light components at all). If a root has no
#     collider anywhere AND no Light component on itself AND has at least
#     one child WITH a Light component, emit those Light-bearing children
#     instead of the container — same principle as the collider rule,
#     just for a different component type.
#   - Otherwise (no collider anywhere, no Light anywhere in children
#     either — Main Camera, Global Volume): emit the root itself
#     unchanged, so non-collidable/non-light objects the agent still
#     needs to see/move don't silently disappear from scene context.
_READ_SCRIPT = """
System.Collections.Generic.IEnumerable<UnityEngine.Transform> AllDescendants(UnityEngine.Transform t) {
  foreach (UnityEngine.Transform child in t) {
    yield return child;
    foreach (var grandchild in AllDescendants(child)) yield return grandchild;
  }
}
bool HasColliderAnywhere(UnityEngine.Transform t) {
  if (t.gameObject.GetComponent<UnityEngine.Collider>() != null) return true;
  foreach (var d in AllDescendants(t)) {
    if (d.gameObject.GetComponent<UnityEngine.Collider>() != null) return true;
  }
  return false;
}
object Entry(UnityEngine.Transform t) {
  var p = t.position; var r = t.eulerAngles;
  return new { instance_id = t.gameObject.GetEntityId().ToString(), name = t.gameObject.name, pos_x = p.x, pos_y = p.y, pos_z = p.z, rot_x = r.x, rot_y = r.y, rot_z = r.z };
}
var list = new System.Collections.Generic.List<object>();
foreach (var t in UnityEngine.Object.FindObjectsByType<UnityEngine.Transform>()) {
  if (t.parent != null) continue;
  if (HasColliderAnywhere(t)) {
    if (t.gameObject.GetComponent<UnityEngine.Collider>() != null) { list.Add(Entry(t)); continue; }
    foreach (UnityEngine.Transform child in t) {
      if (child.gameObject.GetComponent<UnityEngine.Collider>() != null) list.Add(Entry(child));
    }
    continue;
  }
  if (t.gameObject.GetComponent<UnityEngine.Light>() != null) { list.Add(Entry(t)); continue; }
  bool anyChildIsLight = false;
  foreach (UnityEngine.Transform child in t) {
    if (child.gameObject.GetComponent<UnityEngine.Light>() != null) { list.Add(Entry(child)); anyChildIsLight = true; }
  }
  if (anyChildIsLight) continue;
  list.Add(Entry(t));
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


class LightProperties(BaseModel):
    """Current/target values for a Light component's mood-relevant fields."""

    intensity: float | None = None
    color_r: float | None = Field(default=None, description="0-1.")
    color_g: float | None = Field(default=None, description="0-1.")
    color_b: float | None = Field(default=None, description="0-1.")
    color_temperature: float | None = Field(default=None, description="Kelvin, e.g. 1800=warm candle, 6500=cool daylight.")
    bounce_intensity: float | None = Field(default=None, description="Indirect/bounce light multiplier.")


def get_light_properties(target: str) -> LightProperties:
    """Read a Light component's current mood-relevant fields by instance_id
    (same ID space as list_scene_transforms() — fetch it fresh this session,
    see docs/unity-cli-connection.md on why IDs aren't stable across
    sessions)."""
    result = subprocess.run(
        [
            UNITY_EXE,
            "command",
            "component get_fields",
            "--target",
            target,
            "--component",
            "Light",
            "--detail",
            "value",
            "--project-path",
            PROJECT_PATH,
            "--result-only",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    raw = json.loads(result.stdout)
    color = raw.get("m_Color") or {}
    return LightProperties(
        intensity=raw.get("m_Intensity"),
        color_r=color.get("r"),
        color_g=color.get("g"),
        color_b=color.get("b"),
        color_temperature=raw.get("m_ColorTemperature"),
        bounce_intensity=raw.get("m_BounceIntensity"),
    )


def set_light_properties(
    target: str,
    intensity: float | None = None,
    color: tuple[float, float, float] | None = None,
    color_temperature: float | None = None,
    bounce_intensity: float | None = None,
) -> None:
    """Set a Light component's mood-relevant fields by instance_id. Omit a
    field to leave it unchanged. color is (r, g, b), each 0-1.
    color_temperature is Kelvin and only visibly applies while
    m_UseColorTemperature is true (true by default on this scene's light —
    not managed here, see docs if that ever needs toggling)."""
    calls: list[tuple[str, object]] = []
    if intensity is not None:
        calls.append(("m_Intensity", intensity))
    if color is not None:
        calls.append(("m_Color", {"r": color[0], "g": color[1], "b": color[2], "a": 1.0}))
    if color_temperature is not None:
        calls.append(("m_ColorTemperature", color_temperature))
    if bounce_intensity is not None:
        calls.append(("m_BounceIntensity", bounce_intensity))

    for field, value in calls:
        subprocess.run(
            [
                UNITY_EXE,
                "command",
                "component set_field",
                "--target",
                target,
                "--component",
                "Light",
                "--field",
                field,
                "--value",
                json.dumps(value),
                "--project-path",
                PROJECT_PATH,
            ],
            capture_output=True,
            text=True,
            check=True,
        )


_VALID_LIGHT_TYPES = {"Spot", "Directional", "Point", "Rectangle", "Disc", "Pyramid", "Box", "Tube"}

# Creates the GameObject + sets position via script eval (ONE call,
# precise GetEntityId()) rather than the `gameobject create` CLI command.
# Real bug found live: `gameobject create`'s own JSON response truncates
# large instanceIds (float precision loss somewhere in its JSON encoding —
# e.g. returned ...755000 for an object whose real ID was ...755038), so an
# ID read from that command's output can silently fail every later command
# ("No loaded object with instanceId...") even though the object exists and
# gameobject find can locate it by name. script eval's GetEntityId() does
# not have this problem (same precise path list_scene_transforms() uses) —
# never trust a CLI JSON command's own returned instanceId for a large
# number, only script eval's. See docs/unity-cli-connection.md.
_CREATE_SCRIPT = """
var go = new UnityEngine.GameObject("__NAME__");
go.transform.position = new UnityEngine.Vector3(__POS_X__f, __POS_Y__f, __POS_Z__f);
return new { instance_id = go.GetEntityId().ToString() };
""".strip()


def create_light(
    name: str,
    position: tuple[float, float, float],
    light_type: str = "Point",
) -> str:
    """Create a new Light GameObject at position, with a Light component of
    light_type (Spot, Directional, Point, Rectangle, Disc, Pyramid, Box, or
    Tube — Unity's actual enum values, unquoted on the CLI). Returns the new
    object's instance_id (same ID space/session-dynamic caveat as
    list_scene_transforms(), read via script eval for precision — see
    docs/unity-cli-connection.md). Use set_light_properties afterward for
    intensity/color/etc, and set_object_transform for rotation."""
    if light_type not in _VALID_LIGHT_TYPES:
        raise ValueError(f"light_type must be one of {_VALID_LIGHT_TYPES}, got {light_type!r}")

    script = (
        _CREATE_SCRIPT.replace("__NAME__", name)
        .replace("__POS_X__", str(position[0]))
        .replace("__POS_Y__", str(position[1]))
        .replace("__POS_Z__", str(position[2]))
    )
    create_result = subprocess.run(
        [UNITY_EXE, "command", "script", "eval", script, "--result-only", "--project-path", PROJECT_PATH],
        capture_output=True,
        text=True,
        check=True,
    )
    instance_id = json.loads(create_result.stdout)["instance_id"]

    subprocess.run(
        [
            UNITY_EXE,
            "command",
            "component add",
            "--target",
            instance_id,
            "--type",
            "Light",
            "--project-path",
            PROJECT_PATH,
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    if light_type != "Point":  # Point is the Light component's own default
        subprocess.run(
            [
                UNITY_EXE,
                "command",
                "component set_field",
                "--target",
                instance_id,
                "--component",
                "Light",
                "--field",
                "m_Type",
                "--value",
                light_type,
                "--project-path",
                PROJECT_PATH,
            ],
            capture_output=True,
            text=True,
            check=True,
        )

    return instance_id


def count_lights() -> int:
    """How many Light components currently exist in the scene. Used by the
    MAX_LIGHTS guardrail in tools.py before create_light runs."""
    result = subprocess.run(
        [UNITY_EXE, "command", "gameobject find", "--type", "Light", "--project-path", PROJECT_PATH, "--result-only"],
        capture_output=True,
        text=True,
        check=True,
    )
    return len(json.loads(result.stdout))


# Pure calculation, no Unity object touched — uses Unity's own
# Quaternion.LookRotation (not hand-rolled trig, same principle as the
# raycast guardrail's use of Quaternion.Euler) to compute "what rotation
# makes something at light_position face target_position." Returns a plain
# euler tuple so callers can feed it straight into set_object_transform's
# existing rotation path, including its guardrail — this function does NOT
# apply anything itself, avoiding a second write path to keep in sync.
_LOOK_AT_SCRIPT = """
var lightPos = new UnityEngine.Vector3(__LIGHT_X__f, __LIGHT_Y__f, __LIGHT_Z__f);
var targetPos = new UnityEngine.Vector3(__TARGET_X__f, __TARGET_Y__f, __TARGET_Z__f);
var dir = (targetPos - lightPos).normalized;
var rot = UnityEngine.Quaternion.LookRotation(dir);
var e = rot.eulerAngles;
return new { rot_x = e.x, rot_y = e.y, rot_z = e.z };
""".strip()


def compute_look_at_rotation(
    light_position: tuple[float, float, float],
    target_position: tuple[float, float, float],
) -> tuple[float, float, float]:
    """Compute the euler rotation that makes an object at light_position
    face target_position, via Unity's own Quaternion.LookRotation. Does NOT
    apply anything — pass the result to set_object_transform's rotation
    args, which also runs the raycast guardrail on the result."""
    script = (
        _LOOK_AT_SCRIPT.replace("__LIGHT_X__", str(light_position[0]))
        .replace("__LIGHT_Y__", str(light_position[1]))
        .replace("__LIGHT_Z__", str(light_position[2]))
        .replace("__TARGET_X__", str(target_position[0]))
        .replace("__TARGET_Y__", str(target_position[1]))
        .replace("__TARGET_Z__", str(target_position[2]))
    )
    result = subprocess.run(
        [UNITY_EXE, "command", "script", "eval", script, "--result-only", "--project-path", PROJECT_PATH],
        capture_output=True,
        text=True,
        check=True,
    )
    raw = json.loads(result.stdout)
    return (raw["rot_x"], raw["rot_y"], raw["rot_z"])


# --- v3: post-processing (Volume) + fog ---------------------------------
#
# Volume components (ColorAdjustments, Vignette, Bloom, etc.) are NOT
# plain serialized fields readable via `component get_fields` the way
# Light fields are — confirmed live: `component get_fields --component
# UnityEngine.Rendering.Volume` resolves to the wrong thing. They live
# inside a VolumeProfile asset, accessed via `profile.TryGet<T>(out t)`,
# and each parameter is a VolumeParameter<T> wrapper (`.value`,
# `.overrideState`). So these go through script eval, same as everything
# else that doesn't fit the component get_fields/set_field shape.
#
# Found live: this project's "Global Volume" object already has
# ColorAdjustments active with real tuned values from the imported pack.
# Vignette did NOT exist in the profile and had to be added via
# `profile.Add<Vignette>(true)` before it could be set — confirmed this
# live, visually (screenshot showed real edge darkening after setting it).

_GET_COLOR_ADJUSTMENTS_SCRIPT = """
var go = UnityEngine.GameObject.Find("Global Volume");
var vol = go.GetComponent<UnityEngine.Rendering.Volume>();
UnityEngine.Rendering.Universal.ColorAdjustments ca;
vol.profile.TryGet(out ca);
return new { post_exposure = ca.postExposure.value, contrast = ca.contrast.value, saturation = ca.saturation.value, color_filter_r = ca.colorFilter.value.r, color_filter_g = ca.colorFilter.value.g, color_filter_b = ca.colorFilter.value.b };
""".strip()


class ColorAdjustments(BaseModel):
    """Global Volume's ColorAdjustments override — grading for the whole scene."""

    post_exposure: float = Field(description="Exposure offset in EV, 0 = unchanged.")
    contrast: float = Field(description="-100 to 100.")
    saturation: float = Field(description="-100 to 100, -100 = grayscale.")
    color_filter_r: float = Field(description="Tint color, 0-1.")
    color_filter_g: float
    color_filter_b: float


def get_color_adjustments() -> ColorAdjustments:
    """Read the Global Volume's current ColorAdjustments values."""
    result = subprocess.run(
        [UNITY_EXE, "command", "script", "eval", _GET_COLOR_ADJUSTMENTS_SCRIPT, "--result-only", "--project-path", PROJECT_PATH],
        capture_output=True,
        text=True,
        check=True,
    )
    return ColorAdjustments(**json.loads(result.stdout))


def set_color_adjustments(
    post_exposure: float | None = None,
    contrast: float | None = None,
    saturation: float | None = None,
    color_filter: tuple[float, float, float] | None = None,
) -> None:
    """Set any subset of the Global Volume's ColorAdjustments. Omit a field
    to leave it unchanged."""
    assignments = []
    if post_exposure is not None:
        assignments.append(f"ca.postExposure.overrideState = true; ca.postExposure.value = {post_exposure}f;")
    if contrast is not None:
        assignments.append(f"ca.contrast.overrideState = true; ca.contrast.value = {contrast}f;")
    if saturation is not None:
        assignments.append(f"ca.saturation.overrideState = true; ca.saturation.value = {saturation}f;")
    if color_filter is not None:
        assignments.append(
            f"ca.colorFilter.overrideState = true; ca.colorFilter.value = new UnityEngine.Color({color_filter[0]}f, {color_filter[1]}f, {color_filter[2]}f, 1f);"
        )
    if not assignments:
        return
    script = (
        'var go = UnityEngine.GameObject.Find("Global Volume");\n'
        "var vol = go.GetComponent<UnityEngine.Rendering.Volume>();\n"
        "UnityEngine.Rendering.Universal.ColorAdjustments ca;\n"
        "vol.profile.TryGet(out ca);\n"
        + "\n".join(assignments)
        + "\nreturn new { ok = true };"
    )
    subprocess.run(
        [UNITY_EXE, "command", "script", "eval", script, "--result-only", "--project-path", PROJECT_PATH],
        capture_output=True,
        text=True,
        check=True,
    )


_GET_VIGNETTE_SCRIPT = """
var go = UnityEngine.GameObject.Find("Global Volume");
var vol = go.GetComponent<UnityEngine.Rendering.Volume>();
UnityEngine.Rendering.Universal.Vignette vig;
bool exists = vol.profile.TryGet(out vig);
if (!exists) return new { exists = false, intensity = 0f, smoothness = 0f };
return new { exists = true, intensity = vig.intensity.value, smoothness = vig.smoothness.value };
""".strip()


class VignetteState(BaseModel):
    exists: bool = Field(description="False if Vignette has never been added to the profile.")
    intensity: float = Field(description="0-1, 0 = no vignette.")
    smoothness: float = Field(description="0-1, how gradual the falloff is.")


def get_vignette() -> VignetteState:
    """Read the Global Volume's current Vignette state. exists=False means
    it hasn't been added to the profile yet (set_vignette adds it)."""
    result = subprocess.run(
        [UNITY_EXE, "command", "script", "eval", _GET_VIGNETTE_SCRIPT, "--result-only", "--project-path", PROJECT_PATH],
        capture_output=True,
        text=True,
        check=True,
    )
    return VignetteState(**json.loads(result.stdout))


def set_vignette(intensity: float, smoothness: float = 0.4) -> None:
    """Set the Global Volume's Vignette intensity/smoothness, adding the
    override to the profile first if it isn't there yet (confirmed live:
    it wasn't present in this project's imported profile by default)."""
    script = f"""
var go = UnityEngine.GameObject.Find("Global Volume");
var vol = go.GetComponent<UnityEngine.Rendering.Volume>();
UnityEngine.Rendering.Universal.Vignette vig;
bool exists = vol.profile.TryGet(out vig);
if (!exists) vig = vol.profile.Add<UnityEngine.Rendering.Universal.Vignette>(true);
vig.intensity.overrideState = true;
vig.intensity.value = {intensity}f;
vig.smoothness.overrideState = true;
vig.smoothness.value = {smoothness}f;
return new {{ ok = true }};
""".strip()
    subprocess.run(
        [UNITY_EXE, "command", "script", "eval", script, "--result-only", "--project-path", PROJECT_PATH],
        capture_output=True,
        text=True,
        check=True,
    )


_GET_FOG_SCRIPT = """
return new { enabled = UnityEngine.RenderSettings.fog, color_r = UnityEngine.RenderSettings.fogColor.r, color_g = UnityEngine.RenderSettings.fogColor.g, color_b = UnityEngine.RenderSettings.fogColor.b, mode = UnityEngine.RenderSettings.fogMode.ToString(), density = UnityEngine.RenderSettings.fogDensity, start_distance = UnityEngine.RenderSettings.fogStartDistance, end_distance = UnityEngine.RenderSettings.fogEndDistance };
""".strip()


class FogState(BaseModel):
    enabled: bool
    color_r: float
    color_g: float
    color_b: float
    mode: str = Field(description="Linear, Exponential, or ExponentialSquared.")
    density: float = Field(description="Used by Exponential/ExponentialSquared modes.")
    start_distance: float = Field(description="Used by Linear mode.")
    end_distance: float = Field(description="Used by Linear mode.")


def get_fog() -> FogState:
    """Read the scene's current RenderSettings fog state (separate from
    the Volume profile — fog is a global scene render setting)."""
    result = subprocess.run(
        [UNITY_EXE, "command", "script", "eval", _GET_FOG_SCRIPT, "--result-only", "--project-path", PROJECT_PATH],
        capture_output=True,
        text=True,
        check=True,
    )
    return FogState(**json.loads(result.stdout))


def set_fog(
    enabled: bool | None = None,
    color: tuple[float, float, float] | None = None,
    density: float | None = None,
    start_distance: float | None = None,
    end_distance: float | None = None,
) -> None:
    """Set any subset of the scene's fog settings. Omit a field to leave
    it unchanged. Mode is left as whatever it already is (this project's
    scene is already Linear) — changing modes isn't exposed here, not
    needed for the v3 scope."""
    assignments = []
    if enabled is not None:
        assignments.append(f"UnityEngine.RenderSettings.fog = {'true' if enabled else 'false'};")
    if color is not None:
        assignments.append(
            f"UnityEngine.RenderSettings.fogColor = new UnityEngine.Color({color[0]}f, {color[1]}f, {color[2]}f, 1f);"
        )
    if density is not None:
        assignments.append(f"UnityEngine.RenderSettings.fogDensity = {density}f;")
    if start_distance is not None:
        assignments.append(f"UnityEngine.RenderSettings.fogStartDistance = {start_distance}f;")
    if end_distance is not None:
        assignments.append(f"UnityEngine.RenderSettings.fogEndDistance = {end_distance}f;")
    if not assignments:
        return
    script = "\n".join(assignments) + "\nreturn new { ok = true };"
    subprocess.run(
        [UNITY_EXE, "command", "script", "eval", script, "--result-only", "--project-path", PROJECT_PATH],
        capture_output=True,
        text=True,
        check=True,
    )


_GET_SCENE_BOUNDS_SCRIPT = """
var min = new UnityEngine.Vector3(float.MaxValue, float.MaxValue, float.MaxValue);
var max = new UnityEngine.Vector3(float.MinValue, float.MinValue, float.MinValue);
foreach (var t in UnityEngine.Object.FindObjectsByType<UnityEngine.Transform>()) {
  var p = t.position;
  min = UnityEngine.Vector3.Min(min, p);
  max = UnityEngine.Vector3.Max(max, p);
}
var size = max - min;
return new { diagonal = size.magnitude };
""".strip()


class SceneBounds(BaseModel):
    """Overall scene scale — used to sanity-check fog distances against
    the room's actual size, not a generic/guessed number."""

    diagonal: float = Field(description="Distance across the whole scene's bounding box, corner to corner.")


def get_scene_bounds() -> SceneBounds:
    """Compute the scene's overall diagonal size from every object's
    position. Found live (Eran caught it): the agent set fog
    end_distance=35 in a room whose real diagonal is ~22.8 — fog that
    extends well past the room's far wall fogs almost everything visible
    with no real near/far gradient, reading as a flat washed-out haze
    instead of atmospheric depth. This is what set_fog's guardrail checks
    distances against."""
    result = subprocess.run(
        [UNITY_EXE, "command", "script", "eval", _GET_SCENE_BOUNDS_SCRIPT, "--result-only", "--project-path", PROJECT_PATH],
        capture_output=True,
        text=True,
        check=True,
    )
    return SceneBounds(**json.loads(result.stdout))
