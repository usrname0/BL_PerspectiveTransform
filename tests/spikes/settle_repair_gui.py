"""
The half of settle_repair.py that only a live session can answer.

**Never run by hand.** The auto-repair feature was declined on 2026-09-04,
before this session was held - the preview already updates live and the warning
box already explains itself, so the state it would fix is not a confusing one.
The spike is smoke-tested and works; it is kept so that reviving the idea starts
with the measurement rather than with an argument. See DEV.md -> Repairing the
panel's slider after it settles.

Run settle_repair.py first; this continues it. Two questions are left there:

  1. Does a msgbus subscription on a Corner Pin socket fire when a *UI* slider
     writes it? Background mode notifies nothing at all - the control in part A
     is as silent as the subject - so the bus cannot be ruled in or out from
     there, and a detector cannot be designed until it is.

  2. How long are the pauses inside a real number-field drag? The settle delay
     has to be longer than the longest pause a user makes mid-drag, or the
     repair fires into a drag that has not finished - and part E measures what
     that costs. No amount of arithmetic produces this number; it comes off a
     hand.

    blender.exe --factory-startup --python tests/spikes/settle_repair_gui.py

No --background, and no quit timer: close the window when done. Everything is
printed to the console as it happens, so watch the terminal, not the viewport.

**What to do.** The Properties editor is open on the Strip tab with the
Perspective panel drawn. Corner 2 (Top Right) starts at x=0.35, so dragging its
Y field down past about 0.65 makes the quad concave - which the panel's warning
box will confirm. Drag that Y field:

  * slowly, all the way down, in one press
  * again, deliberately pausing partway without releasing
  * again, in a fast flick

After each drag settles, one SUMMARY block prints: how many writes arrived, the
largest gap between two of them, whether msgbus saw any of it, and how long the
shape spent concave. The largest mid-drag gap across those three drags is the
number the settle delay has to beat.
"""

import importlib
import os
import sys
import time

import bpy

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(REPO))

bpy.context.preferences.view.show_splash = False

addon = importlib.import_module(os.path.basename(REPO))
operators = importlib.import_module(addon.__name__ + ".operators.perspective_operators")
nodes = importlib.import_module(addon.__name__ + ".operators.perspective_nodes")
space = importlib.import_module(addon.__name__ + ".operators.perspective_space")

# Draw the panel open, so the corner rows are there to grab.
operators.PERSPECTIVE_PT_perspective.bl_options = set()
addon.register()

# Corner 2 across at x=0.35. From identity no single field can reach a concave
# quad - with y at 1.0, x + y >= 1 holds for every x the socket allows - so the
# x edit is done here and the Y field is left as the one thing to drag.
START_PIN = ((0.0, 0.0), (0.0, 1.0), (0.35, 1.0), (1.0, 0.0))

# Fast enough that the gaps it reports are the field's and not the sampler's.
# A poll costs 4.7 us, measured in settle_repair.py part B.
SAMPLE_INTERVAL = 0.02

# How long the pin has to hold still before a drag counts as over. Only used to
# decide when to print; it is not a proposal for the delay itself.
QUIET = 0.6

_state = {
    "strip": None,
    "last_pin": None,
    "writes": [],        # monotonic time of each observed change
    "concave_from": None,
    "concave_total": 0.0,
    "msgbus": 0,
    "owner": object(),
    "drag": 0,
}


def _pin():
    """The active strip's four corners as plain tuples, or None."""
    strip = _state["strip"]
    if strip is None:
        return None
    return tuple(tuple(float(v) for v in corner) for corner in nodes.read_pin(strip))


def _on_msgbus():
    """A UI write reached the bus - which is question 1."""
    _state["msgbus"] += 1


