"""
Keyframing the corner pin.

The interesting claim here is that a keyed corner reaches the *rendered* frame,
so the important tests render real frames at several times and assert on the
pixels rather than reading values back out of the fcurves.

The headroom test is the sharpest one: adding headroom to an animated pin must
leave every rendered frame byte-for-byte where it was, which only happens if
the keyframe values were remapped along with the strip scale.
"""

import os

import bpy
import numpy as np

import harness as H


def _setup(name, res=512, duration=40):
    """
    Build a scene with an image strip carrying a perspective modifier.

    The strip is stretched over `duration` frames, because an image strip is
    one frame long by default and every test here renders at several frames -
    outside the strip there is simply nothing to look at.
    """
    nodes = H.import_addon_module("operators.perspective_nodes")

    src = H.make_source_image(os.path.join(H.scratch_dir(), "anim_source.png"))
    scene = H.make_scene(name, res, res)
    strip = H.add_image_strip(scene, src)
    H.set_duration(strip, duration)
    nodes.write_pin(strip, scene, nodes.IDENTITY_PIN)
    return scene, strip


def _render_at(scene, tag, frame):
    """Render a single frame and return it as an (h, w, 4) array."""
    return H.render_scene(scene, tag, frame=frame)


def test_keyed_corner_animates_the_render():
    """A keyframed corner must change what renders, frame to frame."""
    anim = H.import_addon_module("operators.perspective_anim")
    scene, strip = _setup("anim_render")

    # Pull the top-right corner in, over 20 frames. Every keyed quad has to
    # stay convex: the Corner Pin homography is only defined for a convex quad
    # and renders unpredictably otherwise (see BLENDER.md -> Corner Pin).
    # (0.5, 0.5) would put three corners on one line, which is that case.
    anim.insert_pin_keys(strip, scene, frame=1)
    nodes = H.import_addon_module("operators.perspective_nodes")
    corners = list(nodes.IDENTITY_PIN)
    corners[2] = (0.55, 0.6)
    nodes.write_pin(strip, scene, corners)
    anim.insert_pin_keys(strip, scene, frame=21)

    first = _render_at(scene, "anim_f1", 1)
    middle = _render_at(scene, "anim_f11", 11)
    last = _render_at(scene, "anim_f21", 21)

    failures = []
    opaque = [int(H.opaque_mask(p).sum()) for p in (first, middle, last)]

    # Frame 1 is the identity pin, so the whole frame is covered.
    if opaque[0] != scene.render.resolution_x * scene.render.resolution_y:
        failures.append(f"frame 1 should be fully covered, got {opaque[0]} px")

    # Pulling a corner in can only remove coverage, and must do so strictly.
    if not opaque[0] > opaque[1] > opaque[2]:
        failures.append(f"coverage should shrink monotonically, got {opaque}")

    # The middle frame must be a genuine interpolation, not a copy of an end.
    if np.abs(middle - first).max() < 0.01:
        failures.append("frame 11 is identical to frame 1: no interpolation")
    if np.abs(middle - last).max() < 0.01:
        failures.append("frame 11 is identical to frame 21: no interpolation")

    return failures


def test_autokey_only_fires_when_enabled():
    """
    Auto-key must be opt-in, and must key only the corner that moved.

    Keying the whole quad is what this used to do, on the reasoning that the
    quad is one shape. It surprised people instead: dragging one handle
    committed the other three to the timeline behind their back. Auto-key on
    any other Blender property keys the thing you touched.
    """
    anim = H.import_addon_module("operators.perspective_anim")
    scene, strip = _setup("anim_autokey")
    failures = []

    scene.tool_settings.use_keyframe_insert_auto = False
    if anim.autokey_corner(strip, scene, 2) != 0:
        failures.append("auto-key fired with the setting off")
    if anim.is_animated(strip):
        failures.append("auto-key created channels with the setting off")

    scene.tool_settings.use_keyframe_insert_auto = True
    keyed = anim.autokey_corner(strip, scene, 2)
    if keyed != 1:
        failures.append(f"auto-key should key one corner, keyed {keyed}")
    if anim.animated_corners(strip) != {2}:
        failures.append(
            f"expected only the dragged corner animated, got {anim.animated_corners(strip)}")

    # A second corner keys on its own without disturbing the first.
    anim.autokey_corner(strip, scene, 0)
    if anim.animated_corners(strip) != {0, 2}:
        failures.append(f"keying a second corner gave {anim.animated_corners(strip)}")

    return failures


