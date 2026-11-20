"""Lightweight v3 authored-store regression; no PMX/configuration baseline needed.

Only run with the authoritative Goo Engine 4.4.3, in a disposable process::

    blender.exe \
        --background --factory-startup --disable-autoexec --python-exit-code 1 \
        --python tests/blender/blender_authored_guards.py

Loads validation.py in isolation, not the addon/workflow, so this suite can run
before a production-wide freeze. Creates only tiny synthetic Mesh/Key RNA. It
never opens/saves a blend, imports PMX, renders, or reads computed normal caches.
Fresh in-memory synthetic hashes are test expectations, NOT new stored baselines
for any existing output. Each edit must read back, change an independent snapshot
and mesh_state (or be an explicitly permitted runtime/UI edit), then restore.
Long real configured-artifact guards belong to blender_normal_guards.py after
source freeze. This suite does not claim workflow._existing or native split PASS.
"""
import ast
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys
import traceback
import uuid

sys.dont_write_bytecode = True
import bpy
import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1])); import testenv
from mathutils import Matrix

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'zzz_mmd_toon' / 'validation.py'
NORMAL_TEST = ROOT / 'tests' / 'blender' / 'blender_normal_guards.py'
AUTHORITATIVE_BLENDER = testenv.goo_exe()
SCHEMA = 'authored-mesh.v3-shape-attribute-uv-structure'


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def plain(value):
    if isinstance(value, (str, bytes, bool, int, float)) or value is None or hasattr(value, 'bl_rna'):
        return value
    return tuple(plain(item) for item in value)


def set_property(target, prop, value):
    # Goo 4.4 nested Python-sequence matrix assignment transposes RNA storage;
    # mathutils.Matrix preserves row/column identity in the native setter.
    current = getattr(target, prop)
    setattr(target, prop, Matrix(value) if isinstance(current, Matrix) else value)


def property_edits(changes):
    @contextmanager
    def apply():
        originals = [(target, prop, plain(getattr(target, prop))) for target, prop, _value in changes]
        require(any(old != plain(new) for (_, _, old), (_, _, new) in zip(originals, changes)), 'No proposed RNA mutation')
        try:
            for target, prop, value in changes:
                descriptor = target.bl_rna.properties[prop]
                require(not descriptor.is_readonly, 'Required real RNA property is read-only: ' + prop)
                set_property(target, prop, value)
                require(plain(getattr(target, prop)) == plain(value), 'RNA readback mismatch: ' + prop)
            yield {'properties': [prop for _target, prop, _value in changes]}
        finally:
            for target, prop, value in reversed(originals):
                if plain(getattr(target, prop)) != value:
                    set_property(target, prop, value)
                require(plain(getattr(target, prop)) == value, 'RNA restoration mismatch: ' + prop)
    return apply


def raw_values(attribute):
    field = ('color_srgb' if attribute.data_type == 'BYTE_COLOR' else 'color'
             if attribute.data_type == 'FLOAT_COLOR' else 'vector'
             if attribute.data_type in {'FLOAT_VECTOR', 'FLOAT2'} else 'value')
    return field, tuple(plain(getattr(item, field)) for item in attribute.data)


def independent_snapshot(parts):
    """Different representation from production hash; no production helpers used."""
    rows = []
    for slot, ob in sorted(parts.items()):
        mesh = ob.data
        attrs = []
        excluded = {'position', '.edge_verts', '.corner_vert', '.corner_edge', 'material_index',
                    '.select_vert', '.select_edge', '.select_poly', '.hide_vert', '.hide_edge', '.hide_poly'}
        excluded.update(prefix + layer.name for layer in mesh.uv_layers for prefix in ('.vs.', '.es.'))
        for attribute in sorted(mesh.attributes, key=lambda item: item.name):
            if attribute.name not in excluded:
                field, values = raw_values(attribute)
                attrs.append((attribute.name, attribute.data_type, attribute.domain, field, values))
        keys = mesh.shape_keys
        blocks = list(keys.key_blocks) if keys else []
        reference = lambda key: None if key is None else (blocks.index(key), key.name)
        shapes = None if keys is None else (
            keys.use_relative, reference(keys.reference_key),
            tuple((key.name, reference(key.relative_key), key.vertex_group, key.frame, key.interpolation,
                   key.lock_shape, tuple(tuple(item.co) for item in key.data)) for key in blocks))
        rows.append((slot,
                     tuple((group.name, bool(group.lock_weight)) for group in ob.vertex_groups),
                     tuple((tuple(vertex.co), tuple(sorted((ob.vertex_groups[g.group].name, float(g.weight))
                            for g in vertex.groups)))
                           for vertex in mesh.vertices),
                     tuple(tuple(edge.vertices) for edge in mesh.edges),
                     tuple((loop.vertex_index, loop.edge_index) for loop in mesh.loops),
                     tuple((poly.loop_start, poly.loop_total, poly.use_smooth, tuple(poly.vertices), poly.material_index)
                           for poly in mesh.polygons),
                     tuple(attrs), shapes, mesh.uv_layers.active_index,
                     tuple((uv.name, uv.active, uv.active_render, uv.active_clone) for uv in mesh.uv_layers),
                     mesh.color_attributes.default_color_name, mesh.color_attributes.render_color_index,
                     bool(mesh.has_custom_normals)))
    return tuple(rows)


