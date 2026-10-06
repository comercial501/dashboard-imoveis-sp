// Torre de Controle — trava de acesso (Cloudflare Pages Functions).
//
// Roda ANTES de qualquer arquivo do site (index.html, app.js, data.json,
// raw.json...). Só entrega o arquivo se o pedido veio do Cloudflare Access com
// um login válido: confere a assinatura do token (cabeçalho Cf-Access-Jwt-Assertion),
// o emissor (TEAM_DOMAIN), o aplicativo (POLICY_AUD) e a validade.
// Sem token, token falso, vencido ou de outro aplicativo = 403. Se as duas
// variáveis não estiverem configuradas no Pages = 503 (fecha tudo, nunca abre).
//
// Por que existe, se o Access já protege o endereço? Porque o "Access" do
// próprio Pages só cobre as PRÉVIAS; o endereço de produção e o endereço único de
// cada publicação (<hash>.projeto.pages.dev) dependem de um aplicativo do Access
// configurado à mão. Esta trava garante que, mesmo se algum endereço ficar de
// fora da configuração, os dados não saem sem login.
//
// Variáveis (Pages > Settings > Variables and Secrets):
//   TEAM_DOMAIN  ex.: https://nome-da-equipe.cloudflareaccess.com   (sem barra no fim)
//   POLICY_AUD   "Application Audience (AUD) Tag" do aplicativo no Zero Trust

const CACHE_CHAVES = { tempo: 0, chaves: null };
const CACHE_MS = 60 * 60 * 1000;

function b64urlParaBytes(s) {
  const b = atob(s.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(s.length / 4) * 4, "="));
  return Uint8Array.from(b, (c) => c.charCodeAt(0));
}

function lerJson(parte) {
  return JSON.parse(new TextDecoder().decode(b64urlParaBytes(parte)));
}

async function buscarChaves(teamDomain, forcar) {
  const agora = Date.now();
  if (!forcar && CACHE_CHAVES.chaves && agora - CACHE_CHAVES.tempo < CACHE_MS && CACHE_CHAVES.dominio === teamDomain) {
    return CACHE_CHAVES.chaves;
  }
  const r = await fetch(`${teamDomain}/cdn-cgi/access/certs`);
  if (!r.ok) throw new Error(`certs ${r.status}`);
  const { keys } = await r.json();
  CACHE_CHAVES.tempo = agora;
  CACHE_CHAVES.chaves = keys;
  CACHE_CHAVES.dominio = teamDomain;
  return keys;
}

export async function validarToken(token, env, agoraSeg = Math.floor(Date.now() / 1000)) {
  const partes = token.split(".");
  if (partes.length !== 3) return false;
  const cab = lerJson(partes[0]);
  if (cab.alg !== "RS256" || !cab.kid) return false; // nada de "alg: none" nem de outro algoritmo
  let chaves = await buscarChaves(env.TEAM_DOMAIN, false);
  let jwk = chaves.find((k) => k.kid === cab.kid);
  if (!jwk) { // a Cloudflare troca as chaves de tempos em tempos: busca de novo uma vez
    chaves = await buscarChaves(env.TEAM_DOMAIN, true);
    jwk = chaves.find((k) => k.kid === cab.kid);
    if (!jwk) return false;
  }
  const chave = await crypto.subtle.importKey("jwk", jwk, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"]);
  const ok = await crypto.subtle.verify(
    "RSASSA-PKCS1-v1_5", chave, b64urlParaBytes(partes[2]), new TextEncoder().encode(`${partes[0]}.${partes[1]}`));
  if (!ok) return false;
  const p = lerJson(partes[1]);
  const aud = Array.isArray(p.aud) ? p.aud : [p.aud];
  if (!aud.includes(env.POLICY_AUD)) return false;
  if (p.iss !== env.TEAM_DOMAIN) return false;
  if (typeof p.exp !== "number" || p.exp <= agoraSeg) return false;
  if (typeof p.nbf === "number" && p.nbf > agoraSeg + 60) return false;
  return true;
}

function negar(status, texto) {
  return new Response(texto, { status, headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store", "x-robots-tag": "noindex" } });
}

export async function onRequest(context) {
  const { request, env, next } = context;
  if (!env.TEAM_DOMAIN || !env.POLICY_AUD) return negar(503, "Acesso ainda não configurado.");
  const token = request.headers.get("cf-access-jwt-assertion");
  if (!token) return negar(403, "Acesso negado: faça login pelo endereço oficial.");
  try {
    if (!(await validarToken(token, env))) return negar(403, "Acesso negado.");
  } catch (e) {
    return negar(403, "Acesso negado.");
  }
  return next();
}
