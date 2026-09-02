"""
BL Perspective Transform - Corner handle gizmos.

Four draggable handles sitting on the corners of the strip's image in the VSE
preview. Each handle reads and writes one socket of the Corner Pin node held by
the strip's compositor modifier, so dragging a handle changes what Blender
renders rather than painting a preview-only overlay.

Screen positions come from operators.perspective_space, which composes the
strip's placement, scale, rotation, origin and mirroring into a single matrix.
Dragging applies that matrix's inverse. There is no per-transform special case
here, and no stored copy of the corner positions: the node sockets are the only
state.
"""

import bpy
import gpu
from bpy.types import Gizmo, GizmoGroup
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Vector

from ..operators import perspective_anim as anim
from ..operators import perspective_nodes as nodes
from ..operators import perspective_space as space
from ..operators.perspective_core import is_strip_visible_at_frame

TOOL_IDNAME = "sequencer.perspective_handles_tool"

HANDLE_RADIUS = 6.0
SELECT_RADIUS = 25.0

COLOR_HANDLE = (1.0, 1.0, 1.0, 0.9)
COLOR_HANDLE_ACTIVE = (1.0, 0.5, 0.0, 1.0)
COLOR_HANDLE_BORDER = (0.0, 0.0, 0.0, 0.8)
COLOR_QUAD = (0.2, 0.8, 1.0, 0.9)
COLOR_BOUNDS = (1.0, 0.25, 0.25, 0.5)


def _frame_to_region(view2d, scene, point):
    """
    Convert a frame-space point to region pixels.

    The preview's View2D is centred on the frame, so frame coordinates are
    shifted by half the render resolution before conversion.
    """
    view_x = point[0] - scene.render.resolution_x * 0.5
    view_y = point[1] - scene.render.resolution_y * 0.5
    return view2d.view_to_region(view_x, view_y, clip=False)


def _region_to_frame(view2d, scene, x, y):
    """Convert region pixels back to a frame-space point."""
    view_x, view_y = view2d.region_to_view(x, y)
    return Vector((view_x + scene.render.resolution_x * 0.5,
                   view_y + scene.render.resolution_y * 0.5))


def _draw_polyline(points, color, width=1.0, closed=True):
    """Draw a connected line through region-space points."""
    if len(points) < 2:
        return
    vertices = [(float(p[0]), float(p[1])) for p in points]
    if closed:
        vertices.append(vertices[0])
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    gpu.state.line_width_set(width)
    shader.bind()
    shader.uniform_float("color", color)
    batch_for_shader(shader, 'LINE_STRIP', {"pos": vertices}).draw(shader)
    gpu.state.line_width_set(1.0)
    gpu.state.blend_set('NONE')


