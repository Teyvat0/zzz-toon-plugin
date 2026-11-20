"""Explicit user decisions for material slots: pick a JSON, or keep the MMD original.

Decisions are plain data (zzz_mapping.json); no character names appear in code.
A choice must be one of the slot's own offered choices (resource JSONs that have, or
can complete from the slot's atlas family, every required map). Nothing is guessed.
"""
import json
from pathlib import Path

FILE = 'zzz_mapping.json'
SCHEMA = 'zzz-user-mapping.v1'
MAX_CHOICES = 80


def choose(row, stem):
    """Apply the user's JSON choice for one planned row. Raises if not offered."""
    offered = next((c for c in row.get('choices', []) if c['stem'] == stem), None)
    if offered is None:
        raise RuntimeError('%02d %s: 所选JSON「%s」缺少该材质域必需贴图，或不在资源目录中' % (row['slot'], row['name'], stem))
    row.update(stem=stem, keep_original=False, texture_overrides=dict(offered['texture_overrides']),
               preserve_source_texture=False, confidence=.5)
    row.pop('json_path', None)
    row.pop('unresolved_reason', None)
    row.setdefault('warnings', []).append('用户手动选择JSON：%s（非自动证据）' % stem)
    row.setdefault('evidence', []).append('user-selected JSON')
    row['user_selected'] = True
    return row


def keep(row):
    row.update(stem='', keep_original=True, texture_overrides={}, preserve_source_texture=False)
    row.pop('effect_policy', None)
    row['archive'] = False
    row['user_selected'] = True
    return row


def path_for(directory):
    return Path(directory) / FILE


def save(directory, rows, material_names):
    data = {'schema': SCHEMA, 'slots': [
        {'slot': int(r['slot']), 'name': material_names[int(r['slot'])],
         'keep_original': bool(r.get('keep_original')), 'stem': r.get('stem') or '', 'cull': r.get('cull') or 'AUTO'}
        for r in rows if r.get('user_selected') or r.get('keep_original') or r.get('cull') in ('ON', 'OFF')]}
    target = path_for(directory)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    return str(target)


def load(directory):
    target = path_for(directory) if directory else None
    if target is None or not target.is_file():
        return None
    try:
        data = json.loads(target.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'error': '无法读取 ' + str(target)}
    if not isinstance(data, dict) or data.get('schema') != SCHEMA or not isinstance(data.get('slots'), list):
        return {'error': '映射文件格式不被识别: ' + str(target)}
    return data


def apply_saved(plan):
    """Re-apply saved decisions to a fresh plan; mismatching slots are only reported."""
    data = load(plan.get('resource_dir'))
    if data is None:
        return plan
    if 'error' in data:
        plan['warnings'].append(data['error'])
        return plan
    names = plan['material_names']
    applied = 0
    for item in data['slots']:
        try:
            slot = int(item['slot'])
            row = plan['rows'][slot]
            if names[slot] != item.get('name'):
                raise ValueError('name')
            if item.get('cull') in ('ON', 'OFF'):
                row['cull'] = item['cull']
            if item.get('keep_original'):
                keep(row)
            elif item.get('stem'):
                if row.get('stem') == item['stem'] and not row.get('keep_original'):
                    continue
                choose(row, item['stem'])
            else:
                continue
            applied += 1
        except (KeyError, IndexError, ValueError, TypeError, RuntimeError):
            plan['warnings'].append('已保存的映射不再适用，已忽略: 槽 %s / %s' % (item.get('slot'), item.get('name')))
    if applied:
        decided = {r['slot'] for r in plan['rows'] if r.get('stem') or r.get('user_selected')}
        for key in ('slot_errors', 'errors'):
            plan[key][:] = [e for e in plan[key] if not (e[:2].isdigit() and int(e[:2]) in decided)]
        plan['warnings'].append('已载入 %s：%d 个槽使用用户保存的选择' % (FILE, applied))
        summary = plan.get('summary')
        if summary:
            summary['mapped'] = sum(bool(r['stem']) for r in plan['rows'])
            summary['unresolved'] = sum(not r['stem'] for r in plan['rows'])
    return plan
