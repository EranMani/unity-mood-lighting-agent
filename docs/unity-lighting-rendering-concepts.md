# Unity lighting & rendering concepts — reference

Captured 2026-11-20 from a live discussion with Eran, working out what
actually matters for this project (vs. general Unity trivia). This is a
reference doc, not a build log entry — see README.md for the actual
build history and decisions.

## Why this matters for THIS product specifically

The product's core promise is "change an existing scene's mood from one
prompt, quickly." That promise can be **silently broken** by a scene's
rendering configuration, independent of whether the agent's light/
skybox/post-processing logic is correct. A scene set up for Baked
lighting will not visually update no matter what the agent changes,
until someone re-runs a lightmap bake (seconds to hours). This is the
single most important thing the readiness check (README v6) exists to
catch.

## Lighting Mode — per LIGHT, not just per scene

Each `Light` component has its own mode (`Light.lightmapBakeType`):

- **Realtime** — both direct hit AND bounced/indirect light recalculated
  live, every frame, for both static and dynamic objects. This is what
  we need. The "expensive" part is specifically the bounced-light
  recalculation, not lighting in general.
- **Baked** — the light's ENTIRE contribution (direct + indirect) is
  pre-computed once into a lightmap texture, for STATIC objects only.
  Changing this light after baking does nothing visually until a
  rebake. Cheap at runtime, completely frozen otherwise.
- **Mixed** — direct hit/shadow stays realtime (updates instantly), but
  the indirect/bounce contribution is baked once. So part of the look
  updates live, part stays stale until rebake — a trap for us, looks
  like it's working but isn't fully.

There's also a scene-wide "Lighting Mode" setting (`LightingSettings.
mixedBakeMode`: Baked Indirect / Shadowmask / Subtractive) that only
matters for how Mixed lights behave — irrelevant if every light is
Realtime.

## Our decision: Realtime-only for the live agent loop

Baking takes real time. If the agent had to wait on a bake after every
single mood attempt, the "quick" part of the product promise is dead.
**Realtime for everything the agent might touch, always, during
iteration.** Baked/Mixed only makes sense as a separate, deliberate
"finalize for shipping/performance" step outside the live mood loop —
not something v6's readiness check should try to support yet.

## Skybox / environment (ambient) lighting

Skybox swaps feed into ambient lighting, which has the same baked-vs-
realtime split as individual lights. If environment lighting is set to
bake its ambient/reflection contribution, a skybox swap won't propagate
live either — same underlying trap, different system.
`DynamicGI.UpdateEnvironment()` (already called by `set_skybox()`) forces
a live refresh of ambient/reflection data regardless, which is why our
skybox swaps already worked visually without a formal bake step.

## Reflection Probes — correction to a common assumption

A Reflection Probe does **not** "only catch static objects" — it
captures a 360° snapshot of whatever is around it and projects that
onto nearby reflective surfaces, static or dynamic alike. The real
split, same pattern as lights:

- **Baked probe**: one frozen snapshot. Won't reflect movement, won't
  pick up a skybox/mood change until rebaked.
- **Realtime probe**: re-renders live (like a small extra camera),
  reflects movement and picks up skybox/environment changes instantly.

If a scene has reflective surfaces (water, metal, glass) and mood swaps
should show up in them, those probes need to be Realtime too.

## Light Probes / Adaptive Probe Volumes (APV)

Lightmaps only work on static meshes (baked onto their UVs). Dynamic
objects (player, NPCs, anything that moves) can't have a lightmap, so
they borrow lighting data from **Light Probes** — sample points
scattered through the scene storing what the bounced/ambient light
looks like there; a moving object interpolates from the probes around
its current position. **APV** (Adaptive Probe Volumes) automates the
placement: define a volume, Unity fills it with a probe grid at a
chosen density, instead of hand-placing individual probe groups.

Deferred past v6 (see README) — these affect visual quality (GI on
dynamic objects), not whether the product works at all, and auto-
placing a correctly-bounded probe setup is a real standalone feature,
not a quick add-on.

## The Static flag

A checkbox next to the name/tag/layer row in the Inspector. Checking it
flips several sub-flags at once: Contribute GI, Occluder Static,
Occludee Static, Batching Static, Navigation Static, Reflection Probe
Static. The one that matters for lighting specifically is **Contribute
GI** — you can toggle just that one via the dropdown arrow instead of
all of them.

## Emissive materials

A material whose surface itself glows (a lightbulb's glass, campfire
embers, a screen), set via the Emission property on the shader, no
separate invisible Light GameObject needed for the glow itself. Catch:
by default an emissive material only makes *itself* look bright — it
does NOT automatically light up nearby objects unless GI is configured
to pick up emissive surfaces (baked, or realtime GI with emissive
support, which has its own cost). Sits closer to a material/content
edit than pure lighting — a judgment call for later, not v6.

## Finding things: by component, never by hardcoded name

Already learned the hard way once (step 33: `GameObject.Find("Global
Volume")` broke on a pack that named it `UNS_Global_Volume`). Every
lookup in this project now queries by COMPONENT TYPE
(`FindObjectsByType<Light>()`, `FindObjectsByType<ReflectionProbe>()`,
the `isGlobal` Volume filter), never by GameObject name. The Unity
Editor's own "Light Explorer" window (Window > Rendering > Light
Explorer) is a human-facing GUI built on exactly these same component
queries — we don't drive that window, we query the same data directly
via `script eval`, which is more reliable and scriptable.

