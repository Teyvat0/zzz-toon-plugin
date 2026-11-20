"""Reproducible data-preservation checks; not a solid/collision certificate."""
import hashlib
import json
import math
import struct
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def artifact(path):
    path = Path(path)
    return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': file_hash(path), 'md5': hashlib.md5(path.read_bytes()).hexdigest()}


def skeleton(arm):
    """Native build may alter constraints/use_connect, never rest or hierarchy."""
    return digest([{'name': b.name, 'jp': getattr(getattr(arm.pose.bones[b.name], 'mmd_bone', None), 'name_j', ''),
                    'parent': b.parent.name if b.parent else None, 'head': list(b.head_local),
                    'tail': list(b.tail_local), 'rest': [list(row) for row in b.matrix_local], 'deform': b.use_deform}
                   for b in arm.data.bones])


# Incompatible with v2: rebuild from trusted PMX/checkpoint, NEVER rebase old runs.
MESH_GUARD_SCHEMA = 'authored-mesh.v3-shape-attribute-uv-structure'

_INTRINSIC_MESH_ATTRIBUTES = {
    'position': ('FLOAT_VECTOR', 'POINT'), '.edge_verts': ('INT32_2D', 'EDGE'),
    '.corner_vert': ('INT', 'CORNER'), '.corner_edge': ('INT', 'CORNER'),
    'material_index': ('INT', 'FACE'),
}  # These exact serialized values are protected separately below.
_MESH_SELECTION_ATTRIBUTES = {
    '.select_vert': ('BOOLEAN', 'POINT'), '.select_edge': ('BOOLEAN', 'EDGE'),
    '.select_poly': ('BOOLEAN', 'FACE'), '.hide_vert': ('BOOLEAN', 'POINT'),
    '.hide_edge': ('BOOLEAN', 'EDGE'), '.hide_poly': ('BOOLEAN', 'FACE'),
}  # Mesh/UV editor selection and hide UI, not shader/object hide_render.
# Every generic Mesh attribute type exposed by the authoritative Goo 4.4.3 RNA.
# Unknown types/domains fail closed instead of falling back to repr/rounded JSON.
_ATTRIBUTE_STORAGE = {
    'FLOAT': ('value', '<f'), 'INT': ('value', '<i'),
    'FLOAT_VECTOR': ('vector', '<3f'), 'FLOAT_COLOR': ('color', '<4f'),
    'BYTE_COLOR': ('color_srgb', '<4B'), 'STRING': ('value', None),
    'BOOLEAN': ('value', '<?'), 'FLOAT2': ('vector', '<2f'),
    'INT8': ('value', '<b'), 'INT16_2D': ('value', '<2h'),
    'INT32_2D': ('value', '<2i'), 'QUATERNION': ('value', '<4f'),
    'FLOAT4X4': ('value', '<16f'),
}


def _mesh_token(stream, value):
    """Unambiguous UTF-8 metadata boundary; binary payloads have explicit lengths."""
    payload = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
    stream.update(struct.pack('<Q', len(payload)))
    stream.update(payload)


def _stable_attributes(mesh):
    # Exact UI-only exclusions, not a general dot/ZZZ prefix escape hatch. UV
    # selection/hide is transient; UV pins (.pn.<name>), crease/custom data stay.
    uv_selection = {prefix + uv.name: ('BOOLEAN', 'CORNER')
                    for uv in mesh.uv_layers for prefix in ('.vs.', '.es.')}
    excluded = {**_INTRINSIC_MESH_ATTRIBUTES, **_MESH_SELECTION_ATTRIBUTES, **uv_selection}
    attributes = []
    for attribute in mesh.attributes:
        expected = excluded.get(attribute.name)
        if expected is not None:
            if (attribute.data_type, attribute.domain) != expected:
                raise RuntimeError('Invalid intrinsic/UI attribute layout: ' + repr((attribute.name, attribute.data_type, attribute.domain, expected)))
            continue
        attributes.append(attribute)
    return sorted(attributes, key=lambda attribute: attribute.name)


