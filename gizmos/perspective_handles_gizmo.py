"""
BL Perspective Transform - Perspective Handles Gizmo System

A complete gizmo-based perspective transform system with individual corner handles.
Based on the crop gizmo but simplified for 4-corner perspective distortion.
"""

import bpy
import math
import gpu
from gpu_extras.batch import batch_for_shader
from bpy.types import Gizmo, GizmoGroup
from mathutils import Vector, Matrix

from ..operators.perspective_core import (
    get_perspective_state, is_strip_visible_at_frame, 
    get_strip_geometry_with_flip_support
)


class PERSPECTIVE_GT_perspective_handle(Gizmo):
    """Individual perspective handle gizmo"""
    bl_idname = "PERSPECTIVE_GT_perspective_handle"
    bl_target_properties = ()
    
    def setup(self):
        """Setup the handle gizmo"""
        # Store handle type and index (only corners for perspective)
        self.handle_type = "corner"  # or "center"
        self.handle_index = 0
        
        # CRITICAL: Essential properties for always-visible gizmos
        self.use_draw_modal = True
        self.use_draw_select = True  
        self.use_event_handle_all = True
        
        # Prevent hiding
        self.use_select_background = False
        self.use_grab_cursor = True
        
        # CRITICAL: Set visibility properties explicitly
        self.hide = False  # Explicitly show the gizmo
        self.alpha = 0.8  # Ensure visible transparency
        self.alpha_highlight = 1.0
        
        # Set colors for visibility
        self.color = (1.0, 1.0, 1.0)
        self.color_highlight = (1.0, 0.5, 0.0)
        
        # Set gizmo scale to match modal operator - EasyCrop uses 6.0
        self.scale_basis = 6.0  # Match modal operator handle size
        
        # Set gizmo to be interactive
        self.select_id = 0  # Will be overridden in group setup
    
    def draw_prepare(self, context):
        """Prepare for drawing - ensure gizmo is visible"""
        self.hide = False  # Force visibility
        self.alpha = 0.8 if not self.is_highlight else 1.0
    
    def draw(self, context):
        """Draw the handle gizmo"""
        # Ensure gizmo is not hidden
        self.hide = False
        
        # Set colors based on state
        if self.is_highlight:
            self.color = self.color_highlight
            self.alpha = self.alpha_highlight
        else:
            self.color = (1.0, 1.0, 1.0)
            self.alpha = 0.8
        
        # Use custom GPU drawing with proper highlight colors
        try:
            # Use the color set by the highlight system
            if self.is_highlight:
                color = (*self.color_highlight, self.alpha_highlight)
            else:
                color = (*self.color, self.alpha)
            
            if self.handle_type == "center":
                # Center handle - use custom perspective symbol drawing
                self._draw_perspective_symbol(color)
            elif self.handle_type == "inner_corner":
                # Inner corner handles - white squares (perspective corners)
                self._draw_handle_square(color, context)
                    
        except Exception as e:
            pass
    
    def test_select(self, context, location):
        """Test if mouse location is over this gizmo"""
        # Get gizmo position from matrix
        gizmo_pos = self.matrix_basis.translation
        
        # Calculate distance between mouse and gizmo center
        distance = ((gizmo_pos.x - location[0])**2 + (gizmo_pos.y - location[1])**2)**0.5
        
        # Threshold for selection (25 pixels like EasyCrop)
        threshold = 25
        
        if distance <= threshold:
            return self.select_id
        else:
            return -1
    
    def draw_select(self, context, select_id):
        """Draw during selection/modal operations - keeps handles visible"""
        self._draw_handle_common(context, during_modal=True)
    
    def _draw_handle_common(self, context, during_modal=False):
        """Common drawing logic for both normal and modal states"""
        if self.handle_type == "center":
            # Center symbol (perspective icon) - always white
            color = (1.0, 1.0, 1.0, 0.8)
            if during_modal:
                # Make center slightly more transparent during modal
                color = (1.0, 1.0, 1.0, 0.6)
            self._draw_perspective_symbol(color)
        elif self.handle_type == "inner_corner":
            # Inner handles - white squares (perspective corners)
            try:
                if self.is_highlight or during_modal:
                    square_color = (1.0, 0.5, 0.0, 1.0)  # Orange when highlighted or during modal
                else:
                    square_color = (1.0, 1.0, 1.0, 0.8)  # White normally
                
                self._draw_handle_square(square_color, context)
                
            except Exception as e:
                # Fallback
                color = (1.0, 1.0, 1.0, 0.8)
                self._draw_handle_square(color, context)
    
    def _draw_perspective_symbol(self, color):
        """Draw the perspective symbol (for center handle)"""
        try:
            center_pos = self.matrix_basis.translation
            center_x = center_pos.x
            center_y = center_pos.y
            
            # Symbol dimensions - simple diamond shape
            size = 6
            
            line_shader = gpu.shader.from_builtin('UNIFORM_COLOR')
            gpu.state.line_width_set(1.5)
            line_shader.bind()
            line_shader.uniform_float("color", color)
            
            # Draw diamond shape representing perspective distortion
            diamond_vertices = [
                (center_x, center_y + size),      # Top
                (center_x + size, center_y),      # Right
                (center_x, center_y - size),      # Bottom
                (center_x - size, center_y),      # Left
                (center_x, center_y + size)       # Close shape
            ]
            
            batch = batch_for_shader(line_shader, 'LINE_STRIP', {"pos": diamond_vertices})
            batch.draw(line_shader)
            
            # Add inner cross to indicate transform center
            cross_size = 3
            cross_lines = [
                [(center_x - cross_size, center_y), (center_x + cross_size, center_y)],  # Horizontal
                [(center_x, center_y - cross_size), (center_x, center_y + cross_size)]   # Vertical
            ]
            
            for line in cross_lines:
                batch = batch_for_shader(line_shader, 'LINES', {"pos": line})
                batch.draw(line_shader)
            
            gpu.state.line_width_set(1.0)
            
        except Exception as e:
            pass
    
    def _draw_handle_square(self, color, context):
        """Draw a square handle with rotation support"""
        try:
            # Get rotation angle from matrix
            rotation_angle = self.matrix_basis.to_3x3().to_euler().z
            
            # Handle center from matrix
            handle_center_x = self.matrix_basis.translation.x
            handle_center_y = self.matrix_basis.translation.y
            
            # Calculate square vertices - match EasyCrop exactly
            size = 6  # Handle size - this is the radius, not diameter
            
            # Base square vertices (before rotation) - EasyCrop uses full size, not half
            base_vertices = [
                Vector((-size, -size)),  # Bottom-left
                Vector((size, -size)),   # Bottom-right  
                Vector((size, size)),    # Top-right
                Vector((-size, size))    # Top-left
            ]
            
            # Apply rotation and translation
            cos_a = math.cos(rotation_angle)
            sin_a = math.sin(rotation_angle)
            
            rotated_vertices = []
            for vertex in base_vertices:
                # Rotate
                x_rot = vertex.x * cos_a - vertex.y * sin_a
                y_rot = vertex.x * sin_a + vertex.y * cos_a
                
                # Translate to handle position
                final_x = x_rot + handle_center_x
                final_y = y_rot + handle_center_y
                
                rotated_vertices.append((final_x, final_y))
            
            # Draw filled square
            shader = gpu.shader.from_builtin('UNIFORM_COLOR')
            batch = batch_for_shader(shader, 'TRI_FAN', {"pos": rotated_vertices})
            shader.bind()
            shader.uniform_float("color", color)
            batch.draw(shader)
            
            # Draw border for better visibility
            border_color = (0.0, 0.0, 0.0, 0.8)  # Black border
            gpu.state.line_width_set(1.0)
            border_vertices = rotated_vertices + [rotated_vertices[0]]  # Close the loop
            border_batch = batch_for_shader(shader, 'LINE_STRIP', {"pos": border_vertices})
            shader.uniform_float("color", border_color)
            border_batch.draw(shader)
            
        except Exception as e:
            pass
    
    def modal(self, context, event, tweak):
        """Handle modal interaction - perspective transform with homography"""
        print(f"Debug: Modal called with event {event.type}, select_id: {getattr(self, 'select_id', 'None')}")
        
        # Follow EasyCrop pattern - check for mouse movement directly from event
        if event.type == 'MOUSEMOVE':
            print("Debug: Processing mouse move")
            return self._handle_mouse_move(context, event)
        elif event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            print("Debug: Processing mouse release")
            return self._handle_confirm(context, event)
        elif event.type in {'ESC', 'RIGHTMOUSE'}:
            print("Debug: Processing cancel")
            return self._handle_cancel(context, event)
        
        return {'RUNNING_MODAL'}
    
    def _handle_mouse_move(self, context, event):
        """Handle mouse movement during drag - calculate perspective transform"""
        scene = context.scene
        if not scene.sequence_editor:
            return {'RUNNING_MODAL'}
            
        strip = scene.sequence_editor.active_strip
        if not strip or not hasattr(strip, 'transform'):
            return {'RUNNING_MODAL'}
        
        # Get current mouse position in view space (like EasyCrop approach)
        view2d = context.region.view2d
        mouse_view_pos = view2d.region_to_view(event.mouse_region_x, event.mouse_region_y)
        
        # Get effective corners for perspective calculation (respects existing transforms)
        from ..operators.perspective_core import get_effective_corners_for_perspective, store_original_corners_in_strip
        original_corners = get_effective_corners_for_perspective(strip, scene)
        
        # Store original corners on first drag if not already stored
        if not hasattr(self, '_stored_original') or not self._stored_original:
            store_original_corners_in_strip(strip, original_corners)
            self._stored_original = True
        
        # Create destination corners by modifying the dragged corner
        dst_corners = [Vector(corner) for corner in original_corners]  # Copy original corners
        
        # Handle different types of handles
        if hasattr(self, 'select_id') and self.select_id >= 0:
            res_x = scene.render.resolution_x
            res_y = scene.render.resolution_y
            
            # Convert view coordinates to strip coordinates
            strip_mouse_x = mouse_view_pos[0] + res_x / 2
            strip_mouse_y = mouse_view_pos[1] + res_y / 2
            
            if self.select_id < 4:
                # INNER HANDLES (0-3): Control perspective distortion within red boundary
                # Apply boundary constraints to keep handles within VSE rectangle
                constrained_pos = self._constrain_to_boundary(Vector([strip_mouse_x, strip_mouse_y]), context)
                
                # Update perspective corner positions for homography 
                dst_corners[self.select_id] = constrained_pos
                
                # Update the handle position to follow the mouse (with constraints)
                view2d = context.region.view2d
                constrained_screen = view2d.view_to_region(constrained_pos.x - res_x/2, constrained_pos.y - res_y/2, clip=False)
                
                # PRESERVE ROTATION during modal operations
                # Extract current rotation from matrix before updating position
                current_rotation = self.matrix_basis.to_3x3().to_euler().z
                
                # Create new matrix with preserved rotation
                translation_matrix = Matrix.Translation((constrained_screen[0], constrained_screen[1], 0))
                rotation_matrix = Matrix.Rotation(current_rotation, 4, 'Z')
                self.matrix_basis = translation_matrix @ rotation_matrix
                
                # Calculate homography matrix from original to new positions
                from ..operators.perspective_math import calculate_homography_matrix
                
                try:
                    homography = calculate_homography_matrix(original_corners, dst_corners)
                    
                    # Store the homography matrix in the strip
                    from ..operators.perspective_core import store_perspective_matrix_in_strip
                    store_perspective_matrix_in_strip(strip, homography)
                    
                    # DECOUPLED FROM VSE TRANSFORMS:
                    # - VSE rectangle stays unchanged (native transforms work normally)
                    # - We only store perspective data for future rendering
                    # - No more erratic scaling from decomposed homography
                    
                    # Store perspective corner offsets for position persistence
                    self._store_perspective_corner_offsets(strip, scene, dst_corners)
                    
                    # TODO: Apply perspective transformation via texture coordinates
                    
                    print(f"Debug: Handle {self.select_id} moved to {constrained_pos}, homography calculated")
                    
                except Exception as e:
                    print(f"Warning: Inner handle homography calculation failed: {e}")
                    
            elif self.select_id == 4:
                # CENTER HANDLE: Control overall positioning (could adjust VSE transform)
                pass  # TODO: Implement center handle behavior
            
            # Force redraw
            for area in context.screen.areas:
                if area.type == 'SEQUENCE_EDITOR':
                    area.tag_redraw()
        
        return {'RUNNING_MODAL'}
    
    def _constrain_to_boundary(self, position, context):
        """Constrain handle position to stay within the VISIBLE ROTATED red boundary rectangle"""
        if not hasattr(self, '_boundary_corners') or not self._boundary_corners:
            print("Debug: No boundary corners, returning unconstrained position")
            return position
        
        # ROTATED RECTANGLE CONSTRAINT:
        # Use the actual rotated boundary corners (same as red rectangle)
        # Check if point is inside the rotated rectangle using point-in-polygon
        
        scene = context.scene
        view2d = context.region.view2d
        res_x = scene.render.resolution_x
        res_y = scene.render.resolution_y
        
        # Convert strip coordinates to screen space for comparison with boundary
        view_x = position.x - res_x / 2
        view_y = position.y - res_y / 2
        screen_pos = view2d.view_to_region(view_x, view_y, clip=False)
        screen_point = Vector(screen_pos)
        
        print(f"Debug: Input position (strip): {position} -> screen: {screen_pos}")
        
        # Check if point is inside the rotated rectangle using point-in-polygon
        from ..operators.perspective_core import point_in_polygon
        
        boundary_corners = self._boundary_corners
        if point_in_polygon(screen_point, boundary_corners):
            # Point is inside - no constraint needed
            print("Debug: Point inside rotated boundary - no constraint")
            return position
        else:
            # Point is outside - find closest point on rotated rectangle boundary
            print("Debug: Point outside rotated boundary - constraining to boundary")
            constrained_screen = self._find_closest_point_on_rotated_rectangle(screen_point, boundary_corners)
            
            # Convert constrained screen position back to strip coordinates
            constrained_view = view2d.region_to_view(constrained_screen.x, constrained_screen.y)
            constrained_strip_x = constrained_view[0] + res_x / 2
            constrained_strip_y = constrained_view[1] + res_y / 2
            
            constrained = Vector([constrained_strip_x, constrained_strip_y])
            print(f"Debug: Constrained to rotated boundary (strip): {constrained}")
            
            return constrained
    
    def _find_closest_point_on_rotated_rectangle(self, point, rectangle_corners):
        """Find the closest point on the boundary of a rotated rectangle"""
        # For a rotated rectangle, we need to find the closest point on any of the 4 edges
        
        if len(rectangle_corners) != 4:
            return point  # Fallback
        
        min_distance = float('inf')
        closest_point = point
        
        # Check each edge of the rectangle
        for i in range(4):
            edge_start = rectangle_corners[i]
            edge_end = rectangle_corners[(i + 1) % 4]  # Next corner (wrapping)
            
            # Find closest point on this edge
            edge_closest = self._closest_point_on_line_segment(point, edge_start, edge_end)
            distance = (point - edge_closest).length
            
            if distance < min_distance:
                min_distance = distance
                closest_point = edge_closest
        
        return closest_point
    
    def _closest_point_on_line_segment(self, point, line_start, line_end):
        """Find the closest point on a line segment to a given point"""
        # Vector from line start to line end
        line_vec = line_end - line_start
        line_length_sq = line_vec.length_squared
        
        if line_length_sq == 0:
            # Line segment is actually a point
            return line_start
        
        # Vector from line start to point
        point_vec = point - line_start
        
        # Project point onto line segment
        t = max(0, min(1, point_vec.dot(line_vec) / line_length_sq))
        
        # Find the projected point
        projection = line_start + t * line_vec
        return projection
    
    def _handle_confirm(self, context, event):
        """Handle drag confirmation"""
        # Transformation is already applied during drag, just finish
        return {'FINISHED'}
    
    def _handle_cancel(self, context, event):
        """Handle drag cancellation - restore original state"""
        scene = context.scene
        if scene.sequence_editor:
            strip = scene.sequence_editor.active_strip
            if strip and hasattr(strip, 'transform'):
                # Clear perspective matrix
                from ..operators.perspective_core import clear_perspective_matrix_from_strip
                clear_perspective_matrix_from_strip(strip)
                
                # Reset basic transform properties
                strip.transform.scale_x = 1.0
                strip.transform.scale_y = 1.0
                strip.transform.rotation = 0.0
                strip.transform.offset_x = 0.0
                strip.transform.offset_y = 0.0
        
        return {'CANCELLED'}
    
    def invoke(self, context, event):
        """Start perspective transform interaction"""
        # Store initial strip state for potential restoration
        scene = context.scene
        if scene.sequence_editor:
            strip = scene.sequence_editor.active_strip
            if strip and hasattr(strip, 'transform'):
                # Store initial transform state
                self.init_transform_state = {
                    'scale_x': strip.transform.scale_x,
                    'scale_y': strip.transform.scale_y,
                    'rotation': strip.transform.rotation,
                    'offset_x': strip.transform.offset_x,
                    'offset_y': strip.transform.offset_y
                }
        
        return {'RUNNING_MODAL'}
    
    def _store_perspective_corner_offsets(self, strip, scene, perspective_corners):
        """
        Store perspective corner offsets relative to UNROTATED VSE rectangle.
        This enables rotation-invariant position persistence.
        
        COORDINATE SYSTEM: Store offsets in unrotated strip space, then rotate when loading
        
        Args:
            strip: Blender sequence strip  
            scene: Blender scene
            perspective_corners: List of 4 Vector objects for current perspective corner positions (STRIP SPACE)
        """
        if not strip or not perspective_corners or len(perspective_corners) != 4:
            return
        
        try:
            # Get UNROTATED VSE corner positions for rotation-invariant storage
            from ..operators.perspective_core import get_strip_geometry_with_flip_support
            
            # Get current rotation
            original_rotation = 0
            if hasattr(strip, 'transform') and hasattr(strip.transform, 'rotation'):
                original_rotation = strip.transform.rotation
                
            # Get unrotated VSE corners without modifying the strip
            unrotated_vse_corners, (pivot_x, pivot_y), (scale_x, scale_y, flip_x, flip_y) = self._get_unrotated_strip_geometry(strip, scene)
            
            # Get current rotated VSE corners 
            current_vse_corners, _, _ = get_strip_geometry_with_flip_support(strip, scene)
            
            # Calculate rotation-invariant offsets by un-rotating the perspective corners
            pivot = Vector((pivot_x, pivot_y))
            unrotated_perspective_corners = []
            
            for perspective_corner in perspective_corners:
                # Un-rotate the perspective corner to match unrotated reference
                angle = -original_rotation  # Negative to un-rotate
                if flip_x != flip_y:  # Handle flip compensation
                    angle = -angle
                    
                unrotated_corner = self._rotate_point(perspective_corner, angle, pivot)
                unrotated_perspective_corners.append(unrotated_corner)
            
            print(f"Debug: Storing ROTATION-INVARIANT offsets")
            print(f"Debug: Original rotation: {math.degrees(original_rotation):.1f}°")
            print(f"Debug: Unrotated VSE corners: {[f'({c.x:.1f},{c.y:.1f})' for c in unrotated_vse_corners]}")
            print(f"Debug: Unrotated perspective corners: {[f'({c.x:.1f},{c.y:.1f})' for c in unrotated_perspective_corners]}")
            
            # Store offsets relative to unrotated corners
            from ..operators.perspective_core import store_perspective_offsets_in_strip
            store_perspective_offsets_in_strip(strip, unrotated_vse_corners, unrotated_perspective_corners)
            
            # Debug: Show calculated rotation-invariant offsets
            for i, (vse_corner, perspective_corner) in enumerate(zip(unrotated_vse_corners, unrotated_perspective_corners)):
                offset_x = perspective_corner.x - vse_corner.x
                offset_y = perspective_corner.y - vse_corner.y
                print(f"Debug: Handle {i} UNROTATED offset - VSE: ({vse_corner.x:.1f},{vse_corner.y:.1f}) -> Perspective: ({perspective_corner.x:.1f},{perspective_corner.y:.1f}) = Offset: ({offset_x:.1f},{offset_y:.1f})")
            
            print(f"Debug: Stored rotation-invariant perspective corner offsets")
            
        except Exception as e:
            print(f"Warning: Could not store perspective corner offsets: {e}")
    
    def _get_unrotated_strip_geometry(self, strip, scene):
        """
        Get strip geometry as if rotation was 0, without modifying the strip.
        
        Returns:
            Tuple of (corners, (pivot_x, pivot_y), (scale_x, scale_y, flip_x, flip_y))
        """
        from ..operators.perspective_core import get_strip_geometry_with_flip_support
        
        # Get current geometry
        rotated_corners, (pivot_x, pivot_y), (scale_x, scale_y, flip_x, flip_y) = get_strip_geometry_with_flip_support(strip, scene)
        
        # Get current rotation
        current_rotation = 0
        if hasattr(strip, 'transform') and hasattr(strip.transform, 'rotation'):
            current_rotation = strip.transform.rotation
        
        if current_rotation == 0:
            # No rotation - return as is
            return rotated_corners, (pivot_x, pivot_y), (scale_x, scale_y, flip_x, flip_y)
        
        # Un-rotate the corners to get unrotated geometry
        pivot = Vector((pivot_x, pivot_y))
        unrotated_corners = []
        
        for corner in rotated_corners:
            # Un-rotate by applying negative rotation
            angle = -current_rotation
            if flip_x != flip_y:  # Handle flip compensation
                angle = -angle
                
            unrotated_corner = self._rotate_point(corner, angle, pivot)
            unrotated_corners.append(unrotated_corner)
        
        return unrotated_corners, (pivot_x, pivot_y), (scale_x, scale_y, flip_x, flip_y)
    
    def _rotate_point(self, point, angle, origin):
        """Rotate a 2D point around an origin"""
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        
        # Translate to origin
        x = point.x - origin.x
        y = point.y - origin.y
        
        # Rotate
        new_x = x * cos_a - y * sin_a
        new_y = x * sin_a + y * cos_a
        
        # Translate back
        return Vector([new_x + origin.x, new_y + origin.y])
    
    def exit(self, context, cancel):
        """Exit perspective transform with cursor restoration"""
        # Implement cursor restoration like in crop gizmo if needed
        pass


