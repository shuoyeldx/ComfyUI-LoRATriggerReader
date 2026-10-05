/**
 * ComfyUI-LoRATriggerReader —— 前端部分 (v1.3)
 * ============================================
 *
 * v1.1 的主要变化（对应后端 nodes.py 的 v1.1 重写）：
 *   1. 两个「读取」节点不再需要你手动选 LoRA —— 它们只有 model 输入口 + 一个
 *      `extra_loras`（手动补充）输入框。后端会顺着 model 那条连线往上走，自动找出
 *      链路上用到的 LoRA。
 *   2. 前端做同样的事（本文件 detectUpstreamLoras），把结果直接画在节点上：
 *      「🔎 检测到 2 个 LoRA: xxx.safetensors, yyy.safetensors」。
 *   3. 触发词选择器仍然有用：自动检测不到时（LoRA 由第三方节点 / 子工作流加载），
 *      用它把 LoRA 名字勾进 `extra_loras`；面板里会同时标出「链路」检测到的项。
 *   4. `LoRATriggerReaderInfo`（纯查询节点）保持手动：写回它的 `lora_name` 下拉框。
 *
 * v1.2 的变化：
 *   5. 新增 `LoRAMultiLoader`（多重 LoRA 加载器）：MODEL + CLIP 进出，一个 `lora_list`
 *      文本框里一行一个 LoRA（可写 `名字: 0.8` 强度），一次全加载，同时输出触发词。
 *      本文件给它加「🎯 选择 LoRA（写入多重加载器）」按钮：选择器勾完后写回 `lora_list`，
 *      已经写过的强度（`: 0.8`）会被保留。
 *   6. 所有四个节点都多一个「❓ 使用说明 / Help」按钮：弹出中英文说明面板（含节点切换、
 *      触发词命名规则、打分表、参数表、FAQ），内容由后端 `/lora_trigger_reader/help` 提供。
 *
 * v1.3 的变化（多重加载器改成下拉框）：
 *   7. `LoRAMultiLoader` 的 LoRA 不再是「在文本框里一行写一个名字:强度」，而是
 *      **4 行下拉框**（`lora_1..4`），每行各有独立的 **MODEL 强度**（`strength_i`）和
 *      **CLIP 强度**（`clip_strength_i`）：点数字框左右小箭头每次 ±0.1，也可以直接输入数字。
 *   8. 原来的 `lora_list` 文本框降级为「(高级) 批量文本」（>4 个 LoRA / 批量粘贴时用）。
 *      选择器勾完后：前 4 个写进下拉框，多出来的（或下拉框里放不下的）写进这个文本框；
 *      文本框里已被写进下拉框的行会被移除，避免同一个 LoRA 被加载两次。
 *   9. 节点上的状态行与新按钮文案都改成「下拉框 + 批量文本」的口径。
 *
 * 兼容性设计（很重要）：
 *   1. 只用 `app.registerExtension` + `addWidget("button")` 这两个从 2023 年至今都存在的 API；
 *   2. `app` 用**动态 import** 获取，失败时依次回退到 `window.comfyAPI.app.app` / `window.app`，
 *      任何一步失败都只是「没有按钮」，绝不影响节点本身的执行；
 *   3. 沿连线反查只用 LiteGraph 的 `graph.links` / `graph.getNodeById`，并对
 *      「links 是对象」和「links 是 Map」两种前端版本都做了兜底；所有取值都包在 try 里；
 *   4. 数据优先走插件自己的 HTTP 接口；接口不可用时回退到 `getNodeDefs()`（只有名字，没有文本信息），
 *      帮助面板接口不可用时显示一段离线提示；
 *   5. 只用原生 DOM + 注入的 CSS，不依赖前端的 Vue / Tailwind 类名，换皮肤也不会碎。
 */

const EXT_NAME = "LoRATriggerReader.Picker";
const API_BASE = "/lora_trigger_reader";
const VERSION = "1.3.0";

const NODE_LOADER = "LoRAMultiLoader";
const NODE_AUTO_SINGLE = "LoRATriggerReader";
const NODE_AUTO_MULTI = "LoRATriggerReaderMulti";
const NODE_INFO = "LoRATriggerReaderInfo";
const AUTO_TYPES = [NODE_AUTO_SINGLE, NODE_AUTO_MULTI];

const AUTO_WIDGET = "extra_loras"; // v1.1：自动节点的手动补充输入框
const INFO_WIDGET = "lora_name"; // 查询节点仍然是下拉框
const LOADER_WIDGET = "lora_list"; // v1.2：多重加载器的 LoRA 列表（v1.3 起降级为「(高级) 批量文本」）
const LOADER_SLOT_COUNT = 4; // v1.3：多重加载器的下拉框行数（与后端 loader.SLOT_COUNT 保持一致）
const LOADER_SLOT_NONE = "不使用 / none"; // v1.3：下拉框的「这一行不加载」哨兵值（与 loader.SLOT_NONE 一致）

// 与后端 graph_probe._LORA_KEY_RE 保持一致：只有这些形状的控件名才算「LoRA 选择」。
// 注意是整串匹配，所以 extra_loras / lora_strength / lora_model 都不会被当成文件名。
const LORA_KEY_RE = /^(?:lora|loras|lora_names?|lora_list)(?:_\d+)?$|^lora_\d+_(?:name|path|file|filename)$|^lora_(?:name|names|path|file|filename|stack|stacks|list)_\d+$|^lora_(?:name|names|path|file|filename|stack|stacks|list)$/i;
// 兜底：名字里带这些词的也不是文件名（例如第三方的 lora_1_weight）
const NON_NAME_KEY_RE = /(strength|weight|scale|block|enable|active|count|seed|step|clip|model|alpha|ratio|bypass|type)/i;
const LORA_EXT_RE = /\.(safetensors|sft|ckpt|pt|pth|bin|gguf|safetensor)$/i;

// 纯数字（强度值）
const NUMBER_ONLY_RE = /^[+-]?(?:\d+\.?\d*|\.\d+)$/;
// 「名字 + 强度」：a.safetensors: 0.8 / a.safetensors @ 0.8 / a.safetensors, 0.8, 0.5
const STRENGTH_TAIL_RE = /^(.+?)\s*[:：@]\s*[+-]?(?:\d+\.?\d*|\.\d+)\s*(?:[,;，；]\s*[+-]?(?:\d+\.?\d*|\.\d+)\s*)?$/;

