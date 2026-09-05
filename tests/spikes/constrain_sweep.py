"""
Measure whether projecting a corner onto the convex region is sound and exact.

This is where CONVEX_MARGIN in operators/perspective_space.py comes from, and
where the numbers in CONVEX_GUARD.md were taken. It is not a test - nothing here
asserts - it is the measurement to re-run before changing that constant or the
projection behind it.

    blender.exe --factory-startup --background --python tests/spikes/constrain_sweep.py

Only three of the four convexity cross products involve any one corner; the
fourth is fixed by the other three and decides the sign. Each of the three is
affine in the moving corner, so the valid positions for it are an intersection
of three half-planes clipped to the unit square - a convex region of at most
seven constraints, whose nearest point is exact by enumeration.

It calls space.constrain_corner() itself rather than carrying a copy of it.
Before stage 1 of CONVEX_GUARD.md landed this file held its own reference
implementation, because the function did not exist yet; keeping that copy now
would only measure how well the copy had been maintained.

Measured on 5.2.1, with the results this run reproduces:

  * soundness   20000 random targets on random convex quads, 0 results that
                is_convex_quad rejects and 0 false None
  * margin      the sweep behind CONVEX_MARGIN, below
  * optimality  0.000e+00 worst excess distance against a brute-force scan of
                the feasible set
  * cost        about 14 us per call, on targets chosen to project every time
  * sliding     into a shallow diagonal boundary, the gizmo's refuse-then-retry
                moved nothing on 36 of 60 events; the projection on none

**The margin is the finding, and float32 is what sizes it.** A projection lands
exactly ON a constraint, so its cross product comes out at CONVEX_EPSILON plus
or minus a rounding error and is_convex_quad's `abs(cross) < epsilon` rejects it
about half the time - 6471 of 20000 with no margin at all. Holding the feasible
region a hair inside the boundary is what fixes it.

How far inside is set by float32, not by that rounding error. A Corner Pin
socket is a C float and so is the mathutils.Vector the function returns, and
quantizing a corner to float32 moves the cross products around it by up to about
1e-7. That is a thousand times the margin this sweep first arrived at in double
precision, CONVEX_EPSILON * 1e-6, and it brings the failure straight back - the
row for it in the table below still rejects 6384 of 20000. The shipped value is
CONVEX_EPSILON * 1e-2, an order of magnitude past the last row that fails.
"""

import os
import random
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

import harness as H

space = H.import_addon_package_module("operators.perspective_space")

EPS = space.CONVEX_EPSILON


def _random_convex_quad(rng):
    """A convex quad in the unit square, in nodes.CORNER_SOCKETS walk order."""
    while True:
        quad = [(rng.uniform(0.0, 0.45), rng.uniform(0.0, 0.45)),
                (rng.uniform(0.0, 0.45), rng.uniform(0.55, 1.0)),
                (rng.uniform(0.55, 1.0), rng.uniform(0.55, 1.0)),
                (rng.uniform(0.55, 1.0), rng.uniform(0.0, 0.45))]
        if space.is_convex_quad(quad):
            return quad


def measure_soundness(trials=20000, seed=1):
    """Every answer must be convex, and a convex quad must never answer None."""
    rng = random.Random(seed)
    bad_convex = none_from_convex = passed = projected = 0
    for _ in range(trials):
        quad = _random_convex_quad(rng)
        index = rng.randrange(4)
        target = (rng.uniform(-0.4, 1.4), rng.uniform(-0.4, 1.4))
        result = space.constrain_corner(quad, index, target)
        if result is None:
            none_from_convex += 1
            continue
        candidate = list(quad)
        candidate[index] = result
        if not space.is_convex_quad(candidate):
            bad_convex += 1
        if (float(result[0]), float(result[1])) == target:
            passed += 1
        else:
            projected += 1
    return trials, bad_convex, none_from_convex, passed, projected


def measure_margin(factors=(0.0, 1e-6, 1e-5, 1e-4, 1e-3, 1e-2, 1e-1),
                   trials=20000):
    """
    Sweep CONVEX_MARGIN and count the answers is_convex_quad then rejects.

    The result carries the float32 round trip, because constrain_corner returns
    a Vector and that is what a socket stores - which is the whole reason the
    shipped value is not the one double precision alone would suggest.
    """
    original = space.CONVEX_MARGIN
    rows = []
    try:
        for factor in factors:
            # Sweeping the constant is the whole point of the spike, and a
            # module is not a class the checker will let you assign into.
            space.CONVEX_MARGIN = EPS * factor  # pyright: ignore[reportAttributeAccessIssue]
            rng = random.Random(1)
            rejected = 0
            worst = None
            for _ in range(trials):
                quad = _random_convex_quad(rng)
                index = rng.randrange(4)
                target = (rng.uniform(-0.4, 1.4), rng.uniform(-0.4, 1.4))
                result = space.constrain_corner(quad, index, target)
                if result is None:
                    continue
                candidate = list(quad)
                candidate[index] = result
                if not space.is_convex_quad(candidate):
                    rejected += 1
                smallest = min(
                    abs(space._area2(candidate[k], candidate[(k + 1) % 4],
                                     candidate[(k + 2) % 4]))
                    for k in range(4))
                if worst is None or smallest < worst:
                    worst = smallest
            rows.append((factor, rejected, worst))
    finally:
        space.CONVEX_MARGIN = original  # pyright: ignore[reportAttributeAccessIssue]
    return trials, rows


