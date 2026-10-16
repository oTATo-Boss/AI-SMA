import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('assemble', ROOT / '新建项目.py')
MOD = importlib.util.module_from_spec(spec)
spec.loader.exec_module(MOD)

class AssemblyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ai-sma-tests-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def run_cli(self, dest, *args):
        return subprocess.run([sys.executable, str(ROOT / '新建项目.py'), '--dest', str(dest), *args], capture_output=True, text=True)

    def test_all_profiles_have_closed_roles_skills_and_valid_projects(self):
        definitions, roles = MOD.registry()
        self.assertEqual(len(definitions['profiles']), 9)
        self.assertEqual(len(roles), 24)
        for profile in definitions['profiles']:
            with self.subTest(profile=profile):
                dest = self.base / profile / '@测试'
                result = self.run_cli(dest, '--profile', profile, '--assemble-only')
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                config = MOD.read_json(dest / MOD.CONFIG)
                self.assertEqual(config['project']['profile'], profile)
                self.assertEqual((dest / 'agents/账号').exists(), profile == 'social-account')
                self.assertFalse((dest / 'agents/账号/账号配置.yaml').exists())
                actual = list((dest / 'agents/role').glob('*/agent.yaml'))
                self.assertEqual(len(actual), len(config['team']['roles']))
                check = subprocess.run([sys.executable, str(dest / 'agents/公共/工具/项目检查/检查.py')], capture_output=True, text=True)
                self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
                receipt = MOD.read_json(dest / 'agents/项目/安装回执.json')
                self.assertEqual(receipt['skills'], {})
                self.assertEqual(MOD.read_json(dest / MOD.STATE)['phase'], 'installation_pending')

    def test_plan_is_read_only_and_routes_union(self):
        dest = self.base / '混合工程'
        result = self.run_cli(dest, '--profile', 'film', '--route', 'ai', '--route', 'cg-3d', '--plan')
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(plan['routes'], ['ai', 'cg-3d'])
        self.assertIn('cg-artist', plan['roles'])
        self.assertIn('media-producer', plan['roles'])
        self.assertFalse(dest.exists())

    def test_resume_preserves_user_edits_and_rejects_forged_stage(self):
        dest = self.base / '@测试'
        result = self.run_cli(dest, '--profile', 'motion-design', '--assemble-only')
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        brief = dest / 'agents/项目/简报.md'
        brief.write_text('用户写的内容\n', encoding='utf-8')
        result = self.run_cli(dest, '--resume', '--assemble-only')
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(brief.read_text(encoding='utf-8'), '用户写的内容\n')
        (dest / '.ai-sma-deploy/stage/AGENTS.md').write_text('changed', encoding='utf-8')
        result = self.run_cli(dest, '--resume', '--assemble-only')
        self.assertEqual(result.returncode, 1)
        self.assertIn('暂存内容改变', result.stderr)

    def test_narrative_mv_and_3d_routes_have_actual_workflow(self):
        result = self.run_cli(self.base / 'story-mv', '--profile', 'music-video', '--variant', 'narrative', '--subtitles', '--plan')
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertIn('screenwriter', plan['roles'])
        self.assertIn('continuity-supervisor', plan['roles'])
        self.assertTrue({'script', 'script-review', 'continuity', 'subtitle'} <= {p['id'] for p in plan['workflow']['phases']})
        result = self.run_cli(self.base / '3d', '--profile', 'science', '--route', 'cg-3d', '--plan')
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertIn('cg-artist', plan['roles'])
        self.assertNotIn('motion-designer', plan['roles'])

    def test_no_overwrite_and_cross_platform_names(self):
        dest = self.base / 'existing'
        dest.mkdir()
        (dest / '用户.txt').write_text('keep', encoding='utf-8')
        result = self.run_cli(dest, '--assemble-only')
        self.assertEqual(result.returncode, 1)
        self.assertEqual((dest / '用户.txt').read_text(), 'keep')
        for name in ['CON', 'con.txt', 'LPT1', 'ending.', '../bad']:
            with self.assertRaises(ValueError):
                MOD.validate_name(name)
        MOD.validate_name('正常 项目')

    def test_optional_roles_and_single_execution(self):
        result = self.run_cli(self.base / 'quiet', '--profile', 'science', '--no-sound', '--no-subtitles', '--execution-mode', 'single', '--plan')
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertNotIn('voice-director', plan['roles'])
        self.assertNotIn('sound-designer', plan['roles'])
        self.assertNotIn('subtitle-editor', plan['roles'])
        self.assertEqual(plan['execution_mode'], 'single')

if __name__ == '__main__':
    unittest.main()
