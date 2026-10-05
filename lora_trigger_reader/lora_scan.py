# -*- coding: utf-8 -*-
"""ComfyUI-LoRATriggerReader 核心逻辑层。

本模块只做三件事，且**不依赖 torch / comfy 运行时**（`folder_paths` 为可选软依赖）：

1. 扫描 LoRA 目录，建立"文本文件索引"（.txt / .md）；
2. 根据 LoRA 名称，在索引中匹配"同名 / 含 LoRA 全名 / 去后缀"的触发词文本；
3. 读取并格式化文本，输出可直接粘贴进提示词的字符串。

因此本模块可以脱离 ComfyUI 单独单元测试（见 tests/test_lora_scan.py）。
"""

from __future__ import annotations

import codecs
import difflib
import os
import re
import threading
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# --------------------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------------------

VERSION = "1.3.0"

#: 视为"触发词文本"的扩展名（全部小写，含点）
TEXT_EXTENSIONS: Tuple[str, ...] = (".txt", ".md")

#: 单个文本文件最多读取的字节数，防止误把超大文件读进显存/内存
MAX_FILE_BYTES = 1024 * 1024  # 1 MiB

#: 文本索引缓存有效期（秒）。目录内容变化最多 8 秒后生效。
INDEX_TTL_SECONDS = 8.0

#: 扫描目录时跳过的文件夹名
SKIP_DIR_NAMES = {
    ".git", ".github", "__pycache__", "node_modules", ".idea", ".vscode",
    ".cache", ".trash", "$RECYCLE.BIN", "System Volume Information",
}

#: 常见的"触发词文件后缀词"。去掉它们之后若等于 LoRA 名，视为强匹配。
#: 例如 `Anima尼可提示词.txt` -> `Anima尼可`，正好等于 `Anima尼可.safetensors`。
SUFFIX_WORDS: Tuple[str, ...] = (
    "触发词", "提示词", "关键词", "说明", "备注", "词", "語", "语",
    "triggerwords", "triggerword", "triggers", "trigger",
    "prompts", "prompt", "keywords", "keyword",
    "activationwords", "activation", "activate", "words", "word",
    "tags", "tag", "info", "note", "notes", "readme", "read",
)

#: 匹配时需要忽略的字符（大小写 + 空白 + 这些分隔符）
_NORM_DROP_RE = re.compile(r"[\s_\-·．.、,，]+")

#: 每行内容尾部需要清理的分隔符
_LINE_TAIL_RE = re.compile(r"[,，;；、\s]+$")

#: 行内注释前缀
_COMMENT_PREFIXES = ("#", "//", "--")

#: 低于该分数认为"没匹配上"
MIN_ACCEPT_SCORE = 700

#: 是否启用模糊匹配（difflib，≥0.90 且归属校验通过才采用）
ENABLE_FUZZY_MATCH = True

#: 模糊匹配阈值
FUZZY_RATIO = 0.90

#: "包含类"匹配（900 / 850 / 800 档）要求参与比较的名字至少有这么"具体"，
#: 否则像 LoRA ``a`` 这种极短的名字会去抢任意带 a 的文本文件。
#: 中日韩等表意文字信息密度高，两个字就足够区分，所以单独放宽到 2 个字符。
MIN_CONTAIN_CHARS = 4
_CJK_RANGES = (
    (0x2E80, 0x303F),   # 中日韩符号/标点
    (0x3040, 0x30FF),   # 日文假名
    (0x3400, 0x4DBF),   # 扩展 A
    (0x4E00, 0x9FFF),   # 基本汉字
    (0xAC00, 0xD7AF),   # 谚文
    (0xF900, 0xFAFF),   # 兼容汉字
    (0xFF00, 0xFFEF),   # 全角字符
)


def _has_cjk(text: str) -> bool:
    for ch in text:
        code = ord(ch)
        for low, high in _CJK_RANGES:
            if low <= code <= high:
                return True
    return False


def _specific_enough(name: str) -> bool:
    """名字是否足够"具体"，可以参与包含类 / 前缀类匹配。

    * ``>= MIN_CONTAIN_CHARS`` 个字符 → 足够具体；
    * 否则只要含有中日韩字符且 ``>= 2`` 个字符也算足够具体（例如 LoRA ``妃咲``）。
    """
    if len(name) >= MIN_CONTAIN_CHARS:
        return True
    return len(name) >= 2 and _has_cjk(name)


