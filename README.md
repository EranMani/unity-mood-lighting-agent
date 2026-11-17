# Unity Mood Lighting Agent

An agent that reads a Unity scene and applies a natural-language lighting mood
("apply a horror feel") by creating/modifying Unity Light objects — without a
human manually placing lights.

Example input: `"apply a horror feel vibe to this scene"`
Example behavior: agent inspects scene geometry + existing lights, then
creates/adjusts Light objects (type, position, color, intensity, range) to
move the scene toward that mood.

## Status: v0 in progress — build log below (see Scope for the target)

**Resume here (next session):** v0's pipeline works end to end, the
rotation guardrail (step 14) catches physically-nonsensical rotations/
moves, and v1 (judge, step 16) + v2 (retry loop, step 17) are both built
and verified live. The real blocker now is the lighting agent's tool list:
it still only has `set_object_transform` (position/rotation) — no
intensity, color, or light-creation — so most moods are structurally
unreachable regardless of how good the judge/loop are. **Next: expand the
agent's tools** (new Light creation, intensity/color on existing lights)
per the v0 tool list below, then re-run the judge loop and see real scores
improve. The `aim_light_at(target_object)` feature (for tasks that name a
target) is still unbuilt, lower priority than the tool expansion.

This project is being built deliberately bottom-up, incrementally, one small
proven step at a time (see `agent/src/unity_mood_lighting_agent/learning_steps/`
— each file is one learning step, kept even after superseded, so the build
history stays visible; `unity_bridge.py` holds the current, consolidated,
actually-imported version of what those steps built). The full vision (bottom of
this doc) involves multiple roles and an automated iterate-until-good-enough
loop. **We are not building that yet.** Ground rule carried over from the
FDE roadmap work: start with one agent solving the smallest real version of
the problem, add complexity only once that's proven, not before.

### Build log

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
17. **The v2 retry loop — `main.py`.** Decided live with Eran: run lighting agent → judge the result → pass, stop; fail, feed the judge's own `notes` back into the next prompt (so the agent knows *why* it failed, not just that it did) → retry, capped at `MAX_ATTEMPTS = 3` (unbounded retry risks cost/infinite-loop if the mood is structurally unreachable with current tools) → give up and report the last judgement if still failing after 3. Each retry re-reads the *current* live scene via `get_scene_context()`, not the original state, so attempt 2 builds on whatever attempt 1 actually left behind. Caught and fixed a real bug during testing: `judgement` referenced after the loop was flagged "possibly unbound" by the type checker (true in principle if `MAX_ATTEMPTS` were 0) — fixed by moving the give-up return inside the loop's last iteration instead of after it. **Verified live, full 3-attempt runs, twice** ("horror mood" and "golden hour sunset"): both ran 3 real attempts, fed real judge feedback back each time, scores varied per attempt (not static), and both correctly gave up and reported the real reason. The low scores are a genuine, expected limitation, not a bug — the lighting agent still has only ONE tool (`set_object_transform`: position/rotation), no intensity/color/light-creation, so most moods are structurally out of reach until the tool list grows (see v0 tool list / Open gap below).

### Unity rotation terminology (for anyone, including future us, re-reading this)

Needed to understand `check_rotation_aims_at_geometry`'s script, in order:

- **Vector3** — just an (x, y, z) triple. Used for positions, but a direction is also just a vector pointing that way.
- **`Vector3.forward`** — the constant `(0, 0, 1)`. An object with zero rotation faces +Z by Unity convention; it's the object's local "front" before any rotation is applied.
- **Euler angles** — rotation as three separate numbers (`rot_x/rot_y/rot_z`): "rotate this many degrees around each axis." Intuitive, but has two real problems: gimbal lock, and **order matters** — X-then-Y-then-Z gives a different final orientation than Z-then-X-then-Y. Unity's fixed order is **Z, then X, then Y**. Not knowing this specific order is exactly what produced the step 13 bug — "+X tilts it this way" doesn't match intuition unless you know Unity's convention going in.
- **Quaternion** — a different representation of the same rotation (4 numbers, not individually meaningful to a human) that avoids gimbal lock and gets composition/ordering right. Nobody hand-writes one; you convert euler → quaternion and let the engine's own math handle it.
- **How the guardrail script uses both**: `Quaternion.Euler(rot_x, rot_y, rot_z)` converts the 3 human numbers into a rotation using Unity's real ZXY order — letting Unity do this instead of reimplementing the ordering in Python means we can never get the convention backwards. `rotation * Vector3.forward` then answers "where does the default forward direction end up after this rotation" — the actual world-space direction the light now points. That direction is what gets raycast.

