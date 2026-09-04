"""
BL Perspective Transform - Operators and the strip properties panel.

The corner handles do the actual editing; these operators cover the things a
drag cannot express: resetting the corners, removing the transform, and
repairing a quad that has been typed into a shape no homography can render.
Reset and Clear are reached from the preview - Strip > Transform, Image > Clear,
and the P and Alt P shortcuts - rather than from the panel, because Blender's
own Transform and Crop panels carry no buttons and this one is meant to read
like them. Make Convex is the exception: it is a button in the panel's own
warning box, because that warning is the only thing that ever calls for it.

STRIP_PT_perspective is the numeric view of the same state, and lives in the
Properties editor beneath Blender's own Crop. See the addon's register() for
how it gets placed there, since panel order is not something a panel can ask
for on its own.
"""

import bpy

from . import perspective_anim as anim
from . import perspective_defaults as defaults
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


class SEQUENCER_OT_perspective_make_convex(bpy.types.Operator):
    """Move one corner the shortest distance that makes the shape renderable"""

    bl_idname = "sequencer.perspective_make_convex"
    bl_label = "Make Convex"
    bl_description = ("Move the nearest corner back until the four form a "
                      "convex shape the Corner Pin can render")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        # The active strip, not the selection: this is the button in the
        # panel's warning box, and the warning is about the strip the panel is
        # drawing. read_pin answers identity for a strip with no transform, so
        # the convexity test alone would never fire for one.
        strip = getattr(context, "active_strip", None)
        if strip is None or not nodes.has_perspective(strip):
            return False
        return not space.is_convex_quad(nodes.read_pin(strip))

    def execute(self, context):
        """
        Repair the quad by moving whichever single corner has least to travel.

        Each corner is projected onto the region where it alone would make the
        quad convex, and the results that actually do are compared. Only one
        corner moves: for a simple concave quad exactly one vertex is on the
        wrong side, and projecting any of the other three cannot reach it -
        those candidates come back failing is_convex_quad and are dropped.
        """
        strip = getattr(context, "active_strip", None)
        scene = nodes.get_sequencer_scene(context)
        if strip is None or scene is None:
            self.report({'ERROR'}, "No strip to repair")
            return {'CANCELLED'}

        corners = [tuple(corner) for corner in nodes.read_pin(strip)]
        best = None
        for index in range(4):
            moved = space.constrain_corner(corners, index, corners[index])
            if moved is None:
                continue
            candidate = list(corners)
            candidate[index] = moved
            if not space.is_convex_quad(candidate):
                continue
            travel = ((moved[0] - corners[index][0]) ** 2
                      + (moved[1] - corners[index][1]) ** 2)
            if best is None or travel < best[0]:
                best = (travel, index, moved)

        # Every triple collinear, so no one corner can rescue the quad. The
        # projection could not be made to produce this from a concave shape,
        # but a hand-typed set of four values is not bound by that.
        if best is None:
            self.report({'ERROR'},
                        "No single corner can make this shape convex - "
                        "use Reset Perspective")
            return {'CANCELLED'}

        _travel, index, moved = best
        corners[index] = moved
        nodes.write_pin(strip, scene, corners)

        # The same auto-key the drag does, on the same corner-only basis - and
        # here it is load-bearing rather than consistent. On an animated corner
        # the value being repaired is in a keyframe, so writing only the socket
        # leaves the key holding the concave shape and the fcurve puts it back
        # on the next frame change. The key is the thing that has to change.
        keyed = anim.autokey_corner(strip, scene, index,
                                    getattr(context, "tool_settings", None))
        label = nodes.CORNER_LABELS[index]
        if keyed:
            self.report({'INFO'}, f"Moved {label} to the nearest convex "
                                  f"position, and keyframed it")
        else:
            self.report({'INFO'}, f"Moved {label} to the nearest convex position")
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
        Draw the filter and the four corners, transform or no transform.

        The rows are the same either way. They bind to the Corner Pin sockets
        once the strip has a perspective, and to the WindowManager placeholders
        until then - which is what lets the values sit there at their defaults
        on a strip nobody has touched, the way Transform and Crop do, instead of
        the panel explaining that there is nothing to show. Writing a
        placeholder builds the transform, after which the sockets take over. See
        perspective_defaults.

        use_property_split and use_property_decorate are what give each row the
        animate dot on the right, which is how a corner gets keyframed by hand
        and how an already-keyed one shows its state. Without them Blender draws
        no decorator column at all, and the values look unanimatable even though
        they are not.
        """
        layout = self.layout
        strip = context.active_strip
        modifier = nodes.find_modifier(strip) if strip else None
        node = nodes.get_corner_pin_node(modifier.node_group) if modifier else None

        # The modifier is ours but its node group has been emptied out. Nothing
        # sensible can be drawn, and the placeholders below would write into a
        # group with nowhere to put the value.
        if modifier is not None and node is None:
            layout.label(text="Node group has no Corner Pin node", icon='ERROR')
            return

        layout.use_property_split = True
        layout.use_property_decorate = True
        # Blender's own Transform and Crop panels grey out on a muted strip.
        layout.active = not strip.mute

        # The handover check is what keeps a drag that has just created the
        # transform from being cut off by its own success - see
        # perspective_defaults.HANDOVER_DELAY. The placeholders read the sockets
        # once they exist, so the values on screen are the real ones either way.
        if node is None or defaults.is_handing_over():
            stand_in = defaults.get_defaults(context)
            filter_target, filter_prop = stand_in, "filter"
            corners = [(stand_in, name) for name in defaults.CORNER_PROPS]
        else:
            filter_target, filter_prop = node.inputs[defaults.FILTER_SOCKET], "default_value"
            corners = [(node.inputs[name], "default_value") for name in nodes.CORNER_SOCKETS]

        # Filter leads, as it does in Blender's Transform panel, where it is the
        # row above Position.
        column = layout.column(align=True)
        column.prop(filter_target, filter_prop, text="Filter")

        # Each corner is drawn as two scalar rows rather than one vector row, so
        # it reads "Bottom Left X" / "Y" the way Transform reads "Position X" /
        # "Y". The pair is aligned together and the four pairs are not, which is
        # the same grouping Blender uses.
        for label, (target, prop) in zip(nodes.CORNER_LABELS, corners):
            column = layout.column(align=True)
            column.prop(target, prop, index=0, text=label + " X", slider=True)
            column.prop(target, prop, index=1, text="Y", slider=True)

        # The handle drag refuses to enter a non-convex shape, but these fields
        # write the sockets directly and nothing can intercept that. Say what
        # happened, because the render gives no clue: a concave quad has no
        # homography, and Blender's solver answers with a blank or garbage
        # frame rather than an error.
        if not space.is_convex_quad(nodes.read_pin(strip)):
            box = layout.box()
            box.label(text="Corners do not form a convex shape", icon='ERROR')
            box.label(text="This cannot be rendered; move a corner back")
            # The one path that can still produce a bad shape gets a one-click
            # way out of it, since the guard cannot sit between the slider and
            # the socket. It moves whichever corner has least to travel.
            box.operator(SEQUENCER_OT_perspective_make_convex.bl_idname)


classes = (
    SEQUENCER_OT_perspective_activate,
    SEQUENCER_OT_perspective_reset,
    SEQUENCER_OT_perspective_clear,
    SEQUENCER_OT_perspective_make_convex,
    STRIP_PT_perspective,
)
