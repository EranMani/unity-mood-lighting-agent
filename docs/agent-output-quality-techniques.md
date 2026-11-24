# Agent output quality techniques — reference

Living doc, started 2026-11-23. Each entry: what we did, why it actually
works (the mechanism, not just "it's a known trick"), where it applies
and where it doesn't, and what we actually verified live. Add to this
file as new techniques get tried on this project, don't start a new one
per technique.

---

## Reference: `ModelSettings` — the knob panel between Agent and the raw API call

Came up while investigating whether our agents do any hidden reasoning
(see Technique 1's native-CoT section below) — worth its own reference
entry since it's the control surface for ANY future tuning of either
agent, not just reasoning.

**The mental model split:**
- **Agent-level config** (`instructions`, `tools`, `output_type`,
  `name`, which model) — defines WHAT the agent is / does.
- **`ModelSettings`** — tunes HOW the actual API call to that model is
  made. Passed via `Agent(model_settings=...)` or per-run via
  `Runner.run(..., run_config=RunConfig(model_settings=...))`. Every
  field defaults to `None` — unset means "use the provider's own
  default for this model," not "off."

**The fields, grouped by what they actually control:**

| Group | Fields | What they do |
|---|---|---|
| Sampling/randomness | `temperature`, `top_p`, `frequency_penalty`, `presence_penalty` | How random/repetitive output is |
| Tool-calling behavior | `tool_choice`, `parallel_tool_calls` | Force a specific tool vs let the model choose; allow multiple tool calls per turn or not |
| Reasoning | `reasoning`, `verbosity` | How much internal deliberation effort a reasoning-capable model spends before answering, and how verbose the visible output is |
| Output limits | `max_tokens`, `truncation`, `top_logprobs` | Caps response length, context-overflow handling, per-token confidence data |
| Observability/infra | `metadata`, `store`, `include_usage`, `response_include`, `prompt_cache_retention`, `prompt_cache_options`, `preserve_raw_usage` | Tracing, caching, usage-tracking — not behavior |
| Reliability | `retry`, `timeout`, `context_management` | Retry policy, request timeout, how conversation history gets trimmed if it overflows |
| Raw passthrough | `extra_query`, `extra_body`, `extra_headers`, `extra_args` | Escape hatches straight to the underlying API client for anything the SDK doesn't wrap yet |

**Current state of this project (checked live, not assumed):**
`dataclasses.fields(ModelSettings)` confirmed every field defaults to
`None`; grepping `agent.py`/`judge.py` found zero occurrences of
`model_settings` anywhere. Neither the lighting agent nor the judge has
ever had ANY of these tuned — both run on `gpt-5.4-mini`'s raw
defaults for sampling, reasoning effort, tool_choice, everything.

**Decided live with Eran (2026-11-23):** don't touch any of this
speculatively. Run the full eval suite first and look at the real
numbers. Only reach for `ModelSettings` (most likely candidate:
`reasoning`, to force more deliberation effort) if the results show an
actual quality problem worth solving — tuning knobs before you've
measured whether there's a problem is the same mistake as adding a
guardrail nobody's hit yet.

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

**How much does this actually matter for results, not just debugging?**
This is the real engineering question, and the honest answer is: it
depends entirely on whether meaningful hidden reasoning is actually
happening, and you usually don't know that unless you check.

- The Agents SDK's `ModelSettings` dataclass has a `reasoning` field —
  checked live: `dataclasses.fields(ModelSettings)` shows it defaults
  to `None`. Then checked this project's actual code: **zero**
  occurrences of `model_settings`/`reasoning` anywhere in `agent.py` or
  `judge.py`. Neither agent has ever configured a reasoning effort.
  That means both are running on whatever `gpt-5.4-mini`'s own default
  is — and "mini"/fast model tiers commonly ship with reduced or
  minimal reasoning budget by default, specifically to keep latency
  and cost down. **We don't actually know how much, if any, hidden
  deliberation is happening on these calls**, and the honest
  engineering move is to not assume there's meaningful hidden
  reasoning covering for you, rather than hope it does.
- This is exactly why the explicit `reasoning` field matters more than
  it might look like on paper: if there's little or no hidden
  deliberation happening (plausible, maybe likely, on an unconfigured
  mini-tier model), the explicit field isn't a nice-to-have alongside
  "probably good enough" native reasoning — it's the **only**
  mechanism actually forcing the model to generate grounded
  observations before committing to a score. Remove it, and on this
  specific setup, there may be no deliberation step at all between
  "look at image" and "produce a number."
- Even on a model that DOES have strong native reasoning turned on,
  the explicit field still isn't redundant, for two separate reasons:
  (1) **faithfulness isn't guaranteed** — a model's hidden reasoning
  and its final visible answer can diverge (a documented failure mode
  in reasoning-model research: the chain of thought doesn't always
  cause the final answer, it can rationalize one reached some other
  way). An explicit field the final score is positioned right after,
  in the same visible context, gives the score something concrete and
  recent to actually condition on, rather than relying on whatever
  happened in a separate, unverifiable internal channel. (2) hidden
  reasoning, even when it exists, is often not returned by the API at
  all, or only as a compressed summary — you can't log it, diff it
  across runs, or debug a bad judgement against it. The explicit field
  costs a handful of extra output tokens and buys genuine inspectability
  either way.
- **The practical rule, not just for this project:** never assume a
  model is doing invisible deliberation you haven't explicitly
  configured and verified. If a task needs grounded, deliberate
  output, engineer that deliberation into something you control (field
  order, explicit prompting) rather than hoping reasoning_effort
  defaults are doing it for you silently. Checking `ModelSettings`
  instead of guessing took one function call — worth doing before
  asserting anything about what a model is or isn't doing internally.

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

---

## Technique 2: diagnosing model vs. instructions vs. architecture — the order to check, and why

**The problem this solves:** when a pipeline produces a result you
don't trust (e.g. a judge passing something that visually looks dull,
not dramatic), there are three structurally different possible causes —
the model's own capability/configuration, the instructions it was
given, or the surrounding architecture (schema, field order, what's
even required) — and they need genuinely different fixes. Guessing
which one is at fault, or reaching for the most familiar lever
(`ModelSettings` — temperature, reasoning effort) without evidence,
wastes effort and can hide the real cause. This came up directly
2026-11-24: Eran asked, when a judge passes something a human wouldn't,
how do you know whether to blame the model, the instructions, or the
architecture — the answer below is the method, with this project's own
case as the worked example.

