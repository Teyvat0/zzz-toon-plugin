"""Required-resource, character-independent ZZZ workflow; original MMD IDs stay intact."""
import copy
import json
import math
from pathlib import Path
import bpy
from . import mmd_adapter, renderer, transaction, validation, resources, materials, auto_mapping, game_bridge, outline_geometry, dependencies, user_mapping, normal_audit

VERSION = '0.3.0'
ROLE_SET = {'face','body','hair','wing','eye','eyebrow','eye_shadow','eye_shadow_texture','eye_highlight','mouth'}


def _progress(context, percent, text):
    """Show stage progress in the status bar. Cosmetic only: never raises."""
    print('ZZZ_PROGRESS %d%% %s' % (percent, text), flush=True)
    try:
        wm = context.window_manager
        wm.progress_begin(0, 100)
        wm.progress_update(int(percent))
        if context.workspace:
            context.workspace.status_text_set('仿ZZZ渲染 %d%%：%s' % (percent, text))
        if context.window:
            bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
    except Exception:
        pass


def _progress_end(context):
    try:
        context.window_manager.progress_end()
        if context.workspace:
            context.workspace.status_text_set(None)
    except Exception:
        pass


def _resource_path(value):
    value = str(value or '').strip()
    if not value:
        return ''
    path = str(Path(bpy.path.abspath(value)).expanduser().resolve())
    try:
        return resources.normalize_root(path)
    except (ValueError, OSError):
        return path


def scan(context, resource_dir=''):
    _, _, root, arm, meshes = mmd_adapter.selected(context)
    source = mmd_adapter.original_materials(meshes)
    plan = auto_mapping.plan(source, meshes, arm, _resource_path(resource_dir))
    plan.update(root=root.name, arm=arm.name)
    plan.setdefault('warnings', [])
    plan.setdefault('errors', [])
    plan.setdefault('slot_errors', [])
    plan.setdefault('rows', [])
    if plan['rows']:
        user_mapping.apply_saved(plan)
    plan['warnings'].extend(normal_audit.audit(meshes, source, plan['rows']))
    if len(root.mmd_root.material_morphs):
        plan['warnings'].append('保留原材质ID和原生Morph链；Diffuse/Alpha接入游戏着色，其他参数等效性不作保证。')
    return plan


