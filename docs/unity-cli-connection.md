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

## Write transform values — `gameobject set_transform`
```bash
unity command "gameobject set_transform" --target <handle> \
  --position '[x,y,z]' --rotation '[x,y,z]'
```
Confirmed to exist, now in heavy use (moves/rotates objects and lights).

## Open items
All originally-open items (`gameobject create`, `component add`, `capture
screenshot`) are done and in use now — see below.

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

## `gameobject create`'s own JSON response truncates large instanceIds
Found live: `gameobject create --name X` returned `instanceId: ...755000`
in its JSON, but the object's REAL id (read via `script eval`'s
`GetEntityId()`) was `...755038` — float precision loss somewhere in that
command's own JSON encoding of a large integer. Using the truncated ID in
any later command fails with "No loaded object with instanceId...", even
though the object exists and `gameobject find --name X` locates it fine.
Rule: never trust `gameobject create`'s own returned `instanceId` for a
large number — create the GameObject via `script eval` instead (reads
`GetEntityId()` directly, same precise path every other read in this
project already uses) and use THAT id for all follow-up commands.

## Colliders can live below the objects you're reading
`list_scene_transforms()` originally read only root-level Transforms
(`t.parent != null` skip). That's fine when a scene's real objects ARE
its roots, but an imported Unity Asset Store pack may organize things as
a handful of container roots (e.g. `Asset`, `Wall`) holding the real
props as direct children — and the container itself can have ZERO
colliders anywhere in its own hierarchy while its children are fully
solid. `Physics.Raycast`/`RaycastAll` only hits actual `Collider`
components wherever they sit; a parent with none is invisible to
raycasting regardless of its children. Fixed by walking each root's
subtree: no collider anywhere → return the root as-is (camera/light/
volume unaffected); has a collider somewhere → return each direct child
that owns one (one level below root, not collapsed to the absolute top,
which would merge many distinct real objects into one meaningless
point).
