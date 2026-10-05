# -*- coding: utf-8 -*-
"""节点 / HTTP 接口 / ComfyUI 加载方式 的单元测试（v1.1：自动反查接入链路）。

这些测试**不需要 ComfyUI、torch、aiohttp**：通过 monkeypatch 把 ``get_lora_roots`` /
``list_lora_names`` 指向临时目录，再用手工构造的 **API 格式 prompt** 模拟工作流，
就能在裸 Python 里完整跑通「顺着 model 连线反查上游 LoRA」这条链路。

运行方式::

    python -m unittest discover -s tests -v
    python tests/test_nodes_api.py
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import importlib.util
import inspect
import io
import json
import os
import sys
import types
import unittest
import uuid
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from lora_trigger_reader import api as lora_api  # noqa: E402
from lora_trigger_reader import graph_probe  # noqa: E402
from lora_trigger_reader import loader as ld  # noqa: E402
from lora_trigger_reader import lora_scan as scan  # noqa: E402
from lora_trigger_reader import nodes as lora_nodes  # noqa: E402

TMP_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(TMP_ROOT, exist_ok=True)

LORA_A = "A.safetensors"
LORA_B = "B.safetensors"
LORA_C = "sub/C.safetensors"
LORA_WOLF = "silver_wolf.safetensors"
ALL_LORAS = [LORA_A, LORA_B, LORA_C, LORA_WOLF]

READER_ID = "100"

#: 四个节点共有的可选参数（自动节点多一个 extra_loras，加载器节点多 model / clip）
COMMON_OPTIONAL_KEYS = {
    "separator",
    "deduplicate",
    "strip_comments",
    "on_missing",
    "fallback_text",
    "extra_dirs",
    "refresh_cache",
}

AUTO_NODES = (lora_nodes.LoRATriggerReader, lora_nodes.LoRATriggerReaderMulti)

#: 需要 unique_id / prompt（hidden 输入）的节点
GRAPH_NODES = AUTO_NODES + (lora_nodes.LoRAMultiLoader,)


def _mkdtemp(prefix: str) -> str:
    """自建临时目录（原因见 test_lora_scan.py：不用 tempfile.mkdtemp）。"""
    path = os.path.join(TMP_ROOT, prefix + uuid.uuid4().hex[:10])
    os.makedirs(path)
    return path


def _write(path: str, text: str, encoding: str = "utf-8") -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding=encoding, newline="") as fh:
        fh.write(text)
    return path


def _loader_node(lora_name: str, model_to: str, cls: str = "LoraLoader", key: str = "lora_name"):
    """一个 LoRA 选择节点的 API 格式片段。"""
    return {
        "class_type": cls,
        "inputs": {
            key: lora_name,
            "strength_model": 1.0,
            "model": [model_to, 0],
            "clip": [model_to, 1],
        },
        "_meta": {"title": cls},
    }


def _chain_prompt(
    lora_names=(),
    reader_type: str = "LoRATriggerReader",
    extra_loras: str = "",
    reader_id: str = READER_ID,
):
    """构造 ``CheckpointLoaderSimple -> LoraLoader... -> reader`` 的 API 格式 prompt。

    ``lora_names`` 按「离 reader 由近到远」的顺序给出（排在前面的是最后加载的那个）。
    """
    prompt = {"1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "base.safetensors"}}}
    prev = "1"
    for index, name in enumerate(reversed(list(lora_names)), start=2):
        nid = str(index)
        prompt[nid] = _loader_node(name, prev)
        prev = nid
    prompt[reader_id] = {
        "class_type": reader_type,
        "inputs": {"model": [prev, 0], "extra_loras": extra_loras},
    }
    return prompt


def _loader_prompt(lora_list: str = "", chain=(), reader_id: str = READER_ID):
    """构造 ``CheckpointLoaderSimple -> LoraLoader... -> LoRAMultiLoader`` 的 prompt。

    多重加载器同时接 MODEL 与 CLIP（clip 直接来自 CheckpointLoaderSimple 的 1 号口）。
    """
    prompt = _chain_prompt(chain, reader_type="LoRAMultiLoader", reader_id=reader_id)
    prompt[reader_id]["inputs"] = {
        "model": prompt[reader_id]["inputs"]["model"],
        "clip": ["1", 1],
        "lora_list": lora_list,
    }
    return prompt


class _Fixture(unittest.TestCase):
    """搭一个假的 LoRA 目录，并把扫描函数指过去。"""

    def setUp(self) -> None:
        self.root = _mkdtemp("nodes_")
        # 假的 LoRA 模型文件（内容无所谓，只要存在即可）
        for name in ALL_LORAS:
            _write(os.path.join(self.root, *name.split("/")), "")
        # 触发词文本
        _write(os.path.join(self.root, "A.txt"), "tag_a\ntag_b\ntag_a\n")
        _write(
            os.path.join(self.root, "sub", "C.md"),
            "c1\nc2\n# 注释行\n// 注释行2\n\n",
        )
        _write(
            os.path.join(self.root, "silver_wolf提示词.txt"),
            "silver wolf (lv.999) (honkai: star rail), confident smile,\n",
        )
        # B.safetensors 故意没有对应文本

        for target, value in (
            ("lora_trigger_reader.lora_scan.get_lora_roots", lambda: [self.root]),
            ("lora_trigger_reader.lora_scan.list_lora_names", lambda: list(ALL_LORAS)),
        ):
            patcher = mock.patch(target, side_effect=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        scan.clear_index_cache()
        self.addCleanup(scan.clear_index_cache)

    # --- 小工具 -------------------------------------------------------------
    def run_auto(self, reader_type: str, chain=(), extra_loras: str = "", **kwargs):
        """用一条真实的 MODEL 链路跑自动节点。

        模拟 ComfyUI 的 ``get_input_data``：prompt 里本节点的 ``inputs`` 中，
        除连线输入外都会作为**关键字参数**传给节点函数。
        """
        prompt = _chain_prompt(chain, reader_type=reader_type, extra_loras=extra_loras)
        given = dict(prompt[READER_ID]["inputs"])
        given.pop("model", None)  # 连线是 [节点id, 槽位]，不是字面值
        call_kwargs = {"prompt": prompt, "unique_id": READER_ID}
        call_kwargs.update(given)
        call_kwargs.update(kwargs)
        node = lora_nodes.NODE_CLASS_MAPPINGS[reader_type]()
        return node.read(**call_kwargs)

    def single(self, chain=(), **kwargs):
        return self.run_auto("LoRATriggerReader", chain, **kwargs)

    def multi(self, chain=(), **kwargs):
        return self.run_auto("LoRATriggerReaderMulti", chain, **kwargs)

    def run_loader(self, lora_list: str = "", chain=(), model=None, clip=None, **kwargs):
        """跑多重 LoRA 加载器。

        模拟 ComfyUI：``lora_list`` 是 widget 值（作为关键字参数传进来），
        ``model`` / ``clip`` 是连线值（这里手工塞哨兵对象；``no_model``/``no_clip`` 表示不接）。
        """
        no_model = kwargs.pop("no_model", False)
        no_clip = kwargs.pop("no_clip", False)
        prompt = _loader_prompt(lora_list, chain)
        call_kwargs = {
            "lora_list": lora_list,
            "model": None if no_model else (object() if model is None else model),
            "clip": None if no_clip else (object() if clip is None else clip),
            "prompt": prompt,
            "unique_id": READER_ID,
        }
        call_kwargs.update(kwargs)
        return lora_nodes.LoRAMultiLoader().load(**call_kwargs)

    def run_slots(self, slots=(), lora_list: str = "", chain=(), model=None, clip=None, **kwargs):
        """按 v1.3 的「下拉框 + 独立强度」跑多重加载器。

        ``slots`` 是 ``(名字, MODEL 强度, CLIP 强度)`` 的列表（强度可省略），
        没写的行一律填「不使用」。其余参数与 :meth:`run_loader` 一致。
        """
        no_model = kwargs.pop("no_model", False)
        no_clip = kwargs.pop("no_clip", False)
        prompt = _loader_prompt(lora_list, chain)
        call_kwargs = {
            "lora_list": lora_list,
            "model": None if no_model else (object() if model is None else model),
            "clip": None if no_clip else (object() if clip is None else clip),
            "prompt": prompt,
            "unique_id": READER_ID,
        }
        for index in range(1, ld.SLOT_COUNT + 1):
            name_key, strength_key, clip_key = lora_nodes._slot_keys(index)
            call_kwargs[name_key] = ld.SLOT_NONE
            call_kwargs[strength_key] = ld.DEFAULT_STRENGTH
            call_kwargs[clip_key] = ld.DEFAULT_STRENGTH
        for row, item in enumerate(slots, start=1):
            name_key, strength_key, clip_key = lora_nodes._slot_keys(row)
            call_kwargs[name_key] = item[0]
            if len(item) > 1 and item[1] is not None:
                call_kwargs[strength_key] = item[1]
            if len(item) > 2 and item[2] is not None:
                call_kwargs[clip_key] = item[2]
        call_kwargs.update(kwargs)
        return lora_nodes.LoRAMultiLoader().load(**call_kwargs)


# ============================================================================
#  节点定义
# ============================================================================
class TestNodeDefinitions(unittest.TestCase):
    CLASSES = {
        "LoRAMultiLoader": lora_nodes.LoRAMultiLoader,
        "LoRATriggerReader": lora_nodes.LoRATriggerReader,
        "LoRATriggerReaderMulti": lora_nodes.LoRATriggerReaderMulti,
        "LoRATriggerReaderInfo": lora_nodes.LoRATriggerReaderInfo,
    }

    def test_mappings_complete(self):
        self.assertEqual(set(lora_nodes.NODE_CLASS_MAPPINGS), set(self.CLASSES))
        for key in lora_nodes.NODE_CLASS_MAPPINGS:
            self.assertIs(lora_nodes.NODE_CLASS_MAPPINGS[key], self.CLASSES[key])
            self.assertTrue(lora_nodes.NODE_DISPLAY_NAME_MAPPINGS.get(key))

    def test_auto_nodes_contract(self):
        """自动节点：required 只有 model，optional 第一项是 extra_loras。"""
        for cls in AUTO_NODES:
            with self.subTest(node=cls.__name__):
                types = cls.INPUT_TYPES()
                self.assertEqual(set(types["required"]), {"model"})
                self.assertEqual(types["required"]["model"][0], "MODEL")
                self.assertEqual(list(types["optional"])[0], "extra_loras")
                self.assertEqual(types["optional"]["extra_loras"][0], "STRING")
                self.assertTrue(types["optional"]["extra_loras"][1]["multiline"])
                self.assertEqual(types["optional"]["extra_loras"][1]["default"], "")
                self.assertEqual(set(types["optional"]) - {"extra_loras"}, COMMON_OPTIONAL_KEYS)
                # 所有可选参数都要有默认值，否则工作流会提示缺参数
                for key, spec in types["optional"].items():
                    self.assertIsInstance(spec, tuple, f"{cls.__name__}.{key}")
                    self.assertGreaterEqual(len(spec), 2, f"{cls.__name__}.{key} 缺少参数选项")
                    self.assertIn("default", spec[1], f"{cls.__name__}.{key} 没有默认值")

    def test_auto_nodes_return_the_model_untouched(self):
        for cls in AUTO_NODES:
            with self.subTest(node=cls.__name__):
                self.assertEqual(cls.FUNCTION, "read")
                self.assertTrue(callable(getattr(cls, "read")))
                self.assertTrue(cls.CATEGORY)
                self.assertFalse(cls.OUTPUT_NODE)
                self.assertEqual(cls.RETURN_TYPES, ("MODEL", "STRING", "STRING"))
                self.assertEqual(cls.RETURN_NAMES, ("model", "trigger_words", "report"))

    def test_hidden_inputs_are_declared(self):
        """必须能拿到本节点 id + 工作流；且不能声明老 ComfyUI 不认识的类型。"""
        for cls in AUTO_NODES:
            with self.subTest(node=cls.__name__):
                hidden = cls.INPUT_TYPES()["hidden"]
                self.assertEqual(hidden["unique_id"], "UNIQUE_ID")
                self.assertEqual(hidden["prompt"], "PROMPT")
                # DYNPROMPT 在旧版本里不会被填进 input_data_all，会让 read() 直接 TypeError
                self.assertNotIn("DYNPROMPT", hidden.values())

    def test_read_signature_matches_input_types(self):
        for name, cls in self.CLASSES.items():
            types = cls.INPUT_TYPES()
            func = getattr(cls, cls.FUNCTION)
            params = inspect.signature(func).parameters
            for key in list(types.get("required", {})) + list(types.get("optional", {})):
                self.assertIn(key, params, f"{name}.{cls.FUNCTION}() 缺少参数 {key}")
        for cls in GRAPH_NODES:
            params = inspect.signature(getattr(cls, cls.FUNCTION)).parameters
            self.assertIn("unique_id", params)
            self.assertIn("prompt", params)

    def test_multi_loader_contract(self):
        """多重 LoRA 加载器（v1.3）：4 行下拉框选 LoRA + 每行独立的 MODEL / CLIP 强度。"""
        cls = lora_nodes.LoRAMultiLoader
        types = cls.INPUT_TYPES()

        # required = SLOT_COUNT 行 × (下拉框, MODEL 强度, CLIP 强度)
        expected_required: list = []
        for index in range(1, ld.SLOT_COUNT + 1):
            expected_required += [f"lora_{index}", f"strength_{index}", f"clip_strength_{index}"]
        self.assertEqual(list(types["required"]), expected_required)

        for index in range(1, ld.SLOT_COUNT + 1):
            name_spec = types["required"][f"lora_{index}"]
            self.assertIsInstance(name_spec[0], list, "下拉框选项必须是 list")
            self.assertEqual(name_spec[0][0], ld.SLOT_NONE, "下拉第一项必须是「不使用」")
            self.assertEqual(name_spec[1]["default"], ld.SLOT_NONE)
            self.assertIn("tooltip", name_spec[1])
            for key, tip in (
                (f"strength_{index}", lora_nodes._TIP_SLOT_MODEL),
                (f"clip_strength_{index}", lora_nodes._TIP_SLOT_CLIP),
            ):
                with self.subTest(key=key):
                    spec = types["required"][key]
                    self.assertEqual(spec[0], "FLOAT")
                    self.assertEqual(spec[1]["default"], ld.DEFAULT_STRENGTH)
                    self.assertEqual(spec[1]["min"], ld.MIN_STRENGTH)
                    self.assertEqual(spec[1]["max"], ld.MAX_STRENGTH)
                    # 用户 m01697：点小箭头每次 ±0.1，也可以直接输入数字
                    self.assertEqual(spec[1]["step"], 0.1)
                    self.assertEqual(spec[1]["tooltip"], tip)

        # MODEL / CLIP 都是**可选**输入（只接一个、或都不接也能跑）
        self.assertEqual(list(types["optional"])[:3], ["model", "clip", "lora_list"])
        self.assertEqual(types["optional"]["model"][0], "MODEL")
        self.assertEqual(types["optional"]["clip"][0], "CLIP")
        # lora_list 降级为「(高级) 批量文本」，仍然保留
        text_spec = types["optional"]["lora_list"]
        self.assertEqual(text_spec[0], "STRING")
        self.assertTrue(text_spec[1]["multiline"])
        self.assertEqual(text_spec[1]["default"], "")
        self.assertEqual(
            set(types["optional"]) - {"model", "clip"}, COMMON_OPTIONAL_KEYS | {"lora_list"}
        )
        self.assertNotIn("extra_loras", types["optional"])
        for key, item in types["optional"].items():
            self.assertIsInstance(item, tuple, f"LoRAMultiLoader.{key}")
            if key not in ("model", "clip"):  # 连线型输入由上游提供，不需要默认值
                self.assertIn("default", item[1], f"LoRAMultiLoader.{key} 没有默认值")

        self.assertEqual(cls.RETURN_TYPES, ("MODEL", "CLIP", "STRING", "STRING"))
        self.assertEqual(cls.RETURN_NAMES, ("model", "clip", "trigger_words", "report"))
        self.assertEqual(cls.FUNCTION, "load")
        self.assertTrue(callable(getattr(cls, "load")))
        self.assertTrue(cls.CATEGORY)
        self.assertFalse(cls.OUTPUT_NODE)

        hidden = types["hidden"]
        self.assertEqual(hidden["unique_id"], "UNIQUE_ID")
        self.assertEqual(hidden["prompt"], "PROMPT")
        self.assertNotIn("DYNPROMPT", hidden.values())

    def test_loader_slot_option_source(self):
        """下拉选项 = [不使用] + ComfyUI 的 LoRA 列表；没有 LoRA 时也不能是空列表。"""
        with mock.patch.object(scan, "list_lora_names", return_value=[LORA_A, LORA_C]):
            options = lora_nodes._lora_options()
        self.assertEqual(options, [ld.SLOT_NONE, LORA_A, LORA_C])
        with mock.patch.object(scan, "list_lora_names", return_value=[]):
            options = lora_nodes._lora_options()
        self.assertEqual(options[0], ld.SLOT_NONE)
        self.assertTrue(len(options) >= 2, "下拉列表为空会让 ComfyUI 报错")

    def test_slot_columns_reads_kwargs(self):
        """IS_CHANGED 通过 _slot_columns(**kwargs) 还原下拉框的值。"""
        values = {
            "lora_1": LORA_A,
            "strength_1": 0.8,
            "clip_strength_1": 0.5,
            "lora_2": ld.SLOT_NONE,
            "strength_3": 1.25,
        }
        names, model_strengths, clip_strengths = lora_nodes._slot_columns(values)
        self.assertEqual(len(names), ld.SLOT_COUNT)
        self.assertEqual(names[0], LORA_A)
        self.assertEqual(names[1], ld.SLOT_NONE)
        self.assertEqual(model_strengths[0], 0.8)
        self.assertEqual(clip_strengths[0], 0.5)
        self.assertEqual(model_strengths[2], 1.25)
        self.assertEqual(clip_strengths[1], ld.DEFAULT_STRENGTH, "缺省时回落默认强度")

    def test_all_nodes_have_bilingual_docs_and_tooltips(self):
        """四个节点都必须有中英文说明 + 端口 tooltip + 搜索别名（老版本忽略这些属性）。"""
        for name, cls in self.CLASSES.items():
            with self.subTest(node=name):
                description = getattr(cls, "DESCRIPTION", "")
                self.assertIn("【English】", description, f"{name} 缺少英文说明")
                self.assertNotEqual(description.strip(), "")
                self.assertTrue(getattr(cls, "SEARCH_ALIASES", None), f"{name} 缺少 SEARCH_ALIASES")
                self.assertTrue(getattr(cls, "OUTPUT_TOOLTIPS", None), f"{name} 缺少 OUTPUT_TOOLTIPS")
                types = cls.INPUT_TYPES()
                for group in ("required", "optional"):
                    for key, item in (types.get(group) or {}).items():
                        self.assertIn("tooltip", item[1], f"{name}.{key} 缺少 tooltip")
        self.assertIn("Multi LoRA loader", lora_nodes.LoRAMultiLoader.DESCRIPTION)

    def test_multi_loader_helps_and_aliases(self):
        self.assertIn("a.safetensors", lora_nodes._TIP_LORA_LIST)
        self.assertIn("0.8", lora_nodes._TIP_LORA_LIST)
        self.assertIn("高级", lora_nodes._TIP_LORA_LIST)
        self.assertIn("下拉", lora_nodes._TIP_SLOT)
        for tip in (lora_nodes._TIP_SLOT_MODEL, lora_nodes._TIP_SLOT_CLIP):
            self.assertIn("0.1", tip)
            self.assertIn("输入数字", tip)
            self.assertIn("【English】", tip)
        self.assertIn("MODEL", lora_nodes._TIP_LOADER_MODEL)
        self.assertIn("CLIP", lora_nodes._TIP_LOADER_CLIP)
        self.assertEqual(lora_nodes.HELP_ROUTE, lora_api.ROUTE_PREFIX + "/help")

    def test_only_nearest_flags(self):
        self.assertTrue(lora_nodes.LoRATriggerReader.ONLY_NEAREST)
        self.assertFalse(lora_nodes.LoRATriggerReaderMulti.ONLY_NEAREST)

    def test_info_node_contract(self):
        cls = lora_nodes.LoRATriggerReaderInfo
        types = cls.INPUT_TYPES()
        self.assertEqual(set(types["required"]), {"lora_name"})
        spec = types["required"]["lora_name"]
        self.assertIsInstance(spec[0], list)
        self.assertTrue(spec[0], "下拉列表不能为空，否则节点在脱离 ComfyUI 时会报错")
        self.assertEqual(set(types["optional"]), COMMON_OPTIONAL_KEYS)
        self.assertNotIn("extra_loras", types["optional"])
        self.assertNotIn("hidden", types)
        self.assertEqual(cls.RETURN_TYPES, ("STRING", "STRING"))
        self.assertEqual(cls.RETURN_NAMES, ("trigger_words", "report"))

    def test_info_combo_follows_scanner(self):
        with mock.patch.object(scan, "list_lora_names", return_value=[LORA_A, LORA_C]):
            spec = lora_nodes.LoRATriggerReaderInfo.INPUT_TYPES()["required"]["lora_name"]
        self.assertEqual(spec[0], [LORA_A, LORA_C])

    def test_is_changed_is_a_string_and_safe(self):
        with mock.patch.object(scan, "get_lora_roots", return_value=[]):
            scan.clear_index_cache()
            self.assertEqual(lora_nodes.LoRATriggerReader.IS_CHANGED(), "empty")
            self.assertEqual(lora_nodes.LoRATriggerReaderMulti.IS_CHANGED(), "empty")
            self.assertIsInstance(lora_nodes.LoRATriggerReaderInfo.IS_CHANGED("x.safetensors"), str)
            self.assertIsInstance(lora_nodes.LoRAMultiLoader.IS_CHANGED("x.safetensors"), str)
        # 出错也不能抛异常（否则工作流会直接失败）
        with mock.patch.object(scan, "get_lora_roots", side_effect=RuntimeError("boom")):
            scan.clear_index_cache()
            self.assertEqual(lora_nodes.LoRATriggerReader.IS_CHANGED(), "fallback")
            self.assertIsInstance(lora_nodes.LoRATriggerReaderInfo.IS_CHANGED("x.safetensors"), str)
        with mock.patch.object(ld, "parse_specs", side_effect=RuntimeError("boom")):
            self.assertEqual(lora_nodes.LoRAMultiLoader.IS_CHANGED("x.safetensors"), "fallback")


# ============================================================================
#  多重 LoRA 加载器执行
# ============================================================================
class TestMultiLoaderExecution(_Fixture):
    """用假的"读文件 / 应用"函数跑加载器，完全不需要 torch。"""

    def setUp(self):
        super().setUp()
        self.read_files = []
        self.apply_calls = []
        self.clear_cache_patcher = mock.patch.object(ld, "clear_lora_cache", side_effect=ld.clear_lora_cache)
        self.clear_cache_patcher.start()
        self.addCleanup(self.clear_cache_patcher.stop)
        ld.clear_lora_cache()

        def fake_load(path):
            self.read_files.append(path)
            return {"file": path}, {"meta": path}

        def fake_apply(model, clip, lora, strength_model, strength_clip, metadata=None):
            self.apply_calls.append((lora["file"], strength_model, strength_clip, metadata))
            return "MODEL_OUT", "CLIP_OUT"

        for target, replacement in (
            ("_default_load_tensor", fake_load),
            ("_default_apply", fake_apply),
        ):
            patcher = mock.patch.object(ld, target, side_effect=replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_loads_every_lora_in_the_text_box(self):
        model = object()
        clip = object()
        out_model, out_clip, text, report = self.run_loader("A.safetensors: 0.8\nsub/C.safetensors",
                                                           model=model, clip=clip)
        # 加载器会把 LoRA 叠加上去，所以返回值是"应用之后"的模型（这里由假 _default_apply 决定）
        self.assertEqual((out_model, out_clip), ("MODEL_OUT", "CLIP_OUT"))
        self.assertEqual(text, "tag_a, tag_b, c1, c2")
        lines = report.split("\n")
        self.assertEqual(lines[0], f"LoRATriggerReader v{scan.VERSION}")
        self.assertTrue(lines[1].startswith("[多重加载器] 已加载 2 个 LoRA"), lines[1])
        self.assertIn("A.safetensors(0.8)", lines[1])
        self.assertIn("C.safetensors(1)", lines[1])
        self.assertIn("共 2 个 LoRA", report)

    def test_strengths_and_paths_are_forwarded(self):
        self.run_loader("A.safetensors: 0.8, 0.4")
        self.assertEqual(
            [os.path.basename(c[0]) for c in self.apply_calls],
            ["A.safetensors"],
        )
        self.assertEqual(self.apply_calls[0][1:3], (0.8, 0.4))

    def test_model_and_clip_may_be_missing(self):
        _m, _c, text, report = self.run_loader("A.safetensors", no_model=True, no_clip=True)
        self.assertEqual(text, "tag_a, tag_b")
        self.assertIn("MODEL / CLIP 都没接", report)
        self.assertEqual(self.apply_calls, [])
        self.assertEqual(self.read_files, [], "两个口都没接时不应该真的读 LoRA 文件")

    def test_only_clip_connected_still_loads(self):
        _m, _c, _text, report = self.run_loader("A.safetensors", no_model=True)
        self.assertEqual(len(self.apply_calls), 1)
        self.assertIn("已加载 1 个 LoRA", report)

    def test_empty_list_falls_back_to_upstream_chain(self):
        # 链路上的 LoRA 按「模型流向」加载：远 -> 近
        _m, _c, text, report = self.run_loader("", chain=[LORA_C, LORA_A, LORA_WOLF])
        self.assertIn("已自动使用 model 接入链路上的 LoRA", report)
        self.assertIn("按模型流向依次加载，共 3 个", report)
        self.assertEqual(
            [os.path.basename(c[0]) for c in self.apply_calls],
            ["silver_wolf.safetensors", "A.safetensors", "C.safetensors"],
        )
        self.assertIn("tag_a", text)
        self.assertIn("silver wolf", text)

    def test_empty_list_and_empty_chain_outputs_nothing(self):
        _m, _c, text, report = self.run_loader("")
        self.assertEqual(text, "")
        self.assertIn("没有读到任何 LoRA", report)
        self.assertIn("lora_list", report)

    def test_manual_list_wins_over_the_chain(self):
        _m, _c, text, report = self.run_loader("A.safetensors", chain=[LORA_WOLF])
        self.assertEqual(text, "tag_a, tag_b")
        self.assertEqual([os.path.basename(c[0]) for c in self.apply_calls], ["A.safetensors"])
        self.assertNotIn("[多重加载器] lora_list 是空的", report)

    def test_missing_file_is_reported(self):
        _m, _c, _text, report = self.run_loader("ghost.safetensors")
        self.assertIn("加载失败：ghost.safetensors", report)
        self.assertIn("找不到该文件", report)

    def test_name_completion_with_scanner_list(self):
        self.run_loader("C")
        self.assertEqual(len(self.apply_calls), 1)
        self.assertTrue(
            self.apply_calls[0][0].replace("\\", "/").endswith("sub/C.safetensors"),
            self.apply_calls[0][0],
        )

    def test_comments_and_blank_lines(self):
        _m, _c, text, report = self.run_loader("# 注释\n\nA.safetensors  # 行尾\n// 注释")
        self.assertEqual(text, "tag_a, tag_b")
        self.assertIn("已加载 1 个 LoRA", report)

    def test_cache_hit_is_reported(self):
        # 直接用真实的 load_tensor_cached（底层换成假的读文件函数），验证缓存行
        with mock.patch.object(ld, "_default_load_tensor", lambda path: ({"file": path}, {"m": 1})):
            self.run_loader("A.safetensors")
            _m, _c, _text, report = self.run_loader("A.safetensors")
        self.assertIn("其中 1 个直接用了内存缓存", report)

    def test_weak_name_uses_on_missing_strategy(self):
        _m, _c, text, _report = self.run_loader("A.safetensors\nghost.safetensors", on_missing="lora_name")
        self.assertEqual(text, "tag_a, tag_b, ghost")

    def test_refresh_cache_triggers_rescan(self):
        self.run_loader("A.safetensors", refresh_cache=True)
        self.assertEqual(len(self.read_files), 1)

    def test_missing_prompt_is_safe(self):
        node = lora_nodes.LoRAMultiLoader()
        _m, _c, text, report = node.load(lora_list="A.safetensors", model=object(), clip=object(),
                                        prompt=None, unique_id=None)
        self.assertEqual(text, "tag_a, tag_b")
        self.assertIn("[多重加载器]", report)

    def test_warnings_are_shown_in_the_report(self):
        _m, _c, _text, report = self.run_loader("A.safetensors: 500")
        self.assertIn("注意", report)
        self.assertIn("超出", report)

    # --- v1.3：下拉框选 LoRA + 每行独立强度 -----------------------------------
    def test_slots_load_the_selected_loras(self):
        """用户 m01678：下拉框选 LoRA，MODEL / CLIP 强度各自独立设置。"""
        _m, _c, text, report = self.run_slots([(LORA_A, 0.8, 0.5), (LORA_C, 0.6, 0.2)])
        self.assertEqual(text, "tag_a, tag_b, c1, c2")
        self.assertEqual([os.path.basename(c[0]) for c in self.apply_calls],
                         ["A.safetensors", "C.safetensors"])
        self.assertEqual(self.apply_calls[0][1:3], (0.8, 0.5), "MODEL / CLIP 强度必须分开传")
        self.assertEqual(self.apply_calls[1][1:3], (0.6, 0.2))
        self.assertTrue(report.split("\n")[1].startswith("[多重加载器] 已加载 2 个 LoRA"), report)

    def test_slot_clip_strength_is_a_separate_box(self):
        """CLIP 强度是独立控件（同 ComfyUI 自带的 LoraLoader），没动过就是默认 1.0。"""
        _m, _c, _text, _report = self.run_slots([(LORA_A, 0.6, None)])
        self.assertEqual(self.apply_calls[-1][1:3], (0.6, 1.0))
        _m, _c, _text, _report = self.run_slots([(LORA_A, 0.6, 0.4)])
        self.assertEqual(self.apply_calls[-1][1:3], (0.6, 0.4))

    def test_slot_none_rows_are_skipped(self):
        """选「不使用」的行不加载，也不报错。"""
        _m, _c, text, report = self.run_slots([(ld.SLOT_NONE, 1.0, 1.0), (LORA_A, 1.0, 1.0)])
        self.assertEqual(text, "tag_a, tag_b")
        self.assertEqual(len(self.apply_calls), 1)
        self.assertIn("已加载 1 个 LoRA", report)

    def test_slot_order_follows_the_row_number(self):
        _m, _c, _text, _report = self.run_slots([(LORA_C, 1.0, 1.0), (LORA_A, 1.0, 1.0)])
        self.assertEqual([os.path.basename(c[0]) for c in self.apply_calls],
                         ["C.safetensors", "A.safetensors"], "按行号 1→4 的顺序加载")

    def test_slots_and_text_box_are_merged(self):
        """下拉框在前、文本框里的补充在后。"""
        _m, _c, text, report = self.run_slots([(LORA_C, 1.0, 1.0)], lora_list="A.safetensors: 0.8")
        self.assertEqual(text, "c1, c2, tag_a, tag_b")
        self.assertEqual([os.path.basename(c[0]) for c in self.apply_calls],
                         ["C.safetensors", "A.safetensors"])
        self.assertEqual(self.apply_calls[1][1:3], (0.8, 0.8))
        self.assertIn("已加载 2 个 LoRA", report)

    def test_empty_slots_still_fall_back_to_the_chain(self):
        _m, _c, _text, report = self.run_slots([], chain=[LORA_C, LORA_A])
        self.assertIn("下拉框和文本框都没写 LoRA", report)
        self.assertIn("共 2 个", report)
        self.assertEqual([os.path.basename(c[0]) for c in self.apply_calls],
                         ["A.safetensors", "C.safetensors"])

    def test_slot_strength_out_of_range_is_clamped(self):
        _m, _c, _text, report = self.run_slots([(LORA_A, 500, -500)])
        self.assertEqual(self.apply_calls[0][1:3], (100.0, -100.0))
        self.assertIn("注意", report)
        self.assertIn("超出", report)

    def test_slots_only_trigger_words_when_model_and_clip_are_missing(self):
        _m, _c, text, report = self.run_slots([(LORA_A, 1.0, 1.0)], no_model=True, no_clip=True)
        self.assertEqual(text, "tag_a, tag_b")
        self.assertIn("MODEL / CLIP 都没接", report)
        self.assertEqual(self.read_files, [])


# ============================================================================
#  自动节点执行（单 LoRA）
# ============================================================================
class TestAutoSingleExecution(_Fixture):
    def test_nearest_lora_only(self):
        sentinel = object()
        model, text, report = self.single([LORA_C, LORA_A], model=sentinel)
        self.assertIs(model, sentinel, "MODEL 必须原样透传，不能改成别的东西")
        self.assertEqual(text, "c1, c2", "单 LoRA 节点只读最近的那个")
        self.assertNotIn("tag_a", text)

    def test_report_has_source_line(self):
        _model, _text, report = self.single([LORA_C, LORA_A])
        lines = report.split("\n")
        self.assertTrue(lines[0].startswith(f"LoRATriggerReader v{scan.VERSION}"))
        self.assertTrue(lines[1].startswith("[接入链路] 检测到 "), lines)
        self.assertIn("#3", lines[1])  # 离 reader 最近的那个 LoRA 节点（id=3）
        self.assertIn("sub/C.safetensors", lines[1])
        self.assertIn("有触发词 1", report)
        self.assertIn(LORA_C, report)

    def test_no_chain_and_no_manual(self):
        model, text, report = self.single([], model="M")
        self.assertEqual(model, "M")
        self.assertEqual(text, "")
        self.assertIn("没有读到任何 LoRA", report)
        self.assertIn("extra_loras", report)
        self.assertIn("接入链路上最近的一个 LoRA", report)

    def test_manual_only_when_chain_is_empty(self):
        _model, text, _report = self.single([], extra_loras=LORA_A)
        self.assertEqual(text, "tag_a, tag_b")

    def test_manual_supplements_the_chain(self):
        """最近的那个 LoRA 之外，手动补充的也会一起读。"""
        _model, text, _report = self.single([LORA_C], extra_loras=LORA_A)
        self.assertEqual(text, "c1, c2, tag_a, tag_b")

    def test_manual_with_strength_suffix_is_stripped(self):
        """回归（用户 m01678）：`名字: 0.8` 的强度尾巴必须剥离，否则短名字匹配不到触发词。"""
        for suffix in (": 0.8", "@ 0.8", ", 0.8", " 0.8", ": 0.8, 0.4", ":0.8"):
            with self.subTest(suffix=suffix):
                _model, text, report = self.single([], extra_loras=LORA_A + suffix)
                self.assertEqual(text, "tag_a, tag_b", f"带 {suffix} 时应仍然读到触发词")
                self.assertIn("有触发词 1", report)

    def test_manual_with_strength_suffix_matches_plain_name(self):
        """带强度和不带强度必须得到完全一样的结果（这就是那个 bug 的判据）。"""
        plain = self.single([], extra_loras=LORA_A)
        weighted = self.single([], extra_loras=f"{LORA_A}: 0.8")
        self.assertEqual(plain[1:], weighted[1:])

    def test_manual_duplicate_of_detected_is_deduped(self):
        _model, text, report = self.single([LORA_A], extra_loras=LORA_A)
        self.assertEqual(text, "tag_a, tag_b")
        self.assertIn("共 1 个 LoRA", report)

    def test_separator_and_dedup(self):
        self.assertEqual(self.single([LORA_A], deduplicate=False)[1], "tag_a, tag_b, tag_a")
        self.assertEqual(self.single([LORA_A], separator="\\n")[1], "tag_a\ntag_b")
        self.assertEqual(self.single([LORA_A], separator=" | ")[1], "tag_a | tag_b")

    def test_strip_comments_toggle(self):
        self.assertEqual(self.single([LORA_C])[1], "c1, c2")
        self.assertEqual(
            self.single([LORA_C], strip_comments=False)[1],
            "c1, c2, # 注释行, // 注释行2",
        )

    def test_suffix_word_matching(self):
        """本地最常见的约定：``xxx提示词.txt`` 对应 ``xxx.safetensors``。"""
        _model, text, report = self.single([LORA_WOLF])
        self.assertEqual(text, "silver wolf (lv.999) (honkai: star rail), confident smile")
        self.assertIn("silver_wolf提示词.txt", report)

    def test_missing_lora_file(self):
        _model, text, report = self.single(["not_here.safetensors"])
        self.assertEqual(text, "")
        self.assertIn("找不到该 LoRA 文件", report)

    def test_on_missing_strategies(self):
        self.assertEqual(self.single([LORA_B])[1], "")
        self.assertEqual(self.single([LORA_B], on_missing="lora_name")[1], "B")
        self.assertEqual(
            self.single([LORA_B], on_missing="custom", fallback_text="my trigger")[1],
            "my trigger",
        )

    def test_extra_dirs_with_manual_loras(self):
        other = _mkdtemp("extra_")
        _write(os.path.join(other, "Z.safetensors"), "")
        _write(os.path.join(other, "Z.txt"), "z_tag\n")
        _model, text, _report = self.single(
            [], extra_loras="Z.safetensors", extra_dirs=other, refresh_cache=True
        )
        self.assertEqual(text, "z_tag")

    def test_missing_prompt_is_safe(self):
        """脱离 ComfyUI（拿不到 prompt）时不能抛异常，只能退化成"没有 LoRA"。"""
        node = lora_nodes.LoRATriggerReader()
        model, text, report = node.read(model="M", prompt=None, unique_id=None)
        self.assertEqual(model, "M")
        self.assertEqual(text, "")
        self.assertIn("无法反查工作流", report)
        self.assertIn("没有读到任何 LoRA", report)

    def test_prompt_with_unknown_node_id(self):
        node = lora_nodes.LoRATriggerReader()
        _model, text, report = node.read(prompt={"1": {"class_type": "X", "inputs": {}}}, unique_id="99")
        self.assertEqual(text, "")
        self.assertIn("找不到节点", report)


# ============================================================================
#  自动节点执行（多 LoRA）
# ============================================================================
class TestAutoMultiExecution(_Fixture):
    def test_merges_every_lora_on_the_chain(self):
        _model, text, report = self.multi([LORA_C, LORA_A])
        self.assertEqual(text, "c1, c2, tag_a, tag_b")
        self.assertIn("共 2 个 LoRA", report)
        self.assertIn("有触发词 2", report)

    def test_order_is_nearest_first(self):
        _model, text, _report = self.multi([LORA_A, LORA_C])
        self.assertEqual(text, "tag_a, tag_b, c1, c2")

    def test_comma_separated_manual_loras(self):
        _model, text, _report = self.multi([], extra_loras=f"{LORA_A}, {LORA_C}")
        self.assertEqual(text, "tag_a, tag_b, c1, c2")

    def test_chain_plus_manual(self):
        _model, text, report = self.multi([LORA_C], extra_loras=LORA_A)
        self.assertEqual(text, "c1, c2, tag_a, tag_b")
        self.assertIn("共 2 个 LoRA", report)

    def test_empty_input(self):
        model, text, report = self.multi([], extra_loras="   \n# 只有注释\n", model="M")
        self.assertEqual(model, "M")
        self.assertEqual(text, "")
        self.assertIn("没有读到任何 LoRA", report)
        self.assertIn("接入链路上的全部 LoRA", report)

    def test_fallback_lora_name_mode(self):
        _model, text, report = self.multi([LORA_A, LORA_B], on_missing="lora_name")
        self.assertEqual(text, "tag_a, tag_b, B")
        self.assertIn("兜底 1", report)

    def test_fallback_custom_mode(self):
        _model, text, report = self.multi([LORA_B], on_missing="custom", fallback_text="x, y")
        self.assertEqual(text, "x, y")
        self.assertIn("已使用兜底文本", report)

    def test_separator_newline_uses_real_newline(self):
        _model, text, _report = self.multi([LORA_C, LORA_A], separator="\\n")
        self.assertEqual(text, "c1\nc2\ntag_a\ntag_b")

    def test_missing_loras_are_reported(self):
        _model, text, report = self.multi(["ghost_a.safetensors", "ghost_b.safetensors"])
        self.assertEqual(text, "")
        self.assertIn("找不到该 LoRA 文件", report)

    def test_short_name_is_completed(self):
        """只写文件名（不带目录）也应能匹配到 sub/C.safetensors。"""
        _model, text, _report = self.multi([], extra_loras="C.safetensors")
        self.assertEqual(text, "c1, c2")

    def test_out_of_chain_lora_is_ignored(self):
        prompt = _chain_prompt([LORA_C], reader_type="LoRATriggerReaderMulti")
        prompt["7"] = _loader_node(LORA_A, "1")  # 没连到 reader
        node = lora_nodes.LoRATriggerReaderMulti()
        _model, text, report = node.read(prompt=prompt, unique_id=READER_ID)
        self.assertEqual(text, "c1, c2")
        self.assertNotIn("tag_a", text)
        self.assertIn("sub/C.safetensors", report)


# ============================================================================
#  查询节点执行（手动）
# ============================================================================
class TestInfoNodeExecution(_Fixture):
    def test_returns_two_values(self):
        out = lora_nodes.LoRATriggerReaderInfo().read(lora_name=LORA_A)
        self.assertIsInstance(out, tuple)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0], "tag_a, tag_b")

    def test_empty_selection(self):
        text, report = lora_nodes.LoRATriggerReaderInfo().read(lora_name="")
        self.assertEqual(text, "")
        self.assertIn("没有选择 LoRA", report)

    def test_missing_lora(self):
        text, report = lora_nodes.LoRATriggerReaderInfo().read(lora_name="not_here.safetensors")
        self.assertEqual(text, "")
        self.assertIn("找不到该 LoRA 文件", report)

    def test_on_missing(self):
        text, _report = lora_nodes.LoRATriggerReaderInfo().read(
            lora_name=LORA_B, on_missing="custom", fallback_text="fb"
        )
        self.assertEqual(text, "fb")


# ============================================================================
#  HTTP 接口载荷
# ============================================================================
class TestApiPayloads(_Fixture):
    def test_list_payload(self):
        payload = lora_api.build_list_payload()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["roots"], [self.root])
        self.assertEqual(payload["count"], len(ALL_LORAS))
        self.assertEqual(payload["with_trigger"], 3)
        self.assertEqual(payload["empty"], 0)

        by_name = {item["name"]: item for item in payload["items"]}
        self.assertEqual(by_name[LORA_A]["status"], "ok")
        self.assertEqual(by_name[LORA_A]["base"], "A.safetensors")
        self.assertEqual(by_name[LORA_A]["trigger_rel"], "A.txt")
        self.assertEqual(by_name[LORA_A]["preview"], "tag_a, tag_b")
        self.assertEqual(by_name[LORA_A]["encoding"], "utf-8")
        self.assertEqual(by_name[LORA_B]["status"], "no_trigger")
        self.assertEqual(by_name[LORA_B]["preview"], "")
        self.assertEqual(by_name[LORA_C]["trigger_rel"], "sub/C.md")

    def test_list_payload_without_preview(self):
        payload = lora_api.build_list_payload(with_preview=False)
        self.assertTrue(all(item["preview"] == "" for item in payload["items"]))

    def test_list_payload_refresh(self):
        first = lora_api.build_list_payload()
        second = lora_api.build_list_payload(refresh=True)
        self.assertEqual(first["count"], second["count"])
        self.assertEqual(first["with_trigger"], second["with_trigger"])

    def test_text_payload_ok(self):
        payload = lora_api.build_text_payload(LORA_A)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["text"], "tag_a, tag_b")
        self.assertEqual(payload["raw"], "tag_a\ntag_b\ntag_a\n")
        self.assertFalse(payload["truncated"])
        self.assertTrue(payload["file"].endswith("A.txt"))

    def test_text_payload_requires_name(self):
        payload = lora_api.build_text_payload("   ")
        self.assertFalse(payload["ok"])
        self.assertIn("lora_name", payload["error"])

    def test_text_payload_missing_lora(self):
        payload = lora_api.build_text_payload("ghost.safetensors")
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["status"], "no_lora")

    def test_preview_is_truncated_and_json_safe(self):
        long_text = "x" * (lora_api.PREVIEW_LIMIT * 3)
        _write(os.path.join(self.root, "A.txt"), long_text)
        scan.clear_index_cache()
        payload = lora_api.build_list_payload(refresh=True)
        preview = {i["name"]: i["preview"] for i in payload["items"]}[LORA_A]
        self.assertLessEqual(len(preview), lora_api.PREVIEW_LIMIT + 1)
        self.assertTrue(preview.endswith("…"))
        json.dumps(payload)  # 必须能序列化成 JSON

    def test_is_true(self):
        for value in ("1", "true", "TRUE", "Yes", "on", " on "):
            self.assertTrue(lora_api._is_true(value), value)
        for value in ("", "0", "false", "no", "off", None):
            self.assertFalse(lora_api._is_true(value), value)

    def test_register_routes_never_raises(self):
        # 裸 Python 环境里没有 aiohttp / server，应当安静地返回 False 而不是抛异常
        result = lora_api.register_routes()
        self.assertIsInstance(result, bool)

    def test_route_prefix(self):
        self.assertTrue(lora_api.ROUTE_PREFIX.startswith("/"))
        self.assertNotIn("..", lora_api.ROUTE_PREFIX)

    def test_help_payload_for_every_node(self):
        """每个节点都要有中英文说明（前端「❓ 使用说明」面板 / ``/help`` 接口用它）。"""
        expected = {"LoRAMultiLoader", "LoRATriggerReader", "LoRATriggerReaderMulti", "LoRATriggerReaderInfo"}
        for key in sorted(expected):
            payload = lora_api.build_help_payload(key)
            with self.subTest(node=key):
                self.assertTrue(payload["ok"], payload.get("error"))
                self.assertTrue(payload["exists"])
                self.assertEqual(payload["node"], key)
                self.assertTrue(payload["zh"].strip())
                self.assertTrue(payload["en"].strip())
                self.assertNotEqual(payload["zh"], payload["en"], "中英文说明不应该一模一样")
                self.assertTrue(payload["title"]["zh"])
                self.assertTrue(payload["title"]["en"])

        keys = {item["key"] for item in payload["nodes"]}
        self.assertTrue(keys >= {"common"} | expected)

    def test_help_payload_defaults_to_overview(self):
        payload = lora_api.build_help_payload()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["node"], "help")
        self.assertTrue(payload["zh"].strip())
        self.assertTrue(payload["en"].strip())

    def test_help_payload_unknown_node_falls_back(self):
        payload = lora_api.build_help_payload("NoSuchNode")
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["exists"])
        self.assertEqual(payload["requested"], "NoSuchNode")
        self.assertTrue(payload["zh"].strip())
        self.assertTrue(payload["nodes"])

    def test_help_payload_never_raises(self):
        with mock.patch.object(lora_api.help_docs, "docs_payload", side_effect=RuntimeError("boom")):
            payload = lora_api.build_help_payload("LoRATriggerReader")
        self.assertFalse(payload["ok"])
        self.assertIn("boom", payload["error"])
        self.assertEqual(payload["nodes"], [])


class TestRouteRegistration(_Fixture):
    """用假的 aiohttp / server 模块验证路由真的注册上了、并且永远不会 500。"""

    def _patch_modules(self):
        registered = []

        class FakeRoutes:
            def get(self, path):
                def decorator(func):
                    registered.append((path, func))
                    return func

                return decorator

        class FakePromptServer:
            class instance:  # noqa: N801 - 模拟 ComfyUI 的类属性写法
                routes = FakeRoutes()

        fake_web = types.SimpleNamespace(
            json_response=lambda payload, headers=None: {"payload": payload, "headers": headers}
        )
        fake_aiohttp = types.ModuleType("aiohttp")
        fake_aiohttp.web = fake_web
        fake_server = types.ModuleType("server")
        fake_server.PromptServer = FakePromptServer

        patcher = mock.patch.dict(sys.modules, {"aiohttp": fake_aiohttp, "server": fake_server})
        patcher.start()
        self.addCleanup(patcher.stop)
        return registered

    def test_routes_registered_and_handlers_work(self):
        registered = self._patch_modules()
        self.assertTrue(lora_api.register_routes())
        paths = [p for p, _f in registered]
        self.assertIn(lora_api.ROUTE_PREFIX + "/list", paths)
        self.assertIn(lora_api.ROUTE_PREFIX + "/text", paths)
        self.assertIn(lora_api.ROUTE_PREFIX + "/help", paths)
        self.assertEqual(len(paths), len(set(paths)), "同一条路由不能注册两次")

        handlers = dict(registered)
        list_handler = handlers[lora_api.ROUTE_PREFIX + "/list"]
        text_handler = handlers[lora_api.ROUTE_PREFIX + "/text"]
        help_handler = handlers[lora_api.ROUTE_PREFIX + "/help"]

        req_list = types.SimpleNamespace(query={"refresh": "1", "preview": "0"})
        resp_list = asyncio.run(list_handler(req_list))
        self.assertTrue(resp_list["payload"]["ok"])
        self.assertEqual(resp_list["payload"]["count"], len(ALL_LORAS))
        self.assertEqual(resp_list["headers"]["Cache-Control"], "no-store")

        req_text = types.SimpleNamespace(query={"lora_name": LORA_A})
        resp_text = asyncio.run(text_handler(req_text))
        self.assertTrue(resp_text["payload"]["ok"])
        self.assertEqual(resp_text["payload"]["text"], "tag_a, tag_b")

        req_help = types.SimpleNamespace(query={"node": "LoRAMultiLoader"})
        resp_help = asyncio.run(help_handler(req_help))
        self.assertTrue(resp_help["payload"]["ok"])
        self.assertEqual(resp_help["payload"]["node"], "LoRAMultiLoader")
        self.assertTrue(resp_help["payload"]["zh"].strip())
        self.assertTrue(resp_help["payload"]["en"].strip())
        self.assertEqual(resp_help["headers"]["Cache-Control"], "no-store")

        # 不传 node 参数时要给总览
        resp_help_default = asyncio.run(help_handler(types.SimpleNamespace(query={})))
        self.assertEqual(resp_help_default["payload"]["node"], "help")

    def test_handlers_never_raise(self):
        registered = self._patch_modules()
        lora_api.register_routes()
        handlers = dict(registered)
        boom = mock.Mock(side_effect=RuntimeError("boom"))
        with mock.patch.object(lora_api, "build_list_payload", boom), mock.patch.object(
            lora_api, "build_text_payload", boom
        ), mock.patch.object(lora_api, "build_help_payload", boom):
            resp_list = asyncio.run(
                handlers[lora_api.ROUTE_PREFIX + "/list"](types.SimpleNamespace(query={}))
            )
            resp_text = asyncio.run(
                handlers[lora_api.ROUTE_PREFIX + "/text"](types.SimpleNamespace(query={}))
            )
            resp_help = asyncio.run(
                handlers[lora_api.ROUTE_PREFIX + "/help"](types.SimpleNamespace(query={}))
            )
        self.assertFalse(resp_list["payload"]["ok"])
        self.assertIn("boom", resp_list["payload"]["error"])
        self.assertEqual(resp_list["payload"]["items"], [])
        self.assertFalse(resp_text["payload"]["ok"])
        self.assertIn("boom", resp_text["payload"]["error"])
        self.assertFalse(resp_help["payload"]["ok"])
        self.assertIn("boom", resp_help["payload"]["error"])


# ============================================================================
#  模拟 ComfyUI 的加载方式（最关键的一层回归测试）
# ============================================================================
class TestSimulatedComfyUILoad(unittest.TestCase):
    """按 ``nodes.py::load_custom_node`` 的做法加载插件根 ``__init__.py``。

    ComfyUI 用的是::

        spec_from_file_location(name, "<插件目录>/__init__.py")   # 不带 submodule_search_locations

    此时 ``from .xxx import`` 会失败，所以插件必须靠 importlib 自举。这个测试就是防止
    那条自举路径将来被改坏（改坏的后果是：ComfyUI 启动后一个节点都看不到）。
    """

    def test_load_like_comfyui(self):
        module_name = "ltr_under_test_" + uuid.uuid4().hex[:8]
        init_py = os.path.join(ROOT, "__init__.py")
        saved_pkg = sys.modules.get("lora_trigger_reader")

        spec = importlib.util.spec_from_file_location(module_name, init_py)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                spec.loader.exec_module(module)
        finally:
            sys.modules.pop(module_name, None)

        output = buf.getvalue()
        self.assertNotIn("加载失败", output, f"插件加载报错了:\n{output}")

        self.assertEqual(
            set(module.NODE_CLASS_MAPPINGS),
            {"LoRAMultiLoader", "LoRATriggerReader", "LoRATriggerReaderMulti", "LoRATriggerReaderInfo"},
        )
        self.assertEqual(set(module.NODE_DISPLAY_NAME_MAPPINGS), set(module.NODE_CLASS_MAPPINGS))
        self.assertEqual(module.WEB_DIRECTORY, "./web")
        self.assertEqual(module.__version__, scan.VERSION)
        for name, cls in module.NODE_CLASS_MAPPINGS.items():
            self.assertTrue(callable(getattr(cls, cls.FUNCTION)), f"{name} 没有 {cls.FUNCTION} 方法")

        # WEB_DIRECTORY 必须真的存在，否则前端脚本会被静默跳过
        web_dir = os.path.join(ROOT, module.WEB_DIRECTORY)
        self.assertTrue(os.path.isdir(web_dir), web_dir)
        self.assertTrue(any(f.endswith(".js") for f in os.listdir(os.path.join(web_dir, "js"))))

        # 子模块 import 顺序不能互相破坏
        if saved_pkg is not None:
            self.assertIs(sys.modules.get("lora_trigger_reader"), saved_pkg)

    def test_package_submodules_are_importable(self):
        pkg = importlib.import_module("lora_trigger_reader")
        for sub in ("lora_scan", "graph_probe", "help_docs", "loader", "nodes", "api"):
            self.assertTrue(hasattr(pkg, sub), f"package 里缺少 {sub}（根 __init__.py 会用到）")
            self.assertTrue(importlib.import_module(f"lora_trigger_reader.{sub}"))


# ============================================================================
#  节点执行与 graph_probe 的衔接
# ============================================================================
class TestGraphIntegration(_Fixture):
    """确认节点真的用了 graph_probe 的结果（而不是自己另写一套）。"""

    def test_node_result_matches_probe_output(self):
        prompt = _chain_prompt([LORA_C, LORA_A], reader_type="LoRATriggerReaderMulti")
        probe = graph_probe.probe_prompt(prompt, READER_ID)
        self.assertEqual(probe["loras"], [LORA_C, LORA_A])
        node = lora_nodes.LoRATriggerReaderMulti()
        _model, text, _report = node.read(prompt=prompt, unique_id=READER_ID)
        self.assertEqual(text, "c1, c2, tag_a, tag_b")

    def test_multi_reads_everything_single_reads_one(self):
        chain = [LORA_C, LORA_A]
        self.assertEqual(self.single(chain)[1], "c1, c2")
        self.assertEqual(self.multi(chain)[1], "c1, c2, tag_a, tag_b")

    def test_reader_sees_the_multi_loaders_text_box(self):
        """``... -> LoRAMultiLoader -> LoRATriggerReader``：reader 要读到加载器文本框里的 LoRA。"""
        loader_id = "50"
        prompt = _chain_prompt([LORA_WOLF], reader_id=READER_ID)
        prompt[loader_id] = {
            "class_type": "LoRAMultiLoader",
            "inputs": {
                "lora_list": "A.safetensors\nsub/C.safetensors",
                "model": prompt[READER_ID]["inputs"]["model"],  # 原来接给 reader 的 LoraLoader 输出
                "clip": ["1", 1],
            },
        }
        prompt[READER_ID]["inputs"]["model"] = [loader_id, 0]

        probe = graph_probe.probe_prompt(prompt, READER_ID)
        self.assertIn("A.safetensors", probe["loras"])
        self.assertIn("sub/C.safetensors", probe["loras"])
        self.assertIn("silver_wolf.safetensors", probe["loras"])

        node = lora_nodes.LoRATriggerReaderMulti()
        _model, text, report = node.read(prompt=prompt, unique_id=READER_ID)
        self.assertIn("tag_a", text)
        self.assertIn("c1", text)
        self.assertIn(f"#{loader_id}", report)


if __name__ == "__main__":
    unittest.main(verbosity=2)
