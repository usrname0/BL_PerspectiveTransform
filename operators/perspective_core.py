"""
BL Perspective Transform - Core strip helpers.

Thin layer between the gizmo and the node group: strip visibility, converting
corner positions between frame space and pin space, and the headroom operation
that makes room for corners beyond the image edge.
"""

from . import perspective_nodes as nodes
from . import perspective_space as space


def get_visible_range(strip):
    """
    Return the strip's visible (start, end) frame range.

    Blender 5.x deprecates frame_final_start and frame_final_end for removal in
    6.0. content_start plus the handle offsets is the replacement, and was
    verified to reproduce the old values exactly, including for trimmed strips.
    """
    content_start = getattr(strip, "content_start", None)
    if content_start is not None:
        start = content_start + getattr(strip, "left_handle_offset", 0.0)
        return start, start + getattr(strip, "duration", 0)
    return strip.frame_final_start, strip.frame_final_end


def is_strip_visible_at_frame(strip, frame):
    """Return True if the strip contributes to the given frame."""
    if getattr(strip, "mute", False):
        return False
    start, end = get_visible_range(strip)
    return start <= frame <= end


def get_corners_in_frame(strip, scene):
    """
    Return the strip's four perspective corners in frame-space pixels.

    Args:
        strip: the strip to query
        scene: the sequencer scene

    Returns:
        list[mathutils.Vector]: corners in perspective_nodes corner order
    """
    matrix = space.pin_to_frame_matrix(strip, scene)
    return [space.apply(matrix, corner) for corner in nodes.read_pin(strip)]


def set_corners_from_frame(strip, scene, frame_corners):
    """
    Write four frame-space corner positions to the strip's corner pin.

    Args:
        strip: the strip to modify
        scene: the sequencer scene
        frame_corners: four frame-space points in corner order

    Returns:
        list[mathutils.Vector]: the pin values actually stored, after clamping
    """
    matrix = space.frame_to_pin_matrix(strip, scene)
    pin_corners = [space.apply(matrix, point) for point in frame_corners]
    return nodes.write_pin(strip, scene, pin_corners)


def needs_headroom(strip, tolerance=1e-4):
    """
    Return True if any corner is sitting on the image edge.

    A corner pinned to the edge cannot be dragged further out, because the
    Corner Pin node clamps its inputs to the unit square. That is the signal
    that the user needs headroom rather than that they have finished.
    """
    for corner in nodes.read_pin(strip):
        if (corner.x <= tolerance or corner.x >= 1.0 - tolerance
                or corner.y <= tolerance or corner.y >= 1.0 - tolerance):
            return True
    return False


def add_headroom(strip, scene, factor=2.0):
    """
    Scale the strip up while holding its perspective quad visually still.

    The Corner Pin node clamps its corners to the source image rectangle, so
    corners can never be dragged beyond the image edge. Scaling the strip
    enlarges that rectangle while this remaps the pin so nothing appears to
    move, leaving margin on all sides to drag into.

    Args:
        strip: the strip to modify
        scene: the sequencer scene
        factor: how much to enlarge by; above 1 adds room, below 1 removes it

    Returns:
        bool: True if applied. False if the change is impossible without
        distorting the image, which happens when shrinking past the point
        where the current corners still fit inside the image rectangle.
    """
    if factor <= 0.0 or not hasattr(strip, "transform"):
        return False

    old_matrix = space.pin_to_frame_matrix(strip, scene)
    frame_corners = [space.apply(old_matrix, corner) for corner in nodes.read_pin(strip)]

    previous_x = strip.transform.scale_x
    previous_y = strip.transform.scale_y
    strip.transform.scale_x = previous_x * factor
    strip.transform.scale_y = previous_y * factor

    new_matrix = space.frame_to_pin_matrix(strip, scene)
    new_corners = [space.apply(new_matrix, point) for point in frame_corners]

    # Shrinking can push corners outside the unit square, where they would be
    # silently clamped and the image would visibly change shape. Refuse instead.
    for corner in new_corners:
        if not (-1e-6 <= corner.x <= 1.0 + 1e-6 and -1e-6 <= corner.y <= 1.0 + 1e-6):
            strip.transform.scale_x = previous_x
            strip.transform.scale_y = previous_y
            return False

    nodes.write_pin(strip, scene, new_corners)
    return True
