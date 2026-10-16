"""One lock order: machine registry -> project -> task. No package installation."""
import contextlib
import os
from pathlib import Path
from sma_common import CONTROL, CONFIG, FLOW, RECEIPT, UpdateError, fingerprint, lock, now, put, read, safe, sha


def machine(home=None):
    return safe(Path(home or os.environ.get('AI_SMA_HOME') or Path.home()).expanduser().resolve(), '.agents/ai-sma')


@contextlib.contextmanager
def coordinated(root, home=None):
    root = Path(root).resolve()
    base = machine(home)
    with lock(safe(base, 'registry.lock')):
        with lock(safe(root, CONTROL + '/project.lock')):
            yield base


def jobs(root):
    result = []
    for path in sorted((Path(root) / 'agents/工作').rglob('task.json')):
        safe(root, path.relative_to(root))
        task = read(path)
        for job in task.get('external_jobs', []):
            if job.get('status') not in {'succeeded', 'failed', 'cancelled'}:
                result.append({'task': task['id'], 'key': job.get('submission_key') or job.get('task_id'), 'status': job.get('status')})
    return result


def register(root, home=None):
    """Caller holds coordinated lock. Only dependency metadata is shared between projects."""
    state = read(Path(root) / CONTROL / 'state.json')
    if not state:
        return
    base = machine(home)
    registry = read(safe(base, 'registry.json'), {'schema_version': 1, 'projects': {}, 'reservations': {}})
    catalog = read(Path(root) / 'agents/公共/技能来源.json', {'skills': {}, 'sources': {}})
    config = read(Path(root) / CONFIG, {})
    receipt = read(Path(root) / RECEIPT, {}).get('skills', {})
    skills = {}
    for name in config.get('skills', {}).get('required', []):
        source_id = catalog['skills'].get(name, {}).get('source')
        source = catalog['sources'].get(source_id, {})
        skills[name] = {'source': source_id, 'path': receipt.get(name, {}).get('package_path'),
                        'ref': receipt.get(name, {}).get('ref'),
                        'accepted': [source.get('ref'), *[v['ref'] for v in source.get('compatible_versions', [])]]}
    registry['projects'][state['project_id']] = {'root': str(Path(root).resolve()), 'skills': skills,
        'leases': read(Path(root) / CONTROL / 'execution.json', {}).get('leases', {}),
        'external_pending': jobs(root), 'updated_at': now()}
    put(safe(base, 'registry.json'), registry)


def admission(root, home=None, allow_ready_dependency=False):
    state = read(Path(root) / CONTROL / 'state.json')
    if not state:
        return
    if state.get('transaction') or state.get('client_pending'):
        raise UpdateError('项目更新事务或客户端验证未完成，请先运行更新 status/resume')
    registry = read(machine(home) / 'registry.json', {})
    for reservation in registry.get('reservations', {}).values():
        if state['project_id'] in reservation['consumers']:
            if allow_ready_dependency and reservation['owner'] == state['project_id'] and reservation.get('verified'):
                continue
            raise UpdateError('共享技能正在维护，请先恢复并验证该操作')


def blockers(root, target_flow=None):
    runtime = read(Path(root) / CONTROL / 'execution.json', {'leases': {}, 'checkpoints': {}})
    result = [{'kind': 'active_execution', 'owner': k, 'task': v['task']} for k, v in runtime['leases'].items()]
    result += [{'kind': 'external_pending', **j} for j in jobs(root)]
    for path in sorted((Path(root) / 'agents/工作').rglob('task.json')):
        task = read(path)
        umbrella = isinstance(task.get('unit'), dict) and task['unit'].get('type') == 'project'
        if task.get('status') in {'结束', '取消'}:
            continue
        if target_flow:
            workflow = target_flow.get('workflows', {}).get(task['workflow'], {})
            phases = workflow.get('phases', [])
            names = [p['name'] if isinstance(p, dict) else p for p in phases]
            aliases = {p['id']: p['name'] for p in phases if isinstance(p, dict)}
            if task.get('phase') not in names:
                result.append({'kind': 'incompatible_checkpoint', 'task': task['id']})
                continue
            position = names.index(task['phase'])
            gates = {g.get('key'): g for g in task.get('gates', [])}
            incompatible = bool(workflow.get('requires_acceptance') and task.get('acceptance', {}).get('status') == '不适用')
            for gate in workflow.get('gates', []):
                before = aliases.get(gate['before_phase'], gate['before_phase'])
                current = gates.get(gate['key'])
                if not current or current.get('before_phase') != before or (before in names and position >= names.index(before) and current.get('decision') != 'approved'):
                    incompatible = True
            for requirement in workflow.get('required_checks', []):
                before = aliases.get(requirement['before_phase'], requirement['before_phase'])
                if before not in names or position < names.index(before):
                    continue
                accepted = any(c.get('name') == requirement['name'] and c.get('result') == 'passed' and c.get('evidence')
                    and (not requirement.get('requires_independent') or c.get('review_mode', task.get('review_mode')) == 'independent')
                    for c in task.get('checks', []))
                incompatible |= not accepted
            if incompatible:
                result.append({'kind': 'incompatible_contract', 'task': task['id']})
                continue
        if task.get('status') == '待开始' or umbrella:
            continue
        checkpoint = runtime['checkpoints'].get(task['id'])
        if not checkpoint or checkpoint.get('task_digest') != sha(path):
            result.append({'kind': 'checkpoint_required', 'task': task['id']})
    return result


