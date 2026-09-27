/*
 * EconoBot — interfaz del chat.
 * El texto del bot siempre se pinta como texto plano (textContent) y los
 * enlaces solo pueden ser rutas internas del sistema o de WhatsApp.
 */
(function () {
    'use strict';

    var raiz = document.getElementById('econobot');
    if (!raiz) return;

    var endpoint = raiz.getAttribute('data-endpoint');
    var endpointEstado = raiz.getAttribute('data-estado');
    var usuario = raiz.getAttribute('data-usuario') || '0';
    var nombre = (raiz.getAttribute('data-nombre') || '').split(' ')[0];

    var lanzador = document.getElementById('econobot-launcher');
    var puntoLanzador = document.getElementById('econobot-launcher-dot');
    var panel = document.getElementById('econobot-panel');
    var zonaMensajes = document.getElementById('econobot-mensajes');
    var zonaOpciones = document.getElementById('econobot-opciones');
    var formulario = document.getElementById('econobot-form');
    var entrada = document.getElementById('econobot-texto');
    var botonEnviar = document.getElementById('econobot-enviar');
    var botonMic = document.getElementById('econobot-mic');
    var botonVoz = document.getElementById('econobot-voz');
    var botonNuevo = document.getElementById('econobot-nuevo');
    var botonCerrar = document.getElementById('econobot-cerrar');
    var estadoTexto = document.getElementById('econobot-status');
    var banner = document.getElementById('econobot-banner');
    var bannerFlujo = document.getElementById('econobot-banner-flujo');
    var zonaFirma = document.getElementById('econobot-firma');
    var lienzo = document.getElementById('econobot-firma-lienzo');
    var botonFirmaLimpiar = document.getElementById('econobot-firma-limpiar');
    var botonFirmaNo = document.getElementById('econobot-firma-no');
    var botonFirmaGuardar = document.getElementById('econobot-firma-guardar');

    var CLAVE_HISTORIAL = 'econobot:v1:historial:' + usuario;
    var CLAVE_VOZ = 'econobot:v1:voz:' + usuario;
    var CLAVE_ABIERTO = 'econobot:v1:abierto:' + usuario;
    var CLAVE_PENDIENTE = 'econobot:v1:pendiente:' + usuario;
    var MAX_HISTORIAL = 80;
    var MOVIL = window.matchMedia('(max-width: 600px)');

    var historial = leerHistorial();
    var enviando = false;
    var ultimaEntradaPorVoz = false;
    var vozActiva = leer(CLAVE_VOZ) !== 'no';
    var abierto = false;
    var elementoPrevio = null;
    var indicadorEscribiendo = null;

    // ── Almacenamiento local (puede no estar disponible) ─────────────
    function leer(clave) {
        try { return window.localStorage.getItem(clave); } catch (e) { return null; }
    }
    function guardar(clave, valor) {
        try { window.localStorage.setItem(clave, valor); } catch (e) { /* sin almacenamiento */ }
    }
    function borrar(clave) {
        try { window.localStorage.removeItem(clave); } catch (e) { /* sin almacenamiento */ }
    }
    function leerHistorial() {
        try {
            var datos = JSON.parse(leer(CLAVE_HISTORIAL) || '[]');
            return Array.isArray(datos) ? datos.slice(-MAX_HISTORIAL) : [];
        } catch (e) {
            return [];
        }
    }
    function guardarHistorial() {
        historial = historial.slice(-MAX_HISTORIAL);
        guardar(CLAVE_HISTORIAL, JSON.stringify(historial));
    }

    // ── CSRF ─────────────────────────────────────────────────────────
    function tokenCsrf() {
        var coincidencia = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        return coincidencia ? decodeURIComponent(coincidencia[1]) : (raiz.getAttribute('data-csrf') || '');
    }

    function nuevoId() {
        if (window.crypto && window.crypto.randomUUID) return window.crypto.randomUUID();
        return 'eb-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10);
    }

    function horaActual() {
        var ahora = new Date();
        return ('0' + ahora.getHours()).slice(-2) + ':' + ('0' + ahora.getMinutes()).slice(-2);
    }

    // ── Enlaces seguros ──────────────────────────────────────────────
    var HOSTS_WHATSAPP = ['wa.me', 'api.whatsapp.com', 'web.whatsapp.com'];

    function urlSegura(url) {
        if (typeof url !== 'string' || !url) return null;
        if (url.charAt(0) === '/' && url.charAt(1) !== '/' && url.charAt(1) !== '\\') return url;
        try {
            var destino = new URL(url);
            if (destino.protocol === 'https:' && HOSTS_WHATSAPP.indexOf(destino.hostname) !== -1) return destino.href;
        } catch (e) { /* URL inválida */ }
        return null;
    }

    function crearEnlace(datos) {
        var url = urlSegura(datos && datos.url);
        if (!url) return null;
        var tipo = datos.kind === 'nueva' || datos.kind === 'wa' ? datos.kind : 'nav';
        var enlace = document.createElement('a');
        enlace.href = url;
        enlace.className = 'econobot-enlace econobot-enlace-' + tipo;
        enlace.textContent = datos.label || 'Abrir';
        if (tipo === 'nueva' || tipo === 'wa') {
            enlace.target = '_blank';
            enlace.rel = 'noopener';
        } else {
            enlace.addEventListener('click', function () {
                // Al cambiar de página el chat se cierra para dejar ver el destino.
                guardar(CLAVE_ABIERTO, 'no');
            });
        }
        return enlace;
    }

    // ── Pintar la conversación ───────────────────────────────────────
    function pintarMensaje(mensaje) {
        var fila = document.createElement('div');
        fila.className = 'econobot-msg econobot-msg-' + (mensaje.rol === 'yo' ? 'yo' : 'bot') + (mensaje.error ? ' is-error' : '');
        var burbuja = document.createElement('div');
        burbuja.className = 'econobot-burbuja';
        burbuja.textContent = mensaje.texto || '';
        fila.appendChild(burbuja);
        if (mensaje.enlaces && mensaje.enlaces.length) {
            var contenedor = document.createElement('div');
            contenedor.className = 'econobot-enlaces';
            mensaje.enlaces.forEach(function (datos) {
                var enlace = crearEnlace(datos);
                if (enlace) contenedor.appendChild(enlace);
            });
            if (contenedor.children.length) fila.appendChild(contenedor);
        }
        if (mensaje.hora) {
            var hora = document.createElement('span');
            hora.className = 'econobot-hora';
            hora.textContent = mensaje.hora;
            fila.appendChild(hora);
        }
        zonaMensajes.appendChild(fila);
        return fila;
    }

    function bajar() {
        zonaMensajes.scrollTop = zonaMensajes.scrollHeight;
    }

    function agregar(mensaje) {
        mensaje.hora = mensaje.hora || horaActual();
        historial.push(mensaje);
        guardarHistorial();
        pintarMensaje(mensaje);
        bajar();
    }

    function pintarPresentacion() {
        var plantilla = document.getElementById('econobot-hero-plantilla');
        if (plantilla && plantilla.content) zonaMensajes.appendChild(plantilla.content.cloneNode(true));
    }

    function pintarHistorial() {
        zonaMensajes.textContent = '';
        pintarPresentacion();
        historial.forEach(pintarMensaje);
        var ultimo = historial.length ? historial[historial.length - 1] : null;
        var delBot = ultimo && ultimo.rol === 'bot';
        pintarOpciones(delBot ? ultimo.opciones : []);
        mostrarFirma(!!(delBot && ultimo.widget === 'firma'));
        bajar();
    }

    function pintarOpciones(opciones) {
        zonaOpciones.textContent = '';
        (opciones || []).slice(0, 14).forEach(function (opcion) {
            if (!opcion || !opcion.label) return;
            var chip = document.createElement('button');
            chip.type = 'button';
            chip.className = 'econobot-chip';
            chip.textContent = opcion.label;
            chip.addEventListener('click', function () {
                enviar(String(opcion.value || opcion.label), { etiqueta: opcion.label });
            });
            zonaOpciones.appendChild(chip);
        });
        zonaOpciones.hidden = !zonaOpciones.children.length;
    }

    function mostrarEscribiendo(activo) {
        raiz.classList.toggle('is-busy', activo);
        estadoTexto.textContent = activo ? 'Escribiendo…' : 'Asistente de Econotec';
        if (activo && !indicadorEscribiendo) {
            indicadorEscribiendo = document.createElement('div');
            indicadorEscribiendo.className = 'econobot-msg econobot-escribiendo';
            indicadorEscribiendo.setAttribute('aria-hidden', 'true');
            var burbuja = document.createElement('div');
            burbuja.className = 'econobot-burbuja';
            for (var i = 0; i < 3; i += 1) burbuja.appendChild(document.createElement('span'));
            indicadorEscribiendo.appendChild(burbuja);
            zonaMensajes.appendChild(indicadorEscribiendo);
            bajar();
        } else if (!activo && indicadorEscribiendo) {
            indicadorEscribiendo.remove();
            indicadorEscribiendo = null;
        }
    }

    function actualizarBanner(pendiente, flujo) {
        banner.hidden = !pendiente;
        if (pendiente) bannerFlujo.textContent = flujo || 'Registro';
        if (puntoLanzador) puntoLanzador.hidden = !pendiente;
        guardar(CLAVE_PENDIENTE, pendiente ? (flujo || 'Registro') : '');
    }

    function bienvenida() {
        agregar({
            rol: 'bot',
            texto: '¡Hola' + (nombre ? ', ' + nombre : '') + '! 👋 Soy EconoBot, tu asistente de Econotec.\n' +
                'Puedo registrar equipos, finalizarlos, confirmar salidas y mostrarte clientes, equipos y alertas. ' +
                'Escribe lo que necesitas o un código como G1031.',
            opciones: [
                { label: '📥 Registrar equipo', value: 'registrar equipo' },
                { label: '✅ Finalizar equipo', value: 'finalizar equipo' },
                { label: '📦 Finalizados en oficina', value: 'equipos finalizados' },
                { label: '🔧 Equipos en taller', value: 'equipos en taller' },
                { label: '👤 Buscar cliente', value: 'buscar cliente' },
                { label: '❓ ¿Qué más puedes hacer?', value: 'ayuda' }
            ]
        });
        pintarOpciones(historial[historial.length - 1].opciones);
    }

    // ── Comunicación con el servidor ─────────────────────────────────
    function bloquear(valor) {
        enviando = valor;
        botonEnviar.disabled = valor;
        Array.prototype.forEach.call(zonaOpciones.querySelectorAll('button'), function (b) { b.disabled = valor; });
        if (botonFirmaGuardar) botonFirmaGuardar.disabled = valor || !firmaConTrazo;
    }

    function recibir(datos) {
        var texto = datos.reply || '';
        agregar({
            rol: 'bot', texto: texto, enlaces: datos.links || [], opciones: datos.options || [],
            widget: datos.widget === 'firma' ? 'firma' : ''
        });
        pintarOpciones(datos.options || []);
        actualizarBanner(!!datos.pending, datos.flow);
        mostrarFirma(datos.widget === 'firma');
        if (vozActiva && ultimaEntradaPorVoz) hablar(texto);
    }

    function mostrarError(texto) {
        agregar({ rol: 'bot', texto: texto, error: true });
        pintarOpciones([]);
    }

    function pedir(cuerpo, reintento) {
        bloquear(true);
        mostrarEscribiendo(true);
        fetch(endpoint, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': tokenCsrf(),
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: JSON.stringify(cuerpo)
        }).then(function (respuesta) {
            return respuesta.json().catch(function () { return {}; }).then(function (datos) {
                return { status: respuesta.status, datos: datos };
            });
        }).then(function (resultado) {
            mostrarEscribiendo(false);
            bloquear(false);
            if (resultado.status === 401) {
                mostrarError(resultado.datos.error || 'Tu sesión terminó. Vuelve a iniciar sesión.');
                return;
            }
            if (resultado.status === 403 && !resultado.datos.error) {
                mostrarError('La página caducó. Recárgala e inténtalo de nuevo.');
                return;
            }
            if (resultado.datos.error || resultado.status >= 400) {
                mostrarError(resultado.datos.error || 'No pude procesar el mensaje. Inténtalo de nuevo.');
                return;
            }
            recibir(resultado.datos);
        }).catch(function () {
            if (!reintento) {
                // Mismo request_id: el servidor no repite una acción ya hecha.
                window.setTimeout(function () { pedir(cuerpo, true); }, 900);
                return;
            }
            mostrarEscribiendo(false);
            bloquear(false);
            mostrarError('No pude conectar con el servidor. Revisa tu conexión e inténtalo de nuevo.');
        });
    }

    function enviar(texto, opciones) {
        opciones = opciones || {};
        texto = (texto || '').trim();
        if (enviando) return;
        if (!texto && !opciones.firma) return;
        if (texto.length > 2000) texto = texto.slice(0, 2000);
        agregar({ rol: 'yo', texto: opciones.firma ? '✍️ Firma del cliente enviada' : (opciones.etiqueta || texto) });
        pintarOpciones([]);
        ultimaEntradaPorVoz = !!opciones.porVoz;
        detenerVoz();
        var cuerpo = { message: opciones.firma ? '' : texto, request_id: nuevoId() };
        if (opciones.firma) cuerpo.signature = opciones.firma;
        pedir(cuerpo, false);
    }

    function sincronizarEstado(mostrarPendiente) {
        if (!endpointEstado || !window.fetch) return;
        fetch(endpointEstado, { credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (datos) {
                if (!datos) return;
                actualizarBanner(!!datos.pending, datos.flow);
                if (datos.pending && mostrarPendiente && datos.resume) recibir(datos.resume);
            })
            .catch(function () { /* sin conexión: se intentará al enviar */ });
    }

    // ── Abrir y cerrar ───────────────────────────────────────────────
    function cerrarMenuMovil() {
        var cabecera = document.querySelector('header.top');
        var boton = document.getElementById('mobile-nav-toggle');
        if (cabecera) cabecera.classList.remove('nav-open');
        if (boton) boton.setAttribute('aria-expanded', 'false');
    }

    function abrir(opciones) {
        opciones = opciones || {};
        if (abierto) {
            if (!opciones.sinFoco) entrada.focus();
            return;
        }
        abierto = true;
        elementoPrevio = document.activeElement;
        cerrarMenuMovil();
        panel.hidden = false;
        raiz.classList.add('is-open');
        lanzador.setAttribute('aria-expanded', 'true');
        if (MOVIL.matches) document.documentElement.classList.add('econobot-bloqueo');
        guardar(CLAVE_ABIERTO, 'si');
        var vacio = !historial.length;
        pintarHistorial();
        if (vacio) bienvenida();
        // Sincroniza el aviso de registro en curso (otra pestaña o recarga).
        sincronizarEstado(vacio);
        ajustarTextarea();
        if (!opciones.sinFoco && !MOVIL.matches) window.setTimeout(function () { entrada.focus(); }, 60);
    }

    function cerrar() {
        if (!abierto) return;
        abierto = false;
        panel.hidden = true;
        raiz.classList.remove('is-open');
        lanzador.setAttribute('aria-expanded', 'false');
        document.documentElement.classList.remove('econobot-bloqueo');
        guardar(CLAVE_ABIERTO, 'no');
        detenerDictado();
        detenerVoz();
        if (elementoPrevio && elementoPrevio.focus && document.contains(elementoPrevio)) {
            try { elementoPrevio.focus({ preventScroll: true }); } catch (e) { elementoPrevio.focus(); }
        } else {
            lanzador.focus();
        }
    }

    lanzador.addEventListener('click', function () { abrir(); });
    botonCerrar.addEventListener('click', cerrar);

    document.addEventListener('click', function (evento) {
        var disparador = evento.target.closest('[data-econobot-open]');
        if (!disparador) return;
        evento.preventDefault();
        abrir();
        var mensaje = disparador.getAttribute('data-econobot-mensaje');
        if (mensaje) enviar(mensaje);
    });

    panel.addEventListener('keydown', function (evento) {
        if (evento.key === 'Escape') {
            evento.stopPropagation();
            cerrar();
        }
    });

    banner.addEventListener('click', function (evento) {
        var boton = evento.target.closest('[data-econobot-enviar]');
        if (!boton) return;
        enviar(boton.getAttribute('data-econobot-enviar'), { etiqueta: boton.getAttribute('data-econobot-etiqueta') });
    });

    botonNuevo.addEventListener('click', function () {
        historial = [];
        borrar(CLAVE_HISTORIAL);
        zonaMensajes.textContent = '';
        pintarPresentacion();
        mostrarFirma(false);
        bienvenida();
        sincronizarEstado(true);
        entrada.focus();
    });

    // ── Escribir ─────────────────────────────────────────────────────
    function ajustarTextarea() {
        entrada.style.height = 'auto';
        entrada.style.height = Math.min(entrada.scrollHeight + 2, 132) + 'px';
        entrada.style.overflowY = entrada.scrollHeight + 2 > 132 ? 'auto' : 'hidden';
    }

    entrada.addEventListener('input', ajustarTextarea);
    entrada.addEventListener('keydown', function (evento) {
        if (evento.key === 'Enter' && !evento.shiftKey && !evento.isComposing) {
            evento.preventDefault();
            formulario.requestSubmit ? formulario.requestSubmit() : formulario.dispatchEvent(new Event('submit', { cancelable: true }));
        }
    });

    formulario.addEventListener('submit', function (evento) {
        evento.preventDefault();
        var texto = entrada.value;
        if (!texto.trim() || enviando) return;
        entrada.value = '';
        ajustarTextarea();
        enviar(texto, { porVoz: dictadoUsado });
        dictadoUsado = false;
    });

    // ── Firma del cliente ────────────────────────────────────────────
    var contexto = lienzo.getContext('2d');
    var dibujando = false;
    var firmaConTrazo = false;
    var escala = 1;

    function prepararLienzo() {
        var caja = lienzo.getBoundingClientRect();
        escala = window.devicePixelRatio || 1;
        lienzo.width = Math.max(1, Math.floor(caja.width * escala));
        lienzo.height = Math.max(1, Math.floor(caja.height * escala));
        contexto.setTransform(escala, 0, 0, escala, 0, 0);
        contexto.fillStyle = '#ffffff';
        contexto.fillRect(0, 0, caja.width, caja.height);
        contexto.strokeStyle = '#111827';
        contexto.lineWidth = 2.4;
        contexto.lineCap = 'round';
        contexto.lineJoin = 'round';
        marcarTrazo(false);
    }

    function marcarTrazo(valor) {
        firmaConTrazo = !!valor;
        botonFirmaGuardar.disabled = !firmaConTrazo || enviando;
    }

    function punto(evento) {
        var caja = lienzo.getBoundingClientRect();
        return { x: evento.clientX - caja.left, y: evento.clientY - caja.top };
    }

    lienzo.addEventListener('pointerdown', function (evento) {
        evento.preventDefault();
        dibujando = true;
        try { lienzo.setPointerCapture(evento.pointerId); } catch (e) { /* no soportado */ }
        var p = punto(evento);
        contexto.beginPath();
        contexto.moveTo(p.x, p.y);
        contexto.lineTo(p.x + 0.01, p.y + 0.01);
        contexto.stroke();
        marcarTrazo(true);
    });
    lienzo.addEventListener('pointermove', function (evento) {
        if (!dibujando) return;
        evento.preventDefault();
        var p = punto(evento);
        contexto.lineTo(p.x, p.y);
        contexto.stroke();
    });
    ['pointerup', 'pointercancel', 'pointerleave'].forEach(function (tipo) {
        lienzo.addEventListener(tipo, function () { dibujando = false; });
    });

    function firmaRecortada() {
        var ancho = lienzo.width;
        var alto = lienzo.height;
        var datos = contexto.getImageData(0, 0, ancho, alto).data;
        var minX = ancho, minY = alto, maxX = 0, maxY = 0, encontrado = false;
        for (var y = 0; y < alto; y += 1) {
            for (var x = 0; x < ancho; x += 1) {
                var i = (y * ancho + x) * 4;
                if (datos[i] < 245 || datos[i + 1] < 245 || datos[i + 2] < 245) {
                    encontrado = true;
                    if (x < minX) minX = x;
                    if (y < minY) minY = y;
                    if (x > maxX) maxX = x;
                    if (y > maxY) maxY = y;
                }
            }
        }
        if (!encontrado) return '';
        var margen = Math.max(10, Math.round(12 * escala));
        minX = Math.max(0, minX - margen);
        minY = Math.max(0, minY - margen);
        maxX = Math.min(ancho - 1, maxX + margen);
        maxY = Math.min(alto - 1, maxY + margen);
        var anchoRecorte = maxX - minX + 1;
        var altoRecorte = maxY - minY + 1;
        var factor = Math.min(1, 900 / anchoRecorte);
        var recorte = document.createElement('canvas');
        recorte.width = Math.max(1, Math.round(anchoRecorte * factor));
        recorte.height = Math.max(1, Math.round(altoRecorte * factor));
        var ctx = recorte.getContext('2d');
        ctx.fillStyle = '#ffffff';
        ctx.fillRect(0, 0, recorte.width, recorte.height);
        ctx.drawImage(lienzo, minX, minY, anchoRecorte, altoRecorte, 0, 0, recorte.width, recorte.height);
        return recorte.toDataURL('image/png');
    }

    function mostrarFirma(visible) {
        var estabaOculta = zonaFirma.hidden;
        zonaFirma.hidden = !visible;
        if (visible && estabaOculta) window.requestAnimationFrame(function () { prepararLienzo(); bajar(); });
    }

    botonFirmaLimpiar.addEventListener('click', prepararLienzo);
    botonFirmaNo.addEventListener('click', function () {
        mostrarFirma(false);
        enviar('no firma', { etiqueta: 'No firma' });
    });
    botonFirmaGuardar.addEventListener('click', function () {
        if (!firmaConTrazo || enviando) return;
        var firma = firmaRecortada();
        if (!firma) return;
        if (firma.length > 700000) {
            mostrarError('La firma quedó muy grande. Límpiala y firma un poco más pequeño.');
            return;
        }
        mostrarFirma(false);
        enviar('', { firma: firma });
    });
    window.addEventListener('resize', function () {
        if (!zonaFirma.hidden && !firmaConTrazo) prepararLienzo();
    });

    // ── Voz: dictado y lectura en voz alta ───────────────────────────
    var Reconocimiento = window.SpeechRecognition || window.webkitSpeechRecognition;
    var reconocimiento = null;
    var escuchando = false;
    var dictadoUsado = false;

    function detenerDictado() {
        if (reconocimiento && escuchando) {
            try { reconocimiento.stop(); } catch (e) { /* ya detenido */ }
        }
    }

    if (Reconocimiento) {
        botonMic.hidden = false;
        botonMic.addEventListener('click', function () {
            if (escuchando) {
                detenerDictado();
                return;
            }
            detenerVoz();
            reconocimiento = new Reconocimiento();
            reconocimiento.lang = 'es-EC';
            reconocimiento.interimResults = true;
            reconocimiento.maxAlternatives = 1;
            var base = entrada.value ? entrada.value.replace(/\s*$/, ' ') : '';
            var final = '';
            reconocimiento.onstart = function () {
                escuchando = true;
                botonMic.classList.add('is-escuchando');
                botonMic.setAttribute('aria-label', 'Detener dictado');
                estadoTexto.textContent = 'Escuchando…';
            };
            reconocimiento.onresult = function (evento) {
                var parcial = '';
                for (var i = evento.resultIndex; i < evento.results.length; i += 1) {
                    if (evento.results[i].isFinal) final += evento.results[i][0].transcript;
                    else parcial += evento.results[i][0].transcript;
                }
                entrada.value = base + final + parcial;
                ajustarTextarea();
            };
            reconocimiento.onerror = function (evento) {
                if (evento.error === 'not-allowed' || evento.error === 'service-not-allowed') {
                    mostrarError('No tengo permiso para usar el micrófono. Actívalo en el navegador para dictar.');
                }
            };
            reconocimiento.onend = function () {
                escuchando = false;
                botonMic.classList.remove('is-escuchando');
                botonMic.setAttribute('aria-label', 'Dictar por voz');
                estadoTexto.textContent = 'Asistente de Econotec';
                if (final.trim()) {
                    dictadoUsado = true;
                    formulario.requestSubmit ? formulario.requestSubmit() : formulario.dispatchEvent(new Event('submit', { cancelable: true }));
                }
            };
            try { reconocimiento.start(); } catch (e) { /* ya activo */ }
        });
    }

    var sintesis = window.speechSynthesis;

    var SIN_EMOJIS = null;
    try {
        SIN_EMOJIS = new RegExp('[\\u{1F000}-\\u{1FAFF}\\u{2600}-\\u{27BF}\\u{2190}-\\u{21FF}\\u{2B00}-\\u{2BFF}\\u{FE0F}]', 'gu');
    } catch (e) {
        SIN_EMOJIS = null;
    }

    function textoParaVoz(texto) {
        var limpio = String(texto || '');
        if (SIN_EMOJIS) limpio = limpio.replace(SIN_EMOJIS, '');
        return limpio
            .replace(/[•«»]/g, '')
            .replace(/\s+/g, ' ')
            .trim()
            .slice(0, 600);
    }

    function hablar(texto) {
        if (!sintesis || !window.SpeechSynthesisUtterance) return;
        var limpio = textoParaVoz(texto);
        if (!limpio) return;
        try {
            sintesis.cancel();
            var locucion = new window.SpeechSynthesisUtterance(limpio);
            locucion.lang = 'es-ES';
            var voces = sintesis.getVoices() || [];
            var voz = voces.filter(function (v) { return /^es(-|_)(EC|419|MX|US|CO)/i.test(v.lang); })[0]
                || voces.filter(function (v) { return /^es/i.test(v.lang); })[0];
            if (voz) {
                locucion.voice = voz;
                locucion.lang = voz.lang;
            }
            sintesis.speak(locucion);
        } catch (e) { /* sin voz */ }
    }

    function detenerVoz() {
        if (sintesis) {
            try { sintesis.cancel(); } catch (e) { /* nada que detener */ }
        }
    }

    function pintarBotonVoz() {
        botonVoz.setAttribute('aria-pressed', vozActiva ? 'true' : 'false');
        botonVoz.textContent = vozActiva ? '🔊' : '🔇';
        botonVoz.title = vozActiva
            ? 'Leer en voz alta las respuestas cuando hablas por micrófono (activado)'
            : 'Lectura en voz alta desactivada';
    }

    if (sintesis && Reconocimiento) {
        botonVoz.hidden = false;
        pintarBotonVoz();
        botonVoz.addEventListener('click', function () {
            vozActiva = !vozActiva;
            guardar(CLAVE_VOZ, vozActiva ? 'si' : 'no');
            if (!vozActiva) detenerVoz();
            pintarBotonVoz();
        });
    }

    // ── Botón flotante sobre barras fijas inferiores ─────────────────
    function ajustarLanzador() {
        var extra = 0;
        Array.prototype.forEach.call(document.querySelectorAll('.actions-bar'), function (barra) {
            var estilo = window.getComputedStyle(barra);
            if (estilo.position !== 'fixed' || estilo.display === 'none' || estilo.visibility === 'hidden') return;
            var caja = barra.getBoundingClientRect();
            if (caja.height > 0 && caja.bottom >= window.innerHeight - 4) extra = Math.max(extra, caja.height);
        });
        raiz.style.setProperty('--eb-extra-bottom', extra + 'px');
    }
    window.addEventListener('resize', ajustarLanzador);
    window.addEventListener('load', ajustarLanzador);
    ajustarLanzador();

    if (typeof MOVIL.addEventListener === 'function') {
        MOVIL.addEventListener('change', function () {
            document.documentElement.classList.toggle('econobot-bloqueo', abierto && MOVIL.matches);
        });
    }

    // ── Estado inicial ───────────────────────────────────────────────
    var pendienteGuardado = leer(CLAVE_PENDIENTE);
    if (pendienteGuardado) actualizarBanner(true, pendienteGuardado);
    if (window.location.hash === '#econobot') {
        // Un enlace a «…#econobot» abre el chat directamente.
        abrir({ sinFoco: true });
        if (window.history && window.history.replaceState) {
            window.history.replaceState(null, '', window.location.pathname + window.location.search);
        }
    } else if (leer(CLAVE_ABIERTO) === 'si' && !MOVIL.matches) {
        abrir({ sinFoco: true });
    }
})();
