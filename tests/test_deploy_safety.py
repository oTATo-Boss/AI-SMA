"""Deployment safety behavior; source installation is deliberately outside these isolated fixtures."""
import argparse
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('deploy_safety', ROOT / '新建项目.py')
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


class DeploymentSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ai-sma-safety-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.dest = self.base / '@测试'

    def plan(self, **changes):
        options = dict(profile='motion-design', route=None, form=None, voice=False, no_voice=False,
                       no_sound=False, subtitles=False, no_subtitles=False, name=None, dest=str(self.dest),
                       client='both', execution_mode='auto', platform=None, browser_profile=None)
        options.update(changes)
        # Exercise real assembly with catalog names while independent source publishing may still be pending.
        # This does not fake environment verification: assemble-only always records not_verified.
        with patch.object(MOD, 'skill_closure', side_effect=lambda names, catalog: sorted(set(names))):
            return MOD.build_plan(argparse.Namespace(**options))

    def assemble(self, plan=None, **options):
        with contextlib.redirect_stdout(io.StringIO()):
            return MOD.assemble(self.dest, plan or self.plan(), assemble_only=options.pop('assemble_only', True), **options)

    def read(self, relative):
        return json.loads((self.dest / relative).read_text(encoding='utf-8'))

    def make_link(self, link, target):
        link.parent.mkdir(parents=True, exist_ok=True)
        if os.name == 'nt':
            result = subprocess.run(['cmd', '/d', '/c', 'mklink', '/J', str(link), str(target)], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            link.symlink_to(target, target_is_directory=True)

    def test_existing_client_settings_are_merged_and_selected_client_is_respected(self):
        folder = self.dest / '.claude'
        folder.mkdir(parents=True)
        existing = {'model': 'user-choice', 'permissions': {'deny': ['Bash(custom)']},
                    'hooks': {'PreToolUse': [{'matcher': 'Read', 'hooks': [{'type': 'command', 'command': 'user-check'}]}]}}
        (folder / 'settings.json').write_text(json.dumps(existing), encoding='utf-8')
        self.assertEqual(self.assemble(self.plan(client='claude')), 2)
        actual = self.read('.claude/settings.json')
        self.assertEqual(actual['model'], existing['model'])
        self.assertEqual(actual['permissions'], existing['permissions'])
        commands = [hook['command'] for group in actual['hooks']['PreToolUse'] for hook in group['hooks']]
        self.assertIn('user-check', commands)
        self.assertTrue(any('hook_entry.py' in command for command in commands))
        self.assertFalse((self.dest / '.codex').exists())

    def test_resume_preserves_user_changed_generated_config_and_roles(self):
        self.assertEqual(self.assemble(), 2)
        path = self.dest / '.codex/config.toml'
        content = path.read_text(encoding='utf-8') + '\n# User setting\nmodel = "user-model"\n'
        path.write_text(content, encoding='utf-8')
        self.assertEqual(self.assemble(resume=True), 2)
        self.assertEqual(path.read_text(encoding='utf-8'), content)
        self.assertEqual(self.read(MOD.STATE)['phase'], 'installation_pending')
        # A user-created role file colliding with a generated name is preserved too.
        role = next((self.dest / '.claude/agents').glob('*.md'))
        role.write_text('User custom role\n', encoding='utf-8')
        self.assertEqual(self.assemble(resume=True), 1)
        self.assertEqual(role.read_text(encoding='utf-8'), 'User custom role\n')

    def test_owned_unchanged_outputs_can_be_regenerated_after_source_change(self):
        self.assertEqual(self.assemble(), 2)
        card = self.dest / 'agents/role/导演/agent.yaml'
        content = card.read_text(encoding='utf-8')
        line = next(line for line in content.splitlines() if line.startswith('description:'))
        card.write_text(content.replace(line, 'description: 已调整的导演职责'), encoding='utf-8')
        self.assertEqual(self.assemble(resume=True), 2)
        self.assertIn('已调整的导演职责', (self.dest / '.codex/agents/film-director.toml').read_text(encoding='utf-8'))
        self.assertIn('.codex/agents/film-director.toml', self.read('agents/项目/团队生成记录.json')['files'])

    def test_control_and_client_directory_links_do_not_write_outside_project(self):
        for name in ('.ai-sma-deploy', '.codex', '.claude'):
            with self.subTest(name=name):
                self.dest = self.base / name.replace('.', '') / '@测试'
                outside = self.base / ('outside-' + name)
                outside.mkdir()
                self.make_link(self.dest / name, outside)
                with self.assertRaisesRegex(ValueError, '链接'):
                    self.assemble()
                self.assertEqual(list(outside.iterdir()), [])

    def test_nested_client_junction_is_rejected_before_writing_role_files(self):
        outside = self.base / 'outside-agents'
        outside.mkdir()
        self.make_link(self.dest / '.claude/agents', outside)
        self.assertEqual(self.assemble(self.plan(client='claude')), 1)
        self.assertEqual(list(outside.iterdir()), [])

    def test_windows_drive_paths_are_rejected_in_deploy_manifests(self):
        for path in (r'C:\outside\file', r'C:relative', r'\\server\share\file', r'..\outside'):
            with self.assertRaises(ValueError):
                MOD.safe_target(self.dest, path)

    def test_disabled_stages_are_removed_and_dependencies_reconnected(self):
        plan = self.plan(profile='science', no_sound=True, no_subtitles=True)
        phases = {phase['id']: phase for phase in plan['workflow']['phases']}
        self.assertNotIn('sound', phases)
        self.assertNotIn('subtitle', phases)
        for phase in phases.values():
            self.assertTrue(set(phase['owners']) <= set(plan['roles']))
            self.assertTrue(set(phase['requires']) <= set(phases))
        self.assertIn('production', phases['edit']['requires'])
        self.assertIsNone(plan['video']['audio_codec'])
        config = MOD.project_config(plan)
        self.assertFalse(config['audio']['sound_enabled'])
        self.assertFalse(config['subtitles']['enabled'])

    def test_successful_file_checks_do_not_claim_client_or_runtime_ready(self):
        with patch.object(MOD, 'check', return_value=(0, 0)):
            self.assertEqual(self.assemble(assemble_only=False), 0)
        state = self.read(MOD.STATE)
        self.assertEqual(state['phase'], 'client_verification_pending')
        self.assertEqual(state['readiness']['skills_and_tools'], 'verified')
        self.assertEqual(state['readiness']['client_discovery'], 'not_verified')
        self.assertEqual(state['readiness']['runtime_samples'], 'not_verified')


if __name__ == '__main__':
    unittest.main()
