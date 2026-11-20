"""TEST ONLY: user-native PMX import + required resources + actual sidebar click.
Fixture paths are never packaged into addon runtime or used as character profiles.
"""
import bpy,sys,json,traceback
from pathlib import Path
from datetime import datetime
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(Path(__file__).resolve().parent))
from mesh_signature_probe import capture
KIND=sys.argv[sys.argv.index('--')+1] if '--' in sys.argv else 'evelyn'
INPUTS={
 'evelyn':(r'D:\MMD\模型\人物\伊芙琳_by_绝区零_630d71de799045678c911656844d3b75\伊芙琳.pmx',r'D:\MMD\HoyoToon-Assets-main\Zenless Zone Zero\ZZZ-Characters\evelyn-chevalier-a-moth-to-light'),
 'astra':(r'D:\MMD\模型\人物\耀嘉音_by_绝区零_9e78c01eb6ef4d6f824d5d6a4b7f5210\耀嘉音.pmx',r'D:\MMD\HoyoToon-Assets-main\Zenless Zone Zero\ZZZ-Characters\astra-yao-scarlet-rock-chandelier\Scarlet Rock'),
 'velina':(r'D:\MMD\模型\人物\维琳娜_by_绝区零_dbd71bbd269a01b0164ec59fc508280c\维琳娜6.pmx',r'D:\MMD\HoyoToon-Assets-main\Zenless Zone Zero\ZZZ-Characters\velina-airgid-elegant-silver-cascade-shade-of-leisure\Elegant Silver Cascade'),
 'ye':(r'D:\MMD\模型\人物\叶瞬光皮肤_by_绝区零_d97a3a854fea33f2169a8773b6ad69c2\叶瞬光.pmx',r'D:\MMD\HoyoToon-Assets-main\Zenless Zone Zero\ZZZ-Characters\ye-shunguang-clouddrift-illumination-touch-of-dawnlight\Touch of Dawnlight'),
 'remielle':(r'D:\MMD\模型\人物\3.1蕾米埃尔_by_绝区零_b01b5cf19c83a57d763b11a0995c74b3\蕾米埃尔-白\蕾米埃尔-白.pmx',r'D:\MMD\HoyoToon-Assets-main\Zenless Zone Zero\ZZZ-Characters\remielle-dan-feathered-murmurs-seashade-pas-seul\Feathered Murmurs'),
}
PMX,RESOURCE=INPUTS[KIND];PMX=Path(PMX)
O=ROOT/'test_outputs'/KIND/datetime.now().strftime('%Y%m%d_%H%M%S_%f');O.mkdir(parents=True,exist_ok=False)
R={'kind':KIND,'status':'running','reader':bpy.app.version_string,'checks':[]}
def check(name,value,detail=None):
 R['checks'].append({'name':name,'pass':bool(value),'detail':detail});assert value,(name,detail)
