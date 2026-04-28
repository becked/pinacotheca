"""Hand-parse TerrainTexturePVTSplat and TerrainHeightSplat MonoBehaviour
binary against the field layout from the decompiled C# source.

Validates Open Question #1's mitigation path: if we can't use UnityPy's
TypeTree reader (verified absent), can we read raw bytes and recover the
per-nation texture references?

Field layout (from ~/Desktop/Old World/decompiled/Assembly-CSharp/):

  TerrainSplatBase (abstract)
    int sortingOffset                       4 bytes

  TerrainTexturePVTSplat : TerrainSplatBase
    bool packInAtlas                        4 (1 + 3 align)
    Texture albedoAtlas                    12 (PPtr)
    Texture alphaAtlas                     12
    Texture normalMetalicRoughnessAtlas    12
    bool useSimpleMode                      4
    Material material                      12
    bool materialUseWorldUVs                4
    float materialTiling                    4
    Texture albedoMap                      12
    Texture normalMap                      12
    Texture metallicMap                    12
    Texture roughnessMap                   12
    Texture alphaMap                       12
    int alphaMapChannel (enum)              4
    Color albedoTint                       16 (4 floats)
    float normalMapIntensity                4
    float metallic                          4
    float roughness                         4
    int atlasIndex                          4
    Vector4 textureArrayIndices            16 (4 floats)
                                          ===
                                          180 bytes (matches 212 - 32 header)

  TerrainHeightSplat : TerrainSplatBase
    bool useSimpleMode                      4
    Material material                      12
    bool overrideWorldUvIsOn                4
    float intensity                         4
    float tiling                            4
    float rgbHeightmapMiddle                4
    Vector2 alphamapScaleBias               8
    Texture rgbHeightmap                   12
    Texture heightmap                      12
                                          ===
                                          64 bytes (matches 100 - 32 header - 4 sortingOffset)

PPtr binary form: int32 m_FileID + int64 m_PathID = 12 bytes, little-endian.
"""

from __future__ import annotations

import os
import struct
from collections import deque
from dataclasses import dataclass
from typing import Any

import UnityPy

from pinacotheca.extractor import find_game_data
from pinacotheca.prefab import _components_of, find_root_gameobject


@dataclass
class PPtr:
    file_id: int
    path_id: int

    def is_null(self) -> bool:
        return self.file_id == 0 and self.path_id == 0


@dataclass
class PVTSplatFields:
    sorting_offset: int
    pack_in_atlas: bool
    albedo_atlas: PPtr
    alpha_atlas: PPtr
    normal_metalic_roughness_atlas: PPtr
    use_simple_mode: bool
    material: PPtr
    material_use_world_uvs: bool
    material_tiling: float
    albedo_map: PPtr
    normal_map: PPtr
    metallic_map: PPtr
    roughness_map: PPtr
    alpha_map: PPtr
    alpha_map_channel: int
    albedo_tint: tuple[float, float, float, float]
    normal_map_intensity: float
    metallic: float
    roughness: float
    atlas_index: int
    texture_array_indices: tuple[float, float, float, float]


@dataclass
class HeightSplatFields:
    sorting_offset: int
    use_simple_mode: bool
    material: PPtr
    override_world_uv: bool
    intensity: float
    tiling: float
    rgb_heightmap_middle: float
    alphamap_scale_bias: tuple[float, float]
    rgb_heightmap: PPtr
    heightmap: PPtr


class Reader:
    """Stream reader over a bytes buffer with Unity alignment helpers."""

    def __init__(self, data: bytes, offset: int = 0) -> None:
        self.data = data
        self.pos = offset

    def read_int32(self) -> int:
        v = struct.unpack_from("<i", self.data, self.pos)[0]
        self.pos += 4
        return v

    def read_int64(self) -> int:
        v = struct.unpack_from("<q", self.data, self.pos)[0]
        self.pos += 8
        return v

    def read_uint32(self) -> int:
        v = struct.unpack_from("<I", self.data, self.pos)[0]
        self.pos += 4
        return v

    def read_float(self) -> float:
        v = struct.unpack_from("<f", self.data, self.pos)[0]
        self.pos += 4
        return v

    def read_bool_aligned(self) -> bool:
        # Unity serializes bool as 1 byte then aligns to 4-byte boundary.
        v = self.data[self.pos] != 0
        self.pos += 1
        # Align up to next 4-byte boundary
        rem = self.pos % 4
        if rem != 0:
            self.pos += 4 - rem
        return v

    def read_pptr(self) -> PPtr:
        fid = self.read_int32()
        pid = self.read_int64()
        return PPtr(file_id=fid, path_id=pid)

    def read_color(self) -> tuple[float, float, float, float]:
        r = self.read_float()
        g = self.read_float()
        b = self.read_float()
        a = self.read_float()
        return (r, g, b, a)

    def read_vector4(self) -> tuple[float, float, float, float]:
        return self.read_color()

    def read_vector2(self) -> tuple[float, float]:
        return (self.read_float(), self.read_float())


