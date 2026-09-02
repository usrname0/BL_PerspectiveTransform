"""
The convexity guard on the corner handles.

A homography maps the unit square onto a convex quadrilateral and onto nothing
else, so Blender's Corner Pin has no solution for a concave, self-intersecting
or collinear quad - and does not say so. Measured on 5.2.1 by sweeping a corner
across the diagonal (see DEV.md -> Convexity), the render stayed correct while
convex, went empty at exactly collinear, and filled the whole frame with
garbage on the concave side.

The point of these tests is the *drag*, not the predicate. A test that only
exercised is_convex_quad would pass whether or not the gizmo ever consulted it,
which is the shape of mistake this project has already shipped once. The gizmo
drag cannot be driven by simulated events, but _drag_to can be called directly
with a stand-in region, and that runs the real guard against the real matrices.
"""

import os

import harness as H


class _FakeView2D:
    """A View2D whose region and view coordinates are the same thing.

    _region_to_frame does the real work of shifting by half the render
    resolution; this only has to be the identity so a test can hand the gizmo a
    frame-space point it chose.
    """

    @staticmethod
    def region_to_view(x, y):
        return x, y


class _FakeRegion:
    """The one member _drag_to reads off a region."""

    def __init__(self):
        self.view2d = _FakeView2D()


class _FakeContext:
    """
    Enough context for the gizmo's drag path.

    A real bpy.context in background mode points at the default scene rather
    than the one the test built, so the gizmo would edit the wrong strip.
    """

    def __init__(self, scene):
        self.scene = scene
        self.sequencer_scene = scene
        self.region = _FakeRegion()


def _setup(name, res=512):
    """Build a scene with an image strip pinned to identity."""
    nodes = H.import_addon_module("operators.perspective_nodes")
    src = H.make_source_image(os.path.join(H.scratch_dir(), "convex_source.png"))
    scene = H.make_scene(name, res, res)
    strip = H.add_image_strip(scene, src)
    H.set_duration(strip, 10)
    nodes.write_pin(strip, scene, nodes.IDENTITY_PIN)
    return scene, strip


def _region_of(scene, pin_point):
    """
    Return the region coordinates the cursor sits at for a pin-space point.

    The strip is untransformed and its source fills the frame, so frame space
    is pin space times the resolution; this also undoes _region_to_frame's
    half-resolution shift, so the gizmo maps it straight back.
    """
    return (pin_point[0] * scene.render.resolution_x - scene.render.resolution_x * 0.5,
            pin_point[1] * scene.render.resolution_y - scene.render.resolution_y * 0.5)


def _begin_drag(gizmo_module, nodes, space, scene, strip, index):
    """
    Set up a stand-in gizmo the way invoke() does, ready to be dragged.

    The drag moves the corner by cursor *travel*, so a single call proves
    nothing on its own - the tests here move the cursor through a sequence of
    positions and watch what the corner does, which is the only way the
    stop-and-resume behaviour is visible at all.
    """
    handle = gizmo_module.PERSPECTIVE_GT_perspective_handle

    class _Stub:
        pass

    _Stub._drag_to = handle._drag_to
    _Stub._accept_corner = handle._accept_corner
    stub = _Stub()
    stub.handle_index = index
    stub._pin_on_invoke = nodes.read_pin(strip)
    stub._pin_corners = list(stub._pin_on_invoke)
    stub._edit_node = nodes.prepare_for_edit(strip, scene)
    stub._drag_matrix = space.frame_to_pin_matrix(strip, scene)
    # A real grab starts with the cursor on the handle.
    stub._last_mouse = _region_of(scene, stub._pin_corners[index])
    return stub


def _move_cursor_to(stub, nodes, scene, strip, pin_point):
    """Move the cursor to a pin-space point and return where the corners ended up."""
    stub._drag_to(_FakeContext(scene), *_region_of(scene, pin_point))
    return [tuple(round(float(v), 4) for v in c) for c in nodes.read_pin(strip)]


