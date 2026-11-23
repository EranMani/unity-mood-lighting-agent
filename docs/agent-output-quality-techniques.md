# Agent output quality techniques — reference

Living doc, started 2026-11-20. Each entry: what we did, why it actually
works (the mechanism, not just "it's a known trick"), where it applies
and where it doesn't, and what we actually verified live. Add to this
file as new techniques get tried on this project, don't start a new one
per technique.

---

## Technique 1: reasoning-first field order in structured output

**What we did:** `judge.py`'s `MoodJudgement` schema had a `notes`
field, positioned LAST, described as "debugging only, not branched on."
Renamed it to `reasoning`, moved it to be the FIRST field (before
`mood_match_score`), and told the judge agent explicitly to write that
field before deciding the score, not after.

```python
# Before (score decided with no visible deliberation):
mood_match_score: int
dominant_color_temp: str
contrast_level: str
notes: str  # last, "debugging only, not branched on"

# After (score is grounded in reasoning already generated):
reasoning: str  # FIRST — describe what the image shows before scoring
mood_match_score: int
dominant_color_temp: str
contrast_level: str
```

### Why this actually works (the mechanism, not just "it's common")

LLMs generate tokens **autoregressively** — left to right, one at a
time, each new token conditioned on every token already generated
(including the model's own prior output in this same response, since
it's all in the same context window as it generates).

A structured-output call (`output_type=SomeModel` in the Agents SDK, or
any JSON-schema-constrained response) forces the model to fill fields
in a **fixed order**. Whatever order the schema declares is the order
the model is forced to generate in.

If the score field comes first, the model has to commit to a number
with **zero prior deliberation in this response** — there's nothing
in its own generated output yet to reason from, only the raw image
input. Any following "notes" field then has to retroactively justify a
number that's already locked in, which is backwards — it can rationalize,
not actually inform, the score.

If the reasoning field comes first, the model generates a textual
description of what it actually observes BEFORE being forced to
produce a number. That description becomes part of the context the
score field is then generated from — the score is now conditioned on
real, specific observations already sitting in the model's own
generated output, not just a fast pattern-match from image to mood
word. This is the same core idea as chain-of-thought prompting, but
applied to field ORDER inside a schema instead of free-text prompting.

**The key insight for an AI engineer:** a model has no "private"
scratch space separate from its visible output (unless it's a native
reasoning model with hidden chain-of-thought tokens — see the note
below). Whatever it needs to have "thought about" before a decision has
to actually exist as generated tokens somewhere before that decision
point. Field order in a structured-output schema is a lever you control
directly, and it's often invisible if you're not looking for it —
"notes" tacked on at the end of a schema looks harmless but is
structurally useless for improving the decision above it.

### Where this applies, and where it doesn't

- **Applies to:** any schema-constrained / structured-output call
  (`output_type` on an Agent, raw JSON-schema-forced completions,
  Pydantic response models). The judge (`judge.py`) is exactly this
  shape — one call, one schema, no tools.
- **Does NOT directly apply to:** tool-calling agents with no
  `output_type`, like this project's lighting agent (`agent.py`). It has
  no fixed schema to reorder — its "output" is a sequence of tool calls
  plus free text, not one JSON blob with field order. Forcing the
  equivalent discipline there would need a different mechanism entirely
  (e.g. a required `reasoning` parameter on every tool call), which has
  a real cost (friction on every single call) and wasn't applied here
  without first seeing evidence the lighting agent's decisions actually
  need more deliberation — decided live with Eran to hold off,
  speculative guardrails/costs aren't added without a observed problem
  to justify them (same discipline as everything else in this project).

### Relation to native chain-of-thought (a different mechanism, worth knowing)

Some models (o1/o3-style "reasoning" models, and reasoning-mode
variants of GPT-5) generate hidden reasoning tokens internally before
their visible output, without needing a schema trick at all. That's a
model-level capability, not something you engineer via field order.
The difference that matters practically: native hidden reasoning isn't
inspectable or loggable (you can't read what it "thought"), while an
explicit `reasoning` field in your own schema IS visible, logged,
diffable across runs — you can go back and read exactly what the judge
saw before scoring something low. For a project where debugging *why*
a mood judgement came out a certain way matters (this one, given the
retry-loop feeds judge feedback into the next attempt), explicit >
hidden, even on a model that also does native reasoning underneath.

### Verified live, not just "it's a known technique"

Ran `judge_mood_match('horror')` against the then-current scene state:
the `reasoning` field came back with specific, concrete visual
observations ("small blue wall lights and bluish screen glows... reads
more like a sparse retro game room or office than a horror setting")
before the score, not generic filler. Re-ran the horror/golden_hour
eval cases afterward — both passed (horror flipped from a 5/10 fail the
run before to 6/10 pass). **Honest caveat, not overclaimed:** that
flip is one data point, and this project already has documented,
measured evidence of real run-to-run LLM non-determinism right at the
pass threshold (`eerie_lab`/`noir` flipped before with zero code
changes, see README step 27). One improved run after a prompt/schema
change is suggestive, not proof of causation — would need several runs
to actually claim this technique measurably improved pass rates here.
