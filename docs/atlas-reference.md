# Atlas Reference for Map Renderers

This document describes how to consume pinacotheca's texture atlas output for sprite-based map rendering. It's written for developers working on per-ankh or similar tools that render Old World game maps.

## Generating Atlases

```bash
# Extract sprites first (requires Old World installed)
pinacotheca

# Generate all atlases (lossless WebP)
pinacotheca-atlas

# Generate specific categories only
pinacotheca-atlas -c terrain height

# Lossy WebP for smaller files (good for CDN delivery)
pinacotheca-atlas --lossy 90

# Custom input/output paths
pinacotheca-atlas -i ./extracted/sprites -o ./output/atlases
```

## Output Structure

```
output/atlases/
├── terrain.webp        # 9 hex-masked terrain sprites
├── terrain.json
├── height.webp         # 3 hex-masked height sprites (hill, mountain, volcano)
├── height.json
├── improvement.webp    # ~132 improvement building sprites
├── improvement.json
├── resource.webp       # ~40 resource icons
├── resource.json
├── specialist.webp     # ~26 specialist portraits
├── specialist.json
├── city.webp           # Crests, city markers, capital markers
└── city.json
```

Each atlas is a pair: a WebP image (sprites packed in a regular grid) and a JSON manifest describing where each sprite lives in the image.

## Manifest Format

```json
{
  "atlas": "terrain.webp",
  "cellWidth": 211,
  "cellHeight": 181,
  "sprites": {
    "TERRAIN_ARID":      { "x": 0,   "y": 0,   "width": 211, "height": 181 },
    "TERRAIN_FROST":     { "x": 211, "y": 0,   "width": 211, "height": 181 },
    "TERRAIN_LUSH":      { "x": 422, "y": 0,   "width": 211, "height": 181 },
    "TERRAIN_MARSH":     { "x": 633, "y": 0,   "width": 211, "height": 181 },
    "..."
  }
}
```

- `cellWidth`/`cellHeight`: uniform cell size for this atlas. Every sprite occupies the same dimensions.
- `sprites`: mapping of sprite name to its pixel region in the atlas image. Sprites are sorted alphabetically and laid out left-to-right, top-to-bottom in a grid.

## Sprite Name Alignment

Sprite names in the manifest match Old World's internal enum names, which are the same values stored in per-ankh's parsed game data. For example:

| Per-ankh field | Example value | Atlas lookup |
|----------------|---------------|--------------|
| `MapTile.terrain` | `TERRAIN_TEMPERATE` | `terrain.json → sprites["TERRAIN_TEMPERATE"]` |
| `MapTile.height` | `HEIGHT_HILL` | `height.json → sprites["HEIGHT_HILL"]` |
| `MapTile.improvement` | `IMPROVEMENT_FARM` | `improvement.json → sprites["IMPROVEMENT_FARM"]` |
| `MapTile.resource` | `RESOURCE_IRON` | `resource.json → sprites["RESOURCE_IRON"]` |
| `MapTile.specialist` | `SPECIALIST_FARMER` | `specialist.json → sprites["SPECIALIST_FARMER"]` |

### Known Naming Mismatches

Religious buildings have swapped word order between database values and sprite names in the game itself. For example, the database stores `IMPROVEMENT_MONASTERY_CHRISTIANITY` but the sprite is named `IMPROVEMENT_CHRISTIANITY_MONASTERY`. The renderer should handle this with a small lookup table mapping database values to sprite names where they differ.

### Missing Sprites

When a tile references a sprite that doesn't exist in the atlas (new DLC content, mods, or game updates), handle it gracefully:

- **Terrain/height**: fall back to a flat colored hex.
- **Improvements/resources/specialists/cities**: skip rendering that tile's icon. deck.gl's `IconLayer` silently skips unknown icon names, which is the correct default.

Log missing sprite names to the console so they can be added to pinacotheca.

## Atlas Categories

### Terrain (211x181, hex-masked)

9 sprites: `TERRAIN_ARID`, `TERRAIN_FROST`, `TERRAIN_LUSH`, `TERRAIN_MARSH`, `TERRAIN_SAND`, `TERRAIN_TEMPERATE`, `TERRAIN_TUNDRA`, `TERRAIN_URBAN`, `TERRAIN_WATER`.

These sprites have been through the hex masking pipeline (see below). They are ready to tile on a pointy-top hex grid.

### Height (211x181, hex-masked)

3 sprites: `HEIGHT_HILL`, `HEIGHT_MOUNTAIN`, `HEIGHT_VOLCANO`.

