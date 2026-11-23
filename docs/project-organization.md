# Project organization

Why this repo is laid out the way it is - written down once so it doesn't
need re-explaining every time a new piece gets added. Rewritten
2026-11-23 - the original version was stale, still describing the step1-7
learning-step layout as if it were the whole codebase; the project has
grown well past that since.

## Layout

```
unity-mood-lighting-agent/          <- the git repo itself
|-- README.md                        <- project overview, setup, usage
|-- docs/                             <- full documentation (see README's index)
|-- mood_test_log.jsonl               <- append-only log of every run
|-- screenshots/<case>/               <- baseline.png + result.png per case
|-- .gitignore
|-- .gitattributes                    <- Git LFS tracking (large binary assets)
|-- MoodLightingScene/                <- the Unity project (URP, 6000.5.7f1)
|   `-- Assets/
|       |-- room/...                  <- indoor test scene (sci-fi mess hall)
|       |-- InnerverseInteractive/...  <- outdoor test scene (forest, Asset Store pack)
|       `-- HDRIs/                     <- 8 CC0 skybox HDRIs (polyhaven.com) + generated materials
`-- agent/                            <- the Python agent code (OpenAI Agents SDK)
    |-- pyproject.toml
    |-- uv.lock
    |-- .env.example                   <- real .env (with the API key) stays local, never committed
    `-- src/unity_mood_lighting_agent/
        |-- unity_bridge.py            <- ALL Unity interop: scene reads/writes, guardrails, capture
        |-- tools.py                   <- the lighting agent's tools (wraps unity_bridge)
        |-- agent.py                   <- the lighting agent + get_scene_context()
        |-- judge.py                   <- the separate scoring agent (structured output)
        |-- main.py                    <- entry point, ties everything into the attempt/retry loop
        |-- eval.py                    <- eval harness, runs the canonical suite
        |-- eval_suite.json            <- the 10 canonical mood test cases, each with its assigned scene
        |-- data/
        |   |-- hdri_manifest.json     <- skybox metadata (sourced from polyhaven.com's own tags)
        |   `-- scene_baselines/       <- per-scene captured original state, for restore
        `-- learning_steps/            <- steps 1-7, kept as the original build record, no longer imported
```

## Why both the Unity project and the agent live in one repo

Judgment call, not a hard rule: this project IS "an agent that controls a
Unity scene," so the scene and the agent that controls it version together.
If the Unity project and the agent code were two separable, independently
useful things, they'd be two repos. They're not - neither half means
anything without the other.

## Why `MoodLightingScene/` and `agent/` are siblings, not nested

Standard practice for a repo mixing two different language ecosystems.
Unity's project format (C#, `Assets/`, `Packages/`, `ProjectSettings/`) and
Python's project format (`pyproject.toml`, `src/`) don't mix - each gets its
own top-level folder, same reason a typical web project keeps `frontend/`
and `backend/` side by side instead of nesting one inside the other.

## Why `agent/src/unity_mood_lighting_agent/...` and not just `agent/*.py`

Not a choice that was made deliberately - it's `uv init`'s own default
layout, generated automatically by `uv init --name unity-mood-lighting-agent`.
It's the Python packaging convention known as the **"src layout"**: code
lives under `src/<package_name>/` instead of directly in the project root.
This prevents Python from accidentally importing in-progress source code
instead of the properly installed package when running tests or scripts -
`uv` already encodes the convention, no need to design it.

## Why `unity_bridge.py` holds everything, instead of one file per concern

Every Unity interop function - scene reads, light/post-processing writes,
screenshot capture, guardrails, scene baseline capture/restore - lives in
one file. This started as a pragmatic "flat files, no folders-per-concern
until it's justified" call back when the file was small (step 8), and has
been left that way deliberately since: splitting it now would mean picking
a taxonomy (by Unity subsystem? by read-vs-write? by guardrail-vs-not?)
with no forcing function yet proving one is better than another. Revisit if
the file keeps growing and a genuine seam appears - not before.

## Why `tools.py` is separate from `unity_bridge.py`

`unity_bridge.py` is the raw capability layer - plain functions, no agent
awareness, callable from anywhere (eval scripts, one-off terminal checks,
the agent's tools). `tools.py` is the thin `@function_tool`-wrapped layer
the lighting agent actually sees - docstrings written for the LLM, not for
a human reading the implementation. Keeping them separate means the raw
functions stay testable/callable without spinning up an agent at all (used
constantly throughout this project's history for direct verification before
trusting a change).

## Why `main.py` (the loop) is separate from `eval.py` (the harness)

`main.py`'s `run()` is the actual product: one task, one scene, in, result
out. `eval.py` is a layer OUTSIDE that - it doesn't talk to any LLM itself,
it only calls `main.py`'s `run()` once per case in `eval_suite.json` and
aggregates the results. Same distinction as an application vs. its test
suite: the eval harness should never need to duplicate the real run logic,
only drive it repeatedly and record outcomes.

## Why `learning_steps/` is still here, unused

Steps 1-7 are the literal incremental build history - each one still
compiles and runs standalone, demonstrating one proven capability before
the next was added. Nothing in the current pipeline imports them anymore;
they're kept purely as a record of how the project actually got built,
same spirit as `docs/build-log.md` but at the code level instead of prose.

## What's NOT decided yet

- Whether Unity-side code (if this ever needs custom C# for the Unity CLI
  integration, beyond `script eval` calls) gets its own folder under
  `MoodLightingScene/` or a separate top-level folder. Not needed yet -
  nothing has required Unity-side scripting so far, everything goes through
  `script eval`/`component get_fields`/`gameobject create` style CLI calls.
- Whether `unity_bridge.py` eventually gets split by subsystem (lights vs.
  post-processing vs. scene-lifecycle) - see the section above; no forcing
  function yet.