/** 去掉 LoRA 名字后面的强度尾巴（多重加载器的 lora_list 里会这么写）。 */
function stripStrength(text) {
  const s = String(text || "").trim();
  const m = STRENGTH_TAIL_RE.exec(s);
  return m ? m[1].trim() : s;
}

/* ------------------------------------------------------------------ 工具 */

async function getApp() {
  try {
    const mod = await import("../../../scripts/app.js");
    if (mod && mod.app) return mod.app;
  } catch (err) {
    console.warn("[LoRATriggerReader] 动态 import app.js 失败，尝试回退方案", err);
  }
  const g = globalThis;
  if (g.comfyAPI && g.comfyAPI.app && g.comfyAPI.app.app) return g.comfyAPI.app.app;
  if (g.app) return g.app;
  return null;
}

function toast(severity, summary, detail) {
  try {
    const g = globalThis;
    const api = (g.comfyAPI && g.comfyAPI.app && g.comfyAPI.app) || g.app;
    if (api && api.extensionManager && api.extensionManager.toast) {
      api.extensionManager.toast.add({ severity, summary, detail, life: 4000 });
      return;
    }
  } catch (err) {
    /* 忽略，继续用 console */
  }
  (severity === "error" ? console.error : console.info)(`[LoRATriggerReader] ${summary}`, detail || "");
}

function findWidget(node, name) {
  const widgets = (node && node.widgets) || [];
  for (let i = 0; i < widgets.length; i++) {
    if (widgets[i] && widgets[i].name === name) return widgets[i];
  }
  return null;
}

/** 把值写进字符串 widget，并尽量触发它的回调 / 标脏画布。 */
function setWidgetValue(app, node, name, value) {
  const w = findWidget(node, name);
  if (!w) return false;
  w.value = value;
  try {
    if (typeof w.callback === "function") w.callback(value, app.canvas, node, [0, 0], null);
  } catch (err) {
    console.warn("[LoRATriggerReader] widget callback 抛错（已忽略）", err);
  }
  try {
    if (w.inputEl) w.inputEl.value = value;
  } catch (err) {
    /* 忽略 */
  }
  try {
    app.graph.setDirtyCanvas(true, true);
  } catch (err) {
    /* 忽略 */
  }
  return true;
}

