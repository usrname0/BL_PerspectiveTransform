"""
Measure what an unkeyed write does to an already-animated property.

This is the "phantom keyframe" report: with auto-keying off, dragging a handle
that has keys on it appears to work, holds while the playhead sits still, and
is gone on the next frame change - with no key anywhere in the Dope Sheet.

It is not a test - nothing here asserts - it answers whether that is ours by
running the identical sequence twice: once on strip.transform.rotation, which
is plain Blender and has nothing to do with this addon, and once on a corner
socket. Part A is self-contained so it also runs on 4.4/4.5, where the addon's
compositor strip modifier does not exist.

    blender.exe --factory-startup --background --python tests/spikes/phantom_key.py

Reported for each step: the value on the original datablock (what the sidebar
and the gizmo read) and the value on the evaluated copy (what the render and
the preview image are built from), so a disagreement between the two shows up
rather than being inferred.
"""

# This spike deliberately speaks two Blender dialects: part A runs on 4.4 and
# 4.5 as well as 5.x, so it reaches for editor.sequences and
# new_effect(frame_end=...) behind hasattr and docstring probes. The workspace
# checks against the 5.2 stubs alone, which know none of the 4.x spellings, and
# nothing here can be annotated into agreeing with both. Strip.transform is the
# other family: it belongs to the concrete strip classes, not to the base.
# See BLENDER.md -> Stub setup.
# pyright: reportAttributeAccessIssue=false, reportArgumentType=false
# pyright: reportCallIssue=false, reportOperatorIssue=false

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

import bpy

KEY_FRAME_A = 1
KEY_FRAME_B = 21
# Halfway between the two keys, so the fcurve value is an interpolated one that
# no keyframe holds - a drag landing back on a key value would prove nothing.
DRAG_FRAME = 11


def _make_scene(name):
    """A scene with one colour strip long enough to hold the two keys."""
    scene = bpy.data.scenes.new(name)
    scene.render.resolution_x = scene.render.resolution_y = 256
    scene.frame_start, scene.frame_end = 1, 40

    # Animation only flushes back to the original datablock - which is what
    # the sidebar, the Dope Sheet and the gizmo read - for the scene the
    # window is showing. Without this the evaluated copy tracks the playhead
    # and the original looks frozen, which is a test artefact, not Blender.
    bpy.context.window.scene = scene

    editor = scene.sequence_editor_create()
    # An empty collection is falsy, so this cannot be an `or` chain.
    strips = editor.strips if hasattr(editor, "strips") else editor.sequences
    # 5.x takes `length`; 4.x takes `frame_end`.
    common = dict(name="pk_strip", type='COLOR', channel=1, frame_start=1)
    if "length" in strips.new_effect.__doc__:
        strip = strips.new_effect(length=40, **common)
    else:
        strip = strips.new_effect(frame_end=41, **common)
    editor.active_strip = strip
    return scene, strip


def _evaluated(scene, strip):
    """The strip as the render sees it: the depsgraph's evaluated copy."""
    with bpy.context.temp_override(scene=scene):
        depsgraph = bpy.context.evaluated_depsgraph_get()
    editor = scene.evaluated_get(depsgraph).sequence_editor
    strips = editor.strips if hasattr(editor, "strips") else editor.sequences
    return strips[strip.name]


def _count_keys(anim_data):
    """
    Total keyframes across an action, whatever layout it uses.

    4.4 moved fcurves out of Action.fcurves into a per-slot channelbag, so a
    spike that reads only one of the two shapes reports zero on half the
    versions it is pointed at.
    """
    action = getattr(anim_data, "action", None)
    if action is None:
        return 0

    layers = getattr(action, "layers", ())
    if not layers:
        return sum(len(curve.keyframe_points) for curve in action.fcurves)

    return sum(len(curve.keyframe_points)
               for layer in layers
               for action_strip in layer.strips
               for bag in getattr(action_strip, "channelbags", ())
               for curve in bag.fcurves)


