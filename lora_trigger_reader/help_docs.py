# -*- coding: utf-8 -*-
"""节点使用说明（中英双语）—— ComfyUI 里点节点上的「❓ 使用说明」按钮就能看到。

内容有三份来源，互为补充，都能在 ComfyUI 界面里直接看到：

1. ``DESCRIPTION``（Python 类属性）—— 鼠标悬停在节点上时的提示，中英双语；
2. 每个输入/输出端口的 ``tooltip`` / ``OUTPUT_TOOLTIPS`` —— 悬停端口时的提示，中英双语；
3. **本模块**里更长的完整说明（配合 ``GET /lora_trigger_reader/help`` 接口 + 前端弹窗）。

这里只放纯文本（用 ``【标题】`` 分段），前端弹窗里按等宽字体原样显示，
不需要 Markdown 渲染器，任何版本的 ComfyUI 前端都能正常看。
"""

from __future__ import annotations

from typing import Any, Dict, List

#: 节点显示顺序（帮助面板左侧列表用）
NODE_ORDER: List[str] = [
    "LoRAMultiLoader",
    "LoRATriggerReader",
    "LoRATriggerReaderMulti",
    "LoRATriggerReaderInfo",
]

#: 帮助面板里显示的标题
TITLES: Dict[str, Dict[str, str]] = {
    "LoRAMultiLoader": {
        "zh": "多重 LoRA 加载器（LoRA Multi Loader）",
        "en": "LoRA Multi Loader",
    },
    "LoRATriggerReader": {
        "zh": "LoRA 触发词读取·自动（最近一个）",
        "en": "LoRA Trigger Reader (auto, nearest)",
    },
    "LoRATriggerReaderMulti": {
        "zh": "LoRA 触发词读取·自动多选（全部）",
        "en": "LoRA Trigger Reader Multi (auto, all)",
    },
    "LoRATriggerReaderInfo": {
        "zh": "LoRA 触发词查看（手动选择）",
        "en": "LoRA Trigger Info (manual pick)",
    },
    "common": {
        "zh": "通用说明：触发词文本怎么找、参数、常见问题",
        "en": "General: how trigger files are found, parameters, FAQ",
    },
    "help": {
        "zh": "帮助面板",
        "en": "Help panel",
    },
}

