"""
Every callback this addon defines must be one Blender will actually dispatch.

A method with a protocol-looking name on the wrong class is invisible dead
code. It reads as a callback, orphan scanning skips it because the name looks
like an override, and nothing will ever point at it. This project carried one,
removed on 2026-09-04:

    PERSPECTIVE_GT_perspective_handle.draw_prepare   a GizmoGroup callback
                                                     sitting on a Gizmo

It claimed to keep the handle visible regardless of group state, and could not:
bpy.types.Gizmo.bl_rna.functions does not list draw_prepare on 5.0.1, 5.1.2 or
5.2.1, so Blender was never going to call it. What actually keeps the handles
visible is the group's refresh(), which sets hide per handle every redraw.

The check here is not a list of names. It is the rule that one broke:

    a public method on a registered class must appear in that class's own
    bl_rna.functions, and must not collide with one of its bl_rna properties

bl_rna.functions enumerates the callback set Blender dispatches, so a public
method missing from it can never fire, whatever it is called. Reading RNA at run
time rather than hardcoding the callback names keeps this true across Blender
versions instead of going stale - see BLENDER.md -> Which callbacks belong to
Gizmo and which to GizmoGroup.

Private helpers are exempt by their leading underscore: a name Blender was
never going to call is not claiming to be a callback.

The same probe settles the second half of the select_id defect. select_id is
not an RNA property of Gizmo on any supported version, so assigning it made an
ordinary Python attribute Blender ignores; it is checked here rather than in a
comment.
"""

import importlib
import os
import sys

import bpy

from harness import repo_root


def _load_gizmo_module():
    """Import the gizmo module by package name, as Blender would."""
    root = repo_root()
    parent = os.path.dirname(root)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    return importlib.import_module(
        os.path.basename(root) + ".gizmos.perspective_handles_gizmo")


def _public_methods(cls):
    """Callables the class itself defines, minus private helpers and bl_*.

    Only the class's own __dict__ - an inherited method is Blender's own and is
    not this addon claiming anything.
    """
    return sorted(
        name for name, value in vars(cls).items()
        if callable(value) or isinstance(value, (classmethod, staticmethod))
        if not name.startswith("_") and not name.startswith("bl_"))


def _check_dispatched(cls, base):
    """Every public method on cls must be a callback base actually dispatches."""
    # bl_rna is typed BlenderRNA by the stubs and is a Struct at run time, so
    # .functions is real and only the stub disagrees.
    functions = base.bl_rna.functions  # pyright: ignore[reportAttributeAccessIssue]
    dispatched = set(functions.keys())
    return [f"{cls.__name__}.{name} is not in {base.__name__}.bl_rna.functions, "
            f"so Blender will never call it"
            for name in _public_methods(cls) if name not in dispatched]


def _check_no_shadowed_property(cls, base):
    """The select / select_id shape: a method sitting on top of a property.

    Defining one does not make it a callback. It makes every Python read of
    that property return a bound method instead of its value, which is always
    truthy and never what the reader wanted.
    """
    properties = set(base.bl_rna.properties.keys())
    return [f"{cls.__name__}.{name} shadows the RNA property {base.__name__}.{name}"
            for name in _public_methods(cls) if name in properties]


def _check_select_id_stays_gone(gizmos):
    """Named explicitly, because this is the one that shipped.

    2.2.1 assigned select_id on the handle and returned it from test_select.
    Gizmo has no such property, so the assignment went nowhere; the value that
    matters is handle_index, which the group sets and invoke() reads.
    """
    failures = []
    handle = gizmos.PERSPECTIVE_GT_perspective_handle

    if "select_id" in bpy.types.Gizmo.bl_rna.properties:
        failures.append("Gizmo.select_id is an RNA property on this Blender - "
                        "the reasoning behind removing it needs rechecking")

    if "draw_prepare" in vars(handle):
        failures.append("Gizmo.draw_prepare is back (it is a GizmoGroup callback)")

    # handle_index is a custom attribute too, but a real one: the addon reads
    # it back itself, which is exactly what select_id never did. It has to stay
    # a bare annotation of an ordinary type - a bpy.props declaration here
    # would be a property the addon then writes over in setup(), and the drag
    # reads a plain attribute either way. See BLENDER.md -> Bare class
    # annotations are safe on a registered class.
    annotations = vars(handle).get("__annotations__", {})
    if annotations.get("handle_index") is not int:
        failures.append(
            "handle_index is annotated "
            f"{annotations.get('handle_index')!r} rather than int")

    return failures


def run():
    """Check both gizmo classes against the RNA Blender will dispatch from."""
    try:
        gizmos = _load_gizmo_module()
    except Exception as error:
        return [f"gizmo module failed to import: {type(error).__name__}: {error}"]

    pairs = ((gizmos.PERSPECTIVE_GT_perspective_handle, bpy.types.Gizmo),
             (gizmos.PERSPECTIVE_GGT_perspective_handles, bpy.types.GizmoGroup))

    failures = []
    for cls, base in pairs:
        failures.extend(_check_dispatched(cls, base))
        failures.extend(_check_no_shadowed_property(cls, base))
    failures.extend(_check_select_id_stays_gone(gizmos))
    return failures