def _mapping(plan, mapping):
    # Recompute and retain resolver evidence; UI controls cannot silently drop
    # inferred texture bindings, source-overlay preservation or dependency hashes.
    rows = copy.deepcopy(plan['rows'])
    if mapping is not None:
        if len(mapping) != len(rows) or {r['slot'] for r in mapping} != set(range(len(rows))):
            raise RuntimeError('原始材质槽发生变化，请重新扫描')
        for override in mapping:
            row = rows[int(override['slot'])]
            # JSON identity/domain/alpha are automatic results tied to resolver
            # evidence. Never accept edits while retaining stale texture bindings.
            # A different JSON is accepted only as an explicit user choice from the
            # slot's own offered choices; keep-original is an explicit decision too.
            if override.get('keep_original') and not row.get('keep_original'):
                user_mapping.keep(row)
            elif 'stem' in override and override['stem'] != row.get('stem') and not override.get('keep_original'):
                user_mapping.choose(row, override['stem'])
                if 'role' in override and override['role'] in ROLE_SET: row['role'] = override['role']
            elif not override.get('keep_original') and row.get('keep_original') and override.get('stem'):
                user_mapping.choose(row, override['stem'])
            for key in ('name','stem','state'):
                if key in override and override[key] != row.get(key) and not (key == 'stem' and (override.get('keep_original') or not override[key])):
                    raise RuntimeError('自动关联结果已被修改，请重新扫描；当前仅支持调整描边参数: '+str(key))
            if 'role' in override and override['role'] != row.get('role') and not row.get('user_selected'):
                raise RuntimeError('自动关联结果已被修改，请重新扫描；当前仅支持调整描边参数: role')
            if 'alpha' in override and abs(float(override['alpha'])-float(row.get('alpha',1.))) > 1e-6:
                raise RuntimeError('原PMX Alpha由原生材质Morph控制，不能在映射表覆盖')
            for key in ('outline','palette','cull','transparency'):
                if key in override: row[key] = override[key]
    if len(rows) != len(plan['material_names']) or {r['slot'] for r in rows} != set(range(len(rows))):
        raise RuntimeError('原始材质槽发生变化，请重新扫描')
    for row in rows:
        slot = row['slot']
        if row['name'] != plan['material_names'][slot]:
            raise RuntimeError('原始材质顺序改变，请重新扫描')
        row['role'] = row.get('role') if row.get('role') in ROLE_SET else 'body'
        row['backend'] = 'GAME_JSON'
        if not row.get('stem'):
            # Explicitly reported, never guessed: the native MMD material stays.
            row.update(backend='MMD_ORIGINAL', keep_original=True, texture_overrides={}, preserve_source_texture=False)
        # Only the evidence-based, recomputed MME policy may default a duplicate
        # effect OFF. UI mappings cannot disable arbitrary original surfaces.
        row['archive'] = row.get('effect_policy') == 'MME_DUPLICATE_OFF'
        row.setdefault('stem', '')
        row.setdefault('state', 'AUTO')
        row.setdefault('palette', None)
        row.setdefault('alpha', plan['rows'][slot].get('alpha', 1.))
        row.setdefault('outline', .34)
        if row.get('cull') not in ('AUTO','ON','OFF'): row['cull'] = 'AUTO'
        if row.get('transparency') not in ('AUTO','ON','OFF'): row['transparency'] = 'AUTO'
        row.setdefault('transparent_auto', plan['rows'][slot].get('transparent_auto', False))
        if row['state'] not in {'AUTO','OPAQUE','BLEND','CLIP','HASHED'}:
            row['state'] = 'AUTO'
        if not math.isfinite(float(row['alpha'])) or not 0 <= float(row['alpha']) <= 1:
            raise RuntimeError('材质 Alpha 超出0..1')
        if not math.isfinite(float(row['outline'])) or not 0 <= float(row['outline']) <= 5:
            raise RuntimeError('描边宽度超出0..5')
        palette = row.get('palette')
        if palette is not None and (len(palette) != 3 or not all(math.isfinite(float(x)) and 0 <= float(x) <= 1 for x in palette)):
            row['palette'] = None
    return sorted(rows, key=lambda r: r['slot'])


def _mapping_digest(rows):
    # Evidence/diagnostics are not user controls. Float properties roundtrip as f32.
    return validation.digest([{k: ([round(float(x),6) for x in r[k]] if k == 'palette' and r.get(k) else
                                    round(float(r.get(k,1. if k == 'alpha' else 0.)),6) if k in {'alpha','outline'} else r.get(k))
                               for k in ('slot','name','stem','role','backend','state','alpha','outline','palette','cull','transparency')}
                              for r in sorted(rows,key=lambda x:x['slot'])])


def _dependencies(data):
    try:
        return ({k:bpy.data.node_groups[v] for k,v in data['groups'].items()},
                {k:bpy.data.objects[v] for k,v in data['keep'].items()},
                {k:bpy.data.collections[v] for k,v in data['collections'].items()})
    except (KeyError,ReferenceError) as exc:
        raise RuntimeError('已配置的必需渲染依赖丢失，请文件回退: '+str(exc)) from exc


def _set_checkpoint(context, root, path):
    root['zzz_checkpoint'] = str(path)
    context.scene['zzz_checkpoint'] = str(path)
    if hasattr(context.scene,'zzz_toon'):
        context.scene.zzz_toon.checkpoint_path = str(path)


def _phase(scene, root, value):
    root['zzz_phase'] = scene['zzz_phase'] = value


def _save_new(path):
    path = Path(path).resolve()
    if path.exists():
        raise RuntimeError('拒绝覆盖已有工程: '+str(path))
    before = transaction.material_save_state()
    result = bpy.ops.wm.save_as_mainfile(filepath=str(path),check_existing=False,compress=True)
    transaction.verify_material_save_state(before, path)
    if result != {'FINISHED'} or not path.is_file() or path.stat().st_size < 1024:
        raise RuntimeError('保存工程未完成，不能报告成功')
    return validation.artifact(path)


