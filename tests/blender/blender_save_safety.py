"""TEST ONLY: genuine MMD save_pre mutation and read-only rejection before backup.
Synthetic RNA data only; all files are unique below test_outputs/save_safety.
"""
import bpy, sys, json, traceback
import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1])); import testenv
from pathlib import Path
from datetime import datetime
ROOT=Path(__file__).resolve().parents[2]
O=ROOT/'test_outputs'/'save_safety'/datetime.now().strftime('%Y%m%d_%H%M%S_%f')
O.mkdir(parents=True,exist_ok=False)
R={'status':'running','reader':bpy.app.version_string,'checks':[]}
def check(name,value,detail=None):
    R['checks'].append({'name':name,'pass':bool(value),'detail':detail})
    if not value:raise AssertionError((name,detail))
def expect_rejected(name,call,fragment):
    try:call()
    except RuntimeError as exc:
        check(name,fragment in str(exc),str(exc));return str(exc)
    raise AssertionError('Expected rejection: '+name)
try:
    check('correct_goo',bpy.app.version[:3]==(4,4,3) and 'Goo' in bpy.app.version_string)
    sys.path.insert(0,str(ROOT));import zzz_mmd_toon;zzz_mmd_toon.register()
    sys.path.insert(0,str(testenv.mmd_parent()))
    import mmd_tools;mmd_tools.register()
    from mmd_tools.handlers import MMDHanders
    from mmd_tools.core.material import FnMaterial
    from zzz_mmd_toon import transaction,workflow
    check('actual_native_handler_registered',MMDHanders.save_pre_handler in bpy.app.handlers.save_pre)
    for obj in list(bpy.data.objects):bpy.data.objects.remove(obj,do_unlink=True)
    for material in list(bpy.data.materials):bpy.data.materials.remove(material)
    a=bpy.data.materials.new('Save_A');b=bpy.data.materials.new('Save_B')
    a.use_fake_user=b.use_fake_user=True
    root=bpy.data.objects.new('Synthetic_MMD_Root',None);bpy.context.scene.collection.objects.link(root);root.mmd_type='ROOT'
    morph=root.mmd_root.material_morphs.add();morph.name='save_probe'
    target=morph.data.add();target.material_data=a;target.material_id=7
    a.mmd_material.material_id=b.mmd_material.material_id=7
    def raw_state():
        return {'ids':[(m.name,int(m.mmd_material.material_id)) for m in bpy.data.materials],
                'target':(target.material_data.name if target.material_data else None,int(target.material_id))}
    # Prove the installed native save handler really has the dangerous behavior.
    MMDHanders.save_pre_handler(None)
    check('actual_native_duplicate_renumber_demonstrated',a.mmd_material.material_id!=b.mmd_material.material_id,raw_state())
    a.mmd_material.material_id=7;b.mmd_material.material_id=7;target.material_id=7
    before=raw_state();path=O/'forbidden_duplicate.blend'
    expect_rejected('duplicate_rejected_before_checkpoint',lambda:transaction.checkpoint(path),'重复原生Material ID')
    check('duplicate_no_file_or_mutation',not path.exists() and raw_state()==before,raw_state())
    # workflow rejects the same global ambiguity even before model selection/new_run.
    expect_rejected('workflow_duplicate_rejected_before_00',lambda:workflow.run(bpy.context,render=False,output_dir=str(O/'forbidden_run')),'重复原生Material ID')
    check('workflow_no_run_directory',not (O/'forbidden_run').exists())
    b.mmd_material.material_id=8;target.material_data=None;target.material_id=7
    MMDHanders.save_pre_handler(None)
    check('actual_native_numeric_only_clear_demonstrated',target.material_id==-1)
    target.material_id=7;before=raw_state();path=O/'forbidden_legacy.blend'
    expect_rejected('numeric_only_rejected_before_checkpoint',lambda:transaction.checkpoint(path),'只有数值ID')
    check('legacy_no_file_or_mutation',not path.exists() and raw_state()==before)
    target.material_data=a;target.material_id=8;before=raw_state();path=O/'forbidden_mismatch.blend'
    expect_rejected('mismatch_rejected_before_checkpoint',lambda:transaction.checkpoint(path),'不一致')
    check('mismatch_no_file_or_mutation',not path.exists() and raw_state()==before)
    target.material_id=7
    all_target=morph.data.add();all_target.material_data=None;all_target.material_id=-1
    before=transaction.material_save_state();path=O/'valid_modern_and_all.blend'
    artifact=transaction.checkpoint(path)
    check('modern_and_all_checkpoint_pass',path.is_file() and artifact['bytes']>1024 and transaction.material_save_state()==before,artifact)
    # Safe native lazy-ID initialization must retain modern target pointers; unlike
    # legacy numeric-only data it starts with matching negative IDs and is explicit.
    a.mmd_material.material_id=-1;target.material_id=-1
    transaction.material_save_state();old_pointer=target.material_data.as_pointer();new_id=FnMaterial(a).material_id
    target.material_id=new_id
    check('native_negative_initialization_modern_target',new_id>=0 and target.material_data.as_pointer()==old_pointer and transaction.material_save_state() is not None)
    before=transaction.material_save_state();path=O/'valid_initialized.blend'
    transaction.checkpoint(path);check('initialized_checkpoint_pass',path.is_file() and transaction.material_save_state()==before)
    # An unexpected later third-party save handler may mutate even valid input.
    # Production must refuse success, never pretend that file is an exact backup.
    def unexpected_handler(_):b.mmd_material.material_id+=100
    bpy.app.handlers.save_pre.append(unexpected_handler)
    path=O/'intentionally_invalid_handler_mutation.blend'
    try:
        message=expect_rejected('unexpected_save_handler_mutation_rejected',lambda:transaction.checkpoint(path),'意外改变')
        marker=Path(str(path)+'.INVALID_SAVE.json')
        check('unexpected_handler_file_marked_invalid',marker.is_file() and json.loads(marker.read_text(encoding='utf-8'))['trusted_checkpoint'] is False)
        R['intentional_invalid_backup']={'path':str(path),'must_not_use':True,'reason':message,'invalid_marker':str(marker)}
    finally:
        bpy.app.handlers.save_pre.remove(unexpected_handler)
    R['status']='pass_native_handler_and_preflight_fail_paths'
except Exception as exc:
    R.update(status='fail',error=str(exc),traceback=traceback.format_exc());raise
finally:
    (O/'save_safety.json').write_text(json.dumps(R,ensure_ascii=False,indent=2),encoding='utf-8')
    print('HEADLESS '+json.dumps({'status':R['status'],'report':str(O/'save_safety.json'),'checks':len(R['checks']),'error':R.get('error')},ensure_ascii=False),flush=True)
