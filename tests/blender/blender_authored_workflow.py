"""TEST ONLY: v3 authored mutations through real _existing AND run(render=False).

Run only against an explicitly supplied, freshly generated, already passing test
artifact with the authoritative Goo Engine 4.4.3 executable. No PMX import,
fixture fabrication, save, render, guard migration or baseline rewrite is allowed.
Missing existing targets are explicit SKIPs. Temporary attributes/groups/UVs test
MEMBERSHIP rejection only; they never stand in for existing-value coverage.
Production and every pre-existing test in --manifest must remain byte-identical.
All mutations are real RNA with readback and exact finally restoration. Reports
are unique under test_outputs/authored_workflow; no latest report is overwritten.
"""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import functools
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import traceback
import uuid

sys.dont_write_bytecode = True
import bpy
import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1])); import testenv

ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = ROOT / 'test_outputs'
AUTHORITATIVE_BLENDER = testenv.goo_exe()
DEFAULT_MANIFEST = OUTPUTS / 'frozen' / 'final_20261117_111740' / 'source_manifest.json'
SCHEMA = 'authored-mesh.v3-shape-attribute-uv-structure'
MESH_ERROR = '原骨 rest/网格/渲染挂接被外部修改'


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def helper(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tests' / 'blender' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=('astra', 'evelyn'))
    parser.add_argument('--artifact', type=Path, required=True)
    parser.add_argument('--expected-artifact-sha256', required=True)
    parser.add_argument('--manifest', type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
    args.fixture = None  # Frozen fixture_path also supports a legacy positional fixture.
    return args


def protect_manifest(path, report):
    path = path.resolve(strict=True)
    data = json.loads(path.read_text(encoding='utf-8'))
    require(data.get('status') == 'frozen_for_final_regression', 'Manifest is not the final frozen runtime')
    report['manifest'] = {'path': str(path), 'sha256': sha256(path), 'schema': data.get('schema')}
    report['protected_hashes'][str(path)] = sha256(path)
    for section in ('files', 'test_files'):
        require(isinstance(data.get(section), dict) and data[section], 'Empty frozen manifest section: ' + section)
        for relative, expected in data[section].items():
            source = (ROOT / relative).resolve(strict=True)
            require(ROOT in source.parents, 'Manifest path escapes project: ' + relative)
            actual = sha256(source)
            require(actual == expected, 'Final freeze mismatch BEFORE test: ' + str(source))
            report['protected_hashes'][str(source)] = expected
    report['manifest']['frozen_file_count'] = len(data['files']) + len(data['test_files'])


def plain(value):
    if isinstance(value, (str, bytes, bool, int, float)) or value is None or hasattr(value, 'bl_rna'):
        return value
    return tuple(plain(item) for item in value)


def describe(value):
    if hasattr(value, 'bl_rna'):
        return {'RNA_type': value.bl_rna.identifier, 'name': getattr(value, 'name', None)}
    return plain(value)


def resolve(target):
    # workflow's view-layer update may replace CustomData storage. Mesh element
    # callers supply a resolver so both mutation and finally target CURRENT RNA.
    return target() if callable(target) else target


@contextmanager
def edit(target, prop, changed, label):
    descriptor = resolve(target).bl_rna.properties.get(prop)
    require(descriptor is not None and not descriptor.is_readonly, 'Actual RNA property is not writable: ' + label)
    old = plain(getattr(resolve(target), prop))
    require(old != plain(changed), 'Proposed RNA mutation is unchanged: ' + label)
    try:
        setattr(resolve(target), prop, changed)
        actual = plain(getattr(resolve(target), prop))
        require(actual == plain(changed), 'RNA mutation did not read back exactly: ' + label)
        yield {'target': label, 'property': prop, 'before': describe(old), 'changed': describe(actual)}
    finally:
        if plain(getattr(resolve(target), prop)) != old:
            setattr(resolve(target), prop, old)
        require(plain(getattr(resolve(target), prop)) == old, 'RNA restoration failed: ' + label)


def checkpoint(report, directory, label):
    """Unique-run partial evidence survives process cancellation; never a PASS."""
    report['last_checkpoint'] = label
    report['checkpoint_utc'] = datetime.now(timezone.utc).isoformat()
    report['case_totals'] = {state: sum(c['status'] == state for c in report['cases'])
                             for state in ('pass', 'skip', 'fail', 'running')}
    (directory / 'partial.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print('PROGRESS ' + json.dumps({'kind': report['kind'], 'checkpoint': label,
                                     'cases': report['case_totals'], 'directory': str(directory)}, ensure_ascii=False), flush=True)


