#!/usr/bin/env python3
"""按 agents/公共/合同.md 校验交接产物：字段、取值、依据是否存在、审片报告对应的成片有没有被改过。参数是文件或目录，目录里只看带 artifact 字段的 JSON。标准库。"""
import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path, PureWindowsPath

ROOT = Path(__file__).resolve().parents[4]
LIBRARY = ROOT / ("agents/项目/爆款库" if (ROOT / "agents/项目/项目配置.yaml").is_file() else "agents/账号/爆款库")
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
V2_SPECS = {
    "script": {"fields": ["format", "scenes"], "items": {"scenes": ["id", "heading", "action", "dialogue"]}},
    "storyboard": {"fields": ["shots"], "items": {"shots": ["id", "scene_id", "description", "frame"]}},
    "continuity": {"fields": ["states", "issues"], "items": {"states": ["unit", "entity", "state"]}},
    "edit": {"fields": ["timeline"], "items": {"timeline": ["id", "source", "in", "out", "start"]}},
    "audio": {"fields": ["tracks"], "items": {"tracks": ["id", "kind", "file", "start", "duration"]}},
    "subtitle": {"fields": ["language", "cues"], "items": {"cues": ["start", "end", "text"]}},
    "render": {"fields": ["media", "spec", "checks"]},
    "delivery": {"fields": ["profile", "package", "checks"]},
}
SPECS.update(V2_SPECS)
LIBRARY_ID = re.compile(r"[a-z]+-\d{8}-[a-z]?\d+")  # 分路采集时序号前可加一个字母，例如 xhs-20261015-a01


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def local_file(value):
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("文件路径必须是使用 / 的项目相对路径")
    rel = Path(value)
    if rel.is_absolute() or PureWindowsPath(value).is_absolute() or ".." in rel.parts:
        raise ValueError("文件路径不能离开项目")
    cursor = ROOT
    for part in rel.parts:
        cursor /= part
        if cursor.is_symlink() or (cursor.exists() and getattr(cursor.lstat(), "st_file_attributes", 0) & 0x400):
            raise ValueError("版本文件不能经过链接")
    if not cursor.resolve().is_relative_to(ROOT.resolve()) or not cursor.is_file():
        raise ValueError("版本文件不存在或越界：" + value)
    return cursor


