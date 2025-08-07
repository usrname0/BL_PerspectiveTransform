"""
Test script for Phase 3 texture distortion implementation.

This script creates a test scene with a color strip and applies perspective
transformation to verify that the texture distortion system is working.
"""

import bpy
import bmesh
from mathutils import Vector, Matrix

def create_test_scene():
    """Create a test scene with a color strip for perspective testing"""
    
    # Clear existing mesh objects
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    
    # Set up sequencer
    if not bpy.context.scene.sequence_editor:
        bpy.context.scene.sequence_editor_create()
    
    seq_editor = bpy.context.scene.sequence_editor
    
    # Clear existing strips
    if seq_editor.sequences:
        for strip in seq_editor.sequences:
            seq_editor.sequences.remove(strip)
    
    # Create a color strip
    bpy.ops.sequencer.effect_strip_add(
        frame_start=1,
        frame_end=250,
        type='COLOR'
    )
    
    # Get the created strip and set it to red
    color_strip = seq_editor.active_strip
    if color_strip:
        color_strip.color = (1.0, 0.2, 0.2)  # Red color
        color_strip.name = "Test_Color_Strip"
        print(f"Created color strip: {color_strip.name} with color {color_strip.color}")
    
    # Set frame range
    bpy.context.scene.frame_start = 1
    bpy.context.scene.frame_end = 250
    bpy.context.scene.frame_set(100)  # Set current frame to middle
    
    # Set VSE as active area
    for area in bpy.context.screen.areas:
        if area.type == 'SEQUENCE_EDITOR':
            for space in area.spaces:
                if space.type == 'SEQUENCE_EDITOR':
                    space.view_type = 'SEQUENCER_PREVIEW'
                    break
            break
    
    print("Test scene created successfully")
    return color_strip

def test_perspective_texture_system():
    """Test the perspective texture distortion system"""
    
    # Create test scene
    strip = create_test_scene()
    if not strip:
        print("ERROR: Failed to create test strip")
        return
    
    # Import perspective system
    try:
        from operators.perspective_core import (
            _get_strip_texture,
            _render_perspective_overlay_quad,
            apply_perspective_to_strip,
            store_perspective_matrix_in_strip
        )
        from operators.perspective_math import calculate_homography_dlt
        print("Successfully imported perspective modules")
    except ImportError as e:
        print(f"ERROR: Failed to import perspective modules: {e}")
        return
    
    # Test texture extraction from color strip
    print("\n=== Testing Texture Extraction ===")
    texture = _get_strip_texture(strip, bpy.context.scene.frame_current)
    if texture:
        print(f"SUCCESS: Extracted texture from strip: {texture}")
        print(f"Texture size: {texture.width}x{texture.height}")
        print(f"Texture format: {texture.format}")
    else:
        print("WARNING: No texture extracted, will use colored overlay")
    
    # Create test perspective corners (slight keystone effect)
    print("\n=== Testing Perspective Transformation ===")
    scene = bpy.context.scene
    res_x = scene.render.resolution_x
    res_y = scene.render.resolution_y
    
    # Original corners (rectangle)
    original_corners = [
        Vector([100, 100]),      # Bottom-left
        Vector([100, res_y-100]), # Top-left
        Vector([res_x-100, res_y-100]), # Top-right
        Vector([res_x-100, 100]) # Bottom-right
    ]
    
    # Perspective corners (keystone effect - narrow at top)
    perspective_corners = [
        Vector([100, 100]),      # Bottom-left (unchanged)
        Vector([200, res_y-100]), # Top-left (moved right)
        Vector([res_x-200, res_y-100]), # Top-right (moved left)
        Vector([res_x-100, 100]) # Bottom-right (unchanged)
    ]
    
    # Calculate homography matrix
    try:
        homography = calculate_homography_dlt(original_corners, perspective_corners)
        print(f"Calculated homography matrix:\n{homography}")
        
        # Store in strip and apply
        store_perspective_matrix_in_strip(strip, homography)
        apply_perspective_to_strip(strip, homography)
        
        print("SUCCESS: Applied perspective transformation to strip")
        print("You should now see a red textured quad with keystone perspective distortion")
        print("The texture should be properly mapped to the distorted shape")
        
    except Exception as e:
        print(f"ERROR: Failed to apply perspective transformation: {e}")
    
    print("\n=== Test Complete ===")
    print("Switch to VSE Preview to see the result")

if __name__ == "__main__":
    test_perspective_texture_system()