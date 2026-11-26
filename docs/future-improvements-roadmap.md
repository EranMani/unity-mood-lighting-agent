# Future improvements roadmap — 2026-11-26

Eran asked for a full "adventure": audit every Unity/rendering capability
the project doesn't use yet, critique the judge agent's design/persona,
critique the lighting agent's instructions, and research whether a
better existing competitor already does this. Two subagents did the
codebase/Unity-capability audit and the competitive research in
parallel; the judge/instruction critique below is a direct analysis of
`judge.py`/`agent.py` as they exist today.

This doc is the working backlog — not all of it should be built, see
"Recommended priority order" at the bottom for what's actually worth
doing next.

---

## 1. Unused Unity/rendering capabilities (full audit)

Full capability-by-capability breakdown with API field names and
implementation notes: see the companion doc this session also
produced, folded in below by category. Every entry follows this
project's existing pattern (`component get_fields`/`set_field` for
plain fields, `script eval` for anything behind `Volume.profile.TryGet<T>()`
or an asset reference).

### 1a. Light fields not exposed (7 found)

| Capability | Field | Why it matters | Priority |
|---|---|---|---|
| **`m_UseColorTemperature` bool** | Light | **Suspected live bug**: `set_light_properties`'s `color_temperature` writes may be silently no-ops on any light where this flag is false. Should be forced true inside `create_light()`, same place shadow_type is force-set. | 🔴 Fix now, cheap, likely-live bug |
| **Shadow strength** | `m_Shadows.m_Strength` | Currently only shadow_type (none/hard/soft) is controlled — not how DARK the shadow is. soft_ambient wants barely-there shadows, noir wants full-strength near-black ones; right now both get the same strength. Trivial single-field addition. | 🟡 High value, cheap |
| Cookie (projected texture mask) | `m_Cookie` | Venetian blinds, jail bars, dappled leaves — atmosphere with zero geometry needed. Needs a cookie-texture asset manifest (same pattern as the HDRI list). | 🟢 Interesting, more setup work |
| Rendering layer mask | `m_RenderingLayerMask` | Light-only-affects-subject tricks (noir spotlight-on-detective). Needs URP "Use Rendering Layers" confirmed first. | ⚪ Low priority, no layer taxonomy yet |
| Area/Rectangle/Disc light shape size | `m_AreaSizeX/Y` | `create_light` already allows these types but never sets their shape — biggest lever for "soft box" vs "bare bulb" look | 🟢 Worth adding if area lights get used |
| Culling mask, bounding sphere override, render mode | various | Performance/layer-taxonomy only, not mood-relevant | ⚪ Skip |

### 1b. URP Volume overrides NOT wired in at all (11 found)

Current Volume profile only has ColorAdjustments, Vignette, and Fog
(which is actually `RenderSettings`, not even a Volume override).

| Override | Unlocks | Priority |
|---|---|---|
| **Bloom** | Biggest single missing lever — festive string lights, neon signage, dreamlike soft glow. Directly serves EXPANSIVE/SOFT_AMBIENT archetypes, which right now only differ from RESTRAINED by color/saturation. **Needs HDR confirmed on at both camera (`m_allowHDR`) and pipeline (`supportsHDR`) level first.** | 🔴 Highest-impact addition |
| **Split Toning** | Independently tints shadows vs highlights (teal shadows/warm highlights) — strictly more expressive than the current single flat `color_filter`, and matches the agent's own "film director" persona language directly. | 🔴 High value, cheap |
| **Film Grain** | Cheap, strong analog-horror/VHS texture for eerie_lab/horror/post-apocalyptic beyond what color grading alone can do | 🟡 Worth adding |
| **Lens Distortion** | Subtle barrel distortion = unease/surveillance-camera feel for horror/eerie moods | 🟡 Worth adding |
| **Chromatic Aberration** | Color-fringing = sickly/disoriented/analog-damaged, pairs with grain+vignette | 🟡 Worth adding |
| **White Balance** | More natural whole-image color temp shift than `color_filter`'s multiply-tint — good for golden-hour/NATURALISTIC moods | 🟡 Worth adding |
| **Depth of Field** | Shallow DoF = intimate/dreamy or dramatic rack-focus | 🟢 Needs a bounds-relative guardrail like `set_fog`'s |
| **Tonemapping mode (None/Neutral/ACES)** | ⚠️ **Completely unknown to the agent what this is currently set to**, yet it changes how EVERY other grading value renders. Given this project's whole history of compounding post-processing bugs, this is a confirmed-relevant variable hiding in plain sight. **Read it first before deciding whether to expose it.** | 🔴 Investigate immediately, cheap |
| Channel Mixer, Lift/Gamma/Gain, Shadows/Midtones/Highlights | Redundant with Split Toning / too technical for mood-mapping | ⚪ Skip, pick one 3-way tool max |
| Panini Projection, Motion Blur | No mood value for static indoor scenes with no motion | ⚪ Skip |

