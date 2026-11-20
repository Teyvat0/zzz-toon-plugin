"""TEST ONLY: hidden/disconnected source preservation is not render admission."""
import bpy,sys,json,traceback,hashlib
from pathlib import Path
from datetime import datetime
ROOT=Path(__file__).resolve().parents[2]
O=ROOT/'test_outputs'/'retained_images'/datetime.now().strftime('%Y%m%d_%H%M%S_%f');O.mkdir(parents=True,exist_ok=False)
R={'status':'running','reader':bpy.app.version_string,'checks':[]}
def check(name,value,detail=None):
    R['checks'].append({'name':name,'pass':bool(value),'detail':detail})
    if not value:raise AssertionError((name,detail))
def material(name):
    m=bpy.data.materials.new(name);m.use_nodes=True;return m
try:
    check('correct_goo',bpy.app.version[:3]==(4,4,3) and 'Goo' in bpy.app.version_string)
    sys.path.insert(0,str(ROOT));from zzz_mmd_toon import dependencies
    for obj in list(bpy.data.objects):bpy.data.objects.remove(obj,do_unlink=True)
    parts={}
    for slot in range(2):
        me=bpy.data.meshes.new('RetentionMesh'+str(slot));me.from_pydata([(0,0,0),(1,0,0),(0,1,0)],[],[(0,1,2)])
        ob=bpy.data.objects.new('RetentionPart'+str(slot),me);bpy.context.scene.collection.objects.link(ob);parts[slot]=ob
        me.materials.append(material('RetentionMat'+str(slot)));ob.hide_render=bool(slot)
    def image(name,color):
        generated=bpy.data.images.new(name,width=2,height=2,alpha=True);generated.generated_color=color
        path=O/(name+'.png');generated.filepath_raw=str(path);generated.file_format='PNG';generated.save()
        bpy.data.images.remove(generated);return bpy.data.images.load(str(path),check_existing=False)
    visible=image('visible',(1,0,0,1));hidden=image('hidden',(0,1,0,1));unused=image('native_unused',(0,0,1,1))
    for slot,im in enumerate((visible,hidden)):
        tree=parts[slot].data.materials[0].node_tree;node=tree.nodes.new('ShaderNodeTexImage');node.image=im
        tree.links.new(node.outputs['Color'],tree.nodes.get('Principled BSDF').inputs['Base Color'])
    tree=parts[1].data.materials[0].node_tree
    group=bpy.data.node_groups.new('DisconnectedNative','ShaderNodeTree');node=group.nodes.new('ShaderNodeTexImage');node.image=unused
    tree.nodes.new('ShaderNodeGroup').node_tree=group
    broken=bpy.data.images.new('missing_unused_native_toon',width=2,height=2);broken.source='FILE';broken.filepath=str(O/'intentionally_missing_toon.png')
    group.nodes.new('ShaderNodeTexImage').image=broken
    gn_only=image('gn_socket_only',(1,1,0,1));gn_mat=material('GN_socket_only_material')
    gn_mat.node_tree.nodes.new('ShaderNodeTexImage').image=gn_only
    gn=bpy.data.node_groups.new('HiddenRetainedGeometry','GeometryNodeTree')
    gn.nodes.new('GeometryNodeSetMaterial').inputs['Material'].default_value=gn_mat
    mod=parts[1].modifiers.new('HiddenRetainedGeometry','NODES');mod.node_group=gn
    check('admission_excludes_hidden_and_disconnected',{i.name for i in dependencies.active_images(parts)}=={visible.name})
    check('retention_includes_hidden_native_and_broken',{i.name for i in dependencies.retained_images(parts)}=={visible.name,hidden.name,unused.name,broken.name,gn_only.name})
    records=dependencies.pack_retained_images(parts);R['records']=records
    check('valid_hidden_and_disconnected_images_packed',all(i.packed_file for i in (visible,hidden,unused,gn_only)))
    check('broken_disconnected_does_not_block',next(x for x in records if x['name']==broken.name)['status']=='skipped_unusable_disconnected')
    dependencies.verify_retained_images(records)
    for row in records:
        if row['status']=='packed_retained':
            check('source_and_actual_packed_hash_'+row['name'],row['source_file_sha256']==row['packed_sha256'][0])
    artifact=O/'synthetic_retained.blend';bpy.ops.wm.save_as_mainfile(filepath=str(artifact),check_existing=False)
    bpy.ops.wm.open_mainfile(filepath=str(artifact),load_ui=False,use_scripts=False)
    dependencies.verify_retained_images(records);check('retained_bytes_verified_after_reopen',True)
    im=bpy.data.images['hidden.png']
    im.unpack(method='REMOVE')
    try:dependencies.verify_retained_images(records)
    except RuntimeError as exc:check('hidden_unpack_mutation_rejected','保留源贴图' in str(exc),str(exc))
    else:raise AssertionError('hidden unpack must be rejected')
    R['status']='pass_hidden_and_disconnected_image_retention'
except Exception as exc:
    R.update(status='fail',error=str(exc),traceback=traceback.format_exc());raise
finally:
    (O/'retained_images.json').write_text(json.dumps(R,ensure_ascii=False,indent=2),encoding='utf-8')
    print('HEADLESS '+json.dumps({'status':R['status'],'checks':len(R['checks']),'error':R.get('error'),'report':str(O/'retained_images.json')},ensure_ascii=False),flush=True)
