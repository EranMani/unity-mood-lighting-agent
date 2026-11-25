# Lighting-only mood test results

Real results from live runs during the 2026-11-19 session, testing
whether lighting alone (intensity/color/color-temp/bounce + create/aim,
no post-processing/fog/skybox) can reliably cross the judge's pass
threshold (`mood_match_score >= 6`). Test scene: the imported "FREE Low
Poly Sci-Fi Mess Hall Environment Demo" (sci-fi corridor: vending
machine, arcade cabinet, bed, shelving, projector).

## Results table

| # | Mood task | Attempts to resolve | Final score | Passed? | Judge notes (verbatim) |
|---|---|---|---|---|---|
| 1 | "apply a horror mood vibe to this scene - dark, ominous, cold, strong contrast" | 2/3 | 6/10 | **Yes** | "The scene has a dark, cold sci-fi look with some ominous lighting and isolated blue accents. But it's more moody/sparse than truly horrifying, and the contrast isn't strong enough for a full horror vibe." |
| 2 | "cozy, warm, inviting mood - like a cafe or living room" | 3/3 (gave up) | 3/10 | No | "There is some warm lighting on the walls, but the scene feels sparse, industrial, and a bit cold rather than cozy or inviting. It reads more like a dim sci-fi room than a cafe or living room." |
| 3 | "eerie abandoned sci-fi lab mood - quiet, unsettling, dim emergency lighting, sense of something wrong" | 1/3 | 6/10 | **Yes** | "The blue emergency-style lights and dark room help sell an eerie sci-fi feel, but the scene reads more like a small retro game room than an abandoned lab. It lacks clutter, decay, or stronger unsettling details to fully match the mood." |
| 4 | "tense sci-fi thriller mood - cold, isolated, high contrast, something lurking nearby" (MAX_LIGHTS=6) | 3/3 (gave up) | 4-5/10 | No | "The scene has a cool, dim sci-fi feel with isolated lighting and a few glowing screens, but it reads more like a quiet retro control room than a tense thriller. There's little visual evidence of menace or something lurking nearby, and the contrast is not especially strong." |
| 5 | Same thriller task, re-run after bumping `MAX_LIGHTS` 6→10 | 3/3 (gave up) | 4/10 | No | "The scene is cool-toned and dim, which helps a bit, but it reads more like a quiet retro game room than a tense sci-fi thriller. There's little real isolation, threat, or high-contrast drama, and nothing clearly suggests something lurking nearby." |
| 6 | "warm golden hour sunlight mood" | 1/3 | 6/10 | **Yes** | "The scene has a warm amber palette that fits golden-hour-adjacent lighting, but it reads more like indoor retro ambient light than natural sunlight. No strong directional sun shafts, shadows, or exterior cues to really sell golden hour." |

## v3: post-processing tools added (color grading, vignette, fog)

Added `set_color_adjustments`, `set_vignette`, `set_fog` — scene-wide
rendering levers beyond individual lights. Re-tested the two moods that
failed lights-only:

| # | Mood task | Attempts | Final score | Passed? | Judge notes (verbatim) |
|---|---|---|---|---|---|
| 7 | "cozy, warm, inviting mood" (post-processing tools available) | 1/3 | 6/10 | **Yes** (was 3/10 lights-only) | "The scene has a soft warm palette and some inviting elements, but it reads more like a sparse retro arcade/utility room than a cozy cafe or living room. The emptiness and lack of soft furnishings reduce the cozy feel." |
| 8 | "tense sci-fi thriller mood" (post-processing tools available) | 3/3 (gave up) | 4-5/10 | No (same as lights-only) | "Cold blue palette and fog create some isolation, but the scene is very washed out and lacks strong contrast or a clear sense of lurking danger. It reads more like an obscured empty room than a tense sci-fi thriller." |

**Real finding**: post-processing moved cozy cafe from fail (3/10) to
pass (6/10) — color grading/vignette gave the agent levers lighting
alone couldn't provide. Thriller mood still failed, same score range as
before — its judge notes still point at content (clutter, menace,
things that could be "lurking"), which post-processing can soften/frame
but not create from nothing. Consistent with v5: post-processing extends
what lighting-only could do, but doesn't remove the content ceiling.

## v3.1: scale-relative fog guardrail + scene-wide context + a real bug fix

Eran caught (visually, from a screenshot) that the agent was stacking
fog + vignette + negative exposure too aggressively, producing washed-
out/flat results. Root cause #1 (fog specifically): `end_distance=35`
set in a room whose real diagonal is ~22.8 — fog that never reaches
full strength within the room reads as a flat haze, not depth. Fixed
with `get_scene_bounds()` (computes real scene diagonal) + a `set_fog`
guardrail rejecting distances that exceed it, plus a docstring
explaining what the numbers mean in world-space terms.

Root cause #2 (general over-stacking): `get_scene_context()` only
exposed object transforms, never the CURRENT color grading/vignette/fog
state — so the agent reasoned about each lever in isolation on every
attempt, with no visibility into what was already pushing the scene
darker/colder. Fixed by adding current post-processing values to the
context string every attempt (not just on judge failure), with explicit
"these effects stack" framing.

While testing, also found and fixed a real, unrelated latent bug:
`set_light_properties`/`get_light_properties`/`set_object_transform`
passed the int instance_id straight into `subprocess.run`'s args list
(which requires str), silently failing with "TypeError: expected str...
not int" on any light whose ID reached these functions as a raw Python
int rather than pre-stringified. Explains "2 point lights errored"
appearing in every recent thriller-mood attempt.

| # | Mood task | Attempts | Final score | Passed? | Judge notes (verbatim) |
|---|---|---|---|---|---|
| 9 | "tense sci-fi thriller mood" (fog guardrail + stacking-aware context + light-update bug fixed) | 3/3 | **7/10** | **Yes** | "The scene does feel cold, isolated, and sci-fi, with blue lighting and a sparse room. But it reads more like a quiet control room than a tense thriller; the contrast is fairly soft and there's little visible sign of danger or something lurking nearby." |

**This is the first passing result for the thriller mood across the
entire session** — went from failing every single attempt (lights-only
AND first post-processing pass) to a clean pass once the agent could
see its own cumulative state and couldn't set fog to nonsensical
distances for the room's scale.

## Score summary

- **5 of 6 distinct moods now pass** (horror, eerie abandoned lab,
  golden hour sunlight, cozy cafe, sci-fi thriller)
- Thriller mood needed BOTH the fog guardrail/context fix AND the
  int-target bug fix to finally pass — can't fully separate which one
  mattered more, both landed in the same commit before the passing run

## Conclusion

Lighting-only (intensity/color/color-temp/bounce/aim, no post-processing)
**reliably crosses the judge's threshold when the mood fits the room's
actual content** (horror/eerie-lab, both roughly sci-fi-adjacent moods
against a sci-fi room). It **reliably fails** when the mood requires
content the room doesn't have (cafe furniture for "cozy," scale/emptiness
for "isolated"/"lurking") — a lighting lever cannot fix a content
mismatch, confirmed by bumping the light cap with zero effect on score.

This is the real evidence behind the v5 decision (parked, not built):
scene/geometry transformation is a separate, bigger problem from
lighting control, not a missing feature of the lighting agent. See
`docs/scene-transformation-roadmap.md`.

## Known bugs fixed during this test series

- `create_light`/`aim_light_at`'s raycast guardrail wasn't checked against
  colliderless root objects — `list_scene_transforms()` was later fixed
  to resolve containers to their real collider-bearing (or Light-bearing)
  children. See README build log steps 20-21 and the "Light" container
  bug (a root named "Light" had no Light component itself, only 2 Point
  Light children — fixed the same way).

## Parked idea: diff-with-outcome tracking (not built, no evidence yet)

Eran's question: right now `get_scene_context()` gives the agent
absolute current state ("fog density is 0.02"), and the judge gives
prose feedback ("too washed out"). Neither tells the agent WHAT CHANGED
between attempts and WHAT EFFECT that change had on the score. A third
layer — "you moved saturation from 7.8 to -12 last attempt, score went
3→5" — would let it reason causally (did that help or hurt?) instead of
re-deriving everything from scratch each attempt.

**Trade-offs if built:**
- Pro: could reduce wasted attempts, more useful the more attempts a
  run has (currently capped at 3, so limited window to pay off)
