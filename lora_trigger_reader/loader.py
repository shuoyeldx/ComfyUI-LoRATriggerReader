# -*- coding: utf-8 -*-
"""多 LoRA 加载器用到的「解析 + 加载」逻辑（和 ComfyUI 解耦，方便单测）。

职责划分
--------

* 解析「下拉框 + 强度框」（:func:`parse_slots`）或 ``lora_list`` 文本
  （:func:`parse_specs`）-> 一组 spec（名字 + model/clip 强度）；
* 依次把每个 LoRA 应用到 MODEL / CLIP 上（顺序 = 书写顺序，写两次就叠加两次，
  和串两个 ``LoraLoader`` 的行为一致）；
* 读 LoRA 文件时带一个小容量缓存（默认 4 个），避免改一个强度就要重新读盘；
* **任何一步失败都不会让工作流崩掉**：错误收集进 outcomes，由 ``nodes.py`` 写进报告。

真正依赖 ComfyUI 的部分（``comfy.utils.load_torch_file`` / ``comfy.sd.load_lora_for_models``）
都是**惰性导入**的，所以本模块在没有 ComfyUI 的环境里也能 import、能单测。
"""

from __future__ import annotations

import math
import os
import re
from collections import OrderedDict
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from . import lora_scan as scan

#: 默认强度（同 ComfyUI 的 LoraLoader）
DEFAULT_STRENGTH = 1.0
#: 强度范围（同 ComfyUI 的 LoraLoader）
MIN_STRENGTH = -100.0
MAX_STRENGTH = 100.0
#: 一次最多加载多少个 LoRA（防止手滑粘进来几百行）
MAX_SPECS = 64
#: LoRA 文件缓存数量
CACHE_MAX = 4
#: 下拉框里表示「这一行不加载」的占位值
SLOT_NONE = "不使用 / none"
#: 多重加载器的下拉行数（改这里即可增减行数；``nodes.py`` 里 ``load()`` 的形参也要同步改）
SLOT_COUNT = 4

_COMMENT_PREFIXES = ("#", "//", "--")
_FLOAT_RE = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$")
_STRENGTH_SEP_RE = re.compile(r"[,，;；\s]+")
_NAME_SPLIT_RE = re.compile(r"[,，;；]+")
#: ComfyUI 提示词里常见的 ``<lora:名字:0.8>`` 写法
_LORA_ANGLE_RE = re.compile(r"^<\s*lora\s*:\s*(?P<name>.+?)\s*(?::\s*(?P<weights>[^:>]*))?\s*>$", re.I)
_LORA_EXT_RE = re.compile(r"\.(?:safetensors|sft|ckpt|pt|pth|bin|gguf|safetensor)$", re.I)

#: path -> (指纹, lora 张量, metadata)
_LORA_CACHE: "OrderedDict[str, Tuple[str, Any, Any]]" = OrderedDict()


# --------------------------------------------------------------------------------------
# 文本解析
# --------------------------------------------------------------------------------------
def _to_float(token: Any) -> Optional[float]:
    """能转成 float 就返回，否则 None（``nan`` / ``inf`` 也返回 None）。"""
    text = str(token).strip()
    if not text or not _FLOAT_RE.match(text):
        return None
    try:
        value = float(text)
    except (TypeError, ValueError):  # pragma: no cover - 正则已挡住
        return None
    return value if math.isfinite(value) else None


def _strength_list(raw: str) -> Optional[List[float]]:
    """把 ``0.8`` / ``0.8, 0.5`` / ``0.8 0.5`` 解析成强度列表；不是强度就返回 None。"""
    text = str(raw or "").strip()
    if not text:
        return None
    parts = [p for p in _STRENGTH_SEP_RE.split(text) if p]
    if not parts:
        return None
    out: List[float] = []
    for part in parts:
        value = _to_float(part)
        if value is None:
            return None
        out.append(value)
    return out


def _known_keys(known_names: Optional[Sequence[str]]) -> set:
    """把 ComfyUI 的 LoRA 列表压成一组用于判断"这像不像 LoRA 名"的键。"""
    keys = set()
    for raw in known_names or ():
        text = str(raw or "").strip().replace("\\", "/")
        if not text:
            continue
        base = text.rsplit("/", 1)[-1]
        for item in (text, base, os.path.splitext(base)[0]):
            if item:
                keys.add(item.casefold())
    return keys


