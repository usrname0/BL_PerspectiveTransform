"""
BL Perspective Transform - Compositor node group management.

The perspective transform is stored as a Corner Pin node inside a compositor
node group, attached to the strip through a COMPOSITOR strip modifier. That
node group is the single source of truth: there is no shadow copy in custom
properties, which means the transform survives save and load, shows up in the
Strip Modifiers tab, renders without any help from this addon, and can be
keyframed like any other node socket.

The node group has the shape:

    Group Input -> Corner Pin -> Group Output

Blender 5.3 adds per-modifier custom inputs, which would let one shared node
group serve every strip. Targeting 5.0 means one group per strip instead, so
this module owns creating, un-sharing and cleaning up those datablocks.
"""

from typing import cast

import bpy
from mathutils import Vector

# Marks a node group as ours, so a strip carrying several compositor modifiers
# can still be handled unambiguously. Stored on the node group rather than the
# modifier because modifier names are user-editable.
GROUP_TAG = "bl_perspective_transform"

# Stamped into the tag so a later version can recognize the groups this one
# wrote and migrate them. Nothing reads it back yet.
GROUP_TAG_VERSION = 1

MODIFIER_NAME = "Perspective"

# Corner ordering used throughout the addon: bottom-left, top-left, top-right,
# bottom-right, walking counterclockwise from the origin. The tuple maps that
# order onto the Corner Pin node's own socket names.
CORNER_SOCKETS = ("Lower Left", "Upper Left", "Upper Right", "Lower Right")

CORNER_LABELS = ("Bottom Left", "Top Left", "Top Right", "Bottom Right")

# Pin values for an untransformed strip, in CORNER_SOCKETS order.
IDENTITY_PIN = ((0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0))


def get_sequencer_scene(context):
    """
    Return the scene whose sequence editor the VSE is showing.

    Blender 5.0 decoupled the sequencer's scene from the window's active scene,
    so context.scene can refer to something else entirely while a VSE is open.
    """
    scene = getattr(context, "sequencer_scene", None)
    return scene if scene is not None else context.scene


def get_active_strip(context):
    """Return the active strip of the sequencer scene, or None."""
    scene = get_sequencer_scene(context)
    editor = getattr(scene, "sequence_editor", None) if scene else None
    return editor.active_strip if editor else None


def _tag_group(node_group):
    """Mark a node group as belonging to this addon."""
    node_group[GROUP_TAG] = GROUP_TAG_VERSION


def _is_our_group(node_group):
    """Return True if a node group was created by this addon."""
    return node_group is not None and node_group.get(GROUP_TAG) is not None


def find_modifier(strip):
    """
    Return the strip's perspective modifier, or None.

    Identified by its node group's tag rather than by modifier name, so a user
    renaming the modifier does not orphan their transform.
    """
    modifiers = getattr(strip, "modifiers", None)
    if not modifiers:
        return None
    for modifier in modifiers:
        if modifier.type == 'COMPOSITOR' and _is_our_group(modifier.node_group):
            return modifier
    return None


def has_perspective(strip):
    """Return True if the strip carries a perspective modifier."""
    return find_modifier(strip) is not None


def get_corner_pin_node(node_group):
    """Return the Corner Pin node inside a node group, or None."""
    if node_group is None:
        return None
    for node in node_group.nodes:
        if node.bl_idname == 'CompositorNodeCornerPin':
            return node
    return None


