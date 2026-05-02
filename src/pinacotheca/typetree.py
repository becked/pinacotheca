"""TypeTree generator setup for MonoBehaviour decoding.

Old World's asset bundles ship without inline typetrees (the Unity
build step strips them), so UnityPy can't decode `MonoBehaviour`
objects out of the box. This module wires `TypeTreeGeneratorAPI` —
which reads `Assembly-CSharp.dll` from the user's local game install
and produces field schemas on demand — into a `UnityPy.Environment` so
that `obj.read_typetree()` works on any class declared in the loaded
DLLs.

Once `setup_typetree_generator(env)` has been called, any caller can
do `obj.read_typetree()` and get back a dict whose keys match the
serialized C# field names. Adapter functions in the per-class modules
(`clutter_transforms.py`, `pvt_splats.py`, `terrain_clutter_splat.py`)
convert that dict into the same dataclass shape the existing hand
parsers return, so call sites stay unchanged.

The generator caches its node tree per (assembly, class) — repeated
reads on a class are cheap.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import UnityPy


def setup_typetree_generator(
    env: UnityPy.Environment,
    *,
    data_root: Path | None = None,
) -> None:
    """Attach a `TypeTreeGenerator` to `env` so MonoBehaviour decoding works.

    Idempotent: returns immediately if `env.typetree_generator` is
    already set. Reads the Unity version from any loaded SerializedFile
    in the env, instantiates the generator, and feeds it every `.dll`
    under the game install's `Managed/` directory.

    `data_root` is the game's Data dir (`.../OldWorld_Data` on Windows,
    `.../OldWorld.app/Contents/Resources/Data` on macOS); if omitted,
    falls back to `extractor.find_game_data()`.
    """
    if env.typetree_generator is not None:
        return

    from UnityPy.helpers.TypeTreeGenerator import TypeTreeGenerator

    if data_root is None:
        from pinacotheca.extractor import find_game_data

        found = find_game_data()
        if found is None:
            raise RuntimeError(
                "Cannot set up TypeTree generator: game install not found. "
                "Pass an explicit data_root or install Old World."
            )
        data_root = found

    managed_dir = data_root / "Managed"
    if not managed_dir.is_dir():
        raise RuntimeError(
            f"Cannot set up TypeTree generator: {managed_dir} is not a directory. "
            f"Expected Assembly-CSharp.dll under the game's Managed/ folder."
        )

    unity_version = _detect_unity_version(env)
    generator = TypeTreeGenerator(unity_version)
    generator.load_local_dll_folder(str(managed_dir))
    env.typetree_generator = generator


def decode_monobehaviour(
    env: UnityPy.Environment,
    obj: Any,
    script_class: str,  # noqa: ARG001
) -> dict[str, Any]:
    """Decode a MonoBehaviour body via TypeTree, returning the field dict.

    `script_class` is the C# class name (e.g. `"ClutterTransforms"`);
    accepted for call-site readability and future error messages. The
    actual class lookup happens inside UnityPy via the object's
    `m_Script` PPtr.

    Lazy-initializes the generator on first call — callers don't need
    to remember to call `setup_typetree_generator` themselves. On
    layout drift (a renamed/removed field), the typetree decode itself
    will fail loudly — same "fail loud" stance as the previous
    body-budget asserts on the hand parsers.
    """
    if env.typetree_generator is None:
        setup_typetree_generator(env)
    result: dict[str, Any] = obj.read_typetree()
    return result


def _detect_unity_version(env: UnityPy.Environment) -> str:
    """Pull the Unity version string off any loaded SerializedFile.

    Every SerializedFile in a Unity build records the version it was
    authored against (e.g. `'6000.3.5f2'`). We use the first one we
    find — they're all the same within a single game build.
    """
    for f in env.files.values():
        version = getattr(f, "unity_version", None)
        if version:
            return str(version)
    raise RuntimeError(
        "Cannot detect Unity version: no SerializedFile in env carries a "
        "unity_version. Did UnityPy.load() find any assets?"
    )
