# Build log — full decision history

> Relocated from `README.md` during the 2026-11-23 repo cleanup, verbatim
> content, nothing lost. The root README is now a clean project overview;
> this file is the full chronological engineering diary — every decision,
> every bug found and fixed, every design discussion, in the order it
> actually happened. If you want to know WHY something is the way it is,
> it's in here.

## Historical status snapshots (superseded by later entries, kept for the record)

**Business scope decision (2026-11-20, locked in with Eran):** the product
is lights + rendering features ONLY (lights, post-processing, skybox/HDRI,
exposure, gamma) — geometry/content changes are explicitly OUT of scope,
not a later phase. This means v5 (scene/geometry transformation) is
**dropped**, not parked — the content-ceiling eval fails that motivated it
aren't bugs to fix under this product definition, they're requests the
product was never meant to handle. This also means the eval suite's old
10-cases-on-one-scene setup under-counted real capability — scene choice
turned out to matter as much as the mood-word itself (step 34).

**Parked for later:** diff-with-outcome tracking — some mood tests (dreamlike,
festive) had the score *drop* across retry attempts, consistent with having
no visibility into "what I changed last time hurt." **Decided live with
Eran: don't build yet** — persistent cross-session memory is real
future-roadmap scope (a later phase where one session handles ask → fix →
ask again, end to end), not needed for the problem actually in front of us
(see `docs/mood-test-results.md`'s "Parked idea" section for the full
trade-off discussion). Revisit once that persistent-memory phase is
actually being built, not before.

### LLM customization options
See `docs/llm-customization-options.md` for the general-knowledge reference
on tools vs. instructions vs. few-shot vs. RAG vs. fine-tuning vs. LoRA —
written after the `create_light` discussion established the gap was tool
availability, not model knowledge.

This project is being built deliberately bottom-up, incrementally, one
small proven step at a time (see
`agent/src/unity_mood_lighting_agent/learning_steps/` — each file is one
learning step, kept even after superseded, so the build history stays
visible; `unity_bridge.py` holds the current, consolidated, actually-imported
version of what those steps built). The full vision (further down this doc)
involves multiple roles and an automated iterate-until-good-enough loop.
**We did not build that all at once.** Ground rule carried over from the FDE
roadmap work: start with one agent solving the smallest real version of the
problem, add complexity only once that's proven, not before.

## Build log