def build_node_group(name):
    """
    Create a tagged compositor node group wired for corner pinning.

    Args:
        name: base name for the datablock; Blender makes it unique

    Returns:
        bpy.types.NodeTree: the new group, pinned to identity
    """
    group = bpy.data.node_groups.new(name, 'CompositorNodeTree')
    _tag_group(group)

    # NodeTree.interface is never None - measured on 5.0.1 and 5.2.1 - but the
    # stubs make every pointer property Optional and there are far too many to
    # correct one at a time.
    group.interface.new_socket(  # pyright: ignore[reportOptionalMemberAccess]
        "Image", in_out='INPUT', socket_type='NodeSocketColor')
    group.interface.new_socket(  # pyright: ignore[reportOptionalMemberAccess]
        "Image", in_out='OUTPUT', socket_type='NodeSocketColor')

    node_in = group.nodes.new('NodeGroupInput')
    corner_pin = group.nodes.new('CompositorNodeCornerPin')
    node_out = group.nodes.new('NodeGroupOutput')

    node_in.location = (-320.0, 0.0)
    corner_pin.location = (-60.0, 0.0)
    node_out.location = (220.0, 0.0)

    group.links.new(node_in.outputs[0], corner_pin.inputs['Image'])
    group.links.new(corner_pin.outputs['Image'], node_out.inputs[0])

    # A Corner Pin corner is a NodeSocketVectorFactor2D on 5.0.1 and 5.2.1;
    # default_value belongs to that subclass, not to the NodeSocket the
    # collection is typed as. The stub then declares it a bpy_prop_array and
    # so refuses the sequence assignment that is the actual API.
    for socket_name, value in zip(CORNER_SOCKETS, IDENTITY_PIN):
        socket = cast(bpy.types.NodeSocketVectorFactor2D,
                      corner_pin.inputs[socket_name])
        socket.default_value = value  # pyright: ignore[reportAttributeAccessIssue]

    return group


def ensure_modifier(strip, scene):
    """
    Return the strip's perspective modifier, creating it if absent.

    Every modifier RNA call that invalidates the sequencer cache - new() and
    remove() both - dereferences a null scene and crashes Blender outright when
    context.sequencer_scene is unset. Reproduced on 5.0.1 and 5.1.2, with every
    modifier type. The temp_override below is what keeps that from happening,
    and must not be removed.

    Args:
        strip: the strip to attach to
        scene: the sequencer scene owning the strip

    Returns:
        bpy.types.StripModifier: the perspective modifier
    """
    existing = find_modifier(strip)
    if existing is not None:
        return existing

    with bpy.context.temp_override(scene=scene, sequencer_scene=scene):
        modifier = strip.modifiers.new(name=MODIFIER_NAME, type='COMPOSITOR')

    modifier.node_group = build_node_group(f"PT_{strip.name}")
    return modifier


def iter_all_strips(scene=None):
    """
    Yield every strip in the file, descending into meta strips.

    Args:
        scene: restrict to one scene, or None to walk all of them
    """
    scenes = [scene] if scene is not None else list(bpy.data.scenes)

    def walk(container):
        for strip in container:
            yield strip
            nested = getattr(strip, "strips", None)
            if nested:
                yield from walk(nested)

    for each in scenes:
        editor = getattr(each, "sequence_editor", None)
        if editor is not None:
            yield from walk(editor.strips)


def count_group_users(node_group):
    """
    Count how many compositor modifiers actually reference a node group.

    Blender's own NodeTree.users is unreliable here: removing a strip modifier
    does not decrement it, so the count only ever grows. Sharing and orphan
    detection both depend on an accurate number, so this walks the strips and
    counts the references directly.
    """
    if node_group is None:
        return 0
    count = 0
    for strip in iter_all_strips():
        for modifier in getattr(strip, "modifiers", ()) or ():
            if modifier.type == 'COMPOSITOR' and modifier.node_group == node_group:
                count += 1
    return count


def ensure_single_user(modifier):
    """
    Give the modifier its own copy of the node group if it is shared.

    Duplicating a strip copies the modifier but shares the node group, so
    without this every corner drag would move both strips at once.

    Returns:
        bpy.types.NodeTree: the group now uniquely owned by this modifier
    """
    group = modifier.node_group
    if group is None:
        return None
    if count_group_users(group) > 1:
        copy = group.copy()
        _tag_group(copy)
        modifier.node_group = copy
        return copy
    return group


def read_pin(strip):
    """
    Return the strip's four pin corners in CORNER_SOCKETS order.

    Args:
        strip: the strip to read

    Returns:
        list[mathutils.Vector]: four pin-space corners; identity if the strip
        has no perspective modifier
    """
    modifier = find_modifier(strip)
    node = get_corner_pin_node(modifier.node_group) if modifier else None
    if node is None:
        return [Vector(c) for c in IDENTITY_PIN]
    return [Vector(node.inputs[name].default_value) for name in CORNER_SOCKETS]


