/* CRM Econotec · Botón de WhatsApp para la página web (sin API de WhatsApp).
   Pegar antes de </body>:
     <script src="{{ base }}/crm/widget.js" defer></script>
   Opción: data-lado="izquierda" para ponerlo a la izquierda.
   El visitante deja su nombre y número antes de ir a WhatsApp: así queda registrado como cliente en el CRM
   aunque después no envíe el mensaje. */
(function () {
  if (window.__econotecWidget) return;
  window.__econotecWidget = true;
  var CRM = "{{ base }}/crm";
  var me = document.currentScript || document.querySelector('script[src*="widget.js"]');
  var LADO = (me && me.getAttribute("data-lado")) === "izquierda" ? "left" : "right";
  var KEY = "econotec_boton_v1";
  var st = {};
  try { st = JSON.parse(localStorage.getItem(KEY) || "{}") || {}; } catch (e) { st = {}; }
  function save() { try { localStorage.setItem(KEY, JSON.stringify(st)); } catch (e) {} }
  var cfg = { numero: "", mensaje_boton: "", categorias: [] };

  var WA_ICO = '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M17.47 14.38c-.3-.15-1.75-.86-2.02-.96-.27-.1-.47-.15-.67.15-.2.3-.77.96-.94 1.16-.17.2-.35.22-.64.07-.3-.15-1.25-.46-2.38-1.47-.88-.79-1.47-1.76-1.65-2.06-.17-.3-.02-.46.13-.6.13-.14.3-.35.45-.52.15-.17.2-.3.3-.5.1-.2.05-.37-.03-.52-.07-.15-.67-1.6-.92-2.2-.24-.58-.49-.5-.67-.51h-.57c-.2 0-.52.07-.79.37-.27.3-1.04 1.02-1.04 2.48s1.07 2.88 1.21 3.08c.15.2 2.1 3.2 5.08 4.49.71.31 1.26.49 1.7.63.71.23 1.36.2 1.87.12.57-.09 1.75-.72 2-1.41.25-.69.25-1.29.17-1.41-.07-.12-.27-.2-.57-.35zM12.04 21.5h-.01a9.43 9.43 0 0 1-4.8-1.31l-.35-.2-3.57.93.95-3.48-.22-.36a9.4 9.4 0 0 1-1.44-5.02c0-5.2 4.24-9.43 9.45-9.43a9.38 9.38 0 0 1 6.68 2.77 9.37 9.37 0 0 1 2.76 6.67c0 5.2-4.24 9.43-9.45 9.43zm8.04-17.47A11.3 11.3 0 0 0 12.04.7C5.77.7.67 5.8.67 12.06c0 2 .52 3.96 1.52 5.68L.57 23.5l5.9-1.55a11.33 11.33 0 0 0 5.57 1.42h.01c6.26 0 11.36-5.1 11.36-11.36 0-3.03-1.18-5.89-3.33-8.03z"/></svg>';

  var css = ':host{all:initial}*{box-sizing:border-box;font-family:Inter,system-ui,-apple-system,"Segoe UI",sans-serif}[hidden]{display:none!important}' +
    '.fab{position:fixed;bottom:20px;' + LADO + ':20px;z-index:2147483000;width:60px;height:60px;border-radius:50%;border:0;background:#25d366;color:#fff;box-shadow:0 6px 20px rgba(0,0,0,.25);cursor:pointer;display:grid;place-items:center;transition:transform .15s}' +
    '.fab:hover{transform:scale(1.06)}.fab svg{width:32px;height:32px}.fab:focus-visible{outline:3px solid #f97618;outline-offset:3px}' +
    '.hint{position:fixed;bottom:34px;' + LADO + ':90px;z-index:2147483000;background:#fff;color:#231f20;border-radius:12px;padding:8px 12px;font-size:13.5px;box-shadow:0 4px 16px rgba(0,0,0,.18);cursor:pointer;max-width:220px}' +
    '.panel{position:fixed;bottom:92px;' + LADO + ':20px;z-index:2147483001;width:min(350px,calc(100vw - 24px));background:#fff;color:#231f20;border-radius:16px;box-shadow:0 12px 40px rgba(0,0,0,.28);display:none;flex-direction:column;overflow:hidden}' +
    '.panel.on{display:flex}' +
    '.head{background:#192324;color:#fff;padding:14px;display:flex;gap:10px;align-items:center}' +
    '.av{width:38px;height:38px;border-radius:50%;background:#fff;color:#f97618;display:grid;place-items:center;font-weight:700;font-size:15px;flex:none}' +
    '.ht{flex:1;min-width:0}.ht b{display:block;font-size:15px}.ht small{opacity:.85;font-size:12px}' +
    '.x{background:none;border:0;color:#fff;font-size:22px;cursor:pointer;line-height:1;padding:4px 6px;border-radius:6px}.x:focus-visible{outline:2px solid #fff}' +
    '.body{padding:14px;background:#f3f3fc}' +
    '.form{display:flex;flex-direction:column;gap:10px;background:#fff;border:1px solid #d6d5dd;border-radius:12px;padding:14px}' +
    '.form p{margin:0;font-size:13.5px;color:#5f5d6b}.form label{font-size:12px;color:#5f5d6b;font-weight:600;display:flex;flex-direction:column;gap:4px}' +
    '.form input,.form select{border:1px solid #d6d5dd;border-radius:8px;padding:10px;font-size:14px;color:#231f20;background:#fff;width:100%}' +
    '.btn{border:0;border-radius:10px;padding:12px;font-size:14.5px;font-weight:600;cursor:pointer;display:flex;align-items:center;justify-content:center;gap:8px;background:#25d366;color:#fff}' +
    '.btn svg{width:18px;height:18px}.btn:hover{background:#1ebe5b}' +
    '.err{color:#b3261e;font-size:12.5px;min-height:1em}' +
    '.ok{background:#e1f1e8;color:#1f7a4d;border-radius:12px;padding:12px;font-size:13.5px;line-height:1.5}.ok a{color:#1f7a4d;font-weight:600}' +
    '.link{background:none;border:0;color:#f97618;font-size:13px;cursor:pointer;margin-top:10px;padding:0}' +
    '@media (prefers-color-scheme:dark){.panel{background:#172030;color:#ecebf5}.body{background:#0f1520}.form{background:#1d2738;border-color:#2a3546;color:#ecebf5}' +
    '.form input,.form select{background:#0f1520;border-color:#2a3546;color:#ecebf5}.form p,.form label{color:#a4a6b8}.hint{background:#172030;color:#ecebf5}.link{color:#ffad70}}' +
    '@media (prefers-reduced-motion:reduce){.fab{transition:none}}';

  var host = document.createElement("div");
  host.id = "econotec-widget";
  var root = host.attachShadow ? host.attachShadow({ mode: "open" }) : host;
  root.innerHTML = '<style>' + css + '</style>' +
    '<button class="fab" type="button" aria-label="Escríbenos por WhatsApp">' + WA_ICO + '</button>' +
    '<div class="hint" role="button" tabindex="0" hidden>¿Te ayudamos? Escríbenos 👋</div>' +
    '<div class="panel" role="dialog" aria-label="Escríbenos por WhatsApp">' +
    '<div class="head"><div class="av">E</div><div class="ht"><b>Econotec</b><small>Respondemos por WhatsApp</small></div>' +
    '<button class="x" type="button" aria-label="Cerrar">×</button></div><div class="body"></div></div>';
  document.body.appendChild(host);

  var $ = function (s) { return root.querySelector(s); };
  var fab = $(".fab"), panel = $(".panel"), body = $(".body"), hint = $(".hint");

  function esc(t) { return String(t).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function rend(t, v) { return (t || "").replace(/\{(\w+)\}/g, function (m, k) { return v[k] != null ? v[k] : m; }).replace(/[ \t]+([,!.?])/g, "$1").replace(/[ \t]{2,}/g, " ").trim(); }
  function waLink(texto) { return "https://wa.me/" + cfg.numero + "?text=" + encodeURIComponent(texto); }

  function abrir() { panel.classList.add("on"); hint.hidden = true; pintar(); }
  function cerrar() { panel.classList.remove("on"); fab.focus(); }
  fab.addEventListener("click", function () { panel.classList.contains("on") ? cerrar() : abrir(); });
  hint.addEventListener("click", abrir);
  $(".x").addEventListener("click", cerrar);
  root.addEventListener("keydown", function (e) { if (e.key === "Escape") cerrar(); });

  function pintar() { st.listo ? pintarListo() : pintarForm(); }

  function pintarForm() {
    var opts = cfg.categorias.map(function (c) { return '<option>' + esc(c) + '</option>'; }).join("");
    body.innerHTML = '<form class="form" novalidate><p>Déjanos tus datos y te abrimos WhatsApp con el mensaje listo.</p>' +
      '<label>Nombre<input name="nombre" autocomplete="name" required value="' + esc(st.nombre || "") + '"></label>' +
      '<label>Tu WhatsApp<input name="telefono" type="tel" inputmode="tel" autocomplete="tel" placeholder="09XXXXXXXX" required value="' + esc(st.telefono || "") + '"></label>' +
      (opts ? '<label>¿Qué te interesa?<select name="servicio"><option value="">Elegir (opcional)</option>' + opts + '</select></label>' : '') +
      '<input name="website" tabindex="-1" autocomplete="off" style="position:absolute;left:-9999px" aria-hidden="true">' +
      '<div class="err" role="alert"></div>' +
      '<button class="btn" type="submit">' + WA_ICO + 'Abrir WhatsApp</button></form>';
    var f = body.querySelector("form");
    f.addEventListener("submit", function (e) {
      e.preventDefault();
      var d = { nombre: f.nombre.value.trim(), telefono: f.telefono.value.trim(), servicio: f.servicio ? f.servicio.value : "", website: f.website.value };
      if (!d.nombre || d.telefono.replace(/\D/g, "").length < 7) { f.querySelector(".err").textContent = "Escribe tu nombre y un número de WhatsApp válido."; return; }
      st.nombre = d.nombre; st.telefono = d.telefono;
      // Se abre en el mismo clic (si no, el navegador lo bloquea) y el registro viaja en paralelo
      var texto = rend(cfg.mensaje_boton, { nombre: d.nombre.split(" ")[0], servicio: d.servicio || "sus servicios", empresa: "" });
      window.open(waLink(texto), "_blank", "noopener");
      fetch(CRM + "/api/boton/registrar/", { method: "POST", headers: { "Content-Type": "text/plain" }, body: JSON.stringify(d), keepalive: true }).catch(function () {});
      st.listo = waLink(texto); save(); pintarListo();
    });
    setTimeout(function () { (f.nombre.value ? f.telefono : f.nombre).focus(); }, 50);
  }

  function pintarListo() {
    body.innerHTML = '<div class="ok">¡Listo, ' + esc((st.nombre || "").split(" ")[0]) + '! Te abrimos WhatsApp con el mensaje escrito: solo toca <b>Enviar</b>.<br><br>' +
      '¿No se abrió? <a href="' + esc(st.listo) + '" target="_blank" rel="noopener">Abrir WhatsApp</a></div>' +
      '<button class="link" type="button">Escribir de nuevo</button>';
    body.querySelector(".link").onclick = function () { st.listo = ""; save(); pintar(); };
  }

  fetch(CRM + "/api/boton/config/").then(function (r) { return r.json(); }).then(function (j) {
    cfg = j;
    if (!cfg.numero) { host.remove(); return; }  // sin número configurado no se muestra el botón
    if (!st.visto) { setTimeout(function () { if (!panel.classList.contains("on")) hint.hidden = false; }, 4000); st.visto = 1; save(); }
  }).catch(function () { host.remove(); });
})();
