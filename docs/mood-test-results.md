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
