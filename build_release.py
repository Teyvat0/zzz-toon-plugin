"""Build a unique local package from a closed runtime allow-list.

No models/game files/MMD Tools/obsolete backends. Integrity-only manifest is not a
regression certificate. Existing packages and manifests are never overwritten.
"""
import argparse
import ast
import hashlib
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'zzz_mmd_toon'
DIST = ROOT / 'dist'


def _source_version():
    # Single source of truth: bl_info['version'] in zzz_mmd_toon/__init__.py.
    tree = ast.parse((SOURCE / '__init__.py').read_text(encoding='utf-8'))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'bl_info' for t in node.targets):
            return tuple(ast.literal_eval(node.value)['version'])
    raise RuntimeError('bl_info missing in zzz_mmd_toon/__init__.py')


VERSION = _source_version()
MODULES = ('__init__', 'application', 'auto_mapping', 'compat', 'dependencies', 'game_bridge', 'light_head', 'lighting',
           'materials', 'mmd_adapter', 'normal_audit', 'native_split', 'outline_geometry', 'renderer',
           'renderer_rim', 'renderer_scene', 'resources', 'toon_build', 'toon_core', 'toon_lib', 'toon_maps', 'toon_outline',
           'toon_surface', 'transaction', 'ui', 'ui_text', 'user_mapping', 'validation', 'workflow')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def checked_sources():
    paths = [SOURCE / (m + '.py') for m in MODULES]
    paths += [SOURCE / 'README.md', SOURCE / 'LICENSE']
    for path in paths:
        if not path.is_file():
            raise RuntimeError('Required release input missing: ' + str(path))
    trees = {}
    for path in paths:
        if path.suffix != '.py':
            continue
        text = path.read_text(encoding='utf-8')
        tree = ast.parse(text, filename=str(path))
        compile(tree, str(path), 'exec')
        trees[path.stem] = tree
        if re.search(r'[A-Z]:[\\/]', text):
            raise RuntimeError('Machine path in runtime ' + str(path))
        if any(name in text for name in ('MAT_Remielle', 'MAT_Zhenzhen', 'MAT_Evelyn', 'MAT_Astra', 'MAT_Velina',
                                          'REMIELLE_PROFILE', 'YE_SHUNGUANG_PROFILE')):
            raise RuntimeError('Character table in runtime ' + str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [n.name for n in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ''] + [n.name for n in node.names]
                if node.level:
                    local = ([node.module.split('.')[0]] if node.module else [n.name for n in node.names])
                    if node.level != 1 or any(n not in MODULES for n in local):
                        raise RuntimeError('Runtime allow-list is not closed: ' + str(path) + ' / ' + str(local))
            else:
                continue
            if any(n.split('.')[0] in ('profiles', 'generic_materials') for n in names):
                raise RuntimeError('Obsolete runtime import in ' + str(path))
    def assignment(tree, key):
        values = [ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == key for t in n.targets)]
        if len(values) != 1:
            raise RuntimeError('Missing/ambiguous version: ' + key)
        return values[0]
    if assignment(trees['__init__'], 'bl_info')['version'] != VERSION or assignment(trees['workflow'], 'VERSION') != '.'.join(map(str, VERSION)):
        raise RuntimeError('Release version disagrees with runtime')
    policy = assignment(trees['game_bridge'], 'RENDER_POLICY')
    if policy != 'mmd-game.v2-native-cull-transparent-eye-shadow':
        raise RuntimeError('Unexpected renderer policy: ' + str(policy))
    return paths, assignment(trees['validation'], 'MESH_GUARD_SCHEMA'), policy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label', default=datetime.now().strftime('%Y%m%d_%H%M%S_%f'), help='Unique build label, never overwrite')
    parser.add_argument('--check', action='store_true', help='Validate inputs without creating a package')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.label):
        parser.error('label must contain only ASCII letters/digits/underscore/dash')
    paths, schema, render_policy = checked_sources()
    if args.check:
        print(json.dumps({'status': 'pass_build_preflight', 'modules': len(MODULES), 'mesh_guard_schema': schema,
                          'render_policy': render_policy}))
        return
    DIST.mkdir(parents=True, exist_ok=True)
    basename = '仿ZZZ渲染_MMD_v%s_通用原生分材质_' % '.'.join(map(str, VERSION)) + args.label
    zip_path, manifest = DIST / (basename + '.zip'), DIST / (basename + '.manifest.json')
    if zip_path.exists() or manifest.exists():
        raise RuntimeError('Refuse to overwrite release artifact or manifest: ' + basename)
    frozen = {path: path.read_bytes() for path in paths}
    with zipfile.ZipFile(zip_path, 'x', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path, content in frozen.items():
            archive.writestr('zzz_mmd_toon/' + path.relative_to(SOURCE).as_posix(), content)
    with zipfile.ZipFile(zip_path) as archive:
        if len(archive.namelist()) != len(paths):
            raise RuntimeError('Unexpected ZIP entry count')
        for path, content in frozen.items():
            entry = 'zzz_mmd_toon/' + path.relative_to(SOURCE).as_posix()
            if archive.read(entry) != content or path.read_bytes() != content:
                raise RuntimeError('Source changed during build or ZIP readback differs: ' + str(path))
    record = {
        'schema': 'zzz-mmd-universal-release.v021', 'built_at': datetime.now(timezone.utc).isoformat(),
        'version': '.'.join(map(str, VERSION)), 'mesh_guard_schema': schema, 'render_policy': render_policy,
        'artifact': {'path': str(zip_path), 'bytes': zip_path.stat().st_size, 'sha256': sha(zip_path),
                     'md5': hashlib.md5(zip_path.read_bytes()).hexdigest()},
        'files': [{'path': str(p), 'entry': 'zzz_mmd_toon/' + p.relative_to(SOURCE).as_posix(),
                   'bytes': len(frozen[p]), 'sha256': hashlib.sha256(frozen[p]).hexdigest()} for p in paths],
        'runtime_modules': list(MODULES), 'character_assets_in_zip': False,
        'character_profile_module_in_zip': False, 'no_json_backend_in_zip': False,
        'validation': 'build integrity only; actual installation/render/guard/motion regressions require separate evidence',
        'distribution': 'Scene, shaders, outline and compositor are generated by code; no .blend asset is bundled',
    }
    with manifest.open('x', encoding='utf-8') as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
    print(json.dumps({'zip': str(zip_path), 'manifest': str(manifest), 'bytes': zip_path.stat().st_size,
                      'sha256': sha(zip_path), 'entries': len(paths)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