def raw_store_snapshot(parts):
    """Includes UI/runtime fields too, to prove reads/restorations have no side effects."""
    return tuple((slot,
                  tuple((a.name, a.data_type, a.domain, raw_values(a))
                        for a in sorted(ob.data.attributes, key=lambda item: item.name)),
                  tuple((group.name, bool(group.lock_weight)) for group in ob.vertex_groups),
                  tuple(tuple((g.group, float(g.weight)) for g in vertex.groups) for vertex in ob.data.vertices),
                  None if ob.data.shape_keys is None else (
                      ob.data.shape_keys.eval_time,
                      tuple((k.name, k.value, k.mute, k.slider_min, k.slider_max) for k in ob.data.shape_keys.key_blocks)),
                  ob.active_shape_key_index, ob.show_only_shape_key)
                 for slot, ob in sorted(parts.items()))


def make_fixture(slot):
    mesh = bpy.data.meshes.new('AuthoredFixture_' + str(slot))
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, .25)], [], [(0, 1, 2), (1, 3, 2)])
    ob = bpy.data.objects.new(mesh.name, mesh)
    bpy.context.scene.collection.objects.link(ob)
    for name in ('Bone', 'Mask', 'Unused'):
        group = ob.vertex_groups.new(name=name)
        if name != 'Unused':
            group.add([0, 1, 2], .5 if name == 'Bone' else .25, 'REPLACE')
    for name in ('GN_Outline', 'OutlineMask'):
        ob.vertex_groups.new(name=name).add([0], .125, 'REPLACE')
    for index, name in enumerate(('UV_Main', 'UV_Secondary')):
        uv = mesh.uv_layers.new(name=name)
        for corner, item in enumerate(uv.data):
            item.uv = ((corner % 3) / 4, index / 4)
    mesh.uv_layers.active_index = 0
    mesh.uv_layers[0].active_render = True
    mesh.uv_layers[0].active_clone = True
    mesh.attributes.new('.pn.UV_Main', 'BOOLEAN', 'CORNER').data[0].value = True
    mesh.attributes.new('custom_normal', 'INT16_2D', 'CORNER')
    mesh.attributes['custom_normal'].data[0].value = (-24575, -24575)
    for name, domain in (('sharp_edge', 'EDGE'), ('sharp_face', 'FACE')):
        if mesh.attributes.get(name) is None:
            mesh.attributes.new(name, 'BOOLEAN', domain)
    for name, domain in (('crease_edge', 'EDGE'), ('crease_vert', 'POINT')):
        mesh.attributes.new(name, 'FLOAT', domain).data[0].value = .25
    types = [item.identifier for item in bpy.types.Attribute.bl_rna.properties['data_type'].enum_items]
    for data_type in types:
        mesh.attributes.new('Typed_' + data_type, data_type, 'POINT')
    for name in ('Color_A', 'Color_B'):
        mesh.color_attributes.new(name, 'BYTE_COLOR', 'CORNER')
    mesh.color_attributes.default_color_name = 'Color_A'
    mesh.color_attributes.render_color_index = list(mesh.color_attributes).index(mesh.color_attributes['Color_A'])
    basis = ob.shape_key_add(name='Basis')
    other = ob.shape_key_add(name='Expression')
    third = ob.shape_key_add(name='Secondary')
    other.data[0].co.z = .25
    third.data[1].co.z = .5
    other.vertex_group = 'Mask'
    third.relative_key = other
    require(basis.frame == 0 and other.frame == 10 and third.frame == 20, 'Unexpected synthetic key frame layout')
    return ob


class DenyNormalCache:
    def __init__(self, mesh):
        self.mesh = mesh

    def __getattr__(self, name):
        if name in {'corner_normals', 'vertex_normals', 'polygon_normals', 'calc_normals',
                    'calc_normals_split', 'calc_loop_triangles', 'update', 'normals_split_custom_set'}:
            raise AssertionError('Computed normal/cache access is forbidden: ' + name)
        return getattr(self.mesh, name)


class ObjectProxy:
    def __init__(self, ob):
        self.ob = ob
        self.data = DenyNormalCache(ob.data)

    def __getattr__(self, name):
        return getattr(self.ob, name)


