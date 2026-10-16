"""Portable primitives shared by deployment updates and task admission. Standard library only."""
import contextlib
import hashlib
import importlib.util
import json
import os
import re
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath

CONTROL = '.ai-sma-deploy/update'
CONFIG = 'agents/项目/项目配置.yaml'
FLOW = 'agents/role/总负责人/工具/任务管理/流程定义.json'
RECEIPT = 'agents/项目/安装回执.json'
GENERATION = 'agents/项目/团队生成记录.json'


class UpdateError(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def read(path, default=None):
    path = Path(path)
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def sha(path):
    path = Path(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def safe(root, relative):
    root = Path(root).absolute()
    if root.resolve() != root:
        raise UpdateError('受管根目录经过链接：' + str(root))
    raw = str(relative).replace('\\', '/')
    rel, win = Path(raw), PureWindowsPath(raw)
    if not raw or rel.is_absolute() or win.drive or win.root or '..' in rel.parts:
        raise UpdateError('越界路径：' + raw)
    for part in rel.parts:
        if re.search(r'[\x00-\x1f:*?"<>|]', part) or part.endswith((' ', '.')) or re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', part):
            raise UpdateError('不可移植路径：' + raw)
    path = root / rel
    for parent in [path, *path.parents]:
        if parent == root:
            break
        if parent.is_symlink() or (parent.exists() and parent.resolve() != parent.absolute()):
            raise UpdateError('受管路径经过链接：' + raw)
    return path


def put(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not isinstance(data, bytes):
        data = (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode()
    fd, tmp = tempfile.mkstemp(prefix='.sma-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            if path.exists() and os.name != 'nt':
                os.fchmod(stream.fileno(), stat.S_IMODE(path.stat().st_mode))
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


@contextlib.contextmanager
def lock(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        if not path.stat().st_size:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise UpdateError('已有操作占用锁：' + str(path)) from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


def category(relative):
    p = str(relative).replace('\\', '/')
    parts = p.split('/')
    if p.startswith(('固定资产/', '交付/', '发布内容/', 'agents/工作/', 'agents/账号/', 'agents/项目/定制/')) or '/记忆/' in p:
        return 'user'
    if p in {CONFIG, 'agents/SKILLS_INDEX.md', '.claude/settings.json', '.codex/hooks.json'}:
        return 'mixed'
    if p in {RECEIPT, GENERATION, 'agents/项目/装配清单.json', '.codex/config.toml'} or p.startswith(('.codex/agents/', '.claude/agents/')):
        return 'generated'
    if p.startswith('agents/项目/'):
        return 'user'
    if p in {'AGENTS.md', 'CLAUDE.md', '更新项目.py'} or p.startswith('agents/公共/'):
        return 'template'
    if len(parts) >= 4 and parts[:2] == ['agents', 'role']:
        return 'template'
    return 'user'


def inventory(root):
    root = Path(root)
    result = {}
    for path in sorted(root.rglob('*')):
        rel = path.relative_to(root).as_posix()
        if set(path.relative_to(root).parts) & {'__pycache__', '.git', '.ai-sma-deploy'} or path.name == '.DS_Store':
            continue
        safe(root, rel)
        if path.is_file():
            result[rel] = sha(path)
    return result
