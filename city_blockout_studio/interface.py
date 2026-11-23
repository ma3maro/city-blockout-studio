
"""Sidebar and native Blender operators."""
from math import ceil, cos, pi, sin

import bpy
from bpy.props import EnumProperty, StringProperty
from mathutils import Quaternion, Vector

from . import (GUIDE_TYPES, PROFILES, ROAD_TYPES, ROAD_KEYS, ROLES, PARTS, TAG,
               activate, add_curve, add_spline, child, create_city, demo, editable, guide_labels,
               update_now)
from .sketch import viewport_plane_point


class CBS_Edit:
    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and editable(context.scene)


class CBS_OT_blank(CBS_Edit,bpy.types.Operator):
    bl_idname = "cbs.blank"
    bl_label = "Start Blank City"
    bl_options = {"REGISTER","UNDO"}

    def execute(self, context):
        create_city(context.scene)
        update_now(context)
        return {"FINISHED"}


class CBS_OT_starter(CBS_Edit,bpy.types.Operator):
    bl_idname = "cbs.starter"
    bl_label = "Load Starter City"
    bl_description = "Create an editable layout with a skyline, parks, and distinct neighborhoods"
    bl_options = {"REGISTER","UNDO"}

    def execute(self, context):
        city = create_city(context.scene)
        roads, zones = (child(city,role) for role in ROLES[:2])
        if roads.objects or zones.objects:
            self.report({"WARNING"},"The city already has guides. Start a new scene to load the starter.")
            return {"CANCELLED"}
        for name,kind,coords in demo.ROADS:
            add_curve(roads,name,coords,kind,smooth=True)
        for name,kind,coords,priority in demo.ZONES:
            obj = add_curve(zones,name,coords,kind,closed=True)
            obj.cbs_guide.priority = priority
        update_now(context)
        for workspace in context.window.screen.areas if context.window else ():
            if workspace.type == "VIEW_3D":
                view = workspace.spaces.active
                view.shading.color_type = "MATERIAL"
                view.clip_end = max(view.clip_end,4000)
                view.region_3d.view_distance = 720
                view.region_3d.view_location = (0,0,8)
        return {"FINISHED"}


class CBS_OT_guide(CBS_Edit,bpy.types.Operator):
    bl_idname = "cbs.add_guide"
    bl_label = "Add Guide"
    bl_description = "Add an editable native curve at the 3D cursor"
    bl_options = {"REGISTER","UNDO"}
    kind: EnumProperty(items=GUIDE_TYPES)

    def execute(self, context):
        city = create_city(context.scene)
        road = self.kind in ROAD_KEYS
        collection = child(city,"Road Guides" if road else "District Guides")
        coords = [(-62,-7),(-28,-6),(22,8),(62,5)] if road else [(-29,-21),(29,-21),(29,21),(-29,21)]
        pos = context.scene.cursor.location.xy
        obj = add_curve(collection,guide_labels[self.kind],coords,self.kind,
                        closed=not road,position=pos,smooth=road)
        activate(context,obj)
        if context.scene.cbs.live:
            update_now(context)
        return {"FINISHED"}


