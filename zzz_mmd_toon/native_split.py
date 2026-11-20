"""Verified native MMD material separation. No rebind, pruning or color changes.

Temporary integer provenance survives Blender's native Separate operator. Compare
original indices, not rounded geometry or decoded/runtime normal caches. Freeze a
NEW strict authored-data baseline only after every comparison and Morph migration.
"""
import hashlib
import struct
from collections import Counter
import bpy
from . import validation

def _value(value):
    if hasattr(value,'to_list'):return value.to_list()
    if isinstance(value,(str,int,float,bool)) or value is None:return value
    try:return tuple(_value(x) for x in value)
    except TypeError:return str(value)


def _id(value, own):
    if value is None:return None
    for name,item in own.items():
        if item is not None and value==item:return ('SELF',name)
    return (value.bl_rna.identifier,value.name_full)


def _animation(data, own):
    ad=getattr(data,'animation_data',None)
    if ad is None:return None
    def action(a):
        if a is None:return None
        return (a.name_full,[(c.data_path,c.array_index,[(tuple(k.co),tuple(k.handle_left),tuple(k.handle_right),k.interpolation) for k in c.keyframe_points]) for c in a.fcurves])
    drivers=[]
    for c in ad.drivers:
        drivers.append((c.data_path,c.array_index,c.mute,c.driver.type,c.driver.expression,
            [(v.name,v.type,[(_id(t.id,own),t.data_path,t.bone_target,t.transform_type,t.transform_space) for t in v.targets]) for v in c.driver.variables]))
    nla=[(t.name,t.mute,[(s.name,action(s.action),s.frame_start,s.frame_end,s.action_frame_start,s.action_frame_end,s.blend_type,s.extrapolation,s.influence,s.mute) for s in t.strips]) for t in ad.nla_tracks]
    return (action(ad.action),drivers,nla,ad.action_blend_type,ad.action_extrapolation,ad.action_influence)


def _remap_self(data, old, new):
    ad=getattr(data,'animation_data',None)
    if ad:
        for curve in ad.drivers:
            for variable in curve.driver.variables:
                for target in variable.targets:
                    for name,item in old.items():
                        if item is not None and target.id==item:
                            target.id=new[name];break


def _object_state(ob, own):
    mods=[]
    for modifier in ob.modifiers:
        fields=[]
        for p in modifier.bl_rna.properties:
            if p.identifier in {'rna_type','name','type','is_active','execution_time','persistent_uid'} or p.is_readonly or p.type=='COLLECTION':continue
            try:
                v=getattr(modifier,p.identifier)
                fields.append((p.identifier,_id(v,own) if p.type=='POINTER' else _value(v)))
            except (AttributeError,TypeError):continue
        mods.append((modifier.name,modifier.type,fields))
    return {'parent':_id(ob.parent,own),'parent_type':ob.parent_type,'parent_bone':ob.parent_bone,
            'matrix_basis':[list(r) for r in ob.matrix_basis],'matrix_parent_inverse':[list(r) for r in ob.matrix_parent_inverse],
            'modifiers':mods,'constraints':[(c.name,c.type,c.mute,c.influence,_id(getattr(c,'target',None),own),getattr(c,'subtarget','')) for c in ob.constraints],
            'object_animation':_animation(ob,own),'mesh_animation':_animation(ob.data,own),'key_animation':_animation(ob.data.shape_keys,own) if ob.data.shape_keys else None}


def _shape_meta(me):
    keys=me.shape_keys
    return None if keys is None else (keys.use_relative,keys.eval_time,keys.reference_key.name if keys.reference_key else None,
        [(k.name,k.relative_key.name if k.relative_key else None,k.value,k.slider_min,k.slider_max,k.mute,k.vertex_group,k.interpolation,k.frame,k.lock_shape) for k in keys.key_blocks])


def _vertex_hash(ob,v):
    h=hashlib.sha256();h.update(struct.pack('<3f',*v.co))
    weights=sorted((ob.vertex_groups[g.group].name,float(g.weight)) for g in v.groups)
    h.update(validation.digest(weights).encode('ascii'))
    if ob.data.shape_keys:
        for key in ob.data.shape_keys.key_blocks:h.update(struct.pack('<3f',*key.data[v.index].co))
    return h.digest()


