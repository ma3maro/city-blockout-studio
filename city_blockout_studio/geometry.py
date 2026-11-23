
"""Street ribbons, parcel placement and lightweight blockout meshes."""
from bisect import bisect_right
from collections import defaultdict, deque
from dataclasses import dataclass
from functools import lru_cache
from math import ceil, cos, floor, hypot, pi, sin, sqrt
from random import Random
from zlib import crc32

from mathutils import Vector

from .styles import FORMS, choose, massing


class Mesh:
    def __init__(self):
        self.vertices = []
        self.faces = []
        self.colors = []
        self.parts = []

    def face(self, points, color):
        start = len(self.vertices)
        self.vertices.extend(points)
        self.faces.append(tuple(range(start, len(self.vertices))))
        self.colors.append(color)

    def prism(self, outline, z, height, wall, top):
        start = len(self.vertices)
        count = len(outline)
        self.vertices.extend((x, y, level) for level in (z, z + height) for x, y in outline)
        bottom = tuple(range(start, start + count))
        upper = tuple(i + count for i in bottom)
        self.faces.extend((bottom[::-1], upper))
        self.colors.extend((wall, top))
        for i, a in enumerate(bottom):
            j = (i + 1) % count
            self.faces.append((a, bottom[j], upper[j], upper[i]))
            self.colors.append(wall)

    def box(self, x, y, w, d, z, height, wall, top=None):
        self.prism(tuple((x + a*w/2, y + b*d/2) for a, b in CORNERS), z, height, wall, top or wall)

    def chamfered(self, w, d, z, height, color, top="Cap"):
        a, b = w / 2, d / 2
        outline = ((-.73*a,-b),(.73*a,-b),(a,-.73*b),(a,.73*b),
                   (.73*a,b),(-.73*a,b),(-a,.73*b),(-a,-.73*b))
        self.prism(outline, z, height, color, top)

    def gable(self, w, d, z, h, wall, roof):
        a, b, c, e = [(w*x/2, d*y/2, z) for x, y in CORNERS]
        r, s = (-w/2, 0, z+h), (w/2, 0, z+h)
        for pts, color in (((a,b,s,r),roof), ((r,s,c,e),roof), ((b,c,s),wall), ((e,a,r),wall)):
            self.face(pts, color)

    def add(self, other, origin, angle=(1., 0.), name=None, basis=None):
        v0, f0 = len(self.vertices), len(self.faces)
        dx, dy = angle
        x, y, z = origin
        if basis is None:
            self.vertices.extend((x+a*dx-b*dy,y+a*dy+b*dx,z+c) for a,b,c in other.vertices)
            basis = ((dx,dy,0.),(-dy,dx,0.),(0.,0.,1.))
        else:
            forward,side,up = basis
            self.vertices.extend((x+a*forward[0]+b*side[0]+c*up[0],
                                  y+a*forward[1]+b*side[1]+c*up[1],
                                  z+a*forward[2]+b*side[2]+c*up[2]) for a,b,c in other.vertices)
        self.faces.extend(tuple(v0 + i for i in face) for face in other.faces)
        self.colors.extend(other.colors)
        if name:
            self.parts.append((name,v0,len(self.vertices),f0,len(self.faces),origin,
                               tuple(co for axis in basis for co in axis)))


CORNERS = ((-1, -1), (1, -1), (1, 1), (-1, 1))
ROLES = ("Ground","Sidewalks","Roads","Markings","Street Fixtures","Buildings","Open Space","Traffic")
DEVELOPMENT = frozenset(("Buildings", "Open Space"))
STREET_LAYERS = frozenset(("Sidewalks","Roads","Markings","Street Fixtures","Traffic"))


@dataclass(frozen=True)
class Options:
    seed: int
    density: float
    height: float
    profile: str
    traffic: int
    setback: float
    parks: bool
    markings: bool
    planting: float
    infill: float
    facades: bool
    fixtures: bool
    terrain_clearance: float

    def development_key(self):
        return (self.seed,self.density,self.height,self.profile,self.setback,self.parks,
                self.planting,self.infill,self.facades)


