
"""City Blockout Studio. Entry points, scene ownership and live preview."""
from functools import lru_cache
from math import ceil, hypot
from time import monotonic
import traceback

import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import interpolate_bezier

from . import demo, geometry, styles


ROAD_TYPES = (("STREET", "Local Street", "Two-way neighborhood street"),
              ("AVENUE", "Avenue", "Wider road with a double center line"))
PROFILES = tuple((key, *label) for key, label in styles.LABELS.items())
ROAD_PROFILES = (("INHERIT", "Use City Profile", "Inherit the city profile"),) + tuple(
    item for item in PROFILES if item[0] != "PARK")
GUIDE_TYPES = ROAD_TYPES + PROFILES
guide_labels = {key: label for key, label, _ in GUIDE_TYPES}
ROAD_KEYS = {key for key, _, _ in ROAD_TYPES}
ROLES = ("Road Guides", "District Guides", "Live City")
TAG = "cbs_role"
BUCKET = "cbs_bucket"
PARTS = "cbs_parts"
_cache = {}
_samples = {}
_networks = {}
_projections = {}
_terrain_changes = {}
_timer_running = False


def terrain_candidate(settings, obj):
    return obj.type == "MESH" and not obj.get(TAG)


class CBS_Guide(bpy.types.PropertyGroup):
    kind: EnumProperty(name="Type", items=GUIDE_TYPES)
    enabled: BoolProperty(name="Include Guide", default=True)
    priority: IntProperty(name="Priority", description="Higher values win where districts overlap", default=0, min=-100, max=100)
    density: FloatProperty(name="Density Multiplier", default=1., min=0., max=2.)
    height: FloatProperty(name="Height Multiplier", default=1., min=.1, max=4., soft_max=2.)
    custom_width: BoolProperty(name="Override Road Width")
    width: FloatProperty(name="Road Width", default=9., min=3., max=60., subtype="DISTANCE")
    left: EnumProperty(name="Left Frontage", items=ROAD_PROFILES)
    right: EnumProperty(name="Right Frontage", items=ROAD_PROFILES)


class CBS_Scene(bpy.types.PropertyGroup):
    city: PointerProperty(type=bpy.types.Collection, options={"HIDDEN"})
    live: BoolProperty(name="Live Preview", default=True)
    character: EnumProperty(name="City Profile", items=tuple(item for item in PROFILES if item[0] != "PARK"))
    density: FloatProperty(name="Building Density", default=.88, min=0., max=1., subtype="FACTOR")
    infill: FloatProperty(name="Block Infill", description="Develop interiors enclosed by roads, after placing street frontages",
                          default=0., min=0., max=1., subtype="FACTOR")
    seed: IntProperty(name="Seed", default=19, min=0)
    height: FloatProperty(name="Building Height", default=1., min=.15, max=4., soft_max=2.)
    street: FloatProperty(name="Local Street Width", default=7.8, min=3., max=38., subtype="DISTANCE")
    avenue: FloatProperty(name="Avenue Width", default=13.4, min=4., max=60., subtype="DISTANCE")
    setback: FloatProperty(name="Building Setback", default=.8, min=0., max=24., subtype="DISTANCE")
    snap_distance: FloatProperty(name="Sketch Snap Distance", default=7., min=0., max=60., subtype="DISTANCE")
    brush_radius: FloatProperty(name="District Brush Radius", default=22., min=3., max=200., subtype="DISTANCE")
    markings: BoolProperty(name="Lane Markings", default=True)
    street_fixtures: BoolProperty(name="Curbs & Streetlights", default=False)
    facades: BoolProperty(name="Facade Detail", description="Create windows and storefront details for closer views", default=False)
    parks: BoolProperty(name="Park Landscaping", default=True)
    trees: FloatProperty(name="Street Trees", default=.48, min=0., max=1., subtype="FACTOR")
    traffic: IntProperty(name="Static Traffic", description="Density of parked-in-place vehicles in travel lanes", default=25, min=0, max=100)
    terrain_mode: EnumProperty(name="Surface", items=(
        ("FLAT", "Flat Ground", "Generate an automatic city base at Z = 0"),
        ("TERRAIN", "Terrain (Experimental)", "Project the city onto an existing mesh from above in world space")))
    terrain: PointerProperty(name="Terrain Mesh", type=bpy.types.Object, poll=terrain_candidate)
    terrain_clearance: FloatProperty(name="Road Clearance",description="Raise roads, markings and traffic above the sampled surface",
                                     default=0.,min=0.,max=4.,soft_max=.6,subtype="DISTANCE")


def child(city, role):
    return next((collection for collection in city.children if collection.get(BUCKET) == role), None)


