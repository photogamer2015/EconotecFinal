/* Notificaciones push de Econotec en este celular o computadora.
 *
 * - Registra el service worker (/service-worker.js).
 * - Si ya hay permiso, mantiene la suscripción al día en el servidor.
 * - Si aún no se ha pedido, muestra un aviso con el botón «Activar».
 * - En iPhone, explica que primero hay que añadir Econotec a la pantalla de inicio.
 */
(function () {
    'use strict';

    const config = document.getElementById('push-config');
    if (!config) return;
    const URLS = {
        sw: config.dataset.sw,
        clave: config.dataset.clave,
        suscribir: config.dataset.suscribir,
        desuscribir: config.dataset.desuscribir,
        probar: config.dataset.probar,
    };
    const CSRF = config.dataset.csrf;
    const CLAVE_OCULTO = 'econotec-push-aviso-oculto';
    const CLAVE_SYNC = 'econotec-push-sincronizada';
    const USUARIO = config.dataset.usuario || '';

    const banner = document.getElementById('push-banner');
    const botonesNav = document.querySelectorAll('[data-push-toggle]');

    const ua = navigator.userAgent || '';
    const esIOS = /iPad|iPhone|iPod/.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
    const instalada = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
    const soporta = 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;

    function base64ABytes(texto) {
        const relleno = '='.repeat((4 - (texto.length % 4)) % 4);
        const crudo = atob((texto + relleno).replace(/-/g, '+').replace(/_/g, '/'));
        return Uint8Array.from(crudo, (c) => c.charCodeAt(0));
    }

    function mismosBytes(a, b) {
        if (!a || !b) return false;
        const x = new Uint8Array(a);
        if (x.length !== b.length) return false;
        return x.every((v, i) => v === b[i]);
    }

    function enviar(url, datos) {
        return fetch(url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF },
            body: JSON.stringify(datos || {}),
        }).then((r) => r.json().catch(() => ({ ok: r.ok })));
    }

    let registro = null;
    let clave = null;

    async function obtenerClave() {
        if (clave) return clave;
        const r = await fetch(URLS.clave, { credentials: 'same-origin' });
        const datos = await r.json();
        clave = base64ABytes(datos.clave);
        return clave;
    }

    function marcaDe(sub) { return USUARIO + '|' + sub.endpoint; }

    function yaSincronizada(sub) {
        try { return sessionStorage.getItem(CLAVE_SYNC) === marcaDe(sub); } catch (e) { return false; }
    }

    async function suscribir(forzar) {
        let sub = await registro.pushManager.getSubscription();
        // Ya se envió al servidor en esta pestaña: no repetir en cada página.
        if (sub && !forzar && yaSincronizada(sub)) return sub;

        const claveServidor = await obtenerClave();
        if (sub && !mismosBytes(sub.options && sub.options.applicationServerKey, claveServidor)) {
            await sub.unsubscribe();
            sub = null;
        }
        if (!sub) {
            sub = await registro.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: claveServidor });
        }
        const r = await enviar(URLS.suscribir, sub.toJSON());
        if (!r.ok) throw new Error('El servidor no guardó la suscripción');
        try { sessionStorage.setItem(CLAVE_SYNC, marcaDe(sub)); } catch (e) { /* sin almacenamiento */ }
        return sub;
    }

    async function desuscribir() {
        const sub = registro && await registro.pushManager.getSubscription();
        if (sub) {
            await enviar(URLS.desuscribir, { endpoint: sub.endpoint });
            await sub.unsubscribe();
        }
    }

    function mostrarBanner(modo) {
        if (!banner) return;
        banner.dataset.modo = modo;
        banner.hidden = false;
    }

    function ocultarBanner(recordar) {
        if (!banner) return;
        banner.hidden = true;
        if (recordar) {
            try { localStorage.setItem(CLAVE_OCULTO, String(Date.now())); } catch (e) { /* sin almacenamiento */ }
        }
    }

    function bannerOcultoReciente() {
        try {
            const t = Number(localStorage.getItem(CLAVE_OCULTO) || 0);
            return t && (Date.now() - t) < 3 * 24 * 60 * 60 * 1000; // vuelve a salir a los 3 días
        } catch (e) { return false; }
    }

    function pintarNav(estado) {
        const textos = {
            activas: '🔔 Notificaciones: activadas',
            apagadas: '🔕 Activar notificaciones',
            bloqueadas: '🚫 Notificaciones bloqueadas',
            ios: '📲 Activar notificaciones',
        };
        const texto = textos[estado] || textos.apagadas;
        const espacio = texto.indexOf(' ');
        botonesNav.forEach((b) => {
            b.hidden = false;
            b.dataset.estado = estado;
            b.title = texto.slice(espacio + 1);
            const icono = b.querySelector('.push-nav-icono');
            const etiqueta = b.querySelector('.push-nav-texto');
            if (icono) icono.textContent = texto.slice(0, espacio);
            if (etiqueta) etiqueta.textContent = texto.slice(espacio + 1);
        });
    }

    async function estadoActual() {
        if (Notification.permission === 'denied') return 'bloqueadas';
        if (Notification.permission !== 'granted') return 'apagadas';
        const sub = await registro.pushManager.getSubscription();
        return sub ? 'activas' : 'apagadas';
    }

    function aviso(titulo, texto, icono) {
        if (window.Swal) {
            window.Swal.fire({ title: titulo, html: texto, icon: icono || 'info', confirmButtonColor: '#f97618' });
        } else {
            window.alert(titulo + '\n\n' + texto.replace(/<[^>]+>/g, ''));
        }
    }

    function explicarIOS() {
        aviso(
            'Notificaciones en iPhone',
            '<div style="text-align:left">' +
            'En iPhone las notificaciones solo funcionan con Econotec instalado (iOS 16.4 o más nuevo):<br><br>' +
            '1. Toca <b>Compartir</b> (el cuadrado con la flecha ↑):<br>' +
            '&nbsp;&nbsp;• En <b>Safari</b>: está en la barra de abajo.<br>' +
            '&nbsp;&nbsp;• En <b>Chrome</b>: está junto a la dirección, arriba a la derecha.<br>' +
            '2. Elige <b>Añadir a pantalla de inicio</b> (si no aparece, desliza hacia abajo en la lista).<br>' +
            '3. Abre Econotec desde el ícono nuevo y toca <b>Activar notificaciones</b>.' +
            '</div>',
        );
    }

    function explicarBloqueadas() {
        aviso(
            'Notificaciones bloqueadas',
            'Este navegador tiene bloqueados los avisos de Econotec.<br><br>' +
            'Toca el candado 🔒 junto a la dirección (o abre la configuración del navegador / de la app), ' +
            'busca <b>Notificaciones</b>, elige <b>Permitir</b> y vuelve a cargar la página.',
            'warning',
        );
    }

    async function activar() {
        try {
            const permiso = await Notification.requestPermission();
            if (permiso !== 'granted') {
                pintarNav(permiso === 'denied' ? 'bloqueadas' : 'apagadas');
                ocultarBanner(true);
                if (permiso === 'denied') explicarBloqueadas();
                return;
            }
            await suscribir(true);
            pintarNav('activas');
            ocultarBanner(false);
            const r = await enviar(URLS.probar);
            if (!r.ok) {
                aviso('Notificaciones activadas', 'Quedó activado, pero la notificación de prueba no salió. Inténtalo de nuevo en unos minutos.', 'warning');
            }
        } catch (e) {
            aviso('No se pudo activar', 'Hubo un problema al activar las notificaciones en este dispositivo. Vuelve a cargar la página e inténtalo otra vez.', 'error');
        }
    }

    async function alTocarNav(evento) {
        evento.preventDefault();
        const estado = evento.currentTarget.dataset.estado;
        if (estado === 'ios') return explicarIOS();
        if (estado === 'bloqueadas') return explicarBloqueadas();
        if (estado === 'activas') {
            const quiere = window.Swal
                ? (await window.Swal.fire({
                    title: 'Notificaciones activadas',
                    text: 'Este dispositivo recibe los avisos de Econotec.',
                    icon: 'success',
                    showDenyButton: true,
                    confirmButtonText: 'Enviar una de prueba',
                    denyButtonText: 'Desactivar en este dispositivo',
                    confirmButtonColor: '#f97618',
                }))
                : { isDenied: window.confirm('¿Desactivar las notificaciones en este dispositivo?') };
            if (quiere.isDenied) {
                await desuscribir();
                try { sessionStorage.removeItem(CLAVE_SYNC); } catch (e) { /* sin almacenamiento */ }
                pintarNav('apagadas');
            } else if (quiere.isConfirmed) {
                await enviar(URLS.probar);
            }
            return;
        }
        await activar();
    }

    botonesNav.forEach((b) => b.addEventListener('click', alTocarNav));
    if (banner) {
        const btnActivar = banner.querySelector('[data-push-activar]');
        const btnCerrar = banner.querySelector('[data-push-cerrar]');
        if (btnActivar) {
            btnActivar.addEventListener('click', () => {
                if (banner.dataset.modo === 'ios') { ocultarBanner(true); explicarIOS(); } else { activar(); }
            });
        }
        if (btnCerrar) btnCerrar.addEventListener('click', () => ocultarBanner(true));
    }

    async function iniciar() {
        if (!soporta) {
            // iPhone en Safari normal: hay que instalar la app primero.
            if (esIOS && !instalada) {
                pintarNav('ios');
                if (!bannerOcultoReciente()) mostrarBanner('ios');
            }
            return;
        }
        try {
            registro = await navigator.serviceWorker.register(URLS.sw, { scope: '/' });
            await navigator.serviceWorker.ready;
        } catch (e) {
            return;
        }
        const estado = await estadoActual();
        pintarNav(estado);
        if (Notification.permission === 'granted') {
            // Mantener la suscripción al día (por si cambió o es otro usuario).
            try { await suscribir(); pintarNav('activas'); } catch (e) { /* se reintenta en la próxima página */ }
        } else if (Notification.permission === 'default' && !bannerOcultoReciente()) {
            mostrarBanner('activar');
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', iniciar);
    } else {
        iniciar();
    }
})();