# --------------------------------------------------------------------------------------
# 可选依赖：folder_paths
# --------------------------------------------------------------------------------------

try:  # pragma: no cover - 取决于运行环境
    import folder_paths  # type: ignore

    _HAS_FOLDER_PATHS = True
except Exception:  # pragma: no cover
    folder_paths = None  # type: ignore
    _HAS_FOLDER_PATHS = False


def has_folder_paths() -> bool:
    """是否成功加载了 ComfyUI 的 folder_paths 模块。"""
    return _HAS_FOLDER_PATHS


# --------------------------------------------------------------------------------------
# 名称归一化与匹配打分
# --------------------------------------------------------------------------------------


def normalize(name: str) -> str:
    """归一化名称：转小写 + 去掉空白与常见分隔符，便于宽松比较。"""
    if not name:
        return ""
    return _NORM_DROP_RE.sub("", str(name).casefold())


def strip_suffix_words(stem: str) -> str:
    """循环剥掉尾部的"触发词/提示词/trigger"等后缀词，再剥掉残余分隔符。"""
    s = normalize(stem)
    changed = True
    while changed and s:
        changed = False
        for word in SUFFIX_WORDS:
            w = normalize(word)
            if w and s.endswith(w) and len(s) > len(w):
                s = s[: -len(w)]
                changed = True
    return _NORM_DROP_RE.sub("", s)


def _owner_conflict(txt_norm: str, lora_norm: str, other_lora_norms: Sequence[str]) -> bool:
    """判断这个文本是不是"更像属于另一个 LoRA"。

    例如 LoRA `A` 与 LoRA `AB` 同时存在，文本 `AB触发词.txt` 里同时包含 `a` 和 `ab`，
    更长的 `ab` 才是它真正的主人 —— 此时 `A` 不应该抢走它。
    """
    if not other_lora_norms:
        return False
    best = ""
    for other in other_lora_norms:
        if not other or other == lora_norm or len(other) < 2:
            continue
        if other in txt_norm and len(other) > len(best):
            best = other
    return bool(best) and len(best) >= len(lora_norm)


def score_entry(
    lora_name: str,
    entry: Dict[str, Any],
    other_lora_norms: Optional[Sequence[str]] = None,
    lora_dir: Optional[str] = None,
) -> int:
    """给一个候选文本文件打分，分数越高越可信；0 表示不采用。

    评分梯度（同目录额外 +25）::

        1000  文本名 == LoRA 文件名（含扩展名）
         980  文本名 == LoRA 主名（去扩展名）
         950  文本名去掉"提示词/触发词/trigger"等后缀 == LoRA 主名
         900  文本名以 LoRA 主名开头（如 `Anima尼可提示词`）
         850  文本名包含 LoRA 主名（用户要求的"含有 LoRA 完整名字"）
         800  LoRA 主名包含文本名（如 LoRA `xx_v2` 对文本 `xx`）
         600+ difflib 模糊匹配（>=0.90）

    900 / 850 / 800 这三档是"包含类"匹配，容易误伤，因此额外要求参与的短名字
    足够具体（见 :func:`_specific_enough`）：LoRA 叫 ``a`` 时不会去抢 ``any.txt``。
    """
    lora_base = os.path.basename(str(lora_name).replace("\\", "/"))
    lora_stem = os.path.splitext(lora_base)[0]
    lora_norm = normalize(lora_stem)
    full_norm = normalize(lora_base)
    if not lora_norm:
        return 0

    txt_stem = entry.get("stem", "")
    txt_norm = entry.get("norm_stem", "") or normalize(txt_stem)
    txt_suffix = entry.get("suffix_stem", "") or strip_suffix_words(txt_stem)

    score = 0
    if txt_stem == lora_base or txt_norm == full_norm:
        score = 1000
    elif txt_norm == lora_norm:
        score = 980
    elif txt_suffix and txt_suffix == lora_norm:
        score = 950
    elif txt_norm.startswith(lora_norm) and _specific_enough(lora_norm):
        score = 900
    elif lora_norm in txt_norm and _specific_enough(lora_norm):
        score = 850
    elif txt_norm and txt_norm in lora_norm and _specific_enough(txt_norm):
        score = 800
    elif ENABLE_FUZZY_MATCH:
        ratio = difflib.SequenceMatcher(None, txt_norm, lora_norm).ratio()
        if ratio >= FUZZY_RATIO:
            score = int(600 + 100 * ratio)

    if score <= 0:
        return 0

    # 归属校验：只对"包含类/模糊类"这种可能抢错文件的档位生效
    if score < 950 and _owner_conflict(txt_norm, lora_norm, other_lora_norms or ()):
        return 0

    # 同目录加成：触发词文本通常和 LoRA 放在一起
    if lora_dir and entry.get("dir") and os.path.normcase(entry["dir"]) == os.path.normcase(lora_dir):
        score += 25
    return score


