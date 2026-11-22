"""MMD Tools compatibility helpers. No bpy import, so unit tests can run them anywhere."""
import re
from pathlib import Path

# Operator properties of mmd_tools.separate_by_materials we must force, if the installed
# version exposes them. keep_normals (MMD Tools >= 4.5, default True) re-encodes the
# authored INT16 custom_normal bytes, so Blender's own copy must be used instead.
FORCED_SEPARATE_OPTIONS = {'clean_shape_keys': False, 'keep_normals': False}
REQUIRED_SEPARATE_OPTIONS = {'clean_shape_keys'}


def parse_version(text):
    """'4.5.14' -> (4, 5, 14); anything unparsable -> ()."""
    nums = re.findall(r'\d+', str(text or ''))
    return tuple(int(n) for n in nums[:3]) if nums else ()


def mmd_tools_version(module):
    """Version string of an imported mmd_tools package, or 'unknown'."""
    path = getattr(module, '__file__', None)
    if path:
        manifest = Path(path).resolve().parent / 'blender_manifest.toml'
        try:
            for line in manifest.read_text(encoding='utf-8').splitlines():
                match = re.match(r'\s*version\s*=\s*"([^"]+)"', line)
                if match:
                    return match.group(1)
        except OSError:
            pass
    info = getattr(module, 'bl_info', None)
    if isinstance(info, dict) and info.get('version'):
        return '.'.join(str(v) for v in info['version'])
    return 'unknown'


def separate_kwargs(property_names):
    """Operator kwargs to pass, given the property names the installed operator exposes.

    Raises RuntimeError when a property we rely on is missing, so the user is told
    before the scene is touched instead of after a failed equivalence check.
    """
    names = set(property_names)
    missing = REQUIRED_SEPARATE_OPTIONS - names
    if missing:
        raise RuntimeError('已安装的 MMD Tools 的“按材质分离”缺少参数 %s，插件无法保证不改动作者数据'
                           % ', '.join(sorted(missing)))
    return {k: v for k, v in FORCED_SEPARATE_OPTIONS.items() if k in names}


def environment_hint(version):
    """Appended to an equivalence failure raised after MMD Tools' operator already ran."""
    return ('\n已调用 MMD Tools %s 的原生分离。若你没有手动改过这个模型，更可能是该版本的行为与本插件不兼容，'
            '而不是模型有问题；请把这段提示连同 MMD Tools 版本发给作者。' % version)
