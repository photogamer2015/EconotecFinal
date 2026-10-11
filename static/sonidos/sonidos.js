/*
 * Reproduce una sola vez el clip corto (tema de Tetris) que dejó el servidor
 * al registrar un equipo. El clip ya viene recortado, con volumen bajo y
 * desvanecido, así que aquí solo se le da play.
 *
 * Si el navegador bloquea el audio automático (Safari, Firefox), suena con la
 * primera interacción del usuario, siempre que sea poco después de cargar.
 */
(function () {
    var script = document.currentScript;
    var src = script && script.getAttribute('data-src');
    if (!src || typeof Audio === 'undefined') return;

    var ESPERA_MAXIMA_MS = 30000;
    var EVENTOS = ['pointerdown', 'pointerup', 'touchend', 'keydown', 'click'];
    var inicio = Date.now();
    var sonando = false;

    var audio = new Audio(src);
    audio.preload = 'auto';

    function dejarDeEsperar() {
        EVENTOS.forEach(function (evento) {
            document.removeEventListener(evento, intentar, true);
        });
    }

    function intentar() {
        if (sonando) return;
        if (Date.now() - inicio > ESPERA_MAXIMA_MS) {
            dejarDeEsperar();
            return;
        }
        var promesa;
        try {
            promesa = audio.play();
        } catch (e) {
            return;
        }
        if (promesa && typeof promesa.then === 'function') {
            promesa.then(function () {
                sonando = true;
                dejarDeEsperar();
            }).catch(function () {
                // Bloqueado por el navegador: se reintenta con la próxima interacción.
            });
        } else {
            sonando = true;
            dejarDeEsperar();
        }
    }

    // Si el archivo no carga, no seguir escuchando clics para nada.
    audio.addEventListener('error', dejarDeEsperar);

    EVENTOS.forEach(function (evento) {
        document.addEventListener(evento, intentar, true);
    });
    intentar();
})();
