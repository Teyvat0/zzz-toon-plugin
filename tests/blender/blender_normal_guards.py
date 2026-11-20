"""TEST ONLY: serialized authored-normal guards; real RNA edits, never save/render.

Parent-run entry (authoritative Goo Engine 4.4.3, disposable process)::

    blender.exe \
        --background --factory-startup --disable-autoexec --python-exit-code 1 \
        --python tests/blender/blender_normal_guards.py \
        -- evelyn [--artifact ABSOLUTE_GENERATED_TEST_BLEND]

``astra`` selects the other latest.json. Explicit artifacts must be configuration
or native-physics outputs inside test_outputs/<kind> or motion/<kind>, never an
original/checkpoint. New-schema artifacts must already pass: no import, migration,
normal recalculation, baseline repair, PMX import, physics build, save or render.
Only legacy-schema cases temporarily change ROOT zzz_run metadata; its exact
original string is restored. No scene metadata or stored mesh/shader hash changes.

Full-array independent serialization includes EVERY short2 of EVERY native part,
including (0, 0), not a nonzero-only sample. Every mutation/restoration compares
all parts against that reference. General short2 cases use two structurally chosen
parts; sharp/smooth/topology cases use one representative part, not 21/31 copies
of the same whole-model guard. ALL real (-24575, -24575) pairs across ALL parts
are individually mutated: this superset replaces Evelyn's four obsolete global
corner indices, with the local geometry and complete hit list recorded as evidence.
No pair is synthesized or normal recalculated. Read-only topology RNA is an
explicit SKIP, never a simulated mutation; required short2 writes cannot skip.
Native Alpha/Diffuse remain permitted. Selection uses no material/character names.
Fixture note: mmd_tools quantises some Evelyn corner normals differently per import, so a
fresh latest.json run holds 0..4 (-24575, -24575) pairs. The four-witness check needs a
run that kept all four: pin it with --artifact (a 4-pair run was verified 21/21 pass).
Results only: test_outputs/normal_guards/<unique>/guards.json and latest.json.
Source author only compiles this file; Blender execution belongs to the parent.
"""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib
import json
from pathlib import Path
import struct
import sys
import traceback
import uuid

sys.dont_write_bytecode = True
import bpy
import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1])); import testenv

ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = ROOT / 'test_outputs'
SCHEMA = 'authored-mesh.v3-shape-attribute-uv-structure'
AUTHORITATIVE_BLENDER = testenv.goo_exe()
MMD_PARENT = testenv.mmd_parent()
ATTRIBUTES = (('custom_normal', 'INT16_2D', 'CORNER'),
              ('sharp_edge', 'BOOLEAN', 'EDGE'), ('sharp_face', 'BOOLEAN', 'FACE'))
CANCEL_PAIR = (-24575, -24575)  # Test-only raw storage witness, never a decoded/generated normal.
MESH_ERROR = '原骨 rest/网格/渲染挂接被外部修改'
LEGACY_ERROR = '这是旧版配置或旧守卫格式'


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def inside(path, directory):
    return path == directory or directory in path.parents


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', nargs='?', choices=('evelyn', 'astra'), default='evelyn')
    parser.add_argument('--artifact', type=Path)
    return parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])


def fixture(args, report):
    latest = OUTPUTS / args.kind / 'latest.json'
    if args.artifact is None:
        report['protected_hashes'][str(latest)] = sha256(latest)
        metadata = json.loads(latest.read_text(encoding='utf-8'))
        artifact = metadata.get('artifact')
        require(isinstance(artifact, dict) and artifact.get('path'), 'latest.json has no artifact.path; no fallback or rebaseline')
        path = Path(artifact['path'])
        report['latest'] = {'path': str(latest), 'status': metadata.get('status'), 'artifact': artifact}
    else:
        path, artifact = args.artifact, None
    require(path.is_absolute(), 'Artifact must be an absolute generated-test path')
    path = path.resolve(strict=True)
    allowed = [(OUTPUTS / args.kind).resolve(), (OUTPUTS / 'motion' / args.kind).resolve()]
    require(any(inside(path, folder) and path.parent != folder for folder in allowed), 'Refusing non-test artifact: ' + str(path))
    require(path.is_file() and path.name in {'仿ZZZ渲染_通用配置.blend', '仿ZZZ渲染_含原生物理.blend'},
            'Refusing original/checkpoint/non-configuration file: ' + str(path))
    actual = sha256(path)
    if artifact and artifact.get('sha256'):
        require(actual == artifact['sha256'], 'Published artifact SHA differs; no repair permitted')
    report['artifact'] = {'path': str(path), 'sha256_before': actual, 'bytes': path.stat().st_size}
    report['protected_hashes'][str(path)] = actual
    return path