def write_pin(strip, scene, corners):
    """
    Write four pin corners to the strip, creating the modifier if needed.

    Values are clamped to the unit square because the Corner Pin node silently
    ignores anything outside it - an out-of-range pin renders identically to no
    pin at all, which would look like the addon had simply stopped working. A
    corner therefore cannot leave the source image rectangle; scaling the strip
    down is what makes room to pin into.

    Args:
        strip: the strip to write to
        scene: the sequencer scene owning the strip
        corners: four (u, v) pairs in CORNER_SOCKETS order

    Returns:
        list[mathutils.Vector]: the clamped values actually written
    """
    modifier = ensure_modifier(strip, scene)
    group = ensure_single_user(modifier)
    node = get_corner_pin_node(group)
    if node is None:
        return read_pin(strip)

    written = []
    for socket_name, corner in zip(CORNER_SOCKETS, corners):
        value = clamp_corner(corner)
        node.inputs[socket_name].default_value = value
        written.append(value)
    return written


def clamp_corner(corner):
    """Clamp a corner to the unit square the Corner Pin node accepts."""
    return Vector((min(max(float(corner[0]), 0.0), 1.0),
                   min(max(float(corner[1]), 0.0), 1.0)))


def prepare_for_edit(strip, scene):
    """
    Return the strip's Corner Pin node, ready for direct socket writes.

    Creating the modifier and un-sharing the node group both walk every strip in
    the file, which is far too slow to repeat on every mouse-move. Call this
    once at the start of a drag and write through write_corner() afterwards.

    Args:
        strip: the strip being edited
        scene: the sequencer scene owning the strip

    Returns:
        bpy.types.Node: the Corner Pin node, or None if it could not be built
    """
    modifier = ensure_modifier(strip, scene)
    return get_corner_pin_node(ensure_single_user(modifier))


def write_corner(node, index, corner):
    """
    Write a single clamped corner to a Corner Pin node obtained earlier.

    Args:
        node: the Corner Pin node from prepare_for_edit()
        index: corner index in CORNER_SOCKETS order
        corner: the (u, v) pin-space position

    Returns:
        mathutils.Vector: the clamped value actually written
    """
    value = clamp_corner(corner)
    node.inputs[CORNER_SOCKETS[index]].default_value = value
    return value


def is_identity(corners, tolerance=1e-5):
    """Return True if the corners are the untransformed unit square."""
    for corner, identity in zip(corners, IDENTITY_PIN):
        if abs(corner[0] - identity[0]) > tolerance or abs(corner[1] - identity[1]) > tolerance:
            return False
    return True


def reset(strip):
    """Return the strip's pin to identity, leaving the modifier in place."""
    modifier = find_modifier(strip)
    if modifier is None:
        return
    group = ensure_single_user(modifier)
    node = get_corner_pin_node(group)
    if node is None:
        return
    for socket_name, value in zip(CORNER_SOCKETS, IDENTITY_PIN):
        node.inputs[socket_name].default_value = value


def clear(strip, scene):
    """
    Remove the perspective modifier and its node group from the strip.

    Args:
        strip: the strip to clear
        scene: the sequencer scene, required for the same reason as in
            ensure_modifier - removing a modifier invalidates the sequencer
            cache and crashes without it

    Returns:
        bool: True if a modifier was removed
    """
    modifier = find_modifier(strip)
    if modifier is None:
        return False

    group = modifier.node_group
    anim_data = getattr(group, "animation_data", None) if group else None
    action = getattr(anim_data, "action", None) if anim_data else None

    with bpy.context.temp_override(scene=scene, sequencer_scene=scene):
        strip.modifiers.remove(modifier)

    # Drop the datablock only once nothing else points at it. Blender's own
    # group.users cannot answer that here - see count_group_users.
    if group is not None and count_group_users(group) == 0:
        bpy.data.node_groups.remove(group)
        # The node group was the action's only user, so without this the keys
        # linger as an orphan datablock until the next save-and-reload.
        if action is not None and action.users == 0:
            bpy.data.actions.remove(action)
    return True
