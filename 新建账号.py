#!/usr/bin/env python3
"""兼容入口：以 AI-SMA v2 社媒账号模板装配项目。"""
import importlib.util
import sys
from pathlib import Path

def main():
    spec = importlib.util.spec_from_file_location('ai_sma_project', Path(__file__).with_name('新建项目.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.main(['--profile', 'social-account', *sys.argv[1:]])

if __name__ == '__main__':
    sys.exit(main())