class AuthoredRegression:
    """Reuse frozen route/no-commit implementation; add independent author checks."""
    def __init__(self, base, normal, workflow, validation, adapter, root, data, report, directory):
        self.runner = base.Regression(workflow, validation, adapter, root, data, report)
        self.runner.report_dir = directory
        self.normal, self.validation = normal, validation
        self.parts, self.root, self.data, self.report = self.runner.parts, root, data, report
        self.directory = directory
        self.baseline_root = str(root['zzz_run'])
        self.baseline_scene = str(bpy.context.scene['zzz_run'])
        self.initial_ids = self.inventory()
        self.reference = {}
        checkpoint(report, directory, 'before_baseline_repeat')
        self.report['baseline_repeat'] = self.runner.repeat('fresh frozen generated artifact')
        checkpoint(report, directory, 'after_baseline_repeat')
        require(validation.mesh_state(self.parts) == data['mesh'], 'Saved v3 guard does not match fresh artifact; NEVER repair it')
        self.report['saved_baseline_sha256_before'] = hashlib.sha256(self.baseline_root.encode('utf-8')).hexdigest()

    @staticmethod
    def inventory():
        return {kind: sorted((item.name, item.as_pointer()) for item in getattr(bpy.data, kind))
                for kind in ('scenes', 'objects', 'meshes', 'shape_keys', 'armatures', 'materials',
                             'node_groups', 'images', 'actions', 'collections')}

    def metadata(self):
        require(str(self.root['zzz_run']) == self.baseline_root, 'Root baseline changed/recomputed')
        require(str(bpy.context.scene['zzz_run']) == self.baseline_scene, 'Scene baseline changed/recomputed')
        require(self.inventory() == self.initial_ids, 'Datablock identity inventory changed')

    def files(self):
        # Full frozen manifest, explicit artifact, this new test, MMD Python and
        # resources are all protected; do not silently absorb concurrent edits.
        for path, expected in self.report['protected_hashes'].items():
            require(sha256(path) == expected, 'Protected file changed during case: ' + path)

    def transient_hash(self, ob):
        mesh = ob.data
        keys = mesh.shape_keys
        state = (None if keys is None else
                 (keys.eval_time, tuple((k.name, k.value, k.slider_min, k.slider_max, k.mute) for k in keys.key_blocks)),
                 ob.active_shape_key_index, ob.show_only_shape_key)
        h = hashlib.sha256(repr(state).encode('utf-8'))
        ui = {'.select_vert', '.select_edge', '.select_poly', '.hide_vert', '.hide_edge', '.hide_poly'}
        ui.update(prefix + uv.name for uv in mesh.uv_layers for prefix in ('.vs.', '.es.'))
        for attr in sorted(mesh.attributes, key=lambda item: item.name):
            if attr.name in ui:
                h.update(repr((attr.name, attr.data_type, attr.domain, len(attr.data))).encode('utf-8'))
                for item in attr.data:
                    h.update(repr(bool(item.value)).encode('ascii'))
        return h.hexdigest()

    def snapshot(self, slot):
        ob = self.parts[slot]
        raw = self.normal.normal_snapshot(ob.data)
        return {'independent_authored': self.normal.strict_other_hash({slot: ob}),
                'independent_raw_normal': self.normal.reference_normal_hash(raw),
                'production_part': self.validation.mesh_state({slot: ob}),
                'runtime_and_UI': self.transient_hash(ob)}

    def skip(self, name, reason, **detail):
        self.report['cases'].append({'name': name, 'status': 'skip', 'reason': reason, **detail})
        checkpoint(self.report, self.directory, name + ' skip')

    def case(self, name, slot, factory, allowed=False):
        case = {'name': name, 'slot': slot, 'object': self.parts[slot].name,
                'expectation': 'allowed_native_runtime' if allowed else 'real_mesh_guard_rejection', 'status': 'running'}
        self.report['cases'].append(case)
        checkpoint(self.report, self.directory, name + ' start')
        before = self.snapshot(slot)
        self.metadata()
        try:
            with factory() as detail:
                case['target'] = detail
                edited = self.snapshot(slot)
                require(edited != before, name + ': no real author/runtime RNA change')
                require(edited['independent_raw_normal'] == before['independent_raw_normal'],
                        name + ': unrelated serialized normal inputs changed')
                for key in ('independent_authored', 'production_part'):
                    require((edited[key] == before[key]) == allowed,
                            name + ': independent/production author hash disagrees: ' + key)
                case['independent_target_before'] = before
                case['independent_target_edited'] = edited
                if allowed:
                    case['modified_repeat'] = self.runner.repeat(name + ' allowed edit')
                else:
                    errors = []
                    for route in ('_existing', 'run'):
                        try:
                            self.runner.call(route)
                        except RuntimeError as exc:
                            require(MESH_ERROR in str(exc), name + ': wrong guard reason from ' + route + ': ' + str(exc))
                            errors.append({'route': route, 'error': str(exc), 'traceback': traceback.format_exc()})
                        else:
                            raise AssertionError(name + ': actual author edit escaped ' + route)
                        self.metadata()
                    case['guard_errors'] = errors
                self.metadata()
                self.files()
        except Exception as exc:
            case.update(status='fail', error=str(exc), traceback=traceback.format_exc())
            checkpoint(self.report, self.directory, name + ' failed_before_restore')
            raise
        finally:
            try:
                require(self.snapshot(slot) == before, name + ': exact original authored/runtime/UI state did not restore')
                self.metadata()
                case['restored_repeat'] = self.runner.repeat(name + ' exact finally restoration')
                require(self.snapshot(slot) == before, name + ': restored routes changed authored/runtime/UI storage')
                self.metadata()
                self.files()
                case['restored'] = True
            except Exception as exc:
                case.update(status='fail', restore_error=str(exc), restore_traceback=traceback.format_exc())
                checkpoint(self.report, self.directory, name + ' restore_failed')
                raise
        case['status'] = 'pass'
        checkpoint(self.report, self.directory, name + ' passed_and_restored')

    def property_case(self, name, slot, target, prop, value, allowed=False):
        if resolve(target).bl_rna.properties[prop].is_readonly:
            self.skip(name, 'Actual RNA descriptor is_readonly=True; no simulated mutation', property=prop, slot=slot)
            return
        self.case(name, slot, functools.partial(edit, target, prop, value, self.parts[slot].name + '/' + prop), allowed)

    @contextmanager
    def temporary_attribute(self, slot, name, domain='POINT'):
        mesh = self.parts[slot].data
        require(mesh.attributes.get(name) is None, 'Temporary author attribute already exists: ' + name)
        try:
            attr = mesh.attributes.new(name, 'FLOAT', domain)
            require(attr.name == name and len(attr.data) > 0, 'Temporary attribute identity/domain is not real')
            attr.data[0].value = .375
            require(attr.data[0].value == .375, 'Temporary attribute RNA did not read back')
            yield {'attribute': name, 'type': 'FLOAT', 'domain': domain, 'count': len(attr.data),
                   'coverage': 'membership addition only; absent from original saved artifact'}
        finally:
            attr = mesh.attributes.get(name)
            if attr is not None:
                mesh.attributes.remove(attr)
            require(mesh.attributes.get(name) is None, 'Temporary attribute survived restoration')

    @contextmanager
    def temporary_group(self, slot, name):
        ob = self.parts[slot]
        require(ob.vertex_groups.get(name) is None, 'Temporary renderer-named group already exists')
        try:
            group = ob.vertex_groups.new(name=name)
            require(group.name == name, 'Renderer-named group was renamed by Blender')
            require(not any(any(g.group == group.index for g in v.groups) for v in ob.data.vertices),
                    'New renderer-named group unexpectedly has memberships')
            yield {'group': name, 'unused': True, 'coverage': 'new unused group membership, not existing-group lock'}
        finally:
            group = ob.vertex_groups.get(name)
            if group is not None:
                ob.vertex_groups.remove(group)
            require(ob.vertex_groups.get(name) is None, 'Temporary group survived restoration')

    @staticmethod
    def uv_state(mesh):
        return (mesh.uv_layers.active_index,
                tuple((uv.name, uv.active_render, uv.active_clone) for uv in mesh.uv_layers))

    @staticmethod
    def restore_uv(mesh, state):
        active, layers = state
        for name, render, clone in layers:
            layer = mesh.uv_layers.get(name)
            require(layer is not None, 'Original UV layer missing on restore: ' + name)
            if render:
                layer.active_render = True
            if clone:
                layer.active_clone = True
        mesh.uv_layers.active_index = active
        require(AuthoredRegression.uv_state(mesh) == state, 'UV selectors did not restore exactly')

    @contextmanager
    def uv_selector(self, slot, prop):
        mesh = self.parts[slot].data
        original = self.uv_state(mesh)
        before_index = next((i for i, uv in enumerate(mesh.uv_layers) if getattr(uv, prop)), None)
        require(before_index is not None, 'No original True UV selector to restore: ' + prop)
        changed = (before_index + 1) % len(mesh.uv_layers)
        require(changed != before_index, 'No distinct existing UV selector target')
        try:
            setattr(mesh.uv_layers[changed], prop, True)
            require(getattr(mesh.uv_layers[changed], prop), 'Existing UV selector RNA did not change')
            yield {'property': prop, 'before_layer': mesh.uv_layers[before_index].name,
                   'changed_layer': mesh.uv_layers[changed].name, 'existing_layer_count': len(mesh.uv_layers)}
        finally:
            self.restore_uv(mesh, original)

    @contextmanager
    def temporary_uv(self, slot):
        mesh = self.parts[slot].data
        original = self.uv_state(mesh)
        name = 'AuthoredWorkflow_UV_' + uuid.uuid4().hex[:8]
        try:
            layer = mesh.uv_layers.new(name=name)
            require(layer.name == name, 'New UV membership identity mismatch')
            yield {'UV': name, 'coverage': 'layer membership addition only, not existing selector coverage'}
        finally:
            layer = mesh.uv_layers.get(name)
            if layer is not None:
                mesh.uv_layers.remove(layer)
            self.restore_uv(mesh, original)

    def execute(self):
        ordered = sorted(self.parts, key=lambda slot: (len(self.parts[slot].data.loops), slot))
        slot = next((s for s in ordered if len(self.parts[s].data.vertices)), None)
        require(slot is not None, 'No genuine authored vertices')
        key_slot = next((s for s in ordered if self.parts[s].data.shape_keys and
                         len(self.parts[s].data.shape_keys.key_blocks) > 1), None)
        if key_slot is None:
            for name in ('shape_relative_key', 'shape_vertex_group', 'shape_use_relative', 'shape_interpolation',
                         'shape_frame', 'shape_lock_shape', 'shape_value_allowed', 'shape_eval_time_allowed',
                         'native_slider_min_allowed', 'native_slider_max_allowed', 'native_mute_allowed'):
                self.skip(name, 'No existing nonbasis ShapeKey in this generated artifact; no fixture synthesized')
        else:
            ob = self.parts[key_slot]
            keys = ob.data.shape_keys
            blocks = list(keys.key_blocks)
            target = blocks[-1]
            alternate = None
            for candidate in blocks:
                if candidate == target or candidate == target.relative_key:
                    continue
                chain, cursor = set(), candidate
                while cursor is not None and cursor.as_pointer() not in chain and cursor != target:
                    chain.add(cursor.as_pointer())
                    parent = cursor.relative_key
                    if parent == cursor:
                        break
                    cursor = parent
                if cursor != target:
                    alternate = candidate
                    break
            if alternate is None:
                self.skip('shape_relative_key', 'No distinct existing acyclic relative_key target', slot=key_slot)
            else:
                self.property_case('shape_relative_key', key_slot, target, 'relative_key', alternate)
            group = next((g for g in ob.vertex_groups if g.name != target.vertex_group), None)
            if group is None:
                self.skip('shape_vertex_group', 'No distinct existing vertex group for this ShapeKey', slot=key_slot)
            else:
                self.property_case('shape_vertex_group', key_slot, target, 'vertex_group', group.name)
            self.property_case('shape_use_relative', key_slot, keys, 'use_relative', not keys.use_relative)
            interpolation = 'KEY_CARDINAL' if target.interpolation != 'KEY_CARDINAL' else 'KEY_LINEAR'
            self.property_case('shape_interpolation', key_slot, target, 'interpolation', interpolation)
            self.property_case('shape_frame', key_slot, target, 'frame', target.frame + 1)
            self.property_case('shape_lock_shape', key_slot, target, 'lock_shape', not target.lock_shape)
            self.property_case('shape_value_allowed', key_slot, target, 'value', .125 if target.value != .125 else .25, True)
            self.property_case('shape_eval_time_allowed', key_slot, keys, 'eval_time', keys.eval_time + 1, True)
            lo = max(-10., target.slider_min - .25)
            hi = min(10., target.slider_max + .25)
            if lo == target.slider_min:
                self.skip('native_slider_min_allowed', 'Existing slider_min already at native hard lower bound', slot=key_slot)
            else:
                self.property_case('native_slider_min_allowed', key_slot, target, 'slider_min', lo, True)
            if hi == target.slider_max:
                self.skip('native_slider_max_allowed', 'Existing slider_max already at native hard upper bound', slot=key_slot)
            else:
                self.property_case('native_slider_max_allowed', key_slot, target, 'slider_max', hi, True)
            self.property_case('native_mute_allowed', key_slot, target, 'mute', not target.mute, True)

        ob = self.parts[slot]
        used_groups = {membership.group for vertex in ob.data.vertices for membership in vertex.groups}
        unused = next((g for g in ob.vertex_groups if g.index not in used_groups), None)
        if unused is None:
            self.skip('existing_unused_group_lock', 'No existing unused vertex group in selected original part', slot=slot)
        else:
            self.property_case('existing_unused_group_lock', slot, unused, 'lock_weight', not unused.lock_weight)
        for name in ('GN_Outline', 'OutlineMask'):
            existing = ob.vertex_groups.get(name)
            if existing is None:
                self.case('new_unused_renderer_named_group_' + name, slot,
                          functools.partial(self.temporary_group, slot, name))
                self.skip('existing_renderer_named_group_lock_' + name,
                          'Original artifact has no such group; temporary membership case is not existing lock coverage', slot=slot)
            elif existing.index not in used_groups:
                self.property_case('existing_renderer_named_group_lock_' + name, slot,
                                   existing, 'lock_weight', not existing.lock_weight)
            else:
                self.skip('existing_renderer_named_group_lock_' + name,
                          'Original renderer-named group is used; unused-group lock target absent', slot=slot)

        crease_slot = next((s for s in ordered if self.parts[s].data.attributes.get('crease_edge') is not None and
                            len(self.parts[s].data.attributes['crease_edge'].data)), None)
        if crease_slot is None:
            self.skip('existing_crease_edge_value', 'No existing nonempty crease_edge in generated artifact; no value baseline synthesized')
            edge_slot = next((s for s in ordered if len(self.parts[s].data.edges)), None)
            if edge_slot is not None:
                self.case('new_crease_edge_membership', edge_slot,
                          functools.partial(self.temporary_attribute, edge_slot, 'crease_edge', 'EDGE'))
        else:
            attribute = self.parts[crease_slot].data.attributes['crease_edge']
            require((attribute.data_type, attribute.domain) == ('FLOAT', 'EDGE'), 'Existing crease_edge has unexpected real layout')
            old = attribute.data[0].value
            mesh = self.parts[crease_slot].data
            self.property_case('existing_crease_edge_value', crease_slot,
                               lambda: mesh.attributes['crease_edge'].data[0], 'value', .375 if old != .375 else .625)
        for prefix in ('.AuthoredWorkflow_', 'ZZZSplit_AuthoredWorkflow_'):
            name = prefix + uuid.uuid4().hex[:8]
            self.case('new_author_attribute_' + prefix, slot, functools.partial(self.temporary_attribute, slot, name))

        uv_slot = next((s for s in ordered if len(self.parts[s].data.uv_layers) >= 2), None)
        if uv_slot is None:
            for prop in ('active_index', 'active_render', 'active_clone'):
                self.skip('existing_UV_' + prop, 'Fewer than two existing UV layers on every part; no selector fixture synthesized')
        else:
            mesh = self.parts[uv_slot].data
            self.property_case('existing_UV_active_index', uv_slot, mesh.uv_layers, 'active_index',
                               (mesh.uv_layers.active_index + 1) % len(mesh.uv_layers))
            for prop in ('active_render', 'active_clone'):
                if not any(getattr(layer, prop) for layer in mesh.uv_layers):
                    self.skip('existing_UV_' + prop, 'No existing True selector to restore exactly', slot=uv_slot)
                else:
                    self.case('existing_UV_' + prop, uv_slot, functools.partial(self.uv_selector, uv_slot, prop))
        named_uv_slot = next((s for s in ordered if self.parts[s].data.uv_layers), None)
        if named_uv_slot is None:
            self.skip('existing_UV_layer_name', 'No existing UV layer in generated artifact')
        else:
            mesh = self.parts[named_uv_slot].data
            self.property_case('existing_UV_layer_name', named_uv_slot, lambda: mesh.uv_layers[0],
                               'name', 'AuthoredWorkflow_Rename_' + uuid.uuid4().hex[:8])
        self.case('new_UV_layer_membership', slot, functools.partial(self.temporary_uv, slot))
        self.report['final_repeat'] = self.runner.repeat('all real authored mutations restored')
        self.metadata()
        self.files()
        self.report['saved_baseline_sha256_after'] = hashlib.sha256(str(self.root['zzz_run']).encode('utf-8')).hexdigest()
        require(self.report['saved_baseline_sha256_after'] == self.report['saved_baseline_sha256_before'], 'Stored baseline was rewritten')
        self.report['final_existing_and_run_pass'] = True


