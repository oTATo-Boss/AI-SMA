#!/usr/bin/env python3
"""装配 AI-SMA 项目。技能和工具由部署智能体安装，本脚本不下载或调用包管理器。"""
import argparse
import copy
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path, PureWindowsPath

ROOT = Path(__file__).resolve().parent
SKELETON = ROOT / '骨架'
CONFIG = 'agents/项目/项目配置.yaml'
STATE = '.ai-sma-deploy/state.json'
IGNORE = {'__pycache__', '.DS_Store', '.git', 'node_modules', '.omc'}

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def write_json(path, value, base=None):
    path = Path(path)
    if base is not None:
        safe_target(base, path.relative_to(base))
        safe_target(base, path.with_name(path.name + '.tmp').relative_to(base))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(tmp, path)

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def registry():
    return read_json(ROOT / '模板/项目类型.json'), read_json(ROOT / '模板/角色.json')['roles']

def template_version():
    return read_json(ROOT / '发布.json')['version']

def alias(value, entries):
    for key, item in entries.items():
        if value in [key, item['name'], *item.get('aliases', [])]:
            return key
    raise ValueError(f'未知类型 {value}；可选：' + '、'.join(entries))

def card_skills(folder):
    text = (SKELETON / 'agents/role' / folder / 'agent.yaml').read_text(encoding='utf-8')
    match = re.search(r'^skills:\s*\[(.*?)\]', text, re.M)
    return [x.strip() for x in match.group(1).split(',') if x.strip()] if match else []

def skill_closure(names, catalog):
    result, visiting = set(), set()
    def visit(name):
        if name in visiting:
            raise ValueError('技能依赖成环：' + name)
        if name in result:
            return
        item = catalog['skills'].get(name)
        if item is None or item.get('status', 'ready') != 'ready':
            raise ValueError('技能未登记或尚不可部署：' + name)
        visiting.add(name)
        for dep in item.get('requires', []):
            visit(dep)
        visiting.remove(name)
        result.add(name)
    for name in sorted(set(names)):
        visit(name)
    return sorted(result)

def select_workflow(workflow, selected, route_owners, disabled):
    """Remove explicitly disabled stages and connect their prerequisites to the next retained stage."""
    result = copy.deepcopy(workflow)
    phases = {phase['id']: phase for phase in result['phases']}
    if len(phases) != len(result['phases']):
        raise ValueError('流程阶段编号重复')
    removed = set()
    for phase in result['phases']:
        owners = route_owners if phase.get('use_route_owners') else set(phase.get('owners', []))
        unknown = owners - selected - disabled
        if unknown:
            raise ValueError('流程负责人未装配：' + ', '.join(sorted(unknown)))
        phase['owners'] = sorted(owners & selected)
        if not phase['owners']:
            removed.add(phase['id'])
    def predecessors(identifier, visiting):
        if identifier in visiting or identifier not in phases:
            raise ValueError('流程依赖成环或缺失：' + identifier)
        if identifier not in removed:
            return [identifier]
        return [item for parent in phases[identifier].get('requires', [])
                for item in predecessors(parent, visiting | {identifier})]
    result['phases'] = [phase for phase in result['phases'] if phase['id'] not in removed]
    for phase in result['phases']:
        phase['requires'] = list(dict.fromkeys(item for parent in phase.get('requires', [])
                                               for item in predecessors(parent, {phase['id']})))
    return result