function parseLines(text) {
  return String(text || "")
    .split(/\r?\n/)
    .map((s) => s.replace(/^\s*#.*$/, "").trim())
    .filter((s) => s.length > 0);
}

function baseName(name) {
  // 非字符串一律返回空串：绝不让 "[object Object]" / "undefined" 漏到界面上
  if (name === null || name === undefined || typeof name === "object") return "";
  const s = String(name).replace(/\\/g, "/");
  const i = s.lastIndexOf("/");
  return i >= 0 ? s.slice(i + 1) : s;
}

/** 给名字做个宽松的比较键（去扩展名、去路径、去空白符号、小写）。 */
function nameKey(name) {
  return baseName(name)
    .replace(LORA_EXT_RE, "")
    .replace(/[\s_\-·．.、,，]+/g, "")
    .toLowerCase();
}

/** 状态徽章文案 */
function statusInfo(item) {
  switch (item.status) {
    case "ok":
      return { cls: "ok", text: "有触发词", tip: item.preview || "" };
    case "empty":
      return { cls: "empty", text: "空文件", tip: item.file || "" };
    case "no_lora":
      return { cls: "bad", text: "找不到 LoRA", tip: item.file || "" };
    case "error":
      return { cls: "bad", text: "出错", tip: item.error || "" };
    default:
      return { cls: "none", text: "无触发词", tip: "" };
  }
}

/* ------------------------------------------------- 沿连线反查上游 LoRA（前端侧） */

function graphOf(node) {
  if (node && node.graph) return node.graph;
  const g = globalThis;
  if (g.app && g.app.graph) return g.app.graph;
  return null;
}

/** 取某个输入口连到的 link 对象（兼容 links 是对象 / Map 两种实现）。 */
function linkOf(node, input) {
  try {
    const id = input && input.link;
    if (id === null || id === undefined) return null;
    const graph = graphOf(node);
    if (!graph || !graph.links) return null;
    const links = graph.links;
    if (typeof links.get === "function") return links.get(id) || null;
    return links[id] || null;
  } catch (err) {
    return null;
  }
}

function nodeById(node, id) {
  try {
    const graph = graphOf(node);
    if (!graph) return null;
    if (typeof graph.getNodeById === "function") {
      const n = graph.getNodeById(id);
      if (n) return n;
    }
    if (graph._nodes_by_id && graph._nodes_by_id[id]) return graph._nodes_by_id[id];
    if (Array.isArray(graph._nodes)) return graph._nodes.find((n) => n && n.id === id) || null;
  } catch (err) {
    /* 忽略 */
  }
  return null;
}

function typeOf(node) {
  return String((node && (node.comfyClass || node.type)) || "");
}

function isBlockedValue(s) {
  const t = String(s || "").trim();
  if (!t) return true;
  if (/^<.*>$/.test(t)) return true; // <未检测到 LoRA> 之类的占位
  if (/^\[object [^\]]*\]$/i.test(t)) return true; // "[object Object]" 这种被 String() 出来的垃圾
  if (/^(none|null|undefined|无|未选择|请选择|未检测到)$/i.test(t)) return true;
  return false;
}

/* 结构化的第三方 LoRA 控件值（例如 rgthree Power Lora Loader 的一个输入里塞
 * {"on": true, "lora": "x.safetensors", "strength": 1.0}）：
 * 下面两张表决定从哪个字段取名字、哪些字段一定不是名字。
 * 老代码对这种值是先 String(value) -> "[object Object]" 再当名字，界面上就会出现
 * 「检测到 1 个 LoRA: [object Object]」——这就是要修的那个显示 bug。 */
const LORA_NAME_KEYS = [
  "lora", "lora_name", "loraname", "lora_path", "lora_file", "lora_filename",
  "name", "value", "file", "filename", "file_name", "path", "base", "title",
];
const LORA_META_KEYS = [
  "on", "enabled", "active", "mode", "id", "type", "class_type", "widgets_values",
  "strength", "strength_model", "strength_clip", "clip_strength", "weight",
];

/** 从一个 widget 的值里抽出所有 LoRA 名字（字符串 / 数组 / 对象 / JSON 串 / 多行 / 逗号都支持）。 */
function extractLoraNames(value) {
  const out = [];
  const add = (v) => {
    if (typeof v !== "string") return; // 布尔 / 数字（on: true、strength: 0.8）不是名字
    const s = stripStrength(v);
    if (isBlockedValue(s)) return;
    if (NUMBER_ONLY_RE.test(s)) return; // "a.safetensors, 0.8" 里被逗号拆出来的强度值
    if (out.indexOf(s) === -1) out.push(s);
  };
  const fromText = (text) => {
    const t = String(text).trim();
    if (!t) return;
    if (t[0] === "{" || t[0] === "[") {
      try {
        walk(JSON.parse(t));
      } catch (err) {
        /* 不是合法 JSON（"[object Object]" 之类）→ 直接丢掉，别当名字 */
      }
      return;
    }
    t.split(/[\n\r,;，；、]+/).forEach(add);
  };
  const walk = (v) => {
    if (v === null || v === undefined) return;
    if (typeof v === "string") {
      fromText(v);
      return;
    }
    if (Array.isArray(v)) {
      v.forEach(walk);
      return;
    }
    if (typeof v === "object") {
      const preferred = [];
      const others = [];
      Object.keys(v).forEach((k) => {
        const item = v[k];
        if (item === null || item === undefined) return;
        if (LORA_META_KEYS.indexOf(k) >= 0) return; // on / strength / mode … 不是名字
        if (typeof item === "object") {
          walk(item);
          return;
        }
        if (typeof item === "string") {
          (LORA_NAME_KEYS.indexOf(k) >= 0 ? preferred : others).push(item);
        }
      });
      // 名字类字段优先（lora / name / value / path…），其余字符串兜底
      preferred.concat(others).forEach(fromText);
      return;
    }
    /* 布尔 / 数字：丢掉 */
  };
  walk(value);
  return out;
}

/** 收集「一个节点自己」用到的 LoRA（看它的 lora* 控件）。 */
function collectFromNode(node, found, seenKeys) {
  const widgets = (node && node.widgets) || [];
  const t = typeOf(node);
  for (let i = 0; i < widgets.length; i++) {
    const w = widgets[i];
    if (!w || !w.name) continue;
    const name = String(w.name);
    if (!LORA_KEY_RE.test(name)) continue;
    const rest = name.replace(/lora/gi, "");
    if (NON_NAME_KEY_RE.test(rest)) continue; // lora_strength 之类
    const names = extractLoraNames(w.value);
    for (const n of names) {
      const key = nameKey(n);
      if (!key || seenKeys.has(key)) continue;
      seenKeys.add(key);
      found.push({ name: n, node_id: node.id, title: node.title || t, key: name });
    }
  }
}

/**
 * 从 nodes 出发，沿输入连线向上游做 BFS，按「离本节点由近到远」的顺序
 * 收集链路上用到的 LoRA。等价于后端 graph_probe.probe_prompt 的前端版本，
 * 只用于界面显示（后端才是权威）。
 */
function detectUpstreamLoras(node, maxDepth) {
  const found = [];
  const seenKeys = new Set();
  const visited = new Set();
  const limit = maxDepth || 64;
  let frontier = [node];
  let depth = 0;
  while (frontier.length && depth < limit) {
    const next = [];
    for (const n of frontier) {
      if (!n || visited.has(n.id)) continue;
      visited.add(n.id);
      const inputs = n.inputs || [];
      for (const inp of inputs) {
        const link = linkOf(n, inp);
        if (!link) continue;
        const src = nodeById(n, link.origin_id);
        if (!src || visited.has(src.id)) continue;
        // 同类读取节点自己不算 LoRA 来源（它的 extra_loras 是手动补充），
        // 但仍要穿过它继续往上游找 —— 后端 graph_probe 也是这么走的，
        // 否则「LoRATriggerReader -> LoRATriggerReaderMulti」串联起来时界面会显示成「没检测到」。
        if (AUTO_TYPES.indexOf(typeOf(src)) < 0) collectFromNode(src, found, seenKeys);
        next.push(src);
      }
    }
    frontier = next;
    depth++;
  }
  return found;
}

/** 面板 / 提示里的「#节点名 文件名」标签（名字取不到时给占位，不显示 undefined / [object Object]）。 */
function chainLabel(item) {
  if (!item) return "";
  const name = baseName(item.name || item.lora || item.lora_name || "") || "（名字未识别）";
  return item.node_id === undefined || item.node_id === null ? name : `#${item.node_id} ${name}`;
}

/** 带 1 秒缓存的检测结果（画节点时会被高频调用）。 */
function detectedLoras(node, force) {
  const now = Date.now();
  const cached = node.__ltrDetected;
  if (!force && cached && now - cached.time < 1000) return cached.list;
  let list = [];
  try {
    list = detectUpstreamLoras(node);
  } catch (err) {
    console.warn("[LoRATriggerReader] 前端检测链路失败（已忽略）", err);
    list = [];
  }
  node.__ltrDetected = { time: now, list };
  return list;
}

function hasModelLink(node) {
  const inputs = (node && node.inputs) || [];
  for (const inp of inputs) {
    if (inp && inp.name === "model" && inp.link !== null && inp.link !== undefined) return true;
  }
  return false;
}

/* ------------------------------------------------------------------ 样式 */

const CSS = `
.ltr-mask{position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:10000;display:flex;align-items:center;justify-content:center;}
.ltr-panel{width:min(880px,92vw);height:min(720px,88vh);display:flex;flex-direction:column;
  background:#1e1e23;color:#e8e8ea;border:1px solid #3a3a44;border-radius:10px;
  box-shadow:0 12px 40px rgba(0,0,0,.55);font:13px/1.5 "Microsoft YaHei",system-ui,sans-serif;overflow:hidden;}
.ltr-head{display:flex;align-items:center;gap:8px;padding:10px 14px;background:#26262e;border-bottom:1px solid #3a3a44;}
.ltr-head h3{margin:0;font-size:14px;font-weight:600;flex:1;}
.ltr-head .ltr-sub{color:#9a9aa8;font-size:12px;}
.ltr-btn{cursor:pointer;border:1px solid #4a4a58;background:#33333d;color:#e8e8ea;border-radius:6px;padding:4px 10px;font-size:12px;}
.ltr-btn:hover{background:#3f3f4c;}
.ltr-btn.primary{background:#3b6fd4;border-color:#4a80e8;}
.ltr-btn.primary:hover{background:#4a80e8;}
.ltr-body{flex:1;overflow:auto;}
.ltr-note{padding:8px 14px;background:#22222a;border-bottom:1px solid #33333d;color:#b9b9c6;font-size:12px;}
.ltr-note b{color:#8ce99a;font-weight:600;}
.ltr-tools{display:flex;flex-wrap:wrap;gap:8px;align-items:center;padding:8px 14px;border-bottom:1px solid #33333d;position:sticky;top:0;background:#1e1e23;z-index:1;}
.ltr-tools input[type=search]{flex:1;min-width:180px;background:#2a2a33;border:1px solid #44444f;color:#e8e8ea;border-radius:6px;padding:5px 8px;}
.ltr-tools label{display:flex;align-items:center;gap:4px;color:#b9b9c6;font-size:12px;user-select:none;}
.ltr-tools select{background:#2a2a33;border:1px solid #44444f;color:#e8e8ea;border-radius:6px;padding:4px 6px;max-width:280px;}
.ltr-item{display:flex;gap:8px;align-items:flex-start;padding:7px 14px;border-bottom:1px solid #2b2b33;}
.ltr-item:hover{background:#25252d;}
.ltr-item input{margin-top:2px;}
.ltr-item .ltr-name{font-weight:500;word-break:break-all;}
.ltr-item .ltr-path{color:#8d8d9c;font-size:11px;word-break:break-all;}
.ltr-item .ltr-prev{color:#9ecb9e;font-size:11px;word-break:break-all;}
.ltr-badge{display:inline-block;min-width:56px;text-align:center;border-radius:4px;font-size:11px;padding:1px 6px;margin-right:6px;}
.ltr-badge.ok{background:#20492c;color:#8ce99a;}
.ltr-badge.empty{background:#4a4218;color:#ffd866;}
.ltr-badge.none{background:#33333d;color:#9a9aa8;}
.ltr-badge.bad{background:#4d2226;color:#ff8787;}
.ltr-badge.chain{background:#1f3a52;color:#8fd0ff;}
.ltr-foot{display:flex;gap:8px;align-items:center;padding:10px 14px;border-top:1px solid #3a3a44;background:#26262e;}
.ltr-foot .ltr-count{flex:1;color:#9a9aa8;font-size:12px;}
.ltr-text{white-space:pre-wrap;word-break:break-all;background:#15151a;border:1px solid #33333d;border-radius:6px;padding:10px;margin:12px 14px;max-height:60vh;overflow:auto;font-family:Consolas,monospace;font-size:12px;}
`;

function ensureCss() {
  if (document.getElementById("ltr-style")) return;
  const style = document.createElement("style");
  style.id = "ltr-style";
  style.textContent = CSS;
  document.head.appendChild(style);
}

/* ------------------------------------------------------------------ 数据 */

let listCache = { time: 0, payload: null };

async function fetchList(force) {
  const now = Date.now();
  if (!force && listCache.payload && now - listCache.time < 20000) return listCache.payload;
  try {
    const resp = await fetch(`${API_BASE}/list${force ? "?refresh=1" : ""}`, { cache: "no-store" });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    if (!data || data.ok !== true) throw new Error((data && data.error) || "接口返回 ok=false");
    listCache = { time: now, payload: data };
    return data;
  } catch (err) {
    console.warn("[LoRATriggerReader] 接口不可用，回退到节点定义里的 LoRA 列表", err);
    const data = await fetchListFallback();
    listCache = { time: now, payload: data };
    return data;
  }
}

/** 接口不可用时的兜底：只能拿到名字，没有触发词信息。 */
async function fetchListFallback() {
  const names = new Set();
  try {
    const mod = await import("../../../scripts/api.js");
    const api = (mod && mod.api) || (globalThis.comfyAPI && globalThis.comfyAPI.api && globalThis.comfyAPI.api.api);
    const defs = await api.getNodeDefs();
    const types = [NODE_INFO, "LoraLoader", "LoraLoaderModelOnly"];
    for (const t of types) {
      const def = defs && defs[t];
      const input = def && def.input && def.input.required && def.input.required.lora_name;
      if (input && Array.isArray(input[0])) input[0].forEach((n) => names.add(n));
    }
  } catch (err) {
    console.warn("[LoRATriggerReader] 兜底列表也失败了", err);
  }
  const items = Array.from(names).map((n) => ({ name: n, base: baseName(n), status: "unknown", preview: "" }));
  return { ok: true, fallback: true, count: items.length, items };
}

async function fetchText(loraName) {
  const resp = await fetch(`${API_BASE}/text?lora_name=${encodeURIComponent(loraName)}`, { cache: "no-store" });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return await resp.json();
}

/* ------------------------------------------------------------------ 选择器面板 */

/**
 * mode: "auto-multi" | "auto-single"   -> 自动节点，写回 extra_loras（可多选）
 *       "loader"                       -> 多重加载器，前 4 个写进下拉框 lora_1..4、
 *                                         多出来的写进 (高级) 批量文本 lora_list
 *       "info"                         -> 查询节点，写回 lora_name（单选）
 */
function openPicker(app, node, mode) {
  ensureCss();
  const isInfo = mode === "info";
  const isLoader = mode === "loader";
  const widgetName = isInfo ? INFO_WIDGET : isLoader ? LOADER_WIDGET : AUTO_WIDGET;
  const multi = !isInfo;
  // v1.3：多重加载器的 LoRA 主要写在下拉框里，「(高级) 批量文本」可能还有内容，两边都算
  const textRaw = String(findWidget(node, LOADER_WIDGET)?.value || "");
  const slotNames = isLoader ? loaderSlotNames(node) : [];
  const currentRaw = isLoader
    ? slotNames.concat(parseLines(textRaw).map(stripStrength)).filter(Boolean).join("\n")
    : String(findWidget(node, widgetName)?.value || "");
  const current = new Set(isInfo ? [stripStrength(String(currentRaw))].filter(Boolean) : parseLines(currentRaw).map(stripStrength));

  // 记住原本写过的整行（下拉框里没有强度，批量文本框里可能带强度："妃咲.safetensors: 0.8"）
  const rawByKey = new Map();
  parseLines(isLoader ? textRaw : currentRaw).forEach((line) => {
    const key = nameKey(stripStrength(line));
    if (key && !rawByKey.has(key)) rawByKey.set(key, line.trim());
  });

  const chain = detectedLoras(node, true);
  const chainKeys = new Set(chain.map((c) => nameKey(c.name)));

  const title = isInfo
    ? "选择 LoRA（含触发词预览）"
    : isLoader
      ? "选择 LoRA（写入多重加载器下拉框）"
      : "LoRA 触发词选择器（手动补充）";

  const mask = document.createElement("div");
  mask.className = "ltr-mask";
  mask.innerHTML = `
    <div class="ltr-panel">
      <div class="ltr-head">
        <h3>${title}</h3>
        <span class="ltr-sub" data-role="stats">加载中…</span>
        <button class="ltr-btn" data-role="reload">重新扫描</button>
        <button class="ltr-btn" data-role="close">关闭</button>
      </div>
      <div class="ltr-note" data-role="note"></div>
      <div class="ltr-tools">
        <input type="search" placeholder="搜索 LoRA 名字 / 路径…" data-role="search" />
        <label><input type="checkbox" data-role="only-ok" /> 只看有触发词</label>
        <label><input type="checkbox" data-role="only-missing" /> 只看没有触发词</label>
        <label><input type="checkbox" data-role="only-chain" /> 只看链路检测</label>
        <label><input type="checkbox" data-role="selected-only" /> 只看已选</label>
      </div>
      <div class="ltr-body" data-role="list"></div>
      <div class="ltr-foot">
        <span class="ltr-count" data-role="count">已选 0 个</span>
        <button class="ltr-btn" data-role="select-chain">选定链路项</button>
        <button class="ltr-btn" data-role="select-visible">${isInfo ? "选中第一个" : "全选当前列表"}</button>
        <button class="ltr-btn" data-role="clear">清空</button>
        <button class="ltr-btn primary" data-role="apply">应用 (写回节点)</button>
      </div>
    </div>`;
  document.body.appendChild(mask);

  const $ = (role) => mask.querySelector(`[data-role="${role}"]`);
  const listEl = $("list");
  let payload = { items: [] };
  const selected = new Set(current);

  const noteEl = $("note");
  if (isInfo) {
    noteEl.innerHTML = `查询节点：勾选的 LoRA 会写回 <b>${INFO_WIDGET}</b> 下拉框（只取第一个）。`;
  } else if (isLoader) {
    const own = Array.from(selected);
    noteEl.innerHTML =
      `勾选的 LoRA 会写进 <b>下拉框</b>（前 ${LOADER_SLOT_COUNT} 个，每行各有独立的 MODEL / CLIP 强度框）；` +
      `多出来的写进 <b>(高级) 批量文本</b>（原来写过的强度 <code>: 0.8</code> 会保留）。` +
      (own.length ? `<br/>当前已选 ${own.length} 个。` : `<br/>当前为空：都留空时节点会自动使用接入链路上的 LoRA。`) +
      (chain.length
        ? `<br/>model 连线上检测到 <b>${chain.length}</b> 个 LoRA：` +
          `${chain.map(chainLabel).join(" · ")}`
        : "");
  } else if (chain.length) {
    noteEl.innerHTML =
      `已在 model 连线上自动检测到 <b>${chain.length}</b> 个 LoRA：` +
      `${chain.map(chainLabel).join(" · ")}<br/>` +
      `下面勾选的是 <b>额外补充</b>（写回 ${AUTO_WIDGET}），一般留空即可。`;
  } else {
    noteEl.innerHTML =
      `没有从 model 连线上检测到 LoRA（可能由第三方节点 / 子工作流加载）。` +
      `可以在这里勾选，写回 <b>${AUTO_WIDGET}</b> 作为手动补充。`;
  }

  const close = () => mask.remove();
  mask.addEventListener("mousedown", (e) => {
    if (e.target === mask) close();
  });
  document.addEventListener("keydown", function esc(e) {
    if (e.key === "Escape") {
      close();
      document.removeEventListener("keydown", esc);
    }
  });

  function isChainItem(it) {
    return chainKeys.has(nameKey(it.name)) || chainKeys.has(nameKey(it.base));
  }

  function visibleItems() {
    const q = ($("search").value || "").trim().toLowerCase();
    const onlyOk = $("only-ok").checked;
    const onlyMissing = $("only-missing").checked;
    const onlyChain = $("only-chain").checked;
    const onlySelected = $("selected-only").checked;
    return (payload.items || []).filter((it) => {
      if (q && !(`${it.name}`.toLowerCase().includes(q) || `${it.base || ""}`.toLowerCase().includes(q))) return false;
      if (onlyOk && it.status !== "ok") return false;
      if (onlyMissing && it.status === "ok") return false;
      if (onlyChain && !isChainItem(it)) return false;
      if (onlySelected && !selected.has(it.name)) return false;
      return true;
    });
  }

  function render() {
    const items = visibleItems();
    listEl.textContent = "";
    if (!items.length) {
      const empty = document.createElement("div");
      empty.className = "ltr-item";
      empty.textContent = payload.items.length ? "没有符合筛选条件的 LoRA" : "没有拿到 LoRA 列表";
      listEl.appendChild(empty);
    }
    const frag = document.createDocumentFragment();
    for (const it of items) {
      const row = document.createElement("div");
      row.className = "ltr-item";
      const box = document.createElement("input");
      box.type = "checkbox";
      box.checked = selected.has(it.name);
      box.addEventListener("change", () => {
        if (box.checked) {
          if (isInfo) selected.clear(); // 查询节点是单选语义
          selected.add(it.name);
        } else {
          selected.delete(it.name);
        }
        if (isInfo) render();
        else updateCount();
      });
      const info = statusInfo(it);
      const body = document.createElement("div");
      body.style.flex = "1";
      const title = document.createElement("div");
      title.className = "ltr-name";
      if (isChainItem(it)) {
        const chainBadge = document.createElement("span");
        chainBadge.className = "ltr-badge chain";
        chainBadge.textContent = "链路";
        chainBadge.title = "这个 LoRA 出现在 model 连线上";
        title.appendChild(chainBadge);
      }
      const badge = document.createElement("span");
      badge.className = `ltr-badge ${info.cls}`;
      badge.textContent = info.text;
      if (info.tip) badge.title = info.tip;
      title.appendChild(badge);
      title.appendChild(document.createTextNode(it.name));
      body.appendChild(title);
      if (it.trigger_rel) {
        const p = document.createElement("div");
        p.className = "ltr-path";
        p.textContent = `→ ${it.trigger_rel}`;
        body.appendChild(p);
      }
      if (it.preview) {
        const pv = document.createElement("div");
        pv.className = "ltr-prev";
        pv.textContent = it.preview;
        pv.title = it.preview;
        body.appendChild(pv);
      }
      row.appendChild(box);
      row.appendChild(body);
      row.addEventListener("click", (e) => {
        if (e.target === box) return;
        box.checked = !box.checked;
        box.dispatchEvent(new Event("change"));
      });
      frag.appendChild(row);
    }
    listEl.appendChild(frag);
    updateCount();

    const ok = (payload.items || []).filter((i) => i.status === "ok").length;
    const empty = (payload.items || []).filter((i) => i.status === "empty").length;
    $("stats").textContent = payload.fallback
      ? `共 ${payload.items.length} 个 LoRA（接口不可用，仅名字）`
      : `共 ${payload.items.length} 个 LoRA / 有触发词 ${ok} / 空文件 ${empty} / 链路 ${chain.length}`;
  }

  function updateCount() {
    $("count").textContent = `已选 ${selected.size} 个`;
  }

  async function load(force) {
    $("stats").textContent = "扫描中…";
    payload = await fetchList(force);
    render();
  }

  $("search").addEventListener("input", render);
  ["only-ok", "only-missing", "only-chain", "selected-only"].forEach((r) => $(r).addEventListener("change", render));
  $("close").addEventListener("click", close);
  $("reload").addEventListener("click", () => load(true));
  $("select-chain").addEventListener("click", () => {
    const all = payload.items || [];
    const hits = all.filter((it) => isChainItem(it));
    if (!hits.length) {
      toast("warn", "链路上没检测到 LoRA", "可以把 model 接到 LoraLoader 的输出，或手动勾选");
      return;
    }
    if (isInfo) selected.clear();
    hits.forEach((it) => selected.add(it.name));
    render();
  });
  $("select-visible").addEventListener("click", () => {
    if (isInfo) {
      const first = visibleItems()[0];
      if (first) {
        selected.clear();
        selected.add(first.name);
        render();
      }
      return;
    }
    visibleItems().forEach((it) => selected.add(it.name));
    render();
  });
  $("clear").addEventListener("click", () => {
    selected.clear();
    render();
  });
  $("apply").addEventListener("click", () => {
    // 保持「先选中的在前」，其余按列表顺序
    const ordered = (payload.items || []).map((i) => i.name).filter((n) => selected.has(n));
    selected.forEach((n) => {
      if (!ordered.includes(n)) ordered.push(n);
    });

    if (isLoader) {
      const res = writeLoaderSlots(app, node, ordered, rawByKey);
      if (!res.ok) toast("error", "写入失败", "找不到下拉框或批量文本框");
      else if (!ordered.length) toast("success", "已清空", "下拉框和批量文本都没有要加载的 LoRA");
      else {
        const parts = [];
        if (res.slots.length) parts.push(`${res.slots.length} 个写进下拉框`);
        if (res.extra.length) parts.push(`${res.extra.length} 个写进「(高级) 批量文本」`);
        if (!res.slots.length && !res.extra.length) parts.push("没有可写的位置");
        toast(
          "success",
          `已应用 ${ordered.length} 个 LoRA`,
          `${parts.join("，")}。下拉框里每行可以单独调 MODEL / CLIP 强度（0.1 步进）。`
        );
      }
      close();
      return;
    }

    let text;
    if (isInfo) text = ordered[0] || "";
    else text = ordered.join("\n");
    const okWrite = setWidgetValue(app, node, widgetName, text);
    if (!okWrite) toast("error", "写入失败", `找不到 ${widgetName} 输入框`);
    else if (isInfo) toast("success", "已应用", `已选择 ${text || "(空)"}`);
    else toast("success", "已应用", ordered.length ? `${ordered.length} 个 LoRA 已写入 ${widgetName}` : `已清空 ${widgetName}`);
    close();
  });

  render();
  load(false);
}

/* ------------------------------------------------------------------ 文本查看面板 */

function openTextViewer(title, bodyText) {
  ensureCss();
  const mask = document.createElement("div");
  mask.className = "ltr-mask";
  const panel = document.createElement("div");
  panel.className = "ltr-panel";
  panel.style.height = "auto";
  panel.innerHTML = `
    <div class="ltr-head">
      <h3></h3>
      <button class="ltr-btn" data-role="copy">复制</button>
      <button class="ltr-btn" data-role="close">关闭</button>
    </div>
    <div class="ltr-text"></div>`;
  panel.querySelector("h3").textContent = title;
  panel.querySelector(".ltr-text").textContent = bodyText || "(空)";
  mask.appendChild(panel);
  document.body.appendChild(mask);
  const close = () => mask.remove();
  mask.addEventListener("mousedown", (e) => {
    if (e.target === mask) close();
  });
  panel.querySelector('[data-role="close"]').addEventListener("click", close);
  panel.querySelector('[data-role="copy"]').addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(bodyText || "");
      toast("success", "已复制到剪贴板");
    } catch (err) {
      toast("error", "复制失败", String(err));
    }
  });
}

