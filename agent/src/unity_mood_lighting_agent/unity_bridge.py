"""
unity_bridge.py — the current, live interface to Unity.

Consolidated from learning_steps/step6 (read) and step7 (write), which
remain in place as the record of how this was found/built/debugged. This
file is what the rest of the project actually imports going forward.

All deterministic, no agent/LLM here — reading/writing a transform by exact
name or ID has no ambiguity. See learning_steps/step5 for why that split
(code vs agent) was made.
"""

import base64
import json
import os
import subprocess
import tempfile

from pydantic import BaseModel, Field


def image_to_data_url(path: str) -> str:
    """Base64-encode a PNG into a data URL for the Agents SDK's
    input_image content block. Shared by judge.py (scoring) and main.py
    (giving the lighting agent itself a visual starting point, not just
    numeric scene context) — same encoding, two different callers."""
    with open(path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("utf-8")
    return f"data:image/png;base64,{encoded}"

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
  return new { instance_id = t.gameObject.GetEntityId().ToString(), name = t.gameObject.name, pos_x = p.x, pos_y = p.y, pos_z = p.z, rot_x = r.x, rot_y = r.y, rot_z = r.z, is_light = t.gameObject.GetComponent<UnityEngine.Light>() != null };
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
    is_light: bool = Field(default=False, description="True if this object has a Light component.")


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
    list_scene_transforms()) in WORLD space. Omit position or rotation to
    leave that channel unchanged.

    Deliberately does NOT use the Unity CLI's own `gameobject
    set_transform --position/--rotation` — confirmed live, 2026-11-24:
    that CLI command writes `transform.localPosition`/`localEulerAngles`
    (relative to the object's parent), while every read in this project
    (list_scene_transforms, get_scene_bounds) reports `transform.position`/
    `eulerAngles` (WORLD space, parent already baked in by Unity). Any
    object with a non-identity parent silently landed somewhere
    completely different from what was requested — found when a spatial-
    placement test asked for an absolute position and got a wildly
    different result. Fix: assign directly to `transform.position`/
    `transform.eulerAngles` (Unity's own world-space setters) via script
    eval instead — Unity computes the correct underlying localPosition
    for whatever parent exists, no manual matrix composition needed on
    our side, same principle as this file's rotation guardrail already
    using Quaternion.Euler instead of reimplementing that math in
    Python. See docs/unity-lighting-rendering-concepts.md for the full
    world-vs-local writeup."""
    assignments = []
    if position is not None:
        assignments.append(f"t.position = new UnityEngine.Vector3({position[0]}f, {position[1]}f, {position[2]}f);")
    if rotation is not None:
        assignments.append(f"t.eulerAngles = new UnityEngine.Vector3({rotation[0]}f, {rotation[1]}f, {rotation[2]}f);")
    if not assignments:
        return

    script = (
        "foreach (var t in UnityEngine.Object.FindObjectsByType<UnityEngine.Transform>(UnityEngine.FindObjectsSortMode.None)) { "
        "if (t.gameObject.GetEntityId().ToString() == \"" + str(target) + "\") { "
        + " ".join(assignments) + " break; } }\n"
        "return new { ok = true };"
    )
    subprocess.run(
        [UNITY_EXE, "command", "script", "eval", script, "--result-only", "--project-path", PROJECT_PATH],
        capture_output=True,
        text=True,
        check=True,
    )


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


# --- Rendered-content visibility guardrail (decided live with Eran,
# 2026-11-23) ----------------------------------------------------------
#
# Found live: a "post-apocalyptic" attempt went to a near-pure-black
# frame (mean_brightness=4.1/255, 98.8% of pixels near-black, vs a
# normal scene's 86.5/255 and 0.2%) after 3 attempts of the agent
# pushing exposure/vignette/fog further in the same direction with no
# signal it had crossed into "unreadable." This CANNOT be caught by
# clamping any single field's value — none of post_exposure, vignette
# intensity, or fog density were individually out of Unity's own legal
# range; it was the COMPOUND effect of several "reasonable alone"
# changes stacking together. The only reliable check is on the actual
# RENDERED pixels, not the input parameters that produced them — same
# principle as everything else in this project: verify the real
# result, don't trust that reasonable-looking inputs produce a
# reasonable-looking output.
#
# This is plain code (PIL, no LLM) — deciding "is this frame even
# visible" has one correct answer, same code-decides/LLM-judges split
# used everywhere else. Run this BEFORE the (expensive) judge LLM call
# so a genuinely blank frame never costs a model call at all.

VISIBILITY_MEAN_BRIGHTNESS_FLOOR = 1.0  # out of 255
VISIBILITY_NEAR_BLACK_PCT_CEILING = 99.0  # % of pixels below NEAR_BLACK_THRESHOLD
NEAR_BLACK_THRESHOLD = 15  # out of 255, per-pixel

# RECALIBRATED 2026-11-26, after the camera near-clip-plane fix (see
# docs/unity-lighting-rendering-concepts.md) changed what "normal"
# brightness looks like for this scene entirely. The original floor/
# ceiling (mean>=10.0, near_black<=90.0%) were calibrated against a
# camera that was secretly rendering a wall at point-blank range; once
# fixed, genuinely GOOD, legible eval results started measuring in a
# range the old thresholds flagged as near-black:
#   eerie_lab (confirmed legible via direct visual check): mean=2.2, pct=98.5%
#   post_apocalyptic (confirmed legible): mean=9.2, pct=88.6%
#   noir (confirmed legible): mean=10.6, pct=90.4%
#   horror (confirmed legible): mean=7.1, pct=94.8%
# vs. an empirically-forced crush on this same scene/lighting rig
# (pushed grading further until it broke): mean=0.4, pct=99.1% at
# severity~5.0, and a borderline/flatter-but-still-arguably-legible
# in-between point at mean=2.5, pct=98.2% (severity~4.0) that is
# numerically indistinguishable from eerie_lab's good 2.2/98.5% —
# confirms these two pixel stats genuinely CANNOT reliably separate
# "legitimately dark" from "a flat crush" once a scene gets this dark;
# it's not a threshold-tuning problem, it's a metric limitation.
# Response: set floor/ceiling to only catch the UNAMBIGUOUS case (a
# forced-crush mean=0.4) and let everything above that reach the judge,
# which can actually assess legibility/atmosphere instead of a blunt
# pixel average — matches this guardrail's own stated purpose (a safety
# net against degenerate results, not a style prescription). Revisit if
# a genuinely crushed frame ever measures above mean=1.0 in practice.

# Calibrated live (2026-11-24) against real reference images Eran provided
# (horror/horror2/noir/thriller/eerie_lab game screenshots) vs this
# project's own flat/failed agent results, both measured the same way
# (p90-p10 luminance spread): real references ranged 45-79, our agent's
# own flat outputs ranged 7-20 — a wide, clean gap. 35 sits comfortably
# below every real reference and well above anything the agent has
# produced so far. Revisit only if a genuinely high-contrast PASSING
# mood trips this floor (not yet observed).
CONTRAST_SPREAD_FLOOR = 3.0  # p90 - p10 luminance, out of 255
P10_CEILING = 30.0  # dark-zone luminance must actually be dark, out of 255
# Calibrated live, 2026-11-24: real THREAT/DRAMATIC references (horror,
# horror2, Noir, Thriller, Eerie Lab) measured p10 in 1-7 (genuinely
# near-black shadows); a manually-tuned "bright, evenly-lit room" that
# PASSED the spread floor (spread=68) measured p10=52 — spread alone is
# NOT sufficient, since a normal well-lit room with natural
# material/geometry variance can produce a wide p90-p10 gap without any
# of it actually being dark. p10<=30 sits above the loosest real
# high-contrast reference seen (Festive.jpg p10=20) and well below the
# false-positive bright-room case (52) — wide, clean gap, same
# calibration method as CONTRAST_SPREAD_FLOOR itself.

# CONTRAST_SPREAD_FLOOR recalibrated 2026-11-26, same camera-fix
# aftermath as the visibility floor above: the "revisit only if a
# genuinely high-contrast PASSING mood trips this floor" condition
# fired for real. Confirmed-legible eval results after the camera fix
# measured spread as low as 2 (eerie_lab) up to 23 (post_apocalyptic) —
# all far below the old 35.0 floor, because a small, perceptually
# salient bright accent (a glowing monitor, an arcade screen) against a
# mostly-dark room barely moves a 90th-percentile pixel COUNT even
# though it's exactly what sells the shot to a human eye. Same root
# limitation as the visibility floor: global percentile spread is not a
# reliable proxy for "does this read as dramatically lit" once lighting
# gets this localized/cinematic. Dropped to 3.0 — now only catches a
# genuinely flat, near-zero-variance frame; P10_CEILING (unchanged,
# still a real signal — no false positives observed on it) stays the
# meaningful half of this check, and the judge is trusted for the
# "does this actually look dramatic" call spread used to gatekeep.


class FrameVisibility(BaseModel):
    """Result of checking whether a captured frame has any visible content
    left, or has been pushed (by exposure/vignette/fog/lights together)
    past the point where there's anything left to judge a mood against."""

    mean_brightness: float = Field(description="0-255, average luminance across the whole frame.")
    pct_near_black: float = Field(description="0-100, percentage of pixels below the near-black threshold.")
    visible: bool = Field(description="False if the frame is effectively blank/unreadable.")


def check_frame_visibility(image_path: str) -> FrameVisibility:
    """Pure pixel-level check, no LLM. Calibrated live against a real
    failure: a bad frame measured mean_brightness=4.1, pct_near_black=98.8;
    a normal frame measured 86.5 and 0.2 — wide margin between the two,
    current thresholds (mean<10 OR >90% near-black) sit well below any
    legitimately dark mood (horror/noir) seen passing so far. Revisit if
    a genuinely dark PASSING mood ever trips this floor — not yet
    observed, so not over-tightened preemptively."""
    from PIL import Image

    img = Image.open(image_path).convert("L")
    histogram = img.histogram()  # 256 buckets, index = luminance value
    total_pixels = img.width * img.height
    mean_brightness = sum(i * count for i, count in enumerate(histogram)) / total_pixels
    near_black_pixels = sum(histogram[: NEAR_BLACK_THRESHOLD + 1])
    pct_near_black = (near_black_pixels / total_pixels) * 100

    visible = (
        mean_brightness >= VISIBILITY_MEAN_BRIGHTNESS_FLOOR
        and pct_near_black <= VISIBILITY_NEAR_BLACK_PCT_CEILING
    )
    return FrameVisibility(
        mean_brightness=round(mean_brightness, 1),
        pct_near_black=round(pct_near_black, 1),
        visible=visible,
    )


def _frame_percentiles(image_path: str, percentiles: tuple[int, ...]) -> list[int]:
    """Shared pixel-histogram percentile helper — pure PIL, no numpy
    (this project's venv doesn't have it), used by both check_frame_
    contrast and measure_frame_brightness so the two deterministic
    checks (and the baseline-brightness calibration reference) all
    compute luminance the exact same way."""
    from PIL import Image

    img = Image.open(image_path).convert("L")
    histogram = img.histogram()  # 256 buckets, index = luminance value
    total_pixels = img.width * img.height

    def _percentile(pct: float) -> int:
        target = total_pixels * pct / 100
        cumulative = 0
        for luminance, count in enumerate(histogram):
            cumulative += count
            if cumulative >= target:
                return luminance
        return 255

    return [_percentile(p) for p in percentiles]


class FrameBrightness(BaseModel):
    """A scene's render brightness, measured in real pixel terms — used
    as the lighting agent's calibration anchor for 'how bright is
    bright' (2026-11-25, Eran's call): hardcoding an intensity number
    doesn't generalize to a scene with zero existing lights, but a
    MEASURED render brightness does, since it's computed fresh for
    whatever scene is active, including an all-dark one."""

    mean_brightness: float = Field(description="0-255, average luminance across the whole frame.")
    p90: float = Field(description="90th percentile luminance, 0-255 — how bright the frame's brightest 10% already gets.")


def measure_frame_brightness(image_path: str) -> FrameBrightness:
    """Pure pixel-level measurement, no LLM — same percentile machinery
    as check_frame_contrast, but a plain fact (what IS this render's
    brightness), not a pass/fail guardrail judgment."""
    from PIL import Image

    img = Image.open(image_path).convert("L")
    histogram = img.histogram()
    total_pixels = img.width * img.height
    weighted_sum = sum(luminance * count for luminance, count in enumerate(histogram))
    mean_brightness = weighted_sum / total_pixels

    p90 = _frame_percentiles(image_path, (90,))[0]
    return FrameBrightness(mean_brightness=round(mean_brightness, 1), p90=float(p90))


class FrameContrast(BaseModel):
    """Result of checking whether a captured frame has real brightness
    SPREAD across it (a genuinely bright zone and a genuinely dark zone),
    as opposed to looking merely dim/dark but uniform. Distinct from
    FrameVisibility, which only catches the opposite failure (everything
    pushed to near-black) — a frame can easily pass visibility (not
    black) while still being flat (no real contrast), which is exactly
    the failure mode observed in horror/noir/thriller this session."""

    p10: float = Field(description="10th percentile luminance, 0-255 — how dark the dark zone actually gets.")
    p90: float = Field(description="90th percentile luminance, 0-255 — how bright the bright zone actually gets.")
    spread: float = Field(description="p90 - p10. Real dramatic lighting measured 45-79 on real game references; this project's own flat failures measured 7-20. Necessary but NOT sufficient on its own — a bright, evenly-lit room can also produce a wide spread from natural material variance without any real darkness; see p10/has_real_contrast.")
    has_real_contrast: bool = Field(description="True only if spread>=CONTRAST_SPREAD_FLOOR AND p10<=P10_CEILING — both a real gap AND a genuinely dark zone, not just a bright room with incidental tonal range.")


def check_frame_contrast(image_path: str) -> FrameContrast:
    """Pure pixel-level check, no LLM — same pattern as
    check_frame_visibility, but for the OPPOSITE failure mode: a frame
    that is not near-black (passes visibility) but is still flat/uniform,
    with no real difference between its brightest and darkest regions.
    Only meaningful for moods that actually call for high contrast —
    main.py gates this on mood_breakdown.target_contrast == 'high', a
    low-contrast mood (soft_ambient, etc.) is SUPPOSED to be flat and
    should never be rejected by this."""
    p10, p90 = _frame_percentiles(image_path, (10, 90))
    spread = p90 - p10
    return FrameContrast(
        p10=float(p10),
        p90=float(p90),
        spread=float(spread),
        has_real_contrast=(spread >= CONTRAST_SPREAD_FLOOR) and (p10 <= P10_CEILING),
    )


# Unity's Light.LightShadows enum displays these human names via
# `component get_fields` (read-only display strings) but accepts raw ints
# (0=None, 1=Hard, 2=Soft) via `component set_field` — confirmed live by
# setting m_Shadows.m_Type=2 and reading back "Soft Shadows".
_SHADOW_TYPE_DISPLAY_TO_NAME = {
    "No Shadows": "none",
    "Hard Shadows": "hard",
    "Soft Shadows": "soft",
}
_SHADOW_TYPE_NAME_TO_INT = {"none": 0, "hard": 1, "soft": 2}


class LightProperties(BaseModel):
    """Current/target values for a Light component's mood-relevant fields."""

    intensity: float | None = None
    color_r: float | None = Field(default=None, description="0-1.")
    color_g: float | None = Field(default=None, description="0-1.")
    color_b: float | None = Field(default=None, description="0-1.")
    color_temperature: float | None = Field(default=None, description="Kelvin, e.g. 1800=warm candle, 6500=cool daylight.")
    bounce_intensity: float | None = Field(default=None, description="Indirect/bounce light multiplier.")
    range: float | None = Field(default=None, description="World-space units the light reaches (Point/Spot only) — small = a tight contained pool, large = floods the whole room evenly. Compare against get_scene_bounds()'s diagonal, not a fixed number.")
    spot_angle: float | None = Field(default=None, description="Degrees, full cone width (Spot only) — narrow = a tight dramatic beam, wide = a broad soft wash.")
    shadow_type: str | None = Field(default=None, description="'none', 'hard', or 'soft' — whether this light casts a shadow at all. Lights created fresh default to 'none' (no shadow), which makes real directional shadow shape impossible regardless of intensity/range.")
    shadow_strength: float | None = Field(default=None, description="0-1 — how dark the shadow actually renders (0=invisible, 1=full black), independent of shadow_type.")
    use_color_temperature: bool | None = Field(default=None, description="Whether color_temperature actually affects this light's rendered color at all — if False, color_temperature is a silent no-op and only the color (RGB) field is visible. set_light_properties always forces this True whenever color_temperature is given.")


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
            str(target),
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
    shadows = raw.get("m_Shadows") or {}
    shadow_type_raw = shadows.get("m_Type")
    shadow_type = _SHADOW_TYPE_DISPLAY_TO_NAME.get(shadow_type_raw, shadow_type_raw) if shadow_type_raw else None
    return LightProperties(
        intensity=raw.get("m_Intensity"),
        color_r=color.get("r"),
        color_g=color.get("g"),
        color_b=color.get("b"),
        color_temperature=raw.get("m_ColorTemperature"),
        bounce_intensity=raw.get("m_BounceIntensity"),
        range=raw.get("m_Range"),
        spot_angle=raw.get("m_SpotAngle"),
        shadow_type=shadow_type,
        shadow_strength=shadows.get("m_Strength"),
        use_color_temperature=raw.get("m_UseColorTemperature"),
    )


def set_light_properties(
    target: str,
    intensity: float | None = None,
    color: tuple[float, float, float] | None = None,
    color_temperature: float | None = None,
    bounce_intensity: float | None = None,
    range: float | None = None,
    spot_angle: float | None = None,
    shadow_type: str | None = None,
    shadow_strength: float | None = None,
) -> None:
    """Set a Light component's mood-relevant fields by instance_id. Omit a
    field to leave it unchanged. color is (r, g, b), each 0-1.
    color_temperature is Kelvin — ALWAYS forces m_UseColorTemperature=true
    in the same call (confirmed live 2026-11-26: Unity's own Light default
    is false, meaning color_temperature was previously a silent no-op on
    both this scene's original lights the whole time; do not revert this
    without re-confirming). range is world-space units (Point/Spot only).
    spot_angle is degrees, full cone width (Spot only). shadow_type is
    'none'/'hard'/'soft'. shadow_strength is 0-1 — how dark the shadow
    actually renders (0=invisible, 1=full black), independent of
    shadow_type; lets soft_ambient (shadows barely registering) and noir
    (full-strength near-black shadows) actually differ, which shadow_type
    alone can't express."""
    calls: list[tuple[str, object]] = []
    if intensity is not None:
        calls.append(("m_Intensity", intensity))
    if color is not None:
        calls.append(("m_Color", {"r": color[0], "g": color[1], "b": color[2], "a": 1.0}))
    if color_temperature is not None:
        calls.append(("m_ColorTemperature", color_temperature))
        calls.append(("m_UseColorTemperature", True))
    if bounce_intensity is not None:
        calls.append(("m_BounceIntensity", bounce_intensity))
    if range is not None:
        calls.append(("m_Range", range))
    if spot_angle is not None:
        calls.append(("m_SpotAngle", spot_angle))
    if shadow_type is not None:
        calls.append(("m_Shadows.m_Type", _SHADOW_TYPE_NAME_TO_INT[shadow_type]))
    if shadow_strength is not None:
        calls.append(("m_Shadows.m_Strength", shadow_strength))

    for field, value in calls:
        subprocess.run(
            [
                UNITY_EXE,
                "command",
                "component set_field",
                "--target",
                str(target),
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

    # Unity's own Light component default is "No Shadows" (confirmed live,
    # 2026-11-24) — silently making real directional shadow shape
    # impossible regardless of intensity/range. Soft is a sane default a
    # mood-lighting agent almost always wants; set_light_properties can
    # still override to 'none'/'hard' afterward if a specific mood calls
    # for it.
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
            "m_Shadows.m_Type",
            "--value",
            str(_SHADOW_TYPE_NAME_TO_INT["soft"]),
            "--project-path",
            PROJECT_PATH,
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    # Confirmed live (2026-11-26): Unity's own Light component default is
    # m_UseColorTemperature=false, meaning set_light_properties'
    # color_temperature param is a SILENT NO-OP on any light where this
    # isn't explicitly forced true — confirmed on this scene's ORIGINAL 2
    # lights too, every color_temperature value this project has ever set
    # (across this entire project's history) rendered through m_Color
    # alone. Forcing it true on every new light so this doesn't repeat.
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
            "m_UseColorTemperature",
            "--value",
            "true",
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


def delete_object(target: str) -> None:
    """Delete a GameObject from the scene by instance_id. Confirmed live
    via `unity command --query delete`: `gameobject delete` takes exactly
    one param, --target (reversible via Unity's own Undo, not exposed
    here). Deterministic, no LLM involved — tools.py's delete_light is
    responsible for deciding WHICH lights are safe to delete; this
    function just executes the deletion once that's decided."""
    subprocess.run(
        [UNITY_EXE, "command", "gameobject delete", "--target", str(target), "--project-path", PROJECT_PATH],
        capture_output=True,
        text=True,
        check=True,
    )


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
UnityEngine.Rendering.Volume vol = null;
foreach (var v in UnityEngine.Object.FindObjectsByType<UnityEngine.Rendering.Volume>(UnityEngine.FindObjectsSortMode.None)) { if (v.isGlobal) { vol = v; break; } }
if (vol == null) return new { post_exposure = 0f, contrast = 0f, saturation = 0f, color_filter_r = 1f, color_filter_g = 1f, color_filter_b = 1f };
UnityEngine.Rendering.Universal.ColorAdjustments ca;
bool exists = vol.profile.TryGet(out ca);
if (!exists) return new { post_exposure = 0f, contrast = 0f, saturation = 0f, color_filter_r = 1f, color_filter_g = 1f, color_filter_b = 1f };
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
        "UnityEngine.Rendering.Volume vol = null;\n"
        "foreach (var v in UnityEngine.Object.FindObjectsByType<UnityEngine.Rendering.Volume>(UnityEngine.FindObjectsSortMode.None)) { if (v.isGlobal) { vol = v; break; } }\n"
        "if (vol == null) return new { ok = false, error = \"No global Volume found in the active scene.\" };\n"
        "UnityEngine.Rendering.Universal.ColorAdjustments ca;\n"
        "bool exists = vol.profile.TryGet(out ca);\n"
        "if (!exists) ca = vol.profile.Add<UnityEngine.Rendering.Universal.ColorAdjustments>(true);\n"
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
UnityEngine.Rendering.Volume vol = null;
foreach (var v in UnityEngine.Object.FindObjectsByType<UnityEngine.Rendering.Volume>(UnityEngine.FindObjectsSortMode.None)) { if (v.isGlobal) { vol = v; break; } }
if (vol == null) return new { exists = false, intensity = 0f, smoothness = 0f };
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
UnityEngine.Rendering.Volume vol = null;
foreach (var v in UnityEngine.Object.FindObjectsByType<UnityEngine.Rendering.Volume>(UnityEngine.FindObjectsSortMode.None)) {{ if (v.isGlobal) {{ vol = v; break; }} }}
if (vol == null) return new {{ ok = false, error = "No global Volume found in the active scene." }};
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


_GET_AMBIENT_SCRIPT = """
return new { intensity = UnityEngine.RenderSettings.ambientIntensity };
""".strip()


class AmbientState(BaseModel):
    intensity: float = Field(
        description="0-1+, scene-wide uniform ambient fill applied to EVERY "
        "surface regardless of any individual light. Unity's default is 1.0. "
        "Confirmed live, 2026-11-24: this is a real, previously-invisible "
        "floor under every 'dark zone' in the frame — dropping it from 1.0 "
        "to 0.05 measurably darkened a frame's darkest 10th percentile "
        "(16 -> 7 out of 255) with no light changes at all."
    )


def get_ambient() -> AmbientState:
    """Read the scene's current ambient light intensity (RenderSettings,
    not a Volume override — a simpler static property, no profile
    involved)."""
    result = subprocess.run(
        [UNITY_EXE, "command", "script", "eval", _GET_AMBIENT_SCRIPT, "--result-only", "--project-path", PROJECT_PATH],
        capture_output=True,
        text=True,
        check=True,
    )
    return AmbientState(**json.loads(result.stdout))


def set_ambient(intensity: float) -> None:
    """Set the scene's ambient light intensity. Low (near 0) for
    high-contrast/dramatic moods so un-lit areas can actually read as
    near-black instead of sitting on a uniform ambient floor; higher is
    fine for soft/diffuse moods where that floor is the desired look."""
    script = f"UnityEngine.RenderSettings.ambientIntensity = {intensity}f; return new {{ ok = true }};"
    subprocess.run(
        [UNITY_EXE, "command", "script", "eval", script, "--result-only", "--project-path", PROJECT_PATH],
        capture_output=True,
        text=True,
        check=True,
    )


class SkyboxState(BaseModel):
    path: str | None = Field(description="Project-relative path to the current skybox material, or None if unset.")


def get_skybox() -> SkyboxState:
    """Read the scene's current skybox material path — a simple ground-
    truth reader, distinct from the richer set_skybox(skybox_id, ...)/
    list_available_skyboxes() pair below (which the agent actually calls
    to pick a mood-appropriate HDRI by id). Used for baseline capture/
    restore and lever-usage diffing, not by the agent directly.
    RenderSettings.ambientMode is Skybox on this scene (confirmed live),
    so swapping it genuinely changes indoor ambient light color/
    intensity too, not just a visible backdrop through windows."""
    script = (
        "string p = UnityEngine.RenderSettings.skybox != null ? "
        "UnityEditor.AssetDatabase.GetAssetPath(UnityEngine.RenderSettings.skybox) : null; "
        "return new { path = p };"
    )
    result = subprocess.run(
        [UNITY_EXE, "command", "script", "eval", script, "--result-only", "--project-path", PROJECT_PATH],
        capture_output=True,
        text=True,
        check=True,
    )
    return SkyboxState(**json.loads(result.stdout))


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
return new {
  diagonal = size.magnitude,
  min_x = min.x, min_y = min.y, min_z = min.z,
  max_x = max.x, max_y = max.y, max_z = max.z
};
""".strip()


class SceneBounds(BaseModel):
    """The scene's real spatial envelope — every object's position
    rolled into one min/max box. Used both to sanity-check fog distances
    (diagonal) and to ground the agent's own placement/creation
    decisions in real coordinates, and to reject anything placed outside
    it (see check_position_within_bounds)."""

    diagonal: float = Field(description="Distance across the whole scene's bounding box, corner to corner.")
    min_x: float
    min_y: float
    min_z: float
    max_x: float
    max_y: float
    max_z: float


def get_scene_bounds() -> SceneBounds:
    """Compute the scene's real bounding box (min/max corners on every
    axis, plus the diagonal) from every object's position. Found live
    (Eran caught it): the agent set fog end_distance=35 in a room whose
    real diagonal is ~22.8 — fog that extends well past the room's far
    wall fogs almost everything visible with no real near/far gradient,
    reading as a flat washed-out haze instead of atmospheric depth. The
    diagonal is what set_fog's guardrail checks distances against; the
    full min/max box is what gives the agent real spatial grounding for
    placement (surfaced in get_scene_context()) and what
    check_position_within_bounds() rejects placements outside of —
    planned in the original v0 tool list, never actually built until
    now."""
    result = subprocess.run(
        [UNITY_EXE, "command", "script", "eval", _GET_SCENE_BOUNDS_SCRIPT, "--result-only", "--project-path", PROJECT_PATH],
        capture_output=True,
        text=True,
        check=True,
    )
    return SceneBounds(**json.loads(result.stdout))


class PositionBoundsCheck(BaseModel):
    """Whether a candidate position sits inside the scene's real
    bounding box (every axis, not just distance) — planned in the
    original v0 guardrail list ('position within the scene's bounding
    box, reject lights placed outside the room/level geometry'), never
    actually built until now."""

    within: bool
    bounds: SceneBounds = Field(description="The scene's current bounding box, for building a useful rejection message.")


def check_position_within_bounds(position: tuple[float, float, float]) -> PositionBoundsCheck:
    """Pure math, no new Unity call beyond the get_scene_bounds() read —
    checks a candidate position against every axis (x/y/z — width,
    height, length) of the scene's real bounding box, not just overall
    scale. Strict min/max, no padding margin: the bounds are computed
    from object PIVOT positions, not actual mesh surfaces, so a
    placement that's technically a little outside the measured box can
    still be visually 'in the room' — if this rejects too eagerly in
    practice, that's the first thing to loosen, not the check itself."""
    bounds = get_scene_bounds()
    x, y, z = position
    within = bounds.min_x <= x <= bounds.max_x and bounds.min_y <= y <= bounds.max_y and bounds.min_z <= z <= bounds.max_z
    return PositionBoundsCheck(within=within, bounds=bounds)


# --- Skybox (HDRI) -----------------------------------------------------
#
# HDRI assets live in MoodLightingScene/Assets/HDRIs/ (sourced from
# polyhaven.com, CC0). The manifest below is plain local metadata, NOT a
# live Unity read — listing what's available has no ambiguity (same
# Code vs. agent rule as list_scene_transforms), so this never touches
# Unity at all. Only the import below fsync's against Unity when it
# actually sets a skybox.

_HDRI_MANIFEST_PATH = os.path.join(os.path.dirname(__file__), "data", "hdri_manifest.json")


class SkyboxOption(BaseModel):
    """One available HDRI skybox, with the metadata the agent reasons over
    to pick a mood-appropriate one. Sourced from polyhaven.com's own
    attribute tagging, not hand-written — their categorization is already
    exactly what a mood decision needs (environment, time of day, weather,
    light type, contrast)."""

    id: str = Field(description="Stable identifier, pass this to set_skybox().")
    filename: str = Field(description="The .hdr file in Assets/HDRIs/.")
    display_name: str
    environment: str | None = Field(default=None, description="'indoor' or 'outdoor'.")
    time_of_day: str | None = None
    weather: str | None = None
    light_type: str | None = Field(default=None, description="'natural', 'artificial', or 'mixed'.")
    contrast: str | None = Field(default=None, description="'low', 'medium', or 'high'.")
    sky_view: str | None = Field(default=None, description="'open' or 'obstructed' — whether open sky is actually visible.")
    tags: list[str] = Field(default_factory=list)
    description: str | None = None


def list_available_skyboxes() -> list[SkyboxOption]:
    """Read the local HDRI manifest (no Unity call — pure local data,
    deterministic). Use this to decide IF a skybox swap fits the mood and
    scene (indoor scene with no visible sky may see little effect) and
    WHICH one, before calling set_skybox()."""
    with open(_HDRI_MANIFEST_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return [SkyboxOption(**entry) for entry in raw]


def set_skybox(skybox_id: str, exposure: float = 1.0, rotation: float = 0.0, tint: tuple[float, float, float] | None = None) -> str:
    """Swap the scene's skybox to one of the HDRIs listed by
    list_available_skyboxes(), by id. exposure (default 1.0, Unity's own
    neutral default) scales overall sky brightness; rotation (0-360
    degrees) spins the HDRI around the vertical axis, useful for moving
    a sun/bright spot out of a bad position. tint (r, g, b, each 0-1,
    default neutral (0.5, 0.5, 0.5) — Unity's Skybox/Panoramic shader
    multiplies _Tint by 2 internally, so 0.5 is the no-op midpoint, not
    0 or 1) color-shifts the whole sky AND, since ambient is
    skybox-driven, the scene's indoor ambient light too — a real,
    nearly-free color lever on top of whichever HDRI is chosen (red for
    an ominous sky, green for toxic/alien, etc. — confirmed 2026-11-26,
    this was previously a hardcoded dead parameter on the exact same
    shader already in use). Uses Unity's built-in Skybox/Panoramic shader
    (pipeline-agnostic — URP's DrawSkyboxPass just renders whatever
    RenderSettings.skybox points at, confirmed live against this
    project's URP shader property list: _MainTex, _Mapping, _ImageType,
    _Exposure, _Rotation, _Tint). Mapping is fixed to Latitude-Longitude
    (equirectangular) since that's the format every polyhaven.com HDRI
    download uses — confirmed live, not guessed. Creates one real .mat
    asset per skybox under Assets/HDRIs/Materials/ (reused on repeat
    calls, not recreated). Calls DynamicGI.UpdateEnvironment() so ambient
    light/reflections pick up the change immediately, not just the
    visible dome."""
    options = {opt.id: opt for opt in list_available_skyboxes()}
    if skybox_id not in options:
        valid = ", ".join(sorted(options))
        return f"Error: unknown skybox_id '{skybox_id}'. Valid ids: {valid}"
    filename = options[skybox_id].filename
    tint_r, tint_g, tint_b = tint if tint is not None else (0.5, 0.5, 0.5)

    script = f"""
var texPath = "Assets/HDRIs/{filename}";
var tex = UnityEditor.AssetDatabase.LoadAssetAtPath<UnityEngine.Texture>(texPath);
if (tex == null) return new {{ ok = false, error = "HDRI texture not found at " + texPath }};

string matDir = "Assets/HDRIs/Materials";
if (!UnityEditor.AssetDatabase.IsValidFolder(matDir)) {{
    UnityEditor.AssetDatabase.CreateFolder("Assets/HDRIs", "Materials");
}}
string matPath = matDir + "/{skybox_id}.mat";
var mat = UnityEditor.AssetDatabase.LoadAssetAtPath<UnityEngine.Material>(matPath);
if (mat == null) {{
    var shader = UnityEngine.Shader.Find("Skybox/Panoramic");
    mat = new UnityEngine.Material(shader);
    UnityEditor.AssetDatabase.CreateAsset(mat, matPath);
}}
mat.SetTexture("_MainTex", tex);
mat.SetFloat("_Mapping", 1f);
mat.SetFloat("_ImageType", 0f);
mat.SetFloat("_Exposure", {exposure}f);
mat.SetFloat("_Rotation", {rotation}f);
mat.SetColor("_Tint", new UnityEngine.Color({tint_r}f, {tint_g}f, {tint_b}f, 0.5f));
UnityEditor.EditorUtility.SetDirty(mat);
UnityEngine.RenderSettings.skybox = mat;
UnityEngine.DynamicGI.UpdateEnvironment();
UnityEditor.AssetDatabase.SaveAssets();
return new {{ ok = true, material_path = matPath }};
""".strip()

    result = subprocess.run(
        [UNITY_EXE, "command", "script", "eval", script, "--result-only", "--project-path", PROJECT_PATH],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(result.stdout)
    if not data.get("ok"):
        return f"Error: {data.get('error', 'unknown failure setting skybox')}"
    return f"Skybox set to '{skybox_id}' ({options[skybox_id].display_name}), exposure={exposure}, rotation={rotation}, tint=({tint_r}, {tint_g}, {tint_b})."


# --- Scene selection ----------------------------------------------------
#
# Multiple real test scenes now exist (TestRoom, the Mess Hall sci-fi
# interior, the Forest outdoor demo) — nothing in the pipeline tracked or
# controlled WHICH one was active, so main.py silently ran a task against
# whatever happened to be open (found live, Eran caught it: an outdoor
# forest test case actually ran against TestRoom after a manual switch).
# "Is the right scene loaded" has exactly one correct answer, same Code
# vs. agent rule as everything else here — deterministic, not the LLM's
# job.

_GET_ACTIVE_SCENE_SCRIPT = """
var s = UnityEditor.SceneManagement.EditorSceneManager.GetActiveScene();
return new { name = s.name, path = s.path };
""".strip()


class ActiveScene(BaseModel):
    name: str
    path: str = Field(description="Project-relative path, e.g. 'Assets/Scenes/TestRoom.unity'.")


def get_active_scene() -> ActiveScene:
    """Read which scene is CURRENTLY open in the Editor. Deterministic,
    no ambiguity — just a live read, same as list_scene_transforms()."""
    result = subprocess.run(
        [UNITY_EXE, "command", "script", "eval", _GET_ACTIVE_SCENE_SCRIPT, "--result-only", "--project-path", PROJECT_PATH],
        capture_output=True,
        text=True,
        check=True,
    )
    return ActiveScene(**json.loads(result.stdout))


def open_scene(scene_path: str) -> None:
    """Force-load the given scene by project-relative path (e.g.
    'Assets/Scenes/TestRoom.unity'), discarding unsaved changes to
    whatever's currently open. Called by main.py's run() BEFORE any
    cleanup/agent work, only when get_active_scene() doesn't already
    match — never silently assumed."""
    script = f'UnityEditor.SceneManagement.EditorSceneManager.OpenScene("{scene_path}"); return new {{ ok = true }};'
    subprocess.run(
        [UNITY_EXE, "command", "script", "eval", script, "--result-only", "--project-path", PROJECT_PATH],
        capture_output=True,
        text=True,
        check=True,
    )


# --- Scene readiness / baseline (v6, see README) -------------------------
#
# Two real problems, both found live testing against new scenes:
# (1) a scene's rendering config can silently break the whole "instant
#     mood change" promise (Baked lights/probes won't visually update
#     until a rebake — see docs/unity-lighting-rendering-concepts.md),
# (2) nothing ever stored a scene's TRUE original values before mutating
#     it, so reset_post_processing() could only reset to an invented
#     neutral baseline, not what the scene actually started as (the
#     Forest pack's real artist-tuned grading is already gone — lesson
#     learned, not repeating it for every future scene).
#
# capture_scene_baseline() MUST run (and only capture once per scene,
# never overwrite) before ensure_scene_ready() touches anything.

_BASELINE_DIR = os.path.join(os.path.dirname(__file__), "data", "scene_baselines")

_CAPTURE_BASELINE_SCRIPT = """
var lights = UnityEngine.Object.FindObjectsByType<UnityEngine.Light>(UnityEngine.FindObjectsSortMode.None);
var lightInfo = new System.Collections.Generic.List<object>();
foreach (var l in lights) {
    lightInfo.Add(new {
        instance_id = l.gameObject.GetEntityId().ToString(),
        name = l.gameObject.name,
        mode = l.lightmapBakeType.ToString(),
        type = l.type.ToString(),
        intensity = l.intensity,
        color_r = l.color.r, color_g = l.color.g, color_b = l.color.b,
        range = l.range,
        spot_angle = l.spotAngle,
        color_temperature = l.colorTemperature,
        bounce_intensity = l.bounceIntensity,
        shadow_type_int = (int)l.shadows,
        shadow_strength = l.shadowStrength,
        use_color_temperature = l.useColorTemperature,
        pos_x = l.transform.position.x, pos_y = l.transform.position.y, pos_z = l.transform.position.z,
        rot_x = l.transform.eulerAngles.x, rot_y = l.transform.eulerAngles.y, rot_z = l.transform.eulerAngles.z
    });
}
var probes = UnityEngine.Object.FindObjectsByType<UnityEngine.ReflectionProbe>(UnityEngine.FindObjectsSortMode.None);
var probeInfo = new System.Collections.Generic.List<object>();
foreach (var p in probes) {
    probeInfo.Add(new { instance_id = p.gameObject.GetEntityId().ToString(), name = p.gameObject.name, mode = p.mode.ToString() });
}
string skyboxPath = UnityEngine.RenderSettings.skybox != null ? UnityEditor.AssetDatabase.GetAssetPath(UnityEngine.RenderSettings.skybox) : null;
bool realtimeGI = false, bakedGI = false;
try {
    var ls = UnityEditor.Lightmapping.lightingSettings;
    if (ls != null) { realtimeGI = ls.realtimeGI; bakedGI = ls.bakedGI; }
} catch { }
return new {
    lights = lightInfo,
    reflection_probes = probeInfo,
    skybox_material_path = skyboxPath,
    realtime_gi = realtimeGI,
    baked_gi = bakedGI
};
""".strip()


def _baseline_path_for_scene(scene_path: str) -> str:
    safe_name = "".join(c if c.isalnum() else "_" for c in scene_path)
    return os.path.join(_BASELINE_DIR, f"{safe_name}.json")


def capture_scene_baseline(scene_path: str | None = None) -> dict:
    """Snapshot the CURRENT scene's real original state (light modes +
    properties, reflection probe modes, skybox material, GI settings) to
    a JSON file keyed by scene path — ONLY if no baseline exists yet for
    this scene. Never overwrites an existing baseline (the whole point
    is capturing truth before anything touches it; capturing again later
    would just save already-mutated state as if it were original, the
    exact mistake that already happened once to the Forest scene's real
    artist-tuned values). Also captures ColorAdjustments/Vignette/Fog
    via the existing get_* functions, same post-processing data
    reset_post_processing() already knows how to re-apply."""
    if scene_path is None:
        scene_path = get_active_scene().path
    path = _baseline_path_for_scene(scene_path)
    if os.path.exists(path):
        return {"status": "already_captured", "path": path}

    result = subprocess.run(
        [UNITY_EXE, "command", "script", "eval", _CAPTURE_BASELINE_SCRIPT, "--result-only", "--project-path", PROJECT_PATH],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(result.stdout)
    data["scene_path"] = scene_path
    color = get_color_adjustments()
    vignette = get_vignette()
    fog = get_fog()
    data["color_adjustments"] = color.model_dump()
    data["vignette"] = vignette.model_dump()
    data["fog"] = fog.model_dump()
    data["ambient"] = get_ambient().model_dump()
    data["baseline_brightness"] = measure_frame_brightness(capture_game_view().path).model_dump()

    os.makedirs(_BASELINE_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return {"status": "captured", "path": path, "light_count": len(data["lights"]), "probe_count": len(data["reflection_probes"])}


_ENSURE_READY_SCRIPT = """
var report = new System.Collections.Generic.Dictionary<string, object>();

// 1. Global Volume — find by component (isGlobal), create if missing entirely.
UnityEngine.Rendering.Volume vol = null;
foreach (var v in UnityEngine.Object.FindObjectsByType<UnityEngine.Rendering.Volume>(UnityEngine.FindObjectsSortMode.None)) { if (v.isGlobal) { vol = v; break; } }
bool volumeCreated = false;
if (vol == null) {
    var go = new UnityEngine.GameObject("Global Volume");
    vol = go.AddComponent<UnityEngine.Rendering.Volume>();
    vol.isGlobal = true;
    var profile = UnityEngine.ScriptableObject.CreateInstance<UnityEngine.Rendering.VolumeProfile>();
    string dir = "Assets/_GeneratedVolumes";
    if (!UnityEditor.AssetDatabase.IsValidFolder(dir)) UnityEditor.AssetDatabase.CreateFolder("Assets", "_GeneratedVolumes");
    UnityEditor.AssetDatabase.CreateAsset(profile, dir + "/AutoGlobalVolumeProfile.asset");
    vol.sharedProfile = profile;
    volumeCreated = true;
}
report["volume_created"] = volumeCreated;

// 1b. Tonemapping override — confirmed live 2026-11-26: this project's
// Volume profile had NO Tonemapping override at all, meaning URP falls
// back to "None" mode (no filmic curve at all) instead of any tonemap
// pass. A/B tested live on the real clean baseline: None (mean=83.4,
// p90=97.0) and Neutral (mean=84.8, p90=98.0) are nearly identical —
// Neutral adds gentle highlight handling with no real shadow cost.
// ACES (mean=52.9, p90=66.0) measured MEANINGFULLY darker — its
// characteristic filmic shadow-crushing toe. Given this project's
// single most recurring problem across its entire history has been
// scenes accidentally crushing to black, deliberately picking the
// MORE shadow-crushing tonemapper would work directly against that —
// Neutral chosen instead, not ACES, specifically for this reason.
UnityEngine.Rendering.Universal.Tonemapping tonemapping;
bool tonemappingExists = vol.profile.TryGet<UnityEngine.Rendering.Universal.Tonemapping>(out tonemapping);
bool tonemappingAdded = false;
if (!tonemappingExists) {
    tonemapping = vol.profile.Add<UnityEngine.Rendering.Universal.Tonemapping>(true);
    tonemapping.mode.overrideState = true;
    tonemapping.mode.value = UnityEngine.Rendering.Universal.TonemappingMode.Neutral;
    tonemappingAdded = true;
}
report["tonemapping_added"] = tonemappingAdded;
report["tonemapping_mode"] = tonemapping.mode.value.ToString();

// 2. Every light -> Realtime mode.
var lights = UnityEngine.Object.FindObjectsByType<UnityEngine.Light>(UnityEngine.FindObjectsSortMode.None);
int lightsFixed = 0;
foreach (var l in lights) {
    if (l.lightmapBakeType != UnityEngine.LightmapBakeType.Realtime) { l.lightmapBakeType = UnityEngine.LightmapBakeType.Realtime; lightsFixed++; }
}
report["light_count"] = lights.Length;
report["lights_fixed"] = lightsFixed;

// 3. Zero lights -> create one baseline directional light so the agent has something to adjust.
bool lightCreated = false;
if (lights.Length == 0) {
    var go = new UnityEngine.GameObject("Directional Light");
    var l = go.AddComponent<UnityEngine.Light>();
    l.type = UnityEngine.LightType.Directional;
    l.lightmapBakeType = UnityEngine.LightmapBakeType.Realtime;
    l.intensity = 1.0f;
    go.transform.rotation = UnityEngine.Quaternion.Euler(50f, -30f, 0f);
    lightCreated = true;
}
report["baseline_light_created"] = lightCreated;

// 4. Every reflection probe -> Realtime mode.
var probes = UnityEngine.Object.FindObjectsByType<UnityEngine.ReflectionProbe>(UnityEngine.FindObjectsSortMode.None);
int probesFixed = 0;
foreach (var p in probes) {
    if (p.mode != UnityEngine.Rendering.ReflectionProbeMode.Realtime) { p.mode = UnityEngine.Rendering.ReflectionProbeMode.Realtime; probesFixed++; }
}
report["probe_count"] = probes.Length;
report["probes_fixed"] = probesFixed;

return report;
""".strip()


def ensure_scene_ready(scene_path: str | None = None) -> dict:
    """Bootstrap the CURRENT scene so mood changes will actually be
    visible in real time (see docs/unity-lighting-rendering-concepts.md):
    calls capture_scene_baseline() FIRST (guarantees the real original is
    saved before anything below touches it), then creates a missing
    Global Volume, adds a Neutral Tonemapping override if none exists
    (confirmed live 2026-11-26: this project rendered with NO tonemapping
    at all for its entire history; A/B tested None/Neutral/ACES on the
    real clean baseline — ACES measured meaningfully darker from its
    shadow-crushing filmic toe, the wrong direction for a project whose
    single biggest recurring bug has been accidental crushing; Neutral
    chosen instead, nearly identical to having none at all but with
    gentle highlight handling), forces every Light + ReflectionProbe to
    mode (Baked/Mixed would silently freeze mood changes until a manual
    rebake), and creates one baseline light if the scene has none at
    all. Deterministic, code-orchestrated — same tier as
    cleanup_agent_lights()/reset_post_processing(), called once at the
    top of main.py's run(), no LLM judgment involved."""
    baseline = capture_scene_baseline(scene_path)
    result = subprocess.run(
        [UNITY_EXE, "command", "script", "eval", _ENSURE_READY_SCRIPT, "--result-only", "--project-path", PROJECT_PATH],
        capture_output=True,
        text=True,
        check=True,
    )
    report = json.loads(result.stdout)
    report["baseline"] = baseline
    return report


def get_baseline_brightness(scene_path: str | None = None) -> FrameBrightness | None:
    """Read the scene's captured baseline render brightness — the
    lighting agent's calibration anchor for 'how bright is bright' in
    THIS scene's own units, measured once at baseline-capture time (see
    capture_scene_baseline). Returns None if no baseline exists yet, or
    it predates this field (old cached data) — callers should treat
    that as 'no anchor available' rather than guessing a fake one."""
    if scene_path is None:
        scene_path = get_active_scene().path
    path = _baseline_path_for_scene(scene_path)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if "baseline_brightness" not in data:
        return None
    return FrameBrightness(**data["baseline_brightness"])


def restore_scene_baseline(scene_path: str | None = None) -> dict:
    """Restore the CURRENT scene to its captured baseline (lights'
    mode+properties, reflection probe modes, skybox material,
    post-processing) — reads what capture_scene_baseline() saved, the
    real intended replacement for reset_post_processing()'s old
    'reset to an invented neutral' approach. This is what a future
    reset UI button calls. Returns an error dict if no baseline was ever
    captured for this scene (nothing to restore to)."""
    if scene_path is None:
        scene_path = get_active_scene().path
    path = _baseline_path_for_scene(scene_path)
    if not os.path.exists(path):
        return {"status": "error", "error": f"No baseline captured yet for '{scene_path}'. Call capture_scene_baseline() first."}

    with open(path, "r", encoding="utf-8") as f:
        baseline = json.load(f)

    skybox_path = baseline.get("skybox_material_path")

    # Inline each restore value as a direct C# literal per target, rather than
    # JSON-deserializing inside script eval — simpler given the mixed types here,
    # and consistent with how every other write in this file builds its script.
    light_restores = []
    for light in baseline["lights"]:
        has_pos = "pos_x" in light
        pos_restore = (
            f'l.transform.position = new UnityEngine.Vector3({light.get("pos_x")}f, {light.get("pos_y")}f, {light.get("pos_z")}f); '
            f'l.transform.eulerAngles = new UnityEngine.Vector3({light.get("rot_x")}f, {light.get("rot_y")}f, {light.get("rot_z")}f); '
            if has_pos
            else ""  # old baseline predates position/rotation capture — leave untouched rather than guess (0,0,0) and risk teleporting into geometry
        )
        spot_angle_restore = (
            f'l.spotAngle = {light["spot_angle"]}f; '
            if light.get("spot_angle") is not None
            else ""  # old baseline predates spot_angle/color_temperature capture — leave untouched
        )
        color_temp_restore = (
            f'l.colorTemperature = {light["color_temperature"]}f; '
            if light.get("color_temperature") is not None
            else ""
        )
        bounce_restore = (
            f'l.bounceIntensity = {light["bounce_intensity"]}f; '
            if light.get("bounce_intensity") is not None
            else ""
        )
        shadow_strength_restore = (
            f'l.shadowStrength = {light["shadow_strength"]}f; '
            if light.get("shadow_strength") is not None
            else ""  # old baseline predates shadow_strength capture — leave untouched
        )
        use_color_temp_restore = (
            f'l.useColorTemperature = {str(light["use_color_temperature"]).lower()}; '
            if light.get("use_color_temperature") is not None
            else ""
        )
        light_restores.append(
            f'foreach (var l in UnityEngine.Object.FindObjectsByType<UnityEngine.Light>(UnityEngine.FindObjectsSortMode.None)) {{ '
            f'if (l.gameObject.GetEntityId().ToString() == "{light["instance_id"]}" || l.gameObject.name == "{light["name"]}") {{ '
            f'l.lightmapBakeType = UnityEngine.LightmapBakeType.{light["mode"]}; '
            f'l.intensity = {light["intensity"]}f; '
            f'l.color = new UnityEngine.Color({light["color_r"]}f, {light["color_g"]}f, {light["color_b"]}f); '
            f'l.range = {light["range"]}f; '
            f'l.shadows = (UnityEngine.LightShadows){light.get("shadow_type_int", 0)}; '
            + spot_angle_restore
            + color_temp_restore
            + bounce_restore
            + shadow_strength_restore
            + use_color_temp_restore
            + pos_restore
            + 'break; } }'
        )
    probe_restores = []
    for probe in baseline["reflection_probes"]:
        probe_restores.append(
            f'foreach (var p in UnityEngine.Object.FindObjectsByType<UnityEngine.ReflectionProbe>(UnityEngine.FindObjectsSortMode.None)) {{ '
            f'if (p.gameObject.GetEntityId().ToString() == "{probe["instance_id"]}" || p.gameObject.name == "{probe["name"]}") {{ '
            f'p.mode = UnityEngine.Rendering.ReflectionProbeMode.{probe["mode"]}; break; }} }}'
        )
    skybox_restore = ""
    if skybox_path:
        skybox_restore = (
            f'var sky = UnityEditor.AssetDatabase.LoadAssetAtPath<UnityEngine.Material>("{skybox_path}"); '
            f'if (sky != null) {{ UnityEngine.RenderSettings.skybox = sky; UnityEngine.DynamicGI.UpdateEnvironment(); }}'
        )

    full_script = "\n".join(light_restores + probe_restores + [skybox_restore, "return new { ok = true };"])
    subprocess.run(
        [UNITY_EXE, "command", "script", "eval", full_script, "--result-only", "--project-path", PROJECT_PATH],
        capture_output=True,
        text=True,
        check=True,
    )

    ca = baseline["color_adjustments"]
    set_color_adjustments(
        post_exposure=ca["post_exposure"],
        contrast=ca["contrast"],
        saturation=ca["saturation"],
        color_filter=(ca["color_filter_r"], ca["color_filter_g"], ca["color_filter_b"]),
    )
    vig = baseline["vignette"]
    set_vignette(intensity=vig["intensity"], smoothness=vig["smoothness"])
    fog = baseline["fog"]
    set_fog(
        enabled=fog["enabled"],
        color=(fog["color_r"], fog["color_g"], fog["color_b"]),
        density=fog["density"],
        start_distance=fog["start_distance"],
        end_distance=fog["end_distance"],
    )
    ambient = baseline.get("ambient", {"intensity": 1.0})  # old baselines predate this field
    set_ambient(intensity=ambient["intensity"])

    return {"status": "restored", "scene_path": scene_path, "lights_restored": len(baseline["lights"]), "probes_restored": len(baseline["reflection_probes"])}


# --- Explicit save (decided live with Eran, 2026-11-20) -------------------
#
# Nothing in this pipeline auto-saves to disk. Every mood attempt, every
# ensure_scene_ready() fix, every restore — all of it only exists in the
# Editor's live in-memory session until save_scene() is called. Confirmed
# live: `git status` showed zero changes to the Forest .unity file despite
# a full mood test run having visibly changed lights/probes/skybox/post-
# processing. Decided deliberately, not a gap to close: the user should
# control when a result is worth keeping (auto-save on every attempt,
# including failed ones, would be the wrong default — see the real
# alternatives discussed and rejected: auto-save every change, or save-
# only-on-judge-pass). This is a plain function, NOT wired into agent.py's
# tool list — the agent never decides to persist its own work.

def save_scene(scene_path: str | None = None) -> dict:
    """Explicitly save the CURRENT scene to disk — a deliberate user
    action, never called automatically by anything in this pipeline.
    scene_path is accepted for API symmetry with the other scene
    functions but isn't required to match since EditorSceneManager only
    ever saves the actual active scene."""
    script = (
        "var s = UnityEditor.SceneManagement.EditorSceneManager.GetActiveScene(); "
        "bool ok = UnityEditor.SceneManagement.EditorSceneManager.SaveScene(s); "
        "return new { ok = ok, path = s.path };"
    )
    result = subprocess.run(
        [UNITY_EXE, "command", "script", "eval", script, "--result-only", "--project-path", PROJECT_PATH],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)