def authored_attributes(mesh):
    """All stable non-intrinsic POINT/EDGE/FACE/CORNER author layers, bit-exact.

    Protect membership/name/domain/type/count and every value, including normals,
    UV FLOAT2 layers, UV pins, colors, creases and unknown/custom-named layers.
    Exclude only separately-hashed intrinsic data and exact transient selection
    layers. Attribute editor active selection is UI, not author structure; color
    default/render identity is structural and is protected by uv_structure.
    """
    h = hashlib.sha256()
    counts = {'POINT': len(mesh.vertices), 'EDGE': len(mesh.edges),
              'FACE': len(mesh.polygons), 'CORNER': len(mesh.loops)}
    attributes = _stable_attributes(mesh)
    _mesh_token(h, ('authored-attributes.v1', len(attributes)))
    for attribute in attributes:
        name, data_type, domain = attribute.name, attribute.data_type, attribute.domain
        if domain not in counts or data_type not in _ATTRIBUTE_STORAGE:
            raise RuntimeError('Unsupported stable authored attribute: ' + repr((name, data_type, domain)))
        if len(attribute.data) != counts[domain]:
            raise RuntimeError('Invalid stable authored attribute length: ' + repr((name, domain, len(attribute.data), counts[domain])))
        _mesh_token(h, (name, data_type, domain, len(attribute.data)))
        field, fmt = _ATTRIBUTE_STORAGE[data_type]
        for item in attribute.data:
            value = getattr(item, field)
            if data_type == 'STRING':
                # RNA returns raw bytes, not necessarily valid UTF-8 author text.
                payload = value.encode('utf-8') if isinstance(value, str) else bytes(value)
                h.update(struct.pack('<Q', len(payload)))
                h.update(payload)
            elif data_type == 'BYTE_COLOR':
                # color_srgb exposes the original uchar4 / 255 (unlike the decoded
                # linear `color`). Rounding recovers exact original bytes, with no
                # epsilon/quantization tolerance between distinct stored values.
                h.update(struct.pack(fmt, *(round(float(channel) * 255) for channel in value)))
            elif data_type == 'FLOAT4X4':
                h.update(struct.pack(fmt, *(component for row in value for component in row)))
            elif isinstance(value, (bool, int, float)):
                h.update(struct.pack(fmt, value))
            else:
                h.update(struct.pack(fmt, *value))
    return h.hexdigest()


def shape_structure(mesh):
    """Shape topology, not animated/evaluated state; coords are hashed separately.

    Intentionally exclude value/eval_time. Also exclude slider_min/slider_max and
    mute: native MMD Tools core/vmd/importer.py:509-510 expands bounds for VMD,
    core/morph.py:423-431 expands bounds/unmutes keys during cleanup, and
    core/sdef.py:62 toggles the SDEF key mute. Freezing these breaks native use.
    Active key/show-only edit UI and action/driver evaluation are not frozen.
    """
    keys = mesh.shape_keys
    if keys is None:
        return None
    blocks = list(keys.key_blocks)

    def reference(key):
        if key is None:
            return None
        for index, candidate in enumerate(blocks):
            if key == candidate:
                return (index, candidate.name)
        raise RuntimeError('ShapeKey references a key outside its authored Key datablock')

    return {'use_relative': bool(keys.use_relative), 'reference_key': reference(keys.reference_key),
            'keys': [(key.name, reference(key.relative_key), key.vertex_group, float(key.frame),
                      key.interpolation, bool(key.lock_shape), len(key.data)) for key in blocks]}


def uv_structure(mesh):
    """Ordered UV identities + active/render/clone, and default/render color names.

    No accesses to UV vertex/edge-selection or pin collections: those RNA getters
    may create storage. Existing pins are protected by authored_attributes without
    materializing any cache or changing absent/present layer state.
    """
    colors = mesh.color_attributes
    return {'layers': [(uv.name, bool(uv.active), bool(uv.active_render), bool(uv.active_clone), len(uv.data))
                       for uv in mesh.uv_layers],
            'active_index': int(mesh.uv_layers.active_index),
            'active_name': mesh.uv_layers.active.name if mesh.uv_layers.active else None,
            'default_color_name': colors.default_color_name,
            'render_color_index': int(colors.render_color_index)}


