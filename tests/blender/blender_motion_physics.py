"""TEST ONLY: native VMD and explicit native physics on a configured test artifact.

Run in Goo Engine with --python-exit-code 1 --python THIS_FILE -- evelyn
(or any other existing test_outputs/<kind>/latest.json fixture label).
Optional: --source-artifact ABSOLUTE_TEST_OUTPUT_BLEND --source-pmx ABSOLUTE_PMX.
The explicit .blend MUST resolve below this addon's test_outputs directory.
No PMX import, profile/count expectations, mesh separation, guard re-baselining,
source save, render, bake, or native physics cleanup is performed here.

All generated files belong to a new test_outputs/motion/<kind>/<unique>/ tree.
Only that motion fixture's latest.json is replaced. This is a short sequential
native simulation smoke test, NOT a collision-free/arbitrary-dance certificate.
"""
import argparse
import importlib
import json
import math
import os
from pathlib import Path
import re
import sys
import traceback
from datetime import datetime, timezone
from uuid import uuid4

import bpy
from mathutils import Quaternion, Vector

ROOT = Path(__file__).resolve().parents[2]
TEST_OUTPUTS = (ROOT / 'test_outputs').resolve()
BODY_NAMES = ('センター', '頭', '上半身', '左腕', '右腕', '左足ＩＫ', '右足ＩＫ')
FINGER_TOKENS = ('親指', '人指', '人差指', '中指', '薬指', '小指')
BLINK_ALIASES = ('まばたき', '瞬き', 'blink', '眨眼', '闭眼', '閉眼')
LIMITS = [
    'Native VMD generated from this artifact: all discovered original JP fingers, present standard body tracks and an existing blink shape.',
    'Native physics build and 61 sequential evaluated frames only; not baked, not an arbitrary dance or collision certificate.',
    'Weighted mesh samples are original-surface vertices, excluding generated outline shells; simulation samples are capped per source mesh.',
    'No guard baseline is reset. Missing fixture evidence, unsupported evaluated topology or a normal-VMD guard mismatch fails explicitly.',
    'Source blend and available source-folder PMX files are hashed read-only; no source project/model is saved.',
]


def arguments():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', nargs='?', default='evelyn', help='Fixture directory label, not a runtime character profile')
    parser.add_argument('--source-artifact', type=Path, help='Explicit configured .blend below test_outputs; no original project accepted')
    parser.add_argument('--source-pmx', type=Path, help='Optional exact original PMX, read/hash only (never imported or saved)')
    parser.add_argument('--diagnostics', action='store_true', help='Opt-in component probes; default path runs production guards before any extra mesh reads')
    args = parser.parse_args(argv)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', args.kind) or args.kind == 'motion':
        parser.error('kind must be a single safe fixture label, not a path or motion')
    return args


def check(report, name, condition, detail=None):
    row = {'name': name, 'pass': bool(condition)}
    if detail is not None:
        row['detail'] = detail
    report['checks'].append(row)
    if not condition:
        raise AssertionError('%s: %s' % (name, detail))


def inside(path, parent):
    path = Path(path).expanduser().resolve()
    if not path.is_relative_to(Path(parent).resolve()):
        raise RuntimeError('Path is outside allowed test output subtree: ' + str(path))
    return path


def write_new_json(path, value):
    # Never overwrite a historical report/checkpoint.
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def enable_addons():
    sys.path.insert(0, str(ROOT))
    addon = importlib.import_module('zzz_mmd_toon')
    if not hasattr(bpy.types.Scene, 'zzz_toon'):
        addon.register()
    from zzz_mmd_toon import mmd_adapter
    try:
        mmd_adapter.native()
    except RuntimeError:
        # Native extension discovery, not a machine-specific/user/model path.
        candidates = []
        for base in bpy.utils.script_paths():
            candidates.extend((Path(base) / 'addons', Path(base) / 'addons_core'))
        user = Path(bpy.utils.user_resource('CONFIG')).parent
        candidates.extend(sorted((user / 'extensions').glob('*')))
        for directory in candidates:
            if (directory / 'mmd_tools' / '__init__.py').is_file():
                sys.path.insert(0, str(directory))
        native = importlib.import_module('mmd_tools')
        if not hasattr(bpy.types.PoseBone, 'mmd_bone'):
            native.register()
        mmd_adapter.native()
    return importlib.import_module('zzz_mmd_toon.workflow'), importlib.import_module('zzz_mmd_toon.validation'), mmd_adapter


def configured_model(adapter, root_name=None):
    roots = [ob for ob in bpy.context.scene.objects if 'zzz_run' in ob and getattr(ob, 'mmd_type', None) == 'ROOT']
    if root_name is not None:
        roots = [ob for ob in roots if ob.name == root_name]
    if len(roots) != 1:
        raise RuntimeError('Expected one configured native MMD root in the active saved scene, got %d' % len(roots))
    adapter.select_root(bpy.context, roots[0])
    return adapter.selected(bpy.context)


