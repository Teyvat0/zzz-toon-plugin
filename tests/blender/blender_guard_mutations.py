"""TEST ONLY: mutate a generated configuration in memory; never save or render.

Run from an otherwise disposable Goo Engine 4.4 process, for example::

    goo-engine.exe --background --factory-startup --python-exit-code 1 \
        --python tests/blender/blender_guard_mutations.py \
        -- evelyn

``-- astra`` chooses that fixture's latest.json.  ``-- evelyn --artifact PATH``
(or ``-- evelyn PATH``) accepts only a .blend below test_outputs/evelyn; it is
an escape hatch while the integration runner has not published a usable latest.
No PMX import, user-original .blend, checkpoint open, save, render, dsh import,
fixture fabrication, or guard-baseline rewrite is performed by this test.

Negative cases: native group identity and instance mute; all four exposed native
output links; ColorMorph.mute; SeparateGeometry.domain; ObjectInfo.transform_space;
duplicate Math Value input 0/1 links; native material_id; source material-slot
identity; existing MaterialMorph target if present (12, or 13 with that target).
Native Alpha and Diffuse Color instance-default edits are two positive cases.
Missing required mutation targets FAIL; only absence of an existing material
Morph is reported as SKIP.  Each applied mutation is restored in a finally block
and both _existing and run(render=False) must succeed after restoration.

Results: test_outputs/guards/<unique-id>/guards.json and guards/latest.json.
The parent must execute the Blender regression; Python compile alone is NOT a
Blender pass, a render comparison, or proof of full native Morph equivalence.
"""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import functools
import hashlib
import importlib
import json
from pathlib import Path
import sys
import traceback
import uuid

# Loading source packages must not write __pycache__ beside the addon or MMD Tools.
sys.dont_write_bytecode = True

import bpy


ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = ROOT / 'test_outputs'
MMD_PARENT = Path(r'C:\Users\gyf20\AppData\Roaming\Blender Foundation\Blender\4.4\extensions\blender_org')
KINDS = ('evelyn', 'astra')
EXPECTED_GUARDS = (
    '原骨 rest/网格/渲染挂接被外部修改',
    '原生材质 Morph 桥组身份被替换',
    '原生材质 Morph 桥组被静音',
    '原材质槽引用已被替换',
    '原生材质Morph目标引用或材质ID被修改',
)


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
    try:
        path.relative_to(directory)
        return True
    except ValueError:
        return False


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', nargs='?', choices=KINDS)
    parser.add_argument('fixture', nargs='?', help='Explicit generated .blend, never a user project')
    parser.add_argument('--kind', dest='kind_option', choices=KINDS, help='Alternative to positional kind')
    parser.add_argument('--artifact', type=Path, help='Same restriction as the positional fixture')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
    require(not (args.fixture and args.artifact), 'Specify an explicit artifact only once')
    require(not (args.kind and args.kind_option), 'Specify the fixture kind only once')
    args.kind = args.kind_option or args.kind or 'evelyn'
    return args


def fixture_path(args, report):
    fixture_root = (OUTPUTS / args.kind).resolve()
    latest = fixture_root / 'latest.json'
    explicit = args.artifact or args.fixture
    report['fixture_latest'] = str(latest)
    if explicit:
        path = Path(explicit).expanduser()
        require(path.is_absolute(), '--artifact must be an absolute path inside the selected test-output subtree')
        report['fixture_selection'] = 'explicit_test_output'
    else:
        require(latest.is_file(), 'No integration latest.json: ' + str(latest))
        report['protected_hashes'][str(latest)] = sha256(latest)
        metadata = json.loads(latest.read_text(encoding='utf-8'))
        report['fixture_latest_status'] = metadata.get('status')
        artifact = metadata.get('artifact')
        require(isinstance(artifact, dict) and artifact.get('path'),
                'latest.json has no artifact.path; rerun the integration fixture or pass --artifact '
                'with a generated file. The test never guesses an original/checkpoint path.')
        path = Path(artifact['path']).expanduser()
        require(path.is_absolute(), 'latest.json artifact.path must be absolute')
        report['fixture_selection'] = 'latest.artifact.path'
        report['fixture_published_artifact'] = artifact
    path = path.resolve(strict=True)
    require(path.is_file() and path.suffix.casefold() == '.blend', 'Fixture is not a .blend file: ' + str(path))
    require(inside(path, fixture_root) and path.parent != fixture_root,
            'Refusing to open anything outside the selected integration test-output subtree: ' + str(path))
    require(path.name == '仿ZZZ渲染_通用配置.blend',
            'Only the integration-generated configuration artifact is allowed, not originals/checkpoints: ' + str(path))
    report['artifact'] = {'path': str(path), 'bytes': path.stat().st_size, 'sha256_before': sha256(path)}
    report['protected_hashes'][str(path)] = report['artifact']['sha256_before']
    return path


