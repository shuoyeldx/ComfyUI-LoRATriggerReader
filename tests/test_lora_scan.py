# -*- coding: utf-8 -*-
"""ComfyUI-LoRATriggerReader 单元测试（纯标准库，无需 ComfyUI / torch）。

运行方式::

    python -m unittest discover -s tests -v
    # 或者
    python tests/test_lora_scan.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from lora_trigger_reader import lora_scan as ls  # noqa: E402

# 临时目录放在测试文件旁边（而不是系统 TEMP），这样在受限沙箱 / 只读 TEMP 环境下也能跑
TMP_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(TMP_ROOT, exist_ok=True)


def _mkdtemp(prefix: str) -> str:
    """自建临时目录。

    不用 ``tempfile.mkdtemp``：它用 ``os.mkdir(..., 0o700)``，而 Windows 版 CPython
    会真的去 chmod，导致目录 DACL 只留给属主，受限沙箱/受控环境下再往里建子目录
    会被拒绝（WinError 5）。这里用默认 0o777 创建，继承父目录权限。
    """
    path = os.path.join(TMP_ROOT, prefix + uuid.uuid4().hex[:10])
    os.makedirs(path)
    return path


def make_entry(path: str) -> dict:
    """按 collect_text_files 的格式手工造一个索引条目。"""
    fn = os.path.basename(path)
    stem = os.path.splitext(fn)[0]
    return {
        "path": path,
        "name": fn,
        "stem": stem,
        "norm_stem": ls.normalize(stem),
        "suffix_stem": ls.strip_suffix_words(stem),
        "dir": os.path.dirname(path),
        "ext": os.path.splitext(fn)[1].lower(),
        "size": 0,
        "mtime": 0.0,
    }


class TestNaming(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(ls.normalize("Anima 尼可-v2.safetensors"), "anima尼可v2safetensors")
        self.assertEqual(ls.normalize(""), "")

    def test_strip_suffix_words(self):
        self.assertEqual(ls.strip_suffix_words("Anima尼可提示词"), "anima尼可")
        self.assertEqual(ls.strip_suffix_words("silver_wolf_lv999_comfy_v2提示词"), "silverwolflv999comfyv2")
        self.assertEqual(ls.strip_suffix_words("鸣潮画风lora"), "鸣潮画风lora")
        self.assertEqual(ls.strip_suffix_words("krea2_better_pussy_poses_v4.2.1"), "krea2betterpussyposesv421")
        self.assertEqual(ls.strip_suffix_words("Lora trigger words"), "lora")


class TestScoring(unittest.TestCase):
    def setUp(self):
        self.dir = "E:/fake/loras"

    def test_same_name_with_extension_in_stem(self):
        # 文本文件叫 "Anima尼可.safetensors.txt" 这种极端情况
        e = make_entry("E:/fake/loras/Anima尼可.safetensors.txt")
        self.assertEqual(ls.score_entry("Anima尼可.safetensors", e, lora_dir="E:/fake/loras"), 1000 + 25)

    def test_same_name(self):
        e = make_entry("E:/fake/loras/Anima尼可.txt")
        self.assertEqual(ls.score_entry("Anima尼可.safetensors", e, lora_dir="E:/fake/loras"), 980 + 25)

    def test_same_stem_other_ext(self):
        e = make_entry("E:/fake/loras/Anima尼可.md")
        self.assertGreaterEqual(ls.score_entry("Anima尼可.safetensors", e), 980)

    def test_suffix_word_match(self):
        e = make_entry("E:/fake/loras/Anima尼可提示词.txt")
        self.assertEqual(ls.score_entry("Anima尼可.safetensors", e, lora_dir="E:/fake/loras"), 950 + 25)

    def test_starts_with(self):
        e = make_entry("E:/fake/loras/silver_wolf_lv999_comfy_v2_说明文案.txt")
        self.assertGreaterEqual(ls.score_entry("silver_wolf_lv999_comfy_v2.safetensors", e), 900)

    def test_contains_full_lora_name(self):
        e = make_entry("E:/fake/loras/【角色】krea2_better_pussy_poses_v4.2.1 触发词.txt")
        self.assertGreaterEqual(ls.score_entry("krea2_better_pussy_poses_v4.2.1.safetensors", e), 850)

    def test_no_match(self):
        e = make_entry("E:/fake/loras/完全不相干的东西.txt")
        self.assertEqual(ls.score_entry("Anima尼可.safetensors", e), 0)

    def test_short_generic_stem_does_not_hijack(self):
        """极短的名字不能参与"包含类"匹配，否则 LoRA `ghost_a` 会抢走 `A.txt`。"""
        e = make_entry("E:/fake/loras/A.txt")
        self.assertEqual(ls.score_entry("ghost_a.safetensors", e), 0)
        # 真正同名的当然还是匹配（980 档不受影响）
        self.assertGreaterEqual(ls.score_entry("A.safetensors", e), 980)
        # 两个字符的 ASCII 名字同样属于"太泛"
        e2 = make_entry("E:/fake/loras/abc.txt")
        self.assertEqual(ls.score_entry("ab.safetensors", e2), 0)

    def test_two_char_cjk_name_is_specific_enough(self):
        """两个汉字信息量足够，应当允许参与包含类匹配。"""
        e = make_entry("E:/fake/loras/妃咲-全身图.txt")
        self.assertGreaterEqual(ls.score_entry("妃咲.safetensors", e), 850)
        self.assertTrue(ls._specific_enough("妃咲"))
        self.assertFalse(ls._specific_enough("a"))
        self.assertFalse(ls._specific_enough("ab"))
        self.assertTrue(ls._specific_enough("abcd"))

    def test_owner_conflict_is_rejected(self):
        # 文本 AB触发词.txt 更像属于 LoRA AB，不应被 LoRA A 抢走
        e = make_entry("E:/fake/loras/AB触发词.txt")
        others = [ls.normalize("A"), ls.normalize("AB")]
        self.assertEqual(ls.score_entry("A.safetensors", e, other_lora_norms=others), 0)
        self.assertGreater(ls.score_entry("AB.safetensors", e, other_lora_norms=others), 0)

    def test_same_dir_bonus(self):
        e1 = make_entry("E:/fake/loras/sub/Anima尼可提示词.txt")
        e2 = make_entry("E:/fake/loras/Anima尼可提示词.txt")
        s1 = ls.score_entry("Anima尼可.safetensors", e1, lora_dir="E:/fake/loras/sub")
        s2 = ls.score_entry("Anima尼可.safetensors", e2, lora_dir="E:/fake/loras/sub")
        self.assertEqual(s1 - s2, 25)

    def test_pick_best_among_candidates(self):
        lora = "Anima/角色lora/Anima尼可.safetensors"
        entries = [
            make_entry("E:/loras/Anima/角色lora/Anima尼可.txt"),
            make_entry("E:/loras/Anima/角色lora/Anima尼可提示词.txt"),
            make_entry("E:/loras/其他/尼可.txt"),
        ]
        best, score, cands = ls.match_text_entry(lora, entries)
        self.assertIsNotNone(best)
        self.assertTrue(best["name"].startswith("Anima尼可"))
        self.assertGreaterEqual(score, 950)
        self.assertGreaterEqual(len(cands), 2)


class TestReadAndFormat(unittest.TestCase):
    def setUp(self):
        self.tmp = _mkdtemp("loratrig_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, name, data: bytes) -> str:
        p = os.path.join(self.tmp, name)
        with open(p, "wb") as f:
            f.write(data)
        return p

    def test_read_utf8(self):
        p = self._write("a.txt", "你好, hello".encode("utf-8"))
        text, enc, trunc = ls.read_text(p)
        self.assertEqual(text, "你好, hello")
        self.assertEqual(enc, "utf-8")
        self.assertFalse(trunc)

    def test_read_utf8_bom(self):
        p = self._write("b.txt", "\ufeff触发词".encode("utf-8"))
        text, enc, _ = ls.read_text(p)
        self.assertEqual(text, "触发词")
        self.assertEqual(enc, "utf-8-sig")

    def test_read_gbk(self):
        p = self._write("c.txt", "妃咲，触发词".encode("gbk"))
        text, enc, _ = ls.read_text(p)
        self.assertEqual(text, "妃咲，触发词")
        self.assertIn(enc, ("gb18030", "gbk"))

    def test_read_utf16(self):
        p = self._write("d.txt", "触发词".encode("utf-16"))
        text, enc, _ = ls.read_text(p)
        self.assertEqual(text, "触发词")
        self.assertEqual(enc, "utf-16")

    def test_read_empty_file(self):
        p = self._write("e.txt", b"")
        text, _, _ = ls.read_text(p)
        self.assertEqual(text, "")
        self.assertEqual(ls.format_trigger_text(text), "")

    def test_truncate_huge_file(self):
        p = self._write("f.txt", b"x" * (ls.MAX_FILE_BYTES + 10))
        text, _, trunc = ls.read_text(p)
        self.assertTrue(trunc)
        self.assertEqual(len(text), ls.MAX_FILE_BYTES)

    def test_format_multiline(self):
        raw = "FX_cos, cosplayer\n\n\nnavy sleeveless cheongsam，\n\nblack high heels\n"
        self.assertEqual(
            ls.format_trigger_text(raw),
            "FX_cos, cosplayer, navy sleeveless cheongsam, black high heels",
        )

    def test_format_dedup_case_insensitive(self):
        raw = "Foo,\nfoo,\nBAR"
        self.assertEqual(ls.format_trigger_text(raw, deduplicate=True), "Foo, BAR")
        self.assertEqual(ls.format_trigger_text(raw, deduplicate=False), "Foo, foo, BAR")

    def test_format_comments_and_blank(self):
        raw = "# 注释\n// 注释2\nreal, words,\n\n"
        self.assertEqual(ls.format_trigger_text(raw), "real, words")

    def test_format_custom_separator(self):
        raw = "a,\nb,\nc"
        self.assertEqual(ls.format_trigger_text(raw, separator=" | "), "a | b | c")
        self.assertEqual(ls.format_trigger_text(raw, separator="\\n"), "a\nb\nc")


class TestParseLoraText(unittest.TestCase):
    KNOWN = ["Anima/角色lora/Anima尼可.safetensors", "Krea2/妃咲.safetensors", "wan/加速.safetensors"]

    def test_newline_separated(self):
        raw = "Krea2/妃咲.safetensors\nwan/加速.safetensors"
        self.assertEqual(ls.parse_lora_text(raw), ["Krea2/妃咲.safetensors", "wan/加速.safetensors"])

    def test_trailing_commas_and_blanks(self):
        raw = "  Krea2/妃咲.safetensors,\n\n,\nwan/加速.safetensors ,\n"
        self.assertEqual(ls.parse_lora_text(raw), ["Krea2/妃咲.safetensors", "wan/加速.safetensors"])

    def test_comments(self):
        raw = "# 角色\nKrea2/妃咲.safetensors\n// 另一只\nwan/加速.safetensors # 备注"
        self.assertEqual(ls.parse_lora_text(raw), ["Krea2/妃咲.safetensors", "wan/加速.safetensors"])

    def test_comma_split_with_known_names(self):
        raw = "Krea2/妃咲.safetensors, wan/加速.safetensors"
        self.assertEqual(ls.parse_lora_text(raw, self.KNOWN), ["Krea2/妃咲.safetensors", "wan/加速.safetensors"])

    def test_comma_without_known_names_not_split(self):
        raw = "Krea2/妃咲.safetensors, wan/加速.safetensors"
        self.assertEqual(ls.parse_lora_text(raw), [raw])

    def test_deduplicate(self):
        raw = "wan/加速.safetensors\nwan/加速.safetensors\nWAN/加速.safetensors"
        self.assertEqual(ls.parse_lora_text(raw), ["wan/加速.safetensors"])

    def test_empty(self):
        self.assertEqual(ls.parse_lora_text(""), [])
        self.assertEqual(ls.parse_lora_text(None), [])

    def test_canonicalize_bare_stem(self):
        # 只写角色名也能补全成完整相对路径
        self.assertEqual(ls.parse_lora_text("妃咲", self.KNOWN), ["Krea2/妃咲.safetensors"])
        self.assertEqual(ls.parse_lora_text("妃咲.safetensors", self.KNOWN), ["Krea2/妃咲.safetensors"])

    def test_canonicalize_ambiguous_kept(self):
        known = ["A/x.safetensors", "B/x.safetensors"]
        self.assertEqual(ls.parse_lora_text("x", known), ["x"])

    def test_canonicalize_full_path_untouched(self):
        self.assertEqual(ls.parse_lora_text("wan/加速.safetensors", self.KNOWN), ["wan/加速.safetensors"])


class TestResolveOnTempTree(unittest.TestCase):
    """用临时目录模拟真实的 LoRA 目录结构。"""

    def setUp(self):
        self.tmp = _mkdtemp("loratrig_tree_")
        self.loras = os.path.join(self.tmp, "loras")
        os.makedirs(os.path.join(self.loras, "Anima", "角色lora"))
        os.makedirs(os.path.join(self.loras, "Krea2"))
        self.roots = [self.loras]
        ls.clear_index_cache()

        self._touch(os.path.join(self.loras, "Anima", "角色lora", "Anima尼可.safetensors"))
        self._touch(os.path.join(self.loras, "Anima", "角色lora", "silver_wolf_lv999_comfy_v2.safetensors"))
        self._touch(os.path.join(self.loras, "Krea2", "妃咲.safetensors"))
        self._touch(os.path.join(self.loras, "Krea2", "无触发词.safetensors"))

        self._text(os.path.join(self.loras, "Anima", "角色lora", "Anima尼可提示词.txt"), "")
        self._text(
            os.path.join(self.loras, "Anima", "角色lora", "silver_wolf_lv999_comfy_v2提示词.txt"),
            "silver wolf (lv.999) (honkai: star rail), confident smile, looking at viewer, cowboy shot,",
        )
        self._text(
            os.path.join(self.loras, "Krea2", "妃咲.txt"),
            "FX_cos, cosplayer\n\nnavy sleeveless cheongsam,\n\nblack high heels\n",
        )
        # 干扰文件：应被归属校验挡掉
        self._text(os.path.join(self.loras, "Krea2", "妃咲改.txt"), "wrong trigger")

    def tearDown(self):
        ls.clear_index_cache()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _touch(self, p):
        with open(p, "wb") as f:
            f.write(b"\0" * 8)

    def _text(self, p, s):
        with open(p, "w", encoding="utf-8") as f:
            f.write(s)

    def test_index_collects_text_only(self):
        entries = ls.build_index(self.roots, refresh=True)
        names = sorted(e["name"] for e in entries)
        self.assertEqual(names, ["Anima尼可提示词.txt", "silver_wolf_lv999_comfy_v2提示词.txt", "妃咲.txt", "妃咲改.txt"])

    def test_resolve_ok(self):
        res = ls.resolve_lora(
            "Anima/角色lora/silver_wolf_lv999_comfy_v2.safetensors",
            roots=self.roots,
            all_lora_names=[
                "Anima/角色lora/silver_wolf_lv999_comfy_v2.safetensors",
                "Krea2/妃咲.safetensors",
            ],
        )
        self.assertEqual(res["status"], "ok")
        self.assertTrue(res["trigger_file"].endswith("silver_wolf_lv999_comfy_v2提示词.txt"))
        self.assertEqual(
            res["text"],
            "silver wolf (lv.999) (honkai: star rail), confident smile, looking at viewer, cowboy shot",
        )

    def test_resolve_empty_file(self):
        res = ls.resolve_lora("Anima/角色lora/Anima尼可.safetensors", roots=self.roots)
        self.assertEqual(res["status"], "empty")
        self.assertTrue(res["trigger_file"].endswith("Anima尼可提示词.txt"))
        self.assertEqual(res["text"], "")

    def test_resolve_missing_trigger(self):
        res = ls.resolve_lora("Krea2/无触发词.safetensors", roots=self.roots)
        self.assertEqual(res["status"], "no_trigger")

    def test_resolve_missing_lora(self):
        res = ls.resolve_lora("Krea2/根本不存在.safetensors", roots=self.roots)
        self.assertEqual(res["status"], "no_lora")

    def test_resolve_multi_merge_and_dedupe(self):
        names = [
            "Krea2/妃咲.safetensors",
            "Anima/角色lora/silver_wolf_lv999_comfy_v2.safetensors",
            "Krea2/妃咲.safetensors",
            "Krea2/无触发词.safetensors",
        ]
        text, report, results = ls.resolve_loras(names, roots=self.roots)
        self.assertEqual(len(results), 4)
        self.assertIn("FX_cos", text)
        self.assertIn("silver wolf (lv.999)", text)
        self.assertEqual(text.count("FX_cos"), 1)
        self.assertIn("共 4 个 LoRA", report)

    def test_resolve_multi_separator_newline(self):
        names = ["Krea2/妃咲.safetensors"]
        text, _, _ = ls.resolve_loras(names, separator="\\n", roots=self.roots)
        self.assertEqual(len(text.split("\n")), 3)

    def test_fallback_modes(self):
        res = ls.resolve_lora("Krea2/无触发词.safetensors", roots=self.roots)
        self.assertEqual(ls.resolve_with_fallback(res, "empty", "x"), "")
        self.assertEqual(ls.resolve_with_fallback(res, "lora_name", "x"), "无触发词")
        self.assertEqual(ls.resolve_with_fallback(res, "custom", "自定义触发词"), "自定义触发词")

    def test_extra_dirs(self):
        extra = os.path.join(self.tmp, "extra")
        os.makedirs(extra)
        with open(os.path.join(extra, "无触发词.md"), "w", encoding="utf-8") as f:
            f.write("extra-dir-trigger")
        ls.clear_index_cache()
        res = ls.resolve_lora(
            "Krea2/无触发词.safetensors",
            roots=self.roots,
            extra_dirs=extra,
        )
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["text"], "extra-dir-trigger")


class TestFolderPathsCompat(unittest.TestCase):
    def test_soft_dependency_helpers_do_not_raise(self):
        # 无论是否装了 ComfyUI，这些函数都必须安全返回
        self.assertIsInstance(ls.get_lora_roots(), list)
        self.assertIsInstance(ls.list_lora_names(), list)
        self.assertIsInstance(ls.has_folder_paths(), bool)
        self.assertIsNone(ls.get_lora_full_path(""))
        self.assertIsNone(ls.get_lora_full_path("不存在的LoRA.safetensors", search_roots=[]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