class CBS_OT_adopt(CBS_Edit,bpy.types.Operator):
    bl_idname = "cbs.adopt"
    bl_label = "Use Selected Curve"
    bl_description = "Use the selected Bézier or Poly curve as an editable guide"
    bl_options = {"REGISTER","UNDO"}
    kind: EnumProperty(items=GUIDE_TYPES)

    @classmethod
    def poll(cls, context):
        obj = context.object
        return super().poll(context) and obj and obj.type == "CURVE" and not obj.library

    def execute(self, context):
        obj = context.object
        road = self.kind in ROAD_KEYS
        if not any(s.type in {"BEZIER","POLY"} and (road or s.use_cyclic_u)
                   and len(s.bezier_points if s.type == "BEZIER" else s.points) >= (2 if road else 3)
                   for s in obj.data.splines):
            self.report({"WARNING"}, "Use a Bézier or Poly spline with at least two points." if road else
                        "Close a Bézier or Poly spline with at least three points before assigning a district.")
            return {"CANCELLED"}
        city = create_city(context.scene)
        collection = child(city,"Road Guides" if road else "District Guides")
        other = child(city,"District Guides" if road else "Road Guides")
        for scene in bpy.data.scenes:
            if scene != context.scene and scene.cbs.city:
                if any(group and obj.name in group.objects for group in (child(scene.cbs.city,r) for r in ROLES[:2])):
                    self.report({"WARNING"},"Duplicate the curve before using it in another city.")
                    return {"CANCELLED"}
        if obj.name not in collection.objects:
            collection.objects.link(obj)
        if obj.name in other.objects:
            other.objects.unlink(obj)
        obj.cbs_guide.kind = self.kind
        if context.scene.cbs.live:
            update_now(context)
        return {"FINISHED"}


class CBS_OT_paint(CBS_Edit,bpy.types.Operator):
    bl_idname = "cbs.paint"
    bl_label = "Paint District"
    bl_description = "Brush a district in the viewport. Enter finishes and Escape cancels"
    bl_options = {"REGISTER","UNDO"}
    kind: EnumProperty(items=PROFILES)

    def invoke(self, context, event):
        if not context.area or context.area.type != "VIEW_3D":
            return {"CANCELLED"}
        self.region = next((r for r in context.area.regions if r.type == "WINDOW"),None)
        if not self.region:
            return {"CANCELLED"}
        self.view = context.space_data.region_3d
        self.radius = context.scene.cbs.brush_radius
        self.guide = self.last = None
        self.pressed = False
        context.workspace.status_text_set("Paint with left mouse  •  Enter: finish  •  Esc: cancel")
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def stamp(self, context, center):
        coords = [(center.x+self.radius*cos(i*pi/8),center.y+self.radius*sin(i*pi/8)) for i in range(16)]
        if self.guide is None:
            city = create_city(context.scene)
            self.guide = add_curve(child(city,"District Guides"),guide_labels[self.kind]+" Brush",
                                   coords,self.kind,closed=True)
            activate(context,self.guide)
        else:
            add_spline(self.guide.data,coords,closed=True)

    def modal(self, context, event):
        if event.type in {"ESC","RET","NUMPAD_ENTER","RIGHTMOUSE"} and event.value == "PRESS":
            context.workspace.status_text_set(None)
            keep = event.type in {"RET","NUMPAD_ENTER"}
            if not self.guide:
                return {"CANCELLED"}
            if not keep:
                data = self.guide.data
                bpy.data.objects.remove(self.guide,do_unlink=True)
                if not data.users:
                    bpy.data.curves.remove(data)
            if context.scene.cbs.live:
                update_now(context)
            return {"FINISHED"} if keep else {"CANCELLED"}
        if event.type == "LEFTMOUSE":
            self.pressed = event.value == "PRESS"
            self.last = None
        if self.pressed and event.type in {"LEFTMOUSE","MOUSEMOVE"}:
            point = viewport_plane_point(self.region,self.view,event)
            if point is not None:
                if self.last is None:
                    self.stamp(context,point)
                    self.last = point
                else:
                    length = (point-self.last).length
                    if length >= self.radius*.65:
                        origin = self.last
                        steps = min(80,ceil(length/(self.radius*.65)))
                        for i in range(1,steps+1):
                            self.stamp(context,origin.lerp(point,i/steps))
                        self.last = point
                context.area.tag_redraw()
            return {"RUNNING_MODAL"}
        if event.type == "LEFTMOUSE":
            return {"RUNNING_MODAL"}
        return {"PASS_THROUGH"}


