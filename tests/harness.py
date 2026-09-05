"""
Shared helpers for the headless test suite.

These tests run inside Blender:

    blender.exe --factory-startup --background --python tests/run.py

Everything here builds a throwaway scene, renders a single frame to PNG, and
reads the result back as a numpy array so assertions can be made against actual
rendered pixels rather than against the addon's own idea of what it did.
"""

import os
import sys

import bpy
import numpy as np

# The source image is four solid colour quadrants, which makes orientation
# unambiguous: any flip, rotation or crop error moves a quadrant somewhere
# the test can see.
QUADRANTS = {
    "red": ((0.0, 0.0, 0.5, 0.5), (1.0, 0.0, 0.0)),      # lower left
    "green": ((0.5, 0.0, 1.0, 0.5), (0.0, 1.0, 0.0)),    # lower right
    "blue": ((0.0, 0.5, 0.5, 1.0), (0.0, 0.0, 1.0)),     # upper left
    "white": ((0.5, 0.5, 1.0, 1.0), (1.0, 1.0, 1.0)),    # upper right
}

IDENTITY_PIN = ((0.0, 1.0), (1.0, 1.0), (0.0, 0.0), (1.0, 0.0))
SOCKET_NAMES = ("Upper Left", "Upper Right", "Lower Left", "Lower Right")