@dataclass
class Zone:
    points: tuple
    profile: str
    priority: int
    density: float
    height: float

    def __post_init__(self):
        self.edges = tuple(zip(self.points, self.points[1:] + self.points[:1]))
        xs, ys = zip(*self.points)
        self.bounds = min(xs), min(ys), max(xs), max(ys)

    def contains(self, x, y):
        l, b, r, t = self.bounds
        if not (l <= x <= r and b <= y <= t):
            return False
        return sum((a[1] > y) != (b[1] > y) and x < a[0] + (b[0]-a[0]) * (y-a[1]) / (b[1]-a[1])
                   for a, b in self.edges) % 2

    def touches(self, x, y, radius):
        l, b, r, t = self.bounds
        return (l-radius <= x <= r+radius and b-radius <= y <= t+radius and
                (self.contains(x, y) or any(distance_sq(x, y, a, b) <= radius**2 for a, b in self.edges)))


class Street:
    def __init__(self, name, points, width, avenue, left, right, closed):
        self.name, self.points, self.width = name, points, width
        self.avenue, self.left, self.right, self.closed = avenue, left, right, closed
        self.walk = 2.05 if avenue else 1.35
        self.lengths = [0.]
        self.tangents = []
        for a, b in zip(points, points[1:]):
            x, y = b[0]-a[0], b[1]-a[1]
            length = hypot(x, y)
            self.tangents.append((x/length, y/length))
            self.lengths.append(self.lengths[-1] + length)
        self.length = self.lengths[-1]

    def at(self, distance):
        i = min(bisect_right(self.lengths, distance) - 1, len(self.tangents) - 1)
        x, y = self.points[i]
        dx, dy = self.tangents[i]
        return x + dx*(distance-self.lengths[i]), y + dy*(distance-self.lengths[i]), dx, dy

    def normals(self):
        for i in range(len(self.points)):
            before = self.tangents[(i-1) % len(self.tangents)] if self.closed or i else self.tangents[0]
            after = self.tangents[i % len(self.tangents)] if self.closed or i < len(self.tangents) else before
            a, b = before
            c, d = after
            length = hypot(a+c, b+d)
            if length < .25:
                yield -d, c
            else:
                u, v = -(b+d)/length, (a+c)/length
                miter = 1 / max(.71, -d*u+c*v)
                yield u*miter, v*miter


class SpatialIndex:
    CELL = 20

    def __init__(self):
        self.cells = defaultdict(list)

    def cells_for(self, x0, y0, x1, y1):
        for i in range(floor(x0/self.CELL),floor(x1/self.CELL)+1):
            for j in range(floor(y0/self.CELL),floor(y1/self.CELL)+1):
                yield i, j

    def add(self, box, item):
        for cell in self.cells_for(*box):
            self.cells[cell].append(item)

    def near(self, x, y, radius):
        seen = set()
        for cell in self.cells_for(x-radius, y-radius, x+radius, y+radius):
            for item in self.cells.get(cell, ()):
                marker = id(item)
                if marker not in seen:
                    seen.add(marker)
                    yield item


def distance_sq(x, y, a, b):
    dx, dy = b[0]-a[0], b[1]-a[1]
    denom = dx*dx + dy*dy
    t = min(1., max(0., ((x-a[0])*dx+(y-a[1])*dy)/denom)) if denom else 0.
    return (x-a[0]-t*dx)**2 + (y-a[1]-t*dy)**2


def nearest_street(index, x, y, radius):
    size = index.CELL
    base_x,base_y = floor(x/size),floor(y/size)
    best,nearest,seen = radius*radius,None,set()
    for ring in range(ceil(radius/size)+1):
        for i in range(-ring,ring+1):
            for j in range(-ring,ring+1):
                if max(abs(i),abs(j)) != ring:
                    continue
                for record in index.cells.get((base_x+i,base_y+j),()):
                    marker = id(record)
                    if marker in seen:
                        continue
                    seen.add(marker)
                    a,b,_,street,_ = record
                    distance = distance_sq(x,y,a,b)
                    if distance < best:
                        length = hypot(b[0]-a[0],b[1]-a[1])
                        nearest = a,b,street,((b[0]-a[0])/length,(b[1]-a[1])/length)
                        best = distance
        if best <= (ring*size)**2:
            break
    return nearest


