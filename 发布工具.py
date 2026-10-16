#!/usr/bin/env python3
"""生成发行资产；不提交、推送或发布。"""
import argparse
import json
import sys
from pathlib import Path
root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / '骨架/agents/公共/工具/更新'))
from sma_release import build

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--development', action='store_true', help='只用于隔离测试；稳定更新拒绝此包')
    args = parser.parse_args()
    print(json.dumps(build(root, args.output, args.development), ensure_ascii=False, indent=2))