_COMMON_ZH = """【这个插件干什么】
LoRA 的触发词（trigger words）通常写在 loras 目录里一个同名的 .txt / .md 里。
本插件把它自动读出来，变成工作流里可以直接连的 STRING，
这样接了 LoRA 之后就不用手动去复制粘贴触发词了。

【触发词文本怎么找】
在 ComfyUI 的所有 LoRA 根目录（含 extra_model_paths.yaml 里的多路径）里搜索
扩展名为 .txt / .md 的文件，然后和 LoRA 的名字（含子目录）比对：

  1000 分  文件名（不含扩展名）与 LoRA 名完全相同
   980 分  去掉分隔符后完全相同（忽略空格、下划线、连字符、点、顿号、逗号）
   950 分  LoRA 名 + 常见后缀词（触发词 / 提示词 / 关键词 / 说明 / 备注 /
           trigger / triggerword / triggers / prompt / prompts / keyword /
           words / tags / info / note / notes / readme / read ...）
   900 分  文本文件名里包含 LoRA 的完整名字
   850 分  去掉分隔符后包含 LoRA 的名字
   800 分  LoRA 名字里包含文本文件名（要求名字足够长，防止 A.txt 抢走 ghost_a）
 600-690  模糊匹配（相似度 >= 0.90，可用常量关闭）
   +25    同一个目录里的额外加分
     0    不是这个 LoRA 的触发词文件
   <700   不采用（例如只有一两个字符的文件名）

保护规则（避免误匹配）：
  * 短名字不参与"包含"类匹配：名字至少 4 个字符，中文至少 2 个字；
  * 同一个文本文件如果明显属于另一个更匹配的 LoRA，就不会被本 LoRA 抢走；
  * 结果里带分数，节点报告里能看到命中了哪个文件、多少分。

【触发词文本本身怎么处理】
  * 编码：先看 BOM（UTF-8-sig / UTF-16 / UTF-32），再依次尝试
    UTF-8 -> GB18030（含 GBK）-> UTF-16 -> Latin-1（永不失败），
    最坏情况用 UTF-8 + replace 兜底，不会因为编码问题报错；
  * 空文件 / 只有空白：算"空文件"，按 on_missing 处理；
  * 注释行：以 #、//、-- 开头的整行忽略；
  * 行尾的逗号、分号、顿号会被去掉，避免拼出 "a,b,," 这种结果；
  * 单文件最多读 1 MiB，超出截断并在报告里标注；
  * separator 填 \\n（反斜杠 n）表示换行输出；
  * deduplicate 按整行去重（忽略大小写）。

【参数（所有节点通用）】
  separator     多条触发词之间的连接符，默认 ", "
  deduplicate   整行去重，默认 true
  strip_comments 忽略 #、//、-- 注释行，默认 true
  on_missing    没有触发词文本时怎么办：
                  empty     输出空字符串（默认）
                  lora_name 输出 LoRA 文件名（很多人拿文件名当触发词）
                  custom    输出 fallback_text 里的内容
  fallback_text on_missing = custom 时用的兜底文本
  extra_dirs    额外扫描的目录（多个用 ; 或换行分隔），留空即可
  refresh_cache 勾选后本次强制重新扫描（默认走 8 秒缓存，速度更快）

【report 输出长什么样】
  LoRATriggerReader v1.3.0
  [接入链路] 检测到 #3 LoraLoader -> Krea2/Krea2角色lora/妃咲.safetensors
  共 1 个 LoRA | 有触发词 1 | 空文件 0 | 未匹配 0
  [1] 妃咲.safetensors -> 妃咲.txt (290 字/utf-8, 分数 1005)

【前端小功能】
  * 节点上的「❓ 使用说明 / Help」按钮：打开本说明（可切中英文）；
  * 「🎯 ...」按钮：打开触发词选择器，可以搜索、预览、按状态筛选，
    一键把 LoRA 名单写回节点（单选节点写 lora_name / 自动节点写 extra_loras /
    加载器写进 4 行下拉框，多出来的写进 (高级) 批量文本）；
  * 「🔄 重新扫描」按钮：清掉前端缓存与链路检测结果，立刻重新扫描；
  * 自动节点底部会实时显示「🔎 检测到 N 个 LoRA: ...」，接线换 LoRA 立刻跟着变。

【常见问题】
  * 节点里一个 LoRA 都没检测到？
      - 自动节点要求 MODEL 线真的连到本节点，且链路上有 LoraLoader 之类的节点；
      - 如果 LoRA 是在子工作流 / 第三方节点里加载的，用 extra_loras（自动节点）
        或下拉框（加载器）手动选上即可。
  * 报告说"没有读到任何 LoRA"？同上，或者 LoRA 名字写错了（可只写文件名）。
  * 状态行显示「检测到 1 个 LoRA: [object Object]」？
      - 这是第三方 LoRA 节点把结构化值塞进控件导致的（例如 rgthree 的 Power Lora
        Loader，一个输入里存 {"on": true, "lora": "x.safetensors", "strength": 0.8}）；
      - v1.3 起前端与后端都会按字段名（lora / name / value / path …）解析这种值，
        并跳过 on / strength 之类的开关与权重字段，所以只会显示真实文件名；
        刷新页面（或重启 ComfyUI）后生效。
  * 触发词没读出来？
      - 确认文本文件在 loras 目录下（或写进 extra_dirs）；
      - 确认文件名带上了 LoRA 的名字（例如 妃咲.txt、妃咲提示词.txt）；
      - 看 report 里的分数与文件名，分数 < 700 表示没被采用。
  * 想放到 LoRA 目录外面？把目录写进 extra_dirs。
  * 加载器改了强度要不要重新读盘？不用，同一个文件在缓存里直接用（最多缓存 4 个）。
"""

