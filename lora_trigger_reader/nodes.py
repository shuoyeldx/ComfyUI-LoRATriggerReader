# -*- coding: utf-8 -*-
"""ComfyUI 节点定义。

刻意使用 **V1 的 ``INPUT_TYPES`` / ``RETURN_TYPES``** 写法（而不是新的 V3 schema），
这样在很老到最新的 ComfyUI 上都能加载：新版本对 V1 节点 100% 向后兼容。

四个节点：

* ``LoRAMultiLoader``          —— 多重 LoRA 加载器：**下拉框选 LoRA + 各自独立的 MODEL 强度 /
  CLIP 强度**（可多行），一次加载到 MODEL + CLIP 上，同时输出这些 LoRA 的触发词
  （等价于好几个 LoraLoader 串起来）；也保留一个高级文本框用于批量粘贴
* ``LoRATriggerReader``        —— 接 MODEL，自动读取接入链路上**最近**那个 LoRA 的触发词
* ``LoRATriggerReaderMulti``   —— 接 MODEL，自动读取接入链路上**全部** LoRA 的触发词并合并
* ``LoRATriggerReaderInfo``    —— 不接模型，手动挑一个 LoRA 查看触发词（调试/查阅用）

所有节点都带**中英双语**的使用说明：类属性 ``DESCRIPTION``（鼠标悬停在节点上）、
端口 ``tooltip`` / ``OUTPUT_TOOLTIPS``（悬停端口）、以及节点上的「❓ 使用说明」按钮
（内容来自 ``help_docs.py`` + ``GET {ROUTE}/help`` 接口）。

自动检测怎么实现的
------------------
节点声明了隐藏输入 ``unique_id`` / ``prompt``，ComfyUI 会把本节点 id 和**原始 API 格式工作流**
传给节点函数（见 ``ComfyUI/execution.py`` 里 ``get_input_data`` 对 ``PROMPT`` / ``UNIQUE_ID``
的处理）。于是节点可以顺着 ``model`` 这条连线往上游走，找出链路上所有 LoRA 选择器
（``LoraLoader``、``LoraLoaderModelOnly``、各种 LoRA Stacker 等）里填的 LoRA 名，
再去匹配同名的触发词文本 —— **用户不用再选一次，上游换了 LoRA 这里自动跟着变**。

所有节点都不修改模型、不加载 LoRA，只做"查文本 -> 输出文本"，因此可以随意插拔。
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import graph_probe
from . import help_docs
from . import loader
from . import lora_scan as scan

CATEGORY = "LoRA/TriggerReader"

#: 帮助面板路由（前端「❓ 使用说明」按钮会请求它）
HELP_ROUTE = "/lora_trigger_reader/help"

# 输入端口上的说明（新前端会显示为 tooltip；老前端忽略该字段，安全）。
# 全部写成中英双语：ComfyUI 官方节点的 DESCRIPTION 也是纯文本，这里先中文后英文。
_TIP_MODEL = (
    "【中文】把 LoRA 链路的 MODEL 接进来。本节点会顺着这条连线往上游反查，自动找出链路上用到的 "
    "LoRA 并读取其触发词；节点不加载 LoRA、不修改模型，只原样透传。\n"
    "【English】Connect the LoRA chain's MODEL here. The node walks upstream along this link to "
    "find every LoRA used on the chain and read its trigger words. It never loads LoRAs or "
    "modifies the model - the model is passed through unchanged."
)
_TIP_LORA = (
    "【中文】要查看触发词的 LoRA；下拉列表来自 ComfyUI 的 loras 目录。\n"
    "【English】The LoRA whose trigger words you want to see; the dropdown comes from ComfyUI's "
    "loras folder."
)
_TIP_EXTRA_LORAS = (
    "【中文】手动补充要读取触发词的 LoRA，一行一个，平时留空。只有链路上检测不到时才需要填，"
    "例如 LoRA 是通过第三方节点或子工作流加载的。可以写完整相对路径，也可以只写文件名（自动补全），"
    "也可以带上强度（`名字: 0.8` 或 `名字 @ 0.8`）—— 强度只用来定位文件，读取触发词时会被忽略。\n"
    "【English】Manually add LoRA names to read, one per line; usually empty. Needed only when the "
    "chain cannot be detected, e.g. the LoRA is loaded by a third-party node or inside a subgraph. "
    "Full relative paths or plain file names are both accepted (auto-completed); a strength suffix "
    "(`name: 0.8` or `name @ 0.8`) is also understood and is ignored while reading trigger words."
)
_TIP_LORA_LIST = (
    "【中文】（高级）批量文本：一行一个 LoRA，可以带强度。\n"
    "  推荐直接用上面的下拉框选 LoRA、再单独设强度；这个框适合粘贴一长串、或者一次写很多个。\n"
    "  a.safetensors                  model/clip 都用 1.0\n"
    "  a.safetensors: 0.8             model/clip 都用 0.8\n"
    "  a.safetensors: 0.8, 0.5        model 0.8 / clip 0.5\n"
    "  a.safetensors @ 0.8 / a.safetensors, 0.8 / a.safetensors 0.8   其他写法\n"
    "  a.safetensors, b.safetensors  一行写两个\n"
    "只写文件名（如 妃咲）也能自动补全；# // -- 开头的行会忽略；写两次就加载两次。\n"
    "【English】(Advanced) Bulk text, one LoRA per line, strength optional. The dropdowns above are "
    "the normal way; use this box to paste a long list. Full example list:\n"
    "  a.safetensors | a.safetensors: 0.8 | a.safetensors: 0.8, 0.5 | a.safetensors @ 0.8 |\n"
    "  a.safetensors, 0.8 | a.safetensors 0.8 | a.safetensors, b.safetensors\n"
    "Plain file names are completed automatically; lines starting with # // -- are ignored; "
    "listing the same LoRA twice applies it twice."
)
_TIP_SLOT = (
    "【中文】下拉选一个 LoRA（下拉列表来自 ComfyUI 的 loras 目录）。选「不使用」= 这一行不加载。"
    "需要几个就填几行；不够就再用下面的「高级」文本框。\n"
    "【English】Pick one LoRA from the dropdown (the list comes from ComfyUI's loras folder). "
    "'不使用 / none' means this row loads nothing. Use as many rows as you need, or the advanced "
    "text box below for more."
)
_TIP_SLOT_MODEL = (
    "【中文】这一行 LoRA 对 MODEL 的强度：1.0 = 原样，0 = 不生效，负数是反向。"
    "点数字框左右的小箭头每次 ±0.1，也可以直接用键盘输入数字（范围 -100 ~ 100）。\n"
    "【English】MODEL strength for this row: 1.0 = unchanged, 0 = no effect, negative inverts. "
    "The little arrows step by 0.1; you can also type a number directly (range -100 .. 100)."
)
_TIP_SLOT_CLIP = (
    "【中文】这一行 LoRA 对 CLIP 的强度：和 MODEL 强度是**分开的两个框**（默认 1.0，"
    "和 ComfyUI 自带的 LoraLoader 一样）。想让 CLIP 跟 MODEL 一样，就把两个框改成同一个数。"
    "同样 0.1 步进、可以直接输入数字（-100 ~ 100）。\n"
    "【English】CLIP strength for this row: a separate box from the MODEL strength (default 1.0, "
    "same as ComfyUI's own LoraLoader). Set both boxes to the same number to keep them equal. "
    "0.1 steps, direct typing supported (range -100 .. 100)."
)
_TIP_LOADER_MODEL = (
    "【中文】要叠加 LoRA 的 MODEL。不接也能用：那样只输出触发词，不加载 LoRA。\n"
    "【English】The MODEL the LoRAs are applied to. Optional: without it the node only outputs "
    "trigger words."
)
_TIP_LOADER_CLIP = (
    "【中文】要叠加 LoRA 的 CLIP。和 model 一起接就是内置 LoraLoader 的效果；只接 CLIP 也可以。\n"
    "【English】The CLIP the LoRAs are applied to as well. Connect both model and clip for the "
    "behaviour of the built-in LoraLoader; clip alone works too."
)
_TIP_SEP = (
    "【中文】多条触发词之间的连接符，默认 ', '；填 \\n 表示换行。\n"
    "【English】Joiner between trigger words, default ', '; use \\n for line breaks."
)
_TIP_DEDUP = (
    "【中文】按整行去重（忽略大小写）。\n"
    "【English】Drop repeated lines (case-insensitive)."
)
_TIP_COMMENTS = (
    "【中文】忽略以 #、//、-- 开头的注释行。\n"
    "【English】Ignore whole-line comments starting with #, // or --."
)
_TIP_ON_MISSING = (
    "【中文】找不到触发词文本时怎么办：\n"
    "empty = 输出空字符串（默认）\n"
    "lora_name = 输出 LoRA 文件名（很多人用文件名当触发词）\n"
    "custom = 输出下面填写的兜底文本\n"
    "【English】What to output when no trigger file is found:\n"
    "empty = empty string (default)\n"
    "lora_name = the LoRA file name (many people use it as the trigger)\n"
    "custom = the fallback text below"
)
_TIP_FALLBACK = (
    "【中文】on_missing = custom 时使用的兜底文本。\n"
    "【English】Text used when on_missing = custom."
)
_TIP_EXTRA_DIRS = (
    "【中文】额外扫描目录（可写多个，用 ; 或换行分隔）。用于把触发词放在 LoRA 目录外的场景；留空即可。\n"
    "【English】Extra folders to scan (separate several with ; or newlines). Useful when trigger "
    "files live outside the LoRA folders; leave empty normally."
)
_TIP_REFRESH = (
    "【中文】勾选后本次执行强制重新扫描目录（默认走 8 秒缓存，速度更快）。\n"
    "【English】When enabled, this run forces a full rescan of the folders (otherwise an 8 second "
    "cache is used, which is faster)."
)


def _lora_list() -> List[str]:
    """下拉列表内容；在脱离 ComfyUI（单测）时返回占位项。"""
    try:
        names = scan.list_lora_names()
    except Exception:
        names = []
    return names or ["<未检测到 LoRA>"]


def _lora_options() -> List[str]:
    """多重加载器下拉框的选项：第一项永远是「不使用」，后面才是真实 LoRA。"""
    names = _lora_list()
    if names == ["<未检测到 LoRA>"]:
        return [loader.SLOT_NONE, "<未检测到 LoRA>"]
    return [loader.SLOT_NONE] + list(names)


def _slot_keys(index: int) -> Tuple[str, str, str]:
    """第 ``index`` 行（从 1 开始）三个控件的名字。"""
    return (f"lora_{index}", f"strength_{index}", f"clip_strength_{index}")


def _slot_columns(source: Mapping[str, Any]) -> Tuple[List[Any], List[Any], List[Any]]:
    """从"按控件名索引的字典"里取出每一行的 ``(名字, MODEL 强度, CLIP 强度)``。

    ``IS_CHANGED`` 收到的是 ``**kwargs``，所以用它来还原下拉框的值。
    """
    names: List[Any] = []
    model_strengths: List[Any] = []
    clip_strengths: List[Any] = []
    for index in range(1, loader.SLOT_COUNT + 1):
        name_key, strength_key, clip_key = _slot_keys(index)
        names.append(source.get(name_key, ""))
        model_strengths.append(source.get(strength_key, loader.DEFAULT_STRENGTH))
        clip_strengths.append(source.get(clip_key, loader.DEFAULT_STRENGTH))
    return (names, model_strengths, clip_strengths)


def _log(*parts: Any) -> None:
    """尽量使用 ComfyUI 自己的日志（没有就退回 print）。"""
    msg = "[LoRATriggerReader] " + " ".join(str(p) for p in parts)
    try:  # pragma: no cover - 依赖 ComfyUI
        from comfy.utils import logging as _c  # type: ignore

        getattr(_c, "info", print)(msg)
        return
    except Exception:
        pass
    try:  # pragma: no cover
        import logging

        logging.getLogger("LoRATriggerReader").info(msg)
    except Exception:
        print(msg)


def _insert_after_version(body: str, line: str) -> str:
    """把一行说明插到报告的第一行（版本行）后面。"""
    lines = body.split("\n")
    if len(lines) >= 1:
        lines.insert(1, line)
    else:  # pragma: no cover - build_report 至少两行
        lines.append(line)
    return "\n".join(lines)


def _dedupe(names: Sequence[str]) -> List[str]:
    """大小写不敏感去重，保持顺序。"""
    out: List[str] = []
    seen: set = set()
    for name in names:
        text = str(name or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


class _Common:
    """四个节点共用的输入片段与工具函数。"""

    RETURN_TYPES = ("MODEL", "STRING", "STRING")
    RETURN_NAMES = ("model", "trigger_words", "report")
    FUNCTION = "read"
    CATEGORY = CATEGORY
    OUTPUT_NODE = False

    #: 声明给 ComfyUI 的隐藏输入：本节点 id + 原始工作流
    HIDDEN_INPUTS: Dict[str, str] = {"unique_id": "UNIQUE_ID", "prompt": "PROMPT"}

    # 这些可选参数在三个节点里都一样
    @staticmethod
    def _common_optional() -> Dict[str, Any]:
        return {
            "separator": ("STRING", {"default": ", ", "tooltip": _TIP_SEP}),
            "deduplicate": ("BOOLEAN", {"default": True, "tooltip": _TIP_DEDUP}),
            "strip_comments": ("BOOLEAN", {"default": True, "tooltip": _TIP_COMMENTS}),
            "on_missing": (["empty", "lora_name", "custom"], {"default": "empty", "tooltip": _TIP_ON_MISSING}),
            "fallback_text": ("STRING", {"default": "", "multiline": True, "tooltip": _TIP_FALLBACK}),
            "extra_dirs": ("STRING", {"default": "", "multiline": False, "tooltip": _TIP_EXTRA_DIRS}),
            "refresh_cache": ("BOOLEAN", {"default": False, "tooltip": _TIP_REFRESH}),
        }

    @staticmethod
    def _prepare(refresh_cache: bool, extra_dirs: Any) -> List[str]:
        if refresh_cache:
            scan.clear_index_cache()
        roots = scan.get_lora_roots()
        if not roots:
            _log("警告：没有检测到 ComfyUI 的 loras 目录，节点将只能返回兜底文本。")
        return roots

    @classmethod
    def _is_changed(cls, extra_dirs: Any = "", **kwargs: Any) -> str:
        """IS_CHANGED：任何触发词文本被改动时，让 ComfyUI 重新执行本节点。

        注意：IS_CHANGED 阶段 ComfyUI 不会传工作流（``prompt`` 恒为空 dict），所以这里
        只能按"整个文本索引的指纹"判断；真正"上游换了 LoRA"导致的重算由 ``model``
        这条依赖自动完成（上游节点重算 -> MODEL 对象变了 -> 本节点重算）。
        """
        return scan.text_index_fingerprint(extra_dirs=extra_dirs)

    @classmethod
    def _resolve(
        cls,
        names: Sequence[str],
        *,
        separator: str,
        deduplicate: bool,
        strip_comments: bool,
        roots: Sequence[str],
        extra_dirs: Any,
        on_missing: str,
        fallback_text: str,
        known: Sequence[str],
    ) -> Tuple[str, str]:
        """真正读文本（两个自动节点共用）。"""
        return scan.resolve_loras(
            list(names),
            separator=separator,
            deduplicate=deduplicate,
            strip_comments=strip_comments,
            roots=roots,
            extra_dirs=extra_dirs,
            all_lora_names=known,
            on_missing=on_missing,
            fallback_text=fallback_text,
        )[:2]


class LoRAMultiLoader(_Common):
    """多重 LoRA 加载器：一次把多行 LoRA 加载到 MODEL + CLIP，并输出它们的触发词。"""

    RETURN_TYPES = ("MODEL", "CLIP", "STRING", "STRING")
    RETURN_NAMES = ("model", "clip", "trigger_words", "report")
    FUNCTION = "load"
    CATEGORY = CATEGORY
    OUTPUT_NODE = False

    DESCRIPTION = (
        "【中文】多重 LoRA 加载器：用下拉框一行一个选 LoRA（默认 4 行，选「不使用」= 跳过），"
        "每一行都有独立的 MODEL 强度和 CLIP 强度（1.0 = 原样，0 = 不生效，负数反向；点小箭头每次 0.1，"
        "也可以直接输入数字），一次把全部 LoRA 叠加到 MODEL 和 CLIP 上 —— 等价于把好几个 LoraLoader "
        "串起来；同时读取这些 LoRA 的触发词输出，可以直接接到 CLIPTextEncode。\n"
        "需要更多 LoRA 时，用下面的「(高级) 批量文本」框，一行写一个（也支持 `名字: 0.8` 这种写法）。\n"
        "model / clip 两个输入都可以不接：不接就只输出触发词、不做加载。\n"
        "下拉框和文本框都留空时，会自动使用 model 这条连线往上游找到的 LoRA。\n"
        "【English】Multi LoRA loader: pick one LoRA per row from the dropdown (4 rows by default, "
        "'不使用 / none' skips a row) and give each row its own MODEL strength and CLIP strength "
        "(1.0 = unchanged, 0 = no effect, negative inverts; the little arrows step by 0.1 and you can "
        "type a number directly). All LoRAs are applied to MODEL and CLIP by this single node - the "
        "equivalent of chaining several LoraLoader nodes - while reading their trigger words for "
        "CLIPTextEncode.\n"
        "Need more LoRAs? Use the advanced bulk text box below, one LoRA per line (a `name: 0.8` "
        "suffix is understood).\n"
        "Both model and clip inputs are optional: without them the node only outputs trigger words.\n"
        "When every dropdown and the text box are empty, the LoRAs found upstream on the model link "
        "are used automatically."
    )
    OUTPUT_TOOLTIPS = (
        "【中文】叠加了全部 LoRA 后的 MODEL\n【English】MODEL with every LoRA applied",
        "【中文】叠加了全部 LoRA 后的 CLIP\n【English】CLIP with every LoRA applied",
        "【中文】这些 LoRA 的触发词（合并后的文本）\n【English】Trigger words of those LoRAs",
        "【中文】加载 + 触发词匹配报告\n【English】Loading and matching report",
    )
    SEARCH_ALIASES = [
        "lora",
        "load lora",
        "lora loader",
        "multi lora",
        "lora stacker",
        "apply lora",
        "lora 加载器",
        "多重lora",
        "多重 lora",
        "多lora",
        "触发词",
        "trigger words",
    ]

    @classmethod
    def INPUT_TYPES(cls) -> Dict[str, Any]:
        options = _lora_options()
        required: Dict[str, Any] = {}
        for index in range(1, loader.SLOT_COUNT + 1):
            name_key, strength_key, clip_key = _slot_keys(index)
            required[name_key] = (
                options,
                {"default": options[0], "tooltip": _TIP_SLOT},
            )
            required[strength_key] = (
                "FLOAT",
                {
                    "default": loader.DEFAULT_STRENGTH,
                    "min": loader.MIN_STRENGTH,
                    "max": loader.MAX_STRENGTH,
                    "step": 0.1,
                    "tooltip": _TIP_SLOT_MODEL,
                },
            )
            required[clip_key] = (
                "FLOAT",
                {
                    "default": loader.DEFAULT_STRENGTH,
                    "min": loader.MIN_STRENGTH,
                    "max": loader.MAX_STRENGTH,
                    "step": 0.1,
                    "tooltip": _TIP_SLOT_CLIP,
                },
            )
        return {
            "required": required,
            "optional": dict(
                model=("MODEL", {"tooltip": _TIP_LOADER_MODEL}),
                clip=("CLIP", {"tooltip": _TIP_LOADER_CLIP}),
                lora_list=(
                    "STRING",
                    {"default": "", "multiline": True, "tooltip": _TIP_LORA_LIST},
                ),
                **_Common._common_optional(),
            ),
            "hidden": dict(_Common.HIDDEN_INPUTS),
        }

    @classmethod
    def IS_CHANGED(cls, lora_list: str = "", extra_dirs: Any = "", **kwargs: Any) -> str:
        """指纹 = 每个 LoRA 文件（路径+强度+大小/mtime） + 触发词文本索引。"""
        parts: List[str] = []
        try:
            known = scan.list_lora_names()
            slot_specs, _slot_warnings = loader.parse_slots(*_slot_columns(kwargs))
            text_specs, _text_warnings = loader.parse_specs(lora_list, known)
            for spec in list(slot_specs) + list(text_specs):
                path = scan.get_lora_full_path(str(spec.get("name") or ""))
                stamp = loader.file_stamp(path) if path else "-"
                parts.append(
                    "{name}|{sm}|{sc}|{stamp}".format(
                        name=spec.get("name"),
                        sm=spec.get("strength_model"),
                        sc=spec.get("strength_clip"),
                        stamp=stamp,
                    )
                )
        except Exception:
            return "fallback"
        return "||".join(parts) + "||" + _Common._is_changed(extra_dirs=extra_dirs)

    def load(  # noqa: A003 - ComfyUI 的 FUNCTION 名
        self,
        lora_1: str = "",
        strength_1: Any = loader.DEFAULT_STRENGTH,
        clip_strength_1: Any = loader.DEFAULT_STRENGTH,
        lora_2: str = "",
        strength_2: Any = loader.DEFAULT_STRENGTH,
        clip_strength_2: Any = loader.DEFAULT_STRENGTH,
        lora_3: str = "",
        strength_3: Any = loader.DEFAULT_STRENGTH,
        clip_strength_3: Any = loader.DEFAULT_STRENGTH,
        lora_4: str = "",
        strength_4: Any = loader.DEFAULT_STRENGTH,
        clip_strength_4: Any = loader.DEFAULT_STRENGTH,
        lora_list: str = "",
        model: Any = None,
        clip: Any = None,
        separator: str = ", ",
        deduplicate: bool = True,
        strip_comments: bool = True,
        on_missing: str = "empty",
        fallback_text: str = "",
        extra_dirs: Any = "",
        refresh_cache: bool = False,
        unique_id: Any = None,
        prompt: Any = None,
    ) -> Tuple[Any, Any, str, str]:
        # 注意：这里的 4 行下拉框形参必须和 loader.SLOT_COUNT / _slot_keys() 保持一致
        roots = self._prepare(refresh_cache, extra_dirs)
        if refresh_cache:
            loader.clear_lora_cache()
        known = scan.list_lora_names()

        slot_specs, slot_warnings = loader.parse_slots(
            [lora_1, lora_2, lora_3, lora_4],
            [strength_1, strength_2, strength_3, strength_4],
            [clip_strength_1, clip_strength_2, clip_strength_3, clip_strength_4],
        )
        text_specs, text_warnings = loader.parse_specs(lora_list, known)
        specs = list(slot_specs) + list(text_specs)
        warnings = list(slot_warnings) + list(text_warnings)

        # 下拉框和文本框都为空时，退回到"顺着 model 连线往上游找 LoRA"（V1.1 的行为）
        auto_line = ""
        if not specs:
            probe = graph_probe.probe_prompt(prompt, unique_id)
            # collect_names 是"离本节点由近到远"，加载要按模型流向（远 -> 近）
            detected = list(reversed(graph_probe.collect_names(probe)))
            if detected:
                specs = [loader.make_spec(name) for name in detected]
                auto_line = (
                    "[多重加载器] 下拉框和文本框都没写 LoRA，已自动使用 model 接入链路上的 LoRA"
                    f"（按模型流向依次加载，共 {len(detected)} 个）。"
                )
            else:
                auto_line = graph_probe.describe_sources(probe)

        model_out, clip_out, outcomes = loader.apply_loras(model, clip, specs, roots=roots)

        report_lines = loader.format_load_report(outcomes)
        if auto_line:
            report_lines.insert(0, auto_line)
        for note in warnings:
            report_lines.append(f"[多重加载器] 注意：{note}")

        names = _dedupe([str(spec.get("name") or "") for spec in specs])
        if not names:
            report = "\n".join(
                [
                    f"LoRATriggerReader v{scan.VERSION}",
                    *report_lines,
                    "没有读到任何 LoRA：请在上面的下拉框里选 LoRA（可以选多行），"
                    "或者在「(高级) 批量文本」里一行一个填写；"
                    "也可以把上游 LoRA 的 MODEL 接到 model 输入上（都留空时自动检测）。",
                ]
            )
            _log("多重加载器：没有可用的 LoRA")
            return (model_out, clip_out, "", report)

        text, body = self._resolve(
            names,
            separator=separator,
            deduplicate=deduplicate,
            strip_comments=strip_comments,
            roots=roots,
            extra_dirs=extra_dirs,
            on_missing=on_missing,
            fallback_text=fallback_text,
            known=known,
        )
        lines = body.split("\n")
        report = "\n".join(lines[:1] + report_lines + lines[1:])
        return (model_out, clip_out, text, report)


class _AutoBase(_Common):
    """自动检测模式的两个节点共用的实现。"""

    #: True = 只取离本节点最近的一个 LoRA；False = 取链路上全部
    ONLY_NEAREST = True

    #: 报告里"读了几个"的说法
    SCOPE_TEXT = "接入链路上最近的 LoRA"

    OUTPUT_TOOLTIPS = (
        "【中文】原样透传的 MODEL（本节点不修改模型）\n【English】The MODEL passed through unchanged",
        "【中文】读到的触发词\n【English】The trigger words that were read",
        "【中文】检测 + 匹配报告\n【English】Detection and matching report",
    )
    SEARCH_ALIASES = [
        "lora trigger",
        "trigger words",
        "lora trigger words",
        "lora info",
        "prompt text",
        "lora 触发词",
        "触发词",
        "触发词读取",
        "提示词",
    ]

    @classmethod
    def INPUT_TYPES(cls) -> Dict[str, Any]:
        return {
            "required": {
                "model": ("MODEL", {"tooltip": _TIP_MODEL}),
            },
            "optional": dict(
                extra_loras=("STRING", {"default": "", "multiline": True, "tooltip": _TIP_EXTRA_LORAS}),
                **_Common._common_optional(),
            ),
            "hidden": dict(_Common.HIDDEN_INPUTS),
        }

    @classmethod
    def IS_CHANGED(cls, extra_dirs: Any = "", **kwargs: Any) -> str:
        return _Common._is_changed(extra_dirs=extra_dirs)

    def read(
        self,
        model: Any = None,
        extra_loras: str = "",
        separator: str = ", ",
        deduplicate: bool = True,
        strip_comments: bool = True,
        on_missing: str = "empty",
        fallback_text: str = "",
        extra_dirs: Any = "",
        refresh_cache: bool = False,
        unique_id: Any = None,
        prompt: Any = None,
    ) -> Tuple[Any, str, str]:
        roots = self._prepare(refresh_cache, extra_dirs)
        known = scan.list_lora_names()

        probe = graph_probe.probe_prompt(prompt, unique_id)
        detected = graph_probe.collect_names(probe, limit=1 if self.ONLY_NEAREST else None)
        # 用 loader.parse_specs 而不是 scan.parse_lora_text：前者会把 `名字: 0.8` 这类强度尾巴
        # 剥离掉（v1.3 修的 bug —— 带权重的短名字会让匹配分数掉到阈值以下，触发词变空）。
        manual_specs, _manual_warnings = loader.parse_specs(extra_loras, known)
        manual = [str(spec.get("name") or "") for spec in manual_specs]
        # 自动检测在前（离本节点最近的排在前面），手动补充在后
        names = _dedupe(list(detected) + list(manual))
        source_line = graph_probe.describe_sources(probe)

        if not names:
            report = (
                f"LoRATriggerReader v{scan.VERSION}\n"
                f"{source_line}\n"
                f"没有读到任何 LoRA：请把上游的 MODEL 接到本节点的 model 输入上，"
                f"或在 extra_loras 里手动填写 LoRA（{self.SCOPE_TEXT}）。"
            )
            _log("没有可读取的 LoRA：", source_line)
            return (model, "", report)

        text, body = self._resolve(
            names,
            separator=separator,
            deduplicate=deduplicate,
            strip_comments=strip_comments,
            roots=roots,
            extra_dirs=extra_dirs,
            on_missing=on_missing,
            fallback_text=fallback_text,
            known=known,
        )
        report = _insert_after_version(body, source_line)
        return (model, text, report)


class LoRATriggerReader(_AutoBase):
    """自动模式：读取接入链路上最近的那个 LoRA 的触发词。"""

    ONLY_NEAREST = True
    SCOPE_TEXT = "接入链路上最近的一个 LoRA"

    DESCRIPTION = (
        "【中文】接在 LoRA 选择节点（LoraLoader 等）右边。\n"
        "它不靠手动选择：而是顺着 model 这条连线往上游反查，自动找出这条链路上用到的 LoRA，"
        "再读取同名（或包含其完整名字）的触发词文本，整理成一行输出。\n"
        "单 LoRA、或者只想用「最后加载的那个 LoRA」的触发词时用这个。\n"
        "【English】Place it to the right of your LoRA loader(s). Instead of picking a LoRA by hand it "
        "walks the model link upstream, finds the LoRA used on that chain, reads the text file with the "
        "same name (or one containing its full name) and outputs the trigger words on one line.\n"
        "Use this node for a single LoRA, or when you only want the last-loaded LoRA's trigger words."
    )


class LoRATriggerReaderMulti(_AutoBase):
    """自动模式：读取接入链路上全部 LoRA 的触发词并合并。"""

    ONLY_NEAREST = False
    SCOPE_TEXT = "接入链路上的全部 LoRA"

    DESCRIPTION = (
        "【中文】接在 LoRA 选择节点（LoraLoader 等）右边，串了几个 LoRA 就读取几个。\n"
        "顺着 model 连线反查整条链路，把链路上所有 LoRA 的触发词按加载顺序合并成一行输出。\n"
        "多 LoRA 串联、或者用了多 LoRA 堆叠节点时用这个。\n"
        "【English】Place it to the right of your LoRA loaders; it reads as many LoRAs as you chained. "
        "It walks the whole model chain upstream and merges the trigger words of every LoRA, in load "
        "order, into one output.\n"
        "Use this node for chained LoRAs or multi-LoRA stacker nodes."
    )
    SEARCH_ALIASES = [
        *_AutoBase.SEARCH_ALIASES,
        "multi lora trigger",
        "all lora trigger words",
        "全部触发词",
        "多lora触发词",
    ]


class LoRATriggerReaderInfo:
    """只读信息节点：不接模型，手动挑一个 LoRA 查看触发词。"""

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("trigger_words", "report")
    FUNCTION = "read"
    CATEGORY = CATEGORY
    OUTPUT_NODE = False
    DESCRIPTION = (
        "【中文】不接模型，手动挑一个 LoRA，看看它有没有触发词文本、内容是什么。\n"
        "适合用来调试：放到工作流里连一个 Show Text 就能看。\n"
        "【English】No model input: pick one LoRA by hand and see whether it has a trigger-word text "
        "file and what is inside. Handy for debugging - drop it anywhere and connect a Show Text node."
    )
    OUTPUT_TOOLTIPS = (
        "【中文】读到的触发词\n【English】The trigger words that were read",
        "【中文】匹配报告\n【English】Matching report",
    )
    SEARCH_ALIASES = [
        "lora info",
        "lora text",
        "trigger words",
        "lora 信息",
        "lora 触发词查看",
        "触发词查看",
        "查看触发词",
    ]

    @classmethod
    def INPUT_TYPES(cls) -> Dict[str, Any]:
        return {
            "required": {
                "lora_name": (_lora_list(), {"tooltip": _TIP_LORA}),
            },
            "optional": dict(_Common._common_optional()),
        }

    @classmethod
    def IS_CHANGED(cls, lora_name: str = "", extra_dirs: Any = "", **kwargs: Any) -> str:
        # 手动模式知道具体是哪个 LoRA，可以给出更精确的指纹（该文件 + 整体索引）
        precise = ""
        try:
            entries = scan.build_index(extra_dirs=extra_dirs)
            entry, _score, _c = scan.match_text_entry(str(lora_name or ""), entries, scan.list_lora_names())
            if entry:
                precise = f"{entry.get('path')}|{entry.get('size')}|{entry.get('mtime')}|"
        except Exception:
            precise = ""
        return precise + _Common._is_changed(extra_dirs=extra_dirs)

    def read(
        self,
        lora_name: str = "",
        separator: str = ", ",
        deduplicate: bool = True,
        strip_comments: bool = True,
        on_missing: str = "empty",
        fallback_text: str = "",
        extra_dirs: Any = "",
        refresh_cache: bool = False,
    ) -> Tuple[str, str]:
        _Common._prepare(refresh_cache, extra_dirs)
        if not lora_name:
            return ("", f"LoRATriggerReader v{scan.VERSION}\n没有选择 LoRA。")
        res = scan.resolve_lora(
            lora_name,
            separator=separator,
            deduplicate=deduplicate,
            strip_comments=strip_comments,
            extra_dirs=extra_dirs,
            all_lora_names=scan.list_lora_names(),
        )
        return (scan.resolve_with_fallback(res, on_missing, fallback_text), scan.build_report([res]))


NODE_CLASS_MAPPINGS: Dict[str, Any] = {
    "LoRAMultiLoader": LoRAMultiLoader,
    "LoRATriggerReader": LoRATriggerReader,
    "LoRATriggerReaderMulti": LoRATriggerReaderMulti,
    "LoRATriggerReaderInfo": LoRATriggerReaderInfo,
}

NODE_DISPLAY_NAME_MAPPINGS: Dict[str, str] = {
    "LoRAMultiLoader": "多重 LoRA 加载器 (LoRA Multi Loader)",
    "LoRATriggerReader": "LoRA 触发词读取·自动 (LoRA Trigger Reader)",
    "LoRATriggerReaderMulti": "LoRA 触发词读取·自动多选 (LoRA Trigger Reader Multi)",
    "LoRATriggerReaderInfo": "LoRA 触发词查看 (LoRA Trigger Info)",
}
