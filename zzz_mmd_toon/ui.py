"""Sidebar deliberately follows imported model -> material folder -> render."""
import json
from pathlib import Path
import bpy
from bpy.props import StringProperty, BoolProperty, IntProperty, FloatProperty, EnumProperty, CollectionProperty, PointerProperty
from . import workflow, transaction, mmd_adapter, game_bridge, lighting

ROLE_ITEMS = [(x, label, '') for x, label in (
    ('UNASSIGNED', '默认身体'), ('face', '脸 / 游戏SDF'), ('body', '身体 / 衣物'), ('hair', '头发'), ('wing', '翅膀'),
    ('eye', '眼白 / 虹膜'), ('eyebrow', '眉睫 / 线条'), ('eye_shadow', '无贴图眼影'),
    ('eye_shadow_texture', '贴图眼影'), ('eye_highlight', '眼高光'), ('mouth', '口腔 / 牙齿'))]
STATE_ITEMS = [(x, x, '') for x in ('AUTO', 'OPAQUE', 'BLEND', 'CLIP', 'HASHED')]


def clear_scan(self, context):
    self.rows.clear()
    self.scan_directory = ''
    self.profile_label = ''
    self.status = '材质目录已改变，请扫描，或直接点击一键配置并渲染。'


class ZZZ_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__
    def draw(self, context):
        self.layout.label(text='渲染场景、着色器、描边与合成器均由插件代码生成，无需另选 .blend。')
        self.layout.label(text='不含角色模型、骨骼、角色贴图或游戏资源 JSON。')
        self.layout.label(text='仍需 Goo Engine 4.4 + 已启用 MMD Tools；普通 Blender 不承诺等效降级。')


_POPULATING = [False]


def _save_cull(self, context):
    if _POPULATING[0]:
        return
    settings = context.scene.zzz_toon
    try:
        from . import user_mapping
        names = {r.slot: r.source_name for r in settings.rows}
        user_mapping.save(settings.scan_directory or settings.resource_dir, mapping(settings), names)
    except Exception as exc:
        settings.status = '背面剔除已改，但无法写入映射文件（本次仍然有效）：%s' % exc


class ZZZ_MappingRow(bpy.types.PropertyGroup):
    slot: IntProperty()
    source_name: StringProperty()
    stem: StringProperty(name='JSON stem', description='精确 JSON 文件名（不含扩展名），不可用共享主贴图代替语义')
    role: EnumProperty(name='域', items=ROLE_ITEMS)
    state: EnumProperty(name='状态', items=STATE_ITEMS, default='AUTO')
    alpha: FloatProperty(name='Alpha', min=0., max=1., default=1.)
    outline: FloatProperty(name='描边宽度', min=0., max=5., default=0.)
    palette_json: StringProperty(default='null')
    archive: BoolProperty(default=False)
    backend: EnumProperty(name='着色来源', items=[('GAME_JSON','游戏JSON与贴图','按原材质槽独立关联JSON、域和状态'),
        ('MMD_ORIGINAL','保留MMD原材质','该槽没有足够证据或由用户决定保留，不套用游戏着色')], default='GAME_JSON')
    user_selected: BoolProperty(default=False)
    cull: EnumProperty(name='背面剔除', items=[('AUTO','自动（按游戏数据）','按游戏材质的 _Cull/_DoubleSided 决定'),
        ('ON','强制开启','隐藏背面；头发、披风等双面薄片会出现缺失'),('OFF','强制关闭','双面显示；会露出法线朝内的内层')], default='AUTO', update=_save_cull)
    keep_original: BoolProperty(name='保留MMD原材质', default=False,
        description='该槽不套用游戏JSON，保持PMX原材质；不会参与描边')
    evidence_json: StringProperty(default='{}')


def _is_sun(self, ob):
    return ob.type == 'LIGHT' and ob.data.type == 'SUN'


