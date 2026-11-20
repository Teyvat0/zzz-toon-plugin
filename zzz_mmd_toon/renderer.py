"""Self-built renderer scene: model attachment, head frame and camera framing."""
import re
import bpy
from mathutils import Matrix, Vector
from bpy_extras.object_utils import world_to_camera_view

from .renderer_scene import build, preflight, base  # noqa: F401  (public entry points)
from .renderer_scene import KEEP  # noqa: F401


def attach_model(context, scene, rig, parts, rows, cols, controls, owner, source_scene):
    # Parts were already created and proven by the native MMD material operator.
    # Keep one primary depth-tested render image; do not force through-hair eyes.
    meshes = set(parts.values())
    physics = bpy.data.collections.new('ZZZ_MMD物理_' + owner[:8])
    scene.collection.children.link(physics)
    rigid_set, joint_set = set(rig.rigidBodies()), set(rig.joints())
    all_objects = list(rig.allObjects())
    for ob in all_objects:
        if ob in meshes:
            continue
        target = physics if ob in rigid_set or ob in joint_set or ob.mmd_type in {'RIGID_GRP_OBJ', 'JOINT_GRP_OBJ', 'TEMPORARY_GRP_OBJ', 'NON_COLLISION_CONSTRAINT', 'TRACK_TARGET'} else controls
        if ob.name not in target.objects:
            target.objects.link(ob)
    archive = bpy.data.collections.new('ZZZ_MME重复叠层_保留关闭_' + owner[:8])
    scene.collection.children.link(archive)
    effect_parts=[]
    row_by_slot={int(r['slot']):r for r in rows}
    for ob in parts.values():
        row=row_by_slot[int(ob['zzz_source_slot'])]
        effect=row.get('effect_policy')=='MME_DUPLICATE_OFF'
        target = archive if effect else cols['Collection']
        if ob.name not in target.objects:
            target.objects.link(ob)
        if effect:
            ob['zzz_effect_policy']='MME_DUPLICATE_OFF'
            ob['zzz_effect_was_hide_render']=bool(ob.hide_render)
            ob.hide_render=True
            ob.name='MME_OFF_'+ob.name
            effect_parts.append({'object':ob.name,'source_slot':int(row['slot']),
                                 'policy':'MME_DUPLICATE_OFF','evidence':row['effect_evidence']})
    archive['zzz_effect_policy']='MME_DUPLICATE_OFF'
    archive['zzz_restore_hint']='Toggle each MME_OFF part hide_render to restore; source Material and geometry are retained.'
    scene['zzz_effect_parts']=__import__('json').dumps(effect_parts,ensure_ascii=False)
    scene['zzz_universal'] = True
    if context.window:
        context.window.scene = scene
        context.window.view_layer = scene.view_layers['ViewLayer']
    # Never unlink the original collections or Bullet links. A separate world uses
    # the same original rigid/constraint IDs, preserving their native parameters.
    with context.temp_override(scene=scene, view_layer=scene.view_layers['ViewLayer']):
        if rigid_set or joint_set:
            bpy.ops.rigidbody.world_add()
            world = scene.rigidbody_world
            rbcol = bpy.data.collections.new('ZZZ_Bullet刚体_' + owner[:8])
            jtcol = bpy.data.collections.new('ZZZ_Bullet约束_' + owner[:8])
            scene.collection.children.link(rbcol)
            scene.collection.children.link(jtcol)
            world.collection, world.constraints = rbcol, jtcol
            for ob in rigid_set:
                rbcol.objects.link(ob)
                ob.hide_render = True
                ob.hide_set(True)
            for ob in joint_set:
                jtcol.objects.link(ob)
                ob.hide_render = True
                ob.hide_set(True)
            for ob in rig.temporaryObjects():
                if ob.rigid_body_constraint and ob.name not in jtcol.objects:
                    jtcol.objects.link(ob)
                ob.hide_render = True
                ob.hide_set(True)
            world.enabled = bool(rig.rootObject().mmd_root.is_built)
            world.substeps_per_frame = source_scene.rigidbody_world.substeps_per_frame if source_scene.rigidbody_world else 6
            world.solver_iterations = source_scene.rigidbody_world.solver_iterations if source_scene.rigidbody_world else 10
            world.point_cache.frame_start, world.point_cache.frame_end = source_scene.frame_start, source_scene.frame_end
    scene.frame_start, scene.frame_end = source_scene.frame_start, source_scene.frame_end
    scene.render.fps = source_scene.render.fps
    scene.gravity = source_scene.gravity
    scene.frame_set(source_scene.frame_current)
    return {'rigids': len(rigid_set), 'joints': len(joint_set), 'built': rig.rootObject().mmd_root.is_built}


