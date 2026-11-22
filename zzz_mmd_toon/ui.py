"""Sidebar deliberately follows imported model -> material folder -> render."""
import json
from pathlib import Path
import bpy
from bpy.props import StringProperty, BoolProperty, IntProperty, FloatProperty, EnumProperty, CollectionProperty, PointerProperty
from . import workflow, transaction, mmd_adapter, game_bridge, lighting, ui_text

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
    self.status_kind = 'info'


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
        settings.status, settings.status_kind = '背面剔除/透明材质已改，但无法写入映射文件（本次仍然有效）：%s' % exc, 'warn'


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
    cull: EnumProperty(name='背面剔除', items=[('AUTO','自动','按游戏材质的 _Cull/_DoubleSided 决定'),
        ('ON','开','强制开启：隐藏背面；头发、披风等双面薄片会出现缺失'),('OFF','关','强制关闭：双面显示；会露出法线朝内的内层')], default='AUTO', update=_save_cull)
    transparency: EnumProperty(name='透明材质', items=[('AUTO','自动','材质名含镜片/玻璃/薄纱，或PMX Alpha<1 时按透明处理'),
        ('ON','透明','强制透明/半透明：不透明度 = 材质Alpha × 贴图Alpha；该槽不生成描边'),('OFF','不透明','忽略贴图Alpha，按普通身体材质')],
        default='AUTO', update=_save_cull)
    transparent_auto: BoolProperty(default=False)
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
    output_dir: StringProperty(name='输出文件夹', subtype='DIR_PATH')   # not shown: empty = next to the .blend (temp if unsaved)
    rows: CollectionProperty(type=ZZZ_MappingRow)
    row_index: IntProperty(default=0)
    choice: EnumProperty(name='候选JSON', items=lambda self, context: _choice_items(self, context))
    scan_directory: StringProperty()
    profile_label: StringProperty()
    status: StringProperty(default='先用 MMD Tools 自行导入 PMX，并选中 MMD 根节点。')
    status_kind: StringProperty(default='info')   # info / warn / error / done: picks the status icon
    checkpoint_path: StringProperty(name='文件回退点', subtype='FILE_PATH')
    outline_scale: FloatProperty(name='描边倍率', min=.05, max=5., default=1.,
        description='所有材质槽描边宽度的总乘数，和每个槽自己的「描边宽度」相乘；1 为默认，首次配置前设置')
    samples: IntProperty(name='采样', min=1, max=1024, default=64)         # not shown: export settings are the user's own
    resolution: IntProperty(name='高度像素', min=128, max=4096, default=960)   # not shown: preview render height
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
        row.transparency = data.get('transparency') if data.get('transparency') in ('AUTO','ON','OFF') else 'AUTO'
        row.transparent_auto = bool(data.get('transparent_auto'))
        row.user_selected = bool(data.get('user_selected'))
        row.backend = 'MMD_ORIGINAL' if row.keep_original else 'GAME_JSON'
        row.evidence_json = json.dumps({k:data.get(k) for k in ('confidence','evidence','warnings','texture_overrides','preserve_source_texture','resolution','unresolved','color_override','effect_policy','effect_evidence','choices','user_selected','reversed_normals')},ensure_ascii=False)
    settings.scan_directory = plan.get('resource_dir','')
    kept = sum(bool(r.get('keep_original')) for r in plan['rows'])
    settings.profile_label = '通用关联 · 无角色白名单 · %d / %d 个材质槽已关联，%d 个保留MMD原材质' % (sum(bool(r.get('stem')) for r in plan['rows']),len(plan['rows']),kept)
    settings.status = '扫描完成：游戏JSON、材质域和状态按原槽保留。'
    settings.status_kind = 'done'
    slot_errors = set(plan.get('slot_errors', []))
    fatal = [e for e in plan.get('errors', []) if e not in slot_errors]
    if fatal:
        settings.status = '资源未就绪（不会报告渲染成功）：\n'+'\n'.join(fatal[:6])
        settings.status_kind = 'error'
    elif kept:
        settings.status = '%d 个材质槽没有足够证据，将保留MMD原材质；可在“材质映射”中为它们手动选JSON。' % kept
        settings.status_kind = 'warn'
    if plan.get('warnings'):
        settings.status += '\n' + '\n'.join(str(x) for x in plan['warnings'][:5])


