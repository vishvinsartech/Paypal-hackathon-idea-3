// Launches the PayPal MCP server for Claude Code (.mcp.json) with a FRESH sandbox access token.
// Reads PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET from .env (or the environment), refuses anything but the PayPal
// sandbox, gets a client-credentials token, then runs `npx -y @paypal/mcp --tools=all` with it. So the server no
// longer depends on PAYPAL_ACCESS_TOKEN being exported in the shell that started VS Code, and every (re)connect
// gets a new token (sandbox tokens expire after a few hours). stdout is the MCP channel: logs go to stderr only.
import {spawn} from "node:child_process";
import {existsSync, readFileSync} from "node:fs";
import {dirname, join} from "node:path";
import {fileURLToPath} from "node:url";

const SANDBOX = "https://api-m.sandbox.paypal.com";
const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const log = (msg) => process.stderr.write(`[mcp_paypal] ${msg}\n`);

function readEnv(path) {
  const out = {};
  if (!existsSync(path)) return out;
  for (const raw of readFileSync(path, "utf8").split(/\r?\n/)) {
    const m = raw.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/);
    if (!m) continue;
    let v = m[2];
    const q = v[0];
    if ((q === "'" || q === '"') && v.indexOf(q, 1) > 0) v = v.slice(1, v.indexOf(q, 1));  // quoted value
    else v = v.replace(/\s+#.*$/, "").trim();  // unquoted: drop an inline comment
    out[m[1]] = v;
  }
  return out;
}

const env = {...readEnv(join(root, ".env")), ...Object.fromEntries(Object.entries(process.env).filter(([, v]) => v))};
const base = env.PAYPAL_API_BASE || SANDBOX;
if (base !== SANDBOX) { log(`Refusing: SubGuard is sandbox only (PAYPAL_API_BASE=${base})`); process.exit(1); }
if (!env.PAYPAL_CLIENT_ID || !env.PAYPAL_CLIENT_SECRET) {
  log("PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET missing in .env (see .env.example)");
  process.exit(1);
}

let token;
try {
  const res = await fetch(`${base}/v1/oauth2/token`, {
    method: "POST", body: "grant_type=client_credentials",
    headers: {"Content-Type": "application/x-www-form-urlencoded",
              Authorization: "Basic " + Buffer.from(`${env.PAYPAL_CLIENT_ID}:${env.PAYPAL_CLIENT_SECRET}`).toString("base64")},
  });
  const data = await res.json();
  if (!res.ok || !data.access_token) throw new Error(`HTTP ${res.status} ${data.error || ""}`.trim());
  token = data.access_token;
} catch (err) {
  log(`Couldn't get a PayPal sandbox token: ${err.message}`);
  process.exit(1);
}
log("got a fresh sandbox token; starting @paypal/mcp");

const child = spawn("npx -y @paypal/mcp --tools=all", {
  shell: true, stdio: "inherit", cwd: root,
  env: {...process.env, PAYPAL_ACCESS_TOKEN: token, PAYPAL_ENVIRONMENT: "SANDBOX"},
});
child.on("exit", (code) => process.exit(code ?? 0));
for (const sig of ["SIGINT", "SIGTERM"]) process.on(sig, () => child.kill(sig));