# --------------------------------------------------------------------------------------
# 文本索引（目录扫描 + TTL 缓存）
# --------------------------------------------------------------------------------------


class _IndexCache:
    """极简 TTL 缓存，避免每个节点执行时都重扫一遍大目录（网络盘尤其重要）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._key: Any = None
        self._time: float = 0.0
        self._entries: List[Dict[str, Any]] = []

    def get(self, key: Any) -> Optional[List[Dict[str, Any]]]:
        with self._lock:
            if self._key == key and (time.time() - self._time) < INDEX_TTL_SECONDS:
                return self._entries
        return None

    def put(self, key: Any, entries: List[Dict[str, Any]]) -> None:
        with self._lock:
            self._key = key
            self._time = time.time()
            self._entries = entries

    def clear(self) -> None:
        with self._lock:
            self._key = None
            self._time = 0.0
            self._entries = []


_CACHE = _IndexCache()


def get_lora_roots() -> List[str]:
    """返回 ComfyUI 已注册的全部 LoRA 根目录（支持 extra_model_paths.yaml 多路径）。"""
    if not _HAS_FOLDER_PATHS:
        return []
    roots: List[str] = []
    try:
        for p in folder_paths.get_folder_paths("loras"):
            if p and os.path.isdir(p):
                roots.append(os.path.abspath(p))
    except Exception:
        return []
    return roots


def list_lora_names() -> List[str]:
    """返回 ComfyUI 可识别的 LoRA 列表（相对路径，使用 `/` 分隔）。"""
    if not _HAS_FOLDER_PATHS:
        return []
    try:
        return list(folder_paths.get_filename_list("loras"))
    except Exception:
        return []


def get_lora_full_path(lora_name: str, search_roots: Optional[Sequence[str]] = None) -> Optional[str]:
    """把 LoRA 相对名解析为磁盘绝对路径。

    兼容新旧 ComfyUI：优先 `get_full_path_or_raise`，退回 `get_full_path`，
    最后再手动在各根目录里找一遍（并尝试反斜杠容错）。
    `search_roots` 用于脱离 ComfyUI 的单测/外部调用。
    """
    if not lora_name:
        return None
    name = str(lora_name).strip().replace("\\", "/")
    if _HAS_FOLDER_PATHS:
        for attr in ("get_full_path_or_raise", "get_full_path"):
            fn = getattr(folder_paths, attr, None)
            if fn is None:
                continue
            try:
                got = fn("loras", name)
                if got and os.path.isfile(got):
                    return os.path.abspath(got)
            except Exception:
                pass
    roots = list(search_roots) if search_roots else get_lora_roots()
    for root in roots:
        direct = os.path.join(root, *name.split("/"))
        if os.path.isfile(direct):
            return os.path.abspath(direct)
    return None


def _split_dirs(raw: Any) -> List[str]:
    """把 `extra_dirs` 字符串拆成目录列表（支持 `;` `|` 与换行分隔）。"""
    if not raw:
        return []
    if isinstance(raw, (list, tuple)):
        parts: List[str] = []
        for item in raw:
            parts.extend(_split_dirs(item))
        return parts
    text = str(raw).replace("\r", "\n")
    parts = re.split(r"[;\n|]+", text)
    out: List[str] = []
    for p in parts:
        p = p.strip().strip('"').strip("'")
        if p and os.path.isdir(p):
            out.append(os.path.abspath(p))
    return out


def collect_text_files(roots: Sequence[str]) -> List[Dict[str, Any]]:
    """递归收集所有触发词文本文件，返回索引条目列表。"""
    entries: List[Dict[str, Any]] = []
    seen: set = set()
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_NAMES and not d.startswith(".")]
            for fn in filenames:
                ext = os.path.splitext(fn)[1].lower()
                if ext not in TEXT_EXTENSIONS:
                    continue
                full = os.path.join(dirpath, fn)
                key = os.path.normcase(full)
                if key in seen:
                    continue
                seen.add(key)
                try:
                    st = os.stat(full)
                    size, mtime = int(st.st_size), float(st.st_mtime)
                except OSError:
                    size, mtime = -1, 0.0
                stem = os.path.splitext(fn)[0]
                entries.append(
                    {
                        "path": os.path.abspath(full),
                        "name": fn,
                        "stem": stem,
                        "norm_stem": normalize(stem),
                        "suffix_stem": strip_suffix_words(stem),
                        "dir": dirpath,
                        "ext": ext,
                        "size": size,
                        "mtime": mtime,
                    }
                )
    return entries


def build_index(
    roots: Optional[Sequence[str]] = None,
    extra_dirs: Any = None,
    refresh: bool = False,
) -> List[Dict[str, Any]]:
    """建立（或取缓存）触发词文本索引。"""
    root_list = list(roots) if roots is not None else get_lora_roots()
    dirs = list(root_list) + _split_dirs(extra_dirs)
    key = tuple(os.path.normcase(d) for d in dirs)
    if not refresh:
        cached = _CACHE.get(key)
        if cached is not None:
            return list(cached)
    entries = collect_text_files(dirs)
    _CACHE.put(key, entries)
    return list(entries)


def clear_index_cache() -> None:
    """清空索引缓存（HTTP 接口 `?refresh=1` 会调用）。"""
    _CACHE.clear()


def text_index_fingerprint(extra_dirs: Any = None, refresh: bool = False) -> str:
    """给 ``IS_CHANGED`` 用：所有触发词文本文件的"整体指纹"。

    自动检测模式下节点事先并不知道会读哪个 LoRA（要等 ComfyUI 把工作流传进来），
    所以这里用**整个文本索引**的 数量|总字节|最新修改时间 作为指纹：
    任何触发词文本被改动，指纹就会变，ComfyUI 会重新执行本节点，不会吃到旧文本。
    索引本身有 TTL 缓存，代价很小。
    """
    try:
        entries = build_index(extra_dirs=extra_dirs, refresh=refresh)
    except Exception:
        return "fallback"
    if not entries:
        return "empty"
    total = 0
    newest = 0.0
    for entry in entries:
        try:
            total += int(entry.get("size") or 0)
        except (TypeError, ValueError):
            pass
        try:
            newest = max(newest, float(entry.get("mtime") or 0.0))
        except (TypeError, ValueError):
            pass
    return f"{len(entries)}|{total}|{int(newest)}"


def match_text_entry(
    lora_name: str,
    entries: Sequence[Dict[str, Any]],
    all_lora_names: Optional[Sequence[str]] = None,
    lora_path: Optional[str] = None,
    top_n: int = 3,
) -> Tuple[Optional[Dict[str, Any]], int, List[Tuple[int, Dict[str, Any]]]]:
    """在索引中为 `lora_name` 挑选最合适的触发词文本。

    返回 ``(最佳条目或 None, 最佳分数, 前 N 个候选 (分数, 条目))``。
    """
    lora_dir = os.path.dirname(lora_path) if lora_path else None
    other: List[str] = []
    if all_lora_names:
        base = os.path.basename(str(lora_name).replace("\\", "/"))
        stem = os.path.splitext(base)[0]
        self_norm = normalize(stem)
        other = [
            normalize(os.path.splitext(os.path.basename(str(n).replace("\\", "/")))[0])
            for n in all_lora_names
        ]
        other = [o for o in other if o and o != self_norm]

    scored: List[Tuple[int, Dict[str, Any]]] = []
    for entry in entries:
        s = score_entry(lora_name, entry, other, lora_dir)
        if s > 0:
            scored.append((s, entry))
    if not scored:
        return None, 0, []

    # 排序：分数 > 名字更短（更贴近 LoRA 名） > 路径更短
    scored.sort(key=lambda x: (-x[0], len(x[1].get("stem", "")), len(x[1].get("path", ""))))
    best_score, best = scored[0]
    if best_score < MIN_ACCEPT_SCORE:
        return None, best_score, scored[:top_n]
    return best, best_score, scored[:top_n]


# --------------------------------------------------------------------------------------
# 文本读取与格式化
# --------------------------------------------------------------------------------------


def _bom_encoding(raw: bytes) -> Optional[str]:
    """按 BOM 猜测编码。"""
    if raw.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    if raw.startswith(codecs.BOM_UTF32_LE) or raw.startswith(codecs.BOM_UTF32_BE):
        return "utf-32"
    if raw.startswith(codecs.BOM_UTF16_LE) or raw.startswith(codecs.BOM_UTF16_BE):
        return "utf-16"
    return None


def read_text(path: str, max_bytes: int = MAX_FILE_BYTES) -> Tuple[str, str, bool]:
    """读取文本文件。

    返回 ``(内容, 实际使用的编码, 是否被截断)``。
    编码探测顺序：BOM > utf-8 > gb18030(GBK 超集) > utf-16 > latin-1（永不失败）。
    """
    with open(path, "rb") as f:
        raw = f.read(max_bytes + 1)
    truncated = len(raw) > max_bytes
    if truncated:
        raw = raw[:max_bytes]

    candidates: List[str] = []
    bom = _bom_encoding(raw)
    if bom:
        candidates.append(bom)
    candidates.extend(["utf-8", "gb18030", "utf-16", "latin-1"])

    tried: set = set()
    for enc in candidates:
        if enc in tried:
            continue
        tried.add(enc)
        try:
            return raw.decode(enc), enc, truncated
        except (UnicodeDecodeError, LookupError):
            continue
    # 理论上 latin-1 不会失败，这里只是兜底
    return raw.decode("utf-8", errors="replace"), "utf-8/replace", truncated


def split_trigger_lines(
    raw: str,
    deduplicate: bool = True,
    strip_comments: bool = True,
) -> List[str]:
    """把原始触发词文本整理成"干净的片段列表"。

    - 按行切分，丢弃空行；
    - 丢弃 `#` / `//` / `--` 开头的注释行；
    - 去掉每行末尾多余的 `,` `，` `;` `；` `、`；
    - 可选按整行去重（忽略大小写，保留首次出现的顺序）。
    """
    if raw is None:
        return []
    text = str(raw).replace("\r\n", "\n").replace("\r", "\n")
    out: List[str] = []
    seen: set = set()
    for line in text.split("\n"):
        s = line.strip()
        if not s:
            continue
        if strip_comments and s.startswith(_COMMENT_PREFIXES):
            continue
        s = _LINE_TAIL_RE.sub("", s).strip()
        if not s:
            continue
        if strip_comments and s.startswith(_COMMENT_PREFIXES):
            continue
        key = s.casefold()
        if deduplicate:
            if key in seen:
                continue
            seen.add(key)
        out.append(s)
    return out


def format_trigger_text(
    raw: str,
    separator: str = ", ",
    deduplicate: bool = True,
    strip_comments: bool = True,
) -> str:
    """把触发词文本整理成一行字符串（内部按整行去重，再用 `separator` 连接）。"""
    if isinstance(separator, str) and separator == "\\n":
        separator = "\n"
    return str(separator).join(split_trigger_lines(raw, deduplicate, strip_comments))


def parse_lora_text(raw: str, known_names: Optional[Sequence[str]] = None) -> List[str]:
    """解析"多 LoRA"输入。

    规则：

    1. 一行一个 LoRA；`#` `//` `--` 开头的行整行忽略，行尾 `# 备注` 也会被去掉；
    2. 每行去掉首尾空白、包裹的引号、多余的 `,` `，` `;` `；`；
    3. 若某行按 `,` `，` `;` `；` 切开后**每一段都能对上已知 LoRA 列表**
       （例如 `a.safetensors, b.safetensors`），则自动拆成多个；
       反之整行当一个名字（LoRA 文件名里极少出现逗号）；
    4. 传入 `known_names`（ComfyUI 的 LoRA 列表）时还会做**名字补全**：
       只写 `妃咲` 或 `妃咲.safetensors` 也能自动补成完整的
       `Krea2/Krea2角色lora/妃咲.safetensors`；若同名候选多于一个则保持原样。

    注意：不传 `known_names` 时不做逗号拆分（无法判断逗号是名字的一部分还是分隔符），
    此时请一行写一个 LoRA。返回列表已按大小写不敏感去重，并保持书写顺序。
    """
    if not raw:
        return []

    # ---- 已知 LoRA 索引（用于拆分判断 + 名字补全） --------------------------------
    full_map: Dict[str, str] = {}
    base_map: Dict[str, str] = {}
    stem_map: Dict[str, List[str]] = {}
    for item in known_names or []:
        s = str(item)
        rel = s.replace("\\", "/")
        base = os.path.basename(rel)
        stem = os.path.splitext(base)[0]
        full_map.setdefault(normalize(rel), s)
        base_map.setdefault(normalize(base), s)
        stem_map.setdefault(normalize(stem), []).append(s)

    def canonical(name: str) -> str:
        """把用户写的名字尽量补全成 ComfyUI 里的完整相对路径。"""
        if not full_map:
            return name
        rel = str(name).replace("\\", "/")
        norm_full = normalize(rel)
        if norm_full in full_map:
            return full_map[norm_full]
        norm_base = normalize(os.path.basename(rel))
        if norm_base in base_map:
            return base_map[norm_base]
        hits = stem_map.get(os.path.splitext(norm_base)[0]) or []
        if len(hits) == 1:
            return hits[0]
        return name

    def is_known(name: str) -> bool:
        if not full_map:
            return False
        rel = str(name).replace("\\", "/")
        if normalize(rel) in full_map or normalize(os.path.basename(rel)) in base_map:
            return True
        hits = stem_map.get(os.path.splitext(normalize(os.path.basename(rel)))[0]) or []
        return len(hits) == 1

    text = str(raw).replace("\r\n", "\n").replace("\r", "\n")
    result: List[str] = []
    seen: set = set()

    def push(name: str) -> None:
        name = str(name).strip().strip('"').strip("'").strip()
        name = name.rstrip(",，;；、").strip()
        if not name or name.startswith(_COMMENT_PREFIXES):
            return
        name = canonical(name)
        key = os.path.normcase(name.replace("\\", "/"))
        if key in seen:
            return
        seen.add(key)
        result.append(name)

    for line in text.split("\n"):
        line = line.strip()
        if not line or line.startswith(_COMMENT_PREFIXES):
            continue
        # 行尾注释（" # 备注"）
        if " #" in line:
            line = line.split(" #", 1)[0].strip()
        if not line:
            continue
        tokens = [t for t in re.split(r"[,，;；]+", line) if t.strip()]
        if len(tokens) > 1 and full_map and all(is_known(t) for t in tokens):
            for t in tokens:
                push(t)
        else:
            push(line)
    return result


# --------------------------------------------------------------------------------------
# 对外主流程
# --------------------------------------------------------------------------------------


def _rel_to_roots(path: Optional[str], roots: Sequence[str]) -> Optional[str]:
    """把绝对路径转成相对某个 LoRA 根目录的相对路径（越短越好），失败返回 None。"""
    if not path:
        return None
    best: Optional[str] = None
    p = os.path.normcase(os.path.abspath(path))
    for root in roots:
        r = os.path.normcase(os.path.abspath(root))
        if p.startswith(r + os.sep):
            rel = os.path.relpath(path, root).replace("\\", "/")
            if best is None or len(rel) < len(best):
                best = rel
    return best


def resolve_lora(
    lora_name: str,
    separator: str = ", ",
    deduplicate: bool = True,
    strip_comments: bool = True,
    entries: Optional[Sequence[Dict[str, Any]]] = None,
    roots: Optional[Sequence[str]] = None,
    extra_dirs: Any = None,
    all_lora_names: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """解析单个 LoRA：定位文件 -> 找触发词文本 -> 读取并格式化。

    返回字典字段：

    ``name, lora_path, trigger_file, trigger_rel, status, text, raw, chars,
    encoding, truncated, score, error, candidates``

    `status` 取值：``ok`` / ``empty``（有文本文件但内容为空） / ``no_trigger`` /
    ``no_lora`` / ``error``。
    """
    result: Dict[str, Any] = {
        "name": str(lora_name or ""),
        "lora_path": None,
        "trigger_file": None,
        "trigger_rel": None,
        "status": "error",
        "text": "",
        "raw": "",
        "lines": [],
        "chars": 0,
        "encoding": "",
        "truncated": False,
        "score": 0,
        "error": "",
        "candidates": [],
    }
    if not lora_name:
        result["status"] = "no_lora"
        result["error"] = "lora_name 为空"
        return result

    root_list = list(roots) if roots is not None else get_lora_roots()
    try:
        lora_path = get_lora_full_path(str(lora_name), root_list)
    except Exception as exc:  # pragma: no cover
        lora_path = None
        result["error"] = f"解析 LoRA 路径失败: {exc}"
    result["lora_path"] = lora_path

    if entries is None:
        entries = build_index(root_list, extra_dirs=extra_dirs)
    names = all_lora_names if all_lora_names is not None else list_lora_names()

    entry, score, candidates = match_text_entry(str(lora_name), entries, names, lora_path)
    result["score"] = int(score)
    result["candidates"] = [
        {"score": int(s), "file": e.get("path"), "name": e.get("name")} for s, e in candidates
    ]

    if entry is None:
        result["status"] = "no_lora" if lora_path is None else "no_trigger"
        if lora_path is None:
            result["error"] = "在 LoRA 目录中找不到该 LoRA 文件"
        return result

    result["trigger_file"] = entry.get("path")
    result["trigger_rel"] = _rel_to_roots(entry.get("path"), root_list) or entry.get("name")
    try:
        raw, encoding, truncated = read_text(str(entry["path"]))
    except Exception as exc:
        result["status"] = "error"
        result["error"] = f"读取文本失败: {exc}"
        return result

    result["raw"] = raw
    result["encoding"] = encoding
    result["truncated"] = bool(truncated)
    result["lines"] = split_trigger_lines(raw, deduplicate, strip_comments)
    result["text"] = format_trigger_text(raw, separator, deduplicate, strip_comments)
    result["chars"] = len(result["text"])
    result["status"] = "ok" if result["text"] else "empty"
    return result


def resolve_loras(
    names: Sequence[str],
    separator: str = ", ",
    deduplicate: bool = True,
    strip_comments: bool = True,
    skip_empty: bool = True,
    roots: Optional[Sequence[str]] = None,
    extra_dirs: Any = None,
    all_lora_names: Optional[Sequence[str]] = None,
    on_missing: str = "empty",
    fallback_text: str = "",
) -> Tuple[str, str, List[Dict[str, Any]]]:
    """批量解析多个 LoRA。

    返回 ``(合并后的触发词文本, 人类可读报告, 每个 LoRA 的解析结果列表)``。
    合并时对整行做去重（可选），并保持输入顺序。
    `on_missing` 与 `fallback_text` 含义同 :func:`resolve_with_fallback`，
    用于在没有触发词文本时补上兜底内容。
    每个结果里会多一个 ``out_text`` 字段（该 LoRA 最终贡献的文本）。
    """
    root_list = list(roots) if roots is not None else get_lora_roots()
    entries = build_index(root_list, extra_dirs=extra_dirs)
    lora_names = list(all_lora_names) if all_lora_names is not None else list_lora_names()

    results: List[Dict[str, Any]] = []
    merged: List[str] = []
    seen: set = set()
    for name in names:
        res = resolve_lora(
            name,
            separator=separator,
            deduplicate=deduplicate,
            strip_comments=strip_comments,
            entries=entries,
            roots=root_list,
            extra_dirs=extra_dirs,
            all_lora_names=lora_names,
        )
        pieces: List[str] = list(res.get("lines") or [])
        if not pieces:
            fb = resolve_with_fallback(res, on_missing, fallback_text)
            if fb:
                pieces = split_trigger_lines(fb, deduplicate, False)
                res["fallback_used"] = True
        for piece in pieces:
            piece = str(piece).strip()
            if not piece:
                continue
            key = piece.casefold()
            if deduplicate and key in seen:
                continue
            seen.add(key)
            merged.append(piece)
        res["out_text"] = format_trigger_text("\n".join(pieces), separator, deduplicate, False) if pieces else ""
        results.append(res)

    sep = "\n" if separator == "\\n" else str(separator)
    return sep.join(merged), build_report(results), results


def build_report(results: Sequence[Dict[str, Any]], max_items: int = 200) -> str:
    """生成一段便于在节点里查看的解析报告（纯文本，多行）。"""
    total = len(results)
    fallback = sum(1 for r in results if r.get("fallback_used"))
    ok = sum(1 for r in results if r.get("status") == "ok" and not r.get("fallback_used"))
    empty = sum(1 for r in results if r.get("status") == "empty" and not r.get("fallback_used"))
    missing = sum(1 for r in results if r.get("status") == "no_trigger" and not r.get("fallback_used"))
    nofile = sum(1 for r in results if r.get("status") == "no_lora" and not r.get("fallback_used"))
    failed = total - ok - empty - missing - nofile - fallback

    parts = [
        f"共 {total} 个 LoRA",
        f"有触发词 {ok}",
        f"空文件 {empty}",
        f"未匹配 {missing}",
    ]
    if nofile:
        parts.append(f"找不到文件 {nofile}")
    if fallback:
        parts.append(f"兜底 {fallback}")
    if failed:
        parts.append(f"异常 {failed}")

    lines = [
        f"LoRATriggerReader v{VERSION}",
        " | ".join(parts),
    ]
    for idx, r in enumerate(results[:max_items], 1):
        status = r.get("status")
        name = os.path.basename(str(r.get("name", "")))
        if r.get("fallback_used"):
            lines.append(f"[{idx}] {name} -> 无触发词，已使用兜底文本: {r.get('out_text')}")
        elif status == "ok":
            lines.append(
                f"[{idx}] {name} -> {r.get('trigger_rel')} "
                f"({r.get('chars')} 字/{r.get('encoding')}{'/截断' if r.get('truncated') else ''}, 分数 {r.get('score')})"
            )
        elif status == "empty":
            lines.append(f"[{idx}] {name} -> {r.get('trigger_rel')} (文件存在但内容为空)")
        elif status == "no_trigger":
            lines.append(f"[{idx}] {name} -> 未找到同名/含名的触发词文本")
        elif status == "no_lora":
            lines.append(f"[{idx}] {name} -> 找不到该 LoRA 文件")
        else:
            lines.append(f"[{idx}] {name} -> 异常: {r.get('error')}")
    if len(results) > max_items:
        lines.append(f"... 其余 {len(results) - max_items} 个省略")
    return "\n".join(lines)


def resolve_with_fallback(
    res: Dict[str, Any],
    on_missing: str = "empty",
    fallback_text: str = "",
) -> str:
    """按 `on_missing` 策略给出最终文本。"""
    text = str(res.get("text") or "")
    if text:
        return text
    mode = str(on_missing or "empty").strip().lower()
    if mode == "lora_name":
        base = os.path.basename(str(res.get("name", "")).replace("\\", "/"))
        return os.path.splitext(base)[0]
    if mode == "custom":
        return str(fallback_text or "")
    return ""


__all__ = [
    "VERSION",
    "TEXT_EXTENSIONS",
    "MAX_FILE_BYTES",
    "build_index",
    "build_report",
    "clear_index_cache",
    "collect_text_files",
    "format_trigger_text",
    "get_lora_full_path",
    "get_lora_roots",
    "has_folder_paths",
    "list_lora_names",
    "match_text_entry",
    "normalize",
    "parse_lora_text",
    "resolve_lora",
    "resolve_loras",
    "resolve_with_fallback",
    "score_entry",
    "split_trigger_lines",
    "strip_suffix_words",
    "text_index_fingerprint",
]
