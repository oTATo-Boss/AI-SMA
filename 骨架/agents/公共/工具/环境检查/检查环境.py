#!/usr/bin/env python3
"""只读验证真实技能包和运行工具；--record 仅保存本次检查回执，绝不安装。"""
import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
DEPENDENCIES = Path(__file__).with_name('依赖.json')
SKIP_DIRS = {'.git', 'node_modules', '__pycache__', '.venv', '.claude', '.agents', '.codex'}
GENERATED = {'SOURCE.md', 'SKILLS_INDEX.md', '.DS_Store'}
CLIENTS = {'codex', 'claude', 'both'}


def read_json(path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding='utf-8'))


def expand(value, root=None, home=None):
    value = str(value)
    if value == '~' or value.startswith('~/'):
        return Path(home or Path.home()) / value[2:] if value != '~' else Path(home or Path.home())
    path = Path(value)
    return path if path.is_absolute() else Path(root or ROOT) / path


def frontmatter_name(path):
    try:
        text = Path(path).read_text(encoding='utf-8')[:4000]
    except (OSError, UnicodeError):
        return None
    match = re.search(r'^name:\s*[\'\"]?([^\'\"\n]+)', text, re.M)
    return match.group(1).strip() if match else None


def skill_index(roots, depth=12, root=None, home=None):
    """兼容旧调用；名字仅用于发现候选，不能用此结果宣布已安装。"""
    index, seen = {}, set()
    for value in roots:
        base = expand(value, root, home)
        if not base.is_dir():
            continue
        for current, dirs, files in os.walk(base, followlinks=True):
            real = os.path.realpath(current)
            if real in seen or len(Path(current).relative_to(base).parts) > depth:
                dirs[:] = []
                continue
            seen.add(real)
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith('.')]
            if 'SKILL.md' in files:
                entry = Path(current) / 'SKILL.md'
                for name in {entry.parent.name, frontmatter_name(entry)} - {None, ''}:
                    index.setdefault(name.lower(), []).append(entry)
    return index


def index_rows(text):
    """保留旧团队生成器使用的 Markdown 索引接口。"""
    rows, header = [], None
    for line in text.splitlines():
        if not line.startswith('|'):
            header = None
            continue
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if set(line.replace('|', '').strip()) <= set('-: '):
            continue
        if header is None:
            header = cells
            continue
        row = dict(zip(header, cells))
        if '名称' in row and ('入口' in row or '来源' in row):
            rows.append(row)
    return rows


def version_tuple(text):
    match = re.search(r'(\d+(?:\.\d+)*)', text or '')
    return tuple(map(int, match.group(1).split('.'))) if match else ()


def run(command, timeout=15):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        return result.returncode, (result.stdout or '') + (result.stderr or '')
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, type(exc).__name__


def inside(path, base):
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except (ValueError, OSError):
        return False


def blob_hash(path, mode='100644'):
    data = os.readlink(path).encode('utf-8') if mode == '120000' else path.read_bytes()
    return hashlib.sha1(b'blob ' + str(len(data)).encode('ascii') + b'\0' + data).hexdigest()


def safe_relative(value):
    path = Path(value)
    return not path.is_absolute() and '..' not in path.parts and bool(value)


