"""
3D mesh rendering to 2D images using moderngl.

Provides headless OpenGL rendering for converting 3D unit meshes
to 2D PNG images with textures applied.
"""

from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray

if TYPE_CHECKING:
    from PIL import Image


def parse_obj(
    obj_data: str,
) -> tuple[
    list[list[float]],
    list[list[float]],
    list[list[float]],
    list[list[tuple[int, int, int]]],
    list[list[float]],
]:
    """
    Parse OBJ file content into vertices, UVs, normals, faces, and tangents.

    The trailing tangents list is keyed by vertex index (same indexing as
    `v` lines) and is populated from non-standard `vtg x y z w` lines —
    see `prefab.bake_to_obj` for the emission. Empty when the OBJ has no
    tangent data.

    Args:
        obj_data: OBJ file content as string

    Returns:
        Tuple of (vertices, uvs, normals, faces, tangents)
        where faces contains tuples of (vertex_idx, uv_idx, normal_idx).
    """
    vertices: list[list[float]] = []
    uvs: list[list[float]] = []
    normals: list[list[float]] = []
    faces: list[list[tuple[int, int, int]]] = []
    tangents: list[list[float]] = []

    for line in obj_data.split("\n"):
        parts = line.strip().split()
        if not parts:
            continue

        if parts[0] == "v":
            vertices.append([float(x) for x in parts[1:4]])
        elif parts[0] == "vt":
            uvs.append([float(x) for x in parts[1:3]])
        elif parts[0] == "vn":
            normals.append([float(x) for x in parts[1:4]])
        elif parts[0] == "vtg":
            tangents.append([float(x) for x in parts[1:5]])
        elif parts[0] == "f":
            face: list[tuple[int, int, int]] = []
            for vert in parts[1:]:
                indices = vert.split("/")
                v_idx = int(indices[0]) - 1  # OBJ is 1-indexed
                vt_idx = int(indices[1]) - 1 if len(indices) > 1 and indices[1] else 0
                vn_idx = int(indices[2]) - 1 if len(indices) > 2 and indices[2] else 0
                face.append((v_idx, vt_idx, vn_idx))
            faces.append(face)

    return vertices, uvs, normals, faces, tangents


def build_vertex_buffer(
    vertices: list[list[float]],
    uvs: list[list[float]],
    normals: list[list[float]],
    faces: list[list[tuple[int, int, int]]],
    tangents: list[list[float]] | None = None,
) -> NDArray[np.float32]:
    """
    Build interleaved vertex buffer from parsed OBJ data.

    Layout per vertex: position (3f), UV (2f), normal (3f), tangent (4f).
    When tangent data isn't available for a vertex, a default
    `(1, 0, 0, 1)` is emitted so the renderer's TBN math still produces
    a valid (if arbitrary) basis — the fragment shader skips normal-map
    sampling via the `use_normal_map` uniform in that case.

    Args:
        vertices: List of [x, y, z] positions
        uvs: List of [u, v] texture coordinates
        normals: List of [nx, ny, nz] normals
        faces: List of faces, each containing (v_idx, vt_idx, vn_idx) tuples
        tangents: Optional list of [tx, ty, tz, w] tangents (per vertex,
            indexed by v_idx). When None or shorter than the vertex
            count for a given face vertex, the default is emitted.

    Returns:
        Numpy array of interleaved vertex data (position, uv, normal, tangent)
    """
    vertex_data: list[float] = []
    has_tangents = tangents is not None and len(tangents) > 0

    for face in faces:
        for v_idx, vt_idx, vn_idx in face:
            vertex_data.extend(vertices[v_idx])  # xyz
            vertex_data.extend(uvs[vt_idx] if uvs else [0.0, 0.0])  # uv
            vertex_data.extend(normals[vn_idx] if normals else [0.0, 0.0, 1.0])  # normal
            if has_tangents and v_idx < len(tangents):  # type: ignore[arg-type]
                vertex_data.extend(tangents[v_idx])  # type: ignore[index]
            else:
                vertex_data.extend([1.0, 0.0, 0.0, 1.0])

    return np.array(vertex_data, dtype="f4")