_COMMON_EN = """【What this plugin does】
Trigger words for a LoRA normally live in a .txt / .md file with a matching name
inside your loras folder. This plugin reads that text and exposes it as a STRING
socket, so you never have to copy-paste trigger words again.

【How the trigger file is found】
All ComfyUI LoRA roots are searched (including extra_model_paths.yaml entries)
for .txt / .md files, and every file name is compared against the LoRA name
(including sub-folders):

  1000 pts  file stem equals the LoRA name
   980 pts  equal after removing separators (space, _ - . , 、)
   950 pts  LoRA name + a common suffix word (trigger / triggerword / triggers /
            prompt / prompts / keyword / words / tags / info / note / notes /
            readme / read ... plus the Chinese equivalents)
   900 pts  the file name contains the full LoRA name
   850 pts  contains the LoRA name after removing separators
   800 pts  the LoRA name contains the file stem (name must be long enough,
            so A.txt can never hijack ghost_a.safetensors)
 600-690   fuzzy match (ratio >= 0.90, can be disabled with a constant)
   +25      bonus for living in the same folder as the LoRA
     0      not a trigger file for this LoRA
   <700    rejected (e.g. a one or two character file stem)

Protection rules (avoid wrong matches):
  * short names never take part in "contains" matches: at least 4 characters,
    or at least 2 CJK characters;
  * a text file that clearly belongs to a better matching LoRA is not stolen;
  * every result carries a score, shown in the node report.

【Text processing】
  * Encoding: BOM detection first (UTF-8-sig / UTF-16 / UTF-32), then
    UTF-8 -> GB18030 (a GBK superset) -> UTF-16 -> Latin-1 (never fails);
    worst case UTF-8 + errors="replace", so you never get an exception;
  * empty or whitespace-only file = "empty file", handled by on_missing;
  * whole-line comments starting with #, // or -- are ignored;
  * trailing commas / semicolons / enumeration marks are trimmed;
  * at most 1 MiB per file (truncated, and the report says so);
  * separator = \\n (backslash n) prints line breaks;
  * deduplicate removes repeated lines (case-insensitive).

【Parameters (shared by every node)】
  separator       joiner between trigger words, default ", "
  deduplicate     drop repeated lines, default true
  strip_comments  ignore #, //, -- comment lines, default true
  on_missing      what to output when there is no trigger file:
                    empty     empty string (default)
                    lora_name the LoRA file name (many people use it as trigger)
                    custom    the text in fallback_text
  fallback_text   used when on_missing = custom
  extra_dirs      extra folders to scan (separate with ; or newlines)
  refresh_cache   force a rescan for this run (otherwise an 8 second cache is used)

【What the report looks like】
  LoRATriggerReader v1.3.0
  [接入链路] 检测到 #3 LoraLoader -> Krea2/Krea2角色lora/妃咲.safetensors
  共 1 个 LoRA | 有触发词 1 | 空文件 0 | 未匹配 0
  [1] 妃咲.safetensors -> 妃咲.txt (290 字/utf-8, 分数 1005)

【Frontend extras】
  * "❓ 使用说明 / Help" button on every node: opens this documentation
    (Chinese / English tabs);
  * "🎯 ..." button: opens the trigger-word picker (search, preview, filter by
    status) and writes the selection back into the node (lora_name for the info
    node, extra_loras for the auto nodes, the four dropdown rows for the loader,
    with any overflow going into the "(advanced) batch text" box);
  * "🔄 重新扫描" button: clears frontend caches and re-detects the model chain;
  * the auto nodes draw "🔎 检测到 N 个 LoRA: ..." at the bottom, updating as
    soon as you rewire the graph.

【FAQ】
  * No LoRA detected?
      - the auto nodes need the MODEL link connected to this node, with a
        LoraLoader-style node upstream;
      - if the LoRA is loaded inside a subgraph or a third-party node, fill in
        extra_loras (auto nodes) or pick it in the dropdown (loader) manually.
  * Report says "没有读到任何 LoRA"? Same as above, or the name is wrong
    (you may write just the file name).
  * Status line shows "检测到 1 个 LoRA: [object Object]"?
      - that happens when a third-party LoRA node stores a structured value in
        its widget (e.g. rgthree's Power Lora Loader holds
        {"on": true, "lora": "x.safetensors", "strength": 0.8});
      - since v1.3 the frontend and the backend both parse such values by field
        name (lora / name / value / path ...) and skip booleans / weights
        (on, strength, ...), so only the real file name is shown -- refresh the
        page (or restart ComfyUI) to pick it up.
  * No trigger words?
      - make sure the text file lives under a loras root (or add extra_dirs);
      - make sure the file name contains the LoRA name (e.g. 妃咲.txt);
      - check the score in the report: below 700 means it was rejected.
  * Want to keep text files outside the LoRA folder? Add the folder to extra_dirs.
  * Does changing the strength reload the file? No, up to 4 LoRAs are cached in
    memory and reused.
"""

