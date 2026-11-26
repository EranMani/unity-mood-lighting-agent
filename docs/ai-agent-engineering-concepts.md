# AI agent engineering concepts

A reference, not a chronological log (that's `docs/mood-test-results.md`).
Each entry is a general AI-engineering principle this project actually hit,
with what it looked like concretely here and what it measurably changed.
Reread this when starting a new agentic project, not just this one.

This is a broad INDEX across concepts — `docs/agent-output-quality-techniques.md`
already has full mechanism-level deep dives on reasoning-first field
ordering and the model-vs-instructions-vs-architecture diagnostic method;
this doc cross-references those rather than re-explaining them, and covers
everything else that came up across the project.

## 1. Structured output as a forcing function, not just a data format

**Principle:** prose instructions ("please try something different," "follow
key/fill/rim lighting") are *suggestions* — a model can nod along and still
not do them. A required structured field the model must fill in for every
relevant item, every turn, forces the behavior instead of hoping for it.

**Here:** the agent kept reaching for the same 1-2 levers (intensity,
grading) attempt after attempt, ignoring prose telling it to vary approach.
Fixed by adding a `Lever` enum + `LeverUsage` list the agent must fill in
exhaustively (every lever, `changed: bool` + a real reason) every attempt —
not optional, not summarized, every single category accounted for.
Immediately broke the habit. Same pattern applied again later for
`LightRole`/`light_role_assignments` (every light gets an explicit
KEY/FILL/RIM/PRACTICAL/UNUSED role + reasoning, every attempt).

**Effect:** lever-diversity bug fixed on the first retry after the schema
change. Confirmed the model *can* reason correctly about structure
(key/fill/rim) once asked to commit to it explicitly in output.

## 2. Verified state, never self-reported state

**Principle:** an agent's own account of what it did (`changes_summary`,
free-text claims) can diverge from what actually happened in the system —
not because it's lying, but because describing an action and performing
it correctly are different skills. Don't branch logic on self-report when
you can independently measure the real state.

**Here:** `main.py` never trusts `decision.lever_accounting` alone —
every attempt it independently snapshots real scene state before/after and
diffs it (`_snapshot_lever_state`/`_diff_levers`), logging any mismatch
between self-reported and verified. Caught real divergences this way.
Same principle extended to `light_role_assignments`: the serialized
conversation history includes the agent's role *claims* right next to the
REAL light state (`get_light_properties`, not self-report) measured after
the attempt — so the model can see its own claim-vs-reality gap directly.

**Effect:** this is the single most load-bearing principle in the project.
Every guardrail that matters is a check against measured reality, not
against what the model said it did.

## 3. Reasoning-first field ordering in structured output

See `docs/agent-output-quality-techniques.md`'s "Technique 1" for the full
mechanism (autoregressive generation, why field order IS generation order).
Applied here: both `judge.py`'s `MoodJudgement` (`reasoning` before
`mood_match_score`) and `agent.py`'s `LightingDecision` (`mood_breakdown`
→ `reasoning` → `light_role_assignments` → `lever_accounting` →
`changes_summary`) are ordered this way deliberately. Necessary but not
sufficient on its own — see #4.

## 4. "Score must follow reasoning" needs to be an explicit rule, not implied

**Principle:** even with reasoning-first field order, a model can still
write an accurate critique and then assign a disconnected score — the
critique and the number aren't automatically coupled just because they're
adjacent fields. If the scoring contract matters, state outright that the
number must be justified by what was just written, not merely preceded by it.

**Here:** caught live — the judge wrote "extremely dark overall...
collapses to near-black... not especially cinematic" and still scored it
6/10 PASS. Reasoning and score were disconnected despite correct field
order. Fixed by adding an explicit instruction: the score MUST follow from
what the reasoning actually describes; a reasoning full of real problems
cannot score a pass just because the mood direction was roughly right.

**Effect:** re-judged the EXACT SAME saved image, same near-identical
reasoning text, new score 4/10 FAIL. Proved the earlier pass was a scoring
bug, not a disagreement about the image — same evidence, different verdict,
purely from making the score-follows-reasoning contract explicit.

## 5. Persona design measurably changes an evaluator's behavior on identical input

**Principle:** an LLM-as-judge's score is a function of its instructions,
not purely "what's objectively in the image/data." A vague or neutral judge
persona can under- or over-score consistently; a persona with a concrete
domain-expert identity and specific failure modes to watch for changes the
actual numbers it produces, on the exact same input.

