"""Sanity check: render a single mesh referenced by a capital's
ClutterTransforms through the existing renderer pipeline. Confirms the
meshes are real, baked 3D building geometry — not placeholders or shader-
only artifacts.

Pulls a few representative meshes (bigHome.001 Greek, TheaterPompey Roman,
BackGate Egyptian, etc.) by pathID — discovered via scan_clutter_meshes.py.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np
import UnityPy

from pinacotheca.extractor import find_game_data
from pinacotheca.prefab import PrefabPart, bake_to_obj, strip_plinth_from_obj
from pinacotheca.renderer import render_mesh_to_image

# (capital, mesh_name, mesh_path_id, material_name, material_path_id)
# pathIDs verified via scripts/probes/scan_clutter_meshes.py.
SAMPLES: list[tuple[str, str, int, str, int]] = [
    ("Greece", "bigHome.001", 6219, "GreeceMat", 48),
    ("Greece", "Cypress.001", 5388, "GreeceMat", 48),
    ("Greece", "Gazeebo.001", 3463, "GreeceMat", 48),
    ("Rome", "TheaterPompey", 5185, "RomeTrim", 58),
    ("Rome", "Mansion", 5857, "RomeTrim", 58),
    ("Rome", "BigTower", 3223, "RomeTrim", 58),
    ("Egypt", "BackGate", 3849, "RomeTrim", 58),  # placeholder material; we'll fix
]


def find_object_by_path_id(env: Any, path_id: int) -> Any:
    """Find an Object by its pathID. PathIDs are NOT unique across files —
    the Mesh references on capital ClutterTransforms point at resources.assets,
    not globalgamemanagers.assets, so look there first."""
    # Prefer resources.assets where the prefabs and meshes live.
    for fname, f in env.files.items():
        if "resources.assets" in fname and not fname.endswith(".resS"):
            target = getattr(f, "objects", {}).get(path_id)
            if target is not None:
                return target
    return None


def find_diffuse_texture_in_material(material_obj: Any) -> Any:
    """Pull the first diffuse-ish texture from a Material's m_SavedProperties."""
    saved = getattr(material_obj, "m_SavedProperties", None)
    if saved is None:
        return None
    tex_envs = getattr(saved, "m_TexEnvs", None) or []
    # m_TexEnvs is a list of (name, TextureEnv) pairs.
    for entry in tex_envs:
        try:
            name = entry[0] if isinstance(entry, (list, tuple)) else entry.first
            env_val = entry[1] if isinstance(entry, (list, tuple)) else entry.second
        except Exception:
            continue
        if name in ("_BaseColorMap", "_BaseMap", "_MainTex", "_BaseColor", "_Albedomap"):
            tex_pptr = getattr(env_val, "m_Texture", None)
            if tex_pptr is None:
                continue
            try:
                if not bool(tex_pptr):
                    continue
                tex_obj = tex_pptr.deref_parse_as_object()
                return tex_obj
            except Exception:
                continue
    return None


def main() -> None:
    game_data = find_game_data()
    assert game_data is not None
    os.chdir(str(game_data))
    env = UnityPy.Environment()
    env.load_file(str(game_data / "globalgamemanagers.assets"))
    env.load_file(str(game_data / "resources.assets"))

    out_dir = Path(__file__).parent / "output" / "clutter_renders"
    out_dir.mkdir(parents=True, exist_ok=True)

    for capital, mesh_name, mesh_pid, mat_name, mat_pid in SAMPLES:
        print(f"\n--- {capital} / {mesh_name} (pid={mesh_pid}) ---")
        mesh_obj = find_object_by_path_id(env, mesh_pid)
        if mesh_obj is None:
            print("  mesh pathID not found")
            continue
        if mesh_obj.type.name != "Mesh":
            print(f"  pathID resolves to {mesh_obj.type.name}, not Mesh")
            continue

        mat_obj = find_object_by_path_id(env, mat_pid)
        if mat_obj is None or mat_obj.type.name != "Material":
            print("  material pathID not Material")
            continue

        try:
            mat_parsed = mat_obj.parse_as_object()
            tex_obj = find_diffuse_texture_in_material(mat_parsed)
            if tex_obj is None:
                print(f"  material '{mat_name}' has no diffuse texture")
                continue
            from pinacotheca.prefab import _decode_texture
            tex_img = _decode_texture(tex_obj)
            if tex_img is None:
                print("  texture decode failed")
                continue
        except Exception as e:
            print(f"  material/texture extraction failed: {e}")
            continue

        # bake_to_obj expects a PPtr (calls deref_parse_as_object); wrap our
        # ObjectReader so that method works.
        class ObjectReaderAsPPtr:
            def __init__(self, reader: Any) -> None:
                self._reader = reader

            def deref_parse_as_object(self) -> Any:
                return self._reader.parse_as_object()

            def __bool__(self) -> bool:
                return True

        part = PrefabPart(
            mesh_obj=ObjectReaderAsPPtr(mesh_obj),
            world_matrix=np.eye(4, dtype=np.float64),
            materials=[mat_obj],
        )
        try:
            obj_str = bake_to_obj([part], pre_rotation_y_deg=180.0)
            obj_str = strip_plinth_from_obj(obj_str)
        except Exception as e:
            print(f"  bake failed: {e}")
            continue

        if not obj_str.strip():
            print("  bake produced empty OBJ")
            continue

        try:
            img = render_mesh_to_image(obj_str, tex_img, force_upright=True)
            out_path = out_dir / f"{capital}_{mesh_name.replace('.', '_')}.png"
            img.save(out_path)
            tex_w, tex_h = tex_img.size
            print(f"  ok: rendered ({img.size[0]}x{img.size[1]}, texture {tex_w}x{tex_h}) → {out_path.name}")
        except Exception as e:
            print(f"  render failed: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
