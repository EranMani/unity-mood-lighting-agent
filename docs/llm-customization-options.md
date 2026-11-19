# LLM customization options — when to use what

Written after hitting a real case in this project: the lighting agent
"failed" at horror mood, and the fix was adding a tool (`create_light`),
not teaching it lighting theory. That's the core lesson this doc exists to
capture — most "the model doesn't know X" problems are actually "the model
has no way to act on X," and the fix tiers are very different in cost.

## The core distinction

**Model already knows it, just needs a way to use it** → give it a tool
(or better instructions on tools it already has). This was our case:
gpt-5.4-mini almost certainly already knows three-point lighting (key/fill/
rim), color temperature, horror-film lighting conventions — general
training-data knowledge. It wasn't producing good horror lighting because
it had no `create_light` tool, not because it didn't understand horror
lighting. Giving it the tool (with a one-line docstring hint, not a
lighting-theory lecture) was enough — it created a sensibly-named,
sensibly-placed "Horror Rim Light" on its own.

**Model doesn't know it at all, or needs YOUR specific facts** → that's a
different problem (retrieval, or genuinely new knowledge), see below.

## The tiers, cheapest/fastest to most expensive, in order you should try them

### 1. Tool definitions + docstrings
What it is: give the model a new capability (a function it can call), with
a clear description of what it does and when to use it.
Cost: near-zero. No training, instant to add, fully reversible.
When to use: the model has the reasoning but not the capability. Almost
always the first thing to check — "does a tool for this even exist?"
before assuming the model's judgment is the problem.
Our example: `create_light` tool. The model already knew WHY you'd want a
second light for contrast; it just had nothing to call.

### 2. Prompt instructions (system/agent instructions)
What it is: plain English guidance in the agent's instructions about when
and how to use what it already has.
Cost: near-zero, instant, reversible.
When to use: the model has the tool but doesn't reliably reach for it, or
needs nudging on priorities/conventions specific to your domain (e.g. "use
Unity's rotation convention, not your intuition" — but note: even this
only works because the model already understood euler angles in general,
we just had to point it at Unity's specific convention).
Real trap we hit: build log #2 — a tool existed but was never mentioned in
instructions, so the model just didn't know to call it. Not a reasoning
failure, a documentation failure.

### 3. Few-shot examples in the prompt
What it is: 2-3 concrete example (input -> correct tool calls/output) pairs
embedded in the prompt itself, not weights.
Cost: low — slightly more tokens per call, no training, instant, reversible.
When to use: instructions alone keep producing the same wrong shape of
output, and showing beats describing. E.g. if the model kept mis-naming
light roles or mis-ordering tool calls, showing one correct example often
fixes it faster than more adjectives in the instructions.
We haven't needed this yet in this project — plain instructions + good
tool docstrings have been enough.

### 4. RAG / retrieval (not really "customization," different problem)
What it is: give the model facts it has no way to know (your private docs,
your specific API, data past its training cutoff) by fetching and
injecting them into context at call time.
Cost: moderate — needs a retrieval pipeline (embeddings/search), but no
training.
When to use: the gap is MISSING FACTS, not missing reasoning or missing
capability. Not relevant to our rotation/lighting-theory problems since
that was all general knowledge the model already had — would be relevant
if, say, we needed the model to know OUR specific scene's naming
conventions or an internal style guide it couldn't infer.

### 5. Fine-tuning
What it is: actually retrain the model's weights on your own labeled
examples, producing a custom model checkpoint.
Cost: high — needs a training pipeline, a real dataset (often hundreds+
of examples), compute, evaluation, and redeployment each time you want to
change behavior. Slow iteration loop compared to tiers 1-3.
When to use: ONLY after tiers 1-3 are proven insufficient — i.e. the model
consistently misuses a well-documented, well-instructed tool, or produces
the wrong shape of output no amount of prompting/examples fixes. This is
usually a sign of a systemic behavior problem, not a one-off.
Trade-off: you gain reliability on your narrow task, you risk losing some
general capability/flexibility (the model gets narrower), and every
behavior change now costs a retrain instead of an instant prompt edit.

### 6. LoRA (Low-Rank Adaptation)
What it is: a cheaper variant of fine-tuning — trains a small adapter
layer instead of the full model's weights.
Cost: lower than full fine-tuning (less compute, smaller artifact, faster
to train/swap), but still real training infra — not something you reach
for casually.
When to use: same triggering condition as fine-tuning (tiers 1-3 proven
insufficient), chosen over full fine-tuning when you want a cheaper/faster
iteration loop, multiple swappable "skins" on one base model, or don't
have the compute budget for full fine-tuning.

## Rule of thumb or you'll over-engineer this

Try tools + instructions first, always. They're free to try and instant to
revert. Reach for RAG only when the actual gap is missing facts, not
missing reasoning. Reach for fine-tuning/LoRA only when you have REAL
EVIDENCE (not a hunch) that a well-built tool + well-written instructions
still fail — e.g. you tried it, it's wrong in a consistent, specific way,
and better prompting provably doesn't fix it. Jumping straight to
fine-tuning for a problem that's actually "the tool doesn't exist yet" is
the same mistake as reaching for a workflow engine to handle 3 states —
expensive machinery solving a problem a cheap fix already solves.

## Our concrete case, mapped to the tiers

| Problem | Looked like | Actually was | Fix tier |
|---|---|---|---|
| Agent set rotation backwards (270° vs 90°) | Model doesn't understand rotation | Model didn't know UNITY's specific ZXY convention | Tier 2 (told it the convention) + a code guardrail (not a model fix at all — deterministic check) |
| Agent couldn't do horror mood | Model doesn't understand horror lighting | Model had no tool to create a light | Tier 1 (new tool) |
| Horror mood still scored low after create_light | Model still doesn't get horror | Scene itself has no geometry for real shadow/contrast | Not a model problem at all — an asset/scene problem |

Note the last row: not everything that looks like "the model needs
customization" actually is a model problem. Sometimes the ceiling is the
environment (the test scene), and no tier of model customization fixes
that.
