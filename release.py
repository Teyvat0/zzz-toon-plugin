"""Release helper: `bump X.Y.Z` edits every version string; `publish` ships a build to GitHub.

  python release.py bump 0.2.3
  python release.py publish --repo-dir <clone> --notes "修复说明"          # dry run
  python release.py publish --repo-dir <clone> --notes "..." --yes        # commit, tag, push, release

Only lines that state the CURRENT version are rewritten; historical mentions are left alone.
"""
import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GITHUB = 'Teyvat0/zzz-toon-plugin'


def current():
    tree = ast.parse((ROOT / 'zzz_mmd_toon' / '__init__.py').read_text(encoding='utf-8'))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, 'id', '') == 'bl_info' for t in node.targets):
            return tuple(ast.literal_eval(node.value)['version'])
    raise SystemExit('bl_info not found')


def rules(old, new):
    o, n = '.'.join(map(str, old)), '.'.join(map(str, new))
    ot, nt = '(%d, %d, %d)' % old, '(%d, %d, %d)' % new
    t = 'tests/blender/blender_zip_install.py'
    return [
        ('zzz_mmd_toon/__init__.py', r"'version': \(%d, %d, %d\)," % old, "'version': %s," % nt, 1),
        ('zzz_mmd_toon/workflow.py', r"^VERSION = '%s'" % re.escape(o), "VERSION = '%s'" % n, 1),
        ('README.md', r'当前版本 %s，' % re.escape(o), '当前版本 %s，' % n, 1),
        ('docs/CONTRACT.md', r'\A# v%s ' % re.escape(o), '# v%s ' % n, 1),
        ('docs/快速开始.md', r'\A# 仿ZZZ渲染 · MMD %s｜' % re.escape(o), '# 仿ZZZ渲染 · MMD %s｜' % n, 1),
        ('zzz_mmd_toon/README.md', r'\A# 仿ZZZ渲染 · MMD %s（' % re.escape(o), '# 仿ZZZ渲染 · MMD %s（' % n, 1),
        (t, r'installed addon %s must' % re.escape(o), 'installed addon %s must' % n, 1),
        (t, r"== workflow\.VERSION == '%s'" % re.escape(o), "== workflow.VERSION == '%s'" % n, 1),
        (t, r"\) == %s\n" % re.escape(ot), ") == %s\n" % nt, 1),
        (t, r"and workflow\.VERSION == '%s'" % re.escape(o), "and workflow.VERSION == '%s'" % n, 1),
    ]


def read(rel):
    with open(ROOT / rel, encoding='utf-8', newline='') as stream:  # keep CRLF/LF as is
        return stream.read()


def bump(version):
    new = tuple(int(x) for x in version.split('.'))
    old = current()
    if len(new) != 3 or new <= old:
        raise SystemExit('new version must be X.Y.Z and greater than current %s' % '.'.join(map(str, old)))
    texts = {}
    for rel, pattern, repl, count in rules(old, new):
        text = texts.get(rel) or read(rel)
        text, found = re.subn(pattern, repl, text, flags=re.M)
        if found != count:
            raise SystemExit('%s: expected %d match(es) for %r, found %d; nothing written' % (rel, count, pattern, found))
        texts[rel] = text
    for rel, text in texts.items():
        with open(ROOT / rel, 'w', encoding='utf-8', newline='') as stream:
            stream.write(text)
    print('bumped %s -> %s in %d files' % ('.'.join(map(str, old)), version, len(texts)))


MIRROR = ('zzz_mmd_toon/*.py', 'zzz_mmd_toon/README.md', 'zzz_mmd_toon/LICENSE', 'docs/*.md', 'tests/**/*.py',
          'tests/fixtures.example.json', '.github/workflows/*.yml', 'build_release.py', 'release.py',
          'README.md', 'LICENSE', '.gitignore')


def run(cmd, cwd=None, check=True):
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding='utf-8',
                            env={**os.environ, 'PYTHONUTF8': '1'})
    if check and result.returncode:
        raise SystemExit('FAILED: %s\n%s%s' % (' '.join(map(str, cmd)), result.stdout, result.stderr))
    return result.stdout.strip()


def build():
    run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/unit', '-p', 'test_*.py'], cwd=ROOT)
    return json.loads(run([sys.executable, 'build_release.py'], cwd=ROOT).splitlines()[-1])


def mirror(repo, write=True):
    copied = []
    for pattern in MIRROR:
        for src in sorted(ROOT.glob(pattern)):
            if not src.is_file() or '__pycache__' in src.parts:
                continue
            dst = repo / src.relative_to(ROOT)
            if not dst.exists() or dst.read_bytes() != src.read_bytes():
                if write:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src, dst)
                copied.append(src.relative_to(ROOT).as_posix())
    return copied


def publish(repo, notes, confirmed):
    repo = Path(repo).resolve()
    version = '.'.join(map(str, current()))
    tag = 'v' + version
    if not (repo / '.git').is_dir():
        raise SystemExit('not a git clone: %s' % repo)
    if run(['git', 'status', '--porcelain'], cwd=repo):
        raise SystemExit('clone has uncommitted changes; clean it first')
    if run(['git', 'branch', '--show-current'], cwd=repo) != 'main':
        raise SystemExit('clone is not on main')
    run(['git', 'pull', '--ff-only'], cwd=repo)
    if run(['git', 'tag', '-l', tag], cwd=repo):
        raise SystemExit('tag %s already exists; run `bump` first' % tag)
    built = build()
    changed = mirror(repo, write=confirmed)
    print('version %s | zip %s | sha256 %s' % (version, built['zip'], built['sha256']))
    print('files to commit (%d): %s' % (len(changed), ', '.join(changed) or '-'))
    if not confirmed:
        print('dry run only; add --yes to commit, tag, push and create the release')
        return
    asset = Path(built['zip']).with_name('zzz_mmd_toon_%s.zip' % tag)
    shutil.copyfile(built['zip'], asset)
    body = '%s\n\n安装：Goo Engine 4.4 → 编辑 → 偏好设置 → 插件 → 从磁盘安装，选择此 zip，需先启用 MMD Tools。\n' \
           '不含角色模型、贴图或游戏 JSON。\nsha256: %s\n' % (notes, built['sha256'])
    run(['git', 'add', '-A'], cwd=repo)
    run(['git', 'commit', '-q', '-m', 'Release %s' % tag, '-m', notes], cwd=repo)
    run(['git', 'tag', '-a', tag, '-m', 'ZZZ MMD Toon plugin %s' % tag], cwd=repo)
    run(['git', 'push', 'origin', 'main', tag], cwd=repo)
    run(['gh', 'release', 'create', tag, str(asset), '--repo', GITHUB, '--title', tag, '--notes', body, '--verify-tag'])
    print('released https://github.com/%s/releases/tag/%s' % (GITHUB, tag))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='cmd', required=True)
    sub.add_parser('bump').add_argument('version')
    p = sub.add_parser('publish')
    p.add_argument('--repo-dir', required=True)
    p.add_argument('--notes', required=True)
    p.add_argument('--yes', action='store_true')
    args = parser.parse_args()
    bump(args.version) if args.cmd == 'bump' else publish(args.repo_dir, args.notes, args.yes)


if __name__ == '__main__':
    main()