def register_current_addons(report):
    # A fresh --factory-startup process avoids stale same-name package instances.
    sys.path.insert(0, str(ROOT))
    addon = importlib.import_module('zzz_mmd_toon')
    require(Path(addon.__file__).resolve() == (ROOT / 'zzz_mmd_toon' / '__init__.py').resolve(),
            'A different zzz_mmd_toon package is loaded; use a fresh factory-startup process')
    if not hasattr(bpy.types.Scene, 'zzz_toon'):
        addon.register()
    require(MMD_PARENT.is_dir(), 'Configured MMD Tools extension parent is missing: ' + str(MMD_PARENT))
    sys.path.insert(0, str(MMD_PARENT))
    mmd = importlib.import_module('mmd_tools')
    require(inside(Path(mmd.__file__).resolve(), (MMD_PARENT / 'mmd_tools').resolve()),
            'A different MMD Tools is loaded; use the declared Blender 4.4 extension')
    if not hasattr(bpy.types.PoseBone, 'mmd_bone'):
        mmd.register()
    report['addons'] = {'zzz_mmd_toon': str(Path(addon.__file__).resolve()),
                        'mmd_tools': str(Path(mmd.__file__).resolve())}
    for package in (ROOT / 'zzz_mmd_toon', MMD_PARENT / 'mmd_tools'):
        for path in sorted(package.rglob('*.py')):
            report['protected_hashes'][str(path.resolve())] = sha256(path)
    return tuple(importlib.import_module('zzz_mmd_toon.' + name)
                 for name in ('workflow', 'validation', 'mmd_adapter', 'renderer'))


def counts():
    return {name: len(getattr(bpy.data, name)) for name in
            ('scenes', 'objects', 'materials', 'node_groups', 'meshes', 'armatures', 'images', 'actions')}


@contextmanager
def forbid_writes_and_render(workflow, report):
    """Fail closed if a repeat unexpectedly tries a workflow commit or render."""
    before = {name: getattr(workflow, name) for name in ('_save_new', '_render')}

    def reject(operation, *_args, **_kwargs):
        report['forbidden_operations'].append(operation)
        raise AssertionError('Guard regression attempted forbidden operation: ' + operation)

    def save_pre(*_args):
        reject('bpy.save_pre')

    def render_pre(*_args):
        reject('bpy.render_pre')

    workflow._save_new = functools.partial(reject, 'workflow._save_new')
    workflow._render = functools.partial(reject, 'workflow._render')
    bpy.app.handlers.save_pre.append(save_pre)
    bpy.app.handlers.render_pre.append(render_pre)
    try:
        yield
    finally:
        for name, function in before.items():
            setattr(workflow, name, function)
        for handlers, callback in ((bpy.app.handlers.save_pre, save_pre),
                                   (bpy.app.handlers.render_pre, render_pre)):
            if callback in handlers:
                handlers.remove(callback)


