"""跨平台入口：运行核心行为测试，不安装技能、不生成收费媒体。"""
import os
import subprocess
import sys
from pathlib import Path
root = Path(__file__).resolve().parents[1]
folders = [root / 'tests', *sorted((root / '骨架/agents').rglob('tests'))]
failed = False
for folder in folders:
    result = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', str(folder), '-p', 'test_*.py', '-v'], cwd=root,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1'))
    failed |= bool(result.returncode)
sys.exit(int(failed))