- Pro: natural fit if MAX_ATTEMPTS is ever raised
- Con: real new state to maintain (every tool call's before/after value
  + the score that followed), more moving parts
- Con: grows the prompt every attempt — more tokens/cost in an already-
  short 3-attempt loop
- Con: risk of overfitting to this one scene's specific numbers rather
  than reasoning about moods generally — could hurt transfer to a
  different scene
- Con: **no evidence yet that this is the actual bottleneck** — thriller
  already passed on attempt 3/3 without it; building this now would be
  solving a hypothesized problem, not an observed one

**Decision**: don't build yet. Run 5+ more mood tests first (different
moods, same scene), then check `mood_test_log.jsonl` + per-attempt judge
notes for a real pattern — e.g. the agent visibly moving a value in a
bad direction twice in a row, or running out of attempts while still
clearly converging. If that pattern shows up, this is justified by
evidence. If not, it's solved already or a different problem.

## Eval harness built, full 10-case suite run twice (step 27)

Built `eval_suite.json` (the 10 moods tested so far, as a canonical,
re-runnable set) + `eval.py` (the harness — scaffolding OUTSIDE the
agent that loops the suite, calls `main.py`'s `run()` per case, tags
each result's `case_name` in `mood_test_log.jsonl`, prints a summary
table). Scoped as single trial per case for v0, per discussion with
Eran — real production evals often run multiple trials per case since
LLM output isn't deterministic; that's the next addition if scores look
inconsistent, not before.

Ran the full suite twice, back to back, same scene, same code, nothing
changed between runs — a direct test of how much a single trial's
pass/fail can be trusted:

| Case | Run 1 | Run 2 | Verdict |
|---|---|---|---|
| horror | 7 PASS | 7 PASS | solid pass |
| golden_hour | 6 PASS | 7 PASS | solid pass |
| zen | 6 PASS | 6 PASS | solid pass |
| eerie_lab | 3 FAIL | 6 PASS | **borderline/noisy — flipped** |
| noir | 6 PASS | 5 FAIL | **borderline/noisy — flipped** |
| cozy_cafe | 2 FAIL | 2 FAIL | solid, consistent fail |
| thriller | 2 FAIL | 3 FAIL | solid, consistent fail |
| dreamlike | 2 FAIL | 3 FAIL | solid, consistent fail |
| festive | 3 FAIL | 1 FAIL | solid, consistent fail |
| post_apocalyptic | 4 FAIL | 1 FAIL | solid, consistent fail |

Both runs landed at 4/10 overall, but *which* 4 passed differed —
`eerie_lab` and `noir` crossed the pass/fail threshold (6) in opposite
directions between runs with zero code/scene changes. That's real,
measured LLM non-determinism, and it specifically matters at the
threshold boundary — a single trial's pass/fail for a borderline case
cannot be trusted; this is the concrete evidence the earlier "no
evidence yet" multi-trial discussion was waiting for, scoped to
borderline cases specifically.

The other 5 failing moods did NOT flip — same ballpark score, same
fail, both runs, no boundary-crossing drama. That consistency is itself
the signal: this isn't noise, it's a real ceiling. All 5
(cozy_cafe, thriller, dreamlike, festive, post_apocalyptic) need actual
scene CONTENT (furniture, decorations, decay, open space) that a sci-fi
mess-hall scene (vending machines, arcade cabinets, bunks) structurally
doesn't have — lighting alone cannot manufacture "festive party" or
"cozy cafe" out of a room full of retro arcade gear. This is exactly
the v5 hypothesis from the original lights-only test series, now
confirmed with a second, independent dataset rather than resting on
the first one alone.

**Conclusion**: the eval harness did its real job here — it separated
"needs more trials before trusting the number" (eerie_lab, noir) from
"needs a different scene/scope, not more lighting tools" (the other 5).
Next real step for THIS scene's results: either (a) build multi-trial
averaging for borderline cases specifically, or (b) treat the 5
consistent fails as confirmation to actually scope v5 (scene/content
transformation) rather than continuing to add more lighting/post-
processing tools against a content ceiling that more lighting can't
cross.

## Post-processing contamination found and fixed; suite run a third time (step 28)

**What we tried to resolve**: Eran asked whether `cleanup_agent_lights()`
also resets post-processing between runs. It didn't — checked the live
code, confirmed no reset logic existed for ColorAdjustments/Vignette/
Fog at all. Checked the LIVE scene state with no mood task running: it
was sitting at `saturation=-100, contrast=70, vignette=0.6` — noir's
leftover grading from the end of run 2, still active. Proof the
contamination was real, not hypothetical: every mood case in the suite
was starting from whatever the PREVIOUS case left behind, not a clean
slate, same bug class as the light-stacking issue but for render state
instead of light objects.

**What we tried**: built `reset_post_processing()` (`tools.py`), called
once at the top of `main.py`'s `run()`, alongside `cleanup_agent_lights()`.
Resets to a defined NEUTRAL baseline (0 exposure/contrast/saturation, no
tint, vignette off, fog off) — explicitly NOT the original imported
pack's values, which were already overwritten by this session's many
mood tests before anyone recorded them; that original baseline is
unrecoverable. This defines a clean, documented, consistent starting
point going forward instead. Verified live before trusting it: read the
contaminated state, called reset, re-read — confirmed clean neutral
values across all three systems.

**Result — ran the full suite a third time, with the fix in place:**

| Case | Run 1 | Run 2 | Run 3 (with fix) |
|---|---|---|---|
| horror | 7 PASS | 7 PASS | 8 PASS |
| golden_hour | 6 PASS | 7 PASS | 7 PASS |
| zen | 6 PASS | 6 PASS | 6 PASS |
| eerie_lab | 3 FAIL | 6 PASS | 6 PASS |
| noir | 6 PASS | 5 FAIL | 5 FAIL |
| cozy_cafe | 2 FAIL | 2 FAIL | 2 FAIL |
| thriller | 2 FAIL | 3 FAIL | 4 FAIL |
| dreamlike | 2 FAIL | 3 FAIL | 3 FAIL |
| festive | 3 FAIL | 1 FAIL | 3 FAIL |
| post_apocalyptic | 4 FAIL | 1 FAIL | 3 FAIL |

**Conclusion, stated honestly**: the pass count did NOT change (4/10, all
three runs). The fix was correct and necessary — contamination was real,
proven live — but it was not the main driver of the low overall pass
rate. Two things it DID show:

1. The 4 hardest-failing moods (cozy_cafe, dreamlike, festive,
   post_apocalyptic) stayed exactly as stuck as before, same low score
   band, completely unmoved by removing a known source of cross-run
   noise. This is a USEFUL negative result — it rules out contamination
   as their cause and strengthens the content-ceiling conclusion rather
   than weakening it: these moods aren't failing because of leftover
   state, they're failing because the scene lacks the content they need.
2. Already-passing moods trended slightly up (horror 7→7→8, golden_hour
   6→7→7) — small, in the expected direction if the fix is doing
   something real, though not a dramatic effect.

One honest caveat, not overclaimed: `eerie_lab`/`noir` (the two
run-to-run flippers) each have only ONE data point post-fix. They look
stable now, but one run isn't enough to confirm the flip-flopping is
actually resolved versus landing the same way by chance again — would
need a 4th run to really know.

**Where this leaves the two real open decisions from step 27**: option
(a), multi-trial averaging, would still only help the 2 borderline
cases — the 4 solid fails are now confirmed NOT to be a trial-count or
contamination problem. Option (b), scoping v5 (scene/content
transformation), looks like the higher-value next move: it's the only
lever that could move 4 of the 6 currently-failing cases, and this
session just spent two real fixes (light-stacking, post-processing
contamination) ruling out the two most likely "it's just orchestration
noise" explanations for them.

## Business reframe: lights/rendering-only, no geometry — v5 killed (2026-11-23)

Eran reframed the business problem explicitly (verbatim): "I don't
want to add new geometry or new props so far... I want to focus on the
lighting agent only so we need to work with what we have in the scene."
This kills v5 (scene/content transformation) as a direction entirely,
not just parks it — the 4 "content ceiling" fails from the previous
section are now the actual product boundary to push against with
lighting/rendering alone, not evidence to go build geometry tools.

Everything below this point is organized the way Eran asked going
forward: **every tuning change gets a dated entry recording what
changed, why, and the measured before/after** — progress or regression,
not just "we tried something." No more ad-hoc notes without a verdict.

