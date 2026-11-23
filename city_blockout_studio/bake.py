
"""Build a detached, organized snapshot of the live city."""
import bpy
from bpy.props import BoolProperty
from mathutils import Matrix, Vector

from . import PARTS, TAG, child, editable, guide_labels, populate, update_now


GROUPS = {
    "Ground": "Landscape", "Open Space": "Landscape",
    "Sidewalks": "Streets", "Roads": "Streets", "Markings": "Streets", "Street Fixtures": "Streets",
    "Buildings": "Buildings", "Traffic": "Vehicles",
}


def weld_surface(vertices, faces, indices):
    points = {}
    unique = []
    remap = []
    for co in vertices:
        key = tuple(round(value,5) for value in co)
        index = points.get(key)
        if index is None:
            index = points[key] = len(unique)
            unique.append(co)
        remap.append(index)
    polygons,materials = [],[]
    for face,index in zip(faces,indices):
        polygon = tuple(dict.fromkeys(remap[v] for v in face))
        if len(polygon) >= 3:
            polygons.append(polygon)
            materials.append(index)
    return unique,polygons,materials


def mesh_part(name, src, record, copy_material):
    start,end,first,last = record["range"]
    origin = Vector(record["origin"])
    orientation = record.get("orientation")
    if orientation:
        basis = Matrix((orientation[:3],orientation[3:6],orientation[6:9])).transposed()
    else:
        basis = Matrix.Identity(3)
    inverse = basis.transposed()
    polygons = src.polygons[first:last]
    used = dict.fromkeys(poly.material_index for poly in polygons)
    slots = {index:i for i,index in enumerate(used)}
    mesh = populate(name,[inverse @ (v.co-origin) for v in src.vertices[start:end]],
                    [tuple(index-start for index in poly.vertices) for poly in polygons],
                    [slots[poly.material_index] for poly in polygons],
                    [copy_material(src.materials[i]) for i in used])
    transform = basis.to_4x4()
    transform.translation = origin
    return mesh,transform


class CBS_OT_bake(bpy.types.Operator):
    bl_idname = "cbs.bake"
    bl_label = "Bake Editable Meshes"
    bl_description = "Create an editable city in its own collection, with independent objects for each building and vehicle"
    bl_options = {"REGISTER","UNDO"}
    hide_live: BoolProperty(name="Hide Live Preview", default=True)
    independent_materials: BoolProperty(name="Copy Materials", description="Give the bake its own set of materials",default=True)

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and bool(context.scene.cbs.city) and editable(context.scene)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self,"hide_live")
        self.layout.prop(self,"independent_materials")

    def execute(self, context):
        if context.scene.cbs.live:
            update_now(context)
        live = child(context.scene.cbs.city,"Live City")
        sources = [(obj,obj.get(TAG)) for obj in live.objects if obj.get(TAG) in GROUPS] if live else []
        if not sources:
            self.report({"WARNING"},"Generate a preview before baking.")
            return {"CANCELLED"}

        baked = bpy.data.collections.new("Baked City")
        groups,materials = {},{}
        counts = {"Buildings":0,"Traffic":0}

        def copy_material(mat):
            if not self.independent_materials:
                return mat
            if mat not in materials:
                materials[mat] = mat.copy()
                materials[mat].name = mat.name+" • Baked"
            return materials[mat]

        try:
            for obj,role in sources:
                title = GROUPS[role]
                if title not in groups:
                    groups[title] = bpy.data.collections.new(title)
                    baked.children.link(groups[title])
                group = groups[title]
                src = obj.data
                parts = src.get(PARTS)
                if parts:
                    for i, record in enumerate(parts.values(),1):
                        prefix = "Building" if role == "Buildings" else "Vehicle"
                        name = f"{prefix} {i:04d}"
                        if role == "Buildings":
                            name += " • "+guide_labels[record["name"]]
                        mesh,local = mesh_part(name,src,record,copy_material)
                        item = bpy.data.objects.new(name,mesh)
                        item.matrix_world = obj.matrix_world @ local
                        group.objects.link(item)
                        counts[role] += 1
                else:
                    name = role+" Baked"
                    verts = [vertex.co.copy() for vertex in src.vertices]
                    faces = [tuple(poly.vertices) for poly in src.polygons]
                    indices = [poly.material_index for poly in src.polygons]
                    if role in {"Roads","Sidewalks","Markings"}:
                        verts,faces,indices = weld_surface(verts,faces,indices)
                    mesh = populate(name,verts,faces,indices,[copy_material(m) for m in src.materials])
                    item = bpy.data.objects.new(name,mesh)
                    item.matrix_world = obj.matrix_world
                    group.objects.link(item)
            context.scene.collection.children.link(baked)
        except Exception:
            for item in list(baked.all_objects):
                data = item.data
                bpy.data.objects.remove(item,do_unlink=True)
                if not data.users:
                    bpy.data.meshes.remove(data)
            for group in groups.values():
                bpy.data.collections.remove(group)
            bpy.data.collections.remove(baked)
            for mat in materials.values():
                if not mat.users:
                    bpy.data.materials.remove(mat)
            raise

        if self.hide_live:
            live.hide_viewport = live.hide_render = True
        self.report({"INFO"}, f"Baked {counts['Buildings']} buildings and {counts['Traffic']} vehicles into {baked.name}")
        return {"FINISHED"}
