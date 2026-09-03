"""
BL Perspective Transform - keyframing the corner pin.

The four Corner Pin sockets are ordinary animatable RNA properties on the node
group datablock, so most of this works with no help from the addon: Blender
renders the animation, drives the preview from it, tracks it in the panel as
the playhead moves, and lists the channels in the Dope Sheet under
Scene -> <node group name>.

Two things Blender cannot do on its own, and this module supplies:

  * Auto-keying on a drag. Auto-key only fires for operators that ask for it.
    The corner handles write their socket through plain RNA, which never
    triggers it, so the gizmo calls autokey_corner() when a drag ends. That
    keys the dragged corner and nothing else - see autokey_corner.
  * Keeping keyed corners honest through a headroom change. Add Headroom
    rewrites the socket values, but an animated corner is driven by its fcurve
    and simply snaps back on the next frame, tearing the transform apart. The
    same remap has to be applied to the stored key values.

Two more facts this module is built on:

  * socket.keyframe_insert("default_value") animates the rendered result
  * the headroom remap is exactly  new = origin + (old - origin) / factor,
    which is axis separable and independent of rotation, mirror, offset,
    source size and resolution - so each fcurve remaps on its own, and the
    bezier handles remap with it.
"""

from . import perspective_nodes as nodes

# Channel group name, so the four corners read as one block in the Dope Sheet
# rather than as eight loose channels.
FCURVE_GROUP = "Perspective"


def _corner_socket(node, index):
    """Return the Corner Pin input socket for a corner index."""
    return node.inputs[nodes.CORNER_SOCKETS[index]]


def corner_data_path(node, index):
    """
    Return the RNA data path of a corner, relative to the node group.

    Looks like nodes["Corner Pin"].inputs[2].default_value. Built through
    path_from_id rather than by formatting a string, so a renamed node or a
    reordered socket list cannot silently produce a path that matches nothing.
    """
    return _corner_socket(node, index).path_from_id("default_value")


def _corner_pin(strip):
    """Return (node_group, corner_pin_node) for a strip, or (None, None)."""
    modifier = nodes.find_modifier(strip)
    group = modifier.node_group if modifier else None
    return group, nodes.get_corner_pin_node(group)


def _iter_fcurve_owners(anim_data):
    """
    Yield (owner, fcurve) for the action bound to anim_data.

    The owner is whatever exposes .fcurves.remove(), so callers can delete a
    curve without knowing which action layout they are looking at. Blender 4.4
    moved fcurves out of Action.fcurves and into a per-slot channelbag; both
    shapes are handled because the legacy one still turns up in older files.
    """
    action = getattr(anim_data, "action", None)
    if action is None:
        return

    layers = getattr(action, "layers", ())
    if layers:
        slot = getattr(anim_data, "action_slot", None)
        handle = getattr(slot, "handle", None)
        for layer in layers:
            for action_strip in layer.strips:
                for bag in getattr(action_strip, "channelbags", ()):
                    if handle is not None and bag.slot_handle != handle:
                        continue
                    for fcurve in bag.fcurves:
                        yield bag, fcurve
        return

    for fcurve in getattr(action, "fcurves", ()):
        yield action, fcurve


def iter_corner_fcurves(strip):
    """
    Yield (corner_index, array_index, fcurve) for every keyed corner channel.

    array_index is 0 for the corner's u and 1 for its v. Channels belonging to
    anything else in the node group are skipped.
    """
    group, node = _corner_pin(strip)
    if node is None:
        return
    anim_data = getattr(group, "animation_data", None)
    if anim_data is None:
        return

    paths = {corner_data_path(node, index): index for index in range(4)}
    for _owner, fcurve in _iter_fcurve_owners(anim_data):
        index = paths.get(fcurve.data_path)
        if index is not None and fcurve.array_index in (0, 1):
            yield index, fcurve.array_index, fcurve


def animated_corners(strip):
    """Return the set of corner indices that carry keyframes."""
    return {index for index, _, _ in iter_corner_fcurves(strip)}


def is_animated(strip):
    """Return True if any corner of the strip's perspective is keyframed."""
    for _ in iter_corner_fcurves(strip):
        return True
    return False


def insert_corner_key(strip, scene, index, frame=None):
    """
    Insert a keyframe for one corner.

    Args:
        strip: the strip carrying the perspective modifier
        scene: the sequencer scene, used for the current frame
        index: corner index in perspective_nodes.CORNER_SOCKETS order
        frame: frame to key, or None for the scene's current frame

    Returns:
        bool: True if a keyframe was written
    """
    _group, node = _corner_pin(strip)
    if node is None:
        return False
    if frame is None:
        frame = scene.frame_current
    socket = _corner_socket(node, index)
    return bool(socket.keyframe_insert("default_value", frame=frame, group=FCURVE_GROUP))