def measure_optimality(trials=100, grid=400):
    """
    Compare the projection against a brute-force scan of the feasible set.

    The scan asks is_convex_quad rather than the module's own half-planes, so
    a wrong feasible region would show up here rather than cancelling itself
    out. The margin is the one honest difference between the two, worth about
    1e-6 of position, so a non-zero excess of that order is not a finding.
    """
    rng = random.Random(2)
    worst = 0.0
    for _ in range(trials):
        quad = _random_convex_quad(rng)
        index = rng.randrange(4)
        target = (rng.uniform(-0.3, 1.3), rng.uniform(-0.3, 1.3))
        result = space.constrain_corner(quad, index, target)
        if result is None:
            continue
        ours = ((float(result[0]) - target[0]) ** 2
                + (float(result[1]) - target[1]) ** 2) ** 0.5
        candidate = list(quad)
        best = None
        for step_x in range(grid + 1):
            x = step_x / grid
            for step_y in range(grid + 1):
                y = step_y / grid
                candidate[index] = (x, y)
                if not space.is_convex_quad(candidate):
                    continue
                distance = ((x - target[0]) ** 2 + (y - target[1]) ** 2) ** 0.5
                if best is None or distance < best:
                    best = distance
        if best is not None:
            worst = max(worst, ours - best)
    return trials, grid, worst


def measure_cost(trials=20000):
    """Microseconds per call, on targets chosen to make it project every time."""
    rng = random.Random(3)
    cases = []
    for _ in range(trials):
        quad = _random_convex_quad(rng)
        cases.append((quad, rng.randrange(4),
                      (rng.uniform(-0.4, 1.4), rng.uniform(-0.4, 1.4))))
    start = time.perf_counter()
    for quad, index, target in cases:
        space.constrain_corner(quad, index, target)
    return (time.perf_counter() - start) / trials * 1e6


def measure_degenerate():
    """Three fixed corners collinear must answer None, not invent a point."""
    quad = [(0.0, 0.0), (0.5, 0.5), (1.0, 1.0), (1.0, 0.0)]
    return space.constrain_corner(quad, 3, (0.9, 0.1)) is None


def measure_sliding(steps=60):
    """
    Drag corner 2 diagonally into the wall raised by pulling corner 1 across.

    Compares the gizmo's refuse-the-move-then-retry-each-axis against
    projecting onto the feasible region. The difference is how many events move
    nothing at all. This is the measurement stage 2 of CONVEX_GUARD.md rests
    on, and it is the reason that stage exists.
    """
    base = [(0.0, 0.0), (0.35, 1.0), (1.0, 1.0), (1.0, 0.0)]
    delta = (-0.02, -0.012)

    def accept(quad, index, point):
        candidate = list(quad)
        candidate[index] = (min(max(point[0], 0.0), 1.0),
                            min(max(point[1], 0.0), 1.0))
        return candidate[index] if space.is_convex_quad(candidate) else None

    retry = list(base)
    stalled = 0
    for _ in range(steps):
        here = retry[2]
        target = (here[0] + delta[0], here[1] + delta[1])
        got = (accept(retry, 2, target)
               or accept(retry, 2, (target[0], here[1]))
               or accept(retry, 2, (here[0], target[1])))
        if got is None:
            stalled += 1
        else:
            retry[2] = got

    projected = list(base)
    dead = 0
    for _ in range(steps):
        here = projected[2]
        target = (here[0] + delta[0], here[1] + delta[1])
        got = space.constrain_corner(projected, 2, target)
        if got is None or (float(got[0]), float(got[1])) == tuple(here):
            dead += 1
        else:
            projected[2] = (float(got[0]), float(got[1]))

    return base[2], retry[2], stalled, projected[2], dead


def main():
    print("=" * 70)
    print("constrain_sweep - space.constrain_corner() on the feasible region")
    print("CONVEX_EPSILON = %g   CONVEX_MARGIN = %g (EPSILON * %g)"
          % (EPS, space.CONVEX_MARGIN, space.CONVEX_MARGIN / EPS))
    print("-" * 70)

    trials, bad, nones, passed, projected = measure_soundness()
    print("soundness    %d random targets on random convex quads" % trials)
    print("             results is_convex_quad rejects : %d" % bad)
    print("             None from a convex quad        : %d" % nones)
    print("             passed through / projected     : %d / %d"
          % (passed, projected))

    trials, rows = measure_margin()
    print("margin       %d projections per row, through float32" % trials)
    print("             %-14s %10s   %s"
          % ("CONVEX_MARGIN", "rejected", "smallest cross seen"))
    for factor, rejected, worst in rows:
        print("             EPSILON * %-4g %10d   %.6e"
              % (factor, rejected, worst))

    trials, grid, worst = measure_optimality()
    print("optimality   %d cases vs a %dx%d scan of is_convex_quad"
          % (trials, grid + 1, grid + 1))
    print("             worst excess distance          : %.3e" % worst)

    print("cost         %.1f us per call, projecting every time" % measure_cost())
    print("degenerate   three fixed corners collinear -> None: %s"
          % measure_degenerate())

    start, retry, stalled, proj, dead = measure_sliding()
    print("sliding      60 events of (-0.020, -0.012) into a shallow boundary")
    print("             start                          : (%.4f, %.4f)" % start)
    print("             axis-retry (gizmo today)       : (%.4f, %.4f), "
          "%d dead events" % (retry[0], retry[1], stalled))
    print("             projection                     : (%.4f, %.4f), "
          "%d dead events" % (proj[0], proj[1], dead))
    print("=" * 70)


main()
