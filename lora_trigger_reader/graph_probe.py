# -*- coding: utf-8 -*-
"""从 ComfyUI 的 prompt（API 格式工作流）反查"本节点的模型接入链路上用了哪些 LoRA"。

为什么要这么做
--------------
``LoRATriggerReader`` 接在 ``LoraLoader`` 右边，输入是 MODEL。既然是"读这个模型用到的
LoRA 的触发词"，就应该**由接入链路自己决定读哪个 LoRA**，而不是让用户在下拉框里再选一次
（选错、或者上游换了 LoRA 而这里忘了改，都会静默出错）。

怎么拿到工作流
--------------
节点声明隐藏输入 ``{"hidden": {"unique_id": "UNIQUE_ID", "prompt": "PROMPT"}}``，
ComfyUI 就会把 ``unique_id``（本节点 id）和 ``prompt``（原始 API 格式工作流）传给节点函数：
见 ``ComfyUI/execution.py`` 里 ``get_input_data`` 对 ``"PROMPT"`` / ``"UNIQUE_ID"`` 的处理。

API 格式长这样::

    {"12": {"class_type": "LoraLoader",
            "inputs": {"lora_name": "Krea2/xxx.safetensors",
                       "strength_model": 1.0,
                       "model": ["4", 0],        # 连到别的节点=链接
                       "clip": ["4", 1]},
            "_meta": {"title": "LoraLoader"}}}

所以**按输入名找值**即可，完全不受前端 widget 顺序 / 版本差异影响：任何上游节点只要有一个
形如 ``lora_name`` / ``lora_1`` / ``lora_name_2`` / ``lora_stack`` 的输入且值是文件名，
就认为它是一个 LoRA 选择器（``LoraLoader``、``LoraLoaderModelOnly``、各种 LoRA Stacker、
pysssss / efficiency 之类的第三方 LoRA 节点都能覆盖）。

本模块**只用标准库**、纯函数、不 import torch/comfy/本包其它模块，方便脱离 ComfyUI 单测。
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# 向上游最多走多少层 / 最多看多少个节点，防止病态工作流里死循环
MAX_DEPTH = 64
MAX_NODES = 256

# 单看"包含 lora 且像名字"还不够，要防止 lora_strength / lora_model 之类的误判
_LORA_KEY_EXACT = frozenset(
    {
        "lora",
        "lora_name",
        "lora_names",
        "lora_list",
        "lora_path",
        "lora_file",
        "lora_filename",
        "lora_stack",
        "lora_stacks",
        "loras",
    }
)
_LORA_KEY_RE = re.compile(
    r"^(?:lora|lora_names?|lora_list)(?:_\d+)?$"          # lora / lora_1 / lora_name / lora_names_2 / lora_list
    r"|^lora_\d+_(?:name|list|path|file|filename)$"        # lora_1_name
    r"|^lora_(?:name|names|list|path|file|filename|stack|stacks)_\d+$"  # lora_name_1
    r"|^lora_(?:name|names|list|path|file|filename|stack|stacks)$",
    re.I,
)

# widget 被转成输入端（PrimitiveNode / "转换为输入"）时，顺着连线在这个节点里找回字符串
_WIDGET_VALUE_KEYS = frozenset({"lora_name", "value", "string", "text", "name", "lora", "str"})

# 这些值等于"没选"（含 v1.3 下拉框的「不使用 / none」哨兵值）
_EMPTY_VALUES = frozenset(
    {
        "",
        "none",
        "null",
        "nil",
        "undefined",
        "<未检测到 lora>",
        "无",
        "未选择",
        "不使用",
        "不使用 / none",
        "not used",
    }
)

_SPLIT_RE = re.compile(r"[\n\r,;，；、]+")

#: ``a.safetensors: 0.8`` / ``a.safetensors @ 0.8`` 这类"名字 + 强度"的写法，只取名字部分。
#: 只认 ``:`` / ``：`` / ``@`` 后面**全是数字**的情况，所以 Windows 路径
#: ``C:\loras\x.safetensors`` 不会被误切。
_STRENGTH_TAIL_RE = re.compile(
    r"^(?P<name>.+?)\s*[:：@]\s*[+-]?(?:\d+\.?\d*|\.\d+)"
    r"\s*(?:[,;，；]\s*[+-]?(?:\d+\.?\d*|\.\d+)\s*)?$"
)

#: 纯数字（``0.8`` / ``-1`` / ``.5``）：逗号拆开后剩下的强度值，直接丢掉
_NUMBER_ONLY_RE = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)$")


def is_lora_key(key: Any) -> bool:
    """这个输入名看起来是不是"选 LoRA"的输入？"""
    k = str(key or "").strip().lower()
    if "lora" not in k:
        return False
    if k in _LORA_KEY_EXACT:
        return True
    return bool(_LORA_KEY_RE.match(k))


def split_names(value: Any) -> List[str]:
    """把 LoRA 选择器的值拆成一个个 LoRA 名字。

    兼容：普通 ``lora_name``（单个文件名）、LoRA Stacker 的多行/逗号文本、
    已经是 list 的情况、``"None"`` 之类的空值。
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        out: List[str] = []
        for item in value:
            out.extend(split_names(item))
        return out
    if not isinstance(value, str):
        if isinstance(value, (int, float)):
            return []
        value = str(value)

    out = []
    for raw in _SPLIT_RE.split(value):
        piece = raw.strip().strip('"').strip("'").strip()
        # 允许 # 注释（有些 stack 文本里会带）
        if "#" in piece:
            piece = piece.split("#", 1)[0].strip()
        if not piece:
            continue
        # "妃咲.safetensors: 0.8" / "妃咲.safetensors @ 0.8" -> 只留名字
        match = _STRENGTH_TAIL_RE.match(piece)
        if match:
            piece = match.group("name").strip()
            if not piece:
                continue
        # 逗号拆开后剩下的强度值（"a.safetensors, 0.8" 里的 0.8）
        if _NUMBER_ONLY_RE.match(piece):
            continue
        low = piece.lower()
        # 「不使用 / none」这类下拉框占位值 = 这一行没选 LoRA
        if low in _EMPTY_VALUES or low.startswith("不使用") or low.startswith("<未检测到"):
            continue
        if len(piece) > 512:
            continue
        out.append(piece.replace("\\", "/"))
    return out


