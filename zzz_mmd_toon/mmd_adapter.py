"""Native MMD data access. Never imports PMX, rebinds or generates weights."""
import importlib
import sys
from collections import Counter
import bpy
from . import validation


def native():
    names = [n for n in sys.modules if n == 'mmd_tools' or n.endswith('.mmd_tools')]
    names += [n for n in bpy.context.preferences.addons.keys() if n == 'mmd_tools' or n.endswith('.mmd_tools')]
    for name in dict.fromkeys(names):
        mod = importlib.import_module(name)
        if hasattr(bpy.types.PoseBone, 'mmd_bone'):
            return mod, importlib.import_module(name + '.core.model').Model
    raise RuntimeError('请先安装并启用 MMD Tools，再自行导入 PMX（推荐保留日文骨名、DISPLAY、PHYSICS）')


def selected(context):
    module, Model = native()
    active = context.view_layer.objects.active
    root = Model.findRoot(active) if active else None
    if root is None:
        roots = {Model.findRoot(o) for o in context.selected_objects}
        roots.discard(None)
        if len(roots) == 1:
            root = roots.pop()
    if root is None:
        raise RuntimeError('请在对象模式选择已导入模型的 MMD 根物体、骨架或网格')
    if context.mode != 'OBJECT':
        raise RuntimeError('请先切换对象模式')
    rig = Model(root)
    arm = rig.armature()
    meshes = list(rig.meshes())
    if not meshes:
        raise RuntimeError('所选 MMD 根节点没有模型网格')
    return module, rig, root, arm, meshes


def original_materials(meshes):
    result = []
    seen = set()
    for ob in meshes:
        for mat in ob.data.materials:
            if mat is None:
                raise RuntimeError('存在空材质槽，拒绝猜测原始材质序号')
            if mat.as_pointer() not in seen:
                seen.add(mat.as_pointer())
                result.append(mat)
    # Enumeration follows original mesh slots. Native numeric IDs are lazy Morph
    # identifiers, NOT a stable ordering key (some imported IDs can be negative).
    # Prepared parts carry the immutable ORIGINAL source-material order.
    if result and all('zzz_source_slot' in mat for mat in result):
        result.sort(key=lambda mat:int(mat['zzz_source_slot']))
    return result


def material_name(mat):
    return getattr(getattr(mat, 'mmd_material', None), 'name_j', '') or mat.name


def head_bone(arm):
    """Language-independent aliases; no profile, character name or bone count."""
    for aliases in ({'頭'}, {'head', '頭部', '头', '头部', '頭骨'}):
        found = [b for b in arm.pose.bones if
                 (getattr(getattr(b, 'mmd_bone', None), 'name_j', '') or b.name).casefold() in aliases
                 or b.name.casefold() in aliases]
        if len(found) == 1:
            return found[0]
    return None


def show_complete_rig(root, arm):
    root.mmd_root.show_armature = True
    arm.hide_viewport = False
    arm.hide_set(False)
    arm.show_in_front = True
    arm.data.display_type = 'STICK'
    originals = [b for b in arm.data.bones if not arm.pose.bones[b.name].is_mmd_shadow_bone]
    union = arm.data.collections.get('ZZZ_全部原始MMD骨') or arm.data.collections.new('ZZZ_全部原始MMD骨')
    for b in originals:
        b.hide = False
        b.hide_select = False
        union.assign(b)
    for col in arm.data.collections:
        col.is_visible = col.name not in {'mmd_shadow', 'mmd_dummy'}
    for scr in bpy.data.screens:
        for area in scr.areas:
            for space in area.spaces:
                if space.type == 'VIEW_3D':
                    space.overlay.show_overlays = True
                    space.overlay.show_bones = True
    finger_names = ('親指', '人指', '中指', '薬指', '小指')
    fingers = [b for b in originals if any(k in arm.pose.bones[b.name].mmd_bone.name_j for k in finger_names)]
    return {'total_bones': len(arm.data.bones), 'original_bones': len(originals), 'fingers': len(fingers),
            'visible_fingers': sum(not b.hide and any(c.is_visible for c in b.collections) for b in fingers), 'display_frames': len(root.mmd_root.display_item_frames)}


def prepare_universal(context, rig, root, arm, meshes, owner):
    """Native material separation FIRST, exact provenance proof, then strict guard."""
    from .native_split import separate
    parts, report = separate(context, rig, root, arm, meshes, original_materials(meshes), owner)
    report['bone_ui'] = show_complete_rig(root, arm)
    return parts, report


