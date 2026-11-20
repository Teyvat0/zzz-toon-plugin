"""Game JSON shader on the SAME original Material; native Morph inputs stay live."""
import bpy
from .outline_geometry import SHELL_ATTRIBUTE
from . import resources, toon_surface

# Incompatible authored shader policy: old saved configurations must be rebuilt
# from trusted PMX / a pre-shading checkpoint, never silently re-baselined.
RENDER_POLICY = 'mmd-game.v2-native-cull-transparent-eye-shadow'
EYE_SHADOW_ROLES = frozenset({'eye_shadow', 'eye_shadow_texture'})
EYE_SHADOW_TINT_SOCKET = 'EyeShadowTint'
# Linear transmittance, not display-sRGB pigment or opacity. Alpha is not used.
EYE_SHADOW_TINT = (.713, .687, .687, 1.)


def culling_policy(source, surface, *, role, preserve_source_texture=False, override='AUTO'):
    """MMD preview raster policy; not a claim about Unity/game pass precedence."""
    native = getattr(source, 'mmd_material', None)
    double = getattr(native, 'is_double_sided', None)
    old = bool(source.use_backface_culling)
    enabled = resources.native_preview_culling(source, surface.use_backface_culling,
        preserve_source_texture=preserve_source_texture)
    if enabled is None:
        raise RuntimeError('原材质缺少可靠单/双面状态，不能推断最终背面剔除: ' + source.name)
    if old or double is False:
        reason = 'preserve native PMX single-sided surface'
    elif preserve_source_texture:
        # Borrowing JSON parameters does not prove donor winding/raster semantics.
        reason = 'inferred source overlay retains native culling'
    else:
        reason = 'direct JSON/semantic MMD preview surface policy'
    if override in ('ON', 'OFF'):
        enabled, reason = override == 'ON', 'user override ' + override
    return {'enabled': enabled, 'reason': reason, 'native_backface_culling': old,
            'native_double_sided': double, 'detached_backface_culling': bool(surface.use_backface_culling),
            'inferred_source_overlay': bool(preserve_source_texture)}


def eye_shadow_tint_input(material):
    """The one documented editable renderer input; graph/links stay guarded."""
    if material.get('zzz_render_policy') != RENDER_POLICY or material.get('preview_role') not in EYE_SHADOW_ROLES:
        return None
    tree = material.node_tree if material.use_nodes else None
    wrapper = tree.nodes.get('ZZZ_GameEnhancement') if tree else None
    if wrapper is None or wrapper.type != 'GROUP' or wrapper.node_tree is None:
        return None
    if wrapper.node_tree.get('zzz_eye_shadow_tint_control') != EYE_SHADOW_TINT_SOCKET:
        return None
    socket = wrapper.inputs.get(EYE_SHADOW_TINT_SOCKET)
    return socket if socket is not None and not socket.is_linked else None


def _copy_graph(material, owner, *, destination=None, prefix=''):
    source = material.node_tree
    tree = destination or bpy.data.node_groups.new('ZZZ_Game_' + material.name, 'ShaderNodeTree')
    tree['zzz_owner'] = owner
    clones = {}
    for node in source.nodes:
        if node.type == 'OUTPUT_MATERIAL':
            continue
        clone = tree.nodes.new(node.bl_idname)
        clone.name, clone.label, clone.location = prefix + node.name, node.label, node.location
        for prop in ('operation', 'blend_type', 'aov_name', 'attribute_name', 'attribute_type', 'uv_map',
                     'interpolation', 'extension', 'projection', 'data_type', 'use_clamp', 'mute'):
            if hasattr(node, prop):
                setattr(clone, prop, getattr(node, prop))
        if node.type == 'GROUP':
            clone.node_tree = node.node_tree
        if getattr(node, 'image', None):
            clone.image = node.image
        if node.type == 'VALTORGB':
            ramp = clone.color_ramp
            ramp.interpolation = node.color_ramp.interpolation
            while len(ramp.elements) < len(node.color_ramp.elements):
                ramp.elements.new(1.)
            for a, b in zip(node.color_ramp.elements, ramp.elements):
                b.position, b.color = a.position, a.color
        for a, b in zip(node.inputs, clone.inputs):
            if hasattr(a, 'default_value'):
                b.default_value = a.default_value
        if node.type in {'RGB', 'VALUE'}:
            for a, b in zip(node.outputs, clone.outputs):
                b.default_value = a.default_value
        clones[node] = clone
    for link in source.links:
        if link.from_node in clones and link.to_node in clones:
            tree.links.new(clones[link.from_node].outputs[list(link.from_node.outputs).index(link.from_socket)],
                           clones[link.to_node].inputs[list(link.to_node.inputs).index(link.to_socket)])
    original = next(n for n in source.nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output and n.inputs['Surface'].is_linked)
    link = original.inputs['Surface'].links[0]
    shader = clones[link.from_node].outputs[list(link.from_node.outputs).index(link.from_socket)]
    return tree, shader