1. `step1_hello_agent.py` — minimal `Agent` + `Runner.run`, no tools. Proved the harness works.
2. (tool added to step1) — first `@function_tool`, hardcoded fake scene (`list_scene_objects`). Caught a real bug: the agent's `instructions` never mentioned the tool existed, so it wasn't being called — fixed by describing the capability in the prompt, not by forcing `tool_choice`.
3. `step3_structured_output.py` — `output_type` + Pydantic `BaseModel`, `SceneReport` (names + count). First typed `final_output`.
4. `step4_object_transforms_tool.py` — upgraded the tool to return real per-object data (`ObjectTransform`: name + position + rotation), still hardcoded. Caught a second real bug: calling a `@function_tool`-decorated function directly (for verification) fails — it's no longer a plain callable once decorated. Fixed by keeping the real logic in a separate `_build_transforms()` function that both the tool and the direct-call demo use.
5. `step5_deterministic_report.py` — **architectural correction.** Step 4 had the LLM narrow rich tool data down to just names+count via its own semantic judgment — works fine at 3 objects, a real reliability risk at scale (hundreds of objects in a real scene). Realized that "list what's in the scene" has zero ambiguity and needs zero reasoning, so it doesn't need an agent at all — see **Code vs. agent, the actual rule** below.
6. `step6_real_unity_connection.py` — real Unity connection, read side. `subprocess` → Unity CLI `script eval` → live Editor → real transform data (not MCP — we have a shell, so we call the CLI directly). Caught 2 real bugs: `GetInstanceID()` is obsolete in this Unity version (hard compile error, not warning — fixed with `GetEntityId().ToString()`), and real scene data differed from our fake data (off-center Cube, rotated light, an unaccounted-for `Global Volume`).
7. `step7_set_transform_tool.py` — write side, `set_object_transform()`. Tested live: raw CLI first (moved the Cube, confirmed visually in the Editor), then the Python wrapper.
8. **Reorganization.** `unity_bridge.py` created — consolidates step6+step7's current logic (`list_scene_transforms()`, `set_object_transform()`, `ObjectTransform`) into one importable module; step files moved to `learning_steps/` and kept unchanged as the historical record. Decided: flat files, not folders-per-concern — current code volume (1 schema, 2 functions) doesn't justify a `schemas/`/`tools/`/`agent/` folder split; revisit if any single concern grows past ~4-5 files.
9. **Agent tool-design decision.** The agent gets exactly ONE tool: `set_object_transform`. Finding/listing objects stays code-orchestrated (same Code vs. agent rule as step 5) — the orchestrator calls `list_scene_transforms()` *before* invoking the agent and injects the result as context, rather than giving the agent a `find_object` tool to call itself. Scene inspection has no ambiguity; only "what to set, for the mood" does.
10. `tools.py` — single-axis edit fix (Eran caught it live): original design forced all 3 position/rotation axes together, blocking a real need ("rotate just the Y axis"). Fixed by reading the object's current transform first and merging in only the given axis/axes.
11. `agent.py` + `main.py` — the full pipeline, end to end. `uv run python main.py "task"` → `get_scene_context()` (code-orchestrated) → one prompt string → `Runner.run` → agent calls `set_object_transform` → real scene change. Verified live both in code and visually in the Editor.
12. **Two design-smell fixes, both caught by Eran, not by me.** First: `build_agent_input(task)` conflated scene-fetching (task-independent) with the task string behind one opaque combined output — split into `get_scene_context()` (no task param) + task passed separately. Second, a self-correction on my own first fix: I'd changed the call into a fake 2-message `[{"role":"user",...}, {"role":"user",...}]` list, but that format exists for real multi-turn conversation history (alternating user/assistant), not for artificially splitting one input in two — reverted to a single plain prompt string.
13. **Real agent judgment test — found a real bug.** Asked the agent to rotate the Directional Light to simulate noon sunlight (ambiguous task, no literal coordinates given). Agent set `rot_x = 270°` — Unity's convention for straight-up-from-below, the *opposite* of overhead. Tool execution was correct; the agent's reasoning about the rotation convention was wrong. Result: scene went black. **Caught only by Eran looking at the Editor — we have no automated way to catch this ourselves.** This is exactly the gap v1's judge step exists to close (see Open gap below). Fixed by telling the agent the correct value (`rot_x = 90°`) directly.
14. **Rotation guardrail — raycast-based, closes the step 13 bug class.** Decided this is two separable things, not one: a **guardrail** (reject bad rotations before they reach Unity — general-purpose, works even with no target object) and a **feature** for later (`aim_light_at(target_object)`, only usable when the task actually names a target — out of scope here, noted for v1+). Built the guardrail:
    - `check_rotation_aims_at_geometry(position, rotation, self_id)` (`unity_bridge.py`) takes a **candidate** position/rotation — never applies it to the live object first (no Editor flicker, no apply-then-revert round trip). Lets Unity's own `Quaternion.Euler` compute the resulting forward vector (see "Unity rotation terminology" below for why this matters) rather than reimplementing that trig in Python, since getting the rotation convention wrong by hand is exactly the bug class being guarded against. Raycasts from the candidate position along that direction (`Physics.RaycastAll`, skipping the light's own collider) and reports `hit: bool`, `hit_name`, `distance`.
    - Wired into `tools.py`'s `set_object_transform`: only runs when the call actually touches rotation (pure position moves skip it); on no-hit, returns a rejection string explaining why instead of touching Unity at all; on hit, proceeds exactly as before.
    - **Verified live, through the real agent, not just unit-tested.** Re-ran the exact step 13 task ("rotate the Directional Light, set rot_x to 270") through `main.py`'s real pipeline: agent tried `rot_x=270` → rejected (no hit) → retried `rot_x=270` again → rejected again → self-corrected to `rot_x=90` → accepted, applied. No human had to look at the Editor to catch the bad value this time — the agent read the rejection message and fixed its own reasoning.
    - Minor trap hit while testing: `load_dotenv()` is only called in `main.py`, not `agent.py` — bypassing `main.py` to call `Runner.run` directly fails with a missing `OPENAI_API_KEY` error that looks like a credentials problem but is actually a "forgot to load .env in this entry point" problem.
    - **Edge case caught by Eran, same day:** the guardrail as first built only ran when rotation changed — but moving an object's *position*, with rotation left untouched, can just as easily point its existing rotation into empty space from the new spot. Fixed by gating on `any_position or any_rotation` (not rotation alone), always checking the resulting candidate position+rotation together regardless of which one actually changed. Verified live: moving the Directional Light far from the Cube (rotation unchanged) now correctly rejects; a normal nearby move still passes.