def normal_inputs(mesh):
    """Bit-exact serialized inputs, NOT runtime calculated corner-normal cache.

    Blender 4.4 stores custom normals as CORNER INT16_2D. Calculated float3
    corner_normals is non-injective and a runtime cache; cancelling normal fans
    can yield different decoded values without an author-data edit. Protect the
    actual signed-short2, both sharp masks, edge/corner topology and smoothing.
    Positions are separately included by mesh_state. Never mutate/update normals.
    """
    h = hashlib.sha256()
    h.update(json.dumps(('normal-inputs.v1', len(mesh.vertices), len(mesh.edges),
                         len(mesh.loops), len(mesh.polygons)), separators=(',', ':')).encode('ascii'))
    for edge in mesh.edges:
        h.update(struct.pack('<2i', *edge.vertices))
    for loop in mesh.loops:
        h.update(struct.pack('<2i', loop.vertex_index, loop.edge_index))
    for polygon in mesh.polygons:
        h.update(struct.pack('<2i?', polygon.loop_start, polygon.loop_total, polygon.use_smooth))
    for name, data_type, domain in (('custom_normal', 'INT16_2D', 'CORNER'),
                                    ('sharp_edge', 'BOOLEAN', 'EDGE'),
                                    ('sharp_face', 'BOOLEAN', 'FACE')):
        attribute = mesh.attributes.get(name)
        metadata = None if attribute is None else (attribute.data_type, attribute.domain, len(attribute.data))
        h.update(json.dumps((name, metadata), separators=(',', ':')).encode('utf-8'))
        if attribute is None:
            continue
        if attribute.data_type != data_type or attribute.domain != domain:
            raise RuntimeError('Unsupported authored normal attribute: ' + repr((name, metadata)))
        if data_type == 'INT16_2D':
            for item in attribute.data:
                h.update(struct.pack('<2h', *item.value))
        else:
            for item in attribute.data:
                h.update(struct.pack('<?', item.value))
    return h.hexdigest()


def mesh_state(parts):
    """Strict v3 author store; no normal-cache reads, repairs or baseline writes."""
    rows = []
    for slot, ob in sorted(parts.items()):
        mesh = ob.data
        h = hashlib.sha256()
        _mesh_token(h, ('mesh-part.v3', len(mesh.vertices), len(mesh.edges), len(mesh.loops), len(mesh.polygons)))
        # Keep all groups including unused/zero weights and lock flags. Evaluated
        # GN outline does not author groups; no name-based renderer escape hatch.
        _mesh_token(h, [(group.name, bool(group.lock_weight)) for group in ob.vertex_groups])
        for v in mesh.vertices:
            h.update(struct.pack('<3f', *v.co))
            weights = sorted((ob.vertex_groups[g.group].name, float(g.weight)) for g in v.groups)
            _mesh_token(h, weights)
        for p in mesh.polygons:
            h.update(struct.pack('<%di' % len(p.vertices), *p.vertices))
            h.update(struct.pack('<i', p.material_index))
        h.update(normal_inputs(mesh).encode('ascii'))
        h.update(authored_attributes(mesh).encode('ascii'))
        _mesh_token(h, uv_structure(mesh))
        _mesh_token(h, shape_structure(mesh))
        if mesh.shape_keys:
            for key in mesh.shape_keys.key_blocks:
                for v in key.data:
                    h.update(struct.pack('<3f', *v.co))
        rows.append((slot, h.hexdigest(), bool(mesh.has_custom_normals)))
    return digest({'schema': MESH_GUARD_SCHEMA, 'parts': rows})


def semantic_slots(meshes, material_slot):
    """Retired decoded-normal/rounded legacy split; deliberately fail closed.

    Only legacy mmd_adapter.prepare called this helper; prepare_universal uses
    native_split.separate's exact serialized POINT/EDGE/CORNER/FACE provenance.
    Do not silently substitute a different equivalence signature or revive old
    baselines. In particular this function must never read computed normals.
    """
    raise RuntimeError('旧版近似拆分验证已停用；请使用 native_split.separate 的 serialized provenance，并从可信原PMX重新配置')


def socket_key(socket):
    """A repeated label (Math 'Value') is not a socket identity."""
    node = socket.node
    collection = node.outputs if socket.is_output else node.inputs
    return (socket.identifier, list(collection).index(socket), socket.name)


def link_key(link):
    return (link.from_node.name, socket_key(link.from_socket),
            link.to_node.name, socket_key(link.to_socket))