def _existing(context, root, resource_dir, outline_scale):
    data = json.loads(root['zzz_run'])
    if (data.get('version') != VERSION or data.get('mesh_guard_schema') != validation.MESH_GUARD_SCHEMA
            or data.get('render_policy') != game_bridge.RENDER_POLICY):
        raise RuntimeError('这是旧版配置或旧守卫格式；请在原文件回退点/原PMX上使用新版，不能转换或重设旧基线')
    if root.get('zzz_phase') not in {'configured_saved','render_failed','rendered'}:
        raise RuntimeError('此前配置未完成，请打开文件回退点')
    if root.get('zzz_physics_phase') in {'failed','building'}:
        raise RuntimeError('物理此前构建未完成，请打开最新02回退点')
    scene = bpy.data.scenes.get(data['scene'])
    if scene != context.scene:
        raise RuntimeError('请切换到已配置的通用渲染场景')
    if _resource_path(resource_dir) != data['resource_dir']:
        raise RuntimeError('资源目录已改变，请文件回退再配置')
    if abs(float(outline_scale)-data['outline_scale']) > 1e-6:
        raise RuntimeError('描边参数改变，请文件回退重新配置，不重复叠加')
    for path, expected in data['resource_hashes'].items():
        if not Path(path).is_file() or validation.file_hash(path) != expected:
            raise RuntimeError('本次实际使用的增强资源已改变，请文件回退: '+path)
    owned_meshes = [o for o in scene.objects if o.get('zzz_owner') == data['owner'] and o.type == 'MESH']
    if any('zzz_slot' not in o for o in owned_meshes):
        raise RuntimeError('已配置原网格的槽标记丢失，请文件回退')
    slots = [int(o['zzz_slot']) for o in owned_meshes]
    if len(slots) != len(set(slots)):
        raise RuntimeError('已配置原网格存在重复槽标记或复制对象，请文件回退')
    parts = dict(zip(slots, owned_meshes))
    _, rig, _, arm, _ = mmd_adapter.selected(context)
    context.view_layer.update()
    if validation.skeleton(arm) != data['skeleton'] or validation.mesh_state(parts) != data['mesh'] or validation.shader_state(parts) != data['shader']:
        raise RuntimeError('原骨 rest/网格/渲染挂接被外部修改，拒绝静默重建；请文件回退')
    if validation.digest(validation.material_targets(root)) != data['material_targets']:
        raise RuntimeError('原生材质Morph目标引用或材质ID被修改，请文件回退')
    dependencies.verify_retained_images(data.get('retained_images',[]))
    groups,keep,cols = _dependencies(data)
    validation.scene_gate(scene,parts,groups,keep,cols,root,arm,data['compositor'])
    if root.mmd_root.is_built:
        mmd_adapter.validate_physics(context,rig,root,arm)
    return data,parts,rig,arm


def _preflight_meshes(context, root, arm, meshes):
    # Non-character-gated constraints only. No scale/head-name/bone-count/JSON/pose
    # admission rule: generic shading keeps original rest, weights, animation, IDs.
    if not arm or not len(arm.data.bones):
        raise RuntimeError('MMD骨架数据丢失，无法保留原生动作入口')
    for ob in meshes:
        if ob.library or ob.data.library:
            raise RuntimeError('模型为只读链接库，请先创建本地可编辑副本: '+ob.name)
        others = [o for o in bpy.data.objects if o.type == 'MESH' and o.data == ob.data and o not in meshes]
        if others:
            raise RuntimeError('mesh数据与其它模型共用，请先单用户化，避免修改其它模型: '+ob.name)
        if not len(ob.data.polygons):
            continue
        if any(m.type == 'NODES' and m.node_group and m.node_group.get('zzz_owner') for m in ob.modifiers):
            raise RuntimeError('模型已有其它运行的仿ZZZ挂接，请使用原文件回退点')
    source = mmd_adapter.original_materials(meshes)
    if not source:
        raise RuntimeError('导入模型没有任何材质，请先用MMD Tools正常导入PMX')
    # In-place wrapping changes only the selected model's materials. Reject actual
    # outside-object sharing rather than confusing native Morph ID references.
    for ob in bpy.data.objects:
        if ob.type == 'MESH' and ob not in meshes and any(m in source for m in ob.data.materials):
            raise RuntimeError('材质与其它模型共用，请先单用户化: '+ob.name)


def _apply(parts, source_materials, rows, groups, directory, owner, outline_scale, root):
    from .application import apply
    return apply(parts, source_materials, rows, groups, directory, owner, outline_scale, root)