def _set_main_light(self, context):
    gn = lighting.group_for(context.scene)
    if gn is not None:
        lighting.set_main_light(gn, self.main_light)


class ZZZ_Settings(bpy.types.PropertyGroup):
    main_light: PointerProperty(name='主光', type=bpy.types.Object, poll=_is_sun, update=_set_main_light,
                                description='选一盏已有的日光灯作主光：方向、颜色、强度驱动着色；留空为内置 Sun')
    resource_dir: StringProperty(name='必需：对应角色JSON与贴图目录', subtype='DIR_PATH', update=clear_scan,
        description='选择对应角色含Materials/Textures的资源目录；同一算法跨角色关联，不使用角色白名单；未解析项明确报告')
    output_dir: StringProperty(name='输出文件夹', subtype='DIR_PATH')
    rows: CollectionProperty(type=ZZZ_MappingRow)
    row_index: IntProperty(default=0)
    choice: EnumProperty(name='候选JSON', items=lambda self, context: _choice_items(self, context))
    scan_directory: StringProperty()
    profile_label: StringProperty()
    status: StringProperty(default='先用 MMD Tools 自行导入 PMX，并选中 MMD 根节点。')
    checkpoint_path: StringProperty(name='文件回退点', subtype='FILE_PATH')
    outline_scale: FloatProperty(name='描边倍率', min=.05, max=5., default=1.)
    samples: IntProperty(name='采样', min=1, max=1024, default=64)
    resolution: IntProperty(name='高度像素', min=128, max=4096, default=960)
    show_options: BoolProperty(name='高级设置 / 物理 / 回退', default=False)
    unmapped_ack: BoolProperty(default=False)  # first click warns about unmapped slots, second click renders anyway


def populate(settings, plan):
    _POPULATING[0] = True
    try:
        _populate_rows(settings, plan)
    finally:
        _POPULATING[0] = False


def _populate_rows(settings, plan):
    settings.rows.clear()
    settings.unmapped_ack = False
    for data in plan['rows']:
        row = settings.rows.add()
        row.slot, row.source_name = data['slot'], data['name']
        row.stem, row.role = data.get('stem') or '', data.get('role') or 'body'
        row.state, row.alpha, row.outline = data.get('state','AUTO'), data.get('alpha',1.), data.get('outline',.34)
        row.palette_json, row.archive = json.dumps(data.get('palette')), data.get('effect_policy')=='MME_DUPLICATE_OFF'
        row.keep_original = bool(data.get('keep_original'))
        row.cull = data.get('cull') if data.get('cull') in ('AUTO','ON','OFF') else 'AUTO'
        row.user_selected = bool(data.get('user_selected'))
        row.backend = 'MMD_ORIGINAL' if row.keep_original else 'GAME_JSON'
        row.evidence_json = json.dumps({k:data.get(k) for k in ('confidence','evidence','warnings','texture_overrides','preserve_source_texture','resolution','unresolved','color_override','effect_policy','effect_evidence','choices','user_selected','reversed_normals')},ensure_ascii=False)
    settings.scan_directory = plan.get('resource_dir','')
    kept = sum(bool(r.get('keep_original')) for r in plan['rows'])
    settings.profile_label = '通用关联 · 无角色白名单 · %d / %d 个材质槽已关联，%d 个保留MMD原材质' % (sum(bool(r.get('stem')) for r in plan['rows']),len(plan['rows']),kept)
    settings.status = '扫描完成：游戏JSON、材质域和状态按原槽保留。'
    slot_errors = set(plan.get('slot_errors', []))
    fatal = [e for e in plan.get('errors', []) if e not in slot_errors]
    if fatal:
        settings.status = '资源未就绪（不会报告渲染成功）：\n'+'\n'.join(fatal[:6])
    elif kept:
        settings.status = '%d 个材质槽没有足够证据，将保留MMD原材质；可在“查看自动关联”中为它们手动选JSON。' % kept
    if plan.get('warnings'):
        settings.status += '\n' + '\n'.join(str(x) for x in plan['warnings'][:5])