def addons(report):
    for package in (ROOT / 'zzz_mmd_toon', MMD_PARENT / 'mmd_tools'):
        require(package.is_dir(), 'Required source package missing: ' + str(package))
        for path in sorted(package.rglob('*.py')):
            report['protected_hashes'][str(path.resolve())] = sha256(path)
    sys.path.insert(0, str(ROOT))
    addon = importlib.import_module('zzz_mmd_toon')
    require(Path(addon.__file__).resolve() == (ROOT / 'zzz_mmd_toon' / '__init__.py').resolve(), 'Wrong addon package loaded')
    if not hasattr(bpy.types.Scene, 'zzz_toon'):
        addon.register()
    sys.path.insert(0, str(MMD_PARENT))
    mmd = importlib.import_module('mmd_tools')
    require(inside(Path(mmd.__file__).resolve(), (MMD_PARENT / 'mmd_tools').resolve()), 'Wrong MMD Tools loaded')
    if not hasattr(bpy.types.PoseBone, 'mmd_bone'):
        mmd.register()
    return tuple(importlib.import_module('zzz_mmd_toon.' + name) for name in ('workflow', 'validation', 'mmd_adapter', 'renderer'))


@contextmanager
def no_commits(workflow, report):
    original = {name: getattr(workflow, name) for name in ('_save_new', '_render')}

    def reject(*_args, **_kwargs):
        report['forbidden_operations'].append('save/render attempted')
        raise AssertionError('Normal guard test must not save/render')

    for name in original:
        setattr(workflow, name, reject)
    bpy.app.handlers.save_pre.append(reject)
    bpy.app.handlers.render_pre.append(reject)
    try:
        yield
    finally:
        for name, function in original.items():
            setattr(workflow, name, function)
        for handlers in (bpy.app.handlers.save_pre, bpy.app.handlers.render_pre):
            if reject in handlers:
                handlers.remove(reject)


def normal_snapshot(mesh):
    """No corner_normals/vertex-normal cache reads, writes, normalization or update."""
    attributes = {}
    for name, data_type, domain in ATTRIBUTES:
        attribute = mesh.attributes.get(name)
        if attribute is None:
            attributes[name] = None
            continue
        require((attribute.data_type, attribute.domain) == (data_type, domain), 'Unsupported real attribute: ' + name)
        values = (tuple(tuple(int(c) for c in item.value) for item in attribute.data) if data_type == 'INT16_2D'
                  else tuple(bool(item.value) for item in attribute.data))
        attributes[name] = ((attribute.data_type, attribute.domain, len(attribute.data)), values)
    return {'counts': (len(mesh.vertices), len(mesh.edges), len(mesh.loops), len(mesh.polygons)),
            'edges': tuple(tuple(edge.vertices) for edge in mesh.edges),
            'corners': tuple((loop.vertex_index, loop.edge_index) for loop in mesh.loops),
            'polygons': tuple((poly.loop_start, poly.loop_total, poly.use_smooth) for poly in mesh.polygons),
            'attributes': attributes}


def reference_normal_hash(snapshot):
    """Independent full stream, including zero pairs and both components of ALL short2."""
    h = hashlib.sha256()
    h.update(json.dumps(('normal-inputs.v1', *snapshot['counts']), separators=(',', ':')).encode('ascii'))
    for row in snapshot['edges']:
        h.update(struct.pack('<2i', *row))
    for row in snapshot['corners']:
        h.update(struct.pack('<2i', *row))
    for row in snapshot['polygons']:
        h.update(struct.pack('<2i?', *row))
    for name, data_type, _domain in ATTRIBUTES:
        attribute = snapshot['attributes'][name]
        h.update(json.dumps((name, None if attribute is None else attribute[0]), separators=(',', ':')).encode('utf-8'))
        if attribute is not None:
            for value in attribute[1]:  # Intentionally NO `if value != (0, 0)` filter.
                h.update(struct.pack('<2h', *value) if data_type == 'INT16_2D' else struct.pack('<?', value))
    return h.hexdigest()


def strict_other_hash(parts):
    """Independent non-normal author snapshot, now including v3 structure/layers."""
    h = hashlib.sha256()

    def plain(value):
        if isinstance(value, (str, bytes, bool, int, float)) or value is None:
            return value
        return tuple(plain(item) for item in value)

    for slot, ob in sorted(parts.items()):
        mesh = ob.data
        h.update(repr((slot, ob.name, mesh.name, [(group.name, bool(group.lock_weight)) for group in ob.vertex_groups],
                       [(mat.name, int(mat.mmd_material.material_id)) if mat else None for mat in mesh.materials])).encode('utf-8'))
        for vertex in mesh.vertices:
            h.update(struct.pack('<3f', *vertex.co))
            h.update(repr(sorted((group.group, float(group.weight)) for group in vertex.groups)).encode('ascii'))
        for poly in mesh.polygons:
            h.update(struct.pack('<i', poly.material_index))
        uv_selection = {prefix + uv.name for uv in mesh.uv_layers for prefix in ('.vs.', '.es.')}
        excluded = {'position', '.edge_verts', '.corner_vert', '.corner_edge', 'material_index',
                    '.select_vert', '.select_edge', '.select_poly', '.hide_vert', '.hide_edge', '.hide_poly',
                    *(name for name, _type, _domain in ATTRIBUTES)} | uv_selection
        for attribute in sorted(mesh.attributes, key=lambda item: item.name):
            if attribute.name in excluded:
                continue
            h.update(repr((attribute.name, attribute.data_type, attribute.domain, len(attribute.data))).encode('utf-8'))
            for item in attribute.data:
                field = ('color_srgb' if attribute.data_type == 'BYTE_COLOR' else 'color'
                         if attribute.data_type == 'FLOAT_COLOR' else 'vector'
                         if attribute.data_type in {'FLOAT2', 'FLOAT_VECTOR'} else 'value')
                h.update(repr(plain(getattr(item, field))).encode('utf-8'))
        h.update(repr((mesh.uv_layers.active_index, mesh.color_attributes.default_color_name,
                       mesh.color_attributes.render_color_index,
                       [(uv.name, uv.active, uv.active_render, uv.active_clone, len(uv.data)) for uv in mesh.uv_layers])).encode('utf-8'))
        keys = mesh.shape_keys
        if keys:
            blocks = list(keys.key_blocks)
            reference = lambda key: None if key is None else (blocks.index(key), key.name)
            h.update(repr((keys.use_relative, reference(keys.reference_key),
                           [(key.name, reference(key.relative_key), key.vertex_group, key.frame,
                             key.interpolation, key.lock_shape, len(key.data)) for key in blocks])).encode('utf-8'))
            for key in blocks:
                for vertex in key.data:
                    h.update(struct.pack('<3f', *vertex.co))
    return h.hexdigest()