/* ------------------------------------------------------------------ 使用说明面板 */

/** 「❓ 使用说明」：中英文节点说明（内容来自后端 /help 接口，可切换节点 / 语言 / 复制）。 */
async function openHelp(app, node) {
  ensureCss();
  const mask = document.createElement("div");
  mask.className = "ltr-mask";
  mask.innerHTML = `
    <div class="ltr-panel">
      <div class="ltr-head">
        <h3>❓ 节点使用说明 / Node help</h3>
        <span class="ltr-sub" data-role="which"></span>
        <button class="ltr-btn" data-role="lang">English</button>
        <button class="ltr-btn" data-role="close">关闭</button>
      </div>
      <div class="ltr-tools">
        <label>节点 / Node <select data-role="pick"></select></label>
        <button class="ltr-btn" data-role="copy">复制</button>
      </div>
      <div class="ltr-body"><div class="ltr-text" data-role="doc">加载中…</div></div>
      <div class="ltr-foot"><span class="ltr-count" data-role="src"></span></div>
    </div>`;
  document.body.appendChild(mask);

  const $ = (role) => mask.querySelector(`[data-role="${role}"]`);
  const close = () => mask.remove();
  mask.addEventListener("mousedown", (e) => {
    if (e.target === mask) close();
  });
  document.addEventListener("keydown", function esc(e) {
    if (e.key === "Escape") {
      close();
      document.removeEventListener("keydown", esc);
    }
  });
  $("close").addEventListener("click", close);

  let payload = null;
  let lang = "zh";
  let current = typeOf(node) || "help";

  const HELP_ENTRY = {
    key: "help",
    title: { zh: "总览 / 怎么用帮助面板", en: "Overview / how to use this panel" },
  };

  function fillPick() {
    const sel = $("pick");
    const items = [HELP_ENTRY].concat(
      ((payload && payload.nodes) || []).filter((it) => it && it.key !== "help")
    );
    sel.textContent = "";
    items.forEach((it) => {
      const opt = document.createElement("option");
      opt.value = it.key;
      opt.textContent = (it.title && (it.title[lang] || it.title.zh)) || it.key;
      sel.appendChild(opt);
    });
    sel.value = current;
    if (!sel.value && sel.options.length) {
      sel.selectedIndex = 0;
      current = sel.options[0].value;
    }
  }

  function render() {
    if (!payload || payload.ok !== true) {
      $("doc").textContent =
        `没能从后端取到说明文本（${API_BASE}/help 接口不可用）。\n` +
        "节点和端口的简短说明仍然可以把鼠标悬停在节点 / 端口上看到。";
      $("which").textContent = "";
      return;
    }
    $("doc").textContent = payload[lang] || payload.zh || "(空)";
    $("which").textContent = (payload.title && (payload.title[lang] || payload.title.zh)) || payload.node || "";
    $("lang").textContent = lang === "zh" ? "English" : "中文";
    $("src").textContent =
      payload.exists === false && payload.requested
        ? `没有「${payload.requested}」的专属说明，已显示总览。`
        : `内容来自 ${API_BASE}/help?node=${payload.node}`;
  }

  async function load(key) {
    $("doc").textContent = "加载中…";
    try {
      const resp = await fetch(`${API_BASE}/help?node=${encodeURIComponent(key)}`, { cache: "no-store" });
      payload = await resp.json();
    } catch (err) {
      console.warn("[LoRATriggerReader] 帮助接口不可用", err);
      payload = null;
    }
    fillPick();
    render();
  }

  $("lang").addEventListener("click", () => {
    lang = lang === "zh" ? "en" : "zh";
    fillPick();
    render();
  });
  $("pick").addEventListener("change", () => {
    current = $("pick").value;
    load(current);
  });
  $("copy").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText($("doc").textContent || "");
      toast("success", "已复制到剪贴板");
    } catch (err) {
      toast("error", "复制失败", String(err));
    }
  });

  load(current);
}

