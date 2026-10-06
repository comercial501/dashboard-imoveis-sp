// Teste ponta a ponta LOCAL da trava, no mesmo motor do Cloudflare (workerd, via
// `wrangler pages dev`), com um servidor de chaves falso. Sem conta Cloudflare.
// Uso (da raiz do repositório): python3 scripts/preparar_pasta_cloudflare.py && node scripts/test_cloudflare_e2e.mjs
import http from "node:http";
import { spawn } from "node:child_process";

const TEAM_PORTA = 8791, SITE_PORTA = 8788, AUD = "aud-e2e";
const TEAM = `http://127.0.0.1:${TEAM_PORTA}`;
const b64 = (o) => Buffer.from(typeof o === "string" ? o : JSON.stringify(o)).toString("base64url");
const falhas = [];
const ok = (c, n) => { console.log((c ? "OK   " : "FALHOU ") + n); if (!c) falhas.push(n); };

const par = await crypto.subtle.generateKey({ name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" }, true, ["sign", "verify"]);
const falso = await crypto.subtle.generateKey({ name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" }, true, ["sign", "verify"]);
const jwk = { ...(await crypto.subtle.exportKey("jwk", par.publicKey)), kid: "k1", alg: "RS256", use: "sig" };
const certs = http.createServer((q, r) => { r.setHeader("content-type", "application/json"); r.end(JSON.stringify({ keys: [jwk] })); }).listen(TEAM_PORTA, "127.0.0.1");
async function token(chave = par.privateKey, aud = AUD, exp = 600) {
  const agora = Math.floor(Date.now() / 1000);
  const h = b64({ alg: "RS256", kid: "k1" }), p = b64({ aud: [aud], iss: TEAM, exp: agora + exp, email: "teste@exemplo.com" });
  const s = Buffer.from(await crypto.subtle.sign("RSASSA-PKCS1-v1_5", chave, new TextEncoder().encode(`${h}.${p}`))).toString("base64url");
  return `${h}.${p}.${s}`;
}
const wr = spawn("npx", ["--yes", "wrangler@4", "pages", "dev", "cloudflare-dist", "--port", String(SITE_PORTA), "--ip", "127.0.0.1",
  "--binding", `TEAM_DOMAIN=${TEAM}`, `POLICY_AUD=${AUD}`], { stdio: ["ignore", "pipe", "pipe"] });
let saida = ""; wr.stdout.on("data", (d) => (saida += d)); wr.stderr.on("data", (d) => (saida += d));
const fim = () => { wr.kill("SIGTERM"); certs.close(); };
try {
  const t0 = Date.now();
  while (Date.now() - t0 < 120000) { try { await fetch(`http://127.0.0.1:${SITE_PORTA}/`); break; } catch { await new Promise((r) => setTimeout(r, 1000)); } }
  const get = (caminho, tok) => fetch(`http://127.0.0.1:${SITE_PORTA}${caminho}`, { headers: tok ? { "cf-access-jwt-assertion": tok } : {} });
  const arquivos = ["/", "/index.html", "/app.js", "/engine.js", "/styles.css", "/data.json", "/raw.json"];
  for (const a of arquivos) { const r = await get(a); ok(r.status === 403, `anônimo: ${a} → ${r.status}`); }
  for (const a of ["/serve_no_cache.py", "/itbi_clean_log.json", "/historico/anuncios.jsonl", "/output/preco_m2_por_bairro.csv", "/_headers", "/functions/_middleware.js"]) { const r = await get(a); ok(r.status === 403, `anônimo: ${a} → ${r.status}`); }
  let r = await get("/data.json", await token(falso.privateKey)); ok(r.status === 403, "token falsificado: data.json → 403");
  r = await get("/data.json", await token(par.privateKey, "outro-app")); ok(r.status === 403, "token de outro aplicativo: data.json → 403");
  r = await get("/data.json", await token(par.privateKey, AUD, -10)); ok(r.status === 403, "token vencido: data.json → 403");
  const bom = await token();
  r = await get("/", bom); ok(r.status === 200 && (await r.text()).includes("Torre de Controle"), "com login válido: página abre (200)");
  r = await get("/data.json", bom); const txt = await r.text(); ok(r.status === 200 && txt.startsWith("{") && JSON.parse(txt).bairros, "com login válido: data.json (200, JSON íntegro)");
  ok((r.headers.get("x-robots-tag") || "").includes("noindex"), "cabeçalho noindex presente");
  r = await get("/raw.json", bom); const n = (await r.arrayBuffer()).byteLength; ok(r.status === 200 && n > 1e6, `com login válido: raw.json (200, ${(n / 1048576).toFixed(1)} MiB)`);
} finally { fim(); }
console.log(); if (falhas.length) { console.log(`${falhas.length} falha(s)`); console.log(saida.slice(-1500)); process.exit(1); }
console.log("Teste ponta a ponta passou.");
