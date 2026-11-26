# Unused Unity lighting/rendering capabilities audit — 2026-11-26

Scope: catalog of Unity/URP/Camera/render-pipeline capabilities NOT
currently exposed to the agent, with concrete field names and a CLI
implementation note consistent with `unity_bridge.py`'s existing
conventions (`component get_fields`/`set_field` for plain serialized
fields, `script eval` for anything behind a `Volume.profile.TryGet<T>()`,
`RenderSettings`, or an asset reference). No instruction/persona changes
proposed — capabilities only.

---

## 1. `UnityEngine.Light` fields not exposed by get/set_light_properties

| Capability | API field | Why it matters for mood | Implementation note |
|---|---|---|---|
| **Light appearance mode** | `m_UseColorTemperature` (bool) | `set_light_properties` already writes `m_ColorTemperature`, but the Light Inspector has a mode toggle ("Color" vs "Filter and Temperature"). The code comment in `unity_bridge.py` even flags this: *"color_temperature...only visibly applies while m_UseColorTemperature is true...not managed here"*. If any light (especially agent-created ones, which inherit Unity's Light-component default) has this false, every `color_temperature` write the agent does is silently a no-op. This is a real, already-suspected gap. | `component set_field --component Light --field m_UseColorTemperature --value true`. Cheapest high-value fix: force this true inside `create_light()`'s existing setup block, same place shadow_type is force-set to "soft". |
| **Cookie (projected texture mask)** | `m_Cookie` (Texture reference), `m_CookieSize` (float, Directional only) | A cookie masks a light's shape — venetian-blind bars for noir, a window-pane cross for a cell/jail mood, dappled leaf shadows for a forest/outdoor scene, a flickering campfire texture. This is a classic, cheap mood tool with no geometry needed — directly fits "sell the feeling through atmosphere alone" since the agent can't add props. | Needs a cookie texture asset imported first (similar to the HDRI manifest pattern — a small curated set of cookie textures e.g. `venetian_blinds.png`, `window_cross.png`, `leaves.png` under `Assets/Cookies/`, with a manifest + `list_available_cookies()`/`set_light_cookie(target, cookie_id)`). Set via `component set_field --field m_Cookie --value <textureGUID-as-objectref>` — object-reference fields need `script eval` (`AssetDatabase.LoadAssetAtPath<Texture>(...)` then assign), not plain JSON value, since `component set_field` with `--value` for a reference type needs the right encoding; safest to go through `script eval` like the skybox material path does. |
| **Culling mask (layers this light affects)** | `m_CullingMask` (bitmask int) | Lets a light affect only objects on a specific layer — e.g. light only the "set dressing" layer and not a UI/overlay layer, or stage a light that affects only certain objects for a surreal/dreamlike partial-illumination effect. Lower priority than cookie/shadow nuances for THIS project since the scene has no meaningful layer taxonomy yet, but worth knowing it exists. | `component get_fields/set_field --component Light --field m_CullingMask --value <int>`. Needs scene layers actually defined first (`settings.tags_layers` CLI group) to be useful — currently moot without that. |
| **Light layer (rendering layer mask, URP-specific)** | `renderingLayerMask` via `m_RenderingLayerMask` (URP's per-light rendering layers, separate from Unity's legacy culling mask) | URP-specific: lets a light interact with only specific objects regardless of their legacy layer, used for e.g. a light that only lights a character and not the room (noir low-key "pool of light on the subject" look, or isolating a glowing prop). | Same encoding as culling mask, field name `m_RenderingLayerMask`; requires the URP Renderer's "Use Rendering Layers" enabled on the Universal Renderer asset (not currently confirmed enabled) — worth checking before building a tool around it. |
| **Shape fields for Area/Rectangle/Disc lights** | `m_AreaSizeX` / `m_AreaSizeY` (Rectangle), implicit radius for Disc, `m_ShapeWidth`/`m_ShapeHeight` depending on Unity version naming | `create_light` already allows `light_type="Rectangle"/"Disc"` but nothing ever sets their shape dimensions after creation — they're created at whatever Unity's default area size is. A soft, broad area light (big rectangle) reads completely differently from a pinpoint — this is the single biggest lever for "soft box" cinematic fill vs. "bare bulb" look, and the project already creates these light types but can't actually shape them. | `component get_fields --component Light --target <id> --detail full` to discover the live field names on this Unity version first (they vary slightly across versions — confirm before hardcoding), then add `area_size_x/y` params to `set_light_properties`. Clear, concrete, immediately useful gap since the light TYPE support already exists but the shape control doesn't. |
| **Bounding sphere override** | `m_BoundingSphereOverride`, `m_UseBoundingSphereOverride` | Performance/culling tool (controls when a light's effect range is considered for culling) — essentially irrelevant to mood, lowest priority on this list, included only for completeness per the audit ask. |
| **Render mode (Auto / Important / Not Important)** | `m_RenderMode` | Controls whether a light is forced to per-pixel/per-vertex rendering in the legacy pipeline — largely moot under URP's forward+/deferred lighting model where this has much less visual effect than in Built-in RP. Low priority; mentioned for completeness. |
| **Layer-aware shadow fields already partially exposed, nuance missing** | `m_Shadows.m_Resolution`, `m_Shadows.m_Bias`, `m_Shadows.m_NormalBias`, `m_Shadows.m_NearPlane`, `m_Shadows.m_Strength` | `shadow_type` (none/hard/soft) is exposed, but shadow **strength** (0-1, how dark the shadow actually is — distinct from existing or not) and **resolution** are not. Shadow strength in particular is a real, simple, high-value mood lever: a "soft_ambient" mood might want shadows to exist (soft type) but barely register (low strength), vs. a noir mood wanting full-strength, nearly black shadows. | `m_Shadows.m_Strength` (float 0-1) via the same `component set_field` pattern already used for `m_Shadows.m_Type`. Trivial addition to `set_light_properties`, same tier of effort as the existing shadow_type field. |

---

## 2. URP Volume override components NOT wired into this project's profile

Current profile only has `ColorAdjustments`, `Vignette`, `Fog` (fog is
actually `RenderSettings`, not a Volume override at all — separate
system). Every item below is added the identical way `set_vignette()`
already proved out: `vol.profile.TryGet<T>(out x); if (!exists) x =
vol.profile.Add<T>(true);` then set `.value`/`.overrideState` per
parameter, via `script eval`.

| Override | Namespace/class | Mood effect it unlocks | Implementation note |
|---|---|---|---|
| **Bloom** | `UnityEngine.Rendering.Universal.Bloom` (`threshold`, `intensity`, `scatter`, `tint`, `clamp`, `highQualityFiltering`, `skipIterations`) | The single highest-impact missing override for this project's genre list: festive/carnival string lights blooming, a sci-fi/thriller glowing console or neon sign, a dreamlike soft glow around any bright highlight, a "magical"/otherworldly quality. Directly serves EXPANSIVE and SOFT_AMBIENT archetypes which the agent currently has very limited tools to visually differentiate from RESTRAINED (right now it's mostly just color/saturation choices). | `bloom.intensity.value` (float, 0+), `bloom.threshold.value` (float, luminance cutoff), `bloom.tint.value` (Color). Add `set_bloom(intensity, threshold, tint)` identical shape to `set_vignette`. |
| **Film Grain** | `UnityEngine.Rendering.Universal.FilmGrain` (`type` enum, `intensity`, `response`) | Cheap, strong period/horror/found-footage texture — VHS/analog-horror grain instantly ages and roughens an image, a strong tool for "eerie_lab"/horror/post-apocalyptic archetypes beyond what color grading alone achieves. | `filmGrain.intensity.value` (0-1), `filmGrain.type.value` (enum int, e.g. `FilmGrainLookup.Thin1`). Straightforward `set_film_grain(intensity, grain_type)`. |
| **Lens Distortion** | `UnityEngine.Rendering.Universal.LensDistortion` (`intensity`, `xMultiplier`, `yMultiplier`, `center`, `scale`) | Subtle barrel/pincushion distortion reads as unease, disorientation, or a found-footage/surveillance-camera feel — useful for horror/eerie moods as a complement to vignette, which is the project's only current "frame-shape" tool. | `lensDistortion.intensity.value` (-1 to 1). `set_lens_distortion(intensity)`. |
| **Chromatic Aberration** | `UnityEngine.Rendering.Universal.ChromaticAberration` (`intensity`) | Color-fringing at frame edges — classic sickly/disoriented/analog-damaged look, pairs well with vignette+grain for horror/eerie archetypes; also a common "dreamlike" soft artifact at low intensity. | `chromaticAberration.intensity.value` (0-1). Trivial, single-field `set_chromatic_aberration(intensity)`. |
| **White Balance** | `UnityEngine.Rendering.Universal.WhiteBalance` (`temperature`, `tint`) | Distinct from `ColorAdjustments.colorFilter` (which multiplies/tints) — white balance shifts the whole image's perceived color temperature more naturally (closer to a camera's actual white-balance dial), good for "golden hour"/"cold morning" NATURALISTIC moods without the slightly artificial multiply-tint look `color_filter` currently produces. | `whiteBalance.temperature.value` (-100 to 100), `.tint.value` (-100 to 100). |
| **Split Toning** | `UnityEngine.Rendering.Universal.SplitToning` (`shadows` Color, `highlights` Color, `balance`) | Independently tints shadows vs. highlights — THE classic film-look grading tool (teal shadows / warm highlights for a cinematic thriller look, or the reverse for a surreal mood). This is strictly more expressive than the current single `color_filter` (one flat tint for the whole image) and maps directly onto the agent's existing film-director persona language. | `splitToning.shadows.value`/`.highlights.value` (Color), `.balance.value` (-100 to 100). |
| **Channel Mixer** | `UnityEngine.Rendering.Universal.ChannelMixer` (`redOutRedIn/GreenIn/BlueIn`, same for green/blue outputs) | Fine color-grading tool, more technical/less immediately mood-mappable than split toning or white balance — lower priority, included for completeness. |
| **Lift / Gamma / Gain** | `UnityEngine.Rendering.Universal.LiftGammaGain` (`lift`, `gamma`, `gain`, each a 4-channel Vector4-like) | Classic 3-way color corrector (shadows/mids/highlights independently) — more powerful but more complex than split toning; likely redundant with split toning + color adjustments for THIS project's mood-archetype granularity. Medium priority. |
| **Shadows/Midtones/Highlights** | `UnityEngine.Rendering.Universal.ShadowsMidtonesHighlights` | Similar 3-way grading tool, alternative to Lift/Gamma/Gain with a more intuitive curve-based UI; pick ONE of these two for the project, not both — redundant to wire both. |
| **Depth of Field** | `UnityEngine.Rendering.Universal.DepthOfField` (`mode` enum Gaussian/Bokeh, `focusDistance`, `aperture`, `focalLength`) | Shallow DoF (background blur) reads as intimate/dreamy/romantic (SOFT_AMBIENT) or as a dramatic rack-focus isolating a subject (RESTRAINED/threat). Real but secondary mood tool — needs a sensible focus distance relative to scene scale (same "calibrate against get_scene_bounds()'s diagonal" pattern already used for light range/fog), so it is a bit more guardrail-work than a simple float set. | `depthOfField.mode.value` (enum int), `.gaussianStart`/`.gaussianEnd` or `.focusDistance`/`.aperture`/`.focalLength` depending on mode. Needs a bounds-relative guardrail like `set_fog`'s. |
| **Panini Projection** | `UnityEngine.Rendering.Universal.PaniniProjection` (`distance`, `cropToFit`) | Wide-FOV barrel-style projection correction — niche, mostly a wide-angle-lens-feel tool, low mood value for this project's indoor room scenes. Low priority. |
| **Motion Blur** | `UnityEngine.Rendering.Universal.MotionBlur` | Requires actual camera/object motion to be visible at all — this project's scenes are static (no animation), so this override would currently have zero visible effect regardless of wiring. Skip unless the project later adds moving objects/cameras. |
| **Tonemapping mode** | `UnityEngine.Rendering.Universal.Tonemapping` (`mode` enum: None / Neutral / ACES) | Currently whatever the imported Volume profile happens to have (likely None or Neutral, unconfirmed — worth a `get_tonemapping()` read first). ACES compresses highlights much more aggressively and shifts overall contrast/color response — this single enum switch changes how EVERY other grading value (post_exposure, contrast, the whole post-processing stack) actually renders, and is a confirmed-relevant variable the agent currently has zero visibility into or control over. Given the project's own documented "compounding post-processing" bug history, this is a meaningfully undercovered variable. | `tonemapping.mode.value` (enum int 0=None, 1=Neutral, 2=ACES). Cheap add: `get_tonemapping()`/`set_tonemapping(mode)`, same shape as `get_vignette`/`set_vignette`. **Recommend reading current value first** before deciding whether to expose it as agent-controllable or just fix it to a sane default. |

