# BL Perspective Transform - Development Plan

## Project Overview

**Goal**: Create a Blender addon that provides true perspective transformation capabilities for video strips in the Video Sequence Editor (VSE), allowing users to distort video content using corner pin handles for keystone correction, creative effects, and perspective matching.

**Current Status**: Phase 3 Complete (Preview) - Ready for Phase 4 (Rendering Integration)
**Next Phase**: Phase 4 - Rendering Integration (Compositor/Export)

### Current Implementation Architecture
- **Modal Operator**: `SEQUENCER_OT_perspective_modal` - Click-and-drag perspective transform interface
- **Gizmo System**: `PERSPECTIVE_GGT_perspective_handles` - Visual corner handles for interactive perspective transformation
- **Toolbar Integration**: Custom tools in VSE toolbar for easy access
- **Core Logic**: Shared perspective calculation functions in `operators/perspective_core.py`

### File Structure
```
D:\Dev\BL_PerspectiveTransform\BL_PerspectiveTransform\
├── __init__.py                     # Main addon registration
├── operators/
│   ├── perspective_modal.py       # Modal operator implementation
│   ├── perspective_core.py        # Shared perspective calculation functions
│   ├── perspective_math.py        # Homography calculations (DLT with SVD)
│   └── perspective_drawing.py     # Drawing utilities for perspective handles
├── gizmos/
│   └── perspective_handles_gizmo.py # Gizmo-based perspective interface
├── tools/
│   └── perspective_tools.py       # Toolbar tool definitions
└── presets/
    └── keymap/
        └── sequencer.py           # Keymap for sequencer shortcuts
```

### Key Features Implemented
1. **Visual Corner Handles**: 4 corner handles for perspective distortion control
2. **Real-time Texture Preview**: Live preview showing actual image content with perspective distortion (GPU overlay)
3. **Perspective-Correct Rendering**: Custom GLSL shader with bilinear inverse mapping for accurate distortion
4. **Transform Support**: Handles rotation, scaling, and flipping correctly (identity-based corner tracking)
5. **Keyboard Shortcuts**: P key activates gizmo tool, Shift+P for modal
6. **Toolbar Integration**: Dedicated perspective tools in VSE toolbar
7. **Handle Visual Feedback**: Orange highlight on hover, consistent 6px sizing
8. **Mathematical Accuracy**: Perfect homography calculation with DLT+SVD
9. **Data Persistence**: All perspective data saved in strip custom properties
10. **Texture Extraction**: Automatic loading and GPU upload of IMAGE strip textures

### User Interface
**Primary Interface: Gizmo Tool**
- **Activation**: P key or toolbar button
- **Tool ID**: `sequencer.perspective_handles_tool`
- **Visual**: Persistent corner handles with orange hover feedback
- **Workflow**: Click and drag corner handles to distort, gizmos stay visible

**Secondary Interface: Modal Operator**
- **Activation**: Shift+P key or menu
- **Tool ID**: `SEQUENCER_OT_perspective_modal`
- **Visual**: Temporary corner handles that appear during operation
- **Workflow**: Single-use operation, handles disappear after use

## Development Phases

###  Phase 1: Foundation & Handle System (COMPLETE)
**Timeline**: Initial development
**Status**:  Complete

#### Core Components Implemented
- [x] **Homography Mathematics** (`perspective_math.py`)
  - DLT (Direct Linear Transform) with SVD calculation
  - Perfect accuracy homography matrix generation
  - 4-point to 4-point perspective mapping

- [x] **Gizmo Handle System** (`perspective_handles_gizmo.py`)  
  - 4 corner handles for perspective distortion control
  - Real-time handle positioning and constraints
  - Orange hover feedback and 6px consistent sizing
  - Boundary constraints (handles stay within VSE rectangle)

- [x] **Data Storage System** (`perspective_core.py`)
  - Homography matrix storage in strip custom properties
  - Perspective corner offset storage (rotation-invariant)
  - Original corner preservation for transform composition

- [x] **Visual Feedback**
  - Red boundary outline (original VSE rectangle)
  - Cyan preview lines connecting perspective handles
  - Diagonal reference lines showing distortion

