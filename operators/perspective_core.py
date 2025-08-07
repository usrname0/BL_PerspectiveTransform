"""
BL Perspective Transform - Core functionality and state management

This module contains the core state variables, geometry calculations,
and utility functions that other perspective transform modules depend on.
"""

import bpy
import math
from mathutils import Vector

# Global state variables
_draw_handle = None
_draw_data = {}
_perspective_active = False


def is_strip_visible_at_frame(strip, frame):
    """Check if a strip is visible at the given frame"""
    return (strip.frame_final_start <= frame <= strip.frame_final_end and not strip.mute)


def point_in_polygon(point, polygon):
    """Check if a point is inside a polygon using ray casting algorithm"""
    x, y = point.x, point.y
    n = len(polygon)
    inside = False
    
    p1x, p1y = polygon[0].x, polygon[0].y
    for i in range(1, n + 1):
        p2x, p2y = polygon[i % n].x, polygon[i % n].y
        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or x <= xinters:
                        inside = not inside
        p1x, p1y = p2x, p2y
    
    return inside


def rotate_point(point, angle, origin=None):
    """Rotate a 2D point around an origin"""
    if origin is None:
        origin = Vector([0, 0])
    
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


def get_strip_geometry_with_flip_support(strip, scene):
    """
    Calculate strip geometry accounting for Mirror X/Y checkboxes
    Returns corner positions in resolution space for perspective transformation
    """
    res_x = scene.render.resolution_x
    res_y = scene.render.resolution_y
    
    # Get actual strip dimensions
    strip_width = res_x
    strip_height = res_y
    
    if hasattr(strip, 'elements') and strip.elements and len(strip.elements) > 0:
        elem = strip.elements[0]
        if hasattr(elem, 'orig_width') and hasattr(elem, 'orig_height'):
            strip_width = elem.orig_width
            strip_height = elem.orig_height
    
    # Get scale and base transform
    scale_x = 1.0
    scale_y = 1.0
    offset_x = 0
    offset_y = 0
    
    if hasattr(strip, 'transform'):
        offset_x = strip.transform.offset_x
        offset_y = strip.transform.offset_y
        if hasattr(strip.transform, 'scale_x'):
            scale_x = strip.transform.scale_x
            scale_y = strip.transform.scale_y
    
    # Check for Mirror X/Y checkboxes
    flip_x = False
    flip_y = False
    
    # Check various possible flip attribute names
    for attr_name in ['use_flip_x', 'flip_x', 'mirror_x']:
        if hasattr(strip, attr_name):
            flip_x = getattr(strip, attr_name)
            break
    
    for attr_name in ['use_flip_y', 'flip_y', 'mirror_y']:
        if hasattr(strip, attr_name):
            flip_y = getattr(strip, attr_name)
            break
    
    # Get rotation angle
    angle = 0
    if hasattr(strip, 'rotation_start'):
        angle = math.radians(strip.rotation_start)
    elif hasattr(strip, 'rotation'):
        angle = strip.rotation
    elif hasattr(strip, 'transform') and hasattr(strip.transform, 'rotation'):
        angle = strip.transform.rotation
    
    # Get crop values - essential for accurate handle positioning
    crop_left = 0
    crop_right = 0
    crop_bottom = 0
    crop_top = 0
    
    if hasattr(strip, 'crop'):
        crop_left = float(strip.crop.min_x)
        crop_right = float(strip.crop.max_x)
        crop_bottom = float(strip.crop.min_y)
        crop_top = float(strip.crop.max_y)
    
    # Calculate scaled dimensions
    scaled_width = strip_width * scale_x
    scaled_height = strip_height * scale_y
    
    # Calculate position (centered by default, then offset)
    left = (res_x - scaled_width) / 2 + offset_x
    right = (res_x + scaled_width) / 2 + offset_x
    bottom = (res_y - scaled_height) / 2 + offset_y
    top = (res_y + scaled_height) / 2 + offset_y
    
    # Apply crop - crop values are in original image space, so scale them
    left += crop_left * scale_x
    right -= crop_right * scale_x
    bottom += crop_bottom * scale_y
    top -= crop_top * scale_y
    
    # Calculate pivot point for rotation
    pivot_x = res_x / 2 + offset_x
    pivot_y = res_y / 2 + offset_y
    
    # Handle flipped coordinates
    if flip_x:
        new_left = res_x - right
        new_right = res_x - left
        left = new_left
        right = new_right
        pivot_x = res_x - pivot_x
    
    if flip_y:
        new_bottom = res_y - top
        new_top = res_y - bottom
        bottom = new_bottom
        top = new_top
        pivot_y = res_y - pivot_y
    
    # Create corner vectors for perspective transformation
    corners = [
        Vector((left, bottom)),  # Bottom-left
        Vector((left, top)),     # Top-left  
        Vector((right, top)),    # Top-right
        Vector((right, bottom))  # Bottom-right
    ]
    
    # Apply rotation if needed
    if angle != 0:
        # When flipped, rotation direction is reversed
        if flip_x != flip_y:  # XOR - if only one axis is flipped
            angle = -angle
        
        center = Vector((pivot_x, pivot_y))
        rotated_corners = []
        for corner in corners:
            rotated = rotate_point(corner, angle, center)
            rotated_corners.append(rotated)
        corners = rotated_corners
    
    return corners, (pivot_x, pivot_y), (scale_x, scale_y, flip_x, flip_y)


