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
                # Center symbol - always white, never highlights
                white_color = (1.0, 1.0, 1.0, 0.8)
                self._draw_perspective_symbol(white_color)
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
        """Draw the perspective symbol - simple single line creating perspective illusion"""
        try:
            center_pos = self.matrix_basis.translation
            center_x = center_pos.x
            center_y = center_pos.y
            
            # Symbol dimensions
            size = 8
            
            line_shader = gpu.shader.from_builtin('UNIFORM_COLOR')
            gpu.state.line_width_set(1.5)
            line_shader.bind()
            line_shader.uniform_float("color", color)
            
            # Single line creating perspective illusion - left side full height, right side shorter
            perspective_vertices = [
                (center_x - size, center_y - size),      # Bottom-left (full height)
                (center_x - size, center_y + size),      # Top-left (full height)
                (center_x + size, center_y + size * 0.6),  # Top-right (scaled down)
                (center_x + size, center_y - size * 0.6),  # Bottom-right (scaled down)
                (center_x - size, center_y - size)       # Back to start (close the shape)
            ]
            
            batch = batch_for_shader(line_shader, 'LINE_STRIP', {"pos": perspective_vertices})
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

            # Draw handle number label
            if hasattr(self, 'handle_index'):
                import blf
                font_id = 0
                blf.position(font_id, handle_center_x + 10, handle_center_y + 10, 0)
                blf.size(font_id, 16)
                blf.color(font_id, 1.0, 1.0, 0.0, 1.0)  # Yellow text
                blf.draw(font_id, str(self.handle_index))

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
        
        # Simple approach: Use current mouse position directly
        view2d = context.region.view2d
        mouse_view_pos = view2d.region_to_view(event.mouse_region_x, event.mouse_region_y)
        
        print(f"Debug: Direct mouse positioning - Screen: ({event.mouse_region_x}, {event.mouse_region_y}) -> View: ({mouse_view_pos[0]:.2f}, {mouse_view_pos[1]:.2f})")
        
        # Get effective corners for perspective calculation (respects existing transforms)
        from ..operators.perspective_core import get_effective_corners_for_perspective, store_original_corners_in_strip
        original_corners = get_effective_corners_for_perspective(strip, scene)

        # Get flip state to remap corners from position-based to identity-based order
        flip_x = False
        flip_y = False
        for attr_name in ['use_flip_x', 'flip_x', 'mirror_x']:
            if hasattr(strip, attr_name):
                flip_x = getattr(strip, attr_name)
                break
        for attr_name in ['use_flip_y', 'flip_y', 'mirror_y']:
            if hasattr(strip, attr_name):
                flip_y = getattr(strip, attr_name)
                break

        # CRITICAL: Remap corners from position-based to identity-based order
        # Same remapping as in refresh()
        if flip_x and flip_y:
            original_corners = [original_corners[2], original_corners[3], original_corners[0], original_corners[1]]
        elif flip_x:
            original_corners = [original_corners[3], original_corners[2], original_corners[1], original_corners[0]]
        elif flip_y:
            original_corners = [original_corners[1], original_corners[0], original_corners[3], original_corners[2]]

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
            
            # Direct mouse positioning: Convert mouse position to strip coordinates (rotated+flipped space)
            # Keep it in the SAME space as original_corners (which are rotated+flipped)
            strip_mouse_x = mouse_view_pos[0] + res_x / 2
            strip_mouse_y = mouse_view_pos[1] + res_y / 2

            print(f"Debug: Mouse -> Strip: ({strip_mouse_x:.1f}, {strip_mouse_y:.1f})")
            print(f"Debug: Handle {self.select_id} being dragged")

            if self.select_id < 4:
                # INNER HANDLES (0-3): Control perspective distortion within red boundary
                # Apply boundary constraints to keep handles within VSE rectangle
                constrained_pos = self._constrain_to_boundary(Vector([strip_mouse_x, strip_mouse_y]), context)

                print(f"Debug: Handle {self.select_id} - Before constraint: ({strip_mouse_x:.1f}, {strip_mouse_y:.1f}) -> After constraint: ({constrained_pos.x:.1f}, {constrained_pos.y:.1f})")

                # Update perspective corner positions for homography
                # Handle i controls corner i directly - no remapping needed
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
                    
                    # Store the homography matrix and enable GPU rendering
                    from ..operators.perspective_core import store_perspective_matrix_in_strip, apply_perspective_to_strip
                    store_perspective_matrix_in_strip(strip, homography)
                    
                    # Enable GPU-based perspective distortion overlay
                    apply_perspective_to_strip(strip, homography)
                    
                    # Store perspective corner offsets for position persistence
                    # Only update the specific handle being dragged, preserve others
                    self._store_single_handle_offset(strip, scene, self.select_id, constrained_pos)
                    
                    # Force refresh of the gizmo group to update all handle positions
                    # This ensures other handles reflect any changes from the storage system
                    if hasattr(self, 'group') and hasattr(self.group, 'refresh'):
                        self.group.refresh(context)
                    
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
                # Clear perspective matrix and GPU rendering
                from ..operators.perspective_core import clear_perspective_matrix_from_strip, _disable_perspective_rendering
                clear_perspective_matrix_from_strip(strip)
                _disable_perspective_rendering(strip)
                
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
        
        # Simple approach: Just store initial strip state for potential restoration
        print(f"Debug: Starting modal drag for handle {getattr(self, 'select_id', 'unknown')}")
        
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

                unrotated_corner = self.group._rotate_point(perspective_corner, angle, pivot)
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
    
    def _store_single_handle_offset(self, strip, scene, handle_id, new_position):
        """
        Store offset for a single handle while preserving other handle positions.
        
        Args:
            strip: Blender sequence strip
            scene: Blender scene  
            handle_id: Which handle (0-3) is being updated
            new_position: New position for this handle (STRIP COORDINATES)
        """
        if not strip or handle_id < 0 or handle_id > 3:
            return
            
        try:
            # Get current rotation and flip state
            current_rotation = 0
            if hasattr(strip, 'transform') and hasattr(strip.transform, 'rotation'):
                current_rotation = strip.transform.rotation

            # Get CANONICAL (unflipped+unrotated) VSE corners for flip/rotation-independent storage
            canonical_vse_corners, (canonical_pivot_x, canonical_pivot_y), (scale_x, scale_y, flip_x, flip_y) = self.group._get_canonical_strip_geometry(strip, scene)
            canonical_pivot = (canonical_pivot_x, canonical_pivot_y)
            
            # Simple approach: Store handle at its actual index, no remapping
            storage_handle_id = handle_id
                
            print(f"Debug: Simple storage - handle {handle_id} stored at index {storage_handle_id}")
            print(f"Debug: MODAL STORAGE - Current scale: ({scale_x:.3f}, {scale_y:.3f}) for handle {handle_id}")
            
            # Get existing proportional offsets (always use proportional system now)
            from ..operators.perspective_core import get_perspective_offsets_from_strip
            existing_offsets = get_perspective_offsets_from_strip(strip)
            
            if not existing_offsets:
                # Initialize with zero proportional offsets (handles at VSE corners)
                existing_offsets = [Vector([0.0, 0.0]) for _ in range(4)]
                print(f"Debug: Initializing proportional offsets - no previous offsets found")
            else:
                print(f"Debug: Found existing proportional offsets: {[f'({o.x:.3f},{o.y:.3f})' for o in existing_offsets]}")
            
            # Get current flipped+rotated corners to calculate handle offsets FROM
            from ..operators.perspective_core import get_strip_geometry_with_flip_support
            current_corners, (pivot_x, pivot_y), _ = get_strip_geometry_with_flip_support(strip, scene)

            # Remap to identity-based order (same as in refresh())
            if flip_x and flip_y:
                current_corners = [current_corners[2], current_corners[3], current_corners[0], current_corners[1]]
            elif flip_x:
                current_corners = [current_corners[3], current_corners[2], current_corners[1], current_corners[0]]
            elif flip_y:
                current_corners = [current_corners[1], current_corners[0], current_corners[3], current_corners[2]]

            # Calculate offsets from corners (in flipped+rotated space) for all handles
            current_offsets_in_transformed_space = []
            for i in range(4):
                if i == storage_handle_id:
                    # For dragged handle, calculate offset from its corner
                    offset_vector = new_position - current_corners[i]
                    print(f"Debug: Handle {i} (DRAGGED) - Corner: ({current_corners[i].x:.1f},{current_corners[i].y:.1f}), Handle: ({new_position.x:.1f},{new_position.y:.1f}), Offset: ({offset_vector.x:.1f},{offset_vector.y:.1f})")
                else:
                    # For other handles, reconstruct their offset from existing stored offsets
                    # Load the offset, apply to canonical corner, flip/rotate to get current position
                    vse_corner_canonical = canonical_vse_corners[i]
                    proportional_offset = existing_offsets[i]

                    vse_width = canonical_vse_corners[2].x - canonical_vse_corners[0].x
                    vse_height = canonical_vse_corners[1].y - canonical_vse_corners[0].y
                    absolute_offset_x = proportional_offset.x * vse_width
                    absolute_offset_y = proportional_offset.y * vse_height

                    canonical_handle_pos = Vector([vse_corner_canonical.x + absolute_offset_x, vse_corner_canonical.y + absolute_offset_y])

                    # Apply flip and rotation to get current handle position
                    res_x = scene.render.resolution_x
                    res_y = scene.render.resolution_y
                    flipped_handle_pos = self.group._apply_flip_to_position(canonical_handle_pos, res_x, res_y, flip_x, flip_y)

                    angle = current_rotation
                    if flip_x != flip_y:
                        angle = -angle
                    rotated_handle_pos = self.group._rotate_point(flipped_handle_pos, angle, Vector((pivot_x, pivot_y)))

                    # Calculate offset in current space
                    offset_vector = rotated_handle_pos - current_corners[i]
                    print(f"Debug: Handle {i} (PRESERVED) - Offset: ({offset_vector.x:.1f},{offset_vector.y:.1f})")

                current_offsets_in_transformed_space.append(offset_vector)

            # Now convert these offsets to canonical space by un-rotating (but NOT un-flipping)
            # The offset should maintain its direction relative to the corner
            canonical_offsets = []
            for i, offset_vector in enumerate(current_offsets_in_transformed_space):
                # Un-rotate the offset vector
                angle = -current_rotation
                if flip_x != flip_y:
                    angle = -angle

                # Rotate the offset vector around origin (not around pivot - it's just a vector)
                cos_a = math.cos(angle)
                sin_a = math.sin(angle)
                canonical_offset_x = offset_vector.x * cos_a - offset_vector.y * sin_a
                canonical_offset_y = offset_vector.x * sin_a + offset_vector.y * cos_a

                canonical_offsets.append(Vector([canonical_offset_x, canonical_offset_y]))
                print(f"Debug: Handle {i} - Offset in transformed space: ({offset_vector.x:.1f},{offset_vector.y:.1f}) -> Canonical offset: ({canonical_offset_x:.1f},{canonical_offset_y:.1f})")
            
            # Convert canonical offsets to proportional values for scale-independence
            canonical_proportional_offsets = []
            vse_width = canonical_vse_corners[2].x - canonical_vse_corners[0].x  # right - left
            vse_height = canonical_vse_corners[1].y - canonical_vse_corners[0].y  # top - bottom

            for canonical_offset in canonical_offsets:
                # Convert absolute offset to proportional offset
                if vse_width != 0 and vse_height != 0:
                    prop_offset_x = canonical_offset.x / vse_width
                    prop_offset_y = canonical_offset.y / vse_height
                else:
                    prop_offset_x = 0.0
                    prop_offset_y = 0.0

                canonical_proportional_offsets.append(Vector([prop_offset_x, prop_offset_y]))

            # Store proportional offsets in CANONICAL space (flip/rotation-independent)
            from ..operators.perspective_core import store_perspective_offsets_in_strip
            store_perspective_offsets_in_strip(strip,
                                               [Vector([0.0, 0.0]) for _ in range(4)],  # Dummy VSE corners (not used with proportional)
                                               canonical_proportional_offsets)  # Store proportional values in canonical space

            print(f"Debug: Updated single handle {handle_id} with CANONICAL PROPORTIONAL offsets (flip/rotation-independent)")
            print(f"Debug: Canonical VSE dimensions: {vse_width:.1f} x {vse_height:.1f}")
            print(f"Debug: Current flip state: flip_x={flip_x}, flip_y={flip_y}")
            for i, prop_offset in enumerate(canonical_proportional_corners):
                print(f"Debug: Handle {i} canonical proportional offset: ({prop_offset.x:.3f}, {prop_offset.y:.3f})")
            
        except Exception as e:
            print(f"Warning: Could not store single handle offset: {e}")

    def exit(self, context, cancel):
        """Exit perspective transform with cursor warping - EasyCrop implementation"""
        if self.handle_type != "center":
            # Deferred cursor warp with timer (EasyCrop approach)
            if not cancel:
                try:
                    # Calculate final handle position in window coordinates
                    region = context.region
                    if region and hasattr(self, 'matrix_basis'):
                        # Get handle position from matrix (screen coordinates)
                        handle_screen_pos = self.matrix_basis.translation
                        
                        # Convert to window coordinates
                        final_x = int(region.x + handle_screen_pos.x)
                        final_y = int(region.y + handle_screen_pos.y)
                        
                        def deferred_cursor_warp():
                            try:
                                # Warp cursor and restore modal state (EasyCrop order)
                                bpy.context.window.cursor_warp(final_x, final_y)
                                bpy.context.window.cursor_modal_restore()
                            except Exception:
                                pass
                            return None
                        
                        # Hide cursor immediately (EasyCrop approach)
                        bpy.context.window.cursor_modal_set('NONE')
                        
                        # Schedule cursor warp with 50ms delay (EasyCrop timing)
                        bpy.app.timers.register(deferred_cursor_warp, first_interval=0.05)
                        
                        print(f"Debug: EasyCrop-style cursor warp scheduled to ({final_x}, {final_y})")
                        
                except Exception:
                    pass