def insert_pin_keys(strip, scene, frame=None):
    """
    Key all four corners at once.

    Not on the drag path - a drag keys only the corner it moved - but the
    whole-quad key is what a test fixture or a caller posing a shape wants.

    Returns:
        int: how many corners were keyed
    """
    return sum(1 for index in range(4)
               if insert_corner_key(strip, scene, index, frame))


def autokey_corner(strip, scene, index, tool_settings=None):
    """
    Key the corner that just moved, if the user has auto-keying switched on.

    Called when a handle drag finishes, and keys *only* the dragged corner,
    which is how auto-key behaves for every other property in Blender.

    The consequence is the ordinary one for an unanimated property: an
    untouched corner stays a constant applying to every frame, so its current
    value holds across frames the user has already posed.

    Args:
        strip: the strip being edited
        scene: the sequencer scene, which supplies the frame to key at
        index: corner index in perspective_nodes.CORNER_SOCKETS order
        tool_settings: where to read the auto-key flag from. Pass
            context.tool_settings: the UI's toggle writes the *window* scene's
            copy, which since 5.0 need not be the sequencer scene. Falling back
            to the scene's own is a last resort and can disagree with what the
            user has switched on.

    Returns:
        int: how many corners were keyed, 0 when auto-keying is off
    """
    if tool_settings is None:
        tool_settings = getattr(scene, "tool_settings", None)
    if tool_settings is None or not tool_settings.use_keyframe_insert_auto:
        return 0
    return 1 if insert_corner_key(strip, scene, index) else 0


def pin_matches(strip, corners, tolerance=1e-6):
    """
    Return True if the strip's pin still equals the given corners.

    Used to tell a real drag from a bare click on a handle: both run the same
    invoke/exit cycle, and a click should neither drop a keyframe nor push an
    undo step. A None baseline counts as "changed", so a drag whose starting
    state was never captured is still committed.
    """
    if corners is None:
        return False
    for before, after in zip(corners, nodes.read_pin(strip)):
        if abs(before[0] - after[0]) > tolerance or abs(before[1] - after[1]) > tolerance:
            return False
    return True


def _remapped(value, centre, factor):
    """Apply the headroom pin remap to a single scalar."""
    return centre + (value - centre) / factor


def keys_fit_after_remap(strip, origin, factor, tolerance=1e-6):
    """
    Return True if every keyed corner value stays inside the unit square.

    The Corner Pin node clamps to 0..1 at evaluation, so a remap that pushes a
    key outside would silently change the shape of the animation at that frame.
    Removing headroom is refused in that case, the same way it is refused when
    the current corners would no longer fit.
    """
    for _index, array_index, fcurve in iter_corner_fcurves(strip):
        centre = float(origin[array_index])
        for key in fcurve.keyframe_points:
            value = _remapped(key.co.y, centre, factor)
            if not (-tolerance <= value <= 1.0 + tolerance):
                return False
    return True


def remap_corner_keys(strip, origin, factor):
    """
    Rescale every keyed corner value for a headroom change.

    The headroom remap is a uniform scale about the strip's transform origin in
    pin space, so it applies to each channel independently and to the bezier
    handles with it - the handle frame coordinates are untouched, only their
    values move, which preserves the shape of the curve exactly.

    Args:
        strip: the strip whose keys should move
        origin: the strip's transform origin, as (x, y) in 0..1
        factor: the same factor passed to add_headroom

    Returns:
        int: how many keyframes were remapped
    """
    count = 0
    for _index, array_index, fcurve in iter_corner_fcurves(strip):
        centre = float(origin[array_index])
        for key in fcurve.keyframe_points:
            key.co.y = _remapped(key.co.y, centre, factor)
            key.handle_left.y = _remapped(key.handle_left.y, centre, factor)
            key.handle_right.y = _remapped(key.handle_right.y, centre, factor)
            count += 1
        fcurve.update()
    return count


def clear_animation(strip):
    """
    Remove every corner fcurve from the strip's perspective.

    Reset would otherwise appear to do nothing on an animated strip: it writes
    identity into the sockets, and the fcurves overwrite that on the very next
    frame change.

    Returns:
        int: how many fcurves were removed
    """
    group, node = _corner_pin(strip)
    if node is None:
        return 0
    anim_data = getattr(group, "animation_data", None)
    if anim_data is None:
        return 0

    paths = {corner_data_path(node, index) for index in range(4)}
    removed = 0
    for owner, fcurve in list(_iter_fcurve_owners(anim_data)):
        if fcurve.data_path in paths:
            owner.fcurves.remove(fcurve)
            removed += 1

    # Drop the action entirely once nothing of ours is left in it, so the strip
    # stops appearing as an animated channel in the Dope Sheet.
    if removed and not any(True for _ in _iter_fcurve_owners(anim_data)):
        group.animation_data_clear()
    return removed