def mapping(settings):
    return [{'slot': r.slot, 'name': r.source_name, 'role': 'body' if r.role == 'UNASSIGNED' else r.role,
             'backend':r.backend, 'alpha': r.alpha, 'state': r.state, 'outline': r.outline, 'cull': r.cull,
             'palette': json.loads(r.palette_json), 'archive':False, **json.loads(r.evidence_json or '{}'),
             'stem': r.stem, 'keep_original': bool(r.keep_original), 'user_selected': bool(r.user_selected)} for r in settings.rows]


_CHOICE_ITEMS = [('', '无', '')]  # Blender keeps raw pointers to dynamic enum strings: the list must outlive the callback.


def _choice_items(self, context):
    global _CHOICE_ITEMS
    settings = context.scene.zzz_toon
    if not 0 <= settings.row_index < len(settings.rows):
        _CHOICE_ITEMS = [('', '无', '')]
    else:
        choices = json.loads(settings.rows[settings.row_index].evidence_json or '{}').get('choices') or []
        _CHOICE_ITEMS = [(c['stem'], c['stem'] + ('' if c.get('same_role') else '（域不同）'), '') for c in choices[:80]] \
            or [('', '无可选JSON', '')]
    return _CHOICE_ITEMS


class ZZZ_OT_scan(bpy.types.Operator):
    bl_idname = 'zzz_toon.scan'
    bl_label = '扫描材质 / 自动映射'
    bl_description = '只读扫描所选 MMD 与资源，保留所有 JSON 状态，不按主贴图合并'

    def execute(self, context):
        settings = context.scene.zzz_toon
        try:
            populate(settings, workflow.scan(context, settings.resource_dir))
            self.report({'INFO'}, settings.status.splitlines()[0])
            return {'FINISHED'}
        except Exception as exc:
            settings.status = str(exc)
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class ZZZ_OT_run(bpy.types.Operator):
    bl_idname = 'zzz_toon.run'
    bl_label = '一键配置并渲染'
    bl_description = '自动扫描、文件备份、准备材质、灯光、描边、双层合成并渲染；不导入PMX、不重建物理'
    render: BoolProperty(default=True)

    def execute(self, context):
        settings = context.scene.zzz_toon
        try:
            _, _, root, _, _ = mmd_adapter.selected(context)
            options = {k: getattr(settings, k) for k in ('resource_dir', 'output_dir', 'outline_scale', 'samples', 'resolution')}
            if not settings.rows and 'zzz_run' not in root:
                populate(settings, workflow.scan(context, settings.resource_dir))
            todo = [r for r in settings.rows if pending(r)] if 'zzz_run' not in root else []
            if todo and not settings.unmapped_ack:
                settings.unmapped_ack = True
                settings.status = ('有 %d 个材质槽没有映射（列表顶部红色）：\n' % len(todo)
                                   + '请为它们选JSON，或再点一次“一键配置并渲染”，忽略它们（保留MMD原材质）直接渲染。')
                self.report({'WARNING'}, '有 %d 个材质槽未映射；再点一次将忽略它们并渲染' % len(todo))
                return {'CANCELLED'}
            settings.unmapped_ack = False
            # Existing rows are checked, not silently discarded. Changing a row
            # after configure requires file rollback, never a hidden rebuild.
            rows = mapping(settings) if settings.rows else None
            result = workflow.run(context, mapping=rows, render=self.render, **options)
            new = context.scene.zzz_toon
            # workflow inherits paths/mapping BEFORE saving the renderer scene.
            new.status = '完成：' + result['status'] + '\n输出：' + result['output']
            new.checkpoint_path = root.get('zzz_checkpoint', '')
            self.report({'INFO'}, '仿ZZZ渲染完成；原工程回退点和验证报告已保留')
            return {'FINISHED'}
        except Exception as exc:
            context.scene.zzz_toon.status = str(exc)
            if 'root' in locals():
                context.scene.zzz_toon.checkpoint_path = root.get('zzz_checkpoint', '')
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        finally:
            workflow._progress_end(context)


