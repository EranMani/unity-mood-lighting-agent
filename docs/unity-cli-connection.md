# Unity CLI connection — what we actually found

Written from real commands run against a live Editor, not from docs alone.
Everything below was verified working on 2026-11-17 against this repo's
`MoodLightingScene` project, Unity CLI `1.0.0`, Editor `6000.5.7f1`.

## Where the CLI actually lives

Checking "Use Unity CLI" at project creation did NOT put `unity` on this
machine's bash `PATH`. The real binary:

```
C:\Users\eranm\AppData\Local\Unity\bin\unity.exe
```

Call it by full path (or add that folder to PATH). Confirmed working:
```bash
"C:/Users/eranm/AppData/Local/Unity/bin/unity.exe" --version
```

## MCP vs. CLI — which one we actually use

**We do NOT use `unity mcp`.** That subcommand starts an MCP server for
*external* AI-client apps with no shell of their own (Claude Desktop,
Cursor, VS Code). We're writing our own Python agent (OpenAI Agents SDK)
that already has full shell/subprocess access, so the Unity CLI's own
documentation is explicit on this point: **"Prefer the CLI when you can run
shell commands... the CLI exposes more than the server's tools."**

Our integration is: Python tool function → `subprocess` call to
`unity command ...` → parse the JSON result. No MCP server/client layer,
no stdio protocol, nothing extra.

## The official Unity CLI skill

Installed via `npx skills add Unity-Technologies/skills` (Unity's own
recommendation, surfaced automatically as a CLI notification the first time
we ran `unity status`). This landed a whole catalog of skills under
`.agents/skills/` and `.claude/skills/` in this repo — `unity-cli` is the
one we actually use; others (`urp-postprocessing`, `unity-package-management`,
etc.) are there but unused so far.

**Why bother installing a skill instead of just using `--help`:** the skill
file (`​.agents/skills/unity-cli/SKILL.md` + its `references/*.md`) documents
real gotchas `--help` text doesn't mention — e.g. Safe Mode breaking the
connection, how multiple open Editors get disambiguated, the exact
difference between `unity mcp` and `unity command`. Read it before
guessing at flags.

## Confirming a live connection

```bash
UNITY="C:/Users/eranm/AppData/Local/Unity/bin/unity.exe"
"$UNITY" status --format json
```

With `MoodLightingScene` open in the Editor, this returned a real connected
instance: `port: 7800`, `state: "ready"`, the correct `projectPath`, PID,
and Editor version. **The Editor has to actually be open** — this isn't a
headless/background thing, it's driving your live, visible Editor window.

## Reading scene structure (identity only, no transform values)

```bash
"$UNITY" command "scene get_hierarchy" --format json --project-path "$PROJ"
```

Returned the real `TestRoom.unity` tree: `Main Camera`, `Directional Light`,
`Global Volume`, `Plane`, `Cube` — each with `name`, `instanceId`,
`hierarchyPath`, `activeSelf`, `components` (list of component type names).
**No position/rotation/scale values in this output** — it only tells you a
`Transform` component exists, not what it's set to.

`unity command "gameobject find" --name <Name> --format json` is similarly
identity-only (`globalId`, `instanceId`, `hierarchyPath`, `type` — no
transform values).

## Reading actual transform values — `script eval`

There is **no built-in read command** for transform values (only
`gameobject set_transform` exists, write-only). To actually read
position/rotation, run real C# through `script eval`:

```bash
"$UNITY" command script eval "$CS" --result-only --project-path "$PROJ"
```

where `$CS` is a C# snippet, e.g.:
```csharp
var list = new System.Collections.Generic.List<object>();
foreach (var t in UnityEngine.Object.FindObjectsByType<UnityEngine.Transform>(UnityEngine.FindObjectsSortMode.None)) {
  if (t.parent != null) continue;  // root-level objects only
  var p = t.position; var r = t.eulerAngles;
  list.Add(new { name = t.gameObject.name, pos_x = p.x, pos_y = p.y, pos_z = p.z, rot_x = r.x, rot_y = r.y, rot_z = r.z });
}
return list;
```

`--result-only` strips the `command`/`parameters`/`target` envelope and
prints just the C# return value as JSON — directly parseable.

**Real result against our actual scene** (not our hardcoded fake data):

| name | pos_x | pos_y | pos_z | rot_x | rot_y | rot_z |
|---|---|---|---|---|---|---|
| Global Volume | 0 | 0 | 0 | 0 | 0 | 0 |
| Directional Light | 0 | 3 | 0 | 63.1 | 15.5 | ~0 |
| Plane | 0 | 0 | 0 | 0 | 0 | 0 |
| Cube | -0.13013 | 0.507 | 0.5 | 0 | 0 | 0 |
| Main Camera | 0 | 1 | -10 | 0 | 0 | 0 |

Two things this caught that our fake `_build_transforms()` data got wrong:
the real Cube isn't at a clean `(0, 0.5, 0)` (Eran nudged it slightly when
placing it by hand), and the Directional Light has a real non-zero rotation
(default-ish angle), while our fake data had it flat at `(0,0,0)`. Also:
**`Global Volume` exists in the real scene and was never in our fake data at
all** — URP's template adds it automatically, we hadn't accounted for it.

## Writing transform values — `gameobject set_transform`

Confirmed to exist (not yet tested live — read-only exploration so far):

```bash
unity command "gameobject set_transform" \
  --target <handle-from-gameobject-find-or-scene-get_hierarchy> \
  --position '[0,0.5,0]' --rotation '[0,0,0]' --scale '[1,1,1]'
```

Takes `target` (an object handle — the `instanceId`/`globalId` from
`gameobject find` or `scene get_hierarchy`), and optional `position`,
`rotation` (Euler degrees), `scale` — each a 3-element array, omitted
channels left unchanged. `idempotent: true`, `destructive: false` per its
own command metadata. This is the write side we'll need once the agent
starts actually placing/moving lights — not wired into Python yet.

## Open items

- `gameobject create` + `component add` (for actually creating Light
  GameObjects) — not yet explored live.
- `capture screenshot` / `capture game_view` — exists per the skill docs,
  needed for the render-and-judge loop (v1+), not yet tested.
- Safe Mode (C# compile errors breaking the Pipeline connection) — documented
  in the skill, not yet hit in practice.