def is_link(value: Any) -> bool:
    """API 格式里"连到别的节点"的表示：``["<节点id>", <输出槽位>]``。"""
    return (
        isinstance(value, (list, tuple))
        and len(value) == 2
        and isinstance(value[0], (str, int))
        and isinstance(value[1], int)
    )


def get_node(prompt: Any, node_id: Any) -> Optional[Dict[str, Any]]:
    """从 prompt 里取节点（id 可能是 str / int，做兼容）。"""
    if not isinstance(prompt, dict):
        return None
    node = prompt.get(node_id)
    if isinstance(node, dict):
        return node
    node = prompt.get(str(node_id))
    if isinstance(node, dict):
        return node
    try:
        node = prompt.get(int(node_id))
    except (TypeError, ValueError):
        node = None
    return node if isinstance(node, dict) else None


def _link_targets(inputs: Any) -> List[Any]:
    """一个节点的 inputs 里，所有"连到上游"的节点 id（保持输入顺序）。"""
    if not isinstance(inputs, dict):
        return []
    out: List[Any] = []
    for value in inputs.values():
        if is_link(value):
            target = str(value[0])
            if target not in out:
                out.append(target)
    return out


def _linked_string(prompt: Any, value: Any, depth: int = 0) -> Optional[str]:
    """widget 被转成输入端时，顺着连线一步找回那个字符串值。"""
    if depth > 2 or not is_link(value):
        return None
    node = get_node(prompt, value[0])
    if not node:
        return None
    inputs = node.get("inputs")
    if not isinstance(inputs, dict):
        return None
    found: List[str] = []
    for key, val in inputs.items():
        if is_link(val):
            continue
        if isinstance(val, str) and val.strip() and str(key).lower() in _WIDGET_VALUE_KEYS:
            found.append(val.strip())
    # 只有一个候选才认为是这个 widget 的值，避免把整个节点的文本都当成 LoRA 名
    if len(found) == 1:
        return found[0]
    return None


def _node_root(node: Dict[str, Any]) -> str:
    return str(node.get("class_type") or node.get("type") or "?")


def _node_title(node: Dict[str, Any]) -> str:
    meta = node.get("_meta")
    if isinstance(meta, dict):
        title = meta.get("title")
        if title:
            return str(title)
    return ""


def _collect_node_loras(prompt: Any, node: Dict[str, Any], node_id: str) -> List[Dict[str, Any]]:
    """收集一个节点里所有"选 LoRA"输入的值。"""
    inputs = node.get("inputs")
    if not isinstance(inputs, dict):
        return []
    out: List[Dict[str, Any]] = []
    for key, value in inputs.items():
        if not is_lora_key(key):
            continue
        raw: Any = value
        if is_link(value):
            linked = _linked_string(prompt, value)
            if linked is None:
                continue
            raw = linked
        for name in split_names(raw):
            out.append(
                {
                    "node_id": node_id,
                    "class_type": _node_root(node),
                    "title": _node_title(node),
                    "key": str(key),
                    "lora_name": name,
                }
            )
    return out


