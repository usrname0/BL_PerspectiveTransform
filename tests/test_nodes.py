"""
Tests for compositor node group management.

Covers the data-model behaviours that are easy to get subtly wrong and hard to
notice: clamping, un-sharing a duplicated strip's node group, and the panel's
placeholder values building a transform out of nothing on first write.
"""

import os

from harness import (add_image_strip, import_addon_module, make_scene,
                     make_source_image, scratch_dir)

nodes = import_addon_module("operators.perspective_nodes")
core = import_addon_module("operators.perspective_core")
space = import_addon_module("operators.perspective_space")

SQUEEZE_PIN = ((0.0, 0.0), (0.25, 1.0), (0.75, 1.0), (1.0, 0.0))


def approx(a, b, tolerance=1e-4):
    """Return True if two 2D points agree within tolerance."""
    return abs(a[0] - b[0]) <= tolerance and abs(a[1] - b[1]) <= tolerance


def check_create_and_roundtrip(source, failures):
    """A written pin must read back unchanged, and only one modifier is created."""
    scene = make_scene("nodes_roundtrip")
    strip = add_image_strip(scene, source)

    if nodes.has_perspective(strip):
        failures.append("a fresh strip already reports a perspective modifier")

    nodes.write_pin(strip, scene, SQUEEZE_PIN)
    if not nodes.has_perspective(strip):
        failures.append("write_pin did not create a modifier")

    read_back = nodes.read_pin(strip)
    for index, (got, want) in enumerate(zip(read_back, SQUEEZE_PIN)):
        if not approx(got, want):
            failures.append(f"roundtrip corner {index}: wrote {want}, read {tuple(got)}")

    nodes.write_pin(strip, scene, SQUEEZE_PIN)
    compositor_modifiers = [m for m in strip.modifiers if m.type == 'COMPOSITOR']
    if len(compositor_modifiers) != 1:
        failures.append(f"expected 1 compositor modifier, found {len(compositor_modifiers)}")


def check_clamping(source, failures):
    """Out-of-range corners must be clamped, since the node silently ignores them."""
    scene = make_scene("nodes_clamp")
    strip = add_image_strip(scene, source)
    nodes.write_pin(strip, scene, ((-0.5, -0.5), (0.0, 1.9), (1.5, 1.0), (1.0, 0.0)))

    for index, corner in enumerate(nodes.read_pin(strip)):
        if not (0.0 <= corner.x <= 1.0 and 0.0 <= corner.y <= 1.0):
            failures.append(f"corner {index} escaped the unit square: {tuple(corner)}")


def check_unshare_on_duplicate(source, failures):
    """Editing one of two strips sharing a node group must not move the other."""
    scene = make_scene("nodes_unshare")
    strip_a = add_image_strip(scene, source)
    nodes.write_pin(strip_a, scene, SQUEEZE_PIN)

    strip_b = scene.sequence_editor.strips.new_image(
        name="second", filepath=source, channel=2, frame_start=1)
    shared_group = nodes.find_modifier(strip_a).node_group
    modifier_b = nodes.ensure_modifier(strip_b, scene)
    # Reproduce exactly what duplicating a strip does: same group, two users.
    old_group = modifier_b.node_group
    modifier_b.node_group = shared_group
    if old_group is not None and old_group.users == 0:
        import bpy
        bpy.data.node_groups.remove(old_group)

    if nodes.count_group_users(shared_group) < 2:
        failures.append("test setup failed: node group is not shared")

    nodes.write_pin(strip_b, scene, ((0.0, 0.0), (0.5, 1.0), (1.0, 1.0), (1.0, 0.0)))

    a_corners = nodes.read_pin(strip_a)
    for index, (got, want) in enumerate(zip(a_corners, SQUEEZE_PIN)):
        if not approx(got, want):
            failures.append(
                f"editing a duplicated strip moved the original: corner {index} "
                f"became {tuple(got)}, expected {want}")

    if nodes.find_modifier(strip_a).node_group == nodes.find_modifier(strip_b).node_group:
        failures.append("node group is still shared after an edit")


def check_clear_and_reset(source, failures):
    """Reset keeps the modifier; clear removes it and its orphaned node group."""
    scene = make_scene("nodes_clear")
    strip = add_image_strip(scene, source)
    nodes.write_pin(strip, scene, SQUEEZE_PIN)

    nodes.reset(strip)
    if not nodes.is_identity(nodes.read_pin(strip)):
        failures.append("reset did not return the pin to identity")
    if not nodes.has_perspective(strip):
        failures.append("reset removed the modifier, but should have kept it")

    nodes.write_pin(strip, scene, SQUEEZE_PIN)
    group_name = nodes.find_modifier(strip).node_group.name
    if not nodes.clear(strip, scene):
        failures.append("clear reported nothing to remove")
    if nodes.has_perspective(strip):
        failures.append("clear left the modifier in place")

    import bpy
    if group_name in bpy.data.node_groups:
        failures.append(f"clear orphaned the node group {group_name}")