def editable(scene):
    city = scene.cbs.city
    return city is None or (city in scene.collection.children_recursive
                            and not city.library and city.users <= 2
                            and all((group := child(city,role)) is None or group.users == 1 for role in ROLES))


def create_city(scene):
    settings = scene.cbs
    if not settings.city:
        settings.city = bpy.data.collections.new("City Blockout Studio")
        scene.collection.children.link(settings.city)
    for role in ROLES:
        if child(settings.city, role) is None:
            collection = bpy.data.collections.new(role)
            collection[BUCKET] = role
            settings.city.children.link(collection)
    return settings.city


def sampled(obj, road):
    matrix = obj.matrix_world
    splines = []
    for i,spline in enumerate(obj.data.splines):
        kind = spline.type
        if kind not in {"POLY","BEZIER"}:
            continue
        closed = spline.use_cyclic_u
        points = spline.bezier_points if kind == "BEZIER" else spline.points
        if len(points) < 2:
            continue
        coords = tuple(tuple(p.co[:3]) for p in points)
        handles = tuple((tuple(p.handle_left),tuple(p.handle_right)) for p in points) if kind == "BEZIER" else ()
        splines.append((i,kind,closed,coords,handles))
    key = obj.as_pointer(),road
    signature = (tuple(tuple(row) for row in matrix),tuple(splines))
    cached = _samples.get(key)
    if cached and cached[0] == signature:
        return cached[1]

    result = []
    for i,kind,closed,points,handles in splines:
        coords = [matrix @ Vector(p) for p in points]
        run = [coords[0]]
        if kind == "BEZIER":
            handles = [(matrix @ Vector(left),matrix @ Vector(right)) for left,right in handles]
        for j in range(len(coords) if closed else len(coords)-1):
            k = (j+1) % len(coords)
            a, d = coords[j], coords[k]
            if kind == "BEZIER":
                b, c = handles[j][1],handles[k][0]
                n = max(5, min(300, ceil(((b-a).length+(c-b).length+(d-c).length)/3.4)))
                run.extend(interpolate_bezier(a,b,c,d,n+1)[1:])
            else:
                n = min(2000, max(1, ceil(hypot(d.x-a.x,d.y-a.y)/3.4))) if road else 1
                run.extend(a.lerp(d,t/n) for t in range(1,n+1))
        xy = []
        for p in run:
            point = float(p.x), float(p.y)
            if not xy or hypot(xy[-1][0]-point[0],xy[-1][1]-point[1]) > .001:
                xy.append(point)
        if closed and len(xy) > 1 and hypot(xy[-1][0]-xy[0][0],xy[-1][1]-xy[0][1]) <= .001:
            xy[-1] = xy[0]
        if len(xy) > 1:
            result.append((i,tuple(xy),closed))
    data = tuple(result)
    _samples[key] = signature,data
    return data


def snapshot(scene):
    settings = scene.cbs
    city = settings.city
    streets, districts = [], []
    active_guides = set()
    for role in ROLES[:2]:
        collection = child(city, role)
        if not collection:
            continue
        for obj in sorted(collection.objects, key=lambda item: item.name):
            if obj.type != "CURVE" or not obj.cbs_guide.enabled:
                continue
            guide = obj.cbs_guide
            kind = guide.kind
            if role == "Road Guides" and kind in ROAD_KEYS:
                active_guides.add((obj.as_pointer(),True))
                width = guide.width if guide.custom_width else (settings.avenue if kind == "AVENUE" else settings.street)
                for i, points, closed in sampled(obj, road=True):
                    streets.append((f"{obj.name}/{i}", points, width, kind == "AVENUE", guide.left, guide.right, closed))
            elif role == "District Guides" and kind not in ROAD_KEYS:
                active_guides.add((obj.as_pointer(),False))
                for _, points, closed in sampled(obj, road=False):
                    if closed and len(points) >= 4 and points[0] == points[-1]:
                        districts.append((points[:-1],kind,guide.priority,guide.density,guide.height))
    for key in _samples.keys()-active_guides:
        _samples.pop(key)
    terrain = settings.terrain if settings.terrain_mode == "TERRAIN" else None
    terrain_key = None
    if terrain and terrain.name in scene.objects and terrain.type == "MESH":
        terrain_key = (terrain.as_pointer(), _terrain_changes.get(terrain.as_pointer(),0),
                       tuple(tuple(row) for row in terrain.matrix_world))
    options = geometry.Options(settings.seed, settings.density, settings.height, settings.character, settings.traffic,
                               settings.setback, settings.parks, settings.markings, settings.trees, settings.infill,
                               settings.facades,settings.street_fixtures,
                               settings.terrain_clearance if terrain_key else 0.)
    return tuple(streets), tuple(districts), options, terrain_key


