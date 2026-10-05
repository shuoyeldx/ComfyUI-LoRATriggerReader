# -*- coding: utf-8 -*-
"""真实 LoRA 目录的端到端自检脚本（不需要 ComfyUI 运行）。

它做三件事：

1. 扫描一个真实的 LoRA 目录（默认自动探测 ComfyUI 常见位置），把所有模型文件当成
   "ComfyUI 里能选到的 LoRA 名字"；
2. 对每一个 LoRA 跑一遍 ``resolve_lora``，看有没有匹配到触发词文本、匹配到哪个文件、得分多少；
3. 打印统计和最典型的几条结果。

用法::

    python tests/integration_real_loras.py                          # 自动探测
    python tests/integration_real_loras.py "D:/ComfyUI/models/loras"
    python tests/integration_real_loras.py "D:/ComfyUI/models/loras" --extra "D:/触发词"
    python tests/integration_real_loras.py --list                   # 只列出名字，不做匹配

排查"某个 LoRA 读不到触发词"时特别有用：它会告诉你到底匹配到了哪个文件（或没匹配到）。
"""

from __future__ import annotations

import os
import sys
from typing import Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from lora_trigger_reader import lora_scan as scan  # noqa: E402

MODEL_EXTENSIONS = (".safetensors", ".ckpt", ".pt", ".pth", ".gguf", ".sft")


def guess_loras_roots() -> List[str]:
    """猜一猜 LoRA 目录在哪（跟真实 ComfyUI 无关，纯路径猜测）。"""
    here = ROOT
    candidates: List[str] = []
    env = os.environ.get("COMFYUI_LORAS_DIR")
    if env:
        candidates.append(env)
    # 插件被放在 <ComfyUI>/custom_nodes/<插件> 时的推导
    custom_nodes = os.path.dirname(here)
    if os.path.basename(os.path.normcase(custom_nodes)) == os.path.normcase("custom_nodes"):
        candidates.append(os.path.join(os.path.dirname(custom_nodes), "models", "loras"))
    # 本机常见位置
    candidates += [
        r"I:\ComfyUI-aki-v2\ComfyUI\models\loras",
        r"D:\ComfyUI\models\loras",
        r"C:\ComfyUI\models\loras",
        os.path.expanduser("~/ComfyUI/models/loras"),
    ]
    out: List[str] = []
    for path in candidates:
        if path and os.path.isdir(path) and os.path.abspath(path) not in out:
            out.append(os.path.abspath(path))
    return out


def collect_lora_names(root: str) -> List[str]:
    """把目录里的模型文件收集成"相对路径"形式的名字（和 ComfyUI 一致，用 / 分隔）。"""
    names: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() not in MODEL_EXTENSIONS:
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root).replace("\\", "/")
            names.append(rel)
    names.sort()
    return names


def main(argv: List[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    extra: List[str] = []
    if "--extra" in argv:
        idx = argv.index("--extra")
        if idx + 1 < len(argv):
            extra = [argv[idx + 1]]

    roots: List[str] = []
    if args:
        roots = [os.path.abspath(args[0])]
    else:
        guessed = guess_loras_roots()
        if not guessed:
            print("没有找到 LoRA 目录，请手动指定：python tests/integration_real_loras.py <loras目录>")
            return 2
        roots = guessed[:1]

    root = roots[0]
    if not os.path.isdir(root):
        print(f"目录不存在: {root}")
        return 2

    names = collect_lora_names(root)
    texts = scan.collect_text_files(roots + [d for d in extra if os.path.isdir(d)])
    print(f"LoRA 目录 : {root}")
    if extra:
        print(f"额外目录 : {', '.join(extra)}")
    print(f"LoRA 数量 : {len(names)}")
    print(f"文本文件 : {len(texts)}  (扩展名 {'/'.join(scan.TEXT_EXTENSIONS)})")
    print("-" * 100)

    if "--list" in argv:
        for n in names:
            print(n)
        return 0

    # 让扫描逻辑以为这就是 ComfyUI 的 LoRA 目录
    scan.get_lora_roots = lambda: list(roots)  # type: ignore[assignment]
    scan.list_lora_names = lambda: list(names)  # type: ignore[assignment]
    scan.clear_index_cache()
    entries = scan.build_index(roots, extra_dirs=extra)

    stats: Dict[str, int] = {}
    hits: List[str] = []
    misses: List[str] = []
    for name in names:
        res = scan.resolve_lora(
            name, entries=entries, roots=roots, extra_dirs=extra, all_lora_names=names
        )
        status = str(res.get("status"))
        stats[status] = stats.get(status, 0) + 1
        line = (
            f"[{status:>9}] 分数 {res.get('score'):>4}  {name}"
            f"  ->  {res.get('trigger_rel') or '(无)'}"
        )
        (hits if status in ("ok", "empty") else misses).append(line)

    print("== 匹配到触发词文本 ==")
    for line in hits:
        print(line)
    print("== 没有匹配到 ==")
    for line in misses:
        print(line)
    print("-" * 100)
    print("统计: " + " | ".join(f"{k}={v}" for k, v in sorted(stats.items())))
    total = len(names) or 1
    print(f"命中率: {(stats.get('ok', 0) / total) * 100:.1f}% (有内容) ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
