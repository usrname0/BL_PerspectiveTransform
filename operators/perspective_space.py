"""
BL Perspective Transform - Coordinate spaces

The Corner Pin compositor node lives inside the strip's own image, so its four
control points are expressed as normalized coordinates on the *source image*
before Blender applies crop, flip, or the strip transform.

Blender applies the transform in this order:

    corner pin -> place source rect in frame -> scale/rotate about origin
               -> offset -> mirror about the frame center

Three details are worth stating, because guessing any of them wrongly produces
handles that drift:

  * Mirroring is applied *last*, about the center of the render frame - not in
    the strip's own image space. With rotation this is what makes a single
    mirror appear to reverse the rotation direction; expressed in this order no
    sign-flip special case is needed.
  * Crop has *no* geometric effect. It clips pixels but never moves or
    recenters the image, so it does not appear in this matrix at all.
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

    # the full source rect sits centered in the render frame at scale 1
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

    # mirroring happens last, about the center of the render frame
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
    Apply a 3x3 homogeneous matrix to a 2D point, dividing through by w.

    The matrices this module composes are affine, so w is always 1. The guard
    is for a matrix that is not, where an unguarded divide would raise instead
    of returning a point.
    """
    result = matrix @ Vector((float(point[0]), float(point[1]), 1.0))
    if abs(result.z) > 1e-12:
        return Vector((result.x / result.z, result.y / result.z))
    return Vector((result.x, result.y))


# Smallest accepted cross product between adjacent edges of the pin quad, in
# pin-space units squared. Measured on 5.2.1 by rendering a quad swept towards
# collinearity: the render stayed sane down to 1e-4, where the image had
# degenerated to 17 percent frame coverage, and collapsed to an empty frame at
# exactly 0.
CONVEX_EPSILON = 1e-4


def is_convex_quad(corners, epsilon=CONVEX_EPSILON):
    """
    Return True if four corners form a convex, non-degenerate quadrilateral.

    A homography maps the unit square onto a convex quad and onto nothing else,
    so Blender's Corner Pin has no solution for a concave or self-intersecting
    one. It does not fail cleanly either: measured on 5.2.1, every concave quad
    rendered a frame filled edge to edge with garbage, and the collinear case
    rendered an empty frame.

    Walking the quad, the cross product of each pair of adjacent edges holds a
    single sign exactly when the polygon is convex and simple; a bow-tie
    produces mixed signs. A near-zero magnitude means three points have gone
    collinear, which is just as unsolvable, so the magnitude is checked too.

    Args:
        corners: four (x, y) points in perspective_nodes.CORNER_SOCKETS order,
            which walks the quad rather than jumping across it
        epsilon: smallest accepted absolute cross product, in the units of the
            input squared. The default suits pin space, where the untransformed
            quad is the unit square and every cross product is 1.

    Returns:
        bool: True if the quad is convex and no three corners are collinear
    """
    sign = 0
    for index in range(4):
        ax, ay = float(corners[index][0]), float(corners[index][1])
        bx, by = float(corners[(index + 1) % 4][0]), float(corners[(index + 1) % 4][1])
        cx, cy = float(corners[(index + 2) % 4][0]), float(corners[(index + 2) % 4][1])
        cross = (bx - ax) * (cy - by) - (by - ay) * (cx - bx)
        if abs(cross) < epsilon:
            return False
        current = 1 if cross > 0.0 else -1
        if sign == 0:
            sign = current
        elif sign != current:
            return False
    return True


# Distance the feasible region for a projected corner is held inside the
# boundary is_convex_quad tests, in the same units as CONVEX_EPSILON.
#
# A projection lands exactly *on* the constraint it was projected onto, so the
# cross product it produces comes out at CONVEX_EPSILON plus or minus a
# rounding error, and is_convex_quad's `abs(cross) < epsilon` rejects roughly
# half of them: swept over 20000 random projections, 6471 come back non-convex
# by this module's own predicate with no margin at all.
#
# The size of the margin is set by float32, not by that rounding error. A
# Corner Pin socket stores a C float - writing 0.70000000000000018 reads back
# 0.69999998807907104, measured on 5.2.1 - and mathutils.Vector, which this
# function returns, is float32 as well. Quantizing a corner perturbs the cross
# products around it by up to about 1e-7, which is 1000 times the margin the
# spike arrived at in double precision. Swept over 20000 random projections on
# 5.2.1, non-convex results after the float32 round trip:
#
#     CONVEX_EPSILON * 0          6471
#     CONVEX_EPSILON * 1e-6    6384        what the sweep found in doubles
#     CONVEX_EPSILON * 1e-4    1836
#     CONVEX_EPSILON * 1e-3       0        worst cross only 5.7e-8 clear
#     CONVEX_EPSILON * 1e-2       0        worst cross 9.6e-7 clear
#
# So 1e-2, an order of magnitude past the last value that still failed, and
# still one percent of the epsilon - far too small to see in a rendered frame.
# It is not a tuning knob: it is the difference between a guard that produces
# shapes its own test rejects and one that does not.
CONVEX_MARGIN = CONVEX_EPSILON * 1e-2

# Slack allowed when testing a point against a half-plane. Orders of magnitude
# tighter than CONVEX_MARGIN, so the margin is not eaten by it.
CONVEX_FEASIBLE_TOL = 1e-12


