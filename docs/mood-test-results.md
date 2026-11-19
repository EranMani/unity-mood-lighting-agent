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

## Score summary

- **3 of 5 distinct moods passed** (horror, eerie abandoned lab, golden hour sunlight)
- **2 of 5 failed** (cozy cafe, sci-fi thriller) — both for the same
  reason: not enough light-only levers to change, it's a content mismatch
- Re-testing the thriller mood with a higher light cap (10 vs 6) did
  **not** change the outcome (4/10 both times) — confirms light count was
  never the real blocker for that mood

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