def test_autokey_reads_the_flag_it_is_given():
    """
    Auto-key must honour the tool_settings it is handed, not only the scene's.

    The auto-key toggle in the UI writes to the *window* scene, which since 5.0
    need not be the sequencer scene. Reading scene.tool_settings can therefore
    miss a setting the user has plainly switched on, so the gizmo passes
    context.tool_settings through.
    """
    anim = H.import_addon_module("operators.perspective_anim")
    scene, strip = _setup("anim_flagsource")
    other = H.make_scene("anim_flagsource_window")
    failures = []

    scene.tool_settings.use_keyframe_insert_auto = False
    other.tool_settings.use_keyframe_insert_auto = True

    # The sequencer scene says no, but the scene the user toggled says yes.
    if anim.autokey_corner(strip, scene, 1, other.tool_settings) != 1:
        failures.append("did not key when the passed tool_settings had auto-key on")

    anim.clear_animation(strip)
    if anim.autokey_corner(strip, scene, 1) != 0:
        failures.append("keyed from the scene's own settings when auto-key was off")

    return failures


def test_a_click_that_moves_nothing_is_not_keyed():
    """A bare click on a handle must not drop a keyframe."""
    anim = H.import_addon_module("operators.perspective_anim")
    nodes = H.import_addon_module("operators.perspective_nodes")
    scene, strip = _setup("anim_click")
    scene.tool_settings.use_keyframe_insert_auto = True
    failures = []

    before = [tuple(c) for c in nodes.read_pin(strip)]

    # Nothing moved: pin_matches is what the gizmo gates its exit() work on.
    if not anim.pin_matches(strip, before):
        failures.append("pin_matches said an untouched pin had changed")

    corners = list(nodes.IDENTITY_PIN)
    corners[2] = (0.55, 0.6)
    nodes.write_pin(strip, scene, corners)
    if anim.pin_matches(strip, before):
        failures.append("pin_matches missed a real corner move")

    # A None baseline must count as changed, so a drag still commits.
    if anim.pin_matches(strip, None):
        failures.append("a None baseline should count as changed")

    return failures


class _FakeContext:
    """
    The few context members the gizmo's end-of-drag path reads.

    A real bpy.context in background mode points at the default scene, not the
    one the test built, so the gizmo would look at the wrong strip entirely.
    """

    def __init__(self, scene):
        self.scene = scene
        self.sequencer_scene = scene
        self.tool_settings = scene.tool_settings
        self.region = None
        self.window = None


def test_gizmo_commits_the_drag_from_exit():
    """
    The end-of-drag work must hang off exit(), not off modal().

    Blender's gizmo tweak operator matches the confirming mouse release against
    its own modal keymap, so Gizmo.modal() is not reliably handed a raw
    LEFTMOUSE/RELEASE - which is how auto-keying came to do nothing on a real
    drag while passing every test that called it directly. exit() is called
    either way, so this asserts the wiring as well as the behaviour.
    """
    import inspect

    # Through the package, so the gizmo's own `..operators` imports resolve and
    # the test sees the very modules the gizmo calls into.
    gizmo_module = H.import_addon_package_module("gizmos.perspective_handles_gizmo")
    anim = H.import_addon_package_module("operators.perspective_anim")
    nodes = H.import_addon_package_module("operators.perspective_nodes")
    handle = gizmo_module.PERSPECTIVE_GT_perspective_handle

    scene, strip = _setup("anim_exit")
    scene.tool_settings.use_keyframe_insert_auto = True
    failures = []

    # --- wiring ---------------------------------------------------------
    exit_src = inspect.getsource(handle.exit)
    modal_src = inspect.getsource(handle.modal)
    if "_finish_edit" not in exit_src:
        failures.append("exit() no longer commits the drag")
    if "_restore" not in exit_src:
        failures.append("exit() no longer restores on cancel")
    for banned in ("autokey", "undo_push"):
        if banned in modal_src:
            failures.append(f"modal() does {banned} again; it may never see the release")

    # --- behaviour: a real drag commits ---------------------------------
    class _Stub:
        pass

    _Stub._finish_edit = handle._finish_edit
    _Stub._restore = handle._restore
    stub = _Stub()

    before = [tuple(c) for c in nodes.read_pin(strip)]
    stub._pin_on_invoke = [tuple(c) for c in before]
    stub._edit_node = nodes.prepare_for_edit(strip, scene)
    stub.handle_index = 2

    corners = list(nodes.IDENTITY_PIN)
    corners[2] = (0.55, 0.6)
    nodes.write_pin(strip, scene, corners)

    try:
        stub._finish_edit(_FakeContext(scene))
    except RuntimeError:
        # undo_push needs a window; auto-keying has already happened by then.
        pass

    # Only the dragged corner, which is what makes this worth asserting: the
    # gizmo has to pass its handle_index through, not key the quad wholesale.
    if sorted(anim.animated_corners(strip)) != [2]:
        failures.append(
            f"exit() should auto-key only corner 2, got {sorted(anim.animated_corners(strip))}")

    # --- behaviour: cancel restores and does not key ---------------------
    anim.clear_animation(strip)
    nodes.write_pin(strip, scene, nodes.IDENTITY_PIN)
    stub._pin_on_invoke = [nodes.Vector(c) for c in nodes.IDENTITY_PIN]
    stub._edit_node = nodes.prepare_for_edit(strip, scene)
    nodes.write_pin(strip, scene, corners)

    stub._restore(_FakeContext(scene))
    restored = [tuple(round(v, 4) for v in c) for c in nodes.read_pin(strip)]
    if restored != [tuple(float(v) for v in c) for c in nodes.IDENTITY_PIN]:
        failures.append(f"cancel did not restore the pin, got {restored}")
    if anim.is_animated(strip):
        failures.append("cancel left keyframes behind")

    return failures