def verify_package(package, source):
    """用发行清单的 Git blob 逐文件验证，不信任回执中自填的 digest/source。"""
    expected = source.get('files', {})
    if not expected or not re.fullmatch(r'[0-9a-f]{40}', source.get('ref', '')):
        return {'status': 'source_unverified', 'errors': ['来源缺少固定提交或完整包文件清单']}
    errors, observed = [], {}
    for rel, metadata in expected.items():
        if not safe_relative(rel):
            errors.append('不安全的包内路径：' + rel)
            continue
        path = package / rel
        mode = metadata.get('mode', '100644')
        if not path.is_file() and not path.is_symlink():
            errors.append('缺资源：' + rel)
            continue
        if mode != '120000' and (path.is_symlink() or not inside(path, package)):
            errors.append('资源路径身份不匹配：' + rel)
            continue
        if mode == '120000' and (not path.is_symlink() or not inside(path, package)):
            errors.append('包内链接必须指向完整包内部：' + rel)
            continue
        try:
            actual = blob_hash(path, mode)
            observed[rel] = actual
            if actual != metadata['blob']:
                errors.append('内容不同：' + rel)
            if os.name != 'nt' and mode == '100755' and not os.access(path, os.X_OK):
                errors.append('缺执行权限：' + rel)
        except (OSError, ValueError) as exc:
            errors.append('不可读取：' + rel + ' (' + type(exc).__name__ + ')')
    # 未登记的脚本、提示词等也会改变包行为；来源记录与运行缓存不参与摘要。
    for current, dirs, files in os.walk(package, followlinks=False):
        dirs[:] = [d for d in dirs if d not in {'.git', 'node_modules', '__pycache__', '.venv', '.ai-sma-source'}]
        for name in files:
            rel = (Path(current) / name).relative_to(package).as_posix()
            if rel not in expected and name not in GENERATED and not name.endswith('.pyc'):
                errors.append('未登记文件：' + rel)
    for rel, metadata in source.get('license_files', {}).items():
        path = package / '.ai-sma-source' / rel
        if not safe_relative(rel) or not path.is_file() or not inside(path, package):
            errors.append('缺包外许可文件：' + rel)
        elif blob_hash(path) != metadata['blob']:
            errors.append('许可文件内容不同：' + rel)
    payload = '\n'.join(f'{rel}\0{observed[rel]}' for rel in sorted(observed))
    return {'status': 'verified' if not errors else 'conflict', 'digest': 'sha256:' + hashlib.sha256(payload.encode()).hexdigest(),
            'files_checked': len(observed), 'files_expected': len(expected), 'errors': errors}


def required_skills(root, config):
    required = config.get('skills', {}).get('required')
    if required is not None:
        return list(dict.fromkeys(required))
    # v1 项目保持可读：按角色卡的实际分配，绝不把整个候选索引当必需。
    result = []
    for card in sorted((root / 'agents/role').glob('*/agent.yaml')):
        text = card.read_text(encoding='utf-8')
        try:
            result.extend(json.loads(text).get('skills', []))
        except ValueError:
            match = re.search(r'^skills:\s*\[(.*?)\]', text, re.M)
            if match:
                result.extend(s.strip().strip('\'\"') for s in match.group(1).split(',') if s.strip())
    return list(dict.fromkeys(result))


def closure(required, catalog):
    result, visiting, errors = [], set(), []
    def visit(name):
        if name in visiting:
            errors.append('技能依赖循环：' + name)
            return
        if name in result:
            return
        skill = catalog.get(name)
        if skill is None:
            errors.append('未登记技能：' + name)
            result.append(name)
            return
        visiting.add(name)
        for dependency in skill.get('requires', []):
            visit(dependency)
        visiting.remove(name)
        result.append(name)
    for name in required:
        visit(name)
    return result, errors


def inspect_skill(name, spec, sources, candidates, receipt, shared, home, client, package_cache=None):
    source = sources.get(spec.get('source'), {})
    result = {'source': spec.get('source'), 'ref': source.get('ref'), 'status': 'missing',
              'verification': {'files': 'not_verified', 'source': 'not_verified'}, 'clients': {}, 'errors': []}
    if spec.get('status') != 'ready' or source.get('status') != 'ready':
        result.update(status='blocked', errors=[spec.get('note') or source.get('note') or '来源仍为候选，不能计入已就绪'])
        return result
    for target in (['codex', 'claude'] if client == 'both' else [client]):
        if target not in spec.get('clients', []):
            result['errors'].append('技能不支持客户端：' + target)
    paths = list(candidates.get(name.lower(), []))
    if receipt.get('path'):
        paths.insert(0, Path(receipt['path']) / 'SKILL.md')
    paths = list({str(p.resolve()): p for p in paths if p.is_file()}.values())
    if not paths:
        return result
    checked, valid = [], []
    for entry in paths:
        if not inside(entry, shared):
            checked.append({'path': str(entry.parent), 'errors': ['技能实体不在共享用途分类库内']})
            continue
        expected_entry = spec.get('entry', 'SKILL.md')
        if not safe_relative(expected_entry):
            checked.append({'path': str(entry.parent), 'errors': ['登记入口路径无效']})
            continue
        package = entry.resolve()
        for _ in Path(expected_entry).parts:
            package = package.parent
        if (package / expected_entry).resolve() != entry.resolve():
            checked.append({'path': str(entry.parent), 'errors': ['入口与完整包根不匹配']})
            continue
        identity = frontmatter_name(entry)
        if identity != spec.get('name', name):
            checked.append({'path': str(entry.parent), 'errors': ['frontmatter 名称不匹配']})
            continue
        cache_key = (str(package), spec['source'])
        if package_cache is not None and cache_key in package_cache:
            proof = package_cache[cache_key]
        else:
            proof = verify_package(package, source)
            if package_cache is not None:
                package_cache[cache_key] = proof
        checked.append({'path': str(entry.parent), **proof})
        if proof['status'] == 'verified':
            valid.append((entry, package, proof))
    if len(paths) != 1 or len(valid) != 1:
        result.update(status='conflict', errors=['存在同名多个实体或完整包验证失败'], candidates=checked)
        return result
    entry, package, proof = valid[0]
    if receipt.get('source') not in (None, spec['source']) or receipt.get('ref') not in (None, source['ref']):
        result.update(status='conflict', errors=['旧回执的来源或版本与当前绑定冲突'])
        return result
    result.update(path=str(entry.parent.resolve()), package_path=str(package), digest=proof['digest'],
                  verification={'files': 'verified', 'source': 'verified', 'files_checked': proof['files_checked']})
    for target in (['codex', 'claude'] if client == 'both' else [client]):
        if target == 'codex':
            linked = inside(entry, shared)
            path = entry.parent
        elif target == 'claude':
            path = home / '.claude/skills' / name
            try:
                linked = path.is_dir() and os.path.samefile(path, entry.parent)
            except OSError:
                linked = False
        else:
            path, linked = None, False
        result['clients'][target] = {'entry': str(path) if path else None,
                                    'entry_status': 'verified' if linked else 'missing_or_wrong_target',
                                    'discovery': 'not_verified', 'note': '文件与入口检查不证明当前客户端已发现或加载'}
        if not linked:
            result['errors'].append(target + ' 的发现入口缺失或指向其他实体')
    result['status'] = 'verified' if not result['errors'] else 'conflict'
    return result