def graph_state(tree, seen=None):
    seen = set() if seen is None else seen
    if tree.as_pointer() in seen:
        return {'shared': tree.name}
    seen.add(tree.as_pointer())
    nodes = []
    # Driven values are evaluated inputs, not authored defaults. Protect the
    # driver contract itself, allowing Sun color/energy to evaluate normally.
    curves = list(tree.animation_data.drivers) if tree.animation_data else []
    driven = {f.data_path for f in curves}
    driver_state = [(f.data_path, f.array_index, f.driver.type, f.driver.expression,
                     [(v.name, v.type, [(t.id.name if t.id else None, t.data_path) for t in v.targets])
                      for v in f.driver.variables]) for f in curves]
    interface = []
    if hasattr(tree, 'interface'):
        interface = [(s.identifier, s.name, s.in_out, s.socket_type)
                     for s in tree.interface.items_tree if s.item_type == 'SOCKET']
    for node in sorted(tree.nodes, key=lambda n: n.name):
        defaults = []
        for socket in node.inputs:
            if hasattr(socket, 'default_value'):
                if socket.path_from_id('default_value') in driven:
                    defaults.append((socket_key(socket), {'driven': True}))
                    continue
                v = socket.default_value
                if isinstance(v, (str, bool, int, float)):
                    val = v
                elif hasattr(v, 'name'):
                    val = {'id': v.name}
                else:
                    try:
                        val = list(v)
                    except TypeError:
                        val = str(v)
                defaults.append((socket_key(socket), val))
        row = {'name': node.name, 'type': node.bl_idname, 'defaults': defaults}
        for prop in ('operation', 'blend_type', 'aov_name', 'attribute_name', 'attribute_type', 'uv_map',
                     'layer', 'interpolation', 'extension', 'projection', 'data_type', 'use_clamp',
                     'mute', 'is_active_output', 'domain', 'transform_space', 'input_type',
                     'convert_from', 'convert_to', 'vector_type', 'clamp_type'):
            if hasattr(node, prop):
                row[prop] = getattr(node, prop)
        if getattr(node, 'image', None):
            import bpy
            image_path = str(Path(bpy.path.abspath(node.image.filepath, library=node.image.library)).resolve())
            row['image'] = [image_path, node.image.colorspace_settings.name, node.image.alpha_mode]
        if getattr(node, 'node_tree', None):
            row['tree'] = graph_state(node.node_tree, seen)
        if node.type in {'RGB','VALUE'}:
            row['outputs']=[(socket.name,list(socket.default_value) if hasattr(socket.default_value,'__len__') else socket.default_value) for socket in node.outputs if hasattr(socket,'default_value')]
        if node.type=='VALTORGB':
            row['ramp']={'interpolation':node.color_ramp.interpolation,'elements':[(float(e.position),list(e.color)) for e in node.color_ramp.elements]}
        nodes.append(row)
    return {'identity': tree.name, 'interface': interface, 'nodes': nodes,
            'drivers': sorted(driver_state, key=lambda item: (item[0], item[1])),
            'links': sorted(link_key(link) for link in tree.links)}


def material_targets(root):
    """Stable native material-Morph targets, not animatable offset values."""
    return [(m.name, [(d.material_data.name if d.material_data else None,
                       int(d.material_id),
                       d.related_mesh_data.name if d.related_mesh_data else None)
                      for d in m.data]) for m in root.mmd_root.material_morphs]