def compute_mesh_bounds(
    vertices: list[list[float]],
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    """
    Compute bounding box and center of mesh.

    Args:
        vertices: List of [x, y, z] positions

    Returns:
        Tuple of (center, extent, min_bounds)
    """
    verts = np.array(vertices)
    min_bounds = verts.min(axis=0)
    max_bounds = verts.max(axis=0)
    center = (min_bounds + max_bounds) / 2
    extent = max_bounds - min_bounds
    return center, extent, min_bounds


def perspective_matrix(fov: float, aspect: float, near: float, far: float) -> NDArray[np.float32]:
    """Create perspective projection matrix."""
    f = 1.0 / np.tan(fov / 2)
    return np.array(
        [
            [f / aspect, 0, 0, 0],
            [0, f, 0, 0],
            [0, 0, (far + near) / (near - far), (2 * far * near) / (near - far)],
            [0, 0, -1, 0],
        ],
        dtype="f4",
    )


def orthographic_matrix(
    left: float,
    right: float,
    bottom: float,
    top: float,
    near: float,
    far: float,
) -> NDArray[np.float32]:
    """Standard OpenGL orthographic projection matrix."""
    return np.array(
        [
            [2 / (right - left), 0, 0, -(right + left) / (right - left)],
            [0, 2 / (top - bottom), 0, -(top + bottom) / (top - bottom)],
            [0, 0, -2 / (far - near), -(far + near) / (far - near)],
            [0, 0, 0, 1],
        ],
        dtype="f4",
    )


def look_at_matrix(
    eye: NDArray[np.float64], target: NDArray[np.float64], up: NDArray[np.float64]
) -> NDArray[np.float32]:
    """Create view matrix looking from eye to target."""
    f = target - eye
    f = f / np.linalg.norm(f)
    s = np.cross(f, up)
    s = s / np.linalg.norm(s)
    u = np.cross(s, f)
    return np.array(
        [
            [s[0], s[1], s[2], -np.dot(s, eye)],
            [u[0], u[1], u[2], -np.dot(u, eye)],
            [-f[0], -f[1], -f[2], np.dot(f, eye)],
            [0, 0, 0, 1],
        ],
        dtype="f4",
    )


# Vertex shader: transform vertices and pass through UVs/normals/TBN.
# `in_tangent` is xyz tangent + w bitangent sign (Unity convention). The
# fragment shader uses v_tbn for normal-mapped lighting; when no normal
# map is bound, v_tbn isn't sampled.
VERTEX_SHADER = """
#version 330
in vec3 in_position;
in vec2 in_uv;
in vec3 in_normal;
in vec4 in_tangent;

out vec2 v_uv;
out vec3 v_normal;
out mat3 v_tbn;

uniform mat4 mvp;

void main() {
    gl_Position = mvp * vec4(in_position, 1.0);
    v_uv = in_uv;
    v_normal = in_normal;
    // Tangent-Bitangent-Normal frame for sampling tangent-space normal
    // maps. Re-orthogonalize T against N (Gram-Schmidt) for numerical
    // safety; B uses the bitangent sign in tangent.w (Unity convention).
    vec3 N = normalize(in_normal);
    vec3 T = normalize(in_tangent.xyz);
    T = normalize(T - dot(T, N) * N);
    vec3 B = cross(N, T) * in_tangent.w;
    v_tbn = mat3(T, B, N);
}
"""

# Fragment shader: sample texture with basic diffuse lighting +
# optional normal map + optional occlusion.
FRAGMENT_SHADER = """
#version 330
in vec2 v_uv;
in vec3 v_normal;
in mat3 v_tbn;
out vec4 fragColor;

uniform sampler2D texture0;  // diffuse / albedo
uniform sampler2D texture1;  // tangent-space normal map (DXT5nm: X in A, Y in G)
uniform sampler2D texture2;  // packed metallic/roughness/occlusion/teamcolor
                             //   — only B (occlusion) is sampled today
// Floor of the directional envelope. Set to 0.4 for buildings/units so
// back-facing and edge-on surfaces darken visibly while staying
// readable, leaving a 60% range for face-by-face shading. Set to 1.0
// for ground layers (the flat biome quad + per-nation PVT planes) where
// the directional term just dims a uniformly-oriented surface and the
// source albedo should pass through unattenuated.
uniform float min_brightness;
// Whether `texture1` should be sampled and used as a tangent-space normal.
// 0 → use the geometric v_normal (and v_tbn is unused).
uniform int use_normal_map;
// Whether `texture2` carries usable occlusion data. When 0, occlusion is
// skipped (texture2 may be unbound).
uniform int use_packed_pbr;
// Occlusion mix strength: 0 = no darkening, 1 = full darkening at black
// occlusion pixels. Tuned so concave joints get visible shadow without
// crushing brick walls.
uniform float occlusion_strength;

void main() {
    vec3 light_dir = normalize(vec3(0.5, 0.5, 1.0));

    // Surface normal: either the perturbed tangent-space sample or the
    // raw geometric normal. The normal-map path swizzles DXT5nm
    // (X in alpha, Y in green) and reconstructs Z assuming a unit
    // normal; clamp under sqrt to guard against rounding.
    vec3 N;
    if (use_normal_map == 1) {
        vec4 n_sample = texture(texture1, v_uv);
        vec2 nm_xy = vec2(n_sample.a, n_sample.g) * 2.0 - 1.0;
        float nm_z = sqrt(max(0.0, 1.0 - dot(nm_xy, nm_xy)));
        vec3 n_ts = vec3(nm_xy, nm_z);
        N = normalize(v_tbn * n_ts);
    } else {
        N = normalize(v_normal);
    }

    float ndotl = dot(N, light_dir);
    float diffuse = mix(min_brightness, 1.0, ndotl * 0.5 + 0.5);
    vec4 tex_color = texture(texture0, v_uv);
    // Alpha-cutout: drop near-transparent fragments so they don't write
    // depth. Without this, vegetation / billboard quads (Citrus, Incense,
    // Yuezhi Capital trees) render as opaque rectangles. 0.5 matches
    // Unity's standard cutout shader threshold.
    if (tex_color.a < 0.5) discard;
    vec3 lit = tex_color.rgb * diffuse;
    if (use_packed_pbr == 1) {
        float occ = texture(texture2, v_uv).b;
        // mix(1, occ, strength) so strength=0 keeps lit unchanged and
        // strength=1 reproduces raw occlusion; we land at 0.6.
        lit *= mix(1.0, occ, occlusion_strength);
    }
    fragColor = vec4(lit, tex_color.a);
}
"""


def autocrop_with_padding(
    img: "Image.Image", padding: int = 32, min_size: int = 256
) -> "Image.Image":
    """
    Crop image to non-transparent content with padding.

    Args:
        img: RGBA image to crop
        padding: Pixels of padding around content
        min_size: Minimum output dimension

    Returns:
        Cropped and padded image
    """
    from PIL import Image

    bbox = img.getbbox()
    if not bbox:
        return img

    # Expand bbox with padding
    left = max(0, bbox[0] - padding)
    top = max(0, bbox[1] - padding)
    right = min(img.width, bbox[2] + padding)
    bottom = min(img.height, bbox[3] + padding)

    # Crop to content
    cropped = img.crop((left, top, right, bottom))

    # Ensure minimum size while maintaining aspect ratio
    w, h = cropped.size
    if w < min_size and h < min_size:
        scale = min_size / max(w, h)
        new_w = int(w * scale)
        new_h = int(h * scale)
        cropped = cropped.resize((new_w, new_h), Image.Resampling.LANCZOS)

    return cropped


def render_mesh_to_image(
    obj_data: str,
    texture_image: "Image.Image",
    width: int = 2048,
    height: int = 2048,
    *,
    autocrop: bool = True,
    padding: int = 32,
    force_upright: bool = False,
    bbox_override: tuple[NDArray[np.float64], NDArray[np.float64]] | None = None,
    flat_lighting: bool = False,
    packed_pbr_image: "Image.Image | None" = None,
    occlusion_strength: float = 0.6,
    normal_map_image: "Image.Image | None" = None,
) -> "Image.Image":
    """
    Render a textured 3D mesh to a 2D PNG image.

    Args:
        obj_data: OBJ file content as string (from UnityPy mesh.export())
        texture_image: PIL Image containing the diffuse texture
        width: Render width in pixels (before cropping)
        height: Render height in pixels (before cropping)
        autocrop: If True, crop to non-transparent content with padding
        padding: Padding pixels around content when autocropping
        force_upright: If True, always treat Y as up and render with an
            orthographic camera at 30° downward tilt. Use this for
            buildings/improvements and resource prefabs, which are authored
            Y-up regardless of footprint shape. Ortho mirrors the game's
            effective behavior on any single hex (its perspective camera is
            far enough that depth foreshortening on a 4-unit tile is
            negligible) and prevents multi-rig resource prefabs from
            depth-crunching back-row and front-row animals onto the same
            screen position. When False, a heuristic rotates the perspective
            camera for meshes that appear lying down (some unit poses).
        bbox_override: Optional (min_bounds, max_bounds) of the *combined*
            scene to frame the camera around, instead of computing it from
            this call's `obj_data`. Used by the layered ground orchestrator
            to render each layer (biome quad, PVT planes, buildings) with
            an identical camera so they line up when alpha-composited.
            Vertices in `obj_data` are still drawn from the OBJ; only the
            framing is relocated.
        flat_lighting: If True, bypass the directional shading term and
            render every fragment at the source texture color directly.
            Use for flat ground planes (biome + PVT) where the directional
            term just dims a uniformly-oriented surface. Default False
            keeps the 0.5–1.0 directional envelope for buildings, units,
            and improvement renders.
        packed_pbr_image: Optional PIL image of the prefab's
            `_MetalicRoughnessOcclusionTeamColor` map. When provided, the
            B channel is sampled as an occlusion factor and multiplies
            the lit color (mix strength `occlusion_strength`). When None,
            occlusion is skipped.
        occlusion_strength: Mix strength for the occlusion modulation
            (0 = no effect, 1 = raw occlusion fully applied). Default 0.6
            gives visible darks at concave joints without crushing
            mid-toned surfaces.
        normal_map_image: Optional PIL image of the prefab's `_BumpMap`
            (Unity DXT5nm: X in alpha, Y in green, Z reconstructed by
            the fragment shader). When provided AND the OBJ has tangent
            data (`vtg` lines), the per-fragment surface normal is
            perturbed for tangent-space normal mapping. When None, or
            when tangents are missing, lighting falls back to flat
            geometric normals.

    Returns:
        PIL Image with rendered mesh on transparent background

    Raises:
        ImportError: If moderngl is not available
        RuntimeError: If OpenGL context creation fails
    """
    import moderngl
    from PIL import Image

    # Create headless OpenGL context
    ctx = moderngl.create_standalone_context()

    try:
        # Parse OBJ data
        vertices, uvs, normals, faces, tangents = parse_obj(obj_data)

        if not vertices or not faces:
            raise ValueError("Empty mesh data")

        # Build vertex buffer
        vertex_data = build_vertex_buffer(vertices, uvs, normals, faces, tangents)
        has_tangents = bool(tangents)

        # Compile shaders
        prog = ctx.program(vertex_shader=VERTEX_SHADER, fragment_shader=FRAGMENT_SHADER)

        # Create vertex buffer and array
        vbo = ctx.buffer(vertex_data.tobytes())
        vao = ctx.vertex_array(
            prog,
            [(vbo, "3f 2f 3f 4f", "in_position", "in_uv", "in_normal", "in_tangent")],
        )

        # Load texture (flip vertically for OpenGL)
        tex_img = texture_image.transpose(Image.Transpose.FLIP_TOP_BOTTOM).convert("RGBA")
        texture = ctx.texture(tex_img.size, 4, tex_img.tobytes())
        texture.build_mipmaps()
        texture.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
        texture.use(location=0)
        prog["texture0"].value = 0  # type: ignore[union-attr]

        # Optional normal map (DXT5nm-encoded) bound to sampler unit 1.
        # Same pattern as packed PBR — bind a 1×1 placeholder when absent
        # so the shader's sampler reads don't fault, then gate via
        # `use_normal_map` (also requires authored tangents).
        if normal_map_image is not None and has_tangents:
            nm_img = normal_map_image.transpose(Image.Transpose.FLIP_TOP_BOTTOM).convert("RGBA")
            normal_tex = ctx.texture(nm_img.size, 4, nm_img.tobytes())
            normal_tex.build_mipmaps()
            normal_tex.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
            use_normal_map = True
        else:
            # 1×1 "neutral" normal in DXT5nm-decoded layout: BGRA where
            # the shader reads `.a` as X (=128 → 0) and `.g` as Y (=128 →
            # 0). With both at 0, reconstructed Z = 1, giving a flat
            # surface normal. Not actually sampled when use_normal_map=0.
            normal_tex = ctx.texture((1, 1), 4, b"\x80\x80\x80\x80")
            use_normal_map = False
        normal_tex.use(location=1)
        prog["texture1"].value = 1  # type: ignore[union-attr]

        # Optional packed PBR texture (M/R/Occlusion/TeamColor). Bound to
        # sampler unit 2. When None, we still need to bind *something* so
        # sampler reads in the shader don't fault — bind a 1×1 white
        # pixel and gate via `use_packed_pbr`.
        if packed_pbr_image is not None:
            pbr_img = packed_pbr_image.transpose(Image.Transpose.FLIP_TOP_BOTTOM).convert("RGBA")
            packed_tex = ctx.texture(pbr_img.size, 4, pbr_img.tobytes())
            packed_tex.build_mipmaps()
            packed_tex.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
        else:
            packed_tex = ctx.texture((1, 1), 4, b"\xff\xff\xff\xff")
        packed_tex.use(location=2)
        prog["texture2"].value = 2  # type: ignore[union-attr]

        # Create framebuffer for offscreen rendering
        fbo = ctx.framebuffer(
            color_attachments=[ctx.texture((width, height), 4)],
            depth_attachment=ctx.depth_renderbuffer((width, height)),
        )
        fbo.use()

        # Compute camera position based on mesh bounds. When `bbox_override`
        # is provided, frame the camera around that combined bbox instead —
        # used by the layered ground orchestrator so each pass shares one
        # camera and the layers line up when composited.
        if bbox_override is not None:
            min_bounds = np.asarray(bbox_override[0], dtype=np.float64)
            max_bounds = np.asarray(bbox_override[1], dtype=np.float64)
            center = (min_bounds + max_bounds) / 2
            extent = max_bounds - min_bounds
        else:
            center, extent, _ = compute_mesh_bounds(vertices)
        max_extent = float(extent.max())

        # Detect if mesh is lying down (wider than tall). Heuristic only
        # applies when force_upright is False — buildings are authored Y-up
        # regardless of footprint shape, so this rotation is wrong for them.
        is_horizontal = not force_upright and (
            extent[1] < extent[0] * 0.5 or extent[1] < extent[2] * 0.5
        )

        aspect = width / height

        if is_horizontal:
            # Model is lying down - view from +X axis with Z as up
            eye = center + np.array([max_extent * 1.5, 0.1, 0])
            up_vector = np.array([0, 0, 1])
            proj = perspective_matrix(np.radians(60.0), aspect, 0.01, 1000)
        elif force_upright:
            # Building/resource view: 30° downward, orthographic. The game's
            # camera is ~25–40 world units from any single hex (a hex is ~4
            # units across), so perspective on a single tile approximates
            # ortho. Using true ortho here matches what the game shows on a
            # single tile and avoids depth-crunch on multi-rig resource
            # prefabs (e.g. herd of goats) where close perspective collapses
            # back-row and front-row animals onto similar screen-Y.
            distance = max_extent * 1.6
            tilt_deg = 30.0
            sin_t = float(np.sin(np.radians(tilt_deg)))
            cos_t = float(np.cos(np.radians(tilt_deg)))
            eye = center + np.array([0.0, distance * sin_t, distance * cos_t])
            up_vector = np.array([0, 1, 0])
            # Frustum sized so visible width matches the legacy perspective
            # view at the mesh-center plane: 1.6 * tan(22.5°) ≈ 0.66.
            half_w = max_extent * 0.66
            half_h = half_w / aspect
            proj = orthographic_matrix(-half_w, half_w, -half_h, half_h, 0.01, 1000)
        else:
            # Normal upright model - view from front
            eye = center + np.array([0, 0.1, max_extent * 1.5])
            up_vector = np.array([0, 1, 0])
            proj = perspective_matrix(np.radians(60.0), aspect, 0.01, 1000)

        view = look_at_matrix(eye, center, up_vector)
        mvp = (proj @ view).T  # Transpose for column-major OpenGL

        prog["mvp"].write(mvp.astype("f4").tobytes())  # type: ignore[union-attr]
        prog["min_brightness"].value = 1.0 if flat_lighting else 0.4  # type: ignore[union-attr]
        prog["use_normal_map"].value = 1 if use_normal_map else 0  # type: ignore[union-attr]
        prog["use_packed_pbr"].value = 1 if packed_pbr_image is not None else 0  # type: ignore[union-attr]
        prog["occlusion_strength"].value = float(occlusion_strength)  # type: ignore[union-attr]

        # Render
        ctx.clear(0.0, 0.0, 0.0, 0.0)  # Transparent background
        ctx.enable(moderngl.DEPTH_TEST)
        ctx.enable(moderngl.CULL_FACE)
        vao.render()

        # Read pixels and create image
        data = fbo.color_attachments[0].read()  # type: ignore[union-attr]
        img = Image.frombytes("RGBA", (width, height), data).transpose(
            Image.Transpose.FLIP_TOP_BOTTOM
        )

        # Auto-crop to content
        if autocrop:
            img = autocrop_with_padding(img, padding=padding)

        return img

    finally:
        ctx.release()