class ZZZ_OT_choice(bpy.types.Operator):
    bl_idname = 'zzz_toon.apply_choice'
    bl_label = '使用所选JSON'
    bl_description = '仅限该槽自己提供的候选JSON；选择是用户决定，会如实标记'
    keep: BoolProperty(default=False)

    def execute(self, context):
        settings = context.scene.zzz_toon
        if not 0 <= settings.row_index < len(settings.rows):
            return {'CANCELLED'}
        row = settings.rows[settings.row_index]
        if self.keep:
            row.stem, row.keep_original, row.backend = '', True, 'MMD_ORIGINAL'
        elif settings.choice:
            row.stem, row.keep_original, row.backend = settings.choice, False, 'GAME_JSON'
        else:
            return {'CANCELLED'}
        row.user_selected = True
        settings.unmapped_ack = False
        try:
            from . import user_mapping
            names = {r.slot: r.source_name for r in settings.rows}
            path = user_mapping.save(settings.scan_directory or settings.resource_dir, mapping(settings), names)
            settings.status = '已选择并记住（下次扫描自动沿用）：' + path
        except Exception as exc:
            settings.status = '已选择，但无法写入映射文件（本次仍然有效）：%s' % exc
        return {'FINISHED'}


class ZZZ_OT_physics(bpy.types.Operator):
    bl_idname = 'zzz_toon.build_physics'
    bl_label = '构建已导入的原生 MMD 物理（慢）'
    bl_description = '独立慢操作：只构建PMX已导入的刚体关节，不凭空补物理，不烘焙缓存'

    def execute(self, context):
        try:
            result = workflow.build_physics(context)
            context.scene.zzz_toon.status = '原生物理：' + result['status'] + '；须从缓存起始帧连续播放，未烘焙。'
            self.report({'INFO'}, context.scene.zzz_toon.status)
            return {'FINISHED'}
        except Exception as exc:
            context.scene.zzz_toon.status = str(exc)
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class ZZZ_OT_restore(bpy.types.Operator):
    bl_idname = 'zzz_toon.restore'
    bl_label = '打开完整文件回退点'
    bl_description = '重新打开备份 .blend，会放弃当前未保存改动；不是对象级假回滚'

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        try:
            path = context.scene.zzz_toon.checkpoint_path or context.scene.get('zzz_checkpoint', '')
            transaction.restore(path)
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


def pending(row):
    """A slot nobody mapped (neither automatically nor by the user)."""
    return bool(row.keep_original and not row.user_selected)


class ZZZ_UL_mapping(bpy.types.UIList):
    def filter_items(self, context, data, propname):
        items = getattr(data, propname)
        order = sorted(range(len(items)), key=lambda i: (not pending(items[i]), items[i].slot))
        neworder = [0] * len(items)
        for position, index in enumerate(order):
            neworder[index] = position
        return [self.bitflag_filter_item] * len(items), neworder

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        if pending(item):
            row.alert = True
            row.label(text='%02d  %s' % (item.slot, item.source_name), icon='ERROR')
            flagged = bool(json.loads(item.evidence_json or '{}').get('reversed_normals'))
            row.label(text='未映射 · 法线朝内，已自动修正，建议映射' if flagged else '未映射 · 保留MMD原材质')
        else:
            row.label(text='%02d  %s' % (item.slot, item.source_name))
            row.label(text=item.stem if item.stem else '已选保留MMD原材质')


