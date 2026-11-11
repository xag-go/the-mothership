// Frugal-Bridge plugin for Amp (~/.config/amp/plugins/frugal-bridge.js; setup fills in the paths below).
// - Output filter: shell tool results over ~12k chars are cut to head + error lines + tail (full text saved).
// - Start files: on each thread's first turn, the "now" / "user" files to read first are appended to the prompt
//   (hidden), from frugal_hook.py (the same resolver as the other tools).
// Amp subagents run the thread's model: no per-helper tier here. Never throws into Amp.
import { execFileSync } from "node:child_process"
import { mkdirSync, writeFileSync } from "node:fs"
import { join } from "node:path"

const HOOK = "__FRUGAL_HOOK__"
const FRUGAL_HOME = "__FRUGAL_HOME__"
const LIMIT = 12000
const SHELL = /^(bash|shell|terminal|exec)$/i
const ERR = /(error|exception|traceback|failed|fail\b|fatal|panic|denied|not found|warning)/i

export function filterOutput(text, limit = LIMIT) {
  if (typeof text !== "string" || text.length <= limit) return null
  const lines = text.split("\n")
  const errs = []
  lines.slice(40, -60).forEach((l, i) => { if (ERR.test(l) && errs.length < 40) errs.push(`${i + 41}: ${l.slice(0, 300)}`) })
  let path = ""
  try {
    const d = join(FRUGAL_HOME, "outputs"); mkdirSync(d, { recursive: true })
    path = join(d, `${Date.now()}-amp-${process.pid}.log`); writeFileSync(path, text)
  } catch { path = "" }
  const out = [lines.slice(0, 40).join("\n"), `\n[frugal-bridge] output cut: ${lines.length} lines, ${text.length} chars.`]
  if (errs.length) out.push("Error-looking lines in the cut part:\n" + errs.join("\n"))
  out.push("... last 60 lines:\n" + lines.slice(-60).join("\n"))
  if (path) out.push(`[full output saved: ${path} — grep it instead of re-running]`)
  return out.join("\n")
}

function startHint() {
  try {
    const out = execFileSync("python3", [HOOK, "--tool", "amp", "--event", "start"], {
      input: JSON.stringify({ hook_event_name: "SessionStart", cwd: process.cwd() }), timeout: 10000,
    }).toString().trim()
    return out ? JSON.parse(out).hookSpecificOutput.additionalContext : null
  } catch { return null }
}

const started = new Set()

export default function (amp) {
  amp.on("tool.result", async (event) => {
    try {
      if (!SHELL.test(event.tool || "")) return
      const cut = filterOutput(typeof event.output === "string" ? event.output : null)
      if (cut) return { status: event.status, output: cut }
    } catch {}
  })
  amp.on("agent.start", async (event) => {
    try {
      const tid = event.threadID || event.thread || "?"
      if (started.has(tid)) return
      started.add(tid)
      const h = startHint()
      if (h) return { message: h }
    } catch {}
  })
}
