// Minimal MCP client for the user's configured "bambu-printer" server.
// Usage:
//   node bambu_call.mjs list [toolName ...]        -> tool names (and schemas for named tools)
//   node bambu_call.mjs call <toolName> '<json args>' [timeoutSec]
// Reads the server config from ~/.claude.json. Never prints the access code;
// any occurrence of it in output is replaced with [redacted].
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const cfg = JSON.parse(fs.readFileSync(path.join(os.homedir(), ".claude.json"), "utf8"))
  .mcpServers?.["bambu-printer"];
if (!cfg) { console.error("bambu-printer is not configured"); process.exit(1); }
const secret = cfg.env?.BAMBU_TOKEN || "";
const redact = (s) => (secret ? String(s).split(secret).join("[redacted]") : String(s));

const [mode, toolName, argJson = "{}", rawTimeout = "90"] = process.argv.slice(2);
const timeoutSec = mode === "list" ? "60" : rawTimeout;
const p = spawn(cfg.command, cfg.args || [], {
  env: { ...process.env, ...(cfg.env || {}), MCP_TRANSPORT: "stdio" },
  stdio: ["pipe", "pipe", "pipe"],
});
let stderr = "";
p.stderr.on("data", (d) => { stderr += d; });
const send = (m) => p.stdin.write(JSON.stringify(m) + "\n");
const finish = (code) => { try { p.kill(); } catch {} process.exit(code); };
const timer = setTimeout(() => {
  console.log("TIMEOUT after " + timeoutSec + "s");
  if (stderr) console.log("stderr tail:\n" + redact(stderr.slice(-1500)));
  finish(2);
}, Number(timeoutSec) * 1000);

let buf = "";
p.stdout.on("data", (d) => {
  buf += d;
  let i;
  while ((i = buf.indexOf("\n")) >= 0) {
    const line = buf.slice(0, i); buf = buf.slice(i + 1);
    let m; try { m = JSON.parse(line); } catch { continue; }
    if (m.id === 1) {
      send({ jsonrpc: "2.0", method: "notifications/initialized" });
      if (mode === "list") send({ jsonrpc: "2.0", id: 2, method: "tools/list" });
      else send({ jsonrpc: "2.0", id: 2, method: "tools/call",
                  params: { name: toolName, arguments: JSON.parse(argJson) } });
    }
    if (m.id === 2) {
      clearTimeout(timer);
      if (mode === "list") {
        const wanted = process.argv.slice(3);
        for (const t of m.result.tools) {
          if (wanted.length === 0) console.log(t.name);
          else if (wanted.includes(t.name)) {
            console.log("== " + t.name + "\n" + t.description + "\n" + JSON.stringify(t.inputSchema, null, 1));
          }
        }
        finish(0);
      }
      if (m.error) { console.log("ERROR: " + redact(JSON.stringify(m.error))); finish(1); }
      for (const c of m.result?.content || []) {
        if (c.type === "text") console.log(redact(c.text));
        else if (c.type === "image") {
          const ext = (c.mimeType || "image/jpeg").split("/")[1];
          const out = path.join(os.homedir(), "Downloads", "X2D-prints", `snapshot_${Date.now()}.${ext}`);
          fs.writeFileSync(out, Buffer.from(c.data, "base64"));
          console.log("IMAGE saved: " + out);
        } else console.log(redact(JSON.stringify(c).slice(0, 2000)));
      }
      finish(m.result?.isError ? 1 : 0);
    }
  }
});
send({ jsonrpc: "2.0", id: 1, method: "initialize", params: {
  protocolVersion: "2025-06-18", capabilities: {},
  clientInfo: { name: "claude-session-helper", version: "1" } } });
