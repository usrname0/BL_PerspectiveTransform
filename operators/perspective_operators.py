"""
BL Perspective Transform - Operators

This module contains the main operators for the perspective transform functionality,
including the primary perspective operator and helper operators for tool activation.
"""

import bpy
import math
from mathutils import Vector

from .perspective_core import (
    get_perspective_state, set_perspective_active, get_draw_data, set_draw_data,
    get_draw_handle, set_draw_handle, clear_perspective_state,
    get_strip_geometry_with_flip_support, is_strip_visible_at_frame, point_in_polygon
)
from .perspective_drawing import draw_perspective_handles


class PERSPECTIVE_OT_transform(bpy.types.Operator):
    """Apply perspective transform to strips in the preview window"""
    bl_idname = "sequencer.perspective"
    bl_label = "Perspective Transform"
    bl_description = "Apply perspective transform to a strip in the Image Preview"
    bl_options = {'REGISTER', 'UNDO'}
    
    @classmethod
    def poll(cls, context):
        scene = context.scene
        if not scene.sequence_editor:
            return False
        
        # Check if we're in preview mode
        space = context.space_data
        if space and space.type == 'SEQUENCE_EDITOR':
            if space.view_type not in {'PREVIEW', 'SEQUENCER_PREVIEW'}:
                return False
        
        # Check for transformable strips (any strip with transform property)
        if scene.sequence_editor.active_strip and hasattr(scene.sequence_editor.active_strip, 'transform'):
            return True
        
        for strip in context.selected_sequences:
            if hasattr(strip, 'transform'):
                return True
                
        return False
    
    def invoke(self, context, event):
        perspective_state = get_perspective_state()
        
        # If perspective transform is already active, don't start a new operation
        if perspective_state['active']:
            self.report({'WARNING'}, "Perspective transform mode already active")
            return {'CANCELLED'}
        
        strip = context.scene.sequence_editor.active_strip
        current_frame = context.scene.frame_current
        
        # Check if we have a suitable active strip that's visible
        has_suitable_active = (strip and 
                              hasattr(strip, 'transform') and 
                              is_strip_visible_at_frame(strip, current_frame))
        
        # If we have a suitable active strip, use it directly (no mouse click needed)
        if has_suitable_active:
            # This is the key change - we proceed directly without requiring a click
            pass
        else:
            # If no suitable active strip, try to find one under the mouse
            mouse_pos = Vector((event.mouse_region_x, event.mouse_region_y))
            strips = self._get_visible_strips(context)
            clicked_strip = None
            
            # Check from top to bottom for a transformable strip
            for s in strips:
                if hasattr(s, 'transform') and self._is_mouse_over_strip(context, s, mouse_pos):
                    clicked_strip = s
                    break
            
            if clicked_strip:
                # Select the clicked strip and make it active
                if not event.shift:
                    bpy.ops.sequencer.select_all(action='DESELECT')
                clicked_strip.select = True
                context.scene.sequence_editor.active_strip = clicked_strip
                strip = clicked_strip
                has_suitable_active = True
            else:
                self.report({'INFO'}, "No transformable strip found - select an image/movie strip")
                return {'CANCELLED'}
        
        if not has_suitable_active:
            self.report({'INFO'}, "No suitable strip for perspective transform")
            return {'CANCELLED'}
        
        # Initialize operator state
        self.active_corner = -1
        self.mouse_start = (0.0, 0.0)
        self.transform_start = None  # Will store initial corner positions
        self.timer = None
        
        # Store the current transform overlay state
        self.prev_show_gizmo = None
        if hasattr(context.space_data, 'show_gizmo'):
            self.prev_show_gizmo = context.space_data.show_gizmo
            context.space_data.show_gizmo = False
        
        # Clean up any existing handler
        if get_draw_handle() is not None:
            try:
                bpy.types.SpaceSequenceEditor.draw_handler_remove(get_draw_handle(), 'PREVIEW')
            except:
                pass
            set_draw_handle(None)
        
        # Mark perspective as active
        set_perspective_active(True)
        
        # Initialize draw data
        set_draw_data({'active_corner': -1, 'frame_count': 0})
        
        # Store initial perspective state (placeholder - will implement proper perspective storage)
        self.transform_start = self._get_current_perspective_state(strip)
        
        # Set up drawing handler
        handler = bpy.types.SpaceSequenceEditor.draw_handler_add(
            draw_perspective_handles, (), 'PREVIEW', 'POST_PIXEL')
        set_draw_handle(handler)
        
        # Force redraw
        context.area.tag_redraw()
        
        # Add timer for redraws
        wm = context.window_manager
        self.timer = wm.event_timer_add(0.01, window=context.window)
        
        # Add modal handler
        wm.modal_handler_add(self)
        
        return {'RUNNING_MODAL'}
    
    def modal(self, context, event):
        draw_data = get_draw_data()
        
        # Store current mouse position for hover detection
        if hasattr(event, 'mouse_region_x') and hasattr(event, 'mouse_region_y'):
            draw_data['mouse_x'] = event.mouse_region_x
            draw_data['mouse_y'] = event.mouse_region_y
            set_draw_data(draw_data)
        
        # Handle timer events
        if event.type == 'TIMER':
            for area in context.screen.areas:
                if area.type == 'SEQUENCE_EDITOR':
                    area.tag_redraw()
            return {'RUNNING_MODAL'}
        
        strip = context.scene.sequence_editor.active_strip
        if not strip:
            return self.finish(context)
        
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            # Check if clicking on a corner handle (perspective only uses 4 corners)
            corner = self._get_corner_at_mouse(context, event)
            
            if corner >= 0 and corner < 4:  # Only corner handles for perspective
                self.active_corner = corner
                draw_data['active_corner'] = corner
                set_draw_data(draw_data)
                self.mouse_start = (event.mouse_region_x, event.mouse_region_y)
                
                # Store current perspective state for this drag
                self.transform_start = self._get_current_perspective_state(strip)
            else:
                # Check if clicking on another strip
                mouse_pos = Vector((event.mouse_region_x, event.mouse_region_y))
                strips = self._get_visible_strips(context)
                clicked_strip = None
                
                # Check from top to bottom
                for s in strips:
                    if self._is_mouse_over_strip(context, s, mouse_pos):
                        clicked_strip = s
                        break
                
                if clicked_strip and clicked_strip != strip:
                    # Switch to different strip
                    self.finish(context)
                    if not event.shift:
                        bpy.ops.sequencer.select_all(action='DESELECT')
                    clicked_strip.select = True
                    context.scene.sequence_editor.active_strip = clicked_strip
                    if hasattr(clicked_strip, 'transform'):
                        bpy.ops.sequencer.perspective('INVOKE_DEFAULT')
                    return {'FINISHED'}
                else:
                    # Exit perspective mode
                    return self.finish(context)
        
        elif event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            if self.active_corner >= 0:
                pass  # Handle release silently
            self.active_corner = -1
            draw_data['active_corner'] = -1
            set_draw_data(draw_data)
        
        elif event.type == 'MOUSEMOVE' and self.active_corner >= 0:
            self._update_perspective(context, event)
            for area in context.screen.areas:
                if area.type == 'SEQUENCE_EDITOR':
                    area.tag_redraw()
            return {'RUNNING_MODAL'}
        
        elif event.type in {'RET', 'NUMPAD_ENTER'}:
            return self.finish(context)
        
        elif event.type == 'ESC':
            # Restore original perspective state
            self._restore_perspective_state(strip, self.transform_start)
            return self.finish(context, cancelled=True)
        
        elif event.type == 'P' and event.alt and event.value == 'PRESS':
            # Clear perspective with Alt+P while in perspective mode
            self._clear_perspective_transform(strip)
            self.transform_start = self._get_current_perspective_state(strip)
            # Force redraw to show the change immediately
            for area in context.screen.areas:
                if area.type == 'SEQUENCE_EDITOR':
                    area.tag_redraw()
            return {'RUNNING_MODAL'}
        
        elif self._is_transform_key(context, event):
            # Exit perspective mode and activate the transform
            transform_op = self._get_transform_operator(context, event)
            if transform_op:
                self.finish(context)
                operator_parts = transform_op.split('.')
                if len(operator_parts) == 2:
                    category, name = operator_parts
                    try:
                        op = getattr(getattr(bpy.ops, category), name)
                        op('INVOKE_DEFAULT')
                    except AttributeError:
                        pass
            return {'FINISHED'}
        
        elif event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            return {'PASS_THROUGH'}
        
        return {'RUNNING_MODAL'}
    
    def finish(self, context, cancelled=False):
        """Clean up and exit"""
        # Clear the active flag
        set_perspective_active(False)
        
        # Restore transform gizmo visibility
        if hasattr(self, 'prev_show_gizmo') and self.prev_show_gizmo is not None and hasattr(context.space_data, 'show_gizmo'):
            context.space_data.show_gizmo = self.prev_show_gizmo
        
        # Remove timer
        if hasattr(self, 'timer') and self.timer:
            try:
                context.window_manager.event_timer_remove(self.timer)
            except:
                pass
            self.timer = None
        
        # Remove draw handler
        if get_draw_handle() is not None:
            try:
                bpy.types.SpaceSequenceEditor.draw_handler_remove(get_draw_handle(), 'PREVIEW')
            except:
                pass
            set_draw_handle(None)
        
        # Clear all state
        clear_perspective_state()
        
        # Reset operator state
        self.active_corner = -1
        
        # Force redraw
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'SEQUENCE_EDITOR':
                    for region in area.regions:
                        region.tag_redraw()
        
        return {'CANCELLED'} if cancelled else {'FINISHED'}
    
    def _get_corner_at_mouse(self, context, event):
        """Check if mouse is over a corner handle (perspective only uses 4 corners)"""
        mouse_pos = Vector((event.mouse_region_x, event.mouse_region_y))
        corners = self._get_perspective_corners(context)
        
        # Check corner handles only (0-3) - no edge handles for perspective
        for i, corner in enumerate(corners):
            if (corner - mouse_pos).length < 10:
                return i
        
        return -1
    
    def _get_perspective_corners(self, context):
        """Get the corner positions in screen space for perspective handles"""
        strip = context.scene.sequence_editor.active_strip
        scene = context.scene
        if not strip or not context.region:
            return []
        
        corners, (pivot_x, pivot_y), (scale_x, scale_y, flip_x, flip_y) = get_strip_geometry_with_flip_support(strip, scene)
        
        # Transform to screen coordinates
        view2d = context.region.view2d
        res_x = scene.render.resolution_x
        res_y = scene.render.resolution_y
        
        screen_corners = []
        for corner in corners:
            view_x = corner.x - res_x / 2
            view_y = corner.y - res_y / 2
            screen_co = view2d.view_to_region(view_x, view_y, clip=False)
            screen_corners.append(Vector(screen_co))
        
        return screen_corners
    
    def cancel(self, context):
        """Called when operator is cancelled by Blender"""
        return self.finish(context, cancelled=True)
    
    def _get_current_perspective_state(self, strip):
        """Get current perspective state (placeholder - will implement proper perspective storage)"""
        # For now, just store basic transform values
        return {
            'offset_x': getattr(strip.transform, 'offset_x', 0),
            'offset_y': getattr(strip.transform, 'offset_y', 0),
            'scale_x': getattr(strip.transform, 'scale_x', 1),
            'scale_y': getattr(strip.transform, 'scale_y', 1),
            'rotation': getattr(strip.transform, 'rotation', 0)
        }
    
    def _restore_perspective_state(self, strip, state):
        """Restore perspective state (placeholder - will implement proper perspective restoration)"""
        if state and hasattr(strip, 'transform'):
            strip.transform.offset_x = state.get('offset_x', 0)
            strip.transform.offset_y = state.get('offset_y', 0)
            strip.transform.scale_x = state.get('scale_x', 1)
            strip.transform.scale_y = state.get('scale_y', 1)
            strip.transform.rotation = state.get('rotation', 0)
    
    def _clear_perspective_transform(self, strip):
        """Clear perspective transform"""
        from .perspective_core import clear_perspective_matrix_from_strip
        
        # Clear stored perspective matrix
        clear_perspective_matrix_from_strip(strip)
        
        # Reset basic transform properties
        if hasattr(strip, 'transform'):
            strip.transform.offset_x = 0
            strip.transform.offset_y = 0
            strip.transform.scale_x = 1
            strip.transform.scale_y = 1
            strip.transform.rotation = 0
    
    def _update_perspective(self, context, event):
        """Update perspective transform based on mouse drag - now with real homography calculation"""
        strip = context.scene.sequence_editor.active_strip
        scene = context.scene
        
        if not strip or not hasattr(strip, 'transform'):
            return
        
        # Get current mouse position in view coordinates
        view2d = context.region.view2d
        mouse_view_pos = view2d.region_to_view(event.mouse_region_x, event.mouse_region_y)
        
        # Get effective corners for perspective calculation (respects existing transforms)
        from .perspective_core import get_effective_corners_for_perspective, store_original_corners_in_strip
        original_corners = get_effective_corners_for_perspective(strip, scene)
        
        # Store original corners on first transform if not already stored  
        if not hasattr(self, '_stored_original') or not self._stored_original:
            store_original_corners_in_strip(strip, original_corners)
            self._stored_original = True
        
        # Create destination corners by modifying the dragged corner
        dst_corners = [Vector(corner) for corner in original_corners]  # Copy original corners
        
        if self.active_corner >= 0 and self.active_corner < 4:
            # Convert mouse position to strip coordinate space
            res_x = scene.render.resolution_x
            res_y = scene.render.resolution_y
            
            # Convert view coordinates to strip coordinates
            strip_mouse_x = mouse_view_pos[0] + res_x / 2
            strip_mouse_y = mouse_view_pos[1] + res_y / 2
            
            # Update the dragged corner position
            dst_corners[self.active_corner] = Vector([strip_mouse_x, strip_mouse_y])
            
            # Calculate homography matrix from original to new positions
            from .perspective_math import calculate_homography_matrix, decompose_homography_to_transform_properties
            
            try:
                homography = calculate_homography_matrix(original_corners, dst_corners)
                
                # Store the homography matrix in the strip for rendering
                from .perspective_core import store_perspective_matrix_in_strip
                store_perspective_matrix_in_strip(strip, homography)
                
                # NOTE: We don't apply basic transform approximation because:
                # 1. It constrains the image to rectangles (scale/rotate only)  
                # 2. True perspective transformation requires custom rendering
                # 3. For now, handles move freely and matrix is stored for future rendering
                # TODO: Implement perspective transformation in Blender's rendering pipeline
                
            except Exception as e:
                print(f"Warning: Homography calculation failed: {e}")
                # Fall back to basic corner-based transform
                self._apply_basic_corner_transform(strip, self.active_corner, mouse_view_pos)
    
    def _apply_basic_corner_transform(self, strip, corner, mouse_view_pos):
        """Fallback basic transform when homography calculation fails"""
        # Simple approximation - just modify basic transform properties
        dx = mouse_view_pos[0] * 0.001
        dy = mouse_view_pos[1] * 0.001
        
        if corner == 0:  # Bottom-left
            strip.transform.offset_x = self.transform_start['offset_x'] + dx
            strip.transform.offset_y = self.transform_start['offset_y'] + dy
        elif corner == 1:  # Bottom-right
            strip.transform.scale_x = max(0.1, self.transform_start['scale_x'] + dx)
        elif corner == 2:  # Top-right
            strip.transform.scale_x = max(0.1, self.transform_start['scale_x'] + dx)
            strip.transform.scale_y = max(0.1, self.transform_start['scale_y'] + dy)
        elif corner == 3:  # Top-left
            strip.transform.offset_y = self.transform_start['offset_y'] + dy
    
    def _is_transform_key(self, context, event):
        """Check if the pressed key is bound to a transform operator"""
        if event.value != 'PRESS':
            return False
        
        wm = context.window_manager
        kc_user = wm.keyconfigs.user
        kc_active = wm.keyconfigs.active
        
        transform_ops = ['transform.translate', 'transform.resize', 'transform.rotate']
        
        keyconfigs_to_check = [kc_user, kc_active]
        
        for kc in keyconfigs_to_check:
            keymaps_to_check = []
            
            preview_km = kc.keymaps.find('SequencerPreview', space_type='SEQUENCE_EDITOR', region_type='WINDOW')
            if preview_km:
                keymaps_to_check.append(preview_km)
            
            sequencer_km = kc.keymaps.find('Sequencer', space_type='SEQUENCE_EDITOR', region_type='WINDOW')
            if sequencer_km:
                keymaps_to_check.append(sequencer_km)
            
            window_km = kc.keymaps.find('Window', space_type='EMPTY', region_type='WINDOW')
            if window_km:
                keymaps_to_check.append(window_km)
            
            for km in keymaps_to_check:
                for kmi in km.keymap_items:
                    if (kmi.active and 
                        kmi.idname in transform_ops and
                        kmi.type == event.type and 
                        kmi.shift == event.shift and
                        kmi.ctrl == event.ctrl and
                        kmi.alt == event.alt and
                        kmi.oskey == event.oskey):
                        return True
        
        return False
    
    def _get_transform_operator(self, context, event):
        """Get which transform operator is bound to the pressed key"""
        wm = context.window_manager
        kc_user = wm.keyconfigs.user
        kc_active = wm.keyconfigs.active
        
        transform_ops = ['transform.translate', 'transform.resize', 'transform.rotate']
        
        keyconfigs_to_check = [kc_user, kc_active]
        
        for kc in keyconfigs_to_check:
            keymaps_to_check = []
            
            preview_km = kc.keymaps.find('SequencerPreview', space_type='SEQUENCE_EDITOR', region_type='WINDOW')
            if preview_km:
                keymaps_to_check.append(preview_km)
            
            sequencer_km = kc.keymaps.find('Sequencer', space_type='SEQUENCE_EDITOR', region_type='WINDOW')
            if sequencer_km:
                keymaps_to_check.append(sequencer_km)
            
            window_km = kc.keymaps.find('Window', space_type='EMPTY', region_type='WINDOW')
            if window_km:
                keymaps_to_check.append(window_km)
            
            for km in keymaps_to_check:
                for kmi in km.keymap_items:
                    if (kmi.active and 
                        kmi.idname in transform_ops and
                        kmi.type == event.type and 
                        kmi.shift == event.shift and
                        kmi.ctrl == event.ctrl and
                        kmi.alt == event.alt and
                        kmi.oskey == event.oskey):
                        return kmi.idname
        
        return None
    
    def _get_visible_strips(self, context):
        """Get all strips visible at the current frame, sorted top to bottom"""
        scene = context.scene
        if not scene.sequence_editor:
            return []
        
        current_frame = scene.frame_current
        strips = []
        
        for strip in scene.sequence_editor.sequences:
            if is_strip_visible_at_frame(strip, current_frame):
                strips.append(strip)
        
        # Sort by channel (higher channels on top), then reverse for top-to-bottom checking
        strips.sort(key=lambda s: s.channel, reverse=True)
        return strips
    
    def _is_mouse_over_strip(self, context, strip, mouse_pos):
        """Check if mouse is over the given strip with flip support"""
        scene = context.scene
        corners, (pivot_x, pivot_y), (scale_x, scale_y, flip_x, flip_y) = get_strip_geometry_with_flip_support(strip, scene)
        
        # Convert to screen space
        view2d = context.region.view2d
        res_x = scene.render.resolution_x
        res_y = scene.render.resolution_y
        
        screen_corners = []
        for corner in corners:
            view_x = corner.x - res_x / 2
            view_y = corner.y - res_y / 2
            screen_co = view2d.view_to_region(view_x, view_y, clip=False)
            screen_corners.append(Vector(screen_co))
        
        return point_in_polygon(mouse_pos, screen_corners)


