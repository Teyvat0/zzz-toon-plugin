"""Machine-specific test configuration, read from environment variables.

ZZZ_MMD_TOOLS_PARENT  directory that contains the `mmd_tools` package
                      (default: the Blender 4.4 user extension repo "blender_org")
ZZZ_GOO_EXE           path of the Goo Engine 4.4.3 executable
                      (default: the running Blender when it reports "Goo")
ZZZ_FIXTURES          JSON file {"kind": ["path/to/model.pmx", "path/to/resource_dir"]}
                      (default: tests/fixtures.json, see tests/fixtures.example.json)
"""
import json
import os
from pathlib import Path


def mmd_parent():
    candidates = []
    if os.environ.get('ZZZ_MMD_TOOLS_PARENT'):
        candidates.append(Path(os.environ['ZZZ_MMD_TOOLS_PARENT']))
    if os.environ.get('APPDATA'):
        candidates.append(Path(os.environ['APPDATA']) / 'Blender Foundation' / 'Blender' / '4.4' / 'extensions' / 'blender_org')
    candidates.append(Path.home() / '.config' / 'blender' / '4.4' / 'extensions' / 'blender_org')
    for path in candidates:
        if (path / 'mmd_tools').is_dir():
            return path
    raise RuntimeError('mmd_tools not found; set ZZZ_MMD_TOOLS_PARENT to the folder containing it. Tried: '
                       + ', '.join(str(c) for c in candidates))


def goo_exe():
    if os.environ.get('ZZZ_GOO_EXE'):
        return Path(os.environ['ZZZ_GOO_EXE'])
    import bpy
    if 'Goo' in bpy.app.version_string:
        return Path(bpy.app.binary_path)
    raise RuntimeError('Goo Engine 4.4.3 required; set ZZZ_GOO_EXE to its blender.exe')


def fixtures():
    path = Path(os.environ.get('ZZZ_FIXTURES') or Path(__file__).resolve().parent / 'fixtures.json')
    if not path.is_file():
        raise RuntimeError('Fixture list missing: ' + str(path) + '. Copy tests/fixtures.example.json to tests/fixtures.json '
                           'and fill in your own PMX and resource folders, or set ZZZ_FIXTURES.')
    return {k: (v[0], v[1]) for k, v in json.loads(path.read_text(encoding='utf-8')).items()}