def _native_outputs(native, owner):
    """Expose INPUT values after native MaterialMorph chains, not stale outer links."""
    old = native.node_tree
    tree = old.copy(); tree.name = 'ZZZ_NativeMorph_' + old.name; tree['zzz_owner'] = owner
    src = next((n for n in tree.nodes if n.type == 'GROUP_INPUT'), None)
    out = next((n for n in tree.nodes if n.type == 'GROUP_OUTPUT' and n.is_active_output), None)
    if src is None or out is None:
        raise RuntimeError('原生 MMD shader 缺少活动输入/输出节点')
    for key, name, typ in (('Diffuse Color', 'ZZZ_Diffuse', 'NodeSocketColor'), ('Alpha', 'ZZZ_Alpha', 'NodeSocketFloat'),
                           ('Base Tex', 'ZZZ_BaseColor', 'NodeSocketColor'), ('Base Alpha', 'ZZZ_BaseAlpha', 'NodeSocketFloat')):
        if key not in native.inputs:
            raise RuntimeError('原生 MMD shader 缺少 Morph 输入: ' + key)
        tree.interface.new_socket(name=name, in_out='OUTPUT', socket_type=typ)
        tree.links.new(src.outputs[key], out.inputs[name])
    values = {s.identifier: (s.default_value[:] if hasattr(s.default_value, '__len__') and not isinstance(s.default_value, str) else s.default_value)
              for s in native.inputs if hasattr(s, 'default_value')}
    native.node_tree = tree
    for socket in native.inputs:
        if socket.identifier in values and not socket.is_linked:
            socket.default_value = values[socket.identifier]
    return tree


def _shell_mask(tree):
    attr = tree.nodes.new('ShaderNodeAttribute'); attr.name = 'ZZZ_OutlineShellMask'
    attr.attribute_name = SHELL_ATTRIBUTE; attr.attribute_type = 'GEOMETRY'
    inverse = tree.nodes.new('ShaderNodeMath'); inverse.name = 'ZZZ_SurfaceOnly'; inverse.operation = 'SUBTRACT'
    inverse.inputs[0].default_value = 1.; tree.links.new(attr.outputs['Fac'], inverse.inputs[1])
    return attr.outputs['Fac'], inverse.outputs[0]


def _mask_aovs(tree, surface_factor, only=None):
    # AOV nodes execute even if their Shader branch is mixed out. Suppress every
    # Color/Value write on generated shells, including the toon core's AOV outputs.
    for aov in list(tree.nodes):
        if aov.bl_idname != 'ShaderNodeOutputAOV' or (only is not None and aov not in only):
            continue
        for socket in aov.inputs:
            old = socket.links[0].from_socket if socket.is_linked else None
            value = socket.default_value[:] if hasattr(socket.default_value, '__len__') else socket.default_value
            if socket.type == 'RGBA':
                mul = tree.nodes.new('ShaderNodeMixRGB'); mul.name = 'ZZZ_SurfaceAOV_' + aov.aov_name
                mul.blend_type = 'MULTIPLY'; mul.inputs[0].default_value = 1.
                if old is not None: tree.links.new(old, mul.inputs[1])
                else: mul.inputs[1].default_value = value
                tree.links.new(surface_factor, mul.inputs[2]); tree.links.new(mul.outputs[0], socket)
            else:
                mul = tree.nodes.new('ShaderNodeMath'); mul.name = 'ZZZ_SurfaceAOV_' + aov.aov_name; mul.operation = 'MULTIPLY'
                if old is not None: tree.links.new(old, mul.inputs[0])
                else: mul.inputs[0].default_value = value
                tree.links.new(surface_factor, mul.inputs[1]); tree.links.new(mul.outputs[0], socket)