### Code vs. agent, the actual rule (locked in at step 5)

**Deterministic data tasks → plain code, no agent.** Listing/reporting scene
contents is pure data transformation: call the tool's underlying function,
map the result into a report shape, done — 100% correct every time,
regardless of whether the scene has 3 objects or 3,000. No `Runner.run`,
no `output_type`, no LLM involved.

**Judgment-under-ambiguity tasks → the agent.** Deciding what lighting
changes actually achieve "a horror feel" has no single correct answer and
genuinely needs reasoning — that's where the agent earns its keep. This is
Week 2 Day 2's orchestration-by-code-vs-by-LLM lesson applied concretely:
use code where the task is deterministic, reserve the LLM for where
autonomy/reasoning is the actual value-add, not a convenience.

Practical effect on the architecture below: scene/light **inspection**
(`list_scene_objects`, `list_lights`) will likely be called directly in
code, not routed through agent reasoning — only the **mood → light-change
decision** step needs the agent in the loop.

---

## v0 scope (what we're actually building first)

**One agent. One pass. No iteration loop. No automated judge.**

1. Agent receives: the mood goal (text) + scene info (via tool calls).
2. Agent calls tools to understand the scene (list objects, list existing
   lights, optionally capture a viewport render).
3. Agent calls tools to create/modify lights based on its understanding of
   the mood.
4. Agent stops. **Eran looks at the result himself.** That's the v0
   "evaluation" — a human eyeball, not an automated score.

No multi-agent pipeline, no evaluator-judge, no retry loop. If v0 can't
produce a scene that reads as "horror" even once, there's no point building
an automated loop around it yet — fix the single pass first.

### v0 tool list

All tools are thin wrappers the agent calls through Unity's MCP integration
(target: the official Unity MCP Server, beta as of May 2026 — not yet
confirmed/installed, see Open Questions).

| Tool | Purpose | Notes |
|---|---|---|
| `list_scene_objects` | Return scene objects with name, type/tag, position, bounding box | Read-only. Keep the schema flat — name/type/position/bounds, not full mesh data |
| `list_lights` | Return existing Light components: type, position, color, intensity, range | Read-only |
| `capture_viewport(camera_name)` | Render the current view, return an image | Used so the agent can actually *see* the space — numeric coordinates alone are a weak signal for spatial/mood reasoning |
| `create_light(type, position, color, intensity, range)` | Create a new Light GameObject | Guardrailed — see below |
| `modify_light(light_id, color, intensity, range, position)` | Change an existing light | Guardrailed — see below |

Deliberately excluded from v0: post-processing/Volume control, fog, skybox,
cookies/gobos. Real mood work in Unity leans on those as much as lights, but
they're a v1+ expansion once the light-only pass is proven to do *something*
sensible.

### v0 guardrails (plain Python, not framework magic)

Per the lesson from the Agentic Engineering course (Week 2 Day 3): guardrails
are just checks you write yourself around a tool call, not a framework
abstraction. Validate before any `create_light`/`modify_light` call actually
reaches Unity:

- `intensity > 0` and below a sane max (reject absurd blown-out values)
- `position` within the scene's bounding box (reject lights placed outside
  the room/level geometry)
- total light count stays under a cap (reject runaway light spam)
- `color` is a valid RGB/RGBA value

No LLM judgment involved in these checks — plain deterministic validation,
same reasoning as any other input-validation code.

### v0 structured output