def _render(scene, output, samples, resolution):
    scene.eevee.taa_render_samples=int(samples)
    scene.render.resolution_x,scene.render.resolution_y=int(resolution*4/3),int(resolution)
    output=Path(output);target=output/'仿ZZZ渲染_正面.png';index=2
    while target.exists():target=output/('仿ZZZ渲染_正面_%03d.png'%index);index+=1
    scene.render.filepath=str(target)
    result=bpy.ops.render.render(write_still=True,scene=scene.name)
    if result!={'FINISHED'} or not target.is_file() or not target.stat().st_size:raise RuntimeError('渲染未完成')
    return str(target)


def _render_checked(scene, root, output, samples, resolution):
    try:
        image=_render(scene,output,samples,resolution);_phase(scene,root,'rendered');return image
    except Exception as exc:
        _phase(scene,root,'render_failed')
        transaction.write_json(Path(output)/'渲染失败_配置已保存可重试.json',{'error':str(exc),'checkpoint':root.get('zzz_checkpoint','')})
        raise RuntimeError('配置已保存，渲染失败可再次点击: '+str(exc)) from exc


def _inherit_ui(scene, root, rows, directory, output, outline_scale, samples, resolution):
    if not hasattr(scene,'zzz_toon'):return
    from . import ui
    settings=scene.zzz_toon
    settings.resource_dir,settings.output_dir=directory,str(output)
    settings.outline_scale,settings.samples,settings.resolution=outline_scale,samples,resolution
    ui.populate(settings,{'rows':rows,'resource_dir':directory,'profile':None,'warnings':[], 'errors':[], 'catalog':[]})
    settings.checkpoint_path=root.get('zzz_checkpoint','')
    settings.status='通用配置完成：使用所选游戏JSON/贴图；原骨架、网格、材质ID与Morph入口保留。'


