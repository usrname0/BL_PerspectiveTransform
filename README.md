# BL Perspective Transform

Drag the four corners of a strip in Blender's Video Sequence Editor preview to
distort it, and have the distortion render.

Reach it from the preview toolbar, the Transform menus, or the keyboard shortcut
(default "P").

![Dragging a corner handle in the VSE preview](./examples/demo.gif)

Corners can be dragged anywhere within the strip's original geometry, which can
be scaled, rotated, cropped, etc. as usual.

![An extreme corner-pin with headroom added](./examples/demo_complex.png)

The transform is stored as a Corner Pin node inside a compositor strip modifier,
so Blender evaluates it as part of normal strip rendering. It is not a preview
overlay: what you see is what renders.

Because the transform lives in a node group on the strip, it survives save and
load, shows up in the Strip Modifiers tab, and every corner can be keyframed.

## Compatibility

- **Blender 5.0 or newer.** Compositor strip modifiers, which this depends on,
  were added in 5.0. Developed and tested against 5.1.2.
- IMAGE and MOVIE strips
- Works alongside the strip's own scale, rotation, mirror and crop

## Usage

1. Select a strip and open the VSE preview
2. Activate the Perspective tool from the toolbar, or press "P"
3. Drag any of the four corner handles

The Perspective tab in the preview sidebar (N) shows numeric corner values, an
interpolation setting, and Reset / Clear buttons.

### Dragging corners outward

Blender's Corner Pin node clamps corners to the edges of the source image, so
by default a corner cannot be dragged outside the original rectangle. When you
hit that limit the sidebar offers **Add Headroom**, which enlarges the strip
while holding the image visually still, leaving room to drag into.

The scale transform (and others) may also be used manually to make room for pins.

## Installation

Download the latest [zip](https://github.com/usrname0/BL_PerspectiveTransform/releases)
and install it as an extension: in Blender, Edit > Preferences > Add-ons, then
the drop-down arrow at the top right > Install from Disk, and pick the zip.

## Troubleshooting

It should work immediately after installing. If the tool does not appear:

1. Check you are on Blender 5.0 or newer - on 4.x the addon will not load
2. Check the console for errors
3. Restart Blender

## Development

Run the test suite headlessly:

    blender --factory-startup --background --python tests/run.py