## World position vs. local position — a real bug this caused (2026-11-24)

Every `Transform` carries TWO separate coordinate representations at
once, not one:

- **World position** (`transform.position`, `transform.eulerAngles`) —
  measured from the scene's single shared origin (0,0,0), the same
  anchor for every object regardless of where it sits in the hierarchy.
  This is "where am I, period."
- **Local position** (`transform.localPosition`,
  `transform.localEulerAngles`) — measured relative to the object's own
  PARENT, not the scene origin. This is "how far am I from my parent,"
  meaningless on its own without knowing what the parent is doing.

If an object has no parent, local and world are numerically identical
(the "parent" is effectively the scene root itself) — this is why a
local/world mix-up can sit completely invisible for a long time: it
only produces a wrong result once an object actually HAS a parent with
a non-identity position/rotation/scale.

**The composition is not simple addition in general.** `world =
parent.TransformPoint(local)`, which accounts for the parent's own
rotation and scale, not just its position — think of a seat bolted
inside a train car: the seat's position relative to the car (local)
never changes, but where it actually sits in the real world depends on
both where the car is AND which way the car is facing. It only
collapses to plain vector addition when the parent's rotation is
identity and scale is 1 (the specific case this project's bug happened
to hit).

**You never need to do that composition by hand.** `Transform` exposes
both spaces as properties, and ASSIGNING to the world ones
(`transform.position = worldVec`, `transform.eulerAngles = worldEuler`)
makes Unity compute and store the correct underlying local values for
whatever parent exists, automatically, in both directions (get and
set). Same principle as this project's rotation guardrail already
using `Quaternion.Euler` instead of reimplementing that trig in Python
— never hand-roll math Unity already does correctly for you.

**The actual bug, found live via a spatial-placement eval test**:
`unity_bridge.set_object_transform()` originally called the Unity
CLI's own `gameobject set_transform --position/--rotation`, which (per
its own `--help` text) writes `localPosition`/`localEulerAngles`. Every
OTHER read in this project (`list_scene_transforms`, `get_scene_bounds`)
reports `transform.position`/`eulerAngles` — WORLD space. The two
original scene lights had no parent all session, so this was invisible
the entire time; the first real test of position-setting (the spatial
eval, see docs/mood-test-results.md) exposed it immediately, after
something in the long-running unsaved Editor session gave both lights
a parent. Confirmed with a live repro: requested absolute position
(1,2,3), the CLI applied it as local, the light actually landed at
parent_world_position + (1,2,3) — nowhere near what was asked for.

