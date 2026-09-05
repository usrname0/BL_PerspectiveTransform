"""
Measure whether the panel's unguarded slider can be repaired once it settles.

**The answer was no, and the feature was declined on 2026-09-04** - see DEV.md
-> Repairing the panel's slider after it settles. This is kept as the
measurement behind that, not as groundwork. Part E is the finding that decided
it: a repair that fires while the field is still being dragged does not merely
fail, it leaves the corner somewhere neither the user nor the guard chose.

A panel row bound to a Corner Pin socket has no Python between the slider and
the value, so a numeric edit can leave the quad concave and the addon only
notices afterwards - see DEV.md -> Convexity. CONVEX_GUARD.md rejected
correcting the socket *during* the edit via msgbus, because a number field
drags from its own start value and would overwrite the correction on the next
event. This measures the other shape: leave the drag alone, and repair once the
value has stopped changing, the way perspective_defaults.HANDOVER_DELAY already
holds the panel's placeholder rows until writing stops.

    blender.exe --factory-startup --background --python tests/spikes/settle_repair.py

It is not a test - nothing asserts. Five parts, and part A is the one that
decides whether the design is even available:

  A  msgbus     does a subscription on a corner socket fire, and on what
  B  polling    what a timer costs if msgbus cannot be the detector
  C  repair     can the repair run with no UI context, as a timer callback has
  D  settle     how a HANDOVER-shaped deadline behaves under a stream of edits
  E  fight      what the user sees if a repair lands in the middle of a drag

**What this cannot answer.** Timers do not fire in background mode - there is
no main loop to run them - so part D drives the deadline logic through an
injected clock rather than through bpy.app.timers, and measures the logic, not
the plumbing. And whether a *UI* slider notifies msgbus at all is a question
only a GUI session can settle; part A measures the Python side, which is the
half that can be wrong on its own.
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

import bpy

# Corner 2 pulled across the diagonal between its neighbours: the shape a
# slider can reach in one drag and the drag itself cannot make.
CONCAVE_PIN = ((0.0, 0.0), (0.0, 1.0), (0.35, 0.35), (1.0, 0.0))


def _setup(name):
    """A scene with one image strip carrying a perspective, ready to edit."""
    import harness as H
    nodes = H.import_addon_module("operators.perspective_nodes")

    source = H.make_source_image(os.path.join(H.scratch_dir(), "settle_src.png"))
    scene = H.make_scene(name, 256, 256)
    bpy.context.window.scene = scene
    strip = H.add_image_strip(scene, source)
    H.set_duration(strip, 10)
    nodes.write_pin(strip, scene, nodes.IDENTITY_PIN)
    return scene, strip


def _corner_socket(strip, index):
    """The Corner Pin input the panel binds a row to, for one corner."""
    import harness as H
    nodes = H.import_addon_module("operators.perspective_nodes")
    modifier = nodes.find_modifier(strip)
    node = nodes.get_corner_pin_node(modifier.node_group) if modifier else None
    return node.inputs[nodes.CORNER_SOCKETS[index]] if node else None


def _watch(datum, prop, writes):
    """
    Subscribe to one property, run some writes, and count what came back.

    Args:
        datum: the datablock or struct owning the property
        prop: the property name to subscribe to
        writes: (label, callable) pairs, run in order

    Returns:
        list: (label, notifications) for each write, plus one for publish_rna
    """
    fired = []
    owner = object()
    results = []
    try:
        bpy.msgbus.subscribe_rna(key=datum.path_resolve(prop, False), owner=owner,
                                 args=(), notify=lambda: fired.append(1))
    except Exception as error:  # noqa: BLE001 - the failure is the measurement
        return [("subscribe_rna", "%s: %s" % (type(error).__name__, error))]

    for label, write in writes:
        before = len(fired)
        write()
        results.append((label, len(fired) - before))

    before = len(fired)
    bpy.msgbus.publish_rna(key=datum.path_resolve(prop, False))
    results.append(("explicit publish_rna", len(fired) - before))

    bpy.msgbus.clear_by_owner(owner)
    return results


def part_a_msgbus():
    """
    Does a subscription on a corner socket fire, and on what.

    msgbus is the detector CONVEX_GUARD.md assumed would be available, so the
    first question is whether it notifies at all. A Python write is not a UI
    edit and the two need not be the same event.

    **With a control**, because "our socket is silent" and "the bus is silent"
    look identical otherwise - see BLENDER.md -> Screenshotting the GUI as a
    spike, which cost the same lesson. The control is an object's location,
    which is plain Blender and has nothing to do with this addon.
    """
    print("\n=== A. msgbus on a corner socket ===")
    import harness as H
    nodes = H.import_addon_module("operators.perspective_nodes")

    obj = bpy.data.objects.new("settle_control", None)
    bpy.context.scene.collection.objects.link(obj)
    print("  control - object.location")
    for label, count in _watch(obj, "location",
                               [("a direct Python write", lambda: setattr(obj, "location", (1.0, 0.0, 0.0)))]):
        print("    %-30s: %s" % (label, count))

    scene, strip = _setup("settle_msgbus")
    socket = _corner_socket(strip, 2)
    if socket is None:
        print("  no Corner Pin node - the rest of this part is meaningless")
        return

    print("  subject - corner pin socket.default_value")
    writes = [
        ("a direct Python write", lambda: setattr(socket, "default_value", (0.35, 0.35))),
        ("nodes.write_pin", lambda: nodes.write_pin(strip, scene, CONCAVE_PIN)),
    ]
    for label, count in _watch(socket, "default_value", writes):
        print("    %-30s: %s" % (label, count))

    print("  If the control is silent too, this says nothing about the socket -")
    print("  it says msgbus is not observable from background mode, and the")
    print("  question moves to a GUI session. settle_repair_gui.py is that.")


def part_b_polling():
    """
    What a poll costs, if msgbus cannot be the detector.

    The fallback detector is a timer that reads the active strip's pin and asks
    the predicate. That is only viable if it is far too cheap to notice at a
    tenth of a second, so the number wanted here is per-call microseconds, and
    whether a scene full of strips changes it - the detector looks at the
    active strip only, so it should not.
    """
    print("\n=== B. cost of polling instead ===")
    import harness as H
    nodes = H.import_addon_module("operators.perspective_nodes")
    space = H.import_addon_module("operators.perspective_space")

    scene, strip = _setup("settle_poll")
    nodes.write_pin(strip, scene, CONCAVE_PIN)

    def poll():
        return space.is_convex_quad(nodes.read_pin(strip))

    poll()
    for label, extra in (("1 strip", 0), ("40 strips", 39)):
        for index in range(extra):
            filler = scene.sequence_editor.strips.new_effect(  # pyright: ignore[reportOptionalMemberAccess]
                name="filler_%d" % index, type='COLOR', channel=2 + index % 8,
                frame_start=1, length=10)
            filler.select = False
        trials = 2000
        start = time.perf_counter()
        for _ in range(trials):
            poll()
        elapsed = (time.perf_counter() - start) / trials
        print("  %-10s %7.1f us per poll, %.4f%% of a 0.1 s timer"
              % (label, elapsed * 1e6, elapsed / 0.1 * 100.0))


def part_c_repair_without_context():
    """
    Can the repair run where a timer callback runs, with no UI context.

    SEQUENCER_OT_perspective_make_convex reads active_strip, the sequencer
    scene and tool_settings off the context it is given. A timer has no area,
    no region and, in background mode, no sequencer scene at all - which is
    also the state that crashes strip.modifiers.new, see BLENDER.md. So the
    question is whether the repair has to become a plain function taking
    (strip, scene) before any of this is possible.
    """
    print("\n=== C. repairing with no UI context ===")
    import harness as H
    nodes = H.import_addon_module("operators.perspective_nodes")
    space = H.import_addon_module("operators.perspective_space")
    anim = H.import_addon_module("operators.perspective_anim")

    scene, strip = _setup("settle_repair_ctx")
    nodes.write_pin(strip, scene, CONCAVE_PIN)
    print("  starting shape convex                 : %s"
          % space.is_convex_quad(nodes.read_pin(strip)))

    # The operator's body, with nothing taken off a context: this is what a
    # timer callback would be able to call.
    corners = [tuple(corner) for corner in nodes.read_pin(strip)]
    best = None
    for index in range(4):
        moved = space.constrain_corner(corners, index, corners[index])
        if moved is None:
            continue
        candidate = list(corners)
        candidate[index] = moved
        if not space.is_convex_quad(candidate):
            continue
        travel = ((moved[0] - corners[index][0]) ** 2
                  + (moved[1] - corners[index][1]) ** 2)
        if best is None or travel < best[0]:
            best = (travel, index, moved)

    if best is None:
        print("  no single corner can repair it        : nothing to measure")
        return
    _travel, index, moved = best
    corners[index] = moved
    nodes.write_pin(strip, scene, corners)
    keyed = anim.autokey_corner(strip, scene, index, None)
    print("  repaired corner                       : %s, moved to (%.4f, %.4f)"
          % (nodes.CORNER_LABELS[index], moved[0], moved[1]))
    print("  autokey with tool_settings None       : %s" % keyed)
    print("  shape convex afterwards               : %s"
          % space.is_convex_quad(nodes.read_pin(strip)))
    print("  so the repair needs (strip, scene) only, not a UI context")


class _Settle:
    """
    The deadline the repair would wait on, with its clock injected.

    Exactly the shape of perspective_defaults._hold_placeholders and
    _finish_handover: every edit pushes the deadline out, and one timer runs
    until nothing has pushed it for `delay`. Written here rather than imported
    because bpy.app.timers do not fire in background mode, so the plumbing
    cannot be measured - only the logic can.
    """

    def __init__(self, delay):
        self.delay = delay
        self.until = None
        self.repairs = []

    def edit(self, now):
        """An edit arrived: push the deadline out."""
        self.until = now + self.delay

    def tick(self, now):
        """The timer ran: repair if nothing has arrived for `delay`."""
        if self.until is not None and now >= self.until:
            self.until = None
            self.repairs.append(now)


def part_d_settle_window():
    """
    What each choice of delay costs, run through the state machine.

    Be clear about what this is: the deadline is arithmetic, and running it
    proves only that it was implemented as described. A pause longer than the
    delay is indistinguishable from the end of a drag, and no measurement
    changes that. What is worth writing down is the trade - a delay is the
    longest mid-drag pause tolerated *and* how long a broken shape stays on
    screen after the user lets go, and those pull in opposite directions.

    The one thing here that is not arithmetic is how long a pause a real
    number-field drag contains, and that is a GUI question this cannot reach.
    """
    print("\n=== D. the settle window (derived, not measured) ===")
    rate = 1.0 / 60.0
    print("  a 60-event drag at 60 Hz, one pause inserted halfway")
    print("  %-8s %-24s %s" % ("delay", "repairs fired", "cost"))
    for delay in (0.25, 0.5, 1.0):
        outcomes = []
        for pause in (0.2, 0.5, 1.5):
            settle = _Settle(delay)
            now = 0.0
            for event in range(60):
                settle.edit(now)
                gap = pause if event == 29 else rate
                for _ in range(int(gap / 0.05)):
                    now += 0.05
                    settle.tick(now)
                now += gap % 0.05
            now += delay + 0.05
            settle.tick(now)
            outcomes.append(len(settle.repairs))
        print("  %-8.2f %-24s %s"
              % (delay,
                 "0.2s:%d  0.5s:%d  1.5s:%d" % tuple(outcomes),
                 "broken shape visible for %.2fs after release" % delay))
    print("  more than one repair means one fired into a drag that had not")
    print("  finished - which part E shows the consequence of")


def part_e_the_fight():
    """
    What the user sees if a repair lands while the field is still being dragged.

    This is the failure CONVEX_GUARD.md rejected msgbus for, and a settle
    window does not remove it - it only makes it rare. A number field computes
    each event from the value it held when the drag started, so it does not
    know the socket was corrected underneath it: the next event writes what the
    cursor says, and the repair is undone in one frame. Printed as the value
    trajectory, because the size of the jump is the whole question.
    """
    print("\n=== E. a repair landing mid-drag ===")
    import harness as H
    nodes = H.import_addon_module("operators.perspective_nodes")
    space = H.import_addon_module("operators.perspective_space")

    scene, strip = _setup("settle_fight")
    # From identity no single slider can reach a concave quad - corner 2 with
    # y at 1.0 satisfies x + y >= 1 for every x it is allowed. Two edits can,
    # which is what a user does: set x, then drag y. So x is already across.
    nodes.write_pin(strip, scene, ((0.0, 0.0), (0.0, 1.0), (0.35, 1.0), (1.0, 0.0)))

    # Now the Y field drags corner 2 down from 1.0. Blender computes each event
    # from the value the field held when the drag began, so this column is
    # unaffected by anything written to the socket in between - and it writes
    # only its own component, so a repair that moved X is not undone by it.
    field_start = 1.0
    fired = False
    print("  corner 2 starts at (0.35, 1.00); the Y field drags from 1.00")
    print("  %-6s %-16s %-20s %s" % ("event", "field writes", "socket holds", ""))
    for event, value in enumerate((0.90, 0.80, 0.70, 0.60, 0.50, 0.40)):
        corners = [list(map(float, corner)) for corner in nodes.read_pin(strip)]
        corners[2][1] = value
        nodes.write_pin(strip, scene, corners)
        note = ""
        if not fired and not space.is_convex_quad(nodes.read_pin(strip)):
            # The user paused here for longer than the delay, so the repair
            # fires - and then the drag carries on.
            fired = True
            held = [tuple(map(float, corner)) for corner in nodes.read_pin(strip)]
            moved = space.constrain_corner(held, 2, held[2])
            if moved is not None:
                held[2] = moved
                nodes.write_pin(strip, scene, held)
                note = "  <- concave; repair moves it to (%.4f, %.4f)" % (moved[0], moved[1])
        after = tuple(round(float(v), 4) for v in nodes.read_pin(strip)[2])
        print("  %-6d %-16s %-20s %s"
              % (event, "y = %.2f" % value, "(%.4f, %.4f)" % after, note))
    final = nodes.read_pin(strip)
    print("  ends convex                           : %s"
          % space.is_convex_quad(final))
    print("  A single-component field overwrites only its own component, so a")
    print("  repair that moved the OTHER coordinate survives the next event -")
    print("  and one that moved this one does not. Either way the shape is")
    print("  concave again by the following event, so only a repair that waits")
    print("  for the drag to end is worth anything.")


def main():
    print("=" * 70)
    print("settle_repair.py - can the panel slider be repaired once it settles")
    print("Blender %s" % bpy.app.version_string)
    print("=" * 70)
    part_a_msgbus()
    part_b_polling()
    part_c_repair_without_context()
    part_d_settle_window()
    part_e_the_fight()
    print("\n" + "=" * 70)


main()