_LOADER_ZH = """【作用】
把 MODEL + CLIP 各接一个 LoRA 加载器该干的事，合成一个节点做完：
用 4 行下拉框选 LoRA（每行各有独立的 MODEL 强度 / CLIP 强度），节点按顺序把它们
加载到 MODEL 和 CLIP 上，同时把每个 LoRA 的触发词读出来合并成一行输出。
适合"一次接三四个 LoRA"的工作流，能少摆好几个 LoraLoader。

【输入】
  lora_1 … lora_4        （下拉框）每行选一个 LoRA；第一项「不使用 / none」= 这一行不加载。
                          下拉框里列出 LoRA 目录（含子目录）里的所有文件。
  strength_1 … 4         （MODEL 强度，浮点数）这一行 LoRA 叠加到 MODEL 上的强度，默认 1.0。
  clip_strength_1 … 4    （CLIP 强度，浮点数）叠加到 CLIP 上的强度，默认 1.0。
                          和 MODEL 是分开的两个框（和内置 LoraLoader 一样）；想让两边一样，
                          就把两个框改成同一个数。
                          两个强度框都可以：① 点数字框左右的小箭头，每次 ±0.1；
                          ② 直接用键盘输入数字。范围 [-100, 100]，超出会被夹住并在报告里说明。
                          1.0 = 原样、0 = 不生效、负数 = 反向。
  lora_list  （可选，(高级) 批量文本）一次贴一大批（超过 4 个）时用，一行一个：
             name.safetensors                 强度都用 1.0
             name.safetensors: 0.8            model 和 clip 都用 0.8
             name.safetensors: 0.8, 0.5       model 0.8 / clip 0.5
             name.safetensors @ 0.8           用 @ 代替冒号
             name.safetensors, 0.8            逗号写法
             a.safetensors 0.8                空格写法（前面确实像个 LoRA 时才这么切）
             <lora:name.safetensors:0.8>      A1111 风格的写法也能认
             a.safetensors, b.safetensors     一行写两个（不带强度）
             妃咲                             只写文件名也行，会自动补全成
                                               Krea2/Krea2角色lora/妃咲.safetensors
             # 注释行 / 行尾 "# 备注"          会被忽略
             强度范围 [-100, 100]，超出会自动夹住并在报告里说明；
             最多 64 个；同一个 LoRA 写两行会加载两次（效果叠加）。
             加载顺序：先下拉框第 1 → 4 行，再这个文本框里的。
  model      （可选，MODEL）接上一个模型就会把 LoRA 叠加到这个模型上。
  clip       （可选，CLIP）接上 CLIP 就会把 LoRA 同时叠加到 CLIP 上；
             两个口都接 = 和 LoraLoader 一样，两个口都不接 = 只读触发词。
  separator / deduplicate / strip_comments / on_missing / fallback_text /
  extra_dirs / refresh_cache   通用参数，见「通用说明」。

【输出】
  model         叠加了全部 LoRA 之后的 MODEL（没接 model 就是空）
  clip          叠加了全部 LoRA 之后的 CLIP（没接 clip 就是空）
  trigger_words 这些 LoRA 的触发词合并成的一行，直接连给 CLIPTextEncode
  report        加载详情 + 每个 LoRA 的触发词命中情况（连 Show Text 看）

【接线示例】
  CheckpointLoaderSimple.model -> LoRAMultiLoader.model -> KSampler.model
  CheckpointLoaderSimple.clip  -> LoRAMultiLoader.clip  -> CLIPTextEncode.clip
  LoRAMultiLoader.trigger_words -> CLIPTextEncode.text
  （想让触发词单独成一个节点输出，见「LoRA 触发词读取」两个节点。）

【下拉框和批量文本都为空时】
节点会退回到"自动检测"：顺着 model 连线往上游走，把链路上所有 LoRA
按"离 Checkpoint 由远到近"的顺序加载（也就是真实的模型流向顺序），
并在报告里写明是自动检测来的。只要下拉框或批量文本框里写了 LoRA，就以你写的为准。

【报告示例】
  LoRATriggerReader v1.3.0
  [多重加载器] 已加载 2 个 LoRA：妃咲.safetensors(0.8), silver_wolf(1)
  共 2 个 LoRA | 有触发词 2 | 空文件 0 | 未匹配 0
  [1] 妃咲.safetensors -> 妃咲.txt (290 字/utf-8, 分数 1005)
  [2] silver_wolf...safetensors -> ...提示词.txt (89 字/utf-8, 分数 975)

【注意】
  * 和内置 LoraLoader 一样：LoRA 是叠加（add_patches）而不是替换模型，
    所以本节点可以直接插在原有的模型链路上，不会破坏上游的 LoRA；
  * 找不到文件 / 读取失败只会在报告里报警告，工作流不会崩；
  * 强度为 0 的 LoRA 仍会被加载（和内置 LoraLoader 的短路行为略有不同），
    想跳过就把它注释掉、或者把下拉框改回「不使用 / none」；
  * 文件读取带缓存（最多 4 个），反复执行时只有第一个 LoRA 会读盘；
  * 从 v1.2 升级上来：v1.2 是"在 lora_list 文本框里写名字"，v1.3 改成了下拉框，
    旧工作流里已经写好的 lora_list 内容不会被删、仍然会被加载，但下拉框需要重新选一次。
"""