class CBS_OT_refresh(bpy.types.Operator):
    bl_idname = "cbs.refresh"
    bl_label = "Refresh Preview"
    bl_description = "Apply pending changes while live preview is paused"
    bl_options = {"REGISTER","UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(context.scene.cbs.city) and editable(context.scene)

    def execute(self, context):
        create_city(context.scene)
        update_now(context,force=True)
        return {"FINISHED"}


class CBS_OT_frame_city(bpy.types.Operator):
    bl_idname = "cbs.frame_city"
    bl_label = "Frame City"
    bl_description = "Fit the live city into the viewport"
    top: bpy.props.BoolProperty(name="Top View",default=False)

    @classmethod
    def poll(cls, context):
        return bool(context.area and context.area.type == "VIEW_3D" and context.scene.cbs.city)

    def execute(self,context):
        live = child(context.scene.cbs.city,"Live City")
        points = [obj.matrix_world @ Vector(co) for obj in live.objects if obj.get(TAG)
                  for co in obj.bound_box] if live else []
        if not points:
            return {"CANCELLED"}
        low = Vector(tuple(min(p[i] for p in points) for i in range(3)))
        high = Vector(tuple(max(p[i] for p in points) for i in range(3)))
        region = context.space_data.region_3d
        region.view_location = (low+high)*.5
        region.view_distance = max(10.,max(high-low)*1.32)
        region.view_perspective = "ORTHO"
        if self.top:
            region.view_rotation = Quaternion((1,0,0,0))
        context.space_data.clip_end = max(context.space_data.clip_end,region.view_distance*4)
        return {"FINISHED"}


class CBS_OT_find_guide(CBS_Edit,bpy.types.Operator):
    bl_idname = "cbs.find_guide"
    bl_label = "Find Guide"
    bl_description = "Search for a road or district by name"
    group: EnumProperty(name="Search",items=(("ROAD","Roads","Search road guides"),
                                              ("ZONE","Districts","Search district guides")))
    guide: StringProperty(name="Guide")

    def collection(self, context):
        city = context.scene.cbs.city
        return child(city,ROLES[0 if self.group == "ROAD" else 1]) if city else None

    def invoke(self,context,event):
        return context.window_manager.invoke_props_dialog(self,width=340)

    def draw(self,context):
        self.layout.prop(self,"group",expand=True)
        collection = self.collection(context)
        if collection:
            self.layout.prop_search(self,"guide",collection,"objects")

    def execute(self,context):
        collection = self.collection(context)
        obj = collection.objects.get(self.guide) if collection else None
        if not obj or obj.name not in context.view_layer.objects:
            self.report({"WARNING"},"Choose a guide from the current view layer.")
            return {"CANCELLED"}
        obj.hide_set(False)
        activate(context,obj)
        return {"FINISHED"}


class CBS_OT_visibility(bpy.types.Operator):
    bl_idname = "cbs.visibility"
    bl_label = "Toggle Live Meshes"
    bl_options = {"REGISTER","UNDO"}

    def execute(self, context):
        live = child(context.scene.cbs.city,"Live City")
        live.hide_viewport = not live.hide_viewport
        live.hide_render = live.hide_viewport
        return {"FINISHED"}


class CBS_OT_guide_overlay(CBS_Edit,bpy.types.Operator):
    bl_idname = "cbs.guide_overlay"
    bl_label = "Toggle Guide X-Ray"
    bl_description = "Show road and district guides through the city geometry or return them to depth-tested display"
    bl_options = {"REGISTER","UNDO"}

    def execute(self,context):
        city = context.scene.cbs.city
        guides = [obj for key in ROLES[:2] if city and (group := child(city,key))
                  for obj in group.objects if obj.type == "CURVE" and not obj.library]
        if not guides:
            return {"CANCELLED"}
        show = not any(obj.show_in_front for obj in guides)
        for obj in guides:
            obj.show_in_front = show
        return {"FINISHED"}


class CBS_MT_create_road(bpy.types.Menu):
    bl_label = "Add Road"

    def draw(self, context):
        for key,label,_ in ROAD_TYPES:
            self.layout.operator("cbs.add_guide",text=label,icon="CURVE_BEZCURVE").kind = key


class CBS_MT_sketch(bpy.types.Menu):
    bl_label = "Sketch Road"

    def draw(self, context):
        self.layout.operator_context = "INVOKE_DEFAULT"
        for key,label,_ in ROAD_TYPES:
            self.layout.operator("cbs.sketch",text=label,icon="GREASEPENCIL").kind = key


class CBS_MT_create_zone(bpy.types.Menu):
    bl_label = "Add District"

    def draw(self, context):
        for key,label,_ in PROFILES:
            self.layout.operator("cbs.add_guide",text=label).kind = key


class CBS_MT_paint_zone(bpy.types.Menu):
    bl_label = "Paint District"

    def draw(self, context):
        self.layout.operator_context = "INVOKE_DEFAULT"
        for key,label,_ in PROFILES:
            self.layout.operator("cbs.paint",text=label).kind = key


class CBS_MT_adopt_curve(bpy.types.Menu):
    bl_label = "Use Selected Curve"

    def draw(self, context):
        for key,label,_ in ROAD_TYPES:
            self.layout.operator("cbs.adopt",text=label,icon="CURVE_BEZCURVE").kind = key
        self.layout.separator()
        for key,label,_ in PROFILES:
            self.layout.operator("cbs.adopt",text=label).kind = key


class CBS_MT_guide_type(bpy.types.Menu):
    bl_label = "Guide Type"

    def draw(self, context):
        city = context.scene.cbs.city
        obj = context.object
        items = ROAD_TYPES if obj.name in child(city,"Road Guides").objects else PROFILES
        for key,label,_ in items:
            self.layout.prop_enum(obj.cbs_guide,"kind",key,text=label)


class CBS_PT_city(bpy.types.Panel):
    bl_label = "City Blockout Studio"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "City Blockout"

    def draw(self, context):
        s = context.scene.cbs
        ui = self.layout
        if not s.city:
            ui.operator("cbs.starter",icon="OUTLINER_COLLECTION")
            ui.operator("cbs.blank",icon="MESH_PLANE")
            return
        if not editable(context.scene):
            ui.label(text="Shared city collection",icon="LINKED")
            return
        row = ui.row(align=True)
        row.prop(s,"live",toggle=True,text="Live Preview",icon="RESTRICT_VIEW_OFF")
        row.operator("cbs.refresh",text="",icon="FILE_REFRESH")
        row.operator("cbs.frame_city",text="",icon="ZOOM_ALL")
        row.operator("cbs.frame_city",text="",icon="VIEW_ORTHO").top = True
        ui.menu("CBS_MT_sketch",icon="GREASEPENCIL")
        row = ui.row(align=True)
        row.menu("CBS_MT_create_road",icon="CURVE_DATA")
        row.menu("CBS_MT_create_zone",icon="MOD_MASK")
        if context.object and context.object.type == "CURVE":
            ui.menu("CBS_MT_adopt_curve",icon="LINKED")
        if any(collection.objects for key in ROLES[:2] if (collection := child(s.city,key))):
            row = ui.row(align=True)
            row.operator("cbs.find_guide",icon="VIEWZOOM")
            row.operator("cbs.guide_overlay",text="",icon="XRAY")
        else:
            ui.operator("cbs.starter",icon="OUTLINER_COLLECTION")
        row = ui.row(align=True)
        row.operator("cbs.bake",icon="MESH_DATA")
        live = child(s.city,"Live City")
        if live:
            row.operator("cbs.visibility",text="",icon="HIDE_ON" if live.hide_viewport else "HIDE_OFF")
            parts = {obj.get(TAG):len(obj.data.get(PARTS,{}))
                     for obj in live.objects if obj.get(TAG) in {"Buildings","Traffic"}}
            if live.hide_viewport:
                ui.label(text="Live meshes hidden",icon="HIDE_ON")
            elif parts:
                ui.label(text=f"{parts.get('Buildings',0):,} buildings  •  {parts.get('Traffic',0):,} vehicles")


class CBS_Subpanel:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_parent_id = "CBS_PT_city"

    @classmethod
    def poll(cls, context):
        return bool(context.scene.cbs.city and editable(context.scene))


class CBS_PT_selected(CBS_Subpanel,bpy.types.Panel):
    bl_label = "Selected Guide"

    @classmethod
    def poll(cls, context):
        if not super().poll(context) or not context.object:
            return False
        return any(collection and context.object.name in collection.objects
                   for role in ROLES[:2] if (collection := child(context.scene.cbs.city,role)))

    def draw(self, context):
        obj, ui = context.object, self.layout
        guide = obj.cbs_guide
        ui.prop(guide,"enabled")
        ui.menu("CBS_MT_guide_type",text=guide_labels[guide.kind],icon="DOWNARROW_HLT")
        if guide.kind in ROAD_KEYS:
            ui.prop(guide,"left",text="Left")
            ui.prop(guide,"right",text="Right")
            ui.prop(guide,"custom_width")
            if guide.custom_width:
                ui.prop(guide,"width")
        elif guide.kind not in {"PARK","EMPTY"}:
            ui.prop(guide,"priority")
            ui.prop(guide,"density")
            ui.prop(guide,"height")


class CBS_PT_layout(CBS_Subpanel,bpy.types.Panel):
    bl_label = "City Layout"

    def draw(self, context):
        s, ui = context.scene.cbs, self.layout
        ui.use_property_split = True
        ui.prop(s,"character",text="Profile")
        ui.prop(s,"density",text="Density",slider=True)
        ui.prop(s,"infill",text="Block Infill",slider=True)
        ui.prop(s,"height",text="Height",slider=True)
        ui.prop(s,"seed")
        ui.prop(s,"setback",text="Setback")
        ui.prop(s,"street",text="Street Width")
        ui.prop(s,"avenue")
        ui.prop(s,"snap_distance",text="Sketch Snap")


class CBS_PT_paint(CBS_Subpanel,bpy.types.Panel):
    bl_label = "District Brush"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        self.layout.prop(context.scene.cbs,"brush_radius")
        self.layout.menu("CBS_MT_paint_zone",icon="BRUSH_DATA")


class CBS_PT_surface(CBS_Subpanel,bpy.types.Panel):
    bl_label = "Surface & Street Detail"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        s, ui = context.scene.cbs, self.layout
        ui.use_property_split = True
        ui.prop(s,"terrain_mode")
        if s.terrain_mode == "TERRAIN":
            ui.prop(s,"terrain")
            if s.terrain and s.terrain.name in context.scene.objects:
                ui.prop(s,"terrain_clearance",text="Clearance")
            else:
                ui.label(text="Select a terrain mesh",icon="INFO")
        ui.prop(s,"markings")
        ui.prop(s,"street_fixtures")
        ui.prop(s,"facades")
        ui.prop(s,"parks")
        ui.prop(s,"trees",slider=True)
        ui.prop(s,"traffic",slider=True)


CLASSES = (CBS_OT_blank,CBS_OT_starter,CBS_OT_guide,CBS_OT_adopt,CBS_OT_paint,CBS_OT_refresh,
           CBS_OT_visibility,CBS_OT_guide_overlay,CBS_OT_frame_city,CBS_OT_find_guide,CBS_MT_create_road,
           CBS_MT_sketch,CBS_MT_create_zone,CBS_MT_paint_zone,CBS_MT_adopt_curve,CBS_MT_guide_type,
           CBS_PT_city,CBS_PT_selected,CBS_PT_layout,CBS_PT_paint,CBS_PT_surface)
