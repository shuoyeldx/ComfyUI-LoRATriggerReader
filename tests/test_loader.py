# -*- coding: utf-8 -*-
"""``lora_trigger_reader.loader`` 的单元测试（纯标准库，不需要 torch / ComfyUI）。

覆盖：强度解析、``lora_list`` 文本解析、路径解析与加载流程（全部用假加载器）、
报告文本、以及"文件指纹 + 内存缓存"的行为。

运行方式::

    python -m unittest discover -s tests -p "test_loader.py" -v
"""

from __future__ import annotations

import os
import shutil
import sys
import unittest
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from lora_trigger_reader import loader as ld  # noqa: E402
from lora_trigger_reader import lora_scan as ls  # noqa: E402

# 临时目录放在测试文件旁边（系统 TEMP 在受限环境里可能不可写）
TMP_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(TMP_ROOT, exist_ok=True)


def _mkdtemp(prefix: str) -> str:
    """自建临时目录（不用 tempfile.mkdtemp，避免 0o700 + Windows chmod 的问题）。"""
    path = os.path.join(TMP_ROOT, prefix + uuid.uuid4().hex[:10])
    os.makedirs(path)
    return path


class TestToFloatAndStrengths(unittest.TestCase):
    def test_to_float_accepts_numbers(self):
        for text, want in (("1", 1.0), ("0.8", 0.8), ("-1", -1.0), ("+2.5", 2.5), (".5", 0.5), ("1e-2", 0.01)):
            self.assertEqual(ld._to_float(text), want, text)

    def test_to_float_rejects_junk(self):
        for text in ("", "  ", "abc", "nan", "inf", "1.2.3", "0x10", None, [1]):
            self.assertIsNone(ld._to_float(text), repr(text))

    def test_strength_list(self):
        self.assertEqual(ld._strength_list("0.8"), [0.8])
        self.assertEqual(ld._strength_list("0.8, 0.5"), [0.8, 0.5])
        self.assertEqual(ld._strength_list("0.8 0.5"), [0.8, 0.5])
        self.assertEqual(ld._strength_list("0.8，0.5"), [0.8, 0.5])
        self.assertIsNone(ld._strength_list(""))
        self.assertIsNone(ld._strength_list("abc"))
        self.assertIsNone(ld._strength_list("0.8, abc"))

    def test_split_strengths_forms(self):
        self.assertEqual(ld.split_strengths(""), ([], [], ""))
        self.assertEqual(ld.split_strengths("a.safetensors"), (["a.safetensors"], [], ""))
        self.assertEqual(ld.split_strengths("a.safetensors: 0.8"), (["a.safetensors"], [0.8], ""))
        self.assertEqual(ld.split_strengths("a.safetensors：0.8"), (["a.safetensors"], [0.8], ""))
        self.assertEqual(ld.split_strengths("a.safetensors: 0.8, 0.5"), (["a.safetensors"], [0.8, 0.5], ""))
        self.assertEqual(ld.split_strengths("a.safetensors @ 0.8"), (["a.safetensors"], [0.8], ""))
        self.assertEqual(ld.split_strengths("a.safetensors, 0.8"), (["a.safetensors"], [0.8], ""))
        self.assertEqual(
            ld.split_strengths("a.safetensors, b.safetensors"),
            (["a.safetensors", "b.safetensors"], [], ""),
        )

    def test_split_strengths_keeps_windows_path_intact(self):
        raw = r"C:\loras\x.safetensors"
        self.assertEqual(ld.split_strengths(raw), ([raw], [], ""))

    def test_split_strengths_colon_without_number_is_part_of_name(self):
        self.assertEqual(ld.split_strengths("a.safetensors: abc"), (["a.safetensors: abc"], [], ""))

    def test_split_strengths_at_without_left_side(self):
        self.assertEqual(ld.split_strengths("@ 0.8"), (["@ 0.8"], [], ""))

    def test_two_names_with_trailing_number_stays_names(self):
        # "a, b, 0.5"：第一个 token 不是数字 => 整行当名字列表，纯数字项由 parse_specs 丢掉
        names, strengths, _ = ld.split_strengths("a.safetensors, b.safetensors, 0.5")
        self.assertEqual(names, ["a.safetensors", "b.safetensors", "0.5"])
        self.assertEqual(strengths, [])
        specs, warnings = ld.parse_specs("a.safetensors, b.safetensors, 0.5")
        self.assertEqual([s["name"] for s in specs], ["a.safetensors", "b.safetensors"])
        self.assertTrue(any("忽略纯数字项" in w for w in warnings), warnings)

    def test_split_strengths_angle_bracket_form(self):
        """`<lora:名:0.8>` / `<lora:名>` 这类写法（v1.3 加的）。"""
        self.assertEqual(
            ld.split_strengths("<lora:a.safetensors:0.8>"),
            (["a.safetensors"], [0.8], ""),
        )
        self.assertEqual(
            ld.split_strengths("<lora:a.safetensors>"),
            (["a.safetensors"], [], ""),
        )
        self.assertEqual(
            ld.split_strengths("<lora:a.safetensors:0.8,0.5>"),
            (["a.safetensors"], [0.8, 0.5], ""),
        )

    def test_split_strengths_space_form_uses_known_names(self):
        """空格写法只在"前半部分确实像个 LoRA"时才切（带扩展名，或能在 known 里找到）。"""
        known = ["a.safetensors", "sub/c.safetensors", "my lora v2.safetensors"]
        self.assertEqual(
            ld.split_strengths("a.safetensors 0.8", known),
            (["a.safetensors"], [0.8], ""),
        )
        # 带 LoRA 扩展名就够了，不一定需要 known 列表
        self.assertEqual(ld.split_strengths("a.safetensors 0.8"), (["a.safetensors"], [0.8], ""))
        # 名字本身就带空格 => 从最长的候选名字往回试，不能切坏
        self.assertEqual(
            ld.split_strengths("my lora v2.safetensors 0.3", known),
            (["my lora v2.safetensors"], [0.3], ""),
        )
        self.assertEqual(
            ld.split_strengths("my lora v2.safetensors 0.3"),
            (["my lora v2.safetensors"], [0.3], ""),
        )
        # 只能靠 known 列表认出来（前缀没有 LoRA 扩展名）
        self.assertEqual(ld.split_strengths("sub/c 0.4", known), (["sub/c"], [0.4], ""))
        # 看不出是 LoRA 时整行当名字（不猜）
        self.assertEqual(ld.split_strengths("hello world 0.8"), (["hello world 0.8"], [], ""))
        self.assertEqual(
            ld.split_strengths("hello world 0.8", known),
            (["hello world 0.8"], [], ""),
        )
        # 右边必须是数字，否则整行当名字
        self.assertEqual(
            ld.split_strengths("a.safetensors abc", known),
            (["a.safetensors abc"], [], ""),
        )

    def test_known_keys_and_looks_like_lora(self):
        keys = ld._known_keys(["sub/C.safetensors", "Anima\\silver_wolf.safetensors"])
        # 路径统一成正斜杠后再 casefold
        self.assertIn("sub/c.safetensors", keys)
        self.assertIn("c.safetensors", keys)
        self.assertIn("c", keys)
        self.assertIn("anima/silver_wolf.safetensors", keys)
        self.assertTrue(ld._looks_like_lora("unknown.safetensors", keys), "带扩展名就算")
        self.assertTrue(ld._looks_like_lora("SUB/C.SAFETENSORS", keys), "大小写无关")
        self.assertTrue(ld._looks_like_lora("Anima\\silver_wolf.safetensors", keys), "反斜杠也能查")
        self.assertTrue(ld._looks_like_lora("c", keys), "干名（词干）也能查到")
        self.assertFalse(ld._looks_like_lora("hello world", keys))
        self.assertFalse(ld._looks_like_lora("", keys))

    def test_clamp_strength(self):
        self.assertEqual(ld.clamp_strength(0.8), (0.8, ""))
        self.assertEqual(ld.clamp_strength("1"), (1.0, ""))
        value, note = ld.clamp_strength("abc")
        self.assertEqual(value, ld.DEFAULT_STRENGTH)
        self.assertIn("不是有效数字", note)
        value, note = ld.clamp_strength(200)
        self.assertEqual(value, ld.MAX_STRENGTH)
        self.assertIn("超出", note)
        value, note = ld.clamp_strength(-200)
        self.assertEqual(value, ld.MIN_STRENGTH)
        self.assertIn("超出", note)