Same dimensions and masking as terrain. Heights are drawn on top of terrain at the same hex position. Flat tiles and ocean tiles have no height sprite — skip them.

### Improvement (200x200)

~132 sprites covering all tile improvements (farms, mines, quarries, temples, etc.). These are square icons, not hex-shaped. They render as point sprites centered on each hex.

### Resource (64x64)

~40 sprites for resources and goods. Small square icons. Render offset slightly from hex center to avoid overlapping with improvements on the same tile.

### Specialist (128x128)

~26 specialist profession icons. Square icons.

### City (136x136)

Combines sprites from two extraction categories (crests and city). Includes nation crests, family crests, city site markers, and capital markers.

## Hex Masking

Terrain and height sprites have a hex mask baked into their alpha channel. This is tile preparation, not an artistic choice — it solves two mechanical problems:

1. **Shadow bleed**: Raw terrain sprites have 3D shadows that extend beyond hex boundaries. The mask clips them cleanly.
2. **Seamless tiling**: Adjacent hex sprites need to overlap slightly to avoid gaps. The mask + dilation pipeline ensures the overlap region has color data instead of transparency.

### Pipeline

1. **Resize** to 211x181 (centered, aspect-preserving, LANCZOS). Height sprites need this since their source dimensions vary. Terrain sprites are already approximately this size.
2. **Edge dilation** (50 iterations): Expand opaque pixels outward into transparent areas by copying RGB values from neighboring opaque pixels. This fills the edges that will be hidden under neighboring tiles.
3. **Hex clip**: Apply a pointy-top elliptical hexagon (radii 120x88 pixels) as the alpha channel. Pixels inside the hex are opaque; outside are transparent.

### Mask Geometry

```
Sprite canvas:   211 x 181 pixels
Hex radii:       120 (horizontal) x 88 (vertical)
Hex orientation:  Pointy-top
Hex center:       (105.5, 90.5) — centered on canvas
```

The hex is the largest ellipse that fits inside the sprite with ~1-3px margin.

## Hex Grid Coordinate System

Old World uses pointy-top hexagons. The renderer's coordinate system must match the masked sprite geometry.

### Hex Spacing

```
Horizontal spacing: 199 pixels (between hex centers, same row)
Vertical spacing:   132 pixels (between hex centers, same column)
```

The horizontal spacing (199) is less than the sprite width (211), creating 12px of intentional overlap. The vertical spacing (132) equals 1.5 * HEX_RADIUS_Y — the standard pointy-top tessellation formula. These overlaps hide any seams between adjacent masked sprites.

### Avoiding Tile Seams

The overlap and edge dilation are necessary but not sufficient to prevent visible seams. If sprites are placed as individual objects and the renderer snaps each one to integer pixel positions independently, sub-pixel rounding mismatches between adjacent tiles can still produce hairline gaps where the background shows through. This is especially visible on water tiles where the uniform color makes even a 1px black line obvious.

The recommended approach is to **composite terrain into a single image** (see the BitmapLayer section below) rather than rendering individual tile sprites. Drawing tiles onto one canvas with `drawImage()` handles sub-pixel positioning correctly and eliminates inter-tile seams entirely.

### Coordinate Conversion

```typescript
const HEX_H_SPACING = 199;
const HEX_V_SPACING = 132;

function hexToPixel(x: number, y: number): [number, number] {
  const px = x * HEX_H_SPACING + ((y + 1) % 2) * (HEX_H_SPACING / 2);
  const py = -(y * HEX_V_SPACING);
  return [px, py];
}
```

- Even-r offset: odd rows are shifted right by half the horizontal spacing (`(y + 1) % 2`).
- Y is negated because Old World's coordinate system has Y=0 at the south, while screen coordinates have Y=0 at the top.
- The exact offset convention (`y + 1` vs `y`) matches the game's save data format.

## Using Atlases with deck.gl

### Loading

Load atlas images and manifests once on startup, then cache for the session.

```typescript
interface AtlasManifest {
  atlas: string;
  cellWidth: number;
  cellHeight: number;
  sprites: Record<string, { x: number; y: number; width: number; height: number }>;
}

async function loadAtlas(basePath: string, name: string): Promise<{
  image: ImageBitmap;
  manifest: AtlasManifest;
}> {
  const [imageResponse, manifestResponse] = await Promise.all([
    fetch(`${basePath}/${name}.webp`),
    fetch(`${basePath}/${name}.json`),
  ]);

  const manifest: AtlasManifest = await manifestResponse.json();
  const blob = await imageResponse.blob();
  const image = await createImageBitmap(blob);

  return { image, manifest };
}
```

### Terrain: Pre-composited BitmapLayer

