"""
v0, step 7: write side. set_object_transform() moves/rotates a real
GameObject via the Unity CLI, same subprocess pattern as _build_transforms()
in step 6. Tested live first via raw CLI (moved the Cube, confirmed visually
in the Editor) before being wrapped here.

Still deterministic code, no agent/LLM — same step 5 rule: "move this
specific object to this specific position" has no ambiguity, no judgment
needed. The agent's job later is deciding WHERE to move things for a mood,
not calling this function correctly.
"""

import subprocess

UNITY_EXE = r"C:\Users\eranm\AppData\Local\Unity\bin\unity.exe"
PROJECT_PATH = r"D:\AI\MyProjects\unity-mood-lighting-agent\MoodLightingScene"


def set_object_transform(
    target: str,
    position: tuple[float, float, float] | None = None,
    rotation: tuple[float, float, float] | None = None,
) -> None:
    """Move/rotate a GameObject by its instance_id (from _build_transforms()).
    Omit position or rotation to leave that channel unchanged, matching the
    Unity CLI's own behavior."""
    args = [
        UNITY_EXE,
        "command",
        "gameobject set_transform",
        "--target",
        target,
        "--project-path",
        PROJECT_PATH,
    ]
    if position is not None:
        args += ["--position", f"[{position[0]},{position[1]},{position[2]}]"]
    if rotation is not None:
        args += ["--rotation", f"[{rotation[0]},{rotation[1]},{rotation[2]}]"]

    subprocess.run(args, capture_output=True, text=True, check=True)


def main() -> None:
    # Smoke test: move the Cube back to a clean position (undoes the manual
    # test move to X=2 we did live). Replace this instance_id by re-running
    # step6's _build_transforms() if the scene has changed since.
    set_object_transform(
        target="568105589213705702",  # Cube
        position=(0, 0.5, 0),
    )
    print("Moved Cube back to (0, 0.5, 0). Check the Editor.")


if __name__ == "__main__":
    main()
