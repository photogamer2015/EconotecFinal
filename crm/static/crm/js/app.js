/* CRM Econotec — interacciones: menú móvil, gráficos, kanban, recordatorios */
(function () {
  const $ = (s, el) => (el || document).querySelector(s);
  const $$ = (s, el) => Array.from((el || document).querySelectorAll(s));
  // El token va en la página (meta csrf-token): así no se confunde con cookies de otros proyectos Django en 127.0.0.1
  const csrf = () => (document.querySelector('meta[name="csrf-token"]') || {}).content || (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || "";

  // ---------- Menú lateral en móvil ----------
  const mb = $("#menuBtn"), side = $("#side"), scrim = $("#scrim");
  const menu = abrir => { side.classList.toggle("open", abrir); if (scrim) scrim.hidden = !abrir; };
  if (mb) mb.onclick = () => menu(!side.classList.contains("open"));
  if (scrim) scrim.onclick = () => menu(false);

  // ---------- Popovers (tema y campana) ----------
  function popover(btn, pop, alAbrir) {
    if (!btn || !pop) return;
    btn.addEventListener("click", e => {
      e.stopPropagation();
      const abrir = pop.hidden;
      $$(".pop").forEach(p => { p.hidden = true; });
      $$("[aria-haspopup]").forEach(b => b.setAttribute("aria-expanded", "false"));
      pop.hidden = !abrir; btn.setAttribute("aria-expanded", String(abrir));
      if (abrir && alAbrir) alAbrir();
    });
    pop.addEventListener("click", e => e.stopPropagation());
  }
  document.addEventListener("click", () => { $$(".pop").forEach(p => { p.hidden = true; }); $$("[aria-haspopup]").forEach(b => b.setAttribute("aria-expanded", "false")); });
  document.addEventListener("keydown", e => { if (e.key === "Escape") { $$(".pop").forEach(p => { p.hidden = true; }); menu && side && menu(false); } });

  // ---------- Tema claro / oscuro / sistema ----------
  const html = document.documentElement;
  const mq = window.matchMedia ? matchMedia("(prefers-color-scheme: dark)") : null;
  function aplicarTema(pref) {
    // Misma preferencia que el resto de Econotec («theme»: light / dark; sin valor = según el sistema)
    try { if (pref === "auto") localStorage.removeItem("theme"); else localStorage.setItem("theme", pref); } catch (e) {}
    const oscuro = pref === "dark" || (pref === "auto" && mq && mq.matches);
    html.setAttribute("data-theme", oscuro ? "dark" : "light");
    html.setAttribute("data-tema-pref", pref);
    $$("#temaPop [data-tema]").forEach(b => b.setAttribute("aria-checked", String(b.dataset.tema === pref)));
  }
  popover($("#temaBtn"), $("#temaPop"));
  $$("#temaPop [data-tema]").forEach(b => b.addEventListener("click", () => { aplicarTema(b.dataset.tema); $("#temaPop").hidden = true; }));
  $$("#temaPop [data-tema]").forEach(b => b.setAttribute("aria-checked", String(b.dataset.tema === (html.getAttribute("data-tema-pref") || "auto"))));
  if (mq && mq.addEventListener) mq.addEventListener("change", () => { if ((html.getAttribute("data-tema-pref") || "auto") === "auto") aplicarTema("auto"); });

  // ---------- Notificaciones: campana, lista y avisos emergentes ----------
  const bell = $("#bellBtn");
  const esc = t => String(t).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  function toast(texto, url, titulo) {
    const box = $("#toasts"); if (!box) return;
    const t = document.createElement(url ? "a" : "div");
    t.className = "toast"; if (url) t.href = url;
    t.innerHTML = `<b>${esc(titulo || "Nueva notificación")}</b><span>${esc(texto)}</span>`;
    box.appendChild(t);
    setTimeout(() => { t.classList.add("fuera"); setTimeout(() => t.remove(), 400); }, 6000);
  }
  if (bell) {
    let ultimoVisto = Number(sessionStorage.getItem("crm-econotec-notif-ult") || 0), primera = true;
    const pintar = j => {
      const cnt = $("#bellCnt");
      cnt.textContent = j.sin_leer > 99 ? "99+" : j.sin_leer; cnt.hidden = !j.sin_leer;
      $$("[data-notif-cnt]").forEach(x => { x.textContent = j.sin_leer; x.hidden = !j.sin_leer; });
      $("#bellList").innerHTML = j.ultimas.length ? j.ultimas.map(n =>
        `<a class="notif mini ${n.leida ? "" : "nueva"}" href="${n.url}"><span class="n-body"><span class="n-txt">${esc(n.texto)}</span><span class="n-meta">${esc(n.tipo_nombre)} · ${n.fecha}</span></span>${n.leida ? "" : '<span class="n-dot"></span>'}</a>`
      ).join("") : '<p class="muted" style="padding:14px;margin:0">Sin notificaciones.</p>';
      const nuevas = j.ultimas.filter(n => !n.leida && n.id > ultimoVisto);
      if (!primera) nuevas.slice(0, 3).reverse().forEach(n => toast(n.texto, n.url));
      if (j.ultimas.length) { ultimoVisto = Math.max(ultimoVisto, ...j.ultimas.map(n => n.id)); sessionStorage.setItem("crm-econotec-notif-ult", ultimoVisto); }
      primera = false;
    };
    const consultar = () => fetch(bell.dataset.estado, { headers: { "x-requested-with": "fetch" } }).then(r => r.ok ? r.json() : null).then(j => j && pintar(j)).catch(() => {});
    popover(bell, $("#bellPop"), consultar);
    $("#bellLeer").addEventListener("click", () => fetch(bell.dataset.leidas, { method: "POST", headers: { "X-CSRFToken": csrf(), "x-requested-with": "fetch" } }).then(consultar));
    consultar();
    setInterval(() => { if (!document.hidden) consultar(); }, 20000);
  }

  // ---------- WhatsApp sin API: plantillas, sugerencia y envío con wa.me ----------
  const plantillas = (() => { const el = $("#plantillas-data"); try { return el ? JSON.parse(el.textContent) : []; } catch (e) { return []; } })();
  const waLink = (numero, texto) => `https://wa.me/${numero || ""}?text=${encodeURIComponent(texto)}`;
  const sel = $("#plantillas");
  if (sel) sel.addEventListener("change", () => {
    const p = plantillas.find(x => String(x.id) === sel.value);
    const ta = sel.form.querySelector("textarea[name=texto]");
    if (ta) { ta.value = p ? p.texto : ""; ta.focus(); }
    const rid = sel.form.querySelector("#respId"); if (rid) rid.value = p ? p.id : "";
  });
  // Con WhatsApp vinculado por QR el mensaje sale directo desde el CRM (no se abre wa.me)
  const waQR = ($('meta[name="wa-qr"]') || {}).content === "1";
  async function enviarQR(url, texto, respuesta) {
    try {
      const r = await fetch(url, {
        method: "POST", headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
        body: JSON.stringify({ texto, respuesta, via: "qr" }),
      });
      const j = await r.json();
      toast(j.ok ? "Mensaje enviado por WhatsApp." : "No se envió: " + (j.estado || "WhatsApp no conectado"), null, "WhatsApp");
      return j.ok;
    } catch (e) { toast("No se envió: revisa la conexión de WhatsApp.", null, "WhatsApp"); return false; }
  }
  const wf = $("#waForm");
  if (wf) wf.addEventListener("submit", async e => {
    e.preventDefault();
    const t = wf.texto.value.trim();
    if (!t) { wf.texto.focus(); return; }
    if (waQR) {
      if (await enviarQR(wf.dataset.log, t, wf.querySelector("#respId").value)) setTimeout(() => location.reload(), 900);
      return;
    }
    window.open(waLink(wf.dataset.wa, t), "_blank", "noopener");
    fetch(wf.dataset.log, {
      method: "POST", keepalive: true,
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
      body: JSON.stringify({ texto: t, respuesta: wf.querySelector("#respId").value }),
    }).then(r => { if (r.ok) setTimeout(() => location.reload(), 600); });
  });

  // ---------- Gráficos del dashboard ----------
  const gd = $("#graficos-data");
  if (gd) {
    const g = JSON.parse(gd.textContent);
    const lc = $("#lineChart");
    if (lc) lc.innerHTML = lineChart(g.serie.map(x => x.mes), g.serie.map(x => x.leads), g.serie.map(x => x.ganados));
  }
  function lineChart(lbl, a, b) {
    const W = 640, H = 220, p = { l: 34, r: 12, t: 12, b: 26 };
    const top = Math.max(5, ...a, ...b);
    const step = top <= 10 ? 2 : top <= 25 ? 5 : 10;
    const mx = Math.ceil(top / step) * step;
    const x = i => p.l + i * (W - p.l - p.r) / Math.max(1, lbl.length - 1);
    const y = v => H - p.b - v / mx * (H - p.t - p.b);
    let gr = "";
    for (let v = 0; v <= mx; v += step) gr += `<line class="grid-l" x1="${p.l}" x2="${W - p.r}" y1="${y(v)}" y2="${y(v)}"/><text x="${p.l - 6}" y="${y(v) + 4}" text-anchor="end">${v}</text>`;
    const pa = a.map((v, i) => `${x(i)},${y(v)}`).join(" "), pb = b.map((v, i) => `${x(i)},${y(v)}`).join(" ");
    return `<svg class="chart" viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Leads y cierres por mes">${gr}
      <polygon class="area" points="${x(0)},${y(0)} ${pa} ${x(a.length - 1)},${y(0)}"/><polyline class="ln" points="${pa}"/><polyline class="ln2" points="${pb}"/>
      <circle class="pt" cx="${x(a.length - 1)}" cy="${y(a[a.length - 1])}" r="4.5"/>
      ${lbl.map((l, i) => `<text x="${x(i)}" y="${H - 6}" text-anchor="middle">${l}</text>`).join("")}</svg>`;
  }

  // ---------- Kanban: arrastrar para cambiar etapa ----------
  const board = $("#board");
  if (board) {
    let arrastrado = null;
    $$(".deal", board).forEach(d => {
      d.addEventListener("dragstart", e => { arrastrado = d; e.dataTransfer.setData("text/plain", d.dataset.id); });
    });
    $$(".col", board).forEach(col => {
      col.addEventListener("dragover", e => { e.preventDefault(); col.classList.add("drop"); });
      col.addEventListener("dragleave", () => col.classList.remove("drop"));
      col.addEventListener("drop", async e => {
        e.preventDefault(); col.classList.remove("drop");
        const id = e.dataTransfer.getData("text/plain");
        if (!id || !arrastrado || arrastrado.closest(".col") === col) return;
        let motivo = "";
        if (col.dataset.etapa === "perdido") {
          motivo = window.prompt ? (window.prompt("Motivo de pérdida (opcional):") || "") : "";
        }
        const r = await fetch(board.dataset.mover.replace("0", id), {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
          body: JSON.stringify({ etapa: col.dataset.etapa, motivo }),
        });
        if (r.ok) location.reload(); else alert("No se pudo mover la oportunidad.");
      });
    });
  }

  // ---------- Recordatorios: marcar hecho sin recargar ----------
  $$(".rem button[data-url]").forEach(b => {
    b.addEventListener("click", async () => {
      const r = await fetch(b.dataset.url, { method: "POST", headers: { "X-CSRFToken": csrf(), "x-requested-with": "fetch" } });
      if (r.ok) { const j = await r.json(); b.closest(".rem").classList.toggle("done", j.completado); }
    });
  });

  // *negrita* y _cursiva_ como en WhatsApp
  $$(".msg, .sug-t").forEach(m => {
    const t = m.firstChild;
    if (t && t.nodeType === 3) {
      const span = document.createElement("span");
      span.innerHTML = t.textContent.replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]))
        .replace(/\*([^*\n]+)\*/g, "<b>$1</b>").replace(/(^|\s)_([^_\n]+)_/g, "$1<i>$2</i>");
      m.replaceChild(span, t);
    }
  });


  // ---------- Chats de WhatsApp: sin QR conectado, la respuesta se abre en WhatsApp (wa.me) ----------
  const rf = $("#replyForm");
  if (rf) rf.addEventListener("submit", () => {
    const t = rf.texto.value.trim();
    if (!t || rf.dataset.directo === "1") return;
    rf.via.value = "wa";
    window.open(waLink(rf.dataset.wa, t), "_blank", "noopener");
  });

  // ---------- Chats de WhatsApp: se actualiza sola cuando llega un mensaje ----------
  const inbox = $("#inbox");
  if (inbox) {
    const base = Number(inbox.dataset.ultimo || 0);
    const ms = $("#msgs"); if (ms) ms.scrollTop = ms.scrollHeight;
    setInterval(async () => {
      const ta = $(".reply textarea");
      if (ta && ta.value.trim()) return; // no recargar si el asesor está escribiendo
      try {
        const r = await fetch(inbox.dataset.estado);
        const j = await r.json();
        if (j.ultimo > base) location.reload();
      } catch (e) {}
    }, 3000);
  }

  // ---------- Lista de clientes: abrir WhatsApp con el mensaje predeterminado ----------
  $$(".wa-rapido").forEach(b => b.addEventListener("click", () => {
    if (waQR) { enviarQR(b.dataset.log, b.dataset.texto, b.dataset.resp); return; }
    window.open(waLink(b.dataset.wa, b.dataset.texto), "_blank", "noopener");
    fetch(b.dataset.log, {
      method: "POST", keepalive: true,
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
      body: JSON.stringify({ texto: b.dataset.texto, respuesta: b.dataset.resp }),
    }).then(r => { if (r.ok) toast("Chat abierto y registrado en el historial.", null, "WhatsApp"); });
  }));

  // ---------- Ficha: barra de etapas del pipeline ----------
  const stp = $("#stepper");
  if (stp) $$(".step", stp).forEach(b => b.addEventListener("click", async () => {
    if (b.classList.contains("actual")) return;
    let motivo = "";
    if (b.dataset.etapa === "perdido") {
      motivo = window.prompt("¿Por qué se perdió? (precio, otro proveedor, no respondió…)");
      if (motivo === null) return;
    }
    const r = await fetch(stp.dataset.mover, {
      method: "POST", headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
      body: JSON.stringify({ etapa: b.dataset.etapa, motivo }),
    });
    if (r.ok) location.reload(); else alert("No se pudo cambiar la etapa.");
  }));

  // ---------- Registrar cliente ----------
  const cf = $("#clienteForm");
  if (cf) {
    const tel = cf.querySelector("[name=telefono]");
    const canal = () => (cf.querySelector("[name=canal]:checked") || {}).value;
    const etapa = () => (cf.querySelector("[name=etapa]:checked") || {}).value;
    const actualizar = () => {
      const pide = ["whatsapp", "llamada"].includes(canal());
      $("#telReq").hidden = !pide; $("#telAyuda").hidden = !pide; tel.required = pide;
      $("#campo-motivo").hidden = etapa() !== "perdido";
      $("#guardarWa").hidden = !(tel.value.replace(/\D/g, "").length >= 7 || pide);
    };
    cf.addEventListener("change", actualizar);
    tel.addEventListener("input", actualizar);
    actualizar();
    const rend = (t, v) => (t || "").replace(/\{(\w+)\}/g, (m, k) => v[k] != null ? v[k] : m).replace(/[ \t]+([,!.?])/g, "$1").replace(/[ \t]{2,}/g, " ").trim();
    $("#guardarWa").addEventListener("click", e => {
      cf.wa_texto.value = "";
      let numero = tel.value.replace(/\D/g, "");
      if (numero.startsWith("0") && numero.length === 10) numero = "593" + numero.slice(1);
      if (!cf.nombre.value.trim() || numero.length < 7) {
        e.preventDefault();
        (numero.length < 7 ? tel : cf.nombre).focus();
        toast(numero.length < 7 ? "Escribe el número de WhatsApp para abrir el chat." : "Escribe el nombre del cliente.", null, "Falta un dato");
        return;
      }
      const resp = cf.responsable && cf.responsable.value ? cf.responsable.options[cf.responsable.selectedIndex].text : cf.dataset.asesor;
      const servicio = cf.servicio.value && cf.servicio.value !== "Por definir" ? cf.servicio.value : "nuestros servicios";
      const texto = rend(cf.dataset.plantilla, { nombre: cf.nombre.value.trim().split(" ")[0], empresa: cf.empresa.value.trim() || "su empresa",
        servicio, equipo: (cf.equipo && cf.equipo.value.trim()) || "su equipo", asesor: resp, horario: cf.dataset.horario });
      if (!texto) return;  // sin plantilla: solo guarda
      cf.wa_texto.value = texto;
      window.open(waLink(numero, texto), "_blank", "noopener");
    });
  }

  // ---------- Copiar al portapapeles ----------
  $$("[data-copy]").forEach(b => b.addEventListener("click", () => {
    const t = $(b.dataset.copy).innerText;
    navigator.clipboard && navigator.clipboard.writeText(t).then(() => { b.textContent = "Copiado"; setTimeout(() => b.textContent = "Copiar", 1500); });
  }));
})();
