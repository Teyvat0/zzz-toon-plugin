"""Per-slot backface-culling override (AUTO/ON/OFF) reaches the final material and is remembered.
Usage: blender --factory-startup -b --python this.py -- PMX RESOURCE_DIR OUT_DIR
"""
import bpy, sys, json
import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1])); import testenv
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
PMX, RES, OUT = sys.argv[sys.argv.index('--') + 1:][:3]
sys.path.insert(0, str(ROOT))
import zzz_mmd_toon
zzz_mmd_toon.register()
from zzz_mmd_toon import workflow, mmd_adapter, ui, user_mapping
sys.path.insert(0, str(testenv.mmd_parent()))
import mmd_tools
mmd_tools.register()
bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete(use_global=False)
assert bpy.ops.mmd_tools.import_model(filepath=PMX, types={'MESH', 'ARMATURE', 'MORPHS', 'DISPLAY', 'PHYSICS'}, scale=.08,
                                      clean_model=False, remove_doubles=False, rename_bones=False, save_log=False) == {'FINISHED'}
_, rig, root, arm, meshes = mmd_adapter.selected(bpy.context)
mmd_adapter.select_root(bpy.context, root)
plan = workflow.scan(bpy.context, RES)
s = bpy.context.scene.zzz_toon
s.resource_dir, s.output_dir, s.samples, s.resolution = RES, OUT, 16, 256
ui.populate(s, plan)
auto = {r.slot: r.cull for r in s.rows}
assert set(auto.values()) == {'AUTO'}, auto
mapped = [r for r in s.rows if not r.keep_original and r.role not in ('eye', 'mouth', 'eyebrow')]
on, off = mapped[0], mapped[1]
on.cull, off.cull = 'ON', 'OFF'
saved = json.loads(user_mapping.path_for(RES).read_text(encoding='utf-8')) if user_mapping.path_for(RES).is_file() else {}
assert {x['slot']: x['cull'] for x in saved.get('slots', [])}.get(on.slot) == 'ON', saved
rows = ui.mapping(s)
res = workflow.run(bpy.context, resource_dir=RES, output_dir=OUT, mapping=rows, render=False, outline_scale=1., samples=16, resolution=256)
mats = {m.get('zzz_source_slot'): m for m in bpy.data.materials if m.get('zzz_owner')}
assert mats[on.slot].use_backface_culling is True, ('on', mats[on.slot].name)
assert mats[off.slot].use_backface_culling is False, ('off', mats[off.slot].name)
print('HEADLESS ' + json.dumps({'status': 'pass', 'on': on.source_name, 'off': off.source_name}, ensure_ascii=False))
