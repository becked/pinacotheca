"""Extract the source PVT textures referenced by each capital + urban tile
splat MonoBehaviour, save as PNGs to scripts/probes/output/pvt_textures/.

Lets the user eyeball each per-nation albedo / alphamask / heightmap /
normalmap to predict what the rendered tile will look like.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import UnityPy

from pinacotheca.extractor import find_game_data
from pinacotheca.prefab import _decode_texture

# All textures referenced by the verified inventory (capitals + urban tiles).
TEXTURE_NAMES = [
    # Greece (capital)
    "GreeceCapTerrain",
    "GreeceCapTerrain_M",
    "GreeceCapTerrain_H",
    "GreeceCapFlatTerrain",  # the universal Bull no-op
    # Greece (urban) + reused by Rome_Urban
    "GreeceurbanTerrain2b",
    "GreeceurbanMask2",
    # Rome (capital)
    "romcapitalSplat",
    "romcapital_CLUT",
    "RomeGroundHeight",
    "RomeGroundNormal",
    # Rome (urban native)
    "fullileSplat",
    "fullileSplatMask",
    # Egypt
    "landEgypt_roads",
    "landEgypt_Mask",
    "landEgypt_height",
    "landEgyptU_roads",
    "landEgyptU_Mask",
    # Persia
    "persiaCapPVT",
    "persia_capMask",
    "persia_UrbanPVT",
    "persia_UrbanMask",
    # Babylon
    "landBabylon",
    "landBabylon_m",
    "lakeBabylon",
    "urbanSpaltBabylon",
    "landBabylon_roadsMask",
    # Carthage
    "Carthagepvt",
    "Carthagepvt_mask",
    "CarthageMoundMask",
    "carthageUrbanPVT",
    "carthageUrbanMask",
    # Assyria
    "AssyriaCapTerrain",
    "AssyriaCapmask",
    "AssyriaCapH",
    "AssyriaTerrain",
    "AssyriaUrbanmask",
]


def main() -> None:
    game_data = find_game_data()
    assert game_data is not None
    os.chdir(str(game_data))
    env = UnityPy.Environment()
    env.load_file(str(game_data / "globalgamemanagers.assets"))
    env.load_file(str(game_data / "resources.assets"))

    out_dir = Path(__file__).parent / "output" / "pvt_textures"
    out_dir.mkdir(parents=True, exist_ok=True)

    wanted = set(TEXTURE_NAMES)
    found: dict[str, Any] = {}

    for obj in env.objects:
        if obj.type.name != "Texture2D":
            continue
        try:
            data = obj.read()
            name = getattr(data, "m_Name", "")
        except Exception:
            continue
        if name in wanted and name not in found:
            found[name] = data

    print(f"Resolving {len(wanted)} texture names...")
    for name in TEXTURE_NAMES:
        tex = found.get(name)
        if tex is None:
            print(f"  MISSING: {name}")
            continue
        try:
            img = _decode_texture(tex)
            if img is None:
                print(f"  DECODE FAIL: {name}")
                continue
            w, h = img.size
            mode = img.mode
            fmt = getattr(tex, "m_TextureFormat", "?")
            out_path = out_dir / f"{name}.png"
            # Save preserving alpha when present.
            if img.mode != "RGBA":
                img = img.convert("RGBA")
            img.save(out_path)
            print(f"  ok: {name}  {w}x{h}  fmt={fmt} mode={mode}  → {out_path.name}")
        except Exception as e:
            print(f"  ERR: {name}  {type(e).__name__}: {e}")

    print(f"\nDone. Output: {out_dir}")


if __name__ == "__main__":
    main()