def attach(source, surface, outline, owner, *, role, preserve_source_texture=False, cull='AUTO'):
    """Commit only predecoded/prehashed inputs; restore local original links on error."""
    if source.get('zzz_owner'):
        raise RuntimeError('原材质已有渲染挂接: ' + source.name)
    native = source.node_tree.nodes.get('mmd_shader') if source.use_nodes else None
    if native is None or native.type != 'GROUP':
        raise RuntimeError('原材质缺少 MMD Tools 原生 shader，不能安全保留材质 Morph: ' + source.name)
    tree = source.node_tree
    out = next((n for n in tree.nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output), None)
    if out is None:
        raise RuntimeError('原材质输出丢失: ' + source.name)
    old_group = native.node_tree
    previous = [(l.from_socket, l.to_socket) for l in out.inputs['Surface'].links]
    old_blend, old_cull = source.blend_method, source.use_backface_culling
    created = []; group = None; owned_native = None
    try:
        group, surface_shader = _copy_graph(surface, owner)
        group.interface.new_socket(name='Shader', in_out='OUTPUT', socket_type='NodeSocketShader')
        for name, typ in (('DiffuseRatio', 'NodeSocketColor'), ('NativeAlpha', 'NodeSocketFloat'),
                          ('SourceColor', 'NodeSocketColor'), ('SourceAlpha', 'NodeSocketFloat')):
            group.interface.new_socket(name=name, in_out='INPUT', socket_type=typ)
        inputs = group.nodes.new('NodeGroupInput'); output = group.nodes.new('NodeGroupOutput')
        core = group.nodes[toon_surface.CORE_NODE]
        is_shadow = role in EYE_SHADOW_ROLES
        if is_shadow:
            tint_socket = group.interface.new_socket(name=EYE_SHADOW_TINT_SOCKET, in_out='INPUT', socket_type='NodeSocketColor')
            tint_socket.default_value = EYE_SHADOW_TINT
            group['zzz_eye_shadow_tint_control'] = EYE_SHADOW_TINT_SOCKET
            # Transparent overlays must not execute Forward's black lighting or
            # Normal/Rim/Eye AOVs. Retain only the independently resolved atlas/UV.
            for node in list(group.nodes):
                if node.bl_idname == 'ShaderNodeOutputAOV':
                    group.nodes.remove(node)
        else:
            shell_factor, surface_factor = _shell_mask(group); _mask_aovs(group, surface_factor)
        baseline = tuple(native.inputs['Diffuse Color'].default_value)
        owned_native = _native_outputs(native, owner)
        wrapper = tree.nodes.new('ShaderNodeGroup'); created.append(wrapper)
        wrapper.name = 'ZZZ_GameEnhancement'; wrapper.node_tree = group
        base_tint, alpha_mul = group.nodes[toon_surface.BASE_TINT], group.nodes[toon_surface.ALPHA_MUL]
        if preserve_source_texture:
            group.links.new(inputs.outputs['SourceColor'], base_tint.inputs[1])
        color = group.nodes.new('ShaderNodeMixRGB'); color.name = 'ZZZ_ColorMorph'
        color.blend_type = 'MULTIPLY'; color.inputs[0].default_value = 1.
        color.inputs[1].default_value = base_tint.inputs[2].default_value
        group.links.new(inputs.outputs['DiffuseRatio'], color.inputs[2]); group.links.new(color.outputs[0], base_tint.inputs[2])
        effective_alpha = inputs.outputs['NativeAlpha']
        if preserve_source_texture:
            opacity = group.nodes.new('ShaderNodeMath'); opacity.name = 'ZZZ_SourceOverlayAlpha'; opacity.operation = 'MULTIPLY'
            group.links.new(effective_alpha, opacity.inputs[0]); group.links.new(inputs.outputs['SourceAlpha'], opacity.inputs[1])
            effective_alpha = opacity.outputs[0]
            for link in list(alpha_mul.inputs[1].links): group.links.remove(link)
            alpha_mul.inputs[1].default_value = 1.
        group.links.new(effective_alpha, alpha_mul.inputs[0])
        tree.links.new(native.outputs['ZZZ_Alpha'], wrapper.inputs['NativeAlpha'])
        if preserve_source_texture:
            tree.links.new(native.outputs['ZZZ_BaseColor'], wrapper.inputs['SourceColor'])
            tree.links.new(native.outputs['ZZZ_BaseAlpha'], wrapper.inputs['SourceAlpha'])
        separate = tree.nodes.new('ShaderNodeSeparateRGB'); created.append(separate); separate.name = 'ZZZ_MorphDiffuseSplit'
        tree.links.new(native.outputs['ZZZ_Diffuse'], separate.inputs[0])
        combine = tree.nodes.new('ShaderNodeCombineRGB'); created.append(combine); combine.name = 'ZZZ_MorphDiffuseRatio'
        for i, channel in enumerate(('R', 'G', 'B')):
            math = tree.nodes.new('ShaderNodeMath'); created.append(math); math.name = 'ZZZ_MorphRatio_' + channel
            if abs(baseline[i]) > 1e-6:
                math.operation = 'DIVIDE'; math.inputs[1].default_value = baseline[i]
            else:
                math.operation = 'ADD'; math.inputs[1].default_value = 1.
            tree.links.new(separate.outputs[channel], math.inputs[0]); tree.links.new(math.outputs[0], combine.inputs[i])
        tree.links.new(combine.outputs[0], wrapper.inputs['DiffuseRatio'])
        if is_shadow:
            if role == 'eye_shadow_texture' and not preserve_source_texture:
                # Use the resolved atlas ALPHA only, never pigment or luminance.
                if not alpha_mul.inputs[1].is_linked:
                    raise RuntimeError('贴图目影缺少已解析的 atlas Alpha，不能替换为常量透明度')
                coverage = group.nodes.new('ShaderNodeMath'); coverage.name = 'ZZZ_EyeShadowCoverage'; coverage.operation = 'MULTIPLY'
                group.links.new(effective_alpha, coverage.inputs[0])
                group.links.new(alpha_mul.inputs[1].links[0].from_socket, coverage.inputs[1])
                effective_alpha = coverage.outputs[0]
            tint_color = group.nodes.new('ShaderNodeMixRGB'); tint_color.name = 'ZZZ_EyeShadowMorphTint'
            tint_color.blend_type = 'MULTIPLY'; tint_color.inputs[0].default_value = 1.
            group.links.new(inputs.outputs[EYE_SHADOW_TINT_SOCKET], tint_color.inputs[1])
            group.links.new(inputs.outputs['DiffuseRatio'], tint_color.inputs[2])
            tint = group.nodes.new('ShaderNodeMixRGB'); tint.name = 'ZZZ_EyeShadowLiveTransmittance'
            tint.blend_type = 'MIX'; tint.inputs[1].default_value = (1., 1., 1., 1.)
            group.links.new(effective_alpha, tint.inputs[0]); group.links.new(tint_color.outputs[0], tint.inputs[2])
            transparent = group.nodes.new('ShaderNodeBsdfTransparent'); transparent.name = 'ZZZ_EyeShadowTransparent'
            group.links.new(tint.outputs[0], transparent.inputs['Color'])
            group.links.new(transparent.outputs[0], output.inputs['Shader'])
            # Drop Forward/unused decoder/AOV nodes, not just their Surface link.
            # Native Alpha=0 becomes white ray transmittance, equal to hiding only
            # this retained overlay. There is no generated outline on eye shadows.
            reachable = {output}
            while True:
                expanded = reachable | {link.from_node for link in group.links if link.to_node in reachable}
                if expanded == reachable: break
                reachable = expanded
            for node in list(group.nodes):
                if node not in reachable: group.nodes.remove(node)
        else:
            _, outline_shader = _copy_graph(outline, owner, destination=group, prefix='ZZZ_Outline_')
            hull = group.nodes.get('ZZZ_Outline_OutlineShader')   # darken the line on dark materials (see toon_outline.DARK_K)
            if hull is not None and 'Base Color' in hull.inputs:
                group.links.new(base_tint.outputs[0], hull.inputs['Base Color'])
            # FlipFaces produces an inverted hull. Cull only the hull's backfaces;
            # original surface alpha/culling remains the explicit native/game policy.
            geometry = group.nodes.new('ShaderNodeNewGeometry'); geometry.name = 'ZZZ_ShellGeometry'
            front = group.nodes.new('ShaderNodeMath'); front.name = 'ZZZ_ShellFront'; front.operation = 'SUBTRACT'; front.inputs[0].default_value = 1.
            group.links.new(geometry.outputs['Backfacing'], front.inputs[1])
            alpha = group.nodes.new('ShaderNodeMath'); alpha.name = 'ZZZ_ShellAlpha'; alpha.operation = 'MULTIPLY'
            group.links.new(effective_alpha, alpha.inputs[0]); group.links.new(front.outputs[0], alpha.inputs[1])
            transparent = group.nodes.new('ShaderNodeBsdfTransparent'); transparent.name = 'ZZZ_ShellTransparent'
            shell = group.nodes.new('ShaderNodeMixShader'); shell.name = 'ZZZ_LiveAlphaOutline'
            group.links.new(alpha.outputs[0], shell.inputs[0]); group.links.new(transparent.outputs[0], shell.inputs[1]); group.links.new(outline_shader, shell.inputs[2])
            final = group.nodes.new('ShaderNodeMixShader'); final.name = 'ZZZ_OriginalOrShell'
            group.links.new(shell_factor, final.inputs[0]); group.links.new(surface_shader, final.inputs[1]); group.links.new(shell.outputs[0], final.inputs[2])
            group.links.new(final.outputs[0], output.inputs['Shader'])
            # The surface is ZZZ_Toon_Core itself; it exposes the Avatar/Normal/Rim AOV data.
            made = []
            for aov_name, socket, kind in (('Avatar', 'Avatar', 'Value'), ('Normal', 'AOV Normal', 'Color'), ('Rim', 'AOV Rim', 'Color')):
                node = group.nodes.new('ShaderNodeOutputAOV'); node.name = aov_name; node.aov_name = aov_name; node.label = aov_name + ' AOV'
                group.links.new(core.outputs[socket], node.inputs[kind]); made.append(node)
            _mask_aovs(group, surface_factor, only=made)   # shells never write scene AOVs
        # Commit the source output LAST. All original native nodes/Material IDs
        # remain; current/future native Morph relinks reach the exposed INPUTs.
        for link in list(out.inputs['Surface'].links): tree.links.remove(link)
        tree.links.new(wrapper.outputs['Shader'], out.inputs['Surface'])
        raster = culling_policy(source, surface, role=role, preserve_source_texture=preserve_source_texture, override=cull)
        source.blend_method = 'HASHED'; source.use_backface_culling = raster['enabled']
        source['zzz_render_policy'] = RENDER_POLICY
        source['zzz_owner'] = owner; source['zzz_owned'] = True; source['zzz_game_bridge'] = True
        source['zzz_generic'] = False; source['preview_role'] = role
        source['zzz_native_tree_ref'] = owned_native; source['zzz_native_baseline_diffuse'] = list(baseline)
        return {'original_material_id_preserved': True, 'native_morph_inputs_live': True,
                'outline_same_material_live_alpha': True, 'shell_aovs_suppressed': True,
                'baseline_diffuse': list(baseline), 'state': 'HASHED', 'render_policy': RENDER_POLICY,
                'culling': raster, 'eye_shadow_transmittance': is_shadow,
                'eye_shadow_tint_input': EYE_SHADOW_TINT_SOCKET if is_shadow else None,
                'limits': ['Diffuse Color and Alpha Morphs bridged; full ambient/specular/sphere equivalence is not certified.',
                           'Culling is an audited PMX/Goo preview policy, not exact Unity pass translation.']}
    except Exception:
        for link in list(out.inputs['Surface'].links): tree.links.remove(link)
        for a, b in previous: tree.links.new(a, b)
        for node in reversed(created): tree.nodes.remove(node)
        native.node_tree = old_group; source.blend_method = old_blend; source.use_backface_culling = old_cull
        for key in ('zzz_owner', 'zzz_owned', 'zzz_game_bridge', 'zzz_generic', 'zzz_render_policy', 'zzz_native_tree_ref', 'zzz_native_baseline_diffuse'):
            if key in source: del source[key]
        if owned_native is not None and owned_native.users == 0: bpy.data.node_groups.remove(owned_native)
        if group is not None and group.users == 0: bpy.data.node_groups.remove(group)
        raise