def inspect_tools(required, definitions):
    output = {}
    for name in sorted(set(required)):
        tool = definitions.get(name)
        if tool is None:
            output[name] = {'status': 'not_verified', 'reason': '无可执行的只读验证配方'}
            continue
        if tool.get('kind') == 'python-module':
            code, _ = run([sys.executable, '-c', 'import importlib; importlib.import_module(' + repr(tool['module']) + ')'])
            output[name] = {'status': 'verified' if code == 0 else 'missing', 'path': sys.executable,
                            'install': None if code == 0 else tool.get('install')}
            continue
        if tool.get('kind') == 'service':
            output[name] = {'status': 'not_verified', 'reason': tool['for'], 'install': tool.get('install')}
            continue
        binary = sys.executable if name == 'python3' else next((shutil.which(n) for n in tool.get('commands', [name]) if shutil.which(n)), None)
        if not binary:
            output[name] = {'status': 'missing', 'install': tool.get('install'), 'reason': tool.get('for')}
            continue
        code, text = run([binary, *tool.get('version', ['--version'])])
        first = next((line.strip() for line in text.splitlines() if line.strip()), '')[:180]
        minimum = tool.get('min')
        ok = code == 0 and (not minimum or version_tuple(first) >= version_tuple(minimum))
        output[name] = {'status': 'verified' if ok else 'unavailable', 'path': binary, 'version': first,
                        'install': None if ok else tool.get('install')}
    return output


def inspect(root, *, home=None, check_tools=True, bindings=None):
    """返回结构化只读结果；home/check_tools/bindings 可供隔离测试和部署绑定使用。"""
    root, home = Path(root).resolve(), Path(home or Path.home()).resolve()
    config = read_json(root / 'agents/项目/项目配置.yaml', {})
    catalog = read_json(root / 'agents/公共/技能来源.json', {})
    receipt_path = root / 'agents/项目/安装回执.json'
    previous = read_json(receipt_path, {'skills': {}})
    receipts = dict(previous.get('skills', {}))
    for name, path in (bindings or {}).items():
        receipts[name] = {'path': str(Path(path).resolve())}
    deps = read_json(root / 'agents/公共/工具/环境检查/依赖.json', {})
    skills = catalog.get('skills', {})
    required, errors = closure(required_skills(root, config), skills)
    client = config.get('project', {}).get('client', 'codex')
    if client == 'claude-code':
        client = 'claude'
    if client not in CLIENTS:
        errors.append('未知客户端：' + str(client))
    shared = home / '.agents/skills'
    candidates = skill_index([str(shared)], root=root, home=home)
    # 同名客户端入口指错会在精确 samefile 检查中暴露，不靠名字复用。
    package_cache = {}
    rows = {name: inspect_skill(name, skills.get(name, {}), catalog.get('sources', {}), candidates,
                                receipts.get(name, {}), shared, home, client, package_cache) for name in required}
    runtimes = list(deps.get('core', ['python3', 'git']))
    for name in required:
        runtimes.extend(skills.get(name, {}).get('runtimes', []))
    tools = inspect_tools(runtimes, {item['name']: item for item in deps.get('tools', [])}) if check_tools else {}
    files_ok = bool(required) and all(row['status'] == 'verified' for row in rows.values())
    tools_ok = check_tools and all(item['status'] == 'verified' for item in tools.values())
    return {'schema_version': 2, 'checked_at': datetime.now(timezone.utc).isoformat(), 'root': str(root),
            'system': platform.system(), 'client': client, 'skills': rows, 'tools': tools, 'errors': errors,
            'files_ready': files_ok, 'tools_ready': tools_ok,
            'client_discovery': 'not_verified', 'runtime_samples': 'not_verified',
            'ready': files_ok and tools_ok and not errors,
            'readiness_scope': '本次 ready 仅表示完整技能包、发现入口路径及必要命令可用；不代表当前客户端发现、账号服务或制作小样通过'}


