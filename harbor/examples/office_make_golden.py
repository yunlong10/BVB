"""Build the golden solution: hand corrections to GPT-6 Astra's office reconstruction (IMG_3011),
made with the video's author.

Applied with Blender 4.2 to GPT-6 Astra's (high) reconstruction of the office video:
  blender -b astra_img_3011.blend --python office_make_golden.py -- "$PWD/golden.blend"
The result is harbor/tasks/bvb-img-3011-office/solution/golden.blend.
"""
import bpy, math, sys
from mathutils import Matrix, Vector

out = sys.argv[sys.argv.index("--") + 1]
log = lambda *a: print("FIX", *a)

def coll_objs(name):
    return list(bpy.data.collections[name].all_objects)

def roots(objs):
    s = set(objs)
    return [o for o in objs if o.parent not in s]

def mat_of(obj_name_prefix):
    for o in bpy.data.objects:
        if o.name.startswith(obj_name_prefix) and o.type == 'MESH' and o.active_material:
            return o.active_material
    raise KeyError(obj_name_prefix)

WHITE = mat_of("white desktop")
BEZEL = mat_of("black bezel")
GLASS = mat_of("display glass")
STEEL = mat_of("monitor stem")
dark = bpy.data.materials.new("matte black bottle"); dark.use_nodes = True
bsdf = dark.node_tree.nodes["Principled BSDF"]
bsdf.inputs["Base Color"].default_value = (0.015, 0.015, 0.017, 1); bsdf.inputs["Roughness"].default_value = 0.45
kb = bpy.data.materials.new("black keyboard"); kb.use_nodes = True
kb.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.03, 0.03, 0.035, 1)
kb.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.6

fixes = bpy.data.collections.new("Hand fixes"); bpy.context.scene.collection.children.link(fixes)

def box(name, size, loc, mat, rot_z=0.0):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc, rotation=(0, 0, rot_z))
    o = bpy.context.active_object; o.name = name; o.scale = size
    o.data.materials.append(mat)
    for c in o.users_collection: c.objects.unlink(o)
    fixes.objects.link(o); return o

def cyl(name, r, h, loc, mat, verts=32):
    bpy.ops.mesh.primitive_cylinder_add(vertices=verts, radius=r, depth=h, location=loc)
    o = bpy.context.active_object; o.name = name
    o.data.materials.append(mat)
    for c in o.users_collection: c.objects.unlink(o)
    fixes.objects.link(o)
    bpy.ops.object.shade_smooth()
    return o

# 1) Book: the M mark reads upside down -> spin the mark 180 deg about the book's centre.
book = bpy.data.objects["notebook"]
c = book.matrix_world.translation.copy()
spin = Matrix.Translation(c) @ Matrix.Rotation(math.pi, 4, 'Z') @ Matrix.Translation(-c)
marks = [o for o in coll_objs("Black notebook on carpet") if o.name.startswith("notebook M mark")]
for o in roots(marks):
    o.matrix_world = spin @ o.matrix_world
log("rotated M mark strokes:", len(marks))

# 2) The first desk seen after looking up from the floor sits flat against the window in
#    Astra's scene. In the video it is turned 90 degrees to the left: it runs from the window
#    back toward the camera along the left side, so nothing sits directly in front of the glass.
old_c, new_c = Vector((2.40, 0.56, 0.0)), Vector((2.45, 0.95, 0.0))
turn = Matrix.Translation(new_c) @ Matrix.Rotation(math.radians(90), 4, 'Z') @ Matrix.Translation(-old_c)
desk_objs = coll_objs("Window desk") + coll_objs("Window monitor")
for o in roots(desk_objs):
    o.matrix_world = turn @ o.matrix_world
# keep the monitor toward the window end of the desk, as in the video
for o in roots(coll_objs("Window monitor")):
    o.matrix_world = Matrix.Translation((0.0, -0.45, 0.0)) @ o.matrix_world
# the chair moves out of the desk's new footprint, into the middle of the view
for o in roots(coll_objs("Window chair")):
    o.matrix_world = Matrix.Translation((-0.74, -0.25, 0.0)) @ o.matrix_world
log("turned window desk objects:", len(desk_objs))

# 3) Missing desk with two monitors, a black keyboard and a black water bottle. In the video the
#    row runs [window][dual-monitor desk][soda-can desk], all perpendicular to the window. Slide the
#    soda-can row away from the window to open the gap (the back-to-back row stays put), build the
#    dual desk in the gap facing the same way, and move the camera with the row from 12 s on.
ROW_SHIFT = 0.85   # last desk in the row then ends just short of the back wall
row_names = ["Disinfectant wipes on cabinet", "Floor personal items", "Miscellaneous foreground cables",
             "Open laptop 0", "Open laptop 1", "Red soda", "Shopping bag", "Spare shoes beneath desk",
             "Tall silver energy drink", "Under desk bin"]
row_names += [c.name for c in bpy.data.collections if c.name.startswith(("Foreground ", "Near bench "))]

# the dual desk gets its own chair: a copy of the soda desk's chair, one desk-length nearer the window
chair_src = coll_objs("Foreground mesh chair 0")
copies = {}
for o in chair_src:
    c2 = o.copy(); fixes.objects.link(c2); copies[o] = c2
for o, c2 in copies.items():
    if o.parent in copies:
        c2.parent = copies[o.parent]; c2.matrix_parent_inverse = o.matrix_parent_inverse.copy()
for o in roots(chair_src):
    copies[o].matrix_world = Matrix.Translation((0.0, -0.52, 0.0)) @ o.matrix_world
for o in coll_objs("Spare chair"):
    o.hide_render = True; o.hide_viewport = True

