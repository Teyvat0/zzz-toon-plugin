"""TEST ONLY: actual ZIP installation and the required-resource sidebar workflow.

Parent-run only; this module does not spawn Blender or build a ZIP. Example::

    # Start a fresh Goo 4.4 --background --factory-startup process with
    # BLENDER_USER_SCRIPTS=<addon-root>/test_outputs/installed/evelyn/<unique>/user_scripts
    # pointing at a newly created empty directory, then pass:
    --python-exit-code 1 --python THIS_FILE -- ABSOLUTE_ADDON.zip evelyn

The other fixture label is ``astra``. Optional --samples/--resolution default to
16/480. PMX/resource paths come ONLY from the literal INPUTS test declaration in
blender_universal.py; that script is parsed, never executed/imported. A fixture
label is not a character profile or an addon admission rule. No latest.json or
previously configured artifact is required, imported, or overwritten.

All installation, reports, checkpoints, saved projects and renders stay in the
unique user_scripts parent. Existing reports are not overwritten. The addon is
installed/enabled with preferences operators, never loaded from its source tree.
Native MMD Tools remains an independently installed test prerequisite. The test
imports PMX through its normal user-side API; installed addon 0.2.1 must then run
mmd_tools.separate_by_materials(clean_shape_keys=False) BEFORE shading, prove exact
original-index provenance, and save the distinct 01 pre-shading checkpoint. New
Object/Mesh IDs are expected: only the post-split authored mesh is a strict guard
baseline. Original Material IDs, the rig and native Morph/physics data remain.
No preferences are saved, no original project is opened/saved, and bytecode writes
are disabled.

A successful Python compile is NOT a Blender/install/render result. Actual GUI
layout interaction, a cold second process, physics/motion, arbitrary characters
and visual equivalence with the original game are outside this test's claims.
"""

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import traceback
import zipfile

# Do this before importing addon/dependency modules, including addon_utils.
sys.dont_write_bytecode = True

import bpy


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'zzz_mmd_toon'
FIXTURES = ROOT / 'tests' / 'blender' / 'blender_universal.py'
PACKAGE = 'zzz_mmd_toon'
KINDS = ('evelyn', 'astra')
DATA_COLLECTIONS = ('scenes', 'objects', 'meshes', 'armatures', 'materials',
                    'node_groups', 'images', 'collections', 'cameras', 'lights',
                    'worlds', 'actions', 'shape_keys', 'textures', 'texts')
LIMITS = [
    'Same sidebar RNA properties and run operator in headless Goo 4.4; not visual panel/draw/UI automation.',
    'Actual save/open_mainfile/repeat in one process, not a cold second-process reopen.',
    'Only the selected test fixture is exercised; no character profiles, fixed material/bone counts or universal compatibility claim.',
    'Native MMD Tools is an external test prerequisite, not bundled or installed by this ZIP.',
    'Real PNG existence/format/size is tested, not a pixel-baseline/game-equivalence comparison.',
    'Native separation uses exact original-index provenance, not old Object/Mesh identity, decoded normal caches or a pixel-equivalence claim.',
    'Original Material datablocks/preexisting numeric IDs and native Morph catalogs/offsets are preserved; negative IDs may only be assigned by the recorded native lazy-ID API.',
    'Native imported physics are retained; physics building, baking, VMD and full animated Morph equivalence are separate tests.',
]


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def check(report, name, condition, detail=None):
    row = {'name': name, 'pass': bool(condition)}
    if detail is not None:
        row['detail'] = detail
    report['checks'].append(row)
    require(condition, '%s: %s' % (name, detail))


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            digest.update(block)
    return digest.hexdigest()