def counts():return {k:len(getattr(bpy.data,k)) for k in ('objects','materials','node_groups','meshes','armatures')}
try:
 check('correct_goo',bpy.app.version[:3]==(4,4,3) and 'Goo' in bpy.app.version_string)
 source_manifest={str(p):__import__('hashlib').sha256(p.read_bytes()).hexdigest() for p in (ROOT/'zzz_mmd_toon').rglob('*.py')}
 R['production_source_manifest']=source_manifest
 sys.path.insert(0,str(ROOT));import zzz_mmd_toon;zzz_mmd_toon.register()
 from zzz_mmd_toon import workflow,validation,mmd_adapter,ui,game_bridge
 sys.path.insert(0,r'C:\Users\gyf20\AppData\Roaming\Blender Foundation\Blender\4.4\extensions\blender_org')
 import mmd_tools;mmd_tools.register()
 bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
 original_hash=validation.file_hash(PMX)
 check('user_native_import',bpy.ops.mmd_tools.import_model(filepath=str(PMX),types={'MESH','ARMATURE','MORPHS','DISPLAY','PHYSICS'},scale=.08,clean_model=False,remove_doubles=False,rename_bones=False,save_log=False)=={'FINISHED'})
 _,rig,root,arm,meshes=mmd_adapter.selected(bpy.context);mmd_adapter.select_root(bpy.context,root)
 parts={i:o for i,o in enumerate(meshes)};mats=mmd_adapter.original_materials(meshes)
 capture(parts,O/'mesh_components','imported')
 before={'mesh':validation.mesh_state(parts),'bones':validation.skeleton(arm),'mesh_ids':[o.data.as_pointer() for o in meshes],
         'mat_ids':[m.as_pointer() for m in mats], 'slots':[[m.as_pointer() if m else None for m in o.data.materials] for o in meshes],
         'morphs':[len(root.mmd_root.vertex_morphs),len(root.mmd_root.material_morphs),len(root.mmd_root.bone_morphs)],
         'physics':[len(list(rig.rigidBodies())),len(list(rig.joints()))]}
 no_resource=workflow.scan(bpy.context,'');check('resource_directory_required',bool(no_resource['errors']))
 plan=workflow.scan(bpy.context,RESOURCE);R['plan']=plan
 check('no_profile_or_character_admission',plan.get('profile') is None)
 check('every_material_has_game_identity',len(plan['rows'])==len(mats) and not plan['errors'] and all(r['stem'] and r['backend']=='GAME_JSON' for r in plan['rows']),plan['errors'])
 check('effect_pass_not_used_as_surface',not any('hairshadow' in r['stem'].lower().replace('_','') for r in plan['rows']))
 settings=bpy.context.scene.zzz_toon;settings.resource_dir=RESOURCE;settings.output_dir=str(O);settings.samples=24;settings.resolution=480
 check('fresh_sidebar_no_manual_mapping',len(settings.rows)==0)
 result=bpy.ops.zzz_toon.run(render=True)
 check('actual_first_ui_click_with_resources',result=={'FINISHED'},bpy.context.scene.zzz_toon.status)
 data=json.loads(root['zzz_run']);output=Path(data['output']);report=json.loads((output/'配置验证报告.json').read_text(encoding='utf-8'))
 R.update(artifact=report['artifact'],output=str(output))
 meshes=list(rig.meshes());parts={int(o['zzz_slot']):o for o in meshes}
 prep=report['prepare']
 check('native_material_separation_first',prep['operator']=='mmd_tools.separate_by_materials' and prep['clean_shape_keys'] is False and all(len({p.material_index for p in ob.data.polygons})==1 for ob in meshes),prep)
 check('exact_provenance_data_equivalence',prep['semantic_equivalence'] and prep['each_original_face_and_corner_once'] and validation.mesh_state(parts)==prep['mesh'])
 check('original_material_ids_unchanged',[m.as_pointer() for m in mmd_adapter.original_materials(meshes)]==before['mat_ids'])
 check('original_skeleton_unchanged',validation.skeleton(arm)==before['bones'])
 check('original_morph_catalog_unchanged',[len(root.mmd_root.vertex_morphs),len(root.mmd_root.material_morphs),len(root.mmd_root.bone_morphs)]==before['morphs'])
 check('native_physics_import_unchanged',[len(list(rig.rigidBodies())),len(list(rig.joints()))]==before['physics'])
 check('native_shader_and_game_bridge_retained',all(m.node_tree.nodes.get('mmd_shader') and m.node_tree.nodes.get('ZZZ_GameEnhancement') for m in mats))
 check('all_applied_game_json',all(r.get('applied_backend')=='GAME_JSON' for r in data['mapping']))
 check('current_render_policy',data.get('render_policy')==game_bridge.RENDER_POLICY and report.get('render_policy')==game_bridge.RENDER_POLICY)
 bridges=[r['bridge'] for r in report['materials'] if 'bridge' in r]
 check('audited_culling_matches_saved_materials',len(bridges)==len(mats) and all(bool(m.use_backface_culling)==r['culling']['enabled'] for m,r in zip(mats,bridges)))
 shadow_mats=[m for m in mats if m.get('preview_role') in game_bridge.EYE_SHADOW_ROLES]
 check('eye_shadow_transparent_branch_no_forward',bool(shadow_mats) and all(game_bridge.eye_shadow_tint_input(m) is not None and any(n.bl_idname=='ShaderNodeBsdfTransparent' and n.name=='ZZZ_EyeShadowTransparent' for n in m.node_tree.nodes['ZZZ_GameEnhancement'].node_tree.nodes) and not any(n.bl_idname=='ShaderNodeOutputAOV' or (n.type=='GROUP' and '1: Face, 2: Eye, 3: Body' in n.inputs) for n in m.node_tree.nodes['ZZZ_GameEnhancement'].node_tree.nodes) for m in shadow_mats))
 R['culling']=[{'slot':i,'name':m.name,'enabled':m.use_backface_culling,'policy':r['culling']} for i,(m,r) in enumerate(zip(mats,bridges))]
 check('resources_hashed_before_commit',bool(data['resource_hashes']))
 check('real_render',Path(report['image']).stat().st_size>1024)
 initial=counts();check('repeat_noop',bpy.ops.zzz_toon.run(render=False)=={'FINISHED'} and counts()==initial,bpy.context.scene.zzz_toon.status)
 # A native MaterialMorph setup can relink these sockets AFTER configuring.
 # It must not invalidate the authored renderer guard or disconnect live inputs.
 source=mats[0];native=source.node_tree.nodes['mmd_shader'];socket=native.inputs['Diffuse Color']
 old=list(socket.default_value);value=list(old);value[0]=max(.01,value[0]*.72);socket.default_value=value
 check('native_color_input_edit_no_false_guard',bpy.ops.zzz_toon.run(render=False)=={'FINISHED'},bpy.context.scene.zzz_toon.status)
 socket.default_value=old
 artifact=report['artifact'];sha=validation.file_hash(artifact['path']);mat_count=len(mats)
 capture(parts,O/'mesh_components','before_reopen')
 (O/'shader_before_reopen.json').write_text(json.dumps(validation.shader_state_data(parts),ensure_ascii=False,indent=2),encoding='utf-8')
 bpy.ops.wm.open_mainfile(filepath=artifact['path'],load_ui=True,use_scripts=False)
 _,rig,root,arm,meshes=mmd_adapter.selected(bpy.context);mmd_adapter.select_root(bpy.context,root)
 check('saved_sidebar_required_resource_and_rows',workflow._resource_path(bpy.context.scene.zzz_toon.resource_dir)==workflow._resource_path(RESOURCE) and len(bpy.context.scene.zzz_toon.rows)==mat_count)
 reopened_parts={int(o['zzz_slot']):o for o in meshes}
 capture(reopened_parts,O/'mesh_components','after_reopen')
 (O/'shader_after_reopen.json').write_text(json.dumps(validation.shader_state_data(reopened_parts),ensure_ascii=False,indent=2),encoding='utf-8')
 R['reopen_hashes']={'bones':validation.skeleton(arm),'mesh':validation.mesh_state(reopened_parts),'shader':validation.shader_state(reopened_parts),'saved':{k:data[k] for k in ('skeleton','mesh','shader')}}
 initial=counts();check('reopen_real_rerender',bpy.ops.zzz_toon.run(render=True)=={'FINISHED'} and counts()==initial,bpy.context.scene.zzz_toon.status)
 check('generated_project_not_overwritten',validation.file_hash(artifact['path'])==sha)
 check('source_pmx_not_modified',validation.file_hash(PMX)==original_hash)
 check('production_source_frozen',all(validation.file_hash(p)==h for p,h in source_manifest.items()))
 check('hidden_and_disconnected_valid_images_retained',bool(data.get('retained_images')) and all(bpy.data.images.get(r['name']) and bpy.data.images[r['name']].packed_file for r in data['retained_images'] if r['status']=='packed_retained'))
 R.update(status='pass_unprofiled_required_resources_first_click_preservation_repeat_reopen',artifact=artifact,output=str(output),
          renders=[str(p) for p in sorted(output.glob('仿ZZZ渲染_正面*.png'))],materials=mat_count,native_morphs=before['morphs'],native_physics=before['physics'],material_diagnostics=report['materials'])
except Exception as exc:
 R.update(status='fail',error=str(exc),traceback=traceback.format_exc());raise
finally:
 (O/'universal.json').write_text(json.dumps(R,ensure_ascii=False,indent=2),encoding='utf-8')
 (O.parent/'latest.json').write_text(json.dumps(R,ensure_ascii=False,indent=2),encoding='utf-8')
 print('HEADLESS '+json.dumps({'status':R['status'],'kind':KIND,'checks':len(R['checks']),'error':R.get('error'),'report':str(O/'universal.json')},ensure_ascii=False),flush=True)