### 1c. Camera fields (7 found, none currently touched by any tool)

| Field | Relevance |
|---|---|
| **Physical Camera (aperture/shutter/ISO/sensor/focal length)** | Already directly implicated as a ruled-out-but-plausible red herring in this session's camera-bug investigation. Still real, still unmanaged, still capable of independently crushing exposure under the agent's own grading. **Recommend surfacing current values diagnostically in `get_scene_context()`** so this trap can't be silently rediscovered again. |
| Clear flags (Skybox/Solid Color/Depth only) | If set to Solid Color, `set_skybox()` does nothing visible — a silent cross-dependency the agent can't currently detect |
| HDR toggle (`m_allowHDR`) | Direct prerequisite for Bloom (§1b) |
| Post-processing per-camera toggle | Master kill-switch for every Volume tool — almost certainly already on (Vignette/grading visibly work), one-time sanity check only |
| Background color, culling mask, occlusion culling | Low/no mood relevance currently |

### 1d. Render pipeline / quality settings (5 found)

Shadow distance/cascades/SSAO/AA mode are real but mostly performance-tier knobs, not mood levers — relevant mainly as one-time diagnostics (e.g. confirming soft shadows actually render meaningfully different from hard ones at the current quality tier), not agent-controllable day to day.

### 1e. Skybox — one real, nearly-free gap found

`set_skybox()` **already exposes exposure and rotation**, not just the asset swap. But `_Tint` on the exact same shader is **hardcoded to neutral gray and never exposed**. Since ambient is skybox-driven, a non-neutral tint would color-shift both the sky AND indoor ambient light without even picking a different HDRI — red for "ominous sky," green for "toxic/alien," on top of whatever HDRI is chosen. **This is close to a one-line fix** (add a `tint` param, write `mat.SetColor("_Tint", ...)`).

### 1f. Reflection probes — currently fully unmanaged

Intensity/box-projection/clear-flags are readable/writable but nothing ever touches them. Low practical payoff right now (no confirmed reflective surfaces in these scenes), but same silent-gap shape as the already-fixed "baked lights don't update live" lesson — worth a one-line mention in `get_scene_context()` before building a full tool.

### 1g. Other confirmed-present, completely unused CLI surface

- `lighting get_settings` — read-only, would let `ensure_scene_ready()` also confirm the scene-wide `mixedBakeMode`, not just per-light bake type.
- `capture game_view --camera <name>` — supports rendering through a non-main camera; not actionable without a second camera existing.
- `material` commands — confirms the CLI surface exists for emissive-material mood edits if that scope is ever revisited (explicitly deferred/out-of-scope today).

---

## 2. Judge agent redesign

Direct critique of `judge.py` as it exists today (not subagent-researched, this is a straight read of the actual code):