def shader_state_data(parts):
    """Authored renderer contract; native Morph INSTANCE inputs remain live."""
    rows = []
    for slot, ob in sorted(parts.items()):
        masks = {name: [(v.index, float(g.weight)) for v in ob.data.vertices for g in v.groups
                        if ob.vertex_groups[g.group].name == name]
                 for name in ('GN_Outline', 'OutlineMask')}
        stack = []
        for mod in ob.modifiers:
            item = [mod.name, mod.type, mod.show_viewport, mod.show_render]
            if mod.type == 'ARMATURE':
                item += [mod.object.name if mod.object else None, mod.use_vertex_groups,
                         mod.use_bone_envelopes, mod.use_deform_preserve_volume,
                         mod.vertex_group, mod.invert_vertex_group]
            stack.append(item)
        rows.append((slot, 'renderer_masks_and_stack', digest(masks), stack))
        rows.append((slot, 'material_slots', [(index, mat.name if mat else None,
                     int(mat.mmd_material.material_id) if mat and hasattr(mat, 'mmd_material') else None,
                     mat.get('zzz_material_uid') if mat else None) for index, mat in enumerate(ob.data.materials)]))
        for index, mat in enumerate(ob.data.materials):
            expected = ob.get('zzz_material_ref_' + str(index))
            if expected is not None and expected != mat:
                raise RuntimeError('原材质槽引用已被替换: ' + ob.name + '/' + str(index))
            if mat is None or not mat.get('zzz_owner'):
                continue
            native = mat.node_tree.nodes.get('mmd_shader')
            expected_tree = mat.get('zzz_native_tree_ref')
            if native is None or native.type != 'GROUP' or expected_tree is None or native.node_tree != expected_tree:
                raise RuntimeError('原生材质 Morph 桥组身份被替换: ' + mat.name)
            if native.mute:
                raise RuntimeError('原生材质 Morph 桥组被静音: ' + mat.name)
            rows.append((slot, mat.name, 'native_bridge_structure', graph_state(native.node_tree)))
            from .game_bridge import eye_shadow_tint_input
            tint_control = eye_shadow_tint_input(mat)
            if tint_control is not None and not all(math.isfinite(float(x)) and 0. <= float(x) <= 1. for x in tint_control.default_value):
                raise RuntimeError('目影透射颜色必须是有限的0..1 RGB(A): ' + mat.name)
            nodes = sorted((n for n in mat.node_tree.nodes if n.name.startswith('ZZZ_')), key=lambda n: n.name)
            authored = []
            for n in nodes:
                defaults = []
                for socket in n.inputs:
                    if hasattr(socket, 'default_value') and not socket.is_linked:
                        if tint_control is not None and socket == tint_control:
                            # One explicit user-facing transmittance control. Its
                            # socket identity and every link/node remain protected.
                            defaults.append((socket_key(socket), {'live_eye_shadow_transmittance': True}))
                            continue
                        value = socket.default_value
                        if not isinstance(value, (str, bool, int, float)):
                            value = {'id':value.name} if hasattr(value, 'name') else list(value)
                        defaults.append((socket_key(socket), value))
                props = {p:getattr(n,p) for p in ('operation','blend_type','use_clamp','convert_from','convert_to',
                         'vector_type','mute','domain','transform_space','is_active_output','attribute_name') if hasattr(n,p)}
                authored.append((n.name, n.bl_idname, props, defaults,
                                 graph_state(n.node_tree) if getattr(n,'node_tree',None) else None))
            rows.append((slot, mat.name, 'live_morph_wrapper', mat.blend_method, mat.use_backface_culling,
                         authored, sorted(link_key(l) for l in mat.node_tree.links if l.from_node in nodes or l.to_node in nodes)))
        for mod in ob.modifiers:
            if mod.type == 'NODES' and mod.node_group and mod.node_group.get('zzz_owner'):
                rows.append((slot, 'GN', graph_state(mod.node_group), mod.show_viewport, mod.show_render))
    return rows


def shader_state(parts):
    return digest(shader_state_data(parts))


def active_images(parts):
    from .dependencies import active_images as reachable
    return reachable(parts)


