"""
End-to-end render tests.

These are the tests that answer the question the project originally failed on:
does a corner drag actually reach rendered output? Every expectation here is a
pixel measurement taken from a real render, not a property read back from the
addon's own state.
"""

import os

import bpy
import numpy as np

from harness import (add_image_strip, import_addon_module, make_scene,
                     make_source_image, opaque_mask, render_scene, row_span,
                     scratch_dir)

nodes = import_addon_module("operators.perspective_nodes")

# Squeeze the top edge to the middle half of the image, in addon corner order
# (bottom-left, top-left, top-right, bottom-right).
SQUEEZE_PIN = ((0.0, 0.0), (0.25, 1.0), (0.75, 1.0), (1.0, 0.0))

# Measured from a 512x512 render of SQUEEZE_PIN. The trapezoid covers three
# quarters of the frame, which is what the geometry predicts exactly.
EXPECT_OPAQUE = 196354
EXPECT_TOP_SPAN = (128, 383)
EXPECT_BOTTOM_SPAN = (1, 510)

# A homography maps the source midline to row 341.3 for this trapezoid.
# Affine interpolation would put it at 256, so this separates a genuinely
# perspective-correct warp from a merely stretched one.
EXPECT_MIDLINE_ROW = 341
MIDLINE_TOLERANCE = 2


def make_movie(source, failures):
    """Render a short H.264 clip so MOVIE strips can be tested too."""
    scene = make_scene("mk_movie")
    scene.frame_end = 5
    scene.render.image_settings.media_type = 'VIDEO'
    scene.render.image_settings.file_format = 'FFMPEG'
    scene.render.ffmpeg.format = 'MPEG4'
    scene.render.ffmpeg.codec = 'H264'
    strip = add_image_strip(scene, source)
    strip.frame_final_duration = 5
    scene.render.filepath = os.path.join(scratch_dir(), "clip")
    with bpy.context.temp_override(scene=scene, sequencer_scene=scene):
        bpy.ops.render.render(animation=True, scene=scene.name)

    for name in sorted(os.listdir(scratch_dir())):
        if name.startswith("clip") and name.endswith(".mp4"):
            return os.path.join(scratch_dir(), name)
    failures.append("could not produce a test movie file")
    return None


def compare_shape(label, pixels, failures):
    """Assert the rendered silhouette matches the expected trapezoid."""
    opaque = int(opaque_mask(pixels).sum())
    if abs(opaque - EXPECT_OPAQUE) > 200:
        failures.append(f"{label}: {opaque} opaque px, expected about {EXPECT_OPAQUE}")

    top = row_span(pixels, pixels.shape[0] - 3)
    bottom = row_span(pixels, 2)
    if top is None or abs(top[0] - EXPECT_TOP_SPAN[0]) > 2 or abs(top[1] - EXPECT_TOP_SPAN[1]) > 2:
        failures.append(f"{label}: top span {top}, expected about {EXPECT_TOP_SPAN}")
    if bottom is None or abs(bottom[0] - EXPECT_BOTTOM_SPAN[0]) > 2:
        failures.append(f"{label}: bottom span {bottom}, expected about {EXPECT_BOTTOM_SPAN}")


def check_image_strip(source, failures):
    """A corner pin written through the addon must reach rendered output."""
    scene = make_scene("render_image")
    strip = add_image_strip(scene, source)
    nodes.write_pin(strip, scene, SQUEEZE_PIN)
    compare_shape("image strip", render_scene(scene, "render_image"), failures)


def check_movie_strip(movie_path, failures):
    """MOVIE strips must warp identically to IMAGE strips."""
    if movie_path is None:
        return
    scene = make_scene("render_movie")
    editor = scene.sequence_editor_create()
    strip = editor.strips.new_movie(name="clip", filepath=movie_path,
                                    channel=1, frame_start=1)
    editor.active_strip = strip
    nodes.write_pin(strip, scene, SQUEEZE_PIN)
    compare_shape("movie strip", render_scene(scene, "render_movie"), failures)


def check_perspective_correct(source, failures):
    """The warp must be a true homography, not affine interpolation."""
    scene = make_scene("render_persp")
    strip = add_image_strip(scene, source)
    nodes.write_pin(strip, scene, SQUEEZE_PIN)
    pixels = render_scene(scene, "render_persp")

    column = pixels[:, pixels.shape[1] // 2, :]
    visible = column[:, 3] > 0.5
    # Blue and white occupy the source image's upper half; where they start is
    # where the source midline landed.
    upper = (column[:, 2] > 0.5) & visible
    rows = np.nonzero(upper)[0]
    if not len(rows):
        failures.append("perspective check: no upper-half content found")
        return

    measured = int(rows[0])
    if abs(measured - EXPECT_MIDLINE_ROW) > MIDLINE_TOLERANCE:
        failures.append(
            f"perspective check: source midline at row {measured}, expected "
            f"{EXPECT_MIDLINE_ROW} (row 256 would mean affine, not perspective)")


def check_identity_renders_clean(source, failures):
    """An identity pin must leave the image untouched."""
    scene = make_scene("render_identity")
    strip = add_image_strip(scene, source)
    nodes.write_pin(strip, scene, nodes.IDENTITY_PIN)
    pixels = render_scene(scene, "render_identity")

    opaque = int(opaque_mask(pixels).sum())
    total = pixels.shape[0] * pixels.shape[1]
    if opaque != total:
        failures.append(f"identity pin: {opaque} of {total} px opaque, expected all")


def check_simulated_drag(source, failures):
    """
    Exercise the exact path a corner drag takes, and check where it lands.

    The gizmo converts a cursor position to frame space, maps it through
    frame_to_pin_matrix, and writes one socket via write_corner. Doing the same
    here and then measuring the render verifies the whole chain at once, which
    is the closest a headless test can get to dragging a handle.
    """
    space = import_addon_module("operators.perspective_space")

    scene = make_scene("render_drag")
    strip = add_image_strip(scene, source)

    node = nodes.prepare_for_edit(strip, scene)
    if node is None:
        failures.append("prepare_for_edit returned no Corner Pin node")
        return

    # Drag the top-left corner to the middle of the frame's top edge.
    target = (256.0, 512.0)
    matrix = space.frame_to_pin_matrix(strip, scene)
    top_left_index = nodes.CORNER_SOCKETS.index("Upper Left")
    nodes.write_corner(node, top_left_index, space.apply(matrix, target))

    pixels = render_scene(scene, "render_drag")
    top = row_span(pixels, pixels.shape[0] - 3)
    if top is None:
        failures.append("simulated drag: nothing rendered on the top row")
        return
    if abs(top[0] - 256) > 3:
        failures.append(
            f"simulated drag: top edge starts at x={top[0]}, expected 256 "
            f"(the corner was dragged to {target})")
    if abs(top[1] - 511) > 3:
        failures.append(f"simulated drag: top edge ends at x={top[1]}, expected 511")


def run():
    """Run the render suite and return a list of failure strings."""
    failures = []
    source = make_source_image(os.path.join(scratch_dir(), "source.png"))

    check_identity_renders_clean(source, failures)
    check_image_strip(source, failures)
    check_perspective_correct(source, failures)
    check_simulated_drag(source, failures)
    check_movie_strip(make_movie(source, failures), failures)
    return failures