def project_terrain(obj, depsgraph):
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        matrix = evaluated.matrix_world
        vertices = [matrix @ v.co for v in mesh.vertices]
        faces = [tuple(p.vertices) for p in mesh.polygons]
        if not vertices or not faces:
            return None
        tree = BVHTree.FromPolygons(vertices, faces)
        ceiling = max(v.z for v in vertices) + 1.
    finally:
        evaluated.to_mesh_clear()
    @lru_cache(maxsize=65000)
    def elevation(x, y):
        hit, _, _, _ = tree.ray_cast((x,y,ceiling),(0,0,-1))
        return hit.z if hit is not None else None

    return elevation


def srgb(code):
    channels = [int(code[i:i+2],16)/255 for i in (0,2,4)]
    return tuple(c/12.92 if c <= .04045 else ((c+.055)/1.055)**2.4 for c in channels) + (1.,)


def material(name):
    mat = bpy.data.materials.get("City • " + name)
    if mat:
        return mat
    mat = bpy.data.materials.new("City • " + name)
    mat.diffuse_color = srgb(styles.PALETTE[name])
    mat.roughness = .79
    mat.use_nodes = True
    shader = mat.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = mat.diffuse_color
    shader.inputs["Roughness"].default_value = .4 if name in {"Glass","Car Window"} else .79
    return mat


def populate(name, vertices, faces, indices, materials):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    for mat in materials:
        mesh.materials.append(mat)
    mesh.polygons.foreach_set("material_index", indices)
    mesh.update()
    return mesh


def discard(obj, collection):
    collection.objects.unlink(obj)
    if not obj.users:
        old = obj.data
        bpy.data.objects.remove(obj)
        if old and not old.users:
            bpy.data.meshes.remove(old)


def replace_outputs(scene, pieces):
    collection = child(scene.cbs.city,"Live City")
    existing = {obj.get(TAG):obj for obj in collection.objects if obj.get(TAG) in pieces}
    prepared = {}
    try:
        for role, buffer in pieces.items():
            if not buffer.faces:
                continue
            colors = {name: i for i,name in enumerate(dict.fromkeys(buffer.colors))}
            prepared[role] = populate(role, buffer.vertices, buffer.faces,
                                      [colors[name] for name in buffer.colors],
                                      [material(name) for name in colors])
    except Exception:
        for mesh in prepared.values():
            bpy.data.meshes.remove(mesh)
        raise
    for role, mesh in prepared.items():
        obj = existing.pop(role, None)
        if obj and len(obj.users_collection) > 1:
            collection.objects.unlink(obj)
            obj = None
        if obj:
            old = obj.data
            obj.data = mesh
            if not old.users:
                bpy.data.meshes.remove(old)
        else:
            obj = bpy.data.objects.new(role,mesh)
            obj[TAG] = role
            obj.hide_select = True
            collection.objects.link(obj)
        if pieces[role].parts:
            obj.data[PARTS] = {str(i): {"name": name, "range": (v0,v1,f0,f1), "origin": origin,
                                       "orientation": orientation}
                               for i,(name,v0,v1,f0,f1,origin,orientation) in enumerate(pieces[role].parts)}
    for obj in existing.values():
        discard(obj, collection)


def dirty_layers(state, previous):
    if previous is None:
        return set(geometry.ROLES)
    roads,zones,options,terrain = state
    old_roads,old_zones,old,old_terrain = previous
    terrain_changed = terrain != old_terrain
    roads_changed = (roads != old_roads and
                     tuple(r[:4]+r[6:] for r in roads) != tuple(r[:4]+r[6:] for r in old_roads))
    layers = set()
    if roads_changed or terrain_changed:
        layers.update(geometry.STREET_LAYERS)
    elif options.terrain_clearance != old.terrain_clearance:
        layers.update(geometry.STREET_LAYERS)
    if options.markings != old.markings:
        layers.add("Markings")
    if options.fixtures != old.fixtures:
        layers.add("Street Fixtures")
    if (options.seed,options.traffic) != (old.seed,old.traffic):
        layers.add("Traffic")
    if (roads_changed or terrain_changed or options.setback != old.setback
            or tuple(z[0] for z in zones) != tuple(z[0] for z in old_zones)):
        layers.add("Ground")
    if (roads != old_roads or terrain_changed or zones != old_zones or
            options.development_key() != old.development_key()):
        layers.update(geometry.DEVELOPMENT)
    return layers


def street_network(scene, roads):
    key = scene.as_pointer()
    cached_roads,streets,index = _networks.get(key,(None,None,None))
    if cached_roads != roads:
        streets = tuple(geometry.Street(*r) for r in roads)
        index = geometry.index_streets(streets)
        _networks[key] = roads,streets,index
    return streets,index