/* ------------------------------------------------------------------ 节点上的状态行 */

/* v1.3：多重加载器每行的三个控件名是 lora_i / strength_i / clip_strength_i
 * （与后端 nodes._slot_keys 一致；这里只用到下拉框 lora_i）。 */

/** v1.3：多重加载器下拉框里真正选了 LoRA 的行（跳过空值 / 「不使用 / none」）。 */
function loaderSlotNames(node) {
  const out = [];
  for (let i = 1; i <= LOADER_SLOT_COUNT; i += 1) {
    const value = String((findWidget(node, `lora_${i}`) || {}).value || "").trim();
    if (!value || value === LOADER_SLOT_NONE || value.indexOf("<未检测到") === 0) continue;
    if (out.indexOf(value) === -1) out.push(value);
  }
  return out;
}

/** 下拉框能不能接受这个名字（老前端没有 options.values 时直接放行）。 */
function slotAccepts(widget, value) {
  const values = widget?.options?.values;
  if (!Array.isArray(values)) return true;
  return values.indexOf(value) >= 0;
}

/**
 * v1.3：把选择器勾中的 LoRA 写回多重加载器。
 *   前 LOADER_SLOT_COUNT 个 -> 下拉框 lora_1..4；
 *   多出来的（或下拉框里放不下的）-> 「(高级) 批量文本」lora_list（原来的强度会保留）；
 *   文本框里已经被写进下拉框的行会被移除，避免同一个 LoRA 被加载两次。
 * 返回 { slots, extra, textTouched, ok }。
 */
