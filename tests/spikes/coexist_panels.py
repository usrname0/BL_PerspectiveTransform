"""
Spike: does re-registering Blender's stock strip panels disturb another addon?

__init__.py raises bl_order on five stock STRIP_PT_* panels so Perspective can
sit under Crop, and bl_order is only read at registration - so each panel is
unregistered and registered again. That is a global change outside this addon's
namespace, and the Blender extension guidelines ask add-ons not to interfere
with each other. This measures what a co-installed addon would actually see.

    blender.exe --factory-startup --background --python tests/spikes/coexist_panels.py
"""

import os
import sys

import bpy

TARGET = "STRIP_PT_adjust_video"

results = []


def raw_draw_funcs(cls):
    """Return the functions Panel.append() stacked onto a class, if any.

    Measured on 5.2.1: _GenericUI.append() replaces cls.draw with a wrapper
    function and hangs the list off the wrapper, not off the class - so this
    has to read cls.__dict__["draw"], and hasattr(cls, "_draw_funcs") is False.
    """
    return getattr(cls.__dict__.get("draw"), "_draw_funcs", [])


def draw_funcs(cls):
    return [f.__name__ for f in raw_draw_funcs(cls)] if cls is not None else None


def check(label, ok, detail=""):
    results.append((label, ok, detail))
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}{' - ' + detail if detail else ''}")


def load_addon():
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(os.path.dirname(here))
    parent = os.path.dirname(root)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    import importlib
    return importlib.import_module(os.path.basename(root))


# --- a stand-in for some other addon that touches the same stock panel -------

_appended_calls = []


def other_addon_draw(self, context):
    _appended_calls.append(1)


class OTHER_PT_child(bpy.types.Panel):
    """A third-party sub-panel parented to a panel we re-register."""
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_category = "Strip"
    bl_label = "Other Addon Child"
    bl_parent_id = TARGET

    def draw(self, context):
        pass


def main():
    addon = load_addon()
    stock = getattr(bpy.types, TARGET)
    original_order = stock.__dict__.get("bl_order")
    print(f"before: {TARGET}.bl_order = {original_order!r}")

    # The other addon registers first, as it would if it loaded first.
    stock.append(other_addon_draw)
    bpy.utils.register_class(OTHER_PT_child)
    subclass_seen = getattr(bpy.types, TARGET)

    # Prove the baseline before touching anything: Panel.append() really does
    # record onto _draw_funcs, and the recorded function really does run.
    check("baseline: append() extended the panel", stock.is_extended(),
          f"draw_funcs={draw_funcs(stock)}")

    print("\n--- after _order_panels_after_perspective() ---")
    addon._order_panels_after_perspective()

    now = getattr(bpy.types, TARGET, None)
    check("stock panel is still registered", now is not None)
    check("bl_order was actually raised",
          now is not None and now.bl_order == addon.PANEL_ORDER_AFTER,
          f"bl_order={getattr(now, 'bl_order', None)!r}")
    check("bpy.types still resolves to the same class object", now is subclass_seen)
    check("the other addon's appended draw func survived",
          now is not None and other_addon_draw in raw_draw_funcs(now),
          f"draw_funcs={draw_funcs(now)}")
    check("the other addon's child panel is still registered",
          getattr(bpy.types, "OTHER_PT_child", None) is not None)
    check("the child panel did not inherit our bl_order",
          "bl_order" not in OTHER_PT_child.__dict__,
          f"resolved bl_order={getattr(OTHER_PT_child, 'bl_order', None)!r}")
    check("all five targets were reordered",
          len(addon._reordered_panels) == len(addon.PANELS_AFTER_PERSPECTIVE),
          f"{len(addon._reordered_panels)}/{len(addon.PANELS_AFTER_PERSPECTIVE)}")

    print("\n--- after _restore_panel_order() ---")
    addon._restore_panel_order()

    restored = getattr(bpy.types, TARGET, None)
    check("stock panel still registered after restore", restored is not None)
    check("bl_order is back to what it was",
          restored is not None and restored.__dict__.get("bl_order") == original_order,
          f"bl_order={restored.__dict__.get('bl_order')!r} (was {original_order!r})")
    check("appended draw func still there after restore",
          restored is not None and other_addon_draw in raw_draw_funcs(restored),
          f"draw_funcs={draw_funcs(restored)}")
    check("child panel still registered after restore",
          getattr(bpy.types, "OTHER_PT_child", None) is not None)
    check("nothing left in _reordered_panels", not addon._reordered_panels)

    # Clean up the stand-in addon the way it would unregister itself.
    bpy.utils.unregister_class(OTHER_PT_child)
    stock.remove(other_addon_draw)

    print("\n--- double register/unregister (addon toggled twice) ---")
    addon._order_panels_after_perspective()
    addon._restore_panel_order()
    addon._order_panels_after_perspective()
    addon._restore_panel_order()
    final = getattr(bpy.types, TARGET, None)
    check("survives being toggled twice", final is not None)
    check("bl_order still original after two cycles",
          final is not None and final.__dict__.get("bl_order") == original_order,
          f"bl_order={final.__dict__.get('bl_order')!r}")

    print("\n" + "=" * 60)
    failed = [r for r in results if not r[1]]
    print(f"FAILED: {len(failed)}" if failed else f"PASSED: {len(results)} checks")
    sys.exit(1 if failed else 0)


main()