class TestMakeSpec(unittest.TestCase):
    def test_defaults(self):
        spec = ld.make_spec("a.safetensors")
        self.assertEqual(spec["name"], "a.safetensors")
        self.assertEqual(spec["strength_model"], 1.0)
        self.assertEqual(spec["strength_clip"], 1.0)
        self.assertEqual(spec["raw"], "a.safetensors")

    def test_clip_defaults_to_model_strength(self):
        spec = ld.make_spec("a.safetensors", 0.8)
        self.assertEqual(spec["strength_model"], 0.8)
        self.assertEqual(spec["strength_clip"], 0.8)

    def test_explicit_clip_strength(self):
        spec = ld.make_spec("a.safetensors", 0.8, 0.4)
        self.assertEqual((spec["strength_model"], spec["strength_clip"]), (0.8, 0.4))


class TestParseSpecs(unittest.TestCase):
    KNOWN = [
        "a.safetensors",
        "b.safetensors",
        "sub/C.safetensors",
        "Krea2/Krea2角色lora/妃咲.safetensors",
        "silver_wolf.safetensors",
    ]

    def test_empty(self):
        self.assertEqual(ld.parse_specs(""), ([], []))
        self.assertEqual(ld.parse_specs(None), ([], []))

    def test_basic_lines_and_line_numbers(self):
        specs, warnings = ld.parse_specs("a.safetensors\n\nb.safetensors")
        self.assertEqual([s["name"] for s in specs], ["a.safetensors", "b.safetensors"])
        self.assertEqual([s["line"] for s in specs], [1, 3])
        self.assertEqual(warnings, [])

    def test_comments_are_skipped(self):
        raw = "\n".join(
            [
                "# 整行注释",
                "// 也是注释",
                "-- 还是注释",
                "a.safetensors # 行尾备注",
                "b.safetensors  # 行尾备注（两个空格）",
            ]
        )
        specs, warnings = ld.parse_specs(raw)
        self.assertEqual([s["name"] for s in specs], ["a.safetensors", "b.safetensors"])
        self.assertEqual(warnings, [])

    def test_strengths_are_applied(self):
        specs, _ = ld.parse_specs("a.safetensors: 0.8\nb.safetensors: 0.6, 0.4")
        self.assertEqual(
            [(s["strength_model"], s["strength_clip"]) for s in specs],
            [(0.8, 0.8), (0.6, 0.4)],
        )

    def test_name_completion_with_known_names(self):
        specs, _ = ld.parse_specs("妃咲\nsub/C", self.KNOWN)
        self.assertEqual(specs[0]["name"], "Krea2/Krea2角色lora/妃咲.safetensors")
        self.assertEqual(specs[1]["name"], "sub/C.safetensors")

    def test_same_name_twice_is_kept_twice(self):
        specs, _ = ld.parse_specs("a.safetensors\na.safetensors")
        self.assertEqual(len(specs), 2)

    def test_pure_number_line_is_ignored_with_warning(self):
        specs, warnings = ld.parse_specs("0.8\na.safetensors")
        self.assertEqual([s["name"] for s in specs], ["a.safetensors"])
        self.assertTrue(any("忽略纯数字项" in w for w in warnings), warnings)

    def test_three_strengths_are_truncated_with_warning(self):
        specs, warnings = ld.parse_specs("a.safetensors: 0.1, 0.2, 0.3")
        self.assertEqual((specs[0]["strength_model"], specs[0]["strength_clip"]), (0.1, 0.2))
        self.assertTrue(any("强度最多两个" in w for w in warnings), warnings)

    def test_out_of_range_strength_warns(self):
        specs, warnings = ld.parse_specs("a.safetensors: 500")
        self.assertEqual(specs[0]["strength_model"], ld.MAX_STRENGTH)
        self.assertTrue(any("超出" in w for w in warnings), warnings)

    def test_crlf_and_trailing_spaces(self):
        specs, _ = ld.parse_specs("a.safetensors\r\n   b.safetensors  \r\n")
        self.assertEqual([s["name"] for s in specs], ["a.safetensors", "b.safetensors"])

    def test_max_specs_is_enforced(self):
        raw = "\n".join(f"lora{i}.safetensors" for i in range(ld.MAX_SPECS + 6))
        specs, warnings = ld.parse_specs(raw)
        self.assertEqual(len(specs), ld.MAX_SPECS)
        self.assertTrue(any("超过" in w for w in warnings), warnings)

    def test_two_names_one_line(self):
        specs, _ = ld.parse_specs("a.safetensors, b.safetensors", self.KNOWN)
        self.assertEqual([s["name"] for s in specs], ["a.safetensors", "b.safetensors"])


