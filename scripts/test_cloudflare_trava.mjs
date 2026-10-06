// Testes da trava de acesso (functions/_middleware.js) sem rede e sem Cloudflare:
// gera um par de chaves RSA, assina tokens falsos e finge ser o servidor de chaves.
// Uso: node scripts/test_cloudflare_trava.mjs
import { onRequest } from "../functions/_middleware.js";

const falhas = [];
const ok = (cond, nome) => { console.log((cond ? "OK   " : "FALHOU ") + nome); if (!cond) falhas.push(nome); };
const b64 = (obj) => Buffer.from(typeof obj === "string" ? obj : JSON.stringify(obj)).toString("base64url");

const TEAM = "https://equipe-teste.cloudflareaccess.com";
const AUD = "aud-do-aplicativo-123";
const env = { TEAM_DOMAIN: TEAM, POLICY_AUD: AUD };

const par = await crypto.subtle.generateKey({ name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" }, true, ["sign", "verify"]);
const outro = await crypto.subtle.generateKey({ name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" }, true, ["sign", "verify"]);
const jwkPublica = { ...(await crypto.subtle.exportKey("jwk", par.publicKey)), kid: "chave-1", alg: "RS256", use: "sig" };
let buscas = 0;
globalThis.fetch = async (url) => {
  buscas++;
  if (String(url) === `${TEAM}/cdn-cgi/access/certs`) return new Response(JSON.stringify({ keys: [jwkPublica] }), { status: 200 });
  return new Response("nada", { status: 404 });
};

async function token({ chave = par.privateKey, kid = "chave-1", alg = "RS256", payload = {} } = {}) {
  const agora = Math.floor(Date.now() / 1000);
  const corpo = { aud: [AUD], iss: TEAM, exp: agora + 600, iat: agora, email: "paulo@exemplo.com", ...payload };
  const h = b64({ alg, kid, typ: "JWT" }), p = b64(corpo);
  const sig = alg === "none" ? "" : Buffer.from(await crypto.subtle.sign("RSASSA-PKCS1-v1_5", chave, new TextEncoder().encode(`${h}.${p}`))).toString("base64url");
  return `${h}.${p}.${sig}`;
}
const chamar = async (tok, e = env, url = "https://site.pages.dev/data.json") => {
  const headers = tok ? { "cf-access-jwt-assertion": tok } : {};
  let passou = false;
  const r = await onRequest({ request: new Request(url, { headers }), env: e, next: async () => { passou = true; return new Response("DADOS"); } });
  return { status: r.status, passou, texto: await r.text() };
};

let r = await chamar(await token());
ok(r.status === 200 && r.passou && r.texto === "DADOS", "token válido: entrega o arquivo");
r = await chamar(null);
ok(r.status === 403 && !r.passou, "sem token (acesso direto): 403, não entrega nada");
r = await chamar("lixo.lixo.lixo");
ok(r.status === 403 && !r.passou, "token que não é token: 403");
r = await chamar(await token({ chave: outro.privateKey }));
ok(r.status === 403 && !r.passou, "assinado com outra chave (falsificado): 403");
r = await chamar(await token({ payload: { aud: ["outro-aplicativo"] } }));
ok(r.status === 403 && !r.passou, "token de OUTRO aplicativo (aud errado): 403");
r = await chamar(await token({ payload: { iss: "https://invasor.cloudflareaccess.com" } }));
ok(r.status === 403 && !r.passou, "emissor errado: 403");
r = await chamar(await token({ payload: { exp: Math.floor(Date.now() / 1000) - 5 } }));
ok(r.status === 403 && !r.passou, "token vencido: 403");
r = await chamar(await token({ alg: "none" }));
ok(r.status === 403 && !r.passou, 'algoritmo "none": 403');
r = await chamar(await token({ kid: "chave-que-nao-existe" }));
ok(r.status === 403 && !r.passou, "chave desconhecida: 403");
r = await chamar(await token({ payload: { aud: AUD } }));
ok(r.status === 200 && r.passou, "aud como texto (não lista) também vale");
for (const caminho of ["/", "/index.html", "/data.json", "/raw.json", "/app.js", "/engine.js", "/styles.css", "/qualquer/coisa.csv"]) {
  const x = await chamar(null, env, `https://site.pages.dev${caminho}`);
  ok(x.status === 403 && !x.passou, `sem login: ${caminho} → 403`);
}
r = await chamar(await token(), { TEAM_DOMAIN: TEAM });
ok(r.status === 503 && !r.passou, "sem POLICY_AUD configurado: 503 (fecha tudo)");
r = await chamar(await token(), {});
ok(r.status === 503 && !r.passou, "variáveis ausentes: 503 (fecha tudo)");
const antes = buscas;
await chamar(await token()); await chamar(await token());
ok(buscas === antes, "as chaves públicas ficam em cache (não busca a cada pedido)");
globalThis.fetch = async () => new Response("erro", { status: 500 });
r = await chamar(await token({ kid: "chave-nova" }));
ok(r.status === 403 && !r.passou, "servidor de chaves fora do ar + chave desconhecida: 403 (fecha, não abre)");

console.log();
if (falhas.length) { console.log(`${falhas.length} teste(s) falharam`); process.exit(1); }
console.log("Todos os testes da trava passaram.");