def _report(label, original, evaluated):
    agree = "" if abs(original - evaluated) < 1e-6 else "   <-- DISAGREE"
    print("  {:<34} original {:+.4f}   evaluated {:+.4f}{}".format(
        label, original, evaluated, agree))


def part_a_rotation():
    """The same sequence on a property this addon does not touch."""
    print("\n=== A. strip.transform.rotation (plain Blender) ===")
    scene, strip = _make_scene("phantom_rotation")

    strip.transform.rotation = 0.0
    strip.transform.keyframe_insert("rotation", frame=KEY_FRAME_A)
    strip.transform.rotation = 0.8
    strip.transform.keyframe_insert("rotation", frame=KEY_FRAME_B)

    read = lambda: (strip.transform.rotation,
                    _evaluated(scene, strip).transform.rotation)

    scene.frame_set(DRAG_FRAME)
    _report("frame {}, before the drag".format(DRAG_FRAME), *read())

    # The drag itself. This is what the gizmo's RNA write looks like, and what
    # dragging Blender's own rotation gizmo with auto-key off looks like.
    strip.transform.rotation = 1.5
    with bpy.context.temp_override(scene=scene):
        bpy.context.view_layer.update()
    _report("after writing 1.5, same frame", *read())

    print("  keyframes anywhere on the scene after the drag: {}".format(
        _count_keys(scene.animation_data)))

    scene.frame_set(DRAG_FRAME + 1)
    _report("frame {}".format(DRAG_FRAME + 1), *read())
    scene.frame_set(DRAG_FRAME)
    _report("back to frame {}".format(DRAG_FRAME), *read())


def part_b_corner():
    """The same sequence on a corner socket."""
    print("\n=== B. corner pin socket (this addon) ===")
    types = bpy.types.StripModifier.bl_rna.properties["type"].enum_items
    if "COMPOSITOR" not in types:
        print("  skipped: no compositor strip modifier before 5.0")
        return

    import harness as H
    nodes = H.import_addon_module("operators.perspective_nodes")
    anim = H.import_addon_module("operators.perspective_anim")

    source = H.make_source_image(os.path.join(H.scratch_dir(), "phantom_src.png"))
    scene = H.make_scene("phantom_corner", 256, 256)
    scene.frame_start, scene.frame_end = 1, 40
    bpy.context.window.scene = scene
    strip = H.add_image_strip(scene, source)
    H.set_duration(strip, 40)
    nodes.write_pin(strip, scene, nodes.IDENTITY_PIN)

    anim.insert_pin_keys(strip, scene, frame=KEY_FRAME_A)
    corners = list(nodes.IDENTITY_PIN)
    corners[1] = (0.75, 0.9)
    nodes.write_pin(strip, scene, corners)
    anim.insert_pin_keys(strip, scene, frame=KEY_FRAME_B)

    socket_name = nodes.CORNER_SOCKETS[1]

    def read():
        group, node = anim._corner_pin(strip)
        original = node.inputs[socket_name].default_value[0]
        with bpy.context.temp_override(scene=scene):
            depsgraph = bpy.context.evaluated_depsgraph_get()
        group_eval = group.evaluated_get(depsgraph)
        evaluated = group_eval.nodes[node.name].inputs[socket_name].default_value[0]
        return original, evaluated

    scene.frame_set(DRAG_FRAME)
    _report("frame {}, before the drag".format(DRAG_FRAME), *read())

    dragged = list(corners)
    dragged[1] = (0.55, 0.7)
    nodes.write_pin(strip, scene, dragged)
    with bpy.context.temp_override(scene=scene):
        bpy.context.view_layer.update()
    _report("after writing 0.55, same frame", *read())

    print("  corners carrying keys after the drag: {}".format(
        sorted(anim.animated_corners(strip))))

    scene.frame_set(DRAG_FRAME + 1)
    _report("frame {}".format(DRAG_FRAME + 1), *read())
    scene.frame_set(DRAG_FRAME)
    _report("back to frame {}".format(DRAG_FRAME), *read())


if __name__ == "__main__":
    print("Blender {}".format(bpy.app.version_string))
    part_a_rotation()
    part_b_corner()
