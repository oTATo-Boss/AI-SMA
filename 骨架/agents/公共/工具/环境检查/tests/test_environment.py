import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('environment', Path(__file__).resolve().parents[1] / '检查环境.py')
environment = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(environment)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding='utf-8')


class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / '项目 空格'
        self.home = self.base / '用户'
        self.package = self.home / '.agents/skills/video/suite'
        self.entry = self.package / 'example'
        self.entry.mkdir(parents=True)
        (self.entry / 'SKILL.md').write_text('---\nname: example\ndescription: test\n---\nRead ../shared/rule.md.\n')
        (self.package / 'shared').mkdir()
        (self.package / 'shared/rule.md').write_text('Complete package resource.\n')
        files = {p.relative_to(self.package).as_posix(): {'blob': environment.blob_hash(p), 'mode': '100644'}
                 for p in self.package.rglob('*') if p.is_file()}
        self.registry = {'schema_version': 2, 'sources': {'test': {'repository': 'https://github.com/test/example', 'ref': 'a'*40,
                         'package_root': 'suite', 'license': 'MIT', 'files': files, 'status': 'ready'}},
                         'skills': {'example': {'name': 'example', 'source': 'test', 'entry': 'example/SKILL.md',
                         'requires': [], 'runtimes': [], 'clients': ['codex', 'claude'], 'status': 'ready'}}}
        write_json(self.root / 'agents/公共/技能来源.json', self.registry)
        self.config = {'schema_version': 2, 'project': {'client': 'codex'}, 'skills': {'required': ['example']}}
        self.save_config()
        write_json(self.root / 'agents/公共/工具/环境检查/依赖.json', {'tools': [], 'core': []})

    def tearDown(self):
        self.temp.cleanup()

    def save_config(self):
        write_json(self.root / 'agents/项目/项目配置.yaml', self.config)

    def inspect(self):
        return environment.inspect(self.root, home=self.home, check_tools=False)

    def test_complete_package_is_verified_but_discovery_is_not_claimed(self):
        result = self.inspect()
        self.assertTrue(result['files_ready'])
        self.assertFalse(result['ready'])
        self.assertEqual(result['skills']['example']['verification']['source'], 'verified')
        self.assertEqual(result['skills']['example']['clients']['codex']['discovery'], 'not_verified')

    def test_generated_index_binds_only_project_skills_and_preserves_user_notes(self):
        path = environment.write_index(self.root)
        before = path.read_text(encoding='utf-8')
        self.assertIn('not_verified', before)
        self.assertNotIn(str(self.entry), before)
        path.write_text(before + '\n用户的复用笔记。\n', encoding='utf-8')
        environment.record(self.root, self.inspect())
        after = path.read_text(encoding='utf-8')
        self.assertIn(str(self.entry.resolve()), after)
        self.assertIn('用户的复用笔记。', after)
        self.assertEqual(after.count('<!-- AI-SMA:skills:start -->'), 1)

    def test_missing_shared_resource_fails_even_with_skill_entry(self):
        (self.package / 'shared/rule.md').unlink()
        result = self.inspect()
        self.assertFalse(result['files_ready'])
        self.assertEqual(result['skills']['example']['status'], 'conflict')
        self.assertIn('缺资源', json.dumps(result, ensure_ascii=False))

    def test_same_name_modified_content_cannot_impersonate_source(self):
        (self.entry / 'SKILL.md').write_text('---\nname: example\n---\nOther provider instructions')
        result = self.inspect()
        self.assertEqual(result['skills']['example']['status'], 'conflict')
        self.assertIn('内容不同', json.dumps(result, ensure_ascii=False))

    def test_duplicate_entities_conflict(self):
        import shutil
        shutil.copytree(self.package, self.home / '.agents/skills/audio/suite')
        self.assertEqual(self.inspect()['skills']['example']['status'], 'conflict')

    def test_claude_link_must_resolve_to_exact_identity(self):
        self.config['project']['client'] = 'claude'
        self.save_config()
        fake = self.home / '.claude/skills/example'
        fake.mkdir(parents=True)
        (fake / 'SKILL.md').write_bytes((self.entry / 'SKILL.md').read_bytes())
        result = self.inspect()
        self.assertEqual(result['skills']['example']['clients']['claude']['entry_status'], 'missing_or_wrong_target')
        (fake / 'SKILL.md').unlink()
        fake.rmdir()
        try:
            fake.symlink_to(self.entry, target_is_directory=True)
        except OSError:
            self.skipTest('OS did not permit test symlink')
        result = self.inspect()
        self.assertTrue(result['files_ready'])
        self.assertEqual(result['skills']['example']['clients']['claude']['discovery'], 'not_verified')

    def test_unknown_client_fails(self):
        self.config['project']['client'] = 'unknown-client'
        self.save_config()
        result = self.inspect()
        self.assertFalse(result['ready'])
        self.assertIn('未知客户端', result['errors'][0])

    def test_forged_receipt_does_not_prove_source_or_discovery(self):
        write_json(self.root / 'agents/项目/安装回执.json', {'skills': {'example': {'path': str(self.entry),
                   'source': 'wrong-source', 'ref': 'a'*40, 'verification': {'files': 'verified'}, 'clients': {'codex': {'discovery': 'verified'}}}}})
        self.assertEqual(self.inspect()['skills']['example']['status'], 'conflict')

    def test_resource_escape_is_rejected(self):
        path = self.package / 'shared/rule.md'
        outside = self.base / 'outside.md'
        outside.write_bytes(path.read_bytes())
        path.unlink()
        try:
            path.symlink_to(outside)
        except OSError:
            self.skipTest('OS did not permit test symlink')
        result = self.inspect()
        self.assertFalse(result['files_ready'])
        self.assertIn('路径身份', json.dumps(result, ensure_ascii=False))

    def test_pending_source_does_not_become_ready_from_files(self):
        self.registry['sources']['test']['status'] = 'blocked'
        write_json(self.root / 'agents/公共/技能来源.json', self.registry)
        self.assertEqual(self.inspect()['skills']['example']['status'], 'blocked')

    def test_record_writes_actual_check_without_client_discovery(self):
        result = self.inspect()
        destination = environment.record(self.root, result)
        saved = json.loads(destination.read_text())
        self.assertEqual(saved['skills']['example']['digest'], result['skills']['example']['digest'])
        self.assertEqual(saved['client_discovery'], 'not_verified')

    def test_dependency_closure_and_cycle(self):
        ordered, errors = environment.closure(['a'], {'a': {'requires': ['b']}, 'b': {'requires': []}})
        self.assertEqual(ordered, ['b', 'a'])
        self.assertEqual(errors, [])
        _, errors = environment.closure(['a'], {'a': {'requires': ['b']}, 'b': {'requires': ['a']}})
        self.assertTrue(errors)

    def test_untracked_instruction_file_changes_package(self):
        (self.package / 'extra.py').write_text('print("unexpected")')
        self.assertFalse(self.inspect()['files_ready'])


if __name__ == '__main__':
    unittest.main()
