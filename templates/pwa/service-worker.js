/* Econotec: recibe las notificaciones push y abre el aviso al tocarlas.
   No guarda páginas en caché: el sistema siempre se carga del servidor. */
const ICONO = '{{ icono|escapejs }}';

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));

self.addEventListener('push', (event) => {
    let datos = {};
    if (event.data) {
        try { datos = event.data.json(); } catch (e) { datos = { cuerpo: event.data.text() }; }
    }
    const opciones = {
        body: datos.cuerpo || '',
        icon: ICONO,
        data: { url: datos.url || '/bienvenida/' },
        vibrate: [200, 100, 200],
    };
    if (datos.etiqueta) {
        opciones.tag = datos.etiqueta;
        opciones.renotify = true;
    }
    event.waitUntil(self.registration.showNotification(datos.titulo || 'Econotec', opciones));
});

self.addEventListener('notificationclick', (event) => {
    event.notification.close();
    const destino = new URL((event.notification.data && event.notification.data.url) || '/bienvenida/', self.location.origin).href;
    event.waitUntil((async () => {
        const ventanas = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
        for (const ventana of ventanas) {
            if (ventana.url.startsWith(self.location.origin) && 'focus' in ventana) {
                try {
                    await ventana.focus();
                    await ventana.navigate(destino);
                    return;
                } catch (e) { /* si no se puede reutilizar, se abre una nueva */ }
            }
        }
        await self.clients.openWindow(destino);
    })());
});