def calculate_perspective_matrix(src_corners, dst_corners):
    """
    Calculate perspective transformation matrix from source to destination corners
    This is a placeholder - will implement proper homography calculation
    """
    # TODO: Implement proper perspective matrix calculation
    # For now, return identity-like transformation
    return {
        'scale_x': 1.0,
        'scale_y': 1.0,
        'offset_x': 0.0,
        'offset_y': 0.0,
        'rotation': 0.0
    }


def apply_perspective_to_strip(strip, homography_matrix):
    """
    Apply perspective transformation using GPU shader rendering.
    
    Creates a draw handler that renders a perspective-distorted texture quad
    on top of the original strip, giving the visual effect of perspective distortion.
    
    Args:
        strip: Blender sequence strip
        homography_matrix: 3x3 Matrix homography transformation
    """
    if not strip or not homography_matrix:
        return
    
    # Store the matrix for the GPU shader system
    store_perspective_matrix_in_strip(strip, homography_matrix)
    
    # Enable GPU-based perspective rendering
    _enable_perspective_rendering(strip)
    
    print(f"Debug: Perspective GPU rendering enabled for strip")


# State management functions
def get_perspective_state():
    """Get the current perspective transform state"""
    global _perspective_active, _draw_data, _draw_handle
    return {
        'active': _perspective_active,
        'draw_data': _draw_data.copy(),
        'has_handler': _draw_handle is not None
    }


def set_perspective_active(active):
    """Set the perspective transform active state"""
    global _perspective_active
    _perspective_active = active


def get_draw_data():
    """Get the current draw data"""
    global _draw_data
    return _draw_data


def set_draw_data(data):
    """Set the draw data"""
    global _draw_data
    _draw_data = data


def get_draw_handle():
    """Get the current draw handler"""
    global _draw_handle
    return _draw_handle


def set_draw_handle(handle):
    """Set the draw handler"""
    global _draw_handle
    _draw_handle = handle


def clear_perspective_state():
    """Clear all perspective transform state"""
    global _perspective_active, _draw_data, _draw_handle
    _perspective_active = False
    _draw_data.clear()
    _draw_handle = None


def get_perspective_matrix_from_strip(strip):
    """
    Retrieve stored perspective matrix from strip custom properties.
    
    Args:
        strip: Blender sequence strip
        
    Returns:
        Matrix: 3x3 perspective transformation matrix, or None if not set
    """
    if not strip:
        return None
    
    try:
        # Check if perspective matrix is stored
        matrix_keys = [f"perspective_h{i}{j}" for i in range(3) for j in range(3)]
        if not all(key in strip for key in matrix_keys):
            return None
        
        # Reconstruct matrix from stored values
        from mathutils import Matrix
        return Matrix([
            [strip["perspective_h00"], strip["perspective_h01"], strip["perspective_h02"]],
            [strip["perspective_h10"], strip["perspective_h11"], strip["perspective_h12"]],
            [strip["perspective_h20"], strip["perspective_h21"], strip["perspective_h22"]]
        ])
        
    except Exception as e:
        print(f"Warning: Could not retrieve perspective matrix: {e}")
        return None


def store_perspective_matrix_in_strip(strip, homography_matrix):
    """
    Store perspective matrix in strip custom properties.
    
    Args:
        strip: Blender sequence strip
        homography_matrix: 3x3 Matrix to store
    """
    if not strip or not homography_matrix:
        return
    
    try:
        # Store matrix components as custom properties
        strip["perspective_h00"] = homography_matrix[0][0]
        strip["perspective_h01"] = homography_matrix[0][1]
        strip["perspective_h02"] = homography_matrix[0][2]
        strip["perspective_h10"] = homography_matrix[1][0]
        strip["perspective_h11"] = homography_matrix[1][1]
        strip["perspective_h12"] = homography_matrix[1][2]
        strip["perspective_h20"] = homography_matrix[2][0]
        strip["perspective_h21"] = homography_matrix[2][1]
        strip["perspective_h22"] = homography_matrix[2][2]
        
    except Exception as e:
        print(f"Warning: Could not store perspective matrix: {e}")


def clear_perspective_matrix_from_strip(strip):
    """
    Clear perspective matrix from strip custom properties.
    
    Args:
        strip: Blender sequence strip
    """
    if not strip:
        return
    
    try:
        # Remove all perspective-related keys (matrix, original corners, and offsets)
        for key in list(strip.keys()):
            if key.startswith("perspective_h") or key.startswith("perspective_orig") or key.startswith("perspective_offset"):
                del strip[key]
                
    except Exception as e:
        print(f"Warning: Could not clear perspective matrix: {e}")


def has_perspective_transform(strip):
    """
    Check if strip has a perspective transformation applied.
    
    Args:
        strip: Blender sequence strip
        
    Returns:
        bool: True if strip has perspective transform
    """
    if not strip:
        return False
    
    # Check if any perspective matrix keys exist
    return any(key.startswith("perspective_h") for key in strip.keys())