def _attribute_values(attribute):
    # Match the v3 guard's actual typed RNA storage, not repr or decoded colors.
    storage=validation._ATTRIBUTE_STORAGE.get(attribute.data_type)
    if storage is None:raise RuntimeError('不支持验证此作者属性: '+attribute.name+' / '+attribute.data_type)
    field,fmt=storage;result=[]
    for item in attribute.data:
        value=getattr(item,field)
        if attribute.data_type=='STRING':
            result.append(value.encode('utf-8') if isinstance(value,str) else bytes(value))
        elif attribute.data_type=='BYTE_COLOR':result.append(struct.pack(fmt,*(round(float(v)*255) for v in value)))
        elif attribute.data_type=='FLOAT4X4':result.append(struct.pack(fmt,*(v for row in value for v in row)))
        elif isinstance(value,(bool,int,float)):result.append(struct.pack(fmt,value))
        else:result.append(struct.pack(fmt,*value))
    return result


def _attributes(me, prefix):
    # Exclude only our four precise provenance names. Arbitrary ZZZSplit_* author
    # layers must not become an unguarded namespace escape hatch.
    provenance={prefix+'_'+domain for domain in ('POINT','EDGE','CORNER','FACE')}
    result={}
    for a in validation._stable_attributes(me):
        if a.name in provenance:continue
        if a.domain not in {'POINT','CORNER','EDGE','FACE'}:raise RuntimeError('不支持的作者属性域: '+a.name)
        result[a.name]=(a.domain,a.data_type,_attribute_values(a))
    return result


def _uv_meta(me):
    meta=validation.uv_structure(me)
    # Local loop counts legitimately shrink; values have original-corner proof.
    meta['layers']=[row[:-1] for row in meta['layers']]
    return meta


def _capture(ob,index,prefix):
    me=ob.data;own={'object':ob,'mesh':me,'keys':me.shape_keys}
    record={'name':ob.name,'own':own,'state':_object_state(ob,own),'shapes':_shape_meta(me),
            'vertices':[_vertex_hash(ob,v) for v in me.vertices],
            'edges':[tuple(e.vertices) for e in me.edges],
            'corners':[(l.vertex_index,l.edge_index) for l in me.loops],
            'faces':[(tuple(p.vertices),tuple(p.loop_indices),me.materials[p.material_index],p.use_smooth) for p in me.polygons],
            'attributes':_attributes(me,prefix),'uv_names':[u.name for u in me.uv_layers],
            'uv_meta':_uv_meta(me),
            'groups':[(g.name,bool(g.lock_weight)) for g in ob.vertex_groups],
            'uv_active':me.uv_layers.active_index,'uv_render':[u.name for u in me.uv_layers if u.active_render],
            'uv_clone':[u.name for u in me.uv_layers if u.active_clone],
            'uv':{u.name:[tuple(d.uv) for d in u.data] for u in me.uv_layers},
            'counts':{'POINT':len(me.vertices),'EDGE':len(me.edges),'CORNER':len(me.loops),'FACE':len(me.polygons)},
            'active_key':ob.active_shape_key_index}
    ob[prefix]=index
    for domain,count in record['counts'].items():
        a=me.attributes.new(prefix+'_'+domain,'INT',domain);a.data.foreach_set('value',list(range(count)))
    return record


def _require(ok,message):
    if not ok:raise RuntimeError('原生材质分离等价检查失败: '+message+'；请打开00完整回退点')