def digest(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'), allow_nan=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def inside(path, directory):
    return Path(path).resolve().is_relative_to(Path(directory).resolve())


def write_new_json(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def arguments():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('zip_path', type=Path, help='Existing absolute addon ZIP; never created/modified here')
    parser.add_argument('kind', choices=KINDS, help='Test fixture only, never passed as a runtime profile')
    parser.add_argument('--samples', type=int, default=16)
    parser.add_argument('--resolution', type=int, default=480)
    args = parser.parse_args(argv)
    require(args.zip_path.is_absolute(), 'ZIP parameter must be an absolute path')
    args.zip_path = args.zip_path.resolve(strict=True)
    require(args.zip_path.is_file() and args.zip_path.suffix.casefold() == '.zip', 'Expected an existing ZIP file')
    require(1 <= args.samples <= 1024 and 128 <= args.resolution <= 4096,
            'Samples/resolution are outside the current sidebar API limits')
    return args


def isolated_output(kind):
    raw = os.environ.get('BLENDER_USER_SCRIPTS', '')
    require(bool(raw.strip()), 'Parent must supply BLENDER_USER_SCRIPTS before starting Blender')
    scripts = Path(raw).expanduser()
    require(scripts.is_absolute(), 'BLENDER_USER_SCRIPTS must be absolute')
    scripts = scripts.resolve(strict=True)
    require(scripts.is_dir() and scripts.name == 'user_scripts', 'Expected an existing user_scripts directory')
    base = (ROOT / 'test_outputs' / 'installed' / kind).resolve()
    require(inside(scripts, base), 'Isolated scripts must be below test_outputs/installed/' + kind)
    relative = scripts.relative_to(base)
    require(len(relative.parts) == 2 and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', relative.parts[0]),
            'Required layout: test_outputs/installed/<kind>/<unique>/user_scripts')
    require(relative.parts[0] not in {'.', '..', 'latest', 'latest.json'}, 'Use a new unique run label')
    # Blender may have created empty directory scaffolding, but no previous files
    # or links are accepted. In particular this cannot silently reuse an install.
    require(not any(p.is_file() or p.is_symlink() for p in scripts.rglob('*')),
            'user_scripts is not fresh: it already contains files or links')
    output = scripts.parent
    require(not inside(SOURCE, output) and not inside(output, SOURCE), 'Test output must not be the source package')
    require(not (output / 'install_validation.json').exists(), 'Refusing to replace an existing installation report')
    # Exclusive claim distinguishes our run even if a previous process died early.
    with (output / '.zip_install_claim').open('x', encoding='utf-8') as stream:
        stream.write(datetime.now(timezone.utc).isoformat() + '\n')
    return output, scripts


def snapshot(path, *, python_only=False):
    path = Path(path)
    if path.is_file():
        return {path.name: sha256(path)}
    require(path.is_dir(), 'Protected path disappeared: ' + str(path))
    files = []
    for child in path.rglob('*'):
        if child.is_file() and '__pycache__' not in child.relative_to(path).parts:
            if not python_only or child.suffix.casefold() == '.py':
                files.append(child)
    return {child.relative_to(path).as_posix(): sha256(child) for child in sorted(files)}


def protect(report, protected, name, path, *, python_only=False):
    path = Path(path).resolve(strict=True)
    before = snapshot(path, python_only=python_only)
    require(bool(before), 'Protected input has no files: ' + str(path))
    protected[name] = (path, python_only, before)
    report['protected_inputs'][name] = {'path': str(path), 'files': len(before), 'sha256': digest(before)}


def verify_protected(report, protected):
    # Run even when installation/rendering fails; a failed test must not conceal
    # damage to a source/model/ZIP or a preferences file. Never alter these inputs.
    for name, (path, python_only, before) in protected.items():
        try:
            after = snapshot(path, python_only=python_only)
            changed = sorted(key for key in set(before) | set(after) if before.get(key) != after.get(key))
            detail = {'path': str(path), 'before_sha256': digest(before),
                      'after_sha256': digest(after), 'changed_files': changed}
            passed = not changed
        except Exception:
            detail = {'path': str(path), 'traceback': traceback.format_exc()}
            passed = False
        report['checks'].append({'name': 'protected_' + name + '_unchanged', 'pass': passed, 'detail': detail})
        if not passed:
            report['status'] = 'fail'
            report.setdefault('integrity_errors', []).append(name)


def fixture_paths(kind):
    # Do not import blender_universal.py: it performs registration/import/render
    # at module scope. Only literal test metadata may cross this boundary.
    parsed = ast.parse(FIXTURES.read_text(encoding='utf-8-sig'), filename=str(FIXTURES))
    declarations = [node.value for node in parsed.body if isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == 'INPUTS' for target in node.targets)]
    require(len(declarations) == 1, 'Expected exactly one literal INPUTS declaration in the integration fixture')
    inputs = ast.literal_eval(declarations[0])
    require(isinstance(inputs, dict) and kind in inputs, 'Selected test fixture has no INPUTS entry')
    row = inputs[kind]
    require(isinstance(row, (tuple, list)) and len(row) == 2 and all(isinstance(x, str) for x in row),
            'Fixture must declare exactly (absolute PMX path, resource directory)')
    pmx, resources = (Path(value).expanduser() for value in row)
    require(pmx.is_absolute() and resources.is_absolute(), 'Test fixture paths must be absolute')
    pmx, resources = pmx.resolve(strict=True), resources.resolve(strict=True)
    require(pmx.is_file() and pmx.suffix.casefold() == '.pmx' and resources.is_dir(), 'Missing PMX/resource fixture')
    return pmx, resources


def zip_manifest(report, archive):
    expected, seen = {}, set()
    forbidden_assets = {'.pmx', '.pmd', '.vmd', '.vpd', '.json', '.png', '.jpg', '.jpeg', '.tga', '.dds', '.exr', '.hdr'}
    with zipfile.ZipFile(archive) as stream:
        for item in stream.infolist():
            raw = item.filename
            require('\\' not in raw, 'ZIP entries must use portable forward slashes: ' + raw)
            path = PurePosixPath(raw)
            require(not path.is_absolute() and '..' not in path.parts and path.parts and path.parts[0] == PACKAGE,
                    'Unexpected/unsafe ZIP entry: ' + raw)
            require(not item.flag_bits & 1, 'Encrypted ZIP entries are not supported: ' + raw)
            if item.is_dir():
                continue
            require(len(path.parts) > 1, 'Package root is not a directory: ' + raw)
            rel = PurePosixPath(*path.parts[1:]).as_posix()
            require(rel.casefold() not in seen, 'Duplicate/case-colliding ZIP file: ' + raw)
            seen.add(rel.casefold())
            require('__pycache__' not in path.parts and path.suffix.casefold() not in {'.pyc', '.pyo', '.blend1'},
                    'ZIP must not contain cache/backup files: ' + raw)
            require(path.stem.casefold() not in {'profiles', 'generic_materials'},
                    'Universal ZIP must not ship profiles/generic_materials: ' + raw)
            require(path.suffix.casefold() not in forbidden_assets, 'Character/model/resource asset found in ZIP: ' + raw)
            require(path.suffix.casefold() != '.blend', 'No .blend asset is allowed; scene/shaders are code-built: ' + raw)
            payload = stream.read(item)  # Reading also verifies the ZIP entry CRC.
            value = hashlib.sha256(payload).hexdigest()
            source = SOURCE / Path(rel)
            require(source.is_file() and sha256(source) == value, 'ZIP bytes differ from current source: ' + raw)
            expected[rel] = value
    required = {'__init__.py', 'ui.py', 'workflow.py', 'renderer.py', 'renderer_scene.py', 'renderer_rim.py', 'light_head.py', 'mmd_adapter.py', 'native_split.py', 'validation.py', 'user_mapping.py',
                'resources.py', 'auto_mapping.py', 'materials.py', 'game_bridge.py', 'outline_geometry.py',
                'application.py', 'dependencies.py', 'transaction.py'}
    check(report, 'zip_required_universal_files_present', required.issubset(expected), sorted(required - set(expected)))
    check(report, 'zip_current_source_sha256_match', bool(expected), {'files': len(expected), 'manifest_sha256': digest(expected)})
    report['zip_entries'] = expected
    return expected


def module_origins(report, installed, expected, label):
    origins = {}
    for name, module in list(sys.modules.items()):
        if name != PACKAGE and not name.startswith(PACKAGE + '.'):
            continue
        file_path = getattr(module, '__file__', None)
        require(file_path, 'Addon module has no verifiable file origin: ' + name)
        path = Path(file_path).resolve(strict=True)
        require(inside(path, installed) and not inside(path, SOURCE), 'Addon module came from outside the isolated install: ' + str(path))
        rel = path.relative_to(installed).as_posix()
        require(rel in expected and sha256(path) == expected[rel], 'Imported module does not match ZIP bytes: ' + name)
        origins[name] = str(path)
    require(PACKAGE in origins and PACKAGE + '.workflow' in origins, 'Expected installed runtime modules were not imported')
    require(PACKAGE + '.profiles' not in origins and PACKAGE + '.generic_materials' not in origins,
            'A profiles/generic fallback module was loaded unexpectedly')
    report.setdefault('module_origins', {})[label] = origins
    check(report, label + '_runtime_only_from_verified_install', True, {'modules': len(origins)})


def counts():
    return {name: len(getattr(bpy.data, name)) for name in DATA_COLLECTIONS}


def morph_catalog(root):
    return {name: [row.name for row in getattr(root.mmd_root, name)]
            for name in ('vertex_morphs', 'material_morphs', 'bone_morphs', 'uv_morphs', 'group_morphs')}


def native_inventory(rig):
    return {'rigids': sorted(ob.name for ob in rig.rigidBodies()), 'joints': sorted(ob.name for ob in rig.joints())}


def native_pointer_inventory(rig):
    return {name: sorted((ob.name, ob.as_pointer()) for ob in objects)
            for name, objects in (('rigids', rig.rigidBodies()), ('joints', rig.joints()))}


def material_id_state(materials):
    return [{'name': mat.name, 'native_id': int(mat.mmd_material.material_id)} for mat in materials]


def morph_state(root):
    # Preserve catalogs AND offsets/target identities, not counts alone. Only
    # related_mesh_data is deliberately omitted: native split must migrate that
    # obsolete Mesh pointer to the corresponding new part (checked separately).
    fields = {
        'vertex_morphs': (),
        'material_morphs': ('material_id', 'offset_type', 'diffuse_color', 'specular_color',
                            'shininess', 'ambient_color', 'edge_color', 'edge_weight',
                            'texture_factor', 'sphere_texture_factor', 'toon_texture_factor'),
        'bone_morphs': ('bone', 'bone_id', 'location', 'rotation'),
        'uv_morphs': ('index', 'offset'),
        'group_morphs': ('name', 'morph_type', 'factor'),
    }

    def value(item):
        return item if isinstance(item, (str, int, float, bool)) or item is None else list(item)

    result = {}
    for name, offset_fields in fields.items():
        rows = []
        for morph in getattr(root.mmd_root, name):
            row = {key: value(getattr(morph, key)) for key in ('name', 'name_e', 'category')}
            if name == 'uv_morphs':
                row.update({key: value(getattr(morph, key))
                            for key in ('uv_index', 'data_type', 'vertex_group_scale')})
            if hasattr(morph, 'data'):
                row['data'] = []
                for offset in morph.data:
                    item = {key: value(getattr(offset, key)) for key in offset_fields}
                    if name == 'material_morphs':
                        item['material'] = offset.material_data.name if offset.material_data else None
                    row['data'].append(item)
            rows.append(row)
        result[name] = rows
    return result


def check_morph_migration(report, root, parts, materials, prep, label):
    targets, valid = [], True
    for morph in root.mmd_root.material_morphs:
        for offset in morph.data:
            material = offset.material_data
            numeric = int(offset.material_id)
            related = offset.related_mesh_data
            if material is None and numeric < 0:
                matched = related is None  # Native all-material target is not mesh-specific.
            else:
                candidates = [mat for mat in materials if int(mat.mmd_material.material_id) == numeric]
                target = material if material is not None else (candidates[0] if len(candidates) == 1 else None)
                matched = target is not None and any(ob.data == related
                    and target in ob.data.materials.values() for ob in parts.values())
            valid = valid and matched
            targets.append({'morph': morph.name, 'material': material.name if material else None,
                            'native_id': numeric, 'related_mesh': related.name if related else None,
                            'matches_split_part': matched})
    migrations = prep.get('material_morph_migrations', [])
    check(report, label + '_native_material_morph_targets_migrated_to_exact_parts',
          valid and len(migrations) == len(targets), {'targets': targets, 'migrations': migrations})


def check_strict_baseline(report, workflow, validation, root, data, label):
    # _existing is read-only and validates authored mesh, shader, native Morph
    # targets and the whole render scene against the NEW post-split baseline.
    before = counts()
    state, parts, _, arm = workflow._existing(bpy.context, root, data['resource_dir'], data['outline_scale'])
    check(report, label + '_post_split_strict_guard',
          state == data and data['version'] == workflow.VERSION == '0.2.1'
          and data['mesh_guard_schema'] == validation.MESH_GUARD_SCHEMA
          and validation.mesh_state(parts) == data['mesh']
          and validation.skeleton(arm) == data['skeleton']
          and validation.shader_state(parts) == data['shader']
          and validation.digest(validation.material_targets(root)) == data['material_targets']
          and counts() == before,
          {'parts': len(parts), 'schema': data['mesh_guard_schema'], 'mesh': data['mesh']})
    check(report, label + '_every_part_uses_original_material', all(
        'zzz_source_slot' in ob and len({p.material_index for p in ob.data.polygons}) == 1
        and all(int(mat.get('zzz_source_slot', -1)) == int(ob['zzz_source_slot']) for mat in ob.data.materials)
        for ob in parts.values()))
    return parts


def enable_native_mmd(report, protected, adapter):
    # This dependency is not the addon under test. Discover already installed
    # native MMD Tools without writing/adding a model-specific source path.
    try:
        module, model = adapter.native()
    except RuntimeError:
        candidates = []
        for value in bpy.utils.script_paths():
            candidates.extend((Path(value) / 'addons', Path(value) / 'addons_core'))
        config = bpy.utils.user_resource('CONFIG')
        if config:
            extension_root = Path(config).resolve().parent / 'extensions'
            if extension_root.is_dir():
                candidates.extend(sorted(path for path in extension_root.iterdir() if path.is_dir()))
        for value in ('BLENDER_SYSTEM_EXTENSIONS', 'BLENDER_USER_EXTENSIONS'):
            raw = os.environ.get(value, '')
            if raw and Path(raw).is_dir():
                candidates.extend(path for path in Path(raw).iterdir() if path.is_dir())
        native_paths = sorted({(path / 'mmd_tools').resolve() for path in candidates
                               if (path / 'mmd_tools' / '__init__.py').is_file()})
        require(len(native_paths) == 1, 'Need exactly one installed native MMD Tools; discovered: ' + str(native_paths))
        protect(report, protected, 'mmd_tools_python', native_paths[0], python_only=True)
        sys.path.insert(0, str(native_paths[0].parent))
        module = importlib.import_module('mmd_tools')
        require(Path(module.__file__).resolve().parent == native_paths[0], 'Unexpected MMD Tools module origin')
        if not hasattr(bpy.types.PoseBone, 'mmd_bone'):
            module.register()
        module, model = adapter.native()
    else:
        protect(report, protected, 'mmd_tools_python', Path(module.__file__).resolve().parent, python_only=True)
    report['mmd_tools'] = {'module': module.__name__, 'path': str(Path(module.__file__).resolve()),
                           'version': list(getattr(module, 'bl_info', {}).get('version', ()))}
    check(report, 'native_mmd_tools_registered', hasattr(bpy.types.PoseBone, 'mmd_bone'))
    return module, model


def model_in_active_scene(adapter):
    roots = [ob for ob in bpy.context.scene.objects if 'zzz_run' in ob and getattr(ob, 'mmd_type', None) == 'ROOT']
    require(len(roots) == 1, 'Expected exactly one configured MMD root in the active render scene')
    adapter.select_root(bpy.context, roots[0])
    return adapter.selected(bpy.context)


def default_bundle(report, addon, renderer, ui, installed, expected, label):
    pref = bpy.context.preferences.addons[PACKAGE].preferences
    check(report, label + '_no_external_template_prefs', not hasattr(pref, 'use_external_template')
          and not hasattr(pref, 'template_path'))
    check(report, label + '_no_bundled_blend_asset', not (installed / 'assets').exists()
          and not any(key.endswith('.blend') for key in expected))
    check(report, label + '_renderer_code_built', callable(renderer.build) and callable(renderer.preflight))
    check(report, label + '_registered_sidebar', hasattr(bpy.types.Scene, 'zzz_toon')
          and all(cls.is_registered for cls in ui.CLASSES))
    require(Path(addon.__file__).resolve() == installed / '__init__.py', 'Enabled addon origin changed')


def sidebar_state(report, workflow, resources, output, args, material_count, label):
    settings = bpy.context.scene.zzz_toon
    detail = {'resource_dir': settings.resource_dir, 'output_dir': settings.output_dir,
              'samples': settings.samples, 'resolution': settings.resolution, 'rows': len(settings.rows)}
    check(report, label + '_sidebar_paths_settings_and_rows',
          workflow._resource_path(settings.resource_dir) == workflow._resource_path(str(resources))
          and Path(bpy.path.abspath(settings.output_dir)).resolve() == output
          and settings.samples == args.samples and settings.resolution == args.resolution
          and len(settings.rows) == material_count
          and all(row.stem and row.backend == 'GAME_JSON' for row in settings.rows), detail)


def png_paths(folder):
    return sorted(folder.glob('仿ZZZ渲染_正面*.png'))


def check_png(report, path, output, label):
    path = Path(path).resolve(strict=True)
    check(report, label + '_real_png', inside(path, output) and path.stat().st_size > 1024
          and path.open('rb').read(8) == b'\x89PNG\r\n\x1a\n', {'path': str(path), 'bytes': path.stat().st_size})
    return path


def run_noop(report, label):
    before = counts()
    result = bpy.ops.zzz_toon.run(render=False)
    check(report, label + '_sidebar_noop_no_duplicate_ids', result == {'FINISHED'} and counts() == before,
          {'result': sorted(result), 'status': bpy.context.scene.zzz_toon.status,
           'before': before, 'after': counts()})
    check(report, label + '_reports_already_configured', 'already_configured_noop' in bpy.context.scene.zzz_toon.status)


def execute(args, output, scripts, report, protected):
    check(report, 'explicit_goo_4_4', bpy.app.version[:2] == (4, 4) and 'Goo' in bpy.app.version_string)
    check(report, 'fresh_background_process', bpy.app.background and not bpy.data.filepath, bpy.data.filepath)
    check(report, 'isolated_scripts_environment_honored',
          Path(bpy.utils.user_resource('SCRIPTS')).resolve() == scripts,
          {'environment': str(scripts), 'blender': bpy.utils.user_resource('SCRIPTS')})
    check(report, 'addon_not_preloaded_or_enabled',
          not any(name == PACKAGE or name.startswith(PACKAGE + '.') for name in sys.modules)
          and PACKAGE not in bpy.context.preferences.addons and not hasattr(bpy.types.Scene, 'zzz_toon'))
    require(hasattr(bpy.context.preferences, 'use_preferences_save'), 'Cannot disable Blender preferences auto-save')
    bpy.context.preferences.use_preferences_save = False
    report['preferences_auto_save_disabled'] = not bpy.context.preferences.use_preferences_save
    # No save_userpref operator is ever called, and the flag stays off at exit.
    protect(report, protected, 'source_addon', SOURCE)
    protect(report, protected, 'test_fixture_declaration', FIXTURES)
    protect(report, protected, 'this_test_script', Path(__file__).resolve())
    protect(report, protected, 'zip_archive', args.zip_path)
    config = bpy.utils.user_resource('CONFIG')
    config_path = Path(config).resolve() / 'userpref.blend' if config else None
    report['user_preferences_file'] = str(config_path) if config_path else None
    prefs_before = sha256(config_path) if config_path and config_path.is_file() else None
    report['user_preferences_sha256_before'] = prefs_before
    pmx, resources = fixture_paths(args.kind)
    report['fixture'] = {'declaration': str(FIXTURES), 'kind': args.kind, 'pmx': str(pmx),
                         'resources': str(resources), 'pmx_sha256': sha256(pmx)}
    protect(report, protected, 'model_folder', pmx.parent)
    protect(report, protected, 'game_resource_folder', resources)
    expected = zip_manifest(report, args.zip_path)
    report['zip_sha256'] = sha256(args.zip_path)

    # Ordinary Blender installer, not source import, path injection or zip extract.
    import addon_utils
    result = bpy.ops.preferences.addon_install(filepath=str(args.zip_path), overwrite=False)
    check(report, 'actual_preferences_addon_install', result == {'FINISHED'}, sorted(result))
    addon_utils.modules_refresh()
    discovered = [module for module in addon_utils.modules() if module.__name__ == PACKAGE]
    check(report, 'installed_zip_discovered_once', len(discovered) == 1, [getattr(m, '__file__', None) for m in discovered])
    installed = Path(discovered[0].__file__).resolve(strict=True).parent
    check(report, 'installed_exact_isolated_addons_path', installed == scripts / 'addons' / PACKAGE, str(installed))
    check(report, 'installed_not_source_checkout', not inside(installed, SOURCE) and inside(installed, scripts), str(installed))
    require(all((installed / name).is_file() and sha256(installed / name) == value for name, value in expected.items()),
            'Installed files do not match every archived file SHA-256')
    installed_files = {p.relative_to(installed).as_posix() for p in installed.rglob('*')
                       if p.is_file() and '__pycache__' not in p.relative_to(installed).parts}
    check(report, 'installed_manifest_exactly_zip', installed_files == set(expected),
          {'missing': sorted(set(expected) - installed_files), 'extra': sorted(installed_files - set(expected))})
    report['installed'] = str(installed)
    result = bpy.ops.preferences.addon_enable(module=PACKAGE)
    check(report, 'actual_preferences_addon_enable', result == {'FINISHED'}, sorted(result))
    addon = importlib.import_module(PACKAGE)
    workflow, validation, adapter, renderer, ui = (importlib.import_module(PACKAGE + '.' + name)
                                                 for name in ('workflow', 'validation', 'mmd_adapter', 'renderer', 'ui'))
    check(report, 'universal_addon_version', tuple(addon.bl_info['version']) == (0, 2, 1)
          and workflow.VERSION == '0.2.1', {'addon': addon.bl_info['version'], 'workflow': workflow.VERSION})
    default_bundle(report, addon, renderer, ui, installed, expected, 'first_enable')
    module_origins(report, installed, expected, 'first_enable')
    enable_native_mmd(report, protected, adapter)

    check(report, 'factory_object_mode', bpy.context.mode == 'OBJECT')
    bpy.ops.object.select_all(action='SELECT')
    check(report, 'clear_disposable_factory_objects', bpy.ops.object.delete(use_global=False) == {'FINISHED'})
    imported = bpy.ops.mmd_tools.import_model(filepath=str(pmx), types={'MESH', 'ARMATURE', 'MORPHS', 'DISPLAY', 'PHYSICS'},
            scale=.08, clean_model=False, remove_doubles=False, rename_bones=False, save_log=False)
    check(report, 'user_native_pmx_import', imported == {'FINISHED'}, sorted(imported))
    _, rig, root, arm, meshes = adapter.selected(bpy.context)
    adapter.select_root(bpy.context, root)
    materials = adapter.original_materials(meshes)
    baseline = {'skeleton': validation.skeleton(arm), 'before_meshes': len(meshes),
                'original_faces': sum(len(ob.data.polygons) for ob in meshes),
                'original_vertices': sum(len(ob.data.vertices) for ob in meshes),
                'rig_ids': {'root': root.as_pointer(), 'armature_object': arm.as_pointer(),
                            'armature_data': arm.data.as_pointer()},
                'material_ids': [mat.as_pointer() for mat in materials],
                'native_material_ids': material_id_state(materials),
                'morph_catalog': morph_catalog(root), 'morph_state': morph_state(root),
                'native_physics': native_inventory(rig), 'native_physics_ids': native_pointer_inventory(rig),
                'physics_built': bool(root.mmd_root.is_built)}
    report['imported_baseline'] = baseline
    before_scan = counts()
    missing = workflow.scan(bpy.context, '')
    check(report, 'resources_required_without_mutation', bool(missing.get('errors')) and counts() == before_scan, missing.get('errors'))
    settings = bpy.context.scene.zzz_toon
    settings.resource_dir, settings.output_dir = str(resources), str(output)
    settings.samples, settings.resolution = args.samples, args.resolution
    check(report, 'first_sidebar_no_manual_scan_or_mapping', len(settings.rows) == 0)
    result = bpy.ops.zzz_toon.run(render=True)
    check(report, 'actual_first_sidebar_configure_and_real_render', result == {'FINISHED'},
          {'result': sorted(result), 'status': bpy.context.scene.zzz_toon.status})
    _, rig, root, arm, meshes = model_in_active_scene(adapter)
    data = json.loads(root['zzz_run'])
    run_output = Path(data['output']).resolve(strict=True)
    check(report, 'all_workflow_outputs_below_unique_run', run_output.parent == output, str(run_output))
    configured = json.loads((run_output / '配置验证报告.json').read_text(encoding='utf-8'))
    check(report, 'first_report_real_configured_render', configured.get('status') == 'pass_configured_rendered', configured.get('status'))
    check(report, 'no_profile_or_fallback_admission',
          configured['profile'] == 'universal-no-character-profile' and missing.get('profile') is None
          and len(data['mapping']) == len(materials)
          and all(row.get('stem') and row.get('backend') == 'GAME_JSON' for row in data['mapping']))
    check(report, 'no_template_fields_recorded', 'template_mode' not in data and 'template_hash' not in data)
    check(report, 'resource_hashes_recorded_before_commit', bool(data['resource_hashes']))
    prep = configured['prepare']
    parts = {int(ob['zzz_slot']): ob for ob in meshes}
    check(report, 'native_material_separation_before_shading',
          prep['operator'] == 'mmd_tools.separate_by_materials' and prep['clean_shape_keys'] is False
          and prep['before_meshes'] == baseline['before_meshes'] and prep['after_meshes'] == len(parts)
          and len(parts) == len(meshes) and all(len({p.material_index for p in ob.data.polygons}) == 1
                                              for ob in meshes),
          {'operator': prep['operator'], 'clean_shape_keys': prep['clean_shape_keys'],
           'before_meshes': prep['before_meshes'], 'after_meshes': prep['after_meshes']})
    check(report, 'exact_original_provenance_uv_weights_shapes_and_authored_attributes',
          prep['semantic_equivalence'] is True and prep['each_original_face_and_corner_once'] is True
          and prep['original_material_ids_preserved'] is True
          and prep['original_faces'] == baseline['original_faces']
          and sum(len(ob.data.polygons) for ob in meshes) == baseline['original_faces']
          and sum(row['faces'] for row in prep['parts']) == baseline['original_faces']
          and len(prep['parts']) == len(parts)
          and all(row['part'] in parts and row['object'] == parts[row['part']].name
                  and row['source_mesh'] in range(baseline['before_meshes'])
                  and row['source_material'] == int(parts[row['part']]['zzz_source_slot'])
                  and row['faces'] == len(parts[row['part']].data.polygons)
                  and row['vertices'] == len(parts[row['part']].data.vertices) for row in prep['parts'])
          and prep['mesh'] == data['mesh'] == validation.mesh_state(parts)
          and prep['skeleton'] == data['skeleton'] == baseline['skeleton'], prep)
    check(report, 'temporary_split_provenance_removed_after_exact_validation', all(
          not any(key.startswith('ZZZSplit_') for key in ob.keys())
          and not any(attribute.name.startswith('ZZZSplit_') for attribute in ob.data.attributes)
          for ob in meshes))
    # Original Mesh/Object IDs may be replaced by native separation; never retain
    # or dereference imported mesh handles here. Material datablocks are not copies.
    check(report, 'original_material_datablocks_preserved',
          [mat.as_pointer() for mat in adapter.original_materials(meshes)] == baseline['material_ids'])
    after_material_ids = material_id_state(materials)
    expected_initializations = [dict(material=old['name'], before=old['native_id'], after=new['native_id'])
        for old, new in zip(baseline['native_material_ids'], after_material_ids)
        if old['native_id'] != new['native_id']]
    check(report, 'preexisting_native_material_ids_unchanged_only_native_lazy_initialization',
          all(old['name'] == new['name'] and (old['native_id'] == new['native_id']
              or old['native_id'] < 0 <= new['native_id'])
              for old, new in zip(baseline['native_material_ids'], after_material_ids))
          and all(row['native_id'] >= 0 for row in after_material_ids)
          and len({row['native_id'] for row in after_material_ids}) == len(materials)
          and configured['native_material_id_initializations'] == expected_initializations,
          {'before': baseline['native_material_ids'], 'after': after_material_ids,
           'native_initializations': configured['native_material_id_initializations']})
    check(report, 'original_rig_ids_rest_hierarchy_and_bones_preserved',
          baseline['rig_ids'] == {'root': root.as_pointer(), 'armature_object': arm.as_pointer(),
                                  'armature_data': arm.data.as_pointer()}
          and validation.skeleton(arm) == baseline['skeleton'])
    check(report, 'native_morph_catalog_offsets_and_imported_physics_preserved',
          morph_catalog(root) == baseline['morph_catalog'] and morph_state(root) == baseline['morph_state']
          and native_inventory(rig) == baseline['native_physics']
          and native_pointer_inventory(rig) == baseline['native_physics_ids']
          and bool(root.mmd_root.is_built) == baseline['physics_built'])
    check_morph_migration(report, root, parts, materials, prep, 'first_click')
    check_strict_baseline(report, workflow, validation, root, data, 'first_click')
    check(report, 'native_shader_and_game_wrapper_retained',
          all(mat.node_tree.nodes.get('mmd_shader') and mat.node_tree.nodes.get('ZZZ_GameEnhancement') for mat in materials))
    sidebar_state(report, workflow, resources, output, args, len(materials), 'first_click')
    artifact = configured['artifact']
    target = Path(artifact['path']).resolve(strict=True)
    check(report, 'new_configuration_saved_inside_unique_output', target.parent == run_output
          and target.name == '仿ZZZ渲染_通用配置.blend' and target.stat().st_size > 1024
          and sha256(target) == artifact['sha256'], artifact)
    checkpoint = Path(configured['checkpoint']['path']).resolve(strict=True)
    check(report, 'new_full_checkpoint_inside_unique_output', checkpoint.parent == run_output
          and checkpoint.name == '00_配置前完整回退.blend' and checkpoint.stat().st_size > 1024
          and sha256(checkpoint) == configured['checkpoint']['sha256'], configured['checkpoint'])
    separated_checkpoint = Path(configured['separated_checkpoint']['path']).resolve(strict=True)
    check(report, 'distinct_01_native_separated_pre_shading_checkpoint',
          separated_checkpoint.parent == run_output and separated_checkpoint not in {checkpoint, target}
          and separated_checkpoint.name == '01_原生分材质_着色前回退.blend'
          and separated_checkpoint.stat().st_size > 1024
          and sha256(separated_checkpoint) == configured['separated_checkpoint']['sha256'],
          configured['separated_checkpoint'])
    first_png = check_png(report, configured['image'], run_output, 'first_click')
    initial_pngs = png_paths(run_output)
    check(report, 'exactly_one_first_render', initial_pngs == [first_png])
    first_png_sha = sha256(first_png)
    protect(report, protected, 'generated_configuration_not_overwritten', target)
    protect(report, protected, 'generated_checkpoint_not_overwritten', checkpoint)
    protect(report, protected, 'generated_01_pre_shading_checkpoint_not_overwritten', separated_checkpoint)
    protect(report, protected, 'first_png_not_overwritten', first_png)
    material_count = len(materials)
    report.update(artifact=artifact, output=str(run_output), mapping=data['mapping'], prepare=prep,
                  native_material_ids=after_material_ids, first_counts=counts(), first_png_sha256=first_png_sha,
                  separated_checkpoint=configured['separated_checkpoint'])
    run_noop(report, 'immediate_repeat')

    # Inspect the actual 01 file, not only its name/report. It must already contain
    # verified material parts/rig/Morph migrations but no renderer/game wrapper.
    result = bpy.ops.wm.open_mainfile(filepath=str(separated_checkpoint), use_scripts=False, load_ui=True)
    check(report, 'actual_01_pre_shading_checkpoint_reopened', result == {'FINISHED'}
          and Path(bpy.data.filepath).resolve() == separated_checkpoint)
    roots = [ob for ob in bpy.context.scene.objects if getattr(ob, 'mmd_type', None) == 'ROOT']
    require(len(roots) == 1, 'Expected the original imported root in the 01 pre-shading checkpoint')
    adapter.select_root(bpy.context, roots[0])
    _, rig, root, arm, meshes = adapter.selected(bpy.context)
    parts = {int(ob['zzz_slot']): ob for ob in meshes}
    materials = adapter.original_materials(meshes)
    # The 01 save precedes application.apply(), which adds Material source-slot
    # metadata. Resolve its order from the native split's Object source markers.
    materials = [next(mat for ob in parts.values() if int(ob['zzz_source_slot']) == slot
                      for mat in ob.data.materials
                      if mat == ob.data.materials[ob.data.polygons[0].material_index])
                 for slot in range(material_count)]
    check(report, '01_contains_exact_split_baseline_before_shading',
          len(parts) == prep['after_meshes'] and validation.mesh_state(parts) == prep['mesh']
          and validation.skeleton(arm) == baseline['skeleton']
          and 'zzz_run' not in root and root.get('zzz_phase') == 'preparing'
          and material_id_state(materials) == after_material_ids
          and all(mat.node_tree.nodes.get('mmd_shader')
                  and not mat.node_tree.nodes.get('ZZZ_GameEnhancement') for mat in materials)
          and not any(name == PACKAGE + '.profiles' for name in sys.modules)
          and not any(mod.type == 'NODES' and mod.node_group and mod.node_group.get('zzz_owner')
                      for ob in meshes for mod in ob.modifiers),
          {'parts': len(parts), 'mesh': validation.mesh_state(parts), 'phase': root.get('zzz_phase')})
    check(report, '01_retains_native_morph_and_physics_data',
          morph_catalog(root) == baseline['morph_catalog'] and morph_state(root) == baseline['morph_state']
          and native_inventory(rig) == baseline['native_physics']
          and bool(root.mmd_root.is_built) == baseline['physics_built'])
    check_morph_migration(report, root, parts, materials, prep, '01_checkpoint')

    result = bpy.ops.wm.open_mainfile(filepath=str(target), use_scripts=False, load_ui=True)
    check(report, 'actual_saved_configuration_reopened', result == {'FINISHED'} and Path(bpy.data.filepath).resolve() == target)
    _, rig, root, arm, meshes = model_in_active_scene(adapter)
    reopened = json.loads(root['zzz_run'])
    materials = adapter.original_materials(meshes)
    check(report, 'reopen_same_owner_and_native_data', reopened['owner'] == data['owner']
          and reopened['mesh'] == prep['mesh'] and validation.skeleton(arm) == baseline['skeleton']
          and material_id_state(materials) == after_material_ids
          and morph_catalog(root) == baseline['morph_catalog'] and morph_state(root) == baseline['morph_state']
          and native_inventory(rig) == baseline['native_physics']
          and bool(root.mmd_root.is_built) == baseline['physics_built'])
    check_strict_baseline(report, workflow, validation, root, reopened, 'reopen')
    default_bundle(report, addon, renderer, ui, installed, expected, 'reopen')
    sidebar_state(report, workflow, resources, output, args, material_count, 'reopen')
    run_noop(report, 'reopen_repeat')
    before = counts()
    result = bpy.ops.zzz_toon.run(render=True)
    check(report, 'reopen_sidebar_real_rerender_no_duplicate_ids', result == {'FINISHED'} and counts() == before,
          {'result': sorted(result), 'before': before, 'after': counts(), 'status': bpy.context.scene.zzz_toon.status})
    rerenders = png_paths(run_output)
    check(report, 'reopen_rerender_new_filename_not_overwrite', len(rerenders) == len(initial_pngs) + 1
          and set(initial_pngs).issubset(rerenders) and sha256(first_png) == first_png_sha, [str(p) for p in rerenders])
    for index, path in enumerate(rerenders):
        check_png(report, path, run_output, 'render_%d' % index)

    before = counts()
    result = bpy.ops.preferences.addon_disable(module=PACKAGE)
    check(report, 'actual_disable_cleans_sidebar_registration', result == {'FINISHED'}
          and not hasattr(bpy.types.Scene, 'zzz_toon') and not any(cls.is_registered for cls in ui.CLASSES)
          and PACKAGE not in bpy.context.preferences.addons)
    check(report, 'disable_does_not_delete_user_or_renderer_ids', counts() == before, {'before': before, 'after': counts()})
    result = bpy.ops.preferences.addon_enable(module=PACKAGE)
    check(report, 'actual_reenable_without_duplicate_ids', result == {'FINISHED'} and counts() == before)
    default_bundle(report, addon, renderer, ui, installed, expected, 'reenable')
    _, rig, root, arm, meshes = model_in_active_scene(adapter)
    check_strict_baseline(report, workflow, validation, root, json.loads(root['zzz_run']), 'reenable')
    sidebar_state(report, workflow, resources, output, args, material_count, 'reenable')
    run_noop(report, 'reenable_repeat')
    check(report, 'one_run_directory_no_repeat_checkpoints_or_projects',
          sorted(path for path in output.glob('仿ZZZ渲染_*') if path.is_dir()) == [run_output]
          and sorted(run_output.glob('*.blend')) == sorted([target, checkpoint, separated_checkpoint]),
          {'runs': [str(p) for p in output.glob('仿ZZZ渲染_*') if p.is_dir()],
           'blends': [str(p) for p in run_output.glob('*.blend')]})
    module_origins(report, installed, expected, 'after_reopen_reenable')
    check(report, 'preferences_not_saved_and_autosave_still_off',
          not bpy.context.preferences.use_preferences_save
          and (sha256(config_path) if config_path and config_path.is_file() else None) == prefs_before)
    report.update(status='pass_isolated_zip_native_pmx_sidebar_first_repeat_reopen_reenable',
                  renders=[str(path) for path in rerenders], final_counts=counts(),
                  configured_report=str(run_output / '配置验证报告.json'))


def main():
    args = arguments()
    output, scripts = isolated_output(args.kind)
    report = {'status': 'running', 'kind': args.kind, 'checks': [], 'protected_inputs': {},
              'reader': bpy.app.version_string, 'reader_version': list(bpy.app.version),
              'test': str(Path(__file__).resolve()), 'isolated_scripts': str(scripts),
              'unique_output': str(output), 'zip': str(args.zip_path),
              'started_utc': datetime.now(timezone.utc).isoformat(), 'limits': LIMITS}
    protected = {}
    failure = None
    try:
        execute(args, output, scripts, report, protected)
    except Exception as exc:
        failure = exc
        report.update(status='fail', error=str(exc), traceback=traceback.format_exc())
    finally:
        verify_protected(report, protected)
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        path = output / 'install_validation.json'
        write_new_json(path, report)
        print('HEADLESS ' + json.dumps({'status': report['status'], 'kind': args.kind,
              'checks': len(report['checks']), 'error': report.get('error'),
              'integrity_errors': report.get('integrity_errors', []), 'report': str(path)}, ensure_ascii=False), flush=True)
    if report['status'] == 'fail':
        raise RuntimeError('ZIP install workflow failed; see ' + str(output / 'install_validation.json')) from failure


if __name__ == '__main__':
    main()
