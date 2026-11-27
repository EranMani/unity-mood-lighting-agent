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

## Spatial eval, final clean result: the model genuinely has spatial reasoning (2026-11-24, continued)

**One guardrail, not two** (Eran's call): `aim_light_at` already knows its intended target, so its shared guardrail path (`_apply_transform_with_guardrail`) now takes a `required_hit_name` — hitting the WRONG object is treated exactly the same as hitting empty space, both rejected. Previously it only checked "hits ANYTHING," which is why an earlier run aimed at the bed instead of the requested arcade machine and was silently approved (hit something, nobody checked it was the right something). Plain `set_object_transform` calls with no implied target keep the old "hits something" check, there's nothing stricter to compare against without a stated target.

**Finally fixed the position/rotation baseline gap**, flagged earlier this session but never patched: `capture_scene_baseline`/`restore_scene_baseline` now capture and restore each light's world position/rotation too (previously only intensity/color/range/shadow_type), using the now-fixed world-space `set_object_transform`. Old cached baseline is safely skipped (position restore only runs `if "pos_x" in light`) rather than guessing (0,0,0) and risking teleporting a light into geometry.

**Redesigned the eval to be more dynamic** (Eran's call): the agent now self-selects a random target object from the scene's own list each run, instead of 4 harness-assigned names — broader coverage over time, and it forces a genuine differentiation check (is it actually varying its choice, not defaulting to the same "obvious" object). Added a `SpatialOutcome` enum (SUCCESS / MOVED_BUT_NOT_AIMED / GAVE_UP_NO_CHANGE) to the structured output, and a second, structural honesty check (`stated_outcome_matches_reality`) comparing the enum against the real geometry, independent of the free-text reasoning-consistency check.

**Hit one real bug while wiring the restore fix**: a plain (non-f) Python string literal `'break; }} }}'` was being interpreted literally (4 real closing braces — `{{`/`}}` escaping only applies inside f-strings), breaking the generated C# script's syntax. Fixed to `'break; } }'` (2 real braces, correct).

**Final clean run, 4 self-selected targets**: 3/4 full deterministic pass (correct target hit via raycast, sane distance, in bounds), 3/4 reasoning-consistent, 3/4 honest. The one failure was the model hallucinating an invalid light instance_id — it couldn't act, and it HONESTLY reported `gave_up_no_change` rather than fabricating success, exactly the behavior the honesty check exists to verify. 2 distinct targets picked across 4 runs (repeated one), genuine variety, not the "same lazy spot" failure mode, though not maximally diverse either.

**Conclusion**: the model genuinely has real spatial reasoning capability — correct position judgment, correct aiming, adaptive retry on guardrail rejection (seen earlier this session: 3 candidate positions tried before landing on one that worked), and now honest self-reporting on failure. The entire earlier "the agent can't execute spatial placement" read on this session's data was caused by this project's own infrastructure bugs (world/local position mismatch, missing baseline restore fields, a too-loose guardrail), not a model capability gap. Next: Eran has architecture questions about how to apply this back to the main mood-lighting attempt loop — to be continued in the next session segment.

## Spatial agent built as a separate, cached, mood-blind "ground base" (2026-11-24, continued)

**Architecture decision, Eran's call**: spatial reasoning (now proven
real) and mood/lighting-technique reasoning stay as two SEPARATE
agents, not folded into one. Pushed back on one detail before building:
should the spatial agent know the mood too? No — kept it strictly
MOOD-BLIND, pure geometry only. Two reasons: (1) a scene's geometry
doesn't change between moods or retry attempts, so a mood-blind
breakdown is cacheable and reusable across EVERY mood/attempt for that
scene, computed once, ever; a mood-aware version would need a fresh
call per mood, losing that; (2) avoids two agents independently
guessing at mood strategy with no guarantee they agree — archetype/
contrast-target judgment stays exclusively the lighting agent's job.

**Built `spatial_agent.py`**: a tool-less (pure analysis, never moves
anything), cheap single-call agent producing a `SpatialBreakdown`
(reasoning + 3-6 `SpatialAnchor`s, each with geometric-only traits —
compact/isolated vs large/central vs near-a-wall — and a concrete
suggested world-space position). Cached per scene (same safe-filename
convention as `unity_bridge.py`'s scene_baselines, under
`data/spatial_breakdowns/`) via `ensure_spatial_breakdown()`
(create-if-missing, ASYNC since a cache miss calls the LLM) and
`load_cached_spatial_breakdown()` (pure sync disk read, safe to call
from inside `agent.py`'s sync `get_scene_context()` — the async create
step always runs once near the top of `main.py`'s `run()`, before any
attempt, so by the time `get_scene_context()` reads it the cache is
guaranteed to already exist).

**Hit one real schema bug**: `tuple[float, float, float]` as a
structured-output field type failed OpenAI's strict schema validation
("array schema missing items"). Fixed by splitting into 3 separate
`_x`/`_y`/`_z` float fields, matching this project's own established
convention everywhere else (LightProperties' `color_r`/`color_g`/
`color_b`, not a tuple) — should have followed it the first time.

**Wired into `get_scene_context()`** as an extra appended section
(Eran's call), advisory, not a constraint — the lighting agent keeps
its full existing toolset and creative freedom to deviate from the
suggestions.

**Result on the 2 struggling cases, by Eran's own stated test
criteria** (run them, see if score improves, keep it if yes, trivially
revert if no): **0/2 passed, no clear score win yet.**
- `horror`: FAIL (4/10). Cache hit confirmed working on a second run
  (no wasted re-computation). Same root problem as before: key light
  intensity stayed timid (0.55 max), never created real brightness.
- `thriller`: FAIL (contrast guardrail, spread capped at 19-25 vs the
  35 floor). Genuinely different, better-grounded reasoning this time
  though — attempt 1 explicitly referenced the spatial anchor ("created
  a new hard-edged spot key near the chair/table area"), and intensity
  escalated the right direction across attempts (1.8 -> 3.2), just not
  far enough.

**Honest conclusion**: the spatial ground-base is working exactly as
designed architecturally (cached, reused, genuinely anchor-referenced
reasoning now shows up in the model's own text) — it fixed the
POSITION half of the problem. It was never going to fix the OTHER,
separately-diagnosed problem from earlier this session (key-light
intensity calibrated to a self-invented, too-timid order of magnitude,
unrelated to WHERE the light sits). Keeping it (cheap, sound, no
regression, real qualitative improvement) — intensity calibration is
still the open item, to be tackled next, separately.

## Brightness-anchor added, tested, same honest pattern (2026-11-24/25, continued)

**Built the deterministic brightness anchor, per the spatial/lighting
separation-of-concerns agreement**: Eran correctly flagged that having
the spatial agent reason about light intensity would violate its own
scope (geometry/placement only, not light values). Redesigned as pure
deterministic code instead — `measure_frame_brightness()` (mean + p90
luminance, no LLM, shares `_frame_percentiles()` with
`check_frame_contrast`), captured ONCE at `capture_scene_baseline()`
time and stored in the baseline JSON, read back via
`get_baseline_brightness()`. Reported in `get_scene_context()` as a
calibration anchor, and referenced explicitly in the archetype
instructions: a dramatic key light's intensity should be judged by
whether the ATTEMPT's own rendered p90 ends up measurably above the
scene's baseline p90, not by an arbitrary invented number. Generalizes
to a scene with zero existing lights (baseline would simply measure
near-black, the instruction still makes sense).

**Caught and fixed a contamination bug while testing**: manually
recapturing the baseline (bypassing `main.py`'s normal
`cleanup_agent_lights()` -> `capture_scene_baseline()` order) briefly
captured 3 lights instead of 2 — a stray agent-created light from an
earlier test run was still in the scene. Cleaned up and recaptured
correctly before trusting the numbers (`baseline: mean=13.3, p90=25.0`
for this scene).

**Result on the same 2 struggling cases**: still 0/2, but with real,
specific partial signal this time — `horror` attempt 2 pushed its own
p90 to exactly 35, genuinely above the 25 baseline, the anchor concept
visibly working as designed for the first time. Still 4 short of the
35 contrast-spread floor. Attempt 3's judge complaint ("a nearly black,
faceted polygon filling most of the frame") reads like a DIFFERENT
problem than intensity at all — possibly camera framing/composition,
not yet investigated. `thriller` showed no clear improvement and
swung to the opposite failure mode (near-black) rather than converging.

**Eran's response, verbatim, governs what comes next**: "i dont accept
this as honest current state of the project. we are not done until the
judge will pass every kind of mood in our eval suite... lets dig deeper
and understand the gaps we have." Explicitly NOT treating today's mixed
results as a stopping point — directed a deeper inspection of exactly
where the lighting agent's retry loop is failing: is it position,
configuration (intensity/color/etc.), or a failure to translate the
judge's own feedback text into concrete technical parameter changes
attempt-to-attempt? That inspection is the next session segment's
starting point, not yet done.

## Full-trace diagnostic finds the real gap: a narrow lever repertoire, not position/execution (2026-11-25)

Ran a 5-attempt diagnostic on `horror` with the full prompt text traced
every attempt (confirmed the judge-feedback delivery mechanism itself
works correctly — full reasoning text present verbatim, the "try a
DIFFERENT lever" nudge fires on schedule). Despite that, across all 5
attempts the agent **never once touched position or rotation** — every
attempt was a variation of "tune this light's intensity/color/global
grading," even when explicitly told the current approach wasn't
working. It wasn't failing to read judge feedback (confirmed, accurate
restatement every time) or failing to execute transforms (proven
capable earlier via spatial_eval) — its own mental menu of "things I
could try" was just too narrow, and nothing had ever told it
repositioning or switching anchors belonged on that menu as a lever
equal to intensity or color.

Clarified for Eran: this was NOT the judge limiting anything — the
judge only describes what's visually wrong, it has no concept of
levers or tools at all. The restriction was entirely self-imposed
agent behavior.

## Lever menu + deterministic lever-usage diffing (2026-11-25)

**Built per Eran's design, confirmed in a 3-part Q&A exchange**: added
a `Lever` enum (position, rotation, intensity, falloff_range, color,
ambient, skybox, global_grading) to `LightingDecision`'s structured
output as `lever_accounting: list[LeverUsage]` — every lever, every
attempt, explicitly marked `changed` or `changed=False` with a real
reason. Per-lever explanations (what each one does, when to reach for
it) live in the instructions as prose, not the schema (OpenAI
structured output doesn't support per-enum-value descriptions). The
instructions explicitly state levers are NOT mutually exclusive —
combining several per attempt is the expected default, not an edge
case — specifically to avoid the schema backfiring into even narrower
single-lever attempts.

**Also built, independently, the deterministic half (Eran: "we dont
trust the lighting agent reasoning enough, so we provide a
deterministic check as well")**: `_snapshot_lever_state()` /
`_diff_levers()` in `main.py` capture real scene state (every light's
position/rotation/intensity/range/color, ambient, skybox, color
grading/vignette/fog) before and after each attempt, and diff it —
zero trust in the model's own `lever_accounting` self-report. The
running set of VERIFIED-touched levers (code, not LLM) is fed into
every subsequent attempt's prompt: "touched = [...], NEVER touched =
[...]". A live mismatch printout (`self_reported_changed` vs
`verified_changed`) runs every attempt as a standing sanity check.

**Also wired `skybox` in as an actual tool** (`list_skyboxes`/
`set_skybox`) — discovered mid-build that a full HDRI-manifest system
already existed in `unity_bridge.py` (multiple skyboxes with mood
metadata: time_of_day, weather, contrast, light_type) but had never
been exposed via `tools.py`/`agent.py`. This scene's `ambientMode` is
Skybox-driven, so swapping it genuinely changes indoor light, not just
a visible backdrop.

**Result, tested on horror + thriller**: the specific gap this was
built to close IS closed — both cases' final attempt touched POSITION
for the first time all session (never happened once across 5 attempts
in the earlier full-trace diagnostic). The mismatch check also caught
one real live self-report divergence (horror attempt 3: self-reported
`rotation` only, verified diff showed `position` also changed) —
direct proof the distrust was warranted. Still 0/2 pass, but for a
NEW, narrower reason: the attempt that finally reaches for position
also overcorrects into near-black and gets guardrail-rejected before
reaching the judge in both cases — the new lever gets used but never
actually scored. This is now a distinct, scoped-down problem
(overcorrection on the attempt that diversifies), not the original
"stuck on 1-2 levers forever" problem, which this change resolved.

## Session summary (2026-11-25): the real culprit was a corrupted baseline, not a model-capability gap — full writeup

This covers the rest of the 2026-11-25 session: mandatory-transform
enforcement, the discovery that the "baseline" every attempt was
restoring to was itself corrupted and near-black, and the render-
pipeline-compounding finding that explains why grading alone could
crush an otherwise well-lit frame. Written up in full because this
segment reframes a large fraction of the session's earlier findings.

### Issue 1: mandatory per-attempt transform enforcement, and the tension it exposed

**Context**: the lever-diversity fix (previous section) worked, but
only loosely — an attempt would eventually touch position, not every
attempt. Eran's call: make it a HARD requirement, not a stronger
prompt, consistent with this project's whole pattern (code enforces,
prompts don't).

**Built**: a new guardrail in `main.py`'s attempt loop — if neither
`position` nor `rotation` is in the verified lever diff for an
attempt, reject it before the judge call (same shape as the
visibility/contrast guardrails), feed back "you MUST move or rotate a
light this attempt," retry free.

**Found and fixed a real bug in the guardrail itself**: it initially
only credited an EXISTING light's position/rotation change, not a
NEWLY CREATED light's placement — meaning an attempt that created a
well-placed new light (exactly the behavior we wanted) still failed
the transform-mandate check and had to make a redundant, pointless
extra move. Fixed `_diff_levers()` to count a light's creation as a
position+rotation change in its own right (placing a brand-new light
IS a spatial decision).

**Found a real tension, reported honestly rather than papered over**:
once a light already exists at a sensible position, a LATER attempt's
most sensible move might genuinely be "don't move anything, just
recover from the previous attempt's overcorrection" — but the hard
per-attempt mandate rejected that sensible recovery anyway, burning
the run's last attempt on the mandate instead of ever reaching the
judge. Flagged a fix (require it once per RUN via the already-tracked
`levers_touched_this_run` set, not every single attempt) but did not
implement it — superseded by the baseline discovery below, which
turned out to be the dominant issue.

### Issue 2: Eran's hunch — "does the agent only ever work with existing lights?" — confirmed with real data

Checked directly: across 2 full eval runs (6 attempts total), light
count stayed at exactly 2 every single attempt. `create_light`/
`create_light_near` are registered, available tools, never called
once. Same root pattern as the lever-diversity gap, one level up:
given an existing option and a from-scratch option, the agent always
takes the existing one. Fixed with an instructions addition
("EXISTING LIGHTS ARE NOT A CONSTRAINT") explicitly telling it a new
light is a normal, equally-valid move, not a last resort — confirmed
working on the very next test run (it created a new light on attempt
2, the first time all session).

### Issue 3 (the big one): "wait, look at the baseline screenshot — it's already black"

**Eran caught this by actually looking at the screenshot**, not by
more guardrail-tuning: "the baseline is not the real original scene,
its like the latest result which is also black." Checked immediately
with `vision_analyze` on `screenshots/horror/latest/baseline.png` —
confirmed, the "baseline" (the state every attempt restores to before
starting) was itself a near-black room.

**Root cause, confirmed by reading the actual `.unity` scene file
directly** (untouched on disk, since the live Unity Editor had been
running continuously, unsaved, for the entire multi-hour session):

| | Real original (`.unity` file + Volume asset) | What every run restored to |
|---|---|---|
| Light "Point Light (4)" intensity | **2.17** | 0.001 |
| Light "Point Light (3)" intensity | **0.81** | 0.02 |
| Ambient intensity | **1.0** | 0.0 |
| ColorAdjustments post_exposure | **+0.39** | -0.15 |
| ColorAdjustments contrast | **17.6** | 32.0 |
| ColorAdjustments saturation | **+7.8** | -12.0 |
| Vignette | **doesn't exist in the original Volume at all** | intensity 0.38 |

**Why this happened**: `capture_scene_baseline()` captures once per
scene and never overwrites, specifically so it'd grab the true
original before anything touched it. But by the time it was first
called this session, the live Editor had already been running unsaved
through hours of earlier mood tests. It captured already-darkened test
residue and every subsequent run treated that as gospel. Every attempt
started from near-black, so of course every attempt kept ending in
near-black — there was barely any room left below the floor it was
already standing on. This explains a large fraction of the session's
earlier findings (the ambient fix, the contrast-floor tuning, the
brightness-anchor calibration, the "capped at 5/10" plateau, the
oscillation into overcorrection) — all of it was downstream of testing
against a broken starting point, not a model-capability gap.

**Fix, applied live and verified**:
1. Read the true values directly from the `.unity` scene file and its
   `Global Volume mesa_Free.asset` (lights, ambient, fog, color
   adjustments — matched by GameObject name, e.g. fileID 507586010 =
   "Point Light (4)").
2. Pushed them into the live Editor via the existing `unity_bridge`
   setter functions (not a new mechanism — this alone is evidence the
   existing tools were fine, only the cached data was wrong).
3. Deleted the corrupted baseline JSON cache, recaptured fresh.
4. Verified with `measure_frame_brightness()` and `vision_analyze` on
   an actual screenshot: mean brightness went from 13.3 to **86.5**,
   p90 from 25.0 to **112.0** — a completely normal, readable room,
   the first time it had actually been seen properly lit all session.
5. **Saved the Unity scene** (`unity.exe command scene save`) to lock
   the fix in — critical, since the Editor had been unsaved this whole
   time and a crash/restart before saving would have lost it.

**Side effect caught and cleaned up before committing**: the earlier
`rm -f .../scene_baselines/*.json` glob (used twice this session to
force a clean baseline recapture) also deleted the UNRELATED Forest
scene's baseline cache by accident — restored via `git checkout --`.
Also found `set_skybox`'s exposure/rotation params mutate the SHARED
`.mat` asset file in place (not scoped to the current session/scene) —
a real design risk worth fixing later (it should probably clone a
scene-local material instead of mutating the shared one), reverted the
incidental change for now, flagged as technical debt.

### Issue 4: re-tested from the real baseline — and found a NEW, more specific problem

Horror re-run from the corrected baseline: attempt 1 landed p10=7,
p90=35, spread=28 — closer to the 35 contrast floor than any attempt
all session, with a believable light setup (not an overcorrected
mess). Real, measurable progress from the baseline fix alone.

But a new pattern showed up clearly once the "always near-black to
start with" noise was removed: `global_grading` (contrast, saturation,
vignette, post_exposure) kept escalating monotonically attempt over
attempt (contrast 38→52→68, saturation -12→-18→-28, vignette
0.28→0.38→0.5) regardless of what the lights were doing. By attempt 3,
TWO agent-created lights at genuinely strong intensity (14 and 8.5)
coexisted with a scene that still rendered 100% black (mean
brightness=0.1/255).

**Eran's question: "how come we get a black color with all the
lights? is it the post-processing?"** — answered empirically, not by
guessing. Reproduced attempt 3's exact state live and isolated each
post-processing knob one at a time:

| State | mean brightness |
|---|---|
| All grading neutral (same lights) | 38.4 |
| + post_exposure alone | 33.3 |
| + contrast alone | 21.2 |
| + vignette alone | 15.4 |
| + fog alone | 38.9 (negligible) |
| + post_exposure + contrast + saturation + color_filter together | 9.9 |
| + vignette ALSO stacked on top of those | **0.4** |
| + fog on top of that | 0.1 |

**Confirmed: yes, it's post-processing, not the lights** — but more
precisely, no single knob is individually devastating; it's the
STACK. Each post-processing stage transforms the OUTPUT of the
previous stage, not the original render, so moderate-looking values
compound multiplicatively in series rather than adding. Fog turned out
to be a red herring in this scene (negligible effect at the ranges
used). Vignette was the specific final blow that tipped an already-
darkened (but not yet black) image into total black.

### Fix 4a: teach the agent the real render pipeline + division of responsibility

Eran's proposal: "maybe we should define the lighting pipeline to the
agent in a constructive way... use post-processing to get the basic
ground mood, then use lights to enhance it... thinking about them as a
whole, not single attributes." Reframed slightly during discussion:
not strict rendering order as a literal instruction sequence, but a
division of responsibility — **lights are the ONLY stage that can
create LOCAL contrast** (one area bright, another dark); post-
processing reshapes the WHOLE frame globally afterward and can't
invent new local differentiation, so it should be a light-touch
finishing pass, not the primary dramatic mechanism. Added a new
"RENDER PIPELINE ORDER" instructions block in `agent.py` teaching this
explicitly, grounded in the exact measured numbers above (not an
abstract warning — a concrete, scene-specific anchor the agent can
reason from).

### Fix 4b: a pre-render grading-severity guardrail — pure arithmetic, zero render cost

Built `_grading_severity()` in `main.py`: a heuristic score summing
`|post_exposure| + contrast/50 + |saturation|/50 + vignette*1.5 +
color_filter_deviation` — deliberately additive in the formula to
mirror the fact that each term is a SEPARATE multiplicative pass in
the real pipeline (summing proxies for compounding). Runs on the
decision's own already-diffed values, before any screenshot — catches
a likely crush before paying for ANY render or judge call, not just
before the judge call like the existing visibility/contrast
guardrails.

**Calibration caught a near-miss before shipping it**: the first
proposed floor (1.8) was checked against horror attempt 1's REAL
values from the corrected-baseline run (the closest-to-passing attempt
all session) and would have false-positive rejected it (severity
~1.88). Raised the floor to 2.6 — safely above that legitimate
attempt, still below the measured ~2.5 first-drop point and ~3.25
full-crush point. Documented explicitly in the code as calibrated
against exactly one measured case, to revisit if it over/under-
triggers on other scenes.

**Result, re-tested**: ran horror again with both fixes in place.
Attempt 2's grading severity (2.96) was caught and rejected BEFORE any
render/judge cost. Attempt 3 pulled grading back to severity 1.67 and
— for the first time this entire session — the run did NOT crash to
black. It reached the judge: score 4/10, with a completely different
and far more mundane complaint than before: *"extremely dark and
heavily underexposed... more like the scene was dimmed than
deliberately lit for tension"* — underlit, not crushed. Still a fail,
but a different, much more tractable class of failure (simple
calibration, not a structural black-hole bug) — exactly the kind of
thing the existing judge-feedback retry loop is designed to fix with
more iterations.

### What worked this session (techniques, for reuse)

- **Empirical isolation testing over guessing**: when asked "is it the
  post-processing?", reproduced the exact failing state live and
  toggled ONE knob at a time before answering — found the real
  mechanism (compounding, not any single value) instead of a plausible
  but wrong guess.
- **Reading the actual source-of-truth file when live state is
  suspect**: the live Unity Editor's in-memory state had drifted for
  hours; the `.unity` scene file + Volume `.asset` on disk were
  untouched and gave the real ground truth directly via `grep`/`sed`,
  no Unity API needed.
- **Distrust self-report, verify with code, and the mismatch check
  paid for itself live**: `lever_accounting`'s self-report vs. the
  deterministic scene-state diff caught a real live divergence
  (reported "rotation" only, verified diff showed "position" too).
- **Calibrate every guardrail floor against a REAL measured data
  point, not a guess** — both `CONTRAST_SPREAD_FLOOR` (earlier
  session) and `GRADING_SEVERITY_FLOOR` (this session) were set from
  actual before/after measurements on this scene, and the severity
  floor was specifically checked against a known-good attempt before
  shipping to catch a false-positive risk.
- **A hard-requirement guardrail can conflict with genuinely sensible
  behavior** — the transform mandate blocked a sensible recovery
  attempt once; worth remembering that "enforce X every single
  attempt" and "enforce X at least once per run" are different
  policies with different failure modes, pick deliberately.
- **When a result seems inexplicable, check the inputs, not just the
  model** — the session's biggest finding came from Eran looking at a
  screenshot and asking "wait, is the baseline itself black?" rather
  than continuing to tune guardrails/instructions against a broken
  starting point.

## Session continued (2026-11-25): result.png never matched what got judged

Right after the fixes above shipped, Eran looked at the latest horror
`result.png` and called out that it was pure black — contradicting the
"4/10, underexposed not crushed" summary just given. Investigation
found a real, separate bug, not a regression of the fixes above.

### The bug: 4 independent `capture_game_view()` calls per attempt

1. `post_attempt_capture` in `main.py`, fed to the visibility and
   contrast guardrails.
2. A second, fully independent capture taken *inside*
   `judge_mood_match()` in `judge.py` — this is the only image the LLM
   judge ever actually sees.
3. A third capture, taken fresh in `main.py` *after* the judge call
   returned (on the passed path, the judge-failed path, and both the
   visibility- and contrast-guardrail-rejection paths), purely to save
   as `result.png` for the record.

Nothing enforced agreement between these three. The judge's own score
and reasoning were accurate for capture #2 — just not for capture #3,
the only one ever written to disk. `result.png` had never been seen by
anything that decided pass/fail; it was a decorative screenshot taken
after the decision was already made.

Confirmed concretely on the `20261125T200516Z` horror run: the logged
judge score was 4/10 ("extremely dark... more like the scene was
dimmed than deliberately lit"), but running `check_frame_visibility()`
directly against the saved `result.png` gave `mean_brightness=19.6`,
`pct_near_black=65.7%` — visibility check still said `visible=True`
(see next section), but visually the frame is close to pure black, a
real mismatch from what the judge scored.

### Investigated, but deliberately did NOT change: the visibility floor

Before assuming `check_frame_visibility()`'s 90%-near-black ceiling
was simply too loose, pulled a real PRE-fix PASSING horror screenshot
(`20261124T085853Z`, judge score 7) and ran the same check on it:
`mean_brightness=14.1`, `pct_near_black=67.2%` — nearly identical
numbers to the broken frame (65.7%/19.6), yet a vision check confirmed
this one is a legitimate, atmospheric dark room with visible shadow
shaping, not a crushed-black failure. The pixel-level stat genuinely
cannot distinguish "crushed black" from "legit dark mood" at this
resolution — tightening the ceiling would have false-rejected good
dark scenes using the one data point that happened to be bad. Left the
threshold exactly as-is; this is a known limitation of a cheap,
free pixel check, not something to patch reactively from a single
bad sample.

### Fix shipped

- `judge.py`: `judge_mood_match(mood_task, image_path=None)` now scores
  whatever `image_path` it's given, instead of taking its own
  independent capture. `image_path=None` still falls back to a fresh
  capture, kept only for standalone/ad-hoc use outside the main loop.
- `main.py`: the single judge call in the attempt loop now passes
  `image_path=post_attempt_capture.path` — the exact frame the
  visibility/contrast guardrails already checked. Every result-saving
  path (`passed`, judge-failed-at-max-attempts, visibility-rejected-at-
  max-attempts, contrast-rejected-at-max-attempts) now copies that same
  file to `result.png` via `shutil.copyfile` instead of calling
  `capture_game_view()` again.
- Left the two PRE-render guardrail rejections (grading-severity,
  no-transform-change) capturing fresh — correct, not an oversight:
  those reject before anything has even been rendered, so there is no
  prior capture to reuse yet.

### Verified live

Re-ran horror end to end post-fix. Judge passed on attempt 1, score
6/10: *"very dark overall... cold blue tint... uniform dim wash rather
than a strongly directional horror setup... reads more like 'lights
turned down' than aggressively tense."* Pulled the saved `result.png`
and vision-checked it directly against that exact reasoning — matched
word for word (dark room, cold blue wall-light/monitor tint, no
dramatic key light, no real shadow shaping). Capture mismatch confirmed
fixed: the file on disk is now provably the file that got judged.

### Known fallout, not retroactively fixed

This capture-mismatch bug existed from when the screenshot pipeline was
first built (2026-11-23) through this session's earlier fixes, so any
historical `result.png` — including past logged "passing" runs — may
not reflect what its judge call actually scored. Not re-validating old
runs; just don't treat an old saved screenshot as ground truth for a
historical score without independently re-checking it.

## Session continued (2026-11-25): key/fill/rim lighting + a p90-vs-baseline guardrail

Eran asked two direct questions after the capture-mismatch fix: does
the agent actually follow key/fill/rim three-point lighting, and is it
being too conservative on intensity? Checked both against real code
and real data before building anything.

**Key/fill/rim: confirmed NO.** `agent.py`'s instructions only knew
one lighting concept — "a key light, suppress everything else near-
zero." No fill light (controlled secondary that keeps the shadow side
readable without flattening it) and no rim/backlight (edge separation
from background) existed anywhere in the prompt.

**"Too conservative on intensity": confirmed NO, wrong diagnosis.**
Pulled the actual numbers from the just-verified 6/10 "passing" horror
run: key light intensity was 14.5 (not timid), yet the frame's own
measured bright zone (p90=44) came in BELOW the scene's untouched,
unlit baseline (p90=112). Raising the intensity number further
wouldn't have fixed this — something (global grading/vignette
stacking back on top) was eating the light's actual contribution
before it ever reached the frame. The real gap: the agent's own
instructions already said the attempt's p90 should clear baseline
p90, but nothing in code enforced it — `CONTRAST_SPREAD_FLOOR`/
`P10_CEILING` check spread and dark-zone darkness, neither checks the
bright zone against baseline. That exact "passing" run (spread=41,
p10=3.0, has_real_contrast=True) sailed through untouched.

**Fix 1 — three-point lighting in the agent's instructions
(`agent.py`).** Replaced the old "one key, kill everything else"
guidance with an explicit KEY + FILL (10-30% of key, never fully off)
+ RIM (optional, behind/to-the-side edge light) structure. Ambient
(separate, uniform, scene-wide lever) still goes near-zero for drama —
kept distinct from a directional fill light, which should NOT go to
zero.

**Fix 2 — a new deterministic guardrail (`main.py`,
`KEY_LIGHT_P90_LIFT_FLOOR = 1.05`).** For high-contrast moods only,
gated behind the existing contrast check (`has_real_contrast`) rather
than replacing it: even when spread/p10 both pass, now also requires
the attempt's rendered p90 to clear the scene's untouched baseline p90
by 5%. Rejects before the judge call, same pattern as the existing
guardrails, with feedback pointing at the specific fix (push key
intensity, narrow range, or ease off a grading value quietly eating
the gain).

**Verified live, two ways:**
- Ran the new guardrail's math directly against the earlier 6/10 "pass"
  (p90=44, baseline p90=112, required=117.6) — confirms it would have
  correctly caught that exact case.
- Re-ran horror live (`MAX_ATTEMPTS_DIAGNOSTIC_OVERRIDE=5`). Attempt 1
  explicitly built key+fill+rim in its own summary — the new
  instructions are being followed, not just present in the prompt.
  Attempt 3 was rejected live by the new guardrail: `p90=48.0 < required
  117.6` — confirmed firing correctly in the real attempt loop, not
  just in a standalone check.

**Net result, reported honestly:** horror did NOT pass in either
post-fix run (3-attempt run failed on the transform-mandate guardrail;
5-attempt run failed on grading-severity after the new p90 guardrail
correctly blocked attempt 3). This is not a regression — the earlier
"pass" was a false positive the loophole let through. Closing it
makes the eval stricter and more honest, but the underlying challenge
(a genuinely dominant key light that survives grading without tripping
severity) is still open. Lights are escalating hard across attempts
(2.8 → 4.8 → 6.2 → 12.5 → 16.5 intensity) while still getting rejected
by one guardrail or another — worth a dedicated tuning pass next
session rather than more ad-hoc pushes.

## Session continued (2026-11-26): the REAL root cause — camera clipping plane, not lighting at all

Eran was working directly in the Unity Editor (separate from the
automated pipeline) and noticed the Scene view showed the room
properly lit while the Game view was near-total black — and, critically,
**disabling the Global Volume's post-processing entirely changed
nothing**. That one fact ruled out everything the last two sessions had
been tuning (grading, vignette, lights) as the cause of this specific
failure mode, since none of that is reachable before the Volume stack
even runs.

Investigated two hypotheses before Eran found the real one:
- Lights set to Baked/Mixed mode with no bake (classic Scene-view-vs-
  Game-view mismatch) — checked directly via `component get_fields`,
  ruled out: all lights confirmed `m_Lightmapping: Realtime`.
- Camera's "Physical Camera" exposure (found ISO 200, f/16, 1/200s
  shutter serialized on the Main Camera — a bright-daylight exposure
  profile that would crush any indoor scene, and wouldn't be touched by
  disabling post-processing) — plausible, matched the symptom, but
  turned out to be a red herring: Physical Camera stayed checked ON in
  Eran's own before/after screenshots and the fix wasn't there.

**The actual bug, found by Eran:** the Main Camera's **near clipping
plane was 0.01**, and the camera sits right at the room's geometry
boundary (confirmed: camera position exactly matched the scene's
bounding-box max corner). A near-clip that tiny means "render anything
no matter how close to the lens" — with the camera sitting against a
wall/ceiling, Unity was rendering that wall's unlit interior face at
point-blank range, filling the entire frame. Raising near to ~12
clipped that wall out of the frustum and revealed the actual room.
This is why Scene view looked fine (its own camera preview ignores a
Camera *component's* clip planes/exposure) and why post-processing was
irrelevant (clipping happens at the geometry stage, before the Volume
stack runs at all).

**This is the real root cause of the "black rendering" plateau this
entire project has been fighting across multiple sessions** — not a
model-capability gap, not grading compounding, not a false-pass
guardrail loophole. All of that work was real and is still correct
(it fixed genuine secondary issues), but the dominant symptom
(total black frames) was sitting in a camera misconfiguration that
none of the agent's tools have ever touched or could ever touch.

**Fixed and verified:**
1. `restore_scene_baseline()` to revert any leftover mutated light
   state from prior test runs, `save_scene()` to lock in Eran's
   near-clip fix (confirmed in the `.unity` file: `near clip plane: 10.9`,
   not `0.01`).
2. Found and removed a leftover agent-created light
   (`AgentLight_Horror_Rim_Back`) from an earlier diagnostic run that
   hadn't been cleaned up (bypassed `main.py`'s normal
   `cleanup_agent_lights()` since these calls went through
   `unity_bridge` directly) — re-saved clean.
3. **Re-captured the baseline brightness** — the old baseline was
   measured through the broken camera. New: mean=90.8, p90=145.0 (up
   from the old broken-camera baseline's mean=86.5, p90=112.0 — same
   ballpark on mean since baseline itself wasn't literally black, but
   p90 jumped meaningfully now that the camera isn't obstructed).
4. Ran a full horror mood test end to end. **The baseline screenshot
   alone is dramatically sharper and more detailed than any screenshot
   this entire project has produced** — full texture/prop detail
   clearly visible, versus the flat, muddy renders every prior session
   worked from. The final attempt's result (rejected on an unrelated
   guardrail technicality — no light position/rotation changed that
   specific attempt, nothing to do with blackness) is visually a
   genuinely convincing horror frame: one dominant light pool on the
   arcade machine, real falloff, dark corners staying dark without
   going unreadable, legible shapes throughout.

**Open question for next session:** how much of the multi-session
"horror/thriller keep ending in black" story, the corrupted-baseline
finding, the grading-compounding finding, the p90-vs-baseline
guardrail, was actually downstream of this camera bug rather than
independent issues? Worth re-running the full eval suite now that the
camera is fixed before doing any more guardrail/instruction tuning —
several "failures" and "fixes" from earlier sessions may look
completely different against a camera that isn't secretly staring
into a wall.

## Session continued (2026-11-26): re-running the eval suite exposed 3 more stale pixel-stat guardrails, all fixed

Ran the full 10-case eval suite fresh after the camera fix: **4/10
passed clean** (golden_hour, cozy_cafe, dreamlike, zen). But checking
the 6 failures by eye (not just trusting the score) found most weren't
real quality failures — they were the SAME class of bug as the camera
fix, just one layer down: every pixel-percentile-based guardrail in
this project (`VISIBILITY_MEAN_BRIGHTNESS_FLOOR`,
`VISIBILITY_NEAR_BLACK_PCT_CEILING`, `CONTRAST_SPREAD_FLOOR`, and this
session's own new `KEY_LIGHT_P90_LIFT_FLOOR`) was calibrated against
either the broken camera's rendering behavior or a single stale data
point, and all four started false-positive rejecting genuinely good,
legible content once the camera started rendering correctly and the
agent's new key+fill+rim instructions started producing real localized
dramatic lighting.

**Confirmed by direct visual check, not assumption:** pulled the actual
`result.png` for every guardrail-rejected case (horror, eerie_lab,
thriller, post_apocalyptic, noir) — 4 of 5 were genuinely good,
legible, convincing frames (full room detail, real light pools, legible
shapes), rejected purely on pixel-percentile math. The 5th (thriller)
was a real borderline case.

**Root cause, same pattern three times over:** global percentile stats
(mean brightness, p90, p90-p10 spread) measured across the WHOLE frame
can't register a small, perceptually-salient bright highlight (a
glowing monitor, a tight key-light pool) against a mostly-dark
background — exactly the kind of shot this project's lighting style
increasingly produces now that it's actually working. Proved this
concretely: a confirmed-good frame (eerie_lab, mean=2.2, pct=98.5%) and
a confirmed-flatter/worse one (empirically forced via escalating
grading, mean=2.5, pct=98.2%) measured ALMOST IDENTICALLY — these two
pixel stats genuinely cannot tell "legitimately dark" from "a flat
crush" apart in this regime. Not a threshold-tuning problem, a real
metric limitation.

**Recalibrated all three, iteratively, verified live each time (3 full
eval re-runs on the 6 failing cases):**
1. `VISIBILITY_MEAN_BRIGHTNESS_FLOOR`: 10.0 → 1.0; `VISIBILITY_NEAR_BLACK_PCT_CEILING`: 90.0 → 99.0
   — only catch an unambiguous forced-crush (mean=0.4, pct=99.1%
   confirmed empirically), let everything above that reach the judge.
2. `CONTRAST_SPREAD_FLOOR`: 35.0 → 3.0 — confirmed-good real examples
   measured spread as low as 2 (eerie_lab), the old 35.0 floor was
   rejecting literally every real good dark/dramatic frame this scene
   can produce. `P10_CEILING` (30.0) left untouched — still a real,
   working signal, no false positives observed on it.
3. `GRADING_SEVERITY_FLOOR`: 2.6 → 3.3 → **3.9** (two passes needed —
   first raise to 3.3 was still too tight, a live eval re-run showed
   the agent's own natural later-attempt escalation landing at
   3.36-3.65, all below the empirically-measured ambiguous point
   (~3.98) and well below the confirmed crush point (~5.0); raised
   again to 3.9, now tied directly to the measured ambiguous boundary).
4. `KEY_LIGHT_P90_LIFT_FLOOR`: 1.05 → **0.15** — this was THIS
   session's own new guardrail (built before the camera fix), and the
   worst-hit: it requires the attempt's own p90 to exceed baseline p90,
   but baseline p90 jumped to 145 post-camera-fix and a tight,
   contained dramatic key-light pool (by design) never moves a
   whole-frame 90th-percentile stat much — every real confirmed-good
   example measured a ratio of just 0.03-0.17 against the room's full
   ambient brightness. The semantics also flipped (was "must exceed
   baseline by a lift factor >1.0", now "must reach this fraction of
   baseline <1.0") — a real fix would compare brightness within the key
   light's own intended pool/ROI rather than a whole-frame percentile;
   flagged for later, not solved this session.

**Final verified result, 3rd and last recalibration pass:** **2/6
genuinely PASSED** (horror 6/10, noir 7/10) with real judge scores on
real legible frames. 2 more (`post_apocalyptic`, `festive`) reached the
judge honestly (4/10 each — real mood-quality feedback, not a guardrail
false-positive) and are now genuine calibration/mood-quality work, not
guardrail bugs. The remaining 2 blocks are both defensible, not
miscalibrations: `eerie_lab`'s final attempt measured pct_near_black=
99.1%, landing exactly on the confirmed-crush data point above; 
`thriller`'s p90=21.0 missed its required 21.8 by under 4%, a genuine
near-miss. Stopped recalibrating here — further gains from here are
real agent/mood-quality tuning, not guardrail-calibration bugs.

## 2026-11-26 (Phase 0+1): color-temp bug, shadow strength, skybox tint, tonemapping

Phase 0 diagnostics (free, code-only) on the real scene confirmed:
`m_UseColorTemperature=false` on BOTH scene lights (every past
`color_temperature` write was a silent no-op), no Tonemapping override
at all, camera/pipeline HDR already enabled (Bloom clear to build later).

Fixes shipped:
- `set_light_properties` now forces `m_UseColorTemperature=true`
  whenever `color_temperature` is set.
- New `shadow_strength` lever (0-1, how dark a shadow renders),
  independent of `shadow_type` (whether one exists at all).
- New skybox `tint` (r,g,b) lever — free color wash on the sky AND
  indoor ambient (skybox-driven here), on top of any HDRI choice.
- Added a Neutral Tonemapping override (project had none). A/B tested
  live on the real clean baseline: None (mean=83.4, p90=97.0) and
  Neutral (mean=84.8, p90=98.0) are nearly identical; ACES (mean=52.9,
  p90=66.0) is meaningfully darker from its filmic shadow-crushing toe
  — the wrong direction for a project whose #1 recurring bug is
  accidental crushing. Neutral chosen, not ACES.

New bug found and fixed in the same pass: once color_temperature
actually works, the agent was still reflexively cooling light `color`
(RGB) at the same time — the two levers multiply, so a cool RGB tint
*and* a cool Kelvin value together double-cool and double-dim a light,
crushing the scene even at modest intensity. `agent.py` now explicitly
warns against stacking both on the same light.

Re-captured baseline on the corrected setup: mean=84.8, p90=98.0.
Validated live (horror + noir): both ran end-to-end cleanly, no
regression, no recurrence of the double-cooling crush.

**New finding, flagged not fixed:** the noir test produced a genuinely
good, legible monochrome frame (full B&W via saturation=-100) that the
grading-severity guardrail rejected anyway (4.44 vs floor 3.9). The
severity formula likely overcounts intentional full desaturation as
crush risk the same way it counts blown-out exposure — those aren't
the same failure mode. Next session.

## 2026-11-26 (cont'd): RGB-only lighting, quick fixes, judge persona

**Went RGB-only for all light tinting.** Decision: drop
`color_temperature` from the agent's instructions and tool docstring
entirely, instead of warning it not to stack color+temperature.
Rationale: Kelvin can only move along the real blackbody curve
(orange->white->blue), structurally cannot produce green/purple/cyan,
which this eval suite needs (horror, post_apocalyptic, eerie_lab). RGB
is a strict superset of what Kelvin can do. Removes the double-cooling
bug class structurally rather than relying on instruction discipline.
`color_temperature` stays in `unity_bridge.py`'s API for manual use.

**Two quick fixes:**
- `capture_scene_baseline`/`restore_scene_baseline` now also track
  `shadow_strength` and `use_color_temperature` (new fields from the
  Phase 0+1 pass, were invisible to restore — an attempt that darkened
  shadows would never get reset back).
- `_grading_severity` no longer penalizes negative saturation.
  URP's saturation is luma-preserving (lerps toward grayscale, doesn't
  scale luminance) — confirmed by the exact noir case above, which
  measured severity=4.44 with the saturation term alone contributing
  2.0 of that. Only over-saturation (positive values, real clipping
  risk) counts now. Verified: same noir snapshot now computes to 2.44.

**Judge persona (the big one).** Found via Eran directly questioning a
passing result: the horror attempt that scored 6/10 PASS had judge
reasoning that read like a fail — "extremely dark overall... mostly
reads as a dim wash... shadow separation is weak because most of the
frame collapses into near-black... not especially cinematic." Score
and reasoning were disconnected, a real judge bug.

Fixed by giving `judge_agent` a persona: an elite AAA video game
lighting producer/cinematographer with zero patience for lazy
fake-drama tricks (turning everything down and calling it horror,
crushing to black and calling it noir). Added an explicit failure-mode
callout: small self-illuminating props (monitor glow, arcade screen,
ceiling panel emissive surface) are NOT the same as the room being lit
— if the floor/walls around them stay near-pure black, that's
underexposed, not atmospheric pooling, and "a few bright dots and
nothing else" is a clear fail well below 6, not borderline. Made
score-must-follow-reasoning an explicit rule.

Verified by re-judging the EXACT SAME saved frame that previously
passed at 6/10: same image, near-identical reasoning text, new score
4/10 FAIL. Proves the bug was in scoring logic, not something
ambiguous about the image. Re-ran horror live end-to-end: both real
attempts now honestly fail at 4/10 (attempt 3 hit the existing
transform-mandate guardrail before reaching the judge, a known
separate tension, not new).

**Honest framing going forward:** this is a strictly harder bar. The
eval pass rate will likely look worse on the next full suite run —
that's the judge telling the truth, not a regression. Several of the
suite's historical 6/10-7/10 passes (recorded earlier in this file,
pre-persona) are now suspect and should be treated as unverified until
re-judged under the new persona. The real work ahead: the lighting
agent still isn't producing a genuine directional key light that
shapes the room — it's dimming/cooling things uniformly, not lighting
them dramatically. Next session: re-run the full 10-case eval suite
under the new judge to get an honest current baseline before any more
tuning.

## 2026-11-26 (cont'd): the REAL key-light root cause — a 10x intensity unit mismatch, not a concept gap

Eran pushed on the key-light problem directly: "the agent doesn't
understand studio lighting." Proposed a structured-output fix mirroring
the proven `Lever` enum pattern — force the agent to explicitly assign
a `LightRole` (KEY/FILL/RIM/PRACTICAL/UNUSED) to EVERY light in the
scene, every attempt, with real reasoning, instead of hoping prose
instructions stick. Built it (`LightRole` enum, `LightRoleAssignment`,
`light_role_assignments` field on `LightingDecision`, logged per-attempt
in `main.py`). Deliberately NOT capped at one KEY per attempt — observe
real usage first, decide on a cap later if ever needed.

**This immediately disproved the "doesn't understand" theory.** Live
test: the agent's own reasoning for a self-created key light read
*"it shapes the wall/shelf geometry and gives the room a second
readable pool so the scene doesn't feel like isolated dots in black"*
— literally pre-empting the judge's own failure-mode language. Then the
actual render was still almost pure black, a handful of blue dots,
nothing else. The agent's PLAN was correct. Its EXECUTION wasn't
working. That reframed the whole investigation: not a concept problem
anymore, an execution/calibration problem.

**Debugging the execution gap, step by step, all empirical:**
1. Boosted the "key" light 6x in place — brightness barely moved
   (14.1→14.1). Boosted the room's own ORIGINAL untouched fixtures 10x
   — also no change. Ruled out anything light-specific (e.g. a new
   light's culling mask).
2. Disabled fog entirely — no change. Ruled out fog.
3. Brute-force intensity sweep up to 50,000 (vs. the project's sane
   range of 0-20) — finally saw real response (mean 14→40, p90 cleared
   baseline). Looked like a catastrophic unit-scale mismatch.
4. Searched Unity's OWN official docs before touching any code (Eran's
   explicit instruction, don't guess). Found URP's documented default
   Point/Spot intensity is just "1" (plain small scale, matching this
   project's whole convention) — directly contradicting a forced
   physical-units theory.
5. Queried the actual scene's lights directly: EVERY light (including
   the room's own untouched original fixtures, never touched by any of
   our tools) is tagged `lightUnit=Candela`.
6. Tested whether that tag does anything: switched Candela→Lumen at a
   FIXED intensity (3.0) — byte-identical render, zero difference.
   Confirmed via more official docs (HDRP's `HDAdditionalLightData`/
   `LightUnitUtils` API) that `lightUnit`/physical-unit conversion is
   an HDRP-only concept; URP has no such toggle, it just reads
   `Light.intensity` as a raw scalar in its own attenuation math and
   ignores the unit tag completely. **There is no legacy/physical
   switch to flip — this needed a code fix, not a settings fix,
   confirmed rather than assumed.**
7. Re-ran the intensity sweep PROPERLY isolated this time (one light,
   zero ambient/grading) — found the earlier "needs 50,000" result was
   a confound: that scene state also had extremely aggressive leftover
   grading (contrast=58+) crushing everything regardless of light
   intensity. Clean isolated sweep: real=1 already gives mean=49,
   fully saturates by real~600-1000 — URP's own attenuation math at
   this scene's real meter-scale distances, not a units problem at all.
8. Re-swept under REALISTIC moderate grading (not zero, not extreme) to
   find the actually usable range: real=200 alone reproduces this
   project's historical "good baseline" mean brightness (84.8) almost
   exactly. **real=200 = nice=20 (the existing sane-range ceiling) x
   10** — a clean, empirically-grounded anchor.

**Fix (Eran's call): a single conversion utility, not a codebase-wide
rewrite.** `LIGHT_INTENSITY_REAL_PER_NICE = 10.0` in `unity_bridge.py`,
with `nice_to_real_intensity()`/`real_to_nice_intensity()` applied
ONLY at the two agent-facing boundary functions
(`set_light_properties` write, `get_light_properties` read) — every
guardrail, instruction, doc, and the agent itself keep operating in the
familiar 0-20 "nice" scale unchanged; only the actual Unity write/read
gets the x10 conversion. `capture_scene_baseline`/`restore_scene_baseline`
talk to Unity in raw native units directly and were deliberately left
untouched (internal snapshot, never agent-facing).

**Caught and fixed a real bug this same fix introduced, before it did
damage:** the two original scene lights' raw intensity (0.81, 2.17)
was captured into the baseline file back before this conversion
existed — plain small numbers, literally what was always in Unity's
raw field. The new `get_light_properties` unconditionally divides
whatever it reads by 10, so those same raw baseline numbers started
reporting as 0.081/0.217 — DOUBLE-dividing values that were never
"real" scaled to begin with, making the room's own original fixtures
look nearly dead. Fixed by migrating: re-wrote the true historical
"nice" values (0.81, 2.17) through `set_light_properties` so they get
correctly written as real=8.1/21.7 this time, then recaptured a fresh
baseline (mean brightness 84.8→99.0, genuinely brighter now that those
original fixtures finally contribute real, visible light instead of
being silently negligible this whole project's history).

**Verified live, immediately:** horror test score climbed from 3-4/10
to 5/10 — a real jump, and qualitatively a completely different
result. The agent's own intensity choices for its key light (7.5 →
10.5 → 14.5 across 3 attempts) landed almost exactly on this project's
long-standing historical reference ("key intensity=14.5, not timid,"
first recorded 2026-11-25) — and for the first time, that familiar
number actually produced a fully legible room: real directional key
light, visible shadow falloff on walls/floor, convincing cold horror
palette. Best frame this project has ever produced, full stop. Judge's
remaining critique (*"underexposed and flat in the middle... shadow
shapes not especially dramatic"*) is now genuine mood-quality feedback,
not "there is basically no lighting happening" — a fundamentally
different, much more tractable class of problem.

**The real lesson:** the agent never had a conceptual gap about
key/fill/rim lighting. It had been operating on an intensity scale
that was silently 10x too small for this specific scene's real render
math this entire project's history, and no "well-lit" result ever
proved otherwise because ambient (unrelated to this bug) was carrying
almost all of the visible brightness in every prior "good" scene.

## 2026-11-26 (cont'd): real conversation history for the retry loop, not a flattened recap

Eran raised that the judge itself is correctly stateless (fresh call
every attempt, no memory of its own past verdicts — deliberately kept
that way, a stateful judge risks anchoring/grade-inflating toward its
own past opinion rather than judging the actual frame), but the
LIGHTING AGENT's own retry loop had no real continuity either — just a
flattened text recap rebuilt from scratch each attempt
(`changes_summary` + judge reasoning pasted as prose), missing the one
thing that actually matters for its own self-consistency:
`light_role_assignments`, its own per-light KEY/FILL/RIM/PRACTICAL
claims, was never fed back at all.

Replaced it with real alternating conversation turns in
`attempt_history` (assistant: the agent's own decision; user: the
feedback that followed), instead of one re-flattened string. Each
assistant turn (`_serialize_decision()`) is a hybrid of prose (narrative
judgment — `reasoning`, `changes_summary`, nothing structural to
represent) and small JSON blocks (where precision matters and
paraphrasing would lose it): the agent's role-assignment CLAIMS, the
VERIFIED lever diff (never `decision.lever_accounting`'s self-report,
same principle already applied elsewhere), and — the key addition —
the REAL light state after the attempt (`get_light_properties`, not
self-report), placed right next to the role claims so a future attempt
can literally see "I called light X my KEY" beside "light X's real
intensity was Y", closing the claim-vs-reality gap the whole
`light_role_assignments` field exists to expose.

Decided NOT to give the judge this same treatment — a stateful judge
would be tempted to bump a score just because the agent "tried to
improve," independent of whether the new frame actually deserves it.
The judge stays fresh and independent every call; only the lighting
agent gets real continuity.

Verified live: ran end-to-end with no errors. Noticed a good
qualitative sign in the SAME run — the agent's own role claims evolved
coherently turn to turn (the two original fixtures went fill → practical
→ unused_this_attempt as it kept concentrating real lighting work into
its own newly-created lights), consistent with it actually tracking its
own prior claims now instead of re-deriving them from scratch each
attempt. Final frame legible and consistent with recent quality (chair/
bed/arcade cabinet clearly visible, real cold falloff) — this change is
a mechanism improvement, not itself a mood-quality fix, so no dramatic
score jump expected from it alone; the main.py docstring's description
of the retry loop was updated to match.

## 2026-11-26 (cont'd again): full 10-case eval suite, after all of this session's fixes together

Before this, caught and fixed a third bug the suite itself would have
silently eaten: the Forest scene's only light is Directional (a sun),
and the x10 intensity conversion built for Point/Spot was applying to
it too. Directional lights have no inverse-square falloff at all
(parallel rays, distance-independent) and the sun already worked fine
at its native raw value — verified live (real=2.8 alone gives a normal
exposed outdoor scene). Gated the conversion by light type
(`_is_falloff_light()`, Point/Spot only) before running anything,
committed as `516e997`.

**Result: 4/10 passed** (up from single-digit passes in any prior
session's full-suite attempt, though direct comparison isn't clean —
no earlier session has a full matching 10-case run logged).

| Mood | Scene | Result | Score | Attempts |
|---|---|---|---|---|
| horror | Mess Hall | FAIL | 4/10 | 3 |
| eerie_lab | Mess Hall | FAIL | 5/10 | 3 |
| golden_hour | Forest | **PASS** | 7/10 | 1 |
| cozy_cafe | Mess Hall | **PASS** | 6/10 | 2 |
| thriller | Mess Hall | FAIL | 5/10 | 3 |
| dreamlike | Forest | FAIL | 5/10 | 3 |
| festive | Mess Hall | **PASS** | 6/10 | 3 |
| post_apocalyptic | Mess Hall | FAIL | 4/10 | 3 |
| zen | Forest | **PASS** | 7/10 | 2 |
| noir | Mess Hall | FAIL | best attempt 5/10 (last attempt guardrail-rejected) | 3 |

**Finding #1 — the failures aren't random, they're one pattern:**
every single Mess Hall case that failed (horror, eerie_lab, thriller,
post_apocalyptic, noir) used the agent's "restrained" lighting
archetype, and every one of them drew the *same* judge critique in
different words: lights read as isolated bright dots/props rather than
a real key shaping the room, darkness is doing the work instead of
deliberate light design, not enough directional shadow structure.
Every Mess Hall case that passed (cozy_cafe, festive) used an
"expansive"/brighter archetype; the Forest "soft_ambient" case (zen)
also passed. This reads as the restrained archetype teaching the agent
"low light count, near-zero ambient, modest intensity" when what dark/
moody genres actually need is a genuinely STRONG, bright, tightly
focused key against a dark field, not just turning everything down
evenly. Next concrete lever to pull: push the restrained archetype's
own instructions/reference intensities higher specifically for the key
light, not just "fewer lights."

**Finding #2 — the self-report-vs-verified mismatch tracking (built
this session) earned its keep immediately:** caught 4 real divergences
in this one run between what the agent claimed in `lever_accounting`
and what the verified scene diff actually showed — thriller attempt 3
(`MISMATCH=['rotation']`), festive attempt 2 (`MISMATCH=['intensity']`,
two newly-created lights stayed at their `create_light()` default
instead of the claimed intensity), noir attempt 2
(`MISMATCH=['color', 'falloff_range', 'intensity']`) and noir attempt 3
(`MISMATCH=['position', 'rotation']`). Worth investigating next
session: if the agent genuinely believes it already moved/retuned a
light when it didn't, that would also explain some of the
`no_transform_change` guardrail rejections that show up as the FINAL,
reported attempt for a few cases (noir specifically) even though an
earlier attempt in the same run scored higher — the agent may think
it's already satisfied the guardrail's requirement on a later attempt
and stop bothering to actually move anything.

**Loose end, not yet root-caused:** `tonemapping_added=True` kept
reappearing for the Mess Hall scene across different cases in this run,
even though the Neutral override was added and (believed) saved earlier
this session — meaning it isn't persisting to the `.unity` file across
scene switches/reloads. Harmless today (same default re-added each
time, idempotent), but worth checking next session whether `save_scene()`
is actually being called after `ensure_scene_ready()` adds it, or
whether the Volume GameObject itself isn't surviving a scene reload for
some other reason.

## 2026-11-26 (cont'd again): spatial-grounding fix — horror 4/10 -> 7/10, confirmed on first retest

Discussed the suite's failure pattern directly with Eran. Checked the
actual archetype instructions rather than guessing — they already say
exactly the right thing ("KEY must visibly shape the SPACE... a real
falloff gradient on the floor/walls... not just glow at its own position
while everything nearby stays black," FILL "never fully off, 10-30% of
key"). The agent's own `reasoning` text for failing attempts echoed this
exact language almost verbatim while still choosing `range=2.0-4.6` in
rooms with a ~20+ unit diagonal — not a missing-concept problem, an
execution-grounding problem: it understood the idea and had no number to
calibrate against.

Checked `get_scene_context()`: the scene bounding box WAS already being
given to the agent (`get_scene_bounds()`), but only framed as a placement
constraint ("don't put a light outside this box"), min/max corners with
no diagonal and no instruction connecting room scale to a `range` choice.
The model would've had to mentally derive a diagonal from six raw numbers
and then decide what that implies for `range` — nothing did that
translation for it.

Built 3 things, in order, before retesting:
1. `get_scene_context()`'s bounds section now states the diagonal directly
   (pre-computed, not left for the model to derive) plus an explicit rule:
   a KEY light's range should be at least 25-40% of the diagonal.
2. Added the same rule to the KEY/FILL/RIM instructions block as a
   craft requirement — explicitly framed as archetype-independent ("this
   is a physical sizing rule, not a mood decision").
3. Built a 4th deterministic guardrail (`RANGE_DIAGONAL_FRACTION_FLOOR =
   0.25`) checking the claimed KEY light's real range against the real
   scene diagonal (`get_scene_bounds()`) — same claim-vs-reality pattern
   as every other guardrail this session, verified state, not self-report.

Re-ran ONLY horror (the case that's failed every session this entire
project). **Result: 7/10, PASS, on attempt 2** — up from 4/10 in the full
suite run just before this fix. Notably, the guardrail never even had to
fire: attempt 1 already picked `range=8.2` on its own, purely from being
told the diagonal and the sizing rule (attempt 1 was rejected by the
existing no-transform-change guardrail instead, unrelated). Attempt 2
widened to `range=9.4`, moved the light, and the judge's critique
qualitatively changed character: "a clear top-right directional key that
creates strong, readable shadows across the room... corners and floor
fall into deep shadow, giving the space a contained, uneasy feel" — a
completely different class of critique than every prior horror attempt's
"isolated bright dots... darkness doing the work instead of light
design."

This is the strongest evidence yet that the lighting agent's conceptual
understanding was never the bottleneck — giving it one additional,
precomputed number (the diagonal) and one sentence connecting it to
`range` was enough to flip the result, with zero changes to the
archetype's creative freedom or any numeric value constraints on color/
intensity/mood direction.

**Not yet done:** re-running the OTHER failing cases (eerie_lab, thriller,
dreamlike, post_apocalyptic, noir) with this fix active — horror was
deliberately tested alone first (Eran's call) to confirm the theory
cheaply before spending a full suite run. Next session: re-run the full
suite to see how many of the other 5 failures this same fix resolves,
since the exact same judge-critique pattern was shared across all of
them.

## 2026-11-26 (cont'd again): re-ran the other 5 failures — range fix confirmed working mechanically, but not the only bottleneck

Ran eerie_lab, thriller, dreamlike, post_apocalyptic, noir with the
range/diagonal fix active. **0/5 passed**, same as before the fix in
raw pass/fail terms — but the DATA tells a more useful story than that
headline:

- **Confirmed the fix is working exactly as designed, mechanically.**
  Every single attempt across all 5 cases now picks ranges in the
  6-10 unit zone (correctly sized against the ~22.8 diagonal) — the
  undersized-range problem that caused horror's failure is gone across
  the board. The theory wasn't wrong; it just wasn't the ONLY
  bottleneck for these 5. Confirms this was worth building regardless
  of today's pass count — it's load-bearing infrastructure other fixes
  now sit on top of.
- eerie_lab/thriller/dreamlike scored the **identical 5/10** as before
  the fix — for these three specifically, range was never the limiting
  factor; whatever else the judge wants is still unmet with a correctly
  sized key.
- **post_apocalyptic hit a newly-visible real bug, not a self-report
  reliability issue.** noir's attempt 2 said outright: "The attempted
  reposition of the fill was rejected, so only the key's transform
  actually changed" — confirmed in code: `tools.py`'s
  `_check_within_bounds()` returns a REJECTION STRING (not an
  exception) when a proposed position is outside the scene's real
  bounding box, and the agent is expected to retry with a valid
  position within that same turn. Sometimes it does; here it didn't,
  and ended up reporting the rejection as a fact in its final decision
  instead of recovering from it — which then trips the
  `no_transform_change` guardrail in a loop it can't escape within 3
  attempts. This reframes the earlier "self-report mismatch" findings
  from thriller/noir in the full suite run: at least some of those
  weren't the agent fabricating a claim, they were genuine attempted
  moves that got silently rejected by a real tool-level bounds check,
  with inconsistent follow-through on reporting that rejection
  accurately in `lever_accounting`.
- **noir hit the `KEY_LIGHT_P90_LIFT_FLOOR` guardrail's own
  already-documented limitation** (flagged in that guardrail's comment
  months ago, never fixed): a legitimately strong, well-shaped key
  light (intensity=12.5, range=9.8 this run) in a spatially localized
  pool doesn't move the WHOLE-FRAME 90th-percentile brightness much if
  its pool only covers a modest fraction of the frame — the guardrail
  can't see a real, good key light that isn't also lighting most of
  the frame. The project's own prior self: "a real fix (comparing
  brightness within the key light's own intended pool/ROI rather than
  the whole frame) would be more principled" — now has a concrete,
  reproduced case motivating actually building it.

**Honest read, not spin:** the range/diagonal fix was real, verified
working, and necessary — but this session's remaining budget ran out
before closing the next two gaps it surfaced. Next session's two most
concrete next moves, in priority order:
1. Fix the position/rotation retry-on-rejection behavior — either make
   the agent reliably retry within the same turn after a bounds
   rejection (instruction fix), or have `main.py` surface the rejection
   explicitly in feedback so the NEXT attempt knows to try a different
   position (same pattern as every other guardrail-feedback loop).
2. Build the long-flagged per-light ROI brightness check instead of
   the whole-frame p90 ratio — `light_role_assignments` already tells
   us exactly which light/position is the KEY each attempt, so this is
   finally buildable with data already being collected.

## 2026-11-27: bounds padding fix + judge/agent shared lever vocabulary

Picked up priority #1 above. Eran's own hunch going in: the bounds
check was probably rejecting valid-looking placements because it had
no slack at the edges.

**Fix 1 — bounds padding.** `check_position_within_bounds()` in
`unity_bridge.py` already had its own docstring flagging this months
ago: "Strict min/max, no padding margin... if this rejects too eagerly
in practice, that's the first thing to loosen." Added
`BOUNDS_PADDING_FRACTION = 0.10` — expands the accept/reject box by
10% of each axis's own extent (scales with scene size, not a flat unit
count); the rejection MESSAGE still reports the real, unpadded bounds
so it stays an honest description of the room's actual geometry, only
the accept/reject decision itself loosened.

**Verified live, twice, on `post_apocalyptic`** (the exact case that
tripped the no-transform-change loop): both re-runs got real
position/rotation changes through on attempts 2 and 3 (verified from
the scene-state diff, not self-report) — no repeat of the stuck loop.
Score moved 4/10 → 5/10 → 4/10 (noisy, as expected for this model/
scene), still FAIL both times, but for a genuine mood-quality reason
now ("reads as dim/tidy, not harshly lit"), confirmed by eye against
the actual screenshot — not the old bounds-rejection plumbing bug.
**This fix is confirmed working and shippable; it did not, and was
never expected to, raise the mood-quality score on its own.**

**Fix 2 — judge/agent translation gap (Eran's diagnosis, verified
first).** Before building anything, checked whether the judge's
strictness itself was the problem (Eran: "the judge is a strict elite
producer, I expect him to fail more, but maybe his feedback isn't
clear enough for the agent to act on"). Loaded the actual
`post_apocalyptic` result screenshot and compared it against the
judge's critique by eye — critique was accurate (soft, evenly-lit,
orderly room, no hard shadow-shaping key), not an over-harsh judge.
Real bottleneck found instead: every deterministic PRE-judge guardrail
in `main.py` hands the agent a highly actionable fix in its own lever
vocabulary ("push key light intensity and/or narrow its range... check
whether global grading is eating the gain") — but the actual LLM
judge's feedback was dumped into `attempt_history` as raw prose
(`judgement.reasoning`) with zero translation into levers. The judge's
own instructions explicitly told it to describe pixels, never to name
a fix. The agent had to re-derive "soft shadows" → "narrow range +
raise intensity" from scratch every single attempt, a much harder
inference than the guardrails' literal recipes.

**Design, decided live with Eran:** rejected a simpler "just make the
judge add a free-text suggestion" fix in favor of giving the judge the
SAME structured vocabulary the agent already uses for itself (`Lever`
enum, `LightRole` enum), plus the real post-attempt scene state (role
assignments + real per-light intensity/range/color + global grading),
so recommendations are grounded in actual numbers, not re-guessed from
pixels. Direction-only (increase/decrease/reposition/reassign), no
target numbers — Eran's explicit call: "let the lighting agent play
with the numbers... the judge's job is to provide the direction." Also
Eran's call: since the judge now sees `light_role_assignments` and the
agent's own reasoning about them, it should be able to recommend a
ROLE SWAP too (e.g. "the light you called FILL is better positioned to
be the KEY"), not just numeric lever tweaks — a second kind of
recommendation, not folded into the `Lever` enum itself (that enum also
drives the agent's own per-attempt `lever_accounting` forcing-function,
unrelated to role assignment).

**Implementation:**
- `judge.py`: new `LeverRecommendation` model (`light_id`, `lever: Lever
  | None`, `suggested_role: LightRole | None` — exactly one of the last
  two set, `direction`, `reason`). `MoodJudgement` gained
  `recommended_levers: list[LeverRecommendation]`. `judge_mood_match()`
  takes a new optional `scene_state` string, injected into the judge's
  prompt alongside the image. Judge instructions updated to require
  1-4 concrete lever/role suggestions grounded in that real state when
  failing, direction only, "a DIAGNOSIS, not a restatement of
  `reasoning`."
- `main.py`: split `_build_role_and_state_json()` out of
  `_serialize_decision()` so the agent's own history turn and the
  judge's new `scene_state` context are built from the IDENTICAL JSON
  blocks (one source of truth, not two descriptions that could drift).
  The `JUDGE FEEDBACK` turn fed back into `attempt_history` now carries
  both the prose critique and the structured lever list. Added a
  console `[judge rec]` print per recommendation for visibility.

**Verified live, twice, on `post_apocalyptic`:** `recommended_levers`
populated correctly both runs, grounded in real light IDs/roles, e.g.
*"AgentLight_Dusty_Key: rotation | reorient to rake more across the
room instead of concentrating on the wall | The current key is
creating a localized warm patch; a harsher side angle would carve the
furniture and floor with stronger directional shadow shape..."* — a
real step up from raw prose. One cosmetic miscalibration noticed: the
judge sometimes attaches a `light_id` to a scene-wide lever
(`ambient`) that should have `light_id=None` per its own instructions
— harmless (just a noisier log line), not fixed this session, worth a
small instruction tightening later if it keeps happening.

**Not yet answered:** whether the new structured recommendations
actually move the pass rate up, only ran 2 single-case verification
passes so far (both correctly exercised the new code path, scores
stayed FAIL at 4-5/10, noisy). Next session: let it run several more
`post_apocalyptic` cycles (and ideally the other still-failing cases)
to see whether grounded lever-level feedback converges faster/higher
than the old prose-only loop did, before concluding anything about
mood-quality impact.

## 2026-11-27 (same day, later): research pass + instruction trim + key:fill ratio field

Eran's framing going in: plumbing (bounds, judge/agent vocabulary) is
done, the remaining gap is the LIGHTING AGENT's actual understanding
of lighting quality — its instructions might be too long/conflicting,
its structured output might be missing or have too many fields, and
`attempt_history`/the full prompt might be bloated. Asked for web
research on real lighting-quality/color-theory resources plus AI
engineering technique before touching anything.

**Research findings:**
- "Instruction complexity cliff" (prompt-engineering research): frontier
  models reliably satisfy ~3 stacked constraints and start dropping
  rules buried mid-prompt in long system prompts. Measured our actual
  instructions against this: `agent.py`'s system prompt was **~16,390
  chars / ~4,097 tokens** (vs. the judge's ~5,706 chars / ~1,426 tokens)
  — real grounds for Eran's "too long, might conflict" hypothesis, not
  just a guess.
- "Lighting ratio" is the real industry vocabulary for key:fill
  relationships, not our old vague "fill ≈ 10-30% of key": standard
  photography/cinema practice is 2:1 (flat/soft), 4:1 (moderate drama),
  8:1+ (strong drama/noir/horror). More precise and easier for the
  agent to reason about numerically than a percentage.
- Color-temperature/CCT psychology research (several studies):
  confirms cooler color temp -> higher arousal, warmer -> lower
  arousal/calmer, illuminance correlates with pleasure/arousal. Matches
  what the archetype section already implies intuitively — a
  confirmatory finding, not a contradiction, nothing changed here.
- Self-critique/predicted-score structured-output fields are a real,
  evidence-backed technique (stepwise self-evaluation literature) but
  cost real tokens — deliberately NOT added this session, would fight
  the trim-instructions goal; flagged as a future experiment only if
  the ratio field + trim alone don't move the needle.

**Checked and ruled out: `attempt_history` is NOT accumulating images.**
Verified in code: only the live `current_turn` each attempt carries a
screenshot; `attempt_history` only ever gets the agent's serialized
decision text and guardrail/judge feedback text, never an image turn.
History stays bounded and text-only across retries — this was Eran's
other suspicion going in, checked directly rather than assumed, and
it's not the bottleneck.

**Change 1 — trimmed `agent.py`'s instructions 44.5%** (16,390 -> 9,100
chars, ~4,097 -> ~2,275 tokens). Removed ONLY project-history narration
("Eran's call, 2026-11-25, found live that the agent reliably
retunes..." etc) — every substantive rule survived (archetypes,
3-point lighting roles, range-vs-diagonal sizing, render pipeline
order with its concrete measured compounding example, existing-lights-
not-a-constraint, the full lever menu, tools). The agent doesn't need
to know WHY a rule exists, just the rule itself; the backstory was pure
token cost on every single call.

**Change 2 — `target_key_fill_ratio` field.** Added to `MoodBreakdown`:
the agent now commits to an explicit key:fill INTENSITY ratio number
(not a vague description) before setting any light intensity, using
the real lighting-ratio convention from the research above (~2-3 soft,
~4-6 medium-contrast, ~7-10+ horror/noir/thriller). `main.py` got a new
diagnostic-only `[ratio]` console print comparing this claimed target
against the REAL measured key/fill intensities (via
`light_role_assignments` + real light state) — no guardrail yet,
deliberately observing real usage first, same caution already applied
to `LightRole`'s no-cap decision.

**Verified live, 3x on `post_apocalyptic`:**
- Scores: guardrail-rejected / 4->5 / guardrail-rejected. **Same 4-5/10
  band as every pre-trim run this project has seen — no clear
  improvement, no regression either, from 3 samples.**
- Ratio tracking is loose but real: some attempts landed close to their
  own stated target (5.0 target -> 5.0 real), others were far off (6.0
  -> 16.0, 5.5 -> 3.4). The agent is reasoning about the number, just
  not hitting it tightly yet — expected with no enforcement, not a bug.
- **New real finding, NOT fixed this session:** 2 of the 3 runs burned
  their FINAL attempt on the `no_transform_change` guardrail instead of
  ever reaching the judge. One of those two is a genuine, not just
  unlucky, bug: the agent's own `lever_accounting` claimed `position`
  changed, but the verified scene-state diff showed
  `MISMATCH=['position']` — a real self-report-vs-reality divergence,
  the same class of bug flagged before for other levers but now caught
  concretely on position/rotation specifically, on the attempt that
  matters most (the last one, with no retry left to recover).

**Honest bottom line:** the instruction trim and ratio field are both
real, defensible, low-risk improvements (shorter prompt, clearer
numeric target, nothing substantive lost) — but 3 runs is too small a
sample to say whether they move the mood-quality score, and the
self-report mismatch on the final attempt is a concrete, likely
higher-leverage target than either of today's changes. Next session's
two candidate priorities, not yet ranked: (1) run several more cycles
across more of the failing cases to get a real read on whether the
trim/ratio changes help, (2) chase the position/rotation self-report
mismatch specifically — it is silently costing whole runs their last,
best-informed attempt.

## 2026-11-27 (same day, later still): closing the agent<->judge comprehension loop

Eran's framing: plumbing between judge and agent (shared Lever/
LightRole vocabulary, real scene state) is done — but nothing forces
the agent to actually ENGAGE with what the judge told it, as opposed to
just having the text available in `attempt_history`. Asked to verify
the shared vocabulary is airtight, then add a structured field that
forces explicit reasoning about whether the judge's feedback was
understood.

**Vocabulary check:** `LeverRecommendation.lever`/`suggested_role`
(judge.py) import the EXACT same `Lever`/`LightRole` enum classes as
`LeverUsage`/`LightRoleAssignment` (agent.py) — not duplicated string
literals that happen to match, the literal same Python enum, no drift
possible. Confirmed clean.

One real gap found and closed: the judge's `scene_state` context
(added last session) included real light/role/grading state, but NOT
the agent's own committed `target_key_fill_ratio` from this session's
earlier change — the judge had no way to compare the agent's STATED
intent against the real numbers it was also being shown. Fixed:
`judge_scene_state` in `main.py` now opens with the agent's committed
archetype/contrast/target_key_fill_ratio before the real light state,
explicitly inviting the judge to call out a gap between intent and
reality.

**Change — `JudgeFeedbackAcknowledgment` structured field.** Added to
`LightingDecision`, placed BEFORE `reasoning` (has to inform the plan,
not describe it after). One entry per recommendation the judge gave
after the LAST attempt (empty list on attempt 1 or after a
guardrail-only rejection): `lever`/`suggested_role` echoed back from
the judge's own recommendation shape, `light_id`, `addressed: bool`,
`note`. Same forcing-function pattern that already fixed
`light_role_assignments`/`lever_accounting` — prose context alone
wasn't enough, explicit structured accounting was what worked those
two times, so applied here too. `main.py` prints `[ack]` lines and
cross-checks `addressed=True` claims against the SAME verified lever
diff already used for `lever_accounting`'s MISMATCH check.

**Verified live, 1x on `post_apocalyptic`:**
- The mechanism works as designed: the agent's attempt 3 acknowledged
  all 4 of attempt 2's judge recommendations (fill intensity down, key
  intensity down, skybox swap, harsher grading), every one correctly
  matched to the real diff, `addressed=True` across the board.
- **Real structural tension exposed, not a comprehension bug:** that
  same attempt 3, having faithfully done everything the judge asked,
  then got guardrail-rejected on `no_transform_change` anyway — none
  of the 4 judge recommendations that attempt happened to mention
  position/rotation, so an agent that fully engages with judge feedback
  can still walk straight into the separate, judge-blind transform
  guardrail with nothing left on its list to satisfy it. This is a real
  conflict between two independent feedback sources (judge
  recommendations vs. the deterministic per-attempt transform
  requirement), not the agent ignoring anything.
- Small rough edge: one acknowledgment (skybox) left both `lever` and
  `suggested_role` unset instead of echoing `lever=skybox` back —
  cosmetic (only affects the console label, not the MISMATCH logic,
  which only fires on `lever`-typed entries), but a small sign the
  vocabulary mirroring isn't perfectly tight yet.

**Not yet decided:** how to resolve the judge-feedback vs. transform-
guardrail tension found above — options include teaching the agent
explicitly that the transform requirement applies regardless of what
the judge asked for, treating it as an implicit standing recommendation
every attempt, or loosening the guardrail itself now that
`target_key_fill_ratio`/acknowledgments give the agent more to work
with. Flagged for discussion, not resolved this session.

## 2026-11-27 (same day, discussion continued): spatial grounding + reasoning/acknowledgments fed to the judge, WITHOUT reopening statelessness

Discussed resolving the judge-feedback-vs-transform-guardrail tension.
Eran's read: option 2 (give the judge spatial understanding, like the
lighting agent already has) over option 1 (just tell the agent the
transform rule stands regardless) — but then raised a bigger point:
the judge gets re-derailed every call because it's stateless and has
no idea what it told the agent last time or whether that landed, so
its recommendations can't build on anything. Proposed giving the judge
conversation history to fix this.

**Pushed back, explicitly, before building anything:** the judge's
statelessness is a DELIBERATE anti-sycophancy guardrail from
2026-11-26 — a judge that remembers its own past scores gets tempted
to score a "trying to improve" frame higher regardless of whether it
earned it. Conversation history would reopen exactly that, since score
and recommendation come out of the same call, you can't hand it memory
for "better recommendations" without also handing it memory of its own
past verdict.

**Resolved, together:** keep the judge's SCORING stateless (fresh
`Runner.run`, no history, never sees its own prior score/reasoning —
untouched) but feed it, as plain per-attempt context (not memory):
1. The once-per-scene spatial breakdown (`spatial_agent.py` — cached,
   mood-blind, geometry-only anchors with suggested light positions).
   Already built for the lighting agent; just needed piping into the
   judge too.
2. The agent's own `reasoning` for the CURRENT attempt (its stated
   intent — explains non-light choices like grading/skybox that
   `light_role_assignments` alone doesn't capture).
3. `decision.judge_feedback_acknowledgments` for the CURRENT attempt —
   what the judge recommended LAST round and what the agent says it
   did about each item, already cross-checked by `main.py` against the
   real diff. This is data the AGENT just produced this attempt, not
   the judge's own memory of anything — the key distinction that keeps
   this from being conversation history in disguise.

**Implementation:** `main.py`'s `judge_scene_state` now includes all
three blocks (spatial text via `format_spatial_breakdown_for_prompt`,
`decision.reasoning`, and a formatted `ack_text` built from
`judge_feedback_acknowledgments`). `judge.py`'s instructions updated:
use the spatial anchors to recommend SPECIFIC coordinates when a key
light's pool misses a real anchor, not just "reposition it"; if the
acknowledgments show a prior recommendation was genuinely addressed
and the problem persists anyway, recommend a DIFFERENT lever next
time instead of repeating the same advice.

**Verified live, 1x on `post_apocalyptic`:**
- All 4 acknowledgments correctly addressed and verified against the
  real diff (same mechanism as last section, still working).
- **Real behavior change observed**: the judge's attempt-3
  recommendation was POSITION/ROTATION-specific ("reposition off-axis
  toward the back-center cluster", "aim lower and more obliquely") —
  the old judge almost never recommended spatial moves; this is the
  gap the spatial grounding was meant to close, and it visibly did on
  this run. No `no_transform_change` guardrail miss this run either
  (attempts 2 and 3 both had real position/rotation changes).
- Still FAIL, 5/10, same critique shape ("too orderly/clean/staged,
  not harsh/decayed enough"). One run is a mechanism check, not proof
  of a score lift — the actual mood-quality ceiling for this case is
  still open.

**Still open, not yet decided:** does richer judge recommendations
alone close the mood-quality gap for `post_apocalyptic` and the other
stuck cases, or is there a deeper issue (scene content ceiling, model
capability, something else)? Needs more runs across more cases before
concluding anything — explicitly NOT doing that right now per Eran's
"no more runs" call this session; next session's call.

## 2026-11-27 (same day, the real diagnosis): the content-ceiling leak, root-caused

Eran's framing: "we're stuck at 5/10, we need to understand what the
judge is MISSING to give better, concise, accurate critique" —
investigated by pulling every `post_apocalyptic` judge verdict logged
today (`mood_test_log.jsonl`) and looking at the actual result image,
not just re-reading prose.

**Root cause found, and it's not a judge-comprehension bug.** Every
single verdict used the identical vocabulary: "staged," "tidy,"
"showroom," "gamey," "orderly," "clean," "intact." Loaded
`screenshots/post_apocalyptic/latest/result.png` directly: this is a
cute, flat-shaded, low-poly "toy" art style — pastel colors (mint-green
bench, cream walls, white vending machines), perfectly clean floor
tiles, a glowing neon arcade sign, zero grime/wear/damage anywhere in
the geometry. **The judge's critique was factually accurate** — no
amount of harsh lighting makes a pastel toy-store room read as
"ravaged," because the problem isn't lighting, it's the scene's own
geometry and art style. This directly re-confirms a finding this
project already made and recorded on 2026-11-23: "lighting alone cannot
manufacture 'post-apocalyptic'... needs actual scene CONTENT (debris,
decay) that a sci-fi mess-hall scene structurally doesn't have."

**Eran's real objection, once this was named explicitly:** the judge's
JOB is to critique lighting, full stop — this product's actual use
case is checking lighting on an ALREADY-MODELED scene with no ability
to change geometry, so a judge that fails the lighting agent for the
level designer's asset choices is a broken product, not an honest
score. Discussed two ways to fix this: (1) make the judge lighting-only
and strip scene-modeling judgment entirely, or (2) build a NEW
geometry-placement agent that can insert decay/debris assets. Pushed
back hard on (2): this directly reopens the 2026-11-20 business
decision ("v5/geometry transformation is killed, not parked, product
scope is lighting/rendering only") — a much bigger, harder problem than
lighting, and not something to reach for before (1) is tried.

**Why the existing soft instruction ("don't deduct for missing props")
already failed, and why a stronger instruction wouldn't fix it either:**
the judge is a vision model scoring a single holistic
`mood_match_score` from a single holistic visual impression — there was
exactly one number for a content-driven vibe to attach to, no matter
how firmly worded the "ignore content" instruction was. This needed a
structural fix, not a better-worded rule.

**Redesigned `MoodJudgement` (judge.py), real breaking change to the
scoring model:**
- Replaced the single free `mood_match_score` with 4 explicit
  LIGHTING-ONLY craft axes, each answerable from lighting alone
  regardless of scene content: `contrast_execution` (brightness
  spread matches the mood's contrast target), `color_story_execution`
  (palette/temperature supports the mood), `shadow_structure` (real
  key/fill/rim falloff vs. "a few bright dots" — the axis that catches
  the small-self-illuminating-props failure mode), `key_light_dominance`
  (key's bright zone clears the real baseline, not just a big intensity
  number).
- `mood_match_score` is now COMPUTED IN CODE (`judge_mood_match()`,
  equal-weighted average of the 4 axes, rounded) — the model's own
  field for it is a discarded placeholder (described as "LEAVE AS 0").
  Structurally, there is no field left for a content vibe to attach to.
- Added `content_ceiling_note: str | None` — the ONE place
  content/geometry observations are explicitly invited, and it is
  NEVER read for scoring. This is where "staged/tidy/showroom" language
  belongs from now on.
- `judge_agent`'s instructions rewritten around the new per-axis
  rubric, explicit "do not let X leak into the 4 numeric axes, it
  belongs in content_ceiling_note" framing, same calibration content
  (dim≠dramatic, practicals≠key) remapped onto the specific axis it
  belongs to. `main.py` prints `[judge axes]` and `[content ceiling,
  NOT scored]` lines, and logs all 4 axes + the note into
  `mood_test_log.jsonl` for future visibility without re-reading prose.

**Verified live, 1x on `post_apocalyptic` (real diagnostic win, not
just a mechanism check):**
- `content_ceiling_note` fired on both judge calls this run, explicitly
  marked uninvolved in scoring: *"the room design itself is compact and
  orderly, which limits how 'ruined' or chaotic the scene can ever
  feel, but that is not the main issue here; the lighting still needs
  stronger spatial shaping."*
- Every score-driving critique this run was a genuine, actionable
  LIGHTING complaint: "key still isn't clearing the room," "leftover
  practical competing as a weak source," "fill too timid," "grading
  still flattening the scene." Zero content language in anything that
  touched a score.
- Still FAIL, 5/10 — same NUMBER as several pre-redesign runs, but the
  qualitative nature of the gap flipped from "unfixable, the furniture
  is too clean" to "fixable, push the key harder and reposition the
  leftover practical." That qualitative shift is the actual point of
  this change, not the number itself.

**Open for next session:** does the now-cleanly-separated lighting
critique actually converge to a pass with more attempts/runs (not done
today, one verification run only), and does this same redesign also
unstick `eerie_lab`/`thriller`/`dreamlike` (the other cases stuck at
5/10 since months ago) the same way, or were those stuck for a
genuinely different reason that this fix doesn't touch.
