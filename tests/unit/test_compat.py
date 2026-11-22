import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'zzz_mmd_toon'))
import compat  # noqa: E402  (bpy-free module, imported directly)


class SeparateKwargsTests(unittest.TestCase):
    def test_forces_keep_normals_off_when_exposed(self):
        kwargs = compat.separate_kwargs({'clean_shape_keys', 'keep_normals', 'something_else'})
        self.assertEqual(kwargs, {'clean_shape_keys': False, 'keep_normals': False})

    def test_old_version_without_keep_normals(self):
        self.assertEqual(compat.separate_kwargs(['clean_shape_keys']), {'clean_shape_keys': False})

    def test_missing_required_option_fails_before_scene_is_touched(self):
        with self.assertRaises(RuntimeError) as ctx:
            compat.separate_kwargs(['keep_normals'])
        self.assertIn('clean_shape_keys', str(ctx.exception))


class VersionTests(unittest.TestCase):
    def test_parse_version(self):
        self.assertEqual(compat.parse_version('4.5.14'), (4, 5, 14))
        self.assertEqual(compat.parse_version('v4.2'), (4, 2))
        self.assertEqual(compat.parse_version(None), ())

    def test_reads_extension_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'blender_manifest.toml').write_text('id = "mmd_tools"\nversion = "4.5.14"\n', encoding='utf-8')
            module = types.SimpleNamespace(__file__=str(Path(tmp) / '__init__.py'))
            self.assertEqual(compat.mmd_tools_version(module), '4.5.14')

    def test_falls_back_to_bl_info_then_unknown(self):
        legacy = types.SimpleNamespace(bl_info={'version': (2, 9, 2)})
        self.assertEqual(compat.mmd_tools_version(legacy), '2.9.2')
        self.assertEqual(compat.mmd_tools_version(types.SimpleNamespace()), 'unknown')

    def test_environment_hint_names_version(self):
        self.assertIn('4.5.14', compat.environment_hint('4.5.14'))


if __name__ == '__main__':
    unittest.main()
