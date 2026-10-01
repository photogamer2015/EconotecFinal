/*
 * Retención en facturas (misma fórmula que econotec/retencion.py).
 *
 *   subtotal = neto ÷ 0,90 · IVA = subtotal × 15 % · total = subtotal + IVA
 *   recibe   = total − retención del IVA (100 %) − retención de renta (10 %)
 *
 * Todo se calcula en centavos enteros con redondeo "mitad hacia arriba",
 * igual que Decimal ROUND_HALF_UP en el servidor.
 */
(function () {
    'use strict';

    function centavos(valor) {
        var numero = parseFloat(String(valor == null ? '' : valor).replace(',', '.'));
        return Number.isFinite(numero) ? Math.round(numero * 100) : 0;
    }

    // a ÷ b redondeado mitad hacia arriba (a ≥ 0, b > 0, enteros).
    function dividir(a, b) {
        return Math.floor((2 * a + b) / (2 * b));
    }

    function dinero(c) {
        var negativo = c < 0;
        c = Math.abs(c);
        var entero = String(Math.floor(c / 100)).replace(/\B(?=(\d{3})+(?!\d))/g, '.');
        var decimales = String(c % 100).padStart(2, '0');
        return (negativo ? '-$' : '$') + entero + ',' + decimales;
    }

    // Lee montos mostrados en pantalla: "$1.234,56", "$35.00", "35,00".
    function numeroDesdeTexto(texto) {
        var limpio = String(texto || '').replace(/[^0-9.,-]/g, '');
        var corte = Math.max(limpio.lastIndexOf(','), limpio.lastIndexOf('.'));
        if (corte < 0) return parseFloat(limpio) || 0;
        var entero = limpio.slice(0, corte).replace(/[.,]/g, '');
        return parseFloat(entero + '.' + limpio.slice(corte + 1)) || 0;
    }

    function totalDesdeNeto(netoC, pct) {
        if (netoC <= 0) return 0;
        var factor = 10000 + pct.iva * 100 - pct.iva * pct.retIva - pct.renta * 100;
        var subtotalC = dividir(netoC * 10000, factor);
        return subtotalC + dividir(subtotalC * pct.iva, 100);
    }

    function desglose(totalC, pct) {
        totalC = Math.max(totalC, 0);
        var subtotalC = dividir(totalC * 100, 100 + pct.iva);
        var ivaC = totalC - subtotalC;
        var ivaRetenidoC = dividir(ivaC * pct.retIva, 100);
        var rentaC = dividir(subtotalC * pct.renta, 100);
        return {
            subtotal: subtotalC,
            iva: ivaC,
            total: totalC,
            ivaRetenido: ivaRetenidoC,
            renta: rentaC,
            recibido: totalC - ivaRetenidoC - rentaC
        };
    }

    /*
     * Conecta un bloque `[data-retencion]`.
     *   opciones.factura      select de "¿Factura con datos?"
     *   opciones.obtenerBase  función que devuelve el saldo / monto base
     *   opciones.alCambiar    se llama después de cada actualización
     */
    function montar(raiz, opciones) {
        if (!raiz) return null;
        opciones = opciones || {};
        var aplica = raiz.querySelector('[data-ret-aplica]');
        var valor = raiz.querySelector('[data-ret-valor]');
        var panel = raiz.querySelector('[data-ret-panel]');
        var recalcular = raiz.querySelector('[data-ret-recalcular]');
        var factura = opciones.factura || null;
        if (!aplica || !valor || !panel) return null;

        var pct = {
            iva: parseInt(raiz.dataset.iva, 10) || 0,
            retIva: parseInt(raiz.dataset.retencionIva, 10) || 0,
            renta: parseInt(raiz.dataset.retencionRenta, 10) || 0
        };

        function baseC() {
            var base = opciones.obtenerBase ? opciones.obtenerBase() : 0;
            return Math.max(centavos(base), 0);
        }

        function calculadoC() {
            return totalDesdeNeto(baseC(), pct);
        }

        // Un valor guardado distinto del calculado se respeta como edición manual.
        var manual = valor.value.trim() !== '' && centavos(valor.value) !== calculadoC();

        function pintarCelda(nombre, texto) {
            var celda = raiz.querySelector('[data-ret-' + nombre + ']');
            if (celda) celda.textContent = texto;
        }

        function actualizar() {
            var conFactura = !factura || factura.value === 'si';
            var activa = conFactura && aplica.value === 'si';
            raiz.style.display = conFactura ? '' : 'none';
            panel.style.display = activa ? '' : 'none';
            // Si la pantalla oculta toda la sección de factura, no se exige el valor.
            var seccionVisible = !raiz.parentElement || raiz.parentElement.getClientRects().length > 0;
            valor.required = activa && seccionVisible;
            if (!activa) valor.setCustomValidity('');

            if (activa) {
                if (!manual) valor.value = (calculadoC() / 100).toFixed(2);
                var d = desglose(centavos(valor.value), pct);
                pintarCelda('base', dinero(baseC()));
                pintarCelda('subtotal', dinero(d.subtotal));
                pintarCelda('iva', dinero(d.iva));
                pintarCelda('total', dinero(d.total));
                pintarCelda('iva-retenido', '-' + dinero(d.ivaRetenido));
                pintarCelda('renta', '-' + dinero(d.renta));
                pintarCelda('recibido', dinero(d.recibido));
                valor.setCustomValidity(
                    !valor.required || centavos(valor.value) > 0
                        ? ''
                        : 'Ingresa el valor con retención (mayor a $0.00).'
                );
                if (recalcular) {
                    var editado = manual && centavos(valor.value) !== calculadoC();
                    recalcular.style.display = editado ? '' : 'none';
                }
            }
            if (opciones.alCambiar) opciones.alCambiar();
        }

        valor.addEventListener('input', function () {
            manual = true;
            actualizar();
        });
        aplica.addEventListener('change', function () {
            if (aplica.value === 'si' && valor.value.trim() === '') manual = false;
            actualizar();
        });
        if (recalcular) {
            recalcular.addEventListener('click', function () {
                manual = false;
                actualizar();
                valor.focus();
            });
        }
        if (factura) factura.addEventListener('change', actualizar);

        // Cualquier cambio del formulario puede mover el saldo o el monto base.
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
        numeroDesdeTexto: numeroDesdeTexto,
        totalDesdeNeto: totalDesdeNeto,
        desglose: desglose,
        montar: montar
    };
})();