def datablock_counts():
    return {name: len(getattr(bpy.data, name)) for name in
            ('scenes', 'objects', 'meshes', 'armatures', 'materials', 'node_groups', 'images', 'actions')}


class ReadOnlyRNA(RuntimeError):
    pass


def writable(target, prop):
    descriptor = target.bl_rna.properties.get(prop)
    require(descriptor is not None, 'Missing actual RNA property: ' + target.bl_rna.identifier + '.' + prop)
    if descriptor.is_readonly:
        raise ReadOnlyRNA(target.bl_rna.identifier + '.' + prop + ': RNA descriptor is_readonly=True; no simulated mutation')


def value_copy(value):
    return tuple(value) if hasattr(value, '__len__') and not isinstance(value, str) else value


def resolve(target):
    """Mesh CustomData elements must be reacquired after depsgraph evaluation.

    Goo 4.4.3 can replace the raw storage during workflow._existing's view-layer
    update. A retained AttributeValue may still accept writes/read back the old
    allocation while the real mesh retains the mutation. Mesh callers therefore
    pass a mesh/name/index resolver, not an element handle. Direct non-CustomData
    targets (native material sockets) remain supported.
    """
    return target() if callable(target) else target


@contextmanager
def edits(changes, detail, cleanup=None):
    """Require real exact readback and finally restore CURRENT RNA, even on error."""
    for target, prop, _value in changes:
        writable(resolve(target), prop)
    originals = [(target, prop, value_copy(getattr(resolve(target), prop))) for target, prop, _value in changes]
    require(any(old != value for (_, _, old), (_, _, value) in zip(originals, changes)), 'Proposed RNA edit is not a mutation')
    try:
        for target, prop, value in changes:
            current = resolve(target)
            writable(current, prop)
            try:
                setattr(current, prop, value)
            except (AttributeError, RuntimeError) as exc:
                if any(word in str(exc).casefold() for word in ('read-only', 'readonly', 'read only')):
                    raise ReadOnlyRNA(current.bl_rna.identifier + '.' + prop + ': ' + str(exc)) from exc
                raise
            require(value_copy(getattr(resolve(target), prop)) == value, 'RNA edit failed exact readback: ' + prop)
        yield detail
    finally:
        for target, prop, value in reversed(originals):
            if value_copy(getattr(resolve(target), prop)) != value:
                setattr(resolve(target), prop, value)
            require(value_copy(getattr(resolve(target), prop)) == value, 'RNA restoration failed: ' + prop)
        if cleanup:
            cleanup()