def iter_lora_entries(
    prompt: Any,
    node_id: Any,
    max_depth: int = MAX_DEPTH,
    max_nodes: int = MAX_NODES,
) -> List[Dict[str, Any]]:
    """从 ``prompt`` 里反查 ``node_id`` 的上游链路，返回按"离本节点由近到远"排序的 LoRA 条目。

    每个条目：``{"node_id", "class_type", "title", "key", "lora_name"}``。
    只沿**所有输入连线**向上走（本节点一般只有一个 MODEL 输入），因此会一起发现
    ``LoraLoader`` 串联、多 LoRA 堆叠节点里的多个 LoRA。
    """
    start = get_node(prompt, node_id)
    if start is None:
        return []

    entries: List[Dict[str, Any]] = []
    seen_nodes: set = set()
    seen_items: set = set()
    visited = 0

    stack: List[Tuple[str, int]] = [(cid, 1) for cid in reversed(_link_targets(start.get("inputs")))]
    while stack:
        current_id, depth = stack.pop()
        if depth > max_depth or visited >= max_nodes:
            continue
        if current_id in seen_nodes:
            continue
        seen_nodes.add(current_id)
        visited += 1

        node = get_node(prompt, current_id)
        if node is None:
            continue
        for entry in _collect_node_loras(prompt, node, current_id):
            item_key = (entry["node_id"], entry["key"], entry["lora_name"].casefold())
            if item_key in seen_items:
                continue
            seen_items.add(item_key)
            entries.append(entry)

        for sub in reversed(_link_targets(node.get("inputs"))):
            if sub not in seen_nodes:
                stack.append((sub, depth + 1))

    return entries


def probe_prompt(prompt: Any, node_id: Any, **kwargs: Any) -> Dict[str, Any]:
    """给节点的执行入口用：把"接入链路上的 LoRA"整理成结构化结果。

    返回::

        {"ok": bool, "node_id": str, "entries": [...],
         "loras": [名字, 按由近到远去重], "sources": [...], "error": Optional[str]}
    """
    result: Dict[str, Any] = {
        "ok": False,
        "node_id": str(node_id) if node_id is not None else "",
        "entries": [],
        "loras": [],
        "sources": [],
        "error": None,
    }

    if not isinstance(prompt, dict) or not prompt:
        result["error"] = "没有拿到工作流信息（prompt 为空）"
        return result
    if node_id is None or node_id == "":
        result["error"] = "没有拿到本节点 id"
        return result
    node = get_node(prompt, node_id)
    if node is None:
        result["error"] = f"在工作流里找不到节点 {node_id}"
        return result

    entries = iter_lora_entries(prompt, node_id, **kwargs)
    result["ok"] = True
    result["entries"] = entries

    names: List[str] = []
    seen: set = set()
    for entry in entries:
        key = entry["lora_name"].casefold()
        if key in seen:
            continue
        seen.add(key)
        names.append(entry["lora_name"])
    result["loras"] = names

    sources: List[Dict[str, Any]] = []
    for entry in entries:
        sid = entry["node_id"]
        hit = next((s for s in sources if s["node_id"] == sid), None)
        if hit is None:
            hit = {
                "node_id": sid,
                "class_type": entry["class_type"],
                "title": entry["title"],
                "keys": [],
                "loras": [],
            }
            sources.append(hit)
        if entry["key"] not in hit["keys"]:
            hit["keys"].append(entry["key"])
        if entry["lora_name"] not in hit["loras"]:
            hit["loras"].append(entry["lora_name"])
    result["sources"] = sources
    return result


def describe_sources(probe: Dict[str, Any], max_items: int = 8) -> str:
    """把探测结果写成一行中文说明，放进节点报告里。"""
    if not isinstance(probe, dict) or not probe.get("ok"):
        reason = (probe or {}).get("error") if isinstance(probe, dict) else None
        return f"[接入链路] 无法反查工作流（{reason or '未知原因'}），只能使用手动填写的 LoRA。"
    sources = probe.get("sources") or []
    if not sources:
        return "[接入链路] 没有检测到 LoRA 节点（上游可能是 CheckpointLoader 直连）。"
    parts: List[str] = []
    for src in sources[:max_items]:
        label = f"#{src.get('node_id')} {src.get('class_type')}"
        title = src.get("title")
        if title and title != src.get("class_type"):
            label += f' "{title}"'
        names = ", ".join(src.get("loras") or [])
        parts.append(f"{label} -> {names}")
    text = "[接入链路] 检测到 " + "；".join(parts)
    if len(sources) > max_items:
        text += f"；其余 {len(sources) - max_items} 个省略"
    return text


def collect_names(probe: Dict[str, Any], limit: Optional[int] = None) -> List[str]:
    """取探测到的 LoRA 名字（``limit=1`` 即"离本节点最近的那一个"）。"""
    names = list((probe or {}).get("loras") or [])
    if limit is not None:
        return names[:limit]
    return names


__all__ = [
    "MAX_DEPTH",
    "MAX_NODES",
    "collect_names",
    "describe_sources",
    "get_node",
    "is_link",
    "is_lora_key",
    "iter_lora_entries",
    "probe_prompt",
    "split_names",
]
