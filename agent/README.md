# agent/

Python agent code (OpenAI Agents SDK). See the top-level
[README.md](../README.md) for project scope, architecture, and documentation index.

Setup:
```
uv sync
cp .env.example .env   # fill in OPENAI_API_KEY
```

Usage:
```
uv run python src/unity_mood_lighting_agent/main.py "apply a horror mood"
uv run python src/unity_mood_lighting_agent/eval.py
```
