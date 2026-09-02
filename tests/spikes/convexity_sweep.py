"""
Measure where the Corner Pin solver stops rendering a valid quad.

This is where CONVEX_EPSILON in operators/perspective_space.py comes from. It is
not a test - nothing here asserts - it is the measurement DEV.md tells you to
re-run before changing that number.

    blender.exe --factory-startup --background --python tests/spikes/convexity_sweep.py

It sweeps the top-right corner of the unit square down the diagonal towards the
line through its two neighbours, rendering each position and reporting how much
of the frame came out opaque. The corner crosses that line at t = 0.5, so the
sweep runs from clearly convex, through exactly collinear, into concave.

Measured on 5.2.1, which is the table in DEV.md -> Convexity: correct renders
down to a smallest cross product of 1e-4 (by which point the image has
degenerated to 17 percent of the frame), an empty frame at exactly collinear,
and a frame filled edge to edge with garbage on the concave side.

Note that a concave quad and an untransformed one both fill the frame
completely, so coverage alone does not separate them - the sign test does.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

import bpy
import numpy as np

import harness as H

# harness stores its pin as Upper Left, Upper Right, Lower Left, Lower Right,
# which jumps across the quad. These indices walk it instead, which is what a
# cross product test needs.
WALK = (0, 1, 3, 2)

# t is where the top-right corner sits on the diagonal. Below 0.5 it has crossed
# the line through its neighbours and the quad is concave.
SWEEP = (1.00, 0.90, 0.75, 0.60, 0.55, 0.520, 0.505, 0.5005, 0.50005, 0.50,
         0.499, 0.48, 0.45, 0.35)


def _cross_products(pin):
    """Yield the cross product of adjacent edges at each vertex of the quad."""
    points = [pin[i] for i in WALK]
    for i in range(4):
        ax, ay = points[i]
        bx, by = points[(i + 1) % 4]
        cx, cy = points[(i + 2) % 4]
        yield (bx - ax) * (cy - by) - (by - ay) * (cx - bx)


def main():
    """Render the sweep and print a row per position."""
    source = H.make_source_image(os.path.join(H.scratch_dir(), "sweep_src.png"))
    print("{:>8} {:>13} {:>8} {:>9} {:>6}".format(
        "t", "min_cross", "convex", "opaque%", "nan"))

    for t in SWEEP:
        pin = [(0.0, 1.0), (t, t), (0.0, 0.0), (1.0, 0.0)]
        tag = "sweep_{}".format(str(t).replace(".", "_"))

        scene = H.make_scene(tag)
        strip = H.add_image_strip(scene, source)
        H.add_compositor_modifier(strip, scene, H.build_corner_pin_group(tag, pin=pin))
        pixels = H.render_scene(scene, tag)

        crosses = list(_cross_products(pin))
        smallest = min(crosses, key=abs)
        convex = len({c > 0.0 for c in crosses}) == 1

        print("{:>8} {:>13.3e} {:>8} {:>9.3f} {:>6}".format(
            t, smallest, str(convex),
            float((pixels[..., 3] > 0.5).mean()) * 100.0,
            int(np.isnan(pixels).sum())))

        bpy.data.scenes.remove(scene)


if __name__ == "__main__":
    main()
