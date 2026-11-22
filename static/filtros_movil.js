/* En el celular, los formularios de filtros largos (lista de equipos, salidas…)
 * muestran solo el buscador y un botón «Filtros»; el resto se despliega al tocarlo. */
(function () {
    'use strict';
    const MINIMO_CAMPOS = 4;

    function activo(el) {
        if (el.matches('select')) return el.selectedIndex > 0;
        const campos = el.matches('input') ? [el] : [...el.querySelectorAll('input[name], select[name]')];
        return campos.some((c) => (c.matches('select') ? c.selectedIndex > 0 : (c.value || '').trim() !== ''));
    }

    function preparar(form) {
        if (form.dataset.filtrosMovil) return;
        const hijos = [...form.children].filter((el) => !el.matches('input[type="hidden"]'));
        const buscador = hijos.find((el) => el.matches('input[type="text"], input[type="search"], input:not([type])'));
        const enviar = hijos.filter((el) => el.matches('button[type="submit"], input[type="submit"]'));
        const extras = hijos.filter((el) => el !== buscador && !enviar.includes(el));
        if (extras.length < MINIMO_CAMPOS) return;

        form.dataset.filtrosMovil = '1';
        form.classList.add('filtros-plegables');
        extras.forEach((el) => el.classList.add('filtro-extra'));

        const activos = extras.filter(activo).length;
        const boton = document.createElement('button');
        boton.type = 'button';
        boton.className = 'btn btn-secondary filtros-movil-toggle';
        boton.setAttribute('aria-expanded', 'false');
        boton.textContent = activos ? `⚙️ Filtros (${activos} activo${activos === 1 ? '' : 's'})` : '⚙️ Más filtros';
        boton.addEventListener('click', () => {
            const abierto = form.classList.toggle('filtros-abiertos');
            boton.setAttribute('aria-expanded', String(abierto));
        });
        (buscador || form.firstElementChild).insertAdjacentElement(buscador ? 'afterend' : 'beforebegin', boton);
    }

    function iniciar() {
        document.querySelectorAll('.toolbar form[method="get"], .toolbar form[method="GET"]').forEach(preparar);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', iniciar);
    } else {
        iniciar();
    }
})();