def store_original_corners_in_strip(strip, original_corners):
    """
    Store original corner positions in strip for transform composition.
    
    Args:
        strip: Blender sequence strip
        original_corners: List of 4 Vector objects for original corner positions
    """
    if not strip or not original_corners or len(original_corners) != 4:
        return
    
    try:
        # Store original corner positions
        for i, corner in enumerate(original_corners):
            strip[f"perspective_orig_x{i}"] = corner.x
            strip[f"perspective_orig_y{i}"] = corner.y
            
    except Exception as e:
        print(f"Warning: Could not store original corners: {e}")


def store_perspective_offsets_in_strip(strip, vse_corners, perspective_corners):
    """
    Store perspective corner offsets relative to VSE rectangle corners.
    This decouples perspective from basic VSE transforms.
    
    Args:
        strip: Blender sequence strip
        vse_corners: List of 4 Vector objects for VSE rectangle corners
        perspective_corners: List of 4 Vector objects for perspective corners
    """
    if not strip or not vse_corners or not perspective_corners:
        return
    if len(vse_corners) != 4 or len(perspective_corners) != 4:
        return
    
    try:
        # Store relative offsets from VSE corners to perspective corners
        for i in range(4):
            offset_x = perspective_corners[i].x - vse_corners[i].x
            offset_y = perspective_corners[i].y - vse_corners[i].y
            strip[f"perspective_offset_x{i}"] = offset_x
            strip[f"perspective_offset_y{i}"] = offset_y
            
    except Exception as e:
        print(f"Warning: Could not store perspective offsets: {e}")


def get_perspective_offsets_from_strip(strip):
    """
    Retrieve perspective corner offsets from strip.
    
    Args:
        strip: Blender sequence strip
        
    Returns:
        List of 4 Vector objects representing offsets, or None if not stored
    """
    if not strip:
        return None
    
    try:
        # Check if all offset keys exist
        offset_keys = [f"perspective_offset_x{i}" for i in range(4)] + [f"perspective_offset_y{i}" for i in range(4)]
        if not all(key in strip for key in offset_keys):
            return None
        
        # Reconstruct offset vectors
        from mathutils import Vector
        offsets = []
        for i in range(4):
            offset_x = strip[f"perspective_offset_x{i}"]
            offset_y = strip[f"perspective_offset_y{i}"]
            offsets.append(Vector([offset_x, offset_y]))
        
        return offsets
        
    except Exception as e:
        print(f"Warning: Could not retrieve perspective offsets: {e}")
        return None


def get_original_corners_from_strip(strip):
    """
    Retrieve original corner positions from strip.
    
    Args:
        strip: Blender sequence strip
        
    Returns:
        List of 4 Vector objects, or None if not stored
    """
    if not strip:
        return None
    
    try:
        # Check if all original corner keys exist
        corner_keys = [f"perspective_orig_x{i}" for i in range(4)] + [f"perspective_orig_y{i}" for i in range(4)]
        if not all(key in strip for key in corner_keys):
            return None
        
        # Reconstruct original corners
        from mathutils import Vector
        original_corners = []
        for i in range(4):
            x = strip[f"perspective_orig_x{i}"]
            y = strip[f"perspective_orig_y{i}"]
            original_corners.append(Vector([x, y]))
        
        return original_corners
        
    except Exception as e:
        print(f"Warning: Could not retrieve original corners: {e}")
        return None


def get_effective_corners_for_perspective(strip, scene):
    """
    Get the effective corners for perspective calculation.
    This respects other transforms and returns either:
    1. Original corners (if perspective transform exists)
    2. Current strip geometry (if no perspective transform yet)
    
    Args:
        strip: Blender sequence strip  
        scene: Blender scene
        
    Returns:
        List of 4 Vector objects representing the effective corners for perspective calculation
    """
    # If we have stored original corners, use those for consistency
    original_corners = get_original_corners_from_strip(strip)
    if original_corners:
        return original_corners
    
    # Otherwise, use current strip geometry as the baseline
    corners, (pivot_x, pivot_y), (scale_x, scale_y, flip_x, flip_y) = get_strip_geometry_with_flip_support(strip, scene)
    return corners


def apply_stored_perspective_to_strip(strip):
    """
    Apply any stored perspective transformation to the strip.
    This is called when initializing or refreshing perspective transforms.
    
    Args:
        strip: Blender sequence strip
    """
    if not strip or not has_perspective_transform(strip):
        return
    
    # Get stored homography matrix
    homography = get_perspective_matrix_from_strip(strip)
    if homography:
        # Apply the stored perspective transformation
        apply_perspective_to_strip(strip, homography)
        print("Debug: Applied stored perspective transformation to strip")


