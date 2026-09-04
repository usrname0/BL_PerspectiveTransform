"""
Screenshot the strip Properties tab, to check where the Perspective panel sits.

Panel order is invisible from Python - it is baked into the region when the
panel list is first built - so this is the only way to confirm that
register()'s bl_order push actually put Perspective directly beneath Crop.
Run it after touching PANELS_AFTER_PERSPECTIVE, or after a new Blender version
renames one of Blender's own strip panels.

    blender.exe --factory-startup --python tests/spikes/panel_order_shot.py

Note: no --background. It needs a GUI to draw and screenshot, and writes
panel_order.png next to the other test output. Everything runs off
bpy.app.timers with gaps between the steps, because an area has to be drawn
once before it will accept configuration, and because a spike that raises
before its quit timer is armed leaves a Blender window on the desktop.

Three things had to be true before this worked, all of them non-obvious:

  * context.active_strip resolves through the *workspace* sequencer scene.
    Without `workspace.sequencer_scene = scene` there is no Strip tab at all
    and setting it raises `enum "STRIP" not found`.
  * A sequencer area has to exist in the window.
  * The panel's open/closed state is baked in on first draw just as its order
    is, so DEFAULT_CLOSED is dropped before register() rather than toggled
    afterwards - toggling later does nothing visible.
"""

import importlib
import os
import sys

import bpy

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(REPO))

# --factory-startup ignores userpref.blend, so the splash comes back however it
# is set in real preferences. Turning it off here, at script-load time, beats
# the first redraw and suppresses it - measured on 5.2.1. Safe to write:
# a --factory-startup run does not save preferences back on quit, verified by
# checksumming userpref.blend across a run that changed this very setting.
bpy.context.preferences.view.show_splash = False

addon = importlib.import_module(os.path.basename(REPO))
operators = importlib.import_module(addon.__name__ + ".operators.perspective_operators")
nodes = importlib.import_module(addon.__name__ + ".operators.perspective_nodes")

# Draw the panel open, so the corner labels are in the shot too.
operators.PERSPECTIVE_PT_perspective.bl_options = set()
addon.register()

OUT = os.path.join(REPO, "tests", "_output", "panel_order.png")
_area = {}
_state = {"tries": 0}


def setup():
    """Build a strip, point the workspace at its scene, and lay out the screen."""
    scene = bpy.context.scene
    scene.sequence_editor_create()
    strip = scene.sequence_editor.strips.new_effect(
        name="Spike", type='COLOR', channel=1, frame_start=1, length=50)
    strip.select = True
    scene.sequence_editor.active_strip = strip
    bpy.context.window.workspace.sequencer_scene = scene

    areas = sorted(bpy.context.window.screen.areas,
                   key=lambda a: a.width * a.height, reverse=True)
    areas[0].type = 'SEQUENCE_EDITOR'
    _area["props"] = next(a for a in bpy.context.window.screen.areas
                          if a.type == 'PROPERTIES')

    # A real pin, so the panel has corner values to show rather than its
    # "no perspective on this strip" state.
    nodes.write_pin(strip, scene, ((0.0, 0.0), (0.15, 1.0), (0.85, 1.0), (1.0, 0.0)))
    return None


def show_tab():
    """
    Switch the Properties editor to the Strip tab, once it has one.

    The tab does not appear until the editor has redrawn with the workspace's
    sequencer scene set, and how many redraws that takes is not fixed - a
    version of this that simply waited a couple of seconds worked most times
    and then did not. Retry until it takes.
    """
    try:
        _area["props"].spaces.active.context = 'STRIP'
    except TypeError:
        _state["tries"] += 1
        if _state["tries"] > 40:
            print("ERROR: the Strip tab never appeared; nothing was shot")
            return None
        return 0.25
    bpy.app.timers.register(shoot, first_interval=1.5)
    return None


def shoot():
    """Screenshot the Properties area."""
    area = _area["props"]
    if area.spaces.active.context != 'STRIP':
        print("ERROR: the Properties editor is not on the Strip tab")
        return None
    region = next(r for r in area.regions if r.type == 'WINDOW')
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with bpy.context.temp_override(window=bpy.context.window, area=area, region=region):
        bpy.ops.screen.screenshot_area(filepath=OUT)
    print("wrote", OUT)
    print("Perspective should appear directly beneath Crop, above Video.")
    return None


def quit_now():
    """Always armed, so a failure cannot leave a window behind."""
    bpy.ops.wm.quit_blender()
    return None


# shoot() is chained off show_tab() rather than given a time of its own, since
# there is no telling in advance when the Strip tab will exist. Only the quit is
# absolute, and it is deliberately generous.
bpy.app.timers.register(setup, first_interval=1.0)
bpy.app.timers.register(show_tab, first_interval=2.0)
bpy.app.timers.register(quit_now, first_interval=20.0)