class PERSPECTIVE_OT_activate_tool(bpy.types.Operator):
    """Activate perspective tool - direct activation like built-in transforms"""
    bl_idname = "sequencer.activate_perspective_tool"
    bl_label = "Activate Perspective Tool"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}
    
    @classmethod
    def poll(cls, context):
        return (context.scene.sequence_editor is not None and
                context.space_data and 
                context.space_data.type == 'SEQUENCE_EDITOR' and
                context.space_data.view_type in {'PREVIEW', 'SEQUENCER_PREVIEW'})
    
    def invoke(self, context, event):
        # Immediately activate the perspective operator - let it handle strip selection
        return bpy.ops.sequencer.perspective('INVOKE_DEFAULT')


class PERSPECTIVE_OT_select_and_transform(bpy.types.Operator):
    """Select strip and activate perspective mode"""
    bl_idname = "sequencer.select_and_perspective"
    bl_label = "Select and Transform"
    bl_description = "Select a strip in the preview and activate perspective mode"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}
    
    @classmethod
    def poll(cls, context):
        return (context.scene.sequence_editor is not None and
                context.space_data and 
                context.space_data.type == 'SEQUENCE_EDITOR' and
                context.space_data.view_type in {'PREVIEW', 'SEQUENCER_PREVIEW'})
    
    def invoke(self, context, event):
        # Check if clicking on a strip
        mouse_pos = Vector((event.mouse_region_x, event.mouse_region_y))
        strips = self._get_visible_strips_for_selection(context)
        clicked_strip = None
        
        # Check from top to bottom
        for strip in strips:
            if hasattr(strip, 'transform') and self._is_mouse_over_strip_for_selection(context, strip, mouse_pos):
                clicked_strip = strip
                break
        
        if clicked_strip:
            # Select the strip
            if not event.shift:
                bpy.ops.sequencer.select_all(action='DESELECT')
            
            clicked_strip.select = True
            context.scene.sequence_editor.active_strip = clicked_strip
            
            context.area.tag_redraw()
            
            # Activate perspective mode
            return bpy.ops.sequencer.perspective('INVOKE_DEFAULT')
        else:
            # Check if we have an active strip ready
            seq_editor = context.scene.sequence_editor
            active_strip = seq_editor.active_strip if seq_editor else None
            current_frame = context.scene.frame_current
            
            if (active_strip and 
                hasattr(active_strip, 'transform') and 
                is_strip_visible_at_frame(active_strip, current_frame)):
                
                perspective_state = get_perspective_state()
                if not perspective_state['active']:
                    return bpy.ops.sequencer.perspective('INVOKE_DEFAULT')
        
        return {'FINISHED'}
    
    def _get_visible_strips_for_selection(self, context):
        """Get all strips visible at the current frame for selection, sorted top to bottom"""
        scene = context.scene
        if not scene.sequence_editor:
            return []
        
        current_frame = scene.frame_current
        strips = []
        
        for strip in scene.sequence_editor.sequences:
            if is_strip_visible_at_frame(strip, current_frame):
                strips.append(strip)
        
        # Sort by channel (higher channels on top), then reverse for top-to-bottom checking
        strips.sort(key=lambda s: s.channel, reverse=True)
        return strips
    
    def _is_mouse_over_strip_for_selection(self, context, strip, mouse_pos):
        """Check if mouse is over the given strip for selection"""
        scene = context.scene
        corners, (pivot_x, pivot_y), (scale_x, scale_y, flip_x, flip_y) = get_strip_geometry_with_flip_support(strip, scene)
        
        # Convert to screen space
        view2d = context.region.view2d
        res_x = scene.render.resolution_x
        res_y = scene.render.resolution_y
        
        screen_corners = []
        for corner in corners:
            view_x = corner.x - res_x / 2
            view_y = corner.y - res_y / 2
            screen_co = view2d.view_to_region(view_x, view_y, clip=False)
            screen_corners.append(Vector(screen_co))
        
        return point_in_polygon(mouse_pos, screen_corners)