"""AI-SMA update planner and recoverable project transaction. No skill installer."""
import argparse
import copy
import difflib
import hashlib
import inspect as signature_tools
import json
import os
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from sma_common import (CONFIG, CONTROL, FLOW, GENERATION, RECEIPT, UpdateError, category,
                        fingerprint, inventory, module, now, put, read, safe, sha)
from sma_coordination import admission, blockers, coordinated, execution, machine, register, reserve
import sma_release as release

ENTRY = '''\n<!-- AI-SMA UPDATE BEGIN -->
进入项目工作时先执行 `python 更新项目.py check --automatic`（使用实际 Python 解释器）。按更新策略及 `agents/公共/项目更新.md` 处理适用更新，再开始制作；无更新或网络不可用时沿用已验证的当前版本。项目级定制见 `agents/项目/定制/项目规则.md`，角色定制见该目录的 `角色/<角色ID>.md`，本人明确要求优先。
<!-- AI-SMA UPDATE END -->\n'''


LEGACY_WRAPPER = '''# AI-SMA managed legacy task admission adapter
import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(_root / 'agents/公共/工具/更新'))
from sma_coordination import coordinated, admission, register
_namespace = dict(__file__=__file__, __name__='ai_sma_legacy_task')
_source = _root / '.ai-sma-deploy/update/bootstrap/legacy-task.py'
exec(compile(_source.read_bytes(), __file__, 'exec'), _namespace)
def _guard(function):
    def wrapped(self, *args, **kwargs):
        with coordinated(self.root):
            admission(self.root)
            result = function(self, *args, **kwargs)
            register(self.root)
            return result
    return wrapped
_namespace['Workspace'].new = _guard(_namespace['Workspace'].new)
_namespace['Workspace'].mutate = _guard(_namespace['Workspace'].mutate)
globals().update({k: v for k, v in _namespace.items() if not k.startswith('__')})
if __name__ == '__main__':
    try:
        sys.exit(main())
    except ValueError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
'''


def report(phase, state=None, **extra):
    state = state or {}
    return dict(phase=phase, current_version=state.get('version'), target_version=extra.pop('target_version', None),
                release_id=state.get('release_id'),
                changes=extra.pop('changes', []), blockers=extra.pop('blockers', []),
                next_action=extra.pop('next_action', None), evidence=extra.pop('evidence', {}), **extra)


