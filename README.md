# ComfyUI-LoRATriggerReader

**LoRA trigger-word reader node** — reads the trigger-word text file (`*.txt` / `*.md`) that ships next to your LoRA, cleans it up, and feeds it into your workflow as a single string. No more digging through folders and copy-pasting by hand. Since **v1.2** it also ships a **multi-LoRA loader** that applies several LoRAs to `MODEL` **and** `CLIP` in one node and outputs their trigger words — and since **v1.3** you pick up to four of them from **dropdown rows**, each with its own MODEL and CLIP strength.

**English** | [中文 / Chinese](README.zh-CN.md)

![license](https://img.shields.io/badge/license-GPL--3.0-blue)
![python](https://img.shields.io/badge/python-3.9%2B-blue)
![deps](https://img.shields.io/badge/dependencies-zero%20third--party-brightgreen)
![nodes](https://img.shields.io/badge/nodes-4-orange)
![version](https://img.shields.io/badge/version-1.3.0-blue)

---

## Table of contents

- [What's new in v1.3](#whats-new-in-v13)
- [What is this](#what-is-this)
- [The problem it solves](#the-problem-it-solves)
- [Features](#features)
- [Installation](#installation)
- [Dependencies](#dependencies)
- [Nodes](#nodes)
- [Automatic upstream detection](#automatic-upstream-detection)
- [Quick start](#quick-start)
- [Trigger-file naming rules (important)](#trigger-file-naming-rules-important)
- [Parameter reference](#parameter-reference)
- [Frontend bonus: the picker and the help panel](#frontend-bonus-the-picker-and-the-help-panel)
- [Text processing details](#text-processing-details)
- [HTTP endpoints](#http-endpoints)
- [Example workflow](#example-workflow)
- [Upgrading](#upgrading)
- [FAQ](#faq)
- [Compatibility and testing](#compatibility-and-testing)
- [Project layout](#project-layout)
- [Development and tests](#development-and-tests)
- [Publishing checklist](#publishing-checklist)
- [License](#license)

---

## What's new in v1.3

**The multi loader now takes LoRAs from four dropdown rows, each with its own MODEL and CLIP strength.** `LoRAMultiLoader` no longer asks you to type `name: strength` lines by hand — the four rows are dropdowns over your LoRA roots (subfolders included), and the old text box is kept only as an **"(advanced) batch text"** field for bulk pasting.

- `lora_1` … `lora_4`: four **dropdowns**, each picking one LoRA. The first entry, `不使用 / none`, means "this row loads nothing" (that is `loader.SLOT_NONE`, and `loader.SLOT_COUNT = 4`).
- `strength_1` … `strength_4`: the **MODEL strength** — FLOAT, `default 1.0`, `min -100`, `max 100`, **`step 0.1`**. The left/right arrows on the number box step by 0.1 and you can also just type a number. `1.0` = unchanged, `0` = no effect, negative = inverted.
- `clip_strength_1` … `clip_strength_4`: the **CLIP strength** — same FLOAT spec (`1.0`, step 0.1). It is a **separate box** from the MODEL strength, exactly like the built-in `LoraLoader`; set both boxes equal if you want them identical.
- `lora_list` is still there but is now **optional**, labelled **"(advanced) batch text"** in the UI — use it to paste more than 4 LoRAs or a bulk list. Its syntax is unchanged: `name.safetensors`, `name.safetensors: 0.8`, `name.safetensors: 0.8, 0.5`, `name.safetensors @ 0.8`, `name.safetensors, 0.8`, the space form `a.safetensors 0.8`, A1111 style `<lora:name.safetensors:0.8>`, two names on one line, `#` comment lines / trailing notes, bare filenames auto-completed to the full relative path, strengths clamped to `[-100, 100]`, at most 64 entries, and the same LoRA twice loads twice.
- **Load order:** dropdown rows 1 → 4 first, then the "(advanced) batch text" box.
- **Auto-detection** now kicks in only when **both the dropdowns and the batch text box are empty**: then the node applies the LoRAs found upstream on the `model` wire. The report says `已自动使用 model 接入链路上的 LoRA（按模型流向依次加载，共 N 个）`.
- The report header is now `LoRATriggerReader v1.3.0`.

**Bug fix: a strength suffix used to make the trigger words come out empty.** The two automatic reader nodes (`LoRATriggerReader` / `LoRATriggerReaderMulti`) parsed `extra_loras` with the old `scan.parse_lora_text`, which **never stripped a strength suffix**, so a short name like `妃咲: 0.8` failed every containment-match tier and fell below the 700-point threshold, producing an empty string. Both the reader nodes and the loader now parse through `loader.parse_specs` / `split_strengths`, so `: 0.8`, `@ 0.8`, `, 0.8`, the space form `0.8` and `<lora:name:0.8>` are all stripped correctly, and `妃咲.safetensors: 0.8` / `妃咲.safetensors 0.8` both read their trigger words. The strength is only used to locate the file — it is ignored when reading the trigger words.

**Frontend.** The picker button on the loader is now **`🎯 选择 LoRA（写入下拉框）`** (it writes into the dropdown rows); the second button is still **`🔄 重新扫描 LoRA 文本`**, and every node has **`❓ 使用说明 / Help`**. After you press "应用", the **first 4 selections go into the dropdown rows** and the overflow goes into the "(advanced) batch text" box; lines that were moved into a dropdown are **removed** from the batch box so the same LoRA is not loaded twice, and strength suffixes already written there are preserved.

<details>
<summary>What was new in v1.2</summary>

**A new node: the multi-LoRA loader.** `LoRAMultiLoader` was introduced with a plain `lora_list` text box. In v1.3 the dropdown rows became the primary way to pick LoRAs and that text box was demoted to the optional "(advanced) batch text" field:

- `lora_list` was a plain text box: one LoRA per line, strength optional (`妃咲.safetensors: 0.6`, `a.safetensors: 0.8, 0.5`, `a.safetensors @ 0.8`, …).
- It has **both** a `model` input/output **and** a `clip` input/output (both inputs are optional: connect neither and the node only outputs trigger words, without loading anything).
- Leave `lora_list` empty and it fell back to the LoRAs found upstream on the `model` wire, applied in model-flow order.
- The reader nodes downstream see the loader's selection, so `… → LoRAMultiLoader → LoRATriggerReader` works with no extra wiring.

**Bilingual in-ComfyUI help for every node.** All four nodes now carry Chinese + English documentation: the node `DESCRIPTION` tooltip, per-port tooltips (`OUTPUT_TOOLTIPS`), search aliases, and a **❓ 使用说明 / Help** button that opens a panel with the full manual (trigger-file rules, scoring table, parameter reference, FAQ) served by the new `GET /lora_trigger_reader/help` endpoint. Older ComfyUI builds simply ignore the attributes they do not know.

</details>

<details>
<summary>What was new in v1.1</summary>

**You no longer pick the LoRA twice.** In v1.0 the node had a `lora_name` dropdown (single) or a `lora_names` text box (multi) and you had to keep that selection in sync with the `LoraLoader` by hand. In **v1.1**:

- connect the **MODEL output of your LoRA loader to the `model` input** of the reader node (i.e. drop the node to the right of the `LoraLoader`);
- the node walks that wire upstream, finds the `LoraLoader` / `LoraLoaderModelOnly` / third-party stacker nodes on the chain, and reads **the LoRA each of them selected**;
- the former manual selection is demoted to an *optional supplement*: `extra_loras`.

| | v1.0 | v1.1 |
| --- | --- | --- |
| Single node | `lora_name` dropdown | `model` input — auto-detected |
| Multi node | `lora_names` multiline text | `model` input — auto-detected |
| Manual selection | the only way | `extra_loras` (supplement / pure text) |
| Info node | `lora_name` dropdown | `lora_name` dropdown (unchanged) |

</details>

Everything else — the trigger-file naming rules, the scoring table, encodings, caching, the picker panel — is unchanged. See [Upgrading](#upgrading).

---

## What is this

Many LoRA downloads come with a readme (`xxx_prompt.txt`, `xxx_trigger.txt`, `xxx.md`, …) that lists the trigger words you are supposed to use with that LoRA.

**ComfyUI-LoRATriggerReader** reads that file for you automatically — and since **v1.1** you do not even have to tell it which LoRA you are using:

```
  [CheckpointLoader]                    ┌──────────────────────────┐
        │ MODEL                         │  LoRATriggerReader       │
        ▼                               │  (right of LoraLoader)   │
  [LoraLoader: silver_wolf]  ──MODEL──▶ │  model  ─────▶ model     │ ──MODEL──▶ [KSampler]
                                        │                          │
                                        │  ...looks left, up the   │
                                        │  model wire, for LoRAs   │  trigger_words
  models/loras/xxx/silver_wolf.safetensors                       │  ──STRING─▶ [CLIPTextEncode]
  models/loras/xxx/silver_wolf_prompt.txt ──read──▶               │
                                        └──────────────────────────┘
```

The reader node **does not load the LoRA and does not modify the model**. It simply passes the incoming model through unchanged (the LoRA is already applied by the upstream `LoraLoader`), walks the `model` link upstream to discover which LoRA(s) were selected there, and reads their trigger words as a side output. That is why it can be dropped in directly to the right of your LoRA selector without breaking anything — and with nothing to keep in sync.

The **`LoRAMultiLoader`** (new in v1.2, dropdown rows since v1.3) is the opposite half: it *does* apply LoRAs — several of them, to `MODEL` and `CLIP`, picked from four dropdown rows (or pasted into the "(advanced) batch text" box) — and outputs their trigger words at the same time. Use it when you want one node instead of a chain of `LoraLoader` nodes.

---

## The problem it solves

- Swapping LoRAs means opening the folder to look up trigger words → now it is automatic.
- Picking the LoRA a second time in the reader node is easy to forget or get wrong → in v1.1 the **`model` wire itself** decides which LoRA is read; change the LoRA upstream and the trigger words follow.
- Trigger files are named inconsistently (`提示词` / `触发词` / `trigger words` / `.md`) → all matched automatically.
- Stacks of several LoRAs → the **multi** node reads every LoRA on the chain, in order.
- Chaining five `LoraLoader` nodes just to stack five LoRAs → the **multi loader** applies them all from four dropdown rows (or a bulk text box), to `MODEL` and `CLIP`, and gives you the trigger words too.
- The file may be missing, or be a 0-byte empty file → no error, the node just outputs an empty string.
- The file may be GBK-encoded, have a BOM, contain blank lines or trailing commas → all handled.

---

## Features

| Feature | Description |
| --- | --- |
| 🔌 Drop-in | Sits right after `LoraLoader` / `LoraLoaderModelOnly`: takes `MODEL`, returns `MODEL` + text |
| 🔎 Auto-detection (v1.1) | Reads the LoRA(s) straight off the `model` connection — no second selection to keep in sync |
| 📚 Multi-LoRA loader (v1.3) | `LoRAMultiLoader`: `lora_1` … `lora_4` dropdowns, each with its own MODEL strength and CLIP strength (step 0.1, typeable; `不使用 / none` = skip the row), plus an optional "(advanced) batch text" box for more than 4 LoRAs → `MODEL` **and** `CLIP`, plus their trigger words. Both inputs optional |
| 🧩 Four nodes | Multi loader / auto single / auto multi / manual info node |
| 🎯 Frontend picker | One button shows which LoRAs have trigger words; search, tick, write back — **without running the workflow**. It is the *supplement* path, not the main one |
| ❓ In-ComfyUI help | Every node has Chinese + English docs: node tooltip, per-port tooltips, search aliases and a Help panel fed by `/lora_trigger_reader/help` |
| 🈶 CJK friendly | Chinese/Japanese/Korean filenames and content, full-width punctuation, UTF-8 / GBK / UTF-16 detection |
| 🪶 Zero dependencies | No third-party libraries at all (nothing to `pip install`) |
| 🛡️ High compatibility | Old-school V1 `INPUT_TYPES`; a broken frontend script never breaks node execution |
| 🔍 Sane matching | Score-based matching plus ownership checks, so short names cannot steal someone else's text file |
| 💾 Smart caching | 8-second directory index cache; changed files make ComfyUI re-run the node |
| 📝 Docs and examples | Ships with an example workflow, unit tests and a real-directory self-check script |

---

## Installation

### Option 1: ComfyUI Manager (recommended)

Open ComfyUI Manager → `Install Custom Nodes` → search for **LoRATriggerReader** → install → restart ComfyUI.

### Option 2: git clone

```bash
cd <your ComfyUI>/custom_nodes
git clone https://github.com/shuoyeldx/ComfyUI-LoRATriggerReader.git
```

### Option 3: manual

Copy the whole `ComfyUI-LoRATriggerReader` folder into `<your ComfyUI>/custom_nodes/` so that the layout is exactly:

```
<ComfyUI>/custom_nodes/ComfyUI-LoRATriggerReader/__init__.py   ← must be at this level
```

Then **restart ComfyUI** (restarting the server, not just refreshing the browser). You should see something like:

```
[LoRATriggerReader] 已加载 v1.3.0，4 个节点: LoRAMultiLoader, LoRATriggerReader, LoRATriggerReaderMulti, LoRATriggerReaderInfo
[LoRATriggerReader] 前端增强已加载 (v1.3.0)
```

The nodes live under the **`LoRA/TriggerReader`** category.

---

## Dependencies

**There are no third-party Python dependencies. Nothing to install.**

- `requirements.txt` only contains an explanatory note so you can confirm this.
- Standard library only: `os`, `re`, `io`, `codecs`, `difflib`, `threading`, `time`, `typing`.
- The three modules below are **soft dependencies** that ship with ComfyUI itself. If any is missing the plugin degrades gracefully instead of failing to load:

| Soft dependency | Used for | Behaviour when missing |
| --- | --- | --- |
| `folder_paths` | Locating the `models/loras` directories | Only the `extra_dirs` directories are scanned; the info node still works |
| `server` (PromptServer) | Registering the HTTP endpoints | The frontend picker falls back to name-only mode |
| `aiohttp` | Returning JSON from those endpoints | Same as above (always present in ComfyUI) |

Because it does not depend on `torch` / `comfy`, the core logic (including the upstream probe) can be unit-tested in plain Python.

---

## Nodes

### 1. `多重 LoRA 加载器 (LoRA Multi Loader)`

**New in v1.2, dropdown rows since v1.3.** Applies up to four LoRAs picked from dropdown rows (plus anything pasted into the optional "(advanced) batch text" box) to `MODEL` **and** `CLIP` — the equivalent of chaining several `LoraLoader` nodes — and outputs their trigger words at the same time. Each row has its **own MODEL strength and CLIP strength**.

```
[CheckpointLoader] ─MODEL─┬─▶ [LoRAMultiLoader] ─MODEL─▶ [KSampler]
                          │    lora_1: 妃咲.safetensors                0.6 / 0.6
                          │    lora_2: silver_wolf_lv999_comfy_v2...   0.8 / 0.8
                          │    lora_3: 不使用 / none                   ─CLIP──▶ [CLIPTextEncode]
                          │    lora_4: 不使用 / none                          │
                          │    (advanced) batch text: (empty)                 ▼
                          └─CLIP──────────────────────────────────  trigger_words (text)
```

| Direction | Name | Type | Description |
| --- | --- | --- | --- |
| Input | `lora_1` … `lora_4` | combo (dropdown) | Four LoRA dropdown rows, filled from your LoRA roots (subfolders included). The first entry is `不使用 / none` (= `loader.SLOT_NONE`), which means "this row loads nothing" |
| Input | `strength_1` … `strength_4` | FLOAT | **MODEL strength** of the matching row: `default 1.0`, `min -100`, `max 100`, **`step 0.1`**. The arrows step by 0.1 and you can type a value directly. `1.0` = unchanged, `0` = no effect, negative = inverted |
| Input | `clip_strength_1` … `clip_strength_4` | FLOAT | **CLIP strength** of the matching row — same spec (`default 1.0`, `min -100`, `max 100`, `step 0.1`) and a **separate box** from the MODEL strength, exactly like the built-in `LoraLoader`. Set both boxes equal if you want them identical |
| Input | `lora_list` | STRING (multiline, **optional**) | Labelled **"(advanced) batch text"** in the UI: paste more than 4 LoRAs or a bulk list here. Not required — see the syntax below |
| Input | `model` | MODEL (optional) | Base model to patch. Leave unconnected to only output trigger words |
| Input | `clip` | CLIP (optional) | CLIP to patch as well. Connect `model` and `clip` for the classic behaviour |
| Output | `model` | MODEL | The model with every selected LoRA applied |
| Output | `clip` | CLIP | The CLIP with every selected LoRA applied |
| Output | `trigger_words` | STRING | Trigger words of every selected LoRA, merged — wire it into `CLIPTextEncode.text` |
| Output | `report` | STRING | Loading report (what was applied, cached, skipped or failed) + the trigger-word match summary |

**Load order: dropdown rows `lora_1` → `lora_4` first, then the "(advanced) batch text" box.**

"(advanced) batch text" syntax (`lora_list`, one entry per line; `#`, `//` and `--` comment lines are ignored, as is a trailing `# note`):

```
妃咲.safetensors              # model and clip both get 1.0
妃咲.safetensors: 0.8         # both get 0.8
妃咲.safetensors: 0.8, 0.5    # model 0.8 / clip 0.5
妃咲.safetensors @ 0.8        # "@" works like ":"
妃咲.safetensors, 0.8         # comma form
a.safetensors 0.8             # space form (only split when the left part really looks like a LoRA)
<lora:妃咲.safetensors:0.8>   # A1111 style
妃咲.safetensors, silver_wolf.safetensors   # two LoRAs on one line
妃咲                          # bare names are completed to their relative path
```

- Strengths are clamped to `[-100, 100]` and out-of-range values are reported as a warning (never an error).
- The same LoRA written twice is loaded **twice** (stacks are intentional here).
- More than 64 entries are truncated, with a warning.
- **Auto-detection:** only when **both the dropdowns and the batch text box are empty** does the node apply the LoRAs found upstream on the `model` wire, in model-flow order (far → near). The report then says `已自动使用 model 接入链路上的 LoRA（按模型流向依次加载，共 N 个）`.
- With neither `model` nor `clip` connected, nothing is loaded at all (no file is even read) and the node still outputs the trigger words.
- Read LoRA tensors are kept in a small LRU cache (4 entries) so a LoRA reused by two nodes in the same run is only read from disk once.

### 2. `LoRA 触发词读取·自动 (LoRA Trigger Reader)`

**Automatic, single.** Reads the **nearest** LoRA node on the connected chain — drop it to the right of the `LoraLoader` whose trigger words you want.

| Direction | Name | Type | Description |
| --- | --- | --- | --- |
| Input | `model` | MODEL (required) | Connect the `MODEL` output of your LoRA loader here. Passed through unchanged |
| Input | `extra_loras` | STRING (multiline, optional) | Manual supplement (see below); leave empty in normal use |
| Output | `model` | MODEL | The same model that came in |
| Output | `trigger_words` | STRING | Cleaned one-line trigger words; wire it into `CLIPTextEncode.text` |
| Output | `report` | STRING | Human-readable report (which chain was detected, which file matched, size, encoding, score) |

Controls (all optional): `separator`, `deduplicate`, `strip_comments`, `on_missing`, `fallback_text`, `extra_dirs`, `refresh_cache` — see the [parameter reference](#parameter-reference).

Node function declares two **hidden inputs**, `unique_id` (`UNIQUE_ID`) and `prompt` (`PROMPT`) — that is how it receives its own node id and the raw workflow so it can probe upstream. It deliberately **does not use `DYNPROMPT`**: older ComfyUI versions do not know that type, drop the parameter, and the node then fails with a `TypeError`.

### 3. `LoRA 触发词读取·自动多选 (LoRA Trigger Reader Multi)`

**Automatic, multi.** Same as above, but reads **every** LoRA on the chain and concatenates their trigger words in load order.

| Direction | Name | Type | Description |
| --- | --- | --- | --- |
| Input | `model` | MODEL (required) | Connect the `MODEL` output of the last LoRA loader here |
| Input | `extra_loras` | STRING (multiline, optional) | Manual supplement |
| Output | `model` | MODEL | The same model that came in |
| Output | `trigger_words` | STRING | Trigger words of all detected LoRAs, in order |
| Output | `report` | STRING | Chain line + per-LoRA match summary |

`extra_loras` is very forgiving — it takes LoRAs the chain probe could not see (e.g. loaded by a third-party node or a sub-workflow), and it doubles as a scratchpad for plain trigger text:

```
# one per line, comment lines are ignored
Anima/角色lora/silver_wolf_lv999_comfy_v2.safetensors
Krea2/Krea2角色lora/妃咲.safetensors

# a bare filename is auto-completed to the relative path
妃咲.safetensors

# even just the character name works
妃咲

# when every segment resolves to a known LoRA, a single comma-separated line is fine
silver_wolf_lv999_comfy_v2.safetensors, 妃咲.safetensors

# plain trigger words also work — anything that resolves to no LoRA is used as literal text
masterpiece, best quality
```

### 4. `LoRA 触发词查看 (LoRA Trigger Info)`

Manual lookup — **no MODEL input and no MODEL output**. Pick a LoRA from the dropdown and read its trigger words; connect a "Show Text" node and queue once to see what it actually resolves to.

| Direction | Name | Type | Description |
| --- | --- | --- | --- |
| Input | `lora_name` | combo | LoRA to inspect (list comes from your `models/loras`) |
| Output | `trigger_words` | STRING | Trigger words |
| Output | `report` | STRING | Report |

---

## Automatic upstream detection

This is the mechanism behind v1.1 (`lora_trigger_reader/graph_probe.py`), and it is deliberately conservative.

- Starting from the reader node's own id, it walks **the upstream link of the `model` input** depth-first, **nearest first** (`MAX_DEPTH = 64`, `MAX_NODES = 256`). Branches not connected to this node are ignored, and cyclic workflows terminate normally.
- On each upstream node it collects only inputs whose name looks like a LoRA *name* **and** is safely shaped: `lora`, `lora_name`, `lora_names`, `lora_path`, `lora_file`, `lora_filename`, `lora_stack`, `lora_stacks`, `loras`, plus third-party numbered forms such as `lora_1_name`, `lora_name_1`, `lora_1`, `lora_1_path`.
- That is also how v1.3 makes the multi loader visible downstream: the dropdown names `lora_1` … `lora_4` are recognised as LoRA inputs and the `不使用 / none` sentinel is treated as "not selected", so on a `CheckpointLoader → LoRAMultiLoader → LoRATriggerReader` chain the reader node sees the LoRAs picked in the loader's dropdowns, in row order 1 → 4.
- Keys that are **explicitly excluded** as "not a name": `lora_strength`, `lora_weight`, `lora_model` and friends.
- It understands a **widget converted into an input socket**: if the value is a link, it follows the link and picks up the string on a `PrimitiveNode` — and only trusts it when there is **exactly one** candidate value there.
- Names are normalised: `\` → `/`, split on newlines / commas / semicolons / `、`, surrounding quotes stripped, and `#` comment tails dropped.

The probe is why "the LoRA you actually loaded" is authoritative: change the `LoraLoader` upstream and the reader follows automatically, with no stale selection to forget.

---

## Quick start

### Single LoRA

```
CheckpointLoaderSimple ──MODEL──▶ LoraLoader ──MODEL──▶ LoRATriggerReader ──MODEL──▶ KSampler
                                       │                        │
                                       └──CLIP──┐               └──trigger_words──▶ CLIPTextEncode(text) ──▶ KSampler(positive)
                                                └──▶ CLIPTextEncode(negative)
```

1. Add a `LoRA 触发词读取·自动` node and place it to the **right** of the `LoraLoader`;
2. Connect the `LoraLoader`'s **MODEL** output to the node's `model` input — the node now reads that LoRA automatically (you can check the status line on the node, e.g. `🔎 检测到 1 个 LoRA: silver_wolf.safetensors`);
3. Wire `model` → `KSampler` and `trigger_words` → the positive `CLIPTextEncode`'s `text` input (convert that widget into an input slot).

### Multiple LoRAs

```
LoraLoader(A) ──MODEL──▶ LoraLoader(B) ──MODEL──▶ LoRATriggerReaderMulti ──MODEL──▶ KSampler
                                                          └──trigger_words──▶ CLIPTextEncode(positive)
```

Put the multi node at the end of the chain and connect the last `LoraLoader`'s MODEL output to its `model` input. Its status line shows both LoRAs (`🔎 检测到 2 个 LoRA: A, B`) and `trigger_words` contains both sets of trigger words concatenated in load order. Nothing to select by hand.

### Several LoRAs without a chain (v1.3)

Use one `LoRAMultiLoader` instead of N `LoraLoader` nodes:

```
CheckpointLoader ─MODEL─▶ LoRAMultiLoader ─MODEL─▶ KSampler
                          └─CLIP───────────▶ CLIPTextEncode
   lora_1: 妃咲.safetensors                    → 0.6 / 0.6
   lora_2: silver_wolf_lv999_comfy_v2.saf...  → 0.8 / 0.8
   lora_3: 不使用 / none
   lora_4: 不使用 / none
```

Connect `model` and `clip` from the checkpoint loader, pick your LoRAs in the dropdown rows (and set each row's MODEL / CLIP strength — the arrows step by 0.1), then read the trigger words off the `trigger_words` output. More than four? Paste the rest into the "(advanced) batch text" box — it loads after the dropdown rows. A downstream `LoRATriggerReader` also sees the rows you picked, so you can keep using the reader nodes for the text processing (separator, dedup, comments, `on_missing`).

### When the chain cannot be detected

If your LoRA is loaded by a node the probe does not recognise, press **🎯 手动补充 LoRA（触发词选择器）**, tick what you need, and the names are written into `extra_loras`. Automatic detection still comes first when both are present.

### Just look, don't run

Use `LoRA 触发词查看` + a "Show Text" node.

---

## Trigger-file naming rules (important)

The plugin scans **every subdirectory** of `models/loras` for `.txt` and `.md` files, scores each candidate, and **uses the highest-scoring one**.

| Score | Condition | Example |
| --- | --- | --- |
| **1000** | Text filename (extension included) equals the LoRA filename | `silver_wolf.safetensors` ↔ `silver_wolf.safetensors.txt` |
| **980** | Equal after stripping extensions | `silver_wolf.safetensors` ↔ `silver_wolf.txt` |
| **950** | Equal after stripping a "suffix word" | `...silver_wolf_lv999_comfy_v2.safetensors` ↔ `...silver_wolf_lv999_comfy_v2提示词.txt` |
| **900** | Text name starts with the LoRA name | `妃咲.safetensors` ↔ `妃咲-全身图.txt` |
| **850** | Text name contains the full LoRA name | `Anima尼可.safetensors` ↔ `推荐_Anima尼可_v2.txt` |
| **800** | LoRA name contains the text name | `silver_wolf_v2.safetensors` ↔ `silver_wolf.txt` |
| **600–690** | Fuzzy: `difflib` ratio ≥ 0.90 (score = 600 + 100 × ratio) | minor typos |
| **+25** | Text file is **in the same subdirectory** as the LoRA | same-dir candidates win over namesakes elsewhere |
| **0** | Ownership conflict: the file clearly belongs to another LoRA | see below |
| **< 700** | Treated as "no match"; the node outputs an empty string | |

Matching ignores case and these characters: space, `_`, `-`, `·`, `．`, `.`, `、`, `,` (so `Silver_Wolf` and `silver wolf` are the same name).

> These rules are identical in v1.0, v1.1, v1.2 and v1.3 — only the way the LoRA name reaches the matcher changed.

### Suffix words (the 950 tier)

If stripping one of these leaves exactly the LoRA name, it scores 950:

```
触发词 提示词 关键词 说明 备注 词 語 语
triggerword triggerwords trigger triggers
prompt prompts keyword keywords
activation activate activationwords words word
tag tags info note notes readme read
```

> Example: `Anima尼可提示词.txt` for the LoRA `Anima尼可.safetensors` — strip `提示词`, names match → hit.

### Ownership check (no stealing)

When the score is below 950 (i.e. not an exact name match), the plugin asks itself: **would this text file suit some other LoRA better?**

Say you have `A.safetensors` and `AB.safetensors` plus `AB提示词.txt`. Without the check, reading `A` could grab `AB提示词.txt` through the "contains" rule. With the check, `AB提示词.txt` belongs only to `AB`, and reading `A` scores 0 and correctly returns an empty string.

On top of that, **very short names are excluded from prefix/contains matching**: a LoRA called `a.safetensors` will not steal `abc.txt` (rule: a name participating in prefix/contains matching needs at least 4 characters, or at least 2 characters if it contains CJK ideographs, e.g. `妃咲`).

---

## Parameter reference

The four nodes share one set of optional controls. The differences in inputs are `extra_loras` (automatic nodes), `lora_name` (info node), and the four dropdown rows + their strengths + the optional "(advanced) batch text" box + optional `model` / `clip` (multi loader).

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `separator` | STRING | `", "` | Joins multiple trigger lines. Use `"\n"` for a real newline; leave empty for no separator |
| `deduplicate` | BOOLEAN | `True` | Drop duplicate trigger words (case-insensitive) |
| `strip_comments` | BOOLEAN | `True` | Ignore lines starting with `#`, `//` or `--` |
| `on_missing` | choice | `empty` | What to output when no trigger file is found: `empty` → empty string / `lora_name` → the LoRA name without extension / `custom` → `fallback_text` |
| `fallback_text` | STRING (multiline) | empty | Text used when `on_missing = custom` |
| `extra_dirs` | STRING | empty | Extra directories to scan, separated by `;` or newlines. Useful when trigger files live outside the LoRA folder |
| `refresh_cache` | BOOLEAN | `False` | Force a rescan for this run (normally an 8-second cache is used) |

Automatic-node-only input:

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `extra_loras` | STRING (multiline) | empty | Manual supplement: LoRAs the upstream probe cannot see, or plain trigger text. Leave empty in normal use. A strength suffix (`: 0.8`, `@ 0.8`, `, 0.8`, the space form, `<lora:name:0.8>`) is stripped before matching |

Multi-loader-only inputs (v1.3):

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `lora_1` … `lora_4` | combo | `不使用 / none` | One LoRA per dropdown row (LoRA roots incl. subfolders); `不使用 / none` skips the row |
| `strength_1` … `strength_4` | FLOAT | `1.0` | MODEL strength of that row, `min -100`, `max 100`, `step 0.1` (typeable) |
| `clip_strength_1` … `clip_strength_4` | FLOAT | `1.0` | CLIP strength of that row — a separate box, same spec |
| `lora_list` | STRING (multiline) | empty | Optional **"(advanced) batch text"**: bulk `name: strength` lines, loaded **after** the dropdown rows |
| `model` / `clip` | MODEL / CLIP | — | Optional; connect neither and only the trigger words are output |

Internal (hidden) inputs, not shown in the UI:

| Hidden input | Type | Description |
| --- | --- | --- |
| `unique_id` | UNIQUE_ID | This node's id, used to find itself in the workflow |
| `prompt` | PROMPT | The raw API-format workflow, used to walk the `model` wire upstream |

(`DYNPROMPT` is intentionally **not** used — see [Nodes](#nodes).)

**Loader-specific rows in the report** (v1.3):

```
LoRATriggerReader v1.3.0
[多重加载器] 已加载 2 个 LoRA：妃咲.safetensors(0.6), silver_wolf_lv999_comfy_v2.safetensors(0.8)
其中 1 个直接用了内存缓存。
共 2 个 LoRA | 有触发词 2 | 空文件 0 | 未匹配 0
[1] 妃咲.safetensors -> Krea2/Krea2角色lora/妃咲.txt (290 字/utf-8, 分数 1005)
[2] silver_wolf_lv999_comfy_v2.safetensors -> Anima/角色lora/silver_wolf_lv999_comfy_v2提示词.txt (89 字/utf-8, 分数 975)
```

Other shapes you may see on the first line: `[多重加载器] 已自动使用 model 接入链路上的 LoRA（按模型流向依次加载，共 N 个）。` (both the dropdown rows and the batch text box are empty), `[多重加载器] MODEL / CLIP 都没接，跳过加载 N 个 LoRA（触发词照常输出）。`, `[多重加载器] 加载失败：xxx -> 原因`, and `[多重加载器] 注意：…` for warnings (clamped strength, truncated list).

**About the `report` output** — it looks like this, and makes debugging easy:

```
LoRATriggerReader v1.3.0
[接入链路] 检测到 #3 LoraLoader -> Krea2/Krea2角色lora/妃咲.safetensors；#2 LoraLoader -> Anima/角色lora/silver_wolf_lv999_comfy_v2.safetensors
共 2 个 LoRA | 有触发词 2 | 空文件 0 | 未匹配 0
[1] 妃咲.safetensors -> Krea2/Krea2角色lora/妃咲.txt (290 字/utf-8, 分数 1005)
[2] silver_wolf_lv999_comfy_v2.safetensors -> Anima/角色lora/silver_wolf_lv999_comfy_v2提示词.txt (89 字/utf-8, 分数 975)
```

The second line is the **chain line** — which upstream nodes were found and which LoRA each of them selected. Its three possible shapes:

```
[接入链路] 检测到 #3 LoraLoader -> Krea2/Krea2角色lora/妃咲.safetensors；#2 LoraLoader -> ...
[接入链路] 没有检测到 LoRA 节点（上游可能是 CheckpointLoader 直连）。
[接入链路] 无法反查工作流（原因），只能使用手动填写的 LoRA。
```

Then comes the **totals header** — `共 N 个 LoRA | 有触发词 ok | 空文件 empty | 未匹配 missing`, with `| 找不到文件 nofile`, `| 兜底 fallback` and `| 异常 failed` appended only when those counts are non-zero — followed by one detail line per LoRA.

(The report is in Chinese: chain line, totals line, then one line per LoRA with the matched file, character count, encoding and score.)

---

## Frontend bonus: the picker and the help panel

Extra buttons are added to the nodes (**frontend only — if it breaks, node execution is unaffected**):

| Button | Where | What it does |
| --- | --- | --- |
| 🎯 手动补充 LoRA（触发词选择器） | automatic nodes | Opens the picker; what you tick is written into `extra_loras` |
| 🔄 重新扫描链路 / LoRA 文本 | automatic nodes | Clears the caches, re-probes the chain and rescans the LoRA text directories |
| 🎯 选择 LoRA（写入下拉框） | multi loader | Opens the picker; after "应用" the **first 4 ticks** are written into the `lora_1` … `lora_4` dropdown rows and the overflow goes into the "(advanced) batch text" box. Lines that were moved into a dropdown are **removed** from the batch box so no LoRA is loaded twice, and any strength suffix already typed in the batch box is preserved |
| 🔄 重新扫描 LoRA 文本 | multi loader | Rescans the LoRA text directories |
| 🎯 选择 LoRA（含触发词预览） | info node | Opens the picker in single mode (writes back to the `lora_name` combo) |
| 📄 查看该 LoRA 的触发词文本 | info node | Pops up the trigger text directly, **without running the workflow** |
| ❓ 使用说明 / Help | all four nodes | Opens the bilingual manual panel (see below) |

On top of that, the automatic nodes **and the multi loader** draw a status line at the bottom of the node so you can see at a glance what they found:

| Status line | Meaning |
| --- | --- |
| `🔎 检测到 N 个 LoRA: a, b` | The chain was probed successfully and N LoRAs were found (green) |
| `🔎 未接入 MODEL…` | Nothing is connected to the `model` input yet |
| `🔎 已接入，但链路上没识别到 LoRA` | Something is connected, but no LoRA selector was found upstream |
| `🔎 将加载 N 个 LoRA（下拉框 M 行）: a, b` | (multi loader) the dropdown rows / batch text box load N LoRAs, M of them from dropdown rows |
| `🔎 下拉框和批量文本都为空，自动加载链路 N 个 LoRA: …` | (multi loader) both the dropdowns and the batch text are empty, so the upstream chain is used |
| `🔎 下拉框和批量文本都为空，链路上也没识别到 LoRA（只输出触发词）` | (multi loader) nothing is selected and the chain has no LoRA either, so only trigger words are output |

The line refreshes by itself when connections change (the detection result is cached for 1 second).

Inside the panel you can:

- search by LoRA name / path;
- filter by "has trigger words / no trigger words / selected only / detected on the chain";
- read the per-row badge: **有触发词** (green) / **空文件** (yellow) / **无触发词** (grey) / **找不到 LoRA** / **出错** (red), plus a **链路** badge for rows that were detected on the `model` connection;
- hover a badge to see the matched file path and a content preview;
- press "选定链路项" to tick everything the chain probe found;
- tick rows and press "应用" — on the automatic nodes the selection is written back as newline-separated lines into `extra_loras` (in the info node into `lora_name`, taking the first ticked item); on the multi loader the first 4 ticks go into the `lora_1` … `lora_4` dropdown rows and the rest into the "(advanced) batch text" box;
- use "全选当前列表" (info node: "选中第一个") / "清空" for bulk operations.

Data comes from `GET /lora_trigger_reader/list`. If that route is unavailable the script falls back to `api.getNodeDefs()`, which only yields LoRA **names** (rows are then marked as a fallback list, with no trigger-word information).

> The script uses **dynamic import with layered fallbacks** (modern `scripts/app.js` → `window.comfyAPI` → `window.app`). Any failure only means the buttons do not appear plus a console warning; the node keeps working.

---

## Text processing details

| Case | Handling |
| --- | --- |
| Encoding | BOM detection first (UTF-8-sig / UTF-16 / UTF-32), then tried in order: UTF-8 → GB18030 (a GBK superset) → UTF-16 → Latin-1 (never fails); the report tells you which one was used |
| Empty file (0 bytes) | Status `empty`, outputs an empty string, **no error** (very common in real LoRA packs) |
| Blank / whitespace-only lines | Dropped |
| Comment lines (`#` / `//` / `--`) | Dropped when `strip_comments = True` |
| Trailing `,` `，` `;` `；` `、` | Trimmed per line (so a trailing comma never produces a stray `, ,`) |
| Duplicate trigger words | Deduplicated when `deduplicate = True` (case-insensitive) |
| Huge files | Only the first 1 MiB is read and the report is flagged as truncated |
| Skipped directories | `.git` `.github` `__pycache__` `node_modules` `.idea` `.vscode` `.cache` `.trash` `$RECYCLE.BIN` `System Volume Information` |
| Directory caching | Text index cached for 8 seconds; `refresh_cache` or the frontend "rescan" button forces a refresh |
| File content changes | `IS_CHANGED` (path + size + mtime) makes ComfyUI re-run this node |

---

## HTTP endpoints

Three read-only endpoints are registered for the frontend and for scripting (no auth, local use only):

| Endpoint | Parameters | Returns |
| --- | --- | --- |
| `GET /lora_trigger_reader/list` | `refresh=1` force rescan; `preview=0` omit previews; `extra_dirs=...` extra dirs | Per LoRA: `name` / `base` / `status` / `trigger_rel` / `chars` / `encoding` / `score` / `preview` … |
| `GET /lora_trigger_reader/text` | `lora_name=xxx` (bare filename or full relative path) | `text`, `status`, matched `trigger_rel`, `candidates` |
| `GET /lora_trigger_reader/help` | `node=` (v1.3: `help` / `common` / `LoRAMultiLoader` / `LoRATriggerReader` / `LoRATriggerReaderMulti` / `LoRATriggerReaderInfo`) | `zh` + `en` documentation text, the node title in both languages, and the list of documented nodes |

All three endpoints set `Cache-Control: no-store` and **always return JSON with an `ok` field instead of ever raising**, so they can never take ComfyUI down with a 500. Previews are capped at 120 characters, and files larger than 256 KiB are skipped for preview (they are still read by the node itself). `/help` is what the frontend "❓ 使用说明 / Help" button calls; an unknown `node` value still returns `ok: true` with the overview text and `exists: false`.

---

## Example workflow

`examples/example_workflow.json` (v1.3, 13 nodes / 18 links) can be dragged straight onto the ComfyUI canvas:

- `CheckpointLoaderSimple` → `LoraLoader(silver_wolf)` → `LoraLoader(妃咲)` → `LoRATriggerReaderMulti` → `KSampler`;
- the last `LoraLoader` also feeds the **`LoRAMultiLoader`** (MODEL **and** CLIP), whose dropdown rows already preselect two example LoRAs with their strengths — `Anima\角色lora\silver_wolf_lv999_comfy_v2.safetensors` (0.8 / 0.8) and `Krea2\Krea2角色lora\妃咲.safetensors` (0.6 / 0.6) — a ready-made demo of the v1.3 loader (its node has 20 `widgets_values`: the 12 dropdown/strength widgets, the "(advanced) batch text" box and the 7 shared options);
- the `LoRAMultiLoader`'s MODEL output branches into a single-select `LoRATriggerReader`, so you can compare the two nodes side by side;
- `trigger_words` is wired into the positive `CLIPTextEncode`'s `text`;
- a Chinese `Note` node inside the graph explains the steps.

> After opening it, replace the checkpoint and the LoRAs with ones you actually have.

---

## Upgrading

**From v1.0** — nothing to do beyond reconnecting, and nothing breaks silently:

- The automatic nodes have **no `lora_name` / `lora_names` widget any more** — a workflow saved with v1.0 keeps its stored widget values, but the node ignores them. Just connect the upstream `LoraLoader` MODEL output to `model` and it works.
- The info node (`LoRA 触发词查看`) is unchanged — it still has a `lora_name` dropdown.
- The matching rules, scoring, encodings, caching and HTTP endpoints are all the same as v1.0.
- If the probe cannot see your LoRA (third-party loader, sub-workflow), put the name into `extra_loras`, or open the picker and use "选定链路项" / tick manually.

**From v1.1** — drop-in, existing workflows keep working:

- The reader nodes' inputs and outputs are unchanged; the frontend just gained one more button (❓ 使用说明 / Help).
- `LoRAMultiLoader` is new, so it is simply absent from workflows saved before v1.2. Add one and connect `model` / `clip` if you want it.
- The reader nodes recognise `lora_list` as a LoRA input name, so a reader placed after the new loader sees its LoRAs. (The strength tail of those entries was *claimed* to be stripped in v1.2 but was not — that is the bug fixed in v1.3, see below.)
- A graph that used to need N chained `LoraLoader` nodes can now be replaced by one `LoRAMultiLoader` — optional, not required.

**From v1.2 → v1.3** — one thing to redo after upgrading:

- **Re-pick the LoRA rows in the `LoRAMultiLoader` after upgrading.** A v1.2 workflow stored the node's widget values **by position**; v1.3 puts the 12 dropdown/strength widgets first, so those old values land on `lora_1` and look scrambled.
- The old `lora_list` text is **not deleted** and is still loaded (the box is now the optional "(advanced) batch text" field), so nothing is lost — but the dropdowns must be re-selected by hand.
- Trigger words with a strength suffix now work. In v1.2 a line like `妃咲: 0.8` in `extra_loras` produced **empty** trigger words (the old `scan.parse_lora_text` never stripped the strength, so the short name fell below the 700-point match threshold). Both reader nodes and the loader now parse through `loader.parse_specs` / `split_strengths`, so `妃咲.safetensors: 0.8` and `妃咲.safetensors 0.8` both read their trigger words — the strength only locates the file and is ignored when reading.

---

## FAQ

**Q: The nodes do not appear in the menu.**
Check the ComfyUI console for `加载失败` / `Traceback`. This plugin logs with the `[LoRATriggerReader]` prefix. The most common cause is one directory level too many (`custom_nodes/xxx/ComfyUI-LoRATriggerReader/`) — `__init__.py` must be directly inside `custom_nodes/ComfyUI-LoRATriggerReader/`.

**Q: I have a trigger file but the node outputs nothing.**
Add a `LoRA 触发词查看` node with a text display and read `report`:

- "未匹配" (no match) → the filename does not follow the rules; see the [score table](#trigger-file-naming-rules-important);
- "空文件" (empty file) → your txt is 0 bytes; fill it in;
- "找不到文件" (file not found) → the LoRA name is not in the directory (possibly a stale cache); tick `refresh_cache` or press the frontend "rescan" button.

**Q: The node status line says `检测到 1 个 LoRA: [object Object]`.**
That happened when the upstream LoRA node stores something other than a plain string in its widget — e.g. rgthree's **Power Lora Loader**, whose input holds `{on: true, lora: "x.safetensors", strength: 0.8}`. **Fixed in v1.3**: both the frontend and the backend now parse such structured values by field name (`lora` / `name` / `value` / `path` …) and skip boolean / weight fields (`on`, `strength`, …), so the status line and the `report` always show the real file name instead of a `String()`-ified object. Refresh the page (or restart ComfyUI) to pick the fix up.

**Q: Nothing is detected on the chain / the node says `🔎 未接入 MODEL…`.**
That means the `model` input has no wire. Connect the `MODEL` output of the LoRA loader that you want read. If the node instead says `🔎 已接入，但链路上没识别到 LoRA`, the LoRA is probably selected by a node whose input names the probe does not recognise (for example a sub-workflow) — fill in `extra_loras`, or use the picker and press "选定链路项".

**Q: I upgraded to v1.1 and my old `lora_names` list is ignored.**
By design: v1.1 reads the chain instead. Reconnect the MODEL wire; if you really need those names, move them into `extra_loras`.

**Q: How do I load several LoRAs without chaining `LoraLoader` nodes?**
Use one `LoRAMultiLoader`: connect `model` and `clip`, then pick your LoRAs in the `lora_1` … `lora_4` dropdown rows and set each row's MODEL and CLIP strength (the arrows step by 0.1, or type a value; set both boxes equal to make them behave identically). Rows left at `不使用 / none` load nothing. Need more than four? Paste the rest into the optional "(advanced) batch text" box — it loads after the dropdown rows. Its `trigger_words` output gives you the matching trigger words at the same time. In v1.1 and earlier you had to chain N loaders.

**Q: I put a LoRA name with a strength into `extra_loras` (e.g. `妃咲: 0.8`) and the trigger words came out empty.**
That was a real bug in v1.2, fixed in v1.3: the automatic reader nodes parsed `extra_loras` with the old `scan.parse_lora_text`, which never stripped a strength suffix, so a short name like `妃咲: 0.8` failed every containment-match tier and scored below 700 → empty text. Both reader nodes and the loader now parse through `loader.parse_specs` / `split_strengths`, so `: 0.8`, `@ 0.8`, `, 0.8`, the space form `妃咲.safetensors 0.8` and `<lora:name:0.8>` are all stripped, and `妃咲.safetensors: 0.8` reads its trigger words. The strength is only used to locate the file — it is ignored when reading the text. Upgrade to v1.3 to get the fix.

**Q: After upgrading, my `LoRAMultiLoader` dropdowns look scrambled.**
That is expected for a workflow saved with v1.2: it stored the node's widget values **by position**, and v1.3 inserts the 12 dropdown/strength widgets in front of them, so the old values land on `lora_1`. **Re-pick the LoRA rows** in the node (the old `lora_list` text is not deleted and is still loaded, so nothing is lost).

**Q: The loader reports `加载失败：xxx -> 找不到该文件`.**
The name is not in the LoRA directory list — for a dropdown row that means the file was added after the list was built, so press "🔄 重新扫描 LoRA 文本"; for the "(advanced) batch text" box, put the relative path (`folder/name.safetensors`) or the exact filename there (a bare name is completed to its relative path when the scanner can find it).

**Q: I connected neither `model` nor `clip` to the multi loader — is that an error?**
No. It then loads nothing (it does not even read the LoRA files) and still outputs the trigger words, which is handy when you only want the text of several LoRAs.

**Q: Does the loader load the same LoRA twice if I write it twice?**
Yes, and that is intentional — repeated lines in the "(advanced) batch text" box (or the same LoRA picked in two dropdown rows) stack it again, and the read tensor is served from the LRU cache, so the file is read from disk only once. It is also why the picker **removes** batch-box lines that it moved into a dropdown row.

**Q: Why does the loader clamp my strength?**
Strengths are clamped to `[-100, 100]`; anything outside is reported as `[多重加载器] 注意：…` in the `report` output and applied as the clamped value, so a typo never fails the run. This applies to the batch-box text and to the dropdown strength boxes — in the UI, `strength_N` / `clip_strength_N` are FLOAT widgets with `min -100`, `max 100` and `step 0.1`, so the arrows step by 0.1 and you can also type an exact value.

**Q: Where is the in-ComfyUI documentation?**
Press **❓ 使用说明 / Help** on any node (v1.3). The panel fetches `/lora_trigger_reader/help` and offers a language switch (中文 / English) plus a node selector covering the overview page and all four nodes. The same text also appears as the node tooltip and as per-port tooltips.

**Q: Why do I get `, ,` in my prompt?**
Trailing commas in the trigger file are trimmed automatically. If a single line contains many comma-separated words, that line is kept as one entry by design. Write one entry per line if you want them split.

**Q: Mojibake / garbled Chinese.**
The plugin detects a BOM first, then tries UTF-8 → GB18030 (a GBK superset) → UTF-16 → Latin-1. If it is still garbled, re-save the trigger file as UTF-8.

**Q: My trigger files are not inside the LoRA directory.**
Put those directories in `extra_dirs`, separated by `;` or newlines. The same-directory bonus (+25) only applies to the LoRA's own directory; files in extra directories still match normally.

**Q: I only want the trigger words of one of several LoRAs.**
Use the single (`·自动`) node in the right place — it takes only the nearest LoRA on the chain. If that LoRA is not the nearest one, use the multi node and list just that name in `extra_loras` instead.

**Q: The LoRA content changed but the output did not.**
Trigger text changes are picked up through `IS_CHANGED`. If that does not kick in, tick `refresh_cache` or press the frontend "rescan" button.

**Q: Does this load the LoRA twice?**
No. The node only passes the model through; the LoRA is loaded by the upstream `LoraLoader`.

---

## Compatibility and testing

| Item | Status |
| --- | --- |
| Tested on | ComfyUI **0.38.0** + `comfyui_frontend_package` **1.53.10** + Python **3.12.10** (Windows) |
| Python versions | Code targets **3.9+** (`from __future__ import annotations`) |
| Node definition style | V1 `INPUT_TYPES` / `NODE_CLASS_MAPPINGS` (not the V3 schema), understood by old and new ComfyUI; no V3-only feature is used |
| Frontend API | `app.registerExtension` + `addWidget("button")` with layered dynamic-import fallbacks and silent degradation |
| Real-world validation | Run against a real folder with 137 LoRAs and 58 trigger files: 54 correct matches, 1 empty file detected, 82 genuinely without trigger words, zero wrong matches |
| Real-world auto-probe | Verified on a real machine: on a chain of two `LoraLoader` nodes, `妃咲` (score 1005) and `silver_wolf_lv999_comfy_v2` (975) were both read out correctly |
| Real-world multi loader | Verified on the same machine: `lora_list` / dropdown-row strengths parsed against the real directory, a real 512-key `.safetensors` loaded through `load_tensor_cached` (0.04 s first time, 0.0000 s from cache), two real LoRAs applied to MODEL+CLIP, and a nonexistent name only produced a `加载失败` report line |
| Real-world help / install | Loaded from `custom_nodes/ComfyUI-LoRATriggerReader` exactly the way ComfyUI loads it (no `submodule_search_locations`): 4 nodes registered, and `/lora_trigger_reader/help` returns Chinese **and** English text for all six node keys (unknown key → `ok: true`, `exists: false`) |
| Unit tests | **228** test cases, all green (`test_lora_scan.py` 44, `test_graph_probe.py` 39, `test_loader.py` 56, `test_nodes_api.py` 89). Run with `python -m unittest discover -s tests` from the extension folder |

Edge cases covered: empty files, GBK/UTF-16/BOM encodings, truncation past 1 MiB, comment lines, full-width trailing commas, duplicate words, ownership conflicts, short-name hijacking, `extra_dirs`, the three `on_missing` strategies, comma-separated multi-LoRA lines, auto-completion of bare filenames / character names, widget-to-input conversion, cyclic graphs, and unknown input names on the chain. The loader additionally covers strength parsing (colon / full-width colon / `@` / comma / space form / A1111 `<lora:…>`), strength-suffix stripping in `extra_loras`, out-of-range clamping, the 64-entry cap, missing files, cache hits and eviction, the four dropdown slots (including the `不使用 / none` sentinel and their per-row MODEL / CLIP strengths), the "neither MODEL nor CLIP connected" path, and structured (dict / list) LoRA widget values from third-party loaders such as rgthree's Power Lora Loader — those are parsed by field name (`lora` / `name` / `value` / `path`…, never `on` / `strength`), so the node status line shows the real file name instead of `[object Object]`.

---

## Project layout

```
ComfyUI-LoRATriggerReader/
├── __init__.py                    # ComfyUI entry: node registration + WEB_DIRECTORY + HTTP routes
├── lora_trigger_reader/           # Prefixed package name so it cannot clash with someone's py/ or utils/
│   ├── __init__.py
│   ├── graph_probe.py             # v1.1: walks the model wire upstream to find the LoRA(s) on the chain
│   ├── help_docs.py               # v1.2: the bilingual node documentation served by /lora_trigger_reader/help
│   ├── loader.py                  # v1.2: multi-LoRA loading / v1.3: the four dropdown slots + per-row strengths (parse specs, apply to MODEL+CLIP, cache)
│   ├── lora_scan.py               # Core logic: scanning, scoring, reading, formatting (no torch)
│   ├── nodes.py                   # The four node definitions (V1 INPUT_TYPES)
│   └── api.py                     # HTTP routes /lora_trigger_reader/list, /text and /help
├── web/
│   └── js/
│       └── lora_trigger_reader.js # Frontend buttons, status line, picker panel and help panel
├── examples/
│   └── example_workflow.json      # Drag-and-drop example workflow (v1.3)
├── tests/
│   ├── test_graph_probe.py        # Upstream chain probe tests
│   ├── test_loader.py             # v1.2: lora_list parsing and LoRA application tests / v1.3: dropdown slot + strength tests
│   ├── test_lora_scan.py          # Core matching/reading tests
│   ├── test_nodes_api.py          # Nodes, HTTP, simulated ComfyUI loading
│   └── integration_real_loras.py  # Optional self-check against a real LoRA folder
├── README.md                      # English documentation (this file, GitHub default)
├── README.zh-CN.md                # Chinese documentation
├── requirements.txt               # Dependency note (zero third-party deps)
├── pyproject.toml                 # ComfyUI Registry publishing metadata
├── LICENSE                        # GPL-3.0
├── .gitignore
└── .github/workflows/
    ├── ci.yml                     # Unit tests + JS syntax check
    └── publish.yml                # Auto-publish to the ComfyUI Registry
```

---

## Development and tests

```bash
# Full unit test suite (no ComfyUI, no torch required)
python -m unittest discover -s tests -v

# Self-check against a real LoRA folder (prints which LoRAs have trigger files)
python tests/integration_real_loras.py "I:/ComfyUI-aki-v2/ComfyUI/models/loras"
python tests/integration_real_loras.py "D:/ComfyUI/models/loras" --extra "D:/my-prompts" --list
```

Frontend syntax check:

```bash
node --input-type=module --check < web/js/lora_trigger_reader.js
```

To tweak the matching rules, edit the constants at the top of `lora_trigger_reader/lora_scan.py`:

```python
TEXT_EXTENSIONS        = (".txt", ".md")   # recognised extensions
SUFFIX_WORDS           = (...)             # suffix words (the 950 tier)
MIN_ACCEPT_SCORE       = 700               # below this, treat as "no match"
ENABLE_FUZZY_MATCH     = True              # enable difflib fuzzy matching
FUZZY_RATIO            = 0.90              # fuzzy threshold
MIN_CONTAIN_CHARS      = 4                 # min length for prefix/contains matching (2 if CJK)
INDEX_TTL_SECONDS      = 8.0               # directory index cache TTL
MAX_FILE_BYTES         = 1024 * 1024       # max bytes read per file
```

To tweak the chain probe, edit the constants at the top of `lora_trigger_reader/graph_probe.py`:

```python
MAX_DEPTH              = 64                # how far up the model wire to walk
MAX_NODES              = 256               # how many upstream nodes to look at
```

To tweak the multi loader, edit the constants at the top of `lora_trigger_reader/loader.py`:

```python
DEFAULT_STRENGTH       = 1.0               # strength when only a name is given
MIN_STRENGTH           = -100.0            # clamp lower bound
MAX_STRENGTH           = 100.0             # clamp upper bound
MAX_SPECS              = 64                # max LoRA entries per run (extra entries are truncated)
CACHE_MAX              = 4                 # how many loaded LoRA tensors stay in memory
SLOT_COUNT             = 4                 # how many dropdown rows the multi loader has (lora_1..lora_4)
SLOT_NONE              = "不使用 / none"    # dropdown sentinel meaning "this row loads nothing"
```

All user-facing documentation text (overview page + the four node pages, in Chinese and English) lives in `lora_trigger_reader/help_docs.py` as plain strings — edit them there and `/lora_trigger_reader/help` plus the frontend Help panel pick it up.

To run a single test file (`tests/` has no `__init__.py`, so `python -m unittest tests.test_x` does not work):

```bash
python -m unittest discover -s tests -p "test_loader.py" -v
```

---

## Publishing checklist

This project is released under the **GPL-3.0** (full text in `LICENSE`). Before cutting a release:

- **copyright**: the `LICENSE` file holds the GNU GPL-3.0 text and must stay **verbatim** — do not edit it. Put your own copyright notice in the README (see below) or in the source headers instead;
- **ComfyUI Registry**: `pyproject.toml` currently has **no `[tool.comfy]` section** — the registry requires `PublisherId` there (and `DisplayName` is recommended). The bundled `publish.yml` only runs when `pyproject.toml` changes, so bump `version` in the same commit;
- bump the version everywhere at once: `pyproject.toml`, the root `__init__.py`, `lora_trigger_reader/lora_scan.py` and `web/js/lora_trigger_reader.js`;
- *(optional)* add an `icon.png` to the repository root and set `[tool.comfy] Icon` if you want a registry icon.

Note that `pyproject.toml` **deliberately omits `web`** from `[tool.comfy]`: `__init__.py` already declares `WEB_DIRECTORY = "./web"`, and registering the frontend twice would load the same script twice.

---

## License

Copyright (C) 2026 shuoyeldx

[GPL-3.0](LICENSE) — free software: you may redistribute and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version. Distributed in the hope that it will be useful, but **without any warranty** — see the [full text](LICENSE).