def world_quad(x, y, dx, dy, w, d):
    return [(x+a*w/2*dx-b*d/2*dy, y+a*w/2*dy+b*d/2*dx) for a, b in CORNERS]


def surface(mesh, points, color, z, elevation):
    heights = [elevation(x, y) for x, y in points]
    if any(h is None for h in heights):
        return
    mesh.face([(x,y,h+z) for (x,y), h in zip(points, heights)], color)


def strip(mesh, street, radius, color, z, elevation, drape):
    def emit(a, b, c, d):
        if drape:
            count = ceil(radius * 2 / 3)
            for i in range(count):
                lower, upper = i/count, (i+1)/count
                def lerp(p, q, t):
                    return p[0] + (q[0]-p[0])*t, p[1] + (q[1]-p[1])*t
                surface(mesh, (lerp(a,b,lower),lerp(c,d,lower),lerp(c,d,upper),lerp(a,b,upper)),
                        color, z, elevation)
        else:
            surface(mesh, (a,c,d,b), color, z, elevation)

    edges = [((x-nx*radius,y-ny*radius),(x+nx*radius,y+ny*radius))
             for (x,y), (nx,ny) in zip(street.points, street.normals())]
    joins = []
    for i, ((a,b),(c,d)) in enumerate(zip(edges, edges[1:])):
        dx, dy = street.tangents[i]
        if (c[0]-a[0])*dx+(c[1]-a[1])*dy <= 0 or (d[0]-b[0])*dx+(d[1]-b[1])*dy <= 0:
            p, q = street.points[i:i+2]
            a, b = (p[0]+dy*radius,p[1]-dx*radius), (p[0]-dy*radius,p[1]+dx*radius)
            c, d = (q[0]+dy*radius,q[1]-dx*radius), (q[0]-dy*radius,q[1]+dx*radius)
        emit(a,b,c,d)
        joins.append(((a,b),(c,d)))
    for i in range(0 if street.closed else 1, len(joins)):
        point = street.points[i]
        for before,after in zip(joins[i-1][1],joins[i][0]):
            cross = (before[0]-point[0])*(after[1]-point[1]) - (before[1]-point[1])*(after[0]-point[0])
            if abs(cross) > .0001:
                verts = (point,before,after) if cross > 0 else (point,after,before)
                surface(mesh,verts,color,z,elevation)


def circles_overlap(index, x, y, radius):
    return any((x-a)**2+(y-b)**2 < (radius+r)**2 for a,b,r in index.near(x,y,radius))


def put_circle(index, x, y, radius):
    index.add((x-radius,y-radius,x+radius,y+radius), (x,y,radius))


class Lots:
    def __init__(self):
        self.index = SpatialIndex()

    def overlaps(self, x, y, dx, dy, u, v):
        for a,b,s,t,p,q in self.index.near(x,y,hypot(u,v)):
            ex,ey = a-x,b-y
            aligned,cross = abs(dx*s+dy*t),abs(dx*t-dy*s)
            if (abs(ex*dx+ey*dy) < u+p*aligned+q*cross
                    and abs(ey*dx-ex*dy) < v+p*cross+q*aligned
                    and abs(ex*s+ey*t) < p+u*aligned+v*cross
                    and abs(ey*s-ex*t) < q+u*cross+v*aligned):
                return True
        return False

    def put(self, x, y, dx, dy, u, v):
        rx,ry = abs(dx)*u+abs(dy)*v,abs(dy)*u+abs(dx)*v
        self.index.add((x-rx,y-ry,x+rx,y+ry),(x,y,dx,dy,u,v))


def street_obstruction(index, x, y, radius, own=None, along=0.):
    return any((p is not own or abs(along-d) > 25 and (not p.closed or p.length-abs(along-d) > 25))
               and distance_sq(x,y,a,b) < (r+radius)**2
               for a,b,r,p,d in index.near(x,y,radius))