def build_plan(args):
    definitions, roles = registry()
    roles.update(getattr(args, 'custom_roles', {}))
    profile_id = alias(args.profile, definitions['profiles'])
    profile = copy.deepcopy(definitions['profiles'][profile_id])
    variant = getattr(args, 'variant', None)
    if variant and profile_id != 'music-video':
        raise ValueError('--variant 仅适用于 music-video')
    if variant == 'narrative':
        profile['roles'] += ['screenwriter', 'creative-critic', 'continuity-supervisor']
        phases = profile['workflow']['phases']
        index = next(i for i, phase in enumerate(phases) if phase['id'] == 'direction')
        previous = list(phases[index].get('requires', []))
        phases[index:index] = [
            dict(id='script', name='剧本', owners=['screenwriter'], requires=previous),
            dict(id='script-review', name='剧本评审', owners=['creative-critic'], requires=['script']),
            dict(id='continuity', name='连续性', owners=['continuity-supervisor'], requires=['script-review'])]
        phases[index + 3]['requires'] = ['continuity']
        profile['workflow'].setdefault('required_checks', []).append(dict(name='剧本评审', before_phase='direction'))
    elif variant == 'performance':
        profile['roles'].append('capture-director')
    elif variant == 'lyric':
        profile['roles'].append('subtitle-editor')
    default_routes = ['live-action'] if variant == 'performance' else profile.get('routes', [])
    routes = list(dict.fromkeys(alias(x, definitions['routes']) for x in (args.route or default_routes)))
    selected, skills, runtimes = set(profile['roles']), list(profile.get('skills', [])), set()
    route_owners, disabled = set(), set()
    if routes == ['cg-3d']:
        selected.discard('motion-designer')
        disabled.add('motion-designer')
    for route in routes:
        item = definitions['routes'][route]
        selected.update(item['roles'])
        route_owners.update(item['roles'])
        skills.extend(item.get('skills', []))
        runtimes.update(item.get('runtimes', []))
    form = args.form or profile.get('form', 'single')
    if form == 'series':
        selected.add('production-manager')
        if profile_id in {'film', 'series', 'music-video'}:
            selected.add('continuity-supervisor')
    if args.voice and not args.no_sound:
        selected.add('voice-director')
    if args.subtitles:
        selected.add('subtitle-editor')
    for flag, role in [(args.no_voice or args.no_sound, 'voice-director'), (args.no_subtitles, 'subtitle-editor'), (args.no_sound, 'sound-designer')]:
        if flag:
            selected.discard(role)
            disabled.add(role)
    inherited = sorted(selected)
    selected.update(getattr(args, 'role_include', []) or [])
    disabled.update(getattr(args, 'role_exclude', []) or [])
    selected.difference_update(disabled)
    phases = profile['workflow']['phases']
    if 'subtitle-editor' in selected and not any('subtitle-editor' in p.get('owners', []) for p in phases):
        index = next(i for i, p in enumerate(phases) if p['id'] == 'review')
        previous = phases[index].get('requires', [])
        phases.insert(index, dict(id='subtitle', name='字幕', owners=['subtitle-editor'], requires=previous))
        phases[index + 1]['requires'] = ['subtitle']
    if 'voice-director' in selected:
        for phase in phases:
            if phase['id'] == 'sound' and 'voice-director' not in phase['owners']:
                phase['owners'].append('voice-director')
    if selected - set(roles):
        raise ValueError('角色未登记：' + ', '.join(sorted(selected - set(roles))))
    catalog = read_json(SKELETON / 'agents/公共/技能来源.json')
    if args.client in {'claude', 'both'} and 'asset-designer' in selected:
        skills.append('codex-imagegen')
    for role in sorted(selected):
        skills.extend(roles[role]['skills'] if roles[role].get('custom') else card_skills(roles[role]['folder']))
    skills = skill_closure(skills, catalog)
    for name in skills:
        runtimes.update(catalog['skills'][name].get('runtimes', []))
    video = copy.deepcopy(profile.get('video', {}))
    delivery = copy.deepcopy(profile.get('delivery', {}))
    required_files = [delivery.get('video_filename', '视频.mp4'), '交付清单.json']
    if delivery.get('cover_required'):
        required_files.append('封面.png')
    if delivery.get('copy_required'):
        required_files.append('发布文案.txt')
    if delivery.get('include_source_project'):
        required_files.append('工程')
    if delivery.get('include_source_manifest'):
        required_files.append('来源清单.json')
    required_files.extend(delivery.get('additional_required_files', []))
    delivery['required_files'] = list(dict.fromkeys(required_files))
    if args.no_sound:
        video['audio_codec'] = None
    return dict(schema_version=2, template_version=template_version(), profile=profile_id,
        selection=dict(inherited_roles=inherited, role_include=getattr(args, 'role_include', []) or [],
                       role_exclude=getattr(args, 'role_exclude', []) or [], variant=variant),
        name=args.name or Path(args.dest).expanduser().name.lstrip('@'), form=form, routes=routes,
        roles=sorted(selected), skills=skills, runtimes=sorted(runtimes), client=args.client,
        execution_mode=args.execution_mode, platforms=[{'name': x} for x in args.platform] if args.platform else profile.get('platforms', []),
        variant=variant, video=video, delivery=delivery,
        workflow=select_workflow(profile['workflow'], selected, route_owners, disabled),
        audio=dict(sound_enabled=not args.no_sound, voice_enabled='voice-director' in selected),
        subtitles=dict(enabled='subtitle-editor' in selected),
        browser_profile=args.browser_profile, hook_shell=getattr(args, 'hook_shell', None), roles_map=roles)