def file_version(record, label):
    if not isinstance(record, dict) or set(record) != {"path", "sha256"}:
        return [label + " 需要且只需要 path 和 sha256"]
    if not isinstance(record["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", record["sha256"]):
        return [label + " 的 sha256 格式错误"]
    try:
        path = local_file(record["path"])
        if sha256(path) != record["sha256"]:
            return [label + " 文件版本已变化：" + record["path"]]
    except (ValueError, OSError) as exc:
        return [label + "：" + str(exc)]
    return []


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
    if not isinstance(data, dict) or not isinstance(data.get("artifact"), str) or data.get("artifact") not in SPECS:
        return [f"artifact 必须是 {sorted(SPECS)} 之一"]
    spec, problems = SPECS[data["artifact"]], []
    for key in COMMON + spec["fields"]:
        if key not in data:
            problems.append(f"缺少字段 {key}")
    if not isinstance(data.get("version"), int) or isinstance(data.get("version"), bool) or data.get("version", 0) < 1:
        problems.append("version 必须是从 1 开始的整数")
    if not isinstance(data.get("evidence_refs"), list):
        problems.append("evidence_refs 必须是列表")
    problems += ref_problems(data.get("evidence_refs"), "evidence_refs")
    for key, allowed in spec.get("enums", {}).items():
        if key in data and (not isinstance(data[key], str) or data[key] not in allowed):
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
                if field in item and (not isinstance(item[field], str) or item[field] not in allowed):
                    problems.append(f"{key} 第 {number} 项的 {field} 只能是 {sorted(allowed)}")
            if "evidence_refs" in item:
                problems += ref_problems(item["evidence_refs"], f"{key} 第 {number} 项")
    if data["artifact"] in V2_SPECS and data.get("schema_version") != 2:
        problems.append("新产物契约需要 schema_version: 2")
    if data.get("schema_version") == 2:
        problems += validate_v2(data)
    return problems + consistency(data)


def validate_v2(data):
    problems = []
    for key in ("task", "owner", "created_at"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            problems.append(key + " 必须是非空文字")
    for key in ("inputs", "files"):
        if not isinstance(data.get(key), list):
            problems.append(key + " 必须是文件版本列表")
            continue
        seen = set()
        for record in data[key]:
            problems += file_version(record, key)
            if isinstance(record, dict) and isinstance(record.get("path"), str):
                if record["path"] in seen:
                    problems.append(key + " 文件重复：" + record["path"])
                seen.add(record["path"])
    kind = data["artifact"]
    collection = {"script": "scenes", "storyboard": "shots", "edit": "timeline", "audio": "tracks", "subtitle": "cues"}.get(kind)
    if collection and isinstance(data.get(collection), list):
        if not data[collection]:
            problems.append(collection + " 不能为空")
        ids = [item.get("id") for item in data[collection] if isinstance(item, dict) and "id" in item]
        if any(not isinstance(i, str) or not i for i in ids) or len([str(i) for i in ids]) != len(set(str(i) for i in ids)):
            problems.append(collection + " 的 id 必须是互不重复的非空文字")
    listed = {v.get("path") for key in ("inputs", "files") for v in data.get(key, []) if isinstance(v, dict) and isinstance(v.get("path"), str)} if all(isinstance(data.get(k), list) for k in ("inputs", "files")) else set()
    for collection, field in (("shots", "frame"), ("timeline", "source"), ("tracks", "file")):
        if collection == "shots" and kind != "storyboard":
            continue
        for item in data.get(collection, []) if isinstance(data.get(collection), list) else []:
            if isinstance(item, dict) and (not isinstance(item.get(field), str) or item[field] not in listed):
                problems.append(collection + " 的 " + field + " 必须在 inputs 或 files 中绑定哈希")
    if kind in {"idea-review", "review-report"}:
        mode = data.get("review_mode")
        if mode not in ("self", "independent"):
            problems.append("评审必须注明 review_mode: self 或 independent")
        for key in ("producer", "producer_run", "reviewer_run"):
            if not isinstance(data.get(key), str) or not data[key].strip():
                problems.append("评审需要 " + key)
        if mode == "independent" and (data.get("producer") == data.get("owner") or data.get("producer_run") == data.get("reviewer_run")):
            problems.append("独立评审必须由不同角色和不同执行实例完成")
        if kind == "idea-review" and mode == "self" and data.get("blind") is not False:
            problems.append("self 创意自检不能声称盲评，blind 必须是 false")
        if not data.get("inputs"):
            problems.append("评审必须绑定被评产物的 inputs 哈希")
    if kind in {"render", "review-report"}:
        problems += file_version(data.get("media"), "media")
        versions = data.get("files" if kind == "render" else "inputs", [])
        if not isinstance(versions, list) or data.get("media") not in versions:
            problems.append("media 必须列入 files（渲染）或 inputs（审片）的版本清单")
    if kind == "render":
        spec = data.get("spec")
        if not isinstance(spec, dict) or any(not isinstance(spec.get(k), (int, float)) or isinstance(spec.get(k), bool) or not math.isfinite(spec[k]) or spec[k] <= 0 for k in ("width", "height", "fps", "duration")):
            problems.append("render spec 需要正数 width、height、fps、duration")
    if kind == "delivery":
        package = data.get("package")
        if not isinstance(package, list) or not package:
            problems.append("delivery package 必须是非空文件版本列表")
        else:
            for item in package:
                problems += file_version(item, "package")
            if package != data.get("files"):
                problems.append("delivery package 必须与 files 版本清单一致")
    if kind in {"render", "delivery"} and not isinstance(data.get("checks"), list):
        problems.append("checks 必须是检查记录列表，不代表内容已验收")
    for collection, start, end in (("timeline", "in", "out"), ("cues", "start", "end")):
        last_start = -1
        for item in data.get(collection, []) if isinstance(data.get(collection), list) else []:
            if not isinstance(item, dict):
                continue
            a, b = item.get(start), item.get(end)
            if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in (a, b)) or a < 0 or b <= a:
                problems.append(collection + " 时间必须满足 0 <= 开始 < 结束")
            if collection == "cues" and isinstance(a, (int, float)):
                if a < last_start:
                    problems.append("字幕必须按开始时间排序")
                last_start = a
    for collection, fields in (("timeline", ("start",)), ("tracks", ("start", "duration"))):
        for item in data.get(collection, []) if isinstance(data.get(collection), list) else []:
            if not isinstance(item, dict):
                continue
            for field in fields:
                value = item.get(field)
                if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value < 0 or (field == "duration" and value == 0):
                    problems.append(collection + " 的 " + field + " 必须是有效秒数")
    return problems


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
        if not (data.get("schema_version") == 2 and data.get("review_mode") == "self") and data.get("blind") is not True:
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
            try:
                path = local_file(media["path"])
                if sha256(path) != media["sha256"]:
                    problems.append(f"成片在审片之后被改过：{media['path']}，需要重新审片")
            except (ValueError, OSError) as exc:
                problems.append(str(exc))
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