def junctions(street, index):
    """Find explicit center-line intersections, including T junctions."""
    found = []
    for i,(a,b) in enumerate(zip(street.points,street.points[1:])):
        dx,dy = b[0]-a[0],b[1]-a[1]
        length = hypot(dx,dy)
        for c,d,_,other,_ in index.near((a[0]+b[0])/2,(a[1]+b[1])/2,length/2):
            if other is street:
                continue
            ux,uy = d[0]-c[0],d[1]-c[1]
            det = dx*uy-dy*ux
            if abs(det) < length*hypot(ux,uy)*.29:
                continue
            ox,oy = c[0]-a[0],c[1]-a[1]
            t,v = (ox*uy-oy*ux)/det,(ox*dy-oy*dx)/det
            if -.0001 <= t <= 1.0001 and -.0001 <= v <= 1.0001:
                along = street.lengths[i]+t*length
                clearance = ((other.width/2 + other.walk)*1.07 + 1.25)*length*hypot(ux,uy)/abs(det)
                if all(abs(old-along) > 3.5 for old,_ in found):
                    found.append((along,clearance))
    return found


def crosswalks(mesh, street, index, z, elevation):
    for position, clearance in junctions(street,index):
        for direction in (-1,1):
            along = position + direction*clearance
            if not 2 < along < street.length-2:
                continue
            x,y,dx,dy = street.at(along)
            if street_obstruction(index,x,y,.25,street,along):
                continue
            for offset in range(-int(street.width/2)+1,int(street.width/2)):
                quad = world_quad(x-dy*offset,y+dx*offset,dx,dy,2.65,.38)
                surface(mesh,quad,"Crossing",z,elevation)


def parcel_blocked(index, x, y, dx, dy, w, depth):
    h, k = w/2+.44, depth/2+.44
    for a,b,r,_,_ in index.near(x,y,hypot(h,k)+1.):
        sx, sy = (a[0]+b[0])/2-x, (a[1]+b[1])/2-y
        tx, ty = (b[0]-a[0])/2, (b[1]-a[1])/2
        s, t = sx*dx+sy*dy, sy*dx-sx*dy
        u, v = tx*dx+ty*dy, ty*dx-tx*dy
        if (abs(s) < h+r+abs(u) and abs(t) < k+r+abs(v)
                and abs(s*v-t*u) < (h+r)*abs(v)+(k+r)*abs(u)):
            return True
    return False


def crown_mesh():
    mesh = Mesh()
    mesh.box(0, 0, .36, .36, 0, 2.1, "Bark")
    rings = [(1.05,1.35),(1.7,2.35),(1.03,3.55),(.23,4.07)]
    outlines = [[(r*cos(i*2*pi/7), r*sin(i*2*pi/7), z) for i in range(7)] for r,z in rings]
    mesh.face(outlines[0][::-1],"Leaf")
    for rank, (lower, upper) in enumerate(zip(outlines,outlines[1:])):
        for i in range(7):
            j = (i+1)%7
            mesh.face((lower[i],lower[j],upper[j],upper[i]), "Leaf Light" if (i+rank)%3 == 0 else "Leaf")
    mesh.face(outlines[-1], "Leaf Light")
    return mesh


def city_bounds(streets, zones):
    coordinates = [p for road in streets for p in road.points] + [p for zone in zones for p in zone.points]
    if not coordinates:
        return -80., -80., 80., 80.
    xs, ys = zip(*coordinates)
    return min(xs)-25, min(ys)-25, max(xs)+25, max(ys)+25


def index_streets(streets):
    street_index = SpatialIndex()
    for street in streets:
        padding = (street.width/2+street.walk)*1.07
        for i, (a, b) in enumerate(zip(street.points, street.points[1:])):
            street_index.add((min(a[0],b[0])-padding,min(a[1],b[1])-padding,
                              max(a[0],b[0])+padding,max(a[1],b[1])+padding),
                             (a,b,padding,street,street.lengths[i]))
    return street_index


