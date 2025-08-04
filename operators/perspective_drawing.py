"""
BL Perspective Transform - Drawing and visual rendering

This module handles all the visual aspects of the perspective transform interface,
including drawing corner handles and the perspective symbol.
"""

import bpy
import gpu
import math
from gpu_extras.batch import batch_for_shader

from .perspective_core import (
    get_perspective_state, get_draw_data, 
    get_strip_geometry_with_flip_support, is_strip_visible_at_frame
)


def draw_line(v1, v2, width, color):
    """Draw a line between two points"""
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.line_width_set(width)
    vertices = [v1, v2]
    batch = batch_for_shader(shader, 'LINES', {"pos": vertices})
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)
    gpu.state.line_width_set(1.0)


def draw_perspective_handles():
    """Main draw function for perspective transform handles"""
    perspective_state = get_perspective_state()
    
    # Exit immediately if perspective mode isn't active
    if not perspective_state['active']:
        return
        
    context = bpy.context
    if not context.area or context.area.type != 'SEQUENCE_EDITOR':
        return
    
    # Always get the current active strip to ensure we have latest state
    scene = context.scene
    if not scene.sequence_editor:
        return
        
    strip = scene.sequence_editor.active_strip
    if not strip or not hasattr(strip, 'transform'):
        return
    
    # Check if strip is visible at current frame
    current_frame = scene.frame_current
    if not is_strip_visible_at_frame(strip, current_frame):
        return
    
    # Get stored data
    draw_data = get_draw_data()
    if not draw_data:
        from .perspective_core import set_draw_data
        set_draw_data({'active_corner': -1, 'frame_count': 0})
        draw_data = get_draw_data()
    
    active_corner = draw_data.get('active_corner', -1)
    
    # Get mouse position for hover detection (stored by modal operator)
    mouse_x = draw_data.get('mouse_x', 0)  
    mouse_y = draw_data.get('mouse_y', 0)
    
    # Get theme colors - match gizmo version
    active_color = (1.0, 0.5, 0.0, 1.0)  # Orange for active/dragging (like gizmo)
    hover_color = (1.0, 0.5, 0.0, 1.0)   # Orange for hover (like gizmo)
    handle_color = (1.0, 1.0, 1.0, 0.7)  # White for normal
    
    # Get current geometry
    corners, (pivot_x, pivot_y), (scale_x, scale_y, flip_x, flip_y) = get_strip_geometry_with_flip_support(strip, scene)
    
    # Get preview transform
    region = context.region
    if not region:
        return
    
    view2d = context.region.view2d
    res_x = scene.render.resolution_x
    res_y = scene.render.resolution_y
    
    # Transform to screen coordinates - only corner handles for perspective
    screen_corners = []
    for corner in corners:
        view_x = corner.x - res_x / 2
        view_y = corner.y - res_y / 2
        screen_co = view2d.view_to_region(view_x, view_y, clip=False)
        screen_corners.append(screen_co)
    
    # Draw perspective symbol at center
    _draw_perspective_symbol(view2d, pivot_x, pivot_y, res_x, res_y)
    
    # Detect hover for feedback - only corners for perspective
    hover_corner = _get_hovered_corner(screen_corners, mouse_x, mouse_y)
    
    # Draw corner handles only (no edge handles for perspective)
    _draw_perspective_handles(screen_corners, active_corner, hover_corner, active_color, hover_color, handle_color)


def _draw_perspective_symbol(view2d, pivot_x, pivot_y, res_x, res_y):
    """Draw the perspective symbol at the strip center"""
    # Transform to screen coordinates
    screen_center = view2d.view_to_region(
        pivot_x - res_x / 2,
        pivot_y - res_y / 2,
        clip=False
    )
    center_x = screen_center[0]
    center_y = screen_center[1]
    
    # Draw perspective symbol - a simple diamond/rhombus shape
    white_color = (1.0, 1.0, 1.0, 0.8)
    line_shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    
    # Symbol dimensions
    size = 6
    
    gpu.state.line_width_set(1.5)
    line_shader.bind()
    line_shader.uniform_float("color", white_color)
    
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


def _get_hovered_corner(screen_corners, mouse_x, mouse_y):
    """Get which corner handle is being hovered (only corners for perspective)"""
    mouse_pos = (mouse_x, mouse_y)
    
    # Check corner handles (0-3)
    for i, corner in enumerate(screen_corners):
        dx = corner[0] - mouse_pos[0]
        dy = corner[1] - mouse_pos[1]
        distance = math.sqrt(dx*dx + dy*dy)
        if distance < 10:  # Same hover distance as crop
            return i
    
    return -1


def _draw_perspective_handles(screen_corners, active_corner, hover_corner, active_color, hover_color, handle_color):
    """Draw corner handles for perspective transformation"""
    handle_size = 6  # Same size as crop handles
    
    # Only draw corner handles (0-3) for perspective transform
    for i, corner in enumerate(screen_corners):
        # Determine color based on state
        if i == active_corner:
            color = active_color
        elif i == hover_corner:
            color = hover_color
        else:
            color = handle_color
        
        _draw_handle_square(corner[0], corner[1], handle_size, color)


def _draw_handle_square(x, y, size, color):
    """Draw a square handle at the given position - match EasyCrop exactly"""
    # Create square vertices - size is radius, not diameter like EasyCrop
    vertices = [
        (x - size, y - size),  # Bottom-left
        (x + size, y - size),  # Bottom-right
        (x + size, y + size),  # Top-right
        (x - size, y + size)   # Top-left
    ]
    
    # Draw filled square
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = batch_for_shader(shader, 'TRI_FAN', {"pos": vertices})
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)
    
    # Draw border for better visibility
    border_color = (0.0, 0.0, 0.0, 0.8)  # Black border
    gpu.state.line_width_set(1.0)
    border_vertices = vertices + [vertices[0]]  # Close the loop
    border_batch = batch_for_shader(shader, 'LINE_STRIP', {"pos": border_vertices})
    shader.uniform_float("color", border_color)
    border_batch.draw(shader)