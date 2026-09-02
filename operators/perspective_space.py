"""
BL Perspective Transform - Coordinate spaces

The Corner Pin compositor node lives inside the strip's own image, so its four
control points are expressed as normalized coordinates on the *source image*
before Blender applies crop, flip, or the strip transform.

Blender's evaluation order was established by rendering test frames and fitting
the model to the measured result (see tests/test_space.py):

    corner pin -> place source rect in frame -> scale/rotate about origin
               -> offset -> mirror about the frame centre

Three details are worth stating because guessing any of them wrongly produces
handles that drift, and each was measured rather than assumed:

  * Mirroring is applied *last*, about the centre of the render frame - not in
    the strip's own image space. With rotation this is what makes a single
    mirror appear to reverse the rotation direction; expressed in this order no
    sign-flip special case is needed.
  * Crop has *no* geometric effect. It clips pixels but never moves or
    recentres the image, so it does not appear in this matrix at all.
  * Placement and the scale/rotation pivot both use the full, uncropped source
    rectangle.

This module builds that chain as a single 3x3 homogeneous matrix. Placing a
handle is the forward map of a pin value; dragging a handle is the inverse map
of the mouse position. Rotation, scale, mirroring and origin all fall out of
the matrix, so no per-transform special cases are needed.

Coordinate spaces used here:

    pin space    normalized [0, 1] on the source image, bottom-left origin.
                 This is exactly what CompositorNodeCornerPin sockets store.
    frame space  pixels in the render frame, bottom-left origin, spanning
                 (0, 0) to (render.resolution_x, render.resolution_y).

Converting frame space to region/screen space is the caller's job, since that
depends on the View2D of the preview region.
"""

import math

from mathutils import Matrix, Vector


def _translation(tx, ty):
    """Return a 3x3 homogeneous 2D translation matrix."""
    return Matrix(((1.0, 0.0, tx),
                   (0.0, 1.0, ty),
                   (0.0, 0.0, 1.0)))


def _scale(sx, sy):
    """Return a 3x3 homogeneous 2D scale matrix."""
    return Matrix(((sx, 0.0, 0.0),
                   (0.0, sy, 0.0),
                   (0.0, 0.0, 1.0)))


def _rotation(angle):
    """Return a 3x3 homogeneous 2D rotation matrix for an angle in radians."""
    c, s = math.cos(angle), math.sin(angle)
    return Matrix(((c, -s, 0.0),
                   (s, c, 0.0),
                   (0.0, 0.0, 1.0)))


def get_source_size(strip, scene):
    """
    Return the strip's source image size in pixels as a (width, height) tuple.

    Corner pin coordinates are normalized against this rectangle, which is the
    uncropped source image - not the render frame. Falls back to the scene
    render resolution for strip types that carry no image elements.
    """
    elements = getattr(strip, "elements", None)
    if elements:
        element = elements[0]
        width = getattr(element, "orig_width", 0)
        height = getattr(element, "orig_height", 0)
        if width and height:
            return float(width), float(height)

    return float(scene.render.resolution_x), float(scene.render.resolution_y)


def get_crop(strip):
    """Return the strip's crop as a (min_x, min_y, max_x, max_y) tuple of pixels."""
    crop = getattr(strip, "crop", None)
    if crop is None:
        return 0.0, 0.0, 0.0, 0.0
    return float(crop.min_x), float(crop.min_y), float(crop.max_x), float(crop.max_y)


def get_flip(strip):
    """Return the strip's mirror state as an (flip_x, flip_y) tuple of bools."""
    return bool(getattr(strip, "use_flip_x", False)), bool(getattr(strip, "use_flip_y", False))