**Fix**: `set_object_transform()` no longer calls the CLI command at
all for this. It writes its own `script eval` that assigns directly to
`t.position`/`t.eulerAngles` (world-space setters), correct regardless
of whatever parent an object has now or gains later — no manual
composition, no dependency on the CLI's (undocumented-to-us) choice of
local space.

## Camera near-clip plane — the real root cause of "black rendering" (2026-11-26)

**The single most expensive lesson this project has produced.** An
entire multi-session saga ("horror/thriller keep ending in black or
capped at 5/10") — the corrupted-baseline finding, the grading-
compounding finding, the p90-vs-baseline guardrail, all real, all
correctly fixed — turned out to be chasing symptoms downstream of a
completely different, far more mundane bug: the scene's **Main
Camera's near clipping plane was `0.01`**, and the camera happened to
sit right at the room's geometry boundary (confirmed: its position
exactly matched the scene's bounding-box max corner — i.e. right in
the corner, likely touching or just inside a wall/ceiling mesh).

**Why a TINY near-clip value causes BLACKNESS, not more visibility
(counterintuitive, read twice):** the near clipping plane is "how
close to the lens before Unity stops drawing it" — a small value means
MORE gets drawn, not less. With the camera touching a wall and
near=0.01, Unity faithfully rendered that wall's own interior/back
face at a few centimeters' distance, filling the ENTIRE frame with an
unlit surface. Visually indistinguishable from "the whole scene is
black" — it isn't a crushed render, it's a wall a centimeter from the
lens. Raising near-clip to ~12 made Unity ignore anything closer than
that, clipping the wall out of the frustum and finally revealing the
actual lit room behind the camera's near plane.

**Why nothing about this project's lighting/grading/guardrail work
could ever have caught it:**
- Clipping happens at the geometry stage of the render pipeline,
  strictly BEFORE the post-processing Volume stack runs. Disabling
  every post-processing effect (grading, vignette, fog) changes
  nothing, because none of it is reachable yet when a near-camera wall
  is already filling the frame. Confirmed live by Eran — the decisive
  clue that ruled out the entire grading/lighting investigation line.
- Unity's Scene view (the Editor's own free-roam camera) does **not**
  use a scene Camera *component's* clip planes or exposure settings at
  all — it has its own independent preview camera. This is exactly why
  Scene view looked properly lit the whole time while Game view (which
  renders through the actual `Main Camera` GameObject) was black. A
  "looks fine in Scene view" check is NOT a substitute for checking
  Game view — they can disagree completely and both be internally
  consistent.
- None of this project's tools (`set_light_properties`,
  `set_color_adjustments`, `set_vignette`, `set_fog`, `set_ambient`,
  etc.) touch the Camera component at all — camera transform/clip
  planes are completely out of scope for the agent, so no amount of
  mood-tuning could ever have self-corrected this.

**Red herring investigated along the way, for the record:** the Main
Camera also has "Physical Camera" exposure fields serialized (ISO 200,
f/16 aperture, 1/200s shutter — a bright-daylight exposure profile that
would plausibly crush an indoor scene too, and also wouldn't be
affected by toggling post-processing). This looked like a strong
candidate and matched the symptom just as well on paper. It was NOT
the actual fix — Physical Camera stayed checked ON in Eran's own
before/after screenshots, and the real fix was the clip plane. Lesson:
two independent explanations can both fit the same symptom; don't stop
investigating once you find A plausible cause, verify the one you fix
is actually the one that moves the needle.

**Practical takeaway for this project going forward:** when a scene
renders black/near-black and disabling post-processing doesn't change
it, check (in this order, cheapest first): (1) Camera near/far clip
planes vs. camera position relative to nearby geometry, (2) whether
Physical Camera is on with implausible exposure values for the scene,
(3) light bake mode (see "Lighting Mode" section above). Don't assume
it's a lighting/grading calibration problem just because that's what
the agent's own levers control — the camera itself is a real, silent
failure point this product has never had a tool or guardrail for.
