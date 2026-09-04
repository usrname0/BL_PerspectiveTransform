"""
BL Perspective Transform - the values the panel shows before a strip has one.

STRIP_PT_perspective shows the filter and the four corners at all times, the way
Blender's own Transform and Crop panels show theirs. Those values live in a
Corner Pin node, and that node only exists once a strip actually has a
perspective, so something has to stand in until then. These properties are it:
they read back as the untransformed identity quad, and writing to one builds the
node group and forwards the write, after which the panel draws the real sockets
instead and keyframing, the animate dot and the Dope Sheet channels all work as
before.

They live on the WindowManager, and they store nothing at all - every one is a
get/set pair over the strip's own state. That matters twice over:

  * Nothing reaches the .blend, so the node group stays the single source of
    truth. A shadow copy in strip properties would have to be kept in step with
    the sockets, and would be the thing an fcurve attached itself to.
  * A placeholder cannot go stale. Selecting a second strip that has no
    perspective shows identity because identity is what that strip reads, not
    because anything was reset.

The get/set pair is also why these are not simply the sockets of a hidden
template node group: a socket has no write hook, so editing one could never
create anything.
"""

import time

import bpy
from bpy.props import EnumProperty, FloatVectorProperty, PointerProperty

from . import perspective_nodes as nodes
from . import perspective_space as space

# Where the pointer lands: context.window_manager.perspective_transform
WM_PROPERTY = "perspective_transform"

# How long the panel keeps drawing placeholder rows after one has been written.
#
# Without this the panel swaps to the real socket rows the instant the transform
# is created, which is in the middle of the drag that created it. Blender matches
# buttons across a redraw by their RNA pointer, so the button under the cursor is
# not carried over: the drag ends, and because a number field grabs and hides the
# cursor while dragging, the pointer is restored to a button that is no longer
# there. Reported as the mouse jumping around, and it does.
#
# Holding the placeholders on screen until the drag has stopped keeps the same
# button under the cursor, so the drag runs to its end. The transform is still
# created on the first delta, so the preview updates live throughout.
#
# Tuning: too long and the animate dots take a beat to appear after a typed edit,
# which is cosmetic. Too short and it swaps during a pause mid-drag, which is the
# bug it exists to prevent. Erring long.
HANDOVER_DELAY = 1.0

# Monotonic deadline, not a strip - a strip is not an ID and holding a reference
# to a deleted one across a timer is a crash waiting to happen. Which strip was
# written does not matter: the placeholders read whatever strip the panel is
# showing, so the worst a stale window can do is leave the decorator column blank
# for a moment on a strip nobody just touched.
_handover = {"until": 0.0}

# The corner placeholders, in nodes.CORNER_SOCKETS order. The panel walks this
# alongside CORNER_LABELS, so the two orders have to agree.
CORNER_PROPS = ("lower_left", "upper_left", "upper_right", "lower_right")

FILTER_SOCKET = "Interpolation"

# The Corner Pin node's Interpolation input is a NodeSocketMenu, and a menu
# socket does not publish its items through RNA - bl_rna reports an empty enum.
# These four are what it accepts, measured on 5.2.1 by assignment; anything else
# raises. A Blender that renames one of them makes the write below fail, which
# is why that write is caught rather than left to raise inside a UI callback.
FILTER_ITEMS = (
    ('Nearest', "Nearest", "No interpolation, nearest source pixel", 0),
    ('Bilinear', "Bilinear", "Linear interpolation between source pixels", 1),
    ('Bicubic', "Bicubic", "Cubic interpolation between source pixels", 2),
    ('Anisotropic', "Anisotropic", "Filter along the direction the image is stretched", 3),
)

FILTER_DEFAULT = 'Bilinear'


def _active_strip():
    """
    Return the strip the panel is drawing, or None.

    context.active_strip is what the panel itself reads, and what Blender's own
    strip panels read, so it is asked first. The sequencer scene's active strip
    is the same object by another route, and is the answer wherever the UI
    context is not available - a script driving these properties, or a test.
    """
    strip = getattr(bpy.context, "active_strip", None)
    if strip is not None:
        return strip
    return nodes.get_active_strip(bpy.context)


def _writable_target():
    """
    Return (strip, scene) for a write, or (None, None) if there is nowhere to write.

    Both are needed: creating the modifier is what crashes Blender outright when
    the sequencer scene is unknown - see perspective_nodes.ensure_modifier.
    """
    strip = _active_strip()
    if strip is None or not hasattr(strip, "transform"):
        return None, None
    scene = nodes.get_sequencer_scene(bpy.context)
    return (strip, scene) if scene is not None else (None, None)


def is_handing_over():
    """
    Return True while the panel should keep drawing placeholder rows.

    The panel asks this alongside "does the strip have a transform", so that a
    drag which has just built one is not interrupted by its own success. See
    HANDOVER_DELAY.
    """
    return time.monotonic() < _handover["until"]


def _tag_properties_redraw():
    """Redraw every Properties editor, so the handover happens on its own."""
    window_manager = getattr(bpy.context, "window_manager", None)
    for window in getattr(window_manager, "windows", ()) or ():
        for area in window.screen.areas:
            if area.type == 'PROPERTIES':
                area.tag_redraw()


def _finish_handover():
    """
    Timer: swap the panel back to the real sockets once writing has stopped.

    Reschedules itself while writes are still arriving, so one drag costs one
    timer no matter how many events it produces.
    """
    remaining = _handover["until"] - time.monotonic()
    if remaining > 0.0:
        return remaining
    _tag_properties_redraw()
    return None