---

## 3. Camera fields untouched by any tool

FOV was manually fixed this session; everything below is still fully
unmanaged. All read via `component get_fields --component Camera
--detail value`, written via `component set_field --component Camera`.

| Field | API name | Mood relevance | Note |
|---|---|---|---|
| **Clear flags** | `m_ClearFlags` (enum: Skybox / Solid Color / Depth only / Don't clear) | If ever set to Solid Color instead of Skybox, swapping skybox via `set_skybox()` would have ZERO visible effect on the background — a silent cross-dependency the agent has no way to detect or explain. Worth at minimum a **read-only** check surfaced in `get_scene_context()` (e.g. "camera clear_flags=Skybox" or a warning if it's Solid Color) so a skybox-swap failure is explainable, even without making it agent-writable. |
| **Background color** | `m_BackGroundColor` | Only visible when clear flags = Solid Color; otherwise irrelevant. Same note as above — low effort, mostly a diagnostic/guardrail value, not a creative lever. |
| **HDR toggle** | `m_allowHDR` (Camera.allowHDR) | Must be ON for Bloom to look correct (bloom needs values above 1.0, which only exist in an HDR buffer) — if HDR is off, wiring Bloom (section 2) would silently underperform or do nothing visible. **Direct dependency the agent should know about before Bloom gets added** — worth confirming this is true before/at the same time as building `set_bloom`. |
| **Post-processing per-camera toggle** | `renderPostProcessing` (`UniversalAdditionalCameraData.renderPostProcessing`, a component Unity attaches alongside Camera under URP, NOT a field on Camera itself) | If this is ever false, NONE of the Volume-based tools (ColorAdjustments, Vignette, future Bloom/grain/etc.) render at all regardless of what values are set — a single master kill-switch the agent has no visibility into. Worth a one-time confirmation this is true on the Main Camera (almost certainly is, since Vignette/ColorAdjustments are already confirmed visually working), then leave alone — not worth exposing as a lever, only worth a sanity check. |
| **Physical Camera (exposure/aperture/shutter/ISO)** | `m_UsePhysicalProperties`, `m_Aperture`, `m_ShutterSpeed`, `m_Iso`, `m_FocalLength`, `m_SensorSize` | **Already directly implicated in this project's own build log** (`unity-lighting-rendering-concepts.md`'s "Physical Camera... ISO 200, f/16 aperture, 1/200s shutter — a bright-daylight exposure profile" red herring). It was ruled out as the actual cause of the black-render bug that session, but it's still real, still unmanaged, and still capable of independently crushing or blowing out exposure regardless of every light/grading value the agent controls. A low aperture f-number (wide open) + high ISO would brighten everything; this is a second, completely independent exposure control layer sitting silently underneath the agent's ColorAdjustments.postExposure. | Given the documented history, strongly recommend at minimum reading and surfacing current Physical Camera values in `get_scene_context()` (same "diagnostic visibility, not necessarily a writable lever" treatment as clear flags) so a future false "the lighting is wrong" investigation doesn't have to rediscover this camera-level trap from scratch again. |
| **Culling mask** | `m_CullingMask` | Controls which object layers the camera renders at all — if a future light/object ends up on an excluded layer, it would be invisible regardless of lighting; currently moot (no real layer taxonomy in these scenes) but a known trap class (same shape as the light culling mask in section 1). |
| **Occlusion culling** | `m_OcclusionCulling` (bool) | Performance feature (skips rendering objects hidden behind others) — correctness, not mood. Only matters if the `occlusion bake`/`occlusion clear_bake` CLI commands (confirmed to exist, see section 7) are ever used; currently irrelevant since nothing has baked occlusion data. |
| **MSAA / anti-aliasing** | Set via `QualitySettings.antiAliasing` (confirmed currently **0** = off via `settings.quality get`) rather than a Camera field under URP (URP's renderer asset controls AA mode: None/FXAA/SMAA/TAA) | Pure image-quality/edge-smoothing, not a mood lever — mentioned for completeness per the audit ask, not recommended as an agent tool. |
| **Target texture / camera stacking** | `targetTexture`, URP `Camera Stack` (`UniversalAdditionalCameraData.cameraStack`) | No secondary/overlay cameras exist in this project (single Main Camera) — camera stacking (e.g. a separate overlay camera for a UI vignette or screen-space post effect layered on top) is architecturally interesting but has nothing to attach to right now. Not actionable without first creating a second camera, out of scope for a lighting-only agent. |

---

## 4. Render pipeline / quality settings not agent-controlled

Confirmed live via `settings.quality get` / `settings.graphics get`:
current quality level is `"PC"` (index 1, levels are `["Mobile","PC"]`),
anti-aliasing=0, vsync-count=0, default render pipeline asset =
`Assets/Settings/PC_RPAsset.asset` (a `UniversalRenderPipelineAsset`).

| Capability | Where it lives | Mood relevance | Note |
|---|---|---|---|
| **Shadow distance** | `QualitySettings.shadowDistance`, settable via `settings.quality set` | How far from the camera shadows render at all — in a small room this is usually a non-issue, but worth confirming it isn't accidentally clipping shadows short in a larger/outdoor scene (Forest scene mentioned in prior docs). | `unity command settings.quality set --settings '{"shadow-distance": N}' --confirm`. Diagnostic more than creative lever for this project's room-scale scenes. |
| **Shadow cascade count/resolution, soft shadow quality** | URP Renderer/Pipeline asset fields (`m_ShadowCascadeCount`, `m_MainLightShadowmapResolution`, `m_SoftShadowQuality`) — NOT exposed via `settings.quality`; live on the `PC_RPAsset.asset` itself, read/written via `component get_fields`/`set_field` with `--target` pointed at that asset path | Shadow resolution/softness quality affects how convincing soft shadows actually look (the project already sets `shadow_type='soft'` per-light, but if the pipeline asset's soft-shadow quality tier is "Low," soft shadows may look barely different from hard ones). Worth a one-time confirmation of current tier; likely not worth agent-control (performance/quality tier, not really a mood choice). | `component get_fields --target Assets/Settings/PC_RPAsset.asset --detail value` to see the real field names on this asset first. |
| **SSAO (ambient occlusion)** | A `ScreenSpaceAmbientOcclusion` renderer feature on the Universal Renderer asset (confirmed by convention, not yet confirmed present on THIS project's specific renderer asset — needs a direct check) | If present and enabled, SSAO adds contact shadows in corners/crevices that meaningfully deepen a scene's sense of enclosure/moodiness, independent of any light. If NOT present at all (likely, given this is a fairly bare renderer asset per the audit), adding it is a real, currently-completely-missing lever for "the room itself feels heavier/darker in its corners," which no light/grading combination the agent has can replicate (it's geometry-aware occlusion, not a uniform or directional effect). | Check via `component get_fields --target <RendererAsset> --detail full` for a `m_RendererFeatures` list; if absent, adding it is an editor-side setup step (not purely scriptable the same way a Volume override is) — flag as "possible, but needs one manual renderer-feature-add step outside the current script-eval pattern," not a drop-in. |
| **Anti-aliasing mode (FXAA/SMAA/TAA)** | Confirmed currently OFF (`anti-aliasing: 0`) via quality settings; URP's actual AA mode is instead a per-Camera `UniversalAdditionalCameraData.antialiasing` enum | Pure edge-quality, not mood — low priority, included for completeness. |
| **HDR (pipeline-level)** | `UniversalRenderPipelineAsset`'s `supportsHDR` field, separate from the per-camera `allowHDR` flag in section 3 — BOTH need to be true for Bloom to work correctly | Direct prerequisite for Bloom (section 2) exactly like the per-camera HDR flag — confirm both before wiring Bloom, not just the camera-level one. | `component get_fields --target Assets/Settings/PC_RPAsset.asset --field m_SupportsHDR --detail value`. |
| **Post-processing quality tier / Screen Space Reflections** | Not present in URP's stock feature set the same way as HDRP (URP has no built-in SSR renderer feature pre-14; may or may not exist depending on URP version used) | Needs a direct version check before claiming this is available at all — do not assume it's present. Lower priority/uncertain; flag for a follow-up check rather than claiming a concrete gap. |

---

## 5. Skybox / HDRI — current behavior and unused headroom

Confirmed from `unity_bridge.py`:

- `list_available_skyboxes()` reads a **local JSON manifest**
  (`data/hdri_manifest.json`) — no Unity call, pure metadata (id,
  filename, display_name, environment, time_of_day, weather,
  light_type, contrast, sky_view, tags, description) sourced from
  polyhaven.com's own tagging.
- `set_skybox(skybox_id, exposure, rotation)` **already exposes**
  exposure and rotation, not just the asset swap — confirmed in the
  code: it creates/reuses a `.mat` using Unity's built-in
  `Skybox/Panoramic` shader and sets `_MainTex`, `_Mapping` (fixed to
  1=Latitude-Longitude), `_ImageType` (fixed to 0), `_Exposure`
  (agent-controlled), `_Rotation` (agent-controlled), `_Tint` (**hardcoded
  to neutral gray `(0.5,0.5,0.5,0.5)`, never agent-exposed**).
- Calls `DynamicGI.UpdateEnvironment()` so ambient light/reflections
  update immediately — already correct, no gap there.

**Unused headroom**: `_Tint` is a real, currently-dead parameter on the
exact same shader already in use — a non-neutral tint would color-shift
the skybox (and, since `RenderSettings.ambientMode` is Skybox-driven per
the existing docstring, also color-shift indoor ambient light) without
needing a different HDRI asset at all — e.g. tinting toward red for an
"ominous sky" or green for an "alien/toxic" mood on top of any chosen
HDRI. Trivial to expose: add a `tint: tuple[float,float,float]` param to
`set_skybox()`, write it to `mat.SetColor("_Tint", ...)` instead of the
hardcoded neutral value.

---

## 6. Reflection probes — currently not agent-controlled at all

Confirmed: `ensure_scene_ready()` forces every `ReflectionProbe` to
`Realtime` mode (so changes aren't frozen), and
`capture_scene_baseline()`/`restore_scene_baseline()` snapshot and
restore each probe's `.mode` — but **nothing else about a reflection
probe is ever read or written**, and no tool lets the agent reason about
or adjust one. `.mode` itself (Baked/Realtime/Custom) isn't exposed as
an agent lever either (only as a code-level readiness fix).

| Capability | API field | What it would add |
|---|---|---|
| **Intensity** | `ReflectionProbe.intensity` | Scales how strongly the probe's captured reflection is blended onto nearby reflective surfaces — directly controls how much any mood-driven lighting/skybox change actually SHOWS UP as a reflection on glossy/metal/wet surfaces, if the scene has any. Currently frozen at whatever the probe's default is regardless of mood. |
| **Box projection + size/offset** | `boxProjection`, `size`, `center` | Controls how the reflection is projected into the room's actual volume (vs. treated as infinitely distant) — affects whether reflections look spatially correct for the room's actual scale. Secondary to intensity for mood purposes. |
| **Clear flags / background color** | `ReflectionProbe.clearFlags`, `.backgroundColor` | Same two Camera-like fields as section 3 — a probe is "like a small extra camera" per the project's own docs, so it independently inherits the same clear-flags trap: if set to Solid Color, a probe will reflect a flat color baked in regardless of what skybox/lighting the agent sets. |

**Why this matters for mood specifically**: this project's scenes are
confirmed to have no currently-known reflective surfaces (not called out
anywhere in the docs as a feature), so the practical payoff today may be
low — but ANY future scene with glass, water, or polished floors would
make this immediately visible and currently completely unresponsive to
mood changes, a silent gap of the exact same shape as the "Baked lights
don't update live" lesson already learned and fixed for lights/probe
MODE. Worth at least a `get_reflection_probes()`/one-line mention in
`get_scene_context()` ("N reflection probes present, intensity=X") so
the agent at least knows whether this lever is relevant to the current
scene, even before building a `set_reflection_probe` write tool.

---

## 7. Other CLI surface confirmed present and completely unused

Cataloged from a live `unity command --grep`/group listing against this
exact CLI build (confirmed, not guessed):

| Command group | What it does | Relevance |
|---|---|---|
| **`lighting bake` / `bake_status` / `cancel_bake` / `clear_bake` / `get_settings` / `set_settings`** | Full async GI-bake control (lightmapper, bounce count, resolution, directional mode, AO settings) via `lighting get_settings`/`set_settings`. | Directly relevant to the project's own documented Realtime-vs-Baked tension (`unity-lighting-rendering-concepts.md`). Not useful for the LIVE per-attempt agent loop (baking is slow, breaks the "quick mood change" promise, as already decided), but `lighting get_settings` as a read-only diagnostic would let `ensure_scene_ready()` confirm the scene-wide `mixedBakeMode` setting too, not just each individual light's bake type — currently only per-light mode is checked, the scene-wide setting is unchecked. |
| **`occlusion bake` / `bake_status` / `cancel_bake` / `clear_bake`** | Occlusion-culling bake control. | Pure performance, not mood — correctly out of scope. |
| **`settings.graphics get/set`** | Read/change the project's default render pipeline ASSET entirely (confirmed: currently `PC_RPAsset`). | Not a mood lever (swapping pipeline assets is a drastic, project-wide operation) — but `settings.graphics get` is a useful one-time diagnostic to confirm URP is actually active (confirmed: `using-scriptable-render-pipeline: true`), already effectively assumed correctly by this codebase. |
| **`settings.quality get/set`** | Read/change QualitySettings: level, vsync, anti-aliasing (confirmed: level=PC, AA=0, vsync=0 on this project). | See section 4 — AA toggle is the one piece here with any visible mood-adjacent effect (smoother edges in brighter/softer moods), everything else is pure performance tuning. |
| **`capture editor_window` / `capture scene_view`** | Beyond the already-used `capture game_view`, the CLI can capture ANY open Editor window (Inspector, Console, custom windows) and the Scene view specifically, with `source=screen` (toolbars/gizmos) or `source=camera` (clean render) variants, plus a `--camera` override to capture through a NON-main camera and a `--max-resolution` cap. | `capture game_view --camera <name>` is a real unused capability: if a second camera (e.g. a tighter close-up angle) is ever added, the judge could be shown a composed, mood-appropriate shot rather than only ever the Main Camera's current framing — not actionable without a second camera existing, but worth knowing the capture-side support already exists. |
| **`component get_properties`** | An alternative to `component get_fields` — returns a component's serialized properties as a flatter JSON map rather than the field-by-field descriptor format. | Not a new capability so much as a possibly-more-convenient read path; not worth switching existing working code, but worth knowing it exists if a future field proves awkward via `get_fields`. |
| **`material`** group (4 commands, unexplored in this pass) | Direct material property read/write (separate from the skybox material path already used). | Could matter if the project ever wants emissive-material mood edits (see `unity-lighting-rendering-concepts.md`'s own "Emissive materials" section, explicitly flagged there as "a judgment call for later, not v6") — confirms the CLI surface to do that already exists, whenever that's revisited. Out of this audit's scope (geometry/material edits), noted only because the doc itself anticipated it. |

---

## Summary table (all sections, at a glance)

| # | Area | Count of concrete unused capabilities found |
|---|---|---|
| 1 | Light fields | 7 (useColorTemperature, cookie, culling mask, rendering layer mask, area shape size, bounding sphere, shadow strength/resolution) |
| 2 | URP Volume overrides | 11 (Bloom, Film Grain, Lens Distortion, Chromatic Aberration, White Balance, Split Toning, Channel Mixer, Lift/Gamma/Gain, Shadows-Midtones-Highlights, Depth of Field, Panini, Tonemapping mode) |
| 3 | Camera fields | 7 (clear flags, background color, HDR toggle, post-processing toggle, Physical Camera, culling mask, occlusion culling) |
| 4 | Pipeline/quality | 5 (shadow distance, cascades/resolution, SSAO, AA mode, pipeline-level HDR) |
| 5 | Skybox | 1 real gap (tint, already-wired shader param, just hardcoded) |
| 6 | Reflection probes | 3 (intensity, box projection/size, clear flags) |
| 7 | CLI surface | 6 command groups confirmed present and unused (lighting bake/settings, occlusion, settings.graphics/quality, capture variants, material) |
