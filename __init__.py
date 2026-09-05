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

from .gizmos import (register_perspective_handles_gizmo,
                     unregister_perspective_handles_gizmo)
from .operators.perspective_defaults import (register_perspective_defaults,
                                             unregister_perspective_defaults)
from .operators.perspective_operators import classes as operator_classes

TOOL_IDNAME = "sequencer.perspective_handles_tool"

addon_keymaps = []


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
        # Menu.append() restores the default operator context after every
        # appended function, so the menu's own INVOKE_REGION_PREVIEW is gone
        # by the time this runs. Without it the shortcut lookup asks the
        # timeline region, finds nothing, and the entry draws without its "P".
        self.layout.operator_context = 'INVOKE_REGION_PREVIEW'
        self.layout.operator("sequencer.perspective_activate", text="Perspective")


def _menu_clear(self, context):
    """Add the clear operator to the preview Clear menu."""
    if context.space_data.view_type in {'PREVIEW', 'SEQUENCER_PREVIEW'}:
        # Same reason as _menu_transform: this is what shows the "Alt P".
        self.layout.operator_context = 'INVOKE_REGION_PREVIEW'
        self.layout.operator("sequencer.perspective_clear", text="Perspective")


_MENUS = (
    ("SEQUENCER_MT_strip_transform", _menu_transform),
    ("SEQUENCER_MT_image_transform", _menu_transform),
    ("SEQUENCER_MT_image_clear", _menu_clear),
)


def register():
    """Register operators, gizmos, the toolbar tool and keymaps."""
    # Before the panel, which draws these whenever a strip has no transform yet.
    register_perspective_defaults()

    for cls in operator_classes:
        bpy.utils.register_class(cls)

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

    for cls in reversed(operator_classes):
        bpy.utils.unregister_class(cls)

    unregister_perspective_defaults()
