"""
BL Perspective Transform - Operators and sidebar panel.

The corner handles do the actual editing; these operators cover the things a
drag cannot express: resetting, removing the transform, and making room for
corners beyond the image edge.
"""

import bpy
from bpy.props import FloatProperty

from . import perspective_anim as anim
from . import perspective_core as core
from . import perspective_nodes as nodes

TOOL_IDNAME = "sequencer.perspective_handles_tool"


def _target_strips(context):
    """Return selected strips that can carry a perspective transform."""
    scene = nodes.get_sequencer_scene(context)
    editor = getattr(scene, "sequence_editor", None) if scene else None
    if editor is None:
        return []
    return [strip for strip in editor.strips if strip.select and hasattr(strip, "transform")]


class SEQUENCER_OT_perspective_activate(bpy.types.Operator):
    """Switch the preview to the perspective corner handle tool"""

    bl_idname = "sequencer.perspective_activate"
    bl_label = "Perspective"
    bl_description = "Activate the perspective corner handle tool"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return nodes.get_active_strip(context) is not None

    def execute(self, context):
        bpy.ops.wm.tool_set_by_id(name=TOOL_IDNAME)
        return {'FINISHED'}


class SEQUENCER_OT_perspective_reset(bpy.types.Operator):
    """Return the corners to the undistorted image rectangle"""

    bl_idname = "sequencer.perspective_reset"
    bl_label = "Reset Perspective"
    bl_description = "Move the corners back to the image rectangle, keeping the modifier"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return any(nodes.has_perspective(s) for s in _target_strips(context))

    def execute(self, context):
        count = 0
        cleared = 0
        for strip in _target_strips(context):
            if not nodes.has_perspective(strip):
                continue
            # Keyframes have to go too. Writing identity into a socket that an
            # fcurve drives looks like it worked and is undone by the very next
            # frame change, which reads as the operator having done nothing.
            cleared += anim.clear_animation(strip)
            nodes.reset(strip)
            count += 1

        if cleared:
            self.report({'INFO'},
                        f"Reset perspective on {count} strip(s), "
                        f"removing {cleared} animation channel(s)")
        else:
            self.report({'INFO'}, f"Reset perspective on {count} strip(s)")
        return {'FINISHED'}


class SEQUENCER_OT_perspective_clear(bpy.types.Operator):
    """Remove the perspective modifier and its node group"""

    bl_idname = "sequencer.perspective_clear"
    bl_label = "Clear Perspective"
    bl_description = "Remove the perspective modifier from the selected strips"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return any(nodes.has_perspective(s) for s in _target_strips(context))

    def execute(self, context):
        scene = nodes.get_sequencer_scene(context)
        count = sum(1 for strip in _target_strips(context) if nodes.clear(strip, scene))
        self.report({'INFO'}, f"Cleared perspective from {count} strip(s)")
        return {'FINISHED'}


class SEQUENCER_OT_perspective_add_headroom(bpy.types.Operator):
    """Scale the strip up so corners can be dragged beyond the image edge"""

    bl_idname = "sequencer.perspective_add_headroom"
    bl_label = "Add Headroom"
    bl_description = ("Enlarge the strip while holding the perspective quad still, "
                      "so corners can be dragged outside the image rectangle")
    bl_options = {'REGISTER', 'UNDO'}

    factor: FloatProperty(
        name="Factor",
        description="How much to enlarge the strip by. Values below 1 remove headroom",
        default=2.0,
        min=0.1,
        max=10.0,
        soft_min=0.5,
        soft_max=4.0,
    )

    @classmethod
    def poll(cls, context):
        return bool(_target_strips(context))

    def execute(self, context):
        scene = nodes.get_sequencer_scene(context)
        applied = 0
        refused = 0
        for strip in _target_strips(context):
            if core.add_headroom(strip, scene, self.factor):
                applied += 1
            else:
                refused += 1

        if refused and not applied:
            self.report({'WARNING'},
                        "Cannot remove headroom: the corners would fall outside the image")
            return {'CANCELLED'}
        if refused:
            self.report({'WARNING'}, f"Applied to {applied} strip(s), skipped {refused}")
        else:
            self.report({'INFO'}, f"Headroom applied to {applied} strip(s)")
        return {'FINISHED'}