# 32-byte MonoBehaviour header: m_GameObject PPtr (12) + m_Enabled aligned
# (4) + m_Script PPtr (12) + m_Name length-0 string (4). Un-named
# MonoBehaviours always serialize the name as a length-0 string.
_MB_HEADER_SIZE = 32


def parse_pvt_splat(data: bytes) -> PVTSplatFields:
    r = Reader(data, offset=_MB_HEADER_SIZE)
    return PVTSplatFields(
        sorting_offset=r.read_int32(),
        pack_in_atlas=r.read_bool_aligned(),
        albedo_atlas=r.read_pptr(),
        alpha_atlas=r.read_pptr(),
        normal_metalic_roughness_atlas=r.read_pptr(),
        use_simple_mode=r.read_bool_aligned(),
        material=r.read_pptr(),
        material_use_world_uvs=r.read_bool_aligned(),
        material_tiling=r.read_float(),
        albedo_map=r.read_pptr(),
        normal_map=r.read_pptr(),
        metallic_map=r.read_pptr(),
        roughness_map=r.read_pptr(),
        alpha_map=r.read_pptr(),
        alpha_map_channel=r.read_int32(),
        albedo_tint=r.read_color(),
        normal_map_intensity=r.read_float(),
        metallic=r.read_float(),
        roughness=r.read_float(),
        atlas_index=r.read_int32(),
        texture_array_indices=r.read_vector4(),
    )


def parse_height_splat(data: bytes) -> HeightSplatFields:
    r = Reader(data, offset=_MB_HEADER_SIZE)
    return HeightSplatFields(
        sorting_offset=r.read_int32(),
        use_simple_mode=r.read_bool_aligned(),
        material=r.read_pptr(),
        override_world_uv=r.read_bool_aligned(),
        intensity=r.read_float(),
        tiling=r.read_float(),
        rgb_heightmap_middle=r.read_float(),
        alphamap_scale_bias=r.read_vector2(),
        rgb_heightmap=r.read_pptr(),
        heightmap=r.read_pptr(),
    )


def resolve_pptr_name(pptr: PPtr, assets_file: Any) -> str | None:
    """Resolve a PPtr to its referent's m_Name. Returns None for null PPtrs."""
    if pptr.is_null():
        return None
    try:
        if pptr.file_id == 0:
            target = assets_file.objects.get(pptr.path_id)
        else:
            ext = assets_file.externals[pptr.file_id - 1]
            ef = getattr(ext, "assets_file", None) or getattr(ext, "asset_file", None)
            if ef is None:
                env = assets_file.parent
                ext_name = getattr(ext, "path", None) or getattr(ext, "file_name", None)
                if env is not None and ext_name is not None:
                    for fname, fobj in env.files.items():
                        if fname.endswith(ext_name) or ext_name.endswith(fname):
                            ef = fobj
                            break
            if ef is None:
                return f"<extern fid={pptr.file_id} pid={pptr.path_id}>"
            target = ef.objects.get(pptr.path_id)
        if target is None:
            return f"<not found pathID={pptr.path_id}>"
        obj = target.parse_as_object()
        return getattr(obj, "m_Name", None)
    except Exception as e:
        return f"<resolve err: {type(e).__name__}: {e}>"


def walk_tree(root_go: Any) -> list[Any]:
    out: list[Any] = [root_go]
    t = None
    for pptr in _components_of(root_go):
        try:
            r = pptr.deref()
            if r.type.name == "Transform":
                t = pptr.deref_parse_as_object()
                break
        except Exception:
            pass
    if t is None:
        return out
    stack: deque = deque([t])
    while stack:
        node = stack.popleft()
        for k in getattr(node, "m_Children", None) or []:
            try:
                if not bool(k):
                    continue
                child_t = k.deref_parse_as_object()
                gp = getattr(child_t, "m_GameObject", None)
                if gp and bool(gp):
                    out.append(gp.deref_parse_as_object())
                stack.append(child_t)
            except Exception:
                pass
    return out


def script_class(reader: Any) -> str:
    raw = reader.get_raw_data()
    if len(raw) < 32:
        return "?"
    # m_Script PPtr is at offset 16 (after m_GameObject 12 + m_Enabled aligned 4)
    file_id, path_id = struct.unpack_from("<iq", raw, 16)
    if path_id == 0:
        return "<no script>"
    af = reader.assets_file
    if file_id == 0:
        target = af.objects.get(path_id)
    else:
        ext = af.externals[file_id - 1]
        ef = getattr(ext, "assets_file", None) or getattr(ext, "asset_file", None)
        if ef is None:
            # Try resolving the external by name via the parent environment.
            try:
                env = af.parent
                ext_name = getattr(ext, "path", None) or getattr(ext, "file_name", None)
                if env is not None and ext_name is not None:
                    for fname, fobj in env.files.items():
                        if fname.endswith(ext_name) or ext_name.endswith(fname):
                            ef = fobj
                            break
            except Exception:
                pass
        if ef is None:
            return f"<extern fid={file_id} pid={path_id}>"
        target = ef.objects.get(path_id)
    if target is None:
        return f"<not found pathID={path_id}>"
    script = target.parse_as_object()
    return getattr(script, "m_ClassName", None) or getattr(script, "m_Name", "?")


