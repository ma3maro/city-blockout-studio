
"""On-canvas sketching and snapping for native road curves."""
from math import cos, pi, sin

import bpy
from bpy.props import EnumProperty
from bpy_extras import view3d_utils
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

from . import (ROAD_TYPES, activate, add_curve, add_spline, child, editable,
               geometry, guide_labels, snapshot, street_network, update_now)


def viewport_plane_point(region, view, event):
    x,y = event.mouse_x-region.x,event.mouse_y-region.y
    if not (0 <= x < region.width and 0 <= y < region.height):
        return None
    ray = view3d_utils.region_2d_to_vector_3d(region,view,(x,y))
    if abs(ray.z) < .001:
        return None
    origin = view3d_utils.region_2d_to_origin_3d(region,view,(x,y),clamp=5000)
    distance = -origin.z/ray.z
    return (origin + ray*distance).xy if distance >= 0 else None


class CBS_OT_sketch(bpy.types.Operator):
    bl_idname = "cbs.sketch"
    bl_label = "Sketch Road"
    bl_description = "Click to lay a road with live feedback and snapping to existing road centerlines"
    bl_options = {"REGISTER","UNDO"}
    kind: EnumProperty(items=ROAD_TYPES)

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and bool(context.scene.cbs.city) and editable(context.scene)

    def invoke(self, context, event):
        area = context.area
        if not area or area.type != "VIEW_3D":
            return {"CANCELLED"}
        self.region = next((r for r in area.regions if r.type == "WINDOW"),None)
        self.collection = child(context.scene.cbs.city,"Road Guides")
        if not self.region or not self.collection:
            return {"CANCELLED"}
        self.area = area
        self.view = area.spaces.active.region_3d
        self.scene = context.scene
        self.points = []
        self.cursor = None
        self.guide = None
        self.snapped = False
        self.smooth = False
        self.index = street_network(self.scene,snapshot(self.scene)[0])[1]
        self.status(context)
        self.handler = bpy.types.SpaceView3D.draw_handler_add(self.draw_overlay,(),"WINDOW","POST_PIXEL")
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def status(self, context):
        kind = "Bézier" if self.smooth else "Polyline"
        context.workspace.status_text_set(f"{kind}  |  Click: add point  •  Shift: free point  •  S: switch curve  •  Backspace: undo point  •  C: close loop  •  Enter: finish  •  Esc: cancel")

    def locate(self, event):
        pos = viewport_plane_point(self.region,self.view,event)
        if pos is None:
            return None,False,False
        radius = self.scene.cbs.snap_distance
        if event.shift or not radius:
            return pos,False,False
        if len(self.points) >= 3 and (self.points[0]-pos).length <= radius:
            return self.points[0],True,True
        match = geometry.nearest_street(self.index,*pos,radius)
        if match:
            a,b,_,_ = match
            origin = Vector(a)
            axis = Vector(b)-origin
            t = min(1.,max(0.,(pos-origin).dot(axis)/axis.length_squared))
            return origin+axis*t,True,False
        return pos,False,False

    def draw_overlay(self):
        if bpy.context.area != self.area:
            return
        position = self.points + ([self.cursor] if self.cursor is not None else [])
        points = [view3d_utils.location_3d_to_region_2d(self.region,self.view,(*p,.18)) for p in position]
        points = [p for p in points if p is not None]
        if not points:
            return
        shader = gpu.shader.from_builtin("UNIFORM_COLOR")
        gpu.state.blend_set("ALPHA")
        gpu.state.line_width_set(2.0)
        try:
            shader.bind()
            shader.uniform_float("color",(.18,.86,.96,.9))
            if len(points) >= 2:
                batch_for_shader(shader,"LINE_STRIP",{"pos":points}).draw(shader)
            for i,p in enumerate(points):
                is_cursor = self.cursor is not None and i == len(points)-1
                radius = 7 if is_cursor else 4
                if is_cursor:
                    shader.uniform_float("color",(1.,.68,.22,1.) if self.snapped else (.18,.86,.96,1.))
                ring = [(p.x+radius*cos(n*pi/8),p.y+radius*sin(n*pi/8)) for n in range(17)]
                batch_for_shader(shader,"LINE_STRIP",{"pos":ring}).draw(shader)
        finally:
            gpu.state.line_width_set(1.0)
            gpu.state.blend_set("NONE")

    def sync(self, context, closed=False):
        if len(self.points) < 2:
            if self.guide:
                self.guide.cbs_guide.enabled = False
            return
        origin = self.points[0]
        coords = [p-origin for p in self.points]
        if self.guide is None:
            self.guide = add_curve(self.collection,guide_labels[self.kind],coords,self.kind,
                                   closed=closed,position=origin,smooth=self.smooth)
            activate(context,self.guide)
        else:
            curve = self.guide.data
            curve.splines.clear()
            add_spline(curve,coords,closed,self.smooth)
            self.guide.location.x,self.guide.location.y = origin
            self.guide.cbs_guide.enabled = True

    def end_overlay(self, context):
        bpy.types.SpaceView3D.draw_handler_remove(self.handler,"WINDOW")
        context.workspace.status_text_set(None)
        self.area.tag_redraw()

    def cancel(self, context):
        self.end_overlay(context)
        if self.guide:
            data = self.guide.data
            bpy.data.objects.remove(self.guide,do_unlink=True)
            if not data.users:
                bpy.data.curves.remove(data)
            if context.scene == self.scene and self.scene.cbs.live:
                update_now(context)

    def finish(self, context, closed=False):
        if len(self.points) < 2:
            self.cancel(context)
            return {"CANCELLED"}
        self.sync(context,closed)
        self.end_overlay(context)
        if self.scene.cbs.live:
            update_now(context)
        return {"FINISHED"}

    def modal(self, context, event):
        if context.scene != self.scene or event.type in {"ESC","RIGHTMOUSE"} and event.value == "PRESS":
            self.cancel(context)
            return {"CANCELLED"}
        if event.type in {"MOUSEMOVE","LEFT_SHIFT","RIGHT_SHIFT"}:
            self.cursor,self.snapped,_ = self.locate(event)
            self.area.tag_redraw()
            return {"RUNNING_MODAL"}
        if event.value != "PRESS":
            return {"PASS_THROUGH"}
        if event.type in {"RET","NUMPAD_ENTER"}:
            return self.finish(context)
        if event.type == "C" and len(self.points) >= 3:
            return self.finish(context,closed=True)
        if event.type == "BACK_SPACE":
            if self.points:
                self.points.pop()
                self.sync(context)
        elif event.type == "S":
            self.smooth = not self.smooth
            self.sync(context)
            self.status(context)
        elif event.type == "LEFTMOUSE":
            point,self.snapped,close = self.locate(event)
            if close:
                return self.finish(context,closed=True)
            if point is not None and (not self.points or (point-self.points[-1]).length > .25):
                self.points.append(point)
                self.sync(context)
            self.cursor = point
        else:
            return {"PASS_THROUGH"}
        self.area.tag_redraw()
        return {"RUNNING_MODAL"}