def scene_gate(scene, parts, groups, keep, collections, root, arm, compositor=None):
    """Required dependency checks while allowing normal VMD/camera/light edits."""
    import bpy
    from mathutils import Vector
    if scene.camera is None or scene.camera.type != 'CAMERA' or scene.camera.name not in scene.objects:
        raise RuntimeError('渲染相机丢失或不属于当前场景')
    if not scene.render.use_compositing or not scene.use_nodes or not scene.node_tree:
        raise RuntimeError('双层合成器被关闭')
    for name in ('ViewLayer', 'Eye'):
        layer = scene.view_layers.get(name)
        if layer is None or not layer.use or not layer.use_pass_z:
            raise RuntimeError('必需渲染层或深度通道被关闭: ' + name)
    if compositor and digest(graph_state(scene.node_tree)) != compositor:
        raise RuntimeError('已配置的双层合成链路被修改；请回退后重新配置')
    rlayers = [n for n in scene.node_tree.nodes if n.type == 'R_LAYERS']
    if not {'ViewLayer', 'Eye'}.issubset({n.layer for n in rlayers}) or any(n.scene != scene for n in rlayers):
        raise RuntimeError('合成器引用了其它场景或缺少眼层')
    if not any(n.type == 'COMPOSITE' and n.inputs[0].is_linked for n in scene.node_tree.nodes):
        raise RuntimeError('合成器输出已断开')
    def find(layer, collection):
        if layer.collection == collection:
            return layer
        for child in layer.children:
            result = find(child, collection)
            if result is not None:
                return result
        return None
    for key, col in collections.items():
        main = find(scene.view_layers['ViewLayer'].layer_collection, col)
        eye = find(scene.view_layers['Eye'].layer_collection, col)
        if col.hide_render or col.hide_viewport or main is None or eye is None or main.exclude or main.holdout:
            raise RuntimeError('必需角色集合被关闭/移出/设为遮罩: ' + key)
        if key == 'Collection' and (not eye.holdout or eye.exclude):
            raise RuntimeError('眼层主角色 holdout 配置被修改')
        if key == 'Hair' and not eye.exclude:
            raise RuntimeError('眼层头发排除配置被修改')
        if key == 'Eye' and (eye.exclude or eye.holdout):
            raise RuntimeError('眼层眼睛集合被关闭')
    from . import lighting
    gn = groups['LightHead']
    sun = lighting.current(gn, keep['Sun'])   # the user may have picked another sun as main light
    if sun.type != 'LIGHT' or sun.data.type != 'SUN' or sun.hide_render or sun.hide_viewport:
        raise RuntimeError('必需 Sun 灯光被删除/关闭')
    drivers = list(gn.animation_data.drivers) if gn.animation_data else []
    targets = [t for f in drivers for v in f.driver.variables for t in v.targets]
    if len(drivers) != 4 or len(targets) != 4 or any(t.id != sun.data for t in targets):
        raise RuntimeError('Sun 驱动目标不正确')
    center = keep['HeadCenter']
    anchor = center.parent
    from . import mmd_adapter
    head = mmd_adapter.head_bone(arm)
    if anchor is None:
        raise RuntimeError('渲染头坐标丢失')
    if anchor.get('zzz_head_fallback'):
        if anchor.parent != arm or anchor.hide_viewport:
            raise RuntimeError('通用坐标后备框架被关闭或改绑')
    else:
        cons = [c for c in anchor.constraints if c.type == 'CHILD_OF' and c.target == arm and head is not None and c.subtarget == head.name and not c.mute and abs(c.influence-1) < 1e-6]
        if len(cons) != 1 or anchor.hide_viewport:
            raise RuntimeError('头部跟随约束被关闭或改绑')
    for name, offset in {'HeadCenter': (0,0,0), 'HeadForward': (0,-.05,0), 'HeadRight': (-.05,0,0)}.items():
        ob = keep[name]
        if ob.parent != anchor or ob.hide_viewport or len(ob.constraints) or (ob.location-Vector(offset)).length > 1e-6:
            raise RuntimeError('头部辅助对象被关闭/改绑: ' + name)
    bpy.context.view_layer.update()
    if head is not None and not anchor.get('zzz_head_fallback') and (center.matrix_world.translation - (arm.matrix_world @ head.head)).length > 1e-4:
        raise RuntimeError('头部坐标没有正确跟随当前姿态')
    return shader_gate(scene, parts, groups, root, arm)


def shader_gate(scene, parts, groups, root, arm):
    expected = {('Normal', 'COLOR'), ('Rim', 'COLOR'), ('Hair', 'VALUE'), ('Avatar', 'VALUE')}
    if not expected.issubset({(a.name, a.type) for a in scene.view_layers['ViewLayer'].aovs}):
        raise RuntimeError('主渲染层 AOV 不完整')
    if ('Eye', 'VALUE') not in {(a.name, a.type) for a in scene.view_layers['Eye'].aovs}:
        raise RuntimeError('眼层 AOV 不完整')
    images = active_images(parts)
    if not all((im.packed_file or im.source == 'GENERATED') and im.size[0] > 0 for im in images):
        raise RuntimeError('实际参与渲染的贴图未打包或解码失败；拒绝报告成功')
    gn = groups['LightHead']
    drivers = list(gn.animation_data.drivers) if gn.animation_data else []
    if len(drivers) != 4 or not all(f.is_valid for f in drivers):
        raise RuntimeError('Sun 的四个几何灯光驱动无效')
    visible = [o for o in parts.values() if not o.hide_render]
    for ob in visible:
        ev = ob.evaluated_get(__import__('bpy').context.evaluated_depsgraph_get())
        me = ev.to_mesh()
        try:
            for name in ('LightDirectionWS', 'LightColor', 'HeadCenter', 'HeadForward', 'HeadRight'):
                if name not in me.attributes:
                    raise RuntimeError(ob.name + ' 缺失属性 ' + name)
        finally:
            ev.to_mesh_clear()
    return {'verdict': 'pass', 'scope': 'shader resources/AOV/head-light attributes only; not collision or topology certificate',
            'render_parts': len(visible), 'active_packed_images': len(images), 'bones': len(arm.data.bones),
            'physics_built': bool(root.mmd_root.is_built)}