Terrain sprites tile the entire map. Since every hex has a terrain type and terrain only changes on turn change, composite all terrain + height sprites into a single image and render it as one `BitmapLayer`.

```typescript
function compositeTerrainImage(
  tiles: MapTile[],
  terrainAtlas: ImageBitmap,
  terrainManifest: AtlasManifest,
  heightAtlas: ImageBitmap,
  heightManifest: AtlasManifest,
): ImageBitmap {
  const bounds = calculateMapBounds(tiles);
  const canvas = new OffscreenCanvas(bounds.width, bounds.height);
  const ctx = canvas.getContext('2d')!;

  // Draw terrain base
  for (const tile of tiles) {
    const sprite = terrainManifest.sprites[tile.terrain];
    if (!sprite) continue;

    const [px, py] = hexToPixel(tile.x, tile.y);
    ctx.drawImage(
      terrainAtlas,
      sprite.x, sprite.y, sprite.width, sprite.height,
      px - sprite.width / 2 + bounds.offsetX,
      py - sprite.height / 2 + bounds.offsetY,
      sprite.width, sprite.height,
    );
  }

  // Draw heights on top at the same positions
  for (const tile of tiles) {
    if (!tile.height || tile.height === 'HEIGHT_FLAT' || tile.height === 'HEIGHT_OCEAN') continue;
    const sprite = heightManifest.sprites[tile.height];
    if (!sprite) continue;

    const [px, py] = hexToPixel(tile.x, tile.y);
    ctx.drawImage(
      heightAtlas,
      sprite.x, sprite.y, sprite.width, sprite.height,
      px - sprite.width / 2 + bounds.offsetX,
      py - sprite.height / 2 + bounds.offsetY,
      sprite.width, sprite.height,
    );
  }

  return canvas.transferToImageBitmap();
}
```

Render the result as:

```typescript
new BitmapLayer({
  id: 'terrain-layer',
  image: compositedTerrainBitmap,
  bounds: [mapLeft, mapBottom, mapRight, mapTop],
})
```

This compositing runs once per turn change (~50ms for ~2000 tiles), not per frame.

### Overlay Icons: IconLayer

Improvements, resources, specialists, and cities render as `IconLayer` instances. Convert the atlas manifest to deck.gl's icon mapping format:

```typescript
function toIconMapping(
  manifest: AtlasManifest,
): Record<string, { x: number; y: number; width: number; height: number; zanchorY: number }> {
  const mapping: Record<string, any> = {};
  for (const [name, rect] of Object.entries(manifest.sprites)) {
    mapping[name] = {
      x: rect.x,
      y: rect.y,
      width: rect.width,
      height: rect.height,
      anchorY: rect.height / 2,
    };
  }
  return mapping;
}
```

Then use in a layer:

```typescript
new IconLayer({
  id: 'improvement-layer',
  data: tiles.filter(t => t.improvement),
  iconAtlas: improvementAtlas,
  iconMapping: toIconMapping(improvementManifest),
  getIcon: (d) => d.improvement,
  getPosition: (d) => hexToPixel(d.x, d.y),
  getSize: 36,
  sizeUnits: 'common',
  sizeMinPixels: 8,
  sizeMaxPixels: 64,
})
```

### Layer Ordering

Render layers bottom to top:

1. **Terrain** (`BitmapLayer`) — pre-composited terrain + height
2. **Ownership** (`PolygonLayer`) — translucent hex fills showing nation control (~30% opacity)
3. **Borders** (`PathLayer`) — colored lines at territory edges
4. **Improvements** (`IconLayer`)
5. **Resources** (`IconLayer`) — offset slightly from hex center to avoid overlap with improvements
6. **Specialists** (`IconLayer`)
7. **Cities** (`IconLayer` + `TextLayer` for labels)

## Atlas Size Limits

All atlases fit within 4096x4096 pixels, the minimum guaranteed texture size for WebGL2. The largest atlas is improvements (~132 sprites at 200x200), which packs into a ~2800x2600 grid.

For browser delivery (Cloudflare Workers, CDN), consider using lossy WebP (`--lossy 90`) to reduce file size. Lossless WebP terrain atlases are small (~100KB) but improvement atlases can be several MB. Lossy at quality 90+ is visually indistinguishable and significantly smaller.

## Regenerating Atlases

When game updates add new sprites:

```bash
# Re-extract all sprites (picks up new content automatically)
pinacotheca

# Regenerate atlases
pinacotheca-atlas
```

The atlas pipeline reads from extracted sprite directories and packs whatever it finds. New sprites appear automatically in the next atlas build as long as pinacotheca's category regex patterns match them.