def main() -> None:
    game_data = find_game_data()
    assert game_data is not None
    os.chdir(str(game_data))
    env = UnityPy.Environment()
    # Load resources.assets and globalgamemanagers.assets — script class names
    # live in the latter as external references from the former.
    env.load_file(str(game_data / "globalgamemanagers.assets"))
    env.load_file(str(game_data / "resources.assets"))

    targets = [
        "Greece_Capital",
        "Rome_Capital",
        "Egypt_Capital",
        "Persia_Capital",
        "Babylonia_Capital",
        "Carthage_Capital",
        "Assyria_Capital",
    ]
    for prefab_name in targets:
        root = find_root_gameobject(env, prefab_name)
        if root is None:
            print(f"\n=== {prefab_name}: NOT FOUND ===")
            continue
        gos = walk_tree(root)
        print(f"\n=== {prefab_name} ===")
        for go in gos:
            go_name = getattr(go, "m_Name", "?")
            for pptr in _components_of(go):
                try:
                    r = pptr.deref()
                    if r.type.name != "MonoBehaviour":
                        continue
                except Exception:
                    continue
                cls = script_class(r)
                if cls not in ("TerrainTexturePVTSplat", "TerrainHeightSplat"):
                    continue
                assets_file = r.assets_file
                try:
                    raw = r.get_raw_data()
                except Exception as e:
                    print(f"  [{go_name}] {cls}: get_raw_data failed: {e}")
                    continue
                print(f"\n  [{go_name}] {cls}  ({len(raw)} bytes)")
                try:
                    if cls == "TerrainTexturePVTSplat":
                        f = parse_pvt_splat(raw)
                        print(f"    sortingOffset={f.sorting_offset}")
                        print(f"    packInAtlas={f.pack_in_atlas}  useSimpleMode={f.use_simple_mode}")
                        print(f"    materialTiling={f.material_tiling:.3f}  useWorldUVs={f.material_use_world_uvs}")
                        print(f"    albedoTint=({f.albedo_tint[0]:.2f},{f.albedo_tint[1]:.2f},{f.albedo_tint[2]:.2f},{f.albedo_tint[3]:.2f})")
                        print(f"    normalIntensity={f.normal_map_intensity:.2f}  metallic={f.metallic:.2f}  roughness={f.roughness:.2f}")
                        print(f"    alphaMapChannel={f.alpha_map_channel}  atlasIndex={f.atlas_index}")
                        for label, pp in [
                            ("material", f.material),
                            ("albedoMap", f.albedo_map),
                            ("normalMap", f.normal_map),
                            ("metallicMap", f.metallic_map),
                            ("roughnessMap", f.roughness_map),
                            ("alphaMap", f.alpha_map),
                            ("albedoAtlas", f.albedo_atlas),
                            ("alphaAtlas", f.alpha_atlas),
                            ("nmrAtlas", f.normal_metalic_roughness_atlas),
                        ]:
                            name = resolve_pptr_name(pp, assets_file)
                            if name:
                                print(f"    {label}: {name}  (fid={pp.file_id} pid={pp.path_id})")
                            elif not pp.is_null():
                                print(f"    {label}: <unresolved> (fid={pp.file_id} pid={pp.path_id})")
                    else:  # TerrainHeightSplat
                        h = parse_height_splat(raw)
                        print(f"    sortingOffset={h.sorting_offset}  useSimpleMode={h.use_simple_mode}")
                        print(f"    intensity={h.intensity:.3f}  tiling={h.tiling:.3f}  middle={h.rgb_heightmap_middle:.3f}")
                        print(f"    overrideWorldUV={h.override_world_uv}  alphamapScaleBias={h.alphamap_scale_bias}")
                        for label, pp in [
                            ("material", h.material),
                            ("rgbHeightmap", h.rgb_heightmap),
                            ("heightmap", h.heightmap),
                        ]:
                            name = resolve_pptr_name(pp, assets_file)
                            if name:
                                print(f"    {label}: {name}  (fid={pp.file_id} pid={pp.path_id})")
                            elif not pp.is_null():
                                print(f"    {label}: <unresolved> (fid={pp.file_id} pid={pp.path_id})")
                except Exception as e:
                    print(f"    PARSE FAIL: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
