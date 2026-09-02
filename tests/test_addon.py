"""
Smoke test that the addon package loads, registers and unregisters cleanly.

The old codebase wrapped every registration step in a bare except, so a broken
import surfaced as the tool silently not appearing. This asserts instead.
"""

import importlib
import os
import sys

import bpy

from harness import repo_root


def _load_package():
    """Import the addon package by its directory name, as Blender would."""
    root = repo_root()
    parent = os.path.dirname(root)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    return importlib.import_module(os.path.basename(root))


def run():
    """Register and unregister the addon, reporting anything that breaks."""
    failures = []

    try:
        addon = _load_package()
    except Exception as error:
        return [f"addon package failed to import: {type(error).__name__}: {error}"]

    try:
        addon.register()
    except Exception as error:
        return [f"register() raised {type(error).__name__}: {error}"]

    # Operators and panels land in bpy.types when registered.
    for name in ("SEQUENCER_OT_perspective_activate",
                 "SEQUENCER_OT_perspective_reset",
                 "SEQUENCER_OT_perspective_clear",
                 "SEQUENCER_OT_perspective_add_headroom",
                 "SEQUENCER_PT_perspective"):
        if not hasattr(bpy.types, name):
            failures.append(f"{name} was not registered")

    if not hasattr(bpy.ops.sequencer, "perspective_activate"):
        failures.append("sequencer.perspective_activate operator is missing")

    # Gizmo and GizmoGroup subclasses are not exposed through bpy.types, so
    # registration is confirmed by the fact that registering again is refused.
    gizmos = importlib.import_module(addon.__name__ + ".gizmos")
    for cls in (gizmos.PERSPECTIVE_GT_perspective_handle,
                gizmos.PERSPECTIVE_GGT_perspective_handles):
        try:
            bpy.utils.register_class(cls)
        except (ValueError, RuntimeError):
            continue  # already registered, which is what we want
        bpy.utils.unregister_class(cls)
        failures.append(f"{cls.__name__} was not registered")

    try:
        addon.unregister()
    except Exception as error:
        failures.append(f"unregister() raised {type(error).__name__}: {error}")
        return failures

    # Unregistering must leave nothing behind, or a reload stacks duplicates.
    for name in ("SEQUENCER_PT_perspective", "SEQUENCER_OT_perspective_activate"):
        if hasattr(bpy.types, name):
            failures.append(f"{name} survived unregister()")

    return failures
