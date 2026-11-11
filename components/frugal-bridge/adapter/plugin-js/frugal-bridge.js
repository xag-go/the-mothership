// Frugal-Bridge plugin for opencode (V1 and V2 plugin APIs) and Kilo Code CLI (opencode V1 API).
// Setup copies it to ~/.config/opencode/plugins/ or ~/.config/kilo/plugin/ and fills in the two paths below.
// - Output filter: shell output over ~12k chars is cut to head + error lines + tail; full text saved, path given.
// - Start files: on a session's first model call, the "now" / "user" files to read first (asks frugal_hook.py,
//   the same resolver as the Claude Code hook), added to the system prompt once per session.
// - Usage: assistant message token counts (V1 message.updated) appended to $FRUGAL_HOME/usage.jsonl.
// Never throws into the host: every handler catches its own errors. Node standard library only.
import { execFileSync } from "node:child_process"
import { appendFileSync, mkdirSync, writeFileSync } from "node:fs"
import { join } from "node:path"

const HOOK = "__FRUGAL_HOOK__"
const FRUGAL_HOME = "__FRUGAL_HOME__"
const TOOL = "__FRUGAL_TOOL__"
const LIMIT = 12000
const SHELL = /^(bash|shell|run_shell_command|terminal|exec)$/i
const ERR = /(error|exception|traceback|failed|fail\b|fatal|panic|denied|not found|warning)/i

export function filterOutput(text, limit = LIMIT) {
  if (typeof text !== "string" || text.length <= limit) return null
  const lines = text.split("\n")
  const head = lines.slice(0, 40), tail = lines.slice(-60)
  const errs = []
  lines.slice(40, -60).forEach((l, i) => { if (ERR.test(l) && errs.length < 40) errs.push(`${i + 41}: ${l.slice(0, 300)}`) })
  let path = ""
  try {
    const d = join(FRUGAL_HOME, "outputs"); mkdirSync(d, { recursive: true })
    path = join(d, `${Date.now()}-shell-${process.pid}.log`); writeFileSync(path, text)
  } catch { path = "" }
  const out = [head.join("\n"), `\n[frugal-bridge] output cut: ${lines.length} lines, ${text.length} chars.`]
  if (errs.length) out.push("Error-looking lines in the cut part:\n" + errs.join("\n"))
  out.push("... last 60 lines:\n" + tail.join("\n"))
  if (path) out.push(`[full output saved: ${path} — grep it instead of re-running]`)
  return out.join("\n")
}

const started = new Set()
export function startHint(cwd) {
  try {
    const out = execFileSync("python3", [HOOK, "--tool", TOOL, "--event", "start"], {
      input: JSON.stringify({ hook_event_name: "SessionStart", cwd: cwd || process.cwd() }), timeout: 10000,
    }).toString().trim()
    return out ? JSON.parse(out).hookSpecificOutput.additionalContext : null
  } catch { return null }
}

export function logUsage(info) {
  try {
    const t = info && info.tokens
    if (!t || info.role !== "assistant") return false
    const cr = (t.cache && t.cache.read) || 0, cw = (t.cache && t.cache.write) || 0
    const rec = { ts: Date.now() / 1000, session: info.sessionID || "?", model: info.modelID || "", provider: info.providerID || "",
      context: (t.input || 0) + cr + cw, input: t.input || 0, output: (t.output || 0) + (t.reasoning || 0), cache_read: cr,
      cache_write: cw, tool: TOOL }
    mkdirSync(FRUGAL_HOME, { recursive: true }); appendFileSync(join(FRUGAL_HOME, "usage.jsonl"), JSON.stringify(rec) + "\n")
    return true
  } catch { return false }
}

const logged = new Set()

// V1 API (opencode 1.x, Kilo): an async function returning hooks
export async function server(input) {
  const cwd = (input && (input.directory || input.worktree)) || process.cwd()
  return {
    "tool.execute.after": async (inp, output) => {
      try {
        if (!SHELL.test((inp && inp.tool) || "")) return
        const cut = filterOutput(output && output.output)
        if (cut) output.output = cut
      } catch {}
    },
    "experimental.chat.system.transform": async (inp, output) => {
      try {
        const sid = (inp && (inp.sessionID || (inp.session && inp.session.id))) || "?"
        if (started.has(sid)) return
        started.add(sid)
        const h = startHint(cwd)
        if (h && output && Array.isArray(output.system)) output.system.push(h)
      } catch {}
    },
    event: async ({ event }) => {
      try {
        if (event && event.type === "message.updated") {
          const info = event.properties && event.properties.info
          const key = info && `${info.id}:${info.time && info.time.completed}`
          if (info && info.time && info.time.completed && !logged.has(key)) { logged.add(key); logUsage(info) }
        }
      } catch {}
    },
  }
}

// V2 API (opencode 2.x): Plugin.define-shaped object
async function setup(ctx) {
  try {
    await ctx.tool.hook("execute.after", (event) => {
      try {
        if (event.status !== "completed" || !SHELL.test(event.tool || "")) return
        const r = event.result
        const text = typeof r === "string" ? r : r && typeof r.output === "string" ? r.output : null
        const cut = filterOutput(text)
        if (cut) event.result = typeof r === "string" ? cut : { ...r, output: cut }
      } catch {}
    })
    await ctx.session.hook("context", (event) => {
      try {
        const sid = (event.session && event.session.id) || event.sessionID || "?"
        if (started.has(sid)) return
        started.add(sid)
        const h = startHint(ctx.location && ctx.location.directory)
        if (h && Array.isArray(event.system)) event.system.push({ type: "text", text: h })
      } catch {}
    })
  } catch {}
}

export default { id: "frugal-bridge", setup, server }
