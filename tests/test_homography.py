"""
Standalone test for homography calculation without Blender dependencies
"""

import numpy as np


class Vector:
    """Simple Vector class for testing"""
    def __init__(self, coords):
        self.x = coords[0]
        self.y = coords[1] if len(coords) > 1 else 0
        self.z = coords[2] if len(coords) > 2 else 0
    
    def __sub__(self, other):
        return Vector([self.x - other.x, self.y - other.y])
    
    def length(self):
        return np.sqrt(self.x**2 + self.y**2)


def calculate_homography_matrix(src_points, dst_points):
    """
    Calculate 3x3 homography matrix from 4 source points to 4 destination points.
    Uses the DLT (Direct Linear Transform) method.
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
        
        return homography
        
    except np.linalg.LinAlgError as e:
        print(f"Warning: Homography calculation failed: {e}")
        return np.eye(3)  # Identity matrix


def apply_homography_to_point(point, homography_matrix):
    """Apply homography transformation to a 2D point."""
    # Convert to homogeneous coordinates [x, y, 1]
    homogeneous = np.array([point.x, point.y, 1.0])
    
    # Apply transformation
    transformed = homography_matrix @ homogeneous
    
    # Convert back to 2D coordinates by dividing by w
    if abs(transformed[2]) > 1e-10:  # Avoid division by zero
        return Vector([transformed[0] / transformed[2], transformed[1] / transformed[2]])
    else:
        return Vector([transformed[0], transformed[1]])


def test_homography_calculation():
    """Test function to verify homography calculation works correctly"""
    
    print("=== Homography Calculation Test ===\n")
    
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
    
    print("Source corners (square):")
    for i, point in enumerate(src_corners):
        print(f"  Corner {i}: ({point.x}, {point.y})")
    
    print("\nDestination corners (distorted):")
    for i, point in enumerate(dst_corners):
        print(f"  Corner {i}: ({point.x}, {point.y})")
    
    # Calculate homography
    H = calculate_homography_matrix(src_corners, dst_corners)
    
    print("\nCalculated Homography Matrix:")
    for i, row in enumerate(H):
        print(f"  [{row[0]:8.4f}, {row[1]:8.4f}, {row[2]:8.4f}]")
    
    # Test by transforming original points
    print("\nTransformation Accuracy Test:")
    total_error = 0
    for i, src_point in enumerate(src_corners):
        transformed = apply_homography_to_point(src_point, H)
        expected = dst_corners[i]
        error = (transformed - expected).length()
        total_error += error
        print(f"  Point {i}: ({src_point.x:3.0f}, {src_point.y:3.0f}) -> "
              f"({transformed.x:6.2f}, {transformed.y:6.2f}) | "
              f"Expected: ({expected.x:3.0f}, {expected.y:3.0f}) | "
              f"Error: {error:.4f}")
    
    print(f"\nTotal Error: {total_error:.4f}")
    print(f"Average Error: {total_error/4:.4f}")
    
    if total_error < 0.01:
        print("PASS: Homography calculation is accurate!")
    else:
        print("FAIL: Homography calculation has significant errors")
    
    return H


def test_identity_transformation():
    """Test that identity transformation works correctly"""
    print("\n=== Identity Transformation Test ===\n")
    
    # Source and destination are the same (should give identity matrix)
    corners = [
        Vector([0, 0]),
        Vector([100, 0]), 
        Vector([100, 100]),
        Vector([0, 100])
    ]
    
    H = calculate_homography_matrix(corners, corners)
    
    print("Identity Homography Matrix:")
    for row in H:
        print(f"  [{row[0]:8.4f}, {row[1]:8.4f}, {row[2]:8.4f}]")
    
    # Should be close to identity matrix
    identity = np.eye(3)
    difference = np.abs(H - identity).max()
    
    print(f"\nMaximum difference from identity: {difference:.6f}")
    
    if difference < 0.001:
        print("PASS: Identity transformation works correctly")
    else:
        print("FAIL: Identity transformation is not accurate")


if __name__ == "__main__":
    test_homography_calculation()
    test_identity_transformation()