#!/usr/bin/env python3
# # 文件说明书 (File Manual)
# ## 核心功能 (Core Function)
# 用合成数据验证群身份隔离、榜单排序、输入完整性、文本安全、模块布局和本地批量交互。
# ## 输入 (Input)
# 文件内生成的虚构群与成员数据，不读取真实聊天记录。
# ## 输出 (Output)
# unittest 验证结果及临时 HTML，测试结束后自动清理。
# ## 定位 (Position)
# render_review_workbench.py 的离线回归测试。
# ## 依赖 (Dependency)
# - Python 3 标准库 unittest、tempfile、subprocess、html.parser。
# - Node.js：执行合成 DOM 中的下拉筛选、全选切换与处理标记检查（无第三方包）。
# - scripts/render_review_workbench.py：被测渲染器。
# ## 维护规则 (Maintenance Rules)
# 1. 每次修改代码逻辑后，必须检查并更新上述的【核心功能】、【输入】、【输出】等信息，确保文档与代码一致。
# 2. 禁止修改或删除本【维护规则】章节的内容。
# 3. 修改完成后，必须扫描当前文件所在的文件夹目录，找到对应的 README 文档，并同步更新该 README 中关于本文件的描述信息；本 Skill 以 SKILL.md 和对应 reference 充当说明入口。

"""Synthetic, privacy-safe checks for the offline review workbench renderer."""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from html.parser import HTMLParser


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "render_review_workbench.py"
spec = importlib.util.spec_from_file_location("render_review_workbench", SCRIPT)
assert spec and spec.loader
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)


class SectionTree(HTMLParser):
    """Check nesting instead of accepting malformed markup like a browser would."""

    def __init__(self) -> None:
        super().__init__()
        self.root = {"tag": "root", "children": []}
        self.stack = [self.root]
        self.ids = {}

    def handle_starttag(self, tag: str, attrs: list) -> None:
        node = {"tag": tag, "attrs": dict(attrs), "children": [], "parent": self.stack[-1]}
        node["parent"]["children"].append(node)
        if "id" in node["attrs"]:
            self.ids[node["attrs"]["id"]] = node
        if tag not in {"input", "br", "hr", "img", "meta", "link"}:
            self.stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        if len(self.stack) == 1 or self.stack[-1]["tag"] != tag:
            raise AssertionError(f"Unexpected closing tag: {tag}")
        self.stack.pop()


def fixture(group_id: str = "demo-primary@chatroom", group_name: str = "合成演示群") -> dict:
    rows = [
        {
            "username": "wxid_test_a",
            "display_name": "样例成员 <A>",
            "status": "confirmed_inactive",
            "status_label": "无发言候选",
            "message_count": 0,
            "valid_count": 0,
            "invalid_count": 0,
            "replies_sent": 0,
            "has_direct_dialogue": False,
            "samples": [],
        },
        {
            "username": "wxid_test_b",
            "display_name": "样例成员 B",
            "status": "normal_activity",
            "status_label": "正常活跃",
            "message_count": 8,
            "valid_count": 5,
            "invalid_count": 1,
            "replies_sent": 2,
            "has_direct_dialogue": True,
            "samples": [{"time": "2026-09-10 10:00:00", "quality": "valid", "text": "</script><script>bad()</script>", "reason": "具体讨论"}],
        },
        {
            "username": "wxid_test_c",
            "display_name": "样例管理成员",
            "status": "excluded",
            "status_label": "已排除",
            "message_count": 20,
            "valid_count": 12,
            "invalid_count": 2,
            "replies_sent": 4,
            "has_direct_dialogue": True,
            "samples": [],
        },
    ]
    return {
        "chatroom_id": group_id,
        "group_name": group_name,
        "date_range": {"start": "2026-05-11 00:00:00", "end": "2026-09-11 23:59:59"},
        "rows": rows,
        "members_total": len(rows),
        "status_counts": {"confirmed_inactive": 1, "normal_activity": 1, "excluded": 1},
    }