class Regression:
    def __init__(self, workflow, validation, adapter, root, data, report):
        self.workflow, self.validation, self.adapter = workflow, validation, adapter
        self.root, self.data, self.report = root, data, report
        self.parts = {int(ob['zzz_slot']): ob for ob in bpy.context.scene.objects
                      if ob.type == 'MESH' and ob.get('zzz_owner') == data['owner'] and 'zzz_slot' in ob}
        require(bool(self.parts), 'The configured scene has no owned original mesh parts')
        self.materials = adapter.original_materials(self.parts.values())
        require(bool(self.materials), 'No original source materials')
        self.before_counts = counts()
        self.before_run = str(root['zzz_run'])
        self.before_targets = validation.material_targets(root)
        self.before_shader = validation.shader_state(self.parts)
        self.report['fixture_inventory'] = {
            'owner': data['owner'], 'scene': data['scene'], 'mesh_parts': len(self.parts),
            'materials': len(self.materials), 'material_morphs': len(root.mmd_root.material_morphs),
            'baseline_counts': self.before_counts,
        }

    def call(self, route):
        self.adapter.select_root(bpy.context, self.root)
        if route == '_existing':
            return self.workflow._existing(bpy.context, self.root, self.data['resource_dir'],
                                           self.data['outline_scale'])
        require(route == 'run', 'Unknown guard route: ' + route)
        return self.workflow.run(bpy.context, resource_dir=self.data['resource_dir'],
                                 output_dir=str(self.report_dir), render=False,
                                 mapping=self.data['mapping'], outline_scale=self.data['outline_scale'],
                                 samples=1, resolution=128)

    def repeat(self, label):
        data, parts, _rig, _arm = self.call('_existing')
        require(data['owner'] == self.data['owner'] and set(parts) == set(self.parts), label + ': _existing changed identity')
        result = self.call('run')
        require(result.get('status') == 'already_configured_noop' and result.get('image') is None,
                label + ': run(render=False) was not a render-free configured no-op')
        require(counts() == self.before_counts, label + ': repeat changed Blender datablock counts')
        require(str(self.root['zzz_run']) == self.before_run, label + ': repeat changed the stored guard baseline')
        return {'routes': ['_existing', 'run(render=False)'], 'status': result['status'], 'counts_unchanged': True}

    def state(self):
        return self.validation.digest({'shader': self.validation.shader_state(self.parts),
                                       'targets': self.validation.material_targets(self.root)})

    def negative(self, name, factory):
        """factory returns a context manager restoring the mutation even on error."""
        case = {'name': name, 'type': 'negative', 'status': 'running'}
        self.report['cases'].append(case)
        before = self.state()
        try:
            with factory() as detail:
                case['target'] = detail
                case['guard_errors'] = []
                for route in ('_existing', 'run'):
                    try:
                        self.call(route)
                    except RuntimeError as exc:
                        error = {'route': route, 'type': type(exc).__name__, 'error': str(exc),
                                 'traceback': traceback.format_exc()}
                        case['guard_errors'].append(error)
                        # run() now has a stricter native save-pre admission before
                        # _existing. Only these exact mutations may fail earlier;
                        # unrelated errors still fail the regression.
                        early = (route == 'run' and (
                            (name == 'source_slot_replaced_with_copied_Material' and '保存前检查失败：重复原生Material ID' in str(exc))
                            or (name == 'existing_MaterialMorph_material_data_retarget' and '保存前检查失败：材质Morph指针与数值ID不一致' in str(exc))))
                        require(early or any(text in str(exc) for text in EXPECTED_GUARDS),
                                name + ': failed for a different reason, not the renderer/Morph/save-safety guard: ' + str(exc))
                    else:
                        raise AssertionError(name + ': mutation escaped ' + route)
                    require(str(self.root['zzz_run']) == self.before_run,
                            name + ': guard failure changed/recomputed its saved baseline')
        except Exception as exc:
            case.update(status='fail', error=str(exc), traceback=traceback.format_exc())
            raise
        finally:
            # Context-manager exit has already restored the exact original value,
            # link endpoints, or ID pointer. No baseline rewriting is allowed.
            try:
                require(self.state() == before, name + ': exact authored state did not restore')
                case['restored_repeat'] = self.repeat(name + ' restored')
                case['restored'] = True
            except Exception as exc:
                case.update(status='fail', restore_error=str(exc), restore_traceback=traceback.format_exc())
                raise
        case['status'] = 'pass'

    def positive(self, name, factory):
        case = {'name': name, 'type': 'positive', 'status': 'running'}
        self.report['cases'].append(case)
        before = self.state()
        try:
            with factory() as detail:
                case['target'] = detail
                require(self.state() == before, name + ': normal native input edit changed the authored guard digest')
                case['modified_repeat'] = self.repeat(name + ' edited')
        except Exception as exc:
            case.update(status='fail', error=str(exc), traceback=traceback.format_exc())
            raise
        finally:
            try:
                require(self.state() == before, name + ': input edit did not restore')
                case['restored_repeat'] = self.repeat(name + ' restored')
                case['restored'] = True
            except Exception as exc:
                case.update(status='fail', restore_error=str(exc), restore_traceback=traceback.format_exc())
                raise
        case['status'] = 'pass'

    def native(self, key=None):
        for material in self.materials:
            node = material.node_tree.nodes.get('mmd_shader') if material.use_nodes else None
            if node and node.type == 'GROUP' and node.node_tree:
                if key is None or (key in node.inputs and not node.inputs[key].is_linked):
                    return material, node
        raise AssertionError('No live native mmd_shader' + (' with unlinked input ' + key if key else ''))

    def outline_trees(self):
        for ob in self.parts.values():
            for mod in ob.modifiers:
                tree = mod.node_group if mod.type == 'NODES' else None
                if tree and tree.get('zzz_owner') == self.data['owner'] and tree.get('zzz_outline_policy'):
                    yield ob, tree

    @contextmanager
    def property_edit(self, target, prop, changed, label):
        old = getattr(target, prop)
        require(old != changed, label + ': proposed edit is not a mutation')
        try:
            setattr(target, prop, changed)
            require(getattr(target, prop) == changed, label + ': RNA edit did not take effect')
            yield {'target': label, 'property': prop, 'before': old, 'changed': changed}
        finally:
            setattr(target, prop, old)

    @contextmanager
    def native_group_copy(self):
        material, native = self.native()
        original = native.node_tree
        input_values = {s.identifier: copy_value(s.default_value) for s in native.inputs if hasattr(s, 'default_value')}
        connected = []
        for link in material.node_tree.links:
            if link.from_node == native or link.to_node == native:
                connected.append((link.from_node, self.validation.socket_key(link.from_socket),
                                  link.to_node, self.validation.socket_key(link.to_socket)))
        clone = original.copy()
        clone.use_fake_user = False
        try:
            native.node_tree = clone
            require(native.node_tree != original, 'Native group copy was not installed')
            yield {'material': material.name, 'original_tree': original.name, 'replacement_tree': clone.name,
                   'replacement': 'byte-for-byte tree.copy(), original zzz_native_tree_ref retained'}
        finally:
            native.node_tree = original
            for link in list(material.node_tree.links):
                if link.from_node == native or link.to_node == native:
                    material.node_tree.links.remove(link)
            for start_node, start_key, end_node, end_key in connected:
                material.node_tree.links.new(socket_from_key(start_node.outputs, start_key),
                                             socket_from_key(end_node.inputs, end_key))
            for socket in native.inputs:
                if socket.identifier in input_values:
                    socket.default_value = input_values[socket.identifier]
            require(clone.users == 0, 'Temporary native group still has users after restoration')
            bpy.data.node_groups.remove(clone)

    @contextmanager
    def native_instance_mute(self):
        material, native = self.native()
        require(not native.mute, 'The unmodified native mmd_shader instance is already muted')
        with self.property_edit(native, 'mute', True, material.name + '/mmd_shader') as detail:
            yield detail

    @contextmanager
    def native_exposed_link(self, exposed):
        material, native = self.native()
        tree = native.node_tree
        output = next((n for n in tree.nodes if n.type == 'GROUP_OUTPUT' and n.is_active_output), None)
        source = next((n for n in tree.nodes if n.type == 'GROUP_INPUT'), None)
        require(output is not None and source is not None, 'Native group has no active IO nodes')
        require(exposed in output.inputs, 'Missing native exposed output: ' + exposed)
        target = output.inputs[exposed]
        before = [(link.from_socket, link.to_socket) for link in target.links]
        require(len(before) == 1, 'Expected exactly one original native bridge link: ' + exposed)
        # Swap only the wire, retaining the group ID and both endpoint names.
        alternate_key = {'ZZZ_Diffuse': 'Base Tex', 'ZZZ_Alpha': 'Base Alpha',
                         'ZZZ_BaseColor': 'Diffuse Color', 'ZZZ_BaseAlpha': 'Alpha'}[exposed]
        alternate = source.outputs.get(alternate_key)
        require(alternate is not None and alternate != before[0][0], 'No distinct compatible alternate native input')
        try:
            for link in list(target.links):
                tree.links.remove(link)
            tree.links.new(alternate, target)
            yield {'material': material.name, 'tree': tree.name, 'output': exposed,
                   'from_before': before[0][0].name, 'from_changed': alternate_key}
        finally:
            for link in list(target.links):
                tree.links.remove(link)
            for start, end in before:
                tree.links.new(start, end)

    @contextmanager
    def color_morph_mute(self):
        for material in self.materials:
            wrapper = material.node_tree.nodes.get('ZZZ_GameEnhancement')
            node = wrapper.node_tree.nodes.get('ZZZ_ColorMorph') if wrapper and wrapper.node_tree else None
            if node:
                with self.property_edit(node, 'mute', not node.mute, material.name + '/ZZZ_ColorMorph') as detail:
                    yield detail
                return
        raise AssertionError('No game ColorMorph node')

    @contextmanager
    def gn_property(self, node_type, prop, expected, changed):
        for ob, tree in self.outline_trees():
            node = next((n for n in tree.nodes if n.bl_idname == node_type and getattr(n, prop) == expected), None)
            if node is not None:
                with self.property_edit(node, prop, changed, ob.name + '/' + tree.name + '/' + node.name) as detail:
                    yield detail
                return
        raise AssertionError('Missing expected original GN node/property: ' + node_type + '/' + prop)

    @contextmanager
    def duplicate_math_ports(self):
        candidate = next(((ob, tree, node) for ob, tree in self.outline_trees() for node in tree.nodes
                          if node.bl_idname == 'ShaderNodeMath' and node.operation == 'MULTIPLY'
                          and len(node.inputs) >= 2 and node.inputs[0].name == node.inputs[1].name
                          and node.inputs[0].is_linked and not node.inputs[1].is_linked), None)
        require(candidate is not None, 'No linked Math duplicate-Value 0/1 input pair in actual outline tree')
        ob, tree, node = candidate
        first, second = node.inputs[0], node.inputs[1]
        endpoints = [(link.from_socket, link.to_socket) for link in list(first.links) + list(second.links)]
        # Preserve defaults; this isolates a port-index rewire that name-only link
        # signatures would miss. Math MULTIPLY may be commutative, but the authored
        # endpoint contract must still reject 0/1 interchange rather than guess.
        try:
            for socket in (first, second):
                for link in list(socket.links):
                    tree.links.remove(link)
            for start, end in endpoints:
                tree.links.new(start, second if end == first else first)
            yield {'object': ob.name, 'tree': tree.name, 'node': node.name,
                   'operation': node.operation,
                   'before_input': list(self.validation.socket_key(first)),
                   'changed_input': list(self.validation.socket_key(second)),
                   'defaults_unchanged': True}
        finally:
            for socket in (first, second):
                for link in list(socket.links):
                    tree.links.remove(link)
            for start, end in endpoints:
                tree.links.new(start, end)

    @contextmanager
    def material_id(self):
        material = self.materials[0]
        ids = {int(mat.mmd_material.material_id) for mat in self.materials}
        changed = max(ids | {0}) + 101
        with self.property_edit(material.mmd_material, 'material_id', changed, material.name) as detail:
            yield detail

    @contextmanager
    def material_copy(self):
        ob = next(iter(self.parts.values()))
        require(len(ob.data.materials) > 0, 'Original mesh has no material slot')
        original = ob.data.materials[0]
        clone = original.copy()
        clone.use_fake_user = False
        try:
            ob.data.materials[0] = clone
            require(ob.data.materials[0] != original, 'Copied Material was not assigned to source slot')
            yield {'object': ob.name, 'slot': 0, 'original_material': original.name,
                   'replacement_material': clone.name, 'same_material_id': int(clone.mmd_material.material_id)}
        finally:
            ob.data.materials[0] = original
            require(clone.users == 0, 'Temporary copied Material still has users after restoration')
            bpy.data.materials.remove(clone)

    def material_morph_target(self):
        for morph in self.root.mmd_root.material_morphs:
            for index, entry in enumerate(morph.data):
                if entry.material_data is None or entry.material_data not in self.materials:
                    continue
                alternate = next((m for m in self.materials if m != entry.material_data), None)
                if alternate is not None:
                    return morph, index, entry, alternate
        return None

    @contextmanager
    def retarget_material_morph(self, fixture):
        morph, index, entry, alternate = fixture
        original, material_id, related = entry.material_data, int(entry.material_id), entry.related_mesh_data
        try:
            # PointerProperty, not the .material name setter: exercise the exact
            # material_data target contract without synchronizing material_id.
            entry.material_data = alternate
            require(entry.material_data == alternate and alternate != original, 'MaterialMorph retarget did not take effect')
            yield {'morph': morph.name, 'entry': index,
                   'original_material': original.name if original else None,
                   'changed_material': alternate.name, 'material_id_retained': material_id}
        finally:
            entry.material_data = original
            entry.material_id = material_id
            entry.related_mesh_data = related

    @contextmanager
    def native_default(self, key):
        material, native = self.native(key)
        socket = native.inputs[key]
        old = copy_value(socket.default_value)
        if key == 'Alpha':
            changed = .37 if abs(float(old) - .37) > .01 else .63
        else:
            changed = list(old)
            changed[0] = .25 if abs(float(old[0]) - .25) > .01 else .75
        try:
            socket.default_value = changed
            require(copy_value(socket.default_value) != old, 'Native input default edit did not take effect: ' + key)
            yield {'material': material.name, 'native_input': key, 'linked': False,
                   'before': old, 'changed': copy_value(socket.default_value)}
        finally:
            socket.default_value = old

    def execute(self, report_dir):
        self.report_dir = report_dir
        self.report['baseline_repeat'] = self.repeat('unmodified reopened artifact')
        self.negative('native_mmd_shader_copied_tree_identity', self.native_group_copy)
        self.negative('native_mmd_shader_instance_mute', self.native_instance_mute)
        for exposed in ('ZZZ_Diffuse', 'ZZZ_Alpha', 'ZZZ_BaseColor', 'ZZZ_BaseAlpha'):
            self.negative('native_exposed_link_' + exposed,
                          functools.partial(self.native_exposed_link, exposed))
        self.negative('game_ColorMorph_mute', self.color_morph_mute)
        self.negative('GN_SeparateGeometry_FACE_to_POINT',
                      functools.partial(self.gn_property, 'GeometryNodeSeparateGeometry', 'domain', 'FACE', 'POINT'))
        self.negative('GN_ObjectInfo_RELATIVE_to_ORIGINAL',
                      functools.partial(self.gn_property, 'GeometryNodeObjectInfo', 'transform_space', 'RELATIVE', 'ORIGINAL'))
        self.negative('Math_duplicate_Value_input_0_to_1', self.duplicate_math_ports)
        self.negative('native_mmd_material_material_id', self.material_id)
        self.negative('source_slot_replaced_with_copied_Material', self.material_copy)
        target = self.material_morph_target()
        if target is None:
            self.report['cases'].append({'name': 'existing_MaterialMorph_material_data_retarget',
                                         'type': 'negative', 'status': 'skip',
                                         'reason': 'No existing material-Morph data entry with another same-model material; no fixture synthesized'})
        else:
            self.negative('existing_MaterialMorph_material_data_retarget',
                          functools.partial(self.retarget_material_morph, target))
        self.positive('native_Alpha_default_allowed', functools.partial(self.native_default, 'Alpha'))
        self.positive('native_Diffuse_Color_default_allowed', functools.partial(self.native_default, 'Diffuse Color'))
        self.report['final_repeat'] = self.repeat('all mutations restored')
        require(self.validation.material_targets(self.root) == self.before_targets, 'Final native Morph targets changed')
        require(self.validation.shader_state(self.parts) == self.before_shader, 'Final authored renderer state changed')
        require(counts() == self.before_counts, 'Final Blender datablock counts changed')


