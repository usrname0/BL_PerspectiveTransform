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
_offscreen_buffers = {}  # Cache offscreen buffers per resolution
_transformed_images = {}  # Cache transformed images per strip


def _enable_perspective_rendering(strip):
    """Enable GPU-based perspective rendering for a strip"""
    global _gpu_draw_handler, _gpu_enabled_strips
    
    if not strip:
        return
    
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
    """GPU draw handler that renders perspective-distorted overlay quads"""
    try:
        # Get current context
        context = bpy.context
        if not context:
            return

        # Get current handle positions in screen coordinates
        screen_positions = _get_current_handle_positions(context)

        if screen_positions and len(screen_positions) == 4:
            # Try to get the strip texture
            scene = context.scene
            strip = None
            if scene and scene.sequence_editor:
                strip = scene.sequence_editor.active_strip

            texture = None
            if strip:
                texture = _get_strip_texture(strip, context)

            # Render the perspective overlay quad with texture (or fallback to cyan overlay)
            _render_perspective_overlay_quad(screen_positions, texture)

    except Exception as e:
        print(f"Debug: GPU overlay draw error: {e}")


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

        # CRITICAL: Remap corners from position-based to identity-based order (same as gizmo refresh())
        # get_strip_geometry_with_flip_support returns corners in POSITION-based order
        # (always [bottom-left, top-left, top-right, bottom-right] positionally)
        # But we need IDENTITY-based order (Corner 0, Corner 1, Corner 2, Corner 3)
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


def _get_or_create_offscreen_buffer(width, height):
    """Get or create an offscreen buffer for rendering"""
    global _offscreen_buffers

    key = (width, height)

    # Check if we have a cached buffer
    if key in _offscreen_buffers:
        return _offscreen_buffers[key]

    try:
        import gpu

        # Create offscreen buffer
        offscreen = gpu.types.GPUOffScreen(width, height)
        _offscreen_buffers[key] = offscreen

        print(f"Debug: Created offscreen buffer {width}x{height}")
        return offscreen

    except Exception as e:
        print(f"Debug: Error creating offscreen buffer: {e}")
        return None


