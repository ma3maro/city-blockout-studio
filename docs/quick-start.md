
# City Blockout Studio 1.1

Sketch a city in Blender by drawing streets and assigning land use. The included starter city has a downtown tower cluster, brick storefronts, contemporary apartments, parks, an industrial area and a vacant waterfront parcel.

## Install

1. In Blender, open **Edit → Preferences → Get Extensions**. Use the menu in the upper right to choose **Install from Disk**, then select **City Blockout Studio.zip**.
2. In the 3D Viewport, press **N** and choose **City Blockout**.
3. Choose **Load Starter City** or **Start Blank City**. You can also open the editable sample after installing the extension. It includes aerial and street cameras and opens in Blender 5.0.1 and 5.3.0.

## Draw and adjust

- **Roads.** Choose **Sketch Road** and click in the viewport to lay out a street. Use **Enter** to finish, **C** to close a loop, **Backspace** to remove the last point, and **Esc** to cancel. Points snap to nearby road centerlines. Hold **Shift** to place a free point. Press **S** to switch between a polyline and a smooth Bézier curve while sketching.
- **Edit or import curves.** Add a local street or avenue, then press **Tab** to move, extrude or reshape its points. Use **Use Selected Curve** to adopt a native Bézier or Poly Curve with one or more splines. Use **Find Guide** to select a named road or district, and the X-ray button beside it to see guides through buildings.
- **Frontages.** Select a road and open **Selected Guide** to set its width or assign each side a different building profile. Left and right follow the spline's point order. Use Blender's **Switch Direction** command to reverse that order.
- **Districts.** Add a district and resize or reshape its closed outline. You can also adopt a closed Bézier or Poly spline. Districts override road frontages, which override the city profile. The higher priority wins where typed districts overlap. Park and Vacant reserve their area before buildings are placed. Vacant also suppresses foliage. Roads still follow your drawn guides.
- **District Brush.** In Top View (**Numpad 7**), open **District Brush**, set a radius and choose **Paint District**. Drag with the left mouse button, then press **Enter** to keep the district or **Esc** to discard it. The resulting outline strokes stay editable as splines.
- **Profiles.** Use Western for brick main streets, Modern for contemporary apartments, Corporate for offices, Busy Mixed Use for storefronts and mid-rises, and Quiet Residential for sparser lots. The other profiles cover modest and upscale housing, skyscrapers, industrial, civic and vacant land. Change global density, scale, setbacks and seed under **City Layout**. Use district multipliers for local density and height.
- **Block interiors.** Raise **Block Infill** to build inside blocks enclosed by roads. Frontage buildings are placed first. Open countryside, parks, and vacant areas stay clear.
- **Road detail.** In **Surface & Street Detail**, adjust lane markings, trees, park planting, and static traffic. Turn on **Curbs & Streetlights** and **Facade Detail** for close-up views. Set **Static Traffic** to zero to hide cars.
- **Terrain (Experimental).** Switch **Surface** to **Terrain (Experimental)** and select a mesh linked to the current scene. Roads and landscaping project down from above in world space. Cars follow the grade and buildings stay upright on foundations. Guides are drawn in XY. Continuous, gently sloping surfaces work best. Use **Clearance** to lift roads slightly if the terrain clips through. Missing ground can leave gaps. Stacked roads, tunnels and bridges require manual editing after baking.
- **Bake.** Choose **Bake Editable Meshes** in Object Mode. Each building and car gets its own mesh, origin, and local axes. Road strips are welded along their seams. The output is grouped under **Baked City**, with its own materials by default. Enable **Hide Live Preview** in the bake dialog to avoid overlapping geometry. Use the eye button beside Bake and the Outliner to switch between the live and baked cities.

**Live Preview** applies changes automatically after a short delay. Pause it while making many edits, then use the refresh button to apply them together. For large layouts, keep facade and street fixtures off during broad layout edits and enable them when moving to street-level work.