class ZZZ_PT_panel(bpy.types.Panel):
    bl_label = '仿ZZZ渲染'
    bl_idname = 'ZZZ_PT_render'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = '仿ZZZ渲染'

    def draw(self, context):
        layout, settings = self.layout, context.scene.zzz_toon
        layout.prop(settings, 'resource_dir', text='资源目录')
        layout.prop(settings, 'output_dir', text='输出目录')
        buttons = layout.row(align=True)
        buttons.operator('zzz_toon.scan', text='扫描', icon='VIEWZOOM')
        big = buttons.row(align=True)
        big.scale_y = 1.4
        big.operator('zzz_toon.run', icon='RENDER_STILL')
        if settings.rows:
            todo = sum(pending(r) for r in settings.rows)
            head = layout.row()
            if todo:
                head.alert = True
                head.label(text='%d 个材质槽未映射（红色，已置顶）' % todo, icon='ERROR')
            else:
                head.label(text='全部 %d 个材质槽已处理' % len(settings.rows), icon='CHECKMARK')
            layout.template_list('ZZZ_UL_mapping', '', settings, 'rows', settings, 'row_index', rows=6)
            if 0 <= settings.row_index < len(settings.rows):
                row = settings.rows[settings.row_index]
                box = layout.box()
                box.label(text='%02d · %s' % (row.slot, row.source_name))
                box.prop(settings, 'choice', text='JSON')
                line = box.row(align=True)
                line.operator('zzz_toon.apply_choice', text='使用所选JSON').keep = False
                line.operator('zzz_toon.apply_choice', text='保留MMD原材质').keep = True
                box.prop(row, 'outline', text='描边')
                if not row.keep_original: box.prop(row, 'cull', text='背面剔除')
                evidence = json.loads(row.evidence_json or '{}')
                for message in (evidence.get('warnings') or [])[:2]:
                    box.label(text=str(message)[:100], icon='INFO')
                if row.role in game_bridge.EYE_SHADOW_ROLES:
                    try:
                        _, _, _, _, meshes = mmd_adapter.selected(context)
                        part = next((ob for ob in meshes if int(ob.get('zzz_slot', -1)) == row.slot), None)
                        material = next((mat for mat in part.data.materials if mat and mat.get('zzz_source_slot') == row.slot), None) if part else None
                        socket = game_bridge.eye_shadow_tint_input(material) if material else None
                        if socket is not None:
                            box.prop(socket, 'default_value', text='目影透射颜色')
                    except (RuntimeError, ReferenceError, ValueError):
                        pass
        if settings.status:
            box = layout.box()
            box.alert = settings.status.startswith(('有 ', '资源未就绪'))
            for line in settings.status.splitlines()[:5]:
                box.label(text=line[:110])
        if lighting.group_for(context.scene):
            layout.prop(settings, 'main_light', text='主光（日光灯）', icon='LIGHT_SUN')
        layout.prop(settings, 'show_options', icon='TRIA_DOWN' if settings.show_options else 'TRIA_RIGHT', emboss=False)
        if settings.show_options:
            layout.prop(settings, 'samples')
            layout.prop(settings, 'resolution')
            layout.prop(settings, 'outline_scale')
            layout.operator('zzz_toon.run', text='仅配置 / 不渲染', icon='MATERIAL').render = False
            layout.operator('zzz_toon.build_physics', icon='PHYSICS')
            layout.prop(settings, 'checkpoint_path')
            layout.operator('zzz_toon.restore', icon='LOOP_BACK')
        layout.label(text='Goo 4.4 · 背面剔除按PMX/JSON推断，异常请自行检查', icon='INFO')

CLASSES = (ZZZ_Preferences, ZZZ_MappingRow, ZZZ_Settings, ZZZ_OT_scan, ZZZ_OT_run, ZZZ_OT_choice, ZZZ_OT_physics, ZZZ_OT_restore, ZZZ_UL_mapping, ZZZ_PT_panel)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.zzz_toon = PointerProperty(type=ZZZ_Settings)


def unregister():
    if hasattr(bpy.types.Scene, 'zzz_toon'):
        del bpy.types.Scene.zzz_toon
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
