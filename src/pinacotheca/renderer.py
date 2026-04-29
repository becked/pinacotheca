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
    list[list[float]], list[list[float]], list[list[float]], list[list[tuple[int, int, int]]]
]:
    """
    Parse OBJ file content into vertices, UVs, normals, and faces.

    Args:
        obj_data: OBJ file content as string

    Returns:
        Tuple of (vertices, uvs, normals, faces)
        where faces contains tuples of (vertex_idx, uv_idx, normal_idx)
    """
    vertices: list[list[float]] = []
    uvs: list[list[float]] = []
    normals: list[list[float]] = []
    faces: list[list[tuple[int, int, int]]] = []

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
        elif parts[0] == "f":
            face: list[tuple[int, int, int]] = []
            for vert in parts[1:]:
                indices = vert.split("/")
                v_idx = int(indices[0]) - 1  # OBJ is 1-indexed
                vt_idx = int(indices[1]) - 1 if len(indices) > 1 and indices[1] else 0
                vn_idx = int(indices[2]) - 1 if len(indices) > 2 and indices[2] else 0
                face.append((v_idx, vt_idx, vn_idx))
            faces.append(face)

    return vertices, uvs, normals, faces


def build_vertex_buffer(
    vertices: list[list[float]],
    uvs: list[list[float]],
    normals: list[list[float]],
    faces: list[list[tuple[int, int, int]]],
) -> NDArray[np.float32]:
    """
    Build interleaved vertex buffer from parsed OBJ data.

    Args:
        vertices: List of [x, y, z] positions
        uvs: List of [u, v] texture coordinates
        normals: List of [nx, ny, nz] normals
        faces: List of faces, each containing (v_idx, vt_idx, vn_idx) tuples

    Returns:
        Numpy array of interleaved vertex data (position, uv, normal)
    """
    vertex_data: list[float] = []

    for face in faces:
        for v_idx, vt_idx, vn_idx in face:
            vertex_data.extend(vertices[v_idx])  # xyz
            vertex_data.extend(uvs[vt_idx] if uvs else [0.0, 0.0])  # uv
            vertex_data.extend(normals[vn_idx] if normals else [0.0, 0.0, 1.0])  # normal

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


# Vertex shader: transform vertices and pass through UVs/normals
VERTEX_SHADER = """
#version 330
in vec3 in_position;
in vec2 in_uv;
in vec3 in_normal;

out vec2 v_uv;
out vec3 v_normal;

uniform mat4 mvp;

void main() {
    gl_Position = mvp * vec4(in_position, 1.0);
    v_uv = in_uv;
    v_normal = in_normal;
}
"""

# Fragment shader: sample texture with basic diffuse lighting
FRAGMENT_SHADER = """
#version 330
in vec2 v_uv;
in vec3 v_normal;
out vec4 fragColor;

uniform sampler2D texture0;

void main() {
    vec3 light_dir = normalize(vec3(0.5, 0.5, 1.0));
    float diffuse = max(dot(normalize(v_normal), light_dir), 0.3);
    vec4 tex_color = texture(texture0, v_uv);
    // Alpha-cutout: drop near-transparent fragments so they don't write
    // depth. Without this, vegetation / billboard quads (Citrus, Incense,
    // Yuezhi Capital trees) render as opaque rectangles. 0.5 matches
    // Unity's standard cutout shader threshold.
    if (tex_color.a < 0.5) discard;
    fragColor = vec4(tex_color.rgb * diffuse, tex_color.a);
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
        vertices, uvs, normals, faces = parse_obj(obj_data)

        if not vertices or not faces:
            raise ValueError("Empty mesh data")

        # Build vertex buffer
        vertex_data = build_vertex_buffer(vertices, uvs, normals, faces)

        # Compile shaders
        prog = ctx.program(vertex_shader=VERTEX_SHADER, fragment_shader=FRAGMENT_SHADER)

        # Create vertex buffer and array
        vbo = ctx.buffer(vertex_data.tobytes())
        vao = ctx.vertex_array(prog, [(vbo, "3f 2f 3f", "in_position", "in_uv", "in_normal")])

        # Load texture (flip vertically for OpenGL)
        tex_img = texture_image.transpose(Image.Transpose.FLIP_TOP_BOTTOM).convert("RGBA")
        texture = ctx.texture(tex_img.size, 4, tex_img.tobytes())
        texture.build_mipmaps()
        texture.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
        texture.use()

        # Create framebuffer for offscreen rendering
        fbo = ctx.framebuffer(
            color_attachments=[ctx.texture((width, height), 4)],
            depth_attachment=ctx.depth_renderbuffer((width, height)),
        )
        fbo.use()

        # Compute camera position based on mesh bounds
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