def run(context, resource_dir='', output_dir='', render=True, mapping=None, outline_scale=1., samples=64, resolution=960):
    if not .05<=float(outline_scale)<=5 or not 1<=int(samples)<=1024 or not 128<=int(resolution)<=4096:
        raise RuntimeError('描边/采样/分辨率超出安全范围')
    renderer.preflight()
    # Native save_pre compatibility handlers can change IDs even for copy=True.
    # Reject their ambiguous/legacy inputs before creating any rollback file.
    transaction.material_save_state()
    _,rig,root,arm,meshes=mmd_adapter.selected(context)
    if 'zzz_run' in root:
        data,parts,rig,arm=_existing(context,root,resource_dir,outline_scale)
        if mapping is not None and _mapping_digest(mapping)!=_mapping_digest(data['mapping']):
            raise RuntimeError('配置已改变，请文件回退后重新配置')
        image=_render_checked(context.scene,root,data['output'],samples,resolution) if render else None
        return {'status':'already_configured_noop','owner':data['owner'],'output':data['output'],'image':image,'checkpoint':{'path':root.get('zzz_checkpoint','')}}
    if root.get('zzz_phase'):raise RuntimeError('此前配置未完成，请使用完整文件回退点')
    _progress(context,3,'扫描材质与资源')
    plan=scan(context,resource_dir)
    # Only resource-level problems block. Slots without proof keep their native MMD
    # material (reported), they never stop the character from being configured.
    fatal=[e for e in plan.get('errors',[]) if e not in set(plan.get('slot_errors',[]))]
    if fatal:
        raise RuntimeError('资源关联尚未完成：\n'+'\n'.join(fatal))
    rows=_mapping(plan,mapping)
    _preflight_meshes(context,root,arm,meshes)
    owner,output=transaction.new_run(output_dir)
    report={'version':VERSION,'render_policy':game_bridge.RENDER_POLICY,'owner':owner,'output':str(output),'profile':'universal-no-character-profile',
            'warnings':plan.get('warnings',[]),'plan':copy.deepcopy(rows),
            'limits':['Common game JSON/material-domain reconstruction, not exact game-shader reproduction','Native material separation verified by exact original-index provenance; original Material IDs retained',
                      'Missing required resources or unresolved material identities block configuration; inferred and optional unresolved bindings are reported','Native physics is separate, not baked or collision-free certified',
                      'Source/render scenes share model IDs; file checkpoint is authoritative']}
    _progress(context,20,'保存配置前回退文件')
    cp=transaction.checkpoint(output/'00_配置前完整回退.blend');report['checkpoint']=cp
    source_scene=context.scene;_set_checkpoint(context,root,cp['path']);saved=False
    try:
        # Native MMD material separation clears globally unused Mesh IDs. Do not
        # build a renderer depsgraph before that native cleanup has completed.
        print('ZZZ_STAGE native_separation_before_template', flush=True)
        source_materials=mmd_adapter.original_materials(meshes)
        # Native MMD Tools lazily assigns negative material IDs on first Morph
        # use. Do it explicitly via its own API after the full-file checkpoint,
        # so later normal binding is not mistaken for external corruption.
        module, _ = mmd_adapter.native()
        FnMaterial = __import__('importlib').import_module(module.__name__+'.core.material').FnMaterial
        id_initializations = []
        for material in source_materials:
            previous_id = int(material.mmd_material.material_id)
            assigned_id = FnMaterial(material).material_id
            if assigned_id != previous_id:
                id_initializations.append({'material':material.name,'before':previous_id,'after':assigned_id})
        report['native_material_id_initializations'] = id_initializations
        # Mirror only IDs initialized by the native API into matching modern
        # targets. This is an explicit, reported ID initialization, not a legacy
        # pointer repair; save-pre preflight already rejected conflicting input.
        initialized={x['material']:x for x in id_initializations}
        for target_root in bpy.data.objects:
            if getattr(target_root,'mmd_type',None)!='ROOT':continue
            for morph in target_root.mmd_root.material_morphs:
                for offset in morph.data:
                    material=offset.material_data
                    if material and material.name in initialized:
                        record=initialized[material.name]
                        if int(offset.material_id)!=record['before']:
                            raise RuntimeError('原生ID初始化后的Morph数值目标冲突；请使用00回退点')
                        offset.material_id=record['after']
        transaction.material_save_state()
        material_targets = validation.digest(validation.material_targets(root))
        _phase(source_scene,root,'preparing')
        _progress(context,25,'按材质原生拆分网格')
        parts,prep=mmd_adapter.prepare_universal(context,rig,root,arm,meshes,owner)
        report['prepare']=prep
        material_targets = validation.digest(validation.material_targets(root))
        # Save a distinct post-separation / pre-shading rollback point, never
        # replace the authoritative complete pre-operation file.
        report['separated_checkpoint']=transaction.checkpoint(output/'01_原生分材质_着色前回退.blend')
        print('ZZZ_STAGE native_separation_verified_checkpoint_saved', flush=True)
        _progress(context,50,'创建渲染场景')
        scene,groups,keep,cols,controls=renderer.build(context,owner)
        print('ZZZ_STAGE renderer_appended_after_native_cleanup', flush=True)
        if context.window:
            context.window.scene=scene;context.window.view_layer=scene.view_layers['ViewLayer']
        report['physics']=renderer.attach_model(context,scene,rig,parts,rows,cols,controls,owner,source_scene)
        report['head']=renderer.head_frame(context,arm,keep,controls,owner)
        _progress(context,60,'构建游戏材质与描边')
        report['materials'],used_hashes=_apply(parts,source_materials,rows,groups,plan['resource_dir'],owner,outline_scale,root)
        if validation.skeleton(arm)!=prep['skeleton'] or validation.mesh_state(parts)!=prep['mesh']:
            raise RuntimeError('渲染挂接意外改变原骨架/网格/UV/权重/形态键，请文件回退')
        _progress(context,72,'自动取景')
        report['framing']=renderer.fit_camera(context,scene,keep['Camera'],parts,resolution)
        mmd_adapter.show_complete_rig(root,arm);mmd_adapter.select_root(context,root)
        # Retention is deliberately broader than current-render admission: hidden
        # MME parts and disconnected native sources stay portable when valid.
        report['retained_images']=dependencies.pack_retained_images(parts)
        if validation.digest(validation.material_targets(root)) != material_targets:
            raise RuntimeError('着色挂接意外改变原生材质Morph目标，请文件回退')
        _progress(context,80,'校验网格/材质/着色未被改动')
        report['gate']=validation.scene_gate(scene,parts,groups,keep,cols,root,arm)
        data={'version':VERSION,'mesh_guard_schema':validation.MESH_GUARD_SCHEMA,'render_policy':game_bridge.RENDER_POLICY,'owner':owner,'output':str(output),'scene':scene.name,'resource_dir':plan['resource_dir'],
              'resource_hashes':used_hashes,'retained_images':report['retained_images'],'outline_scale':float(outline_scale),'mapping':rows,
              'skeleton':prep['skeleton'],'mesh':prep['mesh'],'shader':validation.shader_state(parts),
               'material_targets':material_targets,
              'checkpoint':cp['path'],'compositor':validation.digest(validation.graph_state(scene.node_tree)),
              'groups':{k:v.name for k,v in groups.items()},'keep':{k:v.name for k,v in keep.items()},'collections':{k:v.name for k,v in cols.items()}}
        root['zzz_run']=json.dumps(data,ensure_ascii=False);scene['zzz_run']=root['zzz_run']
        _set_checkpoint(context,root,cp['path']);_inherit_ui(scene,root,rows,plan['resource_dir'],output.parent,outline_scale,samples,resolution)
        scene.eevee.taa_render_samples=int(samples);scene.render.filepath=str(output/'仿ZZZ渲染_正面.png')
        _phase(scene,root,'configured_saved');report['artifact']=_save_new(output/'仿ZZZ渲染_通用配置.blend');saved=True
        report['mapping']=rows;report['status']='pass_configured';transaction.write_json(output/'配置验证报告.json',report)
        if render:_progress(context,92,'渲染中')
        report['image']=_render_checked(scene,root,output,samples,resolution) if render else None
        report['status']='pass_configured_rendered' if render else 'pass_configured';transaction.write_json(output/'配置验证报告.json',report)
        return report
    except Exception as exc:
        if not saved:_phase(context.scene,root,'configuration_failed')
        report.update(status='render_failed_config_saved' if saved else 'failed_use_file_checkpoint',error=str(exc),traceback=__import__('traceback').format_exc(),rollback_path=cp['path'])
        transaction.write_json(output/'配置失败_请文件回退.json',report)
        raise RuntimeError(str(exc)+'\n完整回退文件: '+cp['path']) from exc