class PERSPECTIVE_GT_perspective_handle(Gizmo):
    """A single draggable corner handle."""

    bl_idname = "PERSPECTIVE_GT_perspective_handle"
    bl_target_properties = ()

    def setup(self):
        """Initialise handle state and the flags that keep it visible."""
        self.handle_index = 0
        # use_draw_modal keeps draw() running during a drag. There is no
        # use_draw_select property on Gizmo, and draw_select() is only called
        # for 3D gizmo groups, so a 2D gizmo does hit detection in test_select.
        self.use_draw_modal = True
        self.use_event_handle_all = True
        self.use_grab_cursor = True
        self.hide = False
        self.scale_basis = HANDLE_RADIUS
        self.select_id = 0
        # Captured on invoke so a drag does no datablock bookkeeping per event.
        self._pin_on_invoke = None
        self._edit_node = None
        self._drag_matrix = None
        # The drag's own running state: where the four corners stand right now,
        # and the cursor position the next delta is measured from.
        self._pin_corners = None
        self._last_mouse = None

    def draw_prepare(self, context):
        """Keep the handle visible regardless of gizmo group state."""
        self.hide = False

    def draw(self, context):
        """Draw the handle square."""
        self._draw_square(COLOR_HANDLE_ACTIVE if self.is_highlight else COLOR_HANDLE)

    def _draw_square(self, color):
        """Draw a filled square with a dark border at the handle's position."""
        centre = self.matrix_basis.translation
        size = HANDLE_RADIUS
        corners = [(centre.x - size, centre.y - size),
                   (centre.x + size, centre.y - size),
                   (centre.x + size, centre.y + size),
                   (centre.x - size, centre.y + size)]

        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        gpu.state.blend_set('ALPHA')
        shader.bind()
        shader.uniform_float("color", color)
        batch_for_shader(shader, 'TRI_FAN', {"pos": corners}).draw(shader)
        gpu.state.blend_set('NONE')

        _draw_polyline(corners, COLOR_HANDLE_BORDER, width=1.0, closed=True)

    def test_select(self, context, location):
        """Return this gizmo's id when the cursor is within the grab radius."""
        centre = self.matrix_basis.translation
        dx = centre.x - location[0]
        dy = centre.y - location[1]
        if (dx * dx + dy * dy) ** 0.5 <= SELECT_RADIUS:
            return self.select_id
        return -1

    def invoke(self, context, event):
        """
        Prepare everything the drag needs, once.

        Creating the modifier, un-sharing the node group and composing the
        coordinate matrix all cost more than a mouse-move can afford, and none
        of them change while a single corner is being dragged.

        The cursor position is captured too, because the drag moves the corner
        by how far the cursor has travelled rather than to where it points -
        see _drag_to. One consequence is worth knowing: the handle no longer
        jumps under the cursor when it is grabbed from up to SELECT_RADIUS
        away, it moves relative to where it already was.
        """
        scene = nodes.get_sequencer_scene(context)
        strip = nodes.get_active_strip(context)
        if strip is None:
            return {'CANCELLED'}

        self._pin_on_invoke = nodes.read_pin(strip)
        self._pin_corners = list(self._pin_on_invoke)
        self._edit_node = nodes.prepare_for_edit(strip, scene)
        self._drag_matrix = space.frame_to_pin_matrix(strip, scene)
        self._last_mouse = (event.mouse_region_x, event.mouse_region_y)
        return {'RUNNING_MODAL'}

    def modal(self, context, event, tweak):
        """Move this corner to follow the cursor."""
        if event.type == 'MOUSEMOVE':
            self._drag_to(context, event.mouse_region_x, event.mouse_region_y)
            return {'RUNNING_MODAL'}
        # The end-of-drag work is deliberately NOT done here. Blender's gizmo
        # tweak operator converts the confirming mouse release through its own
        # modal keymap, so this branch is not reliably reached; exit() is the
        # hook Blender always calls when the modal ends. Returning FINISHED
        # here still routes through exit(cancel=False), so both paths agree.
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            return {'FINISHED'}
        if event.type in {'ESC', 'RIGHTMOUSE'}:
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}

    def _accept_corner(self, corner):
        """
        Return the corner clamped to the image, or None if it breaks the quad.

        Only this corner moves during a drag, so the other three are whatever
        they were on invoke, and the convexity test can be run against the
        working copy without re-reading the sockets.
        """
        corner = nodes.clamp_corner(corner)
        candidate = list(self._pin_corners)
        candidate[self.handle_index] = corner
        return corner if space.is_convex_quad(candidate) else None

    def _drag_to(self, context, region_x, region_y):
        """
        Move this corner by however far the cursor travelled since the last event.

        The corner is *not* placed where the cursor points, and that is the
        whole point. A move that would make the quad concave, self-intersecting
        or degenerate has to be turned down - the Corner Pin solver cannot
        express such a quad and renders a blank or garbage frame instead of
        failing - but turning down an absolute position means the cursor keeps
        travelling while the corner sits still, and every pixel of that
        invisible travel has to be dragged back before the corner moves again.
        The handle feels stuck to a wall that is not there.

        Accumulating deltas onto the last accepted position removes that
        entirely: the corner stops at the boundary, and the very first mouse
        move back off it moves the corner again. Where the quad is not
        constrained this is identical to following the cursor, because the
        deltas simply sum to the cursor's travel. The cost is that after being
        held at a boundary the handle sits offset from the cursor; exit()
        already warps the cursor back onto the handle when the drag ends.

        A move refused outright is then tried one axis at a time, so a drag
        running along the boundary keeps making the progress it can instead of
        stopping dead the moment any part of it is disallowed.

        This relies on event.mouse_region_x staying continuous under
        use_grab_cursor, which it does - the absolute positions this used to
        read would have jumped at every cursor wrap otherwise.
        """
        if self._edit_node is None or context.region is None or self._last_mouse is None:
            return
        scene = nodes.get_sequencer_scene(context)
        view2d = context.region.view2d

        previous = space.apply(self._drag_matrix,
                               _region_to_frame(view2d, scene, *self._last_mouse))
        current = space.apply(self._drag_matrix,
                              _region_to_frame(view2d, scene, region_x, region_y))
        self._last_mouse = (region_x, region_y)

        here = self._pin_corners[self.handle_index]
        target = Vector((here.x + current.x - previous.x,
                         here.y + current.y - previous.y))

        accepted = self._accept_corner(target)
        if accepted is None:
            accepted = self._accept_corner(Vector((target.x, here.y)))
        if accepted is None:
            accepted = self._accept_corner(Vector((here.x, target.y)))
        if accepted is None:
            return

        self._pin_corners[self.handle_index] = accepted
        nodes.write_corner(self._edit_node, self.handle_index, accepted)
        _invalidate(nodes.get_active_strip(context))

    def _finish_edit(self, context):
        """
        Do the end-of-drag work: auto-key, then push undo.

        Writing a socket through RNA never triggers Blender's auto-key, so the
        drag has to ask for it explicitly. Only the corner that moved is keyed
        - see perspective_anim.autokey_corner for why.

        Called from exit(), not from modal(). Blender's gizmo tweak operator
        matches the confirming mouse release against its own modal keymap and
        finishes the modal itself, so Gizmo.modal() cannot be relied on to see
        a raw LEFTMOUSE/RELEASE. exit() is called either way.
        """
        strip = nodes.get_active_strip(context)
        scene = nodes.get_sequencer_scene(context)
        if strip is None or scene is None:
            return

        # A click that moved nothing should leave no keyframe and no undo step.
        if anim.pin_matches(strip, self._pin_on_invoke):
            return

        # Read the flag from the context, not the sequencer scene: the auto-key
        # toggle writes to the window scene, and 5.0 decoupled the two.
        anim.autokey_corner(strip, scene, self.handle_index,
                            getattr(context, "tool_settings", None))
        bpy.ops.ed.undo_push(message="Perspective Corner")

    def _restore(self, context):
        """Put the pin back to where it was when the drag started."""
        if self._pin_on_invoke is None or self._edit_node is None:
            return
        for index, corner in enumerate(self._pin_on_invoke):
            nodes.write_corner(self._edit_node, index, corner)
        _invalidate(nodes.get_active_strip(context))

    def exit(self, context, cancel):
        """
        Close out the drag: restore or commit, then put the cursor back.

        This is the only end-of-drag hook Blender guarantees to call, so both
        the cancel path and the confirm path are driven from here rather than
        from modal(). Both are safe to run twice, in case modal() did reach its
        own branch first.
        """
        if cancel:
            self._restore(context)
        else:
            self._finish_edit(context)

        self._edit_node = None
        self._drag_matrix = None
        self._pin_on_invoke = None
        self._pin_corners = None
        self._last_mouse = None

        region = context.region
        if cancel or region is None:
            return
        centre = self.matrix_basis.translation
        target_x = int(region.x + centre.x)
        target_y = int(region.y + centre.y)

        def restore_cursor():
            window = bpy.context.window
            if window is not None:
                window.cursor_warp(target_x, target_y)
                window.cursor_modal_restore()
            return None

        window = context.window
        if window is not None:
            window.cursor_modal_set('NONE')
            bpy.app.timers.register(restore_cursor, first_interval=0.05)