def _area2(a, b, c):
    """
    Return twice the signed area of the triangle a, b, c.

    This is the same quantity is_convex_quad walks the quad computing: the
    cross product of adjacent edges, (b - a) x (c - b), equals (b - a) x (c - a)
    because the two differ by (b - a) x (b - a), which is zero.
    """
    ax, ay = float(a[0]), float(a[1])
    bx, by = float(b[0]), float(b[1])
    cx, cy = float(c[0]), float(c[1])
    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)


def _corner_halfplanes(corners, index):
    """
    Return the half-planes bounding the valid positions for one corner.

    Convexity is four cross products holding one sign at magnitude at least
    CONVEX_EPSILON. Cross product k is twice the signed area of the triangle on
    corners k, k+1 and k+2, so only three of the four involve any given corner.
    The fourth is fixed by the other three, and its sign is the sign the whole
    quad has to hold to.

    Each of the three is affine in the moving corner, so each one is a
    half-plane and the valid positions are their intersection, clipped to the
    unit square the Corner Pin evaluates in. Seven constraints, all convex.

    Args:
        corners: four (x, y) points in perspective_nodes.CORNER_SOCKETS order
        index: which corner is free to move

    Returns:
        list: half-planes as (nx, ny, d), each meaning nx * x + ny * y >= d,
        or None when the other three corners are collinear - which leaves no
        position for this one that makes the quad convex
    """
    fixed = _area2(corners[(index + 1) % 4],
                   corners[(index + 2) % 4],
                   corners[(index + 3) % 4])
    if abs(fixed) < CONVEX_EPSILON:
        return None
    sign = 1.0 if fixed > 0.0 else -1.0

    planes = []
    for k in ((index - 2) % 4, (index - 1) % 4, index):
        trio = [corners[k], corners[(k + 1) % 4], corners[(k + 2) % 4]]
        slot = [j for j in range(3) if (k + j) % 4 == index][0]

        def area_with(point, trio=trio, slot=slot):
            """Twice the signed area of this trio with the corner moved to point."""
            trio[slot] = point
            return _area2(trio[0], trio[1], trio[2])

        # Affine in the moving corner, so two probes give the gradient exactly.
        base = area_with((0.0, 0.0))
        gx = area_with((1.0, 0.0)) - base
        gy = area_with((0.0, 1.0)) - base
        # sign * area >= CONVEX_EPSILON + CONVEX_MARGIN
        planes.append((sign * gx, sign * gy,
                       CONVEX_EPSILON + CONVEX_MARGIN - sign * base))

    # The Corner Pin clamps its sockets to 0..1 at evaluation, so a position
    # outside the unit square is not a position at all.
    planes.extend([(1.0, 0.0, 0.0), (-1.0, 0.0, -1.0),
                   (0.0, 1.0, 0.0), (0.0, -1.0, -1.0)])
    return planes


def _feasible(planes, point, tol=CONVEX_FEASIBLE_TOL):
    """Return True if point satisfies every half-plane, within tol."""
    for nx, ny, d in planes:
        if nx * float(point[0]) + ny * float(point[1]) < d - tol:
            return False
    return True


def constrain_corner(corners, index, target):
    """
    Return the nearest position for one corner that keeps the quad convex.

    A valid target is passed straight through, so nothing is moved that did not
    have to be. An invalid one is projected onto the feasible region built by
    _corner_halfplanes: since that region is a convex polygon, the nearest point
    in it lies either in the relative interior of one of its facets or at one of
    its vertices, so projecting the target onto each constraint line and
    intersecting each pair of lines is an exhaustive candidate set. Measured
    exact against a 601x601 brute-force scan.

    The result is a Vector, so it carries float32 like the socket it is bound
    for; a target that came from a socket or a Blender property survives the
    trip unchanged, and CONVEX_MARGIN is sized so a projected one stays convex
    after the rounding.

    Callers that can act on a refusal use this; nodes.write_pin stays
    deliberately unguarded, because every path funnels through it including
    ones with nothing useful to do about one.

    Args:
        corners: four (x, y) points in perspective_nodes.CORNER_SOCKETS order
        index: which corner is being moved
        target: the (x, y) the caller would like it to take

    Returns:
        Vector: the target itself when it is already valid, otherwise the
        nearest valid position; or None when the other three corners are
        themselves degenerate and no position for this one can rescue the quad
    """
    planes = _corner_halfplanes(corners, index)
    if planes is None:
        return None
    if _feasible(planes, target):
        return Vector((float(target[0]), float(target[1])))

    tx, ty = float(target[0]), float(target[1])
    candidates = []
    for nx, ny, d in planes:
        norm2 = nx * nx + ny * ny
        if norm2 < 1e-24:
            continue
        step = (d - (nx * tx + ny * ty)) / norm2
        candidates.append((tx + step * nx, ty + step * ny))
    for i in range(len(planes)):
        ax, ay, ad = planes[i]
        for j in range(i + 1, len(planes)):
            bx, by, bd = planes[j]
            det = ax * by - ay * bx
            if abs(det) < 1e-12:
                continue
            candidates.append(((ad * by - ay * bd) / det,
                               (ax * bd - ad * bx) / det))

    best = None
    best_distance = None
    for point in candidates:
        if not _feasible(planes, point):
            continue
        distance = (point[0] - tx) ** 2 + (point[1] - ty) ** 2
        if best_distance is None or distance < best_distance:
            best = point
            best_distance = distance
    if best is None:
        return None
    return Vector(best)
