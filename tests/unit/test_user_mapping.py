import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
# user_mapping is pure python; import it without triggering the bpy-dependent package __init__.
pkg = types.ModuleType('zzz_mmd_toon')
pkg.__path__ = [str(ROOT / 'zzz_mmd_toon')]
sys.modules.setdefault('zzz_mmd_toon', pkg)
from zzz_mmd_toon import user_mapping  # noqa: E402


def row(slot, name, stem='', keep=False):
    return {'slot': slot, 'name': name, 'stem': stem, 'keep_original': keep, 'warnings': [], 'evidence': [],
            'texture_overrides': {}, 'effect_policy': 'MME_DUPLICATE_OFF', 'archive': True,
            'choices': [{'stem': 'A', 'texture_overrides': {'_MainTex': 'x.png'}, 'same_role': True},
                        {'stem': 'B', 'texture_overrides': {}, 'same_role': False}]}


def plan(rows, directory):
    return {'rows': rows, 'material_names': [r['name'] for r in rows], 'resource_dir': str(directory), 'warnings': [],
            'slot_errors': ['%02d %s 无法唯一关联' % (r['slot'], r['name']) for r in rows if not r['stem']],
            'errors': ['%02d %s 无法唯一关联' % (r['slot'], r['name']) for r in rows if not r['stem']],
            'summary': {'mapped': 0, 'unresolved': 0}}


class UserMappingTests(unittest.TestCase):
    def test_choose_requires_offered_stem(self):
        r = row(1, 'm', keep=True)
        with self.assertRaises(RuntimeError):
            user_mapping.choose(r, 'Z')
        user_mapping.choose(r, 'A')
        self.assertEqual((r['stem'], r['keep_original'], r['user_selected']), ('A', False, True))
        self.assertEqual(r['texture_overrides'], {'_MainTex': 'x.png'})
        self.assertTrue(any('用户手动' in w for w in r['warnings']))

    def test_keep_clears_stem_and_effect_policy(self):
        r = row(1, 'm', stem='A')
        user_mapping.keep(r)
        self.assertEqual((r['stem'], r['keep_original'], r['archive']), ('', True, False))
        self.assertNotIn('effect_policy', r)

    def test_save_and_reapply_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            rows = [row(0, 'a', keep=True), row(1, 'b', keep=True), row(2, 'c', stem='A')]
            user_mapping.choose(rows[0], 'A')
            user_mapping.keep(rows[1])
            names = {r['slot']: r['name'] for r in rows}
            user_mapping.save(d, rows, names)
            self.assertEqual(json.loads((Path(d) / user_mapping.FILE).read_text(encoding='utf-8'))['schema'], user_mapping.SCHEMA)
            fresh = [row(0, 'a', keep=True), row(1, 'b', keep=True), row(2, 'c', stem='A')]
            p = plan(fresh, d)
            user_mapping.apply_saved(p)
            self.assertEqual(fresh[0]['stem'], 'A')
            self.assertTrue(fresh[1]['keep_original'])
            self.assertEqual(p['slot_errors'], [])
            self.assertEqual(p['errors'], [])

    def test_renamed_material_is_ignored_with_warning(self):
        with tempfile.TemporaryDirectory() as d:
            rows = [row(0, 'a', keep=True)]
            user_mapping.choose(rows[0], 'A')
            user_mapping.save(d, rows, {0: 'a'})
            fresh = [row(0, 'other', keep=True)]
            p = plan(fresh, d)
            user_mapping.apply_saved(p)
            self.assertEqual(fresh[0]['stem'], '')
            self.assertTrue(any('不再适用' in w for w in p['warnings']))
            self.assertEqual(len(p['errors']), 1)

    def test_invalid_file_is_reported_not_trusted(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / user_mapping.FILE).write_text('{"schema":"x"}', encoding='utf-8')
            p = plan([row(0, 'a', keep=True)], d)
            user_mapping.apply_saved(p)
            self.assertTrue(any('格式' in w for w in p['warnings']))
            self.assertEqual(p['rows'][0]['stem'], '')


if __name__ == '__main__':
    unittest.main()