_LOADER_EN = """【Purpose】
Does the job of several LoraLoader nodes at once: pick LoRAs in four dropdown
rows (each row has its own MODEL strength and CLIP strength), and the node
applies them to MODEL and CLIP in order while also reading their trigger words
and merging them into a single line.

【Inputs】
  lora_1 … lora_4        (dropdowns) one LoRA per row; the first entry
                         "不使用 / none" means this row loads nothing.
  strength_1 … 4         (MODEL strength, float) how strongly that row's LoRA is
                         patched into MODEL, default 1.0.
  clip_strength_1 … 4    (CLIP strength, float) the matching strength for CLIP,
                         default 1.0 - a separate box, just like the built-in
                         LoraLoader. Set both boxes to the same value if you want
                         them equal.
                         Both strength boxes accept: (1) the small left/right
                         arrows, which step by 0.1, and (2) typing a number.
                         Range [-100, 100]; out-of-range values are clamped and
                         reported. 1.0 = unchanged, 0 = no effect, negative =
                         inverted.
  lora_list  (optional, "(advanced) batch text") for pasting many LoRAs (>4) at
             once, one per line:
             name.safetensors                 both strengths = 1.0
             name.safetensors: 0.8            model and clip both 0.8
             name.safetensors: 0.8, 0.5       model 0.8 / clip 0.5
             name.safetensors @ 0.8           @ works like the colon
             name.safetensors, 0.8            comma form
             a.safetensors 0.8                space form (only split when the
                                              left side really looks like a LoRA)
             <lora:name.safetensors:0.8>      A1111 style is understood too
             a.safetensors, b.safetensors     two names on one line
             妃咲                             file name only is fine, it is
                                              completed to the full relative path
             # comment / trailing "# note"    ignored
             Strength range is [-100, 100]; out-of-range values are clamped and
             reported. At most 64 entries. The same LoRA written twice is
             applied twice (it stacks, exactly like two LoraLoader nodes).
             Order: dropdown rows 1 → 4 first, then this text box.
  model      (optional, MODEL) connect a model to patch it with the LoRAs.
  clip       (optional, CLIP) connect CLIP to patch it as well.
             Both connected = a LoraLoader; neither connected = read-only mode
             that only outputs trigger words.
  separator / deduplicate / strip_comments / on_missing / fallback_text /
  extra_dirs / refresh_cache   shared parameters, see the General help.

【Outputs】
  model         MODEL with every LoRA applied (None if model is unconnected)
  clip          CLIP with every LoRA applied (None if clip is unconnected)
  trigger_words one line with all trigger words, ready for CLIPTextEncode
  report        loading details plus per-LoRA trigger matching results

【Wiring example】
  CheckpointLoaderSimple.model -> LoRAMultiLoader.model -> KSampler.model
  CheckpointLoaderSimple.clip  -> LoRAMultiLoader.clip  -> CLIPTextEncode.clip
  LoRAMultiLoader.trigger_words -> CLIPTextEncode.text

【Empty dropdowns and batch box】
The node falls back to auto detection: it walks upstream along the model link
and applies every LoRA it finds in real model-flow order (farthest from the
checkpoint first). As soon as a dropdown row or the batch text box has a LoRA,
that wins over auto detection.

【Caveats】
  * LoRAs are additive patches, exactly like the built-in LoraLoader, so this
    node can be inserted into an existing model chain without breaking it;
  * a missing or unreadable file only produces a warning in the report, the
    workflow keeps running;
  * strength 0 still loads the file (unlike the built-in LoraLoader shortcut);
    comment the line out, or set the dropdown back to "不使用 / none";
  * LoRA files are cached (up to 4) so repeated runs only hit the disk once;
  * upgrading from v1.2: v1.2 wrote LoRAs in the lora_list text box, v1.3 uses
    dropdowns. An old workflow keeps its lora_list text (it is still loaded) but
    you have to pick the dropdown rows again.
"""

