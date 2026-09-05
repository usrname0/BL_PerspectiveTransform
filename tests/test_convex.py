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

import contextlib
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
        """A bare object wearing the two drag methods under test.

        The state they read is declared here rather than bolted on after the
        fact, so the double says what it stands in for and a reader can see
        the drag's whole working set in one place.
        """

        handle_index: int
        _pin_on_invoke: list
        _pin_corners: list
        _edit_node: object
        _drag_matrix: object
        _last_mouse: tuple

        _drag_to = handle._drag_to
        _accept_corner = handle._accept_corner

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


# A quad only the panel's numeric fields can produce: corner 2 pulled across
# the diagonal between its neighbours. The drag cannot create it, which is
# exactly why a test has to hand it to the drag ready-made.
CONCAVE_PIN = ((0.0, 0.0), (0.0, 1.0), (0.35, 0.35), (1.0, 0.0))


def _walk(stub, nodes, scene, strip, index, destination, steps=20):
    """
    Drag one handle towards a pin-space point, counting the events that moved it.

    A single placement says nothing about a guard that works on travel, and the
    count is the measurement that matters here: a refused drag is not one that
    ends in the wrong place, it is one that ends where it started having
    ignored every event on the way.
    """
    start = tuple(float(v) for v in nodes.read_pin(strip)[index])
    moved = 0
    for step in range(1, steps + 1):
        fraction = step / steps
        point = (start[0] + (destination[0] - start[0]) * fraction,
                 start[1] + (destination[1] - start[1]) * fraction)
        before = tuple(float(v) for v in nodes.read_pin(strip)[index])
        _move_cursor_to(stub, nodes, scene, strip, point)
        after = tuple(float(v) for v in nodes.read_pin(strip)[index])
        if after != before:
            moved += 1
    return moved


def _random_convex_quad(rng, space):
    """
    A convex quad in the unit square, in nodes.CORNER_SOCKETS walk order.

    Each corner is drawn from its own quadrant, which makes a convex quad far
    more often than not; the predicate is asked anyway rather than assumed.
    """
    while True:
        quad = [(rng.uniform(0.0, 0.45), rng.uniform(0.0, 0.45)),
                (rng.uniform(0.0, 0.45), rng.uniform(0.55, 1.0)),
                (rng.uniform(0.55, 1.0), rng.uniform(0.55, 1.0)),
                (rng.uniform(0.55, 1.0), rng.uniform(0.0, 0.45))]
        if space.is_convex_quad(quad):
            return quad


@contextlib.contextmanager
def _registered(operator_class):
    """
    Register an operator class for the duration of one test.

    The suite does not install the addon, so bpy.ops has nothing to call
    otherwise - and the class is taken straight back out again, since
    test_addon registers the whole package and would meet it still there.
    """
    import bpy
    bpy.utils.register_class(operator_class)
    try:
        yield
    finally:
        bpy.utils.unregister_class(operator_class)


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