def draw_perspective(layout, context, strip):
    """
    Draw the perspective controls for one strip.

    Shared by the preview sidebar and the Properties editor, so the two can
    never drift apart.

    use_property_split and use_property_decorate are what give each corner the
    animate dot on the right, which is how a corner gets keyframed by hand and
    how an already-keyed corner shows its state. Without them Blender draws no
    decorator column at all, and the values look unanimatable even though they
    are not - see DEV.md -> Keyframing.
    """
    modifier = nodes.find_modifier(strip) if strip else None

    if modifier is None:
        column = layout.column()
        column.label(text="No perspective on this strip")
        column.label(text="Drag a corner handle to begin", icon='INFO')
        column.operator(SEQUENCER_OT_perspective_activate.bl_idname,
                        text="Activate Tool", icon='MOD_WARP')
        return

    node = nodes.get_corner_pin_node(modifier.node_group)
    if node is None:
        layout.label(text="Node group has no Corner Pin node", icon='ERROR')
        return

    layout.use_property_split = True
    layout.use_property_decorate = True

    column = layout.column(align=True)
    for socket_name, label in zip(nodes.CORNER_SOCKETS, nodes.CORNER_LABELS):
        column.prop(node.inputs[socket_name], "default_value", text=label)

    column = layout.column()
    column.prop(node.inputs['Interpolation'], "default_value", text="Interpolation")

    # Dragging a keyed corner with auto-key off looks like it worked and is
    # undone on the next frame change. Say so rather than let it puzzle people.
    if anim.is_animated(strip):
        tool_settings = getattr(nodes.get_sequencer_scene(context), "tool_settings", None)
        if tool_settings is not None and not tool_settings.use_keyframe_insert_auto:
            box = layout.box()
            box.label(text="Corners are keyframed", icon='ANIM')
            box.label(text="Turn on auto-keying, or edits revert on frame change")

    if core.needs_headroom(strip):
        box = layout.box()
        box.label(text="Corners are at the image edge", icon='INFO')
        box.operator(SEQUENCER_OT_perspective_add_headroom.bl_idname,
                     text="Add Headroom")

    row = layout.row(align=True)
    row.operator(SEQUENCER_OT_perspective_reset.bl_idname, text="Reset")
    row.operator(SEQUENCER_OT_perspective_clear.bl_idname, text="Clear")


class SEQUENCER_PT_perspective(bpy.types.Panel):
    """Preview sidebar panel showing the corner values of the active strip"""

    bl_idname = "SEQUENCER_PT_perspective"
    bl_label = "Perspective"
    bl_space_type = 'SEQUENCE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "Perspective"

    @classmethod
    def poll(cls, context):
        return nodes.get_active_strip(context) is not None

    def draw(self, context):
        draw_perspective(self.layout, context, nodes.get_active_strip(context))


class STRIP_PT_perspective(bpy.types.Panel):
    """Strip properties panel, alongside Blender's own Transform and Crop"""

    bl_idname = "STRIP_PT_perspective"
    bl_label = "Perspective"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "strip"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        strip = getattr(context, "active_strip", None)
        # Sound strips have no image to distort, and match how Blender polls
        # its own STRIP_PT_adjust_transform and STRIP_PT_adjust_crop.
        return strip is not None and strip.type != 'SOUND'

    def draw(self, context):
        draw_perspective(self.layout, context, context.active_strip)


classes = (
    SEQUENCER_OT_perspective_activate,
    SEQUENCER_OT_perspective_reset,
    SEQUENCER_OT_perspective_clear,
    SEQUENCER_OT_perspective_add_headroom,
    SEQUENCER_PT_perspective,
    STRIP_PT_perspective,
)
