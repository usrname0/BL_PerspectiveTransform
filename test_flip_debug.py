"""
Debug script to test flip detection and handle behavior.
Run this in Blender's text editor while a strip is selected and flipped.
"""

import bpy

# Import from the addon's operators module
def get_strip_geometry_with_flip_support(strip, scene):
    """Import and call the function directly"""
    import sys
    import os
    
    # Get the addon directory
    addon_dir = os.path.dirname(__file__)
    if addon_dir not in sys.path:
        sys.path.insert(0, addon_dir)
    
    try:
        from operators.perspective_core import get_strip_geometry_with_flip_support as get_geometry
        return get_geometry(strip, scene)
    except ImportError:
        # Fallback - try to access via registered addon
        import bl_perspective_transform
        if hasattr(bl_perspective_transform, 'operators'):
            from bl_perspective_transform.operators.perspective_core import get_strip_geometry_with_flip_support as get_geometry
            return get_geometry(strip, scene)
        else:
            raise ImportError("Could not import get_strip_geometry_with_flip_support")

def test_flip_detection():
    """Test if flip states are being detected correctly"""
    print("\n=== FLIP DETECTION DEBUG TEST ===")
    
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
    
    # Test flip detection manually
    flip_x = False
    flip_y = False
    
    print("\n--- Manual Flip Detection ---")
    for attr_name in ['use_flip_x', 'flip_x', 'mirror_x']:
        if hasattr(active_strip, attr_name):
            value = getattr(active_strip, attr_name)
            print(f"Strip.{attr_name}: {value}")
            if value:
                flip_x = True
    
    for attr_name in ['use_flip_y', 'flip_y', 'mirror_y']:
        if hasattr(active_strip, attr_name):
            value = getattr(active_strip, attr_name)
            print(f"Strip.{attr_name}: {value}")
            if value:
                flip_y = True
    
    print(f"Manual detection result: flip_x={flip_x}, flip_y={flip_y}")
    
    # Test via get_strip_geometry_with_flip_support
    print("\n--- Function Detection ---")
    try:
        corners, (pivot_x, pivot_y), (scale_x, scale_y, func_flip_x, func_flip_y) = get_strip_geometry_with_flip_support(active_strip, bpy.context.scene)
        print(f"Function detection result: flip_x={func_flip_x}, flip_y={func_flip_y}")
        
        # Show corners
        print("Strip corners:")
        for i, corner in enumerate(corners):
            print(f"  Corner {i}: ({corner.x:.1f}, {corner.y:.1f})")
            
        # Test flip compensation logic
        if func_flip_x != func_flip_y:
            print("XOR flip detected - rotation should be reversed")
        else:
            print("No XOR flip - rotation normal")
        
    except Exception as e:
        print(f"ERROR: Function test failed: {e}")
    
    # Check transform properties
    print("\n--- Transform Properties ---")
    if hasattr(active_strip, 'transform'):
        transform = active_strip.transform
        print(f"Scale: ({transform.scale_x:.3f}, {transform.scale_y:.3f})")
        print(f"Offset: ({transform.offset_x:.1f}, {transform.offset_y:.1f})")
        print(f"Rotation: {transform.rotation:.3f} radians ({transform.rotation * 57.2958:.1f}°)")
    
    print("=== END FLIP DEBUG TEST ===\n")

if __name__ == "__main__":
    test_flip_detection()