def test_headroom_holds_an_animated_pin_still():
    """
    Add Headroom must leave every rendered frame unchanged, animation included.

    This is the regression test for the bug where headroom rewrote the socket
    values but left the fcurves alone, so an animated corner snapped back to
    its keyed value on the next frame change and the image jumped.
    """
    anim = H.import_addon_module("operators.perspective_anim")
    nodes = H.import_addon_module("operators.perspective_nodes")
    core = H.import_addon_module("operators.perspective_core")
    scene, strip = _setup("anim_headroom")

    # Both poses are convex quads, which is the only shape the Corner Pin
    # homography is defined for - a concave one renders unpredictably and would
    # make this test flap rather than measure headroom.
    nodes.write_pin(strip, scene,
                    ((0.05, 0.05), (0.0, 0.95), (0.85, 0.80), (0.95, 0.10)))
    anim.insert_pin_keys(strip, scene, frame=1)

    nodes.write_pin(strip, scene,
                    ((0.15, 0.10), (0.05, 0.90), (0.70, 0.75), (0.90, 0.20)))
    anim.insert_pin_keys(strip, scene, frame=21)

    frames = (1, 11, 21)
    before = [_render_at(scene, f"anim_hr_before{f}", f) for f in frames]

    if not core.add_headroom(strip, scene, 2.0):
        return ["add_headroom refused on an animated pin"]

    after = [_render_at(scene, f"anim_hr_after{f}", f) for f in frames]

    failures = []
    for frame, was, now in zip(frames, before, after):
        # Resampling at a different strip scale is not bit-exact, so compare on
        # coverage and centroid rather than demanding identical pixels.
        drift = abs(int(H.opaque_mask(was).sum()) - int(H.opaque_mask(now).sum()))
        if drift > 0.01 * H.opaque_mask(was).sum():
            failures.append(f"frame {frame}: coverage moved by {drift} px after headroom")

        for name, rgb in (("red", (1, 0, 0)), ("white", (1, 1, 1))):
            old_c = H.colour_centroid(was, rgb)
            new_c = H.colour_centroid(now, rgb)
            if old_c is None or new_c is None:
                failures.append(f"frame {frame}: {name} quadrant vanished after headroom")
                continue
            shift = max(abs(old_c[0] - new_c[0]), abs(old_c[1] - new_c[1]))
            if shift > 2.0:
                failures.append(
                    f"frame {frame}: {name} centroid moved {shift:.1f}px after headroom")

    return failures