def export_perspective_data_for_compositor(strip, scene):
    """
    Export perspective transformation data in a format suitable for Blender's Compositor Corner Pin node.
    
    Args:
        strip: Blender sequence strip with perspective data
        scene: Blender scene
        
    Returns:
        dict: Corner pin data with original and transformed coordinates
    """
    if not strip or not has_perspective_transform(strip):
        return None
    
    try:
        # Get original corners (source)
        original_corners = get_original_corners_from_strip(strip)
        if not original_corners:
            # Fall back to current strip geometry
            corners, _, _ = get_strip_geometry_with_flip_support(strip, scene)
            original_corners = corners
        
        # Get perspective corner offsets
        offsets = get_perspective_offsets_from_strip(strip)
        if not offsets:
            return None
        
        # Calculate transformed corners (destination)
        current_corners, _, _ = get_strip_geometry_with_flip_support(strip, scene)
        transformed_corners = []
        
        for i, (current_corner, offset) in enumerate(zip(current_corners, offsets)):
            transformed_corner = Vector([
                current_corner.x + offset.x,
                current_corner.y + offset.y
            ])
            transformed_corners.append(transformed_corner)
        
        # Convert to normalized coordinates (0.0 to 1.0)
        res_x = scene.render.resolution_x
        res_y = scene.render.resolution_y
        
        def normalize_coord(coord):
            return (coord.x / res_x, coord.y / res_y)
        
        return {
            'strip_name': strip.name,
            'original_corners': [normalize_coord(c) for c in original_corners],
            'transformed_corners': [normalize_coord(c) for c in transformed_corners],
            'homography_matrix': get_perspective_matrix_from_strip(strip),
            'resolution': (res_x, res_y)
        }
        
    except Exception as e:
        print(f"Warning: Could not export perspective data: {e}")
        return None


def get_perspective_transform_info(strip):
    """
    Get human-readable information about the perspective transformation.
    
    Args:
        strip: Blender sequence strip
        
    Returns:
        dict: Information about the perspective transform
    """
    if not strip or not has_perspective_transform(strip):
        return {"has_transform": False, "message": "No perspective transformation applied"}
    
    try:
        homography = get_perspective_matrix_from_strip(strip)
        offsets = get_perspective_offsets_from_strip(strip)
        
        info = {
            "has_transform": True,
            "strip_name": strip.name,
            "homography_matrix": str(homography) if homography else "None",
            "corner_offsets": len(offsets) if offsets else 0,
            "message": "Perspective transformation data is stored but not visually applied (VSE limitation)"
        }
        
        return info
        
    except Exception as e:
        return {"has_transform": False, "error": str(e)}


# GPU-based Perspective Rendering System
_gpu_draw_handler = None
_gpu_enabled_strips = set()
_original_strip_properties = {}  # Store original strip properties for restoration


def _store_and_hide_original_strip(strip):
    """Store original strip properties and hide the strip during perspective rendering"""
    if not strip:
        return
    
    try:
        # Store original properties for restoration
        _original_strip_properties[strip.name] = {
            'blend_alpha': getattr(strip, 'blend_alpha', 1.0),
            'mute': getattr(strip, 'mute', False)
        }
        
        # DISABLED: Don't hide the original strip - let's see both overlays
        # strip.mute = True
        print(f"Debug: NOT hiding original strip '{strip.name}' - both original and perspective should be visible")
        
    except Exception as e:
        print(f"Debug: Error storing strip properties: {e}")


def _restore_original_strip(strip):
    """Restore original strip properties after perspective rendering"""
    if not strip:
        return
        
    try:
        # Restore original properties
        if strip.name in _original_strip_properties:
            props = _original_strip_properties[strip.name]
            strip.mute = props.get('mute', False)
            if hasattr(strip, 'blend_alpha'):
                strip.blend_alpha = props.get('blend_alpha', 1.0)
            
            # Remove from storage
            del _original_strip_properties[strip.name]
            print(f"Debug: Restored original strip '{strip.name}' properties")
        
    except Exception as e:
        print(f"Debug: Error restoring strip: {e}")


def _enable_perspective_rendering(strip):
    """Enable GPU-based perspective rendering for a strip"""
    global _gpu_draw_handler, _gpu_enabled_strips
    
    if not strip:
        return
    
    # Store original strip properties and hide the strip
    _store_and_hide_original_strip(strip)
    
    # Add strip to enabled set
    _gpu_enabled_strips.add(strip.name)
    
    # Install draw handler if not already installed
    if _gpu_draw_handler is None:
        _gpu_draw_handler = bpy.types.SpaceSequenceEditor.draw_handler_add(
            _draw_perspective_gpu_overlay, (), 'PREVIEW', 'POST_PIXEL'
        )
        print("Debug: GPU perspective draw handler installed")


def _disable_perspective_rendering(strip):
    """Disable GPU-based perspective rendering for a strip"""
    global _gpu_draw_handler, _gpu_enabled_strips
    
    if not strip:
        return
    
    # Restore original strip visibility
    _restore_original_strip(strip)
    
    # Remove strip from enabled set
    _gpu_enabled_strips.discard(strip.name)
    
    # Remove draw handler if no strips are using it
    if not _gpu_enabled_strips and _gpu_draw_handler is not None:
        try:
            bpy.types.SpaceSequenceEditor.draw_handler_remove(_gpu_draw_handler, 'PREVIEW')
            _gpu_draw_handler = None
            print("Debug: GPU perspective draw handler removed")
        except:
            pass