def setup():
    """Build the strip, lay out the screen, and subscribe to the sockets."""
    scene = bpy.context.scene
    scene.render.resolution_x = scene.render.resolution_y = 512
    editor = scene.sequence_editor_create()
    strip = editor.strips.new_effect(name="Settle", type='COLOR', channel=1,
                                     frame_start=1, length=50)
    strip.select = True
    editor.active_strip = strip
    bpy.context.window.workspace.sequencer_scene = scene
    nodes.write_pin(strip, scene, START_PIN)
    _state["strip"] = strip
    _state["last_pin"] = _pin()

    areas = sorted(bpy.context.window.screen.areas,
                   key=lambda a: a.width * a.height, reverse=True)
    areas[0].type = 'SEQUENCE_EDITOR'
    areas[0].spaces.active.view_type = 'PREVIEW'
    _state["props"] = next((a for a in bpy.context.window.screen.areas
                            if a.type == 'PROPERTIES'), None)
    return None


def subscribe():
    """
    Watch all four sockets, the way a real detector would have to.

    Separate timer step: the modifier and its node group have to exist first,
    and an area needs a draw before it will accept configuration.
    """
    if _state["props"] is not None:
        try:
            _state["props"].spaces.active.context = 'STRIP'
        except TypeError:
            return 0.5      # not drawn yet, ask again

    modifier = nodes.find_modifier(_state["strip"])
    node = nodes.get_corner_pin_node(modifier.node_group) if modifier else None
    if node is None:
        print("  no Corner Pin node - msgbus cannot be tested")
        return None

    for name in nodes.CORNER_SOCKETS:
        socket = node.inputs[name]
        bpy.msgbus.subscribe_rna(key=socket.path_resolve("default_value", False),
                                 owner=_state["owner"], args=(), notify=_on_msgbus)

    print("\n" + "=" * 70)
    print("Drag the Top Right corner's Y field in the Properties editor, down")
    print("past about 0.65 - that is where the quad goes concave and the")
    print("warning box appears. Do it three times: slow, with a deliberate")
    print("pause partway, and as a fast flick.")
    print("A SUMMARY prints after each drag settles. Close the window to quit.")
    print("=" * 70 + "\n")
    return None


def sample():
    """
    Watch the pin, and report each drag once it has stopped.

    This is the poll a detector would run, at a rate chosen so the gaps it
    reports belong to the field rather than to the sampler.
    """
    now = time.monotonic()
    current = _pin()
    if current is None:
        return SAMPLE_INTERVAL

    if current != _state["last_pin"]:
        _state["last_pin"] = current
        _state["writes"].append(now)
        convex = space.is_convex_quad(current)
        if not convex and _state["concave_from"] is None:
            _state["concave_from"] = now
        elif convex and _state["concave_from"] is not None:
            _state["concave_total"] += now - _state["concave_from"]
            _state["concave_from"] = None
        return SAMPLE_INTERVAL

    writes = _state["writes"]
    if not writes or now - writes[-1] < QUIET:
        return SAMPLE_INTERVAL

    # Settled: close any open concave span and report the drag.
    if _state["concave_from"] is not None:
        _state["concave_total"] += now - _state["concave_from"]
        _state["concave_from"] = writes[-1]      # still concave, keep counting

    gaps = [b - a for a, b in zip(writes, writes[1:])]
    _state["drag"] += 1
    print("--- SUMMARY, drag %d " % _state["drag"] + "-" * 45)
    print("  writes observed          : %d over %.2f s"
          % (len(writes), writes[-1] - writes[0] if len(writes) > 1 else 0.0))
    print("  largest gap between two  : %.3f s"
          % (max(gaps) if gaps else 0.0))
    print("  median gap               : %.3f s"
          % (sorted(gaps)[len(gaps) // 2] if gaps else 0.0))
    print("  msgbus notifications     : %d   <- question 1" % _state["msgbus"])
    print("  time spent concave       : %.2f s" % _state["concave_total"])
    print("  shape now                : %s"
          % ("convex" if space.is_convex_quad(_pin()) else "CONCAVE"))
    print("  a settle delay has to be longer than the largest gap above, or it")
    print("  would have fired into this drag")
    print("-" * 66)

    _state["writes"] = []
    _state["msgbus"] = 0
    _state["concave_total"] = 0.0
    _state["concave_from"] = None if space.is_convex_quad(_pin()) else now
    return SAMPLE_INTERVAL


bpy.app.timers.register(setup, first_interval=1.0)
bpy.app.timers.register(subscribe, first_interval=2.5)
bpy.app.timers.register(sample, first_interval=3.0)