class TestParseSlots(unittest.TestCase):
    """v1.3：下拉框（名字）+ 两个强度框 → specs。"""

    def test_constants(self):
        self.assertEqual(ld.SLOT_COUNT, 4)
        self.assertTrue(ld.SLOT_NONE)
        self.assertIn("SLOT_NONE", ld.__all__)
        self.assertIn("SLOT_COUNT", ld.__all__)
        self.assertIn("parse_slots", ld.__all__)

    def test_basic_rows(self):
        specs, warnings = ld.parse_slots(
            ["a.safetensors", "b.safetensors", "c.safetensors", "d.safetensors"],
            [0.8, 0.6, 1.0, 1.0],
            [0.5, 0.6, 1.0, 1.0],
        )
        self.assertEqual(warnings, [])
        self.assertEqual(
            [(s["name"], s["strength_model"], s["strength_clip"]) for s in specs],
            [
                ("a.safetensors", 0.8, 0.5),
                ("b.safetensors", 0.6, 0.6),
                ("c.safetensors", 1.0, 1.0),
                ("d.safetensors", 1.0, 1.0),
            ],
        )
        self.assertTrue(all(s["from_slot"] for s in specs))

    def test_row_order_is_preserved(self):
        specs, _ = ld.parse_slots(["c.safetensors", ld.SLOT_NONE, "a.safetensors"])
        self.assertEqual([s["name"] for s in specs], ["c.safetensors", "a.safetensors"])

    def test_none_and_blanks_are_skipped(self):
        specs, warnings = ld.parse_slots(
            [ld.SLOT_NONE, "", None, "  ", "a.safetensors"],
            [1.0, 1.0, 1.0, 1.0, 1.0],
            [1.0, 1.0, 1.0, 1.0, 1.0],
        )
        self.assertEqual([s["name"] for s in specs], ["a.safetensors"])
        self.assertEqual(warnings, [], "空行/不使用不算警告")

    def test_placeholder_rows_are_skipped(self):
        specs, _ = ld.parse_slots(["<未检测到 LoRA>", "a.safetensors"])
        self.assertEqual([s["name"] for s in specs], ["a.safetensors"])

    def test_clip_strength_defaults_to_model_strength(self):
        """程序化调用省略 CLIP 强度时跟随 MODEL（节点里两个框都有值，所以正常走不到这里）。"""
        specs, _ = ld.parse_slots(["a.safetensors"], [0.7])
        self.assertEqual(specs[0]["strength_model"], 0.7)
        self.assertEqual(specs[0]["strength_clip"], 0.7)
        specs, _ = ld.parse_slots(["a.safetensors"], [0.7], [None])
        self.assertEqual(specs[0]["strength_clip"], 0.7)

    def test_strengths_are_clamped_with_row_warning(self):
        specs, warnings = ld.parse_slots(
            ["a.safetensors", "b.safetensors"], [500, "abc"], [-500, 1.0]
        )
        self.assertEqual(specs[0]["strength_model"], ld.MAX_STRENGTH)
        self.assertEqual(specs[0]["strength_clip"], ld.MIN_STRENGTH)
        self.assertEqual(specs[1]["strength_model"], ld.DEFAULT_STRENGTH)
        self.assertTrue(any("第 1 行" in w and "超出" in w for w in warnings), warnings)
        self.assertTrue(any("第 2 行" in w and "不是有效数字" in w for w in warnings), warnings)

    def test_string_numbers_are_accepted(self):
        specs, _ = ld.parse_slots(["a.safetensors"], ["0.5"], ["-0.5"])
        self.assertEqual(specs[0]["strength_model"], 0.5)
        self.assertEqual(specs[0]["strength_clip"], -0.5)

    def test_no_name_completion_for_dropdown_values(self):
        """下拉框的值来自 ComfyUI 列表，不需要（也不应该）再补全成别的名字。"""
        specs, _ = ld.parse_slots(["C"], [1.0, 1.0])
        self.assertEqual([s["name"] for s in specs], ["C"])

    def test_max_specs_is_enforced(self):
        names = [f"lora{i}.safetensors" for i in range(ld.SLOT_COUNT)]
        specs, _ = ld.parse_slots(names * 40)
        self.assertLessEqual(len(specs), ld.MAX_SPECS)