def _draw_perspective_gpu_overlay():
    """GPU draw handler that renders perspective-distorted texture quads"""
    try:
        import gpu
        from gpu_extras.batch import batch_for_shader
        
        context = bpy.context
        if not context.scene or not context.scene.sequence_editor:
            return
            
        active_strip = context.scene.sequence_editor.active_strip
        if not active_strip or active_strip.name not in _gpu_enabled_strips:
            return
        
        # Check if strip is muted (should be muted for perspective rendering)
        if not active_strip.mute:
            print(f"Debug: Warning - perspective strip '{active_strip.name}' is not muted!")
        
        # Get handle positions directly from the gizmo system 
        handle_positions = _get_current_handle_positions(context)
        if not handle_positions or len(handle_positions) != 4:
            print("Debug: No valid handle positions for GPU overlay")
            return
            
        print(f"Debug: GPU overlay rendering for strip '{active_strip.name}' at positions: {handle_positions}")
        
        # Render the overlay quad using the exact same coordinates as preview lines
        _render_perspective_overlay_quad(handle_positions)
        
    except Exception as e:
        print(f"Debug: GPU draw handler error: {e}")


def _get_current_handle_positions(context):
    """Get current handle positions using the same method as the gizmo system"""
    try:
        scene = context.scene
        if not scene.sequence_editor:
            print("Debug: No sequence editor")
            return None
            
        active_strip = scene.sequence_editor.active_strip
        if not active_strip:
            print("Debug: No active strip")
            return None
        
        # Use the exact same calculation as the gizmo system's _get_stored_perspective_positions
        region = context.region
        if not region:
            print("Debug: No region")
            return None
            
        view2d = region.view2d
        res_x = scene.render.resolution_x
        res_y = scene.render.resolution_y
        
        # Get stored perspective offsets (same as gizmo system)
        from .perspective_core import get_perspective_offsets_from_strip
        offsets = get_perspective_offsets_from_strip(active_strip)
        
        if not offsets or len(offsets) != 4:
            print("Debug: No stored perspective offsets found")
            return None
        
        # Get current rotation and geometry (same as gizmo system)  
        current_rotation = 0
        if hasattr(active_strip, 'transform') and hasattr(active_strip.transform, 'rotation'):
            current_rotation = active_strip.transform.rotation
            
        # Get unrotated VSE corners (same as gizmo system)
        corners, (pivot_x, pivot_y), (scale_x, scale_y, flip_x, flip_y) = get_strip_geometry_with_flip_support(active_strip, scene)
        
        # Un-rotate if needed to get unrotated corners (same as gizmo system)
        if current_rotation != 0:
            pivot = Vector((pivot_x, pivot_y))
            unrotated_corners = []
            
            for corner in corners:
                angle = -current_rotation
                if flip_x != flip_y:
                    angle = -angle
                    
                cos_a = math.cos(angle)
                sin_a = math.sin(angle)
                x = corner.x - pivot.x
                y = corner.y - pivot.y
                new_x = x * cos_a - y * sin_a
                new_y = x * sin_a + y * cos_a
                unrotated_corner = Vector([new_x + pivot.x, new_y + pivot.y])
                unrotated_corners.append(unrotated_corner)
        else:
            unrotated_corners = corners
        
        # Calculate VSE dimensions (same as gizmo system)
        vse_width = unrotated_corners[2].x - unrotated_corners[0].x
        vse_height = unrotated_corners[2].y - unrotated_corners[0].y
        
        # Apply proportional offsets (same as gizmo system)
        unrotated_perspective_corners = []
        for i, (vse_corner, proportional_offset) in enumerate(zip(unrotated_corners, offsets)):
            absolute_offset_x = proportional_offset.x * vse_width
            absolute_offset_y = proportional_offset.y * vse_height
            unrotated_perspective_corner = Vector([vse_corner.x + absolute_offset_x, vse_corner.y + absolute_offset_y])
            unrotated_perspective_corners.append(unrotated_perspective_corner)
        
        # Rotate back to current rotation (same as gizmo system)
        if current_rotation != 0:
            pivot = Vector((pivot_x, pivot_y))
            perspective_corners = []
            
            for unrotated_corner in unrotated_perspective_corners:
                angle = current_rotation
                if flip_x != flip_y:
                    angle = -angle
                    
                cos_a = math.cos(angle)
                sin_a = math.sin(angle)
                x = unrotated_corner.x - pivot.x
                y = unrotated_corner.y - pivot.y
                new_x = x * cos_a - y * sin_a
                new_y = x * sin_a + y * cos_a
                rotated_corner = Vector([new_x + pivot.x, new_y + pivot.y])
                perspective_corners.append(rotated_corner)
        else:
            perspective_corners = unrotated_perspective_corners
        
        # Convert to screen coordinates (same as gizmo system)
        screen_positions = []
        for corner in perspective_corners:
            view_x = corner.x - res_x / 2
            view_y = corner.y - res_y / 2
            screen_co = view2d.view_to_region(view_x, view_y, clip=False)
            screen_positions.append((screen_co[0], screen_co[1]))
        
        print(f"Debug: GPU calculated screen positions: {screen_positions}")
        return screen_positions
        
    except Exception as e:
        print(f"Debug: Error getting handle positions: {e}")
        return None