**Here:** gave the judge a persona ("elite AAA lighting producer/
cinematographer, zero patience for lazy fake-drama tricks") plus a
concrete, named failure mode to watch for (small self-illuminating props
≠ the room being lit). Re-judged the same saved frame before/after the
persona change.

**Effect:** same image, 6/10 → 4/10. Nothing about the artifact changed;
only the evaluator's framing did. A reminder that "the judge said X" is
never a neutral fact independent of how the judge was built.

## 6. Asymmetric statefulness: give the actor memory, keep the evaluator fresh

**Principle:** conversation continuity helps a model that's iterating
toward a goal (it can notice "I already tried this, it didn't work").
The same continuity HURTS a model that's supposed to independently judge
each new attempt — a judge that remembers its own past verdict is tempted
to grade a "trying to improve" result more favorably regardless of whether
it earned it. Continuity and independence are in tension; decide
deliberately which side of a two-agent system needs which.

**Here:** confirmed the judge is stateless (fresh `Runner.run()` call every
time, no memory of its own past scores) and decided to KEEP it that way —
explicitly discussed and rejected giving it history, for exactly the
anchoring-bias reason above. Instead gave the LIGHTING agent real
conversation history (see #8), since it's the side that actually needs to
notice repeated failed claims.

**Effect:** the judge stayed the reliable, independent signal that caught
the score-disconnect bug in #4; giving it memory would have risked
reintroducing a version of that same bug through a different mechanism.

## 7. Hybrid prose+JSON beats forcing everything into one format

**Principle:** when building agent-facing context (a prompt, a history
turn), don't force narrative/judgment content into structured formats it
gains nothing from, and don't leave precise record-like content as loose
prose where it can be paraphrased ambiguously. Match the format to the
content: free text for judgment, compact structured blocks for facts.

**Here:** `_serialize_decision()`'s conversation-history turns keep
`reasoning`/`changes_summary` as plain prose (nothing structural to
represent) but render `light_role_assignments`, the verified lever diff,
and the real light state as small JSON blocks (specific IDs and measured
numbers that shouldn't be paraphrased loosely). The alternative — one
giant JSON blob including the narrative fields — was considered and
rejected: this history's only consumer is the model's own next turn, not
a database, so model-readability was the actual design goal, not uniform
machine-parseability (there's already a separate structured log,
`mood_test_log.jsonl`, for that need).

**Effect:** avoided unnecessary escaping/verbosity on narrative fields
while keeping precision exactly where ambiguity would have cost something
(which light had which role, across several similarly-named lights).

## 8. Close the claim-vs-reality loop explicitly, in the agent's own context

**Principle:** when a model makes a structured prediction about the effect
of its own action ("this light will shape the room"), the most direct way
to correct a systematic gap between its predictions and reality is to put
the verified outcome back in front of the model, next to its own claim, in
its own words — not to just add a rule trying to prevent the gap in the
abstract.

**Here:** the real conversation-history rebuild (attempt_history as real
assistant/user turns instead of a flattened recap) exists specifically so
a future attempt can see "I called light X my KEY" directly beside "light
X's real intensity was Y" from `get_light_properties`. This is the
concrete mechanism behind #2 and #6 working together.

**Effect:** verified live — the agent's own role claims evolved coherently
attempt to attempt in the same run (fixtures reclassified fill → practical
→ unused as it moved real work onto its own created lights), consistent
with it tracking its prior claims rather than re-deriving them from a
paraphrase each time.

## 9. Guardrails are safety nets on both tails, never a creativity limiter

**Principle:** a guardrail should reject genuinely broken/unsafe output
(crushed to black, zero real change) — it should never narrow the
legitimate creative range by rejecting something merely unusual. When a
guardrail is miscalibrated, the fix is recalibration against real
evidence, not permanently tightening scope to avoid the failure mode.

**Here:** established and re-applied repeatedly — e.g. the grading-severity
formula initially penalized negative saturation (full B&W desaturation,
a legitimate noir technique) the same as a real exposure crush; fixed once
confirmed URP's saturation is luma-preserving and doesn't actually reduce
brightness, so only over-saturation still counts as risk.

**Effect:** a real noir attempt that was wrongly rejected (severity 4.44
vs. floor 3.9, almost entirely from the saturation term) now computes to
2.44 — correctly passes the same guardrail without loosening it for
genuinely risky cases.

## 10. Isolate variables before trusting a calibration measurement

**Principle:** when sweeping one variable to find its real working range,
every OTHER variable that could independently suppress the signal has to
be controlled (zeroed or held at a known-neutral value) first — otherwise
a confound masquerades as the thing you're measuring.

**Here:** an intensity sweep inside a scene state that still had leftover
aggressive grading (contrast=58+, heavy vignette) suggested intensity
needed to reach 50,000 to matter. Re-swept properly isolated (one light,
zero ambient/grading first, then realistic moderate grading) — real=200
alone reproduced the project's whole-history "good baseline" brightness.
The "50,000" number was real artifact of a confounded measurement, not of
the actual intensity scale.

**Effect:** avoided committing to a 250x-too-large conversion factor that
would have been calibrated against a contaminated measurement.

## 11. Verify via official docs AND a live test — neither alone is enough

Related to `docs/agent-output-quality-techniques.md`'s "Technique 2"
(cheapest/most-likely-cause-first diagnostic order) — same discipline,
applied to a platform/library question instead of a model-vs-instructions
question.

**Principle:** when investigating whether a platform/library behaves a
certain way, check authoritative documentation before writing any fix code
(don't guess-then-patch) — but also don't stop at the docs alone, confirm
empirically, since docs can describe an unused/irrelevant code path or be
stale.

**Here:** before touching any code for the intensity-scale bug, searched
Unity's own official URP/HDRP docs to check whether a legacy/physical
light-units toggle existed. Docs showed URP's documented DEFAULT is the
small legacy-style scale (not forced physical units) — which could have
been read as "nothing to fix here." Instead of stopping there, tested
empirically: switched the scene's own `lightUnit` tag (Candela↔Lumen) at a
fixed intensity and measured a byte-identical render — proving the tag is
inert in URP regardless of what the docs imply about defaults.

**Effect:** confirmed, not assumed, that no toggle existed to flip and a
real code-level conversion was the only path — avoided both an impulsive
code change based on a hunch AND a false "docs say it's fine" dead end.

## 12. Boundary-only conversion layers instead of a system-wide rewrite

**Principle:** when a scale/unit mismatch is found deep in a dependency
(here: Unity's real light-intensity math needing ~10x the project's
assumed numbers), the lower-risk fix is a conversion at the smallest
possible number of I/O boundary points — not propagating the new scale
through every guardrail, instruction, and historical reference that
assumes the old one.

**Here:** `LIGHT_INTENSITY_REAL_PER_NICE` + `nice_to_real_intensity()`/
`real_to_nice_intensity()`, applied ONLY at the two agent-facing boundary
functions (`set_light_properties` write, `get_light_properties` read).
Every guardrail, instruction, and doc that reasons in the familiar 0-20
scale needed zero changes.

**Effect:** the entire fix was two functions and two call sites, not a
rewrite of every number in the codebase — and it's reversible/adjustable
in one place if the real multiplier ever needs revisiting.

## 13. A structural fix can silently corrupt data that predates it — audit, don't just add

**Principle:** when changing what a stored value MEANS (not just how it's
produced going forward), anything already on disk in the old meaning needs
an explicit migration check — a "the field is just a number" assumption
will silently misinterpret old data under the new rule.

**Here:** the original scene's baseline-captured light intensities (0.81,
2.17) predated the intensity-scale conversion — plain small numbers, never
meant to be divided by anything. The new read-side conversion
unconditionally divides by 10 on every read, so these pre-existing numbers
started reporting as 0.081/0.217 — double-dividing values that were never
"real"-scaled to begin with.

**Effect:** caught before it did real damage (the original fixtures would
have looked permanently, silently negligible) by explicitly re-migrating
the baseline (re-writing the true historical values through the new write
path, recapturing). General lesson: a "fix the read/write path" change is
incomplete without an audit of already-stored values under the new
contract.

## 14. Split code-decided guardrails from LLM-judged quality, by cost and reliability

**Principle:** reserve the expensive, subjective LLM judge call for
genuinely holistic quality questions. Catch cheap, objective, or
arithmetic-checkable failure classes with deterministic code first — it's
faster, free, and more reliable than hoping an LLM notices the same thing
every time.

**Here:** the pre-render `_grading_severity` arithmetic guardrail, the
pixel-stat visibility/contrast checks, and the transform-mandate guardrail
all run BEFORE any render or judge call, rejecting likely-crushed or
clearly-non-compliant attempts for free. The judge is only ever called on
an attempt that already passed every deterministic check.

**Effect:** several real crush bugs this project chased across multiple
sessions were caught and fixed at this cheap layer, without ever needing
the judge to reliably notice "this is basically black" — which pixel
statistics do far more reliably than an LLM glancing at an image.