def build_physics(context, output_dir=None):
    _,rig,root,arm,_=mmd_adapter.selected(context)
    if 'zzz_run' not in root:raise RuntimeError('先完成通用渲染配置，再显式构建已导入的原生MMD物理')
    if root.get('zzz_physics_phase') in {'failed','building'}:raise RuntimeError('此前物理未完成，请打开最新02文件回退点')
    data=json.loads(root['zzz_run'])
    data,parts,rig,arm=_existing(context,root,data['resource_dir'],data['outline_scale'])
    if root.mmd_root.is_built:return {**mmd_adapter.validate_physics(context,rig,root,arm),'status':'already_built_noop'}
    if not list(rig.rigidBodies()) or not list(rig.joints()):raise RuntimeError('PMX未导入刚体关节；渲染仍可用，但不能凭空生成物理')
    output=Path(data['output']);target=output/'仿ZZZ渲染_含原生物理.blend'
    if target.exists():raise RuntimeError('物理输出已存在，拒绝覆盖')
    path=output/'02_原生物理构建前回退.blend';number=2
    while path.exists():path=output/('02_原生物理构建前回退_%03d.blend'%number);number+=1
    previous=root.get('zzz_checkpoint','');_set_checkpoint(context,root,str(path))
    try:cp=transaction.checkpoint(path,'before_native_physics')
    except Exception:_set_checkpoint(context,root,previous);raise
    report={'checkpoint':cp,'output':str(output)}
    try:
        root['zzz_physics_phase']='building';report.update(mmd_adapter.build_physics(context,rig,root,arm,parts))
        report['validation']=mmd_adapter.validate_physics(context,rig,root,arm);root['zzz_physics_phase']='built_saved'
        report['artifact']=_save_new(target);transaction.write_json(output/'原生物理构建报告.json',report);return report
    except Exception as exc:
        root['zzz_physics_phase']='failed';_set_checkpoint(context,root,cp['path'])
        report.update(status='failed_use_latest_checkpoint',error=str(exc),rollback_path=cp['path'])
        transaction.write_json(output/'原生物理构建失败_请打开最新02回退点.json',report)
        raise RuntimeError(str(exc)+'\n物理构建前完整回退: '+cp['path']) from exc