class TestApplyLoras(unittest.TestCase):
    def test_missing_path_records_error(self):
        model = object()
        out_model, out_clip, outcomes = ld.apply_loras(
            model, None, [ld.make_spec("nope.safetensors")], resolve_path=lambda name: None
        )
        self.assertIs(out_model, model)
        self.assertIsNone(out_clip)
        self.assertFalse(outcomes[0]["ok"])
        self.assertEqual(outcomes[0]["path"], None)
        self.assertIn("找不到该文件", outcomes[0]["error"])

    def test_both_inputs_none_skips_loading_but_keeps_path(self):
        written = []
        _, _, outcomes = ld.apply_loras(
            None,
            None,
            [ld.make_spec("a.safetensors")],
            resolve_path=lambda name: r"X:\loras\a.safetensors",
            load_tensor=lambda path: written.append(path),
        )
        self.assertTrue(outcomes[0]["ok"])
        self.assertTrue(outcomes[0]["skipped"])
        self.assertEqual(written, [], "两个口都没接时不应该真的读文件")
        self.assertEqual(outcomes[0]["path"], r"X:\loras\a.safetensors")

    def test_load_and_apply_with_fakes(self):
        calls = []

        def fake_load(path):
            return {"file": path}, {"meta": path}

        def fake_apply(model, clip, lora, sm, sc, meta=None):
            calls.append((model, clip, lora, sm, sc, meta))
            return f"model+{lora['file']}", f"clip+{lora['file']}"

        model, clip, outcomes = ld.apply_loras(
            "M",
            "C",
            [ld.make_spec("a.safetensors", 0.8, 0.4)],
            resolve_path=lambda name: r"X:\loras\a.safetensors",
            load_tensor=fake_load,
            apply_one=fake_apply,
        )
        self.assertTrue(outcomes[0]["ok"])
        self.assertFalse(outcomes[0]["cached"])
        self.assertEqual(model, r"model+X:\loras\a.safetensors")
        self.assertEqual(clip, r"clip+X:\loras\a.safetensors")
        self.assertEqual(calls[0][3:], (0.8, 0.4, {"meta": r"X:\loras\a.safetensors"}))

    def test_sequential_application_chains_model(self):
        def fake_apply(model, clip, lora, sm, sc, meta=None):
            return (model or 0) + 1, (clip or 0) + 1

        model, clip, outcomes = ld.apply_loras(
            None,
            10,
            [ld.make_spec("a"), ld.make_spec("b")],
            resolve_path=lambda name: f"X:/{name}",
            load_tensor=lambda path: path,
            apply_one=fake_apply,
        )
        self.assertEqual(model, 2)
        self.assertEqual(clip, 12)
        self.assertTrue(all(o["ok"] for o in outcomes))

    def test_load_error_is_reported_and_loop_continues(self):
        good = []

        def fake_load(path):
            if path.endswith("bad"):
                raise OSError("boom")
            return path

        _, _, outcomes = ld.apply_loras(
            "M",
            None,
            [ld.make_spec("bad"), ld.make_spec("good")],
            resolve_path=lambda name: f"X:/{name}",
            load_tensor=fake_load,
            apply_one=lambda model, clip, lora, sm, sc, meta=None: (good.append(lora), (model, clip))[1],
        )
        self.assertFalse(outcomes[0]["ok"])
        self.assertIn("读取 LoRA 文件失败", outcomes[0]["error"])
        self.assertIn("boom", outcomes[0]["error"])
        self.assertTrue(outcomes[1]["ok"])
        self.assertEqual(good, ["X:/good"])

    def test_apply_error_is_reported_and_loop_continues(self):
        def fake_apply(model, clip, lora, sm, sc, meta=None):
            if lora == "X:/bad":
                raise RuntimeError("nope")
            return model, clip

        _, _, outcomes = ld.apply_loras(
            "M",
            None,
            [ld.make_spec("bad"), ld.make_spec("good")],
            resolve_path=lambda name: f"X:/{name}",
            load_tensor=lambda path: path,
            apply_one=fake_apply,
        )
        self.assertFalse(outcomes[0]["ok"])
        self.assertIn("应用 LoRA 失败", outcomes[0]["error"])
        self.assertTrue(outcomes[1]["ok"])

    def test_roots_are_used_for_path_resolution(self):
        seen = {}
        original = ls.get_lora_full_path

        def fake_get_path(name, search_roots=None):
            seen["name"] = name
            seen["roots"] = list(search_roots or [])
            return f"C:/loras/{name}"

        ls.get_lora_full_path = fake_get_path
        try:
            _, _, outcomes = ld.apply_loras(
                None, None, [ld.make_spec("a.safetensors")], roots=["C:/loras"], load_tensor=lambda p: p
            )
        finally:
            ls.get_lora_full_path = original
        self.assertEqual(seen["name"], "a.safetensors")
        self.assertEqual(seen["roots"], ["C:/loras"])
        self.assertEqual(outcomes[0]["path"], "C:/loras/a.safetensors")

    def test_resolve_path_exception_is_caught(self):
        def boom(name):
            raise RuntimeError("resolve failed")

        _, _, outcomes = ld.apply_loras(None, None, [ld.make_spec("a")], resolve_path=boom)
        self.assertFalse(outcomes[0]["ok"])
        self.assertIn("解析 LoRA 路径失败", outcomes[0]["error"])