def mapping(settings):
    return [{'slot': r.slot, 'name': r.source_name, 'role': 'body' if r.role == 'UNASSIGNED' else r.role,
             'backend':r.backend, 'alpha': r.alpha, 'state': r.state, 'outline': r.outline, 'cull': r.cull,
             'transparency': r.transparency, 'transparent_auto': r.transparent_auto,
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
            settings.status, settings.status_kind = str(exc), 'error'
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
                settings.unmapped_ack, settings.status_kind = True, 'warn'
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
            new.status_kind = 'done'
            new.checkpoint_path = root.get('zzz_checkpoint', '')
            self.report({'INFO'}, '仿ZZZ渲染完成；原工程回退点和验证报告已保留')
            return {'FINISHED'}
        except Exception as exc:
            context.scene.zzz_toon.status = str(exc)
            context.scene.zzz_toon.status_kind = 'error'
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
            settings.status, settings.status_kind = '已选择并记住（下次扫描自动沿用）：' + path, 'info'
        except Exception as exc:
            settings.status, settings.status_kind = '已选择，但无法写入映射文件（本次仍然有效）：%s' % exc, 'warn'
        return {'FINISHED'}


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
        split = layout.split(factor=.5, align=True)
        split.alert = pending(item)   # must be set BEFORE the children exist: they copy it at creation
        left, right = split.row(align=True), split.row(align=True)
        left.alert = right.alert = pending(item)
        left.label(text='%02d  %s' % (item.slot, item.source_name), icon=_row_icon(item))
        if pending(item):
            flagged = bool(json.loads(item.evidence_json or '{}').get('reversed_normals'))
            right.label(text='未映射 · 法线朝内' if flagged else '未映射')
        elif item.keep_original:
            right.label(text='保留MMD原材质')
        else:
            right.label(text=ui_text.short_stem(item.stem))
            if ui_text.is_transparent(item.transparency, item.transparent_auto):
                right.label(text='透明')


_STATUS_ICON = {'info': 'INFO', 'warn': 'ERROR', 'error': 'CANCEL', 'done': 'CHECKMARK'}


def _addon_version():
    import sys
    info = getattr(sys.modules.get(__package__), 'bl_info', None) or {}
    return '.'.join(str(x) for x in info.get('version', ()))


def _environment():
    """(Goo 4.4 ready, MMD Tools ready): drawn in the panel header area."""
    goo = tuple(bpy.app.version[:2]) == (4, 4) and 'Goo' in bpy.app.version_string
    return goo, hasattr(bpy.types.PoseBone, 'mmd_bone')


def _wrapped(layout, context, text, icon='NONE', limit=8):
    """Blender labels never wrap: split by region width so nothing is cut off."""
    width = context.region.width if context.region else 300
    scale = max(.5, context.preferences.system.ui_scale)
    col = layout.column(align=True)
    col.scale_y = .85
    for i, line in enumerate(ui_text.wrap(text, width - 56 * scale, scale, limit)):
        col.label(text=line, icon=icon if i == 0 else 'BLANK1')
    return col


def _row_icon(item):
    if pending(item):
        return 'ERROR'
    if ui_text.is_transparent(item.transparency, item.transparent_auto):
        return 'GHOST_ENABLED'
    return 'MATERIAL_DATA' if item.keep_original else 'CHECKMARK'


class ZZZ_PT_panel(bpy.types.Panel):
    bl_label = '仿ZZZ渲染'
    bl_idname = 'ZZZ_PT_render'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = '仿ZZZ渲染'

    def draw_header(self, context):
        goo, mmd = _environment()
        self.layout.label(text='v' + _addon_version())
        if not (goo and mmd):
            self.layout.alert = True
            self.layout.label(icon='ERROR')

    def draw(self, context):
        layout, settings = self.layout, context.scene.zzz_toon
        layout.use_property_split = False
        goo, mmd = _environment()
        if not (goo and mmd):
            box = layout.box()
            box.alert = True
            if not goo:
                _wrapped(box, context, '当前不是 Goo Engine 4.4，渲染会被拒绝。', 'ERROR')
            if not mmd:
                _wrapped(box, context, '没有检测到已启用的 MMD Tools。', 'ERROR')
        col = layout.column(align=True)
        col.label(text='1  角色资源文件夹')
        _wrapped(col, context, '选这个角色的游戏资源文件夹（里面要有 Materials 和 Textures，放着材质 JSON 与贴图）。', 'INFO', limit=4)
        col.prop(settings, 'resource_dir', text='', icon='FILE_FOLDER')
        layout.separator(factor=.4)
        row = layout.row(align=True)
        row.operator('zzz_toon.scan', text='2  扫描材质', icon='VIEWZOOM')
        big = layout.row(align=True)
        big.scale_y = 1.7
        big.operator('zzz_toon.run', text='3  一键配置并渲染', icon='RENDER_STILL')
        _draw_status(layout, context, settings)
        if lighting.group_for(context.scene):
            layout.prop(settings, 'main_light', text='主光', icon='LIGHT_SUN')


def _draw_status(layout, context, settings):
    if not settings.status:
        return
    kind = ui_text.classify_status(settings.status, settings.status_kind)
    box = layout.box()
    box.alert = kind in ('warn', 'error')
    _wrapped(box, context, settings.status, _STATUS_ICON[kind], limit=10)
    if kind == 'done' and settings.checkpoint_path:
        box.label(text='已生成回退点，可在「高级与回退」恢复', icon='LOOP_BACK')


class ZZZ_PT_mapping(bpy.types.Panel):
    bl_label = '材质映射'
    bl_idname = 'ZZZ_PT_mapping'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = '仿ZZZ渲染'
    bl_parent_id = 'ZZZ_PT_render'

    @classmethod
    def poll(cls, context):
        return bool(context.scene.zzz_toon.rows)

    def draw_header(self, context):
        settings = context.scene.zzz_toon
        todo = sum(pending(r) for r in settings.rows)
        self.layout.label(text='%d 待映射' % todo if todo else '%d 个槽' % len(settings.rows),
                          icon='ERROR' if todo else 'CHECKMARK')

    def draw(self, context):
        layout, settings = self.layout, context.scene.zzz_toon
        todo = sum(pending(r) for r in settings.rows)
        if todo:
            box = layout.box()
            box.alert = True
            _wrapped(box, context, '%d 个材质槽未映射（红色，已置顶）。选好 JSON，或直接渲染以保留 MMD 原材质。' % todo, 'ERROR')
        layout.template_list('ZZZ_UL_mapping', '', settings, 'rows', settings, 'row_index', rows=6)
        if not 0 <= settings.row_index < len(settings.rows):
            return
        row = settings.rows[settings.row_index]
        box = layout.box()
        box.label(text='%02d · %s' % (row.slot, row.source_name), icon='MATERIAL')
        box.prop(settings, 'choice', text='')
        line = box.row(align=True)
        line.operator('zzz_toon.apply_choice', text='使用此 JSON').keep = False
        line.operator('zzz_toon.apply_choice', text='保留原材质').keep = True
        box.separator(factor=.3)
        col = box.column(align=True)
        col.prop(row, 'outline', text='描边宽度')
        if not row.keep_original:
            col.label(text='背面剔除')
            col.row(align=True).prop(row, 'cull', expand=True)
            if row.role in ('body', 'wing'):
                col.label(text='透明材质')
                col.row(align=True).prop(row, 'transparency', expand=True)
        evidence = json.loads(row.evidence_json or '{}')
        for message in (evidence.get('warnings') or [])[:2]:
            _wrapped(box, context, str(message), 'INFO', limit=4)
        if row.role in game_bridge.EYE_SHADOW_ROLES:
            _draw_eye_shadow_tint(box, context, row)


def _draw_eye_shadow_tint(box, context, row):
    try:
        _, _, _, _, meshes = mmd_adapter.selected(context)
        part = next((ob for ob in meshes if int(ob.get('zzz_slot', -1)) == row.slot), None)
        material = next((mat for mat in part.data.materials if mat and mat.get('zzz_source_slot') == row.slot), None) if part else None
        socket = game_bridge.eye_shadow_tint_input(material) if material else None
        if socket is not None:
            box.prop(socket, 'default_value', text='目影透射颜色')
    except (RuntimeError, ReferenceError, ValueError):
        pass


class ZZZ_PT_advanced(bpy.types.Panel):
    bl_label = '高级与回退'
    bl_idname = 'ZZZ_PT_advanced'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = '仿ZZZ渲染'
    bl_parent_id = 'ZZZ_PT_render'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout, settings = self.layout, context.scene.zzz_toon
        layout.use_property_split = True
        layout.use_property_decorate = False
        col = layout.column(align=True)
        col.prop(settings, 'outline_scale')
        layout.use_property_split = False
        layout.operator('zzz_toon.run', text='仅配置，不渲染', icon='MATERIAL').render = False
        box = layout.box()
        box.label(text='回退', icon='LOOP_BACK')
        box.prop(settings, 'checkpoint_path', text='')
        box.operator('zzz_toon.restore', icon='FILE_REFRESH')
        _wrapped(layout, context, 'Goo 4.4 预览：背面剔除按 PMX/JSON 推断，异常请自行检查。不含角色模型、贴图或游戏 JSON。', 'INFO', limit=6)


CLASSES = (ZZZ_Preferences, ZZZ_MappingRow, ZZZ_Settings, ZZZ_OT_scan, ZZZ_OT_run, ZZZ_OT_choice, ZZZ_OT_restore, ZZZ_UL_mapping, ZZZ_PT_panel, ZZZ_PT_mapping, ZZZ_PT_advanced)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.zzz_toon = PointerProperty(type=ZZZ_Settings)


def unregister():
    if hasattr(bpy.types.Scene, 'zzz_toon'):
        del bpy.types.Scene.zzz_toon
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