def _render_perspective_to_offscreen(strip, context, screen_corners, texture):
    """
    Render perspective-transformed texture to an offscreen buffer.
    Returns a rendered image that can be displayed in VSE.
    """
    try:
        import gpu
        from gpu_extras.batch import batch_for_shader
        from mathutils import Matrix
        import numpy as np

        if not texture:
            return None

        # Get render resolution for the offscreen buffer
        scene = context.scene
        width = scene.render.resolution_x
        height = scene.render.resolution_y

        # Get or create offscreen buffer
        offscreen = _get_or_create_offscreen_buffer(width, height)
        if not offscreen:
            return None

        # Bind the offscreen buffer
        with offscreen.bind():
            # Clear the buffer
            gpu.state.clear(color=(0.0, 0.0, 0.0, 0.0))

            # Set up viewport
            gpu.state.viewport_set(0, 0, width, height)

            # Get the perspective shader
            shader = _get_perspective_correct_shader()
            if not shader:
                return None

            # Convert screen corners to render resolution coordinates
            # Screen corners are in viewport space, we need to map to render resolution
            region = context.region
            view2d = region.view2d

            # Map screen corners back to strip space, then to normalized [0,1] coordinates
            render_corners = []
            res_x = scene.render.resolution_x
            res_y = scene.render.resolution_y

            for corner in screen_corners:
                # Convert screen to view space
                view_pos = view2d.region_to_view(corner[0], corner[1])

                # Convert view to strip space
                strip_x = view_pos[0] + res_x / 2
                strip_y = view_pos[1] + res_y / 2

                # Normalize to [0, res] coordinates for rendering
                render_corners.append((strip_x, strip_y))

            # Create vertices for rendering (full render resolution quad)
            vertices = [
                render_corners[0], render_corners[1], render_corners[2],  # Triangle 1
                render_corners[0], render_corners[2], render_corners[3]   # Triangle 2
            ]

            batch = batch_for_shader(shader, 'TRIS', {"pos": vertices})

            # Set up projection for render resolution
            view_matrix = Matrix.Identity(4)
            projection_matrix = Matrix.OrthoProjection('XY', 4)
            projection_matrix[0][0] = 2.0 / width
            projection_matrix[1][1] = 2.0 / height
            projection_matrix[0][3] = -1.0
            projection_matrix[1][3] = -1.0

            mvp_matrix = projection_matrix @ view_matrix

            # Disable blending for opaque rendering
            gpu.state.blend_set('NONE')

            # Bind shader and set uniforms
            shader.bind()
            shader.uniform_sampler("image", texture)
            shader.uniform_float("ModelViewProjectionMatrix", mvp_matrix)
            shader.uniform_float("corner0", (float(render_corners[0][0]), float(render_corners[0][1])))
            shader.uniform_float("corner1", (float(render_corners[1][0]), float(render_corners[1][1])))
            shader.uniform_float("corner2", (float(render_corners[2][0]), float(render_corners[2][1])))
            shader.uniform_float("corner3", (float(render_corners[3][0]), float(render_corners[3][1])))

            # Draw
            batch.draw(shader)

        # Read pixels from offscreen buffer
        buffer = offscreen.texture_color.read()

        # Convert buffer to numpy array
        pixels = np.frombuffer(buffer, dtype=np.float32)

        # Create or update image in bpy.data.images
        image_name = f"PerspectiveTransform_{strip.name}"

        if image_name in bpy.data.images:
            img = bpy.data.images[image_name]
            # Check if size matches
            if img.size[0] != width or img.size[1] != height:
                bpy.data.images.remove(img)
                img = bpy.data.images.new(image_name, width, height, alpha=True)
        else:
            img = bpy.data.images.new(image_name, width, height, alpha=True)

        # Update image pixels
        img.pixels[:] = pixels
        img.update()

        print(f"Debug: Rendered perspective transform to image {image_name}")
        return img

    except Exception as e:
        print(f"Debug: Error rendering perspective to offscreen: {e}")
        import traceback
        traceback.print_exc()
        return None


def _get_strip_texture(strip, context):
    """
    Get GPU texture from strip content at current frame.
    Returns a gpu.types.GPUTexture or None if not available.
    """
    try:
        import gpu
        import numpy as np

        # For now, we'll render the strip's current frame to get its texture
        # This requires rendering the VSE to an offscreen buffer

        scene = context.scene
        if not scene.sequence_editor:
            return None

        # Get strip frame at current time
        frame = scene.frame_current

        # Check if strip is visible at this frame
        if not is_strip_visible_at_frame(strip, frame):
            return None

        # Try to get image data from strip
        # Method 1: For image strips, load and access the image directly
        if strip.type == 'IMAGE':
            # Get the directory and filename from the strip
            if hasattr(strip, 'directory') and hasattr(strip, 'elements') and len(strip.elements) > 0:
                elem = strip.elements[0]
                if hasattr(elem, 'filename') and elem.filename:
                    import os
                    filepath = os.path.join(strip.directory, elem.filename)

                    # Check if image is already loaded
                    img = None
                    for existing_img in bpy.data.images:
                        if existing_img.filepath == filepath or elem.filename in existing_img.name:
                            img = existing_img
                            break

                    # Load image if not already loaded
                    if img is None and os.path.exists(filepath):
                        try:
                            img = bpy.data.images.load(filepath, check_existing=True)
                            print(f"Debug: Loaded image from {filepath}")
                        except Exception as e:
                            print(f"Debug: Could not load image: {e}")

                    if img:
                        return _image_to_gpu_texture(img)

        # Method 2: For movie strips, we need to extract the current frame
        # This is more complex and might require rendering
        if strip.type == 'MOVIE':
            # TODO: Implement movie frame extraction
            # This would require either:
            # - Using ffmpeg/movie clip editor to get current frame
            # - Rendering the strip to an offscreen buffer
            print("Debug: Movie strip texture extraction not yet implemented")
            return None

        # Method 3: Render the strip to an offscreen buffer (universal approach)
        # This would work for all strip types but is more complex
        # TODO: Implement offscreen rendering approach

        return None

    except Exception as e:
        print(f"Debug: Error getting strip texture: {e}")
        return None