class TestFormatLoadReport(unittest.TestCase):
    def test_empty_outcomes(self):
        self.assertEqual(ld.format_load_report([]), ["[多重加载器] lora_list 是空的，没有加载任何 LoRA。"])

    def test_loaded_lines(self):
        outcomes = [
            {"name": "Krea2/Krea2角色lora/妃咲.safetensors", "strength_model": 0.8, "strength_clip": 0.8,
             "ok": True, "skipped": False, "cached": False, "error": ""},
            {"name": "silver_wolf.safetensors", "strength_model": 1.0, "strength_clip": 0.5,
             "ok": True, "skipped": False, "cached": True, "error": ""},
        ]
        lines = ld.format_load_report(outcomes)
        self.assertIn("已加载 2 个 LoRA", lines[0])
        self.assertIn("妃咲.safetensors(0.8)", lines[0])
        self.assertIn("silver_wolf.safetensors(model 1 / clip 0.5)", lines[0])
        self.assertIn("其中 1 个直接用了内存缓存", lines[1])

    def test_skipped_line(self):
        outcomes = [
            {"name": "a.safetensors", "strength_model": 1.0, "strength_clip": 1.0,
             "ok": True, "skipped": True, "cached": False, "error": ""}
        ]
        lines = ld.format_load_report(outcomes)
        self.assertEqual(len(lines), 1)
        self.assertIn("MODEL / CLIP 都没接", lines[0])
        self.assertIn("触发词照常输出", lines[0])

    def test_failed_line(self):
        outcomes = [
            {"name": "a.safetensors", "strength_model": 1.0, "strength_clip": 1.0,
             "ok": False, "skipped": False, "cached": False, "error": "在 LoRA 目录里找不到该文件"}
        ]
        lines = ld.format_load_report(outcomes)
        self.assertIn("加载失败：a.safetensors", lines[0])
        self.assertIn("找不到该文件", lines[0])

    def test_unknown_error_fallback_text(self):
        outcomes = [{"name": "a", "ok": False, "error": ""}]
        self.assertIn("未知错误", ld.format_load_report(outcomes)[0])


