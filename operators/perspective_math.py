"""
BL Perspective Transform - Mathematical Operations

This module contains the core mathematical functions for perspective transformation,
including homography matrix calculation and coordinate transformations.
"""

import numpy as np
from mathutils import Vector, Matrix


def calculate_homography_matrix(src_points, dst_points):
    """
    Calculate 3x3 homography matrix from 4 source points to 4 destination points.
    Uses the DLT (Direct Linear Transform) method with SVD for robust calculation.
    
    Args:
        src_points: List of 4 Vector objects representing source corners
        dst_points: List of 4 Vector objects representing destination corners
        
    Returns:
        mathutils.Matrix: 3x3 homography transformation matrix
        
    Based on standard computer vision homography calculation:
    https://docs.opencv.org/4.x/d9/dab/tutorial_homography.html
    """
    if len(src_points) != 4 or len(dst_points) != 4:
        raise ValueError("Exactly 4 points required for homography calculation")
    
    # Create the coefficient matrix A for the homogeneous system Ah = 0
    # where h = [h11, h12, h13, h21, h22, h23, h31, h32, h33].T
    A = []
    
    for i in range(4):
        x, y = src_points[i].x, src_points[i].y
        u, v = dst_points[i].x, dst_points[i].y
        
        # Two equations per point correspondence:
        # u*(h31*x + h32*y + h33) = h11*x + h12*y + h13
        # v*(h31*x + h32*y + h33) = h21*x + h22*y + h23
        #
        # Rearranged to homogeneous form:
        # h11*x + h12*y + h13*1 + h21*0 + h22*0 + h23*0 - h31*u*x - h32*u*y - h33*u = 0
        # h11*0 + h12*0 + h13*0 + h21*x + h22*y + h23*1 - h31*v*x - h32*v*y - h33*v = 0
        
        A.append([x, y, 1, 0, 0, 0, -u*x, -u*y, -u])
        A.append([0, 0, 0, x, y, 1, -v*x, -v*y, -v])
    
    # Convert to numpy for calculation
    A = np.array(A, dtype=np.float64)
    
    try:
        # Solve using SVD (more robust than eigenvalue method)
        U, S, Vt = np.linalg.svd(A)
        
        # The solution is the column of V corresponding to the smallest singular value
        h = Vt[-1, :]
        
        # Reshape into 3x3 matrix
        homography = h.reshape(3, 3)
        
        # Normalize so that h33 = 1 (unless it's zero)
        if abs(homography[2, 2]) > 1e-10:
            homography = homography / homography[2, 2]
        
        # Convert to Blender's Matrix format
        return Matrix([
            [homography[0,0], homography[0,1], homography[0,2]],
            [homography[1,0], homography[1,1], homography[1,2]],
            [homography[2,0], homography[2,1], homography[2,2]]
        ])
        
    except np.linalg.LinAlgError:
        # Fallback to identity matrix if calculation fails
        print("Warning: Homography calculation failed, using identity matrix")
        return Matrix.Identity(3)


def apply_homography_to_point(point, homography_matrix):
    """
    Apply homography transformation to a 2D point.
    
    Args:
        point: Vector with x, y coordinates
        homography_matrix: 3x3 Matrix for transformation
        
    Returns:
        Vector: Transformed point
    """
    # Convert to homogeneous coordinates [x, y, 1]
    homogeneous = Vector([point.x, point.y, 1.0])
    
    # Apply transformation
    transformed = homography_matrix @ homogeneous
    
    # Convert back to 2D coordinates by dividing by w
    if abs(transformed.z) > 1e-10:  # Avoid division by zero
        return Vector([transformed.x / transformed.z, transformed.y / transformed.z])
    else:
        return Vector([transformed.x, transformed.y])


def get_strip_corner_positions(strip, scene):
    """
    Get the current corner positions of a strip in screen coordinates.
    
    Args:
        strip: Blender sequence strip
        scene: Blender scene
        
    Returns:
        List of 4 Vector objects representing corner positions
    """
    # This is a placeholder - we'll integrate with our existing geometry calculation
    from .perspective_core import get_strip_geometry_with_flip_support
    
    corners, (pivot_x, pivot_y), (scale_x, scale_y, flip_x, flip_y) = get_strip_geometry_with_flip_support(strip, scene)
    return corners


def calculate_perspective_transform_for_strip(strip, scene, handle_positions):
    """
    Calculate perspective transformation for a strip based on new handle positions.
    
    Args:
        strip: Blender sequence strip
        scene: Blender scene
        handle_positions: List of 4 Vector objects for new corner positions
        
    Returns:
        Matrix: 3x3 homography matrix for the transformation
    """
    # Get original strip corners
    original_corners = get_strip_corner_positions(strip, scene)
    
    # Calculate homography from original to new positions
    homography = calculate_homography_matrix(original_corners, handle_positions)
    
    return homography


def decompose_homography_to_transform_properties(homography_matrix):
    """
    Attempt to decompose homography into basic transform properties.
    This is an approximation for cases where we can map to VSE transform properties.
    
    Args:
        homography_matrix: 3x3 Matrix
        
    Returns:
        dict: Transform properties (scale_x, scale_y, rotation, offset_x, offset_y)
    """
    # Extract the 2x2 upper-left submatrix for linear transformation
    linear_part = Matrix([
        [homography_matrix[0][0], homography_matrix[0][1]],
        [homography_matrix[1][0], homography_matrix[1][1]]
    ])
    
    # Extract translation
    offset_x = homography_matrix[0][2]
    offset_y = homography_matrix[1][2]
    
    # Decompose linear part into scale and rotation (approximate)
    # This is a simplified approach - true perspective can't always be decomposed this way
    
    import math
    
    # Calculate scaling factors
    scale_x = math.sqrt(linear_part[0][0]**2 + linear_part[1][0]**2)
    scale_y = math.sqrt(linear_part[0][1]**2 + linear_part[1][1]**2)
    
    # Calculate rotation (approximate)
    rotation = math.atan2(linear_part[1][0], linear_part[0][0])
    
    return {
        'scale_x': scale_x,
        'scale_y': scale_y, 
        'rotation': rotation,
        'offset_x': offset_x,
        'offset_y': offset_y
    }


# Test function for development
def test_homography_calculation():
    """Test function to verify homography calculation works correctly"""
    
    # Define a simple square -> distorted quad transformation
    src_corners = [
        Vector([0, 0]),    # Bottom-left
        Vector([100, 0]),  # Bottom-right
        Vector([100, 100]), # Top-right
        Vector([0, 100])   # Top-left
    ]
    
    # Slightly distorted destination
    dst_corners = [
        Vector([10, 5]),    # Bottom-left (moved)
        Vector([90, 10]),   # Bottom-right (moved)
        Vector([95, 95]),   # Top-right (moved) 
        Vector([5, 90])     # Top-left (moved)
    ]
    
    # Calculate homography
    H = calculate_homography_matrix(src_corners, dst_corners)
    
    print("Homography Matrix:")
    for row in H:
        print(f"[{row[0]:.4f}, {row[1]:.4f}, {row[2]:.4f}]")
    
    # Test by transforming original points
    print("\nTransformation test:")
    for i, src_point in enumerate(src_corners):
        transformed = apply_homography_to_point(src_point, H)
        expected = dst_corners[i]
        error = (transformed - expected).length
        print(f"Point {i}: ({src_point.x}, {src_point.y}) -> ({transformed.x:.2f}, {transformed.y:.2f}) "
              f"(expected: ({expected.x}, {expected.y}), error: {error:.4f})")


if __name__ == "__main__":
    test_homography_calculation()