def snapshot_authored(output, label, validation, root, arm, parts):
    """TEST ONLY diagnostics; never reset any saved production guard."""
    sys.path.insert(0, str(ROOT / 'tests' / 'blender'))
    from mesh_signature_probe import capture
    folder = output / 'authored_diagnostics'
    capture(parts, folder, label)
    data = json.loads(root['zzz_run'])
    write_new_json(folder / (label + '_guards.json'), {
        'expected': {key: data[key] for key in ('skeleton', 'mesh', 'shader', 'material_targets')},
        'actual': {'skeleton': validation.skeleton(arm), 'mesh': validation.mesh_state(parts),
                   'shader': validation.shader_state(parts),
                   'material_targets': validation.digest(validation.material_targets(root))}})
    write_new_json(folder / (label + '_shader.json'), validation.shader_state_data(parts))


def guard(workflow, adapter, root):
    data = json.loads(root['zzz_run'])
    adapter.select_root(bpy.context, root)
    validated = workflow._existing(bpy.context, root, data['resource_dir'], data['outline_scale'])
    result = workflow.run(bpy.context, resource_dir=data['resource_dir'],
                          output_dir=data['output'], render=False, outline_scale=data['outline_scale'])
    if result.get('status') != 'already_configured_noop':
        raise RuntimeError('Configured repeat unexpectedly was not a no-op: ' + str(result))
    return validated, result


def native_inventory(rig):
    return {'rigids': sorted(ob.name for ob in rig.rigidBodies()), 'joints': sorted(ob.name for ob in rig.joints())}


def morph_catalog(root):
    return {name: [item.name for item in getattr(root.mmd_root, name)]
            for name in ('vertex_morphs', 'material_morphs', 'bone_morphs', 'uv_morphs', 'group_morphs')}


def authored(validation, parts, root, arm, rig):
    return {'skeleton': validation.skeleton(arm), 'mesh': validation.mesh_state(parts),
            'shader': validation.shader_state(parts), 'material_targets': validation.digest(validation.material_targets(root)),
            'morph_catalog': morph_catalog(root), 'native_physics': native_inventory(rig),
            'source_meshes': sorted((int(slot), ob.name, ob.data.name, len(ob.data.vertices), len(ob.data.polygons),
                                     [mat.name if mat else None for mat in ob.data.materials],
                                     [key.name for key in ob.data.shape_keys.key_blocks] if ob.data.shape_keys else [])
                                    for slot, ob in parts.items())}


def identities(parts):
    return {str(slot): [ob.as_pointer(), ob.data.as_pointer(),
                        [mat.as_pointer() if mat else None for mat in ob.data.materials]] for slot, ob in parts.items()}


def bone_map(module, arm):
    util = importlib.import_module(module.__name__ + '.utils')
    mapped = util.makePmxBoneMap(arm)
    originals = [bone for bone in arm.pose.bones if not bone.is_mmd_shadow_bone]
    result = {}
    for bone in originals:
        name = bone.mmd_bone.name_j or bone.get('mmd_bone_name_j', bone.get('name_j', bone.name))
        if name in result:
            raise RuntimeError('Duplicate native original JP bone mapping: ' + name)
        if mapped.get(name) != bone:
            raise RuntimeError('Ambiguous native PMX bone mapping: ' + name)
        result[name] = bone
    return result


def vmd_name(name):
    encoded = name.encode('shift_jis', errors='strict')
    if b'\x00' in encoded or len(encoded) > 15 or encoded.decode('shift_jis') != name:
        raise RuntimeError('Native VMD 15-byte bone/morph name is not lossless: ' + name)
    return name


def animation_targets(arm, root, meshes, rig):
    targets = [arm, root]
    placeholder = rig.morph_slider.placeholder()
    objects = list(meshes) + ([placeholder] if placeholder else [])
    for ob in objects:
        keys = getattr(ob.data, 'shape_keys', None)
        if keys is not None and keys not in targets:
            targets.append(keys)
    return targets


def driver_signature(target):
    ad = target.animation_data
    return [(fc.data_path, fc.array_index, fc.driver.type, fc.driver.expression,
             [(var.name, var.type, [(dst.id.name if dst.id else None, dst.data_path) for dst in var.targets])
              for var in fc.driver.variables]) for fc in ad.drivers] if ad else []


