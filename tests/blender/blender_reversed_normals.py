"""Kept-original materials with inward custom normals are flagged at scan time.
Usage: blender --factory-startup -b --python this.py -- PMX RESOURCE_DIR EXPECTED_NAME|none
"""
import bpy, sys, json
import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1])); import testenv
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
PMX, RES, EXPECT = sys.argv[sys.argv.index('--') + 1:][:3]
sys.path.insert(0, str(ROOT))
import zzz_mmd_toon
zzz_mmd_toon.register()
from zzz_mmd_toon import workflow, mmd_adapter, ui
sys.path.insert(0, str(testenv.mmd_parent()))
import mmd_tools
mmd_tools.register()
bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete(use_global=False)
assert bpy.ops.mmd_tools.import_model(filepath=PMX, types={'MESH', 'ARMATURE', 'MORPHS', 'DISPLAY', 'PHYSICS'}, scale=.08,
                                      clean_model=False, remove_doubles=False, rename_bones=False, save_log=False) == {'FINISHED'}
_, rig, root, arm, meshes = mmd_adapter.selected(bpy.context)
mmd_adapter.select_root(bpy.context, root)
plan = workflow.scan(bpy.context, RES)
flagged = [r['name'] for r in plan['rows'] if r.get('reversed_normals')]
ui.populate(bpy.context.scene.zzz_toon, plan)
shown = [r.source_name for r in bpy.context.scene.zzz_toon.rows if json.loads(r.evidence_json).get('reversed_normals')]
ok = (flagged == [] if EXPECT == 'none' else flagged == [EXPECT]) and shown == flagged
ok = ok and (EXPECT == 'none' or any(EXPECT in w for w in plan['warnings']))
print('HEADLESS ' + json.dumps({'status': 'pass' if ok else 'fail', 'flagged': flagged, 'shown': shown, 'warnings': plan['warnings'][:3]}, ensure_ascii=False))
sys.exit(0 if ok else 1)