@lru_cache(maxsize=12)
def vehicle_mesh(paint, variant):
    mesh = Mesh()
    width = 1.84
    mesh.chamfered(4.24,width,.18,.53,paint,paint)
    if variant == 0:
        mesh.chamfered(2.04,width*.84,.71,.52,"Car Window","Car Window")
        mesh.box(0,0,1.15,width*.77,1.23,.035,paint)
    else:
        mesh.chamfered(2.75,width*.89,.71,.73,"Car Window","Car Window")
        mesh.box(-.20,0,1.9,width*.83,1.44,.035,paint)
    mesh.box(2.045,0,.15,width*.76,.46,.13,"Car Light")
    mesh.box(-2.07,0,.12,width*.76,.43,.10,"Car Tail")
    for x in (-1.35,1.35):
        for y in (-.84,.84):
            outer = [(x+.285*cos(i*pi/4),y+(.106 if y > 0 else -.106),.285+.285*sin(i*pi/4)) for i in range(8)]
            inner = [(a,2*y-b,c) for a,b,c in outer]
            rings = (outer,inner) if y > 0 else (inner,outer)
            mesh.face(rings[0][::-1],"Rubber")
            mesh.face(rings[1],"Rubber")
            for i in range(8):
                j = (i+1)%8
                mesh.face((rings[0][i],rings[0][j],rings[1][j],rings[1][i]),"Rubber")
    return mesh


def terrain_basis(elevation, x, y, heading):
    dx,dy = heading
    front,back = elevation(x+1.35*dx,y+1.35*dy),elevation(x-1.35*dx,y-1.35*dy)
    left,right = elevation(x-.9*dy,y+.9*dx),elevation(x+.9*dy,y-.9*dx)
    if None in (front,back,left,right):
        return None
    forward = Vector((dx,dy,(front-back)/2.7)).normalized()
    lateral = Vector((-dy,dx,(left-right)/1.8))
    up = forward.cross(lateral).normalized()
    return tuple(forward),tuple(up.cross(forward)),tuple(up)


@lru_cache(maxsize=1)
def lamp_mesh():
    mesh = Mesh()
    mesh.box(0,0,.35,.38,0,.34,"Pole")
    pole = [(.096*cos(i*pi/3),.096*sin(i*pi/3)) for i in range(6)]
    mesh.prism(pole,.33,4.48,"Pole","Pole")
    mesh.box(0,-.39,.13,.84,4.69,.11,"Pole")
    mesh.box(0,-.83,.36,.41,4.59,.19,"Pole","Light Shade")
    return mesh