def _invalidate(strip):
    """
    Force the sequencer to recomposite the strip after a socket write.

    Changing a node socket does not by itself tell the VSE that its cached
    composite is stale, so without this the preview lags a drag by one edit.
    """
    if strip is None:
        return
    try:
        strip.invalidate_cache('COMPOSITE')
    except (AttributeError, TypeError, RuntimeError):
        pass


class PERSPECTIVE_GGT_perspective_handles(GizmoGroup):
    """Places the four corner handles over the active strip."""

    bl_idname = "PERSPECTIVE_GGT_perspective_handles"
    bl_label = "Perspective Transform Handles"
    bl_space_type = 'SEQUENCE_EDITOR'
    bl_region_type = 'PREVIEW'
    bl_options = {'SHOW_MODAL_ALL'}

    @classmethod
    def poll(cls, context):
        """Show the handles only for a visible, selected strip while the tool is active."""
        space_data = context.space_data
        if not space_data or space_data.type != 'SEQUENCE_EDITOR':
            return False
        if getattr(space_data, "display_mode", 'IMAGE') != 'IMAGE':
            return False

        scene = nodes.get_sequencer_scene(context)
        editor = getattr(scene, "sequence_editor", None) if scene else None
        if editor is None:
            return False

        strip = editor.active_strip
        if strip is None or not hasattr(strip, "transform") or not strip.select:
            return False
        if not is_strip_visible_at_frame(strip, scene.frame_current):
            return False

        workspace = context.workspace
        if workspace is None:
            return False
        return any(getattr(tool, "idname", None) == TOOL_IDNAME for tool in workspace.tools)

    def setup(self, context):
        """Create one gizmo per corner, in perspective_nodes corner order."""
        for index in range(4):
            gizmo = self.gizmos.new(PERSPECTIVE_GT_perspective_handle.bl_idname)
            gizmo.handle_index = index
            gizmo.select_id = index

    def refresh(self, context):
        """Move the handles onto the strip's current corner positions."""
        scene = nodes.get_sequencer_scene(context)
        strip = nodes.get_active_strip(context)
        region = context.region
        if strip is None or region is None:
            return

        view2d = region.view2d
        matrix = space.pin_to_frame_matrix(strip, scene)

        pin_corners = nodes.read_pin(strip)
        self._corner_screen = [_frame_to_region(view2d, scene, space.apply(matrix, c))
                               for c in pin_corners]
        self._bounds_screen = [_frame_to_region(view2d, scene, space.apply(matrix, c))
                               for c in nodes.IDENTITY_PIN]

        for index, gizmo in enumerate(self.gizmos):
            if index >= len(self._corner_screen):
                gizmo.hide = True
                continue
            x, y = self._corner_screen[index]
            gizmo.matrix_basis = Matrix.Translation((x, y, 0.0))
            gizmo.hide = False

    def draw_prepare(self, context):
        """Recompute positions each redraw so handles track zoom and pan."""
        self.refresh(context)
        self._draw_guides()

    def _draw_guides(self):
        """Outline the undistorted image rect and the current corner quad."""
        bounds = getattr(self, "_bounds_screen", None)
        corners = getattr(self, "_corner_screen", None)
        if bounds:
            _draw_polyline(bounds, COLOR_BOUNDS, width=1.0)
        if corners:
            _draw_polyline(corners, COLOR_QUAD, width=2.0)


def register_perspective_handles_gizmo():
    """Register the gizmo classes."""
    bpy.utils.register_class(PERSPECTIVE_GT_perspective_handle)
    bpy.utils.register_class(PERSPECTIVE_GGT_perspective_handles)


def unregister_perspective_handles_gizmo():
    """Unregister the gizmo classes."""
    bpy.utils.unregister_class(PERSPECTIVE_GGT_perspective_handles)
    bpy.utils.unregister_class(PERSPECTIVE_GT_perspective_handle)
