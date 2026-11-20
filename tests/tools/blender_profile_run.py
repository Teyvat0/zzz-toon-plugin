"""TEST ONLY: time each stage of workflow.run (no addon change).
Usage: blender -b --python this.py -- <pmx> <resource_dir> [render:0|1]
"""
import bpy, sys, time, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
argv = sys.argv[sys.argv.index('--') + 1:]
PMX, RES = Path(argv[0]), argv[1]
RENDER = (argv[2] != '0') if len(argv) > 2 else False
sys.path.insert(0, str(ROOT))
import zzz_mmd_toon
zzz_mmd_toon.register()
from zzz_mmd_toon import workflow, validation, mmd_adapter, renderer, transaction, dependencies, application, game_bridge
sys.path.insert(0, r'C:\Users\gyf20\AppData\Roaming\Blender Foundation\Blender\4.4\extensions\blender_org')
import mmd_tools
mmd_tools.register()
T = {}


def wrap(mod, name, label=None):
    fn = getattr(mod, name)
    label = label or mod.__name__.split('.')[-1] + '.' + name

    def inner(*a, **k):
        t = time.perf_counter()
        try:
            return fn(*a, **k)
        finally:
            T[label] = T.get(label, 0) + time.perf_counter() - t
    setattr(mod, name, inner)


for mod, names in ((transaction, ['checkpoint', 'material_save_state', 'new_run']),
                   (mmd_adapter, ['prepare_universal', 'original_materials']),
                   (renderer, ['build', 'attach_model', 'head_frame', 'fit_camera']),
                   (dependencies, ['pack_retained_images']),
                   (validation, ['scene_gate', 'shader_state', 'material_targets', 'skeleton', 'mesh_state', 'digest']),
                   (workflow, ['scan', '_preflight_meshes', '_apply', '_save_new', '_render_checked', '_inherit_ui', '_mapping']),
                   (application, ['apply'])):
    for n in names:
        wrap(mod, n)
bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete(use_global=False)
t0 = time.perf_counter()
bpy.ops.mmd_tools.import_model(filepath=str(PMX), types={'MESH', 'ARMATURE', 'MORPHS', 'DISPLAY', 'PHYSICS'},
                               scale=.08, clean_model=False, remove_doubles=False, rename_bones=False, save_log=False)
T['_import_pmx(not part of run)'] = time.perf_counter() - t0
_, rig, root, arm, meshes = mmd_adapter.selected(bpy.context)
mmd_adapter.select_root(bpy.context, root)
t0 = time.perf_counter()
out = Path(ROOT / 'test_outputs' / 'profile'); out.mkdir(parents=True, exist_ok=True)
try:
    workflow.run(bpy.context, RES, output_dir=str(out), render=RENDER, samples=24, resolution=int(argv[3]) if len(argv)>3 else 400)
finally:
    T['TOTAL run'] = time.perf_counter() - t0
    for k, v in sorted(T.items(), key=lambda x: -x[1]):
        print('PROFILE %7.2fs  %s' % (v, k), flush=True)

