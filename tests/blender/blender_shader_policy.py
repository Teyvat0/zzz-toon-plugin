"""TEST ONLY: synthetic Goo 4.4.3 RNA checks for the renderer shader policy.

Run: blender.exe --background --factory-startup --disable-autoexec -t 2
     --python-exit-code 1 --python tests/blender_shader_policy.py

No PMX, generated production artifact, renderer template, external image, save or
render is used. Materials/meshes/images are fabricated in memory; mmd_shader and
MaterialMorph groups come from the installed native MMD Tools implementation.
These are structural/guard tests, NOT pixel or original-game/MME equivalence proof.
Only stdout receives the report. Production and pre-existing tests are read-only.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import traceback
from types import SimpleNamespace

sys.dont_write_bytecode = True
import bpy
import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1])); import testenv

ROOT = Path(__file__).resolve().parents[2]
AUTHORITATIVE = testenv.goo_exe()
MMD_PARENT = testenv.mmd_parent()
DOMAIN = '1: Face, 2: Eye, 3: Body'
REPORT = {'schema': 'synthetic-shader-policy.v1', 'started_at_utc': datetime.now(timezone.utc).isoformat(),
          'status': 'running', 'cases': [], 'saved': False, 'rendered': False,
          'limits': ['Real RNA/node topology/guard evidence only; no shader pixel evaluation.',
                     'Synthetic surfaces have the required ZZZ_Toon core interface but are not the real shader.',
                     'Production may be concurrently edited by lead; per-run fingerprints identify tested code.']}
SEQUENCE = 0


def require(value, message):
    if not value:
        raise AssertionError(message)


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def protected_inputs():
    return {str(p.relative_to(ROOT)): fingerprint(p)
            for folder in (ROOT / 'zzz_mmd_toon', ROOT / 'tests' / 'blender', ROOT / 'tests' / 'unit', ROOT / 'tests' / 'tools')
            for p in folder.glob('*.py') if p.resolve() != Path(__file__).resolve()}


def run_case(name, operation):
    row = {'name': name}
    try:
        row['evidence'] = operation()
        row['status'] = 'pass'
    except Exception as exc:
        row.update(status='fail', error=str(exc), traceback=traceback.format_exc())
    REPORT['cases'].append(row)
    print('SHADER_POLICY_CASE ' + json.dumps(row, ensure_ascii=True), flush=True)


def unique(label):
    global SEQUENCE
    SEQUENCE += 1
    return 'POLICY_TEST_' + str(SEQUENCE) + '_' + label


def group(name, input_sockets, output_sockets):
    tree = bpy.data.node_groups.new(unique(name), 'ShaderNodeTree')
    for label, kind, value in input_sockets:
        socket = tree.interface.new_socket(name=label, in_out='INPUT', socket_type=kind)
        if value is not None:
            socket.default_value = value
    for label, kind in output_sockets:
        tree.interface.new_socket(name=label, in_out='OUTPUT', socket_type=kind)
    return tree, tree.nodes.new('NodeGroupInput'), tree.nodes.new('NodeGroupOutput')


def material_data(values):
    return SimpleNamespace(floats=values, get=lambda key: values.get(key))


def states(surface, values, role='hair'):
    info = {'limits': []}
    materials._states(surface, material_data(values), role, 1., info)
    return info


def source_material(*, double=True, cull=False):
    material = bpy.data.materials.new(unique('native'))
    material.mmd_material.diffuse_color = (.8, .7, .6)
    material.mmd_material.alpha = .6
    fn = FnMaterial(material)
    fn.update_diffuse_color()
    fn.update_alpha()
    material.mmd_material.is_double_sided = double
    material.use_backface_culling = cull
    material.blend_method = 'HASHED'
    native = material.node_tree.nodes.get('mmd_shader')
    require(native is not None and native.type == 'GROUP', 'Native MMD Tools failed to create mmd_shader')
    require(all(key in native.inputs for key in ('Diffuse Color', 'Alpha', 'Base Tex', 'Base Alpha')),
            'Native shader is missing required actual Morph inputs')
    native.inputs['Diffuse Color'].default_value = (.8, .7, .6, 1.)
    native.inputs['Alpha'].default_value = .6
    native.inputs['Base Alpha'].default_value = .5
    return material


def detached_surface(*, atlas=True, cull=True, aovs=True):
    surface = bpy.data.materials.new(unique('detached'))
    surface.use_nodes = True
    tree = surface.node_tree
    tree.nodes.clear()
    core_tree, inputs, outputs = group('core', [
        (DOMAIN, 'NodeSocketFloat', 3.), ('Base Color', 'NodeSocketColor', (1., 1., 1., 1.)),
        ('Alpha', 'NodeSocketFloat', 1.)], [
        ('Shader', 'NodeSocketShader'), ('Avatar', 'NodeSocketFloat'),
        ('AOV Normal', 'NodeSocketColor'), ('AOV Rim', 'NodeSocketColor')])
    emission = core_tree.nodes.new('ShaderNodeEmission')
    core_tree.links.new(inputs.outputs['Base Color'], emission.inputs['Color'])
    core_tree.links.new(emission.outputs[0], outputs.inputs['Shader'])
    core = tree.nodes.new('ShaderNodeGroup')
    core.name = toon_surface.CORE_NODE
    core.node_tree = core_tree
    base_tint = tree.nodes.new('ShaderNodeMixRGB')
    base_tint.name = toon_surface.BASE_TINT
    base_tint.blend_type = 'MULTIPLY'
    base_tint.inputs[0].default_value = 1.
    base_tint.inputs[1].default_value = (1., 1., 1., 1.)
    base_tint.inputs[2].default_value = (.3, .4, .5, 1.)
    tree.links.new(base_tint.outputs[0], core.inputs['Base Color'])
    alpha_mul = tree.nodes.new('ShaderNodeMath')
    alpha_mul.name = toon_surface.ALPHA_MUL
    alpha_mul.operation = 'MULTIPLY'
    alpha_mul.inputs[0].default_value = 1.
    alpha_mul.inputs[1].default_value = 1.
    tree.links.new(alpha_mul.outputs[0], core.inputs['Alpha'])
    output = tree.nodes.new('ShaderNodeOutputMaterial')
    tree.links.new(core.outputs['Shader'], output.inputs['Surface'])
    image = None
    if atlas:
        image = bpy.data.images.new(unique('exact_atlas'), width=2, height=2, alpha=True)
        image.pixels[:] = (1., .1, .2, 0., .2, .9, .3, .25, .3, .2, .8, .5, .4, .4, .4, 1.)
        uv = tree.nodes.new('ShaderNodeUVMap')
        uv.name = 'ExactAtlasUV'
        uv.uv_map = 'AuthorUV'
        texture = tree.nodes.new('ShaderNodeTexImage')
        texture.name = 'ExactAtlas'
        texture.image = image
        tree.links.new(uv.outputs['UV'], texture.inputs['Vector'])
        tree.links.new(texture.outputs['Color'], base_tint.inputs[1])
        tree.links.new(texture.outputs['Alpha'], alpha_mul.inputs[1])
    if aovs:
        aov = tree.nodes.new('ShaderNodeOutputAOV')
        aov.name = 'Eye'
        aov.aov_name = 'Eye'
    surface.use_backface_culling = cull
    return surface, image


def outline_material():
    material = bpy.data.materials.new(unique('outline'))
    material.use_nodes = True
    tree = material.node_tree
    tree.nodes.clear()
    shader = tree.nodes.new('ShaderNodeEmission')
    out = tree.nodes.new('ShaderNodeOutputMaterial')
    tree.links.new(shader.outputs[0], out.inputs['Surface'])
    return material


def attach_fixture(role, *, preserve=False, double=True, old_cull=False, atlas=True, surface_cull=True):
    source = source_material(double=double, cull=old_cull)
    surface, image = detached_surface(atlas=atlas, cull=surface_cull)
    outline = outline_material()
    identity = source.as_pointer(), source.mmd_material.material_id
    info = game_bridge.attach(source, surface, outline, unique('owner'), role=role,
                              preserve_source_texture=preserve)
    require((source.as_pointer(), source.mmd_material.material_id) == identity, 'Original Material identity/ID changed')
    wrapper = source.node_tree.nodes.get('ZZZ_GameEnhancement')
    require(wrapper is not None and wrapper.node_tree is not None, 'Missing committed game wrapper')
    require(source['zzz_render_policy'] == game_bridge.RENDER_POLICY, 'Missing render policy version stamp')
    return source, surface, wrapper, image, info


def part_for(material):
    mesh = bpy.data.meshes.new(unique('mesh'))
    mesh.from_pydata([(0., 0., 0.), (1., 0., 0.), (0., 1., 0.)], [], [(0, 1, 2)])
    mesh.materials.append(material)
    ob = bpy.data.objects.new(unique('part'), mesh)
    bpy.context.scene.collection.objects.link(ob)
    ob['zzz_material_ref_0'] = material
    return {0: ob}


def upstream(socket):
    require(socket.is_linked and len(socket.links) == 1, 'Expected exactly one upstream link: ' + socket.name)
    return socket.links[0].from_socket


def recursive_nodes(tree, seen=None):
    seen = set() if seen is None else seen
    if tree.as_pointer() in seen:
        return []
    seen.add(tree.as_pointer())
    rows = list(tree.nodes)
    for node in tree.nodes:
        if getattr(node, 'node_tree', None) is not None:
            rows += recursive_nodes(node.node_tree, seen)
    return rows


def eye_structure(role, preserve=False):
    source, _, wrapper, image, info = attach_fixture(role, preserve=preserve)
    tree = wrapper.node_tree
    tint = game_bridge.eye_shadow_tint_input(source)
    require(tint is not None, 'EyeShadowTint instance socket absent after interface update/pruning')
    require(all(abs(a - b) < 1e-6 for a, b in zip(tint.default_value, game_bridge.EYE_SHADOW_TINT)),
            'EyeShadowTint interface default failed to synchronize onto instance')
    input_node = next(n for n in tree.nodes if n.type == 'GROUP_INPUT')
    require(game_bridge.EYE_SHADOW_TINT_SOCKET in input_node.outputs, 'Existing GroupInput was not synchronized')
    require(input_node.outputs[game_bridge.EYE_SHADOW_TINT_SOCKET].is_linked, 'Tint is disconnected after pruning')
    output = next(n for n in tree.nodes if n.type == 'GROUP_OUTPUT' and n.is_active_output)
    shader = upstream(output.inputs['Shader'])
    require(shader.node.bl_idname == 'ShaderNodeBsdfTransparent', 'Transparent is not the direct group Shader output')
    nodes = recursive_nodes(tree)
    require(not any(n.bl_idname == 'ShaderNodeOutputAOV' for n in nodes), 'Eye overlay retains an executable AOV node')
    require(not any(n.name == toon_surface.CORE_NODE for n in nodes), 'Eye overlay retains ZZZ_Toon core')
    require(not any(n.name.startswith('ZZZ_Outline_') or n.name.startswith('ZZZ_Shell') for n in nodes),
            'Eye overlay unexpectedly retained shell/outline graph')
    native = source.node_tree.nodes['mmd_shader']
    require(upstream(wrapper.inputs['NativeAlpha']) == native.outputs['ZZZ_Alpha'], 'Native Alpha is not live')
    native_output = next(n for n in native.node_tree.nodes if n.type == 'GROUP_OUTPUT' and n.is_active_output)
    require(upstream(native_output.inputs['ZZZ_Alpha']).name == 'Alpha', 'Exposed Alpha bypasses native INPUT')
    live = tree.nodes['ZZZ_EyeShadowLiveTransmittance']
    require(live.blend_type == 'MIX' and tuple(live.inputs[1].default_value) == (1., 1., 1., 1.),
            'Alpha=0 does not mix towards white ray transmittance')
    effective = upstream(live.inputs[0])
    if preserve:
        require(effective.node.name == 'ZZZ_SourceOverlayAlpha', 'Preserved source alpha missing from coverage')
        require(upstream(effective.node.inputs[1]).name == 'SourceAlpha', 'Native source alpha lost')
        require(upstream(wrapper.inputs['SourceAlpha']) == native.outputs['ZZZ_BaseAlpha'], 'Source Alpha not exposed')
        require(not any(n.type == 'TEX_IMAGE' for n in nodes), 'Borrowed atlas unexpectedly remains for source-preserved eye')
    elif role == 'eye_shadow_texture':
        require(effective.node.name == 'ZZZ_EyeShadowCoverage', 'Texture eye shadow does not multiply exact atlas alpha')
        alpha = upstream(effective.node.inputs[1])
        require(alpha.name == 'Alpha' and alpha.node.type == 'TEX_IMAGE' and alpha.node.image == image,
                'Eye coverage uses pigment/luma/constant/another atlas instead of exact atlas Alpha')
        vector = upstream(alpha.node.inputs['Vector'])
        require(vector.node.type == 'UVMAP' and vector.node.uv_map == 'AuthorUV', 'Atlas UV provenance was pruned')
        require(upstream(effective.node.inputs[0]).name == 'NativeAlpha', 'Atlas Alpha replaced native Morph Alpha')
    else:
        require(effective.name == 'NativeAlpha', 'Textureless eye coverage is not native Alpha only')
        require(not any(n.type == 'TEX_IMAGE' for n in nodes), 'Textureless eye retains unused atlas node')
    return {'role': role, 'preserve_source_texture': preserve, 'wrapper_inputs': [s.name for s in wrapper.inputs],
            'remaining_node_names': sorted(n.name for n in tree.nodes), 'bridge': info}


def state_rules():
    actual = []
    for values, want in [({'_Cull': 2., '_DoubleSided': 1.}, True),
                         ({'_Cull': 0., '_DoubleSided': 1.}, False),
                         ({'_DoubleSided': 1.}, False), ({}, True)]:
        material = bpy.data.materials.new(unique('state'))
        info = states(material, values)
        require(material.use_backface_culling == want, 'Direct hair _states cull policy mismatch: ' + str(values))
        require(resources.preview_backface_culling(material_data(values), 'hair') == want,
                'Pure preview helper diverged from actual _states RNA')
        actual.append({'role': 'hair', 'json': values, 'backface_culling': material.use_backface_culling,
                       'diagnostics': info})
    # Eye domains intentionally have double-sided surface policy, independent of
    # JSON cull. Native PMX single-sidedness is only applied in the final bridge.
    for role in ('eye', 'mouth', 'eyebrow', 'eye_shadow', 'eye_shadow_texture', 'eye_highlight'):
        material = bpy.data.materials.new(unique('eye_state'))
        values = {'_Cull': 2., '_DoubleSided': 0.}
        info = states(material, values, role)
        require(not material.use_backface_culling, 'Eye semantic double-sided state lost: ' + role)
        require(resources.preview_backface_culling(material_data(values), role) is False,
                'Pure eye cull helper diverged from _states')
        actual.append({'role': role, 'json': values, 'backface_culling': False, 'diagnostics': info})
    return actual


def raster_rules():
    evidence = []
    for label, double, old, detached, preserve, want in [
            ('direct JSON cull2 vs double1', True, False, True, False, True),
            ('native PMX single-sided overrides detached double', False, False, False, False, True),
            ('native old cull preserved', True, True, False, False, True),
            ('inferred layer keeps native double', True, False, True, True, False),
            ('inferred native single-sided stays single', False, False, False, True, True)]:
        source, _, _, _, info = attach_fixture('hair', preserve=preserve, double=double,
                                             old_cull=old, surface_cull=detached)
        require(source.use_backface_culling == want, label)
        require(info['culling']['enabled'] == want, 'Bridge diagnostics disagree with actual RNA')
        evidence.append({'label': label, 'actual_cull': source.use_backface_culling, 'policy': info['culling']})
    return evidence


def tint_and_guards(role):
    source, _, wrapper, _, _ = attach_fixture(role)
    parts = part_for(source)
    before = validation.shader_state(parts)
    baseline_diffuse = tuple(source['zzz_native_baseline_diffuse'])
    tint = game_bridge.eye_shadow_tint_input(source)
    require(tint is not None, 'Editable eye tint missing')
    old = tuple(tint.default_value)
    allowed = []
    for value in ((.2, .3, .4, 1.), (1., 1., 1., 1.), (0., 0., 0., 1.)):
        tint.default_value = value
        require(tuple(tint.default_value) != old, 'Tint RNA edit did not change')
        require(validation.shader_state(parts) == before, 'Documented tint edit changed authored renderer baseline')
        require(tuple(source['zzz_native_baseline_diffuse']) == baseline_diffuse, 'Tint silently re-baselined native Diffuse')
        allowed.append(list(tint.default_value))
    tint.default_value = old
    require(validation.shader_state(parts) == before, 'Tint restoration did not restore signature')
    native = source.node_tree.nodes['mmd_shader']
    old_alpha = float(native.inputs['Alpha'].default_value)
    native.inputs['Alpha'].default_value = 0.
    require(validation.shader_state(parts) == before, 'Normal native Alpha animation was frozen')
    native.inputs['Alpha'].default_value = old_alpha
    spec = SimpleNamespace(name=unique('native_morph'), offset_type='MULT', ambient_color=(1., 1., 1.),
                           diffuse_color=(.6, .8, .9, 0.), specular_color=(1., 1., 1.), shininess=1.,
                           edge_color=(1., 1., 1., 1.), texture_factor=(1., 1., 1., 1.),
                           sphere_texture_factor=(1., 1., 1., 1.), toon_texture_factor=(1., 1., 1., 1.))
    morphs = _MaterialMorph.setup_morph_nodes(source, [spec])
    require(bool(morphs) and native.inputs['Alpha'].is_linked, 'Real native MaterialMorph did not relink Alpha')
    require(validation.shader_state(parts) == before, 'Real native MaterialMorph binding changed authored renderer guard')
    morphs[0].inputs['Fac'].default_value = 1.
    require(validation.shader_state(parts) == before, 'Native MaterialMorph factor animation was frozen')
    require(upstream(wrapper.inputs['NativeAlpha']) == native.outputs['ZZZ_Alpha'], 'Morph binding broke bridge Alpha')
    rejected = []
    def changed(label, mutate, restore):
        try:
            mutate()
            try:
                now = validation.shader_state(parts)
            except RuntimeError as exc:
                rejected.append({'mutation': label, 'rejected': str(exc)})
            else:
                require(now != before, 'Guard missed mutation: ' + label)
                rejected.append({'mutation': label, 'different_signature': True})
        finally:
            restore()
        require(validation.shader_state(parts) == before, 'Failed to restore guarded mutation: ' + label)
    cull = source.use_backface_culling
    changed('material cull', lambda: setattr(source, 'use_backface_culling', not cull),
            lambda: setattr(source, 'use_backface_culling', cull))
    tree = wrapper.node_tree
    output = next(n for n in tree.nodes if n.type == 'GROUP_OUTPUT' and n.is_active_output)
    link = output.inputs['Shader'].links[0]
    a, b = link.from_socket, link.to_socket
    changed('direct Transparent output link', lambda: tree.links.remove(output.inputs['Shader'].links[0]),
            lambda: tree.links.new(a, b))
    math = tree.nodes['ZZZ_EyeShadowLiveTransmittance']
    operation = math.blend_type
    changed('transmittance MIX operation', lambda: setattr(math, 'blend_type', 'MULTIPLY'),
            lambda: setattr(math, 'blend_type', operation))
    other = wrapper.inputs['SourceAlpha']
    original = float(other.default_value)
    changed('non-Tint wrapper input', lambda: setattr(other, 'default_value', .123),
            lambda: setattr(other, 'default_value', original))
    extra = []
    def add_link():
        node = source.node_tree.nodes.new('ShaderNodeRGB')
        node.name = unique('tint_override')
        extra.append(node)
        source.node_tree.links.new(node.outputs[0], tint)
        require(game_bridge.eye_shadow_tint_input(source) is None, 'Linked tint is still treated as live editable default')
    changed('linked Tint control', add_link, lambda: source.node_tree.nodes.remove(extra.pop()))
    return {'role': role, 'baseline_shader_state': before, 'allowed_tints': allowed,
            'native_morph_node_count': len(morphs), 'guarded_mutations': rejected}


def missing_alpha_rollback():
    source = source_material()
    surface, _ = detached_surface(atlas=False)
    outline = outline_material()
    old_group = source.node_tree.nodes['mmd_shader'].node_tree
    old_blend, old_cull = source.blend_method, source.use_backface_culling
    before = validation.graph_state(source.node_tree)
    try:
        game_bridge.attach(source, surface, outline, unique('failure_owner'), role='eye_shadow_texture')
    except RuntimeError as exc:
        require('atlas Alpha' in str(exc), 'Missing atlas failed for an unrelated reason: ' + str(exc))
        error = str(exc)
    else:
        raise AssertionError('Texture eye shadow accepted no atlas Alpha')
    require(source.node_tree.nodes['mmd_shader'].node_tree == old_group, 'Failure retained private native group')
    require(source.blend_method == old_blend and source.use_backface_culling == old_cull, 'Failure retained raster mutation')
    require(not source.get('zzz_owner') and not source.get('zzz_render_policy'), 'Failure committed ownership/policy')
    require(validation.graph_state(source.node_tree) == before, 'Failure changed original graph/links')
    return {'expected_failure': error, 'original_graph_restored': True}


def strict_off_raster_mismatch():
    # This is deliberately an integration safety counterexample, not an assertion
    # that the current OFF matcher is safe. Native side flags can be identical
    # while the direct donor and preserved layer get different final raster cull.
    donor = source_material(double=True, cull=False)
    effect = source_material(double=True, cull=False)
    surface, _ = detached_surface(cull=True)
    direct = game_bridge.culling_policy(donor, surface, role='hair')
    inferred = game_bridge.culling_policy(effect, surface, role='hair', preserve_source_texture=True)
    require(donor.mmd_material.is_double_sided == effect.mmd_material.is_double_sided,
            'Counterexample did not have equal native sidedness')
    require(direct['enabled'] != inferred['enabled'], 'Expected direct/inferred raster divergence was not demonstrated')
    return {'native_side_flags_equal': True, 'direct_donor_policy': direct, 'inferred_effect_policy': inferred,
            'safety_requirement': 'MME_DUPLICATE_OFF must be retracted unless actual final raster coverage is also proved.'}


def culling_unknown_native():
    rejected = []
    for label, source in [
            ('native missing', SimpleNamespace(use_backface_culling=False)),
            ('double-sided missing', SimpleNamespace(use_backface_culling=False, mmd_material=SimpleNamespace())),
            ('old cull missing', SimpleNamespace(mmd_material=SimpleNamespace(is_double_sided=True))),
            ('unknown double', SimpleNamespace(use_backface_culling=False,
                                             mmd_material=SimpleNamespace(is_double_sided=None)))]:
        for preserve in (False, True):
            result = resources.native_preview_culling(source, True, preserve_source_texture=preserve)
            require(result is None, 'Incomplete native raster evidence was guessed: ' + label)
            rejected.append({'case': label, 'preserve_source_texture': preserve, 'final_cull': result})
    # One affirmative source restriction suffices even if the other flag is
    # unavailable: preserved backface-cull still covers fewer sides, never more.
    for source in (SimpleNamespace(use_backface_culling=True),
                   SimpleNamespace(mmd_material=SimpleNamespace(is_double_sided=False))):
        require(resources.native_preview_culling(source, False) is True,
                'Proven native single-sided restriction was dropped')
    complete = SimpleNamespace(use_backface_culling=False,
                               mmd_material=SimpleNamespace(is_double_sided=True))
    for unknown in (None, 0, 1, 'False'):
        require(resources.native_preview_culling(complete, unknown) is None,
                'Unknown/non-bool detached raster evidence was guessed')
        require(resources.native_preview_culling(complete, unknown, preserve_source_texture=True) is False,
                'Native-preserved overlay unnecessarily borrowed unknown detached state')
    return {'unknown_native_cases': rejected, 'affirmative_single_sided_cases': 2,
            'unknown_direct_detached_cases_rejected': 4, 'inferred_unknown_detached_uses_native': 4}


def no_tint_outside_eye():
    source, _, wrapper, _, _ = attach_fixture('hair')
    require(game_bridge.eye_shadow_tint_input(source) is None, 'Non-eye domain acquired editable Tint exemption')
    require(game_bridge.EYE_SHADOW_TINT_SOCKET not in wrapper.inputs, 'Non-eye interface acquired eye Tint')
    tree = wrapper.node_tree
    require(any(n.name == toon_surface.CORE_NODE for n in recursive_nodes(tree)),
            'Non-eye domain lost required ZZZ_Toon core')
    aovs = {n.aov_name for n in recursive_nodes(tree) if n.bl_idname == 'ShaderNodeOutputAOV'}
    require({'Avatar', 'Normal', 'Rim'} <= aovs, 'Non-eye domain lost core AOV outputs: ' + str(aovs))
    parts = part_for(source)
    baseline = validation.shader_state(parts)
    source.use_backface_culling = not source.use_backface_culling
    require(validation.shader_state(parts) != baseline, 'Non-eye culling was not protected')
    return {'role': 'hair', 'editable_eye_tint': False, 'non_eye_core_and_aovs_retained': True,
            'non_eye_cull_guarded': True}


def invalid_tint_rejected():
    source, _, wrapper, _, _ = attach_fixture('eye_shadow')
    tint = game_bridge.eye_shadow_tint_input(source)
    parts = part_for(source)
    before = validation.shader_state(parts)
    old = tuple(tint.default_value)
    rejected = []
    for value in ((-.1, .5, .5, 1.), (1.1, .5, .5, 1.), (float('nan'), .5, .5, 1.)):
        try:
            tint.default_value = value
            actual = tuple(tint.default_value)
            if all(x == x and 0. <= x <= 1. for x in actual):
                # RNA may clamp invalid defaults before the renderer sees them.
                rejected.append({'requested': repr(value), 'rna_clamped_to_valid': list(actual)})
                continue
            try:
                validation.shader_state(parts)
            except RuntimeError as exc:
                require('0..1' in str(exc), 'Invalid Tint failed for an unrelated reason')
                rejected.append({'requested': repr(value), 'rejected': str(exc)})
            else:
                raise AssertionError('Invalid eye Tint bypassed finite 0..1 validation')
        finally:
            tint.default_value = old
        require(validation.shader_state(parts) == before, 'Invalid Tint test failed to restore baseline')
    require(validation.shader_state(parts) == before, 'Final Tint restoration failed')
    # An unmarked replacement interface must lose the one editable-default
    # exemption; changing its value must not silently hide graph tampering.
    marker = wrapper.node_tree['zzz_eye_shadow_tint_control']
    del wrapper.node_tree['zzz_eye_shadow_tint_control']
    try:
        require(game_bridge.eye_shadow_tint_input(source) is None, 'Missing control marker still exempts Tint')
        require(validation.shader_state(parts) != before, 'Removing editable-control marker was not guarded')
    finally:
        wrapper.node_tree['zzz_eye_shadow_tint_control'] = marker
    require(validation.shader_state(parts) == before, 'Control marker restoration changed signature')
    return {'invalid_values': rejected, 'control_marker_removal_guarded': True}


def old_policy_rejected():
    root = bpy.data.objects.new(unique('old_policy_root'), None)
    bpy.context.scene.collection.objects.link(root)
    root['zzz_run'] = json.dumps({'version': workflow.VERSION, 'mesh_guard_schema': validation.MESH_GUARD_SCHEMA,
                                  'render_policy': 'legacy-pre-v2'})
    try:
        workflow._existing(bpy.context, root, '', .001)
    except RuntimeError as exc:
        require('旧版配置' in str(exc), 'Legacy renderer policy failed for an unrelated reason')
        return {'legacy_policy_rejected_before_dependency_checks': str(exc)}
    raise AssertionError('Old render policy unexpectedly accepted without migration')


def main():
    require(Path(bpy.app.binary_path).resolve() == AUTHORITATIVE.resolve(), 'Not the explicitly authorized Goo executable')
    require(bpy.app.version == (4, 4, 3) and 'Goo' in bpy.app.version_string, 'Expected authoritative Goo 4.4.3')
    require(not bpy.data.filepath, 'This test must start from factory startup without opening a project')
    REPORT['reader'] = {'executable': bpy.app.binary_path, 'version': bpy.app.version_string,
                        'build_hash': bpy.app.build_hash.decode('ascii'), 'threads': bpy.context.scene.render.threads}
    REPORT['test_script_sha256'] = fingerprint(Path(__file__))
    REPORT['inputs_before'] = protected_inputs()
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(MMD_PARENT))
    import mmd_tools
    mmd_tools.register()
    global game_bridge, materials, resources, validation, workflow, toon_surface, FnMaterial, _MaterialMorph
    from zzz_mmd_toon import game_bridge, materials, resources, validation, workflow, toon_surface
    from mmd_tools.core.material import FnMaterial
    from mmd_tools.core.shader import _MaterialMorph
    REPORT['render_policy'] = game_bridge.RENDER_POLICY
    # Priority: interface new_socket() after GroupInput already exists, then prune.
    run_case('eye_shadow_interface_and_pruning', lambda: eye_structure('eye_shadow'))
    run_case('eye_shadow_texture_interface_and_exact_alpha', lambda: eye_structure('eye_shadow_texture'))
    run_case('preserved_eye_uses_native_base_alpha', lambda: eye_structure('eye_shadow_texture', True))
    run_case('direct_json_cull_states', state_rules)
    run_case('native_direct_inferred_final_raster', raster_rules)
    run_case('unknown_native_raster_fail_closed', culling_unknown_native)
    run_case('strict_off_final_raster_counterexample', strict_off_raster_mismatch)
    run_case('non_eye_does_not_acquire_tint_exemption', no_tint_outside_eye)
    run_case('eye_shadow_live_tint_native_morph_and_guard', lambda: tint_and_guards('eye_shadow'))
    run_case('textured_eye_live_tint_native_morph_and_guard', lambda: tint_and_guards('eye_shadow_texture'))
    run_case('invalid_eye_tint_and_control_marker_guard', invalid_tint_rejected)
    run_case('missing_exact_atlas_alpha_rollback', missing_alpha_rollback)
    run_case('old_render_policy_rejected_without_rebaseline', old_policy_rejected)
    REPORT['inputs_after'] = protected_inputs()
    REPORT['concurrent_input_changes'] = {p: {'before': value, 'after': REPORT['inputs_after'].get(p)}
                                          for p, value in REPORT['inputs_before'].items()
                                          if REPORT['inputs_after'].get(p) != value}
    REPORT['new_external_input_files'] = sorted(set(REPORT['inputs_after']) - set(REPORT['inputs_before']))
    REPORT['case_totals'] = {state: sum(row['status'] == state for row in REPORT['cases']) for state in ('pass', 'fail')}
    REPORT['status'] = 'pass_structural_synthetic_only' if not REPORT['case_totals']['fail'] else 'fail'
    REPORT['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
    print('HEADLESS ' + json.dumps(REPORT, ensure_ascii=True), flush=True)
    if REPORT['case_totals']['fail']:
        raise RuntimeError('Synthetic shader policy cases failed: ' + str(REPORT['case_totals']))


if __name__ == '__main__':
    main()