def head_frame(context, arm, keep, controls, owner):
    from . import mmd_adapter
    head = mmd_adapter.head_bone(arm)
    context.view_layer.update()
    if head is not None:
        center = arm.matrix_world @ head.head
    else:
        # Generic PMX need not expose a Japanese head name. This frame is only a
        # renderer coordinate fallback, never a new deform bone or guessed weight.
        points = [o.matrix_world @ Vector(corner) for o in context.scene.objects
                  if o.type == 'MESH' and o.get('zzz_owner') == owner for corner in o.bound_box]
        if points:
            center = Vector(((min(p.x for p in points)+max(p.x for p in points))/2,
                             (min(p.y for p in points)+max(p.y for p in points))/2,
                             min(p.z for p in points)*.18+max(p.z for p in points)*.82))
        else:
            center = arm.matrix_world.translation.copy()
    anchor = bpy.data.objects.new('ZZZ_头部坐标_' + owner[:8], None)
    controls.objects.link(anchor)
    anchor['zzz_owner'] = owner
    anchor.matrix_world = Matrix.Translation(center)
    if head is not None:
        con = anchor.constraints.new('CHILD_OF')
        con.target, con.subtarget = arm, head.name
        con.inverse_matrix = (arm.matrix_world @ head.matrix).inverted()
        anchor['zzz_head_bone'] = head.name
    else:
        anchor.parent = arm
        anchor.matrix_parent_inverse = arm.matrix_world.inverted()
        anchor['zzz_head_bone'] = ''
        anchor['zzz_head_fallback'] = True
    for name, delta in {'HeadCenter': (0, 0, 0), 'HeadForward': (0, -.05, 0), 'HeadRight': (-.05, 0, 0)}.items():
        ob = keep[name]
        ob.parent = anchor
        ob.matrix_parent_inverse = Matrix.Identity(4)
        ob.location = delta
        ob.rotation_euler = (0, 0, 0)
        ob.scale = (1, 1, 1)
        ob.hide_viewport = False
        ob.hide_set(False)
        ob.hide_render = True
    context.view_layer.update()
    if (keep['HeadCenter'].matrix_world.translation - center).length > 1e-5:
        raise RuntimeError('头部坐标未正确求值；请文件回退')
    return {'head_bone': head.name if head else None, 'center': list(center),
            'fallback': head is None, 'no_deform_bones_created': True}


def fit_camera(context, scene, camera, parts, resolution):
    scene.render.resolution_x = int(resolution * 4 / 3)
    scene.render.resolution_y = int(resolution)
    camera.data.lens, camera.data.sensor_width = 50, 36
    camera.data.sensor_fit = 'HORIZONTAL'
    camera.data.shift_x = camera.data.shift_y = 0
    camera.data.clip_start, camera.data.clip_end = .01, 1000
    context.view_layer.update()
    dg = context.evaluated_depsgraph_get()
    import numpy as np
    chunks = []
    for ob in parts.values():
        if ob.hide_render:
            continue
        ev = ob.evaluated_get(dg)
        me = ev.to_mesh()
        co = np.empty(len(me.vertices) * 3, dtype=np.float32)
        me.vertices.foreach_get('co', co)
        matrix = np.array(ev.matrix_world, dtype=np.float64)
        chunks.append(co.reshape(-1, 3).astype(np.float64) @ matrix[:3, :3].T + matrix[:3, 3])
        ev.to_mesh_clear()
    points = np.concatenate(chunks) if chunks else np.empty((0, 3))
    if not len(points):
        raise RuntimeError('没有可渲染顶点')

    def project(cam):
        # Vectorised bpy_extras.object_utils.world_to_camera_view (same formula).
        inv = np.array(cam.matrix_world.normalized().inverted(), dtype=np.float64)
        local = points @ inv[:3, :3].T + inv[:3, 3]
        z = -local[:, 2]
        frame = [np.array(v, dtype=np.float64) for v in cam.data.view_frame(scene=scene)[:3]]
        safe = np.where(z == 0.0, 1.0, z)
        if cam.data.type != 'ORTHO':
            frame = [-(v[None, :] / (v[2] / safe)[:, None]) for v in frame]
        else:
            frame = [np.broadcast_to(v, (len(z), 3)) for v in frame]
        min_x, max_x, min_y, max_y = frame[2][:, 0], frame[1][:, 0], frame[1][:, 1], frame[0][:, 1]
        x = (local[:, 0] - min_x) / (max_x - min_x)
        y = (local[:, 1] - min_y) / (max_y - min_y)
        if cam.data.type != 'ORTHO':
            x, y = np.where(z == 0.0, 0.5, x), np.where(z == 0.0, 0.5, y)
        return x, y, z
    low, high = points.min(axis=0), points.max(axis=0)
    look = Vector(((low + high) / 2).tolist())
    dist, margin = 3., .08
    for _ in range(45):
        camera.location = look + Vector((0, -dist, 0))
        camera.rotation_euler = (look - camera.location).to_track_quat('-Z', 'Y').to_euler()
        context.view_layer.update()
        nx, ny, nz = project(camera)
        if nz.min() <= .001:
            dist *= 1.5
            continue
        a, b, c, d = float(nx.min()), float(nx.max()), float(ny.min()), float(ny.max())
        cx, cy = (a+b)/2-.5, (c+d)/2-.5
        hw = dist * camera.data.sensor_width / (2 * camera.data.lens)
        hh = hw * scene.render.resolution_y / scene.render.resolution_x
        look += camera.matrix_world.col[0].to_3d() * cx*2*hw + camera.matrix_world.col[1].to_3d() * cy*2*hh
        ratio = max(b-a, d-c)/(1-2*margin)
        dist *= max(.6, min(1.6, ratio))
        if abs(ratio-1) < .0001 and max(abs(cx), abs(cy)) < .0001:
            break
    camera.location = look + Vector((0, -dist, 0))
    camera.rotation_euler = (look-camera.location).to_track_quat('-Z', 'Y').to_euler()
    context.view_layer.update()
    nx, ny, nz = project(camera)
    bounds = [float(nx.min()), float(nx.max()), float(ny.min()), float(ny.max())]
    if bounds[0] < .07 or bounds[2] < .07 or bounds[1] > .93 or bounds[3] > .93 or nz.min() <= 0:
        raise RuntimeError('自动取景切边: ' + str(bounds))
    scene.camera = camera
    return {'projected_vertices': int(len(points)), 'ndc_bounds': bounds, 'camera': camera.name}
