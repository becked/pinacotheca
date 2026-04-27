"""Render a handful of building meshes using the existing renderer.

Outputs PNGs into scripts/probes/output/ so we can eyeball whether the
unit-pipeline renderer works on buildings or needs camera/lighting tweaks.
"""

from __future__ import annotations

import gc
import os
import re
from pathlib import Path
from typing import Any

import UnityPy

from pinacotheca.extractor import find_game_data
from pinacotheca.renderer import render_mesh_to_image

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# (mesh_name, texture_substring_match) — texture lookup uses substring on lowercase.
# When texture_match is None we let the heuristic pick the best diffuse-style match.
TARGETS: list[tuple[str, str | None]] = [
    ("Library_LOD0", "library_diffuse"),
    ("RoyalLibraryRT", "royallibrary_diffuse"),
    ("Barracks_LOD0", "barracks_diff"),
    ("Granary_LOD0", "granary_diffuse"),
    ("Watermill_LOD0", "watermill_diffuse"),
    ("ChristianTemple_LOD0", "christian_temple_diffuse"),
    ("Hunting_Shrine_LOD0", "hunting_shrine_diffuse"),
    ("Academy", "academy_diff"),
    ("Market", "market_diff"),
    ("Hanging_Garden", "hanging_gardens_diffuse"),
    ("Maurya_Capital", "mauryalow_capital_basecolor"),
    ("Tamil_Capital", "tamil_capital_pvt_basecolor"),
    ("AksumCapitol", "aksumcapitol_diffuse"),
    ("Kushite Pyramid", None),  # See if heuristic finds something usable
]


def normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def main() -> None:
    game_data = find_game_data()
    if game_data is None:
        raise SystemExit("Game data not found")

    os.chdir(str(game_data))
    print("Loading assets...")
    env = UnityPy.Environment()
    env.load_file(str(game_data / "resources.assets"))

    mesh_lookup: dict[str, Any] = {}
    texture_lookup: dict[str, Any] = {}  # normalized name -> obj

    for obj in env.objects:
        try:
            if obj.type.name == "Mesh":
                d = obj.read()
                name = getattr(d, "m_Name", "") or ""
                if name and name not in mesh_lookup:
                    mesh_lookup[name] = obj
            elif obj.type.name == "Texture2D":
                d = obj.read()
                name = getattr(d, "m_Name", "") or ""
                if name:
                    texture_lookup.setdefault(normalize(name), obj)
        except Exception:
            pass

    print(f"  meshes={len(mesh_lookup)}  textures={len(texture_lookup)}")
    print()

    for mesh_name, tex_match in TARGETS:
        out_path = OUTPUT_DIR / f"{mesh_name.replace(' ', '_')}.png"
        print(f"=== {mesh_name} ===")

        if mesh_name not in mesh_lookup:
            print("  [SKIP] mesh not found")
            continue

        # Find texture
        tex_obj = None
        if tex_match:
            tex_obj = texture_lookup.get(normalize(tex_match))
            if tex_obj is None:
                # substring fallback
                for k, v in texture_lookup.items():
                    if normalize(tex_match) in k:
                        tex_obj = v
                        break
        if tex_obj is None:
            # heuristic: find first texture whose normalized name contains the
            # normalized mesh-base name AND has 'diffuse'/'basecolor'/'diff'
            base = normalize(re.sub(r"_LOD\d+$", "", mesh_name, flags=re.IGNORECASE))
            for k, v in texture_lookup.items():
                if base and base in k and any(s in k for s in ("diffuse", "basecolor", "diff")):
                    tex_obj = v
                    break

        if tex_obj is None:
            print("  [SKIP] texture not found")
            continue

        try:
            mesh_data = mesh_lookup[mesh_name].read()
            obj_str = mesh_data.export()
            tex_data = tex_obj.read()
            tex_img = tex_data.image

            if not obj_str or tex_img is None:
                print("  [SKIP] empty mesh or texture")
                continue

            img = render_mesh_to_image(obj_str, tex_img)
            img.save(out_path)
            print(f"  [OK] -> {out_path.name}  ({img.size[0]}x{img.size[1]})")

        except Exception as e:
            print(f"  [ERROR] {e}")
        finally:
            gc.collect()

    print(f"\nWrote outputs to: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