def test_predicate_separates_the_shapes():
    """is_convex_quad must accept convex quads and reject everything else."""
    space = H.import_addon_module("operators.perspective_space")
    failures = []

    # In CORNER_SOCKETS order: bottom left, top left, top right, bottom right,
    # which walks the quad rather than jumping across it.
    convex = [
        ("identity", ((0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0))),
        ("keystone", ((0.0, 0.0), (0.25, 1.0), (0.75, 1.0), (1.0, 0.0))),
        ("sheared", ((0.1, 0.0), (0.0, 0.9), (0.9, 1.0), (1.0, 0.1))),
        # Corner 2 nearly on the diagonal between its neighbours: a sliver, but
        # measured on 5.2.1 to still render correctly, so it must be allowed
        # through. Its smallest cross product is 1e-3, ten times the threshold.
        ("thin", ((0.0, 0.0), (0.0, 1.0), (0.5005, 0.5005), (1.0, 0.0))),
    ]
    for name, corners in convex:
        if not space.is_convex_quad(corners):
            failures.append(f"{name} is convex but was rejected")

    rejected = [
        # Top right pulled across the bottom-left/bottom-right diagonal.
        ("concave", ((0.0, 0.0), (0.0, 1.0), (0.35, 0.35), (1.0, 0.0))),
        # Two corners swapped, so the outline crosses itself.
        ("bowtie", ((0.0, 0.0), (1.0, 1.0), (0.0, 1.0), (1.0, 0.0))),
        # Three points on one line: no homography, and measured to render an
        # empty frame rather than to fail.
        ("collinear", ((0.0, 0.0), (0.0, 1.0), (0.5, 0.5), (1.0, 0.0))),
        # Every corner in the same place.
        ("degenerate", ((0.5, 0.5), (0.5, 0.5), (0.5, 0.5), (0.5, 0.5))),
        # Convex, but so nearly collinear that the render has all but vanished:
        # a cross product of 2e-5, below the measured threshold.
        ("sliver", ((0.0, 0.0), (0.0, 1.0), (0.50001, 0.50001), (1.0, 0.0))),
    ]
    for name, corners in rejected:
        if space.is_convex_quad(corners):
            failures.append(f"{name} is not a convex quad but was accepted")

    # The threshold is a measured number, not a taste: 1e-4 is the smallest
    # cross product whose render was still checked to be correct on 5.2.1.
    if space.CONVEX_EPSILON != 1e-4:
        failures.append(
            f"CONVEX_EPSILON is {space.CONVEX_EPSILON}, but 1e-4 is what was measured; "
            "re-run the sweep in DEV.md -> Convexity before changing it")

    return failures


def test_drag_refuses_to_enter_a_concave_shape():
    """
    The gizmo's drag step must reject a move that breaks convexity.

    This calls the gizmo's own _drag_to, so it fails if the guard is removed
    from the drag path even while is_convex_quad itself still works.
    """
    nodes = H.import_addon_package_module("operators.perspective_nodes")
    space = H.import_addon_package_module("operators.perspective_space")
    gizmo_module = H.import_addon_package_module("gizmos.perspective_handles_gizmo")
    scene, strip = _setup("convex_drag")
    failures = []

    stub = _begin_drag(gizmo_module, nodes, space, scene, strip, 2)

    # Corner 2 is the top right. A valid move first, so the refusal that
    # follows is measured against a corner that had been moving.
    after = _move_cursor_to(stub, nodes, scene, strip, (0.7, 0.7))
    if after[2] != (0.7, 0.7):
        failures.append(f"a convex drag was refused, corner 2 is {after[2]}")

    # Pulling it to (0.2, 0.2) puts it across the diagonal between its
    # neighbours, which is the concave case, and must not be written.
    after = _move_cursor_to(stub, nodes, scene, strip, (0.2, 0.2))
    if after[2] != (0.7, 0.7):
        failures.append(f"a concave drag was written anyway, corner 2 is {after[2]}")

    return failures


def test_the_handle_moves_again_the_moment_the_drag_reverses():
    """
    Coming back off the boundary must move the corner on the very first event.

    This is the bug that shipped with the guard's first version. Refusing an
    *absolute* cursor position leaves the corner still while the cursor carries
    on into the disallowed region, and since nothing on screen moved, the user
    has no idea how far in they went - they then have to drag all of it back
    before anything happens. It reads as having invisibly dragged yourself into
    a hole. Accumulating travel onto the last accepted position is what fixes
    it, and this test is the reason to keep doing that.
    """
    nodes = H.import_addon_package_module("operators.perspective_nodes")
    space = H.import_addon_package_module("operators.perspective_space")
    gizmo_module = H.import_addon_package_module("gizmos.perspective_handles_gizmo")
    scene, strip = _setup("convex_reverse")
    failures = []

    stub = _begin_drag(gizmo_module, nodes, space, scene, strip, 2)
    _move_cursor_to(stub, nodes, scene, strip, (0.7, 0.7))

    # Well past the boundary: under absolute placement this is where the
    # invisible travel would pile up.
    held = _move_cursor_to(stub, nodes, scene, strip, (0.2, 0.2))
    if held[2] != (0.7, 0.7):
        failures.append(f"the corner should be held at (0.7, 0.7), it is {held[2]}")

    # Now reverse by a hair. The cursor is still deep inside the disallowed
    # region, so an absolute reading would refuse this too and the corner would
    # sit there for another 0.5 of travel.
    after = _move_cursor_to(stub, nodes, scene, strip, (0.25, 0.25))
    if after[2] != (0.75, 0.75):
        failures.append(
            f"reversing the drag did not move the corner immediately: {after[2]}, "
            "expected (0.75, 0.75)")

    return failures