**Before writing any date in this table or anywhere in this doc: check
the ACTUAL current date (e.g. from the system/conversation context),
never copy a date from an existing entry above.** Caught a real bug
2026-11-23: an entire table's worth of rows got mislabeled 2026-11-20,
copied from an older, genuinely-correct README entry, without checking
what day it actually was. A change log with wrong dates looks fake and
can't be trusted for sequencing later.

### Change log

| Date | Change | Rationale | Case(s) tested | Score before → after | Verdict |
|---|---|---|---|---|---|
| 2026-11-23 | Eval suite split per scene (`eval_suite.json` scene field, `eval.py` per-case scene) + fixed a `Lightmapping.lightingSettings` crash (throws instead of returning null when unassigned) | Testing every mood against one scene was conflating "mood impossible" with "wrong scene for this mood" | Full 10-case suite | 4/10 (Mess-Hall-only) and 5/10 (Forest-only) → **7/10** (scene-matched) | **Progress** — real, not noise: thriller/dreamlike specifically flip based on scene fit, matching the hypothesis |
| 2026-11-23 | Judge `MoodJudgement.notes` → `reasoning`, moved FIRST (reasoning-then-score instead of score-then-rationalize); see `docs/agent-output-quality-techniques.md` for the full mechanism | Field order is generation order in structured output — forcing a description before the number grounds the score in real observations | horror, golden_hour (smoke test) | horror 5/10 FAIL → 6/10 PASS (same scene state, one more run) | **Inconclusive on its own** — flagged honestly at the time: 1 data point, this project has documented real non-determinism right at the pass boundary, can't attribute the flip to this change alone |
| 2026-11-23 | Judge instructions: explicit scope language — score atmosphere given existing geometry, do NOT deduct for missing props/decorations/debris that would require adding geometry | The judge's own prior reasoning for eerie_lab/festive/post_apocalyptic literally cited "no gifts," "no debris," "no wreckage" — scoring against a target lighting alone can never reach, regardless of agent skill. A real miscalibration, not grade inflation | eerie_lab, festive, post_apocalyptic | eerie_lab 5→6, post_apocalyptic 2→6, festive 3→4 | **Progress on 2/3** — see below |
| 2026-11-23 | Agent instructions: explicit "sell the feeling, not the content" strategy + push for committed/extreme values instead of timid nudges + multiple colored lights for colorful moods + combine levers together | Agent was likely under-using its own toolset (moderate, safe parameter choices) rather than genuinely hitting a wall | eerie_lab, festive, post_apocalyptic (same run as above, both changes landed together) | (combined with judge recalibration above) | **Progress on 2/3**, see below — can't fully separate which of the two changes (judge vs agent) mattered more for eerie_lab/post_apocalyptic, both landed in the same commit before the re-test |
| 2026-11-23 | Built the before/after screenshot pipeline (`main.py` saves `screenshots/<case>/baseline.png` + `result.png` at repo root) — not a scoring change itself, but logged because it immediately changed what we could verify | Text scores alone can't be trusted blindly — needed to actually SEE what a passing/failing result looks like, not just read a number | post_apocalyptic (first real use) | N/A (tooling) | **Real payoff on first use** — see finding below: caught a "pass" that was actually a near-black frame |
| 2026-11-23 | Re-ran `post_apocalyptic` again, no code changes, to check stability after the above | Checking whether the eerie_lab/post_apocalyptic flips were stable or just one lucky run | post_apocalyptic | PASS 6/10 → **FAIL 5/10** on the very next run, same code | **Regression / non-determinism confirmed** — same documented pass-boundary noise as `eerie_lab`/`noir` earlier in this doc, now also hitting `post_apocalyptic`. The screenshot showed WHY: a near-pure-black frame, not a deliberate "grim" look (see finding below) |
| 2026-11-23 | Checked `ModelSettings.reasoning` live (`dataclasses.fields`) and grepped the codebase | Wanted to know if either agent has any hidden deliberation happening before touching anything speculatively | n/a (investigation only) | Confirmed: defaults to `None`, zero occurrences in `agent.py`/`judge.py` — neither agent has ever configured it | **Decision, not a tuning change yet** — documented in `docs/agent-output-quality-techniques.md`; holding off on touching it until the full suite re-run shows a problem specifically needing more reasoning effort to fix |
| 2026-11-23 | Built `check_frame_visibility()` (pure PIL pixel check, no LLM) + wired into `main.py`'s attempt loop BEFORE the judge call — if a frame is near-black, skip the judge entirely and feed back directly, no model call spent on a frame with nothing to score | Per-field value clamps can't catch this: the near-black frame wasn't any single field out of Unity's own legal range, it was a COMPOUND effect of several individually-reasonable changes stacking. Calibrated thresholds (mean_brightness<10 or >90% near-black pixels) against the two real images on file: bad frame measured 4.1/255 + 98.8% near-black, normal frame measured 86.5/255 + 0.2% | post_apocalyptic (re-run didn't trigger it — agent passed clean on attempt 1 this time); branch logic verified directly against the real stored black-frame image | N/A (guardrail, not a scoring tune) | **Built and unit-verified, not yet caught live in a full run** — honest gap: haven't yet observed it fire during an actual attempt loop, only proven the detection function and the logging/feedback code path work correctly in isolation |
| 2026-11-23 | Fixed `screenshots/<case>/` silently overwriting baseline.png/result.png on every run (Eran caught it) — each run now gets its own `screenshots/<case>/<timestamp>/` folder, plus a `latest/` copy kept in sync for stable links (README's demo image). Timestamp is generated once and reused for both the folder name and the matching `mood_test_log.jsonl` entry, so any screenshot set can be matched back to its exact log row with no extra field | A plain overwrite was destroying history — couldn't see run N's screenshots once run N+1 happened for the same case. Considered a version-number counter instead, rejected: needs a disk scan to find "next", fragile if a folder's ever deleted | horror (smoke test) | N/A (infra, not a scoring tune) | **Verified live**: folder `20261123T092904Z` created, timestamp matched the log entry's `2026-11-23T09:29:04...` to the second, `latest/` populated correctly |
| 2026-11-23 | **Fix 1**: `get_scene_context()` now reads and reports each light's real `intensity`/`color`/`color_temperature`/`bounce_intensity` (via `get_light_properties()`), not just position/rotation. Previously the agent was blind to its own lights' actual values across attempts, position/rotation was ALL `get_scene_context()` exposed for any object, lights included. Required tagging `is_light` on every object in the C# transform-read script | Investigating `festive`'s stuck 5→5→4 regression from the previous session — hypothesis: agent couldn't see what it had already set on its own lights, so it could only reason about NEW lights, not adjust existing ones | festive, 3 fresh runs | Baseline (pre-fix, this session): 7 PASS / 6 PASS / 5 FAIL. Post-fix: 5 FAIL / 6 PASS / 5 FAIL | **No improvement in pass rate** (2/3 → 1/3), but a real, legitimate blind-spot fix kept regardless of this specific result — correct bookkeeping the agent should have had from the start |
| 2026-11-23 | **Fix 2**: `main.py`'s retry loop now accumulates a structured `attempt_history` (every prior attempt's own action summary + judge score + judge notes, oldest first) and feeds the full history into every subsequent attempt's prompt, with an explicit "your score did not improve, try a DIFFERENT lever" nudge when the last two scores are flat or declining. Replaces the old single-attempt `feedback` string (judge notes only, no scores, no history, overwritten every attempt) | Eran's hypothesis: the agent sees the latest judge note but has no visibility into its OWN prior values or whether its last change even helped, so it can't tell "pushing harder" from "trying something different" | festive, 3 fresh runs (on top of fix 1) | 4 FAIL / 6 PASS / 5 FAIL | **No improvement in pass rate** (still ~1/3), scores stayed in the same 3-7 band as every other run this session — kept anyway, it's objectively better-informed plumbing, just not festive's actual bottleneck |
| 2026-11-24 | **Fix 3**: agent itself now returns structured output (`LightingDecision`), not free text — `mood_breakdown` (strategy_archetype, genre, target_contrast enum, key_visual_choices) generated FIRST, then `reasoning`, then REQUIRED `changes_summary`. Same reasoning-first technique already proven on the judge, extended one step earlier (commit to an interpretation of the mood before reasoning about tool calls) | Directly fixes an observed bug: the agent sometimes returned a bare `"Done."` with zero description, found during fix 2's runs, making the history mechanism useless for that attempt. Eran's framing: give the agent its own structured output instead of fighting one unstructured prompt to cover every mood | festive, 3 fresh runs | 4 FAIL / 5 FAIL / 4 FAIL | **"Done." bug fixed for good** (required field can't be empty) and `mood_breakdown` populated correctly every attempt, but **festive's pass rate got WORSE, not better** (0/3, down from ~1/3) — see root cause below |
| 2026-11-24 | **Fix 4**: replaced the generic "pick ONE OR TWO primary levers, don't max everything" rule with 4 named `strategy_archetype` blocks (RESTRAINED / EXPANSIVE / SOFT_AMBIENT / NATURALISTIC), each a compact primary/secondary/avoid line (~35-45 words), covering lighting-strategy categories rather than a lookup table of literal mood strings (so unseen moods still classify into one of the 4 via the agent's own reasoning) | Root cause of fix 3's regression: the generic "1-2 levers" restraint rule is correct for RESTRAINED moods (horror/noir) but wrong for EXPANSIVE ones (festive) — festive's one strong baseline run (7 PASS) had used 4 simultaneous colored lights, which the generic restraint rule was actively discouraging. A literal per-mood dict was rejected (doesn't generalize to moods never seen); archetypes are the smallest set that generalizes | festive, 3 fresh runs | 4 FAIL / 4 FAIL / 6 PASS | **Recovered the multi-light color-chaos strategy** (agent correctly self-classified `expansive` and used 4-5 distinctly colored lights every attempt again) and pass rate returned to ~1/3, back in line with every other variant tried today |

### Result of the judge-recalibration + agent-push combo

| Case | Before | After | Verdict |
|---|---|---|---|
| eerie_lab | FAIL 5/10 | **PASS 6/10** | Progress |
| post_apocalyptic | FAIL 2/10 | **PASS 6/10** (first attempt) | Progress |
| festive | FAIL 3/10 | FAIL 4/10, but attempts got WORSE across retries (5→5→4) | Still stuck — see below |

Projected full-suite result: **9/10** (up from 7/10 earlier the same
session, 4/10 at session start).

### New finding: post_apocalyptic's "pass" on re-test was actually a near-black frame (screenshot pipeline caught this)

Built a before/after screenshot pipeline this session (`screenshots/<case>/baseline.png` + `result.png`, root of the repo per Eran's call — see README for the mechanism) specifically so results could be checked visually, not just trusted from a text score. First real payoff: re-ran `post_apocalyptic` again after the above changes and it actually **FAILED this time** (5/10, flipped from the 6/10 pass moments earlier — more of the same documented non-determinism). Looked at the actual `result.png`: it is **almost pure black, no scene content visible at all** — the agent had pushed exposure/vignette/fog so far that there's nothing left to read as any mood, "post-apocalyptic" or otherwise. The judge's own reasoning called this out correctly ("reads more as an exposure/visibility issue"), which is a good sign the recalibrated judge is still a strict, honest critic — it isn't just rubber-stamping dark images as "grim," it penalizes losing the image entirely.

**Real open question, not yet decided**: should there be a guardrail preventing the agent from driving exposure/vignette/fog to the point where the scene goes effectively black? This is the "push for committed/extreme values" instruction from the change above potentially working too well without a floor. Not built yet — flagging as a candidate, not assuming it's needed, consistent with this project's "don't guardrail what you haven't observed" rule — this is now observed once.

### `festive` — full investigation: structured output, archetypes, and why none of it moved the pass rate

**Context for this section**: previous session left `festive` stuck at
4/10 with retries getting WORSE (5→5→4). Two real, competing hypotheses
were open: a genuine content ceiling (lighting literally can't sell
"sparkle"), or the retry loop not actually adapting attempt-to-attempt.
This session tested 5 genuinely different interventions, 3 fresh runs
each (15 total), to find out.

**Fix 1 — light-property visibility.** `get_scene_context()` only
exposed position/rotation for every object, including lights — the
agent had zero visibility into its OWN lights' intensity/color/
color-temperature across attempts, only able to reason about brand-new
lights, never adjust existing ones with real information. Fixed by
tagging `is_light` on every object and reading real light properties via
`get_light_properties()`. **Result: 5 FAIL / 6 PASS / 5 FAIL (1/3).** A
real, legitimate blind-spot fix, kept regardless — but didn't move
festive's pass rate.

**Fix 2 — structured per-attempt history.** The retry loop only ever
carried the latest judge note forward; it had no memory of what IT had
tried before or whether that attempt even worked. Built `attempt_history`
(action + score + judge notes per attempt, fed into every subsequent
prompt) plus an explicit "your score plateaued, try a different lever"
nudge. **Result: 4 FAIL / 6 PASS / 5 FAIL (1/3).** Same band, no
improvement — but genuinely better-informed plumbing than what it
replaced, kept anyway.

**Fix 3 — structured output on the agent itself (Eran's framing: stop
writing one prompt that tries to cover every mood; give the agent its
own structured reasoning).** Added `LightingDecision` (`mood_breakdown`
→ `reasoning` → REQUIRED `changes_summary`), same reasoning-first
technique already proven on the judge (`MoodJudgement`), extended one
step earlier: commit to an interpretation of the mood (genre, contrast
enum, visual approach) before reasoning about tool calls, and a required
field for what actually changed. **This fixed a real, separate bug**:
the agent had twice returned a bare `"Done."` with zero description
during fix 2's testing — tool calls still happened, the agent just
stopped narrating, which made the fix-2 history useless for that
attempt. A required Pydantic field can't be empty, so that bug is gone
for good. **But festive's pass rate got WORSE: 4 FAIL / 5 FAIL / 4 FAIL
(0/3)**, down from the ~1/3 every other variant landed at.

**Root cause of the fix-3 regression, found by comparing transcripts**:
the generic "pick ONE OR TWO primary levers, don't max everything at
once" restraint rule (written to prevent the earlier near-black
guardrail failures) is the right rule for RESTRAINED moods like horror
and noir, but actively wrong for an EXPANSIVE mood like festive. The
one standout baseline run this whole investigation started from (7 PASS,
the best score festive ever got) used FOUR simultaneous distinctly
colored lights (green rim, blue fill, gold sparkle, pink accent) — fix 3's
restraint rule was quietly discouraging exactly that strategy, and the
structured-output runs converged on a conservative one-warm-key +
one-cyan-accent pattern every single attempt, barely varying.

**Fix 4 — strategy archetypes instead of one universal rule (or a
lookup table).** Eran's proposal, refined during discussion: don't try
to write one instruction set that serves every mood (impossible — what
works for horror actively hurts festive), and don't build a dict keyed
by literal mood strings either (only covers moods already enumerated,
never generalizes to something like "underwater alien ritual"). Instead,
classify any mood into one of 4 closed lighting-strategy archetypes —
RESTRAINED, EXPANSIVE, SOFT_AMBIENT, NATURALISTIC — each a compact
primary-lever/secondary-lever/avoid line (~35-45 words, ~150-180 words
total for all 4, small relative to the rest of the instructions). Added
`strategy_archetype` as the first field of `mood_breakdown` (classified
before genre/contrast, since it's the broadest call); the agent
self-selects from the static list, no runtime prompt-assembly or extra
API call needed. **Result: 4 FAIL / 4 FAIL / 6 PASS (1/3).** Confirmed
live: the agent correctly classified festive as `expansive` every
attempt and went back to using 4-5 distinctly colored lights per
attempt — the suppressed strategy was restored. Pass rate recovered to
the same ~1/3 band as every other non-regressed variant.

### Full tally — 15 runs, 5 variants, one conclusion

| Variant | Run 1 | Run 2 | Run 3 | Pass rate |
|---|---|---|---|---|
| Baseline (start of this session) | 7 PASS | 6 PASS | 5 FAIL | 2/3 |
| Fix 1: light visibility | 5 FAIL | 6 PASS | 5 FAIL | 1/3 |
| Fix 2: history + plateau nudge | 4 FAIL | 6 PASS | 5 FAIL | 1/3 |
| Fix 3: structured output (no archetypes) | 4 FAIL | 5 FAIL | 4 FAIL | 0/3 |
| Fix 4: structured output + archetypes | 4 FAIL | 4 FAIL | 6 PASS | 1/3 |

Every single score across all 15 runs landed between 2 and 7, median
sitting right under the pass threshold of 6. **No architecture change
tested this session — light-property visibility, structured
per-attempt history, structured agent output, or strategy archetypes —
shifted festive's underlying score distribution.** This is strong,
repeated evidence that festive on this scene is genuine judge-threshold
noise (same bucket as `eerie_lab`/`noir`/`post_apocalyptic` documented
earlier in this doc), not a fixable prompt or architecture problem. This
also closes the "Parked idea: diff-with-outcome tracking" section
earlier in this doc — it got built (fix 2) once evidence existed, and
the honest result across the whole investigation is that none of these
interventions move a threshold-noise case; multi-trial averaging at the
eval-harness level remains the real open lever for borderline cases,
not more prompt/architecture tuning on this one mood.

**What's being kept regardless of the null result on pass rate**, because
each is independently correct or valuable:
- Light-property visibility (fix 1) — a real, pre-existing blind spot.
- Structured per-attempt history (fix 2) — objectively better-informed
  plumbing than the single-string feedback it replaced.
- Structured agent output with `reasoning` → `changes_summary` (fix 3)
  — permanently fixes the `"Done."` empty-output bug.
- Strategy archetypes (fix 4) — the one piece that generalizes beyond
  festive specifically: any new, never-tested mood now gets classified
  into a lighting strategy instead of fighting one-size-fits-all
  instructions, which is the actual point of this round of work, not
  festive's score.

**Important scope note**: everything above is evidence about ONE mood
(festive) on ONE scene. The next real step is running the full 10-case
suite with all of today's changes in place, to see the aggregate effect
across every mood, not just the one that got the most attention this
session (see below).

## Full 10-case suite, run with all of today's changes in place (2026-11-24)

All of today's work (fixes 1-4: light-property visibility, structured
attempt history, structured agent output, strategy archetypes) targeted
`festive` specifically. Festive's own pass rate never moved. But that's
evidence about one mood on one scene — the real question is what these
changes did to the suite as a whole.

**Found and fixed a real harness bug first**: `eval.py`'s `print_summary()`
assumed every logged row has a `mood_match_score`, but a case whose final
attempt gets guardrail-rejected (near-black frame, judge never called)
logs a different shape (`guardrail_rejected` instead of a score) — see
`_log_guardrail_rejection()` in `main.py`. The full-suite run crashed with
a `KeyError` on exactly this case (`post_apocalyptic`, see below). Fixed
by branching the print on `entry.get("guardrail_rejected")`.

**Result:**

| Case | Score | Result |
|---|---|---|
| horror | 7/10 | PASS |
| eerie_lab | 7/10 | PASS |
| golden_hour | 7/10 | PASS |
| cozy_cafe | 7/10 | PASS |
| thriller | 7/10 | PASS |
| dreamlike | 6/10 | PASS |
| zen | 7/10 | PASS |
| noir | 6/10 | PASS |
| festive | 4/10 | FAIL |
| post_apocalyptic | — (guardrail-rejected) | FAIL |

**8/10 pass.** Up from 4/10 at the start of this session, and from 7/10
earlier the same session (before the judge recalibration + archetype
work). All 8 passes classified into a sensible archetype on attempt 1
or 2 (`restrained` for horror/eerie_lab/thriller/noir, `soft_ambient` for
cozy_cafe/zen/dreamlike, `naturalistic` for golden_hour) and several
passed on the FIRST attempt (golden_hour, zen, noir) — no retries needed,
a good sign the archetype + structured-output combination is giving the
agent a usable, confident starting point instead of hunting around.

**New finding: `post_apocalyptic` failed via the visibility guardrail
firing LIVE for the first time**, not a low judge score. Classified
correctly as `restrained` (desolate, grim, harsh — a real reading of the
mood), and `restrained`'s own archetype guidance explicitly calls for
"ONE dominant light direction + fog/vignette for shadow and isolation" —
which is accurate advice that, pushed with the "commit with real
conviction" instruction, drove attempt 3 to `mean_brightness=4.1/255,
pct_near_black=100%`, rejected before a judge call was spent. This is
exactly the "real open question, not yet decided" flagged earlier in
this doc after the first near-black observation on `post_apocalyptic` —
now observed a second time, and this time the guardrail's own feedback
message (visible in the attempt log) is what should have told the agent
to pull back, but attempt 3 was also the last attempt, so there was no
attempt 4 to show whether it would have recovered. Still an open
question whether a GUARDRAIL (code deciding a hard floor on
exposure/vignette/fog combined) is warranted versus trusting the
feedback loop to self-correct given one more attempt — not built,
flagging again rather than guessing.

**Honest summary for this whole session's festive investigation**: five
different architecture interventions (light visibility, attempt history,
structured output, strategy archetypes) were tested specifically to fix
one stuck mood, and none of them moved that one mood's pass rate — it's
threshold noise, confirmed by 15 runs. But the SAME changes, measured
against the full suite rather than the one case that prompted them,
produced a real, measurable net improvement (4/10 → 8/10 across the
session, with the only two remaining fails being `festive`, already
characterized as noise, and `post_apocalyptic`'s new guardrail-rejection
finding above). The lesson worth keeping: a single hard case can look
unfixable in isolation while the surrounding architecture work that
targeted it still pays off broadly elsewhere — judge this kind of change
by the suite, not just the case that motivated it.

## The 8/10 result didn't survive human eyes: the judge itself was too lenient (2026-11-24)

**Context.** After the 8/10 full-suite result above, Eran looked at the
actual `horror` and `thriller` result screenshots (the ones that scored
7/10 PASS) and flagged them as visually dull, flat, evenly-lit — not
dramatic or tense by his own human judgment at all. He raised a sharp
question before accepting any score at face value again: when the
automated judge passes something a human reviewer wouldn't, who is at
fault — the lighting agent, the judge, or the human for not trusting the
pipeline?

**What we actually did before answering that**: looked at the real
`horror` and `thriller` `latest/result.png` images directly (not the
text score) — same "inspect the artifact, don't trust the number"
principle this project has used since the screenshot pipeline caught
`post_apocalyptic`'s near-black "pass" earlier. Both images were a flat,
cold blue-gray wash: evenly lit, no visible shadow shape from an actual
light direction, nothing reading as dramatic or threatening. Eran's
visual read was correct, confirmed directly, not deferred to on
authority.

**Diagnosis**: this is a judge-calibration problem, not a model-capability
problem and not an agent-competence problem. The judge's own instructions
had been recalibrated earlier this session (step: "score atmosphere given
existing geometry, don't penalize missing props") specifically to stop
being too HARSH about missing content. That fix was correct for the
problem it targeted (eerie_lab/post_apocalyptic/festive's content-ceiling
false negatives), but it had a side effect never checked until now: the
judge became too LENIENT about atmosphere/drama itself, conflating "cold
color temperature + reduced brightness" with "genuinely dramatic
lighting." A dim room and a dramatically-lit room can both read as "dark
and moody" in a text description without the judge distinguishing them —
the judge needed a concrete visual bar for what drama actually requires
(shadow shape, a readable light source doing work), not just absence of
a content-ceiling penalty.

**Why we rejected "check ModelSettings (temperature/reasoning effort)"
as the fix**, which Eran raised as a candidate: those settings control
HOW consistently/deliberately a model reasons, not WHAT criteria it
reasons against. A model thinking harder with the same lenient judge
instructions still passes a dim flat room, because the instructions
themselves never specified the difference between "dim" and "dramatic."
No evidence pointed at the model itself being the bottleneck — the
judge's own instructions were the identified, concrete cause, so that's
what got changed, not model hyperparameters (consistent with this
project's standing rule: don't guess at infra/model-level fixes without
evidence pointing there).

**The fix**: added a "CRITICAL CALIBRATION" clause to `judge.py`'s
instructions — explicit that a cold color temperature alone is not
drama, real drama requires visible shadow shape from an actual light
direction (not a uniform dark wash) plus enough brightness to still read
the scene, and that a frame reading as "the lights were turned down"
rather than "deliberately and dramatically lit" must score LOW for any
mood calling for tension/horror/drama regardless of color temperature.
Also told the judge to score its own `contrast_level` field honestly and
treat a self-reported low/medium contrast as incompatible with a 6+
score on a high-drama mood.

**Result, re-testing `horror` only**: the SAME agent code that produced
the visually-dull 7/10 PASS screenshot earlier now scored attempt 1 at
**3/10**, attempt 2 at **5/10**, and attempt 3 got rejected by the
visibility guardrail (pushed to `mean_brightness=1.8/255`, fully black)
before a judge call was even spent — **horror now FAILS entirely** under
the tightened judge. This directly confirms Eran's visual read: the old
7 PASS was real miscalibration, not genuine quality, the SAME underlying
agent output that used to pass now correctly fails.

**New problem this exposed, not yet fixed**: the agent's retry logic has
no equivalent of the "dim ≠ dramatic" distinction we just gave the
judge. Told its score plateaued/stayed low, and following its own
`restrained` archetype's "commit hard" instruction, the agent's only
available move was to keep pushing exposure/vignette/fog further DOWN
each attempt — walking straight into the same near-black guardrail
rejection already seen on `post_apocalyptic`. A stricter, more honest
judge just makes an agent that doesn't know the real distinction
overcorrect into blackness instead of actually getting more dramatic.
This is the next thing to fix — teaching the AGENT (not just the judge)
that real drama needs a directional light source and visible shadow
shape, not just reduced overall brightness — tracked as a follow-up, not
yet implemented as of this doc entry.

**Who was at fault, stated plainly for the record**: the judge's
calibration, not the lighting agent (which followed its instructions
faithfully and got no useful signal telling it darker ≠ better) and not
Eran (whose visual read was the correct one all along). This is the
second time this exact category of bug has hit this project — a judge
whose instructions don't match the real human bar for its target concept
— first for "missing content," now for "drama vs. dimness." Worth
treating as a pattern: whenever a judge's pass rate feels wrong by eye,
suspect the judge's own instructions before suspecting the agent or the
model.

## Rebuilding RESTRAINED from real reference images — found a real tooling gap, not an instructions gap (2026-11-24)

**Context.** Eran provided 11 real game-lighting reference images (one
per mood from `light_mood_setup/`, covering Alien Isolation-style horror,
a warm-lamp horror variant, LA Noire-style noir, an Alan Wake 2
streetlamp thriller shot, a Control-style eerie lab corridor, a hazy
post-apocalyptic ruin, plus golden hour/zen/dreamlike/festive/cozy café),
a technical-artist palette/contrast reference table, and links to
professional lighting breakdowns. Decided live: no RAG/retrieval system
for this material — it's a one-time authoring input to sharpen 4 static
archetype blocks, not a corpus the agent needs to query live (no
evidence of the scale that would justify that infra).

**What the images actually showed, examined directly, not inferred from
adjectives:** horror, horror2, noir, thriller, and eerie_lab all share
ONE real technique — a single dominant light source producing EXTREME
falloff (a genuinely bright pool/cone where the light hits, the rest of
the frame real near-black by contrast), hard-edged shadow shapes, very
high contrast. `post_apocalyptic` breaks that pattern entirely: diffuse,
overcast, hazy daylight, NO single key light, medium contrast,
desaturated — confirmed independently by the palette table ("medium
contrast, dusty, desaturated" vs horror/noir's "very high"). This meant
`post_apocalyptic` had been wrongly lumped into the same `RESTRAINED`
technique as horror/noir, likely the real reason it kept drifting
toward the near-black guardrail — it was being pushed toward a contrast
target that was never right for it.

**Rebuilt `RESTRAINED`** into two named sub-techniques within the same
archetype enum value (no schema change, just sharper instructions):
THREAT/DRAMATIC (horror/noir/thriller/eerie_lab — single key light,
extreme falloff, very high contrast) vs DESOLATE/ATMOSPHERIC
(post-apocalyptic/ruins — diffuse overcast haze, no key light, medium
contrast, explicitly told NOT to push toward black).

**Re-tested horror/noir/thriller/post_apocalyptic: all 4 still FAILED**,
and — the decisive signal — the judge's complaint was WORD FOR WORD
identical to before the rewrite ("no directional shadows, no strong key
light"). Per this project's own `llm-output-diagnosis` method: unambiguous,
specific instructions that still don't change behavior at all point past
"instructions" to the next layer, tools/architecture.

**Audited `tools.py`/`unity_bridge.py` directly and found a real,
concrete capability gap**: `set_light_properties` never exposed `range`
(how far a light reaches) or `spot_angle` (cone width) at all — and,
confirmed LIVE by creating a real test light and reading its raw fields,
**every agent-created light defaults to `m_Shadows.m_Type: "No Shadows"`**.
No amount of instruction wording could ever have produced a visible
shadow on an agent-created light, the capability was off at the
component level the entire time. The scene's 2 original lights DO have
shadows enabled, but default to `range=10` (per Unity's component
default), which floods this whole small room evenly — explaining why
even manipulating the existing lights never created a real pool-vs-dark
falloff.

**Fix implemented:**
- Added `range`, `spot_angle`, `shadow_type` to `LightProperties`,
  `get_light_properties`, and `set_light_properties` (both the raw
  bridge function and the agent-facing tool, with guardrails: range > 0,
  spot_angle in Unity's valid [1, 179], shadow_type one of
  none/hard/soft).
- `create_light` now explicitly sets `shadow_type='soft'` at creation
  instead of silently inheriting Unity's "No Shadows" default.
- `get_scene_context()` now reports range/spot_angle/shadow_type per
  light, same fix pattern as the earlier intensity/color blind spot.
- `RESTRAINED`'s THREAT/DRAMATIC instructions now explicitly tell the
  agent to size a key light's range as a small fraction of
  `get_scene_bounds()`'s diagonal and confirm shadow_type is hard/soft,
  not just "make one light dominant" in the abstract.

**Re-tested `horror`: confirmed the fix is real** — the agent now
genuinely uses the new levers (asymmetric range per light, e.g. 2.2 vs
2.8, then 3.2 vs 4.0 across attempts), a real, verifiable behavior
change, not just new vocabulary in its reasoning. **But the visual
result still read flat/dim** (confirmed by direct image inspection, not
score alone) and the score stayed FAIL 5/10.

**New suspected cause for next session, not yet fixed**: the agent
pairs "make one light dominant" with a GLOBAL exposure/contrast cut via
`set_color_adjustments`, applied on top of all individual lights'
output. This likely flattens whatever local brightness differential the
lights create, since global grading compresses the whole frame's
exposure uniformly after individual lights render. The agent is also
not boosting its "dominant" light's intensity meaningfully above the
room's original baseline (ended up around 1.15 vs. the original scene's
~2.17) — it's darkening both the dominant and secondary lights, just by
different amounts, rather than making one genuinely bright against a
genuinely dark rest-of-frame. This is a different kind of gap than
tools or instructions — closer to "the agent reasons about each lever
category (lights vs. global grading) independently, without weighing
how they combine," which `get_scene_context()`'s existing "these effects
STACK" warning hints at but doesn't specifically connect to this
single-key-light case. Tracked as the explicit next discussion, not
guessed at further in this pass.

## Current gap assessment — instructions, tools, configuration, or architecture? (2026-11-24)

Summary for quick reference, using this project's own `llm-output-diagnosis`
categories, current as of this session:

| Layer | Verdict | Evidence |
|---|---|---|
| **Architecture** (structured output: `mood_breakdown` → `reasoning` → `changes_summary`) | Solid, no known gap | Every attempt produces specific, concrete, non-generic content in all 3 fields across dozens of runs — the `"Done."` bug this fixed never recurred |
| **Instructions** (judge calibration) | Fixed, confirmed | Decisive proof: changed ONLY wording, same model/settings, behavior flipped completely (horror 7 PASS → 3/5/guardrail-FAIL) |
| **Instructions** (agent archetype text) | Validated as correct, was blocked by a lower layer | The RESTRAINED rewrite described the right technique accurately (confirmed against real references), but changed nothing until the tools layer below it was fixed — now that tools exist, the agent correctly adopts the new instructed behavior (real asymmetric range usage) |
| **Tools/capability surface** | WAS the real gap, now fixed | Confirmed live: `range`/`spot_angle`/`shadow_type` were never exposed; every agent-created light defaulted to no shadows at all, a hard capability block no wording could work around |
| **Configuration** (`ModelSettings`: temperature, reasoning effort) | No identified gap, correctly untouched | No test has isolated a model-capability failure from everything above; touching this now would be a guess, not evidence-driven |
| **New, not yet categorized cleanly** | Open, next session | Global post-processing (exposure/contrast/vignette/fog) appears to cancel out local per-light brightness differentials the agent creates — not a tools gap (both levers exist and work individually) and not quite an instructions gap (the "effects stack" warning already exists in `get_scene_context()`), more a reasoning-about-combined-effects gap specific to the single-key-light technique |

**The honest overall pattern this session surfaced**: every real
improvement came from checking the cheapest, most falsifiable layer
first and only moving down when the evidence demanded it (architecture
→ instructions → tools), never guessing at model/config fixes without a
positive test pointing there. That discipline is what turned "the judge
seems wrong" into two concrete, verified fixes (judge calibration, then
a real tooling gap) instead of two rounds of blind prompt tweaking.

## Closing the gap-assessment's open item: a deterministic contrast guardrail, a cost-aware MAX_ATTEMPTS experiment, and loosened instructions (2026-11-24)

**Context.** The open item from the gap assessment above was: global
post-processing seemed to cancel out whatever local brightness
differential the agent's lights created, leaving `horror` stuck at a
flat/dim result even after the tooling fix (range/shadow_type). Decided
live with Eran: a deterministic, measurable check is more enforcing and
more honest than trying to out-word the problem in prose a third time.

**Technique 1 — calibrate the metric against real data before picking a
threshold, same discipline as the existing near-black guardrail.**
Computed `p90 - p10` luminance spread (a measure of real brightness
contrast across a frame, distinct from mean brightness) on both the
real reference images Eran provided and this project's own flat/failed
results:

| Image | p90−p10 spread |
|---|---|
| Real horror/noir/thriller/eerie-lab references | 45–79 |
| This project's own flat agent results | 7–20 |
| This scene's untouched baseline room (no edits at all) | 59 |

That baseline-room number was the sharpest finding: **the agent's own
edits were making the room flatter than doing nothing.** Concrete,
measured proof the approach was actively fighting the mood, not just
falling short.

**Technique 2 — a second guardrail for the OPPOSITE failure mode,
gated on the agent's own structured output.** Built `check_frame_contrast()`
(same shape as the existing `check_frame_visibility()`, pure pixel
histogram math, no LLM, no numpy dependency — this project's venv
doesn't have numpy, rewrote with `Image.histogram()` + manual
percentile-from-cumulative-count, verified it reproduces the same
numbers as the numpy prototype). Set `CONTRAST_SPREAD_FLOOR = 35`
(comfortably below every real reference, comfortably above the agent's
own flat outputs). Gated it on `decision.mood_breakdown.target_contrast
== "high"` — a low-contrast mood (soft_ambient, etc.) is SUPPOSED to be
flat and must never be rejected by this. Wired into `main.py`'s attempt
loop right after the existing visibility guardrail, same pattern: skip
the judge call entirely on a flat frame, feed back the real numbers
(p10/p90/spread/floor) plus a concrete hypothesis (no light is
genuinely dominant, OR global grading is flattening the differential).
Generalized `_log_guardrail_rejection()` to accept any guardrail
name + detail dict, not just visibility-specific fields.

**Technique 3 — a bounded, reversible diagnostic experiment instead of
a permanent cost increase.** Eran's concern: bumping `MAX_ATTEMPTS`
permanently means more (expensive) lighting-agent calls on every future
run, even when the judge is never reached. Made `MAX_ATTEMPTS`
env-overridable (`MAX_ATTEMPTS_DIAGNOSTIC_OVERRIDE`, default stays 3)
so the experiment could run once, answer the question, and leave zero
permanent cost behind. Ran `horror` with 7 attempts:

| Attempt | Spread | Outcome |
|---|---|---|
| 1 | 16 | Guardrail-rejected (flat) |
| 2 | 31 | Guardrail-rejected (flat) |
| 3 | ≥35 | Reached judge, scored 5/10 |
| 4 | 30 | Guardrail-rejected (flat) |
| 5 | ≥35 | Reached judge, scored 5/10 |
| 6 | — | Guardrail-rejected (near-black, overcorrected) |
| 7 | ≥35 | Reached judge, scored 5/10 |

**Conclusive, not just suggestive**: 3 separate attempts crossed the
35 floor and every single one scored exactly 5/10, with the judge's
complaint identical each time ("subtle, not striking"). More attempts
bought more *chances* to clear the pixel floor, it never bought better
*quality* — proof `MAX_ATTEMPTS` was never the real bottleneck.
Reverted to the default of 3 immediately after, no permanent cost
change.

**Technique 4 — test whether the instructions themselves were the
actual constraint, not the thing enforcing quality.** Eran's hypothesis:
the heavily-prescriptive `RESTRAINED` rewrite (explicit range values,
shadow_type mandates, "avoid" lists, "be conservative with global
grading") may have been constraining the model into a narrow, mechanical
solution instead of freeing it to solve the creative problem well.
Rewrote `RESTRAINED` (and, for consistency, `EXPANSIVE`/`SOFT_AMBIENT`/
`NATURALISTIC`) down to a short genre/contrast-target compass with an
explicit "CREATIVE FREEDOM" framing: the two deterministic guardrails
exist only to catch extreme failures on either side, not to prescribe a
style, clearing them is not the same as succeeding at the mood, push as
boldly as judged necessary. Also softened the `TOOLS` section from
"CRITICAL, often missed" imperative framing back to neutral capability
description.

**Result, mixed, reported honestly, not cherry-picked:**

| Case | Outcome | Visual check |
|---|---|---|
| horror | FAIL 4/10 | **Visibly improved** — real soft-glow pool on the table, genuine darker edges, atmospheric depth, clearly more deliberate than the old flat gray result |
| noir | FAIL (contrast guardrail) | Still flat, never reached the judge |
| thriller | FAIL 4/10 | Still evenly lit, no real falloff, same complaint as before |
| post_apocalyptic | FAIL 4/10 | Still flat/uniform, no real haze/depth |

1 of 4 improved visually (confirmed by direct image inspection, not
score), the other 3 landed in roughly the same place as every prior
variant tried today. **Honest conclusion**: looser instructions didn't
regress anything and genuinely helped in one case, but this isn't a
clean universal fix either — these 4 specific moods, on this specific
small room with its existing fixture layout, keep landing in the same
noisy, borderline zone regardless of which lever gets adjusted (judge
wording, tooling, prescriptive vs. loose instructions). This now reads
less like "one more fix will crack it" and more like a genuine content/
scale ceiling for RESTRAINED moods on THIS scene — the same shape of
conclusion this project already reached for `festive` earlier in the
session, just arrived at through a completely different investigation
path.

**What's being kept, all net-positive regardless of the mixed score
result:**
- The contrast guardrail (real, calibrated, catches a genuine failure
  mode, saves judge-call cost on flat frames).
- `MAX_ATTEMPTS` staying at 3 (now backed by direct evidence it isn't
  the bottleneck, not just an assumption).
- The loosened instructions (simpler, no regressions, one real
  improvement, removes prose that was quietly fighting the model's own
  judgment).

## Rejecting "swap the scene" and finding the real remaining bottleneck: ambient light, a broken contrast metric, and a spatial-reasoning gap (2026-11-24, continued)

**Context.** Proposed 2 ways out of the RESTRAINED ceiling above: a
genuinely different test scene, or averaging multiple trials. Eran
rejected both, explicitly and for a real product reason, not
stubbornness: "what if a user will work with crappy scene like this? we
want to be able to handle any kind of scene that will get thrown at
us... lets keep working on lighting only, and work on the current
scenes and make sure that they constantly pass." Picking a nicer scene
to make the numbers look better was never a fix, it would just hide the
same gap from a future real user. Directed instead: review the
architecture itself for what's actually still missing.

**Technique 1 — test hypotheses directly against the live Editor, not
in prose.** Two live experiments, both run before touching any code:
- Disabled Bloom entirely mid-scene, re-measured contrast: 35 -> 34, no
  meaningful change. Hypothesis (bloom softening edges) ruled out,
  concretely, not assumed.
- Manually tuned one light to an extreme (intensity 20, tight range):
  measured spread=66 — looked like proof the room could do it. Visual
  inspection immediately showed it was a blown-out, fully-clipped solid
  color, not real drama — a false positive caught by looking at the
  actual pixels before trusting the number, same discipline as every
  other check this session. Retried with sane values (intensity 6):
  spread=68, genuinely visible this time — a cheerful, evenly-lit,
  bright room, also not real drama, but the room's physical geometry
  demonstrably CAN reach real-reference contrast levels. Ruled out "the
  room/scene is the ceiling" as cleanly as the bloom hypothesis.

**Technique 2 — a metric bug hiding in plain sight, found by looking at
a result the number said was fine.** That "bright room" test is the
key finding of this entire sub-investigation: it measured spread=68
(numerically in real-reference range) while being visually the
opposite of dramatic. Root cause: `CONTRAST_SPREAD_FLOOR` only checked
the GAP between p10 and p90, never that the dark side was actually
dark. A normal, evenly-lit room with ordinary material/geometry
variance can produce a wide gap on its own, with p10=52 (not remotely
near-black). Recomputed p10/p90 on all 11 real reference images to
calibrate correctly: every real THREAT/DRAMATIC reference (horror,
horror2, Noir, Thriller, Eerie Lab) measured p10 in 1-7; the
false-positive bright room measured p10=52 — wide, clean gap, same
calibration method used for the spread floor itself. Added
`P10_CEILING = 30.0`; `has_real_contrast` now requires BOTH conditions.
This explains the whole session's earlier pattern for free: every
attempt that crossed the old floor-only check still scored ~5/10 from
the judge, because crossing it only proved "not uniformly flat," never
proved real directional drama.

**Technique 3 — a logging blind spot, fixed before diagnosing further.**
The per-attempt debug print only ran AFTER a guardrail-rejected attempt
had already been skipped, so a flat/rejected attempt's actual light
values were invisible in every log this whole session — impossible to
answer "did it even try to dim the other lights" from the logs alone.
Moved the print (archetype, genre, target_contrast, changes_summary,
and every light's live intensity/range/shadow_type/color) to run
immediately after the agent's decision, before any guardrail can skip
the rest of the loop.

**Technique 4 — the real missing lever: ambient light, never read,
never exposed, structural, not a style/prompt problem.** Eran asked
directly: why would two existing lights + a dominant-key strategy still
fail to produce real contrast? Checked `RenderSettings.ambientIntensity`
live: sitting at Unity's default of 1.0 all session, a uniform fill
applied to the ENTIRE scene regardless of any individual light's
position or range — never read, never exposed as a tool, never
mentioned anywhere. Tested directly: dropped it to 0.05 on the agent's
own last (still-failing) light config, no other changes: p10 dropped
16 -> 7, a real, measurable, structural effect. Built `get_ambient()`/
`set_ambient()` (RenderSettings, not a Volume override — simpler
static property, no profile involved), wired into `capture_scene_
baseline()`/`restore_scene_baseline()` so it resets cleanly between
test runs (deleted and let the 2 cached baseline snapshots recapture
fresh rather than hand-editing stale JSON — same principle the system
already uses: never fabricate baseline data, only ever capture it
live). Also fixed a related, previously-unnoticed gap found while in
this code: `restore_scene_baseline()` never restored a light's
`shadow_type`, only intensity/color/range — the capture script didn't
even record it. Fixed both ends (`shadow_type_int` now captured and
restored as an int-cast enum, matching the pattern already used
everywhere else in this file for Unity enum writes).

**Result after exposing ambient + reinforcing "zero the other light,
not just dim it" in the instructions:** real, visible behavioral
change, the first of its kind all session — attempt 1 correctly
dropped ambient to 0.08 and the secondary light to 0.03 (overshot into
full black, caught by the visibility guardrail); attempt 2 corrected to
ambient=0.14, secondary=0.06, landed p10=6 — genuinely dark, comfortably
under the new ceiling, the dark-zone problem that defined this entire
investigation is gone. Still failed (spread=29, short of 35) — but for
a new, different, precisely diagnosed reason this time.

**Technique 5 — instrument the real tool calls instead of guessing from
the agent's own prose.** Eran asked the sharp question directly: does
the agent actually understand key-light theory, or just the vocabulary
for it? Monkeypatched `tools._set_light_properties` to print every real
call's arguments during one full run, independent of what the model's
own `changes_summary` claimed. Result, a precise, two-part answer:
- It genuinely calls the tool and genuinely escalates intensity each
  attempt (0.18 -> 0.32 -> 0.85) — this is NOT a stated-intent-vs-
  no-op gap, it really is trying.
- But it's escalating within a self-invented, wrong order of magnitude
  — this room's own original lights sit around intensity 5-6; tripling
  0.18 twice only reaches 0.85, nowhere near genuinely bright.
- Separately, confirmed by grepping live object positions:
  `set_object_transform`/`aim_light_at` were called ZERO times this
  entire session on either existing light — both tools already exist
  and already work, the agent simply never considers repositioning or
  re-aiming a light as an available lever, only ever tunes numeric
  properties on whatever position the scene's original artist left it.

**Key decision, explicitly reasoned through with Eran before building
anything further**: rejected both "explain key/fill/back/rim theory"
(the model already uses this vocabulary correctly in its own reasoning,
the concept isn't missing) and "build a new enforcing placement tool"
(the tools already exist and already work, they're simply unused) as
the fix. Also rejected anchoring a fixed numeric intensity reference
(e.g. "~5-6") directly into the instructions — Eran caught this live:
"lets assume we get a scene with no lights... the agent needs to build
his own baseline... we cant rely on existing baseline from existing
lights" — a hardcoded number specific to this one room would not
generalize to a scene with zero pre-existing lights, which the product
must handle. Also rejected forcing tool use via `ModelSettings.
tool_choice="required"` for the same reason as always this session:
it only guarantees SOME tool call before the model can finish, it
can't force a SPECIFIC tool or force real geometric reasoning behind
the call — an opaque config knob instead of a legible, debuggable
instruction, inconsistent with everything that has actually worked
this project.

**Next direction, Eran's framing, not yet built**: before redesigning
the attempt loop into explicit phases (a dedicated "establish spatial
baseline from scene geometry" first pass, followed by judge-feedback-
driven refinement passes), test the prerequisite question in total
isolation first — does the model have genuine spatial reasoning
capability at all, given the scene's bounding box, object positions,
and camera image? Agreed: build this as a small, separate, fully
deterministic diagnostic (geometric pass/fail — did the resulting
light's position/rotation actually hit the intended target, at what
distance/angle — reusing the raycast-hit-target logic `aim_light_at`'s
own guardrail already has, no judge LLM needed at all), kept separate
from the mood eval suite's pass/fail tally since it tests an entirely
different capability and shouldn't blur two unrelated numbers together.
Not yet implemented — next session's starting point.

## Spatial eval found a foundational bug before any model-capability answer was valid (2026-11-24, continued)

Built the isolated spatial test (`spatial_eval.py`, a dedicated minimal
agent, no mood/archetype content, 4 target objects, fully deterministic
geometric scoring). First run: 1/4 deterministic pass, 0/4 reasoning-
consistent — looked like a capability failure, but the actual light
positions were bizarre (e.g. requested near a table, landed 12+ units
away in a totally different part of the room), while the model's own
stated reasoning was consistently sensible. That mismatch pointed at
the tool, not the model.

Root cause, confirmed live: `set_object_transform()` called the Unity
CLI's `gameobject set_transform --position/--rotation`, which writes
LOCAL position/rotation (relative to the object's parent); every other
read in this project (`list_scene_transforms`, `get_scene_bounds`)
reports WORLD position (parent already baked in). Both original scene
lights had no parent all session, so this was invisible until this
test — the first real attempt at setting a position on an existing
object — ran against a live Editor session where something (an
unresolved secondary mystery, not file corruption since nothing is
auto-saved) had since given both lights a parent. Full conceptual
writeup (world vs. local, the Transform/parent composition, why it's
not simple addition in general, the Unity built-in fix) is in
`docs/unity-lighting-rendering-concepts.md`.

**Fix**: `set_object_transform()` no longer uses the CLI command at
all — writes its own `script eval` assigning directly to
`t.position`/`t.eulerAngles` (Unity's world-space setters), correct
regardless of any parent. Verified live: requested (1,2,3), got exactly
(1,2,3) in world space.

**Not yet done**: reload the scene fresh in the Editor (clear the
unexplained accumulated parenting/drift from hours of unsaved live
testing) and re-run the 4-case spatial eval on the fixed, clean
pipeline — today's 1/4 result is not a trustworthy read on the model's
actual spatial capability, it's mostly measuring this bug. That re-run
is the real next step before drawing any conclusion.