def write_index(root, result=None):
    """Update the owned binding table while retaining user prose outside its markers."""
    root = Path(root)
    config = read_json(root / 'agents/项目/项目配置.yaml', {})
    catalog = read_json(root / 'agents/公共/技能来源.json', {})
    required, _ = closure(required_skills(root, config), catalog.get('skills', {}))
    start, end = '<!-- AI-SMA:skills:start -->', '<!-- AI-SMA:skills:end -->'
    lines = [start, '## 本项目技能绑定', '',
             '| 技能 | 来源与固定版本 | 文件状态 | 实际入口 |', '|---|---|---|---|']
    for name in required:
        item = catalog['skills'].get(name, {})
        source = catalog.get('sources', {}).get(item.get('source'), {})
        observed = (result or {}).get('skills', {}).get(name, {})
        location = str(observed.get('path') or '待安装并验证').replace('|', '\\|')
        identity = str(item.get('source', '未登记')) + '@' + str(source.get('ref') or '未固定')
        lines.append(f"| {name} | `{identity}` | {observed.get('status', 'not_verified')} | `{location}` |")
    lines += ['', '文件验证不等于客户端已加载、账号模型就绪或媒体制作通过。详细证据见项目安装回执；技能来源和安装步骤见公共说明。', end]
    block = '\n'.join(lines)
    target = root / 'agents/SKILLS_INDEX.md'
    existing = target.read_text(encoding='utf-8') if target.exists() else '# 项目技能索引\n\n用于本项目技能选型与复用，随已分配能力和真实安装结果更新。\n'
    if start in existing and end in existing:
        before, rest = existing.split(start, 1)
        _, after = rest.split(end, 1)
        text = before + block + after
    else:
        text = existing.rstrip() + '\n\n' + block + '\n'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding='utf-8')
    return target


def record(root, result):
    """只保存检查器自己的实测结果；不接收伪造成功状态，不填客户端发现成功。"""
    destination = Path(root) / 'agents/项目/安装回执.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_suffix('.json.tmp')
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(temp, destination)
    write_index(root, result)
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--record', action='store_true', help='仅写本次实测回执，不安装')
    parser.add_argument('--bind', action='append', default=[], metavar='SKILL=PATH', help='显式完整技能目录；仍须逐文件验证')
    args = parser.parse_args(argv)
    try:
        bindings = dict(value.split('=', 1) for value in args.bind)
        result = inspect(args.root, bindings=bindings)
        if args.record:
            record(args.root, result)
    except (ValueError, OSError, KeyError) as exc:
        result = {'schema_version': 2, 'ready': False, 'errors': [str(exc)]}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for name, row in result.get('skills', {}).items():
            print(f"技能 {name}：{row['status']}" + ('；' + '；'.join(row['errors']) if row.get('errors') else ''))
        for name, row in result.get('tools', {}).items():
            print(f"工具 {name}：{row['status']}")
        for error in result.get('errors', []):
            print('问题：' + error)
        print('结果：' + ('文件与工具检查通过' if result.get('ready') else '尚有缺项或冲突'))
        print('客户端实际发现、登录、模型与制作小样仍需分别验证；本命令未安装任何内容。')
    return 0 if result.get('ready') else 1


if __name__ == '__main__':
    raise SystemExit(main())
