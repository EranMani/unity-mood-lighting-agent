# Scene/geometry transformation — parked roadmap idea

**Status: not started, deliberately.** Recorded here so the idea isn't
lost, and so future-us doesn't have to re-derive the reasoning for why
this is scoped separately from the lighting agent. Do not start building
this until v0-v4 (the lighting-only pipeline) are fully proven out, and
there's a real, validated need — not just "it would be cool."

## The evidence that led here

Tested the lighting agent (full tool set: position/rotation, intensity,
color, color temperature, bounce, create/aim) against the imported Mess
Hall demo scene (sci-fi corridor: vending machines, arcade cabinet, bed,
neon-ish props) across three moods:

| Mood | Score | Why |
|---|---|---|
| Horror (dark, ominous, cold) | 6/10 — **passed** | Genre roughly fits a dim techy room |
| Cozy cafe / living room | 3-4/10 — failed | Room's actual props (vending machine, arcade) contradict "cozy" regardless of light color |
| Abandoned sci-fi outpost | 5/10 — close, failed | Genre fits, but judge wanted decay/scale/isolation — things a small clean room physically can't fake with lighting alone |

Conclusion: lighting genuinely shifts atmosphere within what a scene's
geometry supports (confirmed, works). It cannot change what the scene
*is* — no light setting turns a vending machine into a cafe counter, or
makes a small room look derelict and vast. That's not a tooling gap in
the lighting agent; it's a different kind of problem.

## What "scene/geometry transformation" would actually mean

Not fully scoped (that's the point of parking it), but the shape, as
discussed live with Eran:
- Adding/swapping props to match a mood's genre (e.g. a coffee cafe needs
  coffee-cafe props, not sci-fi vending machines)
- Changing materials/colors on existing geometry (walls, floors) rather
  than only changing what lights ON them
- Possibly camera framing/composition, since mood is partly about what's
  actually in frame, not just how it's lit

## Why this is a genuinely different, bigger scope — not an extension

- The lighting agent's tool surface (`set_object_transform`,
  `set_light_properties`, `create_light`/`create_light_near`,
  `aim_light_at`) is entirely about EXISTING objects' transforms and
  Light components. None of it touches meshes, materials, or asset
  import/instantiation of new non-light prefabs.
- Needs a real asset source — where do "cafe props" come from? Either a
  pre-imported library (like the Mess Hall pack was, manually, this
  session) or some kind of procedural/generative asset pipeline. Neither
  exists yet, and sourcing/importing props on demand is a real unsolved
  problem of its own, bigger than anything built so far.
- The judge would need new scoring dimensions beyond `mood_match_score`/
  `dominant_color_temp`/`contrast_level` — those were designed assuming
  lighting is the only lever. Prop/material appropriateness needs its
  own criteria.

## Open questions for whenever this gets picked up

- Swap existing props, or add new ones alongside what's there, or both?
- Where do new props come from — a fixed local asset library the agent
  picks from, or something generative?
- Does the agent get a `list_available_props(category)` style tool, or
  is prop selection still code-orchestrated (same code-vs-agent split
  question that's recurred throughout this project)?
- Materials: full material swap, or just tint/color override on existing
  materials (much smaller, might get partway there without new props at
  all — worth testing BEFORE touching props, since it's a much smaller
  diff)?
- Does this need its own judge pass, run before the lighting judge
  (fix the scene's content first, then light it), or one combined judge
  scoring both at once?

## The honest first experiment, if/when this gets picked up

Before building anything: test whether a **material color/tint override**
alone (no new props, no new meshes — just recoloring existing geometry)
moves the needle on a mismatched mood. That's a much smaller change than
full prop swapping, reuses the same "set properties on an existing
component" pattern the lighting tools already use (`component set_field`
on a `Renderer`/`Material`, not a new asset-import pipeline), and would
tell us whether "wrong colors" or "wrong objects entirely" is the bigger
blocker — the same kind of cheap, disprovable experiment this whole
project has run before building anything heavier.
