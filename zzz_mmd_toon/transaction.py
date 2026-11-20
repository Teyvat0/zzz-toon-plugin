"""File-level rollback. Never pretend split topology can be object-reverted."""
import json
import re
import uuid
from datetime import datetime
from pathlib import Path
import bpy
from .validation import artifact


def new_run(output_dir):
    if not str(output_dir or '').strip():
        # Output is optional, unlike the required game-resource directory.
        # Use a unique run below the project or user temp without overwriting.
        if bpy.data.filepath:
            root = Path(bpy.data.filepath).resolve().parent / '仿ZZZ渲染输出'
        else:
            root = Path(bpy.app.tempdir or __import__('tempfile').gettempdir()) / '仿ZZZ渲染输出'
    else:
        root = Path(bpy.path.abspath(output_dir)).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    owner = uuid.uuid4().hex
    path = root / ('仿ZZZ渲染_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + owner[:8])
    path.mkdir(exist_ok=False)
    return owner, path


def material_save_state():
    """Read-only check BEFORE any save_pre handler can rewrite native identities.

    MMD Tools saves compatibility fields globally, not just on the selected root.
    Reject ambiguous/legacy states instead of silently fixing a would-be backup.
    Runtime Morph offsets/values are deliberately not part of this snapshot.
    """
    materials=[]; seen={}
    for material in bpy.data.materials:
        if not hasattr(material,'mmd_material'):continue
        numeric=int(material.mmd_material.material_id)
        if numeric>=0:
            if numeric in seen:
                raise RuntimeError('保存前检查失败：重复原生Material ID %d (%s / %s)；请在独立文件中处理，未写回退点。' % (numeric,seen[numeric],material.name))
            seen[numeric]=material.name
        materials.append((material.as_pointer(),material.name,numeric))
    targets=[]
    for root in bpy.data.objects:
        if getattr(root,'mmd_type',None)!='ROOT':continue
        for mi,morph in enumerate(root.mmd_root.material_morphs):
            for oi,offset in enumerate(morph.data):
                material=offset.material_data; numeric=int(offset.material_id)
                if material is None and numeric!=-1:
                    raise RuntimeError('保存前检查失败：旧式材质Morph只有数值ID、没有Material指针 (%s/%s/%d)；请先在独立文件原生迁移并验证。' % (root.name,morph.name,oi))
                if material is not None and numeric!=int(material.mmd_material.material_id):
                    raise RuntimeError('保存前检查失败：材质Morph指针与数值ID不一致 (%s/%s/%d)；不会自动重定向。' % (root.name,morph.name,oi))
                targets.append((root.as_pointer(),mi,morph.name,oi,material.as_pointer() if material else 0,numeric,
                                offset.related_mesh_data.as_pointer() if offset.related_mesh_data else 0))
    return (tuple(materials),tuple(targets))


def verify_material_save_state(before, path=None):
    reason=None
    try:
        if material_save_state()!=before:reason='before/after Material or Morph identities differ'
    except RuntimeError as exc:
        reason=str(exc)
    if reason is not None:
        # A callback runs inside Blender's save operation: the file may already
        # exist. Preserve it for diagnosis, label it explicitly INVALID, and never
        # return its artifact as a trusted checkpoint/configuration.
        if path is not None and Path(path).is_file():
            write_json(str(path)+'.INVALID_SAVE.json',{'status':'invalid_save_do_not_use',
                'reason':reason,'artifact':artifact(path),'trusted_checkpoint':False})
        raise RuntimeError('保存回调意外改变原生材质/Morph身份；此文件不能声称是原样回退点，请停止并使用此前可信工程。 '+reason)


def checkpoint(path, label='before_prepare'):
    path = Path(path).resolve()
    if path.exists():
        raise RuntimeError('拒绝覆盖已有回退点: ' + str(path))
    before = material_save_state()
    result = bpy.ops.wm.save_as_mainfile(filepath=str(path), copy=True, check_existing=False, compress=True)
    verify_material_save_state(before, path)
    if result != {'FINISHED'} or not path.is_file():
        raise RuntimeError('无法写入文件级回退点，未开始修改')
    record = artifact(path)
    record['label'] = label
    return record


def write_json(path, value):
    path = Path(path)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def restore(path):
    path = Path(bpy.path.abspath(path)).resolve()
    if not path.is_file() or path.suffix.lower() != '.blend':
        raise RuntimeError('文件回退点不存在')
    return bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=True, use_scripts=False)
