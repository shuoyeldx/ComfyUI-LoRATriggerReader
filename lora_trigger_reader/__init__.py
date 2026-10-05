# -*- coding: utf-8 -*-
"""ComfyUI-LoRATriggerReader 逻辑层（package）。

子模块各自的职责：

* :mod:`lora_trigger_reader.lora_scan`   —— 核心扫描 / 匹配 / 读取逻辑（纯标准库，可单独测试）
* :mod:`lora_trigger_reader.graph_probe` —— 反查工作流（prompt）里上游用到的 LoRA（纯标准库）
* :mod:`lora_trigger_reader.loader`      —— 多 LoRA 加载器的解析 + 加载逻辑（惰性依赖 ComfyUI）
* :mod:`lora_trigger_reader.help_docs`   —— 节点的中英文使用说明文本（纯数据）
* :mod:`lora_trigger_reader.nodes`       —— ComfyUI 节点定义（V1 ``INPUT_TYPES``）
* :mod:`lora_trigger_reader.api`         —— 给前端选择器 / 说明面板用的 HTTP 接口

这里显式 import 各个子模块，是为了让 ``package.nodes`` / ``package.api`` 这种属性访问
一定成立（根目录 ``__init__.py`` 会用到），同时保证导入顺序不会循环依赖：
``lora_scan`` 不依赖任何同级模块，``graph_probe`` / ``help_docs`` 只依赖标准库，
``loader`` 只依赖 ``lora_scan``，``nodes`` / ``api`` 依赖以上全部。
"""

from . import lora_scan  # noqa: F401
from . import graph_probe  # noqa: F401
from . import help_docs  # noqa: F401
from . import loader  # noqa: F401
from . import nodes  # noqa: F401
from . import api  # noqa: F401

__all__ = ["lora_scan", "graph_probe", "loader", "help_docs", "nodes", "api"]
