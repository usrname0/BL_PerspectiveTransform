"""
BL Perspective Transform - Corner-pin perspective for the Blender VSE.

Drag the four corners of a strip in the preview to distort it, and have that
distortion render. The transform is stored as a Corner Pin node inside a
compositor strip modifier, so Blender evaluates it as part of the normal strip
pipeline rather than this addon painting a preview-only overlay.

Requires Blender 5.0 or newer, which is where compositor strip modifiers were
added.
"""

import bpy
from bpy.types import WorkSpaceTool
from pathlib import Path

from .gizmos import (PERSPECTIVE_GGT_perspective_handles,
                     PERSPECTIVE_GT_perspective_handle,
                     register_perspective_handles_gizmo,
                     unregister_perspective_handles_gizmo)
from .operators.perspective_operators import classes as operator_classes

bl_info = {
    "name": "BL Perspective Transform",
    "description": "Corner-pin perspective transforms for Blender's Video Sequence Editor",
    "author": "usrname0",
    "version": (2, 0, 0),
    "blender": (5, 0, 0),
    "location": "Sequencer > Preview > Toolbar",
    "category": "Sequencer",
}

TOOL_IDNAME = "sequencer.perspective_handles_tool"

addon_keymaps = []

# Perspective belongs directly beneath Crop, next to the other strip
# transforms. Panels are ordered by bl_order, and every stock strip panel
# leaves it at the default 0, so ties fall to registration order and anything
# an addon registers lands at the bottom of the block. A panel cannot ask to
# sit in the middle of that; the only lever is to push the stock panels that
# should follow ours to a higher bl_order. bl_order is read into the C
# PanelType at registration, so they have to be re-registered for it to count.
#
# [measured] 5.2.1: re-registering a panel that a third-party sub-panel is
# parented to does not orphan the child - bl_parent_id resolves by name at draw
# time - and the panels come back with their state intact.
#
# The one limitation, also measured: a Properties region bakes panel order into
# itself when it first builds the list, so this only lands if it runs before
# the Strip tab has been drawn. That is the normal case, since extensions
# register at startup; enabling the addon by hand while that tab is open leaves
# Perspective at the bottom until Blender restarts.
PANELS_AFTER_PERSPECTIVE = (
    "STRIP_PT_adjust_video",
    "STRIP_PT_adjust_color",
    "STRIP_PT_adjust_sound",
    "STRIP_PT_time",
    "STRIP_PT_source",
)

# Above our panel's default 0 and below STRIP_PT_custom_props, which Blender
# already pins to 1000 so Custom Properties stays last.
PANEL_ORDER_AFTER = 10

# (class, original bl_order or None if the class did not define one), so
# unregister can put Blender's UI back exactly as it found it.
_reordered_panels = []


def _order_panels_after_perspective():
    """Push the stock strip panels that belong below ours to a higher bl_order."""
    for name in PANELS_AFTER_PERSPECTIVE:
        cls = getattr(bpy.types, name, None)
        if cls is None:
            continue  # a future Blender renamed or dropped it; order is cosmetic
        original = cls.__dict__.get("bl_order")
        try:
            bpy.utils.unregister_class(cls)
            cls.bl_order = PANEL_ORDER_AFTER
            bpy.utils.register_class(cls)
        except (RuntimeError, ValueError):
            continue
        _reordered_panels.append((cls, original))


def _restore_panel_order():
    """Undo _order_panels_after_perspective, leaving Blender's UI as found."""
    for cls, original in reversed(_reordered_panels):
        try:
            bpy.utils.unregister_class(cls)
            if original is None:
                del cls.bl_order
            else:
                cls.bl_order = original
            bpy.utils.register_class(cls)
        except (RuntimeError, ValueError, AttributeError):
            continue
    _reordered_panels.clear()


class PERSPECTIVE_TOOL_perspective_handles(WorkSpaceTool):
    """Preview toolbar entry that shows the four corner handles."""

    bl_space_type = 'SEQUENCE_EDITOR'
    bl_context_mode = 'PREVIEW'

    bl_idname = TOOL_IDNAME
    bl_label = "Perspective"
    bl_description = "Distort a strip by dragging its corner handles"
    bl_icon = str(Path(__file__).parent / "icons" / "perspective")
    bl_widget = "PERSPECTIVE_GGT_perspective_handles"
    bl_keymap = None

    @staticmethod
    def draw_settings(context, layout, tool):
        """Show what the tool will act on."""
        from .operators import perspective_core as core
        from .operators import perspective_nodes as nodes

        strip = nodes.get_active_strip(context)
        if strip is None or not hasattr(strip, "transform"):
            layout.label(text="Select a transformable strip")
            return

        scene = nodes.get_sequencer_scene(context)
        if not core.is_strip_visible_at_frame(strip, scene.frame_current):
            layout.label(text="Strip is not visible at this frame")
            return

        layout.label(text=strip.name)
        if nodes.has_perspective(strip):
            layout.operator("sequencer.perspective_reset", text="Reset")
        else:
            layout.label(text="Drag a corner to begin")


def _menu_transform(self, context):
    """Add the tool to the preview Transform menus."""
    if context.space_data.view_type in {'PREVIEW', 'SEQUENCER_PREVIEW'}:
        self.layout.operator("sequencer.perspective_activate", text="Perspective")


def _menu_clear(self, context):
    """Add the clear operator to the preview Clear menu."""
    if context.space_data.view_type in {'PREVIEW', 'SEQUENCER_PREVIEW'}:
        self.layout.operator("sequencer.perspective_clear", text="Perspective")


_MENUS = (
    ("SEQUENCER_MT_strip_transform", _menu_transform),
    ("SEQUENCER_MT_image_transform", _menu_transform),
    ("SEQUENCER_MT_image_clear", _menu_clear),
)


def register():
    """Register operators, gizmos, the toolbar tool and keymaps."""
    for cls in operator_classes:
        bpy.utils.register_class(cls)

    _order_panels_after_perspective()

    register_perspective_handles_gizmo()

    keyconfig = bpy.context.window_manager.keyconfigs.addon
    if keyconfig:
        # The VSE preview keymap was renamed "SequencerPreview" -> "Preview" in
        # Blender 4.5. This addon requires 5.0+, so only the new name applies.
        keymap = keyconfig.keymaps.new(name="Preview",
                                       space_type="SEQUENCE_EDITOR",
                                       region_type="WINDOW")
        addon_keymaps.append(
            (keymap, keymap.keymap_items.new("sequencer.perspective_activate", 'P', 'PRESS')))
        addon_keymaps.append(
            (keymap, keymap.keymap_items.new("sequencer.perspective_clear", 'P', 'PRESS', alt=True)))

    bpy.utils.register_tool(PERSPECTIVE_TOOL_perspective_handles,
                            after={"builtin.transform"}, separator=False)

    for menu_name, func in _MENUS:
        menu = getattr(bpy.types, menu_name, None)
        if menu is not None:
            menu.append(func)


def unregister():
    """Undo everything register() did, in reverse order."""
    for menu_name, func in reversed(_MENUS):
        menu = getattr(bpy.types, menu_name, None)
        if menu is not None:
            menu.remove(func)

    bpy.utils.unregister_tool(PERSPECTIVE_TOOL_perspective_handles)

    for keymap, item in addon_keymaps:
        keymap.keymap_items.remove(item)
    addon_keymaps.clear()

    unregister_perspective_handles_gizmo()

    _restore_panel_order()

    for cls in reversed(operator_classes):
        bpy.utils.unregister_class(cls)