def test_a_drag_along_the_boundary_keeps_moving():
    """
    A move refused whole must still be tried one axis at a time.

    Without this, a drag running at a shallow angle into the boundary is
    refused on every single event - the user is mostly moving parallel to it,
    and the handle stops dead anyway.
    """
    nodes = H.import_addon_package_module("operators.perspective_nodes")
    space = H.import_addon_package_module("operators.perspective_space")
    gizmo_module = H.import_addon_package_module("gizmos.perspective_handles_gizmo")
    scene, strip = _setup("convex_slide")
    failures = []

    stub = _begin_drag(gizmo_module, nodes, space, scene, strip, 2)
    _move_cursor_to(stub, nodes, scene, strip, (0.6, 0.6))

    # Mostly leftwards, slightly up. The whole move crosses the boundary and so
    # does the x half of it, but the y half does not, so the corner should
    # travel up rather than stop.
    after = _move_cursor_to(stub, nodes, scene, strip, (0.1, 0.7))
    if after[2] != (0.6, 0.7):
        failures.append(
            f"a shallow drag along the boundary gave {after[2]}, expected (0.6, 0.7)")

    return failures


def test_a_refused_drag_renders_the_shape_it_stopped_at():
    """
    The guard has to hold the last good *render*, not just the last good value.

    The failure this exists to prevent is not a wrong number but an unusable
    frame: measured on 5.2.1 a concave pin renders the whole frame filled edge
    to edge with garbage. So the strip is first dragged into a strong but valid
    shape covering about 70 percent of the frame, and the refused drag must
    leave that render untouched - a full frame would mean the concave value got
    through, and the identity square would mean the guard reset something.
    """
    import numpy as np

    nodes = H.import_addon_package_module("operators.perspective_nodes")
    space = H.import_addon_package_module("operators.perspective_space")
    gizmo_module = H.import_addon_package_module("gizmos.perspective_handles_gizmo")
    scene, strip = _setup("convex_render")
    failures = []

    stub = _begin_drag(gizmo_module, nodes, space, scene, strip, 2)
    _move_cursor_to(stub, nodes, scene, strip, (0.7, 0.7))
    good = H.render_scene(scene, "convex_good", frame=1)
    coverage = float((good[..., 3] > 0.5).mean())
    if not 0.6 < coverage < 0.8:
        failures.append(f"the valid pin should cover about 70% of the frame, got {coverage:.3f}")

    _move_cursor_to(stub, nodes, scene, strip, (0.2, 0.2))
    after = H.render_scene(scene, "convex_refused", frame=1)

    if np.isnan(after).any():
        failures.append("the refused drag rendered NaNs")
    if not np.array_equal(good, after):
        changed = float((np.abs(good - after) > 1e-4).any(axis=2).mean())
        failures.append(
            f"the refused drag changed the render: {changed:.3f} of pixels differ")

    return failures


TESTS = (
    test_predicate_separates_the_shapes,
    test_drag_refuses_to_enter_a_concave_shape,
    test_the_handle_moves_again_the_moment_the_drag_reverses,
    test_a_drag_along_the_boundary_keeps_moving,
    test_a_refused_drag_renders_the_shape_it_stopped_at,
)


def run():
    """Run every check in this suite and return a list of failure strings."""
    failures = []
    for test in TESTS:
        try:
            result = test() or []
        except Exception as error:  # noqa: BLE001 - a raising test is a failure
            import traceback
            traceback.print_exc()
            result = [f"{test.__name__} raised {type(error).__name__}: {error}"]
        for failure in result:
            failures.append(f"{test.__name__}: {failure}")
        print(f"  {'FAIL' if result else 'ok  '}  {test.__name__}")
    return failures
