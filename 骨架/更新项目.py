#!/usr/bin/env python3
"""AI-SMA 更新入口；仓库和已部署项目共用同一实现。"""
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
base = root / 'agents/公共/工具/更新'
if not base.is_dir():
    base = root / '骨架/agents/公共/工具/更新'
sys.path.insert(0, str(base))
from sma_update import main

if __name__ == '__main__':
    sys.exit(main())