def test_a_drag_cannot_enter_a_concave_shape():
    """
    The gizmo's drag step must never leave the quad non-convex.

    This calls the gizmo's own _drag_to, so it fails if the guard is removed
    from the drag path even while is_convex_quad and constrain_corner both
    still work.

    Asserted as the property rather than as a position. The guard used to
    refuse such a move whole and the corner stayed exactly where it was, which
    a test could pin to a number; it now slides to the nearest position that
    keeps the quad convex, and which number that is belongs to
    test_constrain_corner_finds_the_nearest_point. What belongs here is that
    the drag consulted it at all: the shape stays convex, the corner does not
    reach the concave target, and it went as far as it could - a hair further
    in and it would not be convex any more.
    """
    nodes = H.import_addon_package_module("operators.perspective_nodes")
    space = H.import_addon_package_module("operators.perspective_space")
    gizmo_module = H.import_addon_package_module("gizmos.perspective_handles_gizmo")
    scene, strip = _setup("convex_drag")
    failures = []

    stub = _begin_drag(gizmo_module, nodes, space, scene, strip, 2)

    # Corner 2 is the top right. A valid move first, so what follows is
    # measured against a corner that had been moving.
    after = _move_cursor_to(stub, nodes, scene, strip, (0.7, 0.7))
    if after[2] != (0.7, 0.7):
        failures.append(f"a convex drag was constrained, corner 2 is {after[2]}")

    # Pulling it to (0.2, 0.2) puts it across the diagonal between its
    # neighbours, which is the concave case.
    _move_cursor_to(stub, nodes, scene, strip, (0.2, 0.2))
    corners = [tuple(float(v) for v in c) for c in nodes.read_pin(strip)]
    if not space.is_convex_quad(corners):
        failures.append(f"a concave drag was written anyway, the pin is {corners}")
    if corners[2][0] < 0.25 and corners[2][1] < 0.25:
        failures.append(f"the corner reached the concave target, it is {corners[2]}")

    # On the wall, not short of it. Measured on 5.2.1 the corner lands at
    # (0.5001, 0.5001), where a further 1e-5 towards the target is already
    # rejected - so the smallest nudge this can ask about is a real one.
    probe = list(corners)
    probe[2] = (corners[2][0] - 1e-5, corners[2][1] - 1e-5)
    if space.is_convex_quad(probe):
        failures.append(
            f"the corner stopped short of the boundary at {corners[2]}; a further "
            "1e-5 towards the target is still convex, so it is not the nearest point")

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

    Projecting the target rather than refusing it does not change that
    argument: the corner is still held on the wall while the cursor travels
    past it, so the accumulation is still what keeps the excursion from piling
    up. The assertion is the property rather than the position - reversing by a
    hair moves the corner by the whole of that hair, with nothing swallowed.
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
    _move_cursor_to(stub, nodes, scene, strip, (0.2, 0.2))
    held = tuple(float(v) for v in nodes.read_pin(strip)[2])
    if held[0] < 0.25 and held[1] < 0.25:
        failures.append(f"the corner followed the cursor into the concave target: {held}")

    # Now reverse by a hair. The cursor is still deep inside the disallowed
    # region, so an absolute reading would refuse this too and the corner would
    # sit there for another 0.3 of travel.
    _move_cursor_to(stub, nodes, scene, strip, (0.25, 0.25))
    after = tuple(float(v) for v in nodes.read_pin(strip)[2])
    moved = (after[0] - held[0], after[1] - held[1])
    if abs(moved[0] - 0.05) > 1e-3 or abs(moved[1] - 0.05) > 1e-3:
        failures.append(
            f"reversing the drag by (0.05, 0.05) moved the corner by {moved}; off "
            "the wall it should follow the cursor one for one")

    return failures


def test_a_drag_along_the_boundary_keeps_moving():
    """
    A drag at a shallow angle into the boundary must keep making progress.

    The user is mostly moving parallel to the wall, so nearly every event has
    somewhere legal to go. What the guard used to do was refuse the move whole
    and retry X alone and then Y alone, which is a coarse approximation of the
    projection and agrees with it only where the boundary is axis-aligned.
    Measured on 5.2.1 with Upper Left pulled across to x=0.35, so the wall
    Upper Right meets runs at no axis's angle: 60 events of (-0.020, -0.012)
    moved nothing on 36 of them under the axis retries and the handle crawled.
    Under the projection all 60 move.

    The count is the assertion, not the destination. A drag that stops dead is
    the failure being prevented, and where 60 events of sliding end up is the
    projection's business.
    """
    nodes = H.import_addon_package_module("operators.perspective_nodes")
    space = H.import_addon_package_module("operators.perspective_space")
    gizmo_module = H.import_addon_package_module("gizmos.perspective_handles_gizmo")
    scene, strip = _setup("convex_slide")
    failures = []

    # Convex, so the guard is armed rather than in its "do not make it worse"
    # escape case, and the wall it raises for corner 2 is diagonal.
    nodes.write_pin(strip, scene, ((0.0, 0.0), (0.35, 1.0), (1.0, 1.0), (1.0, 0.0)))
    stub = _begin_drag(gizmo_module, nodes, space, scene, strip, 2)

    steps = 60
    moved = _walk(stub, nodes, scene, strip, 2,
                  (1.0 - steps * 0.020, 1.0 - steps * 0.012), steps=steps)
    if moved != steps:
        failures.append(
            f"a shallow drag into a diagonal boundary moved on {moved} of {steps} "
            "events; it should slide along the wall rather than stall against it")
    if not space.is_convex_quad(nodes.read_pin(strip)):
        failures.append("sliding along the boundary left the quad non-convex")

    return failures