def main():
    args = arguments()
    directory = OUTPUTS / 'authored_workflow' / (datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '_' + args.kind + '_' + uuid.uuid4().hex[:8])
    directory.mkdir(parents=True, exist_ok=False)
    report = {'kind': args.kind, 'status': 'running', 'schema': SCHEMA, 'reader': bpy.app.version_string,
              'binary': bpy.app.binary_path, 'started_utc': datetime.now(timezone.utc).isoformat(),
              'cases': [], 'forbidden_operations': [], 'protected_hashes': {str(Path(__file__).resolve()): sha256(__file__)},
              'limits': ['Actual generated artifact, real _existing and run(render=False), real RNA; no epsilon or fake acceptance',
                         'No PMX import, fixture fabrication, baseline migration/reset, save, render, native rebind or physics build',
                         'Missing existing structures are explicit skips; temporary layer/group cases prove membership rejection only',
                         'frame is skipped if actual RNA is read-only; interpolation is a separate real existing-key negative',
                         'No computed corner_normals, pixel equivalence, full VMD import or native Morph equivalence certificate',
                         'Full original parts are guarded by both workflow routes; independent per-target snapshots include raw normals/runtime/UI']}
    failure = None
    try:
        require(bpy.app.version == (4, 4, 3) and 'Goo' in bpy.app.version_string and
                Path(bpy.app.binary_path).resolve() == AUTHORITATIVE_BLENDER.resolve(), 'Use only authoritative Goo Engine 4.4.3')
        checkpoint(report, directory, 'started_before_manifest')
        protect_manifest(args.manifest, report)
        base = helper('_frozen_guard_route_helpers', 'blender_guard_mutations.py')
        normal = helper('_frozen_normal_reference_helpers', 'blender_normal_guards.py')
        checkpoint(report, directory, 'frozen_manifest_verified')
        path = base.fixture_path(args, report)
        require(report['artifact']['sha256_before'] == args.expected_artifact_sha256.lower(), 'Fresh artifact SHA differs from lead-published SHA')
        workflow, validation, adapter, renderer = base.register_current_addons(report)
        require(validation.MESH_GUARD_SCHEMA == SCHEMA, 'Production schema is not final v3; no fallback')
        checkpoint(report, directory, 'before_open_explicit_artifact')
        result = bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=True, use_scripts=False)
        checkpoint(report, directory, 'after_open_explicit_artifact')
        require(result == {'FINISHED'} and Path(bpy.data.filepath).resolve() == path, 'Explicit fresh artifact did not open')
        roots = [ob for ob in bpy.context.scene.objects if 'zzz_run' in ob and getattr(ob, 'mmd_type', None) == 'ROOT']
        require(len(roots) == 1, 'Expected one saved configured MMD root')
        root = roots[0]
        data = json.loads(root['zzz_run'])
        require(data.get('version') == workflow.VERSION and data.get('mesh_guard_schema') == SCHEMA,
                'Stale artifact schema/version; rebuild from trusted PMX, NEVER rebaseline here')
        require(bpy.context.scene.name == data['scene'], 'Wrong configured active scene')
        require(Path(data['output']).resolve() == path.parent, 'Generated artifact was moved from its embedded output directory')
        for source in data['resource_hashes']:
            source = str(Path(source).resolve())
            report['protected_hashes'][source] = sha256(source)
        with base.forbid_writes_and_render(workflow, report):
            regression = AuthoredRegression(base, normal, workflow, validation, adapter, root, data, report, directory)
            regression.execute()
        require(not report['forbidden_operations'], 'A save/render was attempted')
        report['status'] = 'pass_authored_v3_existing_and_run'
    except Exception as exc:
        failure = (exc, exc.__traceback__)
        report.update(status='fail', error=str(exc), traceback=traceback.format_exc())
    finally:
        changes = []
        for path, expected in report['protected_hashes'].items():
            try:
                actual = sha256(path)
                if actual != expected:
                    changes.append({'path': path, 'before': expected, 'after': actual})
            except Exception as exc:
                changes.append({'path': path, 'before': expected, 'error': str(exc)})
        report['source_artifact_and_frozen_tests_unchanged'] = not changes
        report['protected_hash_changes'] = changes
        if changes:
            report['status'] = 'fail'
            report['hash_error'] = 'Protected frozen runtime/test/artifact changed; not a passing regression'
            if failure is None:
                failure = (AssertionError(report['hash_error']), None)
        if 'artifact' in report:
            report['artifact']['sha256_after'] = sha256(report['artifact']['path'])
        report['case_totals'] = {state: sum(c['status'] == state for c in report['cases']) for state in ('pass', 'skip', 'fail', 'running')}
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        report_path = directory / 'guards.json'
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
        print('HEADLESS ' + json.dumps({'status': report['status'], 'kind': args.kind, 'cases': report['case_totals'],
                                        'error': report.get('error'), 'report': str(report_path)}, ensure_ascii=False), flush=True)
    if failure is not None:
        raise failure[0].with_traceback(failure[1])


if __name__ == '__main__':
    main()