_SINGLE_ZH = """【作用】
接在 LoraLoader 之类的节点右边，自动读取**离本节点最近的那个 LoRA** 的触发词。
不用手动选 LoRA：上游换成别的 LoRA，这里输出的触发词自动跟着变。

【输入】
  model       （必填，MODEL）把 LoRA 链路的 MODEL 接到这里。节点不修改模型，
               只原样透传（所以它可以直接插在 KSampler 前面）。
  extra_loras （可选，多行文本）手动补充要读触发词的 LoRA，平时留空。
               链路上检测不到时（例如 LoRA 在子工作流里加载）才需要填。
               一行一个，也支持只写文件名。
  其它是通用参数，见「通用说明」。

【输出】
  model         原样透传的 MODEL
  trigger_words 最近那个 LoRA 的触发词，一行
  report        检测到了哪些 LoRA、命中了哪个文本文件、多少分

【和"自动多选"的区别】
  本节点只取最近的一个；要合并链路上全部 LoRA 请用
  「LoRA 触发词读取·自动多选 (LoRA Trigger Reader Multi)」。

【例子】
  CheckpointLoaderSimple -> LoraLoader(A) -> LoraLoader(B) -> 本节点
  结果：输出 B 的触发词（B 离本节点最近）。

【前端】
  节点底部会显示「🔎 检测到 N 个 LoRA: ...」；
  「🎯 手动补充 LoRA（触发词选择器）」把选择结果写进 extra_loras；
  「🔄 重新扫描链路 / LoRA 文本」清缓存并立刻重新检测。
"""