**The checking order — cheapest and most likely first, most expensive
and least likely last:**

1. **Architecture/output structure, check first, free to check.** Open
   the actual raw structured output, not just the final score/answer.
   Is a reasoning-style field present, required, and ordered BEFORE the
   conclusion (see Technique 1 above)? Is it populated with specific,
   concrete detail, or generic filler that could apply to anything? A
   thin, generic, or absent reasoning field — or a final answer that
   doesn't logically follow from its own stated reasoning — points at
   architecture, not capability. This is the cheapest check (just read
   the output) and the most common real cause, fix it before anything
   else.

2. **Instructions/spec, check second.** Read what the model actually
   said in its reasoning, word for word. The test: *if a smart human
   intern followed these exact written instructions, and nothing else,
   would they make the same mistake?* If yes, it's the instructions,
   not the model. A model that produces coherent, specific, well-
   grounded reasoning but applies the WRONG criterion (because the
   instructions never defined that criterion precisely) is doing
   exactly what it was told — that's a spec bug.
   - **The decisive proof, not just a guess**: change ONLY the
     instruction text — same model, same `ModelSettings`, same input —
     and see if behavior changes. If it does, it was never a model
     problem; a real capability limitation can't be fixed by words
     alone. If changing the words changes nothing, that's evidence
     pointing further down this list.

3. **Model/configuration itself, only with positive evidence, not
   because 1 and 2 didn't occur to you first.** Suspect this when:
   instructions are unambiguous and reasoning is required/grounded, yet
   the final answer still contradicts its own stated reasoning (a real
   consistency failure); OR the exact sub-skill, isolated in a minimal
   test with maximum clarity and nothing else in the prompt, still
   fails (a real capability gap); OR the identical prompt run multiple
   times with nothing changed gives wildly different results (variance
   — check `temperature` specifically, that's the one setting that's
   actually about this). `reasoning_effort`/model tier are worth
   touching only once one of these is demonstrated with a real test,
   never as a first guess.

**Worked example from this project (2026-11-24, horror mood):** Eran
flagged the `horror` and `thriller` result screenshots as visually dull
despite a 7/10 PASS score. Checked step 1 first: the judge's `reasoning`
field WAS present, required, and ordered first (Technique 1 was already
applied) — so architecture wasn't the gap. Checked step 2: read the
judge's actual reasoning text — it was specific and coherent ("cold
blue tones, isolated lighting"), not vague or hallucinated, it was
faithfully describing a real criterion, just the wrong one (conflating
"cold + dim" with "dramatic"). That's an instructions problem, confirmed
by the decisive proof: changed ONLY `judge.py`'s instruction text (added
an explicit "dim ≠ dramatic, real drama needs visible shadow shape"
clause), same model, same settings, re-ran the identical agent output —
score dropped from 7 PASS to 3/5/guardrail-rejected. Behavior flipped
entirely from a pure wording change, which is the clean proof it was
never a model-capability issue. `ModelSettings` (temperature, reasoning
effort) was explicitly considered and rejected as the first thing to
try — no test had been run that isolated model capability from
instructions, so there was no evidence pointing there, only an untested
hunch. See `docs/mood-test-results.md`'s "The 8/10 result didn't survive
human eyes" section for the full incident writeup.