def capture_animation(targets, arm):
    bindings = []
    for target in targets:
        ad = target.animation_data
        if ad and any(not track.mute and len(track.strips) for track in ad.nla_tracks):
            raise RuntimeError('Fixture already has active NLA; refusing to clear or mask pre-existing user animation: ' + target.name)
        bindings.append((target, ad.action if ad else None, getattr(ad, 'action_slot', None) if ad else None, driver_signature(target)))
    return {'bindings': bindings, 'actions': {action.as_pointer() for action in bpy.data.actions},
            'pose': {bone.name: bone.matrix_basis.copy() for bone in arm.pose.bones},
            'shapes': [(target, [(key.name, float(key.value), float(key.slider_min), float(key.slider_max))
                                 for key in target.key_blocks]) for target in targets if isinstance(target, bpy.types.Key)]}


def restore_test_animation(saved, arm):
    # Restore bindings rather than animation_data_clear(): that would delete native Morph drivers.
    for target, action, slot, drivers in saved['bindings']:
        ad = target.animation_data
        if ad:
            ad.action = action
            if slot is not None and hasattr(ad, 'action_slot'):
                ad.action_slot = slot
        if driver_signature(target) != drivers:
            raise RuntimeError('Native drivers changed during VMD regression: ' + target.name)
    for name, matrix in saved['pose'].items():
        arm.pose.bones[name].matrix_basis = matrix
    for keys, rows in saved['shapes']:
        for name, value, lo, hi in rows:
            key = keys.key_blocks[name]
            key.slider_min, key.slider_max, key.value = lo, hi, value
    removed = []
    for action in list(bpy.data.actions):
        if action.as_pointer() not in saved['actions']:
            if action.users:
                raise RuntimeError('New test action still has users after restoring original bindings: ' + action.name)
            removed.append(action.name)
            bpy.data.actions.remove(action)
    bpy.context.scene.frame_set(1)
    bpy.context.view_layer.update()
    return removed


def weighted_vertices(meshes, bone_names, cap=None):
    result = {}
    for ob in meshes:
        groups = {g.index for g in ob.vertex_groups if g.name in bone_names}
        referenced = {index for face in ob.data.polygons for index in face.vertices}
        ids = [v.index for v in ob.data.vertices if v.index in referenced and
               any(g.group in groups and g.weight > 0.0 for g in v.groups)]
        total = len(ids)
        if cap and total > cap:
            ids = [ids[round(i * (total - 1) / (cap - 1))] for i in range(cap)]
        if ids:
            result[ob.name] = (ob, ids, total)
    return result


def original_surface_points(weighted, shell_attribute):
    """Map source polygon corners to evaluated non-shell corners, never guess indices.

    The installed outline API marks original faces False and generated faces True.
    Verify count/winding/material and a consistent one-to-one source vertex mapping
    with modifiers ENABLED; otherwise fail, rather than sample a shell as a hand.
    """
    depsgraph = bpy.context.evaluated_depsgraph_get()
    result = {}
    for name, (ob, ids, _) in weighted.items():
        evaluated = ob.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)
        try:
            marker = mesh.attributes.get(shell_attribute)
            if marker is None or marker.domain != 'FACE' or marker.data_type != 'BOOLEAN':
                raise RuntimeError('Missing evaluated original/shell FACE marker: ' + name)
            original_faces = [p for p in mesh.polygons if not marker.data[p.index].value]
            if len(original_faces) != len(ob.data.polygons):
                raise RuntimeError('Evaluated original surface face count changed: ' + name)
            mapping, reverse = {}, {}
            for src, dst in zip(ob.data.polygons, original_faces):
                if len(src.vertices) != len(dst.vertices) or src.material_index != dst.material_index:
                    raise RuntimeError('Unsupported original-surface topology/material order: ' + name)
                for source_index, evaluated_index in zip(src.vertices, dst.vertices):
                    if source_index in mapping and mapping[source_index] != evaluated_index:
                        raise RuntimeError('Inconsistent original evaluated vertex mapping: ' + name)
                    if evaluated_index in reverse and reverse[evaluated_index] != source_index:
                        raise RuntimeError('Non-bijective original evaluated vertex mapping: ' + name)
                    mapping[source_index], reverse[evaluated_index] = evaluated_index, source_index
            result[name] = [list(evaluated.matrix_world @ mesh.vertices[mapping[index]].co) for index in ids]
        finally:
            evaluated.to_mesh_clear()
    return result


def max_distance(first, second):
    if set(first) != set(second):
        raise RuntimeError('Evaluated mesh sample identity changed')
    maximum = 0.0
    for name in first:
        if len(first[name]) != len(second[name]):
            raise RuntimeError('Evaluated sample count changed: ' + name)
        maximum = max(maximum, max(((Vector(a) - Vector(b)).length for a, b in zip(first[name], second[name])), default=0.0))
    return maximum


