"""TEST ONLY: actual native MaterialMorph nodes + pixel proof for live shell alpha.
Opens only a generated test artifact; never writes a .blend or changes baselines.
"""
import bpy,sys,json,traceback,math
import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1])); import testenv
from pathlib import Path
from datetime import datetime
from types import SimpleNamespace
from array import array
ROOT=Path(__file__).resolve().parents[2]
KIND=sys.argv[sys.argv.index('--')+1] if '--' in sys.argv else 'astra'
O=ROOT/'test_outputs'/'material_morph'/KIND/datetime.now().strftime('%Y%m%d_%H%M%S_%f');O.mkdir(parents=True,exist_ok=False)
R={'kind':KIND,'reader':bpy.app.version_string,'status':'running','checks':[]}
def check(name,value,detail=None):
 R['checks'].append({'name':name,'pass':bool(value),'detail':detail});assert value,(name,detail)
def pixels(path):
 im=bpy.data.images.load(str(path),check_existing=False)
 try:
  out=array('f',[0.])*(len(im.pixels));im.pixels.foreach_get(out);return out
 finally:bpy.data.images.remove(im)
def difference(a,b):
 ds=[abs(x-y) for x,y in zip(a,b)]
 return {'max':max(ds,default=0.),'mean':sum(ds)/max(1,len(ds)),'changed_components':sum(x>1e-6 for x in ds),'components':len(ds)}