def copy_value(value):
    return list(value) if hasattr(value, '__len__') and not isinstance(value, str) else value


def socket_from_key(sockets, key):
    identifier, index, name = key
    socket = sockets[index]
    require(socket.identifier == identifier and socket.name == name,
            'Original node socket identity did not restore: ' + repr(key))
    return socket


def write_report(report, directory):
    text = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
    (directory / 'guards.json').write_text(text, encoding='utf-8')
    (directory.parent / 'latest.json').write_text(text, encoding='utf-8')
    print('HEADLESS ' + json.dumps({'status': report['status'], 'kind': report['kind'],
                                    'cases': len(report['cases']),
                                    'passed': sum(c.get('status') == 'pass' for c in report['cases']),
                                    'skipped': sum(c.get('status') == 'skip' for c in report['cases']),
                                    'error': report.get('error'),
                                    'report': str(directory / 'guards.json')}, ensure_ascii=False), flush=True)


def main():
    args = arguments()
    directory = OUTPUTS / 'guards' / (datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '_' + args.kind + '_' + uuid.uuid4().hex[:8])
    directory.mkdir(parents=True, exist_ok=False)
    report = {'kind': args.kind, 'status': 'running', 'reader': bpy.app.version_string,
              'started_utc': datetime.now(timezone.utc).isoformat(), 'cases': [],
              'protected_hashes': {str(Path(__file__).resolve()): sha256(__file__)}, 'forbidden_operations': [],
              'limits': ['Real Blender regression required; source author only performed in-memory Python syntax compilation',
                         'Uses generated test artifacts only; no PMX import or user-original blend is opened',
                         'No save, render, pixel comparison, physics build, native Morph binding, or dsh runtime dependency',
                         'Existing MaterialMorph retarget is skipped only when no eligible existing entry exists',
                         'Stale saved guard hashes or invalid latest metadata fail baseline; the test never repairs fixtures']}
    failure = None
    try:
        require(bpy.app.version[:2] == (4, 4) and 'Goo' in bpy.app.version_string,
                'Use Goo Engine 4.4, not standard Blender with an approximate node fallback')
        path = fixture_path(args, report)
        workflow, validation, adapter, renderer = register_current_addons(report)
        result = bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=True, use_scripts=False)
        require(result == {'FINISHED'}, 'Opening generated test artifact did not finish')
        require(Path(bpy.data.filepath).resolve() == path, 'Blender opened a different project')
        _module, _rig, root, _arm, _meshes = adapter.selected(bpy.context)
        require('zzz_run' in root, 'Generated artifact has no existing universal configuration')
        data = json.loads(root['zzz_run'])
        require(inside(Path(data['output']).resolve(), (OUTPUTS / args.kind).resolve()),
                'Fixture embeds a non-test output path; refusing to invoke its repeat workflow')
        require(Path(data['output']).resolve() == path.parent, 'Fixture was moved away from its generated output directory')
        require(data.get('version') == workflow.VERSION, 'Generated fixture guard version is stale; rebuild integration fixture')
        require(bpy.context.scene.name == data['scene'], 'Generated artifact did not reopen its configured render scene')
        # Scene/shaders are code-built; nothing imports or needs dsh/K.
        for source in data['resource_hashes']:
            resolved = str(Path(source).resolve())
            report['protected_hashes'][resolved] = sha256(resolved)
        regression = Regression(workflow, validation, adapter, root, data, report)
        with forbid_writes_and_render(workflow, report):
            regression.execute(directory)
        require(not report['forbidden_operations'], 'An unexpected save/render was attempted')
        report['status'] = 'pass_guard_mutations_and_native_inputs'
    except Exception as exc:
        failure = (exc, exc.__traceback__)
        report.update(status='fail', error=str(exc), traceback=traceback.format_exc())
    finally:
        changed = []
        for source, expected in report['protected_hashes'].items():
            try:
                actual = sha256(source)
            except Exception as exc:
                changed.append({'path': source, 'sha256_before': expected, 'error': str(exc),
                                'traceback': traceback.format_exc()})
            else:
                if actual != expected:
                    changed.append({'path': source, 'sha256_before': expected, 'sha256_after': actual})
        report['source_hashes_unchanged'] = not changed
        report['source_hash_changes'] = changed
        if 'artifact' in report:
            try:
                report['artifact']['sha256_after'] = sha256(report['artifact']['path'])
            except Exception:
                report['artifact']['sha256_after'] = None
                report['artifact']['hash_traceback'] = traceback.format_exc()
        if changed:
            report['status'] = 'fail'
            report['hash_error'] = 'A protected input/source file changed; never treated as a passing mutation test'
            if failure is None:
                exc = AssertionError(report['hash_error'])
                failure = (exc, None)
                report['error'] = str(exc)
        report['case_totals'] = {status: sum(case.get('status') == status for case in report['cases'])
                                 for status in ('pass', 'fail', 'skip', 'running')}
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        write_report(report, directory)
    if failure is not None:
        raise failure[0].with_traceback(failure[1])


if __name__ == '__main__':
    main()