def finite(value):
    if isinstance(value, dict):
        return all(finite(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return all(finite(item) for item in value)
    return math.isfinite(float(value))


def model_scale(meshes):
    coordinates = [ob.matrix_world @ vertex.co for ob in meshes for vertex in ob.data.vertices]
    if not coordinates or not all(all(math.isfinite(v) for v in point) for point in coordinates):
        raise RuntimeError('Invalid or empty original source model')
    lo = Vector(tuple(min(point[i] for point in coordinates) for i in range(3)))
    hi = Vector(tuple(max(point[i] for point in coordinates) for i in range(3)))
    diagonal = (hi - lo).length
    if not math.isfinite(diagonal) or diagonal <= 0:
        raise RuntimeError('Degenerate original model bounds')
    return diagonal, (lo + hi) * .5


def generate_vmd(module, output, fingers, body, blink):
    vmd = importlib.import_module(module.__name__ + '.core.vmd')
    motion = vmd.File()
    motion.header = vmd.Header()
    motion.header.model_name = 'ZZZ_Universal_Test'
    motion.boneAnimation, motion.shapeKeyAnimation = vmd.BoneAnimation(), vmd.ShapeKeyAnimation()
    for name in fingers + body:
        vmd_name(name)
        for frame, phase in ((0, 0), (15, 1), (30, 0)):
            key = vmd.BoneFrameKey()
            key.frame_number, key.location = frame, (0., 0., 0.)
            # Generic rotational pulse only: no fixture scale or character pose adaptation.
            angle = (.32 if name in fingers else .12) * phase * (-1 if name.startswith('右') else 1)
            quat = Quaternion((0., 0., 1.), angle)
            key.rotation = (quat.x, quat.y, quat.z, quat.w)
            key.interp = [20, 20, 0, 0, 20, 20, 0, 0, 107, 107, 127, 127, 107, 107, 127, 127] * 4
            motion.boneAnimation[name].append(key)
    vmd_name(blink)
    for frame, value in ((0, 0.), (15, .55), (30, 0.)):
        key = vmd.ShapeKeyFrameKey()
        key.frame_number, key.weight = frame, value
        motion.shapeKeyAnimation[blink].append(key)
    path = output / 'native_body_fingers_blink.vmd'
    if path.exists():
        raise RuntimeError('Refusing to overwrite generated VMD')
    motion.save(filepath=str(path))
    loaded = vmd.File()
    loaded.load(filepath=str(path))
    if set(loaded.boneAnimation) != set(fingers + body) or set(loaded.shapeKeyAnimation) != {blink}:
        raise RuntimeError('Native VMD name roundtrip was not lossless')
    return path


def run_vmd(report, output, module, rig, root, arm, meshes, parts, workflow, validation, adapter, shell_attribute):
    mapped = bone_map(module, arm)
    fingers = [name for name in mapped if any(token in name for token in FINGER_TOKENS)]
    body = [name for name in BODY_NAMES if name in mapped and name not in fingers]
    check(report, 'actual_original_finger_tracks_available', bool(fingers), {'names': fingers, 'original_bones': len(mapped)})
    key_meshes = [ob for ob in meshes if ob.data.shape_keys is not None]
    present = {key.name for ob in key_meshes for key in ob.data.shape_keys.key_blocks}
    blink = next((name for alias in BLINK_ALIASES for name in sorted(present) if name.casefold() == alias.casefold()), None)
    check(report, 'existing_blink_shape_available', blink is not None, {'present_shape_names': sorted(present)})
    weighted = weighted_vertices(meshes, {mapped[name].name for name in fingers})
    check(report, 'actual_original_finger_weights_present', bool(weighted),
          {name: {'source_weighted_vertices': total, 'sampled': len(ids)} for name, (_, ids, total) in weighted.items()})
    diagonal, _ = model_scale(meshes)
    epsilon, return_tolerance = max(diagonal * 1e-7, 1e-9), max(diagonal * 1e-5, 1e-8)
    targets = animation_targets(arm, root, meshes, rig)
    saved = capture_animation(targets, arm)
    path = generate_vmd(module, output, fingers, body, blink)
    report['vmd'] = {'path': str(path), 'fingers': fingers, 'body_present': body,
                     'body_absent': [name for name in BODY_NAMES if name not in mapped], 'blink': blink,
                     'frame_mapping': {'vmd': [0, 15, 30], 'blender': [1, 16, 31]},
                     'motion_epsilon': epsilon, 'return_tolerance': return_tolerance}
    try:
        adapter.select_root(bpy.context, root)
        result = bpy.ops.mmd_tools.import_vmd(directory=str(output) + os.sep, files=[{'name': path.name}],
                                              scale=.08, margin=0, bone_mapper='PMX', use_pose_mode=False,
                                              update_scene_settings=False, use_NLA=False)
        action = arm.animation_data.action if arm.animation_data else None
        check(report, 'native_vmd_import_finished_and_armature_action', result == {'FINISHED'} and action is not None, sorted(result))
        for name in fingers + body:
            bone = mapped[name]
            rotation_prop = {'QUATERNION': 'rotation_quaternion', 'AXIS_ANGLE': 'rotation_axis_angle'}.get(bone.rotation_mode, 'rotation_euler')
            paths = [(bone.path_from_id('location'), 3), (bone.path_from_id(rotation_prop), len(getattr(bone, rotation_prop)))]
            curves = [action.fcurves.find(data_path, index=index) for data_path, size in paths for index in range(size)]
            check(report, 'native_bone_curves:' + name, all(curve and len(curve.keyframe_points) == 3 and
                  [round(point.co.x) for point in curve.keyframe_points] == [1, 16, 31] for curve in curves))
        for ob in key_meshes:
            keys = ob.data.shape_keys
            shape_action = keys.animation_data.action if keys.animation_data else None
            check(report, 'native_shape_action_on_complete_source_mesh:' + ob.name, shape_action is not None,
                  {'shape_keys': len(keys.key_blocks), 'action': shape_action.name if shape_action else None})
            if blink in keys.key_blocks:
                curve = shape_action.fcurves.find(keys.key_blocks[blink].path_from_id('value'))
                check(report, 'native_blink_curve:' + ob.name, curve is not None and len(curve.keyframe_points) == 3)
        samples, blink_values = [], []
        for frame in (1, 16, 31):
            bpy.context.scene.frame_set(frame)
            bpy.context.view_layer.update()
            samples.append(original_surface_points(weighted, shell_attribute))
            blink_values.append({ob.name: float(ob.data.shape_keys.key_blocks[blink].value)
                                 for ob in key_meshes if blink in ob.data.shape_keys.key_blocks})
        displacement, returned = max_distance(samples[0], samples[1]), max_distance(samples[0], samples[2])
        check(report, 'native_vmd_actual_weighted_source_mesh_moves_and_returns',
              finite(samples) and displacement > epsilon and returned <= return_tolerance,
              {'peak_displacement': displacement, 'return_error': returned})
        check(report, 'native_blink_actual_values_return', all(abs(value - expected) < 1e-5
              for values, expected in zip(blink_values, (0., .55, 0.)) for value in values.values()), blink_values)
        # Distinguish finger deformation from a whole-body transform: mute ONLY newly
        # imported body curves and blink curves, leaving every modifier/constraint live.
        muted = []
        for name in body:
            prefix = mapped[name].path_from_id() + '.'
            for curve in action.fcurves:
                if curve.data_path.startswith(prefix):
                    muted.append((curve, curve.mute)); curve.mute = True
        for ob in key_meshes:
            shape_action = ob.data.shape_keys.animation_data.action
            for curve in shape_action.fcurves:
                muted.append((curve, curve.mute)); curve.mute = True
            if blink in ob.data.shape_keys.key_blocks:
                ob.data.shape_keys.key_blocks[blink].value = 0.
        finger_samples = []
        try:
            for frame in (1, 16, 31):
                bpy.context.scene.frame_set(frame)
                bpy.context.view_layer.update()
                finger_samples.append(original_surface_points(weighted, shell_attribute))
        finally:
            for curve, previous in muted:
                curve.mute = previous
        finger_displacement = max_distance(finger_samples[0], finger_samples[1])
        finger_returned = max_distance(finger_samples[0], finger_samples[2])
        check(report, 'isolated_native_fingers_deform_original_weighted_mesh_and_return',
              finite(finger_samples) and finger_displacement > epsilon and finger_returned <= return_tolerance,
              {'peak_displacement': finger_displacement, 'return_error': finger_returned})
        bpy.context.scene.frame_set(16)
        bpy.context.view_layer.update()
        _, repeated = guard(workflow, adapter, root)
        check(report, 'normal_native_vmd_passes_existing_guard_without_rebaseline', repeated['status'] == 'already_configured_noop', repeated)
        report['vmd'].update(displacement=displacement, return_error=returned, finger_only_displacement=finger_displacement,
                             finger_only_return_error=finger_returned, blink_values=blink_values)
    finally:
        report.setdefault('vmd', {})['removed_test_actions'] = restore_test_animation(saved, arm)
    _, repeated = guard(workflow, adapter, root)
    check(report, 'guard_after_restoring_only_test_animation', repeated['status'] == 'already_configured_noop')


def evaluate_physics(report, rig, root, arm, meshes, adapter, shell_attribute):
    scene = bpy.context.scene
    native = adapter.validate_physics(bpy.context, rig, root, arm)
    check(report, 'native_physics_not_baked', not native['baked'], native)
    dynamic = [ob for ob in rig.rigidBodies() if str(ob.mmd_rigid.type) != '0']
    tracks = sorted({ob.mmd_rigid.bone for ob in dynamic if ob.mmd_rigid.bone})
    check(report, 'actual_dynamic_rigids_and_tracked_bones_present', bool(dynamic) and bool(tracks),
          {'dynamic_rigids': len(dynamic), 'tracks': tracks})
    weighted = weighted_vertices(meshes, set(tracks), cap=512)
    check(report, 'actual_physics_bone_weighted_source_samples', bool(weighted),
          {name: {'source_weighted_vertices': total, 'sampled': len(ids)} for name, (_, ids, total) in weighted.items()})
    diagonal, center = model_scale(meshes)
    epsilon, bound = max(diagonal * 1e-7, 1e-9), diagonal * 20.
    first_rigids = first_bones = first_mesh = None
    max_rigid = max_bone = max_mesh = max_radius = 0.
    frames = []
    # Start at cache start, evaluate EVERY frame in order. No frame jumping/bake.
    for frame in range(1, 62):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        depsgraph = bpy.context.evaluated_depsgraph_get()
        rigid_matrices = {ob.name: [list(row) for row in ob.evaluated_get(depsgraph).matrix_world] for ob in dynamic}
        evaluated_arm = arm.evaluated_get(depsgraph)
        bone_matrices = {name: [list(row) for row in (evaluated_arm.matrix_world @ evaluated_arm.pose.bones[name].matrix)] for name in tracks}
        rigid_points = {name: [row[3] for row in matrix[:3]] for name, matrix in rigid_matrices.items()}
        # Bone tails catch genuine tracked rotation even when an anchored head
        # remains fixed. Both endpoints are evaluated in the same dependency graph.
        bone_points = {name + ':' + endpoint: list(evaluated_arm.matrix_world @ getattr(evaluated_arm.pose.bones[name], endpoint))
                       for name in tracks for endpoint in ('head', 'tail')}
        mesh_points = original_surface_points(weighted, shell_attribute)
        check(report, 'sequential_evaluated_finite:%02d' % frame, finite([rigid_matrices, bone_matrices, mesh_points]))
        all_points = list(rigid_points.values()) + list(bone_points.values()) + [p for points in mesh_points.values() for p in points]
        radius = max((Vector(point) - center).length for point in all_points)
        max_radius = max(max_radius, radius)
        check(report, 'sequential_evaluated_model_relative_bound:%02d' % frame, radius <= bound,
              {'radius': radius, 'bound': bound})
        if first_mesh is None:
            first_rigids, first_bones, first_mesh = rigid_points, bone_points, mesh_points
        rigid_delta = max((Vector(point) - Vector(first_rigids[name])).length for name, point in rigid_points.items())
        bone_delta = max((Vector(point) - Vector(first_bones[name])).length for name, point in bone_points.items())
        mesh_delta = max_distance(first_mesh, mesh_points)
        max_rigid, max_bone, max_mesh = max(max_rigid, rigid_delta), max(max_bone, bone_delta), max(max_mesh, mesh_delta)
        frames.append({'frame': frame, 'rigid_max_translation': rigid_delta, 'bone_max_translation': bone_delta,
                       'weighted_mesh_max_displacement': mesh_delta, 'max_radius': radius})
    check(report, 'evaluated_native_dynamic_rigids_moved', max_rigid > epsilon, max_rigid)
    check(report, 'evaluated_native_tracked_bones_moved', max_bone > epsilon, max_bone)
    check(report, 'evaluated_actual_weighted_source_mesh_moved', max_mesh > epsilon, max_mesh)
    check(report, 'simulation_still_not_baked', not scene.rigidbody_world.point_cache.is_baked)
    report['simulation'] = {'frames': frames, 'sequential_range': [1, 61], 'model_diagonal': diagonal,
                            'motion_epsilon': epsilon, 'radius_bound': bound, 'max_radius': max_radius,
                            'max_displacement': {'dynamic_rigid': max_rigid, 'tracked_bone': max_bone, 'weighted_mesh': max_mesh},
                            'dynamic_rigids': len(dynamic), 'tracked_bones': len(tracks), 'not_baked': True}


def run(report, args, output):
    workflow, validation, adapter = enable_addons()
    check(report, 'goo_engine_44', bpy.app.version[:2] == (4, 4) and 'Goo' in bpy.app.version_string, bpy.app.version_string)
    latest_path = TEST_OUTPUTS / args.kind / 'latest.json'
    latest = json.loads(latest_path.read_text(encoding='utf-8')) if latest_path.is_file() else None
    report['fixture_latest'] = {'path': str(latest_path), 'status': latest.get('status') if latest else None}
    if args.source_artifact is None:
        check(report, 'fixture_latest_succeeded', latest is not None and str(latest.get('status', '')).startswith('pass'), report['fixture_latest'])
        artifact = latest.get('artifact') or {}
        check(report, 'fixture_latest_has_artifact', bool(artifact.get('path')))
        source = inside(artifact['path'], TEST_OUTPUTS)
    else:
        source = inside(args.source_artifact, TEST_OUTPUTS)
        artifact = {}
        report['explicit_source_artifact_override'] = str(source)
    check(report, 'source_is_existing_test_blend', source.is_file() and source.suffix.casefold() == '.blend', str(source))
    report['source_artifact'] = validation.artifact(source)
    source_sha = report['source_artifact']['sha256']
    check(report, 'latest_artifact_hash_matches_when_provided', not artifact.get('sha256') or artifact['sha256'] == source_sha)
    pmx_hashes = {}
    try:
        check(report, 'open_configured_test_artifact', bpy.ops.wm.open_mainfile(filepath=str(source), load_ui=True, use_scripts=False) == {'FINISHED'})
        module, rig, root, arm, meshes = configured_model(adapter)
        root_name = root.name
        (data, parts, rig, arm), repeated = guard(workflow, adapter, root)
        check(report, 'initial_saved_guard_passes_no_rebaseline', repeated['status'] == 'already_configured_noop')
        check(report, 'source_has_unbuilt_native_physics', not root.mmd_root.is_built and bool(list(rig.rigidBodies())) and bool(list(rig.joints())), native_inventory(rig))
        # Hash all PMX candidates in the native import folder, rather than invent a
        # hardcoded character/source path when mmd_tools persisted only a folder.
        if args.source_pmx:
            candidates = [args.source_pmx.expanduser().resolve()]
        else:
            folder = root.get('import_folder', '')
            candidates = sorted(Path(bpy.path.abspath(folder)).resolve().glob('*.pmx')) if folder else []
        for path in candidates:
            check(report, 'source_pmx_readable:' + path.name, path.is_file() and path.suffix.casefold() == '.pmx', str(path))
            pmx_hashes[str(path)] = validation.file_hash(path)
        report['source_pmx'] = {'hashes': pmx_hashes, 'scope': 'all PMX files in persisted native import_folder, or explicit --source-pmx; read-only',
                                'unavailable': not bool(pmx_hashes)}
        baseline = authored(validation, parts, root, arm, rig)
        if args.diagnostics:
            snapshot_authored(output, 'initial', validation, root, arm, parts)
        original_ids = identities(parts)
        guard_baseline = {key: data[key] for key in ('skeleton', 'mesh', 'shader', 'material_targets')}
        report['original_inventory'] = baseline
        shell_attribute = importlib.import_module('zzz_mmd_toon.outline_geometry').SHELL_ATTRIBUTE
        run_vmd(report, output, module, rig, root, arm, meshes, parts, workflow, validation, adapter, shell_attribute)
        check(report, 'vmd_preserved_all_authored_native_data', authored(validation, parts, root, arm, rig) == baseline)
        check(report, 'vmd_preserved_original_mesh_material_identity_no_split', identities(parts) == original_ids and
              {ob.as_pointer() for ob in rig.meshes()} == {ob.as_pointer() for ob in meshes})
        # build_physics reads zzz_run.output, NOT its output_dir argument. Change
        # only this output-routing field in memory; every stored guard is kept.
        physics_output = output / 'native_physics'
        physics_output.mkdir(exist_ok=False)
        relocated = json.loads(root['zzz_run'])
        relocated['output'] = str(physics_output)
        root['zzz_run'] = bpy.context.scene['zzz_run'] = json.dumps(relocated, ensure_ascii=False)
        bpy.context.scene.zzz_toon.output_dir = str(physics_output)
        check(report, 'only_output_routing_relocated_in_run_metadata',
              {key: value for key, value in relocated.items() if key != 'output'} == {key: value for key, value in data.items() if key != 'output'})
        scene = bpy.context.scene
        world = scene.rigidbody_world
        check(report, 'native_world_exists_unbaked_before_build', world is not None and not world.point_cache.is_baked)
        # Isolated generated artifact only; ensures requested sequential coverage.
        scene.frame_start, scene.frame_end = 1, max(scene.frame_end, 61)
        world.point_cache.frame_start, world.point_cache.frame_end = 1, max(world.point_cache.frame_end, 61)
        scene.frame_set(1)
        adapter.select_root(bpy.context, root)
        result = bpy.ops.zzz_toon.build_physics()
        check(report, 'actual_independent_sidebar_build_physics_finished', result == {'FINISHED'}, scene.zzz_toon.status)
        physical_validation = adapter.validate_physics(bpy.context, rig, root, arm)
        check(report, 'native_imported_rigid_joint_inventory_unchanged', native_inventory(rig) == baseline['native_physics'], physical_validation)
        if args.diagnostics:
            snapshot_authored(output, 'after_build', validation, root, arm, parts)
        check(report, 'build_preserved_all_authored_native_data', authored(validation, parts, root, arm, rig) == baseline)
        check(report, 'build_preserved_original_mesh_material_identity_no_split', identities(parts) == original_ids)
        checkpoint = Path(root.get('zzz_checkpoint', '')).resolve()
        check(report, 'new_checkpoint_inside_unique_output_and_ui', checkpoint.is_relative_to(physics_output.resolve()) and checkpoint.is_file() and
              str(checkpoint) == scene['zzz_checkpoint'] == scene.zzz_toon.checkpoint_path, str(checkpoint))
        native_report_path = physics_output / '原生物理构建报告.json'
        native_report = json.loads(native_report_path.read_text(encoding='utf-8'))
        physical = inside(native_report['artifact']['path'], physics_output)
        check(report, 'physical_artifact_saved_new_not_source', physical.is_file() and physical != source and Path(bpy.data.filepath).resolve() == physical)
        physical_sha = validation.file_hash(physical)
        report['physics'] = {'artifact': validation.artifact(physical), 'checkpoint': str(checkpoint), 'validation': physical_validation}
        check(report, 'reopen_new_native_physics_artifact', bpy.ops.wm.open_mainfile(filepath=str(physical), load_ui=True, use_scripts=False) == {'FINISHED'})
        module, rig, root, arm, meshes = configured_model(adapter, root_name)
        stored = json.loads(root['zzz_run'])
        reopened_parts = {int(ob['zzz_slot']): ob for ob in meshes
                          if ob.get('zzz_owner') == stored['owner'] and 'zzz_slot' in ob}
        if args.diagnostics:
            snapshot_authored(output, 'after_physics_reopen', validation, root, arm, reopened_parts)
        (reopened, parts, rig, arm), repeated = guard(workflow, adapter, root)
        check(report, 'reopened_saved_original_guards_unchanged', {key: reopened[key] for key in guard_baseline} == guard_baseline)
        check(report, 'reopen_preserved_all_authored_native_data', authored(validation, parts, root, arm, rig) == baseline)
        before_ids = identities(parts)
        before_objects = {ob.as_pointer() for ob in bpy.data.objects}
        noop = workflow.build_physics(bpy.context)
        check(report, 'reopened_repeat_native_physics_noop', noop.get('status') == 'already_built_noop' and
              {ob.as_pointer() for ob in bpy.data.objects} == before_objects and identities(parts) == before_ids, noop)
        check(report, 'reopened_native_validate_physics', adapter.validate_physics(bpy.context, rig, root, arm)['status'] == 'validated_built')
        check(report, 'reopened_sequential_cache_covers_1_to_61', bpy.context.scene.rigidbody_world.point_cache.frame_start == 1 and
              bpy.context.scene.rigidbody_world.point_cache.frame_end >= 61)
        evaluate_physics(report, rig, root, arm, meshes, adapter, shell_attribute)
        check(report, 'simulation_preserved_authored_native_data', authored(validation, parts, root, arm, rig) == baseline)
        check(report, 'saved_physics_artifact_not_overwritten_during_validation', validation.file_hash(physical) == physical_sha)
        report['status'] = 'pass_native_vmd_ui_physics_reopen_short_sequential_simulation'
    finally:
        check(report, 'configured_source_artifact_hash_unchanged', validation.file_hash(source) == source_sha)
        for path, sha in pmx_hashes.items():
            check(report, 'source_pmx_hash_unchanged:' + Path(path).name, validation.file_hash(path) == sha)


def main():
    args = arguments()
    output = TEST_OUTPUTS / 'motion' / args.kind / (datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '_' + uuid4().hex[:8])
    output.mkdir(parents=True, exist_ok=False)
    report = {'kind': args.kind, 'status': 'running', 'reader': bpy.app.version_string,
              'started_utc': datetime.now(timezone.utc).isoformat(), 'output': str(output), 'checks': [], 'limits': LIMITS}
    report_path = output / 'motion_physics.json'
    report['report'] = str(report_path)
    try:
        run(report, args, output)
    except Exception as exc:
        report.update(status='fail', error=str(exc), traceback=traceback.format_exc())
        raise
    finally:
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        write_new_json(report_path, report)
        # This pointer is the sole intentionally replaceable file; never replace
        # test_outputs/<kind>/latest.json or any historical report/project.
        with (output.parent / 'latest.json').open('w', encoding='utf-8') as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        print('HEADLESS ' + json.dumps({'status': report['status'], 'kind': args.kind,
              'checks': len(report['checks']), 'error': report.get('error'), 'report': str(report_path)}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
