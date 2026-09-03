"""
BL Perspective Transform - Core strip helpers.

Thin layer between the gizmo and the node group: strip visibility, and
converting corner positions between frame space and pin space.
"""

from . import perspective_nodes as nodes
from . import perspective_space as space


def get_visible_range(strip):
    """
    Return the strip's visible (start, end) frame range.

    Blender 5.x deprecates frame_final_start and frame_final_end for removal in
    6.0. content_start plus the handle offsets is the replacement, and the two
    agree exactly, trimmed strips included.
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
