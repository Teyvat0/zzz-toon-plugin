"""TEST ONLY: real native separation of a tiny authored MMD fixture, no template/render.
Tests exact typed provenance and modern MaterialMorph migration in authoritative Goo.
No PMX or existing blend is opened/saved. Artifacts are diagnostic JSON only.
"""
import bpy, sys, json, traceback
import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1])); import testenv
from datetime import datetime
from pathlib import Path
from mathutils import Matrix
ROOT=Path(__file__).resolve().parents[2]
O=ROOT/'test_outputs'/'native_split_synthetic'/datetime.now().strftime('%Y%m%d_%H%M%S_%f')
O.mkdir(parents=True,exist_ok=False)
R={'status':'running','reader':bpy.app.version_string,'checks':[]}
def check(name,value,detail=None):
    R['checks'].append({'name':name,'pass':bool(value),'detail':detail})
    if not value:raise AssertionError((name,detail))
try:
    check('authoritative_goo',bpy.app.version[:3]==(4,4,3) and 'Goo' in bpy.app.version_string)
    sys.path.insert(0,str(ROOT));import zzz_mmd_toon
    sys.path.insert(0,str(testenv.mmd_parent()))
    import mmd_tools;mmd_tools.register()
    from mmd_tools.core.model import Model
    from zzz_mmd_toon import native_split,validation
    for ob in list(bpy.data.objects):bpy.data.objects.remove(ob,do_unlink=True)
    rig=Model.create('Synthetic_Author',add_root_bone=True);root=rig.rootObject();arm=rig.armature()
    me=bpy.data.meshes.new('Synthetic_Source');me.from_pydata([(0,0,0),(1,0,0),(0,1,0),(1,1,.2)],[],[(0,1,2),(1,3,2)])
    ob=bpy.data.objects.new('Synthetic_Source',me);bpy.context.scene.collection.objects.link(ob);rig.attachMeshes([ob])
    mats=[bpy.data.materials.new(n) for n in ('Authored_A','Authored_B')]
    for i,m in enumerate(mats):
        m.mmd_material.material_id=100+i;me.materials.append(m)
    me.polygons[1].material_index=1
    for name in ('全ての親','GN_Outline','OutlineMask','unused_authored'):
        group=ob.vertex_groups.new(name=name)
        if name!='unused_authored':group.add([0,1,2,3],.5 if name=='GN_Outline' else 0.,'REPLACE')
        group.lock_weight=name=='unused_authored'
    basis=ob.shape_key_add(name='Basis');key=ob.shape_key_add(name='AuthorKey');key.data[1].co.z+=.125
    key.value=.2;key.vertex_group='GN_Outline';key.interpolation='KEY_LINEAR';key.lock_shape=True
    for n in ('UV_primary','UV_clone'):
        uv=me.uv_layers.new(name=n)
        for i,d in enumerate(uv.data):d.uv=(i/8.,(i%3)/4.)
    me.uv_layers.active_index=0;me.uv_layers[1].active_render=True;me.uv_layers[1].active_clone=True
    # Explicit authored normals, including present all-false sharp storage.
    # Distinct non-axis normals: a uniform (0,0,1) survives a float round trip byte-for-byte
    # and would hide MMD Tools >= 4.5 keep_normals re-encoding the INT16 custom_normal bytes.
    import math
    def _unit(i):
        a=.37+i*.91;b=.21+i*.53
        return (math.sin(a)*math.cos(b),math.sin(a)*math.sin(b),math.cos(a))
    me.normals_split_custom_set([_unit(i) for i in range(len(me.loops))])
    def _shading_normals(objects):
        out={}
        for o in objects:
            m=o.data
            for p in m.polygons:
                for li in p.loop_indices:
                    c=m.vertices[m.loops[li].vertex_index].co
                    out[tuple(round(x,4) for x in (*c,*p.center))]=tuple(m.loops[li].normal)
        return out
    original_normals=_shading_normals([ob])
    for name,domain in (('sharp_edge','EDGE'),('sharp_face','FACE')):
        if me.attributes.get(name) is None:me.attributes.new(name,'BOOLEAN',domain)
    values={'FLOAT':.125,'INT':127,'FLOAT_VECTOR':(.1,.2,.3),'FLOAT_COLOR':(.1,.2,.3,.4),
            'BYTE_COLOR':(.2,.4,.6,.8),'STRING':b'author-\xff','BOOLEAN':True,'FLOAT2':(.25,.75),
            'INT8':-12,'INT16_2D':(-9,10),'INT32_2D':(-12345,67890),'QUATERNION':(1.,0.,0.,0.),
            'FLOAT4X4':Matrix(((1,.25,0,0),(0,1,0,0),(0,0,1,0),(0,0,0,1)))}
    for n,(typ,value) in enumerate(values.items()):
        domain=('POINT','EDGE','CORNER','FACE')[n%4];name='ZZZSplit_author_'+typ
        a=me.attributes.new(name,typ,domain);field=validation._ATTRIBUTE_STORAGE[typ][0]
        for item in a.data:setattr(item,field,value)
    pin=me.attributes.new('.pn.UV_primary','BOOLEAN','CORNER');pin.data[1].value=True
    me.color_attributes.default_color_name='ZZZSplit_author_BYTE_COLOR'
    me.color_attributes.render_color_index=0
    original_uv=native_split._uv_meta(me);original_shape=native_split._shape_meta(me)
    morph=root.mmd_root.material_morphs.add();morph.name='Modern_Target'
    target=morph.data.add();target.material_data=mats[1];target.material_id=101;target.related_mesh_data=me
    bones=validation.skeleton(arm);original_materials=[m.as_pointer() for m in mats]
    parts,proof=native_split.separate(bpy.context,rig,root,arm,[ob],mats,'synthetic-proof-20261117')
    R['proof']=proof
    check('real_native_operator_and_exact_proof',proof['operator']=='mmd_tools.separate_by_materials' and proof['semantic_equivalence'] and len(parts)==2)
    after_normals=_shading_normals(parts.values())
    worst=max((math.degrees(math.acos(max(-1.,min(1.,sum(x*y for x,y in zip(v,original_normals[k])))))) for k,v in after_normals.items() if k in original_normals),default=999.)
    check('custom_normal_bytes_and_shading_retained',len(after_normals)==len(original_normals)==6 and set(after_normals)==set(original_normals) and worst<.5,{'corners':len(after_normals),'worst_deg':worst})
    check('author_skeleton_unchanged',validation.skeleton(arm)==bones)
    check('original_material_ids_retained',[m.as_pointer() for m in mats]==original_materials and [m.mmd_material.material_id for m in mats]==[100,101])
    check('modern_morph_pointer_numeric_and_related_mesh',target.material_data==mats[1] and target.material_id==101 and any(target.related_mesh_data==p.data and mats[1] in p.data.materials.values() for p in parts.values()))
    check('uv_clone_render_and_default_color',all(native_split._uv_meta(p.data)==original_uv for p in parts.values()))
    check('full_shape_metadata_retained',all(native_split._shape_meta(p.data)==original_shape for p in parts.values()))
    check('arbitrary_provenance_like_authored_layers_retained',all(p.data.attributes.get('ZZZSplit_author_'+typ) for p in parts.values() for typ in values))
    check('unused_and_renderer_named_author_groups_retained',all(p.vertex_groups.get('unused_authored').lock_weight and p.vertex_groups.get('GN_Outline') and p.vertex_groups.get('OutlineMask') for p in parts.values()))
    check('no_temporary_provenance_remaining',all(not any(a.name.startswith('ZZZSplit_synthetic-pr') for a in p.data.attributes) for p in parts.values()))
    R['status']='pass_real_native_split_typed_authored_morph_provenance'
except Exception as exc:
    R.update(status='fail',error=str(exc),traceback=traceback.format_exc());raise
finally:
    (O/'native_split.json').write_text(json.dumps(R,ensure_ascii=False,indent=2),encoding='utf-8')
    print('HEADLESS '+json.dumps({'status':R['status'],'checks':len(R['checks']),'report':str(O/'native_split.json'),'error':R.get('error')},ensure_ascii=False),flush=True)
