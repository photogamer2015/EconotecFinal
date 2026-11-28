/*
 * Econotec CRM · Puente de WhatsApp por código QR (sin API de Meta)
 * ---------------------------------------------------------------
 * Se vincula al número escaneando un QR, igual que WhatsApp Web (librería whatsapp-web.js).
 *   1. Llega un mensaje  → se envía al CRM (/crm/api/whatsapp/qr/entrante/) → el CRM devuelve la respuesta del bot
 *                          → se manda por WhatsApp.
 *   2. Un asesor responde en el CRM → el CRM llama a este programa (POST /enviar) → sale por WhatsApp.
 *
 * Arranque: npm install (solo la primera vez) y luego npm start.
 * La sesión queda guardada en .wwebjs_auth/: el QR se escanea una sola vez.
 */
const fs = require("fs");
const http = require("http");
const path = require("path");
const QRCode = require("qrcode");
const qrcodeTerminal = require("qrcode-terminal");
const { Client, LocalAuth } = require("whatsapp-web.js");

// ---------- Configuración: se lee del .env de Econotec (carpeta de arriba) ----------
function leerEnv(archivo) {
  const vars = {};
  try {
    for (const linea of fs.readFileSync(archivo, "utf8").split(/\r?\n/)) {
      const m = linea.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/);
      if (m) vars[m[1]] = m[2].replace(/^["']|["']$/g, "");
    }
  } catch (e) { /* sin .env: se usan las variables del sistema */ }
  return vars;
}
const ENV = { ...leerEnv(path.join(__dirname, "..", ".env")), ...process.env };
const TOKEN = ENV.WA_QR_TOKEN || "";
const CRM_URL = (ENV.CRM_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
const PUERTO = Number(new URL(ENV.WA_QR_URL || "http://127.0.0.1:3010").port || 3010);
const MAPA = path.join(__dirname, "mapa.json"); // número → chat de WhatsApp (para responder al chat correcto)

if (!TOKEN) {
  console.error("Falta WA_QR_TOKEN en el .env de Econotec. Escribe una clave larga, por ejemplo WA_QR_TOKEN=econotec-bot-una-clave-larga");
  process.exit(1);
}

let estado = "iniciando";
let qrDataUrl = null;
let numeroPropio = "";
const inicio = Date.now();
let mapa = {};
try { mapa = JSON.parse(fs.readFileSync(MAPA, "utf8")); } catch (e) { mapa = {}; }
const guardarMapa = () => fs.writeFile(MAPA, JSON.stringify(mapa), () => {});
const hora = () => new Date().toLocaleTimeString("es-EC", { hour: "2-digit", minute: "2-digit" });
const log = (...a) => console.log(`[${hora()}]`, ...a);
const espera = ms => new Promise(r => setTimeout(r, ms));

// ---------- Cliente de WhatsApp ----------
// WA_QR_VISIBLE=True en .env abre la ventana de Chrome (útil si el modo oculto no carga WhatsApp Web)
const VISIBLE = String(ENV.WA_QR_VISIBLE || "").toLowerCase() === "true";
const client = new Client({
  authStrategy: new LocalAuth({ dataPath: path.join(__dirname, ".wwebjs_auth") }),
  authTimeoutMs: 180000, // la primera carga de WhatsApp Web puede tardar más de 30 s
  puppeteer: {
    headless: !VISIBLE,
    protocolTimeout: 300000,
    args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
  },
});

let intentos = 0;
function iniciar() {
  intentos += 1;
  estado = "iniciando";
  client.initialize().catch(async e => {
    estado = "desconectado";
    log(`No se pudo iniciar WhatsApp (intento ${intentos}): ${e.message}`);
    if (intentos < 5) {
      log("Reintentando en 10 s…");
      try { await client.destroy(); } catch (x) { /* nada */ }
      setTimeout(iniciar, 10000);
    } else {
      log("Revisa tu internet. Si sigue igual, pon WA_QR_VISIBLE=True en .env y vuelve a ejecutar npm start.");
    }
  });
}

client.on("qr", async qr => {
  estado = "esperando_qr";
  qrDataUrl = await QRCode.toDataURL(qr, { margin: 1, width: 280 });
  log("Escanea este código con WhatsApp → Dispositivos vinculados → Vincular un dispositivo");
  log("(también aparece en el CRM de Econotec: Ajustes de WhatsApp → Conexión)");
  qrcodeTerminal.generate(qr, { small: true });
});
client.on("authenticated", () => { log("Sesión autenticada."); qrDataUrl = null; });
client.on("auth_failure", m => { estado = "desconectado"; log("Falló la autenticación:", m); });
client.on("ready", () => {
  estado = "conectado";
  qrDataUrl = null;
  numeroPropio = (client.info && client.info.wid && client.info.wid.user) || "";
  log(`✓ WhatsApp conectado (+${numeroPropio}). El bot ya responde los mensajes.`);
});
client.on("disconnected", async motivo => {
  estado = "desconectado";
  log("WhatsApp se desconectó:", motivo, "— reintentando en 10 s…");
  await espera(10000);
  try { await client.destroy(); } catch (e) { /* ya estaba cerrado */ }
  intentos = 0;
  iniciar();
});

// Cola por chat: las respuestas salen en orden y con una pausa natural
const colas = {};
function enCola(chatId, tarea) {
  colas[chatId] = (colas[chatId] || Promise.resolve()).then(tarea).catch(e => log("Error en", chatId, e.message));
  return colas[chatId];
}

const IGNORAR = new Set(["e2e_notification", "notification_template", "call_log", "protocol", "revoked", "ciphertext", "gp2"]);

client.on("message", msg => {
  // Solo chats individuales que escriben al número; nada de grupos, estados ni difusiones
  if (msg.fromMe || msg.isStatus || msg.broadcast) return;
  if (!msg.from || msg.from.endsWith("@g.us") || msg.from === "status@broadcast" || msg.from.endsWith("@newsletter")) return;
  if (IGNORAR.has(msg.type)) return;
  if (msg.timestamp && msg.timestamp * 1000 < inicio - 60000) return; // mensajes viejos al reconectar

  enCola(msg.from, async () => {
    let numero = msg.from.split("@")[0];
    let nombre = "";
    try {
      const c = await msg.getContact();
      numero = c.number || numero;
      nombre = c.pushname || c.name || "";
    } catch (e) { /* sin datos del contacto */ }
    mapa[numero] = msg.from;
    guardarMapa();

    const texto = msg.type === "chat" ? msg.body : `[${msg.type === "ptt" ? "nota de voz" : msg.type} recibido]${msg.body ? " " + msg.body : ""}`;
    log(`← ${nombre || numero}: ${texto.slice(0, 80)}`);

    let datos;
    try {
      const r = await fetch(`${CRM_URL}/crm/api/whatsapp/qr/entrante/`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Bridge-Token": TOKEN },
        body: JSON.stringify({ numero, nombre, texto, id: msg.id && msg.id._serialized }),
      });
      datos = await r.json();
      if (!r.ok) { log("El CRM rechazó el mensaje:", datos.error || r.status); return; }
    } catch (e) {
      log("No se pudo hablar con el CRM (¿está abierto en", CRM_URL + "?):", e.message);
      return;
    }

    for (const respuesta of datos.respuestas || []) {
      try { const chat = await msg.getChat(); await chat.sendStateTyping(); } catch (e) { /* opcional */ }
      await espera(1200 + Math.random() * 1300); // pausa humana: evita parecer spam
      await client.sendMessage(msg.from, respuesta);
      log(`→ Bot a ${nombre || numero}: ${respuesta.split("\n")[0].slice(0, 80)}`);
    }
  });
});

// ---------- Mini servidor local para el CRM ----------
function responder(res, codigo, obj) {
  res.writeHead(codigo, { "Content-Type": "application/json" });
  res.end(JSON.stringify(obj));
}

http.createServer((req, res) => {
  if (req.headers["x-bridge-token"] !== TOKEN) return responder(res, 403, { ok: false, error: "Token inválido" });

  if (req.method === "GET" && req.url === "/estado") {
    return responder(res, 200, { estado, qr: qrDataUrl, numero: numeroPropio });
  }

  if (req.method === "POST" && req.url === "/enviar") {
    let cuerpo = "";
    req.on("data", c => { cuerpo += c; if (cuerpo.length > 1e6) req.destroy(); });
    req.on("end", async () => {
      let d;
      try { d = JSON.parse(cuerpo || "{}"); } catch (e) { return responder(res, 400, { ok: false, error: "JSON inválido" }); }
      const numero = String(d.numero || "").replace(/\D/g, "");
      const texto = String(d.texto || "").trim();
      if (!numero || !texto) return responder(res, 400, { ok: false, error: "Faltan número o texto" });
      if (estado !== "conectado") return responder(res, 503, { ok: false, error: "WhatsApp no conectado" });
      const chatId = mapa[numero] || `${numero}@c.us`;
      let enviado = false;
      await enCola(chatId, async () => { await client.sendMessage(chatId, texto); enviado = true; });
      if (!enviado) return responder(res, 500, { ok: false, error: "No se pudo enviar" });
      log(`→ Asesor a +${numero}: ${texto.split("\n")[0].slice(0, 80)}`);
      responder(res, 200, { ok: true });
    });
    return;
  }

  responder(res, 404, { ok: false, error: "Ruta no encontrada" });
}).listen(PUERTO, "127.0.0.1", () => {
  log(`Puente de WhatsApp escuchando en http://127.0.0.1:${PUERTO} · CRM: ${CRM_URL}`);
  log("Iniciando WhatsApp (la primera vez puede tardar 1-2 minutos)…");
  iniciar();
});

process.on("SIGINT", async () => { log("Cerrando WhatsApp…"); try { await client.destroy(); } catch (e) {} process.exit(0); });
process.on("SIGTERM", async () => { try { await client.destroy(); } catch (e) {} process.exit(0); });