_SINGLE_EN = """【Purpose】
Plug it to the right of a LoraLoader-style node and it automatically reads the
trigger words of the nearest LoRA on that model chain. No manual selection:
swap the upstream LoRA and the output follows.

【Inputs】
  model       (required, MODEL) the LoRA chain's MODEL. The node never modifies
              the model, it passes it through, so it can sit right before KSampler.
  extra_loras (optional, multiline) manually add LoRA names to read, usually
              left empty. Needed only when the chain cannot be detected (for
              example a LoRA loaded inside a subgraph).
  the remaining parameters are shared, see the General help.

【Outputs】
  model         the same MODEL, passed through
  trigger_words the nearest LoRA's trigger words, one line
  report        which LoRAs were detected, which text file matched, its score

【Difference from the multi variant】
  This node takes only the nearest LoRA. Use
  "LoRA Trigger Reader Multi (auto, all)" to merge every LoRA on the chain.

【Example】
  CheckpointLoaderSimple -> LoraLoader(A) -> LoraLoader(B) -> this node
  Output: B's trigger words (B is nearest).

【Frontend】
  The node shows "🔎 检测到 N 个 LoRA: ..." at the bottom; the
  "🎯 手动补充 LoRA（触发词选择器）" button writes its selection into
  extra_loras; "🔄 重新扫描链路 / LoRA 文本" clears caches and re-detects.
"""

_MULTI_ZH = """【作用】
和「自动（最近一个）」一样顺着 model 连线反查，但读取链路上**全部 LoRA**
的触发词，按加载顺序合并成一行输出。串了几个 LoRA 就输出几个的触发词。

【输入】
  model       （必填，MODEL）LoRA 链路的 MODEL，原样透传。
  extra_loras （可选，多行文本）手动补充的 LoRA，一行一个，平时留空。
  其它是通用参数，见「通用说明」。

【输出】
  model         原样透传的 MODEL
  trigger_words 全部 LoRA 的触发词合并后的一行（按链路顺序，最近的排在前面）
  report        共几个 LoRA、有触发词几个、空文件几个、未匹配几个 + 逐条明细

【顺序】
  报告里的顺序 = 从本节点往上（最近的在前）。
  例如 Checkpoint -> LoraLoader(A) -> LoraLoader(B) -> 本节点，
  输出顺序是 B 的触发词在前、A 的在后。

【例子】
  三个 LoRA 串联，文本框想一次把三套触发词都写进去：用这个节点，
  trigger_words 直接连 CLIPTextEncode.text。

【前端】
  节点底部实时显示检测到的 LoRA 数量；
  「🎯 手动补充 LoRA（触发词选择器）」支持搜索/预览/按状态筛选，
  可以把一批 LoRA 一次性写进 extra_loras。
"""

_MULTI_EN = """【Purpose】
Same upstream detection as the single variant, but it reads the trigger words of
every LoRA on the chain and merges them into one line, in loading order.

【Inputs】
  model       (required, MODEL) the LoRA chain's MODEL, passed through unchanged.
  extra_loras (optional, multiline) manual additions, one per line, usually empty.
  other parameters are shared, see the General help.

【Outputs】
  model         the same MODEL, passed through
  trigger_words every LoRA's trigger words merged into one line (nearest first)
  report        totals (found / with trigger / empty / missing) plus per-LoRA detail

【Order】
  The report lists LoRAs from this node upwards (nearest first). For
  Checkpoint -> LoraLoader(A) -> LoraLoader(B) -> this node, B comes before A.

【Example】
  Three chained LoRAs, and you want all three sets of trigger words in one text
  box: use this node and wire trigger_words straight into CLIPTextEncode.text.

【Frontend】
  The bottom of the node shows how many LoRAs were detected. The
  "🎯 手动补充 LoRA（触发词选择器）" button opens a picker with search, preview
  and status filters that writes a batch of names into extra_loras.
"""

_INFO_ZH = """【作用】
不接模型的手动版：从下拉框里挑一个 LoRA，看看它有没有触发词文本、内容是什么。
用来调试、查阅、或者临时把一个 LoRA 的触发词接到文本框里。

【输入】
  lora_name  （必填）下拉框，列表来自 ComfyUI 的 loras 目录（含子目录）。
  其它是通用参数，见「通用说明」。

【输出】
  trigger_words 这个 LoRA 的触发词，一行
  report        命中了哪个文本文件、多少字、什么编码、分数多少

【例子】
  接一个「Show Text」或者「Preview Text」节点就能直接看；
  也可以把 trigger_words 接到 CLIPTextEncode.text 临时顶上。

【前端】
  「🎯 选择 LoRA（含触发词预览）」：打开选择器，搜索、看预览、
  按"有触发词 / 没有触发词"筛选，双击或选中后点「应用」写回下拉框；
  「📄 查看该 LoRA 的触发词文本」：直接弹出完整文本，可一键复制。
"""