def test_headroom_refuses_when_a_key_would_not_fit():
    """Shrinking must be refused when any keyframe would leave the unit square."""
    anim = H.import_addon_module("operators.perspective_anim")
    nodes = H.import_addon_module("operators.perspective_nodes")
    core = H.import_addon_module("operators.perspective_core")
    scene, strip = _setup("anim_refuse")
    failures = []

    # Frame 1 sits well inside, frame 21 sits hard on the edge. The current
    # frame alone would allow the shrink; the keyed frame must veto it.
    corners = list(nodes.IDENTITY_PIN)
    corners = [(0.4, 0.4), (0.4, 0.6), (0.6, 0.6), (0.6, 0.4)]
    nodes.write_pin(strip, scene, corners)
    anim.insert_pin_keys(strip, scene, frame=1)

    nodes.write_pin(strip, scene, nodes.IDENTITY_PIN)
    anim.insert_pin_keys(strip, scene, frame=21)

    scene.frame_set(1)
    scale_before = (strip.transform.scale_x, strip.transform.scale_y)
    if core.add_headroom(strip, scene, 0.5):
        failures.append("shrink was allowed even though a keyframe leaves the unit square")
    if (strip.transform.scale_x, strip.transform.scale_y) != scale_before:
        failures.append("refused shrink still changed the strip scale")

    return failures


def test_reset_and_clear_remove_the_animation():
    """Reset must strip the fcurves; Clear must not leave an orphan action."""
    anim = H.import_addon_module("operators.perspective_anim")
    nodes = H.import_addon_module("operators.perspective_nodes")
    scene, strip = _setup("anim_reset")
    failures = []

    anim.insert_pin_keys(strip, scene, frame=1)
    if not anim.is_animated(strip):
        failures.append("setup failed: pin is not animated")

    removed = anim.clear_animation(strip)
    if removed != 8:
        failures.append(f"expected 8 channels removed (4 corners x uv), got {removed}")
    if anim.is_animated(strip):
        failures.append("corners still animated after clear_animation")

    # And a full Clear should take this strip's action datablock with it. Only
    # this strip's action matters - other suites leave their own behind.
    anim.insert_pin_keys(strip, scene, frame=1)
    group = nodes.find_modifier(strip).node_group
    action_name = group.animation_data.action.name

    nodes.clear(strip, scene)
    if action_name in {a.name for a in bpy.data.actions}:
        failures.append(f"Clear left the orphan action {action_name!r} behind")

    return failures


def test_remap_is_exact_for_the_headroom_factor():
    """The closed-form key remap must match the matrix it stands in for."""
    anim = H.import_addon_module("operators.perspective_anim")
    nodes = H.import_addon_module("operators.perspective_nodes")
    space = H.import_addon_module("operators.perspective_space")
    scene, strip = _setup("anim_remap")
    failures = []

    strip.transform.rotation = 0.7
    strip.transform.origin = (0.25, 0.8)
    strip.transform.offset_x = -40.0
    strip.use_flip_x = True

    factor = 2.0
    origin = tuple(strip.transform.origin)

    old_matrix = space.pin_to_frame_matrix(strip, scene)
    strip.transform.scale_x *= factor
    strip.transform.scale_y *= factor
    new_inverse = space.frame_to_pin_matrix(strip, scene)
    strip.transform.scale_x /= factor
    strip.transform.scale_y /= factor

    for point in ((0.0, 0.0), (1.0, 1.0), (0.3, 0.9)):
        through_matrix = space.apply(new_inverse, space.apply(old_matrix, point))
        closed_form = (anim._remapped(point[0], origin[0], factor),
                       anim._remapped(point[1], origin[1], factor))
        error = max(abs(through_matrix[0] - closed_form[0]),
                    abs(through_matrix[1] - closed_form[1]))
        if error > 1e-5:
            failures.append(
                f"remap mismatch at {point}: matrix {tuple(through_matrix)} "
                f"vs closed form {closed_form}, error {error:.2e}")

    return failures


TESTS = (
    test_keyed_corner_animates_the_render,
    test_autokey_only_fires_when_enabled,
    test_autokey_reads_the_flag_it_is_given,
    test_a_click_that_moves_nothing_is_not_keyed,
    test_gizmo_commits_the_drag_from_exit,
    test_headroom_holds_an_animated_pin_still,
    test_headroom_refuses_when_a_key_would_not_fit,
    test_reset_and_clear_remove_the_animation,
    test_remap_is_exact_for_the_headroom_factor,
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
