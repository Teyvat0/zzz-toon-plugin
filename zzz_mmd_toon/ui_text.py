"""bpy-free text helpers for the sidebar (testable without Blender)."""

CJK_PX, LATIN_PX = 12.0, 6.5   # Blender's default UI font at ui_scale 1.0
STATUS_KINDS = ('error', 'warn', 'done', 'info')


def char_px(ch):
    return CJK_PX if ord(ch) >= 0x2E80 else LATIN_PX


def _units(para):
    """CJK characters are one unit each; a run of other non-space characters stays whole."""
    unit = ''
    for ch in para:
        if ord(ch) >= 0x2E80 or ch == ' ':
            if unit:
                yield unit
                unit = ''
            yield ch
        else:
            unit += ch
    if unit:
        yield unit


def wrap(text, avail_px, scale=1.0, limit=None):
    """Greedy wrap; Blender labels never wrap on their own. Long ASCII words are split."""
    avail = max(60.0, float(avail_px))
    lines = []
    for para in str(text).splitlines() or ['']:
        line, used = '', 0.0
        for unit in _units(para):
            width = sum(char_px(c) for c in unit) * scale
            if line and used + width > avail:
                lines.append(line.rstrip())
                line, used = '', 0.0
            if not line and unit == ' ':
                continue
            while width > avail:                  # one word wider than the line
                fit = max(1, int(avail / (LATIN_PX * scale)))
                lines.append(unit[:fit])
                unit = unit[fit:]
                width = sum(char_px(c) for c in unit) * scale
            line += unit
            used += width
        lines.append(line.rstrip())
    if limit and len(lines) > limit:
        lines = lines[:limit - 1] + [lines[limit - 1].rstrip() + ' …']
    return lines


def classify_status(status, kind=''):
    """Explicit kind wins; otherwise infer from the prefixes the workflow already uses."""
    if kind in STATUS_KINDS:
        return kind
    text = str(status or '')
    if text.startswith('资源未就绪'):
        return 'error'
    if text.startswith('有 '):
        return 'warn'
    if text.startswith('完成：'):
        return 'done'
    return 'info'


def is_transparent(mode, auto):
    """Same rule as application.is_transparent, for the PropertyGroup row (no dict access)."""
    return mode == 'ON' or (mode == 'AUTO' and bool(auto))


def short_stem(stem):
    """MAT_Yanagi_Body_2_UI -> Yanagi_Body_2 (list rows are narrow)."""
    text = str(stem or '')
    if text.startswith('MAT_'):
        text = text[4:]
    return text[:-3] if text.endswith('_UI') else text