class Suite:
    def __init__(self, validation, parts, report):
        self.validation, self.parts, self.report = validation, parts, report
        self.baseline = validation.mesh_state(parts)
        self.reference = independent_snapshot(parts)
        self.raw = raw_store_snapshot(parts)
        self.initial_ids = self.inventory()

    def inventory(self):
        return tuple((kind, tuple(item.as_pointer() for item in getattr(bpy.data, kind)))
                     for kind in ('objects', 'meshes', 'shape_keys', 'materials', 'images', 'actions'))

    def restored(self):
        require(independent_snapshot(self.parts) == self.reference, 'Independent authored structure did not restore')
        require(raw_store_snapshot(self.parts) == self.raw, 'Raw author/UI/runtime store did not restore exactly')
        require(self.validation.mesh_state(self.parts) == self.baseline, 'Strict v3 baseline did not restore')
        require(self.inventory() == self.initial_ids, 'Blender datablock inventory changed')

    def case(self, name, factory, allowed=False):
        case = {'name': name, 'status': 'running', 'expectation': 'allowed_runtime_or_UI' if allowed else 'strict_hash_changes'}
        self.report['cases'].append(case)
        before_raw = raw_store_snapshot(self.parts)
        try:
            with factory() as detail:
                case['target'] = detail
                after_reference = independent_snapshot(self.parts)
                require(raw_store_snapshot(self.parts) != before_raw or after_reference != self.reference,
                        name + ': no real RNA change')
                result = self.validation.mesh_state(self.parts)
                require((after_reference == self.reference) == allowed, name + ': independent snapshot disagreement')
                require((result == self.baseline) == allowed, name + ': production guard disagreement')
                case['changed_mesh_hash'] = result != self.baseline
                case['status'] = 'pass'
        except Exception as exc:
            case.update(status='fail', error=str(exc), traceback=traceback.format_exc())
            raise
        finally:
            self.restored()
            case['restored'] = True

    def property(self, name, target, prop, value, allowed=False):
        self.case(name, property_edits([(target, prop, value)]), allowed)

    def invalid_ui_layout(self, mesh, data_type, domain):
        name = 'invalid_UV_UI_layout_' + data_type + '_' + domain
        case = {'name': name, 'status': 'running', 'expectation': 'strict_layout_rejection'}
        self.report['cases'].append(case)
        before = raw_store_snapshot(self.parts)
        try:
            with self.temporary_attribute(mesh, '.vs.UV_Main', data_type, domain) as detail:
                case['target'] = detail
                require(raw_store_snapshot(self.parts) != before, 'Malformed UI-layer edit was not real RNA')
                try:
                    self.validation.mesh_state(self.parts)
                except RuntimeError as exc:
                    require('Invalid intrinsic/UI attribute layout' in str(exc), 'Wrong layout rejection: ' + str(exc))
                    case.update(status='pass', rejection=str(exc))
                else:
                    raise AssertionError('Malformed name-matched UI layer escaped the guard')
        except Exception as exc:
            case.update(status='fail', error=str(exc), traceback=traceback.format_exc())
            raise
        finally:
            self.restored()
            case['restored'] = True

    def normal_helper_audit(self):
        """Exercise WIP test helpers on tiny real RNA, never its frozen-artifact main."""
        before = sha256(NORMAL_TEST)
        spec = importlib.util.spec_from_file_location('_independent_normal_guard_helpers', NORMAL_TEST)
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        snapshots = {slot: helper.normal_snapshot(ob.data) for slot, ob in self.parts.items()}
        for slot, snapshot in snapshots.items():
            require(helper.reference_normal_hash(snapshot) == self.validation.normal_inputs(self.parts[slot].data),
                    'WIP normal helper reference disagrees with production full stream')
        other = helper.strict_other_hash(self.parts)
        checked = []
        for slot, ob in self.parts.items():
            mesh = ob.data
            # Index 0 is a genuine cancellation witness; the final pair is a
            # genuine (0,0). Probe both components and retain every original pair.
            for index in (0, len(mesh.loops) - 1):
                original = tuple(mesh.attributes['custom_normal'].data[index].value)
                require(original == ((-24575, -24575) if index == 0 else (0, 0)), 'Wrong real short2 fixture')
                for component in (0, 1):
                    value = list(original)
                    value[component] ^= 1
                    name = 'normal_helper_short2_part_%d_corner_%d_component_%d' % (slot, index, component)
                    @contextmanager
                    def probe(m=mesh, s=slot, i=index, pair=tuple(value), c=component):
                        with helper.edits([(m.attributes['custom_normal'].data[i], 'value', pair)],
                                          {'slot': s, 'corner': i, 'component': c, 'pair': pair}) as detail:
                            current = {part: helper.normal_snapshot(obj.data) for part, obj in self.parts.items()}
                            require([part for part in current if current[part] != snapshots[part]] == [s],
                                    'WIP full-array snapshot missed/changed the wrong part')
                            require(helper.reference_normal_hash(current[s]) == self.validation.normal_inputs(m),
                                    'WIP reference stream disagreed after actual short2 edit')
                            require(helper.reference_normal_hash(current[s]) != helper.reference_normal_hash(snapshots[s]),
                                    'WIP reference missed original zero/cancellation short2 component')
                            require(helper.strict_other_hash(self.parts) == other, 'Normal helper contaminated nonnormal store')
                            yield detail
                        require({part: helper.normal_snapshot(obj.data) for part, obj in self.parts.items()} == snapshots,
                                'WIP normal helper did not restore complete arrays')
                    self.case(name, probe)
                    checked.append(name)
        require(sha256(NORMAL_TEST) == before, 'WIP normal test changed during helper audit')
        tree = ast.parse(NORMAL_TEST.read_text(encoding='utf-8'))
        require(not any(isinstance(node, ast.Attribute) and node.attr == 'corner_normals' for node in ast.walk(tree)),
                'WIP normal suite accesses computed corner_normals')
        self.report['normal_test_helper_audit'] = {
            'test': str(NORMAL_TEST), 'sha256_before': before, 'sha256_after': sha256(NORMAL_TEST),
            'cases': checked, 'parts': len(self.parts),
            'all_short2_pairs': sum(len(item['attributes']['custom_normal'][1]) for item in snapshots.values()),
            'original_zero_pairs': sum(item['attributes']['custom_normal'][1].count((0, 0)) for item in snapshots.values()),
            'static_no_computed_corner_normals': True,
            'limit': 'Pure helpers on real tiny synthetic RNA only; no workflow._existing, artifact load or production-wide hash freeze main executed'}

    @contextmanager
    def attribute_layout(self, mesh, name, data_type=None, domain=None, absent=False):
        original = mesh.attributes[name]
        old_type, old_domain = original.data_type, original.domain
        field, values = raw_values(original)
        try:
            mesh.attributes.remove(original)
            if not absent:
                replacement = mesh.attributes.new(name, data_type or old_type, domain or old_domain)
                require(replacement.name == name, 'Attribute replacement renamed')
            yield {'attribute': name, 'before': (old_type, old_domain), 'after': None if absent else (data_type or old_type, domain or old_domain)}
        finally:
            current = mesh.attributes.get(name)
            if current:
                mesh.attributes.remove(current)
            restored = mesh.attributes.new(name, old_type, old_domain)
            for item, value in zip(restored.data, values):
                set_property(item, field, value)

    @contextmanager
    def temporary_attribute(self, mesh, name, data_type='FLOAT', domain='POINT'):
        require(mesh.attributes.get(name) is None, 'Temporary attribute already exists')
        try:
            attribute = mesh.attributes.new(name, data_type, domain)
            require(attribute.name == name, 'Temporary attribute renamed')
            attribute.data[0].value = True if data_type == 'BOOLEAN' else .5
            yield {'attribute': name, 'added': True, 'type': data_type, 'domain': domain}
        finally:
            if mesh.attributes.get(name):
                mesh.attributes.remove(mesh.attributes[name])

    @contextmanager
    def append_shape(self, ob):
        key = ob.shape_key_add(name='Temporary_Shape')
        try:
            require(key.name == 'Temporary_Shape', 'Temporary key renamed')
            yield {'shape': key.name, 'added': True}
        finally:
            ob.shape_key_remove(key)

    @contextmanager
    def retime_shape(self, ob):
        keys = ob.data.shape_keys
        old_mode, old_time = keys.use_relative, keys.eval_time
        old_frames = tuple(key.frame for key in keys.key_blocks)
        require(old_frames == (0, 10, 20), 'Frame retime fixture must start evenly spaced')
        try:
            # `frame` is read-only RNA. Native operator writes real absolute-key
            # timing; first retime normalizes a genuinely different last frame.
            keys.use_relative = False
            keys.eval_time = 41
            temporary = ob.shape_key_add(name='Frame_Probe')
            require(temporary.frame == 41, 'New absolute key did not use eval_time')
            ob.shape_key_remove(temporary)
            # Need an existing nonuniform frame without changing key topology:
            # recreate ONLY the last synthetic key with identical stable payload.
            last = keys.key_blocks[-1]
            data = [tuple(item.co) for item in last.data]
            state = (last.name, last.relative_key, last.vertex_group, last.interpolation, last.lock_shape)
            ob.shape_key_remove(last)
            last = ob.shape_key_add(name=state[0])
            for item, co in zip(last.data, data):
                item.co = co
            last.relative_key, last.vertex_group, last.interpolation, last.lock_shape = state[1:]
            keys.eval_time, keys.use_relative = old_time, old_mode
            require(tuple(key.frame for key in keys.key_blocks) == (0, 10, 41), 'Real authored frame did not change')
            yield {'property': 'ShapeKey.frame', 'RNA_readonly': True, 'method': 'replace synthetic absolute last key, preserve name/coords/reference',
                   'before': old_frames, 'after': tuple(key.frame for key in keys.key_blocks)}
        finally:
            keys.use_relative = False
            bpy.context.view_layer.objects.active = ob
            ob.select_set(True)
            require(bpy.ops.object.shape_key_retime() == {'FINISHED'}, 'Native shape_key_retime failed')
            keys.use_relative, keys.eval_time = old_mode, old_time
            require(tuple(key.frame for key in keys.key_blocks) == old_frames, 'Authored frames did not restore')

    @contextmanager
    def shape_order(self, ob):
        old = ob.active_shape_key_index
        bpy.context.view_layer.objects.active = ob
        ob.select_set(True)
        ob.active_shape_key_index = 1
        try:
            require(bpy.ops.object.shape_key_move(type='DOWN') == {'FINISHED'}, 'Real shape order edit failed')
            yield {'method': 'native shape_key_move DOWN', 'keys': [key.name for key in ob.data.shape_keys.key_blocks]}
        finally:
            require(bpy.ops.object.shape_key_move(type='UP') == {'FINISHED'}, 'Shape order restoration failed')
            ob.active_shape_key_index = old

    @contextmanager
    def uv_flag(self, mesh, prop, index):
        # active_render/active_clone are one-hot identity selectors. Assigning
        # False is ignored by RNA, so restore via the original True selector.
        originals = tuple(bool(getattr(layer, prop)) for layer in mesh.uv_layers)
        require(sum(originals) == 1 and not originals[index], 'UV selector fixture must really change')
        try:
            setattr(mesh.uv_layers[index], prop, True)
            require(getattr(mesh.uv_layers[index], prop), 'UV flag write/readback failed')
            yield {'UV': mesh.uv_layers[index].name, 'property': prop, 'before': originals}
        finally:
            setattr(mesh.uv_layers[originals.index(True)], prop, True)
            require(tuple(bool(getattr(layer, prop)) for layer in mesh.uv_layers) == originals,
                    'UV identity flags did not restore')

    @contextmanager
    def uv_removal(self, mesh):
        old_active = mesh.uv_layers.active_index
        layer = mesh.uv_layers[-1]
        name = layer.name
        require(not layer.active_render and not layer.active_clone and old_active != len(mesh.uv_layers) - 1,
                'Removal fixture must not alias active/render/clone selection')
        field, values = raw_values(mesh.attributes[name])
        require(not any(mesh.attributes.get(prefix + name) for prefix in ('.vs.', '.es.', '.pn.')),
                'Removal fixture unexpectedly has auxiliary layers')
        try:
            mesh.uv_layers.remove(layer)
            require(mesh.uv_layers.get(name) is None and mesh.attributes.get(name) is None,
                    'Real UV layer removal did not remove backing attribute')
            yield {'UV': name, 'removed': True, 'corners': len(values)}
        finally:
            restored = mesh.uv_layers.new(name=name)
            require(restored.name == name, 'UV restoration renamed')
            for item, value in zip(mesh.attributes[name].data, values):
                set_property(item, field, value)
            mesh.uv_layers.active_index = old_active

    @contextmanager
    def uv_order(self, mesh):
        names = [layer.name for layer in mesh.uv_layers]
        require(len(names) == 2, 'UV-order fixture must contain exactly two layers')
        active = mesh.uv_layers.active.name
        render = next(layer.name for layer in mesh.uv_layers if layer.active_render)
        clone = next(layer.name for layer in mesh.uv_layers if layer.active_clone)
        records = {name: (attribute.data_type, attribute.domain, *raw_values(attribute))
                   for name in [name for uv in names for name in (uv, '.pn.' + uv, '.vs.' + uv, '.es.' + uv)]
                   if (attribute := mesh.attributes.get(name)) is not None}

        def rebuild(order):
            # Removing a CustomData layer invalidates other RNA layer handles;
            # reacquire each current tail instead of retaining stale references.
            while mesh.uv_layers:
                mesh.uv_layers.remove(mesh.uv_layers[-1])
            for name in order:
                require(mesh.uv_layers.new(name=name).name == name, 'UV order recreation renamed')
            for name, (data_type, domain, field, values) in records.items():
                attribute = mesh.attributes.get(name) or mesh.attributes.new(name, data_type, domain)
                require((attribute.data_type, attribute.domain) == (data_type, domain), 'UV auxiliary layout changed')
                for item, value in zip(attribute.data, values):
                    set_property(item, field, value)
            mesh.uv_layers.active_index = list(order).index(active)
            mesh.uv_layers[render].active_render = True
            mesh.uv_layers[clone].active_clone = True

        try:
            rebuild(list(reversed(names)))
            require([layer.name for layer in mesh.uv_layers] == list(reversed(names)), 'UV order did not change')
            yield {'before': names, 'after': [layer.name for layer in mesh.uv_layers],
                   'method': 'recreate synthetic UV layers in reverse order with identical named payloads/selectors'}
        finally:
            rebuild(names)

    @contextmanager
    def uv_addition(self, mesh):
        old_active = mesh.uv_layers.active_index
        layer = mesh.uv_layers.new(name='Temporary_UV')
        try:
            yield {'UV': layer.name, 'added': True}
        finally:
            mesh.uv_layers.remove(layer)
            mesh.uv_layers.active_index = old_active

    def execute(self):
        validation = self.validation
        require(validation.MESH_GUARD_SCHEMA == SCHEMA, 'Explicit v3 schema mismatch')
        require(self.baseline == validation.mesh_state(dict(reversed(list(self.parts.items())))), 'Part ordering must be canonical')
        before_raw = raw_store_snapshot(self.parts)
        proxied = {slot: ObjectProxy(ob) for slot, ob in self.parts.items()}
        require(validation.mesh_state(proxied) == self.baseline, 'No-cache proxy changed authored hash')
        for _index in range(3):
            require(validation.mesh_state(self.parts) == self.baseline, 'Repeated pure read changed hash')
        require(raw_store_snapshot(self.parts) == before_raw, 'Guard read created/modified attribute storage')
        self.report['read_only_guard'] = {'normal_cache_trap': 'pass', 'repeated_reads': 4, 'raw_storage_unchanged': True}
        self.normal_helper_audit()
        for slot, ob in self.parts.items():
            key = ob.data.shape_keys.key_blocks[1]
            self.property('relative_key_part_' + str(slot), key, 'relative_key', ob.data.shape_keys.key_blocks[2])
        ob = self.parts[0]
        mesh, keys = ob.data, ob.data.shape_keys
        key = keys.key_blocks[1]
        self.property('shape_vertex_group', key, 'vertex_group', 'Bone')
        self.property('shape_use_relative', keys, 'use_relative', False)
        self.property('shape_interpolation', key, 'interpolation', 'KEY_CARDINAL')
        self.property('shape_lock_shape', key, 'lock_shape', True)
        self.property('shape_rename', key, 'name', 'Renamed_Expression')
        self.property('shape_coordinate', key.data[0], 'co', (0, 0, .5))
        self.case('shape_key_addition', lambda: self.append_shape(ob))
        self.case('shape_key_order_reference', lambda: self.shape_order(ob))
        self.case('shape_frame_real_absolute_storage', lambda: self.retime_shape(ob))
        self.property('shape_value_allowed', keys.key_blocks[1], 'value', .5, allowed=True)
        self.property('shape_eval_time_allowed', keys, 'eval_time', 7.5, allowed=True)
        self.property('native_VMD_slider_min_allowed', keys.key_blocks[1], 'slider_min', -2.0, allowed=True)
        self.property('native_VMD_slider_max_allowed', keys.key_blocks[1], 'slider_max', 2.0, allowed=True)
        self.property('native_Morph_SDEF_mute_allowed', keys.key_blocks[1], 'mute', True, allowed=True)
        self.property('active_shape_key_UI_allowed', ob, 'active_shape_key_index', 1, allowed=True)
        self.property('show_only_shape_key_UI_allowed', ob, 'show_only_shape_key', True, allowed=True)
        for data_type in [item.identifier for item in bpy.types.Attribute.bl_rna.properties['data_type'].enum_items]:
            attribute = mesh.attributes['Typed_' + data_type]
            field, _values = raw_values(attribute)
            old = plain(getattr(attribute.data[0], field))
            if data_type == 'STRING':
                value = b'author\xff-bytes'
            elif data_type == 'BOOLEAN':
                value = not old
            elif data_type in {'INT', 'INT8'}:
                value = 1
            elif data_type in {'FLOAT', 'INT16_2D', 'INT32_2D', 'FLOAT_VECTOR', 'FLOAT2', 'FLOAT_COLOR', 'QUATERNION'}:
                value = .25 if isinstance(old, float) else tuple((1 if 'INT' in data_type else .25) if i == 0 else v for i, v in enumerate(old))
            elif data_type == 'BYTE_COLOR':
                value = tuple((0.0 if v else 1.0) if i == 0 else v for i, v in enumerate(old))
            elif data_type == 'FLOAT4X4':
                value = tuple(tuple(.25 if (i, j) == (0, 1) else v for j, v in enumerate(row)) for i, row in enumerate(old))
            else:
                raise AssertionError('Test has no type coverage: ' + data_type)
            self.property('typed_attribute_' + data_type, attribute.data[0], field, value)
        # Adjacent IEEE32 and uchar values must not be rounded into equivalence.
        float32 = lambda value: struct.unpack('<f', struct.pack('<f', value))[0]
        adjacent_float = struct.unpack('<f', struct.pack('<I', 0x3f800001))[0]
        for name in ('Typed_FLOAT', 'crease_edge'):
            attribute = mesh.attributes[name]
            old = float(attribute.data[0].value)
            @contextmanager
            def lowbit_float(a=attribute, original=old):
                try:
                    a.data[0].value = 1.0
                    before = validation.mesh_state(self.parts)
                    a.data[0].value = adjacent_float
                    require(a.data[0].value == adjacent_float, 'Adjacent float32 did not read back')
                    require(validation.mesh_state(self.parts) != before, 'Adjacent authored float32 bits escaped')
                    yield {'attribute': a.name, 'before_bits': '3f800000', 'after_bits': '3f800001'}
                finally:
                    a.data[0].value = original
            self.case('adjacent_float32_' + name, lowbit_float)
        byte_color = mesh.attributes['Typed_BYTE_COLOR'].data[0]
        old_color = tuple(byte_color.color_srgb)
        @contextmanager
        def lowbit_color():
            try:
                byte_color.color_srgb = (1., 0., 0., 1.)
                before = validation.mesh_state(self.parts)
                byte_color.color_srgb = (float32(254 / 255), 0., 0., 1.)
                require(tuple(byte_color.color_srgb) == (float32(254 / 255), 0., 0., 1.), 'Adjacent byte color readback failed')
                require(validation.mesh_state(self.parts) != before, 'Adjacent BYTE_COLOR storage escaped')
                yield {'attribute': 'Typed_BYTE_COLOR', 'before_byte': 255, 'after_byte': 254}
            finally:
                byte_color.color_srgb = old_color
        self.case('adjacent_byte_color_original_uchar', lowbit_color)
        self.property('crease_edge_value', mesh.attributes['crease_edge'].data[0], 'value', .5)
        self.property('crease_vert_value', mesh.attributes['crease_vert'].data[0], 'value', .5)
        self.property('stable_attribute_rename', mesh.attributes['Typed_FLOAT'], 'name', 'Renamed_FLOAT')
        self.case('stable_attribute_domain', lambda: self.attribute_layout(mesh, 'Typed_FLOAT', domain='FACE'))
        self.case('stable_attribute_type', lambda: self.attribute_layout(mesh, 'Typed_FLOAT', data_type='INT'))
        self.case('stable_attribute_removal', lambda: self.attribute_layout(mesh, 'Typed_FLOAT', absent=True))
        for name in ('Added_Author', '.unknown_author', '.material_index', 'ZZZSplit_untrusted', '.select_custom', '.vs.NotAnExistingUV'):
            self.case('stable_attribute_addition_' + name, lambda n=name: self.temporary_attribute(mesh, n))
        self.property('UV_coordinate', mesh.uv_layers[0].data[0], 'uv', (.5, .25))
        self.property('UV_active_index', mesh.uv_layers, 'active_index', 1)
        self.case('UV_active_render', lambda: self.uv_flag(mesh, 'active_render', 1))
        self.case('UV_active_clone', lambda: self.uv_flag(mesh, 'active_clone', 1))
        self.property('UV_name', mesh.uv_layers[1], 'name', 'Renamed_UV')
        self.property('UV_pin_authored', mesh.attributes['.pn.UV_Main'].data[0], 'value', False)
        self.case('UV_addition', lambda: self.uv_addition(mesh))
        self.case('UV_removal', lambda: self.uv_removal(mesh))
        self.case('UV_ordered_identity', lambda: self.uv_order(mesh))
        for data_type, domain in (('FLOAT', 'CORNER'), ('BOOLEAN', 'POINT')):
            self.invalid_ui_layout(mesh, data_type, domain)
        self.property('color_default_render_identity', mesh.color_attributes, 'default_color_name', 'Color_B')
        color_b_index = list(mesh.color_attributes).index(mesh.color_attributes['Color_B'])
        self.property('color_render_index', mesh.color_attributes, 'render_color_index', color_b_index)
        for name, domain in (('.select_vert', 'POINT'), ('.select_edge', 'EDGE'), ('.select_poly', 'FACE'),
                             ('.hide_vert', 'POINT'), ('.hide_edge', 'EDGE'), ('.hide_poly', 'FACE'),
                             ('.vs.UV_Main', 'CORNER'), ('.es.UV_Main', 'CORNER')):
            attribute = mesh.attributes.get(name)
            if attribute:
                self.property('transient_UI_' + name, attribute.data[0], 'value', not attribute.data[0].value, allowed=True)
            else:
                self.case('transient_UI_addition_' + name,
                          lambda n=name, d=domain: self.temporary_attribute(mesh, n, 'BOOLEAN', d), allowed=True)
        for name in ('Bone', 'GN_Outline', 'OutlineMask'):
            group = ob.vertex_groups[name]
            @contextmanager
            def group_weight(g=group):
                old = g.weight(0)
                try:
                    value = .25 if old == .5 else .5
                    g.add([0], value, 'REPLACE')
                    require(g.weight(0) == value, 'Author group weight edit failed')
                    yield {'authored_group': g.name, 'weight': value}
                finally:
                    g.add([0], old, 'REPLACE')
            # Names that resemble renderer masks are still original author data.
            self.case('authored_group_weight_' + name, group_weight)
        unused = ob.vertex_groups['Unused']
        self.property('unused_authored_vertex_group_name', unused, 'name', 'Changed_Unused')
        self.property('unused_authored_vertex_group_lock', unused, 'lock_weight', True)
        @contextmanager
        def zero_membership():
            try:
                unused.add([3], 0.0, 'REPLACE')
                require(any(g.group == unused.index and g.weight == 0.0 for g in mesh.vertices[3].groups),
                        'Zero-weight membership was not physically stored')
                yield {'authored_group': unused.name, 'vertex': 3, 'stored_zero_weight': True}
            finally:
                unused.remove([3])
        self.case('authored_group_explicit_zero_weight_membership', zero_membership)
        @contextmanager
        def group_addition():
            group = ob.vertex_groups.new(name='New_Unused_Author')
            try:
                require(group.name == 'New_Unused_Author', 'New author group renamed')
                yield {'authored_group': group.name, 'added': True}
            finally:
                ob.vertex_groups.remove(group)
        self.case('authored_group_addition_without_weights', group_addition)
        self.restored()
        try:
            validation.semantic_slots(None, None)
        except RuntimeError as exc:
            require('serialized provenance' in str(exc), 'Legacy helper rejected for wrong reason')
            self.report['legacy_rounded_helper_fail_closed'] = str(exc)
        else:
            raise AssertionError('Retired semantic_slots path must fail closed')
        # Static evidence includes ALL Attribute nodes, not a text-comment search.
        tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
        forbidden = [node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute) and node.attr == 'corner_normals']
        require(not forbidden, 'Production still accesses computed corner_normals')
        self.report['static_no_computed_corner_normals'] = True
        self.report['synthetic_mesh_hash'] = self.baseline
        self.report['parts'] = len(self.parts)
        self.report['attribute_types_covered'] = [item.identifier for item in bpy.types.Attribute.bl_rna.properties['data_type'].enum_items]


