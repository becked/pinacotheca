# Material rendering pipeline

This doc covers everything between `bake_to_obj` (which emits the OBJ
string in baked render space) and the PNG that hits disk: the moderngl
context, vertex/fragment shaders, sampler binding, lighting envelope,
normal mapping, occlusion modulation, and the neutral team-color
pre-process. For the prefab-walking half of the pipeline (XML chain,
splat dropping, plinth strip, ground layering) see
`docs/extracting-3d-buildings.md`.

## Pipeline overview

```
PrefabPart list
   │
   │  bake_to_obj(parts, pre_rotation_y_deg=180.0)
   ▼
OBJ string (custom: includes `vtg x y z w` per-vertex tangent lines)
   │
   │  strip_plinth_from_obj(...)         (improvements only)
   ▼
OBJ string (filtered)
   │
   │  render_mesh_to_image(obj, diffuse,
   │                       packed_pbr_image=...,
   │                       normal_map_image=...,
   │                       flat_lighting=...,
   │                       bbox_override=..., ...)
   ▼
PIL RGBA Image
```

`render_mesh_to_image` does its own OBJ parse, builds an interleaved
vertex buffer, sets up an offscreen moderngl framebuffer, binds three
samplers (or 1×1 placeholders), runs vertex+fragment shaders, reads the
color attachment, optionally autocrops, and returns the PIL image.

## Vertex format

Interleaved layout per vertex, 12 floats (48 bytes):

| Slot | Source | Notes |
|---|---|---|
| `in_position` (3f) | OBJ `v` lines | Baked render-space, X negated, pre-rotation applied |
| `in_uv` (2f) | OBJ `vt` lines | Pass-through |
| `in_normal` (3f) | OBJ `vn` lines | Inverse-transpose of M[:3,:3], X negated |
| `in_tangent` (4f) | OBJ `vtg` lines | xyz transformed by M[:3,:3] (true vector, not inv-transpose), X negated, w sign-flipped |

