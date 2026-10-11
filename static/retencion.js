/*
 * Retención en facturas: el valor con retención (total de la factura) se
 * escribe a mano. Aquí solo se muestra el campo cuando aplica y se exige
 * que sea mayor a $0.00; el desglose lo arma el servidor desde ese total.
 */
(function () {
    'use strict';

    function centavos(valor) {
        var numero = parseFloat(String(valor == null ? '' : valor).replace(',', '.'));
        return Number.isFinite(numero) ? Math.round(numero * 100) : 0;
    }

    /*
     * Conecta un bloque `[data-retencion]`.
     *   opciones.factura      select de "¿Factura con datos?"
     *   opciones.alCambiar    se llama después de cada actualización
     */
    function montar(raiz, opciones) {
        if (!raiz) return null;
        opciones = opciones || {};
        var aplica = raiz.querySelector('[data-ret-aplica]');
        var valor = raiz.querySelector('[data-ret-valor]');
        var panel = raiz.querySelector('[data-ret-panel]');
        var factura = opciones.factura || null;
        if (!aplica || !valor || !panel) return null;

        function actualizar() {
            var conFactura = !factura || factura.value === 'si';
            var activa = conFactura && aplica.value === 'si';
            raiz.style.display = conFactura ? '' : 'none';
            panel.style.display = activa ? '' : 'none';
            // Si la pantalla oculta toda la sección de factura, no se exige el valor.
            var seccionVisible = !raiz.parentElement || raiz.parentElement.getClientRects().length > 0;
            valor.required = activa && seccionVisible;
            valor.setCustomValidity(
                !valor.required || centavos(valor.value) > 0
                    ? ''
                    : 'Ingresa el valor con retención (mayor a $0.00).'
            );
            if (opciones.alCambiar) opciones.alCambiar();
        }

        valor.addEventListener('input', actualizar);
        aplica.addEventListener('change', actualizar);
        if (factura) factura.addEventListener('change', actualizar);

        // Otros campos del formulario pueden mostrar u ocultar la sección de factura.
        var formulario = raiz.closest('form');
        if (formulario) {
            ['input', 'change'].forEach(function (tipo) {
                formulario.addEventListener(tipo, function (evento) {
                    if (!raiz.contains(evento.target)) actualizar();
                });
            });
        }

        actualizar();
        return { actualizar: actualizar };
    }

    window.EconotecRetencion = {
        centavos: centavos,
        montar: montar
    };
})();
