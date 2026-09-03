"""
BL Perspective Transform - Operators and the strip properties panel.

The corner handles do the actual editing; these operators cover the things a
drag cannot express: resetting, removing the transform, and making room for
corners beyond the image edge.

STRIP_PT_perspective is the numeric view of the same state, and lives in the
Properties editor beneath Blender's own Crop. See the addon's register() for
how it gets placed there, since panel order is not something a panel can ask
for on its own.
"""

import bpy
from bpy.props import FloatProperty

from . import perspective_anim as anim
from . import perspective_core as core
from . import perspective_nodes as nodes
from . import perspective_space as space

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


class STRIP_PT_perspective(bpy.types.Panel):
    """
    Strip properties panel, sitting directly beneath Blender's own Crop.

    This is the only numeric UI the addon has.
    """

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
        """
        Draw the corner values and whatever the strip's state needs saying.

        use_property_split and use_property_decorate are what give each row the
        animate dot on the right, which is how a corner gets keyframed by hand
        and how an already-keyed one shows its state. Without them Blender
        draws no decorator column at all, and the values look unanimatable even
        though they are not.
        """
        layout = self.layout
        strip = context.active_strip
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

        # Each corner is drawn as two scalar rows rather than one vector row,
        # so it reads "Bottom Left X" / "Y" the way Blender's own Transform
        # panel reads "Position X" / "Y". The pair is aligned together and the
        # four pairs are not, which is the same grouping Blender uses.
        for socket_name, label in zip(nodes.CORNER_SOCKETS, nodes.CORNER_LABELS):
            socket = node.inputs[socket_name]
            column = layout.column(align=True)
            column.prop(socket, "default_value", index=0, text=label + " X")
            column.prop(socket, "default_value", index=1, text="Y")

        column = layout.column()
        column.prop(node.inputs['Interpolation'], "default_value", text="Interpolation")

        # The handle drag refuses to enter a non-convex shape, but these fields
        # write the sockets directly and nothing can intercept that. Say what
        # happened, because the render gives no clue: a concave quad has no
        # homography, and Blender's solver answers with a blank or garbage
        # frame rather than an error.
        if not space.is_convex_quad(nodes.read_pin(strip)):
            box = layout.box()
            box.label(text="Corners do not form a convex shape", icon='ERROR')
            box.label(text="This cannot be rendered; move a corner back")

        if core.needs_headroom(strip):
            box = layout.box()
            box.label(text="Corners are at the image edge", icon='INFO')
            box.operator(SEQUENCER_OT_perspective_add_headroom.bl_idname,
                         text="Add Headroom")

        row = layout.row(align=True)
        row.operator(SEQUENCER_OT_perspective_reset.bl_idname, text="Reset")
        row.operator(SEQUENCER_OT_perspective_clear.bl_idname, text="Clear")


classes = (
    SEQUENCER_OT_perspective_activate,
    SEQUENCER_OT_perspective_reset,
    SEQUENCER_OT_perspective_clear,
    SEQUENCER_OT_perspective_add_headroom,
    STRIP_PT_perspective,
)
