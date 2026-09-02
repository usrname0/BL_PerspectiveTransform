"""
Validation of the pin-space to frame-space matrix against real renders.

This is the regression test for the bug class that consumed the original
project: handles drifting away from the image under rotation, mirroring, crop
and scale. Rather than trusting the matrix, every case renders an actual frame
and compares the measured centroid of each colour quadrant against the position
the matrix predicts.
"""

import itertools
import os
from math import radians

from harness import (QUADRANTS, IDENTITY_PIN, add_compositor_modifier,
                     add_image_strip, build_corner_pin_group, colour_centroid,
                     import_addon_module, make_scene, make_source_image,
                     render_scene, scratch_dir)

space = import_addon_module("operators.perspective_space")

SRC_W = SRC_H = 512
TOLERANCE_PX = 2.0


def visible_quadrant_centre(strip, scene, quadrant_rect):
    """
    Return the pin-space centre of the part of a quadrant that survives cropping.

    Crop removes pixels from the source image, so a cropped quadrant's centroid
    is not the quadrant's own centre. Intersecting with the visible rectangle
    first keeps the prediction exact.

    Args:
        strip: the strip being tested
        scene: the scene providing render resolution
        quadrant_rect: (u0, v0, u1, v1) of the quadrant in pin space

    Returns:
        tuple[float, float] or None if the quadrant is fully cropped away
    """
    src_w, src_h = space.get_source_size(strip, scene)
    crop_min_x, crop_min_y, crop_max_x, crop_max_y = space.get_crop(strip)

    vis_u0 = crop_min_x / src_w
    vis_u1 = (src_w - crop_max_x) / src_w
    vis_v0 = crop_min_y / src_h
    vis_v1 = (src_h - crop_max_y) / src_h

    u0 = max(quadrant_rect[0], vis_u0)
    v0 = max(quadrant_rect[1], vis_v0)
    u1 = min(quadrant_rect[2], vis_u1)
    v1 = min(quadrant_rect[3], vis_v1)
    if u1 <= u0 or v1 <= v0:
        return None
    return (u0 + u1) * 0.5, (v0 + v1) * 0.5


def check_case(label, source, setup, use_modifier, failures):
    """Render one transform configuration and compare predicted to measured centroids."""
    scene = make_scene("space_" + label)
    strip = add_image_strip(scene, source)
    if setup:
        setup(strip)
    if use_modifier:
        group = build_corner_pin_group("ng_" + label, IDENTITY_PIN)
        add_compositor_modifier(strip, scene, group)

    pixels = render_scene(scene, "space_" + label)
    matrix = space.pin_to_frame_matrix(strip, scene)

    for name, (rect, rgb) in QUADRANTS.items():
        centre = visible_quadrant_centre(strip, scene, rect)
        measured = colour_centroid(pixels, rgb)
        if centre is None:
            if measured is not None:
                failures.append(f"{label}/{name}: expected fully cropped, but found {measured}")
            continue
        if measured is None:
            failures.append(f"{label}/{name}: quadrant missing from render")
            continue

        predicted = space.apply(matrix, centre)
        dx = predicted.x - measured[0]
        dy = predicted.y - measured[1]
        distance = (dx * dx + dy * dy) ** 0.5
        if distance > TOLERANCE_PX:
            failures.append(
                f"{label}/{name}: predicted ({predicted.x:.1f}, {predicted.y:.1f}) "
                f"but measured ({measured[0]:.1f}, {measured[1]:.1f}), off by {distance:.1f}px")


def run():
    """Run the coordinate-space suite and return a list of failure strings."""
    failures = []
    source = make_source_image(os.path.join(scratch_dir(), "source.png"), SRC_W, SRC_H)

    def setup(scale=1.0, rotation=0.0, flip_x=False, flip_y=False,
              crop=None, offset=(0.0, 0.0), origin=None):
        def apply_setup(strip):
            strip.transform.scale_x = scale
            strip.transform.scale_y = scale
            strip.transform.rotation = rotation
            strip.transform.offset_x = offset[0]
            strip.transform.offset_y = offset[1]
            strip.use_flip_x = flip_x
            strip.use_flip_y = flip_y
            if origin is not None:
                strip.transform.origin = origin
            if crop is not None:
                strip.crop.min_x, strip.crop.min_y, strip.crop.max_x, strip.crop.max_y = crop
        return apply_setup

    # The modifier itself must be geometrically neutral at an identity pin.
    check_case("plain", source, setup(), use_modifier=False, failures=failures)
    check_case("identity_pin", source, setup(), use_modifier=True, failures=failures)

    # Each transform on its own.
    check_case("scale_half", source, setup(scale=0.5), False, failures)
    # Scaled down so the offset image stays inside the frame; clipped content
    # would skew the measured centroids and make the check meaningless.
    check_case("offset", source, setup(scale=0.5, offset=(60.0, -40.0)), False, failures)
    check_case("flip_x", source, setup(flip_x=True), False, failures)
    check_case("flip_y", source, setup(flip_y=True), False, failures)
    check_case("flip_xy", source, setup(flip_x=True, flip_y=True), False, failures)
    check_case("crop_left", source, setup(crop=(128, 0, 0, 0)), False, failures)
    check_case("crop_all", source, setup(crop=(64, 32, 96, 16)), False, failures)
    check_case("origin_corner", source, setup(scale=0.5, origin=(0.0, 0.0)), False, failures)

    # Crop must stay geometrically inert even while the image is being scaled,
    # rotated and mirrored around it.
    check_case("crop_scale", source, setup(scale=0.5, crop=(128, 0, 0, 0)), False, failures)
    check_case("crop_rot90", source,
               setup(scale=0.5, rotation=radians(90.0), crop=(128, 0, 0, 0)), False, failures)
    check_case("crop_origin", source,
               setup(scale=0.5, crop=(96, 48, 0, 0), origin=(0.0, 1.0)), False, failures)

    # Mirroring is applied about the frame centre after the offset, so mirror
    # combined with a non-zero offset is the case that pins down the order.
    check_case("offset_flip_x", source,
               setup(scale=0.5, offset=(80.0, 0.0), flip_x=True), False, failures)
    check_case("offset_flip_y", source,
               setup(scale=0.5, offset=(0.0, 70.0), flip_y=True), False, failures)

    # Rotation, kept scaled down so nothing leaves the frame and gets clipped.
    for degrees in (15.0, 45.0, 90.0, -30.0):
        check_case(f"rot{int(degrees)}", source,
                   setup(scale=0.5, rotation=radians(degrees)), False, failures)

    # The combinations that broke the original implementation: rotation together
    # with mirroring, where the old code needed a sign-flip hack.
    for flip_x, flip_y in itertools.product((False, True), repeat=2):
        check_case(f"rot30_fx{int(flip_x)}_fy{int(flip_y)}", source,
                   setup(scale=0.5, rotation=radians(30.0),
                         flip_x=flip_x, flip_y=flip_y), False, failures)

    # Everything at once.
    check_case("combined", source,
               setup(scale=0.45, rotation=radians(20.0), flip_x=True, flip_y=True,
                     crop=(48, 24, 32, 64), offset=(35.0, -22.0)), True, failures)

    return failures
