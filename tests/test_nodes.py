"""
Tests for compositor node group management.

Covers the data-model behaviours that are easy to get subtly wrong and hard to
notice: clamping, un-sharing a duplicated strip's node group, and headroom
holding the image visually still while it changes the underlying numbers.
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


def check_headroom(source, failures):
    """Headroom must enlarge the strip while leaving the quad visually still."""
    scene = make_scene("nodes_headroom")
    strip = add_image_strip(scene, source)
    nodes.write_pin(strip, scene, SQUEEZE_PIN)

    before = core.get_corners_in_frame(strip, scene)
    scale_before = strip.transform.scale_x

    if not core.add_headroom(strip, scene, 2.0):
        failures.append("add_headroom refused a straightforward enlargement")
        return

    if abs(strip.transform.scale_x - scale_before * 2.0) > 1e-5:
        failures.append(f"scale should have doubled, got {strip.transform.scale_x}")

    after = core.get_corners_in_frame(strip, scene)
    for index, (a, b) in enumerate(zip(before, after)):
        if not approx(a, b, tolerance=0.5):
            failures.append(
                f"headroom moved corner {index} on screen: {tuple(a)} -> {tuple(b)}")

    # The point of headroom is margin to drag into, so no corner should still
    # be sitting on the image edge.
    if core.needs_headroom(strip):
        failures.append("corners are still pinned to the image edge after headroom")

    # Shrinking back below what the corners need must be refused, not silently
    # clamped into a different shape.
    nodes.write_pin(strip, scene, ((0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)))
    if core.add_headroom(strip, scene, 0.25):
        failures.append("removing headroom should have been refused")


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


def run():
    """Run the node management suite and return a list of failure strings."""
    failures = []
    source = make_source_image(os.path.join(scratch_dir(), "source.png"))

    check_create_and_roundtrip(source, failures)
    check_clamping(source, failures)
    check_unshare_on_duplicate(source, failures)
    check_clear_and_reset(source, failures)
    check_headroom(source, failures)
    check_frame_roundtrip(source, failures)
    return failures
