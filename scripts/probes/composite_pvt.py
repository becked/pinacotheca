"""Composite albedo × alphamask for each capital — flat 2D, no shader, no
displacement. Just shows what the painted region looks like with the mask
applied. Pre-render sanity check before committing to a full PVT pipeline.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

SRC = Path(__file__).parent / "output" / "pvt_textures"
OUT = Path(__file__).parent / "output" / "pvt_composites"

# (capital, albedo, mask, height) — taking from the verified-truth table.
CAPITALS = [
    ("Greece", "GreeceCapTerrain", "GreeceCapTerrain_M", "GreeceCapTerrain_H"),
    ("Rome", "romcapitalSplat", "romcapital_CLUT", "RomeGroundHeight"),
    ("Egypt", "landEgypt_roads", "landEgypt_Mask", "landEgypt_height"),
    ("Persia", "persiaCapPVT", "persia_capMask", None),
    ("Babylon", "landBabylon", "landBabylon_m", "lakeBabylon"),
    ("Carthage", "Carthagepvt", "Carthagepvt_mask", "CarthageMoundMask"),
    ("Assyria", "AssyriaCapTerrain", "AssyriaCapmask", "AssyriaCapH"),
]


def composite(capital: str, albedo_name: str, mask_name: str, height_name: str | None) -> None:
    albedo = Image.open(SRC / f"{albedo_name}.png").convert("RGBA")
    mask = Image.open(SRC / f"{mask_name}.png")

    # Mask might be L (single-channel) or RGBA. Take R channel either way.
    if mask.mode == "RGBA":
        mask_r = mask.split()[0]
    else:
        mask_r = mask.convert("L")

    # Resize mask to albedo size (mask is usually 1/4 the resolution).
    if mask_r.size != albedo.size:
        mask_r = mask_r.resize(albedo.size, Image.LANCZOS)

    # Apply mask as alpha channel: RGB from albedo, A from mask.
    rgb = albedo.split()[:3]
    composite = Image.merge("RGBA", (*rgb, mask_r))

    out_path = OUT / f"{capital}_albedo_x_mask.png"
    composite.save(out_path)
    print(f"  {capital}: {albedo.size} albedo × {mask.size} mask → {out_path.name}")

    # Also produce a "ground-style" preview: composite over a neutral
    # mid-gray background so we can see what the painted region looks like
    # when the surrounding biome is generic dirt.
    bg = Image.new("RGBA", albedo.size, (90, 80, 65, 255))  # warm dirt
    bg.alpha_composite(composite)
    bg.save(OUT / f"{capital}_on_dirt.png")

    # If there's a heightmap, save a side-by-side preview of mask + height
    # so we can correlate where the relief happens.
    if height_name:
        try:
            height = Image.open(SRC / f"{height_name}.png").convert("L")
            if height.size != albedo.size:
                height_resized = height.resize(albedo.size, Image.LANCZOS)
            else:
                height_resized = height
            # Tint the height: white = up, black = flat. Just re-save it.
            height_resized.save(OUT / f"{capital}_height.png")
        except FileNotFoundError:
            pass


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"Compositing {len(CAPITALS)} capitals...")
    for cap, albedo, mask, height in CAPITALS:
        try:
            composite(cap, albedo, mask, height)
        except FileNotFoundError as e:
            print(f"  {cap}: skip ({e})")
    print(f"\nOutput: {OUT}")


if __name__ == "__main__":
    main()
