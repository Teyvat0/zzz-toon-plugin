"""Build the renderer scene from code: camera, sun, head empties, layers, world, compositor."""
import re
import bpy
from . import light_head, renderer_rim

KEEP = ('Camera', 'Sun', 'HeadCenter', 'HeadForward', 'HeadRight')
_IDS = ('scenes', 'objects', 'collections', 'node_groups', 'lights', 'cameras', 'worlds')
HEADS = {'HeadCenter': (0., 0., 1.4), 'HeadForward': (0., -.05, 1.4), 'HeadRight': (-.05, 0., 1.4)}


def base(name):
    return re.sub(r'\.\d{3}$', '', name)


def preflight():
    if bpy.app.version[:2] != (4, 4) or 'Goo' not in bpy.app.version_string:
        raise RuntimeError('仿ZZZ渲染首版仅支持已验证的 Goo Engine 4.4；普通 Blender 不提供等效降级')
    return {'version': bpy.app.version_string}


def _settings(scene):
    r, e = scene.render, scene.eevee
    r.resolution_x, r.resolution_y, r.resolution_percentage, r.fps = 1280, 960, 100, 30
    r.use_sequencer, r.use_compositing, r.film_transparent = False, True, False
    r.image_settings.file_format, r.image_settings.color_mode = 'PNG', 'RGBA'
    scene.view_settings.view_transform = 'Standard'
    for name in ('use_ssr', 'use_gtao', 'use_fast_gi', 'use_bloom', 'use_shadows', 'use_raytracing',
                 'use_volume_custom_range'):
        setattr(e, name, True)
    e.fast_gi_quality = 0.
    world = bpy.data.worlds.new('World'); world.use_nodes = True
    bg = next(n for n in world.node_tree.nodes if n.bl_idname == 'ShaderNodeBackground')
    bg.inputs[0].default_value = (0.050876, 0.050876, 0.050876, 1.); bg.inputs[1].default_value = 1.
    scene.world = world


def _objects(scene, controls):
    cam_data = bpy.data.cameras.new('Camera'); cam_data.clip_end = 100.
    sun_data = bpy.data.lights.new('Sun', 'SUN')
    sun_data.energy, sun_data.angle, sun_data.use_shadow = 1., .00918, False
    sun_data.specular_factor = sun_data.diffuse_factor = sun_data.transmission_factor = 0.
    keep = {'Camera': bpy.data.objects.new('Camera', cam_data), 'Sun': bpy.data.objects.new('Sun', sun_data)}
    keep['Camera'].location, keep['Camera'].rotation_euler = (0., -1.8, 1.33), (1.5708, 0., 0.)
    keep['Sun'].rotation_euler = (-0.0873, 0.9774, -0.7854)
    for name, loc in HEADS.items():
        ob = bpy.data.objects.new(name, None)
        ob.empty_display_type, ob.location, ob.hide_render = 'PLAIN_AXES', loc, True
        keep[name] = ob
    for ob in keep.values():
        controls.objects.link(ob)
    scene.camera = keep['Camera']
    return keep


def build(context, owner):
    """Create the whole renderer scene. On failure only IDs created here are removed."""
    before = {key: set(getattr(bpy.data, key)) for key in _IDS}
    old_scene = context.scene
    try:
        return _build(context, owner)
    except Exception:
        if context.window:
            context.window.scene = old_scene
        transient = set().union(*(set(getattr(bpy.data, key)) - before[key] for key in _IDS))
        if transient:
            bpy.data.batch_remove(ids=transient)
        raise


def _build(context, owner):
    scene = bpy.data.scenes.new('仿ZZZ渲染_' + owner[:8])
    scene['zzz_owner'], scene['zzz_renderer'] = owner, '仿ZZZ渲染'
    if context.window:
        context.window.scene = scene
    _settings(scene)
    main = scene.view_layers[0]; main.name = 'ViewLayer'
    eye = scene.view_layers.new('Eye')
    for layer, aovs in ((main, (('Normal', 'COLOR'), ('Rim', 'COLOR'), ('Hair', 'VALUE'), ('Avatar', 'VALUE'))),
                        (eye, (('Eye', 'VALUE'),))):
        layer.use_pass_z = True
        for name, kind in aovs:
            aov = layer.aovs.add(); aov.name, aov.type = name, kind
    cols = {}
    for key in ('Collection', 'Eye', 'Hair'):
        cols[key] = bpy.data.collections.new(key)
        scene.collection.children.link(cols[key])
    eye_by_id = {c.collection.as_pointer(): c for c in eye.layer_collection.children}
    eye_by_id[cols['Collection'].as_pointer()].holdout = True
    eye_by_id[cols['Hair'].as_pointer()].exclude = True
    controls = bpy.data.collections.new('ZZZ_控制与灯光_' + owner[:8])
    scene.collection.children.link(controls)
    keep = _objects(scene, controls)
    for ob in keep.values():
        ob['zzz_owner'] = owner
    tree = light_head.build(owner, keep['Sun'], keep['HeadCenter'], keep['HeadForward'], keep['HeadRight'])
    renderer_rim.chain(scene)
    return scene, {'LightHead': tree}, keep, cols, controls