def validate_name(name):
    if not name or name in {'.', '..'} or re.search(r'[\\/:*?"<>|\x00-\x1f]', name) or name.endswith((' ', '.')):
        raise ValueError('项目名为空或包含不支持的字符')
    if re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', name):
        raise ValueError('项目名是 Windows 保留名称')

def safe_target(dest, relative):
    dest = Path(dest)
    rel = Path(relative)
    foreign = PureWindowsPath(str(relative))
    if rel.is_absolute() or foreign.drive or '..' in rel.parts or '..' in foreign.parts:
        raise ValueError('部署清单含越界路径')
    target = dest / rel
    for path in [target, *target.parents]:
        if path == dest:
            break
        if path.is_symlink() or (path.exists() and path.resolve() != path.absolute()):
            raise ValueError('部署目标经过链接：' + str(relative))
    return target

def project_config(plan):
    return dict(schema_version=2,
        selection=plan.get('selection', {}), updates=dict(mode='auto', interval_hours=24, pin=None),
        project=dict(name=plan['name'], profile=plan['profile'], form=plan['form'], stage='开工中', language='zh-CN',
            timezone='Asia/Shanghai', client=plan['client'], browser_profile=plan['browser_profile'], hook_shell=plan.get('hook_shell'),
            goal='待填写：项目目标', audience='待填写：目标观众'),
        content=dict(production_routes=plan['routes']), platforms=plan['platforms'], video=plan['video'], delivery=plan['delivery'],
        autonomy=dict(max_parallel_agents=3, rework_rounds_max=2, network_commands=True),
        team=dict(roles=plan['roles'], execution_mode=plan['execution_mode']), skills=dict(required=plan['skills']),
        runtimes=plan['runtimes'], identity=dict(references=[], constraints=[]),
        audio=dict(**plan.get('audio', {}), voice_policy='无声' if not plan.get('audio', {}).get('sound_enabled', True)
                   else ('待填写：旁白要求' if plan.get('audio', {}).get('voice_enabled') else '无旁白')),
        subtitles=plan.get('subtitles', {}), isolation=dict(allowed_terms=[]))