def repo_root():
    """Return the addon repository root, so tests can import addon modules."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def scratch_dir():
    """Return (creating if needed) the directory rendered test output goes to."""
    path = os.path.join(repo_root(), "tests", "_output")
    os.makedirs(path, exist_ok=True)
    return path


def make_source_image(path, width=512, height=512):
    """
    Write the four-quadrant reference image used by every render test.

    Args:
        path: destination PNG path
        width, height: image dimensions in pixels

    Returns:
        str: the path written
    """
    image = bpy.data.images.new("pt_test_source", width=width, height=height, alpha=True)
    pixels = np.zeros((height, width, 4), dtype=np.float32)
    pixels[..., 3] = 1.0
    for (u0, v0, u1, v1), rgb in QUADRANTS.values():
        x0, x1 = int(u0 * width), int(u1 * width)
        y0, y1 = int(v0 * height), int(v1 * height)
        pixels[y0:y1, x0:x1, :3] = rgb
    # foreach_set takes any buffer; the stub asks for a Sequence, which an
    # ndarray is not, and passing a list instead would defeat the point of it.
    image.pixels.foreach_set(pixels.ravel())  # pyright: ignore[reportArgumentType]
    image.filepath_raw = path
    image.file_format = 'PNG'
    image.save()
    bpy.data.images.remove(image)
    return path


def build_corner_pin_group(name, pin=IDENTITY_PIN, prescale=None):
    """
    Create a compositor node group of the shape the addon uses.

        Group Input -> [Transform (Scale)] -> Corner Pin -> Group Output

    Args:
        name: datablock name for the node group
        pin: 4 (u, v) pairs in Upper Left, Upper Right, Lower Left, Lower Right order
        prescale: optional uniform scale applied before the pin

    Returns:
        bpy.types.NodeTree: the created group
    """
    group = bpy.data.node_groups.new(name, 'CompositorNodeTree')
    # NodeTree.interface is never None; the stubs make every pointer property
    # Optional. Same suppression as operators/perspective_nodes.py.
    group.interface.new_socket(  # pyright: ignore[reportOptionalMemberAccess]
        "Image", in_out='INPUT', socket_type='NodeSocketColor')
    group.interface.new_socket(  # pyright: ignore[reportOptionalMemberAccess]
        "Image", in_out='OUTPUT', socket_type='NodeSocketColor')

    node_in = group.nodes.new('NodeGroupInput')
    node_out = group.nodes.new('NodeGroupOutput')
    corner_pin = group.nodes.new('CompositorNodeCornerPin')

    source = node_in.outputs[0]
    if prescale is not None:
        transform = group.nodes.new('CompositorNodeTransform')
        # default_value lives on the concrete socket class, not on the
        # NodeSocket the inputs collection is typed as.
        transform.inputs['Scale'].default_value = prescale  # pyright: ignore[reportAttributeAccessIssue]
        group.links.new(source, transform.inputs['Image'])
        source = transform.outputs['Image']

    group.links.new(source, corner_pin.inputs['Image'])
    group.links.new(corner_pin.outputs['Image'], node_out.inputs[0])

    for socket_name, value in zip(SOCKET_NAMES, pin):
        corner_pin.inputs[socket_name].default_value = value  # pyright: ignore[reportAttributeAccessIssue]

    return group


def make_scene(name, res_x=512, res_y=512):
    """Create a scene configured for deterministic, colour-accurate test renders."""
    scene = bpy.data.scenes.new(name)
    scene.render.resolution_x = res_x
    scene.render.resolution_y = res_y
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.render.compositor_device = 'CPU'
    scene.frame_start = scene.frame_end = 1
    # Standard view transform keeps the quadrant colours readable; AgX would
    # tone-map them into something the classifier cannot separate.
    # view_settings is never None, and view_transform is writable whatever the
    # stub says about assigning to it.
    view = scene.view_settings
    view.view_transform = 'Standard'  # pyright: ignore[reportAttributeAccessIssue, reportOptionalMemberAccess]
    return scene


def add_image_strip(scene, image_path):
    """Add an image strip on channel 1 at frame 1 and make it active."""
    editor = scene.sequence_editor_create()
    strip = editor.strips.new_image(name="pt_strip", filepath=image_path,
                                    channel=1, frame_start=1)
    editor.active_strip = strip
    return strip


def set_duration(strip, frames):
    """
    Stretch a strip to a number of frames, across the 5.x rename.

    An image strip is one frame long by default, and any test rendering at
    several frames needs it longer. `duration` is the 5.1 replacement for
    `frame_final_duration`; 5.0 is the addon's stated minimum and has only the
    old name, so a test that used the new one unconditionally simply raised
    there and took the whole suite with it.
    """
    if "duration" in strip.bl_rna.properties:
        strip.duration = frames
    else:
        strip.frame_final_duration = frames


def add_compositor_modifier(strip, scene, node_group):
    """
    Attach a compositor modifier carrying node_group.

    The sequencer_scene override is required: StripModifiers.new() dereferences
    a null scene and crashes Blender outright when context.sequencer_scene is
    unset, which is always the case in background mode.
    """
    with bpy.context.temp_override(scene=scene, sequencer_scene=scene):
        modifier = strip.modifiers.new(name="Perspective", type='COMPOSITOR')
    modifier.node_group = node_group
    return modifier


def render_scene(scene, tag, frame=None):
    """
    Render one frame of scene and return the result as an (h, w, 4) float array.

    Row 0 of the array is the bottom of the image, matching Blender's own
    bottom-left pixel origin.

    Args:
        scene: the scene to render
        tag: filename prefix for the rendered PNG
        frame: frame to render, or None to render whatever range the scene is
            already set to. Passing a frame is what the animation tests need,
            since a keyed pin only differs from frame to frame.
    """
    if frame is not None:
        scene.frame_start = scene.frame_end = frame
        scene.frame_set(frame)

    out_dir = scratch_dir()
    scene.render.filepath = os.path.join(out_dir, tag + "_")
    with bpy.context.temp_override(scene=scene, sequencer_scene=scene):
        bpy.ops.render.render(animation=True, scene=scene.name)

    # Named from frame_start rather than hardcoded to 0001, so a scene set to
    # any single frame reads back the file it actually wrote.
    path = os.path.join(out_dir, "{}_{:04d}.png".format(tag, scene.frame_start))
    image = bpy.data.images.load(path)
    # bpy_prop_array is sized at run time; the stub does not declare __len__.
    buffer = np.zeros(len(image.pixels), dtype=np.float32)  # pyright: ignore[reportArgumentType]
    image.pixels.foreach_get(buffer)
    result = buffer.reshape((scene.render.resolution_y, scene.render.resolution_x, 4))
    bpy.data.images.remove(image)
    return result


def opaque_mask(pixels, threshold=0.5):
    """Return a boolean mask of pixels whose alpha exceeds threshold."""
    return pixels[..., 3] > threshold


def colour_centroid(pixels, rgb, tolerance=0.25):
    """
    Return the (x, y) pixel centroid of the region matching an RGB colour.

    Args:
        pixels: (h, w, 4) float array
        rgb: the colour to match
        tolerance: per-channel matching tolerance

    Returns:
        tuple[float, float] or None if the colour is not present
    """
    mask = opaque_mask(pixels)
    for channel, target in enumerate(rgb):
        mask &= np.abs(pixels[..., channel] - target) <= tolerance
    if not mask.any():
        return None
    ys, xs = np.nonzero(mask)
    # +0.5 puts the centroid at pixel centres rather than corners.
    return float(xs.mean()) + 0.5, float(ys.mean()) + 0.5


def row_span(pixels, row, threshold=0.5):
    """Return the (first, last) opaque column index on a row, or None."""
    xs = np.nonzero(pixels[row, :, 3] > threshold)[0]
    return (int(xs[0]), int(xs[-1])) if len(xs) else None


def import_addon_module(module_name):
    """
    Import an addon module by name without registering the addon.

    Lets the coordinate maths be tested in isolation from Blender's addon
    machinery, which needs a full extension install to load normally.
    """
    root = repo_root()
    if root not in sys.path:
        sys.path.insert(0, root)
    import importlib
    return importlib.import_module(module_name)


def import_addon_package_module(module_name):
    """
    Import an addon module through the real package name.

    import_addon_module() puts the repo root on sys.path, so submodules import
    as top-level packages. That is enough for the operators, but anything using
    a package-relative `..` import fails with "attempted relative import beyond
    top-level package" - the gizmos import `..operators` and do exactly that.
    This puts the repo's *parent* on sys.path instead and imports through the
    package, so those resolve.

    Args:
        module_name: path below the addon root, e.g.
            "gizmos.perspective_handles_gizmo"
    """
    root = repo_root()
    parent = os.path.dirname(root)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    import importlib
    return importlib.import_module("{}.{}".format(os.path.basename(root), module_name))