def _looks_like_lora(name: str, keys: set) -> bool:
    """名字是否"确实像个 LoRA"：带 LoRA 扩展名，或能在已知列表里找到。"""
    text = str(name or "").strip()
    if not text:
        return False
    if _LORA_EXT_RE.search(text):
        return True
    if not keys:
        return False
    flat = text.replace("\\", "/")
    base = flat.rsplit("/", 1)[-1]
    return flat.casefold() in keys or base.casefold() in keys or os.path.splitext(base)[0].casefold() in keys


def split_strengths(
    line: str,
    known_names: Optional[Sequence[str]] = None,
) -> Tuple[List[str], List[float], str]:
    """把一行拆成 ``(名字列表, 强度列表, 提示)``。

    ================================ ========================== ==========
    写法                              结果                       备注
    ================================ ========================== ==========
    ``a.safetensors``                (["a.safetensors"], [], "") 强度默认 1.0
    ``a.safetensors: 0.8``           ([...], [0.8], "")         model/clip 都用 0.8
    ``a.safetensors: 0.8, 0.5``      ([...], [0.8, 0.5], "")    model 0.8 / clip 0.5
    ``a.safetensors @ 0.8``          ([...], [0.8], "")         ``@`` 等价于 ``:``
    ``a.safetensors, 0.8``           ([...], [0.8], "")         逗号写法
    ``a.safetensors 0.8``            ([...], [0.8], "")         空格写法（只在"像 LoRA"时切）
    ``<lora:a:0.8>``                 (["a"], [0.8], "")         提示词写法
    ``a.safetensors, b.safetensors`` (["a", "b"], [], "")        多个名字
    ================================ ========================== ==========

    只有"右边真的全是数字"时才当强度，所以 ``C:\\loras\\x.safetensors`` 这种
    带冒号的 Windows 路径不会被误切；空格写法额外要求前半部分**确实像个 LoRA 名字**
    （带 .safetensors 之类的扩展名，或能在 ``known_names`` 里找到），避免把
    ``my lora v2`` 这种带空格的名字切坏。
    """
    text = str(line or "").strip()
    if not text:
        return ([], [], "")

    keys = _known_keys(known_names) if known_names else set()

    # 0) ComfyUI 提示词写法 <lora:名字:0.8>
    angle = _LORA_ANGLE_RE.match(text)
    if angle:
        name = (angle.group("name") or "").strip()
        if name:
            got = _strength_list(angle.group("weights") or "")
            return ([name], got or [], "")

    if "@" in text:
        left, right = text.rsplit("@", 1)
        got = _strength_list(right)
        if got is not None and left.strip():
            return ([left.strip()], got, "")

    # 冒号（半角/全角都支持），取最后出现的那个
    idx = max(text.rfind(":"), text.rfind("："))
    if idx > 0:
        left, right = text[:idx], text[idx + 1 :]
        got = _strength_list(right)
        if got is not None and left.strip():
            return ([left.strip()], got, "")

    tokens = [t.strip() for t in _NAME_SPLIT_RE.split(text) if t.strip()]
    if len(tokens) > 1:
        rest = [_to_float(t) for t in tokens[1:]]
        if _to_float(tokens[0]) is None and all(v is not None for v in rest):
            return ([tokens[0]], [v for v in rest if v is not None], "")
        return (tokens, [], "")

    # 空格写法：只有前半部分确实像个 LoRA 名字时才当强度，名字里的空格不受影响
    parts = text.split()
    if len(parts) >= 2:
        # 从最长的候选名字开始试，这样 `my lora v2.safetensors 0.3` 也能正确切分
        for cut in range(len(parts) - 1, 0, -1):
            head = " ".join(parts[:cut])
            rest = [_to_float(p) for p in parts[cut:]]
            if (
                _to_float(head) is None
                and all(v is not None for v in rest)
                and _looks_like_lora(head, keys)
            ):
                return ([head], [v for v in rest if v is not None], "")

    return ([text], [], "")


def clamp_strength(value: Any) -> Tuple[float, str]:
    """校验强度：非法 -> 1.0；超范围 -> 夹到 [-100, 100]。返回 ``(值, 提示)``。"""
    number = _to_float(value)
    if number is None:
        return DEFAULT_STRENGTH, f"强度 {value!r} 不是有效数字，已按 {DEFAULT_STRENGTH} 处理"
    if number < MIN_STRENGTH or number > MAX_STRENGTH:
        fixed = max(MIN_STRENGTH, min(MAX_STRENGTH, number))
        return fixed, f"强度 {number:g} 超出 [{MIN_STRENGTH:g}, {MAX_STRENGTH:g}]，已限制为 {fixed:g}"
    return number, ""