def roadside_details(mesh,street,index,z,elevation):
    radius = street.width/2+.04
    normals = list(street.normals())
    for side in (-1,1):
        rings = [((x+nx*radius*side,y+ny*radius*side),
                  (x+nx*(radius+.19)*side,y+ny*(radius+.19)*side))
                 for (x,y),(nx,ny) in zip(street.points,normals)]
        for i,((a,b),(c,d)) in enumerate(zip(rings,rings[1:])):
            x,y = (a[0]+c[0])/2,(a[1]+c[1])/2
            distance = (street.lengths[i]+street.lengths[i+1])/2
            if street_obstruction(index,x,y,.35,street,distance):
                continue
            pts = [a,c,d,b] if side > 0 else [a,b,d,c]
            surface(mesh,pts,"Curb",z+.115,elevation)
            ha,hc = elevation(*a),elevation(*c)
            if ha is not None and hc is not None:
                edge = [(*a,ha+z-.025),(*c,hc+z-.025),(*c,hc+z+.115),(*a,ha+z+.115)]
                mesh.face(edge if side > 0 else edge[::-1],"Curb")
        count = 23 if street.avenue else 33
        for distance in range(11+(count//2 if side < 0 else 0),int(street.length-8),count):
            x,y,dx,dy = street.at(distance)
            offset = side*(radius+street.walk*.65)
            x,y = x-dy*offset,y+dx*offset
            if street_obstruction(index,x,y,1.2,street,distance):
                continue
            height = elevation(x,y)
            if height is not None:
                mesh.add(lamp_mesh(),(x,y,height+.064),(dx*side,dy*side))


@lru_cache(maxsize=3)
def block_sites(streets):
    """Flood from the boundary of a road mask to identify enclosed city blocks."""
    if not streets:
        return ()
    left,bottom,right,top = city_bounds(streets,())
    resolution = max(5,ceil(sqrt((right-left)*(top-bottom)/85000)),
                     ceil(max(right-left,top-bottom)/460))
    x0,y0 = floor(left/resolution)*resolution,floor(bottom/resolution)*resolution
    cols,rows = ceil((right-x0)/resolution)+1,ceil((top-y0)/resolution)+1
    mask = bytearray(cols*rows)
    for street in streets:
        radius = street.width/2+street.walk+resolution*.64
        radius_sq = radius*radius
        start,end = street.points[0],street.points[-1]
        sx,sy = street.tangents[0]
        ex,ey = street.tangents[-1]
        for i,(a,b) in enumerate(zip(street.points,street.points[1:])):
            clip_start = not street.closed and street.lengths[i] <= radius
            clip_end = not street.closed and street.length-street.lengths[i+1] <= radius
            u0 = max(0,ceil((min(a[0],b[0])-radius-x0)/resolution))
            u1 = min(cols-1,floor((max(a[0],b[0])+radius-x0)/resolution))
            v0 = max(0,ceil((min(a[1],b[1])-radius-y0)/resolution))
            v1 = min(rows-1,floor((max(a[1],b[1])+radius-y0)/resolution))
            for v in range(v0,v1+1):
                yy = y0+v*resolution
                for u in range(u0,u1+1):
                    index = v*cols+u
                    if mask[index]:
                        continue
                    xx = x0+u*resolution
                    if (clip_start and (xx-start[0])*sx+(yy-start[1])*sy < -.001 or
                            clip_end and (xx-end[0])*ex+(yy-end[1])*ey > .001):
                        continue
                    if distance_sq(xx,yy,a,b) <= radius_sq:
                        mask[index] = 1

    queue = deque()

    def visit(index):
        if mask[index] == 0:
            mask[index] = 2
            queue.append(index)

    for u in range(cols):
        visit(u)
        visit((rows-1)*cols+u)
    for v in range(rows):
        visit(v*cols)
        visit(v*cols+cols-1)
    while queue:
        i = queue.popleft()
        column = i%cols
        if column > 0:
            visit(i-1)
        if column < cols-1:
            visit(i+1)
        if i >= cols:
            visit(i-cols)
        if i+cols < len(mask):
            visit(i+cols)

    spacing = max(1,ceil(15/resolution))
    return tuple((x0+u*resolution,y0+v*resolution) for v in range(1,rows-1,spacing)
                 for u in range(1,cols-1,spacing) if not mask[v*cols+u])


def street_layers(result, streets, street_index, options, elevation, drape):
    cars = SpatialIndex()
    traffic, seed = options.traffic, options.seed
    for index, street in enumerate(streets):
        z = .09 + (.022 if street.avenue else 0) + min(.009, index*.00003)
        radius = street.width/2
        if "Sidewalks" in result:
            strip(result["Sidewalks"], street, radius+street.walk, "Paving", .056+min(.012,index*.00003), elevation, drape)
        if "Roads" in result:
            strip(result["Roads"], street, radius, "Avenue" if street.avenue else "Street", z, elevation, drape)
        if "Street Fixtures" in result and options.fixtures:
            roadside_details(result["Street Fixtures"],street,street_index,z,elevation)
        if "Markings" in result and options.markings:
            if street.avenue:
                crosswalks(result["Markings"],street,street_index,z+.012,elevation)
            step = 11 if street.avenue else 14
            for s in range(9, int(street.length-5), step):
                x,y,dx,dy = street.at(s)
                if not street_obstruction(street_index,x,y,3.2,street,s):
                    if street.avenue:
                        for offset in (-.19, .19):
                            points = world_quad(x-dy*offset,y+dx*offset,dx,dy,4.3,.13)
                            surface(result["Markings"],points,"Lane",z+.010,elevation)
                    else:
                        surface(result["Markings"],world_quad(x,y,dx,dy,2.7,.12),"Crossing",z+.010,elevation)
        if "Traffic" in result and traffic and street.width >= 5:
            rng = Random(seed + crc32(street.name.encode()) + 377)
            step = max(9, round(36 / max(.2, traffic/28)))
            for s in range(rng.randrange(6, step), int(street.length-5), step):
                for side in (-1,1):
                    if rng.random() > min(.86, traffic/45):
                        continue
                    distance = min(street.length-3, max(3, s+rng.uniform(-2,2)))
                    x,y,dx,dy = street.at(distance)
                    x,y = x-dy*side*radius*.53,y+dx*side*radius*.53
                    h = elevation(x,y)
                    if h is None or street_obstruction(street_index,x,y,2.,street,distance) or circles_overlap(cars,x,y,2.5):
                        continue
                    heading = -dx*side,-dy*side
                    basis = terrain_basis(elevation,x,y,heading) if drape else None
                    if drape and basis is None:
                        continue
                    paint = rng.choice(("Car Coral","Car Cream","Car Blue","Car Yellow"))
                    car = vehicle_mesh(paint,int(distance)%4 == 0)
                    result["Traffic"].add(car,(x,y,h+z+.02),heading,"Vehicle",basis=basis)
                    put_circle(cars,x,y,2.5)


def develop(result, streets, zones, street_index, options, bounds, elevation):
    seed, density, height_scale = options.seed, options.density, options.height
    profile, setbacks, planting = options.profile, options.setback, options.planting
    zones = sorted(zones, key=lambda zone: -zone.priority)
    reserves = [zone for zone in zones if zone.profile in {"PARK", "EMPTY"}]
    vacancies = [zone for zone in reserves if zone.profile == "EMPTY"]
    typed = [zone for zone in zones if zone.profile not in {"PARK","EMPTY"}]
    left, bottom, right, top = bounds
    occupied = Lots()
    tree = crown_mesh()
    if options.parks:
        for zone in reserves:
            if zone.profile != "PARK":
                continue
            l,b,r,t = zone.bounds
            step = max(4, ceil(sqrt(max(1.,(r-l)*(t-b))/2100)))
            for x in range(floor(l/step)*step,ceil(r),step):
                for y in range(floor(b/step)*step,ceil(t),step):
                    quad = [(x,y),(x+step,y),(x+step,y+step),(x,y+step)]
                    cx,cy = x+step/2,y+step/2
                    if all(zone.contains(a,b) for a,b in quad) and not any(v.touches(cx,cy,step*.71) for v in vacancies):
                        surface(result["Open Space"],quad,"Lawn",.027,elevation)
            step = max(9, ceil(sqrt(max(1.,(r-l)*(t-b))/650)))
            rng = Random(seed ^ 961)
            for x in range(floor(l/step)*step,ceil(r),step):
                for y in range(floor(b/step)*step,ceil(t),step):
                    a,c = x+rng.uniform(0,step),y+rng.uniform(0,step)
                    h = elevation(a,c)
                    if (h is not None and zone.contains(a,c) and not any(v.touches(a,c,2) for v in vacancies)
                            and not street_obstruction(street_index,a,c,2) and not occupied.overlaps(a,c,1,0,2,2)):
                        result["Open Space"].add(tree,(a,c,h+.025))
                        occupied.put(a,c,1,0,2,2)

    focus_x, focus_y = (left+right)/2, (bottom+top)/2
    scale = max(65, hypot(right-left,top-bottom)*.47)

    def parcel(x,y,override,coverage,rng):
        zone = next((z for z in typed if z.contains(x,y)),None)
        land_use = zone.profile if zone else (override if override != "INHERIT" else profile)
        lot_density = density*coverage*(zone.density if zone else 1.)
        if land_use == "QUIET":
            lot_density *= .62
        elif land_use == "BUSY":
            lot_density *= 1.24
        if rng.random() >= lot_density:
            return None
        kind = choose(land_use,hypot(x-focus_x,y-focus_y)/scale,rng)
        if not kind:
            return None
        form = FORMS[kind]
        w,d = rng.uniform(*form.width),rng.uniform(*form.depth)
        return kind,w,d,zone,land_use

    def place(x,y,heading,site,rng):
        kind,w,d,zone,land_use = site
        dx,dy = heading
        footprint = hypot(w,d)/2
        margin = 1.7 if land_use == "QUIET" else .6
        u,v = w/2+margin,d/2+margin
        if (any(z.touches(x,y,footprint+.35) for z in reserves)
                or parcel_blocked(street_index,x,y,dx,dy,w,d)
                or occupied.overlaps(x,y,dx,dy,u,v)):
            return
        low = high = 0.
        if elevation is not flat_elevation:
            points = world_quad(x,y,dx,dy,w,d)
            midpoints = [((a+c)*.5,(b+e)*.5) for (a,b),(c,e) in zip(points,points[1:]+points[:1])]
            heights = [elevation(px,py) for px,py in [*points,*midpoints,(x,y)]]
            if any(h is None for h in heights):
                return
            low,high = min(heights),max(heights)
        local = Mesh()
        if high-low > .12:
            local.box(0,0,w,d,low-high-.08,high-low+.09,"Stone")
        height = rng.uniform(*FORMS[kind].height)*height_scale*(zone.height if zone else 1.)
        massing(local,kind,w,d,height,rng,details=options.facades)
        result["Buildings"].add(local,(x,y,high+.045),heading,kind)
        occupied.put(x,y,dx,dy,u,v)

    for street in streets:
        stream = seed * 173 + crc32(street.name.encode())
        for s in range(9, int(street.length-5), 9):
            for side, override in ((1,street.left),(-1,street.right)):
                rng = Random(stream+s*7171+side*73)
                x,y,dx,dy = street.at(s+rng.uniform(-1.1,1.1))
                offset = street.width/2 + street.walk + setbacks + 2.5
                gx,gy = x-dy*side*(offset+5),y+dx*side*(offset+5)
                site = parcel(gx,gy,override,1.,rng)
                if not site:
                    continue
                distance = offset+site[2]/2
                a,b = x-dy*side*distance,y+dx*side*distance
                # The frontage is local -Y. Flip the tangent on the opposite bank.
                place(a,b,(dx*side,dy*side),site,rng)

    if options.infill > 0 and density > 0:
        for a,b in block_sites(streets):
            rng = Random(seed*173+crc32(f"{a},{b}".encode())+2199)
            x,y = a+rng.uniform(-1.7,1.7),b+rng.uniform(-1.7,1.7)
            nearest = nearest_street(street_index,x,y,140)
            side = 1
            heading = (1.,0.)
            override = "INHERIT"
            if nearest:
                start,_,street,(dx,dy) = nearest
                side = 1 if dx*(y-start[1])-dy*(x-start[0]) >= 0 else -1
                heading = dx*side,dy*side
                override = street.left if side > 0 else street.right
            site = parcel(x,y,override,options.infill,rng)
            if site:
                place(x,y,heading,site,rng)

    if planting and profile != "EMPTY":
        for street in streets:
            rng = Random(seed+crc32(street.name.encode())+3919)
            for along in range(15,int(street.length-12),21 if street.avenue else 29):
                x,y,dx,dy = street.at(along+rng.uniform(-1.2,1.2))
                for side in (-1,1):
                    if rng.random() >= planting:
                        continue
                    offset = side*(street.width/2+street.walk+1.1)
                    a,b = x-dy*offset,y+dx*offset
                    if (any(zone.touches(a,b,1.7) for zone in reserves)
                            or street_obstruction(street_index,a,b,1.3,street,along)
                            or occupied.overlaps(a,b,1,0,1.55,1.55)):
                        continue
                    h = elevation(a,b)
                    if h is not None:
                        result["Open Space"].add(tree,(a,b,h+.025))
                        occupied.put(a,b,1,0,1.55,1.55)


def flat_elevation(x, y):
    return 0.


def build(streets, zones, options, elevation, roles, street_index):
    result = {role: Mesh() for role in ROLES if role in roles}
    drape = elevation is not None
    elevation = elevation or flat_elevation
    bounds = city_bounds(streets, zones) if "Ground" in roles or DEVELOPMENT <= roles else None
    if "Ground" in roles and not drape:
        left, bottom, right, top = bounds
        if streets:
            depth = max(form.depth[1] for form in FORMS.values())
            margin = max(0.,max(road.width/2+road.walk for road in streets)+options.setback+depth+4.-25.)
            left,bottom,right,top = left-margin,bottom-margin,right+margin,top+margin
        result["Ground"].box((left+right)/2, (bottom+top)/2, right-left, top-bottom, -1.55, 1.55, "Base", "Ground")
    if STREET_LAYERS & roles:
        def raised(x,y):
            height = elevation(x,y)
            return height+options.terrain_clearance if height is not None else None
        street_layers(result,streets,street_index,options,raised if drape and options.terrain_clearance else elevation,drape)
    if DEVELOPMENT <= roles:
        develop(result, streets, zones, street_index, options, bounds, elevation)
    return result
