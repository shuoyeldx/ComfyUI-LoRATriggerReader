# -*- coding: utf-8 -*-
"""给前端选择器用的 HTTP 接口（软依赖 aiohttp / server，缺失时自动跳过）。

接口列表::

    GET /lora_trigger_reader/list   列出全部 LoRA 及其触发词文本情况
        查询参数: refresh=1 强制重扫, extra_dirs=xxx 额外目录, preview=0 不返回预览
    GET /lora_trigger_reader/text   读取单个 LoRA 的完整触发词文本
        查询参数: lora_name=<相对路径>
    GET /lora_trigger_reader/help   节点的中英文使用说明（前端「❓ 使用说明」面板）
        查询参数: node=help|common|LoRAMultiLoader|LoRATriggerReader|...

返回 JSON，永远不会 500（出错也返回 ``ok: false`` + ``error``），
这样前端脚本可以放心地把接口失败降级掉。
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from . import help_docs
from . import lora_scan as scan

ROUTE_PREFIX = "/lora_trigger_reader"
PREVIEW_LIMIT = 120
PREVIEW_MAX_BYTES = 256 * 1024


def _preview(path: Optional[str], size: Any, limit: int = PREVIEW_LIMIT) -> str:
    if not path:
        return ""
    try:
        if isinstance(size, (int, float)) and size > PREVIEW_MAX_BYTES:
            return "(文件较大，略过预览)"
        text, _enc, _trunc = scan.read_text(path)
    except Exception as exc:  # pragma: no cover
        return f"(预览失败: {exc})"
    one = scan.format_trigger_text(text)
    if len(one) > limit:
        return one[:limit] + "…"
    return one


def build_list_payload(
    refresh: bool = False,
    extra_dirs: Any = None,
    with_preview: bool = True,
) -> Dict[str, Any]:
    """给 /list 接口准备数据（抽成普通函数，便于单测）。"""
    if refresh:
        scan.clear_index_cache()
    roots = scan.get_lora_roots()
    names = scan.list_lora_names()
    entries = scan.build_index(roots, extra_dirs=extra_dirs)
    size_by_path = {e.get("path"): e.get("size") for e in entries}

    items: List[Dict[str, Any]] = []
    for name in names:
        try:
            res = scan.resolve_lora(
                name,
                entries=entries,
                roots=roots,
                all_lora_names=names,
            )
        except Exception as exc:  # pragma: no cover
            items.append({"name": name, "status": "error", "error": str(exc)})
            continue
        size = size_by_path.get(res.get("trigger_file"))
        items.append(
            {
                "name": name,
                "base": os.path.basename(str(name).replace("\\", "/")),
                "status": res.get("status"),
                "file": res.get("trigger_file"),
                "trigger_rel": res.get("trigger_rel"),
                "chars": res.get("chars"),
                "encoding": res.get("encoding"),
                "score": res.get("score"),
                "size": size,
                "preview": _preview(res.get("trigger_file"), size) if with_preview else "",
            }
        )

    return {
        "ok": True,
        "version": scan.VERSION,
        "roots": roots,
        "count": len(items),
        "with_trigger": sum(1 for i in items if i.get("status") == "ok"),
        "empty": sum(1 for i in items if i.get("status") == "empty"),
        "items": items,
    }


def build_text_payload(lora_name: str, extra_dirs: Any = None) -> Dict[str, Any]:
    """给 /text 接口准备数据。"""
    name = str(lora_name or "").strip()
    if not name:
        return {"ok": False, "error": "缺少 lora_name 参数"}
    res = scan.resolve_lora(name, extra_dirs=extra_dirs, all_lora_names=scan.list_lora_names())
    return {
        "ok": res.get("status") == "ok",
        "name": name,
        "status": res.get("status"),
        "text": res.get("text") or "",
        "raw": res.get("raw") or "",
        "file": res.get("trigger_file"),
        "encoding": res.get("encoding"),
        "truncated": res.get("truncated"),
        "error": res.get("error") or "",
    }


def _is_true(value: Any) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def build_help_payload(node: Any = "help") -> Dict[str, Any]:
    """给 /help 接口准备数据（中英文节点说明）。"""
    try:
        return help_docs.docs_payload(str(node or "help").strip() or "help")
    except Exception as exc:  # pragma: no cover
        return {
            "ok": False,
            "node": str(node or "help"),
            "error": f"{type(exc).__name__}: {exc}",
            "nodes": [],
        }


def register_routes() -> bool:
    """注册 HTTP 路由。返回是否注册成功（没装 aiohttp 时返回 False）。"""
    try:  # pragma: no cover - 依赖 ComfyUI 运行环境
        from aiohttp import web  # type: ignore
        from server import PromptServer  # type: ignore
    except Exception:
        return False

    instance = getattr(PromptServer, "instance", None)
    routes = getattr(instance, "routes", None)
    if routes is None:
        return False

    async def _list(request: Any) -> Any:  # pragma: no cover
        try:
            payload = build_list_payload(
                refresh=_is_true(request.query.get("refresh", "")),
                extra_dirs=request.query.get("extra_dirs", ""),
                with_preview=not (request.query.get("preview") == "0"),
            )
        except Exception as exc:
            payload = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "items": []}
        return web.json_response(payload, headers={"Cache-Control": "no-store"})

    async def _text(request: Any) -> Any:  # pragma: no cover
        try:
            payload = build_text_payload(
                request.query.get("lora_name", ""),
                extra_dirs=request.query.get("extra_dirs", ""),
            )
        except Exception as exc:
            payload = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        return web.json_response(payload, headers={"Cache-Control": "no-store"})

    async def _help(request: Any) -> Any:  # pragma: no cover
        try:
            payload = build_help_payload(request.query.get("node", "help"))
        except Exception as exc:
            payload = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "nodes": []}
        return web.json_response(payload, headers={"Cache-Control": "no-store"})

    try:  # pragma: no cover
        routes.get(ROUTE_PREFIX + "/list")(_list)
        routes.get(ROUTE_PREFIX + "/text")(_text)
        routes.get(ROUTE_PREFIX + "/help")(_help)
    except Exception as exc:
        # 重复注册（例如热重载）时会抛错，这里忽略即可，接口已经存在
        print(f"[LoRATriggerReader] 注册 HTTP 接口时出现问题（通常可忽略）: {exc}")
        return False
    return True


__all__ = [
    "ROUTE_PREFIX",
    "build_help_payload",
    "build_list_payload",
    "build_text_payload",
    "register_routes",
]
