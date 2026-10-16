#!/usr/bin/env python3
"""AI-SMA update entrypoint. A pending transaction uses its verified pre-update runtime."""
import hashlib
import json
import re
import sys
from pathlib import Path

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, 'reconfigure'):
        stream.reconfigure(encoding='utf-8')

root = Path(__file__).resolve().parent
base = root / 'agents/公共/工具/更新'
arguments = list(sys.argv[1:])
installed = base.is_dir()
if not installed:
    base = root / '骨架/agents/公共/工具/更新'
project = root if installed else Path.cwd()
explicit = False
for index, argument in enumerate(arguments):
    if argument == '--project' and index + 1 < len(arguments):
        project = Path(arguments[index + 1]); explicit = True
    elif argument.startswith('--project='):
        project = Path(argument.split('=', 1)[1]); explicit = True
if installed and not explicit:
    arguments = ['--project', str(project), *arguments]
project = project.expanduser().resolve()
state_path = project / '.ai-sma-deploy/update/state.json'
try:
    if state_path.exists():
        if state_path.resolve() != state_path.absolute():
            raise ValueError('更新控制目录经过链接')
        state = json.loads(state_path.read_text(encoding='utf-8'))
        transaction = state.get('transaction')
        if transaction and installed:
            if not re.fullmatch(r'[0-9a-f]{32}', transaction):
                raise ValueError('更新事务 ID 无效')
            folder = project / '.ai-sma-deploy/update/plans' / transaction
            manifest_path = folder / 'recovery-runtime.json'
            if manifest_path.resolve() != manifest_path.absolute():
                raise ValueError('恢复清单经过链接')
            if manifest_path.exists():
                manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
                runtime = folder / 'recovery-runtime'
                if manifest.get('schema_version') != 1 or not {'sma_common.py', 'sma_coordination.py', 'sma_release.py', 'sma_update.py'} <= set(manifest.get('files', {})):
                    raise ValueError('恢复运行时清单不完整')
                for relative, digest in manifest['files'].items():
                    if not relative or relative.startswith('/') or chr(92) in relative or ':' in relative or '..' in Path(relative).parts:
                        raise ValueError('恢复运行时路径无效')
                    path = runtime / relative
                    if path.resolve() != path.absolute() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                        raise ValueError('恢复运行时文件损坏：' + relative)
                base = runtime
            elif installed:
                raise ValueError('旧事务没有恢复运行时，请从完整发行目录指定 --project 运行 resume')
except (ValueError, OSError, TypeError) as error:
    print(json.dumps({'phase': 'recovery_bootstrap_error', 'blockers': [str(error)]}, ensure_ascii=False))
    sys.exit(1)

sys.path.insert(0, str(base))
from sma_update import main

if __name__ == '__main__':
    sys.exit(main(arguments))