try:
 check('correct_goo',bpy.app.version[:2]==(4,4) and 'Goo' in bpy.app.version_string)
 sys.path.insert(0,str(ROOT));import zzz_mmd_toon;zzz_mmd_toon.register()
 sys.path.insert(0,str(testenv.mmd_parent()));import mmd_tools;mmd_tools.register()
 from zzz_mmd_toon import workflow,validation,mmd_adapter
 from mmd_tools.core.shader import _MaterialMorph
 info=json.loads((ROOT/'test_outputs'/KIND/'latest.json').read_text(encoding='utf-8'))
 path=Path(info['artifact']['path']).resolve()
 check('generated_test_artifact_only',path.is_relative_to((ROOT/'test_outputs').resolve()) and path.suffix=='.blend')
 original=validation.file_hash(path)
 bpy.ops.wm.open_mainfile(filepath=str(path),load_ui=True,use_scripts=False)
 _,rig,root,arm,meshes=mmd_adapter.selected(bpy.context);mmd_adapter.select_root(bpy.context,root)
 scene=bpy.context.scene;settings=scene.zzz_toon;data=json.loads(root['zzz_run'])
 parts={int(o['zzz_slot']):o for o in meshes};mats=mmd_adapter.original_materials(meshes)
 def guarded():
  return workflow.run(bpy.context,resource_dir=settings.resource_dir,outline_scale=settings.outline_scale,render=False)['status']=='already_configured_noop'
 check('original_guard_valid',guarded())
 world=scene.rigidbody_world
 if world:world.enabled=False
 scene.frame_set(1);bpy.context.view_layer.update()
 def render(label):
  target=O/(label+'.png');scene.eevee.taa_render_samples=24
  scene.render.resolution_x=640;scene.render.resolution_y=480;scene.render.resolution_percentage=100
  scene.render.filepath=str(target)
  result=bpy.ops.render.render(write_still=True,scene=scene.name)
  check('render_'+label,result=={'FINISHED'} and target.is_file())
  return pixels(target)
 # Bind the SAME native Morph implementation which user material-Morph binding uses.
 # It relinks mmd_shader INSTANCE inputs after configuration, never source IDs.
 spec=SimpleNamespace(name='ZZZ_TEST_Multiply',offset_type='MULT',ambient_color=(1.,1.,1.),diffuse_color=(.45,1.,1.,0.),specular_color=(1.,1.,1.),shininess=1.,edge_color=(1.,1.,1.,1.),texture_factor=(1.,1.,1.,1.),sphere_texture_factor=(1.,1.,1.,1.),toon_texture_factor=(1.,1.,1.,1.))
 native_nodes=[]
 for mat in mats:
  native_nodes.extend(_MaterialMorph.setup_morph_nodes(mat,[spec]))
 for n in native_nodes:n.inputs['Fac'].default_value=0.
 bpy.context.view_layer.update();check('native_morph_bind_keeps_renderer_guard',guarded())
 visible=render('01_native_morph_fac0')
 for n in native_nodes:n.inputs['Fac'].default_value=1.
 bpy.context.view_layer.update();check('native_alpha_zero_keeps_guard',guarded())
 hidden_alpha=render('02_native_alpha_zero')
 hidden_flags=[(o,o.hide_render) for o in meshes]
 for o,_ in hidden_flags:o.hide_render=True
 baseline=render('03_geometry_hidden_control')
 for o,flag in hidden_flags:o.hide_render=flag
 zero=difference(hidden_alpha,baseline);R['alpha_zero_vs_hidden']=zero
 check('zero_native_alpha_removes_surface_and_outline_pixels',zero['max']<=2./255 and zero['mean']<=1e-5,zero)
 for n in native_nodes:n.inputs['Alpha2'].default_value=1.
 bpy.context.view_layer.update();check('native_color_morph_keeps_guard',guarded())
 colored=render('04_native_diffuse_color')
 color=difference(visible,colored);R['diffuse_change']=color
 check('native_diffuse_morph_changes_actual_pixels',color['mean']>1e-5 and color['changed_components']>100,color)
 for n in native_nodes:n.inputs['Fac'].default_value=0.
 bpy.context.view_layer.update();restored=render('05_native_morph_restored')
 restored_diff=difference(visible,restored);R['restore_difference']=restored_diff
 check('native_morph_restores_actual_pixels',restored_diff['max']<=2./255 and restored_diff['mean']<1e-5,restored_diff)
 # Isolate generated shells in EVALUATED GN only. The original Mesh stays untouched.
 # This is an ablation, so intentionally do not run the authored-GN guard until restored.
 cut=[]
 for o in meshes:
  for mod in o.modifiers:
   if mod.type!='NODES' or not mod.node_group or not mod.node_group.get('zzz_owner'):continue
   tree=mod.node_group
   for node in tree.nodes:
    if node.bl_idname!='GeometryNodeStoreNamedAttribute':continue
    if node.inputs['Name'].default_value!='ZZZ_OutlineShell' or bool(node.inputs['Value'].default_value):continue
    for link in list(tree.links):
     if link.from_node==node and link.to_node.bl_idname=='GeometryNodeJoinGeometry':
      cut.append((tree,link.from_socket,link.to_socket));tree.links.remove(link)
 check('shell_only_ablation_found_original_branches',bool(cut),len(cut))
 scene.render.use_compositing=False
 for n in native_nodes:n.inputs['Alpha2'].default_value=1.;n.inputs['Fac'].default_value=0.
 shell_visible=render('06_generated_shell_only')
 for n in native_nodes:n.inputs['Alpha2'].default_value=0.;n.inputs['Fac'].default_value=1.
 shell_zero=render('07_generated_shell_alpha_zero')
 for o,_ in hidden_flags:o.hide_render=True
 shell_control=render('08_shell_geometry_hidden_control')
 for o,flag in hidden_flags:o.hide_render=flag
 shell_delta=difference(shell_visible,shell_zero);shell_clear=difference(shell_zero,shell_control)
 R['shell_visible_change']=shell_delta;R['shell_zero_vs_control']=shell_clear
 check('generated_shell_has_visible_pixels',shell_delta['changed_components']>20,shell_delta)
 check('generated_shell_disappears_with_native_alpha',shell_clear['max']<=2./255 and shell_clear['mean']<=1e-5,shell_clear)
 for tree,source,target in cut:tree.links.new(source,target)
 scene.render.use_compositing=True
 for n in native_nodes:n.inputs['Fac'].default_value=0.
 bpy.context.view_layer.update();check('restored_authored_guard_after_ablation',guarded())
 check('saved_artifact_never_overwritten',validation.file_hash(path)==original)
 R.update(status='pass_actual_native_material_morph_color_alpha_and_same_material_shell',source=str(path),source_sha256=original,synthetic_native_morph_nodes=len(native_nodes),renders=[str(p) for p in sorted(O.glob('*.png'))],limits=['Synthetic MULT Diffuse/Alpha Morph nodes are real native MMD Tools nodes, but this is not proof of every native material-Morph property.','Shell-only isolation temporarily modifies evaluated GN in memory and is restored; the saved .blend and original source Mesh are never written.'])
except Exception as exc:
 R.update(status='fail',error=str(exc),traceback=traceback.format_exc());raise
finally:
 (O/'report.json').write_text(json.dumps(R,ensure_ascii=False,indent=2),encoding='utf-8')
 (O.parent/'latest.json').write_text(json.dumps(R,ensure_ascii=False,indent=2),encoding='utf-8')
 print('HEADLESS '+json.dumps({'kind':KIND,'status':R['status'],'checks':len(R['checks']),'error':R.get('error'),'report':str(O/'report.json')},ensure_ascii=False),flush=True)