class TestTensorCache(unittest.TestCase):
    def setUp(self):
        self.tmp = _mkdtemp("cache_")
        ld.clear_lora_cache()

    def tearDown(self):
        ld.clear_lora_cache()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, name: str, body: str = "x") -> str:
        path = os.path.join(self.tmp, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
        return path

    def test_file_stamp(self):
        path = self._write("a.bin", "12345")
        stamp = ld.file_stamp(path)
        self.assertEqual(stamp, f"{os.stat(path).st_size}|{int(os.stat(path).st_mtime_ns)}")
        self.assertEqual(ld.file_stamp(os.path.join(self.tmp, "missing.bin")), "-")

    def test_custom_loader_bypasses_cache(self):
        calls = []
        ld.load_tensor_cached(r"X:\a.bin", loader=lambda p: calls.append(p) or p)
        ld.load_tensor_cached(r"X:\a.bin", loader=lambda p: calls.append(p) or p)
        self.assertEqual(len(calls), 2)
        self.assertEqual(ld._LORA_CACHE, {})

    def test_custom_loader_tuple_and_single_value(self):
        lora, meta, cached = ld.load_tensor_cached("x", loader=lambda p: ({"t": 1}, {"m": 2}))
        self.assertEqual((lora, meta, cached), ({"t": 1}, {"m": 2}, False))
        lora, meta, cached = ld.load_tensor_cached("x", loader=lambda p: {"t": 3})
        self.assertEqual((lora, meta, cached), ({"t": 3}, None, False))

    def test_cache_hit_and_invalidation(self):
        path = self._write("a.bin", "aaa")
        loads = []
        original = ld._default_load_tensor

        def fake_default(p):
            loads.append(p)
            return {"file": p}, {"n": len(loads)}

        ld._default_load_tensor = fake_default
        try:
            first = ld.load_tensor_cached(path)
            second = ld.load_tensor_cached(path)
        finally:
            ld._default_load_tensor = original
        self.assertEqual(loads, [path], "第二次应该命中缓存")
        self.assertFalse(first[2])
        self.assertTrue(second[2])
        self.assertEqual(second[0], {"file": path})
        self.assertEqual(second[1], {"n": 1})

        # 文件变了（size 不同）-> 缓存失效
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("bbbb")
        ld._default_load_tensor = fake_default
        try:
            third = ld.load_tensor_cached(path)
        finally:
            ld._default_load_tensor = original
        self.assertFalse(third[2])
        self.assertEqual(loads, [path, path])

    def test_cache_eviction_keeps_cache_max(self):
        paths = [self._write(f"{i}.bin", "x" * (i + 1)) for i in range(ld.CACHE_MAX + 1)]
        original = ld._default_load_tensor
        ld._default_load_tensor = lambda p: (p, None)
        try:
            for path in paths:
                ld.load_tensor_cached(path)
        finally:
            ld._default_load_tensor = original
        self.assertEqual(len(ld._LORA_CACHE), ld.CACHE_MAX)
        first_key = os.path.normcase(os.path.abspath(paths[0]))
        self.assertNotIn(first_key, ld._LORA_CACHE, "最旧的条目应该被淘汰")

    def test_clear_lora_cache(self):
        ld._LORA_CACHE["k"] = ("s", 1, 2)
        ld.clear_lora_cache()
        self.assertEqual(len(ld._LORA_CACHE), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