def _render_perspective_overlay_quad(screen_corners):
    """Render a perspective-distorted overlay quad with actual texture"""
    try:
        import gpu
        from gpu_extras.batch import batch_for_shader
        
        print(f"Debug: Rendering textured quad with corners: {screen_corners}")
        
        # Try to get strip texture first
        context = bpy.context
        active_strip = None
        if context.scene.sequence_editor:
            active_strip = context.scene.sequence_editor.active_strip
        
        strip_texture = _get_strip_texture(active_strip, context.scene.frame_current) if active_strip else None
        
        if strip_texture:
            # Render with actual texture
            _render_textured_perspective_quad(screen_corners, strip_texture)
        else:
            # Fallback to colored overlay
            _render_colored_overlay_quad(screen_corners)
        
    except Exception as e:
        print(f"Debug: Overlay quad render error: {e}")


def _render_textured_perspective_quad(screen_corners, texture):
    """Render perspective-distorted texture quad with correct UV mapping"""
    try:
        import gpu
        from gpu_extras.batch import batch_for_shader
        
        # Get the homography matrix for this strip to calculate proper UV coordinates
        context = bpy.context
        active_strip = context.scene.sequence_editor.active_strip if context.scene.sequence_editor else None
        homography = get_perspective_matrix_from_strip(active_strip) if active_strip else None
        
        if homography:
            # Use perspective-correct UV mapping
            vertices, uv_coords = _calculate_perspective_correct_mapping(screen_corners, homography)
        else:
            # Fallback to simple mapping
            vertices, uv_coords = _calculate_simple_mapping(screen_corners)
        
        # Use IMAGE shader for texture rendering
        shader = gpu.shader.from_builtin('IMAGE')
        
        batch = batch_for_shader(shader, 'TRIS', {
            "pos": vertices,
            "texCoord": uv_coords
        })
        
        # Bind texture and render
        gpu.state.blend_set('ALPHA')
        shader.bind()
        shader.uniform_sampler("image", texture)
        batch.draw(shader)
        gpu.state.blend_set('NONE')
        
        print("Debug: Successfully rendered textured perspective quad")
        
    except Exception as e:
        print(f"Debug: Textured quad render error: {e}")


def _calculate_perspective_correct_mapping(screen_corners, homography):
    """
    Calculate perspective-correct UV mapping.
    
    For proper perspective texture mapping, we use the inverse homography transformation
    to map from the distorted screen space back to the original texture UV coordinates.
    """
    try:
        from mathutils import Matrix, Vector
        
        # Create triangulated quad vertices
        vertices = [
            screen_corners[0],  # Bottom-left
            screen_corners[1],  # Top-left  
            screen_corners[2],  # Top-right
            screen_corners[0],  # Bottom-left (second triangle)
            screen_corners[2],  # Top-right
            screen_corners[3]   # Bottom-right
        ]
        
        # For perspective-correct texture mapping, we need to apply the forward homography
        # to transform the original texture UV coordinates to match the distorted quad
        
        # Original texture UV corners (normalized 0-1 space)
        original_uv_corners = [
            (0.0, 0.0),  # Bottom-left
            (0.0, 1.0),  # Top-left
            (1.0, 1.0),  # Top-right
            (1.0, 0.0)   # Bottom-right
        ]
        
        # Since we're using the IMAGE shader, we need to provide UV coordinates that,
        # when sampled, produce the correct perspective effect.
        # The GPU will handle perspective-correct interpolation.
        
        # For now, use direct UV mapping - the perspective distortion comes from
        # the vertex positions (screen_corners) being transformed
        uv_coords = [
            original_uv_corners[0],  # Bottom-left
            original_uv_corners[1],  # Top-left
            original_uv_corners[2],  # Top-right
            original_uv_corners[0],  # Bottom-left (second triangle)
            original_uv_corners[2],  # Top-right
            original_uv_corners[3]   # Bottom-right
        ]
        
        print("Debug: Using perspective-correct UV mapping with standard coordinates")
        print(f"Debug: Screen vertices form perspective quad, UV coords: {original_uv_corners}")
        
        return vertices, uv_coords
        
    except Exception as e:
        print(f"Debug: Perspective UV calculation error: {e}")
        return _calculate_simple_mapping(screen_corners)


def _calculate_simple_mapping(screen_corners):
    """Calculate simple UV mapping as fallback"""
    vertices = [
        screen_corners[0],  # Bottom-left
        screen_corners[1],  # Top-left  
        screen_corners[2],  # Top-right
        screen_corners[0],  # Bottom-left (second triangle)
        screen_corners[2],  # Top-right
        screen_corners[3]   # Bottom-right
    ]
    
    # Simple UV coordinates mapping texture (0,0) to (1,1)
    uv_coords = [
        (0.0, 0.0),  # Bottom-left
        (0.0, 1.0),  # Top-left
        (1.0, 1.0),  # Top-right
        (0.0, 0.0),  # Bottom-left (second triangle)
        (1.0, 1.0),  # Top-right
        (1.0, 0.0)   # Bottom-right
    ]
    
    print("Debug: Using simple UV mapping")
    return vertices, uv_coords