#### Key Technical Achievements
- Stable handle interaction (no glitchy strip movement)
- Proper coordinate system handling (strip � view � screen)
- Flip state compensation and rotation support
- EasyCrop-style cursor warping and modal interaction

###  Phase 2: GPU Overlay System (COMPLETE)
**Timeline**: Current implementation  
**Status**:  Complete

#### Components Implemented
- [x] **GPU Draw Handler** (`perspective_core.py`)
  - `SpaceSequenceEditor.draw_handler_add` integration
  - 'PREVIEW' region, 'POST_PIXEL' drawing
  - Automatic handler installation/removal

- [x] **Perspective Overlay Rendering**
  - Semi-transparent cyan quad showing perspective distortion
  - Real-time GPU batch rendering with triangulated quads
  - Alpha blending for overlay effect

- [x] **Performance Optimization**
  - Only renders when strips have active perspective transforms
  - Strip-based enable/disable system
  - Proper cleanup on addon unregister

#### Current Capabilities
-  Real-time visual feedback of perspective distortion
-  Stable original strip (no unwanted movement)
-  Mathematical accuracy (homography calculated correctly)
-  Data persistence across Blender sessions

### = Phase 3: Full Texture Distortion (IN PROGRESS)
**Timeline**: Next major milestone
**Status**: = Planning/Research

#### Objectives
Transform the colored overlay into actual texture distortion of the video/image content.

#### Technical Challenges
1. **Strip Texture Extraction**
   - Access the underlying texture/image data from VSE strips
   - Handle different strip types (movie, image, color, etc.)
   - Work with Blender's texture system

2. **Perspective-Correct Texture Mapping**
   - Implement proper UV coordinate transformation
   - Use `IMAGE` shader with custom vertex positions
   - Ensure perspective-correct interpolation (not affine)

3. **Performance Considerations**
   - GPU texture upload/update efficiency
   - Frame-accurate texture sampling for video strips
   - Memory management for texture resources

#### Implementation Strategy

**Option A: Direct Texture Rendering**
```python
# Pseudo-code approach
strip_texture = get_strip_texture(active_strip, current_frame)
shader = gpu.shader.from_builtin('IMAGE')  
batch = batch_for_shader(shader, 'TRIS', {
    "pos": perspective_vertices,
    "texCoord": [(0,0), (1,0), (1,1), (0,1)]  # Original UV coords
})
```

**Option B: Render Target Approach**
- Render strip to offscreen buffer
- Apply perspective transformation as post-process
- Composite back to VSE preview

**Option C: Custom Shader Approach**
- Write custom vertex/fragment shaders
- Handle perspective transformation in shader code
- Maximum flexibility but higher complexity

#### Research Tasks
- [ ] Investigate VSE strip texture access methods
- [ ] Study Blender's GPU texture system
- [ ] Research perspective-correct texture mapping techniques
- [ ] Analyze performance implications of different approaches

### =� Phase 4: Enhancement & Polish (PLANNED)
**Timeline**: Post-texture implementation
**Status**: =� Planned

#### Planned Features
- [ ] **Texture Blending Options**
  - Original strip visibility control
  - Overlay blend modes (multiply, screen, etc.)
  - Feathered edges for seamless integration

- [ ] **Advanced Handle Features**  
  - Handle snapping to grid/guides
  - Numerical input for precise positioning
  - Handle locking to prevent accidental movement

- [ ] **Animation Support**
  - Keyframe perspective transformations
  - Linear/bezier interpolation between keyframes
  - Timeline integration with VSE keyframe system

- [ ] **User Interface Enhancements**
  - Properties panel for numerical control
  - Preset system for common transformations
  - Import/export of perspective data

- [ ] **Performance Optimizations**
  - Texture caching for repeated frames
  - LOD system for distant/small strips
  - GPU memory management improvements

### =� Phase 5: Advanced Features (FUTURE)
**Timeline**: Long-term goals
**Status**: =� Future

#### Advanced Capabilities
- [ ] **Multi-Point Tracking Integration**
  - Motion tracking data import
  - Automatic corner detection
  - Tracking data to perspective transform conversion

