# Project organization

Why this repo is laid out the way it is — written down once so it doesn't
need re-explaining every time a new piece gets added.

## Layout

```
unity-mood-lighting-agent/          <- the git repo itself
├── README.md                        <- architecture doc: scope, v0 plan, full vision
├── .gitignore
├── docs/                             <- this folder: design/process notes
├── MoodLightingScene/                <- the Unity project (URP, 6000.5.7f1)
│   └── Assets/Scenes/TestRoom.unity  <- v0 test scene: floor + cube
└── agent/                            <- the Python agent code (OpenAI Agents SDK)
    ├── pyproject.toml
    ├── uv.lock
    ├── .env.example                  <- real .env (with the API key) stays local, never committed
    └── src/unity_mood_lighting_agent/
        └── step1_hello_agent.py      <- incremental build steps, one file per step
```

## Why both the Unity project and the agent live in one repo

Judgment call, not a hard rule: this project IS "an agent that controls a
Unity scene," so the scene and the agent that controls it version together.
If the Unity project and the agent code were two separable, independently
useful things, they'd be two repos. They're not — neither half means
anything without the other right now.

## Why `MoodLightingScene/` and `agent/` are siblings, not nested

Standard practice for a repo mixing two different language ecosystems.
Unity's project format (C#, `Assets/`, `Packages/`, `ProjectSettings/`) and
Python's project format (`pyproject.toml`, `src/`) don't mix — each gets its
own top-level folder, same reason a typical web project keeps `frontend/`
and `backend/` side by side instead of nesting one inside the other.

## Why `agent/src/unity_mood_lighting_agent/...` and not just `agent/*.py`

Not a choice we made — it's `uv init`'s own default layout, generated
automatically by `uv init --name unity-mood-lighting-agent`. It's the Python
packaging convention known as the **"src layout"**: code lives under
`src/<package_name>/` instead of directly in the project root. The reason
this convention exists (not specific to this project): it prevents Python
from accidentally importing your in-progress source code instead of the
properly installed package when you run tests or scripts, which becomes a
real bug source once a project grows past a single script. We didn't need
to design this — `uv` already encodes the convention.

## Why files are named `stepN_description.py`

This one actually is a deliberate choice for *this* project, not a general
Python convention, and it's provisional. Since we're building the agent
incrementally and explicitly trying to understand + explain each step
(not just end up with a working result), each step gets its own file named
after what it proves — `step1_hello_agent.py` is "just prove the harness
works, no tools yet." This makes it possible to look back at the git history
or the file list and see the actual learning progression, not just the
final state. Easy to rename or restructure later if it stops being useful
once there are many steps — nothing downstream depends on this naming yet.

## What's NOT decided yet

- Whether later steps get consolidated into fewer files once the agent
  stabilizes, or stay split by step indefinitely (probably the former, once
  v0 is actually working end to end — numbered step files are a learning
  aid for right now, not meant to be the permanent shape of the codebase).
- Whether Unity-side code (if we end up writing any C# for the Unity CLI/MCP
  integration) gets its own folder under `MoodLightingScene/` or a separate
  top-level folder. Not needed yet — nothing has required Unity-side scripting so far.
