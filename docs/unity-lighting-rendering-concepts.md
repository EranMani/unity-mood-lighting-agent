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