15. **`capture_game_view()` — the screenshot half of v1's judge.** Tested live first (per project discipline): Unity CLI has `capture game_view` (actual rendered scene, URP included), `capture scene_view` (editor camera + gizmos — wrong one), and `capture editor_window` (any editor panel — also wrong). `game_view` is correct for judging mood since it's what a player would actually see. Returns PNG + dimensions; `unity_bridge.py` wrapper defaults to a fresh temp file via `tempfile.mkstemp` if no path given. Deterministic wrapper, same as every other bridge function — scoring the image is the judge agent's job, not this one's.
16. **`judge.py` — a SECOND, separate agent, the v1 judge.** Structured output (`MoodJudgement`: `mood_match_score` 0-10, `dominant_color_temp`, `contrast_level`, `notes`) exactly as the README's v1 plan speced, built as `output_type` on its own `Agent` instance — not a tool on the lighting agent, a fully separate evaluator. `judge_mood_match(task)` captures the current live view, base64-encodes it into a `data:image/png;base64,...` URL (the Agents SDK takes images via `input_image`/`image_url` content blocks, confirmed by reading `ResponseInputImageContentParam` directly rather than guessing), and returns `(passed, judgement)` — **code** decides pass/fail from `mood_match_score >= PASS_THRESHOLD` (6), the judge agent only produces the score, same code-decides/LLM-judges split as the rotation guardrail. Verified live against two different scene states (default scene scored 1/10 against "horror"; a rotated-light scene scored 2/10 against "sunset" with specific, differentiated reasoning each time) — confirms it's reading real pixels, not returning a static response.
17. **The v2 retry loop — `main.py`.** Decided live with Eran: run lighting agent → judge the result → pass, stop; fail, feed the judge's own `notes` back into the next prompt (so the agent knows *why* it failed, not just that it did) → retry, capped at `MAX_ATTEMPTS = 3` (unbounded retry risks cost/infinite-loop if the mood is structurally unreachable with current tools) → give up and report the last judgement if still failing after 3. Each retry re-reads the *current* live scene via `get_scene_context()`, not the original state, so attempt 2 builds on whatever attempt 1 actually left behind. Caught and fixed a real bug during testing: `judgement` referenced after the loop was flagged "possibly unbound" by the type checker (true in principle if `MAX_ATTEMPTS` were 0) — fixed by moving the give-up return inside the loop's last iteration instead of after it. **Verified live, full 3-attempt runs, twice** ("horror mood" and "golden hour sunset"): both ran 3 real attempts, fed real judge feedback back each time, scores varied per attempt (not static), and both correctly gave up and reported the real reason.
18. **`set_light_properties` tool — intensity, color, color temperature, bounce.** Read a live Light component's actual fields via `component get_fields` rather than guessing field names from memory (`m_Intensity`, `m_Color`, `m_ColorTemperature` + `m_UseColorTemperature` gate, `m_BounceIntensity`, `m_Range`, `m_Shadows.m_Strength`). Added `get_light_properties`/`set_light_properties` to `unity_bridge.py`, wired as a tool with a sanity guardrail (intensity in (0,20], bounce in [0,5]). **Verified live: real improvement.** Re-ran "horror mood" with only this new tool — score went from 1/10 (position/rotation-only) to 2-3/10, with the judge's own notes shifting from "very bright and minimal" to "cool and foggy, helps a little."
19. **`create_light` tool — the agent can add lights, not just edit them.** Session-long discussion first (see "LLM customization options" doc): established the gap wasn't lighting-theory *knowledge* (the model already has that) but *capability* — no tool existed to create a light at all. Built `create_light(name, position, light_type)` in `unity_bridge.py`. Real bug found and fixed during this: `gameobject create`'s own CLI JSON response **truncates large instanceIds** (float precision loss), so trusting that command's own returned ID broke every later call on it. Fixed by creating the GameObject via `script eval` instead (same precise `GetEntityId()` path every other bridge read already uses). Added `count_lights()` + a `MAX_LIGHTS = 6` cap guardrail. **Verified live: the agent used it unprompted** — given "horror mood," it created a real, sensibly-named, sensibly-placed "Horror Rim Light" on its own.
20. **Real bug found by Eran: `create_light` had NO rotation guardrail at all.** New lights got Unity's default rotation `(0,0,0)` and the guardrail that protects `set_object_transform` was never wired into `create_light`. Fix, decided live with Eran across several exchanges:
    - `create_light` now runs the raycast guardrail against its own default rotation and **warns** (doesn't auto-delete) if it points at nothing.
    - New `aim_light_at(light_target, aim_at_target)` tool: rotates an existing light to face another object, computed via Unity's own `Quaternion.LookRotation`, applied through a shared `_apply_transform_with_guardrail` helper refactored out of `set_object_transform` so the guardrail **cannot be missed by a future tool**.
    - Deliberately a **separate** tool from `create_light`, not a parameter on it — needs to work on any existing light, not just newly created ones.
    - New `create_light_near(name, aim_at_target, offset_x, offset_y, offset_z, light_type)`: creates a light at `target_position + offset` and pre-aims it at the target in one atomic step.
21. **Deeper root cause found: aim targets could be colliderless root objects.** Testing against the Mess Hall sample scene kept failing even with correct offset math — root cause: `list_scene_transforms()` only ever read root-level objects, and container roots had zero colliders anywhere in their own hierarchy — only their nested prop children did. Fixed the read script: for each root, if it/its subtree has no collider anywhere, return the root unchanged; if it does, return each direct child that itself owns a collider.
22. **v3: post-processing tools — `set_color_adjustments`, `set_vignette`, `set_fog`.** Live-tested the Global Volume first: `ColorAdjustments` already active with real tuned values from the imported pack; `Vignette` did NOT exist in the profile by default, had to be added via `profile.Add<Vignette>(true)`. All three go through `script eval` since Volume components use `profile.TryGet<T>(out t)` + `VolumeParameter<T>` wrappers. Fog is separate from Volume entirely (`UnityEngine.RenderSettings`). Wired all 3 as agent tools with sanity guardrails. **Real result**: cozy cafe mood flipped from failing (3/10, lights-only) to passing (6/10, attempt 1).
23. **Fog scale guardrail — Eran caught a real bug visually.** Agent-set fog `end_distance=35` in a room whose real diagonal is ~22.8 — fog that never reaches full strength within the room reads as a flat, washed-out haze. Fixed `set_fog`'s docstring + a guardrail rejecting `end_distance` greater than the scene's real diagonal (via a new `get_scene_bounds()`).
24. **Scene-wide post-processing state added to `get_scene_context()`; a real, separate bug found and fixed.** The agent was reasoning about each render lever in isolation, stacking several darkening/desaturating effects into an unreadable, overly flat result — because `get_scene_context()` never exposed CURRENT post-processing values. Fixed by adding current `ColorAdjustments`/`Vignette`/`Fog` values to the context string every attempt. Also found and fixed a real, unrelated latent bug: `set_light_properties`/`get_light_properties`/`set_object_transform` passed the `int` instance_id straight into `subprocess.run`'s args list (requires `str`), silently failing. **Verified live**: thriller mood passed, 7/10, first time all session.
25. **"Unnamed point light" bug — root cause confirmed.** The agent called `set_light_properties` with the object's **name**, not its `instance_id`, even though the correct id was in its own context. Confirmed: a pure LLM reasoning slip, not a pipeline bug — structured output only constrains a field's *type*, not its *value* against live scene state. Fix: added `_resolve_target(objects, target)` in `tools.py` — resolves by `instance_id` first, falls back to exact `name` match if that misses.
26. **Light-stacking bug — fixed.** Lights created across separate `main.py` runs had no identity marker and nothing deleted them, piling up indefinitely across sessions. Built: `AGENT_LIGHT_PREFIX` ("AgentLight_") prepended unconditionally; `delete_object()`; `delete_light` agent tool, rejects anything untagged; `cleanup_agent_lights()` — plain function, not an agent tool, called once at the top of `main.py`'s `run()`.
27. **Eval harness built; full 10-case suite run twice, back to back.** Built `eval_suite.json` (10 canonical mood cases) + `eval.py`. Ran the full suite twice with zero code/scene changes — `eerie_lab`/`noir` flipped pass/fail between runs (real LLM non-determinism at the threshold), while 5 other moods failed hard and consistently both times. Both runs landed at 4/10.
28. **Post-processing contamination found and fixed; suite run a third time.** Checked live: scene was sitting at leftover `noir` grading with no mood task running. Built `reset_post_processing()`, called alongside `cleanup_agent_lights()`. **Ran the full suite a third time: still 4/10.** The fix was real and necessary, but NOT the main bottleneck — the 4 hardest-failing moods stayed exactly as stuck.

### Unity LookRotation / parenting terminology (for anyone re-reading this)

- **`Quaternion.LookRotation(direction)`** — Unity's own function for "what rotation makes something face this direction." Let Unity's own math handle the convention, never hand-roll the trig.
- **Offset-before-lookat order matters, not a style choice.** To place a light near a target and aim it back: compute `light_position = target_position + offset` FIRST, then compute `LookRotation` from `light_position` toward `target_position`. Doing it the other way gives a direction vector of `(0,0,0)` — undefined/NaN after `.normalized`.
- **GameObject parenting ≠ one flat list.** A scene's Transform hierarchy can nest arbitrarily. Reading only root-level objects is fine when a scene's props ARE the roots, but breaks down the moment an imported asset pack organizes its real objects as children of container roots.
- **Colliders can live at any depth, not necessarily where you'd guess.** `Physics.Raycast`/`RaycastAll` only ever hit an actual `Collider` component, wherever in the hierarchy it happens to sit.

### Unity rotation terminology (for anyone, including future us, re-reading this)

- **Vector3** — just an (x, y, z) triple. Used for positions, but a direction is also just a vector pointing that way.
- **`Vector3.forward`** — the constant `(0, 0, 1)`. An object with zero rotation faces +Z by Unity convention.
- **Euler angles** — rotation as three separate numbers: gimbal lock, and **order matters** — Unity's fixed order is **Z, then X, then Y**. Not knowing this specific order is exactly what produced the step 13 bug.
- **Quaternion** — a different representation of the same rotation that avoids gimbal lock and gets composition/ordering right. Nobody hand-writes one; you convert euler → quaternion and let the engine's own math handle it.
- **How the guardrail script uses both**: `Quaternion.Euler(rot_x, rot_y, rot_z)` converts the 3 human numbers using Unity's real ZXY order; `rotation * Vector3.forward` answers "where does the default forward direction end up after this rotation" — the actual world-space direction raycast against geometry.

### Code vs. agent, the actual rule (locked in at step 5)

**Deterministic data tasks → plain code, no agent.** Listing/reporting scene
contents is pure data transformation: call the tool's underlying function,
map the result into a report shape, done — 100% correct every time,
regardless of whether the scene has 3 objects or 3,000. No `Runner.run`,
no `output_type`, no LLM involved.

**Judgment-under-ambiguity tasks → the agent.** Deciding what lighting
changes actually achieve "a horror feel" has no single correct answer and
genuinely needs reasoning — that's where the agent earns its keep. Use code
where the task is deterministic, reserve the LLM for where
autonomy/reasoning is the actual value-add, not a convenience.

This rule is used everywhere in this project — scene listing, pass/fail
decisions, guardrails, scene selection, visibility checks, logging — all
code. Only "what change achieves this mood" is the agent's job.

---

## v0 scope (what was built first)

**One agent. One pass. No iteration loop. No automated judge.**

1. Agent receives: the mood goal (text) + scene info (via tool calls).
2. Agent calls tools to understand the scene (list objects, list existing
   lights, optionally capture a viewport render).
3. Agent calls tools to create/modify lights based on its understanding of
   the mood.
4. Agent stops. A human looks at the result. That's v0's "evaluation" — a
   human eyeball, not an automated score.

No multi-agent pipeline, no evaluator-judge, no retry loop. If v0 can't
produce a scene that reads as "horror" even once, there's no point building
an automated loop around it yet — fix the single pass first.

### v0 tool list (original plan)

| Tool | Purpose | Notes |
|---|---|---|
| `list_scene_objects` | Return scene objects with name, type/tag, position, bounding box | Read-only |
| `list_lights` | Return existing Light components: type, position, color, intensity, range | Read-only |
| `capture_viewport(camera_name)` | Render the current view, return an image | Lets the agent actually *see* the space |
| `create_light(type, position, color, intensity, range)` | Create a new Light GameObject | Guardrailed |
| `modify_light(light_id, color, intensity, range, position)` | Change an existing light | Guardrailed |

Deliberately excluded from v0: post-processing/Volume control, fog, skybox,
cookies/gobos — all built later in v3.

### v0 guardrails (plain Python, not framework magic)

Guardrails are just checks you write yourself around a tool call, not a
framework abstraction. Validate before any `create_light`/`modify_light`
call actually reaches Unity:

- `intensity > 0` and below a sane max
- `position` within the scene's bounding box
- total light count stays under a cap
- `color` is a valid RGB/RGBA value

No LLM judgment involved in these checks — plain deterministic validation.

---

## Full vision (the roadmap this project actually followed)

**v1 — add an automated judge.** A second agent renders the result and
scores it against the mood goal using structured output (not free text).
Code decides pass/fail from `mood_match_score`, not the LLM.

**v2 — add the iterate loop.** A deterministic Python loop: generate/modify
→ render → judge → if score below threshold, adjust and retry, up to N
iterations → stop. Never declare success without actually looking at the
rendered result.

**v3 — expand the action space.** Post-processing (color grading, vignette,
fog), skybox — mood in a real engine is rarely lights alone. Built and
proven (steps 22-24).

**v4 — mood grounding rubric (not built).** Translate mood words into
concrete parameter ranges instead of relying on the model's own
training-data sense of "what horror lighting looks like."

**v5 — scene/geometry transformation (killed, not parked).** Found live
testing "cozy cafe" and "abandoned outpost": lighting alone has a hard
physical ceiling — it can shift atmosphere within what a scene's actual
geometry supports, but cannot turn a sci-fi room into a cafe. Confirmed by
the eval harness across 3 separate runs (steps 27-28): the same moods
failed hard and consistently every time, with zero run-to-run variance,
unlike the borderline cases that flipped from LLM non-determinism alone.
**Killed outright by the 2026-11-20 business scope decision** (see
historical status notes above) — the product is lights/rendering only,
geometry changes are a request the product is not meant to handle, not a
gap to close. See `docs/scene-transformation-roadmap.md` for the fuller
discussion that was had before this was killed.

**v6 — scene readiness / rendering configuration check.** The pipeline
originally assumed a scene already has working lighting infrastructure.
Real edge cases that break that assumption:
- **Lighting Mode (Baked vs Realtime vs Mixed).** If a scene is
  Baked-only, every light change is invisible until a lightmap bake
  re-runs — breaks the product's core "change the mood quickly from one
  prompt" promise. Built: force Realtime/Mixed before any mood task runs.
- **Global Volume missing entirely.** Built: auto-create.
- **Zero lights in the scene.** Built: baseline light auto-created.
- **Light count as context.** Surfaced into `get_scene_context()`.

Deliberately deferred, affect visual *quality* not whether the product
works at all: Reflection Probes/Light Probes/Adaptive Probe Volumes beyond
the Realtime-mode fix already built, static emissive materials as GI light
sources, 2D Lights (URP 2D-renderer feature, this project is 3D).

### Steps 29-40 (post v5-kill, v6 and beyond)

29. **Skybox/HDRI control — `list_available_skyboxes()` + `set_skybox()`.** Downloaded 8 CC0 HDRIs from polyhaven.com (their own API already classifies environment/time_of_day/weather/contrast/sky_view), built `hdri_manifest.json` from that real metadata. Shader property names confirmed live via reflection before writing any code. **Verified live, both directions:** zero visible change on the enclosed Mess Hall (correct, no windows), dramatic correct day→night swap on an outdoor scene. Real finding: swapping the skybox does NOT touch the scene's directional light — for a full night mood the agent needs to coordinate both.
30. **Lighting agent given vision.** Only the judge agent ever saw a screenshot; the lighting agent making the actual mood decisions only ever got text. Now `main.py` captures the live game view every attempt and passes it alongside scene-context text.
31. **Outdoor test scene — "Ultimate Nature – Starter"** (free Asset Store pack). Picked because its stated Unity version almost exactly matched this project's, confirmed clean URP shaders after import. Caught a real account-vs-Editor mismatch during download: Unity's web "Add to My Assets" and the Editor's Package Manager can be signed into different Unity IDs.
32. **Multi-scene pipeline — `get_active_scene()`/`open_scene()`.** Nothing in the pipeline tracked which scene was active, so an outdoor test case actually ran silently against the wrong scene after a manual Editor switch. Fixed by making scene identity explicit end to end.
33. **Two real bugs found immediately by testing against new scenes.** `set_color_adjustments`/`get_color_adjustments` threw a raw `NullReferenceException` on any scene without a pre-existing ColorAdjustments override — fixed with the same "add if missing" pattern `set_vignette` used. Deeper one: every Volume lookup was hardcoded to `GameObject.Find("Global Volume")` by NAME — broke on the Forest pack. Fixed properly: find the Volume by its `isGlobal` component instead of by name.
34. **Eval suite run against the Forest scene: 5/10, but the real signal is which cases flipped.** `dreamlike` went FAIL→PASS outdoors; `thriller` went PASS→FAIL outdoors. Real, direct evidence the old content-ceiling conclusion was partly an artifact of testing every mood against one mismatched scene — while `cozy_cafe`/`festive`/`post_apocalyptic` stayed stuck regardless of scene, confirming those specific ones really do need geometry.
35. **v6 built: scene readiness + real baseline capture/restore.** `docs/unity-lighting-rendering-concepts.md` records the underlying Unity knowledge. Three new deterministic functions: `capture_scene_baseline()`, `ensure_scene_ready()`, `restore_scene_baseline()`. **Verified live, real round trip:** mutated color adjustments + skybox, restored, confirmed both landed back on the true captured values.
36. **`save_scene()` — explicit, deliberate save.** Nothing in this pipeline auto-saves. `save_scene()` is a plain function, NOT an agent tool — the agent never decides to persist its own work. Found a real bug verifying it: `GetEntityId()` instance IDs are NOT stable across Editor sessions — fixed with the same instance-id-then-name fallback from step 25.
37. **Real spatial grounding — full bounding box + a guardrail planned since v0.** `get_scene_bounds()` extended to return actual min/max corners. Surfaced into `get_scene_context()`. `check_position_within_bounds()` wired into every placement path. Verified through the real wrapped tool via a properly-constructed `ToolContext`, not just a code-structure argument.
38. **Eval suite split per scene, and a real bug found reaching the Mess Hall's baseline.** `eval_suite.json`'s cases now each declare their own `scene`. `TestRoom` dropped from eval scope entirely. First capture against Mess Hall crashed: `Lightmapping.lightingSettings` THROWS when no LightingSettings asset is assigned, it doesn't return null. Fixed with try/catch.
39. **Judge: reasoning-first field order in structured output.** `docs/agent-output-quality-techniques.md` records the full technique. `MoodJudgement.notes` (last, "debugging only") renamed to `reasoning` and moved first. Deliberately NOT applied to the lighting agent — it has no `output_type` (tool-calling, not structured output).
40. **Judge scope recalibration + agent push + screenshot pipeline.** Found the judge's own stated reasoning was citing missing physical objects ("no gifts," "no debris") as the reason several moods failed — a real miscalibration, not an agent capability gap. Fixed both sides: judge now scores atmosphere given existing geometry; agent instructions push for committed/extreme values. Also built the before/after screenshot pipeline (`screenshots/<case>/baseline.png` + `result.png`). First real payoff: caught that a "passing" result had actually gone to a near-black frame. Full details and what came after (the visibility guardrail, `docs/mood-test-results.md`'s change-log discipline): `docs/mood-test-results.md`.

---

## Open questions / not yet decided

- **MCP integration — updated 2026 (Unity CLI).** Unity deprecated the
  in-editor AI Assistant's MCP server and replaced it with the **Unity CLI**
  (`unity` standalone binary). This project calls it directly via
  `subprocess`, not through MCP (we have a shell). See
  `docs/unity-cli-connection.md`.
- **Agent harness**: **OpenAI Agents SDK** — decided, used throughout.

## Open gap found by real testing (2026-11-17)

The noon-sunlight test (step 13) proved the actual risk v1's judge step was
meant to address: the agent can execute a tool call correctly while
reasoning about rotation/direction conventions *incorrectly*, with no
automated way to catch it — only a human looking at the Editor did. This
was the strongest real argument for building v1 (the judge), not just a
theoretical nice-to-have. v1 is now built and in continuous use.