def render_stage(stage, plan):
    folders = {plan['roles_map'][role]['folder'] for role in plan['roles']}
    for source in sorted(SKELETON.rglob('*')):
        if not source.is_file() or set(source.parts) & IGNORE or source.suffix == '.pyc':
            continue
        rel = source.relative_to(SKELETON)
        if rel.parts[:2] == ('agents', 'role') and rel.parts[2] not in folders:
            continue
        if rel.parts[:2] == ('agents', '账号') and (plan['profile'] != 'social-account' or rel.name == '账号配置.yaml'):
            continue
        if rel.parts[0] in {'.codex', '.claude'}:
            continue
        target = safe_target(stage, rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        if target.suffix in {'.md', '.yaml', '.json', '.txt'}:
            text = target.read_text(encoding='utf-8').replace('{{账号名}}', plan['name']).replace('{{项目名}}', plan['name'])
            text = text.replace('{{浏览器资料}}', plan['browser_profile'] or '待填写：需要平台登录时配置')
            if plan['profile'] == 'social-account':
                text = text.replace('agents/账号/账号配置.yaml', CONFIG)
            target.write_text(text, encoding='utf-8')
    write_json(stage / CONFIG, project_config(plan), stage)
    write_json(stage / 'agents/项目/装配清单.json', {k: v for k, v in plan.items() if k != 'roles_map'}, stage)
    write_json(stage / 'agents/项目/安装回执.json', dict(schema_version=2, skills={}, tools={}), stage)
    (stage / 'agents/SKILLS_INDEX.md').write_text('# 项目技能索引\n\n只登记本项目分配的技能，来源清单用于解析完整依赖。\n', encoding='utf-8')
    environment = load_module(stage / 'agents/公共/工具/环境检查/检查环境.py', 'assembly_environment')
    environment.write_index(stage)
    flow_path = stage / 'agents/role/总负责人/工具/任务管理/流程定义.json'
    flow = read_json(flow_path)
    workflow = plan['workflow']
    flow['workflows']['content'] = dict(label='项目制作', document='agents/role/总负责人/AGENT.md',
        phases=workflow['phases'], gates=[], required_checks=workflow.get('required_checks', []), requires_acceptance=True)
    flow['project']['timezone'] = 'Asia/Shanghai'
    flow['packages']['project-video'] = plan['delivery'].get('required_files', ['成片.mp4', '交付清单.json'])
    write_json(flow_path, flow, stage)
    for folder in folders:
        safe_target(stage, Path('agents/role') / folder / '记忆/记录').mkdir(parents=True, exist_ok=True)

def run_tool(dest, relative, *args):
    return subprocess.run([sys.executable, str(dest / relative), *args], cwd=dest,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1'), check=False).returncode

def check(dest):
    structural = run_tool(dest, 'agents/公共/工具/项目检查/检查.py')
    environment = run_tool(dest, 'agents/公共/工具/环境检查/检查环境.py')
    return structural, environment

def assemble(dest, plan, resume=False, assemble_only=False):
    state_path = safe_target(dest, STATE)
    if dest == ROOT or ROOT in dest.parents:
        raise ValueError('用户项目不能建在模板仓库内')
    if resume:
        if safe_target(dest, '.ai-sma-deploy/update/state.json').exists():
            raise ValueError('项目已接入更新管理；首次部署基线已封存，请使用 更新项目.py status/resume 或 新建项目.py --check')
        if not state_path.is_file():
            raise ValueError('没有本工具的部署记录，不能恢复')
        state = read_json(state_path)
        if state.get('destination') != str(dest):
            raise ValueError('部署记录的目标路径不匹配')
        plan = state['plan']
    else:
        if state_path.exists():
            raise ValueError('已有部署记录，请使用 --resume 或 --check')
        if (dest / '.ai-sma-deploy').exists():
            raise ValueError('已有未登记的 .ai-sma-deploy 目录，保留原内容')
        if dest.exists() and any(not p.name.startswith('.') for p in dest.iterdir()):
            raise ValueError('目标文件夹含已有内容，不覆盖；请使用空文件夹')
        validate_name(plan['name'])
        dest.mkdir(parents=True, exist_ok=True)
        state = dict(schema_version=2, destination=str(dest), phase='preparing', plan=plan, files={})
        write_json(state_path, state, dest)
    stage = safe_target(dest, '.ai-sma-deploy/stage')
    for client in (['codex', 'claude'] if plan['client'] == 'both' else [plan['client']]):
        safe_target(dest, '.' + client)
    if not state.get('expected'):
        stage.mkdir(parents=True, exist_ok=True)
        render_stage(stage, plan)
        state['expected'] = {str(p.relative_to(stage)): digest(p) for p in stage.rglob('*') if p.is_file()}
        write_json(state_path, state, dest)
    completed = state['phase'] in {'assembled', 'installation_pending', 'ready', 'checks_failed', 'client_verification_pending'}
    for rel, expected in state['expected'].items():
        target = safe_target(dest, rel)
        if target.exists() and digest(target) != expected and not (completed and rel in state['files']):
            raise ValueError('目标已有不同内容，保留原文件：' + rel)
        if digest(safe_target(stage, rel)) != expected:
            raise ValueError('部署暂存内容改变：' + rel)
    for rel, expected in state['expected'].items():
        target = safe_target(dest, rel)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(stage / rel, target)
        state['files'][rel] = expected
        write_json(state_path, state, dest)
    for folder in ('固定资产', '交付', '发布内容'):
        safe_target(dest, folder).mkdir(exist_ok=True)
    state['phase'] = 'assembled'
    write_json(state_path, state, dest)
    result = run_tool(dest, 'agents/公共/工具/团队/生成角色.py')
    if result:
        state['phase'] = 'checks_failed'
        write_json(state_path, state, dest)
        return result
    hook_path = dest / 'agents/公共/工具/写入保护/hook_config.py'
    if hook_path.exists():
        hooks_module = load_module(hook_path, 'hook_config')
        hooks = hooks_module.render_hooks(dest, python_executable=sys.executable, shell=plan.get('hook_shell'))
        for client, rel in [('codex', '.codex/hooks.json'), ('claude', '.claude/settings.json')]:
            if plan['client'] in {client, 'both'}:
                target = safe_target(dest, rel)
                existing = read_json(target) if target.exists() else read_json(SKELETON / rel)
                write_json(target, hooks_module.merge_hooks(existing, hooks[client]), dest)
                state.setdefault('client_files', {})[rel] = digest(target)
    run_tool(dest, 'agents/role/总负责人/工具/任务管理/任务管理.py', 'sync')
    structural, environment = (0, 1) if assemble_only else check(dest)
    state['phase'] = 'checks_failed' if structural else ('installation_pending' if environment else 'client_verification_pending')
    state['checks'] = dict(structure=None if assemble_only else structural, environment=None if assemble_only else environment)
    state['readiness'] = dict(structure='not_verified' if assemble_only else ('failed' if structural else 'verified'),
        skills_and_tools='not_verified' if assemble_only else ('incomplete' if environment else 'verified'),
        client_discovery='not_verified', services_and_models='not_verified', runtime_samples='not_verified')
    write_json(state_path, state, dest)
    if not assemble_only and structural == 0:
        updater_path = dest / 'agents/公共/工具/更新'
        sys.path.insert(0, str(updater_path))
        try:
            from sma_update import Updater
            Updater(dest).adopt()
        finally:
            sys.path.remove(str(updater_path))
    print(f"项目已装配：{dest}；状态：{state['phase']}")
    print('下一步：部署智能体读取 agents/公共/技能安装.md，安装并验证装配清单要求的技能及工具；本脚本未执行安装。')
    return 1 if structural else (2 if environment else 0)

def main(argv=None):
    if sys.version_info < (3, 11):
        print('AI-SMA v2.1 需要 Python 3.11 或更新版本；请由部署智能体选择实际可用解释器。', file=sys.stderr)
        return 2
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dest', default=str(Path.cwd()))
    parser.add_argument('--profile', default='social-account')
    parser.add_argument('--name')
    parser.add_argument('--variant', choices=['narrative', 'performance', 'lyric'])
    parser.add_argument('--form', choices=['single', 'series', 'account'])
    parser.add_argument('--route', action='append')
    parser.add_argument('--platform', action='append')
    parser.add_argument('--client', choices=['codex', 'claude', 'both'], default='both')
    parser.add_argument('--execution-mode', choices=['auto', 'multi', 'single'], default='auto')
    parser.add_argument('--browser-profile')
    parser.add_argument('--hook-shell', choices=['posix', 'powershell', 'cmd'], help='实际客户端运行钩子的 shell；默认按操作系统选择')
    parser.add_argument('--role-include', action='append', default=[])
    parser.add_argument('--role-exclude', action='append', default=[])
    for flag in ('voice', 'subtitles', 'no-voice', 'no-sound', 'no-subtitles', 'resume', 'check', 'plan', 'list', 'assemble-only'):
        parser.add_argument('--' + flag, action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.list:
            print(json.dumps(registry()[0], ensure_ascii=False, indent=2))
            return 0
        dest = Path(args.dest).expanduser().resolve()
        if args.check:
            structure, environment = check(dest)
            return 1 if structure else (2 if environment else 0)
        if args.voice and args.no_voice or args.subtitles and args.no_subtitles:
            raise ValueError('同一能力不能同时启用与关闭')
        plan = None if args.resume else build_plan(args)
        if args.plan:
            print(json.dumps(plan if plan else read_json(dest / STATE)['plan'], ensure_ascii=False, indent=2))
            return 0
        return assemble(dest, plan, args.resume, args.assemble_only)
    except (ValueError, OSError, KeyError) as exc:
        print(f'停止：{exc}', file=sys.stderr)
        return 1

if __name__ == '__main__':
    sys.exit(main())
