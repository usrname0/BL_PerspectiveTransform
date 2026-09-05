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


class _RecordingLayout:
    """Minimal uiLayout stand-in that records the context each button drew with."""

    def __init__(self):
        # What Blender hands an appended menu draw function: the default, not
        # whatever the menu's own draw() left behind.
        self.operator_context = 'INVOKE_REGION_WIN'
        self.drawn = []

    def operator(self, idname, **_kwargs):
        self.drawn.append((idname, self.operator_context))
        return self


class _RecordingMenu:
    """What Blender passes an appended menu draw function as `self`.

    A named class rather than a type() call: the checker reads a three-argument
    type("Menu", ...) as bpy.types.Menu, whose own layout is a different thing
    entirely.
    """

    def __init__(self):
        self.layout = _RecordingLayout()


class _PreviewSpace:
    view_type = 'PREVIEW'


class _PreviewContext:
    space_data = _PreviewSpace()


def _check_menu_operator_context(addon):
    """Every preview menu entry must draw with INVOKE_REGION_PREVIEW.

    The keymap items live in the "Preview" keymap, which hangs off the
    RGN_TYPE_PREVIEW region. A button drawn with the default
    INVOKE_REGION_WIN sends the shortcut lookup to the timeline region
    instead, where it finds nothing, so the entry appears with no shortcut
    beside it while every builtin next to it shows one. Measured on 5.2.1:
    find_item_from_operator returns nothing under INVOKE_REGION_WIN and "P" /
    "Alt P" under INVOKE_REGION_PREVIEW.
    """
    failures = []
    for menu_name, func in addon._MENUS:
        menu = _RecordingMenu()
        func(menu, _PreviewContext())
        if not menu.layout.drawn:
            failures.append(f"{menu_name}: drew nothing in a preview space")
        for idname, context in menu.layout.drawn:
            if context != 'INVOKE_REGION_PREVIEW':
                failures.append(
                    f"{menu_name}: {idname} drawn with {context}, so its "
                    "shortcut will not show")
    return failures


def _stock_panel_orders():
    """Map every stock strip panel to the bl_order set in its own class dict.

    None where the class defines none, which is what all of them do except
    Custom Properties.
    """
    return {name: getattr(bpy.types, name).__dict__.get("bl_order")
            for name in dir(bpy.types) if name.startswith("STRIP_PT_")}


def _check_stock_panels_untouched(before):
    """Blender's own strip panels must be exactly as the addon found them.

    Earlier versions raised bl_order on five stock panels and re-registered
    them, to sit our panel beneath Crop. The extensions site review rejected
    that outright - an addon does not reorder another addon's or Blender's
    UI - so this pins the absence: same panels, same bl_order, none of them
    unregistered on the way past.
    """
    failures = []
    after = _stock_panel_orders()
    for name, order in before.items():
        if name not in after:
            failures.append(f"{name} is no longer registered")
        elif after[name] != order:
            failures.append(f"{name}.bl_order changed {order!r} -> {after[name]!r}")
    return failures


def run():
    """Register and unregister the addon, reporting anything that breaks."""
    failures = []

    try:
        addon = _load_package()
    except Exception as error:
        return [f"addon package failed to import: {type(error).__name__}: {error}"]

    defaults = importlib.import_module(
        addon.__name__ + ".operators.perspective_defaults")

    before_register = _stock_panel_orders()

    try:
        addon.register()
    except Exception as error:
        return [f"register() raised {type(error).__name__}: {error}"]

    # Operators and panels land in bpy.types when registered.
    for name in ("SEQUENCER_OT_perspective_activate",
                 "SEQUENCER_OT_perspective_reset",
                 "SEQUENCER_OT_perspective_clear",
                 "PERSPECTIVE_PT_perspective"):
        if not hasattr(bpy.types, name):
            failures.append(f"{name} was not registered")

    # The preview sidebar copy of the panel was removed once the Properties
    # one had a home beside Transform and Crop. Registering it again would
    # bring back a whole sidebar tab holding one duplicated panel.
    if hasattr(bpy.types, "SEQUENCER_PT_perspective"):
        failures.append("SEQUENCER_PT_perspective is back in the preview sidebar")

    failures.extend(_check_stock_panels_untouched(before_register))

    if not hasattr(bpy.ops.sequencer, "perspective_activate"):
        failures.append("sequencer.perspective_activate operator is missing")

    # The panel draws these on every strip that has no transform yet, so a
    # missing pointer is a panel that raises on the first strip selected.
    if not hasattr(bpy.types.WindowManager, defaults.WM_PROPERTY):
        failures.append(f"WindowManager.{defaults.WM_PROPERTY} was not registered")

    failures.extend(_check_menu_operator_context(addon))

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
    for name in ("PERSPECTIVE_PT_perspective", "SEQUENCER_OT_perspective_activate"):
        if hasattr(bpy.types, name):
            failures.append(f"{name} survived unregister()")

    if hasattr(bpy.types.WindowManager, defaults.WM_PROPERTY):
        failures.append(f"WindowManager.{defaults.WM_PROPERTY} survived unregister()")

    failures.extend(_check_stock_panels_untouched(before_register))

    return failures