- [ ] **3D Integration**
  - Export to 3D scene for advanced compositing
  - Camera matching for perspective correction
  - 3D plane projection workflow

- [ ] **Compositor Integration**
  - Corner Pin node integration
  - Automatic compositor setup
  - Render layer export options

- [ ] **Format Export/Import**
  - After Effects corner pin data
  - Nuke transform data
  - Industry-standard formats

## Technical Architecture

### Core Modules
```
operators/
   perspective_core.py       # Core logic & state management
   perspective_math.py       # Homography calculations  
   perspective_operators.py  # Blender operators
   perspective_drawing.py    # Drawing utilities

gizmos/
   perspective_handles_gizmo.py  # Interactive handle system

tools/
   perspective_tools.py      # Toolbar integration
```

### Key Data Structures
```python
# Homography Matrix (3x3)
strip["perspective_h00"] through strip["perspective_h22"]

# Corner Offsets (proportional, rotation-invariant)
strip["perspective_offset_x0"] through strip["perspective_offset_y3"]

# Original Corners (for transform composition)
strip["perspective_orig_x0"] through strip["perspective_orig_y3"]
```

### Coordinate Systems
1. **Strip Space**: Resolution-based coordinates (0 to res_x/res_y)
2. **View Space**: Centered coordinates (-res_x/2 to res_x/2)  
3. **Screen Space**: Region pixel coordinates for handle positioning

## Testing & Validation

### Current Test Coverage
- [x] Homography calculation accuracy (0.0000 error on test cases)
- [x] Handle positioning with rotation/flip states
- [x] Data persistence across Blender sessions
- [x] GPU overlay rendering stability

### Planned Testing
- [ ] Performance testing with high-resolution textures
- [ ] Memory leak detection for texture resources
- [ ] Cross-platform compatibility (Windows/macOS/Linux)
- [ ] Blender version compatibility testing

## Known Issues & Limitations

### Current Limitations
- **No Real Texture Distortion**: Currently shows colored overlay only
- **Single Strip Support**: GPU rendering only works with active strip
- **No Animation**: No keyframe support yet
- **Basic Visual Feedback**: Limited to colored overlay

### Technical Debt
- GPU handler could be more efficiently managed
- Error handling could be more robust
- Memory cleanup could be more thorough

## Success Criteria

### Phase 3 Success Criteria
- [ ] Video/image content shows actual perspective distortion
- [ ] Performance acceptable for real-time preview
- [ ] Texture quality maintained during transformation
- [ ] No visual artifacts or rendering glitches

### Project Success Criteria  
- [ ] True perspective distortion of video content
- [ ] Intuitive handle-based interface
- [ ] Professional-grade accuracy and performance
- [ ] Seamless VSE integration
- [ ] Industry-standard export capabilities

## Resources & References

### Technical References
- Computer Vision: Algorithms and Applications (Szeliski) - Homography theory
- OpenGL Programming Guide - Perspective-correct texture mapping
- Blender GPU Module Documentation - GPU rendering system

### Blender-Specific Resources
- VSE Workshop 2024 notes - Recent VSE developments
- GPU Shader Examples - Texture rendering techniques
- Extension Guidelines - Blender 4.x compliance

### Similar Tools (Research)
- After Effects Corner Pin effect
- Nuke CornerPin2D node
- DaVinci Resolve perspective correction
- Motion tracking software workflows

## Development Notes

### Key Insights
1. **VSE Treats Strips as Textures**: Can render custom geometry with draw handlers
2. **GPU Rendering is Key**: Much better than trying to approximate with affine transforms
3. **Handle System Works Well**: EasyCrop-based approach is solid foundation
4. **Mathematical Accuracy**: Homography calculation is production-ready

### Lessons Learned
- Don't try to force affine transforms to do perspective work
- GPU overlay approach much better than transform property manipulation
- Proper coordinate system handling is critical
- User feedback on visual behavior is invaluable

---

*Last Updated: 2025-08-06*
*Current Phase: 2 Complete, 3 In Progress*
*Next Milestone: Full texture distortion implementation*