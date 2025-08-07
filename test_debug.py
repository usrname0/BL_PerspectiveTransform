"""
Debug test for perspective texture distortion.
Run this in Blender's text editor to test the system.
"""

import bpy

def test_perspective_debug():
    """Debug the perspective texture system"""
    print("\n=== PERSPECTIVE TEXTURE DEBUG TEST ===")
    
    # Check if we have a sequence editor
    if not bpy.context.scene.sequence_editor:
        print("ERROR: No sequence editor found")
        return
    
    # Check for active strip
    active_strip = bpy.context.scene.sequence_editor.active_strip
    if not active_strip:
        print("ERROR: No active strip found")
        return
    
    print(f"Active strip: {active_strip.name} (type: {active_strip.type})")
    print(f"Strip muted: {active_strip.mute}")
    
    # Test texture extraction
    try:
        from operators.perspective_core import _get_strip_texture, _gpu_enabled_strips
        
        texture = _get_strip_texture(active_strip, bpy.context.scene.frame_current)
        if texture:
            print(f"SUCCESS: Texture extracted - {texture.width}x{texture.height}, format: {texture.format}")
        else:
            print("WARNING: No texture extracted")
        
        # Check if perspective rendering is enabled
        if active_strip.name in _gpu_enabled_strips:
            print("SUCCESS: Strip is in enabled set for perspective rendering")
        else:
            print("INFO: Strip not in perspective rendering set")
            
    except ImportError as e:
        print(f"ERROR: Could not import perspective modules: {e}")
    except Exception as e:
        print(f"ERROR: Texture test failed: {e}")
    
    # Check for perspective data
    try:
        from operators.perspective_core import has_perspective_transform, get_perspective_matrix_from_strip
        
        if has_perspective_transform(active_strip):
            print("SUCCESS: Strip has perspective transform data")
            homography = get_perspective_matrix_from_strip(active_strip)
            if homography:
                print(f"Homography matrix present: {homography[0][0]:.3f}, {homography[0][1]:.3f}, {homography[0][2]:.3f}")
        else:
            print("INFO: No perspective transform data found")
            
    except Exception as e:
        print(f"ERROR: Perspective data check failed: {e}")
    
    print("=== END DEBUG TEST ===\n")

if __name__ == "__main__":
    test_perspective_debug()