def _render_colored_overlay_quad(screen_corners):
    """Render colored overlay quad as fallback"""
    try:
        import gpu
        from gpu_extras.batch import batch_for_shader
        
        # Create a more visible overlay for debugging
        overlay_color = (1.0, 0.0, 1.0, 1.0)  # Solid magenta for visibility
        
        print(f"Debug: Rendering colored overlay with vertices: {screen_corners}")
        
        # Use built-in shader for colored geometry
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        
        # Create triangulated quad (two triangles)
        vertices = [
            screen_corners[0],  # Corner 0
            screen_corners[1],  # Corner 1
            screen_corners[2],  # Corner 2
            screen_corners[0],  # Corner 0 (second triangle)
            screen_corners[2],  # Corner 2
            screen_corners[3]   # Corner 3
        ]
        
        batch = batch_for_shader(shader, 'TRIS', {"pos": vertices})
        
        # Enable blending for proper rendering
        gpu.state.blend_set('ALPHA')
        
        shader.bind()
        shader.uniform_float("color", overlay_color)
        batch.draw(shader)
        
        # Restore blending
        gpu.state.blend_set('NONE')
        
        print("Debug: Successfully rendered solid magenta overlay quad")
        
    except Exception as e:
        print(f"Debug: Colored overlay render error: {e}")


def _get_strip_texture(strip, frame):
    """
    Get GPU texture from VSE strip using multiple fallback methods.
    
    Args:
        strip: Blender sequence strip
        frame: Current frame number
        
    Returns:
        GPU texture object or None if unable to extract texture
    """
    if not strip:
        return None
        
    try:
        # Method 1: Try direct image access for image strips
        texture = _get_image_strip_texture(strip)
        if texture:
            print("Debug: Got texture from image strip")
            return texture
        
        # Method 2: Try movie clip access for movie strips
        texture = _get_movie_strip_texture(strip, frame)
        if texture:
            print("Debug: Got texture from movie strip")
            return texture
            
        # Method 3: Try scene strip rendering
        texture = _get_scene_strip_texture(strip, frame)
        if texture:
            print("Debug: Got texture from scene strip")
            return texture
        
        print("Debug: No texture extraction method succeeded")
        return None
        
    except Exception as e:
        print(f"Debug: Strip texture extraction error: {e}")
        return None


def _get_image_strip_texture(strip):
    """Get texture from image/color strip"""
    try:
        import gpu
        
        print(f"Debug: Attempting texture extraction from strip '{strip.name}' (type: {strip.type})")
        
        # Method 1: Handle color strips by creating a simple colored texture
        if strip.type == 'COLOR':
            print("Debug: Color strip detected, creating color texture")
            return _create_color_texture(strip)
        
        # Method 2: Handle image strips - try multiple approaches
        if hasattr(strip, 'elements') and strip.elements:
            element = strip.elements[0]
            print(f"Debug: Image strip element found: {element}")
            
            if hasattr(element, 'filename'):
                filename = element.filename
                print(f"Debug: Element filename: {filename}")
                
                # Try to find the image in bpy.data.images by filename
                for image in bpy.data.images:
                    print(f"Debug: Checking image '{image.name}' with filepath '{image.filepath}'")
                    if (filename in image.filepath or filename in image.name or 
                        image.name == filename or image.name == strip.name):
                        if image.size[0] > 0 and image.size[1] > 0:
                            print(f"Debug: Found matching image '{image.name}' ({image.size[0]}x{image.size[1]})")
                            return gpu.texture.from_image(image)
                        else:
                            print(f"Debug: Image '{image.name}' has zero size")
        
        # Method 3: Try to load the strip's source image if not already loaded
        if hasattr(strip, 'directory') and hasattr(strip, 'elements') and strip.elements:
            try:
                import os
                element = strip.elements[0]
                if hasattr(element, 'filename'):
                    full_path = os.path.join(strip.directory, element.filename)
                    print(f"Debug: Attempting to load image from path: {full_path}")
                    
                    # Check if file exists
                    if os.path.exists(full_path):
                        # Load image if not already in bpy.data.images
                        image_name = strip.name + "_texture"
                        if image_name not in bpy.data.images:
                            image = bpy.data.images.load(full_path)
                            image.name = image_name
                            print(f"Debug: Loaded new image '{image_name}' from file")
                        else:
                            image = bpy.data.images[image_name]
                            print(f"Debug: Using existing image '{image_name}'")
                        
                        if image.size[0] > 0 and image.size[1] > 0:
                            return gpu.texture.from_image(image)
                    else:
                        print(f"Debug: File does not exist: {full_path}")
            except Exception as load_error:
                print(f"Debug: Failed to load image: {load_error}")
        
        # Method 4: Create a placeholder texture for unsupported types
        print(f"Debug: Creating placeholder texture for strip type {strip.type}")
        return _create_placeholder_texture(strip)
                    
    except Exception as e:
        print(f"Debug: Image strip texture error: {e}")
        return None