def make_spec(
    name: str,
    strength_model: Any = DEFAULT_STRENGTH,
    strength_clip: Any = None,
) -> Dict[str, Any]:
    """构造一个 spec（供"自动检测到的 LoRA"复用）。"""
    sm, _ = clamp_strength(strength_model)
    sc, _ = clamp_strength(sm if strength_clip is None else strength_clip)
    return {
        "name": str(name or ""),
        "strength_model": sm,
        "strength_clip": sc,
        "raw": str(name or ""),
        "line": 0,
    }


def parse_specs(
    raw: Any,
    known_names: Optional[Sequence[str]] = None,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """解析 ``lora_list`` 文本，返回 ``(specs, warnings)``。

    * ``#`` / ``//`` / ``--`` 开头的行整行忽略，行尾 `` # 备注`` 也会去掉；
    * 同一行里逗号分隔的多个名字（例 ``a.safetensors, b.safetensors``）会拆成多个 spec；
    * 传 ``known_names``（ComfyUI 的 LoRA 列表）时做名字补全：
      只写 ``妃咲`` 或 ``妃咲.safetensors`` 也能补成 ``Krea2/Krea2角色lora/妃咲.safetensors``；
    * **不去重**：同一个 LoRA 写两行会真的加载两次（效果叠加），和串两个 LoraLoader 一致。
    """
    specs: List[Dict[str, Any]] = []
    warnings: List[str] = []
    text = str(raw or "").replace("\r\n", "\n").replace("\r", "\n")

    for lineno, line in enumerate(text.split("\n"), 1):
        line = line.strip()
        if not line or line.startswith(_COMMENT_PREFIXES):
            continue
        if " #" in line:  # 行尾注释
            line = line.split(" #", 1)[0].strip()
        if not line:
            continue

        names, strengths, note = split_strengths(line, known_names)
        if note:
            warnings.append(f"第 {lineno} 行：{note}")
        if len(strengths) > 2:
            warnings.append(f"第 {lineno} 行：强度最多两个（model、clip），多余的已忽略")
            strengths = strengths[:2]
        sm, note_m = clamp_strength(strengths[0] if strengths else DEFAULT_STRENGTH)
        sc, note_c = clamp_strength(
            strengths[1] if len(strengths) > 1 else (strengths[0] if strengths else DEFAULT_STRENGTH)
        )
        for extra in (note_m, note_c):
            if extra:
                warnings.append(f"第 {lineno} 行：{extra}")

        for name in names:
            if _to_float(name) is not None:
                warnings.append(f"第 {lineno} 行：忽略纯数字项 {name!r}")
                continue
            for item in scan.parse_lora_text(name, known_names) or [name]:
                if _to_float(item) is not None:
                    continue
                specs.append(
                    {
                        "name": str(item),
                        "strength_model": sm,
                        "strength_clip": sc,
                        "raw": str(name),
                        "line": lineno,
                    }
                )

        if len(specs) > MAX_SPECS:
            warnings.append(f"LoRA 数量超过 {MAX_SPECS} 个，多余的已忽略")
            specs = specs[:MAX_SPECS]
            break

    return specs, warnings


def _pick(seq: Optional[Sequence[Any]], index: int, default: Any = None) -> Any:
    """取 ``seq[index]``；越界 / None / 空串都返回 ``default``。"""
    try:
        value = seq[index]  # type: ignore[index]
    except (TypeError, IndexError, KeyError):
        return default
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    return value


def parse_slots(
    names: Sequence[Any],
    strengths: Optional[Sequence[Any]] = None,
    clip_strengths: Optional[Sequence[Any]] = None,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """把「下拉框 + 两个强度框」组成的一行行参数变成 specs。

    * 每行一个 LoRA：``lora_1`` / ``strength_1`` / ``clip_strength_1`` ...；
    * ``SLOT_NONE`` / 空值 = 这一行不加载；下拉框报「未检测到 LoRA」时也跳过；
    * 强度非法 -> 1.0，越界 -> 夹到 ``[-100, 100]``，两种情况都会写进 warnings；
    * clip 强度没给（None / 空）时跟随 model 强度，和内置 LoraLoader 一致；
    * 超过 ``MAX_SPECS`` 行时截断并写警告；
    * 下拉框里的名字来自 ComfyUI 的列表，因此**不做名字补全**，原样交给解析器。
    """
    specs: List[Dict[str, Any]] = []
    warnings: List[str] = []
    for index, raw in enumerate(list(names or ()), 1):
        name = str(raw or "").strip()
        if not name or name == SLOT_NONE or name.startswith("<未检测到"):
            continue
        raw_sm = _pick(strengths, index - 1, DEFAULT_STRENGTH)
        raw_sc = _pick(clip_strengths, index - 1, None)
        sm, note_m = clamp_strength(raw_sm)
        sc, note_c = clamp_strength(sm if raw_sc is None else raw_sc)
        for note in (note_m, note_c):
            if note:
                warnings.append(f"第 {index} 行（下拉框）：{note}")
        specs.append(
            {
                "name": name,
                "strength_model": sm,
                "strength_clip": sc,
                "raw": name,
                "line": index,
                "from_slot": True,
            }
        )
    if len(specs) > MAX_SPECS:
        warnings.append(
            f"下拉框的行数超过 {MAX_SPECS}（共 {len(specs)} 行），已忽略后面的 "
            f"{len(specs) - MAX_SPECS} 行"
        )
        specs = specs[:MAX_SPECS]
    return specs, warnings


# --------------------------------------------------------------------------------------
# 加载
# --------------------------------------------------------------------------------------
def clear_lora_cache() -> None:
    """清空 LoRA 张量缓存。"""
    _LORA_CACHE.clear()


def file_stamp(path: str) -> str:
    """``size|mtime_ns`` 指纹，用于判断缓存是否过期。"""
    try:
        st = os.stat(path)
        return f"{st.st_size}|{int(st.st_mtime_ns)}"
    except Exception:
        return "-"


def _default_load_tensor(path: str) -> Tuple[Any, Any]:
    """默认的 LoRA 文件读取（惰性导入 comfy.utils，兼容不同版本）。"""
    import comfy.utils  # type: ignore  # pragma: no cover - 依赖 ComfyUI

    try:  # 新版有 return_metadata
        got = comfy.utils.load_torch_file(path, safe_load=True, return_metadata=True)
    except TypeError:  # 老版没有这个参数
        got = comfy.utils.load_torch_file(path, safe_load=True)
    if isinstance(got, tuple) and len(got) == 2:
        return got[0], got[1]
    return got, None


def load_tensor_cached(path: str, loader: Optional[Callable[[str], Any]] = None) -> Tuple[Any, Any, bool]:
    """读 LoRA 张量（带缓存）。返回 ``(lora, metadata, 是否命中缓存)``。

    传了自定义 ``loader``（单测）时不走缓存。
    """
    if loader is not None:
        got = loader(path)
        if isinstance(got, tuple) and len(got) == 2:
            return got[0], got[1], False
        return got, None, False

    key = os.path.normcase(os.path.abspath(path))
    stamp = file_stamp(path)
    hit = _LORA_CACHE.get(key)
    if hit is not None and hit[0] == stamp:
        _LORA_CACHE.move_to_end(key)
        return hit[1], hit[2], True

    lora, meta = _default_load_tensor(path)
    _LORA_CACHE[key] = (stamp, lora, meta)
    _LORA_CACHE.move_to_end(key)
    while len(_LORA_CACHE) > CACHE_MAX:
        _LORA_CACHE.popitem(last=False)
    return lora, meta, False


def _default_apply(
    model: Any,
    clip: Any,
    lora: Any,
    strength_model: float,
    strength_clip: float,
    metadata: Any = None,
) -> Tuple[Any, Any]:
    """默认的 LoRA 应用（惰性导入 comfy.sd，兼容老版本没有 lora_metadata 参数）。"""
    import comfy.sd  # type: ignore  # pragma: no cover - 依赖 ComfyUI

    try:
        return comfy.sd.load_lora_for_models(
            model, clip, lora, strength_model, strength_clip, lora_metadata=metadata
        )
    except TypeError:  # pragma: no cover - 老版本 ComfyUI
        return comfy.sd.load_lora_for_models(model, clip, lora, strength_model, strength_clip)


def apply_loras(
    model: Any,
    clip: Any,
    specs: Sequence[Dict[str, Any]],
    *,
    roots: Optional[Sequence[str]] = None,
    resolve_path: Optional[Callable[[str], Optional[str]]] = None,
    load_tensor: Optional[Callable[[str], Any]] = None,
    apply_one: Optional[Callable[..., Tuple[Any, Any]]] = None,
) -> Tuple[Any, Any, List[Dict[str, Any]]]:
    """依次把 ``specs`` 应用到 MODEL / CLIP 上。

    返回 ``(model, clip, outcomes)``；outcomes 每项字段：
    ``name, strength_model, strength_clip, path, ok, skipped, cached, error``。

    ``model`` 与 ``clip`` 都为 None（两个口都没接）时只解析路径、不加载，
    outcomes 里标记 ``skipped``，这样节点仍然能输出触发词。
    """
    outcomes: List[Dict[str, Any]] = []
    if resolve_path is None:
        root_list = list(roots) if roots is not None else scan.get_lora_roots()

        def resolve_path(name: str) -> Optional[str]:  # type: ignore[misc]
            return scan.get_lora_full_path(name, root_list)

    for spec in specs:
        name = str(spec.get("name") or "")
        outcome: Dict[str, Any] = {
            "name": name,
            "strength_model": spec.get("strength_model", DEFAULT_STRENGTH),
            "strength_clip": spec.get("strength_clip", DEFAULT_STRENGTH),
            "path": None,
            "ok": False,
            "skipped": False,
            "cached": False,
            "error": "",
        }
        try:
            path = resolve_path(name)
        except Exception as exc:  # pragma: no cover - 防御
            path = None
            outcome["error"] = f"解析 LoRA 路径失败: {exc}"
        if not path:
            outcome["error"] = outcome["error"] or "在 LoRA 目录里找不到该文件"
            outcomes.append(outcome)
            continue
        outcome["path"] = path

        if model is None and clip is None:
            outcome["ok"] = True
            outcome["skipped"] = True
            outcomes.append(outcome)
            continue

        try:
            lora, meta, cached = load_tensor_cached(path, load_tensor)
            outcome["cached"] = bool(cached)
        except Exception as exc:
            outcome["error"] = f"读取 LoRA 文件失败: {exc}"
            outcomes.append(outcome)
            continue

        apply = apply_one or _default_apply
        try:
            model, clip = apply(
                model,
                clip,
                lora,
                float(outcome["strength_model"]),
                float(outcome["strength_clip"]),
                meta,
            )
            outcome["ok"] = True
        except Exception as exc:
            outcome["error"] = f"应用 LoRA 失败: {exc}"
        outcomes.append(outcome)

    return model, clip, outcomes


def format_load_report(outcomes: Sequence[Dict[str, Any]]) -> List[str]:
    """把 outcomes 变成写进报告的若干行（纯文本、中文）。"""
    loaded = [o for o in outcomes if o.get("ok") and not o.get("skipped")]
    skipped = [o for o in outcomes if o.get("skipped")]
    failed = [o for o in outcomes if not o.get("ok")]
    cache_hits = sum(1 for o in loaded if o.get("cached"))

    def _label(outcome: Dict[str, Any]) -> str:
        base = os.path.basename(str(outcome.get("name", "")).replace("\\", "/"))
        sm = float(outcome.get("strength_model", DEFAULT_STRENGTH))
        sc = float(outcome.get("strength_clip", DEFAULT_STRENGTH))
        if sm == sc:
            return f"{base}({sm:g})"
        return f"{base}(model {sm:g} / clip {sc:g})"

    lines: List[str] = []
    if loaded:
        items = ", ".join(_label(o) for o in loaded)
        lines.append(f"[多重加载器] 已加载 {len(loaded)} 个 LoRA：{items}")
        if cache_hits:
            lines.append(f"[多重加载器] 其中 {cache_hits} 个直接用了内存缓存。")
    if skipped:
        lines.append(
            f"[多重加载器] MODEL / CLIP 都没接，跳过加载 {len(skipped)} 个 LoRA（触发词照常输出）。"
        )
    for outcome in failed:
        lines.append(
            f"[多重加载器] 加载失败：{outcome.get('name')} -> {outcome.get('error') or '未知错误'}"
        )
    if not lines and not outcomes:
        lines.append("[多重加载器] lora_list 是空的，没有加载任何 LoRA。")
    return lines


__all__ = [
    "DEFAULT_STRENGTH",
    "MIN_STRENGTH",
    "MAX_STRENGTH",
    "MAX_SPECS",
    "CACHE_MAX",
    "SLOT_NONE",
    "SLOT_COUNT",
    "apply_loras",
    "clamp_strength",
    "clear_lora_cache",
    "file_stamp",
    "format_load_report",
    "load_tensor_cached",
    "make_spec",
    "parse_slots",
    "parse_specs",
    "split_strengths",
]