def pin_to_frame_matrix(strip, scene):
    """
    Build the matrix taking pin space to frame space.

    The composition follows Blender's evaluation order, read right to left:

        mirror . offset . rotate/scale about origin . place in frame . image size

    Crop is deliberately absent: it clips pixels without moving the image.

    Args:
        strip: the VSE strip carrying the perspective modifier
        scene: the scene providing render resolution

    Returns:
        mathutils.Matrix: a 3x3 homogeneous matrix mapping pin space to frame
        space. Always invertible - scale components are clamped away from zero.
    """
    src_w, src_h = get_source_size(strip, scene)
    flip_x, flip_y = get_flip(strip)

    transform = getattr(strip, "transform", None)
    if transform is not None:
        scale_x = getattr(transform, "scale_x", 1.0)
        scale_y = getattr(transform, "scale_y", 1.0)
        rotation = getattr(transform, "rotation", 0.0)
        offset_x = getattr(transform, "offset_x", 0.0)
        offset_y = getattr(transform, "offset_y", 0.0)
        origin = getattr(transform, "origin", (0.5, 0.5))
        origin_x, origin_y = float(origin[0]), float(origin[1])
    else:
        scale_x = scale_y = 1.0
        rotation = offset_x = offset_y = 0.0
        origin_x = origin_y = 0.5

    # A zero scale would make the matrix singular and break the inverse used for
    # dragging. Clamp to a value small enough to be visually identical.
    if abs(scale_x) < 1e-6:
        scale_x = math.copysign(1e-6, scale_x) if scale_x else 1e-6
    if abs(scale_y) < 1e-6:
        scale_y = math.copysign(1e-6, scale_y) if scale_y else 1e-6

    res_x = float(scene.render.resolution_x)
    res_y = float(scene.render.resolution_y)

    # pin space [0,1] -> source image pixels
    m = _scale(src_w, src_h)

    # the full source rect sits centred in the render frame at scale 1
    corner_x = res_x * 0.5 - src_w * 0.5
    corner_y = res_y * 0.5 - src_h * 0.5
    m = _translation(corner_x, corner_y) @ m

    # scale and rotate about the origin point, then offset
    pivot = Vector((corner_x + origin_x * src_w,
                    corner_y + origin_y * src_h))
    about_pivot = (_translation(pivot.x, pivot.y)
                   @ _rotation(rotation)
                   @ _scale(scale_x, scale_y)
                   @ _translation(-pivot.x, -pivot.y))
    m = about_pivot @ m
    m = _translation(offset_x, offset_y) @ m

    # mirroring happens last, about the centre of the render frame
    if flip_x:
        m = (_translation(res_x, 0.0) @ _scale(-1.0, 1.0)) @ m
    if flip_y:
        m = (_translation(0.0, res_y) @ _scale(1.0, -1.0)) @ m

    return m


def frame_to_pin_matrix(strip, scene):
    """Return the inverse of pin_to_frame_matrix, for turning drags into pin values."""
    return pin_to_frame_matrix(strip, scene).inverted()


def apply(matrix, point):
    """
    Apply a 3x3 homogeneous matrix to a 2D point.

    Args:
        matrix: 3x3 mathutils.Matrix
        point: any 2-sequence of floats

    Returns:
        mathutils.Vector: the transformed 2D point
    """
    result = matrix @ Vector((float(point[0]), float(point[1]), 1.0))
    if abs(result.z) > 1e-12:
        return Vector((result.x / result.z, result.y / result.z))
    return Vector((result.x, result.y))


def pin_to_frame(strip, scene, pin_points):
    """
    Map pin-space points to frame space.

    Args:
        strip: the VSE strip
        scene: the scene providing render resolution
        pin_points: iterable of 2-sequences in normalized pin space

    Returns:
        list[mathutils.Vector]: the points in frame-space pixels
    """
    matrix = pin_to_frame_matrix(strip, scene)
    return [apply(matrix, p) for p in pin_points]


def frame_to_pin(strip, scene, frame_points):
    """
    Map frame-space points back to pin space.

    Args:
        strip: the VSE strip
        scene: the scene providing render resolution
        frame_points: iterable of 2-sequences in frame-space pixels

    Returns:
        list[mathutils.Vector]: the points in normalized pin space
    """
    matrix = frame_to_pin_matrix(strip, scene)
    return [apply(matrix, p) for p in frame_points]
