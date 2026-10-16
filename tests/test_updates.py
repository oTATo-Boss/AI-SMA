"""Real filesystem/CLI transactions with isolated fixture skills; no author installations or media services."""
import argparse
import contextlib
import copy
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '骨架/agents/公共/工具/更新'))
from sma_common import CONFIG, CONTROL, FLOW, RECEIPT, UpdateError, fingerprint, inventory, module, put, read, sha
from sma_update import Updater
from sma_coordination import execution, coordinated, register, reserve, admission, blockers
import sma_release


class UpdateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared = tempfile.TemporaryDirectory(prefix='sma-update-fixtures-')
        cls.fixture = Path(cls.shared.name) / 'repo'
        cls.fixture.mkdir()
        for item in sma_release.INPUTS:
            source = ROOT / item
            if source.is_dir():
                shutil.copytree(source, cls.fixture / item, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            else:
                shutil.copy2(source, cls.fixture / item)
        catalog_path = cls.fixture / '骨架/agents/公共/技能来源.json'
        catalog = read(catalog_path)
        cls.skill_files = {}
        for name, spec in catalog['skills'].items():
            if spec.get('status') != 'ready':
                continue
            cls.skill_files[name + '/SKILL.md'] = f'---\nname: {name}\ndescription: Isolated fixture.\n---\nFixture only.\n'.encode()
            spec.update(source='fixture', entry=name + '/SKILL.md', runtimes=[], requires=[], clients=['codex', 'claude'])
        cls.skill_files['LICENSE'] = b'Test fixture public domain\n'
        files = {path: {'blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest(), 'mode': '100644'} for path, data in cls.skill_files.items()}
        catalog['sources'] = {'fixture': {'repository': 'https://example.invalid/fixture', 'ref': 'a' * 40,
            'package_root': '.', 'license': 'CC0-1.0', 'license_files': {}, 'status': 'ready', 'files': files}}
        put(catalog_path, catalog)
        definitions = read(cls.fixture / '模板/项目类型.json')
        for route in definitions['routes'].values():
            route['runtimes'] = []  # Fixture validates update logic, not media software availability on CI hosts.
        put(cls.fixture / '模板/项目类型.json', definitions)
        meta = read(cls.fixture / '发布.json')
        meta['version'] = '2.0.0'
        put(cls.fixture / '发布.json', meta)
        subprocess.run(['git', 'init', '-q', str(cls.fixture)], check=True)
        subprocess.run(['git', 'add', '.'], cwd=cls.fixture, check=True)
        subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture'], cwd=cls.fixture, check=True)

    @classmethod
    def tearDownClass(cls):
        cls.shared.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='sma-update-test-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.home = self.base / 'home'
        self.project = self.base / '@测试 项目'
        self.repo = self.base / 'repo'
        shutil.copytree(self.fixture, self.repo, ignore=shutil.ignore_patterns('__pycache__'))
        self.env = patch.dict(os.environ, {'AI_SMA_HOME': str(self.home), 'PYTHONDONTWRITEBYTECODE': '1'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.assembly = module(self.repo / '新建项目.py', 'test_update_assembly')

    def deploy(self, profile='science', **kwargs):
        options = dict(profile=profile, form=None, route=None, platform=None, client='codex', execution_mode='single',
            name=None, dest=str(self.project), browser_profile=None, voice=False, no_voice=False, no_sound=False,
            subtitles=False, no_subtitles=False)
        options.update(kwargs)
        plan = self.assembly.build_plan(argparse.Namespace(**options))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assembly.assemble(self.project, plan, assemble_only=True)
        self.updater = Updater(self.project, self.home)
        self.updater.adopt()
        return plan

    def install(self):
        package = self.home / '.agents/skills/video/fixture'
        for rel, data in self.skill_files.items():
            put(package / rel, data)
        if read(self.project / CONFIG)['project']['client'] in {'claude', 'both'}:
            for name in read(self.project / CONFIG)['skills']['required']:
                entry = self.home / '.claude/skills' / name
                entry.parent.mkdir(parents=True, exist_ok=True)
                if not entry.exists():
                    if os.name == 'nt':
                        subprocess.run(['cmd', '/d', '/c', 'mklink', '/J', str(entry), str(package / name)], check=True, capture_output=True)
                    else:
                        entry.symlink_to(package / name, target_is_directory=True)
        tool = module(self.project / 'agents/公共/工具/环境检查/检查环境.py', 'fixture_inspector')
        result = tool.inspect(self.project, home=self.home)
        self.assertTrue(result['ready'], result)
        tool.record(self.project, result)

    def target(self, version='2.1.0', edit=True):
        meta = read(self.repo / '发布.json')
        meta['version'] = version
        put(self.repo / '发布.json', meta)
        if edit:
            path = self.repo / '骨架/agents/role/导演/AGENT.md'
            put(path, path.read_bytes() + b'\nUpdated direction method.\n')
        output = self.base / ('release-' + version)
        sma_release.build(self.repo, output, development=True)
        extracted = self.base / ('source-' + version)
        sma_release.unpack((output / sma_release.ASSET).read_bytes(), extracted, allow_development=True)
        return extracted

    def planned(self, **kwargs):
        result = self.updater.plan(source=self.target(**kwargs), development=True)
        self.assertEqual(result['phase'], 'planned', result)
        return result['plan']

    def test_dependency_missing_keeps_current_team(self):
        self.deploy()
        original = sha(self.project / 'agents/role/导演/AGENT.md')
        identifier = self.planned()
        self.assertEqual(self.updater.prepare(identifier)['phase'], 'dependencies_pending')
        self.assertEqual(self.updater.apply(identifier)['phase'], 'dependencies_pending')
        self.assertEqual(sha(self.project / 'agents/role/导演/AGENT.md'), original)
        self.assertEqual(self.updater.state()['version'], '2.0.0')

    def test_apply_and_rollback_preserve_user_files(self):
        self.deploy()
        self.install()
        for rel in ['交付/首版/video.mp4', 'agents/role/导演/记忆/经验.md', 'agents/项目/简报.md']:
            put(self.project / rel, b'User content unchanged.\n')
        original = {r: sha(self.project / r) for r in ['交付/首版/video.mp4', 'agents/role/导演/记忆/经验.md', 'agents/项目/简报.md']}
        old = sha(self.project / 'agents/role/导演/AGENT.md')
        identifier = self.planned()
        self.assertEqual(self.updater.prepare(identifier)['phase'], 'prepared')
        result = self.updater.apply(identifier)
        self.assertIn(result['phase'], {'updated', 'client_reload_required'}, result)
        self.assertEqual(self.updater.state()['version'], '2.1.0')
        self.assertNotEqual(sha(self.project / 'agents/role/导演/AGENT.md'), old)
        self.assertEqual(original, {r: sha(self.project / r) for r in original})
        result = self.updater.rollback(identifier)
        self.assertEqual(result['recovery']['phase'], 'rolled_back')
        self.assertEqual(self.updater.state()['version'], '2.0.0')
        self.assertEqual(sha(self.project / 'agents/role/导演/AGENT.md'), old)

    def test_local_prompt_conflict_blocks_entire_update(self):
        self.deploy()
        path = self.project / 'agents/role/导演/AGENT.md'
        put(path, path.read_bytes() + b'\nUser customization\n')
        result = self.updater.plan(source=self.target(), development=True)
        self.assertEqual(result['phase'], 'conflict')
        with self.assertRaises(UpdateError):
            self.updater.prepare(result['plan'])
        self.assertIn(b'User customization', path.read_bytes())

    def test_local_prompt_unchanged_upstream_is_retained(self):
        self.deploy()
        path = self.project / 'agents/role/编剧/AGENT.md'
        put(path, path.read_bytes() + b'\nUser customization\n')
        identifier = self.planned()
        _, plan = self.updater.load_plan(identifier)
        self.assertNotIn('agents/role/编剧/AGENT.md', [c['path'] for c in plan['changes']])

    def test_changes_after_planning_are_rejected(self):
        self.deploy()
        identifier = self.planned()
        config = read(self.project / CONFIG)
        config['project']['goal'] = 'New user goal'
        put(self.project / CONFIG, config)
        with self.assertRaisesRegex(UpdateError, '规划后文件变化'):
            self.updater.prepare(identifier)

    def test_failed_checks_restore_entire_transaction(self):
        self.deploy()
        self.install()
        identifier = self.planned()
        self.updater.prepare(identifier)
        old = sha(self.project / 'agents/role/导演/AGENT.md')
        with patch.object(self.updater, 'checks', return_value=[{'returncode': 1}]):
            result = self.updater.apply(identifier)
        self.assertEqual(result['recovery']['phase'], 'rolled_back')
        self.assertEqual(sha(self.project / 'agents/role/导演/AGENT.md'), old)
        self.assertIsNone(self.updater.state()['transaction'])

    def test_interrupted_write_is_recovered(self):
        self.deploy()
        self.install()
        identifier = self.planned()
        self.updater.prepare(identifier)
        import sma_update
        original = sma_update.put
        def interrupt(path, value):
            if str(path).endswith('transaction.json') and value.get('journal') and value['journal'][-1]['state'] == 'done':
                raise KeyboardInterrupt('simulated process exit')
            return original(path, value)
        with patch.object(sma_update, 'put', side_effect=interrupt), self.assertRaises(KeyboardInterrupt):
            self.updater.apply(identifier)
        self.assertEqual(self.updater.state()['transaction'], identifier)
        result = self.updater.resume()
        self.assertEqual(result['recovery']['phase'], 'rolled_back')

    def test_rollback_refuses_post_update_user_edit(self):
        self.deploy()
        self.install()
        identifier = self.planned()
        self.updater.prepare(identifier)
        self.assertIn(self.updater.apply(identifier)['phase'], {'updated', 'client_reload_required'})
        path = self.project / 'agents/role/导演/AGENT.md'
        put(path, path.read_bytes() + b'\nNew user work\n')
        result = self.updater.rollback(identifier)
        self.assertEqual(result['recovery']['phase'], 'recovery_blocked')
        self.assertIn(b'New user work', path.read_bytes())

    def test_offline_check_is_throttled_and_no_role_changes(self):
        self.deploy()
        with patch('sma_release.releases', side_effect=OSError('offline')) as request:
            self.assertEqual(self.updater.check(automatic=True)['phase'], 'check_unavailable')
            self.assertEqual(self.updater.check(automatic=True)['phase'], 'check_cached')
            self.assertEqual(request.call_count, 1)

    def test_v1_and_broken_baselines_refused(self):
        self.project.mkdir()
        with self.assertRaisesRegex(UpdateError, 'v1'):
            Updater(self.project, self.home).adopt()
        with self.assertRaises(UpdateError):
            Updater(self.project, self.home).check()
        self.assertFalse(list(self.project.iterdir()))
        self.assertFalse(self.home.exists())

    def test_release_tamper_and_zip_escape_rejected(self):
        source = self.target()
        put(source / '新建项目.py', b'changed')
        with self.assertRaises(UpdateError):
            sma_release.verify(source, True)
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as archive:
            archive.writestr('../escape', b'no')
        with self.assertRaises(UpdateError):
            sma_release.unpack(data.getvalue(), self.base / 'bad')
        self.assertFalse((self.base / 'escape').exists())

    def test_nine_profiles_preserve_choices_and_resolve_update(self):
        for profile in self.assembly.registry()[0]['profiles']:
            with self.subTest(profile=profile):
                meta = read(self.repo / '发布.json')
                meta['version'] = '2.0.0'
                put(self.repo / '发布.json', meta)
                self.project = self.base / ('@测试-' + profile)
                self.deploy(profile, no_sound=True, no_subtitles=True)
                self.install()
                config = read(self.project / CONFIG)
                config['video']['width_px'] = 1234
                config['project']['goal'] = 'User approved goal'
                put(self.project / CONFIG, config)
                source = self.target(edit=False) if not (self.base / 'source-2.1.0').exists() else self.base / 'source-2.1.0'
                result = self.updater.plan(source=source, development=True)
                self.assertEqual(result['phase'], 'planned', result)
                folder, _ = self.updater.load_plan(result['plan'])
                target = read(folder / 'stage' / CONFIG)
                self.assertEqual(target['video']['width_px'], 1234)
                self.assertEqual(target['project']['goal'], 'User approved goal')
                self.assertNotIn('voice-director', target['team']['roles'])
                self.assertNotIn('subtitle-editor', target['team']['roles'])
                self.assertEqual(self.updater.prepare(result['plan'])['phase'], 'prepared')
                applied = self.updater.apply(result['plan'])
                self.assertIn(applied['phase'], {'updated', 'client_reload_required'}, applied)

    def task(self):
        tool = module(self.project / 'agents/role/总负责人/工具/任务管理/任务管理.py', 'fixture_tasks')
        workspace = tool.Workspace(self.project)
        task, path = workspace.new('制作验证', 'maintenance', '检查更新', ['检查完成'], 'test')
        return tool, workspace, task, path

    def test_execution_leases_block_update_and_children_can_end_individually(self):
        self.deploy()
        self.install()
        _, _, task, path = self.task()
        execution(self.project, 'begin', path, 'parent', self.home)
        execution(self.project, 'begin', path, 'child', self.home)
        identifier = self.planned()
        self.updater.prepare(identifier)
        self.assertEqual(self.updater.apply(identifier)['phase'], 'waiting_idle')
        execution(self.project, 'end', path, 'child', self.home)
        self.assertEqual(self.updater.apply(identifier)['phase'], 'waiting_idle')
        execution(self.project, 'checkpoint', path, 'parent', self.home)
        self.assertIn(self.updater.apply(identifier)['phase'], {'updated', 'client_reload_required'})

    def test_update_lock_blocks_new_tasks(self):
        self.deploy()
        tool, workspace, _, _ = self.task()
        state = self.updater.state()
        state['transaction'] = 'a' * 32
        self.updater.save(state)
        with self.assertRaisesRegex(tool.TaskError, '事务'):
            workspace.new('被阻挡', 'maintenance', 'x', ['x'], 'x')

    def test_external_unknown_state_blocks_checkpoint(self):
        self.deploy()
        _, _, task, path = self.task()
        execution(self.project, 'begin', path, 'parent', self.home)
        task['external_jobs'] = [{'tool': 'fixture', 'task_id': None, 'status': 'unknown', 'record': 'pending'}]
        put(self.project / path, task)
        with self.assertRaisesRegex(UpdateError, '外部任务'):
            execution(self.project, 'checkpoint', path, 'parent', self.home)

    def test_explicit_disabled_role_is_not_reintroduced(self):
        self.deploy()
        config = read(self.project / CONFIG)
        config['team']['roles'].remove('storyboard-artist')
        put(self.project / CONFIG, config)
        identifier = self.planned()
        folder, plan = self.updater.load_plan(identifier)
        self.assertNotIn('storyboard-artist', read(folder / 'stage' / CONFIG)['team']['roles'])
        self.assertIn('.codex/agents/storyboard-artist.toml', [c['path'] for c in plan['changes'] if c['kind'] == 'retire'])

    def test_compatible_package_is_reused_with_real_version(self):
        self.deploy()
        self.install()
        path = self.project / 'agents/公共/技能来源.json'
        catalog = read(path)
        source = catalog['sources']['fixture']
        previous = copy.deepcopy(source)
        previous['compatibility_evidence'] = ['fixture integration proof']
        source['ref'] = 'b' * 40
        source['files']['LICENSE']['blob'] = 'c' * 40
        source['compatible_versions'] = [previous]
        put(path, catalog)
        inspector = module(self.project / 'agents/公共/工具/环境检查/检查环境.py', 'compatible_fixture')
        result = inspector.inspect(self.project, home=self.home)
        self.assertTrue(result['ready'], result)
        self.assertTrue(all(row['ref'] == 'a' * 40 for row in result['skills'].values()))
        self.assertTrue(all(row['preferred_ref'] == 'b' * 40 for row in result['skills'].values()))
        inspector.record(self.project, result)
        self.assertIn('fixture@' + 'a' * 40, (self.project / 'agents/SKILLS_INDEX.md').read_text())

    def test_other_project_incompatible_consumer_prevents_package_change(self):
        self.deploy()
        self.install()
        with coordinated(self.project, self.home):
            register(self.project, self.home)
        first = self.project
        self.project = self.base / '@另一个测试'
        self.deploy()
        self.install()
        with coordinated(self.project, self.home):
            register(self.project, self.home)
        with self.assertRaisesRegex(UpdateError, '不兼容'):
            reserve(first, 'fixture', 'b' * 40, self.home)

    def test_shared_install_reservation_is_verified_and_released_on_commit(self):
        self.deploy()
        identifier = self.planned()
        self.updater.prepare(identifier)
        package = self.home / '.agents/skills/video/fixture'
        self.updater.dependency_begin(identifier, 'fixture', 'a' * 40, str(package))
        with self.assertRaisesRegex(UpdateError, '共享技能'):
            with coordinated(self.project, self.home):
                admission(self.project, self.home)
        # The operator performs installation, never the updater.
        for rel, data in self.skill_files.items():
            put(package / rel, data)
        self.assertEqual(self.updater.dependency_finish('fixture')['phase'], 'dependency_verified')
        self.assertIn(self.updater.apply(identifier)['phase'], {'updated', 'client_reload_required'})
        registry = read(self.home / '.agents/ai-sma/registry.json')
        self.assertFalse(registry['reservations'])

    def test_same_version_changed_manifest_is_refused(self):
        self.deploy()
        source = self.target()
        self.updater.plan(source=source, development=True)
        manifest = read(source / sma_release.MANIFEST)
        manifest['summary'] = 'Replaced identity'
        put(source / sma_release.MANIFEST, manifest)
        with self.assertRaisesRegex(UpdateError, '提交或摘要'):
            self.updater.plan(source=source, development=True)

    def test_symlink_managed_destination_rejected(self):
        self.deploy()
        directory = self.project / 'agents/role/导演'
        outside = self.base / 'outside'
        directory.rename(outside)
        if os.name == 'nt':
            subprocess.run(['cmd', '/d', '/c', 'mklink', '/J', str(directory), str(outside)], check=True, capture_output=True)
        else:
            directory.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(UpdateError, '链接'):
            self.updater.plan(source=self.target(), development=True)

    def test_new_applicable_role_is_seeded_and_requires_client_reload(self):
        self.deploy(client='both')
        self.install()
        definitions = read(self.repo / '模板/项目类型.json')
        definitions['profiles']['science']['roles'].append('production-manager')
        put(self.repo / '模板/项目类型.json', definitions)
        identifier = self.planned()
        self.updater.prepare(identifier)
        result = self.updater.apply(identifier)
        self.assertEqual(result['phase'], 'client_reload_required', result)
        folder = read(self.repo / '模板/角色.json')['roles']['production-manager']['folder']
        self.assertTrue((self.project / 'agents/role' / folder / '记忆/经验.md').is_file())
        self.assertTrue((self.project / '.claude/agents/production-manager.md').is_file())
        with coordinated(self.project, self.home), self.assertRaisesRegex(UpdateError, '客户端'):
            admission(self.project, self.home)

    def test_historical_contract_snapshot_survives_current_flow_changes(self):
        self.deploy()
        _, workspace, task, path = self.task()
        self.assertFalse(workspace.validate(task)[0])
        workspace.definition['workflows']['maintenance']['phases'] = ['全新阶段']
        self.assertFalse(workspace.validate(task)[0])

    def test_user_custom_role_and_project_overrides_are_preserved(self):
        self.deploy()
        custom = self.project / 'agents/role/项目专属评审'
        shutil.copytree(self.project / 'agents/role/导演', custom)
        card = custom / 'agent.yaml'
        text = card.read_text().replace('id: film-director', 'id: local-reviewer')
        put(card, text.encode())
        config = read(self.project / CONFIG)
        config['team']['roles'].append('local-reviewer')
        put(self.project / CONFIG, config)
        override = self.project / 'agents/项目/定制/角色/film-director.md'
        put(override, '使用克制的镜头语言。\n'.encode())
        identifier = self.planned()
        folder, _ = self.updater.load_plan(identifier)
        self.assertIn('local-reviewer', read(folder / 'stage' / CONFIG)['team']['roles'])
        self.assertEqual((folder / 'stage/agents/项目/定制/角色/film-director.md').read_bytes(), override.read_bytes())

    def test_manipulated_plan_cannot_write_deliveries(self):
        self.deploy()
        identifier = self.planned()
        folder, plan = self.updater.load_plan(identifier)
        plan['changes'].append({'path': '交付/old.mp4', 'before': None, 'after': None, 'kind': 'write'})
        put(folder / 'plan.json', plan)
        with self.assertRaisesRegex(UpdateError, '用户数据'):
            self.updater.prepare(identifier)

    def test_tls_fallback_preserves_certificate_verification(self):
        import ssl
        import urllib.error
        error = urllib.error.URLError(ssl.SSLCertVerificationError('missing Python CA store'))
        result = subprocess.CompletedProcess([], 0, b'[]\n200', b'')
        with patch('sma_release.urllib.request.urlopen', side_effect=error), patch('sma_release.shutil.which', return_value='/usr/bin/curl'), patch('sma_release.subprocess.run', return_value=result) as request:
            self.assertEqual(sma_release.get('https://api.github.com/repos/oTATo-Boss/AI-SMA/releases'), b'[]')
            args = request.call_args.args[0]
            self.assertNotIn('-k', args)
            self.assertIn('--proto-redir', args)
            self.assertEqual(args[1], '-q')

    def test_corrupt_archive_is_a_structured_validation_error(self):
        with self.assertRaisesRegex(UpdateError, '归档损坏'):
            sma_release.unpack(b'not a zip', self.base / 'invalid-release')

    def test_http_rate_limit_remains_distinct_with_system_tls(self):
        import ssl
        import urllib.error
        self.deploy()
        error = urllib.error.URLError(ssl.SSLCertVerificationError('missing CA store'))
        result = subprocess.CompletedProcess([], 22, b'\n429', b'Rate limit')
        with patch('sma_release.urllib.request.urlopen', side_effect=error), patch('sma_release.shutil.which', return_value='/usr/bin/curl'), patch('sma_release.subprocess.run', return_value=result):
            self.assertEqual(self.updater.check()['phase'], 'rate_limited')

    def test_cli_timeout_is_reported_without_traceback(self):
        from sma_update import main
        output = io.StringIO()
        with patch.object(Updater, 'prepare', side_effect=subprocess.TimeoutExpired('fixture', 15)), contextlib.redirect_stdout(output):
            self.assertEqual(main(['--project', str(self.project), 'prepare', '--plan', 'a' * 32]), 1)
        self.assertEqual(json.loads(output.getvalue())['phase'], 'error')

    def test_network_check_releases_writer_locks_and_preserves_new_policy(self):
        self.deploy()
        def remote():
            self.updater.policy('frozen')
            return []
        with patch('sma_release.releases', side_effect=remote):
            self.assertEqual(self.updater.check()['phase'], 'check_stale')
        self.assertEqual(read(self.project / CONFIG)['updates']['mode'], 'frozen')

    def test_corrupt_original_baseline_prevents_adoption(self):
        self.deploy()
        shutil.rmtree(self.project / CONTROL)
        put(self.project / '.ai-sma-deploy/stage/AGENTS.md', b'corrupted')
        with self.assertRaisesRegex(UpdateError, '基线损坏'):
            self.updater.adopt()

    def test_other_process_cannot_enter_locked_transaction(self):
        self.deploy()
        self.install()
        identifier = self.planned()
        self.updater.prepare(identifier)
        with coordinated(self.project, self.home):
            result = subprocess.run([sys.executable, str(self.project / '更新项目.py'), '--project', str(self.project),
                '--home', str(self.home), 'apply', '--plan', identifier], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('占用锁', result.stdout)
        self.assertEqual(self.updater.state()['version'], '2.0.0')

    def test_legacy_baseline_can_adopt_first_stable_of_same_version(self):
        self.deploy()
        source = self.target()
        manifest = read(source / sma_release.MANIFEST)
        state = self.updater.state()
        state['version'] = '2.1.0'
        self.updater.save(state)
        with patch('sma_release.releases', return_value=[{'tag_name': 'v2.1.0'}]), patch('sma_release.fetch', return_value=(source, manifest)):
            self.assertEqual(self.updater.check()['phase'], 'update_available')

    def test_rollback_supports_v2_inspector_signature(self):
        from types import SimpleNamespace
        self.deploy()
        def legacy_inspect(root, *, home=None):
            return {'ready': home == self.home}
        with patch('sma_update.module', return_value=SimpleNamespace(inspect=legacy_inspect)):
            self.assertTrue(self.updater.environment(self.project)['ready'])

    def test_legacy_windows_crlf_generated_files_are_not_user_conflicts(self):
        self.deploy()
        shutil.rmtree(self.project / CONTROL)
        client = self.project / '.codex/agents/film-director.toml'
        client.write_bytes(client.read_bytes().replace(b'\r\n', b'\n').replace(b'\n', b'\r\n'))
        self.updater.adopt()
        self.assertEqual(self.updater.state()['baseline']['.codex/agents/film-director.toml'], sha(client))
        self.planned()

    def test_pending_and_parent_tasks_still_require_compatible_contracts(self):
        self.deploy()
        _, _, task, path = self.task()
        flow = read(self.project / FLOW)
        flow['workflows']['maintenance']['phases'] = ['不同阶段']
        self.assertIn('incompatible_checkpoint', [b['kind'] for b in blockers(self.project, flow)])
        task['unit'] = {'type': 'project', 'id': 'parent'}
        put(self.project / path, task)
        flow = read(self.project / FLOW)
        flow['workflows']['maintenance']['gates'] = [{'key': 'new-gate', 'before_phase': task['phase']}]
        self.assertIn('incompatible_contract', [b['kind'] for b in blockers(self.project, flow)])

    def test_rollback_refuses_incompatible_new_pending_task(self):
        self.deploy()
        self.install()
        path = self.repo / '骨架' / FLOW
        flow = read(path)
        flow['workflows']['maintenance']['phases'].insert(0, '新增阶段')
        put(path, flow)
        identifier = self.planned()
        self.updater.prepare(identifier)
        self.assertIn(self.updater.apply(identifier)['phase'], {'updated', 'client_reload_required'})
        # Client evidence is tested independently; simulate its completion in this rollback fixture.
        state = self.updater.state();state['client_pending'] = False;self.updater.save(state)
        self.task()
        with self.assertRaisesRegex(UpdateError, '不兼容'):
            self.updater.rollback(identifier)
        self.assertEqual(self.updater.state()['version'], '2.1.0')


if __name__ == '__main__':
    unittest.main()
