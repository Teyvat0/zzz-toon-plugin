"""TEST ONLY: PMX import + resources + real sidebar run with keep-original slots allowed.
Usage: blender -b --python this.py -- <kind> <pmx> <resource_dir> [render:0|1]
"""
import bpy, sys, json, traceback
from pathlib import Path
from datetime import datetime
ROOT = Path(__file__).resolve().parents[2]
argv = sys.argv[sys.argv.index('--') + 1:]
KIND, PMX, RES = argv[0], Path(argv[1]), argv[2]
RENDER = (argv[3] != '0') if len(argv) > 3 else True
O = ROOT / 'test_outputs' / 'keep_original' / (KIND + '_' + datetime.now().strftime('%H%M%S'))
O.mkdir(parents=True, exist_ok=True)
R = {'kind': KIND, 'status': 'running', 'checks': []}


def check(name, value, detail=None):
    R['checks'].append({'name': name, 'pass': bool(value), 'detail': detail})
    assert value, (name, detail)


try:
    sys.path.insert(0, str(ROOT))
    import zzz_mmd_toon
    zzz_mmd_toon.register()
    from zzz_mmd_toon import workflow, validation, mmd_adapter
    sys.path.insert(0, r'C:\Users\gyf20\AppData\Roaming\Blender Foundation\Blender\4.4\extensions\blender_org')
    import mmd_tools
    mmd_tools.register()
    bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete(use_global=False)
    check('import', bpy.ops.mmd_tools.import_model(filepath=str(PMX), types={'MESH', 'ARMATURE', 'MORPHS', 'DISPLAY', 'PHYSICS'},
          scale=.08, clean_model=False, remove_doubles=False, rename_bones=False, save_log=False) == {'FINISHED'})
    _, rig, root, arm, meshes = mmd_adapter.selected(bpy.context)
    mmd_adapter.select_root(bpy.context, root)
    mats = mmd_adapter.original_materials(meshes)
    plan = workflow.scan(bpy.context, RES)
    fatal = [e for e in plan['errors'] if e not in set(plan['slot_errors'])]
    check('no_resource_level_errors', not fatal, fatal)
    kept = [r['slot'] for r in plan['rows'] if r.get('keep_original')]
    R.update(materials=len(mats), mapped=len(mats) - len(kept), kept=kept,
             kept_names=[plan['rows'][s]['name'] for s in kept],
             choices={s: len(plan['rows'][s]['choices']) for s in kept})
    s = bpy.context.scene.zzz_toon
    s.resource_dir, s.output_dir, s.samples, s.resolution = RES, str(O), 16, 400
    if '--pick' in argv and kept:
        # Simulate the sidebar: scan, choose first same-role JSON per kept slot, save, rescan (reload), run.
        from zzz_mmd_toon import ui, user_mapping
        ui.populate(s, plan)
        picked = {}
        for i, row in enumerate(s.rows):
            if row.keep_original:
                cs = plan['rows'][row.slot]['choices']
                c = next((c for c in cs if c['same_role']), None)
                if c:
                    s.row_index = i; s.choice = c['stem']
                    check('apply_choice', bpy.ops.zzz_toon.apply_choice(keep=False) == {'FINISHED'})
                    picked[row.slot] = c['stem']
        check('mapping_autosaved', (Path(RES) / 'zzz_mapping.json').is_file(), s.status)
        plan2 = workflow.scan(bpy.context, RES)
        R['reloaded_stems'] = {k: plan2['rows'][k]['stem'] for k in picked}
        check('mapping_reloaded', all(plan2['rows'][k]['stem'] == v for k, v in picked.items()), R['reloaded_stems'])
        check('slot_errors_cleared', not any(e[:2].isdigit() and int(e[:2]) in picked for e in plan2['slot_errors']))
        R['picked'] = picked
        kept = [r['slot'] for r in plan2['rows'] if r.get('keep_original')]
        # fresh sidebar rows again so run rebuilds from the saved file
        s.rows.clear()
    result = bpy.ops.zzz_toon.run(render=RENDER)
    if kept and result == {'CANCELLED'} and s.unmapped_ack:   # first click only warns about unmapped slots
        check('first_click_warns_only', 'zzz_run' not in root, s.status)
        result = bpy.ops.zzz_toon.run(render=RENDER)
    check('ui_run', result == {'FINISHED'}, bpy.context.scene.zzz_toon.status)
    data = json.loads(root['zzz_run'])
    report = json.loads((Path(data['output']) / '配置验证报告.json').read_text(encoding='utf-8'))
    check('kept_slots_untouched_native', all(not m.get('zzz_owner') and m.get('zzz_keep_original') for m in mats if m.get('zzz_keep_original')))
    check('mapped_slots_game_json', sum(r.get('applied_backend') == 'GAME_JSON' for r in data['mapping']) == len(mats) - len(kept))
    if RENDER:
        check('real_render', Path(report['image']).stat().st_size > 1024)
    R['culling'] = [dict(slot=m.get('zzz_source_slot'), name=m.name, keep=bool(m.get('zzz_keep_original')),
                         role=m.get('preview_role'), cull=m.use_backface_culling,
                         pmx_double=getattr(getattr(m, 'mmd_material', None), 'is_double_sided', None))
                    for m in bpy.data.materials if m.get('zzz_source_slot') is not None]
    R['output'] = data['output']
    R['status'] = 'pass'
except Exception as exc:
    R.update(status='fail', error=str(exc), traceback=traceback.format_exc())
finally:
    (O / 'result.json').write_text(json.dumps(R, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    print('HEADLESS ' + json.dumps({k: R.get(k) for k in ('kind', 'status', 'materials', 'mapped', 'kept_names', 'error')}, ensure_ascii=False, default=str), flush=True)