class PERSPECTIVE_GGT_perspective_handles(GizmoGroup):
    """Gizmo group for perspective transform handles"""
    bl_idname = "PERSPECTIVE_GGT_perspective_handles"
    bl_label = "Perspective Transform Handles"
    bl_space_type = 'SEQUENCE_EDITOR'
    bl_region_type = 'PREVIEW'
    bl_options = {'PERSISTENT'}
    
    @classmethod
    def poll(cls, context):
        """Check if perspective handles should be shown"""
        # Only show in VSE preview
        if not context.space_data or context.space_data.type != 'SEQUENCE_EDITOR':
            return False

        # Check display mode
        if hasattr(context.space_data, 'display_mode'):
            if context.space_data.display_mode != 'IMAGE':
                return False

        # Require sequence editor and active strip with transform
        if not context.scene.sequence_editor:
            return False

        active_strip = context.scene.sequence_editor.active_strip
        if not active_strip or not hasattr(active_strip, 'transform'):
            return False

        # Only show for SELECTED strips
        if not active_strip.select:
            return False

        # Only show for visible strips at current frame
        current_frame = context.scene.frame_current
        if not is_strip_visible_at_frame(active_strip, current_frame):
            return False

        # Don't show if modal perspective mode is active
        perspective_state = get_perspective_state()
        if perspective_state['active']:
            return False

        # Require perspective handles tool to be active
        try:
            workspace = bpy.context.workspace
            for tool in workspace.tools:
                if hasattr(tool, 'idname') and tool.idname == "sequencer.perspective_handles_tool":
                    return True
        except:
            pass

        return False
    
    def setup(self, context):
        """Setup the gizmo group with boundary + inner handle system"""
        # Create simplified handle system:
        # - No outer handles (just red boundary outline drawn separately)
        # - Inner handles (4): Perspective corners constrained within boundary (select_id 0-3)  
        # - Center handle (1): Transform center (select_id 4)
        
        # Inner perspective handles (0-3) - these control perspective distortion within red boundary
        for i in range(4):
            gz = self.gizmos.new(PERSPECTIVE_GT_perspective_handle.bl_idname)
            gz.handle_type = "inner_corner"
            gz.handle_index = i
            gz.select_id = i
        
        # Center handle (4)
        gz_center = self.gizmos.new(PERSPECTIVE_GT_perspective_handle.bl_idname)
        gz_center.handle_type = "center" 
        gz_center.handle_index = 4
        gz_center.select_id = 4
    
    def refresh(self, context):
        """Update gizmo positions based on current strip geometry"""
        scene = context.scene
        if not scene.sequence_editor:
            return
            
        strip = scene.sequence_editor.active_strip
        if not strip:
            return
        
        # Don't show during modal mode
        perspective_state = get_perspective_state()
        if perspective_state['active']:
            for gz in self.gizmos:
                gz.hide = True
            return
        
        # Get current strip geometry
        try:
            corners, (pivot_x, pivot_y), (scale_x, scale_y, flip_x, flip_y) = get_strip_geometry_with_flip_support(strip, scene)
        except:
            for gz in self.gizmos:
                gz.hide = True
            return
        
        # Convert to view coordinates
        region = context.region
        if not region:
            return
            
        view2d = region.view2d
        res_x = scene.render.resolution_x
        res_y = scene.render.resolution_y
        
        # Calculate rotation for handle alignment
        angle = 0
        if hasattr(strip, 'transform') and hasattr(strip.transform, 'rotation'):
            angle = strip.transform.rotation
        
        # Handle flipped rotation
        if flip_x != flip_y:  # XOR - if only one axis is flipped
            angle = -angle
        
        # Convert corners to screen coordinates for proper positioning
        screen_corners = []
        for corner in corners:
            view_x = corner.x - res_x / 2
            view_y = corner.y - res_y / 2
            screen_co = view2d.view_to_region(view_x, view_y, clip=False)
            screen_corners.append(Vector(screen_co))
        
        # Store rotated screen corners for both boundary drawing AND constraints
        # Now we properly constrain to the visible rotated rectangle
        self._boundary_corners = screen_corners
        for gz in self.gizmos:
            gz._boundary_corners = screen_corners
        
        # Position inner perspective handles (0-3) - these control perspective distortion
        # Load stored perspective positions or default to strip corners
        # COORDINATE FLOW: Strip -> View -> Screen -> Matrix Translation
        for i, gz in enumerate(self.gizmos[:4]):  # First 4 are inner perspective corners
            if i < len(screen_corners):
                screen_corner = screen_corners[i]  # SCREEN COORDINATES from VSE corners
                
                # Check for stored perspective corner positions (returns SCREEN COORDINATES)
                stored_positions = self._get_stored_perspective_positions(strip, scene, view2d, res_x, res_y)
                
                if stored_positions and i < len(stored_positions):
                    # Use stored perspective position (SCREEN COORDINATES)
                    handle_x, handle_y = stored_positions[i]
                    print(f"Debug: Handle {i} using STORED position (screen): ({handle_x:.1f},{handle_y:.1f})")
                else:
                    # Default to strip corner positions (SCREEN COORDINATES)
                    handle_x = screen_corner.x
                    handle_y = screen_corner.y
                    print(f"Debug: Handle {i} using DEFAULT VSE corner (screen): ({handle_x:.1f},{handle_y:.1f})")
                
                # Set position using screen coordinates (SCREEN COORDINATES -> MATRIX)
                gz.matrix_basis = Matrix.Translation((handle_x, handle_y, 0))
                
                # Apply rotation to matrix for proper handle alignment
                rot_matrix = Matrix.Rotation(angle, 4, 'Z')
                gz.matrix_basis = gz.matrix_basis @ rot_matrix
                
                gz.hide = False
            else:
                gz.hide = True
        
        # Position center handle - index 4
        if len(self.gizmos) > 4:
            gz_center = self.gizmos[4]
            center_view_x = pivot_x - res_x / 2
            center_view_y = pivot_y - res_y / 2
            center_screen_co = view2d.view_to_region(center_view_x, center_view_y, clip=False)
            
            gz_center.matrix_basis = Matrix.Translation((center_screen_co[0], center_screen_co[1], 0))
            gz_center.hide = False
        
        # Draw red boundary outline (VSE rectangle bounds)
        self._draw_boundary_outline()
    
    def _get_stored_perspective_positions(self, strip, scene, view2d, res_x, res_y):
        """
        Get stored perspective handle positions in screen coordinates with rotation-invariant loading.
        
        COORDINATE SYSTEM FLOW:
        1. Load rotation-invariant offsets (unrotated strip space)
        2. Get unrotated VSE corners (strip space)
        3. Apply offsets to get unrotated perspective corners (strip space)
        4. Rotate perspective corners to current rotation (strip space)
        5. Convert to view space (centered coordinates)
        6. Convert to screen space (region pixels)
        
        Returns:
            List of (x, y) tuples in screen coordinates, or None if not stored
        """
        if not strip:
            return None
        
        # Try to get stored rotation-invariant offsets (UNROTATED STRIP COORDINATE SPACE)
        from ..operators.perspective_core import get_perspective_offsets_from_strip
        offsets = get_perspective_offsets_from_strip(strip)
        
        if not offsets or len(offsets) != 4:
            return None
        
        try:
            # Get current rotation for rotation compensation
            current_rotation = 0
            if hasattr(strip, 'transform') and hasattr(strip.transform, 'rotation'):
                current_rotation = strip.transform.rotation
                
            # Get UNROTATED VSE corners without modifying the strip
            unrotated_corners, (pivot_x, pivot_y), (scale_x, scale_y, flip_x, flip_y) = self._get_unrotated_strip_geometry(strip, scene)
            
            print(f"Debug: Loading ROTATION-INVARIANT positions")
            print(f"Debug: Current rotation: {math.degrees(current_rotation):.1f}°")
            print(f"Debug: Unrotated VSE corners: {[f'({c.x:.1f},{c.y:.1f})' for c in unrotated_corners]}")
            print(f"Debug: Stored offsets: {[f'({o.x:.1f},{o.y:.1f})' for o in offsets]}")
            
            # Apply offsets to unrotated corners to get unrotated perspective positions
            unrotated_perspective_corners = []
            for i, (vse_corner, offset) in enumerate(zip(unrotated_corners, offsets)):
                unrotated_perspective_corner = Vector([vse_corner.x + offset.x, vse_corner.y + offset.y])
                unrotated_perspective_corners.append(unrotated_perspective_corner)
                print(f"Debug: Handle {i} - Unrotated VSE: ({vse_corner.x:.1f},{vse_corner.y:.1f}) + Offset: ({offset.x:.1f},{offset.y:.1f}) = Unrotated Perspective: ({unrotated_perspective_corner.x:.1f},{unrotated_perspective_corner.y:.1f})")
            
            # Rotate perspective corners to current rotation
            pivot = Vector((pivot_x, pivot_y))
            perspective_positions = []
            
            for i, unrotated_corner in enumerate(unrotated_perspective_corners):
                # Apply current rotation
                angle = current_rotation
                if flip_x != flip_y:  # Handle flip compensation
                    angle = -angle
                    
                rotated_corner = self._rotate_point(unrotated_corner, angle, pivot)
                
                print(f"Debug: Handle {i} - Rotating: ({unrotated_corner.x:.1f},{unrotated_corner.y:.1f}) -> ({rotated_corner.x:.1f},{rotated_corner.y:.1f})")
                
                # Convert to view coordinates (VIEW SPACE - centered at origin)
                view_x = rotated_corner.x - res_x / 2
                view_y = rotated_corner.y - res_y / 2
                
                # Convert to screen coordinates (SCREEN SPACE - region pixels)
                screen_co = view2d.view_to_region(view_x, view_y, clip=False)
                
                print(f"Debug: Handle {i} - Strip: ({rotated_corner.x:.1f},{rotated_corner.y:.1f}) -> View: ({view_x:.1f},{view_y:.1f}) -> Screen: ({screen_co[0]:.1f},{screen_co[1]:.1f})")
                
                perspective_positions.append((screen_co[0], screen_co[1]))
            
            return perspective_positions
            
        except Exception as e:
            print(f"Warning: Could not retrieve stored perspective positions: {e}")
            return None
    
    def _draw_boundary_outline(self):
        """Draw red outline showing VSE rectangle bounds"""
        if not hasattr(self, '_boundary_corners') or not self._boundary_corners:
            return
            
        try:
            # Draw red rectangle outline
            boundary_color = (1.0, 0.2, 0.2, 0.8)  # Red color
            
            line_shader = gpu.shader.from_builtin('UNIFORM_COLOR')
            gpu.state.line_width_set(2.0)  # Thicker line for visibility
            line_shader.bind()
            line_shader.uniform_float("color", boundary_color)
            
            # Create boundary line vertices (closed rectangle)
            boundary_vertices = []
            for corner in self._boundary_corners:
                boundary_vertices.append((corner.x, corner.y))
            # Close the rectangle
            boundary_vertices.append((self._boundary_corners[0].x, self._boundary_corners[0].y))
            
            batch = batch_for_shader(line_shader, 'LINE_STRIP', {"pos": boundary_vertices})
            batch.draw(line_shader)
            
            gpu.state.line_width_set(1.0)  # Reset line width
            
        except Exception as e:
            pass


# Registration functions
def register_perspective_handles_gizmo():
    """Register the perspective handles gizmo"""
    try:
        bpy.utils.register_class(PERSPECTIVE_GT_perspective_handle)
        bpy.utils.register_class(PERSPECTIVE_GGT_perspective_handles)
    except Exception as e:
        pass


def unregister_perspective_handles_gizmo():
    """Unregister the perspective handles gizmo"""
    try:
        bpy.utils.unregister_class(PERSPECTIVE_GGT_perspective_handles)
        bpy.utils.unregister_class(PERSPECTIVE_GT_perspective_handle)
    except Exception as e:
        pass