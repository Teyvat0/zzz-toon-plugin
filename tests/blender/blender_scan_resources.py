"""Read-only native imported-model material association diagnostic; not a profile."""
import sys,json,traceback
from pathlib import Path
import bpy
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from zzz_mmd_toon import auto_mapping,mmd_adapter
sys.path.insert(0,r'C:\Users\gyf20\AppData\Roaming\Blender Foundation\Blender\4.4\extensions\blender_org')
import mmd_tools;mmd_tools.register()
kind=sys.argv[sys.argv.index('--')+1]
fixtures={
'evelyn':(r'D:\MMD\模型\人物\伊芙琳_by_绝区零_630d71de799045678c911656844d3b75\伊芙琳.pmx',r'D:\MMD\HoyoToon-Assets-main\Zenless Zone Zero\ZZZ-Characters\evelyn-chevalier-a-moth-to-light'),
'astra':(r'D:\MMD\模型\人物\耀嘉音_by_绝区零_9e78c01eb6ef4d6f824d5d6a4b7f5210\耀嘉音.pmx',r'D:\MMD\HoyoToon-Assets-main\Zenless Zone Zero\ZZZ-Characters\astra-yao-scarlet-rock-chandelier\Scarlet Rock'),
'velina':(r'D:\MMD\模型\人物\维琳娜_by_绝区零_dbd71bbd269a01b0164ec59fc508280c\维琳娜6.pmx',r'D:\MMD\HoyoToon-Assets-main\Zenless Zone Zero\ZZZ-Characters\velina-airgid-elegant-silver-cascade-shade-of-leisure\Elegant Silver Cascade')}
pmx,res=fixtures[kind]
bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
bpy.ops.mmd_tools.import_model(filepath=pmx,types={'MESH','ARMATURE','MORPHS','DISPLAY','PHYSICS'},scale=.08,clean_model=False,remove_doubles=False,rename_bones=False,save_log=False)
_,rig,root,arm,meshes=mmd_adapter.selected(bpy.context)
plan=auto_mapping.plan(mmd_adapter.original_materials(meshes),meshes,arm,res)
out=ROOT/'test_outputs'/'resource_scan';out.mkdir(parents=True,exist_ok=True)
(out/(kind+'.json')).write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
(out/(kind+'.txt')).write_text('\n'.join(json.dumps({k:r.get(k) for k in ('slot','name','role','stem','atlas_candidates','texture_overrides','evidence','warnings','unresolved_reason')},ensure_ascii=False) for r in plan['rows'])+'\nERRORS\n'+'\n'.join(plan['errors']),encoding='utf-8')
print('HEADLESS '+json.dumps({'kind':kind,'summary':plan.get('summary'),'errors':plan['errors']},ensure_ascii=False),flush=True)