def bind_context(root, task_id):
    """Caller holds project coordination; bind execution without rewriting historic task data."""
    root = Path(root)
    state = read(root / CONTROL / 'state.json')
    role_files = [*list((root / 'agents/role').rglob('AGENT.md')), *list((root / 'agents/role').rglob('agent.yaml')),
                  *list((root / 'agents/项目/定制').rglob('*.md')), root / 'AGENTS.md']
    context = {'version': state['version'], 'release_id': state['release_id'], 'workflow': read(root / FLOW),
        'roles_digest': fingerprint({p.relative_to(root).as_posix(): sha(p) for p in role_files}),
        'skills': read(root / RECEIPT, {}).get('skills', {})}
    context_id = fingerprint(context)
    put(safe(root, CONTROL + '/contexts/' + context_id + '.json'), context)
    bindings = read(root / CONTROL / 'task-contexts.json', {})
    bindings[task_id] = context_id
    put(safe(root, CONTROL + '/task-contexts.json'), bindings)
    return context_id


def execution(root, action, task_path, owner, home=None):
    root = Path(root).resolve()
    path = safe(root, task_path)
    if path.is_dir():
        path = safe(root, str(Path(task_path) / 'task.json'))
    if not path.is_relative_to(root / 'agents/工作'):
        raise UpdateError('执行登记只接受项目任务')
    with coordinated(root, home):
        state = read(root / CONTROL / 'state.json')
        if not state:
            raise UpdateError('先接入更新管理')
        runtime_path = safe(root, CONTROL + '/execution.json')
        runtime = read(runtime_path, {'leases': {}, 'checkpoints': {}, 'segments': []})
        task = read(path)
        if not task:
            raise UpdateError('任务不存在')
        if action == 'begin':
            admission(root, home)
            if owner in runtime['leases']:
                raise UpdateError('执行者已有未结束登记；先恢复或结束，不自动抢占')
            definition = read(root / FLOW)['workflows'].get(task['workflow'], {})
            names = {p['name'] if isinstance(p, dict) else p for p in definition.get('phases', [])}
            if task['phase'] not in names:
                raise UpdateError('当前流程不兼容此任务阶段，先处理检查点迁移')
            context_id = bind_context(root, task['id'])
            runtime['leases'][owner] = {'task': task['id'], 'context': context_id, 'started_at': now()}
            runtime['segments'].append(dict(runtime['leases'][owner], owner=owner))
        else:
            lease = runtime['leases'].get(owner)
            if lease and lease['task'] != task['id']:
                raise UpdateError('执行者与任务不匹配')
            others = any(v['task'] == task['id'] for k, v in runtime['leases'].items() if k != owner)
            pending = any(j['task'] == task['id'] for j in jobs(root))
            if action == 'checkpoint' and others:
                raise UpdateError('此任务仍有其他执行者，不能结束检查点')
            if action == 'checkpoint' and pending:
                raise UpdateError('外部任务未终结，不能关闭执行登记')
            if not task.get('next_action') and task.get('status') not in {'结束', '取消'}:
                raise UpdateError('检查点缺少下一步')
            runtime['leases'].pop(owner, None)
            if not others and not pending:
                runtime['checkpoints'][task['id']] = {'task_digest': sha(path), 'phase': task['phase'],
                    'next_action': task['next_action'], 'input_versions': task.get('input_versions', []), 'at': now()}
        put(runtime_path, runtime)
        register(root, home)
        return {'phase': 'execution_' + action, 'task': task['id'], 'owner': owner}


def reserve(root, source, target_ref, home=None):
    """Reserve an externally executed package change; no downloading, copying or installing."""
    with coordinated(root, home):
        register(root, home)
        state = read(Path(root) / CONTROL / 'state.json')
        registry_path = safe(machine(home), 'registry.json')
        registry = read(registry_path)
        consumers, problems = [state['project_id']], []
        for identifier, project in registry['projects'].items():
            uses = [s for s in project['skills'].values() if s['source'] == source]
            if not uses:
                continue
            if identifier not in consumers:
                consumers.append(identifier)
            if project['leases'] or project['external_pending']:
                problems.append('消费者存在执行中任务：' + identifier)
            if identifier != state['project_id'] and any(target_ref not in s['accepted'] for s in uses):
                problems.append('消费者不兼容目标版本：' + identifier)
        if source in registry['reservations']:
            problems.append('此来源已有维护登记')
        if problems:
            raise UpdateError('；'.join(problems))
        registry['reservations'][source] = {'owner': state['project_id'], 'consumers': consumers,
            'target_ref': target_ref, 'at': now()}
        put(registry_path, registry)
        return registry['reservations'][source]