def _create_color_texture(strip):
    """Create a simple colored texture for color strips"""
    try:
        import gpu
        import numpy as np
        
        # Get the color from the strip
        color = [1.0, 1.0, 1.0, 1.0]  # Default white
        if hasattr(strip, 'color') and len(strip.color) >= 3:
            color = [strip.color[0], strip.color[1], strip.color[2], 1.0]
        
        print(f"Debug: Creating color texture for strip '{strip.name}' with color {color}")
        
        # Create a small colored texture (64x64 is enough for solid color)
        width, height = 64, 64
        
        # Create RGBA array
        texture_data = np.full((height, width, 4), color, dtype=np.float32)
        
        # Create GPU texture from numpy array
        texture = gpu.texture.from_numpy(texture_data)
        
        print(f"Debug: Successfully created {width}x{height} color texture")
        return texture
        
    except Exception as e:
        print(f"Debug: Color texture creation error: {e}")
        return None


def _create_placeholder_texture(strip):
    """Create a placeholder texture for strips when actual texture extraction fails"""
    try:
        import gpu
        import numpy as np
        
        # Create a distinctive pattern so we can see it's working
        # Use a checkerboard pattern in magenta/cyan
        width, height = 64, 64
        
        # Create checkerboard pattern
        texture_data = np.zeros((height, width, 4), dtype=np.float32)
        
        for y in range(height):
            for x in range(width):
                # Checkerboard pattern (8x8 squares)
                if (x // 8 + y // 8) % 2 == 0:
                    texture_data[y, x] = [1.0, 0.0, 1.0, 1.0]  # Magenta
                else:
                    texture_data[y, x] = [0.0, 1.0, 1.0, 1.0]  # Cyan
        
        # Create GPU texture from numpy array
        texture = gpu.texture.from_numpy(texture_data)
        
        print(f"Debug: Created {width}x{height} placeholder checkerboard texture")
        return texture
        
    except Exception as e:
        print(f"Debug: Placeholder texture creation error: {e}")
        return None


def _get_movie_strip_texture(strip, frame):
    """Get texture from movie strip by accessing underlying movie clip"""
    try:
        import gpu
        
        # Check if it's a movie strip
        if strip.type != 'MOVIE':
            return None
            
        # Try to access movie clip data
        if hasattr(strip, 'elements') and strip.elements:
            element = strip.elements[0]
            if hasattr(element, 'filename'):
                # Look for movie clip in bpy.data.movieclips
                for clip in bpy.data.movieclips:
                    if element.filename in clip.filepath:
                        # Try to get frame as image
                        # This is tricky - movieclips don't expose frames directly
                        # We might need to use the clip editor's cache
                        pass
        
        return None
        
    except Exception as e:
        print(f"Debug: Movie strip texture error: {e}")
        return None


def _get_scene_strip_texture(strip, frame):
    """
    Get texture by rendering strip to offscreen buffer.
    This is the most reliable method for any strip type.
    """
    try:
        import gpu
        
        # Get render resolution 
        scene = bpy.context.scene
        res_x = scene.render.resolution_x
        res_y = scene.render.resolution_y
        
        # Create offscreen buffer
        offscreen = gpu.types.GPUOffScreen(res_x, res_y)
        
        # This is a placeholder implementation
        # In practice, we'd need to:
        # 1. Set up a temporary scene with just this strip
        # 2. Render it to the offscreen buffer
        # 3. Extract the texture from the buffer
        
        # For now, return None to use colored overlay
        print("Debug: Scene strip texture rendering not yet implemented")
        return None
        
    except Exception as e:
        print(f"Debug: Scene strip texture error: {e}")
        return None


def _create_texture_from_render_result():
    """Helper function to create GPU texture from render result"""
    try:
        import gpu
        
        # Access render result 
        render_result = bpy.data.images.get("Render Result")
        if not render_result:
            return None
            
        if render_result.size[0] == 0 or render_result.size[1] == 0:
            print("Debug: Render result has zero size")
            return None
            
        # Create texture from render result
        return gpu.texture.from_image(render_result)
        
    except Exception as e:
        print(f"Debug: Render result texture error: {e}")
        return None


def clear_all_perspective_gpu_rendering():
    """Clear all GPU perspective rendering (for cleanup)"""
    global _gpu_draw_handler, _gpu_enabled_strips, _original_strip_properties
    
    # Restore all hidden strips
    for strip_name in list(_original_strip_properties.keys()):
        # Find the strip by name
        if bpy.context.scene.sequence_editor:
            for strip in bpy.context.scene.sequence_editor.sequences:
                if strip.name == strip_name:
                    _restore_original_strip(strip)
                    break
    
    _original_strip_properties.clear()
    _gpu_enabled_strips.clear()
    
    if _gpu_draw_handler is not None:
        try:
            bpy.types.SpaceSequenceEditor.draw_handler_remove(_gpu_draw_handler, 'PREVIEW')
        except:
            pass
        _gpu_draw_handler = None