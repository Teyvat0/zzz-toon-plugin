"""Repro: open a saved 00 rollback .blend and run native_split.separate on it.
Usage: blender -b --factory-startup --python repro_custom_normal_split.py -- <blend> <plugin_root> <mmd_tools_parent>
"""
import sys, json, traceback
import bpy
blend, plugin_root, mmd_parent = sys.argv[sys.argv.index('--') + 1:][:3]
sys.path.insert(0, plugin_root)
sys.path.insert(0, mmd_parent)
import mmd_tools
mmd_tools.register()
bpy.ops.wm.open_mainfile(filepath=blend)
from mmd_tools.core.model import Model, FnModel
from zzz_mmd_toon import native_split, mmd_adapter
out = {'plugin_root': plugin_root, 'mmd_tools': getattr(mmd_tools, '__file__', '')}
try:
    root = next(o for o in bpy.data.objects if o.mmd_type == 'ROOT')
    rig = Model(root)
    arm = rig.armature()
    meshes = list(rig.meshes())
    out['meshes'] = [(m.name, len(m.data.materials), len(m.data.loops), m.data.has_custom_normals) for m in meshes]
    mats = mmd_adapter.original_materials(meshes)
    parts, report = native_split.separate(bpy.context, rig, root, arm, meshes, mats, 'repro')
    out['status'] = 'ok'
    out['parts'] = len(parts)
except Exception as e:
    out['status'] = 'fail'
    out['error'] = str(e)
    out['tb'] = traceback.format_exc()[-1500:]
print('REPRO ' + json.dumps(out, ensure_ascii=False))
