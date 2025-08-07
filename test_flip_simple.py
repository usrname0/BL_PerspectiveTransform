"""
Simple flip detection test - no imports needed.
Run this in Blender's text editor while a strip is selected.
"""

import bpy

def test_flip_simple():
    """Test flip detection without imports"""
    print("\n=== SIMPLE FLIP DETECTION TEST ===")
    
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
    flip_x_found = False
    flip_y_found = False
    
    print("\n--- Manual Flip Detection ---")
    
    # Check all possible flip attributes
    flip_x_attrs = ['use_flip_x', 'flip_x', 'mirror_x']
    flip_y_attrs = ['use_flip_y', 'flip_y', 'mirror_y']
    
    for attr_name in flip_x_attrs:
        if hasattr(active_strip, attr_name):
            value = getattr(active_strip, attr_name)
            print(f"Strip.{attr_name}: {value}")
            if value:
                flip_x_found = True
        else:
            print(f"Strip.{attr_name}: NOT FOUND")
    
    for attr_name in flip_y_attrs:
        if hasattr(active_strip, attr_name):
            value = getattr(active_strip, attr_name)
            print(f"Strip.{attr_name}: {value}")
            if value:
                flip_y_found = True
        else:
            print(f"Strip.{attr_name}: NOT FOUND")
    
    print(f"\nFinal detection: flip_x={flip_x_found}, flip_y={flip_y_found}")
    
    # Test XOR logic
    if flip_x_found != flip_y_found:
        print("XOR FLIP DETECTED - Rotation should be reversed!")
    else:
        print("No XOR flip - Rotation should be normal")
    
    # Check transform properties
    print("\n--- Transform Properties ---")
    if hasattr(active_strip, 'transform'):
        transform = active_strip.transform
        print(f"Scale: ({transform.scale_x:.3f}, {transform.scale_y:.3f})")
        print(f"Offset: ({transform.offset_x:.1f}, {transform.offset_y:.1f})")
        print(f"Rotation: {transform.rotation:.3f} radians ({transform.rotation * 57.2958:.1f}°)")
        
        # Test what would happen with flip compensation
        if flip_x_found != flip_y_found:
            compensated_rotation = -transform.rotation
            print(f"With flip compensation: {compensated_rotation:.3f} radians ({compensated_rotation * 57.2958:.1f}°)")
    
    # Check what type of strip we have
    print(f"\n--- Strip Type Info ---")
    print(f"Strip type: {active_strip.type}")
    
    # For image strips, check for more properties
    if active_strip.type == 'IMAGE':
        print("Image strip detected")
        if hasattr(active_strip, 'elements') and active_strip.elements:
            elem = active_strip.elements[0]
            if hasattr(elem, 'filename'):
                print(f"Image file: {elem.filename}")
    
    print("=== END SIMPLE FLIP TEST ===\n")

if __name__ == "__main__":
    test_flip_simple()