def check_frame_roundtrip(source, failures):
    """Corners set from frame space must read back to the same frame positions."""
    scene = make_scene("nodes_frame")
    strip = add_image_strip(scene, source)
    strip.transform.scale_x = strip.transform.scale_y = 0.6
    strip.transform.rotation = 0.4
    strip.use_flip_x = True

    nodes.write_pin(strip, scene, SQUEEZE_PIN)
    target = core.get_corners_in_frame(strip, scene)
    core.set_corners_from_frame(strip, scene, target)
    result = core.get_corners_in_frame(strip, scene)

    for index, (a, b) in enumerate(zip(target, result)):
        if not approx(a, b, tolerance=0.01):
            failures.append(
                f"frame roundtrip corner {index}: {tuple(a)} -> {tuple(b)}")


def check_panel_defaults(source, failures):
    """
    The panel's placeholder values must read identity and create on first write.

    PERSPECTIVE_PT_perspective draws these whenever a strip has no transform, so that
    the corners and the filter are visible at their defaults the way Blender's
    own Transform panel shows its own. They store nothing: reading asks the
    strip, and writing builds the node group.
    """
    import bpy

    defaults = import_addon_module("operators.perspective_defaults")
    scene = make_scene("nodes_defaults")
    strip = add_image_strip(scene, source)
    scene.sequence_editor.active_strip = strip

    defaults.register_perspective_defaults()
    try:
        # The properties reach the strip through bpy.context, which in a
        # headless run points at the startup scene rather than this one.
        with bpy.context.temp_override(scene=scene, sequencer_scene=scene):
            stand_in = defaults.get_defaults(bpy.context)
            if stand_in is None:
                failures.append("the placeholder group did not register")
                return

            for index, name in enumerate(defaults.CORNER_PROPS):
                value = tuple(getattr(stand_in, name))
                if not approx(value, nodes.IDENTITY_PIN[index]):
                    failures.append(
                        f"placeholder {name} reads {value}, expected identity "
                        f"{nodes.IDENTITY_PIN[index]}")
            if stand_in.filter != defaults.FILTER_DEFAULT:
                failures.append(
                    f"placeholder filter reads {stand_in.filter!r}, "
                    f"expected {defaults.FILTER_DEFAULT!r}")
            if nodes.has_perspective(strip):
                failures.append("reading a placeholder created a transform")

            # One write, and the strip has a real transform carrying it.
            stand_in.upper_right = (0.8, 0.9)
            if not nodes.has_perspective(strip):
                failures.append("writing a placeholder did not create the transform")
                return

            pin = nodes.read_pin(strip)
            expected = list(nodes.IDENTITY_PIN)
            expected[2] = (0.8, 0.9)
            for index, (got, want) in enumerate(zip(pin, expected)):
                if not approx(got, want):
                    failures.append(
                        f"after the placeholder write, corner {index} is "
                        f"{tuple(got)}, expected {want}")

            # And now the placeholder is a view onto the socket it created.
            if not approx(tuple(stand_in.upper_right), (0.8, 0.9)):
                failures.append(
                    f"placeholder reads back {tuple(stand_in.upper_right)} "
                    f"rather than the socket it wrote")

            stand_in.filter = 'Nearest'
            node = nodes.get_corner_pin_node(nodes.find_modifier(strip).node_group)
            written = node.inputs[defaults.FILTER_SOCKET].default_value
            if written != 'Nearest':
                failures.append(
                    f"placeholder filter wrote {written!r} to the socket, "
                    f"expected 'Nearest'")
            if stand_in.filter != 'Nearest':
                failures.append("placeholder filter did not read its own write back")

            # A write holds the placeholder rows on screen for a moment, so the
            # drag that created the transform is not cut off when the panel
            # would otherwise swap in the socket rows underneath the cursor.
            if not defaults.is_handing_over():
                failures.append("a placeholder write did not hold the handover open")
            defaults._handover["until"] = 0.0
            if defaults.is_handing_over():
                failures.append("the handover did not close when its deadline passed")
    finally:
        defaults.unregister_perspective_defaults()

    # unregister has to take the handover timer with it, or it outlives the addon.
    import bpy as _bpy
    if _bpy.app.timers.is_registered(defaults._finish_handover):
        failures.append("the handover timer survived unregister")


def run():
    """Run the node management suite and return a list of failure strings."""
    failures = []
    source = make_source_image(os.path.join(scratch_dir(), "source.png"))

    check_create_and_roundtrip(source, failures)
    check_clamping(source, failures)
    check_unshare_on_duplicate(source, failures)
    check_clear_and_reset(source, failures)
    check_frame_roundtrip(source, failures)
    check_panel_defaults(source, failures)
    return failures