def prepare(context, module, rig, root, arm, meshes, materials, owner):
    slot_by_pointer = {m.as_pointer(): i for i, m in enumerate(materials)}
    def slot(mat):
        if mat.as_pointer() not in slot_by_pointer:
            raise RuntimeError('拆分出现未知材质')
        return slot_by_pointer[mat.as_pointer()]
    before = validation.semantic_slots(meshes, slot)
    bone_before = validation.skeleton(arm)
    for mat in materials:
        mat['zzz_source_slot'] = slot(mat)
    util = importlib.import_module(module.__name__ + '.utils')
    for ob in list(meshes):
        used = {p.material_index for p in ob.data.polygons}
        if len(used) > 1:
            util.separateByMaterials(ob)
    meshes = list(rig.meshes())
    after = validation.semantic_slots(meshes, slot)
    if before != after or validation.skeleton(arm) != bone_before:
        raise RuntimeError('按材质拆分的三角/UV/角法线/权重/形态键或骨架等价检查失败，请使用文件回退')
    parts = {}
    for ob in meshes:
        used = {p.material_index for p in ob.data.polygons}
        if len(used) != 1:
            raise RuntimeError('不支持空网格或混合材质 part')
        index = slot(ob.data.materials[next(iter(used))])
        if index in parts:
            raise RuntimeError('同一原始材质对应多个独立网格；首版拒绝自动合并，请回退并使用单个原始 PMX 导入')
        ob['zzz_slot'] = index
        ob['zzz_source_name'] = material_name(materials[index])
        ob['zzz_owner'] = owner
        ob.name = 'ZZZ_%02d_%s' % (index, ob['zzz_source_name'])
        parts[index] = ob
    if set(parts) != set(range(len(materials))):
        raise RuntimeError('拆分后原始材质槽不完整')
    return parts, {'semantic_equivalence': True, 'per_slot': before, 'skeleton': bone_before,
                   'mesh': validation.mesh_state(parts), 'bone_ui': show_complete_rig(root, arm)}


def archive_duplicates(parts, rows):
    """Retired rounded-position archive entry; never trust it as a hide proof."""
    raise RuntimeError('旧版位置近似归档已停用；只允许当前 auto_mapping 的完整独立 MME_DUPLICATE_OFF 证明')


def select_root(context, root):
    for ob in context.view_layer.objects:
        if ob.select_get():
            ob.select_set(False)
    root.hide_set(False)
    root.select_set(True)
    context.view_layer.objects.active = root


def validate_physics(context, rig, root, arm):
    """Do not trust is_built alone: native build sets it before it can fail."""
    world = context.scene.rigidbody_world
    rigids, joints = list(rig.rigidBodies()), list(rig.joints())
    if not root.mmd_root.is_built or not world or not world.enabled or not rigids or not joints or not world.collection or not world.constraints:
        raise RuntimeError('物理构建标志、刚体世界或启用状态不完整；请使用最新文件回退点')
    if any(not o.rigid_body or o.name not in world.collection.all_objects for o in rigids) or any(not o.rigid_body_constraint or o.name not in world.constraints.all_objects for o in joints):
        raise RuntimeError('原生物理刚体/关节未完整接入 Bullet 世界')
    expected = {o.mmd_rigid.bone for o in rigids if str(o.mmd_rigid.type) != '0' and o.mmd_rigid.bone}
    missing = []
    for name in expected:
        bone = arm.pose.bones.get(name)
        track = bone.constraints.get('mmd_tools_rigid_track') if bone else None
        if not track or track.mute or not track.target or track.influence < .999:
            missing.append(name)
    if missing:
        raise RuntimeError('动态骨追踪未完成，拒绝把半构建当成功: ' + ', '.join(sorted(missing)[:8]))
    return {'status': 'validated_built', 'rigids': len(rigids), 'joints': len(joints),
            'bone_tracks': len(expected), 'baked': bool(world.point_cache.is_baked)}


def build_physics(context, rig, root, arm, parts):
    scene = context.scene
    rigids, joints = list(rig.rigidBodies()), list(rig.joints())
    if not rigids or not joints:
        raise RuntimeError('PMX 导入时没有刚体/关节。请回到导入前并勾选 Physics；插件不会凭空生成物理')
    if root.mmd_root.is_built:
        return {**validate_physics(context, rig, root, arm), 'status': 'already_built_noop'}
    world = scene.rigidbody_world
    if not world:
        raise RuntimeError('渲染场景的刚体世界不存在，请先完成配置')
    for ob in rigids:
        if ob.name not in world.collection.objects:
            world.collection.objects.link(ob)
    for ob in joints:
        if ob.name not in world.constraints.objects:
            world.constraints.objects.link(ob)
    bones, geometry, shaders = validation.skeleton(arm), validation.mesh_state(parts), validation.shader_state(parts)
    select_root(context, root)
    result = bpy.ops.mmd_tools.build_rig(non_collision_distance_scale=1.5, collision_margin=1e-6)
    if result != {'FINISHED'} or not root.mmd_root.is_built:
        raise RuntimeError('原生 MMD Tools 物理构建失败')
    # Native Model.build may set Armature.show_viewport=True, but must not alter
    # its render/target contract, geometry or authored renderer data.
    if bones != validation.skeleton(arm) or geometry != validation.mesh_state(parts) or shaders != validation.shader_state(parts):
        raise RuntimeError('物理构建意外改变原骨 rest/父级、网格数据或着色器，请文件回退')
    world.enabled = True
    if not all(o.name in world.collection.all_objects for o in rigids) or not all(o.name in world.constraints.all_objects for o in joints):
        raise RuntimeError('刚体或关节不在 Bullet 世界中')
    return {'status': 'built', 'rigids': len(rigids), 'joints': len(joints),
            'bone_tracks': sum('mmd_tools_rigid_track' in b.constraints for b in arm.pose.bones),
            'temporary_helpers': len(list(rig.temporaryObjects())), 'baked': world.point_cache.is_baked,
            'limits': 'native build only; no collision-free/arbitrary dance guarantee; play sequentially from cache start'}
