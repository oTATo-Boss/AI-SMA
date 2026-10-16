"""实际文件哈希与 v2 制作产物合同的隔离测试。"""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("contracts_v2", Path(__file__).resolve().parents[1] / "校验产物.py")
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


class ContractV2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ai-sma-contract-")
        self.root = Path(self.temp.name)
        self.old_root, self.old_library = MOD.ROOT, MOD.LIBRARY
        MOD.ROOT, MOD.LIBRARY = self.root, self.root / "agents/项目/爆款库"
        (self.root / "agents/工作/t").mkdir(parents=True)
        self.media = self.file("视频.mp4", b"test-media")
        self.frame = self.file("帧.png", b"test-frame")
        self.sound = self.file("声音.wav", b"test-audio")

    def tearDown(self):
        MOD.ROOT, MOD.LIBRARY = self.old_root, self.old_library
        self.temp.cleanup()

    def file(self, name, content):
        path = "agents/工作/t/" + name
        (self.root / path).write_bytes(content)
        return {"path": path, "sha256": hashlib.sha256(content).hexdigest()}

    def base(self, kind, **kwargs):
        return {"schema_version": 2, "artifact": kind, "task": "t", "version": 1, "owner": "producer",
                "created_at": "2026-10-16 12:00", "evidence_refs": [], "inputs": [], "files": [], **kwargs}

    def test_eight_production_contracts(self):
        items = [
            self.base("script", format="screenplay", scenes=[{"id": "S01", "heading": "INT. ROOM", "action": "走进来", "dialogue": []}]),
            self.base("storyboard", files=[self.frame], shots=[{"id": "SH01", "scene_id": "S01", "description": "特写", "frame": self.frame["path"]}]),
            self.base("continuity", states=[{"unit": "SH01", "entity": "主角", "state": "蓝色外套"}], issues=[]),
            self.base("edit", inputs=[self.media], timeline=[{"id": "E01", "source": self.media["path"], "in": 0, "out": 2, "start": 0}]),
            self.base("audio", files=[self.sound], tracks=[{"id": "A01", "kind": "voice", "file": self.sound["path"], "start": 0, "duration": 2}]),
            self.base("subtitle", language="zh-CN", cues=[{"start": 0, "end": 1, "text": "你好"}]),
            self.base("render", files=[self.media], media=self.media, spec={"width": 1920, "height": 1080, "fps": 30, "duration": 2}, checks=[]),
            self.base("delivery", files=[self.media], profile="science", package=[self.media], checks=[]),
        ]
        for item in items:
            self.assertEqual(MOD.validate_data(item), [], item["artifact"])
        (self.root / self.media["path"]).write_bytes(b"changed")
        self.assertTrue(MOD.validate_data(items[-2]))
        self.assertTrue(MOD.validate_data(items[-1]))

    def test_independent_and_self_review_are_distinct(self):
        data = self.base("review-report", owner="reviewer", producer="producer", producer_run="run-1", reviewer_run="run-2",
                         review_mode="independent", inputs=[self.media], media=self.media, method={"video": "full-playback"},
                         verdict="pass", defects=[], strengths=[], publishable=True)
        self.assertEqual(MOD.validate_data(data), [])
        data["reviewer_run"] = "run-1"
        self.assertTrue(any("独立评审" in p for p in MOD.validate_data(data)))
        data["review_mode"] = "self"
        self.assertEqual(MOD.validate_data(data), [])
        (self.root / self.media["path"]).write_bytes(b"new-cut")
        self.assertTrue(MOD.validate_data(data))

    def test_self_idea_review_cannot_claim_blind(self):
        candidates = self.file("候选.json", b"{}")
        data = self.base("idea-review", producer="producer", producer_run="run-1", reviewer_run="run-1", review_mode="self",
                         inputs=[candidates], blind=False, scores=[{"candidate": "A", "total": 20, "dimensions": {}, "risks": []}],
                         pick="A", explore_pick=None, verdict="pass", required_changes=[], similarity_flags=[])
        self.assertEqual(MOD.validate_data(data), [])
        data["blind"] = True
        self.assertTrue(any("不能声称盲评" in p for p in MOD.validate_data(data)))

    def test_bad_ranges_missing_binding_and_path_escape(self):
        data = self.base("subtitle", language="zh", cues=[{"start": 2, "end": 1, "text": "bad"}])
        self.assertTrue(MOD.validate_data(data))
        data = self.base("storyboard", shots=[{"id": "1", "scene_id": "1", "description": "d", "frame": self.frame["path"]}])
        self.assertTrue(any("绑定哈希" in p for p in MOD.validate_data(data)))
        for path in ("../escape", "C:/file", "agents/../escape"):
            data = self.base("delivery", profile="film", package=[{"path": path, "sha256": "0" * 64}], checks=[])
            self.assertTrue(MOD.validate_data(data))


if __name__ == "__main__":
    unittest.main()