class Updater:
    def __init__(self, root, home=None):
        self.root = Path(root).expanduser().resolve()
        self.home = Path(home or os.environ.get('AI_SMA_HOME') or Path.home()).expanduser().resolve()
        self.control = safe(self.root, CONTROL)
        self.state_path = safe(self.root, CONTROL + '/state.json')

    def state(self):
        state = read(self.state_path)
        if not state:
            raise UpdateError('项目尚未接入；v2 项目先运行 adopt，v1 需要专门迁移')
        if state.get('root') != str(self.root):
            raise UpdateError('项目位置已变化；运行 adopt 重新验证并登记')
        return state

    def save(self, state):
        put(self.state_path, state)

    def adopt(self):
        with coordinated(self.root, self.home):
            existing = read(self.state_path)
            if existing:
                if existing.get('root') != str(self.root):
                    raise UpdateError('已接入项目移动后须核对客户端绝对路径；暂不自动重绑定')
                register(self.root, self.home)
                return report('already_adopted', existing)
            config = read(safe(self.root, CONFIG), {})
            if config.get('schema_version') != 2:
                raise UpdateError('v1 或未知项目需要专门迁移，本次未修改')
            deploy = read(safe(self.root, '.ai-sma-deploy/state.json'), {})
            if deploy.get('destination') and Path(deploy['destination']).resolve() != self.root:
                raise UpdateError('原部署路径已变化，先核对客户端绝对路径和项目归属；本次不自动重绑定')
            expected = deploy.get('expected', {})
            if not expected or not deploy.get('plan'):
                raise UpdateError('缺少原始 v2 部署基线，不能猜测归属')
            normalized = {}
            for raw, digest in expected.items():
                rel = raw.replace('\\', '/')
                original = safe(self.root, '.ai-sma-deploy/stage/' + rel)
                if sha(original) != digest:
                    raise UpdateError('部署基线损坏：' + rel)
                if category(rel) != 'user':
                    normalized[rel] = digest
            baseline = safe(self.root, CONTROL + '/baseline')
            for rel in normalized:
                put(safe(baseline, rel), safe(self.root, '.ai-sma-deploy/stage/' + rel).read_bytes())
            original_config = read(safe(baseline, CONFIG))
            original_roles = set(original_config.get('team', {}).get('roles', []))
            current_roles = set(config['team']['roles'])
            config.setdefault('selection', {'role_include': sorted(current_roles - original_roles),
                'role_exclude': sorted(original_roles - current_roles), 'variant': deploy['plan'].get('variant')})
            config.setdefault('updates', {'mode': 'auto', 'interval_hours': 24, 'pin': None})
            # Validate all bootstrap collisions before changing any user files.
            boot = {f'agents/公共/工具/更新/{p.name}': p.read_bytes() for p in Path(__file__).parent.glob('*.py')}
            launcher = Path(__file__).parents[4] / '更新项目.py'
            if not launcher.exists():
                raise UpdateError('更新发行缺少项目入口')
            boot['更新项目.py'] = launcher.read_bytes()
            boot['agents/公共/项目更新.md'] = (Path(__file__).parents[2] / '项目更新.md').read_bytes()
            for rel, data in boot.items():
                current = safe(self.root, rel)
                if current.exists() and current.read_bytes() != data and rel not in normalized:
                    raise UpdateError('接入工具与用户文件冲突：' + rel)
                if current.exists() and rel in normalized and sha(current) != normalized[rel]:
                    raise UpdateError('接入工具存在本地修改：' + rel)
            task_rel = 'agents/role/总负责人/工具/任务管理/任务管理.py'
            legacy_task = safe(self.root, task_rel).read_bytes()
            needs_wrapper = b'def update_guard(' not in legacy_task and b'AI-SMA managed legacy task' not in legacy_task
            if needs_wrapper and sha(safe(self.root, task_rel)) != normalized.get(task_rel):
                raise UpdateError('旧任务工具有本地修改，先处理接入冲突：' + task_rel)
            for rel, data in boot.items():
                put(safe(self.root, rel), data)
                put(safe(baseline, rel), data)
                normalized[rel] = sha(safe(baseline, rel))
            if needs_wrapper:
                put(safe(self.root, CONTROL + '/bootstrap/legacy-task.py'), legacy_task)
                put(safe(self.root, task_rel), LEGACY_WRAPPER.encode())
                put(safe(baseline, task_rel), LEGACY_WRAPPER.encode())
                normalized[task_rel] = sha(safe(baseline, task_rel))
            elif b'AI-SMA managed legacy task' in legacy_task:
                if sha(safe(self.root, CONTROL + '/bootstrap/legacy-task.py')) != normalized.get(task_rel):
                    raise UpdateError('旧任务适配层的原始备份不匹配')
                put(safe(baseline, task_rel), legacy_task)
                normalized[task_rel] = sha(safe(baseline, task_rel))
            entry_path = safe(self.root, 'AGENTS.md')
            entry = entry_path.read_text(encoding='utf-8')
            if '<!-- AI-SMA UPDATE BEGIN -->' not in entry:
                put(entry_path, (entry.rstrip() + '\n' + ENTRY).encode())
            old_entry = safe(baseline, 'AGENTS.md').read_text(encoding='utf-8')
            if '<!-- AI-SMA UPDATE BEGIN -->' not in old_entry:
                put(safe(baseline, 'AGENTS.md'), (old_entry.rstrip() + '\n' + ENTRY).encode())
                normalized['AGENTS.md'] = sha(safe(baseline, 'AGENTS.md'))
            put(safe(self.root, CONFIG), config)
            for rel in ('agents/项目/定制/项目规则.md', 'agents/项目/定制/README.md'):
                if not safe(self.root, rel).exists():
                    put(safe(self.root, rel), '# 项目定制\n\n本人明确要求优先。角色补充要求放在 角色/<角色ID>.md；记忆继续保留在角色记忆目录。\n'.encode())
            owned = read(safe(self.root, GENERATION), {}).get('files', {})
            for rel, digest in {**deploy.get('client_files', {}), **owned}.items():
                rel = rel.replace('\\', '/')
                safe(self.root, rel)
                if category(rel) in {'generated', 'mixed'}:
                    current = safe(self.root, rel)
                    if current.is_file() and sha(current) != digest:
                        # v2 Windows generators hashed LF text but write_text stored CRLF bytes.
                        # Adopt only the proven same text, preserving substantive user edits as conflicts.
                        try:
                            normalized_text = hashlib.sha256(current.read_text(encoding='utf-8').encode('utf-8')).hexdigest()
                        except UnicodeError:
                            normalized_text = None
                        if normalized_text == digest:
                            digest = sha(current)
                    normalized[rel] = digest
                    if sha(safe(self.root, rel)) == digest:
                        put(safe(baseline, rel), safe(self.root, rel).read_bytes())
            state = {'schema_version': 1, 'project_id': uuid.uuid4().hex, 'root': str(self.root),
                'version': deploy['plan']['template_version'], 'release_id': 'legacy:' + fingerprint(expected),
                'baseline': normalized, 'installed_roles': list(current_roles), 'transaction': None,
                'client_pending': False, 'last_transaction': None, 'seen_releases': {}, 'created_at': now()}
            # Every existing task has a historical workflow snapshot, without rewriting task.json.
            context = {'version': state['version'], 'workflow': read(safe(self.root, FLOW)), 'release_id': state['release_id']}
            context_id = fingerprint(context)
            put(safe(self.root, CONTROL + '/contexts/' + context_id + '.json'), context)
            bindings = {read(p)['id']: context_id for p in (self.root / 'agents/工作').rglob('task.json')}
            put(safe(self.root, CONTROL + '/task-contexts.json'), bindings)
            self.save(state)
            register(self.root, self.home)
            return report('adopted', state, next_action='check；现有角色和制作资料未升级')

    def status(self):
        state = self.state()
        reservations = read(machine(self.home) / 'registry.json', {}).get('reservations', {})
        return report('client_reload_required' if state['client_pending'] else ('transaction_pending' if state['transaction'] else 'current'),
            state, policy=read(self.root / CONFIG)['updates'], transaction=state['transaction'],
            last_check=state.get('check'), blockers=blockers(self.root), roles=state['installed_roles'],
            dependency_operations={key: value for key, value in reservations.items() if value['owner'] == state['project_id']})

    def policy(self, mode, pin=None):
        with coordinated(self.root, self.home):
            self.state()
            config = read(self.root / CONFIG)
            if pin:
                release.version(pin)
            config['updates'] = {'mode': mode, 'interval_hours': 24, 'pin': pin}
            put(safe(self.root, CONFIG), config)
            return report('policy_saved', self.state(), policy=config['updates'])

    def check(self, automatic=False, refresh=False):
        with coordinated(self.root, self.home):
            state = self.state()
            policy = read(self.root / CONFIG)['updates']
            if automatic and policy['mode'] in {'manual', 'frozen'}:
                return report('policy_skipped', state)
            last = state.get('check', {})
            if automatic and not refresh and last.get('attempted_at'):
                elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(last['attempted_at'])).total_seconds()
                if elapsed < 86400:
                    return report('check_cached', state, previous=last, next_action=last.get('next_action'))
            attempted = now()
            request_id = uuid.uuid4().hex
            state['check'] = dict(phase='checking', attempted_at=attempted, request_id=request_id)
            self.save(state)
        # Network work must not hold the machine/project writer locks or stall other productions.
        try:
            result = report('no_update', state)
            for row in release.releases():
                v = release.version(row['tag_name'])
                current_version = release.version(state['version'])
                if v < current_version or (v == current_version and not state['release_id'].startswith('legacy:')) or v[0] != current_version[0]:
                    continue
                if policy.get('pin') and v != release.version(policy['pin']):
                    continue
                source, manifest = release.fetch(row, machine(self.home) / 'cache')
                self.remember_release(state, manifest)
                if state['version'] not in manifest['upgrade_from'] or manifest.get('breaking'):
                    continue
                result = report('update_available', state, target_version=manifest['version'], source=str(source),
                    next_action=('plan → prepare → 补齐依赖 → apply' if policy['mode'] == 'auto' else '等待本人发起更新'))
                break
            result['evidence']['transport'] = release.LAST_TRANSPORT
        except release.urllib.error.HTTPError as exc:
            result = report('rate_limited' if exc.code in {403, 429} else 'check_unavailable', state,
                            blockers=[str(exc)], next_action='保留当前版本，稍后手动重试')
        except (ValueError, KeyError) as exc:
            result = report('release_rejected', state, blockers=[str(exc)], next_action='保留当前版本，核对发行身份及校验结果')
        except (OSError, subprocess.TimeoutExpired) as exc:
            result = report('check_unavailable', state, blockers=[str(exc)], next_action='沿用当前版本；手动 check --refresh 可重试')
        with coordinated(self.root, self.home):
            current = self.state()
            if (current['release_id'] != state['release_id'] or read(self.root / CONFIG)['updates'] != policy
                    or current.get('check', {}).get('request_id') != request_id):
                return report('check_stale', current, next_action='检查期间版本、策略或请求已变化；保留较新状态')
            for v, identity in state['seen_releases'].items():
                if v in current['seen_releases'] and current['seen_releases'][v] != identity:
                    raise UpdateError('并发检查发现发行身份变化')
                current['seen_releases'][v] = identity
            result['notify'] = result.get('target_version') != last.get('target_version') or result['phase'] != last.get('phase')
            current['check'] = dict(result, attempted_at=attempted, request_id=request_id)
            self.save(current)
        return result

    def release_reservations(self, identifier):
        path = safe(machine(self.home), 'registry.json')
        registry = read(path, {})
        state = self.state()
        registry['reservations'] = {key: value for key, value in registry.get('reservations', {}).items()
            if not (value.get('owner') == state['project_id'] and value.get('plan') == identifier and value.get('verified'))}
        put(path, registry)

    def remember_release(self, state, manifest):
        identity = fingerprint(manifest)
        old = state['seen_releases'].get(manifest['version'])
        if old and old != identity:
            raise UpdateError('已知版本的提交或摘要发生变化，拒绝采用')
        state['seen_releases'][manifest['version']] = identity

    def source(self, to, source=None, development=False):
        if source:
            root = Path(source).resolve()
            manifest = release.verify(root, development)
            if to and release.version(to) != release.version(manifest['version']):
                raise UpdateError('目标版本与本地发行包不一致')
            return root, manifest
        for row in release.releases():
            if release.version(row['tag_name']) == release.version(to):
                return release.fetch(row, machine(self.home) / 'cache')
        raise UpdateError('未找到指定稳定发行')

    def render(self, source, dest, state):
        assembly = module(source / '新建项目.py', 'sma_target_assembly')
        config = read(self.root / CONFIG)
        original = read(self.control / 'baseline' / CONFIG)
        selection = copy.deepcopy(config['selection'])
        # Also capture direct role-list edits made since the last managed activation.
        selection['role_include'] = sorted(set(selection.get('role_include', [])) | (set(config['team']['roles']) - set(state['installed_roles'])))
        selection['role_exclude'] = sorted(set(selection.get('role_exclude', [])) | (set(state['installed_roles']) - set(config['team']['roles'])))
        args = argparse.Namespace(profile=config['project']['profile'], form=config['project']['form'],
            route=config['content']['production_routes'], platform=None, client=config['project']['client'],
            execution_mode=config['team']['execution_mode'], name=config['project']['name'], dest=str(self.root),
            browser_profile=config['project'].get('browser_profile'),
            hook_shell=config['project'].get('hook_shell', read(self.root / '.ai-sma-deploy/state.json')['plan'].get('hook_shell')),
            voice=config['audio'].get('voice_enabled', False), no_voice=not config['audio'].get('voice_enabled', False),
            no_sound=not config['audio'].get('sound_enabled', True), subtitles=config['subtitles'].get('enabled', False),
            no_subtitles=not config['subtitles'].get('enabled', False), variant=selection.get('variant'),
            role_include=selection['role_include'], role_exclude=selection['role_exclude'], custom_roles={})
        known = assembly.registry()[1]
        for card in (self.root / 'agents/role').glob('*/agent.yaml'):
            metadata = module(self.root / 'agents/公共/工具/团队/生成角色.py', 'sma_card_reader').load_card(card)[0]
            if metadata.get('id') in args.role_include and metadata['id'] not in known:
                args.custom_roles[metadata['id']] = {'folder': card.parent.name, 'skills': metadata.get('skills', []), 'custom': True}
        plan = assembly.build_plan(args)
        assembly.render_stage(dest, plan)
        upstream = inventory(dest)
        # Preserve user-owned files only where needed for checking/rendering; never copy media/work/deliveries.
        for subtree in ('agents/项目', 'agents/账号'):
            for path in (self.root / subtree).rglob('*'):
                if path.is_file():
                    rel = path.relative_to(self.root).as_posix()
                    safe(self.root, rel)
                    if category(rel) == 'user':
                        put(safe(dest, rel), path.read_bytes())
        for custom in args.custom_roles.values():
            for path in (self.root / 'agents/role' / custom['folder']).rglob('*'):
                if path.is_file():
                    rel = path.relative_to(self.root).as_posix()
                    safe(self.root, rel)
                    put(safe(dest, rel), path.read_bytes())
        # Keep local changes when upstream did not change that file.
        for rel, target_hash in list(upstream.items()):
            current = safe(self.root, rel)
            if category(rel) == 'template' and target_hash == state['baseline'].get(rel) and current.is_file():
                put(safe(dest, rel), current.read_bytes())
        effective = copy.deepcopy(config)
        effective['project'].setdefault('hook_shell', args.hook_shell)
        effective['selection'] = selection
        effective['team']['roles'] = plan['roles']
        extra_skills = set(config['skills']['required']) - set(original['skills']['required'])
        reader = module(dest / 'agents/公共/工具/团队/生成角色.py', 'sma_effective_cards')
        card_skills = []
        for role in reader.roles()[0]:
            if role['meta'].get('id') in plan['roles']:
                card_skills.extend(role['meta'].get('skills', []))
        effective['skills']['required'] = assembly.skill_closure(plan['skills'] + list(extra_skills) + card_skills, read(dest / 'agents/公共/技能来源.json'))
        effective['runtimes'] = sorted(set(plan['runtimes']) | (set(config.get('runtimes', [])) - set(original.get('runtimes', []))))
        put(dest / CONFIG, effective)
        # Existing complete installation receipts are inputs, never reset by rendering a new skeleton.
        put(dest / RECEIPT, read(self.root / RECEIPT, {}))
        if (self.root / 'agents/SKILLS_INDEX.md').exists():
            put(dest / 'agents/SKILLS_INDEX.md', (self.root / 'agents/SKILLS_INDEX.md').read_bytes())
        env = module(dest / 'agents/公共/工具/环境检查/检查环境.py', 'sma_target_environment')
        env.write_index(dest)
        # Generate client files against actual user cards/configuration, not the original generic defaults.
        team = module(dest / 'agents/公共/工具/团队/生成角色.py', 'sma_target_team')
        team.available_skills = lambda: None
        if safe(self.root, '.codex/config.toml').is_file():
            put(safe(dest, '.codex/config.toml'), safe(self.root, '.codex/config.toml').read_bytes())
        files, problems, _, _ = team.plan()
        if problems:
            raise UpdateError('；'.join(problems))
        owned = {'schema_version': 1, 'files': {}}
        for path, content in files.items():
            rel = path.relative_to(dest).as_posix()
            put(path, content.encode())
            owned['files'][rel] = sha(path)
        put(dest / GENERATION, owned)
        # Preserve settings; only replace this project's registered protection hook with target code's command.
        hooks = module(dest / 'agents/公共/工具/写入保护/hook_config.py', 'sma_target_hooks')
        rendered = hooks.render_hooks(self.root, python_executable=sys.executable, shell=args.hook_shell)
        for client, rel in [('codex', '.codex/hooks.json'), ('claude', '.claude/settings.json')]:
            if config['project']['client'] in {client, 'both'}:
                existing = read(safe(self.root, rel), read(source / '骨架' / rel, {}))
                put(safe(dest, rel), hooks.merge_hooks(existing, rendered[client]))
        flow = read(dest / FLOW)
        flow['packages']['project-video'] = config['delivery'].get('required_files', flow['packages']['project-video'])
        flow['project']['timezone'] = config['project'].get('timezone', 'Asia/Shanghai')
        put(dest / FLOW, flow)
        return plan, upstream

    def plan(self, to=None, source=None, development=False, allow_breaking=False):
        source, manifest = self.source(to, source, development)
        with coordinated(self.root, self.home):
            state = self.state()
            admission(self.root, self.home)
            self.remember_release(state, manifest)
            if release.version(manifest['version']) < release.version(state['version']):
                raise UpdateError('降级请使用最近事务 rollback，不跨版本重新铺装')
            if state['version'] not in manifest['upgrade_from']:
                raise UpdateError('发行未声明此版本的升级路径')
            if manifest.get('migrations'):
                raise UpdateError('此发行需要额外迁移器；当前协议不能自动执行')
            if (manifest.get('breaking') or release.version(state['version'])[0] != release.version(manifest['version'])[0]) and not allow_breaking:
                raise UpdateError('跨主版本或破坏性更新需要显式 --allow-breaking')
            identifier = uuid.uuid4().hex
            folder = safe(self.root, CONTROL + '/plans/' + identifier)
            stage = folder / 'stage'
            plan, upstream = self.render(source, stage, state)
            current_sources = read(self.root / 'agents/公共/技能来源.json')['sources']
            target_catalog = read(stage / 'agents/公共/技能来源.json')
            for name in read(stage / CONFIG)['skills']['required']:
                source_id = target_catalog['skills'][name]['source']
                previous_source = current_sources.get(source_id)
                target_source = target_catalog['sources'][source_id]
                if previous_source and any(previous_source.get(key) != target_source.get(key) for key in ('repository', 'package_root')):
                    raise UpdateError('来源身份或完整包边界发生变化，需先明确处理：' + source_id)
            desired = inventory(stage)
            changes, conflicts, observed = [], [], {}
            owned_clients = read(self.root / GENERATION, {}).get('files', {})
            client_paths = {p.replace('\\', '/') for p in owned_clients}
            candidates = set(desired) | {p for p in client_paths if p.startswith(('.claude/agents/', '.codex/agents/'))}
            for rel in sorted(candidates):
                if category(rel) == 'user':
                    if not safe(self.root, rel).exists() and ('/记忆/经验.md' in rel or rel.startswith('agents/项目/定制/')):
                        changes.append({'path': rel, 'before': None, 'after': desired[rel], 'kind': 'seed'})
                        observed[rel] = None
                    continue
                current = sha(safe(self.root, rel))
                observed[rel] = current
                target = desired.get(rel)
                base = state['baseline'].get(rel)
                if target is None:
                    # Only registered, unchanged obsolete client entries can leave discovery.
                    if current is not None and current == base:
                        changes.append({'path': rel, 'before': current, 'after': None, 'kind': 'retire'})
                    elif current is not None:
                        conflicts.append({'path': rel, 'reason': '旧客户端入口被用户修改，不能停用'})
                    continue
                if current == target:
                    continue
                structured = rel in {CONFIG, RECEIPT, GENERATION, 'agents/SKILLS_INDEX.md', '.claude/settings.json', '.codex/hooks.json', 'agents/项目/装配清单.json'}
                if not structured and current != base and current is not None:
                    if upstream.get(rel) == base:
                        continue
                    conflicts.append({'path': rel, 'reason': '用户和上游均有修改或文件未登记'})
                    if safe(self.root, rel).suffix in {'.md', '.yaml', '.json', '.toml', '.py'}:
                        diff = ''.join(difflib.unified_diff(safe(self.root, rel).read_text(encoding='utf-8').splitlines(True),
                            safe(stage, rel).read_text(encoding='utf-8').splitlines(True), fromfile='current/' + rel, tofile='target/' + rel))
                        put(safe(folder, 'diffs/' + rel + '.diff'), diff.encode())
                elif current is None and base is not None:
                    conflicts.append({'path': rel, 'reason': '受管文件被本地删除，保留用户选择'})
                else:
                    changes.append({'path': rel, 'before': current, 'after': target, 'kind': 'write'})
            value = {'id': identifier, 'created_at': now(), 'source': str(source), 'development': development,
                'manifest': manifest, 'from_release': state['release_id'], 'from_version': state['version'],
                'target_version': manifest['version'], 'changes': changes, 'conflicts': conflicts, 'observed': observed,
                'baseline': {**{p: h for p, h in desired.items() if category(p) != 'user'}, **{p: h for p, h in upstream.items() if category(p) == 'template'}},
                'stage_hashes': desired, 'roles': plan['roles'], 'phase': 'planned'}
            for change in changes:
                before_path = safe(self.root, change['path'])
                after_path = safe(stage, change['path'])
                change['before_mode'] = before_path.stat().st_mode & 0o777 if before_path.exists() else None
                change['after_mode'] = after_path.stat().st_mode & 0o777 if after_path.exists() else None
            put(folder / 'plan.json', value)
            self.save(state)
            return report('conflict' if conflicts else 'planned', state, target_version=manifest['version'],
                plan=identifier, changes=changes, blockers=conflicts, next_action='处理冲突并重新 plan' if conflicts else 'prepare --plan ' + identifier)

    def load_plan(self, identifier):
        if not identifier or not all(c in '0123456789abcdef' for c in identifier) or len(identifier) != 32:
            raise UpdateError('计划 ID 无效')
        folder = safe(self.root, CONTROL + '/plans/' + identifier)
        value = read(folder / 'plan.json')
        if not value or value['id'] != identifier:
            raise UpdateError('计划不存在')
        return folder, value

    def validate_plan(self, folder, plan):
        state = self.state()
        if state['release_id'] != plan['from_release']:
            raise UpdateError('当前版本已变化，请重新规划')
        if plan['conflicts']:
            raise UpdateError('计划存在冲突，不能部分应用')
        if fingerprint(release.verify(plan['source'], plan['development'])) != fingerprint(plan['manifest']):
            raise UpdateError('目标发行身份变化')
        if inventory(folder / 'stage') != plan['stage_hashes']:
            raise UpdateError('目标暂存内容变化，请重新规划')
        for rel, expected in plan['observed'].items():
            if sha(safe(self.root, rel)) != expected:
                raise UpdateError('规划后文件变化，请重新规划：' + rel)
        for change in plan['changes']:
            rel = change['path']
            seed = change['kind'] == 'seed' and change['before'] is None and ('/记忆/经验.md' in rel or rel.startswith('agents/项目/定制/'))
            if category(rel) == 'user' and not seed:
                raise UpdateError('更新计划试图修改用户数据：' + rel)
            if change['before'] != plan['observed'].get(rel):
                raise UpdateError('更新计划前置摘要不符：' + rel)
            if change['after'] != sha(safe(folder / 'stage', rel)):
                raise UpdateError('更新计划目标摘要不符：' + rel)
            if change['kind'] == 'retire' and not rel.startswith(('.codex/agents/', '.claude/agents/')):
                raise UpdateError('只能退役受管客户端入口')
        return state

    def environment(self, stage):
        tool = module(stage / 'agents/公共/工具/环境检查/检查环境.py', 'sma_verify_environment')
        options = {'home': self.home}
        if 'allow_ref_transition' in signature_tools.signature(tool.inspect).parameters:
            options['allow_ref_transition'] = True
        return tool.inspect(stage, **options)

    def prepare(self, identifier):
        with coordinated(self.root, self.home):
            folder, plan = self.load_plan(identifier)
            state = self.validate_plan(folder, plan)
            for rel in inventory(self.control / 'baseline'):
                put(safe(folder / 'previous-baseline', rel), safe(self.control / 'baseline', rel).read_bytes())
            for change in plan['changes']:
                if change['before'] is not None:
                    put(safe(folder / 'backup', change['path']), safe(self.root, change['path']).read_bytes())
            environment = self.environment(folder / 'stage')
            put(folder / 'environment.json', environment)
            plan['phase'] = 'prepared'
            put(folder / 'plan.json', plan)
            return report('prepared' if environment['ready'] else 'dependencies_pending', state,
                plan=identifier, target_version=plan['target_version'], changes=plan['changes'],
                evidence={'environment': environment}, next_action='apply' if environment['ready'] else 'Codex 读取暂存来源及安装说明，补齐依赖后重新 prepare')

    def checks(self):
        commands = ['agents/公共/工具/项目检查/检查.py', 'agents/公共/工具/团队/生成角色.py']
        evidence = []
        for rel in commands:
            args = [sys.executable, str(safe(self.root, rel))] + (['--check'] if rel.endswith('生成角色.py') else [])
            result = subprocess.run(args, cwd=self.root, capture_output=True, text=True,
                env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1', AI_SMA_HOME=str(self.home)))
            evidence.append({'tool': rel, 'returncode': result.returncode, 'output': (result.stdout + result.stderr)[-12000:]})
        return evidence

    def apply(self, identifier):
        with coordinated(self.root, self.home):
            folder, plan = self.load_plan(identifier)
            state = self.validate_plan(folder, plan)
            admission(self.root, self.home, allow_ready_dependency=True)
            if plan['phase'] != 'prepared':
                raise UpdateError('先 prepare，再 apply')
            busy = blockers(self.root, read(folder / 'stage' / FLOW))
            if busy:
                return report('waiting_idle', state, plan=identifier, blockers=busy)
            environment = self.environment(folder / 'stage')
            if not environment['ready']:
                return report('dependencies_pending', state, plan=identifier, evidence={'environment': environment})
            # Refresh receipts from measurements, not caller-provided success flags.
            tool = module(folder / 'stage/agents/公共/工具/环境检查/检查环境.py', 'sma_record_environment')
            environment['root'] = str(self.root)
            tool.record(folder / 'stage', environment)
            for rel in (RECEIPT, 'agents/SKILLS_INDEX.md'):
                after = sha(folder / 'stage' / rel)
                plan['changes'] = [c for c in plan['changes'] if c['path'] != rel]
                before = sha(self.root / rel)
                if before != after:
                    if before is not None:
                        put(safe(folder / 'backup', rel), safe(self.root, rel).read_bytes())
                    plan['changes'].append({'path': rel, 'before': before, 'after': after, 'kind': 'write'})
                plan['baseline'][rel] = after
                plan['stage_hashes'][rel] = after
            put(folder / 'plan.json', plan)
            transaction = {'id': identifier, 'phase': 'applying', 'previous': state, 'journal': [], 'started_at': now()}
            put(folder / 'transaction.json', transaction)
            state = copy.deepcopy(state)
            state['transaction'] = identifier
            self.save(state)
            try:
                for change in plan['changes']:
                    target = safe(self.root, change['path'])
                    if sha(target) != change['before']:
                        raise UpdateError('应用时文件改变：' + change['path'])
                    transaction['journal'].append(dict(change, state='intent'))
                    put(folder / 'transaction.json', transaction)
                    if change['after'] is None:
                        target.unlink()
                    else:
                        put(target, safe(folder / 'stage', change['path']).read_bytes())
                        if os.name != 'nt' and change.get('after_mode') is not None:
                            os.chmod(target, change['after_mode'])
                    transaction['journal'][-1]['state'] = 'done'
                    put(folder / 'transaction.json', transaction)
                evidence = self.checks()
                if any(e['returncode'] for e in evidence):
                    put(folder / 'checks.json', evidence)
                    raise UpdateError('更新后项目／客户端文件检查失败，恢复原版本')
                put(folder / 'checks.json', evidence)
                for rel, digest in plan['baseline'].items():
                    if safe(folder / 'stage', rel).is_file() and sha(safe(folder / 'stage', rel)) == digest:
                        put(safe(self.control / 'baseline', rel), safe(folder / 'stage', rel).read_bytes())
                reload_required = any(c['path'].startswith(('.codex/', '.claude/')) for c in plan['changes'])
                state.update(version=plan['target_version'], release_id=fingerprint(plan['manifest']),
                    baseline=plan['baseline'], installed_roles=plan['roles'], transaction=None,
                    last_transaction=identifier, client_pending=reload_required)
                transaction['phase'] = 'committed'
                transaction['finished_at'] = now()
                put(folder / 'transaction.json', transaction)
                self.save(state)
                register(self.root, self.home)
                self.release_reservations(identifier)
                return report('client_reload_required' if reload_required else 'updated', state, transaction=identifier,
                    evidence={'checks': evidence, 'skills_and_tools': 'verified', 'client_discovery': 'pending' if reload_required else 'unchanged', 'production_samples': 'not_verified'},
                    next_action='重载并以实际发现证据 verify-client' if reload_required else '重新读取角色说明后开始新执行段')
            except Exception as exc:
                transaction['error'] = str(exc)
                put(folder / 'transaction.json', transaction)
                result = self.restore(folder, plan, transaction)
                return report('apply_failed', self.state(), blockers=[str(exc)], recovery=result,
                              evidence={'checks': read(folder / 'checks.json', [])})

    def restore(self, folder, plan, transaction):
        problems = []
        # Check the complete restore set before modifying any file.
        for change in transaction['journal']:
            current = sha(safe(self.root, change['path']))
            if current not in {change['before'], change['after']}:
                problems.append('更新后出现其他修改：' + change['path'])
            if change['before'] is not None and sha(safe(folder / 'backup', change['path'])) != change['before']:
                problems.append('备份损坏：' + change['path'])
        if problems:
            transaction['phase'] = 'recovery_blocked'
            put(folder / 'transaction.json', transaction)
            state = self.state()
            state['transaction'] = transaction['id']
            self.save(state)
            return {'phase': 'recovery_blocked', 'blockers': problems}
        for change in reversed(transaction['journal']):
            target = safe(self.root, change['path'])
            if sha(target) == change['before']:
                continue
            if change['before'] is None:
                target.unlink()
            else:
                put(target, safe(folder / 'backup', change['path']).read_bytes())
                if os.name != 'nt' and change.get('before_mode') is not None:
                    os.chmod(target, change['before_mode'])
        # Restore saved baseline independently from current local edits.
        old_base = folder / 'previous-baseline'
        if old_base.exists():
            for rel in inventory(old_base):
                put(safe(self.control / 'baseline', rel), safe(old_base, rel).read_bytes())
        previous = copy.deepcopy(transaction['previous'])
        registry = read(machine(self.home) / 'registry.json', {})
        dependencies = [r for r in registry.get('reservations', {}).values()
                        if r.get('owner') == previous['project_id'] and r.get('plan') == transaction['id']]
        if dependencies and not self.environment(self.root)['ready']:
            previous['transaction'] = transaction['id']
            self.save(previous)
            transaction['phase'] = 'dependency_recovery_required'
            put(folder / 'transaction.json', transaction)
            return {'phase': 'dependency_recovery_required', 'blockers': ['旧版本文件已恢复；共享技能尚不兼容，按维护登记恢复并验证后 resume']}
        if transaction['phase'] == 'committed' and any(c['path'].startswith(('.codex/', '.claude/')) for c in transaction['journal']):
            previous['client_pending'] = True
        self.save(previous)
        transaction['phase'] = 'rolled_back'
        put(folder / 'transaction.json', transaction)
        register(self.root, self.home)
        self.release_reservations(transaction['id'])
        return {'phase': 'rolled_back'}

    def resume(self):
        with coordinated(self.root, self.home):
            state = self.state()
            if not state['transaction']:
                return report('nothing_to_resume', state)
            folder, plan = self.load_plan(state['transaction'])
            transaction = read(folder / 'transaction.json')
            # Interrupted updates always restore first; rerun planning against actual current state afterwards.
            return report('recovered', state, recovery=self.restore(folder, plan, transaction), next_action='重新 plan/prepare/apply')

    def rollback(self, identifier):
        with coordinated(self.root, self.home):
            state = self.state()
            if state['transaction'] or state['last_transaction'] != identifier:
                raise UpdateError('只支持最近已完成事务；先恢复进行中的更新')
            if blockers(self.root):
                raise UpdateError('存在执行或外部任务，不能回退')
            folder, plan = self.load_plan(identifier)
            transaction = read(folder / 'transaction.json')
            # Validate old dependency compatibility before restoring old template requirements.
            preview = folder / 'rollback-preview'
            if preview.exists():
                shutil.rmtree(preview)
            shutil.copytree(folder / 'stage', preview)
            for change in plan['changes']:
                target = safe(preview, change['path'])
                if change['before'] is not None:
                    put(target, safe(folder / 'backup', change['path']).read_bytes())
                elif target.exists():
                    target.unlink()
            if not self.environment(preview)['ready']:
                raise UpdateError('当前共享依赖不兼容旧版本；先按安装说明恢复并验证，不能仅回退回执')
            state['transaction'] = identifier
            self.save(state)
            return report('rollback', state, recovery=self.restore(folder, plan, transaction))

    def verify_client(self, evidence_path):
        with coordinated(self.root, self.home):
            state = self.state()
            path = safe(self.root, evidence_path)
            evidence = read(path)
            config = read(self.root / CONFIG)
            required_clients = {'codex', 'claude'} if config['project']['client'] == 'both' else {config['project']['client']}
            if not evidence or evidence.get('release_id') != state['release_id'] or set(evidence.get('clients', {})) != required_clients:
                raise UpdateError('发现证据缺少正确版本或客户端')
            for client, item in evidence['clients'].items():
                transcript = safe(self.root, item['transcript'])
                if sha(transcript) != item['sha256'] or item.get('method') not in {'live-client', 'live-agent'}:
                    raise UpdateError('需要实际客户端输出及匹配摘要')
                if not set(config['team']['roles']) <= set(item.get('roles', [])):
                    raise UpdateError('发现证据缺少已启用角色')
                if not set(config['skills']['required']) <= set(item.get('skills', [])):
                    raise UpdateError('发现证据缺少本项目技能')
            state['client_pending'] = False
            state['client_evidence'] = {'path': str(path.relative_to(self.root)), 'sha256': sha(path), 'at': now()}
            self.save(state)
            return report('client_verified', state, evidence=state['client_evidence'])

    def dependency_begin(self, identifier, source_id, ref, path, adopt_existing=False):
        folder, plan = self.load_plan(identifier)
        target_catalog = read(folder / 'stage/agents/公共/技能来源.json')
        target_source = target_catalog['sources'].get(source_id, {})
        versions = [target_source, *[dict(target_source, **v) for v in target_source.get('compatible_versions', [])]]
        target = next((v for v in versions if v.get('ref') == ref), None)
        required = read(folder / 'stage' / CONFIG)['skills']['required']
        if not target or not any(target_catalog['skills'][name]['source'] == source_id for name in required):
            raise UpdateError('维护来源不属于本计划的必需依赖或版本未获验证')
        package = Path(path).absolute()
        shared = self.home / '.agents/skills'
        try:
            safe(shared, package.relative_to(shared))
        except ValueError as exc:
            raise UpdateError('技能实体必须位于共享用途分类库内') from exc
        registry = read(machine(self.home) / 'registry.json', {})
        if package.exists() and str(package) not in registry.get('packages', {}) and not adopt_existing:
            raise UpdateError('此现有共享包尚未交由更新系统维护；保留原安装，明确接管后才可 --adopt-existing')
        previous = read(self.root / 'agents/公共/技能来源.json')['sources'].get(source_id)
        inspector = module(folder / 'stage/agents/公共/工具/环境检查/检查环境.py', 'sma_dependency_inspector')
        previous_version = None
        if package.exists():
            if not previous or previous.get('repository') != target.get('repository'):
                raise UpdateError('现有包来源不一致')
            for candidate in [previous, *[dict(previous, **v) for v in previous.get('compatible_versions', [])]]:
                if inspector.verify_package(package, candidate)['status'] == 'verified':
                    previous_version = candidate
                    break
            if not previous_version:
                raise UpdateError('现有共享包存在本地修改或来源不完整')
        reservation = reserve(self.root, source_id, ref, self.home)
        with coordinated(self.root, self.home):
            registry_path = safe(machine(self.home), 'registry.json')
            registry = read(registry_path)
            reservation.update(plan=identifier, path=str(package), target=target, previous=previous_version,
                backup=str(machine(self.home) / 'backups' / uuid.uuid4().hex), verified=False)
            reservation['consumers'] = sorted(set(reservation['consumers']) | {self.state()['project_id']})
            registry['reservations'][source_id] = reservation
            put(registry_path, registry)
        return report('dependency_reserved', self.state(), reservation=reservation,
            next_action='Codex 先保留完整旧包到 backup，再按公开说明安装到 path、维护索引及链接，最后 dependency-finish；本工具未执行安装')

    def dependency_finish(self, source_id, restore=False):
        with coordinated(self.root, self.home):
            state = self.state()
            path = safe(machine(self.home), 'registry.json')
            registry = read(path)
            reservation = registry.get('reservations', {}).get(source_id)
            if not reservation or reservation['owner'] != state['project_id']:
                raise UpdateError('没有本项目持有的技能维护登记')
            folder, plan = self.load_plan(reservation['plan'])
            inspector = module(folder / 'stage/agents/公共/工具/环境检查/检查环境.py', 'sma_dependency_finish')
            expected = reservation['previous'] if restore else reservation['target']
            if expected is None:
                raise UpdateError('新装包无需删除；验证当前版本后保留为可复用安装')
            proof = inspector.verify_package(Path(reservation['path']), expected)
            if proof['status'] != 'verified':
                raise UpdateError('技能实体校验失败：' + '；'.join(proof['errors']))
            if not restore and reservation['previous']:
                proof_backup = inspector.verify_package(Path(reservation['backup']), reservation['previous'])
                if proof_backup['status'] != 'verified':
                    raise UpdateError('旧技能完整备份尚未验证')
            registry.setdefault('packages', {})[reservation['path']] = {'source': source_id, 'ref': expected['ref'], 'digest': proof['digest']}
            if restore:
                del registry['reservations'][source_id]
            else:
                reservation['verified'] = True
            put(path, registry)
            return report('dependency_restored' if restore else 'dependency_verified', state,
                next_action='resume 后重新规划' if restore else '其他必需依赖就绪后 apply；切换前保留维护屏障')


def main(argv=None):
    if sys.version_info < (3, 11):
        print(json.dumps(report('runtime_required', blockers=['更新工具需要 Python 3.11 或更新版本'],
                                next_action='使用可用的新解释器重试；本次未修改项目'), ensure_ascii=False))
        return 2
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', default=str(Path.cwd()))
    parser.add_argument('--home', help='隔离测试主目录；默认使用当前用户')
    parser.add_argument('--json', action='store_true')
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('status', 'adopt', 'resume'):
        sub.add_parser(name)
    check = sub.add_parser('check')
    check.add_argument('--automatic', action='store_true')
    check.add_argument('--refresh', action='store_true')
    plan = sub.add_parser('plan')
    plan.add_argument('--to')
    plan.add_argument('--source', help='已校验的发行包展开目录')
    plan.add_argument('--allow-development', action='store_true', help='仅隔离开发验证使用')
    plan.add_argument('--allow-breaking', action='store_true')
    for name in ('prepare', 'apply'):
        sub.add_parser(name).add_argument('--plan', required=True)
    sub.add_parser('rollback').add_argument('--transaction', required=True)
    policy = sub.add_parser('policy')
    policy.add_argument('--mode', required=True, choices=['auto', 'notify', 'manual', 'frozen'])
    policy.add_argument('--pin')
    for name in ('begin', 'checkpoint', 'end'):
        p = sub.add_parser(name)
        p.add_argument('--task', required=True)
        p.add_argument('--owner', required=True)
    sub.add_parser('verify-client').add_argument('--evidence', required=True)
    # Shared-package reservations wrap human/agent execution; this CLI never installs packages.
    reserve_cmd = sub.add_parser('dependency-begin')
    reserve_cmd.add_argument('--plan', required=True)
    reserve_cmd.add_argument('--source', required=True)
    reserve_cmd.add_argument('--ref', required=True)
    reserve_cmd.add_argument('--path', required=True)
    reserve_cmd.add_argument('--adopt-existing', action='store_true')
    finish = sub.add_parser('dependency-finish')
    finish.add_argument('--source', required=True)
    finish.add_argument('--restore', action='store_true')
    for child in sub.choices.values():
        child.add_argument('--project', default=argparse.SUPPRESS)
        child.add_argument('--home', default=argparse.SUPPRESS)
        child.add_argument('--json', action='store_true', default=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    updater = Updater(args.project, args.home)
    try:
        if args.command == 'check':
            result = updater.check(args.automatic, args.refresh)
        elif args.command == 'plan':
            result = updater.plan(args.to, args.source, args.allow_development, args.allow_breaking)
        elif args.command in {'prepare', 'apply'}:
            result = getattr(updater, args.command)(args.plan)
        elif args.command == 'rollback':
            result = updater.rollback(args.transaction)
        elif args.command == 'policy':
            result = updater.policy(args.mode, args.pin)
        elif args.command in {'begin', 'checkpoint', 'end'}:
            result = execution(updater.root, args.command, args.task, args.owner, updater.home)
        elif args.command == 'verify-client':
            result = updater.verify_client(args.evidence)
        elif args.command == 'dependency-begin':
            result = updater.dependency_begin(args.plan, args.source, args.ref, args.path, args.adopt_existing)
        elif args.command == 'dependency-finish':
            result = updater.dependency_finish(args.source, args.restore)
        else:
            result = getattr(updater, args.command)()
    except (ValueError, OSError, KeyError, TypeError) as exc:
        result = report('error', blockers=[str(exc)], next_action='保留现状，根据阻塞原因处理后重试')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result['phase'] == 'error' else (2 if result['phase'] in {'conflict', 'dependencies_pending', 'waiting_idle', 'apply_failed', 'client_reload_required', 'check_unavailable', 'release_rejected', 'rate_limited'} else 0)


if __name__ == '__main__':
    sys.exit(main())
