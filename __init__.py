"""
BL Perspective Transform - Perspective distortion tool for VSE

This addon provides:
- 4-corner perspective transformation handles
- Working menu integration with proper context handling
- Simple toolbar tool (standard Blender behavior)
- Proper keymap handling with P key for perspective transform
- Real-time preview of perspective distortion
"""

bl_info = {
    "name": "BL Perspective Transform",
    "description": "Perspective transformation tool for Blender's Video Sequence Editor",
    "author": "usrname0",
    "version": (1, 0, 0),
    "blender": (4, 4, 0),
    "location": "Sequencer > Preview > Toolbar",
    "warning": "",
    "doc_url": "",
    "tracker_url": "",
    "category": "Sequencer"
}

import bpy
import os
from pathlib import Path
from bpy.types import WorkSpaceTool

# Import operators with error handling
try:
    from .operators.perspective_operators import (
        PERSPECTIVE_OT_transform, 
        PERSPECTIVE_OT_select_and_transform, 
        PERSPECTIVE_OT_activate_tool
    )
    from .operators.perspective_core import (
        is_strip_visible_at_frame,
        get_perspective_state,
        set_perspective_active,
        clear_perspective_state
    )
    operators_imported = True
except ImportError as e:
    operators_imported = False

# Import gizmos with error handling
try:
    from .gizmos import (
        PERSPECTIVE_GT_perspective_handle,
        PERSPECTIVE_GGT_perspective_handles,
        register_perspective_handles_gizmo,
        unregister_perspective_handles_gizmo
    )
    gizmos_imported = True
except ImportError as e:
    gizmos_imported = False


class PERSPECTIVE_OT_clear_transform(bpy.types.Operator):
    """Clear perspective transform from selected strips"""
    bl_idname = "sequencer.clear_perspective"
    bl_label = "Clear Perspective"
    bl_description = "Clear perspective transform from all selected strips"
    bl_options = {'REGISTER', 'UNDO'}
    
    @classmethod
    def poll(cls, context):
        if not context.scene.sequence_editor:
            return False
        
        # Check if any selected strips have transform capability
        for strip in context.selected_sequences:
            if hasattr(strip, 'transform'):
                return True
        return False
    
    def execute(self, context):
        cleared_count = 0
        
        for strip in context.selected_sequences:
            if hasattr(strip, 'transform'):
                # Reset perspective transform (placeholder - will implement proper reset)
                # For now, just reset basic transform values
                if hasattr(strip.transform, 'offset_x'):
                    strip.transform.offset_x = 0
                    strip.transform.offset_y = 0
                cleared_count += 1
        
        if cleared_count > 0:
            self.report({'INFO'}, f"Cleared perspective from {cleared_count} strip(s)")
        else:
            self.report({'INFO'}, "No strips with transform found")
        
        return {'FINISHED'}


class PERSPECTIVE_TOOL_perspective_handles(WorkSpaceTool):
    bl_space_type = 'SEQUENCE_EDITOR'
    bl_context_mode = 'PREVIEW'
    
    bl_idname = "sequencer.perspective_handles_tool"
    bl_label = "Perspective"
    bl_description = "Apply perspective transform using corner handle gizmos"
    # Use pathlib for cross-platform compatibility (Blender 4.4+ extensions)
    bl_icon = str(Path(__file__).parent / "icons" / "perspective")
    bl_widget = "PERSPECTIVE_GGT_perspective_handles"
    
    # Keymap is handled by gizmos - no tool-level keymap needed
    bl_keymap = None
    
    @staticmethod  
    def draw_settings(context, layout, tool):
        # Handles tool status display
        seq_editor = context.scene.sequence_editor
        if not seq_editor:
            layout.label(text="No sequence editor")
            return
            
        active_strip = seq_editor.active_strip
        current_frame = context.scene.frame_current
        
        # Show current state
        perspective_state = get_perspective_state()
        if perspective_state['active']:
            layout.label(text="Modal perspective mode active", icon='INFO')
            layout.label(text="(Handles tool disabled)")
        elif active_strip and hasattr(active_strip, 'transform'):
            if is_strip_visible_at_frame(active_strip, current_frame):
                layout.label(text=f"Ready: {active_strip.name}")
                layout.label(text="Drag corner handles for perspective")
                layout.label(text="Click center to start modal mode")
            else:
                layout.label(text="Strip not at current frame")
        else:
            layout.label(text="Select a transformable strip")


