# -*- coding: utf-8 -*-
"""``graph_probe`` 的单元测试：从 API 格式工作流反查"接入链路上用了哪些 LoRA"。

不依赖 ComfyUI / torch，纯 dict 输入输出。

运行方式::

    python -m unittest discover -s tests -v
    python tests/test_graph_probe.py
"""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from lora_trigger_reader import graph_probe  # noqa: E402


# --------------------------------------------------------------------------- 造数据

def loader(node_id, lora_name, model_to, key="lora_name", cls="LoraLoader", title=None):
    """一个 LoRA 选择节点的 API 格式片段。"""
    node = {
        "class_type": cls,
        "inputs": {
            key: lora_name,
            "strength_model": 1.0,
            "model": [model_to, 0],
            "clip": [model_to, 1],
        },
    }
    if title:
        node["_meta"] = {"title": title}
    return node


def chain_prompt(lora_names, reader_id="100", reader_type="LoRATriggerReader", extra_loras=""):
    """构造 ``CheckpointLoaderSimple -> LoraLoader... -> reader`` 的 prompt。

    ``lora_names`` 按「离 reader 由近到远」的顺序给出。
    reader 默认放在 id=100，避免和链上的 LoRA 节点 id 撞车。
    """
    prompt = {"1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "base.safetensors"}}}
    prev = "1"
    for index, name in enumerate(reversed(list(lora_names)), start=2):
        nid = str(index)
        prompt[nid] = loader(nid, name, prev)
        prev = nid
    prompt[reader_id] = {
        "class_type": reader_type,
        "inputs": {"model": [prev, 0], "extra_loras": extra_loras},
    }
    return prompt


# ============================================================================
#  输入名判定
# ============================================================================
class TestIsLoraKey(unittest.TestCase):
    def test_recognised_keys(self):
        for key in (
            "lora",
            "lora_name",
            "lora_names",
            "lora_list",  # 本插件「多重 LoRA 加载器」的文本框
            "lora_list_1",
            "lora_1_list",
            "loras",
            "lora_1",
            "lora_2",
            "lora_name_1",
            "lora_names_2",
            "lora_1_name",
            "lora_1_path",
            "lora_path",
            "lora_file",
            "lora_filename",
            "lora_stack",
            "lora_stacks",
            "Lora_Name",  # 大小写不敏感
        ):
            with self.subTest(key=key):
                self.assertTrue(graph_probe.is_lora_key(key), key)

    def test_rejects_strength_and_unrelated(self):
        for key in (
            "lora_strength",
            "lora_1_strength",
            "lora_2_weight",
            "lora_model",
            "lora_type",
            "strength_model",
            "ckpt_name",
            "model",
            "text",
            "extra_loras",  # 本插件自己的"手动补充"输入，不是 LoRA 选择器
            "",
            None,
        ):
            with self.subTest(key=key):
                self.assertFalse(graph_probe.is_lora_key(key), repr(key))


class TestSplitNames(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(graph_probe.split_names("a.safetensors"), ["a.safetensors"])

    def test_multiline_and_delimiters(self):
        self.assertEqual(
            graph_probe.split_names("a.safetensors\nb.safetensors, c.safetensors;d.safetensors、e.safetensors"),
            ["a.safetensors", "b.safetensors", "c.safetensors", "d.safetensors", "e.safetensors"],
        )

    def test_quotes_comments_and_slashes(self):
        self.assertEqual(graph_probe.split_names('"Krea2/a.safetensors"'), ["Krea2/a.safetensors"])
        self.assertEqual(graph_probe.split_names("a.safetensors  # 中文注释"), ["a.safetensors"])
        self.assertEqual(graph_probe.split_names("# 整行注释"), [])
        self.assertEqual(graph_probe.split_names("sub\\C.safetensors"), ["sub/C.safetensors"])

    def test_lists_and_empty_values(self):
        self.assertEqual(graph_probe.split_names(["a.safetensors", "b.safetensors"]), ["a.safetensors", "b.safetensors"])
        for value in ("", "   ", "None", "none", "null", "未选择", "<未检测到 LoRA>", None, 12, 3.5):
            with self.subTest(value=value):
                self.assertEqual(graph_probe.split_names(value), [])

    def test_overlong_piece_is_dropped(self):
        self.assertEqual(graph_probe.split_names("x" * 600), [])

    def test_strength_tails_are_stripped(self):
        # lora_list 里可以写 "名字: 0.8" / "名字 @ 0.8" / "名字, 0.8"（含全角冒号）
        self.assertEqual(graph_probe.split_names("a.safetensors: 0.8"), ["a.safetensors"])
        self.assertEqual(graph_probe.split_names("a.safetensors：0.8"), ["a.safetensors"])
        self.assertEqual(graph_probe.split_names("a.safetensors @ 0.8"), ["a.safetensors"])
        self.assertEqual(graph_probe.split_names("a.safetensors: 0.8, 0.5"), ["a.safetensors"])
        self.assertEqual(graph_probe.split_names("a.safetensors, 0.8"), ["a.safetensors"])
        self.assertEqual(
            graph_probe.split_names("a.safetensors: 0.8\nb.safetensors @ 1.2\nc.safetensors, 0.5"),
            ["a.safetensors", "b.safetensors", "c.safetensors"],
        )

    def test_windows_path_colon_is_not_a_strength_tail(self):
        # 冒号右边必须是数字才当强度，所以绝对路径不会被切断
        self.assertEqual(graph_probe.split_names(r"C:\loras\x.safetensors"), ["C:/loras/x.safetensors"])

    def test_number_only_pieces_are_dropped(self):
        self.assertEqual(graph_probe.split_names("0.8"), [])
        self.assertEqual(graph_probe.split_names("a.safetensors, 0.8, 0.5"), ["a.safetensors"])
        self.assertEqual(graph_probe.split_names("a.safetensors: 0.8, 0.5"), ["a.safetensors"])


class TestIsLinkAndGetNode(unittest.TestCase):
    def test_is_link(self):
        self.assertTrue(graph_probe.is_link(["1", 0]))
        self.assertTrue(graph_probe.is_link((2, 1)))
        for value in ("1", ["1"], ["1", "0"], [1], None, 0, {"a": 1}):
            with self.subTest(value=value):
                self.assertFalse(graph_probe.is_link(value), repr(value))

    def test_get_node_accepts_str_and_int_ids(self):
        prompt = {"3": {"class_type": "LoraLoader", "inputs": {}}, 4: {"class_type": "X", "inputs": {}}}
        self.assertEqual(graph_probe.get_node(prompt, "3")["class_type"], "LoraLoader")
        self.assertEqual(graph_probe.get_node(prompt, 3)["class_type"], "LoraLoader")
        self.assertEqual(graph_probe.get_node(prompt, 4)["class_type"], "X")
        self.assertEqual(graph_probe.get_node(prompt, "4")["class_type"], "X")
        self.assertIsNone(graph_probe.get_node(prompt, "99"))
        self.assertIsNone(graph_probe.get_node(None, "3"))


# ============================================================================
#  反查链路
# ============================================================================
class TestIterLoraEntries(unittest.TestCase):
    def test_returns_nearest_first(self):
        prompt = chain_prompt(["nearest.safetensors", "farther.safetensors"])
        entries = graph_probe.iter_lora_entries(prompt, "100")
        self.assertEqual([e["lora_name"] for e in entries], ["nearest.safetensors", "farther.safetensors"])
        self.assertEqual([e["node_id"] for e in entries], ["3", "2"])

    def test_entry_fields(self):
        prompt = chain_prompt(["sub/C.safetensors"])
        prompt["2"]["_meta"] = {"title": "我的 LoRA"}
        entry = graph_probe.iter_lora_entries(prompt, "100")[0]
        self.assertEqual(entry["node_id"], "2")
        self.assertEqual(entry["class_type"], "LoraLoader")
        self.assertEqual(entry["title"], "我的 LoRA")
        self.assertEqual(entry["key"], "lora_name")
        self.assertEqual(entry["lora_name"], "sub/C.safetensors")

    def test_unrelated_branch_is_ignored(self):
        prompt = chain_prompt(["on_chain.safetensors"])
        # 一个没连到 reader 的 LoRA 节点（例如只给 CLIP 用）
        prompt["20"] = loader("20", "off_chain.safetensors", "1")
        self.assertEqual([e["lora_name"] for e in graph_probe.iter_lora_entries(prompt, "100")], ["on_chain.safetensors"])

    def test_duplicate_names_are_collapsed_per_node(self):
        prompt = chain_prompt(["A.safetensors", "A.safetensors"])
        entries = graph_probe.iter_lora_entries(prompt, "100")
        self.assertEqual(len(entries), 2)  # 两个节点各一条
        self.assertEqual([e["lora_name"] for e in entries], ["A.safetensors", "A.safetensors"])

    def test_stacker_style_keys(self):
        """第三方多 LoRA 堆叠节点：一个节点里多个 lora_N_name 输入。"""
        prompt = {"1": {"class_type": "CheckpointLoaderSimple", "inputs": {}}}
        prompt["2"] = {
            "class_type": "LoraStacker",
            "inputs": {
                "lora_1_name": "one.safetensors",
                "lora_1_strength": 0.8,
                "lora_2_name": "two.safetensors",
                "lora_2_strength": 0.5,
                "model": ["1", 0],
            },
        }
        prompt["100"] = {"class_type": "LoRATriggerReaderMulti", "inputs": {"model": ["2", 0]}}
        entries = graph_probe.iter_lora_entries(prompt, "100")
        self.assertEqual([e["lora_name"] for e in entries], ["one.safetensors", "two.safetensors"])
        self.assertEqual({e["key"] for e in entries}, {"lora_1_name", "lora_2_name"})

    def test_widget_converted_to_input_is_followed(self):
        """widget 被转成输入端（连到 PrimitiveNode）时也能找回字符串。"""
        prompt = {
            "1": {"class_type": "CheckpointLoaderSimple", "inputs": {}},
            "4": {"class_type": "PrimitiveNode", "inputs": {"value": "from_primitive.safetensors"}},
            "5": {"class_type": "LoraLoader", "inputs": {"lora_name": ["4", 0], "model": ["1", 0]}},
            "100": {"class_type": "LoRATriggerReader", "inputs": {"model": ["5", 0]}},
        }
        entries = graph_probe.iter_lora_entries(prompt, "100")
        self.assertEqual([e["lora_name"] for e in entries], ["from_primitive.safetensors"])

    def test_widget_converted_to_input_without_string_is_skipped(self):
        prompt = {
            "1": {"class_type": "CheckpointLoaderSimple", "inputs": {}},
            "4": {"class_type": "SomeNode", "inputs": {"a": "x", "b": "y"}},  # 多个候选，无法判断
            "5": {"class_type": "LoraLoader", "inputs": {"lora_name": ["4", 0], "model": ["1", 0]}},
            "100": {"class_type": "LoRATriggerReader", "inputs": {"model": ["5", 0]}},
        }
        self.assertEqual(graph_probe.iter_lora_entries(prompt, "100"), [])

    def test_cycle_terminates(self):
        prompt = {
            "2": {"class_type": "LoraLoader", "inputs": {"lora_name": "a.safetensors", "model": ["3", 0]}},
            "3": {"class_type": "LoraLoader", "inputs": {"lora_name": "b.safetensors", "model": ["2", 0]}},
            "100": {"class_type": "LoRATriggerReader", "inputs": {"model": ["2", 0]}},
        }
        entries = graph_probe.iter_lora_entries(prompt, "100")
        self.assertEqual(sorted(e["lora_name"] for e in entries), ["a.safetensors", "b.safetensors"])

    def test_max_depth_and_max_nodes(self):
        prompt = chain_prompt(["one.safetensors", "two.safetensors", "three.safetensors"])
        self.assertEqual(len(graph_probe.iter_lora_entries(prompt, "100", max_depth=2)), 2)
        self.assertEqual(len(graph_probe.iter_lora_entries(prompt, "100", max_nodes=1)), 1)

    def test_unknown_reader_id(self):
        self.assertEqual(graph_probe.iter_lora_entries(chain_prompt([]), "77"), [])


    def test_multi_loader_node_is_read_from_its_text_box(self):
        """「多重 LoRA 加载器」的 lora_list 文本框也要能被反查到（含强度写法）。"""
        prompt = {
            "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "base.safetensors"}},
            "2": loader("2", "upstream.safetensors", "1"),
            "3": {
                "class_type": "LoRAMultiLoader",
                "inputs": {
                    "lora_list": "a.safetensors: 0.8\nb.safetensors @ 1.2",
                    "model": ["2", 0],
                    "clip": ["1", 1],
                    "strength_model": 1.0,
                },
            },
            "100": {"class_type": "LoRATriggerReader", "inputs": {"model": ["3", 0]}},
        }
        entries = graph_probe.iter_lora_entries(prompt, "100")
        self.assertEqual([e["node_id"] for e in entries], ["3", "3", "2"])
        self.assertEqual(
            [e["lora_name"] for e in entries],
            ["a.safetensors", "b.safetensors", "upstream.safetensors"],
        )
        self.assertEqual(entries[0]["key"], "lora_list")
        self.assertEqual(entries[0]["class_type"], "LoRAMultiLoader")
        self.assertEqual(graph_probe.collect_names(graph_probe.probe_prompt(prompt, "100")),
                         ["a.safetensors", "b.safetensors", "upstream.safetensors"])

    def test_multi_loader_empty_list_falls_through_to_upstream(self):
        prompt = {
            "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "base.safetensors"}},
            "2": loader("2", "upstream.safetensors", "1"),
            "3": {
                "class_type": "LoRAMultiLoader",
                "inputs": {"lora_list": "", "model": ["2", 0], "clip": ["1", 1]},
            },
            "100": {"class_type": "LoRATriggerReader", "inputs": {"model": ["3", 0]}},
        }
        entries = graph_probe.iter_lora_entries(prompt, "100")
        self.assertEqual([e["lora_name"] for e in entries], ["upstream.safetensors"])

    def test_multi_loader_dropdown_rows_are_read_in_row_order(self):
        """v1.3：多重加载器的 4 行下拉框（lora_1..4）要按行号被反查到，「不使用」要跳过。"""
        prompt = {
            "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "base.safetensors"}},
            "3": {
                "class_type": "LoRAMultiLoader",
                "inputs": {
                    "lora_1": "first.safetensors",
                    "strength_1": 0.8,
                    "clip_strength_1": 0.5,
                    "lora_2": "不使用 / none",
                    "strength_2": 1.0,
                    "clip_strength_2": 1.0,
                    "lora_3": "third.safetensors",
                    "strength_3": 1.0,
                    "clip_strength_3": 1.0,
                    "lora_4": "",
                    "strength_4": 1.0,
                    "clip_strength_4": 1.0,
                    "lora_list": "",
                    "model": ["1", 0],
                    "clip": ["1", 1],
                },
            },
            "100": {"class_type": "LoRATriggerReader", "inputs": {"model": ["3", 0]}},
        }
        entries = graph_probe.iter_lora_entries(prompt, "100")
        self.assertEqual([e["key"] for e in entries], ["lora_1", "lora_3"])
        self.assertEqual([e["lora_name"] for e in entries], ["first.safetensors", "third.safetensors"])
        # 强度控件不能被当成 LoRA 名字
        self.assertFalse(any("strength" in e["key"] for e in entries))

    def test_none_sentinel_is_not_a_lora_name(self):
        """v1.3 下拉框的默认值「不使用 / none」等于没选。"""
        for value in ("不使用 / none", "不使用", "none", "None", "不使用/none"):
            with self.subTest(value=value):
                self.assertEqual(graph_probe.split_names(value), [])
        # 但名字里带「不使用」以外的内容照旧能读出来
        self.assertEqual(graph_probe.split_names("lora_2"), ["lora_2"])


class TestProbePrompt(unittest.TestCase):
    def test_ok_payload(self):
        prompt = chain_prompt(["nearest.safetensors", "farther.safetensors"])
        probe = graph_probe.probe_prompt(prompt, "100")
        self.assertTrue(probe["ok"])
        self.assertEqual(probe["node_id"], "100")
        self.assertIsNone(probe["error"])
        self.assertEqual(probe["loras"], ["nearest.safetensors", "farther.safetensors"])
        self.assertEqual([s["node_id"] for s in probe["sources"]], ["3", "2"])
        self.assertEqual(probe["sources"][0]["loras"], ["nearest.safetensors"])

    def test_loras_are_deduplicated_across_nodes(self):
        prompt = chain_prompt(["A.safetensors", "A.safetensors"])
        probe = graph_probe.probe_prompt(prompt, "100")
        self.assertEqual(probe["loras"], ["A.safetensors"])
        self.assertEqual(len(probe["entries"]), 2)

    def test_int_node_id(self):
        probe = graph_probe.probe_prompt(chain_prompt(["A.safetensors"]), 100)
        self.assertTrue(probe["ok"])
        self.assertEqual(probe["node_id"], "100")

    def test_missing_prompt_or_node(self):
        for prompt, node_id, needle in (
            (None, "100", "prompt"),
            ({}, "100", "prompt"),
            (chain_prompt(["A.safetensors"]), None, "id"),
            (chain_prompt(["A.safetensors"]), "", "id"),
            (chain_prompt(["A.safetensors"]), "77", "找不到"),
        ):
            with self.subTest(prompt=prompt, node_id=node_id):
                probe = graph_probe.probe_prompt(prompt, node_id)
                self.assertFalse(probe["ok"])
                self.assertIn(needle, probe["error"])
                self.assertEqual(probe["loras"], [])
                self.assertEqual(graph_probe.collect_names(probe), [])

    def test_no_lora_on_chain(self):
        prompt = chain_prompt([])
        probe = graph_probe.probe_prompt(prompt, "100")
        self.assertTrue(probe["ok"])
        self.assertEqual(probe["loras"], [])
        self.assertIn("没有检测到 LoRA 节点", graph_probe.describe_sources(probe))


class TestDescribeAndCollect(unittest.TestCase):
    def test_describe_sources_lists_node_ids_and_names(self):
        prompt = chain_prompt(["nearest.safetensors", "farther.safetensors"])
        prompt["3"]["_meta"] = {"title": "我的 LoRA"}
        text = graph_probe.describe_sources(graph_probe.probe_prompt(prompt, "100"))
        self.assertTrue(text.startswith("[接入链路] 检测到 "))
        self.assertIn("#3 LoraLoader", text)
        self.assertIn("我的 LoRA", text)
        self.assertIn("nearest.safetensors", text)
        self.assertIn("#2 LoraLoader", text)
        self.assertIn("；", text)

    def test_describe_sources_failure_line(self):
        text = graph_probe.describe_sources(graph_probe.probe_prompt(None, "100"))
        self.assertIn("无法反查工作流", text)
        self.assertIn("手动填写", text)

    def test_describe_sources_truncates(self):
        names = [f"l{i}.safetensors" for i in range(10)]
        text = graph_probe.describe_sources(graph_probe.probe_prompt(chain_prompt(names), "100"), max_items=3)
        self.assertIn("其余 7 个省略", text)

    def test_collect_names_limit(self):
        prompt = chain_prompt(["nearest.safetensors", "farther.safetensors"])
        probe = graph_probe.probe_prompt(prompt, "100")
        self.assertEqual(graph_probe.collect_names(probe, limit=1), ["nearest.safetensors"])
        self.assertEqual(len(graph_probe.collect_names(probe)), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