class Regression:
    def __init__(self, workflow, validation, adapter, root, data, parts, report):
        self.workflow, self.validation, self.adapter = workflow, validation, adapter
        self.root, self.data, self.parts, self.report = root, data, parts, report
        self.blob, self.scene_blob = str(root['zzz_run']), str(bpy.context.scene['zzz_run'])
        self.counts = datablock_counts()
        self.other = strict_other_hash(parts)
        self.snapshots = self.capture()
        self.shader = validation.shader_state(parts)
        self.targets = validation.material_targets(root)
        self.hashes = {slot: reference_normal_hash(snapshot) for slot, snapshot in self.snapshots.items()}
        self.short2_mutated_slots = set()
        self.reference_checks = {slot: 1 for slot in parts}  # Initial capture already compared every part.
        inventory = []
        for slot, snapshot in self.snapshots.items():
            attribute = snapshot['attributes']['custom_normal']
            require(attribute is not None, 'Fixture must contain real CORNER INT16_2D custom_normal')
            values = attribute[1]
            require(len(values) == snapshot['counts'][2] and bool(values), 'ALLshort2 must cover every original corner')
            inventory.append({'slot': slot, 'mesh': parts[slot].data.name, 'all_short2_pairs': len(values),
                              'all_short2_components': 2 * len(values), 'zero_sentinels': values.count((0, 0)),
                              'minus24575_pairs': values.count((-24575, -24575)),
                              'all_short2_bytes_sha256': hashlib.sha256(b''.join(struct.pack('<2h', *pair) for pair in values)).hexdigest(),
                              'normal_inputs_reference': self.hashes[slot]})
        report['inventory'] = inventory
        self.representatives = self.representative_slots()
        self.assert_restored('initial new-schema fixture')

    def representative_slots(self):
        """Two real split parts by structure, never by fixture/material names."""
        require(len(self.parts) >= 2, 'Native-split regression requires genuine short2 mutations on at least two parts')
        require(len({ob.data.as_pointer() for ob in self.parts.values()}) == len(self.parts),
                'Native-split fixture must have distinct authored Mesh data for every part')
        ordered = sorted(self.snapshots, key=lambda slot: (self.snapshots[slot]['counts'][2], slot))
        candidates = [slot for slot in ordered if any(pair != (0, 0) for pair in
                      self.snapshots[slot]['attributes']['custom_normal'][1])]
        require(bool(candidates), 'No original nonzero short2 for real zero-sentinel transition')
        # A large nonzero-bearing part covers masks/topology and a small distinct
        # part checks part ownership. Neither mutations nor ALLshort2 reference
        # coverage depend on slot 0, material labels, object names or role tables.
        primary = candidates[-1]
        secondary = next(slot for slot in ordered if slot != primary)
        self.report['coverage'] = {
            'reference_policy': 'EVERY part; EVERY signed-short2 pair/component, including zero; independent full stream on each mutation and restoration',
            'mutation_policy': 'Two structural representatives for general short2; one for sharp/smooth/edge/cyclic cases; ALL actual CANCEL_PAIR matches on ALL parts',
            'reference_part_count': len(self.parts),
            'reference_short2_pairs': sum(row['all_short2_pairs'] for row in self.report['inventory']),
            'short2_representative_slots': [primary, secondary], 'mask_topology_representative_slot': primary,
            'representatives': [{'slot': slot, 'object': self.parts[slot].name, 'mesh': self.parts[slot].data.name,
                                 'counts': self.snapshots[slot]['counts']} for slot in (primary, secondary)],
            'selection': 'largest nonzero-bearing part, then smallest distinct part, ordered by corner count/slot; no name/role predicates',
            'not_claimed': 'General mutation types are not repeated on every part or every bit; all-part reference comparison is exhaustive'}
        return primary, secondary

    def capture(self):
        result = {slot: normal_snapshot(ob.data) for slot, ob in self.parts.items()}
        for slot, snapshot in result.items():
            require(self.validation.normal_inputs(self.parts[slot].data) == reference_normal_hash(snapshot),
                    'normal_inputs disagrees with independent ALLshort2/edge/corner/mask serialization for part ' + str(slot))
            if hasattr(self, 'reference_checks'):
                self.reference_checks[slot] += 1
        return result

    def metadata_unchanged(self):
        require(str(self.root['zzz_run']) == self.blob, 'Root baseline blob changed/rebased')
        require(str(bpy.context.scene['zzz_run']) == self.scene_blob, 'Scene baseline blob changed/rebased')
        require(datablock_counts() == self.counts, 'Blender datablock inventory changed')

    def files_unchanged(self):
        # Check source artifact and every protected production .py after EACH case,
        # not merely after process exit. Full resource/template hashes also run finally.
        artifact = self.report['artifact']['path']
        for path, expected in self.report['protected_hashes'].items():
            if path == artifact or Path(path).suffix == '.py':
                require(sha256(path) == expected, 'Protected artifact/core changed during case: ' + path)

    def existing(self):
        self.adapter.select_root(bpy.context, self.root)
        return self.workflow._existing(bpy.context, self.root, self.data['resource_dir'], self.data['outline_scale'])

    def assert_restored(self, label):
        require(self.capture() == self.snapshots, label + ': serialized normal input bytes did not restore')
        require(strict_other_hash(self.parts) == self.other, label + ': coordinates/UVs/weights/shapes/materials changed')
        require(self.validation.mesh_state(self.parts) == self.data['mesh'], label + ': strict mesh baseline differs')
        require(self.validation.shader_state(self.parts) == self.shader, label + ': authored shader changed')
        require(self.validation.material_targets(self.root) == self.targets, label + ': native material targets changed')
        self.metadata_unchanged()
        validated, parts, _rig, _arm = self.existing()
        require(validated == self.data and set(parts) == set(self.parts), label + ': _existing changed configured identity')
        self.metadata_unchanged()
        self.files_unchanged()

    def rejected(self, expected):
        try:
            self.existing()
        except RuntimeError as exc:
            require(expected in str(exc), 'Rejected for wrong reason: ' + str(exc))
            return {'type': type(exc).__name__, 'error': str(exc), 'traceback': traceback.format_exc()}
        raise AssertionError('Real RNA/legacy-schema mutation escaped workflow._existing')

    def negative(self, name, factory, required=False):
        case = {'name': name, 'type': 'real_RNA_negative', 'status': 'running', 'required_writable_RNA': required}
        self.report['cases'].append(case)
        try:
            with factory() as detail:
                case['target'] = detail
                modified = self.capture()
                changed = [slot for slot in modified if modified[slot] != self.snapshots[slot]]
                require(bool(changed), name + ': no real serialized input changed')
                for slot in changed:
                    require(self.validation.normal_inputs(self.parts[slot].data) != self.hashes[slot], name + ': normal_inputs missed RNA mutation')
                require(self.validation.mesh_state(self.parts) != self.data['mesh'], name + ': strict mesh_state missed mutation')
                require(strict_other_hash(self.parts) == self.other, name + ': mutation touched non-normal author data')
                case['changed_normal_inputs'] = {str(slot): {'before': self.hashes[slot], 'after': reference_normal_hash(modified[slot])} for slot in changed}
                case['workflow_rejection'] = self.rejected(MESH_ERROR)
                self.metadata_unchanged()
                case['status'] = 'pass'
                if detail.get('attribute') == 'custom_normal':
                    self.short2_mutated_slots.update(changed)
        except ReadOnlyRNA as exc:
            case.update(status='fail' if required else 'skip', reason=str(exc), traceback=traceback.format_exc())
            if required:
                raise AssertionError(name + ': required real short2 RNA write unavailable; not a passing or skipped test') from exc
        except Exception as exc:
            case.update(status='fail', error=str(exc), traceback=traceback.format_exc())
            raise
        finally:
            try:
                self.assert_restored(name + ' restored')
                case['restored_existing_pass'] = True
            except Exception as exc:
                case.update(status='fail', restore_error=str(exc), restore_traceback=traceback.format_exc())
                raise

    def schema_cases(self):
        for marker in (None, 'authored-mesh.v2-serialized-normal-inputs', 'legacy-unsupported-test-only'):
            name = 'missing_schema' if marker is None else 'previous_v2_schema' if marker.startswith('authored-mesh.v2') else 'legacy_schema'
            case = {'name': name, 'type': 'root_metadata_only_negative', 'status': 'running', 'marker': marker}
            self.report['cases'].append(case)
            modified = dict(self.data)
            if marker is None:
                del modified['mesh_guard_schema']
            else:
                modified['mesh_guard_schema'] = marker
            try:
                self.root['zzz_run'] = json.dumps(modified, ensure_ascii=False)
                require({key: value for key, value in modified.items() if key != 'mesh_guard_schema'} ==
                        {key: value for key, value in self.data.items() if key != 'mesh_guard_schema'}, 'Legacy test changed baseline hashes')
                case['workflow_rejection'] = self.rejected(LEGACY_ERROR)
                require(str(self.root['zzz_run']) == json.dumps(modified, ensure_ascii=False), 'Legacy rejection rewrote root metadata')
                case['status'] = 'pass'
            except Exception as exc:
                case.update(status='fail', error=str(exc), traceback=traceback.format_exc())
                raise
            finally:
                self.root['zzz_run'] = self.blob  # Exact original string, NOT a new baseline.
                self.assert_restored(case['name'] + ' restored')
                case['restored_current_schema_pass'] = True

    def duplicate_slot(self):
        case = {'name': 'copied_owned_mesh_duplicate_slot', 'type': 'object_identity_negative', 'status': 'running'}
        self.report['cases'].append(case)
        source = next(iter(self.parts.values()))
        duplicate = source.copy()  # SAME owner/slot/mesh; never copy or edit mesh/material data.
        try:
            bpy.context.scene.collection.objects.link(duplicate)
            require(duplicate.data == source.data and duplicate.get('zzz_owner') == self.data['owner'] and
                    duplicate.get('zzz_slot') == source.get('zzz_slot'), 'Actual duplicate lost owner/slot/shared mesh')
            case['target'] = {'source': source.name, 'copy': duplicate.name, 'shared_mesh': source.data.name,
                              'owner': duplicate['zzz_owner'], 'slot': int(duplicate['zzz_slot'])}
            case['workflow_rejection'] = self.rejected('已配置原网格存在重复槽标记或复制对象')
            require(str(self.root['zzz_run']) == self.blob and str(bpy.context.scene['zzz_run']) == self.scene_blob,
                    'Duplicate rejection rewrote baseline metadata')
            case['status'] = 'pass'
        except Exception as exc:
            case.update(status='fail', error=str(exc), traceback=traceback.format_exc())
            raise
        finally:
            bpy.data.objects.remove(duplicate, do_unlink=True)
            self.assert_restored('duplicate owned mesh removed')
            case['restored_existing_pass'] = True

    def short2(self, slot, index, changed):
        mesh = self.parts[slot].data
        old = tuple(mesh.attributes['custom_normal'].data[index].value)
        return edits([(lambda: mesh.attributes['custom_normal'].data[index], 'value', changed)],
                     {'slot': slot, 'mesh': mesh.name, 'corner': index, 'attribute': 'custom_normal', 'before': old, 'changed': changed})

    def cancel_pair_cases(self):
        """Exhaustive raw-pair superset: local indices may change after native split."""
        matches = []
        for slot, snapshot in sorted(self.snapshots.items()):
            values = snapshot['attributes']['custom_normal'][1]
            # Scan the WHOLE retained short2 array on EVERY part; do not sample,
            # use obsolete pre-split indices or choose a similar decoded float3.
            indices = [index for index, pair in enumerate(values) if pair == CANCEL_PAIR]
            wanted = set(indices)
            mesh = self.parts[slot].data
            faces = {index: poly for poly in mesh.polygons for index in poly.loop_indices if index in wanted}
            for index in indices:
                require(index in faces, 'Original CANCEL_PAIR has no owning polygon')
                poly = faces[index]
                vertex = mesh.loops[index].vertex_index
                matches.append({'slot': slot, 'object': self.parts[slot].name, 'mesh': mesh.name, 'corner': index,
                                'pair': values[index], 'vertex': vertex, 'position': tuple(mesh.vertices[vertex].co),
                                'polygon': poly.index, 'face_corner_offset': index - poly.loop_start,
                                'face_corners': tuple(poly.loop_indices), 'face_vertices': tuple(poly.vertices),
                                'face_positions': [tuple(mesh.vertices[v].co) for v in poly.vertices]})
        coverage = {'method': 'Exhaustive equality scan of all actual signed-short2 arrays in all native parts, then one genuine bit-edit/refusal/restore per hit',
                    'raw_pair': CANCEL_PAIR, 'reference_parts_scanned': len(self.snapshots),
                    'reference_pairs_scanned': sum(len(s['attributes']['custom_normal'][1]) for s in self.snapshots.values()),
                    'matched_pairs': len(matches), 'matches': matches,
                    'supersedes': 'Evelyn formerly used four global corner numbers; their raw-pair superset is tested without assuming post-split local indices',
                    'identity_limit': 'Superset coverage, not a one-to-one geometric remap from the old no-split artifact; native provenance separately proves every original corner appears once'}
        self.report['cancel_pair_coverage'] = coverage
        if self.report['kind'] == 'evelyn':
            # Fixture-specific coverage assertion only; not addon logic or a role
            # table. The four previously observed witnesses must lie in this
            # complete actual-pair set if the native exact-provenance proof holds.
            coverage['minimum_previous_witnesses'] = 4
            require(len(matches) >= 4, 'Evelyn lost its four real [-24575,-24575] witness superset; do not synthesize/rebaseline')
        if not matches:
            self.report['cases'].append({'name': 'original_minus24575_pairs_all_parts', 'status': 'skip', 'type': 'fixture_absence',
                                         'reason': 'No actual [-24575,-24575] pair in any part; no short2 is fabricated'})
        passed = 0
        for match in matches:
            slot, index = match['slot'], match['corner']
            name = 'original_cancel_pair_slot_' + str(slot) + '_corner_' + str(index)
            self.negative(name, lambda s=slot, i=index: self.short2(s, i, (CANCEL_PAIR[0] ^ 1, CANCEL_PAIR[1])), required=True)
            passed += 1
        coverage['individually_mutated_rejected_restored'] = passed
        coverage['all_actual_matches_tested'] = passed == len(matches)
        require(coverage['all_actual_matches_tested'], 'Not every actual CANCEL_PAIR match was tested')

    @contextmanager
    def mask(self, mesh, name):
        domain = {'sharp_edge': 'EDGE', 'sharp_face': 'FACE'}[name]
        original = mesh.attributes.get(name)
        created = False
        try:
            if original is None:
                attribute = mesh.attributes.new(name=name, type='BOOLEAN', domain=domain)
                created = True
                require(attribute.name == name, 'Reserved normal attribute was renamed by Blender')
            else:
                attribute = original
            require(attribute.data_type == 'BOOLEAN' and attribute.domain == domain and len(attribute.data), 'Wrong sharp-mask RNA layout')
            old = bool(attribute.data[0].value)
            with edits([(lambda: mesh.attributes[name].data[0], 'value', not old)],
                       {'mesh': mesh.name, 'attribute': name, 'index': 0, 'before': old, 'changed': not old,
                        'attribute_initially_absent': original is None}) as detail:
                yield detail
        finally:
            if created:
                mesh.attributes.remove(mesh.attributes[name])

    def smooth(self, mesh):
        absent = mesh.attributes.get('sharp_face') is None

        def cleanup():
            # use_smooth aliases sharp_face; restoring True may leave a newly-created
            # all-False attribute. Remove ONLY an attribute absent from the fixture.
            if absent and mesh.attributes.get('sharp_face') is not None:
                mesh.attributes.remove(mesh.attributes['sharp_face'])

        poly = mesh.polygons[0]
        return edits([(lambda: mesh.polygons[0], 'use_smooth', not poly.use_smooth)],
                     {'mesh': mesh.name, 'polygon': poly.index, 'before': poly.use_smooth, 'changed': not poly.use_smooth}, cleanup)

    def topology(self, mesh):
        poly = next((poly for poly in mesh.polygons if poly.loop_total >= 3), None)
        require(poly is not None, 'No polygon for valid cyclic corner-topology mutation')
        loops = [mesh.loops[index] for index in range(poly.loop_start, poly.loop_start + poly.loop_total)]
        old = [(loop.vertex_index, loop.edge_index) for loop in loops]
        rotated = old[1:] + old[:1]  # Valid winding/connectivity, not an invalid edge index.
        changes = [(lambda index=loop.index: mesh.loops[index], prop, row[component]) for loop, row in zip(loops, rotated)
                   for component, prop in enumerate(('vertex_index', 'edge_index'))]
        return edits(changes, {'mesh': mesh.name, 'polygon': poly.index, 'before_corners': old,
                               'changed_corners': rotated, 'policy': 'cyclic rotation; same valid polygon winding'})

    def native_positive(self, key):
        case = {'name': 'native_' + key + '_allowed', 'type': 'native_input_positive', 'status': 'running'}
        self.report['cases'].append(case)
        candidate = next(((mat, mat.node_tree.nodes.get('mmd_shader')) for mat in self.adapter.original_materials(self.parts.values())
                          if mat.use_nodes and mat.node_tree.nodes.get('mmd_shader') and
                          key in mat.node_tree.nodes['mmd_shader'].inputs and not mat.node_tree.nodes['mmd_shader'].inputs[key].is_linked), None)
        require(candidate is not None, 'No existing native unlinked input: ' + key)
        mat, node = candidate
        socket = node.inputs[key]
        old = value_copy(socket.default_value)
        changed = (struct.unpack('<f', struct.pack('<f', .37 if abs(old - .37) > .01 else .63))[0] if key == 'Alpha'
                   else tuple((.25 if abs(old[0] - .25) > .01 else .75) if i == 0 else v for i, v in enumerate(old)))
        try:
            with edits([(socket, 'default_value', changed)], {'material': mat.name, 'input': key, 'before': old, 'changed': changed}) as detail:
                case['target'] = detail
                self.assert_restored('normal native ' + key + ' input edit')
                case.update(status='pass', modified_existing_pass=True)
        except Exception as exc:
            case.update(status='fail', error=str(exc), traceback=traceback.format_exc())
            raise
        finally:
            self.assert_restored('native ' + key + ' restored')
            case['restored_existing_pass'] = True

    def execute(self):
        self.schema_cases()
        self.duplicate_slot()
        for slot in self.representatives:
            values = self.snapshots[slot]['attributes']['custom_normal'][1]
            # First pair is deliberately selected from ALL pairs, without a nonzero filter.
            first = values[0]
            self.negative('all_short2_lowbit_x_slot_' + str(slot),
                          lambda s=slot, p=first: self.short2(s, 0, (p[0] ^ 1, p[1])), required=True)
            sign_y = ((first[1] & 0xffff) ^ 0x8000)
            sign_y = sign_y - 0x10000 if sign_y >= 0x8000 else sign_y
            self.negative('all_short2_signbit_y_slot_' + str(slot),
                          lambda s=slot, p=first, y=sign_y: self.short2(s, 0, (p[0], y)), required=True)
        primary = self.representatives[0]
        nonzero = next(index for index, pair in enumerate(self.snapshots[primary]['attributes']['custom_normal'][1])
                       if pair != (0, 0))
        self.negative('short2_to_zero_sentinel_slot_' + str(primary),
                      lambda: self.short2(primary, nonzero, (0, 0)), required=True)
        # An original sentinel may live outside either general representative.
        # Search all parts and record genuine absence instead of fabricating one.
        zero = next(((slot, index) for slot, snapshot in sorted(self.snapshots.items())
                     for index, pair in enumerate(snapshot['attributes']['custom_normal'][1]) if pair == (0, 0)), None)
        self.report['coverage']['original_zero_sentinel'] = None if zero is None else {'slot': zero[0], 'corner': zero[1]}
        if zero is None:
            self.report['cases'].append({'name': 'original_zero_to_singlebit_all_parts', 'status': 'skip', 'type': 'fixture_absence',
                                         'reason': 'Full arrays of all parts contain no original (0,0); nonzero-to-zero transition is still a required real mutation'})
        else:
            self.negative('original_zero_to_singlebit_slot_' + str(zero[0]),
                          lambda: self.short2(*zero, (1, 0)), required=True)
        mesh = self.parts[primary].data
        for name in ('sharp_edge', 'sharp_face'):
            self.negative(name + '_slot_' + str(primary), lambda m=mesh, n=name: self.mask(m, n))
        self.negative('polygon_use_smooth_slot_' + str(primary), lambda: self.smooth(mesh))
        require(len(mesh.edges), 'Fixture representative has no edge topology')
        edge = mesh.edges[0]
        self.negative('edge_vertices_orientation_slot_' + str(primary),
                      lambda: edits([(lambda: mesh.edges[0], 'vertices', tuple(reversed(tuple(mesh.edges[0].vertices))))],
                                    {'slot': primary, 'mesh': mesh.name, 'edge': edge.index,
                                     'operation': 'reverse ordered endpoints; same valid undirected edge'}))
        self.negative('corner_vertex_edge_cyclic_topology_slot_' + str(primary), lambda: self.topology(mesh))
        self.cancel_pair_cases()
        require(set(self.representatives).issubset(self.short2_mutated_slots) and len(self.short2_mutated_slots) >= 2,
                'At least two distinct native parts must really mutate short2, reject and restore; skips cannot satisfy coverage')
        self.report['coverage']['genuine_short2_mutated_slots'] = sorted(self.short2_mutated_slots)
        self.native_positive('Alpha')
        self.native_positive('Diffuse Color')
        self.assert_restored('all RNA and legacy metadata restored')
        self.report['coverage']['independent_full_reference_checks_by_slot'] = {str(slot): count for slot, count in self.reference_checks.items()}
        self.report['final_existing_pass'] = True