### Current state
- **Zero persona.** The agent prompt is pure task description ("you are given a screenshot... score it"), no identity, no stakes, no demanding standard. Compare this to `agent.py`'s lighting agent, which DOES have a persona ("world-class lighting director... you do not settle for a timid, half-committed result") and that persona demonstrably drives better behavior throughout this project's history.
- **Single scalar output.** `mood_match_score` (0-10) is the only quality signal, plus `dominant_color_temp`/`contrast_level` as loose descriptive tags. No structured breakdown of WHY — the agent's retry feedback only gets the raw reasoning text, not a per-dimension score it can target.
- **No before/after comparison.** The judge only ever sees the result frame, never the baseline. It can't tell "this is dramatically different from before" vs "this scene already looked moody and nothing really changed" — it's judging in a vacuum.
- **No visibility into the agent's own intent.** It only gets the mood_task string, never the lighting agent's own `mood_breakdown` (archetype/genre/target_contrast/strategy). It can't flag "the agent correctly understood this needs high contrast but then delivered medium" — only "this image does/doesn't look right," collapsing two different failure modes into one score.
- **`gpt-5.4-mini` for the single source of truth.** Every guardrail calibration this entire project has done (today's whole session) treats the judge's score as ground truth to tune against. If the judge itself is noisy, that noise gets baked into guardrail floors as if it were signal. This is the single highest-leverage thing to reconsider, since everything else in the pipeline is downstream of this call being trustworthy.
- **Single sample, no consistency check.** One LLM call scoring an inherently subjective axis ("how horror does this look") will have real run-to-run variance. The project's own docs already flagged this as a known gap ("next thing to add if scores look inconsistent run-to-run, not before") — given how much guardrail-chasing happened this session, it's worth asking whether some of that was judge noise, not guardrail miscalibration.

### Concrete recommendations
1. **Give it a persona — and make it the deliberate adversarial counterpart to the lighting agent's persona**, not just "a strict critic." Something like: *"You are a demanding AAA game studio's lighting producer, reviewing a lighting director's work before it ships. You have shipped multiple atmospheric, critically-praised titles and have zero tolerance for 'technically correct but uninspired' results. You are not here to be encouraging — you are here to protect the game's reputation."* This mirrors the agent's own persona construction (one creates, one critiques) rather than adding a generic "be strict" instruction — same pattern, opposite role.
2. **Add a before/after comparison.** Pass both `baseline.png` and the result image. Ask explicitly: "did the lighting meaningfully transform from the original, or does this read as a dim/cold version of the same base look?" This directly targets the exact failure mode ("lights turned down" vs "deliberately lit") that's recurred across this entire project's history.
3. **Add the agent's own stated intent to the judge's input** (`mood_breakdown`'s archetype/genre/target_contrast), so it can call out intent-vs-execution mismatches specifically, not just vibe-score the final pixels.
4. **Switch to structured, weighted sub-scores** instead of one holistic number: e.g. `drama_and_contrast` (does the lighting itself create shape, not just dimness), `color_story` (does the palette support the mood), `legibility` (can you still read the space), `distinctiveness` (does this feel deliberately composed vs. generic). Compute the final score from these, and feed the WORST-scoring dimension back as the sharpest piece of retry feedback.
5. **Consider a stronger model for the judge specifically**, even if the lighting agent stays on a cheaper/faster model — the judge is the one component every other piece of this system (guardrails, calibration, the whole retry loop) treats as ground truth.
6. **Run the judge 2-3x and take the median**, at least for close calls near the pass threshold, to separate genuine quality signal from LLM sampling noise — directly actionable now that multiple sessions' worth of effort has gone into guardrail calibration that implicitly assumed judge-score stability.

---

## 3. Lighting agent instruction refinements

The agent's instructions are already strong (persona, archetype classification, key/fill/rim, render-pipeline-order, lever menu, deterministic diffing) — these are additive gaps, not fixes to something broken:

- **Motivated lighting isn't explicitly taught.** Real lighting design ties every light to an in-world source (a lamp, a screen, a window) — the project already has a Spatial Agent producing anchors for exactly this purpose, but the lighting agent's instructions never explicitly say "every light should read as coming from something in the room, not floating in space." Worth one explicit line tying the key/fill/rim guidance to the existing spatial anchors.
- **No color-theory technique beyond "cold vs warm."** Classic complementary schemes (warm key + cool shadows = teal-orange; the reverse, cool key + warm practical highlights, for horror) aren't named anywhere. The agent currently picks color pragmatically per-attempt rather than from a named palette technique — naming 2-3 concrete schemes per archetype could sharpen consistency.
- **No composition/framing guidance** — where in frame the brightest/darkest zones should fall relative to the camera isn't addressed at all (rule-of-thirds-style lighting composition). Given the camera is explicitly out of scope, this is about placing lights to favor where the EXISTING camera is already looking, not moving the camera.
- **Fog-color-matches-key-light-color unification** isn't explicitly called out — fog currently gets tuned as its own independent lever rather than instructed to echo the key light's color temperature for atmospheric consistency.
- **If Bloom/Split Toning get added (§1b), the lever menu needs updating** to include them as named options, same structure as the existing 8-lever list, not just silently available as new tool calls with no guidance on when to reach for them.

---

## 4. Competitive landscape — verdict

Full findings from the research pass (web search + source review):

**No existing product combines our specific stack**: Unity-only + strictly lighting/rendering-scoped (geometry/props explicitly off-limits) + judge agent + deterministic pixel guardrails + automatic retry-until-pass loop. Individual pieces exist scattered across different products, never together:

- **Promethean AI** (real, 7+ year commercial product, Unreal-primary with Unity/Maya/Blender plugins) — does NL-driven scene changes in Unity, but for **object placement/set-dressing**, explicitly NOT lighting (lighting was "in the works" in 2018 demos and still isn't a shipped feature as of 2024-2025 coverage). Opposite scope from us: it touches geometry/props, barely touches lighting.
- **Unity's own Muse suite** (Chat/Sprite/Texture/Animate/Behavior) — **no lighting/mood/atmosphere feature exists or has been announced.** A real, confirmed gap in Unity's own official tooling.
- **3DLabInstruments/UnityACPClient** (GitHub, OSS) — the closest functional match. Ships a demo "switch scene lighting from noon to another look" and a mood-based lighting skill. But it's a generic coding-agent bridge with **no judge, no guardrails, no retry loop, and no lighting-only scope enforcement** — the agent can and is expected to touch anything in the scene.
- **Quadify's BlenderMCP "AI Render Critic"** — a real, shipped feature that's the closest match to our *judge half* specifically (VLM critiques a render with a lighting-focused mode, 1-10 score). But it's **advisory only** — no autonomous edit/retry loop, no deterministic guardrail, and it's Blender, not Unity.
- **LumiVideo** (academic preprint) — closest conceptual cousin: an agentic perception→reasoning→execution→reflection pipeline with a VLM judge and beam-search retry. But scoped to 2D video color grading (LUTs), not 3D engine lighting, and has **no deterministic pixel-guardrail layer** at all — purely trusts the VLM judge.
- **unity-semantic-bridge** (GitHub) — worth noting as a real signal: this project actually **removed** an LLM-judged lighting diagnostic sub-agent in a changelog, replacing it with deterministic checks, because pure-LLM lighting judgment wasn't worth the cost/complexity. That's direct evidence from someone else's real attempt that argues FOR keeping our deterministic guardrails as the primary gate (already our design) rather than over-trusting the judge.

**Verdict: genuine, narrow white space, not a reinvention.** The two actual differentiators worth defending explicitly:
1. **The hard lighting-only scope guarantee** — nothing else in this space enforces this; competitors either don't touch lighting at all or touch everything unscoped.
2. **The judge + deterministic-guardrail dual-gate retry loop** — pieces of this exist elsewhere (VLM critics in Quadify/LumiVideo), but nothing pairs an LLM judge with a hard, non-LLM pixel-metric safety net the way this project does, and at least one real competitor found pure-LLM judging alone not worth it.

Worth watching: Unity Muse is expanding yearly, so this gap in official tooling may not stay open forever.

---

## Recommended priority order

Given everything above, roughly in order of (impact × cheapness):

1. **Fix `m_UseColorTemperature`** in `create_light()` — suspected live bug, one line.
2. **Check `Tonemapping` mode right now** — read-only, costs nothing, could explain existing weirdness.
3. **Add shadow strength** to `set_light_properties` — trivial, directly differentiates soft_ambient vs noir.
4. **Add skybox `_Tint`** — near-zero-effort, already-wired shader param.
5. **Add Bloom** (after confirming HDR is on both camera + pipeline level) — highest-impact new Volume override.
6. **Add Split Toning** — cheap, high expressive value, matches the agent's own persona language.
7. **Judge redesign**: persona + before/after comparison, in that order — directly targets this project's most recurring failure mode ("dimmed, not deliberately lit").
8. Everything else (Film Grain, Lens Distortion, Chromatic Aberration, White Balance, Depth of Field, cookies, reflection probes, multi-sample judge averaging, structured sub-scores) — real, but second-wave, not blocking anything today.