def _hold_placeholders():
    """Extend the handover window, and make sure something ends it."""
    _handover["until"] = time.monotonic() + HANDOVER_DELAY
    if not bpy.app.timers.is_registered(_finish_handover):
        bpy.app.timers.register(_finish_handover, first_interval=HANDOVER_DELAY)


def _push_undo(strip, was_missing):
    """
    Push an undo step, but only for the write that created the transform.

    Buttons owned by the WindowManager sit outside undo, so nothing is recorded
    for these edits unless it is recorded here. Once the modifier exists the
    panel draws the real sockets, whose edits Blender records itself - so this
    fires once per strip, and a slider drag does not fill the undo stack.
    """
    if was_missing and nodes.has_perspective(strip):
        bpy.ops.ed.undo_push(message="Add Perspective")


def _corner_property(index):
    """
    Build the placeholder property for one corner.

    Args:
        index: corner index, in nodes.CORNER_SOCKETS order

    Returns:
        the FloatVectorProperty to annotate onto the PropertyGroup
    """

    def getter(self):
        strip = _active_strip()
        if strip is None:
            return nodes.IDENTITY_PIN[index]
        # read_pin answers identity for a strip with no modifier, which is
        # exactly the value this placeholder exists to show.
        return tuple(nodes.read_pin(strip)[index])

    def setter(self, value):
        strip, scene = _writable_target()
        if strip is None:
            return
        _hold_placeholders()
        was_missing = not nodes.has_perspective(strip)
        corners = list(nodes.read_pin(strip))
        # The handle drag guards itself against a non-convex quad; this is the
        # same guard on the panel's own path, and it costs nothing because this
        # path already runs Python. It only ever covers a strip with no
        # transform yet, where the other three corners are still identity, so
        # the shapes it refuses are the ones you get by pulling one corner
        # across the square's diagonal. Narrow, but it is the guard being
        # consistent rather than absent. Once the strip has a transform the
        # panel binds to the sockets, and nothing in Python sits between the
        # slider and the value - see STRIP_PT_perspective's warning.
        constrained = space.constrain_corner(corners, index, value)
        if constrained is None:
            return
        corners[index] = constrained
        nodes.write_pin(strip, scene, corners)
        _push_undo(strip, was_missing)

    return FloatVectorProperty(
        name=nodes.CORNER_LABELS[index],
        description="Corner position on the source image",
        size=2,
        # The socket this stands in for is a 0..1 factor pair with a step of 10
        # and three decimal places, measured on 5.2.1. Matching it keeps the
        # field from changing under the cursor when the real socket takes over.
        min=0.0,
        max=1.0,
        step=10,
        precision=3,
        get=getter,
        set=setter,
    )


def _get_filter(self):
    """Return the strip's filter as an enum index; EnumProperty getters are ints."""
    strip = _active_strip()
    modifier = nodes.find_modifier(strip) if strip else None
    node = nodes.get_corner_pin_node(modifier.node_group) if modifier else None
    value = node.inputs[FILTER_SOCKET].default_value if node else FILTER_DEFAULT
    for identifier, _name, _description, number in FILTER_ITEMS:
        if identifier == value:
            return number
    return next(item[3] for item in FILTER_ITEMS if item[0] == FILTER_DEFAULT)


def _set_filter(self, value):
    """Write the filter to the strip, building the transform if it has none."""
    strip, scene = _writable_target()
    if strip is None:
        return
    _hold_placeholders()
    was_missing = not nodes.has_perspective(strip)
    node = nodes.prepare_for_edit(strip, scene)
    if node is None:
        return
    try:
        node.inputs[FILTER_SOCKET].default_value = FILTER_ITEMS[value][0]
    except (TypeError, IndexError, KeyError):
        return  # a Blender that renamed the menu entries; leave the socket alone
    _push_undo(strip, was_missing)


class PERSPECTIVE_PG_defaults(bpy.types.PropertyGroup):
    """
    The panel's stand-in values for a strip that has no perspective yet.

    Every property here is a view onto the strip's Corner Pin node rather than
    storage of its own. Reading one gives the strip's current value, or identity
    where there is nothing to read; writing one creates the transform.
    """

    lower_left: _corner_property(0)
    upper_left: _corner_property(1)
    upper_right: _corner_property(2)
    lower_right: _corner_property(3)

    filter: EnumProperty(
        name="Filter",
        description="Method used to resample the image the corners are pinned to",
        items=FILTER_ITEMS,
        default=FILTER_DEFAULT,
        get=_get_filter,
        set=_set_filter,
    )


def get_defaults(context):
    """Return the placeholder group, or None if the addon is not registered."""
    return getattr(context.window_manager, WM_PROPERTY, None)


def register_perspective_defaults():
    """Register the placeholder group and hang it off the WindowManager."""
    bpy.utils.register_class(PERSPECTIVE_PG_defaults)
    setattr(bpy.types.WindowManager, WM_PROPERTY,
            PointerProperty(type=PERSPECTIVE_PG_defaults))


def unregister_perspective_defaults():
    """Remove the WindowManager pointer and the group behind it."""
    if bpy.app.timers.is_registered(_finish_handover):
        bpy.app.timers.unregister(_finish_handover)
    _handover["until"] = 0.0
    if hasattr(bpy.types.WindowManager, WM_PROPERTY):
        delattr(bpy.types.WindowManager, WM_PROPERTY)
    bpy.utils.unregister_class(PERSPECTIVE_PG_defaults)
