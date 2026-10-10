/*
 * Simulación gamificada del equipo (detalle del ingreso).
 *
 * Pinta un mapa isométrico en SVG con las estaciones del flujo de Econotec
 * (Recepción → Diagnóstico → Taller → Listo → Caja → Salida), los personajes
 * reales del equipo (el género viene inferido desde el servidor) y anima el
 * recorrido del equipo hasta su estado actual.
 *
 * Todo dato del usuario se pinta con textContent: nunca con innerHTML.
 */
(function () {
    'use strict';

    var nodoDatos = document.getElementById('simulacion-data');
    var boton = document.getElementById('sim-abrir');
    if (!nodoDatos || !boton) return;

    var datos = JSON.parse(nodoDatos.textContent);
    var urlMascota = boton.getAttribute('data-mascota') || '';
    var SVGNS = 'http://www.w3.org/2000/svg';
    var TW = 32;
    var TH = 16;
    var ZH = 34;
    var reducido = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);

    // ── Geometría del mundo ───────────────────────────────────────────
    var VIA_A = 4;
    var VIA_B = 15.6;
    var VIA_C = 9.6;
    var CALLE = 0;
    var ESPERA_CLIENTE = [CALLE, 6.8];
    var Z_PLAT = 0.3;
    // `acceso`: puntos desde la vía hasta el lugar (`slot`) donde reposa el equipo.
    var ESTACIONES = [
        { cx: 3.4, cy: 1.7, lado: 'a', slot: [4.4, 1.95, Z_PLAT + 0.55], acceso: [[4.4, 3.0, Z_PLAT]] },
        { cx: 8.4, cy: 1.7, lado: 'a', slot: [9.5, 1.0, Z_PLAT + 0.5], acceso: [[9.5, 3.0, Z_PLAT]] },
        { cx: 13.2, cy: 1.7, lado: 'a', slot: [14.3, 1.0, Z_PLAT + 0.5], acceso: [[14.3, 3.0, Z_PLAT]] },
        { cx: 13.2, cy: 11.8, lado: 'c', slot: [13.4, 12.0, Z_PLAT + 0.12], acceso: [[14.8, 10.4, Z_PLAT], [14.8, 12.0, Z_PLAT]] },
        { cx: 8.4, cy: 11.8, lado: 'c', slot: [9.1, 11.65, Z_PLAT + 0.55], acceso: [[10.0, 10.4, Z_PLAT], [10.0, 11.65, Z_PLAT]] },
        { cx: 3.4, cy: 11.8, lado: 'c', slot: [3.4, 11.5, Z_PLAT], acceso: [[3.4, 10.4, Z_PLAT]] }
    ];
    var ICONOS_EQUIPO = {
        impresora: '🖨', laptop: '💻', pc: '🖥', monitor: '🖥', cpu: '🖥',
        celular: '📱', tablet: '📱', consola: '🎮', mando: '🎮', maquina_coser: '🧵'
    };
    var NIVELES = ['Recién llegado', 'En revisión', 'En el taller', 'Casi listo', 'Por cobrar', 'Entregado'];
    var TEXTO_ESTADO = { hecho: 'Completado', actual: 'Está aquí', pendiente: 'Pendiente', alerta: 'Requiere atención' };

    // ── Utilidades DOM ────────────────────────────────────────────────
    function iso(x, y, z) {
        return [(x - y) * TW, (x + y) * TH - (z || 0) * ZH];
    }

    function puntos(lista) {
        return lista.map(function (p) {
            var s = iso(p[0], p[1], p[2]);
            return s[0].toFixed(1) + ',' + s[1].toFixed(1);
        }).join(' ');
    }

    function svg(tag, attrs, padre) {
        var n = document.createElementNS(SVGNS, tag);
        if (attrs) {
            Object.keys(attrs).forEach(function (k) { n.setAttribute(k, attrs[k]); });
        }
        if (padre) padre.appendChild(n);
        return n;
    }

    function svgTexto(padre, attrs, contenido) {
        var t = svg('text', attrs, padre);
        t.textContent = contenido;
        return t;
    }

    function html(tag, clase, padre, contenido) {
        var n = document.createElement(tag);
        if (clase) n.className = clase;
        if (contenido !== undefined && contenido !== null) n.textContent = contenido;
        if (padre) padre.appendChild(n);
        return n;
    }

    function hash(texto) {
        var h = 0;
        for (var i = 0; i < (texto || '').length; i++) {
            h = ((h << 5) - h + texto.charCodeAt(i)) | 0;
        }
        return Math.abs(h);
    }

    function anchoTexto(nodo, respaldo) {
        try {
            var w = nodo.getComputedTextLength();
            if (w > 0) return w;
        } catch (e) { /* el nodo aún no se pinta */ }
        return respaldo;
    }

    function esperar(ms) {
        return new Promise(function (ok) { setTimeout(ok, reducido ? 0 : ms); });
    }

    // ── Piezas isométricas ────────────────────────────────────────────
    function prisma(padre, x, y, z, w, d, alto, tono) {
        var g = svg('g', { 'class': 'pz ' + tono }, padre);
        var z1 = z + alto;
        svg('polygon', { 'class': 'izq', points: puntos([[x, y + d, z1], [x + w, y + d, z1], [x + w, y + d, z], [x, y + d, z]]) }, g);
        svg('polygon', { 'class': 'der', points: puntos([[x + w, y, z1], [x + w, y + d, z1], [x + w, y + d, z], [x + w, y, z]]) }, g);
        svg('polygon', { 'class': 'top', points: puntos([[x, y, z1], [x + w, y, z1], [x + w, y + d, z1], [x, y + d, z1]]) }, g);
        return g;
    }

    function losa(padre, x, y, w, d, z, clase) {
        return svg('polygon', { 'class': clase, points: puntos([[x, y, z], [x + w, y, z], [x + w, y + d, z], [x, y + d, z]]) }, padre);
    }

    // Texto pintado sobre la cara izquierda (a lo largo del eje x) o derecha (eje y).
    function rotulo(padre, x, y, z, eje, contenido, clase) {
        var p = iso(x, y, z);
        var m = eje === 'x' ? 'matrix(0.894,0.447,0,1,' : 'matrix(0.894,-0.447,0,1,';
        return svgTexto(padre, { 'class': clase, transform: m + p[0].toFixed(1) + ',' + p[1].toFixed(1) + ')', 'text-anchor': 'middle' }, contenido);
    }

    // ── Escena ────────────────────────────────────────────────────────
    var raiz;
    var lienzo;
    var capaSuelo;
    var capaObjetos;
    var capaUI;
    var capaGlobos;
    var objetos = [];
    var entidades = {};
    var etiquetas = [];
    var plataformas = [];
    var vista = null;
    var vistaInicial = null;
    // Zona del mundo que siempre debe verse (la punta derecha de la isla, que
    // solo tiene árboles, puede quedar bajo el panel lateral).
    var MUNDO = { x: -478, y: -78, w: 960, h: 630 };
    var seleccion = datos.etapa_actual;
    var turno = 0;
    var construido = false;
    var escenaOrdenada = false;
    var relojId = null;

    function registrar(el, profundidad) {
        var ent = { el: el, profundidad: profundidad };
        objetos.push(ent);
        return ent;
    }

    function ordenarTodo() {
        objetos.sort(function (a, b) { return a.profundidad - b.profundidad; });
        objetos.forEach(function (o) { capaObjetos.appendChild(o.el); });
        escenaOrdenada = true;
    }

    function reordenar(ent) {
        var i = objetos.indexOf(ent);
        if (i !== -1) objetos.splice(i, 1);
        var j = 0;
        while (j < objetos.length && objetos[j].profundidad <= ent.profundidad) j++;
        objetos.splice(j, 0, ent);
        var siguiente = objetos[j + 1] ? objetos[j + 1].el : null;
        if (ent.el.parentNode !== capaObjetos || ent.el.nextSibling !== siguiente) {
            capaObjetos.insertBefore(ent.el, siguiente);
        }
    }

    function objetoEstatico(profundidad, dibujar) {
        var g = svg('g', null);
        dibujar(g);
        return registrar(g, profundidad);
    }

    function arbol(x, y, escala) {
        escala = escala || 1;
        objetoEstatico(x + y, function (g) {
            var p = iso(x, y, 0);
            g.setAttribute('transform', 'translate(' + p[0].toFixed(1) + ',' + p[1].toFixed(1) + ') scale(' + escala + ')');
            g.setAttribute('class', 'sim-arbol');
            svg('ellipse', { cx: 0, cy: 0, rx: 11, ry: 5.5, 'class': 'sombra' }, g);
            svg('rect', { x: -2, y: -16, width: 4, height: 16, rx: 1.5, 'class': 'tronco' }, g);
            svg('circle', { cx: 0, cy: -26, r: 13, 'class': 'copa' }, g);
            svg('circle', { cx: -4, cy: -30, r: 6, 'class': 'copa-luz' }, g);
        });
    }

    function farol(x, y) {
        objetoEstatico(x + y, function (g) {
            var p = iso(x, y, 0);
            g.setAttribute('transform', 'translate(' + p[0].toFixed(1) + ',' + p[1].toFixed(1) + ')');
            svg('rect', { x: -1.2, y: -42, width: 2.4, height: 42, rx: 1, 'class': 'farol-poste' }, g);
            svg('circle', { cx: 0, cy: -44, r: 4.5, 'class': 'farol-luz' }, g);
        });
    }

    function construirSuelo() {
        // Isla flotante.
        prisma(capaSuelo, -1.2, -0.6, -0.9, 19.2, 14.6, 0.9, 't-isla');
        // Calle lateral que une la entrada y la salida.
        losa(capaSuelo, -0.9, 1.6, 1.8, 11.6, 0.01, 'sim-calle');
        for (var yy = 2.2; yy < 12.6; yy += 1.1) {
            losa(capaSuelo, -0.06, yy, 0.12, 0.55, 0.02, 'sim-calle-linea');
        }
        // Parque central.
        losa(capaSuelo, 2.2, 5.3, 12.4, 3.2, 0.01, 'sim-parque');
        var lago = [[9.4, 6.0, 0.02], [11.6, 5.8, 0.02], [12.6, 6.8, 0.02], [11.4, 7.9, 0.02], [9.2, 7.6, 0.02], [8.6, 6.7, 0.02]];
        svg('polygon', { 'class': 'sim-lago', points: puntos(lago) }, capaSuelo);
        svg('polygon', { 'class': 'sim-lago-brillo', points: puntos([[10.2, 6.4, 0.03], [11.3, 6.3, 0.03], [11.6, 6.7, 0.03], [10.5, 6.8, 0.03]]) }, capaSuelo);

        // Vías: A (recepción → taller), B (giro) y C (listo → salida).
        losa(capaSuelo, -0.9, VIA_A - 0.65, VIA_B + 0.65 + 0.9, 1.3, 0.02, 'sim-via');
        losa(capaSuelo, VIA_B - 0.65, VIA_A - 0.65, 1.3, VIA_C - VIA_A + 1.3, 0.02, 'sim-via');
        losa(capaSuelo, -0.9, VIA_C - 0.65, VIA_B + 0.65 + 0.9, 1.3, 0.02, 'sim-via');
        flechas();

        // Plataformas de cada estación.
        ESTACIONES.forEach(function (est, i) {
            var x0 = est.cx - 1.8;
            var y0 = est.lado === 'a' ? 0.4 : 10.5;
            var g = prisma(capaSuelo, x0, y0, 0, 3.6, 2.6, Z_PLAT, 't-plat');
            g.classList.add('sim-plataforma');
            g.setAttribute('data-etapa', i);
            var anillo = svg('polygon', { 'class': 'sim-plat-borde', points: puntos([[x0, y0, Z_PLAT], [x0 + 3.6, y0, Z_PLAT], [x0 + 3.6, y0 + 2.6, Z_PLAT], [x0, y0 + 2.6, Z_PLAT]]) }, g);
            var c = iso(est.cx, est.cy, Z_PLAT);
            var pulso = svg('ellipse', { cx: c[0].toFixed(1), cy: c[1].toFixed(1), rx: 62, ry: 31, 'class': 'sim-pulso' }, g);
            plataformas.push({ g: g, anillo: anillo, pulso: pulso });
            g.addEventListener('click', function () { seleccionar(i, true); });
        });
    }

    function flechas() {
        var tramos = [
            { desde: [0.6, VIA_A], hasta: [VIA_B - 0.6, VIA_A] },
            { desde: [VIA_B, VIA_A + 0.6], hasta: [VIA_B, VIA_C - 0.6] },
            { desde: [VIA_B - 0.6, VIA_C], hasta: [0.6, VIA_C] }
        ];
        var n = 0;
        tramos.forEach(function (t) {
            var dx = t.hasta[0] - t.desde[0];
            var dy = t.hasta[1] - t.desde[1];
            var largo = Math.sqrt(dx * dx + dy * dy);
            var ux = dx / largo;
            var uy = dy / largo;
            for (var s = 0; s <= largo; s += 1.25) {
                var x = t.desde[0] + ux * s;
                var y = t.desde[1] + uy * s;
                // Chevron ">" en el plano del suelo apuntando hacia el avance.
                var px = -uy;
                var py = ux;
                var forma = [
                    [x - ux * 0.25 + px * 0.32, y - uy * 0.25 + py * 0.32, 0.03],
                    [x + ux * 0.2, y + uy * 0.2, 0.03],
                    [x - ux * 0.25 - px * 0.32, y - uy * 0.25 - py * 0.32, 0.03],
                    [x - ux * 0.05 - px * 0.32, y - uy * 0.05 - py * 0.32, 0.03],
                    [x + ux * 0.4, y + uy * 0.4, 0.03],
                    [x - ux * 0.05 + px * 0.32, y - uy * 0.05 + py * 0.32, 0.03]
                ];
                svg('polygon', { 'class': 'sim-flecha', points: puntos(forma), style: 'animation-delay:' + (n * 0.09).toFixed(2) + 's' }, capaSuelo);
                n++;
            }
        });
    }

    function arco(x, y, letrero) {
        // Pórtico que cruza la vía: el letrero va en la cara que mira a la cámara.
        objetoEstatico(x + y - 0.2, function (g) {
            prisma(g, x - 0.2, y - 1.0, 0, 0.4, 0.35, 1.7, 't-pilar');
        });
        objetoEstatico(x + y + 1.4, function (g) {
            prisma(g, x - 0.2, y + 0.65, 0, 0.4, 0.35, 1.7, 't-pilar');
            prisma(g, x - 0.25, y - 1.15, 1.7, 0.5, 2.3, 0.55, 't-arco');
            rotulo(g, x + 0.26, y, 1.86, 'y', letrero, 'sim-arco-texto');
        });
    }

    function construirEstaciones() {
        var e;

        // 0 · Recepción: mostrador y planta.
        e = ESTACIONES[0];
        objetoEstatico(e.cx - 0.1 + 1.95, function (g) {
            prisma(g, e.cx - 1.5, 1.7, Z_PLAT, 2.8, 0.5, 0.55, 't-mostrador');
            prisma(g, e.cx - 1.5, 1.7, Z_PLAT + 0.55, 2.8, 0.5, 0.06, 't-acento');
            rotulo(g, e.cx - 0.1, 2.2, Z_PLAT + 0.22, 'x', 'RECEPCIÓN', 'sim-rotulo');
        });
        objetoEstatico(e.cx + 1.4 + 0.8, function (g) { maceta(g, e.cx + 1.4, 0.8); });

        // 1 · Diagnóstico: escritorio con monitor y lupa.
        e = ESTACIONES[1];
        objetoEstatico(e.cx + 0.7 + 1.0, function (g) {
            prisma(g, e.cx - 0.2, 0.7, Z_PLAT, 1.8, 0.6, 0.5, 't-madera');
            prisma(g, e.cx - 0.05, 0.76, Z_PLAT + 0.5, 0.7, 0.12, 0.5, 't-monitor');
            var p = iso(e.cx + 0.3, 0.88, Z_PLAT + 0.78);
            svgTexto(g, { x: p[0].toFixed(1), y: p[1].toFixed(1), 'class': 'sim-emoji-mini', 'text-anchor': 'middle' }, '📊');
        });

        // 2 · Taller: banco de trabajo, panel de herramientas y lámpara.
        e = ESTACIONES[2];
        // El panel de herramientas es una pared al fondo: se ordena por su esquina mínima.
        objetoEstatico(e.cx - 0.2 + 0.5, function (g) {
            prisma(g, e.cx - 0.2, 0.5, Z_PLAT, 1.8, 0.12, 1.25, 't-panel');
            ['🔧', '🪛', '🔌'].forEach(function (ico, k) {
                var p = iso(e.cx + 0.15 + k * 0.55, 0.62, Z_PLAT + 0.85);
                svgTexto(g, { x: p[0].toFixed(1), y: p[1].toFixed(1), 'class': 'sim-emoji-mini', 'text-anchor': 'middle' }, ico);
            });
        });
        objetoEstatico(e.cx + 0.7 + 1.0, function (g) {
            prisma(g, e.cx - 0.2, 0.7, Z_PLAT, 1.8, 0.6, 0.5, 't-banco');
            prisma(g, e.cx - 0.05, 0.8, Z_PLAT + 0.5, 0.35, 0.3, 0.12, 't-acento');
        });

        // 3 · Listo para retiro: estantería con equipos y pallet.
        e = ESTACIONES[3];
        objetoEstatico(e.cx - 0.1 + 10.9, function (g) {
            prisma(g, e.cx - 1.5, 10.7, Z_PLAT, 2.7, 0.45, 0.08, 't-estante');
            prisma(g, e.cx - 1.5, 10.7, Z_PLAT + 0.6, 2.7, 0.45, 0.08, 't-estante');
            prisma(g, e.cx - 1.5, 10.7, Z_PLAT + 1.2, 2.7, 0.45, 0.08, 't-estante');
            [[-1.3, 0.08, 't-cajita'], [-0.6, 0.08, 't-cajita2'], [0.5, 0.08, 't-cajita'], [-1.1, 0.68, 't-cajita2'], [0.1, 0.68, 't-cajita'], [0.7, 0.68, 't-cajita2']].forEach(function (c) {
                prisma(g, e.cx + c[0], 10.75, Z_PLAT + c[1], 0.45, 0.35, 0.4, c[2]);
            });
        });
        objetoEstatico(13.4 + 12.0 - 0.3, function (g) {
            prisma(g, 12.95, 11.55, Z_PLAT, 0.9, 0.9, 0.12, 't-madera');
        });

        // 4 · Caja: mostrador con caja registradora y Econobot.
        e = ESTACIONES[4];
        objetoEstatico(e.cx + 11.65, function (g) {
            prisma(g, e.cx - 1.0, 11.4, Z_PLAT, 2.0, 0.5, 0.55, 't-mostrador');
            prisma(g, e.cx - 1.0, 11.4, Z_PLAT + 0.55, 2.0, 0.5, 0.06, 't-acento');
            prisma(g, e.cx - 0.95, 11.45, Z_PLAT + 0.61, 0.5, 0.38, 0.25, 't-monitor');
            rotulo(g, e.cx, 11.9, Z_PLAT + 0.22, 'x', 'CAJA', 'sim-rotulo');
        });

        // 5 · Salida: puerta y bancas.
        e = ESTACIONES[5];
        objetoEstatico(e.cx + 10.9, function (g) {
            prisma(g, e.cx - 1.2, 10.75, Z_PLAT, 0.25, 0.25, 1.4, 't-pilar');
            prisma(g, e.cx + 0.95, 10.75, Z_PLAT, 0.25, 0.25, 1.4, 't-pilar');
            prisma(g, e.cx - 1.2, 10.75, Z_PLAT + 1.4, 2.4, 0.25, 0.3, 't-arco');
            rotulo(g, e.cx, 11.0, Z_PLAT + 1.48, 'x', 'GRACIAS', 'sim-arco-texto');
        });
        objetoEstatico(e.cx - 1.0 + 12.7, function (g) { prisma(g, e.cx - 1.3, 12.5, Z_PLAT, 1.0, 0.35, 0.22, 't-madera'); });
        objetoEstatico(e.cx + 1.2 + 12.4, function (g) { maceta(g, e.cx + 1.2, 12.4); });

        // Plaza central con la estatua de Econobot.
        objetoEstatico(5.6 + 6.9, function (g) {
            prisma(g, 4.9, 6.2, 0, 1.4, 1.4, 0.35, 't-pedestal');
            var p = iso(5.6, 6.9, 0.35);
            if (urlMascota) {
                var img = svg('image', { x: (p[0] - 30).toFixed(1), y: (p[1] - 66).toFixed(1), width: 60, height: 66, 'class': 'sim-estatua' }, g);
                img.setAttributeNS('http://www.w3.org/1999/xlink', 'href', urlMascota);
                img.setAttribute('href', urlMascota);
            }
        });

        arco(0.9, VIA_A, 'ECONOTEC');
        arco(0.9, VIA_C, 'SALIDA');

        // Vegetación y faroles.
        [[2.9, 5.9, 1], [3.8, 7.9, 0.85], [7.2, 5.7, 0.9], [7.6, 8.1, 1.05], [13.4, 5.9, 0.9], [13.9, 7.9, 1.1], [16.9, 1.2, 1], [17.0, 12.4, 0.95], [16.8, 6.8, 1.1], [0.9, 0.2, 0.85], [6.0, 0.2, 0.7], [10.9, 0.3, 0.75], [0.9, 13.0, 0.8], [6.0, 13.2, 0.7], [10.8, 13.1, 0.8]].forEach(function (a) {
            arbol(a[0], a[1], a[2]);
        });
        [[5.4, 3.0], [10.6, 3.0], [5.4, 10.9], [10.6, 10.9], [16.6, 4.4]].forEach(function (f) { farol(f[0], f[1]); });
    }

    function maceta(g, x, y) {
        prisma(g, x - 0.18, y - 0.18, Z_PLAT, 0.36, 0.36, 0.3, 't-maceta');
        var p = iso(x, y, Z_PLAT + 0.3);
        svg('circle', { cx: p[0].toFixed(1), cy: (p[1] - 8).toFixed(1), r: 8.5, 'class': 'copa' }, g);
        svg('circle', { cx: (p[0] - 2.5).toFixed(1), cy: (p[1] - 11).toFixed(1), r: 3.5, 'class': 'copa-luz' }, g);
    }

    // ── Personajes ────────────────────────────────────────────────────
    var PIELES = ['#f1c9a5', '#e0ac69', '#c68642', '#a8754a', '#8d5524'];
    var PELOS = ['#2b1d14', '#1f1a17', '#4a2f1d', '#3b2a20', '#6b4423'];
    var ROPA_CLIENTE = ['#2563eb', '#0d9488', '#7c3aed', '#db2777', '#0891b2', '#16a34a'];

    function paleta(persona, tipo) {
        var h = hash(persona.nombre_completo || persona.nombre || tipo);
        var p = {
            piel: PIELES[h % PIELES.length],
            pelo: PELOS[(h >> 3) % PELOS.length],
            ropa: ROPA_CLIENTE[(h >> 5) % ROPA_CLIENTE.length],
            pantalon: '#334155'
        };
        if (tipo === 'asesora') { p.ropa = '#f97618'; p.pantalon = '#1f2937'; }
        if (tipo === 'tecnico') { p.ropa = '#334155'; p.pantalon = '#1e293b'; p.gorra = '#f97618'; }
        return p;
    }

    function dibujarPersona(padre, genero, p) {
        var g = svg('g', { 'class': 'sim-persona-cuerpo' }, padre);
        svg('ellipse', { cx: 0, cy: 0, rx: 7.5, ry: 3.6, 'class': 'sombra' }, g);
        var piernas = svg('g', { 'class': 'piernas' }, g);
        svg('rect', { x: -4.2, y: -10, width: 3.4, height: 10, rx: 1.6, fill: genero === 'f' ? p.piel : p.pantalon, 'class': 'pierna pi' }, piernas);
        svg('rect', { x: 0.8, y: -10, width: 3.4, height: 10, rx: 1.6, fill: genero === 'f' ? p.piel : p.pantalon, 'class': 'pierna pd' }, piernas);
        var torso = svg('g', { 'class': 'torso' }, g);
        if (genero === 'f') {
            // Cabello largo por detrás de la cabeza.
            svg('path', { d: 'M-7.2,-27 a7.2,7.6 0 0 1 14.4,0 l0.6,10.5 q-1.4,1.7 -3.4,0.6 l-0.6,-7.5 h-7.6 l-0.6,7.5 q-2,1.1 -3.4,-0.6 z', fill: p.pelo }, torso);
            svg('path', { d: 'M-5.4,-21 L5.4,-21 L8.4,-8 Q0,-6 -8.4,-8 Z', fill: p.ropa, 'stroke-linejoin': 'round' }, torso);
        } else {
            svg('rect', { x: -6.2, y: -21.5, width: 12.4, height: 12.5, rx: 3.5, fill: p.ropa }, torso);
        }
        svg('rect', { x: -8.6, y: -20.5, width: 3, height: 10, rx: 1.5, fill: p.ropa, 'class': 'brazo bi' }, torso);
        svg('rect', { x: 5.6, y: -20.5, width: 3, height: 10, rx: 1.5, fill: p.ropa, 'class': 'brazo bd' }, torso);
        svg('circle', { cx: 0, cy: -27.5, r: 6.2, fill: p.piel }, torso);
        if (genero === 'f') {
            svg('path', { d: 'M-6.6,-27.2 a6.6,7 0 0 1 13.2,0 q-2.6,-3.4 -7.4,-2.4 q-2.8,0.6 -5.8,2.4 z', fill: p.pelo }, torso);
            if (p.gorra) svg('rect', { x: -6.4, y: -32.4, width: 12.8, height: 2.2, rx: 1.1, fill: p.gorra }, torso);
        } else if (p.gorra) {
            svg('path', { d: 'M-6.6,-28 a6.6,6.4 0 0 1 13.2,0 z', fill: p.gorra }, torso);
            svg('rect', { x: 2, y: -29.2, width: 7.2, height: 2, rx: 1, fill: p.gorra }, torso);
        } else {
            svg('path', { d: 'M-6.5,-26.6 a6.5,6.8 0 0 1 13,0 q-3,-2.2 -6.5,-1.7 q-3.5,-0.5 -6.5,1.7 z', fill: p.pelo }, torso);
        }
        svg('circle', { cx: -2.2, cy: -27, r: 0.85, 'class': 'ojo' }, torso);
        svg('circle', { cx: 2.2, cy: -27, r: 0.85, 'class': 'ojo' }, torso);
        svg('path', { d: 'M-1.6,-24.4 q1.6,1.2 3.2,0', 'class': 'boca' }, torso);
        return g;
    }

    function dibujarRobot(padre) {
        var g = svg('g', { 'class': 'sim-persona-cuerpo' }, padre);
        svg('ellipse', { cx: 0, cy: 0, rx: 7.5, ry: 3.6, 'class': 'sombra' }, g);
        var torso = svg('g', { 'class': 'torso' }, g);
        svg('rect', { x: -6, y: -18, width: 12, height: 15, rx: 4, 'class': 'robot-cuerpo' }, torso);
        svg('circle', { cx: 0, cy: -10.5, r: 2.4, 'class': 'robot-luz' }, torso);
        svg('rect', { x: -8, y: -32, width: 16, height: 12.5, rx: 5, 'class': 'robot-cuerpo' }, torso);
        svg('rect', { x: -5.8, y: -29.5, width: 11.6, height: 7, rx: 3.5, 'class': 'robot-visor' }, torso);
        svg('circle', { cx: -2.4, cy: -26, r: 1.2, 'class': 'robot-ojo' }, torso);
        svg('circle', { cx: 2.4, cy: -26, r: 1.2, 'class': 'robot-ojo' }, torso);
        svg('line', { x1: 0, y1: -32, x2: 0, y2: -36, 'class': 'robot-antena' }, torso);
        svg('circle', { cx: 0, cy: -37, r: 1.8, 'class': 'robot-luz' }, torso);
        return g;
    }

    function crearPersonaje(clave, persona, tipo, x, y, z) {
        var g = svg('g', { 'class': 'sim-personaje sim-' + tipo });
        var escala = svg('g', { transform: 'scale(1.2)' }, g);
        var cuerpo = svg('g', { 'class': 'sim-flota' }, escala);
        if (tipo === 'robot') {
            dibujarRobot(cuerpo);
        } else {
            dibujarPersona(cuerpo, persona.genero, paleta(persona, tipo));
        }
        var sobre = svg('g', { 'class': 'sim-sobre sim-' + tipo }, capaGlobos);
        var placa = svg('g', { 'class': 'sim-placa', transform: 'translate(0,-54)' }, sobre);
        var fondo = svg('rect', { x: -20, y: -9, width: 40, height: 15, rx: 7.5 }, placa);
        var t = svgTexto(placa, { x: 0, y: 2, 'text-anchor': 'middle' }, persona.nombre);
        var burbuja = svg('g', { 'class': 'sim-burbuja', transform: 'translate(0,-74)' }, sobre);
        var ent = registrar(g, 0);
        ent.x = x; ent.y = y; ent.z = z || 0;
        ent.placa = { fondo: fondo, texto: t };
        ent.burbuja = burbuja;
        ent.sobre = sobre;
        ent.persona = persona;
        var alClic = function () { seleccionar(etapaDePersonaje(clave), true); };
        g.addEventListener('click', alClic);
        placa.addEventListener('click', alClic);
        entidades[clave] = ent;
        return ent;
    }

    function etapaDePersonaje(clave) {
        if (clave === 'asesora') return 0;
        if (clave === 'tecnico') return entidades.tecnico && entidades.tecnico.x > 11 ? 2 : 1;
        if (clave === 'tecnico_reparo') return 2;
        if (clave === 'robot') return 4;
        if (clave === 'cliente') return datos.retirado ? 5 : datos.etapa_actual;
        return datos.etapa_actual;
    }

    function ajustarPlaca(ent) {
        var w = anchoTexto(ent.placa.texto, ent.persona.nombre.length * 6.4) + 14;
        ent.placa.fondo.setAttribute('x', (-w / 2).toFixed(1));
        ent.placa.fondo.setAttribute('width', w.toFixed(1));
    }

    function decir(ent, contenido, tono) {
        if (!ent || !ent.burbuja) return;
        var b = ent.burbuja;
        while (b.firstChild) b.removeChild(b.firstChild);
        b.setAttribute('class', 'sim-burbuja' + (tono ? ' es-' + tono : ''));
        if (!contenido) return;
        // El grupo interno es el que se anima: el externo conserva su posición.
        var globo = svg('g', { 'class': 'sim-globo' }, b);
        var fondo = svg('rect', { x: -40, y: -14, width: 80, height: 22, rx: 11 }, globo);
        svg('path', { d: 'M-4,7.5 L0,13 L4,7.5 Z', 'class': 'pico' }, globo);
        var t = svgTexto(globo, { x: 0, y: 1.5, 'text-anchor': 'middle' }, contenido);
        var w = anchoTexto(t, contenido.length * 6.2) + 20;
        fondo.setAttribute('x', (-w / 2).toFixed(1));
        fondo.setAttribute('width', w.toFixed(1));
    }

    function colocar(ent, x, y, z) {
        ent.x = x; ent.y = y; ent.z = z || 0;
        var p = iso(x, y, ent.z + (ent.salto || 0));
        var traslado = 'translate(' + p[0].toFixed(1) + ',' + p[1].toFixed(1) + ')';
        ent.el.setAttribute('transform', traslado);
        if (ent.sobre) ent.sobre.setAttribute('transform', traslado);
        var prof = x + y + (ent.extraProfundidad || 0);
        if (Math.abs(prof - ent.profundidad) > 0.01) {
            ent.profundidad = prof;
            if (escenaOrdenada) reordenar(ent);
        }
    }

    // ── Equipo (caja con insignia) ────────────────────────────────────
    function crearEquipo() {
        var g = svg('g', { 'class': 'sim-equipo' });
        var cuerpo = svg('g', null, g);
        svg('ellipse', { cx: 0, cy: 0, rx: 13, ry: 6.5, 'class': 'sombra' }, cuerpo);
        prisma(cuerpo, -0.32, -0.32, 0, 0.64, 0.64, 0.5, 't-carton');
        prisma(cuerpo, -0.06, -0.32, 0.5, 0.12, 0.64, 0.015, 't-cinta');
        var ent = registrar(g, 0);
        ent.extraProfundidad = 0.15;
        ent.el.addEventListener('click', function () { seleccionar(datos.etapa_actual, true); });
        entidades.equipo = ent;

        // Insignia con el tipo de equipo y su código, siempre visible encima.
        ent.sobre = svg('g', { 'class': 'sim-equipo-marca' }, capaGlobos);
        var salto = svg('g', { 'class': 'sim-equipo-salto' }, ent.sobre);
        var insignia = svg('g', { 'class': 'sim-equipo-insignia', transform: 'translate(0,-34)' }, salto);
        svg('circle', { cx: 0, cy: 0, r: 11 }, insignia);
        svgTexto(insignia, { x: 0, y: 4.5, 'text-anchor': 'middle' }, ICONOS_EQUIPO[datos.equipo.tipo] || '📦');
        var chip = svg('g', { transform: 'translate(13,-34)' }, salto);
        var fondo = svg('rect', { x: 0, y: -9, width: 54, height: 18, rx: 9, 'class': 'sim-equipo-chip' }, chip);
        var t = svgTexto(chip, { x: 8, y: 4, 'class': 'sim-equipo-codigo' }, datos.codigo);
        ent.chip = { fondo: fondo, texto: t };
        ent.sobre.addEventListener('click', function () { seleccionar(datos.etapa_actual, true); });
        return ent;
    }

    // ── Etiquetas de estaciones ───────────────────────────────────────
    function crearEtiquetas() {
        datos.etapas.forEach(function (etapa, i) {
            var est = ESTACIONES[i];
            var p = est.lado === 'a' ? iso(est.cx - 0.9, 0.3, 2.9) : iso(est.cx + 1.3, 13.3, 0);
            var g = svg('g', { 'class': 'sim-etiqueta es-' + etapa.estado, transform: 'translate(' + p[0].toFixed(1) + ',' + p[1].toFixed(1) + ')', tabindex: 0, role: 'button' }, capaUI);
            g.setAttribute('aria-label', etapa.titulo + ': ' + TEXTO_ESTADO[etapa.estado]);
            if (est.lado === 'a') svg('line', { x1: 0, y1: 16, x2: 0, y2: ((2.9 - Z_PLAT) * ZH).toFixed(1), 'class': 'sim-etiqueta-poste' }, g);
            var fondo = svg('rect', { x: -60, y: -16, width: 120, height: 32, rx: 16, 'class': 'sim-etiqueta-fondo' }, g);
            svg('circle', { cx: 0, cy: 0, r: 11, 'class': 'sim-etiqueta-icono-fondo' }, g);
            var ico = svgTexto(g, { x: 0, y: 4.2, 'class': 'sim-etiqueta-icono', 'text-anchor': 'middle' }, etapa.icono);
            var titulo = svgTexto(g, { x: 0, y: -1.5, 'class': 'sim-etiqueta-titulo' }, etapa.titulo);
            var estado = svgTexto(g, { x: 0, y: 10, 'class': 'sim-etiqueta-estado' }, (etapa.estado === 'hecho' ? '✓ ' : etapa.estado === 'alerta' ? '⚠ ' : etapa.estado === 'actual' ? '● ' : '') + TEXTO_ESTADO[etapa.estado]);
            g.addEventListener('click', function () { seleccionar(i, true); });
            g.addEventListener('keydown', function (ev) {
                if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); seleccionar(i, true); }
            });
            etiquetas.push({ g: g, fondo: fondo, ico: ico, titulo: titulo, estado: estado, etapa: etapa });
        });
    }

    function ajustarEtiquetas() {
        etiquetas.forEach(function (e) {
            var w = Math.max(anchoTexto(e.titulo, e.etapa.titulo.length * 6.8), anchoTexto(e.estado, 70)) + 48;
            e.fondo.setAttribute('x', (-w / 2).toFixed(1));
            e.fondo.setAttribute('width', w.toFixed(1));
            var izq = -w / 2;
            e.g.querySelector('.sim-etiqueta-icono-fondo').setAttribute('cx', (izq + 18).toFixed(1));
            e.ico.setAttribute('x', (izq + 18).toFixed(1));
            e.titulo.setAttribute('x', (izq + 34).toFixed(1));
            e.estado.setAttribute('x', (izq + 34).toFixed(1));
        });
    }

    function marcarEtapa(i, estado) {
        var e = etiquetas[i];
        if (!e) return;
        e.g.setAttribute('class', 'sim-etiqueta es-' + estado + (i === seleccion ? ' seleccionada' : ''));
        e.estado.textContent = (estado === 'hecho' ? '✓ ' : estado === 'alerta' ? '⚠ ' : estado === 'actual' ? '● ' : '') + TEXTO_ESTADO[estado];
        plataformas[i].g.classList.toggle('es-actual', estado === 'actual' || estado === 'alerta');
        plataformas[i].g.classList.toggle('es-hecho', estado === 'hecho');
        var paso = raiz.querySelectorAll('.sim-paso')[i];
        if (paso) paso.className = 'sim-paso es-' + estado + (i === seleccion ? ' seleccionado' : '');
    }

    // ── Vehículos ─────────────────────────────────────────────────────
    function crearVehiculo(clave, tono, letrero) {
        // Orientado a lo largo del eje y (la calle); la cabina mira hacia -y.
        var g = svg('g', { 'class': 'sim-vehiculo' });
        svg('polygon', { 'class': 'sombra', points: puntos([[-0.55, -1.3, 0], [0.6, -1.3, 0], [0.6, 1.1, 0], [-0.55, 1.1, 0]]) }, g);
        prisma(g, -0.42, -0.5, 0.12, 0.84, 1.5, 0.85, tono);
        prisma(g, -0.42, -1.15, 0.12, 0.84, 0.65, 0.58, tono);
        svg('polygon', { 'class': 'sim-vidrio', points: puntos([[0.425, -1.05, 0.42], [0.425, -0.62, 0.42], [0.425, -0.62, 0.64], [0.425, -1.05, 0.64]]) }, g);
        rotulo(g, 0.43, 0.25, 0.42, 'y', letrero, 'sim-vehiculo-texto');
        [[0.42, -0.85], [0.42, 0.65]].forEach(function (r) {
            var p = iso(r[0], r[1], 0.12);
            svg('ellipse', { cx: p[0].toFixed(1), cy: p[1].toFixed(1), rx: 5, ry: 6.5, 'class': 'sim-rueda' }, g);
        });
        var ent = registrar(g, 0);
        ent.sobre = svg('g', { 'class': 'sim-sobre' }, capaGlobos);
        ent.burbuja = svg('g', { 'class': 'sim-burbuja', transform: 'translate(0,-62)' }, ent.sobre);
        ent.persona = { nombre: letrero };
        entidades[clave] = ent;
        return ent;
    }

    // ── Movimiento ────────────────────────────────────────────────────
    function suavizar(t) { return t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t; }

    function mover(ent, ruta, velocidad, opciones) {
        opciones = opciones || {};
        var miTurno = turno;
        var tramos = [];
        var previo = [ent.x, ent.y, ent.z];
        ruta.forEach(function (p) {
            var destino = [p[0], p[1], p.length > 2 ? p[2] : previo[2]];
            var dx = destino[0] - previo[0];
            var dy = destino[1] - previo[1];
            var dz = destino[2] - previo[2];
            var largo = Math.sqrt(dx * dx + dy * dy + dz * dz);
            if (largo > 0.001) tramos.push({ a: previo, b: destino, largo: largo });
            previo = destino;
        });
        if (!tramos.length) return Promise.resolve();
        if (reducido) {
            var fin = tramos[tramos.length - 1].b;
            colocar(ent, fin[0], fin[1], fin[2]);
            return Promise.resolve();
        }
        ent.el.classList.add('caminando');
        return new Promise(function (resolver) {
            var indice = 0;
            var inicio = null;
            function cuadro(ts) {
                if (miTurno !== turno) { ent.el.classList.remove('caminando'); resolver(); return; }
                if (inicio === null) inicio = ts;
                var tramo = tramos[indice];
                var dur = Math.max(120, (tramo.largo / velocidad) * 1000);
                var t = Math.min(1, (ts - inicio) / dur);
                var k = opciones.suave ? suavizar(t) : t;
                ent.salto = opciones.saltar ? Math.abs(Math.sin(t * Math.PI)) * 0.35 : 0;
                colocar(ent,
                    tramo.a[0] + (tramo.b[0] - tramo.a[0]) * k,
                    tramo.a[1] + (tramo.b[1] - tramo.a[1]) * k,
                    tramo.a[2] + (tramo.b[2] - tramo.a[2]) * k);
                if (opciones.cargando) opciones.cargando();
                if (t >= 1) {
                    indice++;
                    inicio = ts;
                    if (indice >= tramos.length) {
                        ent.salto = 0;
                        ent.el.classList.remove('caminando');
                        resolver();
                        return;
                    }
                }
                requestAnimationFrame(cuadro);
            }
            requestAnimationFrame(cuadro);
        });
    }

    function seguir(portador, dz, dx) {
        return function () {
            colocar(entidades.equipo, portador.x + (dx || 0), portador.y + 0.05, (portador.z || 0) + dz);
        };
    }

    function entrarA(i) {
        return ESTACIONES[i].acceso.concat([ESTACIONES[i].slot]);
    }

    function salirDe(i) {
        return ESTACIONES[i].acceso.slice().reverse();
    }

    function rutaPorVia(desdeEtapa, hastaEtapa) {
        // Puntos de la vía para ir de una estación a otra (siempre hacia adelante).
        var ruta = [];
        var a = ESTACIONES[desdeEtapa];
        var b = ESTACIONES[hastaEtapa];
        ruta.push([a.cx, a.lado === 'a' ? VIA_A : VIA_C, 0]);
        if (a.lado === 'a' && b.lado === 'c') {
            ruta.push([VIA_B, VIA_A, 0]);
            ruta.push([VIA_B, VIA_C, 0]);
        }
        ruta.push([b.cx, b.lado === 'a' ? VIA_A : VIA_C, 0]);
        return ruta;
    }

    // ── Toasts, monedas y confeti ─────────────────────────────────────
    function toast(texto, tipo) {
        var cont = raiz.querySelector('.sim-toasts');
        var t = html('div', 'sim-toast' + (tipo ? ' es-' + tipo : ''), cont, texto);
        setTimeout(function () { t.classList.add('sale'); }, reducido ? 1600 : 2200);
        setTimeout(function () { if (t.parentNode) t.parentNode.removeChild(t); }, reducido ? 1900 : 2600);
    }

    function monedas(x, y, z, cantidad) {
        if (reducido) return;
        var p = iso(x, y, z);
        for (var i = 0; i < cantidad; i++) {
            var m = svg('g', { 'class': 'sim-moneda', transform: 'translate(' + p[0].toFixed(1) + ',' + p[1].toFixed(1) + ')' }, capaUI);
            var c = svg('g', { style: '--dx:' + ((Math.random() - 0.5) * 70).toFixed(0) + 'px;--dy:' + (-40 - Math.random() * 40).toFixed(0) + 'px;animation-delay:' + (i * 0.07).toFixed(2) + 's' }, m);
            svg('circle', { r: 5.5 }, c);
            svgTexto(c, { y: 2.6, 'text-anchor': 'middle' }, '$');
            setTimeout(function (nodo) { return function () { if (nodo.parentNode) nodo.parentNode.removeChild(nodo); }; }(m), 1600);
        }
    }

    function confeti() {
        if (reducido) return;
        var cont = html('div', 'sim-confeti', raiz.querySelector('.sim-escenario'));
        var colores = ['#f97618', '#6d5ef5', '#22c55e', '#facc15', '#ec4899', '#0ea5e9'];
        for (var i = 0; i < 70; i++) {
            var c = html('i', null, cont);
            c.style.left = (Math.random() * 100).toFixed(1) + '%';
            c.style.background = colores[i % colores.length];
            c.style.animationDelay = (Math.random() * 0.6).toFixed(2) + 's';
            c.style.setProperty('--giro', (Math.random() * 720 - 360).toFixed(0) + 'deg');
        }
        setTimeout(function () { if (cont.parentNode) cont.parentNode.removeChild(cont); }, 3200);
    }

    function chispas(activo) {
        var e = ESTACIONES[2];
        var previo = capaUI.querySelector('.sim-chispas');
        if (previo) previo.parentNode.removeChild(previo);
        if (!activo || reducido) return;
        var p = iso(e.slot[0], e.slot[1], e.slot[2] + 0.55);
        var g = svg('g', { 'class': 'sim-chispas', transform: 'translate(' + p[0].toFixed(1) + ',' + p[1].toFixed(1) + ')' }, capaUI);
        for (var i = 0; i < 6; i++) {
            svg('circle', { r: 1.8, style: '--a:' + (i * 60) + 'deg;animation-delay:' + (i * 0.12).toFixed(2) + 's' }, g);
        }
    }

    // ── Estado y diálogos ─────────────────────────────────────────────
    function textoCliente() {
        var alerta = datos.alerta || {};
        if (datos.retirado) return datos.a_domicilio ? '¡Llegó a mi casa! 🎉' : '¡Gracias, Econotec! 🎉';
        if (alerta.tipo === 'cliente') return 'Revisando la cotización 💬';
        if (datos.etapa_actual === 3) {
            if (alerta.tipo === 'saldo') return 'Por pagar: ' + datos.dinero.saldo;
            return '¡Mi equipo está listo! 📲';
        }
        if (datos.etapa_actual === 1) return 'Esperando diagnóstico ⏳';
        return 'Esperando reparación 🛠';
    }

    function textoTecnico() {
        var alerta = datos.alerta || {};
        if (alerta.tipo === 'valor') return 'Falta valor acordado ⚠';
        if (datos.etapa_actual === 1) return 'Diagnosticando… 🔍';
        if (datos.etapa_actual === 2) {
            if (alerta.tipo === 'repuesto') return 'Esperando repuestos 📦';
            if (alerta.tipo === 'cliente') return 'Esperando al cliente 📞';
            if (datos.garantia) return 'Revisando garantía 🛡';
            return 'Reparando… 🔧';
        }
        return '';
    }

    function tonoAlerta() {
        var alerta = datos.alerta || {};
        if (alerta.tipo === 'valor' || alerta.tipo === 'saldo') return 'alerta';
        if (alerta.tipo === 'repuesto' || alerta.tipo === 'cliente') return 'espera';
        return '';
    }

    function textoRobot() {
        if (datos.dinero.sin_cobro) return 'Sin cobro ✓';
        if (datos.dinero.valor_pendiente) return 'Valor por definir';
        if (!datos.dinero.saldo_pendiente) return 'Pagado ✓';
        if (datos.etapa_actual < 3 && datos.dinero.tiene_anticipo) return 'Anticipo ' + datos.dinero.anticipo + ' ✓';
        return 'Por cobrar ' + datos.dinero.saldo;
    }

    function tecnicoUnico() {
        var a = datos.personajes.tecnico;
        var b = datos.personajes.tecnico_reparo;
        return a.nombre_completo === b.nombre_completo;
    }

    function puestoTecnico(etapa) {
        // El técnico trabaja a la izquierda; el equipo queda sobre el escritorio a la derecha.
        var e = ESTACIONES[etapa];
        return [e.cx - 0.9, 1.9, Z_PLAT];
    }

    // Coloca todo en su estado final, sin animación.
    function estadoFinal() {
        var actual = datos.etapa_actual;
        var equipo = entidades.equipo;
        var cliente = entidades.cliente;
        datos.etapas.forEach(function (e, i) { marcarEtapa(i, e.estado); });

        var t = entidades.tecnico;
        var tr = entidades.tecnico_reparo;
        if (tecnicoUnico()) {
            var puesto = puestoTecnico(actual >= 2 ? 2 : 1);
            colocar(t, puesto[0], puesto[1], puesto[2]);
        }
        if (tr) {
            var pr = puestoTecnico(2);
            colocar(tr, pr[0], pr[1], pr[2]);
        }

        enBrazos(datos.retirado);
        if (datos.retirado) {
            colocar(cliente, ESPERA_CLIENTE[0], ESPERA_CLIENTE[1], 0);
            colocar(equipo, ESPERA_CLIENTE[0] + 0.35, ESPERA_CLIENTE[1] + 0.05, 0.42);
            if (entidades.van) colocar(entidades.van, CALLE, ESPERA_CLIENTE[1] + 2.4, 0);
        } else {
            var slot = ESTACIONES[actual].slot;
            colocar(equipo, slot[0], slot[1], slot[2]);
            colocar(cliente, ESPERA_CLIENTE[0], ESPERA_CLIENTE[1], 0);
            if (entidades.van) colocar(entidades.van, CALLE, 11.2, 0);
        }
        if (entidades.camion) colocar(entidades.camion, VIA_B, 6.6, 0);

        var tonoCliente = '';
        if (datos.retirado) tonoCliente = 'exito';
        else if ((datos.alerta || {}).tipo === 'saldo') tonoCliente = 'alerta';
        else if ((datos.alerta || {}).tipo === 'cliente') tonoCliente = 'espera';
        decir(cliente, textoCliente(), tonoCliente);
        var habla = textoTecnico();
        if (habla) decir(actual >= 2 && tr ? tr : t, habla, tonoAlerta());
        decir(entidades.robot, textoRobot(), datos.dinero.saldo_pendiente && datos.etapa_actual >= 3 ? 'alerta' : '');
        if (entidades.camion) decir(entidades.camion, 'Repuestos en camino ⏳', 'espera');
        chispas(actual === 2 && !datos.retirado && !(datos.alerta && datos.alerta.tipo === 'repuesto'));
        actualizarHud(true);
    }

    // ── Recorrido animado ─────────────────────────────────────────────
    function reproducir() {
        turno++;
        var miTurno = turno;
        var actual = datos.etapa_actual;
        var equipo = entidades.equipo;
        var cliente = entidades.cliente;
        var asesora = entidades.asesora;
        var t = entidades.tecnico;
        var vivo = function () { return miTurno === turno; };
        var xpParcial = 0;

        raiz.classList.add('reproduciendo');
        ocultarEquipo(false);
        chispas(false);
        Object.keys(entidades).forEach(function (k) { decir(entidades[k], ''); });
        datos.etapas.forEach(function (e, i) { marcarEtapa(i, 'pendiente'); });
        actualizarHud(false, 0);

        // Punto de partida: cliente en la calle con su equipo en brazos.
        colocar(cliente, CALLE, ESPERA_CLIENTE[1] - 1.2, 0);
        colocar(equipo, CALLE + 0.35, ESPERA_CLIENTE[1] - 1.15, 0.42);
        enBrazos(true);
        if (tecnicoUnico()) {
            var p0 = puestoTecnico(1);
            colocar(t, p0[0], p0[1], p0[2]);
        }
        if (entidades.van) colocar(entidades.van, CALLE, 11.2, 0);
        if (entidades.camion) colocar(entidades.camion, VIA_B, 6.6, 0);

        function llegar(i) {
            if (!vivo()) return Promise.reject('cancelado');
            var etapa = datos.etapas[i];
            var estado = i === actual && !datos.retirado ? etapa.estado : 'hecho';
            if (etapa.clave === 'caja' && etapa.estado === 'alerta') estado = 'alerta';
            marcarEtapa(i, estado);
            if (estado === 'hecho') {
                xpParcial += 20;
                actualizarHud(false, xpParcial);
                toast(etapa.icono + ' ' + etapa.titulo + ' ✓  +20 XP', 'xp');
            }
            return esperar(450);
        }

        function paso(promesa) {
            return promesa.then(function () { if (!vivo()) return Promise.reject('cancelado'); });
        }

        var e0 = ESTACIONES[0];
        var cadena = paso(mover(cliente, [[CALLE, VIA_A], [e0.cx, VIA_A], [e0.cx, 2.75, Z_PLAT]], 4.2, { cargando: seguir(cliente, 0.42, 0.35) }))
            .then(function () {
                decir(asesora, cliente.persona.genero === 'f' ? '¡Bienvenida, ' + cliente.persona.nombre + '!' : '¡Bienvenido, ' + cliente.persona.nombre + '!');
                return esperar(700);
            })
            .then(function () {
                enBrazos(false);
                return paso(mover(equipo, [e0.slot], 3, { saltar: true }));
            })
            .then(function () {
                if (datos.dinero.tiene_anticipo) {
                    monedas(e0.slot[0], e0.slot[1], e0.slot[2] + 0.6, 6);
                    toast('💵 Anticipo ' + datos.dinero.anticipo, 'dinero');
                }
                decir(asesora, '');
                // El cliente regresa a la calle mientras el equipo sigue su camino.
                mover(cliente, [[e0.cx, VIA_A, 0], [CALLE, VIA_A, 0], [ESPERA_CLIENTE[0], ESPERA_CLIENTE[1], 0]], 4.2);
                return llegar(0);
            });

        // Recorrido estación por estación hasta la actual.
        var ultimaEtapa = datos.retirado ? 4 : actual;
        function avanzar(desde, hasta) {
            return function () {
                var origen = ESTACIONES[desde];
                var destino = ESTACIONES[hasta];
                var ruta = salirDe(desde).concat(rutaPorVia(desde, hasta), entrarA(hasta));
                var tareas = [mover(equipo, ruta, 5.2, { saltar: true })];
                if (tecnicoUnico() && hasta === 2) {
                    // El mismo técnico camina del escritorio al banco de trabajo.
                    var pt = puestoTecnico(2);
                    tareas.push(mover(t, [[ESTACIONES[1].cx + 1.7, pt[1], Z_PLAT], [10.3, pt[1], 0], [11.3, pt[1], 0], [11.5, pt[1], Z_PLAT], pt], 3.2));
                }
                return paso(Promise.all(tareas)).then(function () { return llegar(hasta); });
            };
        }
        for (var i = 1; i <= ultimaEtapa; i++) {
            cadena = cadena.then(avanzar(i - 1, i));
        }

        if (datos.retirado) {
            cadena = cadena.then(function () {
                // El equipo pasa por caja y sale por la puerta de salida.
                var s4 = ESTACIONES[4].slot;
                monedas(s4[0], s4[1], s4[2] + 0.6, 8);
                decir(entidades.robot, textoRobot());
                return paso(mover(equipo, salirDe(4).concat(rutaPorVia(4, 5), entrarA(5)), 5.2, { saltar: true }))
                    .then(function () { return llegar(5); });
            }).then(function () {
                var e5 = ESTACIONES[5];
                if (entidades.van) {
                    var van = entidades.van;
                    return paso(mover(equipo, salirDe(5).concat([[e5.cx, VIA_C, 0], [CALLE, VIA_C, 0], [CALLE, 10.6, 1.0]]), 5, { saltar: true }))
                        .then(function () {
                            decir(van, 'Entrega a domicilio 🚚', 'exito');
                            ocultarEquipo(true);
                            return paso(mover(van, [[CALLE, ESPERA_CLIENTE[1] + 2.4, 0]], 3.2, { suave: true }));
                        })
                        .then(function () {
                            colocar(equipo, ESPERA_CLIENTE[0] + 0.35, ESPERA_CLIENTE[1] + 0.05, 0.42);
                            enBrazos(true);
                            ocultarEquipo(false);
                        });
                }
                return paso(mover(cliente, [[CALLE, VIA_C, 0], [e5.cx, VIA_C, 0]], 4.2))
                    .then(function () {
                        return paso(mover(equipo, salirDe(5).concat([[e5.cx + 0.35, VIA_C + 0.05, 0.42]]), 3, { saltar: true }));
                    })
                    .then(function () { enBrazos(true); })
                    .then(function () {
                        return paso(mover(cliente, [[CALLE, VIA_C, 0], [ESPERA_CLIENTE[0], ESPERA_CLIENTE[1], 0]], 4.2, { cargando: seguir(cliente, 0.42, 0.35) }));
                    });
            }).then(function () {
                confeti();
                toast('🏆 ¡Equipo entregado! Misión cumplida', 'logro');
            });
        }

        cadena.then(function () {
            if (!vivo()) return;
            raiz.classList.remove('reproduciendo');
            estadoFinal();
            logrosDesbloqueados();
        }).catch(function () { /* recorrido cancelado */ });
    }

    function ocultarEquipo(oculto) {
        entidades.equipo.el.classList.toggle('oculto', oculto);
        entidades.equipo.sobre.classList.toggle('oculto', oculto);
    }

    // Mientras alguien carga el equipo, su insignia no tapa la cara del personaje.
    function enBrazos(cargado) {
        entidades.equipo.sobre.classList.toggle('en-brazos', cargado);
    }

    function saltarAlFinal() {
        turno++;
        raiz.classList.remove('reproduciendo');
        ocultarEquipo(false);
        estadoFinal();
    }

    function logrosDesbloqueados() {
        var conseguidos = datos.logros.filter(function (l) { return l.ok; });
        conseguidos.slice(-1).forEach(function (l) {
            if (l.clave !== 'entregado') toast('🏅 Logro: ' + l.titulo, 'logro');
        });
        raiz.querySelectorAll('.sim-logro').forEach(function (nodo, i) {
            if (datos.logros[i].ok) nodo.classList.add('brilla');
        });
    }

    // ── HUD (HTML) ────────────────────────────────────────────────────
    function construirModal() {
        raiz = html('div', 'sim-modal');
        raiz.id = 'sim-modal';
        raiz.setAttribute('role', 'dialog');
        raiz.setAttribute('aria-modal', 'true');
        raiz.setAttribute('aria-labelledby', 'sim-titulo');
        raiz.hidden = true;

        var ventana = html('div', 'sim-ventana', raiz);

        // Barra superior.
        var barra = html('header', 'sim-barra', ventana);
        var marca = html('div', 'sim-marca', barra);
        html('span', 'sim-marca-icono', marca, '🎮');
        var tit = html('div', null, marca);
        var h = html('h2', null, tit, 'Simulación del equipo');
        h.id = 'sim-titulo';
        html('small', null, tit, 'Econotec · recorrido en vivo');

        var chip = html('div', 'sim-equipo-chip', barra);
        html('span', 'sim-codigo', chip, datos.codigo);
        var info = html('div', null, chip);
        html('strong', null, info, datos.equipo.tipo_display + ' — ' + datos.equipo.marca + ' ' + datos.equipo.modelo);
        html('small', null, info, datos.estado.texto + (datos.estado.subestado ? ' · ' + datos.estado.subestado : ''));

        var vivo = html('div', 'sim-vivo', barra);
        html('span', 'sim-vivo-punto', vivo);
        html('span', null, vivo, 'En vivo');
        html('time', 'sim-reloj', vivo);

        var cerrar = html('button', 'sim-cerrar', barra, '✕');
        cerrar.type = 'button';
        cerrar.setAttribute('aria-label', 'Cerrar simulación');
        cerrar.addEventListener('click', cerrarModal);

        // Indicadores.
        var kpis = html('div', 'sim-kpis', ventana);
        kpi(kpis, '⏱', 'Días en Econotec', datos.dias_texto, datos.estado.texto, 'k-dias');
        var kPagado = kpi(kpis, '💵', 'Pagado', datos.dinero.pagado, datos.dinero.sin_cobro ? 'Servicio sin cobro' : 'de ' + datos.dinero.total, 'k-pagado');
        var barraPago = html('div', 'sim-barrita', kPagado);
        html('i', null, barraPago).style.width = datos.dinero.pagado_pct + '%';
        kpi(kpis, datos.dinero.saldo_pendiente ? '⚠' : '✅', 'Saldo', datos.dinero.saldo, datos.dinero.saldo_pendiente ? 'Pendiente de cobro' : 'Al día', 'k-saldo' + (datos.dinero.saldo_pendiente ? ' es-alerta' : ' es-ok'));
        var kNivel = kpi(kpis, '⭐', 'Nivel', '', '', 'k-nivel');
        var barraXp = html('div', 'sim-barrita es-xp', kNivel);
        html('i', null, barraXp);

        // Escenario.
        var escenario = html('div', 'sim-escenario', ventana);
        lienzo = svg('svg', { 'class': 'sim-svg', role: 'img', 'aria-label': 'Mapa isométrico del recorrido del equipo ' + datos.codigo, preserveAspectRatio: 'xMidYMid meet' }, escenario);
        var defs = svg('defs', null, lienzo);
        var filtro = svg('filter', { id: 'sim-sombra-suave', x: '-20%', y: '-20%', width: '140%', height: '160%' }, defs);
        svg('feDropShadow', { dx: 0, dy: 3, stdDeviation: 3, 'flood-opacity': 0.18 }, filtro);
        var mundo = svg('g', { 'class': 'sim-mundo' }, lienzo);
        capaSuelo = svg('g', { 'class': 'capa-suelo' }, mundo);
        capaObjetos = svg('g', { 'class': 'capa-objetos' }, mundo);
        capaUI = svg('g', { 'class': 'capa-ui' }, mundo);
        capaGlobos = svg('g', { 'class': 'capa-globos' }, mundo);

        var controles = html('div', 'sim-controles', escenario);
        control(controles, '＋', 'Acercar', function () { zoom(0.8); });
        control(controles, '－', 'Alejar', function () { zoom(1.25); });
        control(controles, '⟲', 'Recentrar', function () { vista = Object.assign({}, vistaInicial); aplicarVista(); });

        var reproduccion = html('div', 'sim-reproduccion', escenario);
        var btnPlay = html('button', 'sim-btn-play', reproduccion, '▶ Repetir recorrido');
        btnPlay.type = 'button';
        btnPlay.addEventListener('click', reproducir);
        var btnSaltar = html('button', 'sim-btn-saltar', reproduccion, '⏭ Saltar');
        btnSaltar.type = 'button';
        btnSaltar.addEventListener('click', saltarAlFinal);

        html('div', 'sim-toasts', escenario);
        if (datos.alerta) {
            var aviso = html('div', 'sim-aviso es-' + datos.alerta.tipo, escenario);
            html('span', null, aviso, '⚠');
            html('span', null, aviso, datos.alerta.texto);
        }

        var panel = html('aside', 'sim-panel', escenario);
        panel.setAttribute('aria-live', 'polite');

        // Línea de etapas y logros.
        var pie = html('footer', 'sim-pie', ventana);
        var linea = html('ol', 'sim-linea', pie);
        datos.etapas.forEach(function (etapa, i) {
            var li = html('li', 'sim-paso es-' + etapa.estado, linea);
            var b = html('button', null, li);
            b.type = 'button';
            html('span', 'sim-paso-icono', b, etapa.icono);
            html('span', 'sim-paso-titulo', b, etapa.titulo);
            b.addEventListener('click', function () { seleccionar(i, true); });
        });
        var logros = html('div', 'sim-logros', pie);
        html('span', 'sim-logros-titulo', logros, 'Logros');
        datos.logros.forEach(function (l) {
            var b = html('span', 'sim-logro' + (l.ok ? ' ok' : ''), logros, l.ok ? l.icono : '🔒');
            b.title = l.titulo + (l.ok ? ' — desbloqueado' : ' — bloqueado');
            b.setAttribute('aria-label', b.title);
        });

        raiz.addEventListener('click', function (ev) { if (ev.target === raiz) cerrarModal(); });
        document.body.appendChild(raiz);
    }

    function kpi(padre, icono, titulo, valor, sub, clase) {
        var c = html('div', 'sim-kpi ' + clase, padre);
        html('span', 'sim-kpi-icono', c, icono);
        var cuerpo = html('div', 'sim-kpi-cuerpo', c);
        html('span', 'sim-kpi-titulo', cuerpo, titulo);
        html('strong', 'sim-kpi-valor', cuerpo, valor);
        html('small', 'sim-kpi-sub', cuerpo, sub);
        return c;
    }

    function control(padre, texto, etiqueta, accion) {
        var b = html('button', null, padre, texto);
        b.type = 'button';
        b.title = etiqueta;
        b.setAttribute('aria-label', etiqueta);
        b.addEventListener('click', accion);
        return b;
    }

    function actualizarHud(final, xp) {
        var valorXp = final ? datos.xp : (xp || 0);
        var nivelIndice = final ? (datos.retirado ? 5 : datos.etapa_actual) : Math.max(0, Math.round(valorXp / 20) - 1);
        var k = raiz.querySelector('.k-nivel');
        k.querySelector('.sim-kpi-valor').textContent = 'Nivel ' + (nivelIndice + 1) + ' · ' + valorXp + ' XP';
        k.querySelector('.sim-kpi-sub').textContent = NIVELES[Math.min(nivelIndice, NIVELES.length - 1)] + ' · ' + (final ? datos.progreso : Math.round(valorXp * 100 / datos.xp_max)) + '% del recorrido';
        k.querySelector('.sim-barrita i').style.width = Math.round(valorXp * 100 / datos.xp_max) + '%';
    }

    // ── Panel lateral ─────────────────────────────────────────────────
    var PERSONAS_ETAPA = {
        recepcion: ['asesora', 'cliente'],
        diagnostico: ['tecnico'],
        taller: ['tecnico_reparo'],
        listo: ['tecnico_reparo'],
        caja: ['robot'],
        salida: ['cliente']
    };

    function avatar(padre, persona, tipo) {
        var s = svg('svg', { viewBox: '-14 -40 28 42', width: 34, height: 50, 'aria-hidden': 'true' }, padre);
        if (tipo === 'robot') dibujarRobot(s);
        else dibujarPersona(s, persona.genero, paleta(persona, tipo));
        return s;
    }

    function tipoDe(clave) {
        if (clave === 'asesora') return 'asesora';
        if (clave === 'tecnico' || clave === 'tecnico_reparo') return 'tecnico';
        if (clave === 'robot') return 'robot';
        return 'cliente';
    }

    function seleccionar(i, desdeUsuario) {
        seleccion = i;
        var etapa = datos.etapas[i];
        var panel = raiz.querySelector('.sim-panel');
        while (panel.firstChild) panel.removeChild(panel.firstChild);

        var cab = html('div', 'sim-panel-cabecera', panel);
        html('span', 'sim-panel-icono', cab, etapa.icono);
        var t = html('div', null, cab);
        html('small', null, t, 'Estación ' + (i + 1) + ' de ' + datos.etapas.length);
        html('h3', null, t, etapa.titulo);
        var x = html('button', 'sim-panel-cerrar', cab, '✕');
        x.type = 'button';
        x.setAttribute('aria-label', 'Ocultar detalle');
        x.addEventListener('click', function () { raiz.classList.remove('panel-abierto'); });

        html('span', 'sim-chip es-' + etapa.estado, panel, TEXTO_ESTADO[etapa.estado]);

        var claves = (PERSONAS_ETAPA[etapa.clave] || []).slice();
        if (etapa.clave === 'listo' && datos.etapa_actual < 3) claves = [];
        if (claves.length) {
            var gente = html('div', 'sim-gente', panel);
            claves.forEach(function (clave) {
                var persona = clave === 'robot'
                    ? { nombre: 'Econobot', nombre_completo: 'Econobot', rol: 'Cajero virtual', genero: 'm' }
                    : datos.personajes[clave];
                if (!persona) return;
                var fila = html('div', 'sim-persona-fila', gente);
                avatar(fila, persona, tipoDe(clave));
                var txt = html('div', null, fila);
                html('strong', null, txt, persona.nombre_completo);
                html('small', null, txt, persona.rol);
            });
        }

        var tabla = html('dl', 'sim-detalles', panel);
        etapa.detalles.forEach(function (fila) {
            var d = html('div', null, tabla);
            html('dt', null, d, fila[0]);
            html('dd', null, d, fila[1]);
        });

        if (datos.alerta && datos.alerta.etapa === i) {
            var a = html('p', 'sim-panel-alerta', panel);
            a.textContent = '⚠ ' + datos.alerta.texto;
        }

        etiquetas.forEach(function (e, k) { e.g.classList.toggle('seleccionada', k === i); });
        plataformas.forEach(function (p, k) { p.g.classList.toggle('seleccionada', k === i); });
        raiz.querySelectorAll('.sim-paso').forEach(function (p, k) { p.classList.toggle('seleccionado', k === i); });
        if (desdeUsuario) raiz.classList.add('panel-abierto');
    }

    // ── Cámara: zoom y arrastre ───────────────────────────────────────
    function aplicarVista() {
        lienzo.setAttribute('viewBox', [vista.x, vista.y, vista.w, vista.h].map(function (n) { return n.toFixed(1); }).join(' '));
    }

    function zoom(factor, cx, cy) {
        var nuevoW = Math.min(vistaInicial.w * 1.6, Math.max(vistaInicial.w * 0.35, vista.w * factor));
        var f = nuevoW / vista.w;
        if (cx === undefined) { cx = vista.x + vista.w / 2; cy = vista.y + vista.h / 2; }
        vista.x = cx - (cx - vista.x) * f;
        vista.y = cy - (cy - vista.y) * f;
        vista.w *= f;
        vista.h *= f;
        aplicarVista();
    }

    function puntoSvg(ev) {
        var r = lienzo.getBoundingClientRect();
        var escala = Math.max(vista.w / r.width, vista.h / r.height);
        var offX = (r.width * escala - vista.w) / 2;
        var offY = (r.height * escala - vista.h) / 2;
        return [vista.x - offX + (ev.clientX - r.left) * escala, vista.y - offY + (ev.clientY - r.top) * escala, escala];
    }

    function activarCamara() {
        var arrastre = null;
        lienzo.addEventListener('wheel', function (ev) {
            ev.preventDefault();
            var p = puntoSvg(ev);
            zoom(ev.deltaY > 0 ? 1.1 : 0.9, p[0], p[1]);
        }, { passive: false });
        lienzo.addEventListener('pointerdown', function (ev) {
            if (ev.button !== 0) return;
            arrastre = { x: ev.clientX, y: ev.clientY, vx: vista.x, vy: vista.y, escala: puntoSvg(ev)[2], movio: false, id: ev.pointerId };
        });
        lienzo.addEventListener('pointermove', function (ev) {
            if (!arrastre) return;
            var dx = ev.clientX - arrastre.x;
            var dy = ev.clientY - arrastre.y;
            if (!arrastre.movio && Math.abs(dx) + Math.abs(dy) > 5) {
                arrastre.movio = true;
                lienzo.setPointerCapture(arrastre.id);
                lienzo.classList.add('arrastrando');
            }
            if (!arrastre.movio) return;
            vista.x = arrastre.vx - dx * arrastre.escala;
            vista.y = arrastre.vy - dy * arrastre.escala;
            aplicarVista();
        });
        function soltar() {
            arrastre = null;
            lienzo.classList.remove('arrastrando');
        }
        lienzo.addEventListener('pointerup', soltar);
        lienzo.addEventListener('pointercancel', soltar);
    }

    // ── Construcción y apertura ───────────────────────────────────────
    function construirMundo() {
        construirSuelo();
        construirEstaciones();

        crearPersonaje('asesora', datos.personajes.asesora, 'asesora', ESTACIONES[0].cx - 0.8, 1.25, Z_PLAT);
        var pt = puestoTecnico(1);
        crearPersonaje('tecnico', datos.personajes.tecnico, 'tecnico', pt[0], pt[1], pt[2]);
        if (!tecnicoUnico()) {
            var pr = puestoTecnico(2);
            crearPersonaje('tecnico_reparo', datos.personajes.tecnico_reparo, 'tecnico', pr[0], pr[1], pr[2]);
        }
        crearPersonaje('robot', { nombre: 'Econobot', nombre_completo: 'Econobot', genero: 'm' }, 'robot', ESTACIONES[4].cx - 0.4, 11.05, Z_PLAT);
        crearPersonaje('cliente', datos.personajes.cliente, 'cliente', ESPERA_CLIENTE[0], ESPERA_CLIENTE[1], 0);
        crearEquipo();
        if (datos.a_domicilio) crearVehiculo('van', 't-van', 'ECONOTEC');
        if (datos.alerta && datos.alerta.tipo === 'repuesto') crearVehiculo('camion', 't-camion', 'REPUESTOS');

        Object.keys(entidades).forEach(function (k) {
            var e = entidades[k];
            colocar(e, e.x || 0, e.y || 0, e.z || 0);
        });
        ordenarTodo();
        crearEtiquetas();

        encuadrar();
        activarCamara();
    }

    // Ajusta la cámara para que el mapa quepa junto al panel lateral.
    function encuadrar() {
        var r = lienzo.getBoundingClientRect();
        if (!r.width || !r.height) return;
        var ancho = window.innerWidth > 860;
        var panel = raiz.querySelector('.sim-panel');
        var reservaDer = window.innerWidth > 1100 && panel ? panel.offsetWidth + 24 : 0;
        var reservaIzq = ancho ? 62 : 0;
        var dispW = Math.max(200, r.width - reservaDer - reservaIzq);
        var dispH = r.height - (ancho ? 0 : 48);
        var s = Math.min(dispW / MUNDO.w, dispH / MUNDO.h);
        var ox = reservaIzq + (dispW - MUNDO.w * s) / 2;
        var oy = (dispH - MUNDO.h * s) / 2;
        vistaInicial = { x: MUNDO.x - ox / s, y: MUNDO.y - oy / s, w: r.width / s, h: r.height / s };
        vista = Object.assign({}, vistaInicial);
        aplicarVista();
    }

    function ajustarTextos() {
        Object.keys(entidades).forEach(function (k) {
            if (entidades[k].placa) ajustarPlaca(entidades[k]);
        });
        ajustarEtiquetas();
        var eq = entidades.equipo;
        var w = anchoTexto(eq.chip.texto, datos.codigo.length * 7) + 16;
        eq.chip.fondo.setAttribute('width', w.toFixed(1));
    }

    function actualizarReloj() {
        var r = raiz.querySelector('.sim-reloj');
        var ahora = new Date();
        r.textContent = String(ahora.getHours()).padStart(2, '0') + ':' + String(ahora.getMinutes()).padStart(2, '0');
    }

    var focoPrevio = null;

    function abrirModal() {
        if (!raiz) construirModal();
        focoPrevio = document.activeElement;
        raiz.hidden = false;
        document.documentElement.classList.add('sim-bloqueo');
        requestAnimationFrame(function () { raiz.classList.add('visible'); });
        if (!construido) {
            construirMundo();
            ajustarTextos();
            construido = true;
        }
        seleccionar(datos.etapa_actual, false);
        encuadrar();
        actualizarReloj();
        relojId = setInterval(actualizarReloj, 30000);
        raiz.querySelector('.sim-cerrar').focus();
        if (reducido) estadoFinal();
        else reproducir();
    }

    function cerrarModal() {
        if (!raiz || raiz.hidden) return;
        turno++;
        raiz.classList.remove('visible', 'panel-abierto', 'reproduciendo');
        document.documentElement.classList.remove('sim-bloqueo');
        clearInterval(relojId);
        setTimeout(function () { raiz.hidden = true; }, reducido ? 0 : 220);
        if (focoPrevio && focoPrevio.focus) focoPrevio.focus();
    }

    boton.addEventListener('click', abrirModal);
    window.addEventListener('resize', function () {
        if (raiz && !raiz.hidden && construido) encuadrar();
    });
    document.addEventListener('keydown', function (ev) {
        if (ev.key === 'Escape' && raiz && !raiz.hidden) cerrarModal();
    });
})();