class WorkbenchTests(unittest.TestCase):
    def render_page(self, data: dict) -> str:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "workbench.html"
            renderer.render_html(data, output, data["group_name"], "2026-05-11 至 2026-09-11", data["chatroom_id"])
            return output.read_text(encoding="utf-8")

    def test_full_group_identity_scopes_local_keys_and_escapes_evidence(self) -> None:
        data = fixture()
        renderer.validate_payload(data)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "workbench.html"
            renderer.render_html(data, output, data["group_name"], "2026-05-11 至 2026-09-11", data["chatroom_id"])
            page = output.read_text(encoding="utf-8")
        self.assertIn("wechat-hygiene-review::demo-primary@chatroom::20260511-20260911", page)
        self.assertIn("wechat-hygiene-processed::demo-primary@chatroom::20260511-20260911", page)
        self.assertIn("wechat-hygiene-announcement::demo-primary@chatroom::20260511-20260911", page)
        self.assertIn("&lt;/script&gt;&lt;script&gt;bad()&lt;/script&gt;", page)
        self.assertNotIn("STEP 02 / MANUAL REVIEW", page)
        self.assertNotIn("逐一核对成员身份、发言和证据，再在微信中执行实际操作。", page)
        self.assertNotIn("<option value='special_keep'>", page)

    def test_other_group_gets_its_own_scope_without_export_controls(self) -> None:
        data = fixture("88888@chatroom", "新群样例")
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "analysis.json"
            output = Path(directory) / "workbench.html"
            source.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            run = subprocess.run([sys.executable, str(SCRIPT), "--analysis-json", str(source), "--output-html", str(output), "--chatroom-id", "88888@chatroom", "--group-name", "新群样例"], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            page = output.read_text(encoding="utf-8")
        self.assertTrue("wechat-hygiene-review::88888@chatroom::20260511-20260911" in page)
        self.assertNotIn("人工确认净化名单.json", page)
        self.assertNotIn("exportSelection", page)
        self.assertNotIn("wechat-hygiene-review::demo-primary", page)
        self.assertIn('"各位群友，"', page)
        self.assertNotIn("本群新人加入转向邀请制", page)

    def test_leaderboard_includes_exempt_members_and_ranks_by_message_count(self) -> None:
        data = fixture()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "workbench.html"
            renderer.render_html(data, output, data["group_name"], "2026-05-11 至 2026-09-11", data["chatroom_id"])
            page = output.read_text(encoding="utf-8")
        board = page.split("<ol class='leader-grid'>", 1)[1].split("</ol>", 1)[0]
        self.assertEqual(board.count("class='leader-card"), 2)
        self.assertLess(board.index("wxid_test_c"), board.index("wxid_test_b"))
        self.assertNotIn("wxid_test_a", board)

    def test_leaderboard_caps_at_ten_and_uses_stable_tiebreak(self) -> None:
        data = fixture()
        for count in range(1, 13):
            data["rows"].append({**data["rows"][1], "username": f"wxid_extra_{count:02d}", "display_name": f"样例 {count}", "message_count": count, "valid_count": 0})
        data["members_total"] = len(data["rows"])
        data["status_counts"]["normal_activity"] += 12
        renderer.validate_payload(data)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "workbench.html"
            renderer.render_html(data, output, data["group_name"], "2026-05-11 至 2026-09-11", data["chatroom_id"])
            page = output.read_text(encoding="utf-8")
        board = page.split("<ol class='leader-grid'>", 1)[1].split("</ol>", 1)[0]
        self.assertEqual(board.count("class='leader-card"), 10)
        self.assertLess(board.index("wxid_test_b"), board.index("wxid_extra_08"))

    def test_special_keep_is_rendered_as_review_only(self) -> None:
        data = fixture("88888@chatroom", "新群样例")
        data["rows"].append({**data["rows"][1], "username": "wxid_special", "display_name": "特殊保留成员", "status": "special_keep", "status_label": "特殊保留"})
        data["members_total"] += 1
        data["status_counts"]["special_keep"] = 1
        renderer.validate_payload(data)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "workbench.html"
            renderer.render_html(data, output, data["group_name"], "2026-05-11 至 2026-09-11", data["chatroom_id"])
            page = output.read_text(encoding="utf-8")
        section = page.split("<section id='special_keep'", 1)[1].split("</section>", 1)[0]
        self.assertIn("wxid_special", section)
        self.assertIn("加入复核名单", section)
        self.assertIn("<option value='special_keep'>", page)
        self.assertIn("'special_keep','excluded'].includes", page)

    def test_conflicting_group_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "analysis.json"
            output = Path(directory) / "workbench.html"
            source.write_text(json.dumps(fixture(), ensure_ascii=False), encoding="utf-8")
            run = subprocess.run([sys.executable, str(SCRIPT), "--analysis-json", str(source), "--output-html", str(output), "--chatroom-id", "88888@chatroom"], capture_output=True, text=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertFalse(output.exists())

    def test_other_group_without_id_cannot_inherit_default_group(self) -> None:
        data = fixture("88888@chatroom", "新群样例")
        del data["chatroom_id"]
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "analysis.json"
            source.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            rejected = subprocess.run([sys.executable, str(SCRIPT), "--analysis-json", str(source)], capture_output=True, text=True)
            self.assertNotEqual(rejected.returncode, 0)
            accepted = subprocess.run([sys.executable, str(SCRIPT), "--analysis-json", str(source), "--chatroom-id", "88888@chatroom", "--group-name", "新群样例"], capture_output=True, text=True)
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            output = Path(accepted.stdout.strip())
            self.assertIn("88888_chatroom", output.name)
            self.assertTrue(output.exists())

    def test_missing_group_identity_is_rejected_without_output(self) -> None:
        for missing in (("chatroom_id",), ("group_name",), ("chatroom_id", "group_name")):
            data = fixture()
            for key in missing:
                del data[key]
            with tempfile.TemporaryDirectory() as directory:
                source = Path(directory) / "analysis.json"
                output = Path(directory) / "workbench.html"
                source.write_text(json.dumps(data), encoding="utf-8")
                run = subprocess.run([sys.executable, str(SCRIPT), "--analysis-json", str(source), "--output-html", str(output)], capture_output=True, text=True)
                self.assertNotEqual(run.returncode, 0)
                self.assertFalse(output.exists())

    def test_filename_uses_full_identity_even_for_sanitized_collisions(self) -> None:
        self.assertNotEqual(renderer.safe_group_stem("Same name", "demo@chatroom"), renderer.safe_group_stem("Same name", "demo_chatroom"))

    def test_announcement_context_is_configurable_and_js_escaped(self) -> None:
        data = fixture("88888@chatroom", "新群样例")
        data["announcement_context"] = {
            "salutation": "大家 </script>",
            "community_label": "新群",
            "policy_text": "请先阅读新群群规",
        }
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "workbench.html"
            renderer.render_html(data, output, data["group_name"], "2026-05-11 至 2026-09-11", data["chatroom_id"])
            page = output.read_text(encoding="utf-8")
        self.assertIn("请先阅读新群群规", page)
        self.assertIn(r"\u003c/script\u003e", page)
        self.assertNotIn("本群新人加入转向邀请制", page)

    def test_invalid_input_does_not_overwrite_existing_report(self) -> None:
        data = fixture()
        data["status_counts"]["confirmed_inactive"] = 99
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "workbench.html"
            output.write_text("existing review state", encoding="utf-8")
            with self.assertRaises(ValueError):
                renderer.render_html(data, output, data["group_name"], "2026-05-11 至 2026-09-11", data["chatroom_id"])
            self.assertEqual(output.read_text(encoding="utf-8"), "existing review state")

    def test_missing_metrics_and_count_mismatch_are_not_fabricated(self) -> None:
        data = fixture()
        del data["rows"][0]["valid_count"]
        with self.assertRaises(ValueError):
            renderer.validate_payload(data)
        data = fixture()
        data["status_counts"]["confirmed_inactive"] = 2
        with self.assertRaises(ValueError):
            renderer.validate_payload(data)
        data = fixture()
        del data["members_total"]
        with self.assertRaises(ValueError):
            renderer.validate_payload(data)
        data = fixture()
        data["rows"][1]["samples"][0]["text"] = 123
        with self.assertRaises(ValueError):
            renderer.validate_payload(data)
        data = fixture()
        data["status_counts"]["unknown_status"] = 1
        with self.assertRaises(ValueError):
            renderer.validate_payload(data)

    def test_current_controls_and_short_copy_are_the_default(self) -> None:
        page = self.render_page(fixture())
        for removed in ("导出已勾选名单", "导出已净化名单", "导出未净化名单", "飞书 Markdown 名单", "exportSelection", "；请逐一核对", "，请结合证据复核", "暂无新成员记录。", ">前 10</span>", "历史数据复核："):
            self.assertNotIn(removed, page)
        self.assertEqual(page.count("class='section-select-all'"), 2)
        self.assertEqual(page.count("id='purgeSelectAll'"), 1)
        self.assertIn("role='combobox'", page)
        self.assertIn("role='listbox'", page)
        self.assertIn(".status-filter-control[hidden]", page)
        self.assertIn(".status-filter-trigger:focus-visible{outline:2px solid #93bfa8", page)
        self.assertIn(".remove-selected{grid-column:2;grid-row:2;justify-self:end;", page)
        self.assertIn("background:#fff0ee;color:#b6564c", page)
        self.assertIn("#purgeView .purge-grid{grid-template-columns:repeat(6", page)
        self.assertIn("<strong>0</strong><span class='label'>新成员保护</span><small>暂无新成员记录</small>", page)
        self.assertNotIn("未核验", page)
        self.assertIn("<strong>3</strong><span class='label'>群成员</span>", page)
        self.assertNotIn("366", page)

    def test_review_headings_and_separators_are_above_the_grids(self) -> None:
        page = self.render_page(fixture())
        tree = SectionTree()
        tree.feed(re.search(r"<main id='purgeView'.*?</main>", page, re.S).group())
        self.assertEqual(len(tree.stack), 1)
        for section_id, list_id in (("purgeActionSection", "purgeActionList"), ("purgeProtectedSection", "purgeProtectedList")):
            section = tree.ids[section_id]
            self.assertEqual(len(section["children"]), 2)
            self.assertEqual(section["children"][0]["attrs"]["class"], "section-heading")
            self.assertIs(section["children"][1], tree.ids[list_id])
            self.assertIs(tree.ids[list_id]["parent"], section)
        self.assertEqual(tree.ids["purgeSelectAll"]["parent"]["attrs"]["class"], "section-title-row")

    def test_actual_new_members_are_not_replaced_with_empty_zero(self) -> None:
        data = fixture()
        data["rows"].append({**data["rows"][0], "username": "wxid_new", "display_name": "样例新人", "status": "recent_joiner", "status_label": "新加入", "joined_at": "2026-09-11 20:00:00"})
        data["members_total"] += 1
        data["status_counts"]["recent_joiner"] = 1
        page = self.render_page(data)
        self.assertIn("<strong>1</strong><span class='label'>新成员保护</span>", page)
        self.assertNotIn("暂无新成员记录", page)
        self.assertIn("入群不足 24 小时，单独观察", page)

    def test_local_interactions_with_and_without_special_keep_option(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js unavailable; interactive checks require Node.js")
        for include_special in (False, True):
            with self.subTest(include_special=include_special):
                data = fixture()
                if include_special:
                    data["rows"].append({**data["rows"][0], "username": "wxid_special", "display_name": "合成保留成员", "status": "special_keep", "status_label": "特殊保留"})
                    data["members_total"] += 1
                    data["status_counts"]["special_keep"] = 1
                page = self.render_page(data)
                run = subprocess.run([node, str(Path(__file__).with_name("test_review_workbench_interactions.js"))], input=page, capture_output=True, text=True, timeout=20)
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                self.assertIn("PASS", run.stdout)


if __name__ == "__main__":
    unittest.main()