def _generate(scene, depsgraph, state, previous):
    roads, zones, settings, terrain_key = state
    roles = dirty_layers(state,previous)
    if not roles:
        return
    key = scene.as_pointer()
    if terrain_key:
        cached_key,terrain = _projections.get(key,(None,None))
        if cached_key != terrain_key:
            terrain = project_terrain(scene.cbs.terrain,depsgraph)
            _projections[key] = terrain_key,terrain
    else:
        _projections.pop(key,None)
        terrain = None
    streets,index = street_network(scene,roads)
    pieces = geometry.build(streets,[geometry.Zone(*z) for z in zones],settings,terrain,roles,index)
    replace_outputs(scene, pieces)


def refresh(scene, depsgraph, immediate=True, force=False):
    """Compare only generator inputs, then update the preview when they settle."""
    if not scene.cbs.city or not editable(scene) or any(child(scene.cbs.city,k) is None for k in ROLES):
        return
    now = monotonic()
    key = scene.as_pointer()
    previous, pending, started, changed = _cache.get(key,(None,None,now,now))
    state = snapshot(scene)
    if state == previous and not force:
        _cache[key] = previous, None, now, now
        return
    if pending != state:
        started, changed = (now if pending is None else started), now
    if immediate or now-changed >= .085 or now-started >= .26:
        _generate(scene,depsgraph,state,None if force else previous)
        _cache[key] = state,None,now,now
    else:
        _cache[key] = previous,state,started,changed


def _tick():
    global _timer_running
    scene = bpy.context.scene
    if scene and scene.cbs.city and scene.cbs.live and not _timer_running:
        _timer_running = True
        try:
            refresh(scene,bpy.context.evaluated_depsgraph_get(),immediate=False)
        except Exception:
            traceback.print_exc()
            return .75
        finally:
            _timer_running = False
    return .085


@persistent
def depsgraph_changed(scene, depsgraph):
    terrain = scene.cbs.terrain if scene.cbs.terrain_mode == "TERRAIN" else None
    if terrain:
        for update in depsgraph.updates:
            if (update.id == terrain.data or
                    update.id == terrain and (update.is_updated_geometry or update.is_updated_transform)):
                key = terrain.as_pointer()
                _terrain_changes[key] = _terrain_changes.get(key,0)+1
                break


@persistent
def clear_cache(_dummy):
    _cache.clear()
    _samples.clear()
    _networks.clear()
    _projections.clear()
    geometry.block_sites.cache_clear()
    _terrain_changes.clear()


@persistent
def before_save(_dummy):
    scene = bpy.context.scene
    if scene and scene.cbs.city and scene.cbs.live:
        refresh(scene,bpy.context.evaluated_depsgraph_get())


def update_now(context, force=False):
    context.view_layer.update()
    refresh(context.scene,context.evaluated_depsgraph_get(),force=force)


def add_spline(curve, coords, closed=False, smooth=False):
    spline = curve.splines.new("BEZIER" if smooth else "POLY")
    points = spline.bezier_points if smooth else spline.points
    points.add(len(coords)-1)
    for p,(x,y) in zip(points,coords):
        p.co = (x,y,0.) if smooth else (x,y,0.,1.)
        if smooth:
            p.handle_left_type = p.handle_right_type = "AUTO"
    spline.use_cyclic_u = closed
    return spline


def add_curve(collection, name, coords, kind, closed=False, position=(0.,0.), smooth=False):
    curve = bpy.data.curves.new(name,"CURVE")
    curve.dimensions = "3D"
    add_spline(curve,coords,closed,smooth)
    obj = bpy.data.objects.new(name,curve)
    obj.hide_render = True
    obj.show_in_front = True
    obj.location = (position[0],position[1],.17)
    collection.objects.link(obj)
    obj.cbs_guide.kind = kind
    return obj


def activate(context, obj):
    for old in context.selected_objects:
        old.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj


from . import bake, interface, sketch

CLASSES = (CBS_Guide,CBS_Scene,sketch.CBS_OT_sketch,bake.CBS_OT_bake,*interface.CLASSES)
HANDLERS = ((bpy.app.handlers.depsgraph_update_post,depsgraph_changed),
            (bpy.app.handlers.load_post,clear_cache), (bpy.app.handlers.undo_post,clear_cache),
            (bpy.app.handlers.redo_post,clear_cache),(bpy.app.handlers.save_pre,before_save))


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Object.cbs_guide = PointerProperty(type=CBS_Guide)
    bpy.types.Scene.cbs = PointerProperty(type=CBS_Scene)
    for handlers, fn in HANDLERS:
        handlers.append(fn)
    bpy.app.timers.register(_tick,first_interval=.085,persistent=True)


def unregister():
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    for handlers, fn in HANDLERS:
        handlers.remove(fn)
    del bpy.types.Scene.cbs
    del bpy.types.Object.cbs_guide
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    clear_cache(None)