function writeLoaderSlots(app, node, names, rawByKey) {
  const slots = [];
  const extra = [];
  for (const name of names) {
    const index = slots.length + 1;
    const widget = index <= LOADER_SLOT_COUNT ? findWidget(node, `lora_${index}`) : null;
    if (widget && slotAccepts(widget, name)) slots.push(name);
    else extra.push(name);
  }

  let ok = true;
  slots.forEach((name, i) => {
    if (!setWidgetValue(app, node, `lora_${i + 1}`, name)) ok = false;
  });

  const selectedKeys = new Set(names.map((n) => nameKey(n)));
  const kept = [];
  let removed = 0;
  parseLines(String((findWidget(node, LOADER_WIDGET) || {}).value || "")).forEach((line) => {
    const key = nameKey(stripStrength(line));
    if (key && selectedKeys.has(key)) removed += 1;
    else kept.push(line.trim());
  });

  let textTouched = false;
  if (extra.length || removed) {
    const lines = kept.concat(extra.map((n) => (rawByKey && rawByKey.get(nameKey(n))) || n));
    textTouched = true;
    if (!setWidgetValue(app, node, LOADER_WIDGET, lines.join("\n"))) ok = false;
  }
  return { slots, extra, textTouched, ok };
}

/** 多重加载器的 LoRA 名字：下拉框 + 「(高级) 批量文本」两边都算（含去强度尾巴、忽略注释行与纯数字行）。 */
function loaderListNames(node) {
  const out = loaderSlotNames(node);
  const raw = String((findWidget(node, LOADER_WIDGET) || {}).value || "");
  parseLines(raw).forEach((line) => {
    const name = stripStrength(line);
    if (!name || NUMBER_ONLY_RE.test(name)) return;
    if (out.indexOf(name) === -1) out.push(name);
  });
  return out;
}