def _image_to_gpu_texture(image):
    """Convert a Blender image to a GPU texture"""
    try:
        import gpu
        import numpy as np

        if not image or not image.pixels:
            return None

        # Get image dimensions
        width = image.size[0]
        height = image.size[1]

        if width == 0 or height == 0:
            return None

        # Get pixel data as numpy array
        # Blender stores pixels as flat RGBA array
        pixels = np.array(image.pixels[:], dtype=np.float32)

        # Reshape to (height, width, 4) for RGBA
        pixels = pixels.reshape((height, width, 4))

        # Flip vertically (Blender images are stored bottom-to-top)
        pixels = np.flipud(pixels)

        # Flatten back for buffer
        pixels = pixels.flatten()

        # Create GPU buffer from numpy array
        buffer = gpu.types.Buffer('FLOAT', len(pixels), pixels.tolist())

        # Create GPU texture with buffer
        texture = gpu.types.GPUTexture((width, height), format='RGBA32F', data=buffer)

        print(f"Debug: Created GPU texture {width}x{height}")
        return texture

    except Exception as e:
        print(f"Debug: Error converting image to GPU texture: {e}")
        return None


def _get_perspective_correct_shader():
    """Get or create the perspective-correct texture shader using homography"""
    import gpu

    # Vertex shader - passes through position and screen coordinates
    vertex_shader = '''
        uniform mat4 ModelViewProjectionMatrix;

        in vec2 pos;

        out vec2 screenPos;

        void main()
        {
            screenPos = pos;
            gl_Position = ModelViewProjectionMatrix * vec4(pos, 0.0, 1.0);
        }
    '''

    # Fragment shader - uses bilinear inverse mapping for perspective-correct UV calculation
    fragment_shader = '''
        uniform sampler2D image;
        uniform vec2 corner0;  // Screen space quad corners
        uniform vec2 corner1;
        uniform vec2 corner2;
        uniform vec2 corner3;

        in vec2 screenPos;
        out vec4 fragColor;

        // Bilinear interpolation to find normalized coordinates within quad
        vec2 getBilinearCoords(vec2 p, vec2 c0, vec2 c1, vec2 c2, vec2 c3)
        {
            // Iterative bilinear inverse mapping
            // Start with a guess
            vec2 uv = vec2(0.5, 0.5);

            // Newton-Raphson iteration to find uv
            for (int i = 0; i < 10; i++)
            {
                float u = uv.x;
                float v = uv.y;

                // Bilinear interpolation formula
                // Corner layout: 0=bottom-left, 1=top-left, 2=top-right, 3=bottom-right
                vec2 pos = (1.0 - u) * (1.0 - v) * c0 +
                          u * (1.0 - v) * c3 +
                          u * v * c2 +
                          (1.0 - u) * v * c1;

                vec2 error = p - pos;

                if (length(error) < 0.1) break;

                // Jacobian
                vec2 du = (1.0 - v) * (c3 - c0) + v * (c2 - c1);
                vec2 dv = (1.0 - u) * (c1 - c0) + u * (c2 - c3);

                float det = du.x * dv.y - du.y * dv.x;
                if (abs(det) < 0.001) break;

                // Newton-Raphson update
                vec2 delta = vec2(
                    (error.x * dv.y - error.y * dv.x) / det,
                    (error.y * du.x - error.x * du.y) / det
                );

                uv += delta;
                uv = clamp(uv, 0.0, 1.0);
            }

            return uv;
        }

        void main()
        {
            // Find normalized coordinates within the quad
            vec2 uv = getBilinearCoords(screenPos, corner0, corner1, corner2, corner3);

            // Flip V coordinate (texture is upside down)
            uv.y = 1.0 - uv.y;

            // Sample texture
            fragColor = texture(image, uv);
        }
    '''

    try:
        shader = gpu.types.GPUShader(vertex_shader, fragment_shader)
        return shader
    except Exception as e:
        print(f"Debug: Error creating perspective shader: {e}")
        return None


