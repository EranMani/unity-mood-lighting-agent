# Unity CLI connection — summary

Verified 2026-11-17 against `MoodLightingScene`, Unity CLI `1.0.0`, Editor `6000.5.7f1`.

## Binary location
`C:\Users\eranm\AppData\Local\Unity\bin\unity.exe` — not on PATH, call by full path.

## MCP vs CLI — why subprocess, not MCP
MCP is for shell-less clients (Claude Desktop, Cursor). Our Python agent has
a shell, so we call `unity command ...` directly via `subprocess`. No MCP
server/client layer, no stdio protocol. Path: Python → subprocess →
`unity.exe` → live Editor's Pipeline server (not MCP) → JSON back.

## Skill source
`npx skills add Unity-Technologies/skills` installed the `unity-cli` skill
(`.agents/skills/unity-cli/`, git-ignored, reproducible) — that's where every
command/flag below came from. Docs there cover real gotchas (Safe Mode,
multi-Editor targeting) that `--help` doesn't.

## Confirm connection
```bash
unity status --format json
```
Needs `MoodLightingScene` open. Confirms `port`, `state: ready`, project path.

## Read scene (identity only, no transform values)
```bash
unity command "scene get_hierarchy" --format json --project-path "$PROJ"
unity command "gameobject find" --name <Name> --format json
```
Both return name/id/path, never position or rotation.

## Read real transform values — `script eval` (the only way)
```bash
unity command script eval "$CS" --result-only --project-path "$PROJ"
```
`$CS` is C# that reads `transform.position`/`eulerAngles` and returns a list
— see `step6_real_unity_connection.py` for the actual script. `--result-only`
prints just that return value as JSON.

Real scene caught 2 things our hardcoded fake data got wrong: Cube's
off-center position, Directional Light's real rotation. Also found
`Global Volume` existed and wasn't in our fake data at all.

## Write transform values — `gameobject set_transform` (not yet used)
```bash
unity command "gameobject set_transform" --target <handle> \
  --position '[x,y,z]' --rotation '[x,y,z]'
```
Found, confirmed to exist, not yet called live.

## Open items
`gameobject create` + `component add` (make lights), `capture screenshot`
(v1 judge loop) — not yet tested.

## instanceId is session-dynamic — always re-fetch, never hardcode
`instance_id`/`instanceId` values (from `GetEntityId()` or `gameobject
find`) are NOT stable across Editor restarts/domain reloads — same object,
different session, different ID. Confirmed live: reused an ID from an
earlier session, `component set_field` failed with "No loaded object with
instanceId...". Not a bug, not two ID spaces — `GetEntityId().ToString()`
and `gameobject find`'s `instanceId` ARE the same space, confirmed matching
in the same session. Rule: always call `list_scene_transforms()` /
`gameobject find` fresh within the current session before using an ID;
never cache or hardcode one across runs.