def main():
    args = arguments()
    directory = OUTPUTS / 'normal_guards' / (datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '_' + args.kind + '_' + uuid.uuid4().hex[:8])
    directory.mkdir(parents=True, exist_ok=False)
    report = {'kind': args.kind, 'status': 'running', 'reader': bpy.app.version_string, 'schema': SCHEMA,
              'started_utc': datetime.now(timezone.utc).isoformat(), 'cases': [], 'forbidden_operations': [],
              'protected_hashes': {str(Path(__file__).resolve()): sha256(__file__)},
              'limits': ['Author performed syntax compilation and independent authored-structure tests only; parent must run frozen-artifact normal regression',
                         'v3 structure excludes key.value/eval_time and native VMD/Morph/SDEF runtime slider bounds/mute; see validation.shape_structure rationale',
                         'Runtime corner_normals cache is neither read nor mutated; serialized author input coverage only',
                         'ALLshort2 reference includes every pair; mutation probes are representative, not an exhaustive 32-bit-per-corner sweep',
                         'Read-only RNA is explicitly skipped; no mocked normal data or baseline repairs',
                         'No save/render, native Morph rebind, physics build, PMX import, or shader equivalence certificate']}
    failure = None
    try:
        require(bpy.app.version == (4, 4, 3) and 'Goo' in bpy.app.version_string and
                Path(bpy.app.binary_path).resolve() == AUTHORITATIVE_BLENDER.resolve(),
                'Use only the authoritative Goo Engine 4.4.3 executable: ' + str(AUTHORITATIVE_BLENDER))
        path = fixture(args, report)
        workflow, validation, adapter, renderer = addons(report)
        require(validation.MESH_GUARD_SCHEMA == SCHEMA, 'Production schema differs; no compatibility fallback')
        result = bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=True, use_scripts=False)
        require(result == {'FINISHED'} and Path(bpy.data.filepath).resolve() == path, 'Fixture did not open')
        roots = [ob for ob in bpy.context.scene.objects if 'zzz_run' in ob and getattr(ob, 'mmd_type', None) == 'ROOT']
        require(len(roots) == 1, 'Expected exactly one configured MMD root in saved active scene')
        root = roots[0]
        adapter.select_root(bpy.context, root)
        data = json.loads(root['zzz_run'])
        require(data.get('version') == workflow.VERSION and data.get('mesh_guard_schema') == SCHEMA,
                'Fixture has old schema/version; rebuild from trusted PMX, NEVER rebaseline this artifact')
        require(bpy.context.scene.name == data['scene'], 'Wrong saved configured scene')
        allowed = [(OUTPUTS / args.kind).resolve(), (OUTPUTS / 'motion' / args.kind).resolve()]
        require(any(inside(Path(data['output']).resolve(), folder) for folder in allowed), 'Embedded output is outside generated test subtrees')
        parts = {int(ob['zzz_slot']): ob for ob in bpy.context.scene.objects
                 if ob.type == 'MESH' and ob.get('zzz_owner') == data['owner'] and 'zzz_slot' in ob}
        require(bool(parts), 'No original owned mesh parts')
        for source in data['resource_hashes']:
            resolved = str(Path(source).resolve())
            report['protected_hashes'][resolved] = sha256(resolved)
        with no_commits(workflow, report):
            regression = Regression(workflow, validation, adapter, root, data, parts, report)
            report['baseline_new_schema_existing_pass'] = True
            regression.execute()
        require(not report['forbidden_operations'], 'A save/render was attempted')
        report['status'] = 'pass_serialized_normal_inputs_and_native_inputs'
    except Exception as exc:
        failure = (exc, exc.__traceback__)
        report.update(status='fail', error=str(exc), traceback=traceback.format_exc())
    finally:
        changes = []
        for source, expected in report['protected_hashes'].items():
            try:
                actual = sha256(source)
                if actual != expected:
                    changes.append({'path': source, 'before': expected, 'after': actual})
            except Exception as exc:
                changes.append({'path': source, 'before': expected, 'error': str(exc), 'traceback': traceback.format_exc()})
        report['source_artifact_and_core_hashes_unchanged'] = not changes
        report['protected_hash_changes'] = changes
        if changes:
            report.update(status='fail', hash_error='Protected artifact/core/input changed; not a passing test')
            if failure is None:
                failure = (AssertionError(report['hash_error']), None)
        if 'artifact' in report:
            report['artifact']['sha256_after'] = sha256(report['artifact']['path'])
        report['case_totals'] = {status: sum(case.get('status') == status for case in report['cases']) for status in ('pass', 'skip', 'fail', 'running')}
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        text = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
        (directory / 'guards.json').write_text(text, encoding='utf-8')
        (directory.parent / 'latest.json').write_text(text, encoding='utf-8')
        print('HEADLESS ' + json.dumps({'status': report['status'], 'kind': args.kind, 'cases': report['case_totals'],
                                        'error': report.get('error'), 'report': str(directory / 'guards.json')}, ensure_ascii=False), flush=True)
    if failure is not None:
        raise failure[0].with_traceback(failure[1])


if __name__ == '__main__':
    main()