row_objs = [o for n in row_names for o in coll_objs(n)]
for o in roots(row_objs):
    o.matrix_world = Matrix.Translation((0.0, ROW_SHIFT, 0.0)) @ o.matrix_world
log("slid soda-can row:", len(row_names), "groups,", len(row_objs), "objects")

# dual desk: same footprint depth and height as the soda desk, filling window sill -> soda desk
dx0, dx1, top = -1.45, -0.65, 0.75
dy0, dy1 = 0.27, 0.57 + ROW_SHIFT - 0.02
cx, cy, w, d = (dx0 + dx1) / 2, (dy0 + dy1) / 2, dx1 - dx0, dy1 - dy0
box("dual desk top", (w, d, 0.04), (cx, cy, top - 0.02), WHITE)
for y in (dy0 + 0.04, dy1 - 0.04):
    box("dual desk leg", (w - 0.08, 0.05, top - 0.04), (cx, y, (top - 0.04) / 2), STEEL)
box("dual desk crossbar", (0.05, d - 0.1, 0.08), (dx0 + 0.12, cy, 0.6), STEEL)
mx = dx0 + 0.19                       # monitors along the divider side, screens facing the chair (+x)
for i, my in enumerate((cy - 0.285, cy + 0.285)):
    box(f"dual monitor {i} foot", (0.18, 0.24, 0.02), (mx, my, top + 0.01), STEEL)
    box(f"dual monitor {i} stem", (0.04, 0.05, 0.26), (mx - 0.03, my, top + 0.15), STEEL)
    box(f"dual monitor {i} bezel", (0.035, 0.55, 0.34), (mx, my, top + 0.36), BEZEL)
    box(f"dual monitor {i} screen", (0.004, 0.53, 0.315), (mx + 0.019, my, top + 0.36), GLASS)
box("black keyboard", (0.14, 0.42, 0.022), (dx0 + 0.50, cy - 0.10, top + 0.011), kb)
box("black mouse", (0.10, 0.06, 0.03), (dx0 + 0.50, cy + 0.22, top + 0.015), kb)
bottle_xy = (dx0 + 0.36, cy + 0.02)
cyl("black water bottle body", 0.038, 0.23, (*bottle_xy, top + 0.115), dark)
cyl("black water bottle shoulder", 0.032, 0.03, (*bottle_xy, top + 0.245), dark)
cyl("black water bottle cap", 0.026, 0.035, (*bottle_xy, top + 0.275), dark)

# the small white cabinet tucks under the dual desk; its boxed keyboard goes away
for o in roots(coll_objs("Spare cabinet")):
    o.matrix_world = Matrix.Translation((-0.89, 0.49, 0.0)) @ o.matrix_world
for o in coll_objs("Spare keyboard on packaging"):
    o.hide_render = True; o.hide_viewport = True
log("added dual-monitor desk y[%.2f, %.2f] with keyboard + black bottle" % (dy0, dy1))

# 4) Judge read the desk rows as cubicles: the privacy panels stand 0.53 m above the desktops.
#    The real ones are low; drop them to 0.30 m, keeping their bottom edge on the desk.
panels = [o for o in bpy.data.objects if o.name.startswith("desktop privacy panel")]
for o in panels:
    bb = [o.matrix_world @ Vector(v) for v in o.bound_box]
    z0 = min(v.z for v in bb)
    o.dimensions = (o.dimensions.x, o.dimensions.y, 0.30)
    bpy.context.view_layer.update()
    bb = [o.matrix_world @ Vector(v) for v in o.bound_box]
    o.location.z += z0 - min(v.z for v in bb)
log("lowered privacy panels:", len(panels))

# 5) Camera spin: Astra keyed the camera heading across the +/-180 deg seam (-3.11 at 4.1 s,
#    +3.02 at 5.4 s, and likewise 1.3 s -> 2.7 s), so linear interpolation turns the long way
#    round and shows an empty wall and the far side of the office. Unwrap the heading keys so
#    each step turns the short way.
cam = bpy.context.scene.camera
act = cam.animation_data.action
fcs = getattr(act, "fcurves", None)
if fcs is None:
    fcs = [fc for layer in act.layers for strip in layer.strips for bag in strip.channelbags for fc in bag.fcurves]
heading = next(fc for fc in fcs if fc.data_path == "rotation_euler" and fc.array_index == 2)
pts = sorted(heading.keyframe_points, key=lambda k: k.co[0])
fixed = 0
for prev, cur in zip(pts, pts[1:]):
    while cur.co[1] - prev.co[1] > math.pi:
        cur.co[1] -= 2 * math.pi; fixed += 1
    while cur.co[1] - prev.co[1] < -math.pi:
        cur.co[1] += 2 * math.pi; fixed += 1
    cur.handle_left[1] = cur.handle_right[1] = cur.co[1]
heading.update()
log("unwrapped camera heading keys:", fixed, [round(k.co[1], 3) for k in pts])

# 6) Camera follows the slid row from 12 s on, so the dual desk shows ~10-11 s and the
#    soda-can desk ~12 s, as in the video.
sc = bpy.context.scene
n_frames = sc.frame_end - sc.frame_start + 1
f_from = sc.frame_start + round(12.0 / 24.3 * (n_frames - 1)) - 1
ycurve = next(fc for fc in fcs if fc.data_path == "location" and fc.array_index == 1)
moved = 0
for k in ycurve.keyframe_points:
    if k.co[0] >= f_from:
        k.co[1] += ROW_SHIFT; k.handle_left[1] += ROW_SHIFT; k.handle_right[1] += ROW_SHIFT; moved += 1
ycurve.update()
log("camera y keys shifted:", moved, "from frame", f_from)

bpy.ops.wm.save_as_mainfile(filepath=out)
log("saved", out)
