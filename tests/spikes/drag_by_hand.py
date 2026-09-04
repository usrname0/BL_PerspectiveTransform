"""
Open a live session set up for the one thing no script can answer: drag feel.

Stage 2 of CONVEX_GUARD.md hands the corner drag space.constrain_corner, so a
move that would break convexity is projected onto the nearest position that
keeps it rather than being refused whole and retried one axis at a time. The
headless suite can prove the corner never goes concave and that reversal
responds on the first event. It cannot say whether sliding along the boundary
feels better than stopping against it, and that is what the stage is gated on.

    blender.exe --factory-startup --python tests/spikes/drag_by_hand.py

No --background, and deliberately **no quit timer** - this one is driven by
hand, so it stays open until it is closed. It leaves the addon registered from
this working tree, so whatever is in gizmos/perspective_handles_gizmo.py right
now is what the mouse is testing.

It sets up the case where the two rules disagree most: Upper Left pulled across
to x=0.35, which raises a boundary for Upper Right running diagonally, at no
axis's angle. Drag the top right handle down and to the left, into the middle
of the image.

  * projection (this tree)  the handle runs along the wall and keeps moving
  * axis retries (before)   it moves in steps, dead on 36 of 60 events, and
                            only along whichever axis happens to be free

Also worth checking in the same session, because the stage must not have cost
them: pushing hard into the wall and then reversing by a hair must move the
handle on the very first event, and the handle must never enter a shape whose
render fills the frame with garbage.
"""

import importlib
import os
import sys

import bpy
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(REPO))

bpy.context.preferences.view.show_splash = False

addon = importlib.import_module(os.path.basename(REPO))
nodes = importlib.import_module(addon.__name__ + ".operators.perspective_nodes")
addon.register()

TOOL_IDNAME = "sequencer.perspective_handles_tool"
OUT = os.path.join(REPO, "tests", "_output")

# Upper Left across at x=0.35, which is what makes the boundary for Upper Right
# diagonal. The other three are identity, so the shape is still convex and the
# guard is armed rather than in its escape case.
START_PIN = ((0.0, 0.0), (0.35, 1.0), (1.0, 1.0), (1.0, 0.0))

_state = {}


def _source_image():
    """Write a four-quadrant PNG, so the perspective is readable on sight."""
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "drag_by_hand_source.png")
    image = bpy.data.images.new("pt_drag_source", width=512, height=512, alpha=True)
    pixels = np.zeros((512, 512, 4), dtype=np.float32)
    pixels[..., 3] = 1.0
    pixels[0:256, 0:256, :3] = (0.9, 0.2, 0.2)
    pixels[0:256, 256:512, :3] = (0.2, 0.9, 0.2)
    pixels[256:512, 0:256, :3] = (0.2, 0.4, 0.9)
    pixels[256:512, 256:512, :3] = (0.9, 0.9, 0.2)
    image.pixels.foreach_set(pixels.ravel())
    image.filepath_raw = path
    image.file_format = 'PNG'
    image.save()
    bpy.data.images.remove(image)
    return path


def setup():
    """Build the strip and point the workspace at its scene."""
    scene = bpy.context.scene
    scene.render.resolution_x = 512
    scene.render.resolution_y = 512
    editor = scene.sequence_editor_create()
    strip = editor.strips.new_image(name="Drag", filepath=_source_image(),
                                    channel=1, frame_start=1)
    if "duration" in strip.bl_rna.properties:
        strip.duration = 50
    else:
        strip.frame_final_duration = 50
    strip.select = True
    editor.active_strip = strip
    bpy.context.window.workspace.sequencer_scene = scene
    nodes.write_pin(strip, scene, START_PIN)
    _state["strip"] = strip

    area = max(bpy.context.window.screen.areas, key=lambda a: a.width * a.height)
    area.type = 'SEQUENCE_EDITOR'
    _state["area"] = area
    return None


def activate_tool():
    """
    Switch the area to the preview and make the perspective tool current.

    Split into its own timer step because an area has to be drawn once before
    it will accept configuration - see BLENDER.md -> Screenshotting the GUI as
    a spike, which cost the same second there.
    """
    area = _state["area"]
    area.spaces.active.view_type = 'PREVIEW'
    region = next(r for r in area.regions if r.type == 'PREVIEW')
    with bpy.context.temp_override(window=bpy.context.window, area=area, region=region):
        bpy.ops.wm.tool_set_by_id(name=TOOL_IDNAME)

    print("\n" + "=" * 70)
    print("Drag the TOP RIGHT handle down and left, into the middle of the image.")
    print("Upper Left sits at x=0.35, so the wall it meets is diagonal.")
    print("  expected now : the handle slides along the wall and keeps moving")
    print("  before       : it moved in axis-aligned steps, dead on 36 of 60 events")
    print("Then push well past the wall and reverse by a hair - the handle must")
    print("move on that first event, not after dragging the excursion back.")
    print("Close the window when done; nothing here quits on its own.")
    print("=" * 70 + "\n")
    return None


bpy.app.timers.register(setup, first_interval=1.0)
bpy.app.timers.register(activate_tool, first_interval=2.5)
