# -*- coding: utf-8 -*-
"""
ComfyUI-LoRATriggerReader
=========================

读取 LoRA 的触发词文本（与 LoRA 同名、或文件名里含有 LoRA 完整名字的 .txt/.md），
整理后直接输出到工作流里，方便给 CLIP Text Encode 用。

v1.1 起：把上游 LoRA 加载节点的 MODEL 接到本节点的 ``model`` 输入即可 ——
节点会沿这条连线自动反查上游用的是哪些 LoRA，不需要手动选择。

ComfyUI 用 ``importlib.util.spec_from_file_location`` **不带包路径**的方式加载自定义节点
（见 ``nodes.py::load_custom_node``），此时 ``from .xxx import`` 这种相对导入会直接失败。
所以这里用 importlib 把自己的子包 ``lora_trigger_reader`` 注册成一个真正的包再导入，
既避免了相对导入的坑，也不会污染 ``sys.path``（不会和别人的 ``py`` / ``utils`` 撞名）。
"""

from __future__ import annotations

import importlib.util
import os
import sys
from types import ModuleType

__version__ = "1.3.0"

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGE_NAME = "lora_trigger_reader"
PACKAGE_DIR = os.path.join(HERE, PACKAGE_NAME)

#: ComfyUI 会把这个目录挂到 /extensions/<name>/ 下，前端自动加载里面的 js
WEB_DIRECTORY = "./web"

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}
__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY", "__version__"]


def _load_package() -> ModuleType:
    """把 ``lora_trigger_reader`` 子目录当成正规包加载（可重复调用）。"""
    init_py = os.path.join(PACKAGE_DIR, "__init__.py")
    if not os.path.isfile(init_py):
        raise ImportError(f"找不到插件包: {init_py}")

    existing = sys.modules.get(PACKAGE_NAME)
    if existing is not None:
        if getattr(existing, "__ltr_loaded__", False):
            return existing
        # 已经由别的方式（例如把插件目录加进 sys.path 后正常 import）加载过**同一个**包，
        # 那就直接复用，避免把 sys.modules 里的对象换掉造成模块身份不一致。
        existed_file = getattr(existing, "__file__", None)
        if existed_file and os.path.normcase(os.path.abspath(existed_file)) == os.path.normcase(init_py):
            existing.__ltr_loaded__ = True  # type: ignore[attr-defined]
            return existing

    spec = importlib.util.spec_from_file_location(
        PACKAGE_NAME,
        init_py,
        submodule_search_locations=[PACKAGE_DIR],
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"无法为 {init_py} 创建加载器")
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE_NAME] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(PACKAGE_NAME, None)
        raise
    module.__ltr_loaded__ = True  # type: ignore[attr-defined]
    return module


def _register_web_api() -> None:
    """注册 HTTP 接口（失败不影响节点本身）。"""
    try:
        api = importlib.import_module(PACKAGE_NAME + ".api")
    except Exception as exc:  # pragma: no cover
        print(f"[LoRATriggerReader] 无法导入 api 模块（不影响节点）: {type(exc).__name__}: {exc}")
        return
    try:
        ok = api.register_routes()
        if not ok:
            print("[LoRATriggerReader] 提示: 未注册 HTTP 接口（不影响节点使用）。")
    except Exception as exc:  # pragma: no cover
        print(f"[LoRATriggerReader] 注册 HTTP 接口失败: {type(exc).__name__}: {exc}")


try:  # pragma: no cover - 只有真正在 ComfyUI 里跑才会走到
    _pkg = _load_package()
    # 显式 import 子模块，而不是依赖 _pkg.nodes 这种属性访问：
    # 万一子包 __init__.py 没 import 某个子模块，属性访问会 AttributeError，
    # 那样整个插件就静默注册不上节点了。
    _scan_mod = importlib.import_module(PACKAGE_NAME + ".lora_scan")
    _nodes_mod = importlib.import_module(PACKAGE_NAME + ".nodes")
    NODE_CLASS_MAPPINGS = dict(getattr(_nodes_mod, "NODE_CLASS_MAPPINGS", {}))
    NODE_DISPLAY_NAME_MAPPINGS = dict(getattr(_nodes_mod, "NODE_DISPLAY_NAME_MAPPINGS", {}))
    __version__ = str(getattr(_scan_mod, "VERSION", __version__))
    _register_web_api()
    print(
        f"[LoRATriggerReader] 已加载 v{__version__}，"
        f"{len(NODE_CLASS_MAPPINGS)} 个节点: {', '.join(NODE_CLASS_MAPPINGS)}"
    )
except Exception as _exc:  # pragma: no cover
    import traceback

    print(f"[LoRATriggerReader] 加载失败: {type(_exc).__name__}: {_exc}")
    traceback.print_exc()