class PERSPECTIVE_GGT_perspective_handles(GizmoGroup):
    """Gizmo group for perspective transform handles"""
    bl_idname = "PERSPECTIVE_GGT_perspective_handles"
    bl_label = "Perspective Transform Handles"
    bl_space_type = 'SEQUENCE_EDITOR'
    bl_region_type = 'PREVIEW'
    bl_options = {'SHOW_MODAL_ALL'}
    
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
            
        # Debug: Print when refresh is called
        print(f"DEBUG: Gizmo refresh called for strip {strip.name}")
        
        # Don't show during modal mode
        perspective_state = get_perspective_state()
        if perspective_state['active']:
            for gz in self.gizmos:
                gz.hide = True
            return
        
        
        # Get current strip geometry
        try:
            corners, (pivot_x, pivot_y), (scale_x, scale_y, flip_x, flip_y) = get_strip_geometry_with_flip_support(strip, scene)

            # CRITICAL: get_strip_geometry_with_flip_support returns corners in POSITION-based order
            # (always [bottom-left, top-left, top-right, bottom-right] positionally)
            # But we need IDENTITY-based order (Corner 0, Corner 1, Corner 2, Corner 3)
            # When flipped, we must remap to restore identity-based ordering

            if flip_x and flip_y:
                # Both flips: diagonal swap
                corners = [corners[2], corners[3], corners[0], corners[1]]
            elif flip_x:
                # X-flip only: left↔right swap
                corners = [corners[3], corners[2], corners[1], corners[0]]
            elif flip_y:
                # Y-flip only: top↔bottom swap
                corners = [corners[1], corners[0], corners[3], corners[2]]
            # else: no flip, corners already in identity order

            # Debug flip states and corner positions - ALWAYS print so we can see changes
            print(f"DEBUG: Current flip state - flip_x={flip_x}, flip_y={flip_y}")
            for i, corner in enumerate(corners):
                print(f"DEBUG: Corner {i} (identity-based): ({corner.x:.1f}, {corner.y:.1f})")
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
                
                # Try to get stored perspective positions first (returns SCREEN COORDINATES)
                stored_positions = None
                try:
                    stored_positions = self._get_stored_perspective_positions(strip, scene, view2d, res_x, res_y)
                except Exception as e:
                    print(f"Warning: Could not get stored perspective positions: {e}")
                    stored_positions = None

                # Use stored positions if available, otherwise default to VSE corners
                if stored_positions and i < len(stored_positions):
                    # Use the stored perspective position (already in screen coordinates)
                    handle_x, handle_y = stored_positions[i]
                    print(f"Debug: Handle {i} using STORED position: screen ({handle_x:.1f},{handle_y:.1f})")
                else:
                    # Fall back to VSE corner position
                    handle_x, handle_y = screen_corner.x, screen_corner.y
                    print(f"Debug: Handle {i} using VSE CORNER fallback: screen ({handle_x:.1f},{handle_y:.1f})")
                
                # Set position using screen coordinates (SCREEN COORDINATES -> MATRIX)
                # NOTE: Position is already in rotated space from get_strip_geometry_with_flip_support()
                # We still need to apply rotation to the matrix for the DRAWING layer (handle squares)
                # to rotate visually, but the POSITION is already correct
                translation_matrix = Matrix.Translation((handle_x, handle_y, 0))
                rot_matrix = Matrix.Rotation(angle, 4, 'Z')
                gz.matrix_basis = translation_matrix @ rot_matrix

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
        
        # Draw perspective distortion preview lines
        self._draw_perspective_preview_lines(context)
        
        # Draw perspective grid overlay (if enabled)
        self._draw_perspective_grid_overlay(context)
    
    def draw_prepare(self, context):
        """Called before drawing - ensures frequent updates for zoom responsiveness"""
        # Force refresh when viewport changes (zoom/pan)
        # This ensures handles and boundary update immediately with viewport changes
        scene = context.scene
        if scene and scene.sequence_editor and scene.sequence_editor.active_strip:
            # Trigger position recalculation
            self.refresh(context)
        
    
    def _get_stored_perspective_positions(self, strip, scene, view2d, res_x, res_y):
        """
        Get stored perspective handle positions in screen coordinates with flip/rotation-independent loading.

        COORDINATE SYSTEM FLOW:
        1. Load flip/rotation-independent offsets (canonical/unflipped/unrotated space)
        2. Get canonical VSE corners (unflipped/unrotated strip space)
        3. Apply offsets to get canonical perspective corners
        4. Apply current flip to get flipped perspective corners
        5. Apply current rotation to get final rotated+flipped corners
        6. Convert to view space (centered coordinates)
        7. Convert to screen space (region pixels)

        Returns:
            List of (x, y) tuples in screen coordinates, or None if not stored
        """
        if not strip:
            return None

        # Try to get stored flip/rotation-independent offsets (CANONICAL SPACE)
        from ..operators.perspective_core import get_perspective_offsets_from_strip
        offsets = get_perspective_offsets_from_strip(strip)
        
        if not offsets or len(offsets) != 4:
            return None
        
        try:
            # Get current rotation for rotation compensation
            current_rotation = 0
            if hasattr(strip, 'transform') and hasattr(strip.transform, 'rotation'):
                current_rotation = strip.transform.rotation

            # Get CANONICAL VSE corners (unflipped+unrotated) without modifying the strip
            canonical_corners, (canonical_pivot_x, canonical_pivot_y), (scale_x, scale_y, flip_x, flip_y) = self._get_canonical_strip_geometry(strip, scene)
            canonical_pivot = (canonical_pivot_x, canonical_pivot_y)

            # Calculate canonical VSE dimensions for proportional offset conversion
            vse_width = canonical_corners[2].x - canonical_corners[0].x  # right - left
            vse_height = canonical_corners[1].y - canonical_corners[0].y  # top - bottom

            print(f"Debug: FLIP/ROTATION-INDEPENDENT LOADING")
            print(f"Debug: Current rotation: {math.degrees(current_rotation):.1f}°")
            print(f"Debug: Current flip: flip_x={flip_x}, flip_y={flip_y}")
            print(f"Debug: Current scale: ({scale_x:.3f}, {scale_y:.3f})")
            print(f"Debug: Canonical VSE dimensions: {vse_width:.1f} x {vse_height:.1f}")
            print(f"Debug: Canonical VSE corners: {[f'({c.x:.1f},{c.y:.1f})' for c in canonical_corners]}")
            print(f"Debug: Stored proportional offsets (canonical): {[f'({o.x:.3f},{o.y:.3f})' for o in offsets]}")

            # Convert proportional offsets to absolute offsets (as vectors, not positions)
            canonical_offset_vectors = []
            for proportional_offset in offsets:
                absolute_offset_x = proportional_offset.x * vse_width
                absolute_offset_y = proportional_offset.y * vse_height
                canonical_offset_vectors.append(Vector([absolute_offset_x, absolute_offset_y]))
                print(f"Debug: Proportional offset ({proportional_offset.x:.3f},{proportional_offset.y:.3f}) -> Absolute offset ({absolute_offset_x:.1f},{absolute_offset_y:.1f})")

            # Get current corners in flipped+rotated space
            from ..operators.perspective_core import get_strip_geometry_with_flip_support
            current_corners, (pivot_x, pivot_y), _ = get_strip_geometry_with_flip_support(strip, scene)

            # Remap corners to identity-based order
            if flip_x and flip_y:
                current_corners = [current_corners[2], current_corners[3], current_corners[0], current_corners[1]]
            elif flip_x:
                current_corners = [current_corners[3], current_corners[2], current_corners[1], current_corners[0]]
            elif flip_y:
                current_corners = [current_corners[1], current_corners[0], current_corners[3], current_corners[2]]

            # Rotate the canonical offset vectors to match current rotation
            rotated_offset_vectors = []
            for i, canonical_offset in enumerate(canonical_offset_vectors):
                angle = current_rotation
                if flip_x != flip_y:
                    angle = -angle

                cos_a = math.cos(angle)
                sin_a = math.sin(angle)
                rotated_offset_x = canonical_offset.x * cos_a - canonical_offset.y * sin_a
                rotated_offset_y = canonical_offset.x * sin_a + canonical_offset.y * cos_a

                rotated_offset_vectors.append(Vector([rotated_offset_x, rotated_offset_y]))
                print(f"Debug: Handle {i} - Canonical offset ({canonical_offset.x:.1f},{canonical_offset.y:.1f}) -> Rotated offset ({rotated_offset_x:.1f},{rotated_offset_y:.1f})")

            # Apply rotated offsets to current corners to get handle positions
            perspective_positions = []
            for i, (corner, offset_vector) in enumerate(zip(current_corners, rotated_offset_vectors)):
                handle_position = corner + offset_vector
                print(f"Debug: Handle {i} - Corner ({corner.x:.1f},{corner.y:.1f}) + Offset ({offset_vector.x:.1f},{offset_vector.y:.1f}) = Handle ({handle_position.x:.1f},{handle_position.y:.1f})")

                # Convert to view coordinates (VIEW SPACE - centered at origin)
                view_x = handle_position.x - res_x / 2
                view_y = handle_position.y - res_y / 2

                # Convert to screen coordinates (SCREEN SPACE - region pixels)
                screen_co = view2d.view_to_region(view_x, view_y, clip=False)

                print(f"Debug: Handle {i} - Strip: ({handle_position.x:.1f},{handle_position.y:.1f}) -> View: ({view_x:.1f},{view_y:.1f}) -> Screen: ({screen_co[0]:.1f},{screen_co[1]:.1f})")

                perspective_positions.append((screen_co[0], screen_co[1]))

            # Positions are already in identity-based order (Handle 0's position is at index 0, etc.)
            return perspective_positions
            
        except Exception as e:
            print(f"Warning: Could not retrieve stored perspective positions: {e}")
            return None
    
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

            # Draw corner number labels in red
            import blf
            font_id = 0
            for i, corner in enumerate(self._boundary_corners):
                blf.position(font_id, corner.x - 15, corner.y - 15, 0)
                blf.size(font_id, 16)
                blf.color(font_id, 1.0, 0.0, 0.0, 1.0)  # Red text
                blf.draw(font_id, f"C{i}")

        except Exception as e:
            pass
    
    def _draw_perspective_preview_lines(self, context):
        """Draw cyan lines connecting handles to show perspective distortion preview"""
        if len(self.gizmos) < 4:
            return
            
        try:
            # Get handle positions from gizmo matrices
            handle_positions = []
            for i in range(4):  # First 4 gizmos are corner handles
                if i < len(self.gizmos) and hasattr(self.gizmos[i], 'matrix_basis'):
                    pos = self.gizmos[i].matrix_basis.translation
                    handle_positions.append((pos.x, pos.y))
                else:
                    return  # Not enough handles
            
            # Draw cyan perspective preview lines connecting the handles
            perspective_color = (0.0, 1.0, 1.0, 0.6)  # Cyan with transparency
            
            line_shader = gpu.shader.from_builtin('UNIFORM_COLOR')
            gpu.state.line_width_set(1.5)  # Medium line width
            line_shader.bind()
            line_shader.uniform_float("color", perspective_color)
            
            # Create perspective quad outline (connecting corner handles)
            perspective_vertices = handle_positions + [handle_positions[0]]  # Close the quad
            
            batch = batch_for_shader(line_shader, 'LINE_STRIP', {"pos": perspective_vertices})
            batch.draw(line_shader)
            
            # Optional: Draw diagonal lines to show the distortion more clearly
            diagonal_color = (0.0, 1.0, 1.0, 0.3)  # More transparent cyan
            line_shader.uniform_float("color", diagonal_color)
            
            # Diagonal lines: 0->2 and 1->3
            diagonal_vertices = [
                handle_positions[0], handle_positions[2],  # Bottom-left to top-right
                handle_positions[1], handle_positions[3]   # Top-left to bottom-right
            ]
            
            diagonal_batch = batch_for_shader(line_shader, 'LINES', {"pos": diagonal_vertices})
            diagonal_batch.draw(line_shader)
            
            gpu.state.line_width_set(1.0)  # Reset line width
            
        except Exception as e:
            pass
    
    def _draw_perspective_grid_overlay(self, context):
        """Draw a subtle grid showing the perspective transformation effect"""
        if len(self.gizmos) < 4:
            return
        
        # Only draw grid during active dragging for performance
        is_dragging = any(hasattr(gz, '_is_dragging') and getattr(gz, '_is_dragging', False) for gz in self.gizmos[:4])
        if not is_dragging:
            return
            
        try:
            # Get current strip and homography matrix
            scene = context.scene
            if not scene.sequence_editor:
                return
                
            strip = scene.sequence_editor.active_strip
            if not strip:
                return
                
            # Get stored homography matrix
            from ..operators.perspective_core import get_perspective_matrix_from_strip
            homography = get_perspective_matrix_from_strip(strip)
            if not homography:
                return
            
            # Draw a 4x4 grid showing the perspective effect
            grid_color = (0.0, 1.0, 1.0, 0.2)  # Very transparent cyan
            
            line_shader = gpu.shader.from_builtin('UNIFORM_COLOR')
            gpu.state.line_width_set(1.0)
            line_shader.bind()
            line_shader.uniform_float("color", grid_color)
            
            # Create grid lines in original space, then transform them
            grid_lines = []
            divisions = 4
            
            # Get VSE boundary corners for grid base
            if not hasattr(self, '_boundary_corners') or len(self._boundary_corners) != 4:
                return
                
            boundary = self._boundary_corners
            
            # Vertical lines
            for i in range(divisions + 1):
                t = i / divisions
                # Interpolate along top and bottom edges
                top_point = (
                    boundary[1].x + t * (boundary[2].x - boundary[1].x),
                    boundary[1].y + t * (boundary[2].y - boundary[1].y)
                )
                bottom_point = (
                    boundary[0].x + t * (boundary[3].x - boundary[0].x),
                    boundary[0].y + t * (boundary[3].y - boundary[0].y)
                )
                grid_lines.extend([top_point, bottom_point])
            
            # Horizontal lines
            for i in range(divisions + 1):
                t = i / divisions
                # Interpolate along left and right edges
                left_point = (
                    boundary[0].x + t * (boundary[1].x - boundary[0].x),
                    boundary[0].y + t * (boundary[1].y - boundary[0].y)
                )
                right_point = (
                    boundary[3].x + t * (boundary[2].x - boundary[3].x),
                    boundary[3].y + t * (boundary[2].y - boundary[3].y)
                )
                grid_lines.extend([left_point, right_point])
            
            # Draw the grid
            batch = batch_for_shader(line_shader, 'LINES', {"pos": grid_lines})
            batch.draw(line_shader)
            
        except Exception as e:
            pass

    def _get_flip_aware_strip_position(self, handle_index, strip_corners, strip, scene, flip_x, flip_y):
        """
        Get handle position in strip coordinate space that properly follows flips.
        This works before rotation is applied, so rotation will be handled by existing pipeline.
        
        Logic:
        1. Get stored offset for this handle (relative to its original corner)
        2. Determine which corner this handle should follow when flipped  
        3. Apply the offset (flipped if necessary) to the target corner
        
        Args:
            handle_index: Which handle (0-3)
            strip_corners: Current VSE corners in strip coordinates (before screen conversion)
            strip: Blender strip
            scene: Blender scene
            flip_x, flip_y: Current flip states
            
        Returns:
            Vector: position in strip coordinate space
        """
        
        # Get stored perspective offsets
        from ..operators.perspective_core import get_perspective_offsets_from_strip
        offsets = get_perspective_offsets_from_strip(strip)
        
        if not offsets or len(offsets) != 4 or handle_index >= 4:
            # No stored offsets - use VSE corner as fallback
            if handle_index < len(strip_corners):
                corner = strip_corners[handle_index]
                print(f"Debug: Handle {handle_index} using strip corner fallback: ({corner.x:.1f},{corner.y:.1f})")
                return corner
            return Vector((0, 0))
        
        # Step 1: Determine which corner this handle should follow when flipped
        # Corner mapping: 0=bottom-left, 1=top-left, 2=top-right, 3=bottom-right
        target_corner_index = handle_index  # Default: handle follows its own corner
        
        if flip_x and not flip_y:
            # Horizontal flip: left↔right
            corner_remap = [3, 2, 1, 0]  # 0→3, 1→2, 2→1, 3→0
            target_corner_index = corner_remap[handle_index]
        elif not flip_x and flip_y:
            # Vertical flip: top↔bottom  
            corner_remap = [1, 0, 3, 2]  # 0→1, 1→0, 2→3, 3→2
            target_corner_index = corner_remap[handle_index]
        elif flip_x and flip_y:
            # Both flips: diagonal opposite
            corner_remap = [2, 3, 0, 1]  # 0→2, 1→3, 2→0, 3→1
            target_corner_index = corner_remap[handle_index]
        
        # Step 2: Get the offset for this handle (stored as proportional offset)
        offset = offsets[handle_index]
        
        # Step 3: Flip the offset values if necessary
        offset_x = offset.x
        offset_y = offset.y
        
        if flip_x:
            offset_x = -offset_x  # Flip X offset
        if flip_y:
            offset_y = -offset_y  # Flip Y offset
        
        # Step 4: Get current VSE dimensions for converting proportional to absolute offset
        vse_width = abs(strip_corners[2].x - strip_corners[0].x)  # right - left
        vse_height = abs(strip_corners[1].y - strip_corners[0].y)  # top - bottom
        
        # Step 5: Apply flipped offset to target corner in strip space
        if target_corner_index < len(strip_corners):
            target_corner = strip_corners[target_corner_index]
            
            # Convert proportional offset to absolute strip offset  
            absolute_offset_x = offset_x * vse_width
            absolute_offset_y = offset_y * vse_height
            
            final_position = Vector((
                target_corner.x + absolute_offset_x,
                target_corner.y + absolute_offset_y
            ))
            
            print(f"Debug: Handle {handle_index} -> Corner {target_corner_index}, offset ({offset_x:.3f},{offset_y:.3f}) -> strip ({final_position.x:.1f},{final_position.y:.1f})")
            return final_position
        
        # Fallback
        return strip_corners[handle_index] if handle_index < len(strip_corners) else Vector((0, 0))

    def _unflip_position(self, position, res_x, res_y, flip_x, flip_y):
        """
        Un-flip a position to get it into canonical (unflipped) space.
        This reverses the flip transformations applied by get_strip_geometry_with_flip_support.

        Args:
            position: Vector in flipped space
            res_x, res_y: Resolution (mirror happens around resolution, not pivot!)
            flip_x: Whether X is flipped
            flip_y: Whether Y is flipped

        Returns:
            Vector in unflipped space
        """
        x = position.x
        y = position.y

        # Reverse flip transformations
        # Blender mirrors around resolution: flipped_x = res_x - x
        # To reverse: x = res_x - flipped_x (same operation!)
        if flip_x:
            x = res_x - x
        if flip_y:
            y = res_y - y

        return Vector([x, y])

    def _apply_flip_to_position(self, position, res_x, res_y, flip_x, flip_y):
        """
        Apply flip to a position to get it into flipped space.
        This applies the same flip transformations as get_strip_geometry_with_flip_support.

        Args:
            position: Vector in unflipped space
            res_x, res_y: Resolution (mirror happens around resolution, not pivot!)
            flip_x: Whether to flip X
            flip_y: Whether to flip Y

        Returns:
            Vector in flipped space
        """
        x = position.x
        y = position.y

        # Apply flip transformations
        # Blender mirrors around resolution: flipped_x = res_x - x
        if flip_x:
            x = res_x - x
        if flip_y:
            y = res_y - y

        return Vector([x, y])

    def _get_canonical_strip_geometry(self, strip, scene):
        """
        Get strip geometry in canonical space (no rotation, no flip).
        This is the base geometry for flip/rotation-independent storage.

        Returns:
            Tuple of (corners, (pivot_x, pivot_y), (scale_x, scale_y, flip_x, flip_y))
        """
        # First get unrotated (but still flipped) geometry
        unrotated_corners, (pivot_x, pivot_y), (scale_x, scale_y, flip_x, flip_y) = self._get_unrotated_strip_geometry(strip, scene)

        # Then un-flip the corners to get canonical geometry
        res_x = scene.render.resolution_x
        res_y = scene.render.resolution_y
        canonical_corners = []

        for corner in unrotated_corners:
            canonical_corner = self._unflip_position(corner, res_x, res_y, flip_x, flip_y)
            canonical_corners.append(canonical_corner)

        # Also un-flip the pivot for canonical space
        # Blender flips pivot with: pivot_x = res_x - pivot_x
        # To reverse: same operation (it's symmetric)
        canonical_pivot_x = pivot_x
        canonical_pivot_y = pivot_y
        if flip_x:
            canonical_pivot_x = res_x - pivot_x
        if flip_y:
            canonical_pivot_y = res_y - pivot_y

        return canonical_corners, (canonical_pivot_x, canonical_pivot_y), (scale_x, scale_y, flip_x, flip_y)

    def _get_unrotated_strip_geometry(self, strip, scene):
        """
        Get strip geometry as if rotation was 0, without modifying the strip.
        NOTE: This still includes flip transformations!

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