_INFO_EN = """【Purpose】
The manual, model-free variant: pick a LoRA from the dropdown and see whether it
has trigger words and what they are. Handy for debugging, looking things up, or
temporarily feeding a text encoder.

【Inputs】
  lora_name  (required) dropdown built from ComfyUI's loras folder (including
             sub-folders).
  other parameters are shared, see the General help.

【Outputs】
  trigger_words the LoRA's trigger words, one line
  report        which text file matched, its length, encoding and score

【Example】
  Wire it into a Show Text / Preview Text node, or temporarily connect
  trigger_words to CLIPTextEncode.text.

【Frontend】
  "🎯 选择 LoRA（含触发词预览）" opens the picker: search, preview, filter by
  "has trigger words / has none", then apply to write the choice back into the
  dropdown. "📄 查看该 LoRA 的触发词文本" pops up the full text with a copy button.
"""

_HELP_ZH = """【怎么用这个帮助面板】
左上角切换节点，右上角切换中文 / English。
每个页面里：【作用】是什么、【输入】/【输出】每个端口什么意思、【例子】怎么接线。
通用页面讲触发词文件的命名规则、打分表、通用参数和常见问题。
"""
_HELP_EN = """【How to use this help panel】
Pick a node on the left, switch between Chinese and English on the right.
Every page lists what the node does, what each input/output means and a wiring
example. The General page covers trigger file naming, the score table, shared
parameters and the FAQ.
"""

DOCS: Dict[str, Dict[str, str]] = {
    "common": {"zh": _COMMON_ZH, "en": _COMMON_EN},
    "LoRAMultiLoader": {"zh": _LOADER_ZH, "en": _LOADER_EN},
    "LoRATriggerReader": {"zh": _SINGLE_ZH, "en": _SINGLE_EN},
    "LoRATriggerReaderMulti": {"zh": _MULTI_ZH, "en": _MULTI_EN},
    "LoRATriggerReaderInfo": {"zh": _INFO_ZH, "en": _INFO_EN},
    "help": {"zh": _HELP_ZH, "en": _HELP_EN},
}


def doc_for(node: str = "help", lang: str = "zh") -> str:
    """取某个节点的说明文本；节点不存在时退回 help（再不行返回空串）。"""
    key = str(node or "help")
    entry = DOCS.get(key) or DOCS.get("help") or {}
    use_en = str(lang or "zh").lower().startswith("en")
    return str(entry.get("en" if use_en else "zh") or "")


def title_for(node: str, lang: str = "zh") -> str:
    """取帮助面板里显示的标题。"""
    entry = TITLES.get(str(node or "")) or {}
    use_en = str(lang or "zh").lower().startswith("en")
    return str(entry.get("en" if use_en else "zh") or node)


def docs_payload(node: str = "help") -> Dict[str, Any]:
    """给 /help 接口准备的载荷：一次把中英文都带上，前端切换不用再请求。"""
    key = str(node or "help")
    exists = key in DOCS
    return {
        "ok": True,
        "node": key if exists else "help",
        "requested": key,
        "exists": exists,
        "title": {"zh": title_for(key, "zh"), "en": title_for(key, "en")},
        "zh": doc_for(key, "zh"),
        "en": doc_for(key, "en"),
        "nodes": list_nodes(),
    }


def list_nodes() -> List[Dict[str, Any]]:
    """帮助面板左侧列表。"""
    items: List[Dict[str, Any]] = [
        {"key": "common", "title": {"zh": title_for("common", "zh"), "en": title_for("common", "en")}}
    ]
    for key in NODE_ORDER:
        items.append({"key": key, "title": {"zh": title_for(key, "zh"), "en": title_for(key, "en")}})
    return items


__all__ = ["NODE_ORDER", "TITLES", "DOCS", "doc_for", "title_for", "docs_payload", "list_nodes"]