function drawStatusLine(ctx, node) {
  const size = node.size || [200, 100];
  const w = size[0];
  let text;
  let color = "#9a9aa8";
  const chain = detectedLoras(node);
  /* 显示用：只画真实文件名的 basename，拿不到名字时给个占位，绝不出现 "[object Object]" */
  const short = (list) => {
    const names = list
      .map((c) => baseName(typeof c === "object" && c !== null ? c.name || c.lora || c.lora_name || "" : c))
      .filter((s) => s && !/^\[object [^\]]*\]$/i.test(s));
    return names.length ? names.join(", ") : "（名字未识别）";
  };

  if (typeOf(node) === NODE_LOADER) {
    // 多重加载器：优先看下拉框 + 批量文本框里写了什么，都为空时才用链路检测结果
    const own = loaderListNames(node);
    const rowCount = loaderSlotNames(node).length;
    if (own.length) {
      text = `🔎 将加载 ${own.length} 个 LoRA（下拉框 ${rowCount} 行）: ${short(own)}`;
      color = "#8ce99a";
    } else if (chain.length) {
      text = `🔎 下拉框和批量文本都为空，自动加载链路 ${chain.length} 个 LoRA: ${short(chain)}`;
      color = "#8fd0ff";
    } else {
      text = "🔎 下拉框和批量文本都为空，链路上也没识别到 LoRA（只输出触发词）";
    }
  } else if (!hasModelLink(node)) {
    text = "🔎 未接入 MODEL：把左侧 LoraLoader 的 MODEL 接进来";
  } else if (!chain.length) {
    text = "🔎 已接入，但链路上没识别到 LoRA";
  } else {
    text = `🔎 检测到 ${chain.length} 个 LoRA: ${short(chain)}`;
    color = "#8ce99a";
  }

  ctx.save();
  ctx.font = "11px sans-serif";
  let shown = text;
  while (shown.length > 4 && ctx.measureText(shown).width > w - 16) {
    shown = shown.slice(0, -2);
  }
  const y = size[1] - 6;
  ctx.fillStyle = "rgba(0,0,0,0.35)";
  ctx.fillRect(6, y - 12, w - 12, 15);
  ctx.fillStyle = color;
  ctx.fillText(shown, 9, y);
  ctx.restore();
}

