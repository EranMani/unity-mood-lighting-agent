# Unity Mood Lighting Agent

An agent that reads a Unity scene and applies a natural-language lighting mood
("apply a horror feel") by creating/modifying Unity Light objects — without a
human manually placing lights.

Example input: `"apply a horror feel vibe to this scene"`
Example behavior: agent inspects scene geometry + existing lights, then
creates/adjusts Light objects (type, position, color, intensity, range) to
move the scene toward that mood.

## Status: v0 in progress — build log below (see Scope for the target)

This project is being built deliberately bottom-up, incrementally, one small
proven step at a time (see `agent/src/unity_mood_lighting_agent/step*.py` —
each file is one learning step, kept even after superseded, so the build
history stays visible). The full vision (bottom of this doc) involves
multiple roles and an automated iterate-until-good-enough loop. **We are not
building that yet.** Ground rule carried over from the FDE roadmap work:
start with one agent solving the smallest real version of the problem, add
complexity only once that's proven, not before.

### Build log

1. `step1_hello_agent.py` — minimal `Agent` + `Runner.run`, no tools. Proved the harness works.
2. (tool added to step1) — first `@function_tool`, hardcoded fake scene (`list_scene_objects`). Caught a real bug: the agent's `instructions` never mentioned the tool existed, so it wasn't being called — fixed by describing the capability in the prompt, not by forcing `tool_choice`.
3. `step3_structured_output.py` — `output_type` + Pydantic `BaseModel`, `SceneReport` (names + count). First typed `final_output`.
4. `step4_object_transforms_tool.py` — upgraded the tool to return real per-object data (`ObjectTransform`: name + position + rotation), still hardcoded. Caught a second real bug: calling a `@function_tool`-decorated function directly (for verification) fails — it's no longer a plain callable once decorated. Fixed by keeping the real logic in a separate `_build_transforms()` function that both the tool and the direct-call demo use.
5. `step5_deterministic_report.py` — **architectural correction.** Step 4 had the LLM narrow rich tool data down to just names+count via its own semantic judgment — works fine at 3 objects, a real reliability risk at scale (hundreds of objects in a real scene). Realized that "list what's in the scene" has zero ambiguity and needs zero reasoning, so it doesn't need an agent at all — see **Code vs. agent, the actual rule** below.

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

## Repo layout

```
docs/            design notes, architecture decisions
(agent code, Unity project, etc. — added as v0 work actually starts)
```