The `vtg` line is a custom OBJ extension this codebase introduced. Faces
keep standard `v/vt/vn` syntax; tangents are looked up by vertex index
in `build_vertex_buffer`. When a mesh has no authored tangents, no `vtg`
lines are emitted and the vertex buffer falls back to `(1, 0, 0, 1)`
per vertex (the renderer also gates `use_normal_map = 0` so the
defaulted basis isn't sampled). `parse_obj` and
`_parse_obj_vertices_and_faces` both ignore unknown line prefixes, so
the plinth-strip code path passes `vtg` through untouched.

External tools (Blender, etc.) consuming our intermediate OBJ would
silently drop tangents — the OBJ is purely an internal pipe between
`bake_to_obj` and `render_mesh_to_image`, not a portable interchange
format.

## Sampler binding

Three texture units, all bound on every render call. When the optional
texture isn't supplied, a 1×1 placeholder is bound and the
corresponding `use_*` uniform is set to 0 so the shader skips that
sampler's contribution.

| Unit | Sampler | Source | Placeholder |
|---|---|---|---|
| 0 | `texture0` | diffuse / albedo | required (passed via `texture_image`) |
| 1 | `texture1` | tangent-space normal map | 1×1 RGBA `(128, 128, 128, 128)` (decoded as flat normal) |
| 2 | `texture2` | packed metallic/roughness/occlusion/teamcolor | 1×1 white |

Texture-key discovery for the optional samplers:

- `find_diffuse_for_prefab` — keys `_BaseColorMap`, `_BaseMap`,
  `_MainTex`, `_BaseColor`. Result has the neutral team-color
  pre-process applied (see below).
- `find_normal_map_for_prefab` — keys `_BumpMap`, `_NormalMap`.
- `find_packed_pbr_for_prefab` — keys
  `_MetalicRoughnessOcclusionTeamColor`, `_NormalMetalicRoughness`.
  Refuses textures whose B-channel mean is below 0.5 (Library-style
  `_DetailTexture` puts non-occlusion data in B and would crush the
  surface to dark).

All three share `_find_texture_for_prefab(parts, allowed_keys)` which
picks the largest-area decoded texture across all materials so a small
atlas/detail entry doesn't beat the prefab's main map.

## Lighting envelope

The fragment shader computes a per-pixel directional shading factor and
multiplies the diffuse color:

```glsl
float ndotl = dot(N, light_dir);                         // [-1, 1]
float diffuse = mix(min_brightness, 1.0, ndotl*0.5+0.5); // [min, 1]
lit.rgb = tex_color.rgb * diffuse;
```

`min_brightness` is a uniform set per render:

| Caller | Value | Effect |
|---|---|---|
| Buildings, units, improvements | `0.4` | 60% range, visible face contrast, back faces darken to 40% |
| Ground layers (`flat_lighting=True`) | `1.0` | No directional shading; diffuse passes through unattenuated |

The `flat_lighting=True` path is for the biome quad and per-nation PVT
planes in `layered_render.py`. They're horizontal Quads with a uniform
geometric normal — the directional term would just dim every pixel by
the same factor.

The 0.4 floor is a tuning knob in `renderer.py` (search for
`min_brightness`) — drop it for stronger shadows, raise it for a
flatter look. See the iteration history in this doc's git log.

## Normal mapping

### DXT5nm channel convention

Old World normal maps are `m_TextureFormat=12` (DXT5/BC3) using Unity's
HDRP DXT5nm encoding:

- **R = constant `1.0`** (encoder fills max; not sampled)
- **G = Y normal** (variable around 0.5, std ~0.1)
- **B = X normal (low precision)** — same data as A but from the BC3
  RGB block (5/6/5 bits)
- **A = X normal (high precision)** — from the BC3 alpha block (8-bit
  interpolated)

We sample `n_sample.a` for X and `n_sample.g` for Y in the fragment
shader. UnityPy's stock `tex.image` decodes BC3 as RGBA in PIL's
standard layout, no extra swizzle needed at decode time.

Verified probe data (Aksum, `tools/probes`):

```
AksumCapitol_Normal channel stats:
  R: min=255 max=255 mean=255.0 std=0.0     (constant — confirms encoder pattern)
  G: min=0   max=255 mean=127.2 std=26.1    (Y component)
  B: min=0   max=255 mean=127.1 std=26.1    (X low-precision)
  A: min=0   max=255 mean=126.9 std=20.6    (X high-precision)
```

### Fragment shader

```glsl
vec4 n_sample = texture(texture1, v_uv);
vec2 nm_xy = vec2(n_sample.a, n_sample.g) * 2.0 - 1.0;
float nm_z = sqrt(max(0.0, 1.0 - dot(nm_xy, nm_xy)));
vec3 n_ts = vec3(nm_xy, nm_z);
N = normalize(v_tbn * n_ts);
```

`max(0, ...)` under the sqrt guards against numerical jitter at
`nm_xy = (1, 1)`. The `v_tbn` matrix is built in the vertex shader from
the per-vertex `in_tangent` plus geometric normal, with Gram-Schmidt
re-orthogonalisation.

### TBN matrix construction

```glsl
vec3 N = normalize(in_normal);
vec3 T = normalize(in_tangent.xyz);
T = normalize(T - dot(T, N) * N);  // Gram-Schmidt against N
vec3 B = cross(N, T) * in_tangent.w;
v_tbn = mat3(T, B, N);
```

`in_tangent.w` is Unity's bitangent sign — kept through the OBJ pipe
in the `vtg` line's 4th component, with one sign flip during `bake_to_obj`
to compensate for the cross-product handedness change under the
coordinate X-flip (see "Tangent transport" below).

### Tangent transport through `bake_to_obj`

UnityPy exposes `MeshHandler.m_Tangents: list[(x, y, z, w)]` after
`process()`. When present, `bake_to_obj` emits one `vtg x y z w` line
per vertex:

```python
# Tangent xyz transforms as a true vector under m3 (NOT inverse-transpose
# — tangents lie in the surface plane and follow geometric scale/rotation).
wtx = m3 @ (tx, ty, tz)

# Negate X (matches positions/normals) and flip bitangent sign in w to
# compensate for the cross-product handedness change when the coordinate
# frame reflects.
sb.append(f"vtg {-wtx[0]} {wtx[1]} {wtx[2]} {-tw}\n")
```

The X-negate + w-flip pair is verified by tests
(`test_bake_to_obj_emits_vtg_when_tangents_present`).

### Fallback when tangents are absent

`m_Tangents = None` → no `vtg` lines emitted → vertex buffer fills
default `(1, 0, 0, 1)` per vertex AND the renderer sets
`use_normal_map = 0`. Result: identical to the pre-normal-mapping path.

## Occlusion modulation

```glsl
if (use_packed_pbr == 1) {
    float occ = texture(texture2, v_uv).b;
    lit *= mix(1.0, occ, occlusion_strength);
}
```

`occlusion_strength` defaults to `0.6` — visible darks at concave
joints (alcoves, cornice undersides, courtyards) without crushing
mid-toned surfaces. Range: 0 (no effect) to 1 (raw occlusion fully
applied).

The B-channel-mean threshold in `find_packed_pbr_for_prefab` (refuses
< 0.5) prevents Library-style `_DetailTexture` materials — which use B
for non-occlusion data with mean ~0.17 — from being misinterpreted.
Verified across `AksumCapitol`, `Maurya`, `Tamil`, `Library`,
`Granary`.

Channel layout of the packed texture varies across materials. Building
materials follow:

| Channel | Aksum | Maurya | Library | Notes |
|---|---|---|---|---|
| R | 0 (unused) | sparse 0-255 (mean 7) | 0 | metallic mask, often unused |
| G | 113-248 (mean 187) | 40-255 (mean 210) | 162-239 (mean 216) | roughness-shaped |
| B | 198-255 (mean 254) | 0-255 (mean 236) | 0-82 (mean 44) | occlusion (high mean) — Library uses different convention |
| A | 255 | sparse 0-255 (mean 3) | sparse | team-color mask (when present), often empty |

We don't sample R, G, or A today; they're reserved for future
metallic/roughness/team-mask work.

## Neutral team color (pink replacement)

Old World building diffuse textures (Aksum's most visibly) carry
hand-painted pink regions intended for runtime tinting via the
`_PrimaryTeamColor` shader uniform (`ImprovementRenderer.cs:290`,
`DefaultRenderer.cs:202-205`). Our offline renderer has no player
context, so the tint never happens and the raw pink reads through.

`apply_neutral_team_color(diffuse)` in `prefab.py` swaps pink pixels for
mid-gray:

```python
pink = (R > 200) & (130 < G < 200) & (130 < B < 200)
arr[pink, :3] = 180
```

The range is intentionally narrow to avoid touching legitimate pink art
(Egyptian frescoes, decorative motifs). The replacement happens inside
`find_diffuse_for_prefab` as a pre-process — every caller of that
function gets the cleaned image automatically.

We tried to use a proper team-color mask (sample one of the packed
texture channels) but probing showed no reliable cross-prefab signal:
Aksum's R is uniformly 0, A is uniformly 255, and Maurya/Tamil's R/A
have sparse data that doesn't align with the pink pixels in the
diffuse. Color-key replacement is the right answer for the
neutral-tint case.

## Tuning knobs

All in `renderer.py` unless noted.

| Knob | Where | Default | Effect |
|---|---|---|---|
| `min_brightness` (uniform) | shader + `render_mesh_to_image` | 0.4 (buildings) / 1.0 (flat) | Lighting envelope floor |
| `occlusion_strength` (uniform) | shader + `render_mesh_to_image` | 0.6 | Strength of B-channel darks |
| Pink range | `apply_neutral_team_color` in `prefab.py` | `R>200 ∧ 130<G<200 ∧ 130<B<200` | Which diffuse pixels become gray |
| Pink replacement color | `apply_neutral_team_color` in `prefab.py` | `(180, 180, 180)` | What pink becomes |
| B-mean occlusion threshold | `find_packed_pbr_for_prefab` in `prefab.py` | 0.5 | Above which the packed texture is used as occlusion |
| Normal map intensity | not implemented | n/a | If we ever want to amplify the per-fragment perturbation, multiply `nm_xy` by a scalar in the shader |

## File map

- `src/pinacotheca/renderer.py` — moderngl context, shaders, vertex
  buffer build, sampler binding, framebuffer, autocrop. The
  `render_mesh_to_image` entry point.
- `src/pinacotheca/prefab.py` — `bake_to_obj` (emits `vtg`),
  `_find_texture_for_prefab` (shared search), `find_diffuse_for_prefab`,
  `find_normal_map_for_prefab`, `find_packed_pbr_for_prefab`,
  `apply_neutral_team_color`.
- `src/pinacotheca/layered_render.py` — orchestrates the multi-pass
  composite for capitals + urban tiles. Sets `flat_lighting=True` for
  biome and per-nation PVT layers; passes `packed_pbr_image` and
  `normal_map_image` into the buildings layer.
- `src/pinacotheca/extractor.py` — calls the find_* helpers and
  threads the optional textures into `render_mesh_to_image` at the
  three improvement render call sites.

## Reference

Decompiled C# (read-only from `decompiled/Assembly-CSharp/`):

- `ImprovementRenderer.cs:290` — `SetTeamColor` sets
  `_PrimaryTeamColor` uniform on building materials at runtime
- `DefaultRenderer.cs:199-205` — `setAssetMainColor` /
  `setAssetTeamColor` set `_Color` / `_TeamColor` per material
- `TerrainTexturePVTSplat.cs:48-99` — terrain splat material
  properties (`_NormalMetalicRoughness`, `_Metallicmap`, etc.) —
  similar pattern to building packed textures but separate code path
- `ColorChannel.cs:1-7` — `enum ColorChannel { Red, Green, Blue, Alpha }`
  (verified 0=R 1=G 2=B 3=A)

Tests:

- `tests/test_team_color.py` — pink replacement range and
  preserves-other-colors guarantees
- `tests/test_prefab.py::test_bake_to_obj_emits_vtg_when_tangents_present`
  — `vtg` emission with X-negate + w-flip
- `tests/test_prefab.py::test_bake_to_obj_skips_vtg_without_tangents`
  — fallback path when meshes lack tangents
- `tests/test_renderer.py::test_bbox_override_shrinks_the_footprint`
  — frame override, end-to-end through the OpenGL pipeline