function attachStatusLine(app, node) {
  if (node.__ltrStatus) return;
  node.__ltrStatus = true;
  const orig = node.onDrawForeground;
  node.onDrawForeground = function (ctx) {
    if (typeof orig === "function") {
      try {
        orig.apply(this, arguments);
      } catch (err) {
        /* 忽略原实现的错误，别影响我们画状态行 */
      }
    }
    try {
      drawStatusLine(ctx, this);
    } catch (err) {
      /* 画不出来就算了，绝不能影响工作流 */
    }
  };
  // 连线变化 / 节点被删时清掉缓存，让状态行立刻刷新
  const origConn = node.onConnectionsChange;
  node.onConnectionsChange = function () {
    node.__ltrDetected = null;
    if (typeof origConn === "function") {
      try {
        return origConn.apply(this, arguments);
      } catch (err) {
        /* 忽略 */
      }
    }
  };
}

/* ------------------------------------------------------------------ 注册 */

function addButtons(app, node, kind) {
  if (!node || node.__ltrButtons) return;
  node.__ltrButtons = true;

  if (kind === "auto") {
    node.addWidget("button", "🎯 手动补充 LoRA（触发词选择器）", null, () =>
      openPicker(app, node, node.comfyClass === NODE_AUTO_MULTI ? "auto-multi" : "auto-single")
    );
    node.addWidget("button", "🔄 重新扫描链路 / LoRA 文本", null, async () => {
      node.__ltrDetected = null;
      const chain = detectedLoras(node, true);
      const data = await fetchList(true);
      toast(
        "success",
        "已重新扫描",
        `链路检测到 ${chain.length} 个 LoRA；文本目录共 ${data.items.length} 个 LoRA`
      );
    });
  } else if (kind === "loader") {
    node.addWidget("button", "🎯 选择 LoRA（写入下拉框）", null, () => openPicker(app, node, "loader"));
    node.addWidget("button", "🔄 重新扫描 LoRA 文本", null, async () => {
      node.__ltrDetected = null;
      const data = await fetchList(true);
      const rows = loaderSlotNames(node).length;
      const total = loaderListNames(node).length;
      toast(
        "success",
        "已重新扫描",
        `下拉框选了 ${rows} 行、合计 ${total} 个 LoRA；文本目录共 ${data.items.length} 个 LoRA（重新打开下拉框即可看到新 LoRA）`
      );
    });
  } else if (kind === "info") {
    node.addWidget("button", "🎯 选择 LoRA（含触发词预览）", null, () => openPicker(app, node, "info"));
    node.addWidget("button", "📄 查看该 LoRA 的触发词文本", null, async () => {
      const name = findWidget(node, INFO_WIDGET)?.value;
      if (!name) {
        toast("warn", "还没选 LoRA");
        return;
      }
      try {
        const data = await fetchText(name);
        if (data.status === "ok") openTextViewer(`${name} (${data.encoding})`, data.text);
        else if (data.status === "empty") openTextViewer(`${name}`, "(找到了触发词文本，但文件是空的)");
        else openTextViewer(`${name}`, `没有找到触发词文本（status=${data.status}）`);
      } catch (err) {
        toast("error", "读取失败", String(err));
      }
    });
  }

  // 所有节点都有：中英文使用说明（后端 help_docs 提供内容）
  node.addWidget("button", "❓ 使用说明 / Help", null, () => {
    openHelp(app, node);
  });
}

(async () => {
  const app = await getApp();
  if (!app || typeof app.registerExtension !== "function") {
    console.warn("[LoRATriggerReader] 找不到 app 对象，前端增强已跳过（节点本身仍可正常使用）");
    return;
  }
  try {
    app.registerExtension({
      name: EXT_NAME,
      nodeCreated(node) {
        const t = typeOf(node);
        try {
          if (AUTO_TYPES.indexOf(t) >= 0) {
            addButtons(app, node, "auto");
            attachStatusLine(app, node);
          } else if (t === NODE_LOADER) {
            addButtons(app, node, "loader");
            attachStatusLine(app, node);
          } else if (t === NODE_INFO) {
            addButtons(app, node, "info");
          }
        } catch (err) {
          console.warn("[LoRATriggerReader] 添加按钮失败（已忽略）", err);
        }
      },
    });
    console.info(`[LoRATriggerReader] 前端增强已加载 (v${VERSION})`);
  } catch (err) {
    console.warn("[LoRATriggerReader] 注册扩展失败（已忽略）", err);
  }
})();
