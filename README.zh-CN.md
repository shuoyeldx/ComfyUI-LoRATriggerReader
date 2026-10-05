# ComfyUI-LoRATriggerReader

**LoRA 触发词自动读取节点** —— 只要你把上游 LoRA 加载节点的 MODEL 接到本节点，它就会自动反查链路上用了哪些 LoRA，读取 LoRA 旁边写好的触发词文本（`.txt` / `.md`），整理成一行字符串送进工作流，再也不用翻文件夹、手动复制粘贴。插件里还有一个 **`多重 LoRA 加载器 (LoRA Multi Loader)`**：用 **4 行下拉框**挑好要用的 LoRA、每行还能单独调 **MODEL 强度 / CLIP 强度**，**一个节点**就能把它们依次叠加到 MODEL 和 CLIP 上，并把它们的触发词一起输出。

[English](README.md) | **中文**

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
![python](https://img.shields.io/badge/python-3.9%2B-blue)
![deps](https://img.shields.io/badge/dependencies-%E9%9B%B6%E7%AC%AC%E4%B8%89%E6%96%B9%E4%BE%9D%E8%B5%96-brightgreen)
![nodes](https://img.shields.io/badge/nodes-4-orange)

> **v1.3 核心变化**：`多重 LoRA 加载器 (LoRA Multi Loader)` 的 LoRA 选择从「一个文本框里一行写一个 `名字: 强度`」改成 **4 行下拉框** —— `lora_1` … `lora_4` 每行从 LoRA 目录（含子目录）里挑一个，第一项 `不使用 / none` 表示这行不加载；每行还有**独立的 MODEL 强度 / CLIP 强度**两个数字框（默认 `1.0`，点数字框左右的小箭头每次 `±0.1`，也可以直接用键盘输入数字）。原来的文本框保留为「**(高级) 批量文本**」（可选），用来一次贴超过 4 个 LoRA 或批量粘贴。加载顺序是**先下拉框第 1 → 4 行，再批量文本**；只有**下拉框和批量文本都为空**时，才自动改用 `model` 链路上的 LoRA。这一版还修掉了一个真实 bug：**以前在 LoRA 后面写强度会读不到触发词**（`妃咲: 0.8` 这类短名字的强度尾巴没被剥离，在「包含类」匹配档位全部失配、分数掉到 700 分阈值以下），现在读取节点和加载器统一改用 `loader.parse_specs` / `split_strengths`，`: 0.8`、`@ 0.8`、`, 0.8`、空格 `0.8`、`<lora:名:0.8>` 这些写法都能被正确剥离 —— **强度只用来定位文件，读触发词时会被忽略**。另外，四个节点都带**中英双语使用说明**：节点 `DESCRIPTION`（悬停节点）、每个端口的 tooltip、以及节点上的「**❓ 使用说明 / Help**」按钮（内容由后端 `GET /lora_trigger_reader/help` 提供）。
>
> **v1.1 核心变化**：v1.0 要在节点上手动选 LoRA（`lora_name` 下拉 / `lora_names` 多行文本）；v1.1 只需要把上游 LoRA 加载节点的 **MODEL 输出连到本节点的 `model` 输入**，节点自己反查工作流，找到 `LoraLoader` / `LoraLoaderModelOnly` / 第三方堆叠节点上选的 LoRA，再去读各自的触发词文本。手动选择降级为「补充」用途（`extra_loras`）。

---

## 目录

- [这是什么](#这是什么)
- [它解决什么问题](#它解决什么问题)
- [功能特性](#功能特性)
- [安装](#安装)
- [依赖说明](#依赖说明)
- [节点一览](#节点一览)
- [多重 LoRA 加载器（v1.3 改版）](#多重-lora-加载器v13-改版)
- [自动反查链路（v1.1 新增）](#自动反查链路v11-新增)
- [快速上手](#快速上手)
- [触发词文件命名规则（重点）](#触发词文件命名规则重点)
- [参数详解](#参数详解)
- [前端增强：触发词选择器与说明面板](#前端增强触发词选择器与说明面板)
- [文本处理细节](#文本处理细节)
- [HTTP 接口](#http-接口)
- [示例工作流](#示例工作流)
- [升级说明](#升级说明)
- [常见问题](#常见问题)
- [兼容性与测试情况](#兼容性与测试情况)
- [目录结构](#目录结构)
- [开发与测试](#开发与测试)
- [许可](#许可)

---

## 这是什么

很多人下载 LoRA 时，作者会附一个说明文件（`xxx提示词.txt`、`xxx触发词.txt`、`xxx.md`……），里面写着这个 LoRA 该用什么触发词。

**ComfyUI-LoRATriggerReader** 就是把这个文件自动读进来：

```
  [CheckpointLoader]                    ┌──────────────────────────┐
        │ MODEL                         │  LoRATriggerReader       │
        ▼                               │  (接在 LoraLoader 右边)  │
  [LoraLoader: silver_wolf]  ──MODEL──▶ │  model  ─────▶ model     │ ──MODEL──▶ [KSampler]
                                        │                          │
  models/loras/xxx/silver_wolf.safetensors                       │  trigger_words
  models/loras/xxx/silver_wolf提示词.txt ──读取──▶                 │ ──STRING─▶ [CLIPTextEncode]
                                        └──────────────────────────┘
```

节点**不加载 LoRA、不改模型**，只是把上游（`LoraLoader`）已经加载好 LoRA 的模型**原样透传**过去，顺便把触发词文本读出来。所以它可以直接插在 LoRA 选择节点的右边，不破坏任何现有工作流。

从 **v1.1** 起，你也不需要再告诉节点"读哪个 LoRA"了：它顺着 `model` 这条连线往上游反查，自己找到链路上用到的 LoRA（`LoraLoader`、`LoraLoaderModelOnly`、各种第三方 LoRA 堆叠节点都行），再去读各自的触发词文本。所以上游换了 LoRA，这里会自动跟着变，不会出现"两边不一致"的静默错误。

`多重 LoRA 加载器 (LoRA Multi Loader)` 则把「串好几个 LoRA 加载器」这件事收进**一个节点**：用 4 行下拉框挑 LoRA、每行单独设 MODEL / CLIP 强度，它就会把它们依次叠加到 MODEL 和 CLIP 上，同时输出这些 LoRA 的触发词——接一条链路的活儿它一个节点就干完了，下游的读取节点也照样能自动发现它加载了哪些 LoRA。详见[多重 LoRA 加载器](#多重-lora-加载器v13-改版)。

---

## 它解决什么问题

- 换一个 LoRA 就要回文件夹看一次触发词 → 现在自动读。
- 触发词文件叫法五花八门（`提示词` / `触发词` / `trigger words` / `.md`）→ 自动匹配。
- 一个工作流里叠了好几个 LoRA → **自动多选节点**帮你把几个触发词按顺序拼好。
- 一条链路上要串好几个 `LoraLoader`，接线又长又乱 → **多重 LoRA 加载器**一个节点用下拉框挑好多个 LoRA、各调各的强度（MODEL + CLIP 一次到位），顺便把触发词一起输出。
- 上游换了 LoRA、读取节点却忘了改 → 现在跟着 `model` 链路自动变，不会再默默读错。
- LoRA 是通过第三方节点 / 子工作流加载的，链路反查不到 → 用 `extra_loras` 手动补上即可。
- 文件可能不存在、可能是 0 字节空文件 → 不会报错，节点照常跑，只输出空字符串。
- 文件是 GBK 编码、带 BOM、有空行、行尾多余逗号 → 全部自动处理。

---

## 功能特性

| 特性 | 说明 |
| --- | --- |
| 🔌 即插即用 | 接在 `LoraLoader` / `LoraLoaderModelOnly` 右边即可，输入 `MODEL`，输出 `MODEL` + 文本 |
| 🧭 自动反查 | 不用手动选 LoRA：顺着 `model` 连线往上游走，自动找出链路上填的 LoRA 并读取触发词 |
| 🧱 多重加载 | **一个节点**用 4 行下拉框 + 每行独立的 MODEL / CLIP 强度加载多个 LoRA，等价于串好几个 `LoraLoader`，同时输出它们的触发词 |
| 🧩 四个节点 | 多重加载器 / 自动单选 / 自动多选 / 手动查询节点，按需使用 |
| 🈯 双语说明 | 四个节点都带中英双语 `DESCRIPTION`、端口 tooltip，以及节点上的「❓ 使用说明 / Help」面板 |
| 🎯 前端选择器 | 节点底部直接显示链路状态，点按钮就能看到每个 LoRA 有没有触发词，搜索、勾选、一键写回，**不需要真的执行工作流** |
| 🈶 中文友好 | 支持中文文件名、中文内容、中文标点；自动识别 UTF-8 / GBK / UTF-16 |
| 🪶 零依赖 | 不引入任何第三方库（不需要 `pip install` 任何东西） |
| 🛡️ 高兼容 | 使用最老的 V1 `INPUT_TYPES` 写法，同时兼容 V1 与 V3 节点 API；不用任何 V3 专属特性；前端脚本失败也不影响节点执行 |
| 🔍 匹配可控 | 打分式匹配 + 归属校验，避免"短名字抢走别人的文本文件" |
| 💾 智能缓存 | 文本索引缓存 8 秒，避免每个队列任务都重新扫盘；文件变了会自动让 ComfyUI 重新执行 |
| 📝 示例与文档 | 自带示例工作流、224 个单元测试、真实目录自检脚本 |

---

## 安装

### 方式一：ComfyUI Manager（推荐）

打开 ComfyUI Manager → `Install Custom Nodes` → 搜索 **LoRATriggerReader** → 安装 → 重启 ComfyUI。

### 方式二：git clone

```bash
cd <你的 ComfyUI 目录>/custom_nodes
git clone https://github.com/shuoyeldx/ComfyUI-LoRATriggerReader.git
```

### 方式三：手动

把 `ComfyUI-LoRATriggerReader` 整个文件夹复制到 `<你的 ComfyUI 目录>/custom_nodes/` 下，确保结构是这样：

```
<ComfyUI>/custom_nodes/ComfyUI-LoRATriggerReader/__init__.py   ← 必须直接在这个层级
```

然后**重启 ComfyUI**（不是刷新浏览器）。重启后控制台应该出现类似：

```
[LoRATriggerReader] 已加载 v1.3.0，4 个节点: LoRAMultiLoader, LoRATriggerReader, LoRATriggerReaderMulti, LoRATriggerReaderInfo
[LoRATriggerReader] 前端增强已加载 (v1.3.0)
```

节点在右键菜单里的分类是 **`LoRA/TriggerReader`**。

前端 JS 由根目录 `__init__.py` 里的 `WEB_DIRECTORY = "./web"` 注册；`pyproject.toml` 的 `[tool.comfy]` 里**故意不写 `web`**（两处同时注册会导致同一份前端脚本被加载两次）。

## 依赖说明

**本插件没有任何第三方 Python 依赖，不需要 `pip install` 任何东西。**

- `requirements.txt` 里只写了说明文字，方便你确认这一点。
- 只用 Python 标准库：`os`、`re`、`codecs`、`difflib`、`threading`、`time`、`typing`。
- 以下是 **ComfyUI 自带的软依赖**，缺失时会自动降级，不会导致插件加载失败：

| 软依赖 | 用途 | 缺失时的表现 |
| --- | --- | --- |
| `folder_paths` | 拿到 `models/loras` 路径列表 | 只能用 `extra_dirs` 手动指定目录；手动查询节点的下拉框会显示 `<未检测到 LoRA>`，但节点本身仍可用 |
| `server`（PromptServer） | 注册 HTTP 接口 | 前端选择器回退到只显示名字（标记 fallback） |
| `aiohttp` | HTTP 接口返回 JSON | 同上（ComfyUI 自带，一般不会缺） |
| `comfy.utils.logging` | 走 ComfyUI 的日志通道 | 自动退回 `logging` / `print`，功能不受影响 |
| `comfy.utils.load_torch_file` + `comfy.sd.load_lora_for_models` | **多重 LoRA 加载器**真正加载 LoRA 时用（和官方 `LoraLoader` 用的是同一套函数） | 只有那个加载器不加载、改为一律输出触发词；其余节点完全不受影响 |

因为不依赖 `torch` / `comfy` 运行时（加载器里对 `comfy` 是**惰性导入**），核心逻辑可以直接在裸 Python 里跑单元测试。

---

## 节点一览

本插件一共 **四个**节点：`多重 LoRA 加载器` 负责**加载**多个 LoRA（4 行下拉框 + 每行独立的 MODEL / CLIP 强度，见[下一节](#多重-lora-加载器v13-改版)），下面三个负责**读取触发词**。

### 1. `LoRA 触发词读取·自动 (LoRA Trigger Reader)`

**自动单选**：接在 `LoraLoader` 右边，只读**接入链路上最近的一个** LoRA。

| 方向 | 名称 | 类型 | 说明 |
| --- | --- | --- | --- |
| 输入 | `model` | MODEL（必填） | 上游 LoRA 加载节点的 MODEL 输出，原样透传 |
| 输入 | `extra_loras` | STRING（多行文本框，可选） | 手动补充链路上没有的 LoRA 或纯文字触发词，默认留空 |
| 输入 | 其余可选参数 | — | `separator` / `deduplicate` / `strip_comments` / `on_missing` / `fallback_text` / `extra_dirs` / `refresh_cache`，见[参数详解](#参数详解) |
| 输出 | `model` | MODEL | 透传进来的模型 |
| 输出 | `trigger_words` | STRING | 整理好的一行触发词，直接接到 `CLIPTextEncode` 的 `text` |
| 输出 | `report` | STRING | 人类可读的报告（接入链路、匹配到哪个文件、多少字、什么编码、匹配分数） |

### 2. `LoRA 触发词读取·自动多选 (LoRA Trigger Reader Multi)`

**自动多选**：读**接入链路上全部** LoRA，按顺序合并成一行输出。多 LoRA 串联、或者用了多 LoRA 堆叠节点时用这个。

输入/输出与上面的单 LoRA 节点完全一致，区别只有一个：它不取"最近的一个"，而是取链路上的全部 LoRA。

### 3. `LoRA 触发词查看 (LoRA Trigger Info)`

**手动查询节点**：**没有 MODEL 输入/输出**，从下拉框选一个 LoRA 拿触发词，纯查看。接一个「显示文本」节点就能调试"这个 LoRA 到底有没有触发词文件、读到的是什么"。

| 方向 | 名称 | 类型 | 说明 |
| --- | --- | --- | --- |
| 输入 | `lora_name` | 下拉框 | 要查看的 LoRA（列表来自你的 `models/loras`） |
| 输入 | 其余可选参数 | — | 同上表里的可选参数（没有 `extra_loras`） |
| 输出 | `trigger_words` | STRING | 触发词文本 |
| 输出 | `report` | STRING | 报告 |

### 关于自动节点拿到工作流的方式

两个自动节点的执行函数声明了隐藏输入 `unique_id`(UNIQUE_ID) 和 `prompt`(PROMPT) —— 这是它拿到**本节点 id** 和**原始工作流**的方式。它**故意不用 `DYNPROMPT`**：老版本 ComfyUI 不认识该类型，会把参数整个漏掉，导致 `TypeError`。

---

## 多重 LoRA 加载器（v1.3 改版）

### `多重 LoRA 加载器 (LoRA Multi Loader)`

**一次加载多个 LoRA**：节点上有 **4 行下拉框**，每行从 LoRA 目录（含子目录）里挑一个 LoRA —— 第一项是 `不使用 / none`，表示这一行不加载。每行还配**两个独立的强度框**：

- `strength_1` … `strength_4`：**MODEL 强度**，FLOAT，`default=1.0`、`min=-100`、`max=100`、`step=0.1`。点数字框左右的小箭头每次 `±0.1`，也可以直接用键盘输入数字；`1.0` = 原样、`0` = 不生效、负数 = 反向。
- `clip_strength_1` … `clip_strength_4`：**CLIP 强度**，同样是 FLOAT、默认 `1.0`、`0.1` 步进。它和 MODEL 强度是**分开的两个框**（和 ComfyUI 自带 `LoraLoader` 的行为一致）；想让两边一样，就把两个框改成同一个数。

节点会按顺序把它们依次叠加到 `model` 与 `clip` 上（等价于把好几个 `LoraLoader` 串起来），同时读取这些 LoRA 的触发词，直接输出给 `CLIPTextEncode`。

| 方向 | 名称 | 类型 | 说明 |
| --- | --- | --- | --- |
| 输入 | `lora_1` … `lora_4` | 下拉框 ×4 | 每行从 LoRA 目录（含子目录）里选一个 LoRA；第一项 `不使用 / none` 表示这一行不加载 |
| 输入 | `strength_1` … `strength_4` | FLOAT ×4（**MODEL 强度**） | 每行独立，`default=1.0`、`min=-100`、`max=100`、`step=0.1`；小箭头每次 `±0.1`，也可直接键盘输入 |
| 输入 | `clip_strength_1` … `clip_strength_4` | FLOAT ×4（**CLIP 强度**） | 同样是 `default=1.0`、`min=-100`、`max=100`、`step=0.1`；与 MODEL 强度**分开的两个框**，想一致就填同一个数 |
| 输入 | `lora_list` | STRING（多行文本框，**可选**，界面上叫「**(高级) 批量文本**」） | 一次贴超过 4 个 LoRA 或批量粘贴时用；一行一个，可带强度，见下方写法 |
| 输入 | `model` | MODEL（**可选**） | 上游模型；不接就只输出触发词、不做加载 |
| 输入 | `clip` | CLIP（**可选**） | 上游 CLIP；不接就只给 MODEL 打补丁 |
| 输入 | 其余可选参数 | — | `separator` / `deduplicate` / `strip_comments` / `on_missing` / `fallback_text` / `extra_dirs` / `refresh_cache`，见[参数详解](#参数详解) |
| 输出 | `model` | MODEL | 叠加了全部 LoRA 之后的模型 |
| 输出 | `clip` | CLIP | 叠加了全部 LoRA 之后的 CLIP |
| 输出 | `trigger_words` | STRING | 这些 LoRA 的触发词合并成的一行文本 |
| 输出 | `report` | STRING | 加载 + 匹配报告（每行的强度、是否加载成功、匹配到哪个文本文件等） |

「(高级) 批量文本」`lora_list` 的写法（冒号右边的都是强度）：

| 写法 | 结果 |
| --- | --- |
| `a.safetensors` | model / clip 都用 `1.0` |
| `a.safetensors: 0.8` | model / clip 都用 `0.8` |
| `a.safetensors: 0.8, 0.5` | model 用 `0.8`，clip 用 `0.5` |
| `a.safetensors @ 0.8` | `@` 等价于 `:` |
| `a.safetensors, 0.8` | 逗号写法，同样认成强度 |
| `a.safetensors, b.safetensors` | 一行写两个名字，两个都会加载 |
| `妃咲` | 只写文件名或角色名也行，会自动补全成相对路径 |
| `a.safetensors 0.8` | 空格写法：只有前半部分确实像个 LoRA 时才会这么切 |
| `<lora:a.safetensors:0.8>` | A1111 风格写法，同样认成强度 |
| `# 备注` / `// 备注` / `-- 备注` | 整行忽略；行尾的 ` # 备注` 也会去掉 |

**加载顺序**：先加载下拉框第 1 → 4 行（`不使用 / none` 的行跳过），再加载「(高级) 批量文本」里的 LoRA；每个 LoRA 分别取自己的 MODEL 强度与 CLIP 强度。

其他行为：

- **不去重**：同一个 LoRA 写两行会真的加载两次（效果叠加），和串两个 `LoraLoader` 一致；
- 强度会被**夹到 `[-100, 100]`**（`MIN_STRENGTH` / `MAX_STRENGTH`），非法数字按 `1.0` 处理；超范围、多余强度、非法项都会在 `report` 里给出警告；
- 一次最多 **64 行**（`MAX_SPECS=64`，防止手滑一次贴进来几百行，超出部分截断）；
- **下拉框和批量文本都为空时**：才自动改用 `model` 这条连线往上游找到的 LoRA，并按**模型流向（远 → 近）**依次加载（和上游 `LoraLoader` 的先后顺序一致），报告里会写明"已自动使用 model 接入链路上的 LoRA（按模型流向依次加载，共 N 个）"；
- `model` / `clip` 都**不接**时不做加载（也不会去读 safetensors 文件），仍然照常输出触发词；
- 单个 LoRA 加载失败**不会让工作流崩掉**：错误会收集进 `report`，其余 LoRA 继续加载；
- 加载过的 LoRA 张量会在内存里缓存（最多 4 个，`CACHE_MAX`），只改强度时不必重新读盘。

> **下游读取节点能自动看到它**：`lora_1` … `lora_4` 这些下拉框名字会被[链路反查](#自动反查链路v11-新增)识别成 LoRA 输入（`不使用 / none` 当成「没选」跳过），`lora_list` 也是被认识的键名 —— 所以「一个多重加载器 + 一个读取节点」就能覆盖多个 LoRA。像 `CheckpointLoader → LoRAMultiLoader → LoRATriggerReader` 这种链路，读取节点能看到加载器下拉框里选的 LoRA，并按行号 1 → 4 的顺序读出。

---

## 自动反查链路（v1.1 新增）

自动节点**不需要你告诉它读了哪个 LoRA**，它自己从工作流里找。做法（`lora_trigger_reader/graph_probe.py`）：

1. 从**本节点 id** 出发，沿 `model` 输入的上游连线做深度优先遍历，**最近者在前**（最多 `MAX_DEPTH=64` 层、`MAX_NODES=256` 个节点，防止病态工作流里死循环）。
2. 每个上游节点里，只收**名字里含 `lora` 且形状安全**的输入：
   - `lora`、`lora_name`、`lora_names`、`lora_path`、`lora_file`、`lora_filename`、`lora_stack`、`lora_stacks`、`loras`，以及 `多重 LoRA 加载器` 用的 `lora_list`；
   - 以及编号形式：`lora_1_name`、`lora_name_1`、`lora_1`、`lora_1_path` 等 —— `多重 LoRA 加载器` v1.3 的 4 个下拉框 `lora_1` … `lora_4` 正落在这一条里，按行号 1 → 4 的顺序读出；值为 `不使用 / none` 时当成「没选」跳过；
   - **显式排除** `lora_strength`、`lora_weight`、`lora_model` 这类不是名字的键。
3. 认识「控件被转成输入端」的情况：如果这个值是一条连线（`["节点id", 槽位]`），会顺着连线找到上游 PrimitiveNode 上的字符串——只有**恰好一个候选**时才采信，避免把整个节点的文本当成 LoRA 名。
4. 名字会**归一化**：`\` → `/`、按换行/逗号/分号/顿号拆分、去掉引号、支持 `#` 注释行。
5. **未连到本节点的分支会被忽略**；工作流成环也能正常终止。

举个例子，API 格式的工作流里上游是这样：

```json
{"3": {"class_type": "LoraLoader",
       "inputs": {"lora_name": "Krea2/角色lora/妃咲.safetensors",
                  "model": ["2", 0]}}}
```

节点读到 `lora_name` 的值就认定"这里选了一个 LoRA"，于是去匹配 `妃咲` 的触发词文本。所以任何第三方 LoRA 节点，只要有形如 `lora_name` / `lora_1` / `lora_name_2` / `lora_stack` 的输入，都能被自动发现。

**本插件的 `多重 LoRA 加载器` 也在内**：它把 LoRA 写在下拉框 `lora_1` … `lora_4`（以及可选的 `lora_list` 批量文本）里，这些键名同样被认识——所以你在加载器里选的、写的 LoRA，下游的读取节点都会自动算进来。

反查结果会写成一行放进 `report`：

```
LoRATriggerReader v1.3.0
[接入链路] 检测到 #3 LoraLoader -> Krea2/Krea2角色lora/妃咲.safetensors；#2 LoraLoader -> Anima/角色lora/silver_wolf_lv999_comfy_v2.safetensors
共 2 个 LoRA | 有触发词 2 | 空文件 0 | 未匹配 0
[1] 妃咲.safetensors -> Krea2/Krea2角色lora/妃咲.txt (290 字/utf-8, 分数 1005)
[2] silver_wolf_lv999_comfy_v2.safetensors -> Anima/角色lora/silver_wolf_lv999_comfy_v2提示词.txt (89 字/utf-8, 分数 975)
```

链路上一个 LoRA 都没有时，第 2 行会写成：

```
[接入链路] 没有检测到 LoRA 节点（上游可能是 CheckpointLoader 直连）。
```

拿不到工作流时（例如 `IS_CHANGED` 阶段、或工作流信息异常）会写成：

```
[接入链路] 无法反查工作流（原因），只能使用手动填写的 LoRA。
```

自动反查的结果排在前面（最近的 LoRA 最前），`extra_loras` 里手动补充的排在后面；两边重复的会自动去重。

---

## 快速上手

### 单个 LoRA

```
CheckpointLoaderSimple ──MODEL──▶ LoraLoader ──MODEL──▶ LoRATriggerReader ──MODEL──▶ KSampler
                                       │                        │
                                       └──CLIP──┐               └──trigger_words──▶ CLIPTextEncode(text) ──▶ KSampler(positive)
                                                └──▶ CLIPTextEncode(negative)
```

1. 右侧新建 `LoRA 触发词读取·自动` 节点；
2. 把上游 `LoraLoader` 的 **MODEL 输出**接到本节点的 `model` 输入（接在它右边就行）；
3. 把 `model` 输出接到 `KSampler`，把 `trigger_words` 接到正向提示词节点的 `text` 输入（把那个小圆点转成输入口即可）。

不需要再选 LoRA：节点底部会显示 `🔎 检测到 1 个 LoRA: xxx.safetensors`，说明它已经找到上游用的是哪个。

### 多个 LoRA

```
LoraLoader(A) ──MODEL──▶ LoraLoader(B) ──MODEL──▶ LoRATriggerReaderMulti ──MODEL──▶ KSampler
                                                          └──trigger_words──▶ CLIPTextEncode(positive)
```

把上游最后一个 `LoraLoader` 的 MODEL 接到 `LoRA 触发词读取·自动多选`，它会自动反查出这条链路上的 `A` 和 `B`，输出就是把两个 LoRA 的触发词按顺序拼好的一行文本。

如果其中某个 LoRA 是链路上检测不到的（比如通过子工作流加载），点节点上的 **🎯 手动补充 LoRA（触发词选择器）** 勾上它，点「应用」，节点会把名字写进 `extra_loras`，和自动检测的结果一起输出。

### 一次加载并读取多个 LoRA（v1.3）

```
CheckpointLoaderSimple ──MODEL/CLIP──▶ LoRAMultiLoader ──MODEL──▶ KSampler
                                             │
                                             └──trigger_words──▶ CLIPTextEncode(text) ──▶ KSampler(positive)
```

在节点的 **4 行下拉框**里挑 LoRA，再用每行旁边的 **MODEL 强度 / CLIP 强度**数字框调各自的强度（例如第 1 行选 `Anima\角色lora\silver_wolf_lv999_comfy_v2.safetensors`、MODEL 与 CLIP 都填 `0.8`；第 2 行选 `Krea2\Krea2角色lora\妃咲.safetensors`、两边都填 `0.6`），不需要的行就留 `不使用 / none`。要一次用超过 4 个 LoRA，或者想直接粘贴一段清单，就把它们写进「**(高级) 批量文本**」：

```
Anima/角色lora/silver_wolf_lv999_comfy_v2.safetensors: 0.8
Krea2/Krea2角色lora/妃咲.safetensors: 0.6
```

`model` 接上游的模型、`clip` 接上游的 CLIP（比如 `CheckpointLoaderSimple` 的这两个输出），输出接给 `KSampler` 和 `CLIPTextEncode` 即可：**一个节点同时完成"加载两个 LoRA"和"输出两个 LoRA 的触发词"**。要再叠加别的 LoRA，就把它的输出继续往后接（或者把它们写成一行行加到「(高级) 批量文本」里）。

### 只想看不想跑

用 `LoRA 触发词查看` 节点 + 「显示文本 / Show Text」节点，下拉框选一个 LoRA，点 Queue 就能看到内容和报告。

---

## 触发词文件命名规则（重点）

插件会扫描 `models/loras` 下的**所有子目录**，找 `.txt` 和 `.md` 文件，然后按下面的规则给每个文件打分，**取分数最高的那个**。

| 分数 | 触发条件 | 例子 |
| --- | --- | --- |
| **1000** | 文本文件名（含扩展名）与 LoRA 文件名完全一样 | `silver_wolf.safetensors` ↔ `silver_wolf.safetensors.txt` |
| **980** | 去掉扩展名后完全一样 | `silver_wolf.safetensors` ↔ `silver_wolf.txt` |
| **950** | 去掉"后缀词"后一样 | `...silver_wolf_lv999_comfy_v2.safetensors` ↔ `...silver_wolf_lv999_comfy_v2提示词.txt` |
| **900** | 文本名以 LoRA 名开头 | `妃咲.safetensors` ↔ `妃咲-全身图.txt` |
| **850** | 文本名里包含 LoRA 完整名字 | `Anima尼可.safetensors` ↔ `推荐_Anima尼可_v2.txt` |
| **800** | LoRA 名里包含文本名 | `silver_wolf_v2.safetensors` ↔ `silver_wolf.txt` |
| **600~690** | 模糊匹配：`difflib` 相似度 ≥ 0.90（分数 = 600 + 100 × 相似度） | 轻微拼写差异 |
| **+25** | 文本文件与 LoRA **在同一个子目录**（额外加分） | 同目录优先于别处的同名文件 |
| **0** | 归属冲突：这个文件明显更属于另一个 LoRA | 见下方「归属校验」 |
| **< 700** | 视为没匹配上，节点输出空字符串 | |

匹配时会忽略大小写和这些字符：空格、`_`、`-`、`·`、`．`、`.`、`、`、`,`（例如 `Silver_Wolf` 和 `silver wolf` 视为同一个名字）。

### 后缀词列表（950 分的档位）

去掉这些词之后如果正好等于 LoRA 名，就按 950 分算：

```
触发词 提示词 关键词 说明 备注 词 語 语
triggerword triggerwords trigger triggers
prompt prompts keyword keywords
activation activate activationwords words word
tag tags info note notes readme read
```

> 例如你的文件叫 `Anima尼可提示词.txt`，LoRA 叫 `Anima尼可.safetensors` → 去掉「提示词」后一致 → 命中。

### 归属校验（避免抢错文件）

当分数低于 950（也就是"不是精确同名"）时，插件会反问一句：**这个文本文件会不会更适合别的 LoRA？**

比如你有两个 LoRA：`A.safetensors` 和 `AB.safetensors`，还有一个 `AB提示词.txt`。
如果没有归属校验，读 `A` 的时候可能会用"包含"规则把 `AB提示词.txt` 抢过来。有了校验，`AB提示词.txt` 只会归 `AB`，读 `A` 时得 0 分，老老实实输出空字符串。

另外，**极短的名字不能参与"包含类"匹配**（`MIN_CONTAIN_CHARS=4`）：像 LoRA `a.safetensors` 不会去抢 `abc.txt`（规则：参与前缀/包含匹配的名字至少 4 个字符，或者含中日韩文字且至少 2 个字符，例如 `妃咲`）。

---

## 参数详解

以下可选参数在四个节点里都有；两个自动节点多了必填的 `model` 输入和 `extra_loras`，多重加载器多了 `lora_1` … `lora_4` 四个下拉框（每行配 `strength_1` … `strength_4` 与 `clip_strength_1` … `clip_strength_4`）以及可选的 `lora_list`（「(高级) 批量文本」）/ `model` / `clip`，手动查询节点则换成 `lora_name` 下拉框。

可选输入的声明顺序（`extra_loras` 之后）是：`separator` → `deduplicate` → `strip_comments` → `on_missing` → `fallback_text` → `extra_dirs` → `refresh_cache`。

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `extra_loras` | STRING（多行） | 空 | 手动补充要读取触发词的 LoRA，一行一个；只有「链路上检测不到」时才需要填。支持完整相对路径、文件名或角色名，也可以直接写纯文字触发词 |
| `separator` | STRING | `", "` | 多行触发词之间的连接符。填 `"\n"` 表示真的换行；想用空字符串就直接留空 |
| `deduplicate` | BOOLEAN | `True` | 去掉重复的触发词（忽略大小写） |
| `strip_comments` | BOOLEAN | `True` | 忽略以 `#`、`//`、`--` 开头的注释行 |
| `on_missing` | 三选一 | `empty` | 没找到触发词文件时的行为：`empty` 输出空字符串 / `lora_name` 输出 LoRA 名字（去掉扩展名）/ `custom` 输出 `fallback_text` |
| `fallback_text` | STRING（多行） | 空 | `on_missing = custom` 时用的兜底文本 |
| `extra_dirs` | STRING | 空 | 额外扫描目录。可写多个，用 `;` 或换行分隔。用于把触发词放在 LoRA 目录外面的情况 |
| `refresh_cache` | BOOLEAN | `False` | 勾上则本次执行强制重新扫盘（平时走 8 秒缓存，更快） |

`extra_loras` 的写法很宽松：

```
# 每行一个，注释行会被忽略
Anima/角色lora/silver_wolf_lv999_comfy_v2.safetensors
Krea2/Krea2角色lora/妃咲.safetensors

# 也可以只写文件名（自动补全相对路径）
妃咲.safetensors

# 甚至可以只写角色名
妃咲

# 每一段都能对上已知 LoRA 时，写在一行也行
silver_wolf_lv999_comfy_v2.safetensors, 妃咲.safetensors
```

**关于 `report` 输出**：它长这样，方便排查问题——

```
LoRATriggerReader v1.3.0
[接入链路] 检测到 #3 LoraLoader -> Krea2/Krea2角色lora/妃咲.safetensors；#2 LoraLoader -> Anima/角色lora/silver_wolf_lv999_comfy_v2.safetensors
共 2 个 LoRA | 有触发词 2 | 空文件 0 | 未匹配 0
[1] 妃咲.safetensors -> Krea2/Krea2角色lora/妃咲.txt (290 字/utf-8, 分数 1005)
[2] silver_wolf_lv999_comfy_v2.safetensors -> Anima/角色lora/silver_wolf_lv999_comfy_v2提示词.txt (89 字/utf-8, 分数 975)
```

统计头固定为 `共 N 个 LoRA | 有触发词 ok | 空文件 empty | 未匹配 missing`，`找不到文件 nofile`、`兜底 fallback`、`异常 failed` 只在非零时追加。

**多重加载器多出来的报告行（v1.3）**：

```
LoRATriggerReader v1.3.0
[多重加载器] 已加载 2 个 LoRA：妃咲.safetensors(0.6), silver_wolf_lv999_comfy_v2.safetensors(0.8)
其中 1 个直接用了内存缓存。
共 2 个 LoRA | 有触发词 2 | 空文件 0 | 未匹配 0
[1] 妃咲.safetensors -> Krea2/Krea2角色lora/妃咲.txt (290 字/utf-8, 分数 1005)
[2] silver_wolf_lv999_comfy_v2.safetensors -> Anima/角色lora/silver_wolf_lv999_comfy_v2提示词.txt (89 字/utf-8, 分数 975)
```

第一行还可能出现：`[多重加载器] 已自动使用 model 接入链路上的 LoRA（按模型流向依次加载，共 N 个）。`（下拉框和批量文本都为空时才会出现）、`[多重加载器] MODEL / CLIP 都没接，跳过加载 N 个 LoRA（触发词照常输出）。`、`[多重加载器] 加载失败：xxx -> 原因`，以及告警行 `[多重加载器] 注意：…`（强度被夹取、行数被截断等）。

---

## 前端增强：触发词选择器与说明面板

节点上会多出几个按钮（**纯前端，坏的也不影响节点执行**）：

| 按钮 | 出现位置 | 作用 |
| --- | --- | --- |
| 🎯 手动补充 LoRA（触发词选择器） | 自动节点（单/多选） | 打开选择面板，应用后写进 `extra_loras` |
| 🔄 重新扫描链路 / LoRA 文本 | 自动节点（单/多选） | 清掉缓存重新扫描链路与文本目录 |
| 🎯 选择 LoRA（写入下拉框） | 多重加载器 | 打开选择面板：勾选项的**前 4 个写进下拉框**，多出来的（或下拉框里放不下的）写进「(高级) 批量文本」；批量文本框里已经被写进下拉框的那些行会被**移除**，避免同一个 LoRA 被加载两次；批量文本框里原来写的强度（`名字: 0.8`）会保留 |
| 🔄 重新扫描 LoRA 文本 | 多重加载器 | 重新扫描 LoRA 文本目录 |
| 🎯 选择 LoRA（含触发词预览） | 查询节点 | 打开选择面板（应用后写回 `lora_name` 下拉框） |
| 📄 查看该 LoRA 的触发词文本 | 查询节点 | 直接弹出触发词内容，**不用执行工作流** |
| ❓ 使用说明 / Help | **全部四个节点**（含多重加载器） | 打开中英双语说明面板，可切换节点 / 语言、复制文本 |

自动节点和 `多重 LoRA 加载器` 都会在**节点底部画一行状态**，一眼就能看出链路：

- `🔎 检测到 N 个 LoRA: a, b` —— 成功反查到；
- `🔎 未接入 MODEL…` —— 还没有把上游的 MODEL 接进来；
- `🔎 已接入，但链路上没识别到 LoRA` —— 接线有了，但找不到 LoRA 选择器；
- `🔎 将加载 N 个 LoRA（下拉框 M 行）: a, b` —— （多重加载器）有选择时，N 是总数、M 是其中来自下拉框的行数；
- `🔎 下拉框和批量文本都为空，自动加载链路 N 个 LoRA: …` —— （多重加载器）两处都空着，将按模型流向往上游链路取；
- `🔎 下拉框和批量文本都为空，链路上也没识别到 LoRA（只输出触发词）` —— （多重加载器）两处都空、上游链路上也没有可识别的 LoRA。

连线变化后状态行会自动刷新（1 秒缓存）。

选择面板里可以：

- 搜索 LoRA 名字 / 路径；
- 筛选「只看有触发词 / 只看没有触发词 / 只看已选 / 只看链路」；
- 每行的徽章告诉你状态：**有触发词 ok**（绿）/ **空文件 empty**（黄）/ **无触发词 none**（灰）/ **找不到 LoRA、出错 bad**（红）；链路检测到的项另外带一个「链路」徽章；
- 鼠标悬停徽章可以看到匹配到的文件路径和内容预览；
- 点「选定链路项」一键勾上链路检测到的 LoRA，「全选当前列表」勾上当前筛选结果（查询节点这里是「选中第一个」），「清空」清掉选择；
- 勾选后点「应用」，自动按 `\n` 写回 `extra_loras`（查询节点则写回 `lora_name` 下拉框，只取第一个勾选项）。

> 数据来自插件自己的 HTTP 接口 `GET /lora_trigger_reader/list`；**接口不可用时**会回退到 `api.getNodeDefs()`（只拿得到名字，没有文本信息，列表会标记 fallback）。
>
> 前端脚本使用了**动态 import + 多层回退**（新版 `scripts/app.js` → `window.comfyAPI` → `window.app`），任何一步失败都只会让按钮消失并在控制台留一条警告，节点本身依旧可用。

### ❓ 使用说明 / Help 面板（v1.3 更新）

四个节点（含 `多重 LoRA 加载器`）都带一个「**❓ 使用说明 / Help**」按钮，点开是中英双语面板：

- 可以切换**节点**（总览 / 通用参数 / 多重加载器 / 自动单选 / 自动多选 / 查看节点），也可以一键切**中文 / English**；
- 内容涵盖节点用法、每个端口的含义、下拉框与「(高级) 批量文本」的写法、触发词命名规则与打分表、参数表、常见问题；
- 面板里可以直接**复制**当前说明文本；
- 另外，鼠标停在**节点本身**上会显示节点的 `DESCRIPTION`，停在某个**输入/输出端口**上会显示该端口的 tooltip，同样是中英双语；
- 文本来自后端 `GET /lora_trigger_reader/help`（见 [HTTP 接口](#http-接口)）；接口不可用时面板里会给出一条降级提示，节点本身不受影响。

> ComfyUI 里节点说明最终长什么样，取决于你的前端版本：老版本不显示 `DESCRIPTION` / `OUTPUT_TOOLTIPS`，但**不会报错**（这些属性会被自动忽略），「❓ 使用说明」按钮则始终可用。

---

## 文本处理细节

| 情况 | 处理方式 |
| --- | --- |
| 编码 | 先做 BOM 探测（utf-8-sig / utf-16 / utf-32），再依次尝试 utf-8 → gb18030（GBK 超集）→ utf-16 → latin-1（永不失败），报告里会告诉你是哪种编码 |
| 空文件（0 字节） | 状态标为 `empty`，输出空字符串，**不报错**（真实 LoRA 包里很常见） |
| 空行 / 只有空格的行 | 丢弃 |
| 注释行（`#` / `//` / `--` 开头） | `strip_comments = True` 时丢弃 |
| 行尾多余的 `,` `，` `;` `；` `、` | 自动去掉（所以文件末尾带逗号不会产生 `, ,` 这种空项） |
| 重复触发词 | `deduplicate = True` 时去掉（忽略大小写） |
| 超大文件 | 只读前 1 MiB，并在报告里标记已截断，防止误读巨型文件 |
| 目录缓存 | 文本索引缓存 8 秒（`INDEX_TTL_SECONDS=8.0`）；`refresh_cache` 或前端「重新扫描」可强制刷新 |
| 文件内容变化 | 通过 `IS_CHANGED`（文件路径 + 大小 + 修改时间）让 ComfyUI 重新执行本节点 |
| 扫描跳过的目录 | `.git`、`.github`、`__pycache__`、`node_modules`、`.idea`、`.vscode`、`.cache`、`.trash`、`$RECYCLE.BIN`、`System Volume Information` |
| 只认的扩展名 | `.txt`、`.md` |

---

## HTTP 接口

插件会注册三个只读接口，供前端和脚本调用（不需要鉴权，只在本机使用）：

| 接口 | 参数 | 返回 |
| --- | --- | --- |
| `GET /lora_trigger_reader/list` | `refresh=1` 强制刷新；`preview=0` 不带内容预览；`extra_dirs=...` 额外目录 | 每个 LoRA 的 `name` / `base` / `status` / `trigger_rel` / `chars` / `encoding` / `score` / `preview` 等 |
| `GET /lora_trigger_reader/text` | `lora_name=xxx`（支持文件名或完整相对路径） | 该 LoRA 的触发词 `text`、`status`、匹配到的 `trigger_rel`、`candidates` 候选列表 |
| `GET /lora_trigger_reader/help` | `node=`，可选值 `help`（默认）/ `common` / `LoRAMultiLoader` / `LoRATriggerReader` / `LoRATriggerReaderMulti` / `LoRATriggerReaderInfo`；节点不存在时退回 `help` | 节点说明：`ok` / `node` / `requested` / `exists` / `title{zh,en}` / `zh` / `en` / `nodes`（**一次把中英文两份都带回来**，前端切换语言不用再请求） |

- 响应头固定带 `Cache-Control: no-store`，不会被浏览器缓存。
- 三个接口**永远返回带 `ok` 字段的 JSON**：任何异常都会返回 `{"ok": false, "error": "..."}`，不会抛 500，所以不会把 ComfyUI 弄崩。
- 内容预览最多 **120 字**；文件大于 **256 KiB** 时跳过预览。

---

## 示例工作流

`examples/example_workflow.json` 是一个可以直接拖进 ComfyUI 画布的示例（v1.3，13 个节点 / 18 条连线）：

- `CheckpointLoaderSimple` → `LoraLoader` → `LoraLoader(妃咲)` → `LoRATriggerReaderMulti` → `KSampler`；
- 第二个 `LoraLoader` 的 MODEL / CLIP 还分出一路给 **`多重 LoRA 加载器 (LoRA Multi Loader)`**（它的 `widgets_values` 已经改成 20 项：12 个下拉/强度 + 批量文本 + 7 个通用参数；第 1 行预选 `Anima\角色lora\silver_wolf_lv999_comfy_v2.safetensors`(0.8/0.8)、第 2 行预选 `Krea2\Krea2角色lora\妃咲.safetensors`(0.6/0.6)），它的 MODEL 输出再接到 `LoRATriggerReader`（单选）——这一条用来演示「**加载器下拉框里选的 LoRA，下游的读取节点也能自动检测到**」；
- `LoRATriggerReader(Multi)` 的 `trigger_words` 接到正向 `CLIPTextEncode` 的 `text` 上，会自动和你手写的提示词拼接；
- 里面还带一个中文 `Note` 节点写着使用步骤。

> 打开后请先把 `CheckpointLoaderSimple` 的模型和两个 `LoraLoader` 的 LoRA 换成你自己有的。

---

## 升级说明

**从 v1.0 升上来：** 自动节点（`·自动` / `·自动多选`）已经没有 `lora_name` / `lora_names` 控件了，v1.0 存下来的旧控件值会被忽略（不会报错）——把上游 `LoraLoader` 的 MODEL 输出接到本节点的 `model` 输入就能用。手动查询节点 `LoRA 触发词查看` 完全没变，依旧是下拉框选 LoRA。匹配规则、打分表、编码识别、目录缓存、HTTP 接口都和 v1.0 一致；万一反查不到（子工作流、第三方加载方式），把名字填进 `extra_loras`，或者点节点上的选择器用「选定链路项」。

**从 v1.1 升上来：** 读取类节点的输入端 / 输出端**完全没变**，旧工作流照常跑，只是节点上多了一个「❓ 使用说明 / Help」按钮。`多重 LoRA 加载器` 是 v1.2 的新节点，v1.2 之前保存的工作流里不会出现它，需要用就自己拖一个并接上 `model` / `clip`（两个都可以不接）。另外两点行为变化：

- 触发词匹配现在会先剥掉强度尾巴（`妃咲.safetensors: 0.8` → `妃咲.safetensors`），纯数字的片段也会被丢掉；
- `lora_list` 也被认成 LoRA 输入键名，所以放在 `多重 LoRA 加载器` 后面的读取节点能直接读到它一行行写的 LoRA。

原来串 N 个 `LoraLoader` 的图可以换成一个 `多重 LoRA 加载器`，但这**不是必须的**——两者可以混用。

**从 v1.2 升上来：** `多重 LoRA 加载器` 的 LoRA 选择从「一个文本框里一行写一个 `名字: 强度`」换成了 **4 行下拉框 + 每行独立的 MODEL / CLIP 强度**（`step=0.1`，也可以直接键盘输入数字），原来的文本框保留为「**(高级) 批量文本**」（可选）。需要知道的变化：

- **旧工作流里的控件值会错位**：v1.2 保存的工作流是按**位置**存控件值的，v1.3 把 12 个下拉/强度控件放在了最前面，所以打开旧工作流时那些旧值会落到 `lora_1` 上、看起来乱掉 —— **请在节点里重新在下拉框里选一遍 LoRA**。旧 `lora_list` 文本框里的内容不会被删、仍然会被加载，所以配置不会丢，只是下拉框需要重选。
- **修掉了一个真实 bug：写强度时读不到触发词。** 以前两个「自动读取」节点（`LoRATriggerReader` / `LoRATriggerReaderMulti`）的 `extra_loras` 走的是旧的 `scan.parse_lora_text`，它**从不剥离强度尾巴**，于是像 `妃咲: 0.8` 这样的短名字在包含类匹配档位全部失配、分数掉到 700 分阈值以下，触发词就空了。现在读取节点和加载器都改用 `loader.parse_specs` / `split_strengths`：`: 0.8`、`@ 0.8`、`, 0.8`、空格 `0.8`、`<lora:名:0.8>` 这些写法都能被正确剥离，`妃咲.safetensors: 0.8` 和 `妃咲.safetensors 0.8` 都能正常读出触发词。注意：**强度只用来定位文件，读触发词时会被忽略。**
- **自动检测的触发条件变了**：以前是「`lora_list` 留空」就自动用 `model` 链路上的 LoRA；现在是**下拉框和批量文本都为空**时才自动检测，并按模型流向依次加载。
- **加载顺序**固定为**先下拉框第 1 → 4 行（跳过 `不使用 / none`），再批量文本**；前端「🎯 选择 LoRA」按钮也改成**把前 4 个写进下拉框**、其余写进批量文本，并移除批量文本框里已经进下拉框的行。
- 版本号升到 **1.3.0**（`lora_scan.VERSION`、根 `__init__.py` 的 `__version__`、`pyproject.toml` 的 `version`、前端 JS 的 `VERSION`、帮助文档里的报告示例全部同步），单元测试增加到 **224** 个（`python -m unittest discover -s tests`）。

---

## 常见问题

**Q：菜单里找不到节点？**
看 ComfyUI 控制台有没有 `加载失败` / `Traceback`。本插件的日志前缀是 `[LoRATriggerReader]`。常见原因是把文件多套了一层目录（`custom_nodes/xxx/ComfyUI-LoRATriggerReader/`），必须让 `__init__.py` 直接位于 `custom_nodes/ComfyUI-LoRATriggerReader/` 下。

**Q：我有触发词文件，但节点输出是空的？**
打开「LoRA 触发词查看」节点接一个显示文本节点看 `report`：

- 显示「未匹配」→ 文件名不符合命名规则，参考上面的[打分表](#触发词文件命名规则重点)；
- 显示「空文件」→ 你的 txt 是 0 字节，需要自己补内容；
- 显示「找不到文件」→ 你选的 LoRA 名字在目录里找不到（可能是缓存），勾一下 `refresh_cache` 或者点前端「重新扫描」。

**Q：节点没有检测到 LoRA 怎么办？**
先看节点底部的状态行和 `report` 的第 2 行：

- `🔎 未接入 MODEL…` → 还没把上游 LoRA 加载节点的 MODEL 输出接到本节点的 `model` 输入；
- `🔎 已接入，但链路上没识别到 LoRA` → 接线有了，但上游没有能被识别的 LoRA 选择器（例如 LoRA 是通过子工作流或自定义脚本加载的）；
- 如果某个 LoRA 是接在**另一条分支**上的（没有连到本节点），它会被忽略——这是有意为之，只有"真正接到本节点的模型链路"才算数；
- 确实要读链路上没有的 LoRA，就填 `extra_loras`，或点节点上的 **🎯 手动补充 LoRA**。

**Q：手动选择还能用吗？**
能。v1.1 把手动选择降级为「补充」：自动检测正常情况下已经够用，只有在链路反查不到（子工作流、第三方加载方式）时才需要往 `extra_loras` 里填。手动查询节点 `LoRA 触发词查看` 依旧是纯手动选下拉框。

**Q：为什么不用 `DYNPROMPT` 拿工作流？**
因为老版本 ComfyUI 不认识 `DYNPROMPT` 这个类型，会把参数整个漏掉，直接导致节点函数 `TypeError`。所以两个自动节点用的是最保守的隐藏输入 `unique_id`(UNIQUE_ID) + `prompt`(PROMPT)。

**Q：为什么加了逗号之后提示词里出现 `, ,` ？**
触发词文件行尾自带逗号时插件会自动清理，但如果你的文件里是「一行里写了很多用逗号分隔的词」，那本来就是一整行，不会被拆开。想拆行，就按行写。

**Q：中文显示乱码？**
插件已按 UTF-8 → GB18030 → UTF-16 的顺序猜编码。如果还是乱码，把触发词文件另存为 UTF-8。

**Q：我的触发词文件不在 LoRA 目录里。**
用 `extra_dirs` 填上目录，多个目录用 `;` 或换行分隔。**同目录加分（+25）只对 LoRA 自己所在目录生效**，额外目录里的文件照样能匹配上。

**Q：多个 LoRA 只想用其中一个的触发词？**
用**自动单选**节点（`LoRA 触发词读取·自动`），它只读离自己最近的那一个 LoRA；或者干脆在 `extra_loras` 里只写你要的那个。

**Q：换了 LoRA 内容但输出没变？**
触发词文本变化会通过 `IS_CHANGED` 自动触发重跑；上游换了 LoRA，`model` 这条依赖也会让本节点重算。如果没生效，勾 `refresh_cache`。

**Q：会不会重复加载 LoRA？**
不会。本节点**只透传模型**，LoRA 是由上游 `LoraLoader` 加载的。

**Q：怎么不串一堆 `LoraLoader` 就加载多个 LoRA？**
用 `多重 LoRA 加载器`：`model` / `clip` 接上上游，在 **4 行下拉框**里挑 LoRA、用旁边的 MODEL / CLIP 强度框调各行的强度（要一次用更多、或想粘贴清单，就把它们写进「(高级) 批量文本」，如 `妃咲.safetensors: 0.6`），它按加载顺序依次叠加，并把这些 LoRA 的触发词一起输出。v1.1 及更早版本只能靠串接多个 `LoraLoader`。

**Q：加载器报 `加载失败：xxx -> 在 LoRA 目录里找不到该文件`？**
说明下拉框 / 「(高级) 批量文本」里的名字在 LoRA 目录里找不到。写相对路径（`Krea2\Krea2角色lora\妃咲.safetensors`）或准确的文件名都可以，只写一个裸文件名/角色名时插件会尝试自动补全；刚放进目录的文件点一下「🔄 重新扫描 LoRA 文本」。

**Q：为什么写了 `妃咲: 0.8` 之后触发词是空的？（v1.3 已修复）**
这是 v1.3 之前版本的一个真实 bug：两个「自动读取」节点（`LoRATriggerReader` / `LoRATriggerReaderMulti`）的 `extra_loras` 走的是旧的 `scan.parse_lora_text`，它**从不剥离强度尾巴**，于是像 `妃咲: 0.8` 这样的短名字在包含类匹配档位全部失配、分数掉到 700 分阈值以下，触发词就空了。v1.3 起读取节点和加载器都改用 `loader.parse_specs` / `split_strengths`，`: 0.8`、`@ 0.8`、`, 0.8`、空格 `0.8`、`<lora:名:0.8>` 这些写法都能被正确剥离，`妃咲.safetensors: 0.8` 和 `妃咲.safetensors 0.8` 都能正常读出触发词。注意：**强度只用来定位文件，读触发词时会被忽略。**

**Q：`model` 和 `clip` 都不接会不会报错？**
不会。两个都不接时它**一个 LoRA 也不加载、连 LoRA 文件都不读**，但仍然照常输出触发词（报告里会写「MODEL / CLIP 都没接，跳过加载 N 个 LoRA（触发词照常输出）」）——只想拿多个 LoRA 的触发词时很好用。

**Q：同一个 LoRA 写了两次会加载两次吗？**
会，这是有意设计的（重复写就是重复叠加，比如在下拉框和「(高级) 批量文本」里各写了一次）。不用担心读盘开销：已读的张量在内存里最多缓存 4 个，同一轮里第二次用直接从缓存拿。

**Q：为什么加载器把我写的强度改小了？**
强度会被夹到 `[-100, 100]` 区间，超出范围只在 `report` 里给一条 `[多重加载器] 注意：…` 警告并按夹取后的值生效，不会中断任务。下拉框旁边的 MODEL / CLIP 强度框本身就限在 `[-100, 100]`，所以「被夹取」最常出现在「(高级) 批量文本」里手写的强度上。

**Q：ComfyUI 里面的使用说明在哪看？**
任一节点上的「**❓ 使用说明 / Help**」按钮（v1.3）。面板可以切换中文 / 英文，也可以切换「总览页 + 四个节点」的说明文本，内容来自 `GET /lora_trigger_reader/help`；同样的文字也出现在节点 `DESCRIPTION`（鼠标悬停节点）和每个端口的 tooltip 里。

**Q：多重加载器为什么还要接 CLIP？**
因为 ComfyUI 的 `load_lora_for_models` 会**同时给 MODEL 和 CLIP 打补丁** —— 很多 LoRA 不只要改模型，触发词也要送进 `CLIPTextEncode`，两边必须用同一份 LoRA 权重。只接 `model` 也能用，但那样 CLIP 侧不会被修改。

**Q：加载器里的 LoRA 会覆盖上游的 LoRA 吗？**
不会。下拉框和「(高级) 批量文本」只是**这个加载器自己**要加载的清单，它不会去改动上游 `LoraLoader` 已经加载好的东西（效果是叠加的，等价于继续往后串几个 `LoraLoader`）。链路上所有 LoRA（包括批量文本里写的）都会被下游的读取节点算进来。

---

## 兼容性与测试情况

| 项目 | 情况 |
| --- | --- |
| 测试环境 | ComfyUI **0.38.0** + `comfyui_frontend_package` **1.53.10** + Python **3.12.10**（Windows） |
| Python 版本 | 代码兼容 **3.9+**（`from __future__ import annotations`） |
| 节点定义风格 | V1 `INPUT_TYPES` / `NODE_CLASS_MAPPINGS`；**同时兼容 V1 与 V3 节点 API**，没有用任何 V3 专属特性 |
| 前端 API | `app.registerExtension` + `addWidget("button")`，动态 import 多层回退，失败静默降级 |
| 真实数据验证 | 在 `I:\ComfyUI-aki-v2\ComfyUI\models\loras` 的 **137 个 LoRA / 58 个文本文件**上跑过：54 个匹配到触发词 + 1 个空文件 + 82 个"确实没有触发词"，未出现抢错文件 |
| 真机自动反查 | 两个 `LoraLoader` 串联的链路上，妃咲（分数 **1005**）和 silver_wolf_lv999_comfy_v2（**975**）都被自动正确读出 |
| 真机多重加载器（v1.3） | 同一台机器上验证：4 个下拉框与各自的 MODEL / CLIP 强度、以及「(高级) 批量文本」的强度都解析正确；`loader.load_tensor_cached` 真读一个 512 键的 `.safetensors`（首次 0.2s，第二次缓存命中 0.0000s）；两个真实 LoRA 依次叠加到 MODEL+CLIP；写了不存在的名字只产生一行 `加载失败` 报告、不抛异常 |
| 真机接口与安装（v1.3） | 以 ComfyUI 的方式（`spec_from_file_location`，不带 `submodule_search_locations`）从 `custom_nodes/ComfyUI-LoRATriggerReader` 加载：4 个节点全部注册；`/lora_trigger_reader/help` 六个键都有中文与英文（`common` 中文 2551 字 / 英文 4406 字），未知节点名仍返回 `ok=true` + `exists=false` |
| 单元测试 | **224** 个用例全绿（`test_lora_scan.py` 44 + `test_graph_probe.py` 35 + `test_loader.py` 56 + `test_nodes_api.py` 89） |
| 示例工作流 | 用真实 ComfyUI 节点定义做过结构校验：13 个节点 / 18 条连线、每个节点的输入类型与输出槽位、连线的两端与登记信息全部通过 |
| 前端脚本 | `node --check` 语法检查通过 |

已覆盖的边界情况：空文件、GBK/UTF-16/BOM 编码、超 1 MiB 截断、注释行、行尾中文逗号、重复词、归属冲突、短名字抢文件、`extra_dirs`、`on_missing` 三种兜底策略、多 LoRA 逗号一行写法、只写文件名/角色名的自动补全、链路反查（含 `lora_strength` 之类的键不被误认、控件转输入端、成环链路、超深/超宽链路）、多重加载器（4 行下拉框槽位与 `不使用 / none`、MODEL / CLIP 双强度、各种强度写法、强度夹范围与非法值、64 行截断、不去重、下拉框和批量文本都为空时自动用上游 LoRA、加载失败不崩），以及 HTTP `/help` 的中英文载荷与未知节点回退。

---

## 目录结构

```
ComfyUI-LoRATriggerReader/
├── __init__.py                    # ComfyUI 入口：注册节点 + WEB_DIRECTORY + HTTP 接口
├── lora_trigger_reader/           # 包名带前缀，避免和别人的 py/ utils/ 重名
│   ├── __init__.py
│   ├── lora_scan.py               # 核心逻辑：扫描、打分匹配、读文件、格式化（无 torch 依赖）
│   ├── graph_probe.py             # v1.1：沿 model 连线反查链路上用了哪些 LoRA
│   ├── loader.py                  # 多重加载器的下拉框/强度解析 + 加载（对 comfy 惰性导入，可裸跑单测）
│   ├── help_docs.py               # 四个节点的中英双语说明文本（/help 接口的数据源）
│   ├── nodes.py                   # 四个节点的定义（V1 INPUT_TYPES）
│   └── api.py                     # HTTP 接口 /lora_trigger_reader/list、/text 与 /help
├── web/
│   └── js/
│       └── lora_trigger_reader.js # 前端按钮、节点底部状态行与选择器面板
├── examples/
│   └── example_workflow.json      # 可直接拖进画布的示例工作流
├── tests/
│   ├── test_lora_scan.py          # 核心匹配/读取逻辑测试
│   ├── test_graph_probe.py        # v1.1：链路反查测试
│   ├── test_loader.py             # 多重加载器的解析 / 加载测试
│   ├── test_nodes_api.py          # 节点、HTTP（含 /help）、模拟 ComfyUI 加载测试
│   └── integration_real_loras.py  # 拿真实 LoRA 目录自检（可选）
├── README.md                      # 英文说明（GitHub 首页默认显示）
├── README.zh-CN.md                # 中文说明（本文件）
├── requirements.txt               # 依赖说明（零第三方依赖）
├── pyproject.toml                 # ComfyUI Registry 发布元数据
├── LICENSE                        # MIT
├── .gitignore
└── .github/workflows/
    ├── ci.yml                     # 单元测试 + JS 语法检查
    └── publish.yml                # 自动发布到 ComfyUI Registry
```

---

## 开发与测试

```bash
# 全部单元测试（不需要 ComfyUI、不需要 torch）
python -m unittest discover -s tests -v

# 拿真实 LoRA 目录做一次自检（会打印每个 LoRA 有没有配上触发词）
python tests/integration_real_loras.py "I:/ComfyUI-aki-v2/ComfyUI/models/loras"
python tests/integration_real_loras.py "D:/ComfyUI/models/loras" --extra "D:/我的提示词" --list
```

前端脚本语法检查：

```bash
node --input-type=module --check < web/js/lora_trigger_reader.js
```

想改匹配规则，改 `lora_trigger_reader/lora_scan.py` 顶部的常量就行：

```python
TEXT_EXTENSIONS        = (".txt", ".md")   # 认哪些扩展名
SUFFIX_WORDS           = (...)             # 后缀词（950 分档）
MIN_ACCEPT_SCORE       = 700               # 低于这个分数算没匹配上
MIN_CONTAIN_CHARS      = 4                 # 参与包含匹配的最短长度（含 CJK 时 2 个字，如「妃咲」）
ENABLE_FUZZY_MATCH     = True              # 是否启用模糊匹配
FUZZY_RATIO            = 0.90              # 模糊匹配阈值
INDEX_TTL_SECONDS      = 8.0               # 目录索引缓存时长
MAX_FILE_BYTES         = 1024 * 1024       # 单个文件最多读多少字节
```

想改链路反查的搜索范围，改 `lora_trigger_reader/graph_probe.py` 顶部的常量：

```python
MAX_DEPTH              = 64                # 最多往上游走多少层
MAX_NODES              = 256               # 最多看多少个节点
```

想改多重加载器的行为，改 `lora_trigger_reader/loader.py` 顶部的常量：

```python
SLOT_COUNT             = 4                 # 下拉框行数：lora_1 … lora_4
SLOT_NONE              = "不使用 / none"    # 下拉框的「不加载」档
DEFAULT_STRENGTH       = 1.0               # 强度框默认值；批量文本不写强度时 model/clip 都用这个值
MIN_STRENGTH           = -100.0            # 强度下限（和官方 LoraLoader 一致）
MAX_STRENGTH           = 100.0             # 强度上限
MAX_SPECS              = 64                # 一次最多加载多少个 LoRA（超出截断）
CACHE_MAX              = 4                 # 内存里最多缓存几个已读入的 LoRA 张量
```

所有面向用户的说明文本（总览页 + 四个节点页，中英双语）都在 `lora_trigger_reader/help_docs.py` 里，改那里即可——`/lora_trigger_reader/help` 接口和前端「❓ 使用说明」面板会同步生效。

只跑某一个测试文件（`tests` 目录里没有 `__init__.py`，所以 `python -m unittest tests.test_xxx` 会报 `ModuleNotFoundError`，必须用 `discover`）：

```bash
python -m unittest discover -s tests -p "test_loader.py" -v
```

---

## ⚠️ 开发与维护声明 / Development & Maintenance

本插件的代码主要由生成式 AI 辅助编写。虽然作者进行了基本测试，但无法保证在所有环境和 ComfyUI 版本下都能稳定运行。本项目按“原样”提供，目前处于**随缘维护**状态，不保证及时更新或修复所有 Bug。
遇到问题欢迎提 Issue 交流，也欢迎直接提交 PR 修复。

The code for this plugin was primarily written with the assistance of generative AI. While basic testing has been conducted, stability across all environments and ComfyUI versions is not guaranteed. This project is provided "as-is" and is maintained on a best-effort basis. Feel free to open an Issue or submit a PR.

## 许可

[GPL v3](LICENSE) —— 随便用，出问题自己负责 🙂
