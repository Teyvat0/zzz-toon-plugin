import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'zzz_mmd_toon'))
import ui_text  # noqa: E402  (bpy-free module, imported directly)


class WrapTests(unittest.TestCase):
    def test_short_text_is_one_line(self):
        self.assertEqual(ui_text.wrap('扫描完成', 300), ['扫描完成'])

    def test_cjk_breaks_by_width_and_keeps_all_text(self):
        text = '这是一段比较长的中文提示用来检查折行'
        lines = ui_text.wrap(text, 100)
        self.assertGreater(len(lines), 1)
        self.assertEqual(''.join(lines), text)
        self.assertTrue(all(sum(ui_text.char_px(c) for c in l) <= 100 for l in lines))

    def test_ascii_word_is_not_split_when_it_fits(self):
        lines = ui_text.wrap('请选择 JSON 文件夹', 70)
        self.assertTrue(any('JSON' in l for l in lines))

    def test_overlong_word_is_split(self):
        lines = ui_text.wrap('a' * 100, 100)
        self.assertGreater(len(lines), 1)
        self.assertEqual(''.join(lines), 'a' * 100)

    def test_newlines_are_kept_and_limit_adds_ellipsis(self):
        self.assertEqual(ui_text.wrap('a\nb', 200), ['a', 'b'])
        lines = ui_text.wrap('\n'.join('line%d' % i for i in range(9)), 200, limit=3)
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[-1].endswith('…'))

    def test_empty_text_and_tiny_width_do_not_loop(self):
        self.assertEqual(ui_text.wrap('', 100), [''])
        self.assertTrue(ui_text.wrap('测试文字', 1))


class StatusTests(unittest.TestCase):
    def test_explicit_kind_wins(self):
        self.assertEqual(ui_text.classify_status('完成：x', 'error'), 'error')

    def test_prefix_inference(self):
        self.assertEqual(ui_text.classify_status('资源未就绪（不会报告渲染成功）：'), 'error')
        self.assertEqual(ui_text.classify_status('有 2 个材质槽没有映射'), 'warn')
        self.assertEqual(ui_text.classify_status('完成：ok'), 'done')
        self.assertEqual(ui_text.classify_status('先导入 PMX'), 'info')
        self.assertEqual(ui_text.classify_status('', 'bogus'), 'info')


class RowTests(unittest.TestCase):
    def test_short_stem(self):
        self.assertEqual(ui_text.short_stem('MAT_Yanagi_Body_2_UI'), 'Yanagi_Body_2')
        self.assertEqual(ui_text.short_stem('Custom'), 'Custom')
        self.assertEqual(ui_text.short_stem(None), '')

    def test_is_transparent_matches_application_rule(self):
        self.assertTrue(ui_text.is_transparent('ON', False))
        self.assertTrue(ui_text.is_transparent('AUTO', True))
        self.assertFalse(ui_text.is_transparent('AUTO', False))
        self.assertFalse(ui_text.is_transparent('OFF', True))


if __name__ == '__main__':
    unittest.main()