def separate(context,rig,root,arm,meshes,materials,owner):
    """Actual sidebar-native operator; return parts + verifiable preparation report."""
    prefix='ZZZSplit_'+owner[:12]
    _require(not any(getattr(m,'data_type',None)=='DATA' for m in root.mmd_root.uv_morphs),'旧式UV Morph DATA索引未迁移；请先在独立文件完成原生转换并验证')
    positive_ids=[int(m.mmd_material.material_id) for m in bpy.data.materials if hasattr(m,'mmd_material') and m.mmd_material.material_id>=0]
    _require(len(positive_ids)==len(set(positive_ids)),'文件内存在重复原生Material ID，保存handler会重编号')
    for ob in meshes:
        _require(len(ob.data.polygons)>0,'原网格为空: '+ob.name)
        _require(not any(a.name.startswith(prefix) for a in ob.data.attributes),'provenance名称冲突')
        _require(not any(m and '_temp' in m.name for m in ob.data.materials),'请先退出原生材质Morph临时预览')
        _require(not any(u.name.startswith('__uv.') for u in ob.data.uv_layers),'请先退出原生UV Morph编辑预览')
        ad=ob.data.animation_data
        _require(not (ad and ad.drivers and ad.action is None and not ad.nla_tracks),'Mesh-only drivers会被原生UV预览清理删除，需独立迁移验证')
        for other in bpy.data.objects:
            if other in meshes:continue
            _require(not any(getattr(x,'target',None)==ob for x in other.constraints),'外部约束以原网格为目标，无法隐式改为全部分部')
            _require(not any(getattr(x,'object',None)==ob or getattr(x,'target',None)==ob for x in other.modifiers),'外部修改器以原网格为目标，无法隐式扩展')
    bone_before=validation.skeleton(arm)
    targets=[]
    for morph in root.mmd_root.material_morphs:
        for offset in morph.data:
            targets.append((morph.name,offset,offset.material_data,int(offset.material_id),offset.related_mesh_data))
    records={i:_capture(ob,i,prefix) for i,ob in enumerate(meshes)}
    for ob in list(meshes):
        for selected in context.selected_objects:selected.select_set(False)
        ob.hide_set(False);ob.select_set(True);context.view_layer.objects.active=ob
        _require(bpy.ops.mmd_tools.separate_by_materials(clean_shape_keys=False)=={'FINISHED'},'原生operator未完成')
    new=list(rig.meshes());seen={i:{d:Counter() for d in r['counts']} for i,r in records.items()}
    slot_by_material={m.as_pointer():i for i,m in enumerate(materials)};parts={};part_records=[];restored_attributes=[]
    for ob in new:
        _require(prefix in ob,'原网格来源标记丢失: '+ob.name)
        origin=int(ob[prefix]);r=records[origin];me=ob.data
        ids={}
        for domain in r['counts']:
            a=me.attributes.get(prefix+'_'+domain)
            _require(a is not None and a.domain==domain and a.data_type=='INT','原索引属性丢失 '+domain)
            ids[domain]=[d.value for d in a.data]
            _require(all(0<=v<r['counts'][domain] for v in ids[domain]),'原索引越界 '+domain)
            seen[origin][domain].update(ids[domain])
        _require(_shape_meta(me)==r['shapes'],'形态键名称/值/相对关系变化 '+ob.name)
        _require([(g.name,bool(g.lock_weight)) for g in ob.vertex_groups]==r['groups'],'作者顶点组结构/锁变化 '+ob.name)
        for v in me.vertices:_require(_vertex_hash(ob,v)==r['vertices'][ids['POINT'][v.index]],'坐标/权重/形态键变化 '+ob.name)
        for e in me.edges:_require(tuple(ids['POINT'][i] for i in e.vertices)==r['edges'][ids['EDGE'][e.index]],'边拓扑变化')
        for l in me.loops:_require((ids['POINT'][l.vertex_index],ids['EDGE'][l.edge_index])==r['corners'][ids['CORNER'][l.index]],'角拓扑变化')
        for p in me.polygons:
            vs,ls,mat,smooth=r['faces'][ids['FACE'][p.index]]
            _require(tuple(ids['POINT'][i] for i in p.vertices)==vs and tuple(ids['CORNER'][i] for i in p.loop_indices)==ls,'面绕序/原角引用变化')
            _require(me.materials[p.material_index]==mat and p.use_smooth==smooth,'原Material身份或smooth变化')
        # Separate may elide an all-false sharp/UV-pin storage layer in a part.
        # Restore only these precise BOOLEAN layers and only a proven all-false
        # subset of the captured author store. Never infer/recompute normals or
        # accept loss of a nonzero authored value / an arbitrary custom layer.
        attrs=_attributes(me,prefix)
        restorable={'sharp_edge':'EDGE','sharp_face':'FACE'}
        restorable.update({'.pn.'+uv.name:'CORNER' for uv in me.uv_layers})
        for name in sorted(set(r['attributes'])-set(attrs)):
            domain,typ,values=r['attributes'][name]
            subset=[struct.unpack('<?',values[i])[0] for i in ids[domain]] if typ=='BOOLEAN' else None
            _require(restorable.get(name)==domain and typ=='BOOLEAN' and not any(subset),'作者属性丢失 '+name)
            attr=me.attributes.new(name,typ,domain)
            for i,item in enumerate(attr.data):item.value=subset[i]
            restored_attributes.append({'object':ob.name,'attribute':name,'domain':domain,'source_layer_existed':True,
                'source_values_exact':True,'all_false_subset':True,'subset_count':len(subset),
                'subset_typed_sha256':hashlib.sha256(b''.join(values[i] for i in ids[domain])).hexdigest()})
        attrs=_attributes(me,prefix)
        _require(set(attrs)==set(r['attributes']),'作者属性集合变化 '+ob.name+' added='+repr(sorted(set(attrs)-set(r['attributes'])))+' missing='+repr(sorted(set(r['attributes'])-set(attrs))))
        for name,(domain,typ,values) in attrs.items():
            old_domain,old_typ,old_values=r['attributes'][name]
            _require((domain,typ)==(old_domain,old_typ),'作者属性类型变化 '+name)
            _require(all(v==old_values[ids[domain][i]] for i,v in enumerate(values)),'作者属性字节值变化 '+name)
        _require([u.name for u in me.uv_layers]==r['uv_names'],'UV层结构变化')
        for u in me.uv_layers:_require(all(tuple(d.uv)==r['uv'][u.name][ids['CORNER'][i]] for i,d in enumerate(u.data)),'UV坐标变化 '+u.name)
        # The sidebar operator resets the active UV selection; restore author UI.
        me.uv_layers.active_index=r['uv_active']
        for u in me.uv_layers:
            u.active_render=u.name in r['uv_render']
            u.active_clone=u.name in r['uv_clone']
        _require(_uv_meta(me)==r['uv_meta'],'UV渲染/clone/颜色默认层结构变化 '+ob.name)
        ob.active_shape_key_index=r['active_key']
        own={'object':ob,'mesh':me,'keys':me.shape_keys}
        for item in own.values():
            if item is not None:_remap_self(item,r['own'],own)
        _require(_object_state(ob,own)==r['state'],'父级/变换/修改器/动画或driver引用变化 '+ob.name)
        used={p.material_index for p in me.polygons}
        _require(len(used)==1,'分离后仍是混合材质 '+ob.name)
        mat=me.materials[next(iter(used))];source_slot=slot_by_material.get(mat.as_pointer())
        _require(source_slot is not None,'未知Material ID')
        part_slot=len(parts);ob['zzz_slot']=part_slot;ob['zzz_source_slot']=source_slot;ob['zzz_source_name']=getattr(mat.mmd_material,'name_j','') or mat.name;ob['zzz_owner']=owner
        ob.name='ZZZ_%02d_%s'%(source_slot,ob['zzz_source_name']);me.name=ob.name+'_Mesh'
        parts[part_slot]=ob;part_records.append({'part':part_slot,'source_mesh':origin,'source_material':source_slot,'object':ob.name,'faces':len(me.polygons),'vertices':len(me.vertices)})
    for origin,r in records.items():
        for domain,count in r['counts'].items():
            _require(set(seen[origin][domain])==set(range(count)),'原数据覆盖丢失 '+str(origin)+' '+domain)
            if domain in {'FACE','CORNER'}:_require(all(n==1 for n in seen[origin][domain].values()),'原面/角被复制')
    _require(validation.skeleton(arm)==bone_before,'原骨rest/父级变化')
    migrations=[]
    for name,offset,material,numeric,related in targets:
        offset.material_data=material;offset.material_id=numeric
        if material is None and numeric<0:
            # Native all-material semantics have no mesh-specific target.
            offset.related_mesh_data=None
            migrations.append({'morph':name,'all_materials':True});continue
        _require(material is not None,'legacy材质Morph必须在保存前的只读检查中拒绝 '+name)
        candidates=[ob for ob in parts.values() if material in ob.data.materials.values()]
        _require(bool(candidates),'材质Morph目标分部不存在 '+name)
        # Modern material_data remains authoritative even if several disconnected
        # parts share one Material. related_mesh_data is the native legacy lookup.
        offset.related_mesh_data=candidates[0].data
        original_target=next(t[2] for t in targets if t[1]==offset)
        _require(offset.material_data==original_target and offset.material_id==numeric,'材质Morph身份/ID变化')
        migrations.append({'morph':name,'material':material.name,'mesh':candidates[0].data.name,'parts':len(candidates)})
    # Clear only native SDEF runtime caches (not keys, weights, drivers or bindings).
    import importlib
    from .mmd_adapter import native
    module,_=native();FnSDEF=importlib.import_module(module.__name__+'.core.sdef').FnSDEF
    FnSDEF.clear_cache()
    for ob in parts.values():
        for domain in records[int(ob[prefix])]['counts']:ob.data.attributes.remove(ob.data.attributes[prefix+'_'+domain])
        del ob[prefix]
    report={'operator':'mmd_tools.separate_by_materials','clean_shape_keys':False,'semantic_equivalence':True,
            'comparison':'exact original POINT/EDGE/CORNER/FACE provenance, serialized attributes, all UV/weights/shapes; no decoded normal cache',
            'before_meshes':len(records),'after_meshes':len(parts),'original_faces':sum(r['counts']['FACE'] for r in records.values()),
            'each_original_face_and_corner_once':True,'original_material_ids_preserved':True,'parts':part_records,'material_morph_migrations':migrations,'restored_authored_attribute_storage':restored_attributes,
            'skeleton':bone_before,'mesh':validation.mesh_state(parts)}
    return parts,report