def test_a_constrained_drag_still_renders():
    """
    The guard has to hold a usable *render*, not just a value the predicate likes.

    The failure this exists to prevent is not a wrong number but an unusable
    frame: measured on 5.2.1 a concave pin renders the whole frame filled edge
    to edge with garbage, and a collinear one renders an empty frame. Coverage
    alone cannot tell a broken pin from a working one, because an untransformed
    pin fills the frame too - so the strip is dragged into a strong but valid
    shape covering about 70 percent first, and the drag into the concave target
    has to leave something between the two failures.

    This used to assert the render was bit-identical afterwards, which was only
    available because a refused move left the corner exactly where it was. The
    corner now slides to the wall, and on the wall the quad is at its thinnest
    legal shape - measured, 17.4 percent coverage, which is the 1e-4 row of the
    sweep in DEV.md -> Convexity and was checked there to render correctly. So
    the assertion is the band: not the empty frame, not the full one.
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
        failures.append(
            f"the valid pin should cover about 70% of the frame, got {coverage:.3f}")

    _move_cursor_to(stub, nodes, scene, strip, (0.2, 0.2))
    after = H.render_scene(scene, "convex_constrained", frame=1)
    coverage = float((after[..., 3] > 0.5).mean())

    if np.isnan(after).any():
        failures.append("the constrained drag rendered NaNs")
    if not space.is_convex_quad(nodes.read_pin(strip)):
        failures.append("the constrained drag left the quad non-convex")
    if coverage > 0.9:
        failures.append(
            f"the constrained drag filled {coverage:.3f} of the frame; a concave "
            "pin renders edge to edge with garbage, an untransformed one fills it too")
    if coverage < 0.05:
        failures.append(
            f"the constrained drag left only {coverage:.3f} of the frame covered; "
            "a collinear pin renders empty")

    return failures


def test_a_drag_escapes_a_shape_it_did_not_make():
    """
    A drag must be able to leave a non-convex shape, and not to re-enter one.

    The guard's rule is "do not make it worse", not "must be convex", and the
    difference only shows from inside a bad quad. Only the panel's numeric
    fields can produce one - they write their socket and nothing in Python sits
    between - and a guard that asks solely whether the candidate is convex
    refuses every small step out of it, because a step out of a bad shape is
    still a bad shape. Measured on 5.2.1 before the rule changed: all four
    handles dead in every direction, 0 of 40 events moving anything, against 33
    of 40 for the same walk from a convex start. That left the Make Convex
    button as the only way back out of a state the panel could reach in one
    slider drag.

    Asserted as properties rather than as positions: where a corner ends up in
    a shape the guard is not constraining is not the point, and pinning it to a
    number here would make this a test of the drag maths instead.

    Every case starts a fresh strip, because a drag that escapes is supposed to
    change the shape and the next handle has to meet the original one.
    """
    nodes = H.import_addon_package_module("operators.perspective_nodes")
    space = H.import_addon_package_module("operators.perspective_space")
    gizmo_module = H.import_addon_package_module("gizmos.perspective_handles_gizmo")
    failures = []

    for index, destination in ((0, (0.9, 0.1)), (1, (0.1, 0.9)),
                               (2, (0.9, 0.9)), (3, (0.9, 0.1))):
        scene, strip = _setup(f"convex_escape_{index}")
        nodes.write_pin(strip, scene, CONCAVE_PIN)
        if space.is_convex_quad(nodes.read_pin(strip)):
            failures.append(f"corner {index}: the fixture is not concave to begin with")
            continue

        stub = _begin_drag(gizmo_module, nodes, space, scene, strip, index)
        moved = _walk(stub, nodes, scene, strip, index, destination)
        if moved != 20:
            failures.append(
                f"handle {index} moved on {moved} of 20 events inside a shape it "
                "did not make; the guard is refusing moves out of a bad quad")

        # Corner 2 is the one across the diagonal, so it is the one whose drag
        # has to end somewhere renderable. No other single corner can reach
        # that concavity, so the other three are not asked to fix it - they
        # only have to be free to move.
        if index == 2 and not space.is_convex_quad(nodes.read_pin(strip)):
            failures.append(
                "dragging the corner that broke the quad back out left it concave")

    # And the escape is one-way. This is the half that keeps "do not make it
    # worse" from quietly meaning "anything goes": the moment the shape is
    # sound again the guard re-arms, mid-drag, on the same handle.
    scene, strip = _setup("convex_escape_oneway")
    nodes.write_pin(strip, scene, CONCAVE_PIN)
    stub = _begin_drag(gizmo_module, nodes, space, scene, strip, 2)
    _walk(stub, nodes, scene, strip, 2, (0.95, 0.95))
    if not space.is_convex_quad(nodes.read_pin(strip)):
        failures.append("the escape drag never reached a convex shape")
    else:
        _walk(stub, nodes, scene, strip, 2, (0.2, 0.2))
        if not space.is_convex_quad(nodes.read_pin(strip)):
            failures.append(
                "the same drag went straight back into a concave shape; the "
                "guard did not re-arm once the quad was sound")

    return failures


def test_constrain_corner_result_is_always_convex():
    """
    Every position the projection returns must satisfy the predicate it serves.

    A guard whose own output its own test rejects is worse than no guard, and
    that is the failure this catches: the projection lands exactly ON a
    constraint, so the cross product it produces comes out at CONVEX_EPSILON
    plus or minus a rounding error and is_convex_quad rejects about half of
    them. With CONVEX_MARGIN set to zero this fails on roughly a third of the
    cases below.

    The result is checked exactly as returned - a mathutils.Vector, which is
    float32, as is the socket it is bound for. That is deliberate. Quantizing a
    corner to float32 moves the cross products around it by up to about 1e-7,
    a thousand times the margin that sufficed in double precision, so a version
    of this test working in doubles would pass against a margin the addon
    cannot actually use. See CONVEX_MARGIN's comment for the sweep.
    """
    import random

    space = H.import_addon_package_module("operators.perspective_space")
    failures = []

    rng = random.Random(1)
    trials = 2000
    rejected = refused = projected = 0
    for _ in range(trials):
        quad = _random_convex_quad(rng, space)
        index = rng.randrange(4)
        target = (rng.uniform(-0.4, 1.4), rng.uniform(-0.4, 1.4))
        result = space.constrain_corner(quad, index, target)
        if result is None:
            refused += 1
            continue
        candidate = list(quad)
        candidate[index] = result
        if not space.is_convex_quad(candidate):
            rejected += 1
        if (float(result[0]), float(result[1])) != target:
            projected += 1

    if rejected:
        failures.append(
            f"{rejected} of {trials} projected positions are not convex by "
            "is_convex_quad - CONVEX_MARGIN is too small to survive float32")
    if refused:
        failures.append(
            f"{refused} of {trials} convex quads were refused outright; a quad "
            "that is already convex always has room for one of its corners")
    if projected < trials // 10:
        failures.append(
            f"only {projected} of {trials} targets were projected at all, so "
            "this test is no longer exercising the projection")

    return failures


def test_constrain_corner_passes_a_valid_target_through():
    """
    A target that is already valid must come back untouched, bit for bit.

    A guard that projected unconditionally would move values nobody asked it to
    move - and on the panel's placeholder rows that is a slider quietly
    disagreeing with the cursor. Targets are rounded to float32 first, because
    that is what a socket or a Blender property can hold, so the comparison can
    then be exact rather than approximate.
    """
    import random
    import struct

    space = H.import_addon_package_module("operators.perspective_space")
    failures = []

    def f32(value):
        """Round to what a socket can actually store."""
        return struct.unpack("f", struct.pack("f", value))[0]

    rng = random.Random(7)
    checked = moved = 0
    for _ in range(2000):
        quad = _random_convex_quad(rng, space)
        index = rng.randrange(4)
        target = (f32(rng.uniform(0.0, 1.0)), f32(rng.uniform(0.0, 1.0)))
        candidate = list(quad)
        candidate[index] = target
        # Only a target that is genuinely valid has a right to come back
        # unchanged, and CONVEX_MARGIN makes valid a hair stricter than the
        # predicate - so ask for room to spare rather than for the boundary.
        if not space.is_convex_quad(candidate, epsilon=space.CONVEX_EPSILON * 10.0):
            continue
        checked += 1
        result = space.constrain_corner(quad, index, target)
        if result is None or (float(result[0]), float(result[1])) != target:
            moved += 1

    if checked < 100:
        failures.append(
            f"only {checked} valid targets were generated, too few to say "
            "anything about the pass-through")
    if moved:
        failures.append(
            f"{moved} of {checked} already-valid targets came back changed")

    return failures


def test_constrain_corner_finds_the_nearest_point():
    """
    The projection has to be the *nearest* valid position, not merely a valid one.

    An approximation would still guard correctly and would still pass every
    other test here, while putting the corner somewhere the user did not point.
    The gizmo's own refuse-then-retry-one-axis is exactly such an
    approximation, and on a boundary that is not axis-aligned it lands
    somewhere quite different - so the answer is compared against a brute-force
    scan.

    The scan asks is_convex_quad rather than the module's own half-planes: a
    test that reused the implementation's idea of the feasible set could not
    catch the implementation getting that set wrong. The tolerance covers the
    one legitimate difference between the two, CONVEX_MARGIN, which is worth
    about 1e-6 of position.
    """
    import random

    space = H.import_addon_package_module("operators.perspective_space")
    failures = []

    rng = random.Random(11)
    grid = 200
    worst = 0.0
    for _ in range(12):
        quad = _random_convex_quad(rng, space)
        index = rng.randrange(4)
        target = (rng.uniform(-0.3, 1.3), rng.uniform(-0.3, 1.3))
        result = space.constrain_corner(quad, index, target)
        if result is None:
            failures.append("a convex quad was refused")
            continue
        ours = ((float(result[0]) - target[0]) ** 2
                + (float(result[1]) - target[1]) ** 2) ** 0.5

        candidate = list(quad)
        best = None
        for step_x in range(grid + 1):
            x = step_x / grid
            for step_y in range(grid + 1):
                y = step_y / grid
                candidate[index] = (x, y)
                if not space.is_convex_quad(candidate):
                    continue
                distance = ((x - target[0]) ** 2 + (y - target[1]) ** 2) ** 0.5
                if best is None or distance < best:
                    best = distance
        if best is not None:
            worst = max(worst, ours - best)

    if worst > 1e-3:
        failures.append(
            f"the projection is {worst:.3e} further from the target than a "
            f"{grid + 1}x{grid + 1} scan found, so it is not the nearest point")

    return failures


def test_constrain_corner_refuses_a_degenerate_quad():
    """
    Three fixed corners on one line leaves nowhere for the fourth to go.

    The answer has to be None rather than an invented point: the collinear
    triple is one of the four cross products, and the moving corner is not in
    it, so no position for it can rescue the quad. The second half of the check
    is that the refusal is not simply a blanket one.
    """
    space = H.import_addon_package_module("operators.perspective_space")
    nodes = H.import_addon_package_module("operators.perspective_nodes")
    failures = []

    collinear = ((0.0, 0.0), (0.5, 0.5), (1.0, 1.0), (1.0, 0.0))
    result = space.constrain_corner(collinear, 3, (0.9, 0.1))
    if result is not None:
        failures.append(
            f"a quad whose other three corners are collinear answered "
            f"{tuple(result)}, expected None")

    sound = space.constrain_corner(nodes.IDENTITY_PIN, 3, (0.9, 0.1))
    if sound is None:
        failures.append("a sound quad was refused too, so the refusal says nothing")

    return failures


def test_a_placeholder_write_cannot_go_concave():
    """
    The panel's placeholder rows must not be able to write an unrenderable quad.

    They are the one numeric path that runs Python before the value lands, so
    they get the same guard the drag has. Once the strip has a transform the
    rows bind straight to the sockets and nothing can intercept them - that is
    the gap Make Convex exists for, and it is not this test.
    """
    import bpy

    nodes = H.import_addon_package_module("operators.perspective_nodes")
    space = H.import_addon_package_module("operators.perspective_space")
    defaults = H.import_addon_package_module("operators.perspective_defaults")
    failures = []

    defaults.register_perspective_defaults()

    # Corner 2 pulled across the diagonal between its neighbours, on a strip
    # whose other three corners are still identity.
    scene, strip = _setup("convex_placeholder_bad")
    nodes.clear(strip, scene)
    with bpy.context.temp_override(scene=scene, sequencer_scene=scene):
        stand_in = defaults.get_defaults(bpy.context)
        stand_in.upper_right = CONCAVE_PIN[2]
    if not nodes.has_perspective(strip):
        failures.append("the write was dropped entirely instead of constrained")
    elif not space.is_convex_quad(nodes.read_pin(strip)):
        pin = [tuple(round(float(v), 4) for v in c) for c in nodes.read_pin(strip)]
        failures.append(f"a placeholder wrote a concave quad: {pin}")

    # And a value it has no business touching must arrive unchanged.
    scene, strip = _setup("convex_placeholder_ok")
    nodes.clear(strip, scene)
    with bpy.context.temp_override(scene=scene, sequencer_scene=scene):
        stand_in = defaults.get_defaults(bpy.context)
        stand_in.upper_right = (0.75, 0.9)
    written = tuple(float(v) for v in nodes.read_pin(strip)[2])
    if abs(written[0] - 0.75) > 1e-6 or abs(written[1] - 0.9) > 1e-6:
        failures.append(f"a valid placeholder write was moved to {written}")

    return failures


def test_make_convex_repairs_a_concave_quad():
    """
    Make Convex must turn a concave pin into one that renders.

    Asserted on the rendered frame, because the value alone would not settle
    it: measured on 5.2.1 a concave pin fills the frame edge to edge with
    garbage, and so does no pin at all - so an operator that "repaired" the
    quad by clearing it back to identity would look like one that worked, on
    coverage and on convexity both. What separates them here is that the repair
    is the *nearest* convex position, which puts the corner on the boundary and
    renders a thin quad: a full frame before, a sliver after.
    """
    import bpy
    import numpy as np

    nodes = H.import_addon_package_module("operators.perspective_nodes")
    space = H.import_addon_package_module("operators.perspective_space")
    ops = H.import_addon_package_module("operators.perspective_operators")
    scene, strip = _setup("convex_repair")
    failures = []

    nodes.write_pin(strip, scene, CONCAVE_PIN)
    broken = H.render_scene(scene, "convex_repair_broken", frame=1)
    if float((broken[..., 3] > 0.5).mean()) < 0.99:
        failures.append(
            "the fixture should render a full frame of garbage; a concave pin "
            "that no longer does means this test has stopped measuring anything")

    with _registered(ops.SEQUENCER_OT_perspective_make_convex):
        with bpy.context.temp_override(scene=scene, sequencer_scene=scene,
                                       active_strip=strip):
            if not ops.SEQUENCER_OT_perspective_make_convex.poll(bpy.context):
                failures.append("the operator did not poll on a concave quad")
            # The addon's own operator, which no stub can know about.
            result = bpy.ops.sequencer.perspective_make_convex()  # pyright: ignore[reportAttributeAccessIssue]
            if 'FINISHED' not in result:
                failures.append(f"the operator returned {result}")
            still_offered = ops.SEQUENCER_OT_perspective_make_convex.poll(bpy.context)

    if not space.is_convex_quad(nodes.read_pin(strip)):
        failures.append("the quad is still not convex after the repair")
    if still_offered:
        failures.append("the operator still offers itself on a repaired quad")

    moved = sum(1 for got, was in zip(nodes.read_pin(strip), CONCAVE_PIN)
                if abs(float(got[0]) - was[0]) > 1e-4
                or abs(float(got[1]) - was[1]) > 1e-4)
    if moved != 1:
        failures.append(f"{moved} corners moved; the repair should move exactly one")

    repaired = H.render_scene(scene, "convex_repair_fixed", frame=1)
    coverage = float((repaired[..., 3] > 0.5).mean())
    if np.isnan(repaired).any():
        failures.append("the repaired pin rendered NaNs")
    if not 0.01 < coverage < 0.9:
        failures.append(
            f"the repaired frame covers {coverage:.3f} of the frame; a full one "
            "means a concave or an identity pin is still what is being rendered")

    return failures


def test_make_convex_overwrites_a_bad_keyframe():
    """
    On an animated corner the bad value is in a keyframe, so the key has to change.

    Writing only the socket looks like it worked and is undone by the next
    frame change, because an animated property is driven by its fcurve - the
    phantom keyframe in DEV.md. Reset had to learn this rule already; the
    repair meets it by auto-keying the corner it moved, exactly as a drag does.

    Stepping the frame away and back is the only thing that tells a written key
    from a written socket.
    """
    import bpy

    nodes = H.import_addon_package_module("operators.perspective_nodes")
    space = H.import_addon_package_module("operators.perspective_space")
    anim = H.import_addon_package_module("operators.perspective_anim")
    ops = H.import_addon_package_module("operators.perspective_operators")
    scene, strip = _setup("convex_repair_keyed")
    failures = []

    nodes.write_pin(strip, scene, CONCAVE_PIN)
    anim.insert_corner_key(strip, scene, 2, frame=1)
    scene.tool_settings.use_keyframe_insert_auto = True

    with _registered(ops.SEQUENCER_OT_perspective_make_convex):
        with bpy.context.temp_override(scene=scene, sequencer_scene=scene,
                                       active_strip=strip,
                                       tool_settings=scene.tool_settings):
            bpy.ops.sequencer.perspective_make_convex()  # pyright: ignore[reportAttributeAccessIssue]

    repaired = tuple(float(v) for v in nodes.read_pin(strip)[2])
    scene.frame_set(5)
    scene.frame_set(1)
    after = tuple(float(v) for v in nodes.read_pin(strip)[2])

    if after != repaired:
        failures.append(
            f"the corner read {repaired} after the repair and {after} after a "
            "frame change, so the fcurve overwrote it - the key was not keyed")
    if not space.is_convex_quad(nodes.read_pin(strip)):
        failures.append("the concave shape came back on the next frame change")

    return failures


TESTS = (
    test_predicate_separates_the_shapes,
    test_a_drag_cannot_enter_a_concave_shape,
    test_the_handle_moves_again_the_moment_the_drag_reverses,
    test_a_drag_along_the_boundary_keeps_moving,
    test_a_constrained_drag_still_renders,
    test_a_drag_escapes_a_shape_it_did_not_make,
    test_constrain_corner_result_is_always_convex,
    test_constrain_corner_passes_a_valid_target_through,
    test_constrain_corner_finds_the_nearest_point,
    test_constrain_corner_refuses_a_degenerate_quad,
    test_a_placeholder_write_cannot_go_concave,
    test_make_convex_repairs_a_concave_quad,
    test_make_convex_overwrites_a_bad_keyframe,
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
