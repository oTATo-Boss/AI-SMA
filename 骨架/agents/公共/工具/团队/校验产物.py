#!/usr/bin/env python3
"""按 agents/公共/合同.md 校验交接产物：字段、取值、依据是否存在、审片报告对应的成片有没有被改过。参数是文件或目录，目录里只看带 artifact 字段的 JSON。标准库。"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
LIBRARY = ROOT / "agents/账号/爆款库"
COMMON = ["artifact", "task", "version", "owner", "created_at", "evidence_refs"]
SPECS = {
    "viral-reference": {"fields": ["id", "platform", "url", "author", "published_at", "collected_at", "metrics", "baseline",
                                   "outlier_ratio", "media_reviewed", "observed", "inferred", "transferable"]},
    "opportunity-brief": {"fields": ["opportunities", "account_baseline", "gaps"],
                          "items": {"opportunities": ["topic", "why_now", "evidence_refs", "audience_signal", "mechanism_hints"]}},
    "idea-candidates": {"fields": ["method", "candidates"],
                        "items": {"candidates": ["id", "one_liner", "hook", "beats", "payoff", "why", "evidence_refs",
                                                 "borrowed_mechanism", "difference_from_source", "feasibility"]}},
    "blind-candidates": {"fields": ["candidates"],
                         "items": {"candidates": ["id", "one_liner", "hook", "beats", "payoff", "why", "evidence_refs",
                                                  "borrowed_mechanism", "difference_from_source", "feasibility"]}},
    "idea-review": {"fields": ["blind", "scores", "pick", "explore_pick", "verdict", "required_changes", "similarity_flags"],
                    "items": {"scores": ["candidate", "total", "dimensions", "risks"]},
                    "enums": {"verdict": {"pass", "revise", "reject"}}},
    "shot-list": {"fields": ["total_seconds", "shots"],
                  "items": {"shots": ["id", "seconds", "visual", "action", "camera", "audio", "text", "assets"]}},
    "asset-manifest": {"fields": ["assets"],
                       "items": {"assets": ["id", "shot", "type", "path", "source", "tool", "job_id", "check"]}},
    "review-report": {"fields": ["media", "method", "verdict", "defects", "strengths", "publishable"],
                      "items": {"defects": ["timecode", "shot", "severity", "problem", "cause", "owner", "fix"]},
                      "enums": {"verdict": {"pass", "rework", "reject"}},
                      "item_enums": {"defects": {"severity": {"blocker", "major", "minor"},
                                                 "fix": {"trim", "regenerate", "redo", "repackage"}}}},
    "experience-update": {"fields": ["mechanism", "evidence", "sample_size", "window", "confidence", "status", "recommendation"],
                          "enums": {"confidence": {"low", "medium", "high"}, "status": {"hypothesis", "verified"}}},
}
LIBRARY_ID = re.compile(r"[a-z]+-\d{8}-[a-z]?\d+")  # 分路采集时序号前可加一个字母，例如 xhs-20261015-a01


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def ref_problems(refs, where):
    problems = []
    for ref in refs if isinstance(refs, list) else []:
        if not isinstance(ref, str) or not ref.strip():
            problems.append(f"{where}：依据不能是空值")
        elif LIBRARY_ID.fullmatch(ref) and not (LIBRARY / f"{ref}.json").exists():
            problems.append(f"{where}：爆款库没有条目 {ref}")
        elif ref.startswith("agents/") and not (ROOT / ref.split("#")[0]).exists():
            problems.append(f"{where}：依据文件不存在 {ref}")
    return problems


def validate_data(data):
    if not isinstance(data, dict) or data.get("artifact") not in SPECS:
        return [f"artifact 必须是 {sorted(SPECS)} 之一"]
    spec, problems = SPECS[data["artifact"]], []
    for key in COMMON + spec["fields"]:
        if key not in data:
            problems.append(f"缺少字段 {key}")
    if not isinstance(data.get("version"), int) or data.get("version", 0) < 1:
        problems.append("version 必须是从 1 开始的整数")
    if not isinstance(data.get("evidence_refs"), list):
        problems.append("evidence_refs 必须是列表")
    problems += ref_problems(data.get("evidence_refs"), "evidence_refs")
    for key, allowed in spec.get("enums", {}).items():
        if key in data and data[key] not in allowed:
            problems.append(f"{key} 只能是 {sorted(allowed)}")
    for key, fields in spec.get("items", {}).items():
        items = data.get(key)
        if not isinstance(items, list):
            problems.append(f"{key} 必须是列表")
            continue
        for number, item in enumerate(items, 1):
            if not isinstance(item, dict):
                problems.append(f"{key} 第 {number} 项必须是对象")
                continue
            problems += [f"{key} 第 {number} 项缺少 {f}" for f in fields if f not in item]
            for field, allowed in spec.get("item_enums", {}).get(key, {}).items():
                if field in item and item[field] not in allowed:
                    problems.append(f"{key} 第 {number} 项的 {field} 只能是 {sorted(allowed)}")
            if "evidence_refs" in item:
                problems += ref_problems(item["evidence_refs"], f"{key} 第 {number} 项")
    return problems + consistency(data)


def consistency(data):
    problems = []
    kind = data["artifact"]
    if kind == "viral-reference":
        if not isinstance(data.get("media_reviewed"), bool):
            problems.append("media_reviewed 必须是 true 或 false")
        if not isinstance(data.get("outlier_ratio"), (int, float)):
            problems.append("outlier_ratio 必须是数字")
    elif kind == "blind-candidates":
        if "method" in data:
            problems.append("盲评候选不能写 method")
        ids = [c.get("id") for c in data.get("candidates") or [] if isinstance(c, dict)]
        if len(ids) != len(set(ids)):
            problems.append("盲评候选的编号有重复，各路要用总负责人分的前缀")
    elif kind == "idea-review":
        if data.get("blind") is not True:
            problems.append("创意评审必须盲评（blind 为 true）")
        scores = data.get("scores") if isinstance(data.get("scores"), list) else []
        candidates = {s.get("candidate") for s in scores if isinstance(s, dict)}
        if data.get("verdict") == "pass" and data.get("pick") not in candidates:
            problems.append("verdict 为 pass 时，pick 必须是打过分的候选之一")
        if data.get("explore_pick") not in (None, "") and data.get("explore_pick") not in candidates:
            problems.append("explore_pick 必须是打过分的候选之一")
    elif kind == "review-report":
        media = data.get("media")
        if not isinstance(media, dict) or not {"path", "sha256"} <= set(media):
            problems.append("media 需要 path 和 sha256")
        else:
            path = ROOT / media["path"]
            if not path.is_file():
                problems.append(f"审片对象不存在：{media['path']}")
            elif sha256(path) != media["sha256"]:
                problems.append(f"成片在审片之后被改过：{media['path']}，需要重新审片")
        defects = data.get("defects") if isinstance(data.get("defects"), list) else []
        blockers = [d for d in defects if isinstance(d, dict) and d.get("severity") == "blocker"]
        if data.get("verdict") == "pass" and (blockers or data.get("publishable") is not True):
            problems.append("verdict 为 pass 时不能有 blocker，且 publishable 必须为 true")
    elif kind == "experience-update":
        if data.get("status") == "verified" and (not isinstance(data.get("sample_size"), int) or data["sample_size"] < 3):
            problems.append("样本少于 3 条的经验只能是 hypothesis")
    return problems


def validate_file(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [f"读不了或不是 JSON：{exc}"]
    return validate_data(data)


ARCHIVED = re.compile(r"\.v\d+\.json$")  # 返工前存档的旧版本，只留作历史


def artifact_files(paths):
    """展开目录：只要带 artifact 字段的 JSON，跳过 .v<N>.json 存档版本；单独指定的文件都要校验。"""
    found = []
    for raw in paths:
        path = Path(raw) if Path(raw).is_absolute() else (Path.cwd() / raw)
        if path.is_file():
            found.append(path)
        elif path.is_dir():
            for item in sorted(path.rglob("*.json")):
                if "node_modules" in item.parts or item.name == "task.json" or ARCHIVED.search(item.name):
                    continue
                try:
                    if '"artifact"' in item.read_text(encoding="utf-8", errors="ignore")[:4000]:
                        found.append(item)
                except OSError:
                    continue
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help="产物文件或目录，例如任务目录或 agents/账号/爆款库")
    args = parser.parse_args()
    files, failed = artifact_files(args.paths), 0
    for path in files:
        problems = validate_file(path)
        label = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
        print(("✓ " if not problems else "✗ ") + label)
        for item in problems:
            print("    " + item)
        failed += bool(problems)
    print(f"产物：{len(files)} 个，有问题 {failed} 个")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