**None yet, deliberately.** Structured output (Pydantic schema + `output_type`)
is the right tool for an evaluator/judge step, and v0 has no judge — the human
is the judge. Tool calls already give the agent's actions enough structure
(typed function args). Introducing a judge schema now would be designing for
a loop we haven't proven we need.

---

## Full vision (not being built yet — recorded so we don't lose the shape)

Once v0 proves a single pass can produce something reasonable, the natural
next steps, in order:

**v1 — add an automated judge.** A second agent renders the result and scores
it against the mood goal using a **structured output** (not free text):

| Field | Type | Purpose |
|---|---|---|
| `mood_match_score` | int 0-10 | Overall match to the requested mood |
| `dominant_color_temp` | str (warm/neutral/cool) | Sanity-check against mood expectations |
| `contrast_level` | str (low/medium/high) | Horror mood wants high contrast, pooled light, not even fill |
| `notes` | str, short | One or two lines of free-text reasoning, for debugging only — not branched on |

Code (not the LLM) decides pass/fail from `mood_match_score`, keeping this
code-orchestrated rather than LLM-orchestrated — same production-system bias
Ed Donner's course argued for (predictable > autonomous, for anything where
you want to trust the result).

**v2 — add the iterate loop.** A deterministic Python loop: generate/modify →
render → judge → if score below threshold, adjust and retry, up to N
iterations → stop. This is the "render-and-look" verification pattern (same
shape as the Alvarmethod `learn-visual` skill) — never declare success without
actually looking at the rendered result.

**v3 — expand the action space.** Post-processing (bloom, color grading),
fog, skybox — mood in a real engine is rarely lights alone. Also: reason from
the gameplay camera's actual POV, not just generic top-down scene data, since
horror staging is about what the player sees.

**v4 — mood grounding rubric.** Translate mood words into concrete parameter
ranges (intensity bands, color temperature ranges, contrast targets) instead
of relying on the model's own training-data sense of "what horror lighting
looks like." Makes the judge's scoring criteria explicit and reviewable
instead of implicit.

---

## Open questions / not yet decided

- **MCP integration — updated 2026 (Unity CLI).** Unity deprecated the
  in-editor AI Assistant's MCP server and replaced it with the **Unity CLI**
  (`unity` standalone binary — installs editors/modules, manages projects
  from a terminal, and exposes its own MCP server for AI-driven Editor
  control). This is now the target, not the old in-editor MCP server
  referenced in earlier drafts of this doc. Install via
  `curl -fsSL https://unity.com/install.sh | bash` (Unity Hub also installs
  it automatically on recent versions). Not yet installed/wired up against
  this repo — v0's tool list (below) will be implemented against whatever
  `unity mcp configure` exposes once we get there. Community packages (e.g.
  coplaydev's "MCP for Unity") remain a fallback if the official path doesn't
  fit the v0 tool list.
- **Test scene**: starting from an empty Unity project. Needs a small test
  scene (a simple room with basic geometry) before v0 can be exercised at all.
- **Agent harness**: **OpenAI Agents SDK** — decided. Chosen deliberately to
  double as hands-on reinforcement of the FDE roadmap course material (Week 2).

## Open gap found by real testing (2026-11-17)

The noon-sunlight test (build log #13) proved the actual risk v1's judge
step is meant to address: the agent can execute a tool call correctly while
reasoning about rotation/direction conventions *incorrectly*, with no
automated way for us to catch it — only a human looking at the Editor did.
v0 has zero visual feedback loop. This is now the strongest real argument
for building v1 next, not just a theoretical nice-to-have.

## Repo layout

```
README.md                      architecture, build log, decisions
docs/                           design notes (Unity CLI findings, etc.)
MoodLightingScene/               the Unity project (URP, 6000.5.7f1)
agent/
  src/unity_mood_lighting_agent/
    unity_bridge.py              current: ObjectTransform, list_scene_transforms(), set_object_transform()
    tools.py                     the agent's one tool (wraps unity_bridge)
    agent.py                     the Agent + get_scene_context()
    main.py                      entry point: uv run python main.py "task"
    learning_steps/              steps 1-7, kept as the historical build record
```