def _render_perspective_overlay_quad(screen_corners, texture=None):
    """Render a perspective-distorted overlay quad with optional texture"""
    try:
        import gpu
        from gpu_extras.batch import batch_for_shader
        from mathutils import Matrix

        print(f"Debug: Rendering overlay quad with corners: {screen_corners}")

        if texture is not None:
            # Disable blending for opaque texture rendering
            gpu.state.blend_set('NONE')
            # Render with texture using custom perspective-correct shader
            print(f"Debug: Rendering with texture: {texture}")

            # Get custom shader
            shader = _get_perspective_correct_shader()
            if shader is None:
                print("Debug: Failed to create shader, falling back to colored overlay")
                texture = None  # Fall through to colored overlay
            else:
                # Create two triangles to fill the quad
                vertices = [
                    screen_corners[0], screen_corners[1], screen_corners[2],  # Triangle 1
                    screen_corners[0], screen_corners[2], screen_corners[3]   # Triangle 2
                ]

                batch = batch_for_shader(shader, 'TRIS', {"pos": vertices})

                # Set up orthographic projection matrix for 2D screen space
                region = bpy.context.region
                view_matrix = Matrix.Identity(4)
                projection_matrix = Matrix.OrthoProjection('XY', 4)
                projection_matrix[0][0] = 2.0 / region.width
                projection_matrix[1][1] = 2.0 / region.height
                projection_matrix[0][3] = -1.0
                projection_matrix[1][3] = -1.0

                mvp_matrix = projection_matrix @ view_matrix

                shader.bind()
                shader.uniform_sampler("image", texture)
                shader.uniform_float("ModelViewProjectionMatrix", mvp_matrix)

                # Pass quad corners as individual vec2 uniforms
                try:
                    shader.uniform_float("corner0", (float(screen_corners[0][0]), float(screen_corners[0][1])))
                    shader.uniform_float("corner1", (float(screen_corners[1][0]), float(screen_corners[1][1])))
                    shader.uniform_float("corner2", (float(screen_corners[2][0]), float(screen_corners[2][1])))
                    shader.uniform_float("corner3", (float(screen_corners[3][0]), float(screen_corners[3][1])))
                except Exception as e:
                    print(f"Debug: Error setting quad corners uniform: {e}")

                batch.draw(shader)

        else:
            # Fallback: render semi-transparent cyan overlay (original behavior)
            # Enable alpha blending for transparent overlay
            gpu.state.blend_set('ALPHA')

            overlay_color = (0.0, 1.0, 1.0, 0.2)  # Cyan with transparency

            shader = gpu.shader.from_builtin('UNIFORM_COLOR')

            vertices = [
                screen_corners[0], screen_corners[1], screen_corners[2],
                screen_corners[0], screen_corners[2], screen_corners[3]
            ]

            batch = batch_for_shader(shader, 'TRIS', {"pos": vertices})

            shader.bind()
            shader.uniform_float("color", overlay_color)
            batch.draw(shader)

        # Restore blending
        gpu.state.blend_set('NONE')

    except Exception as e:
        print(f"Debug: Overlay quad render error: {e}")


def clear_all_perspective_gpu_rendering():
    """Clear all GPU perspective rendering (for cleanup)"""
    global _gpu_draw_handler, _gpu_enabled_strips
    
    _gpu_enabled_strips.clear()
    
    if _gpu_draw_handler is not None:
        try:
            bpy.types.SpaceSequenceEditor.draw_handler_remove(_gpu_draw_handler, 'PREVIEW')
        except:
            pass
        _gpu_draw_handler = None