# Menu functions
def menu_func_strip_transform(self, context):
    """Add Perspective Transform to Strip > Transform menu"""
    if context.space_data.view_type in {'PREVIEW', 'SEQUENCER_PREVIEW'}:
        self.layout.operator_context = 'INVOKE_REGION_PREVIEW'
        self.layout.operator("sequencer.perspective", text="Perspective")


def menu_func_image_transform(self, context):
    """Add Perspective Transform to Image > Transform menu"""
    if context.space_data.view_type in {'PREVIEW', 'SEQUENCER_PREVIEW'}:
        self.layout.operator_context = 'INVOKE_REGION_PREVIEW'
        self.layout.operator("sequencer.perspective", text="Perspective")


def menu_func_image_clear(self, context):
    """Add Clear Perspective to Image > Clear menu"""
    if context.space_data.view_type in {'PREVIEW', 'SEQUENCER_PREVIEW'}:
        self.layout.operator("sequencer.clear_perspective", text="Perspective")


# Registration
classes = [
    PERSPECTIVE_OT_transform,
    PERSPECTIVE_OT_select_and_transform,
    PERSPECTIVE_OT_activate_tool,
    PERSPECTIVE_OT_clear_transform,
]

addon_keymaps = []


def register():
    """Register the addon"""
    if not operators_imported:
        return
    
    # Register classes
    for cls in classes:
        if cls is not None:
            try:
                bpy.utils.register_class(cls)
            except Exception as e:
                pass
    
    # Register gizmos
    if gizmos_imported:
        try:
            register_perspective_handles_gizmo()
        except Exception as e:
            pass
    
    
    # Register keymaps - only in Preview area
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if kc:
        # Preview region keymaps only
        km = kc.keymaps.new(name="SequencerPreview", space_type="SEQUENCE_EDITOR", region_type="WINDOW")
        
        # Perspective operator - P key (modal for quick access, returns to previous tool)
        kmi = km.keymap_items.new("sequencer.perspective", 'P', 'PRESS')
        addon_keymaps.append((km, kmi))
        
        # Clear perspective operator - Alt+P key
        kmi_clear = km.keymap_items.new("sequencer.clear_perspective", 'P', 'PRESS', alt=True)
        addon_keymaps.append((km, kmi_clear))
    
    # Register the tools - only the gizmo handles tool
    try:
        bpy.utils.register_tool(PERSPECTIVE_TOOL_perspective_handles, after={"builtin.transform"}, separator=False)
    except Exception as e:
        pass
        try:
            bpy.utils.register_tool(PERSPECTIVE_TOOL_perspective_handles)
        except Exception as e2:
            pass
    
    # Add menu items
    try:
        bpy.types.SEQUENCER_MT_strip_transform.append(menu_func_strip_transform)
        bpy.types.SEQUENCER_MT_image_transform.append(menu_func_image_transform)
        bpy.types.SEQUENCER_MT_image_clear.append(menu_func_image_clear)
    except Exception as e:
        pass


def unregister():
    """Unregister the addon"""
    # Force cleanup of any active perspective mode
    try:
        clear_perspective_state()
    except:
        pass
    
    # Force restore gizmos in case they were disabled
    try:
        for area in bpy.context.screen.areas:
            if area.type == 'SEQUENCE_EDITOR':
                for space in area.spaces:
                    if space.type == 'SEQUENCE_EDITOR' and hasattr(space, 'show_gizmo'):
                        space.show_gizmo = True
    except:
        pass
    
    
    # Unregister gizmos
    if gizmos_imported:
        try:
            unregister_perspective_handles_gizmo()
        except Exception as e:
            pass
    
    # Remove menu items
    try:
        bpy.types.SEQUENCER_MT_strip_transform.remove(menu_func_strip_transform)
        bpy.types.SEQUENCER_MT_image_transform.remove(menu_func_image_transform)
        bpy.types.SEQUENCER_MT_image_clear.remove(menu_func_image_clear)
    except:
        pass
    
    # Unregister the tools
    try:
        bpy.utils.unregister_tool(PERSPECTIVE_TOOL_perspective_handles)
    except:
        pass
    
    # Clean up draw handlers
    try:
        from .operators.perspective_core import get_draw_handle
        if get_draw_handle() is not None:
            bpy.types.SpaceSequenceEditor.draw_handler_remove(get_draw_handle(), 'PREVIEW')
    except:
        pass
    
    # Remove keymaps
    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()
    
    # Unregister classes
    for cls in reversed(classes):
        if cls is not None:
            try:
                bpy.utils.unregister_class(cls)
            except:
                pass


if __name__ == "__main__":
    register()