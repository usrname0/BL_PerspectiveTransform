"""
Check the placeholder handover in a live GUI session.

The panel draws WindowManager placeholders until a strip has a transform, then
swaps to the Corner Pin sockets. Doing that swap the instant the transform
appears destroys the button the user is dragging, and a number field hides and
restores the cursor, so the pointer jumps. perspective_defaults.HANDOVER_DELAY
holds the placeholder rows on screen until writing has stopped.

This writes one corner through the placeholder property - the same path a panel
edit takes - and shoots the panel twice:

    handover_during.png   inside the window: placeholder rows, new value, no dots
    handover_after.png    past it: socket rows, same value, animate dots present

The two must be identical apart from the decorator column, and the second must
happen with no further input - the timer redraws the panel on its own.

    blender.exe --factory-startup --python tests/spikes/handover_shot.py

Note: no --background. Same shape as panel_order_shot.py, and the same three
non-obvious requirements apply - see its docstring.

**What this cannot check** is the thing the delay exists for: whether a click-
drag survives. A button drag cannot be driven from a script any more than a
gizmo drag can. What it does establish is that the button under the cursor is
not replaced during the window, which is the mechanism the jump came from.
"""

import importlib
import os
import sys

import bpy

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(REPO))

bpy.context.preferences.view.show_splash = False

addon = importlib.import_module(os.path.basename(REPO))
operators = importlib.import_module(addon.__name__ + ".operators.perspective_operators")
defaults = importlib.import_module(addon.__name__ + ".operators.perspective_defaults")
nodes = importlib.import_module(addon.__name__ + ".operators.perspective_nodes")

# Draw the panel open, so the corner rows are in the shot.
operators.STRIP_PT_perspective.bl_options = set()
addon.register()

OUT = os.path.join(REPO, "tests", "_output")
_area = {}
_state = {"tries": 0, "strip": None}


def setup():
    """Build a strip, point the workspace at its scene, and lay out the screen."""
    scene = bpy.context.scene
    scene.sequence_editor_create()
    strip = scene.sequence_editor.strips.new_effect(
        name="Spike", type='COLOR', channel=1, frame_start=1, length=50)
    strip.select = True
    scene.sequence_editor.active_strip = strip
    bpy.context.window.workspace.sequencer_scene = scene
    _state["strip"] = strip

    areas = sorted(bpy.context.window.screen.areas,
                   key=lambda a: a.width * a.height, reverse=True)
    areas[0].type = 'SEQUENCE_EDITOR'
    _area["props"] = next(a for a in bpy.context.window.screen.areas
                          if a.type == 'PROPERTIES')
    return None


def show_tab():
    """Switch the Properties editor to the Strip tab, once it has one."""
    try:
        _area["props"].spaces.active.context = 'STRIP'
    except TypeError:
        _state["tries"] += 1
        if _state["tries"] > 40:
            print("ERROR: the Strip tab never appeared; nothing was shot")
            return None
        return 0.25
    bpy.app.timers.register(write_through_placeholder, first_interval=1.5)
    return None


def _shoot(name):
    """Screenshot the Properties area."""
    area = _area["props"]
    region = next(r for r in area.regions if r.type == 'WINDOW')
    os.makedirs(OUT, exist_ok=True)
    with bpy.context.temp_override(window=bpy.context.window, area=area, region=region):
        bpy.ops.screen.screenshot_area(filepath=os.path.join(OUT, name))
    print("wrote", os.path.join(OUT, name))


def write_through_placeholder():
    """The panel edit itself: one write to the WindowManager placeholder."""
    strip = _state["strip"]
    print("  active_strip resolves in a UI context:",
          getattr(bpy.context, "active_strip", None) is not None)
    print("  has perspective before the write:", nodes.has_perspective(strip))

    bpy.context.window_manager.perspective_transform.upper_right = (0.80, 0.90)

    print("  has perspective after the write :", nodes.has_perspective(strip))
    print("  handover open after the write   :", defaults.is_handing_over())
    _area["props"].tag_redraw()
    bpy.app.timers.register(shoot_during, first_interval=0.25)
    return None


def shoot_during():
    """Inside the window: placeholder rows, carrying the value just written."""
    print("  handover still open at +0.25s   :", defaults.is_handing_over())
    _shoot("handover_during.png")
    bpy.app.timers.register(shoot_after, first_interval=2.0)
    return None


def shoot_after():
    """Past the window: the socket rows must have arrived unprompted."""
    print("  handover closed at +2.25s       :", not defaults.is_handing_over())
    _shoot("handover_after.png")
    print("Compare the two: identical rows, and only the second has animate dots.")
    return None


def quit_now():
    """Always armed, so a failure cannot leave a window behind."""
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(setup, first_interval=1.0)
bpy.app.timers.register(show_tab, first_interval=2.0)
bpy.app.timers.register(quit_now, first_interval=25.0)