def main():
    directory = ROOT / 'test_outputs' / 'authored_guards' / (datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '_' + uuid.uuid4().hex[:8])
    directory.mkdir(parents=True, exist_ok=False)
    report = {'status': 'running', 'schema': SCHEMA, 'started_utc': datetime.now(timezone.utc).isoformat(),
              'binary': bpy.app.binary_path, 'version': bpy.app.version_string, 'cases': [],
              'source': str(SOURCE), 'source_sha256_before': sha256(SOURCE), 'test_sha256': sha256(__file__),
              'limits': ['Tiny synthetic RNA only, not configured-character/native split/workflow acceptance',
                         'No production-wide hash freeze required; only this validation module is loaded and protected',
                         'No PMX or blend opened/saved, no rendering, no stored baseline updates, no computed normal cache reads',
                         'key.value/eval_time are live animation inputs, not structural guard fields',
                         'slider_min/max and mute stay live: MMD Tools core/vmd/importer.py:509-510, core/morph.py:423-431, core/sdef.py:62',
                         'Mesh/UV selection/hide editor state excluded; UV pin/default/render/clone and custom named attributes protected',
                         'Every original vertex group name/lock/weight is protected, including GN_Outline/OutlineMask and stored zero weights']}
    failure = None
    forbidden_operations = []

    def forbid(*_args, **_kwargs):
        forbidden_operations.append('save/render attempted')
        raise AssertionError('Independent authored guard tests must never save/render')

    try:
        require(bpy.app.version == (4, 4, 3) and 'Goo' in bpy.app.version_string and
                Path(bpy.app.binary_path).resolve() == AUTHORITATIVE_BLENDER.resolve(), 'Wrong Blender engine/binary')
        bpy.app.handlers.save_pre.append(forbid)
        bpy.app.handlers.render_pre.append(forbid)
        spec = importlib.util.spec_from_file_location('_independent_authored_validation', SOURCE)
        validation = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(validation)
        parts = {slot: make_fixture(slot) for slot in (0, 1)}
        Suite(validation, parts, report).execute()
        require(not forbidden_operations, 'Forbidden save/render attempted')
        report['status'] = 'pass_synthetic_authored_v3'
    except Exception as exc:
        report.update(status='fail', error=str(exc), traceback=traceback.format_exc())
        failure = (exc, exc.__traceback__)
    finally:
        for handlers in (bpy.app.handlers.save_pre, bpy.app.handlers.render_pre):
            if forbid in handlers:
                handlers.remove(forbid)
        report['forbidden_operations'] = forbidden_operations
        report['source_sha256_after'] = sha256(SOURCE)
        report['source_unchanged'] = report['source_sha256_before'] == report['source_sha256_after']
        if not report['source_unchanged']:
            report['status'] = 'fail'
            report['hash_error'] = 'validation.py changed during independent test'
            if failure is None:
                failure = (AssertionError(report['hash_error']), None)
        report['case_totals'] = {status: sum(case.get('status') == status for case in report['cases'])
                                 for status in ('pass', 'skip', 'fail', 'running')}
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        text = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
        destination = directory / 'guards.json'
        destination.write_text(text, encoding='utf-8')
        (directory.parent / 'latest.json').write_text(text, encoding='utf-8')
        print('HEADLESS ' + json.dumps({'status': report['status'], 'cases': report['case_totals'],
                                        'error': report.get('error'), 'report': str(destination)}, ensure_ascii=False), flush=True)
    if failure:
        raise failure[0].with_traceback(failure[1])


if __name__ == '__main__':
    main()
