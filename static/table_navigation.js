(function () {
    'use strict';

    const TABLE_SELECTOR = 'table:not([data-table-navigation="off"])';
    const HOST_SELECTOR = '.table-wrap, .table-responsive, [class*="table-wrap"]';
    const enhancedTables = new WeakSet();
    const resizeObservers = new WeakMap();
    const tableRefreshers = [];
    const refreshersByTable = new WeakMap();
    let tableSequence = 0;

    function normalizeText(value) {
        return (value || '')
            .normalize('NFD')
            .replace(/[\u0300-\u036f]/g, '')
            .replace(/\s+/g, ' ')
            .trim()
            .toLowerCase();
    }

    function directTableForHost(host) {
        return Array.prototype.find.call(host.children, function (child) {
            return child.tagName === 'TABLE';
        });
    }

    function findScrollHost(table) {
        let host = table.closest(HOST_SELECTOR);
        if (host && (!host.dataset.tableNavigationOwner || directTableForHost(host) === table)) {
            return host;
        }

        let parent = table.parentElement;
        for (let depth = 0; parent && depth < 4; depth += 1, parent = parent.parentElement) {
            const style = window.getComputedStyle(parent);
            if (style.overflowX === 'auto' || style.overflowX === 'scroll') {
                if (!parent.dataset.tableNavigationOwner) return parent;
                break;
            }
        }

        host = document.createElement('div');
        host.className = 'table-scroll-viewport table-navigation-created';
        table.parentNode.insertBefore(host, table);
        host.appendChild(table);
        return host;
    }

    function getHeaders(table) {
        const headerRow = table.tHead && table.tHead.rows.length
            ? table.tHead.rows[table.tHead.rows.length - 1]
            : null;
        return headerRow ? Array.prototype.slice.call(headerRow.cells) : [];
    }

    function findContextColumn(table, headers) {
        const configured = table.getAttribute('data-context-column');
        if (configured !== null && configured !== '') {
            const configuredIndex = Number(configured);
            if (Number.isInteger(configuredIndex) && configuredIndex >= 0 && configuredIndex < headers.length) {
                return configuredIndex;
            }
        }

        const labels = headers.map(function (header) {
            return normalizeText(header.textContent);
        });
        const priorities = [
            /\b(cliente|nombres?|persona|usuario|tecnico|asesor|vendedor|responsable|proveedor)\b/,
            /\b(codigo|numero|recibo|venta|cedula|ruc)\b|^n[.\u00ba\u00b0]?$/,
            /\b(equipo|producto|concepto|titulo|actividad|categoria|modelo)\b/
        ];

        for (const pattern of priorities) {
            const match = labels.findIndex(function (label) { return pattern.test(label); });
            if (match !== -1) return match;
        }
        return headers.length ? 0 : -1;
    }

    function isTransparentColor(color) {
        return !color || color === 'transparent' || color === 'rgba(0, 0, 0, 0)';
    }

    function getPaintedColor(cell, property, fallback) {
        let color = window.getComputedStyle(cell)[property];
        if (isTransparentColor(color) && cell.parentElement) {
            color = window.getComputedStyle(cell.parentElement)[property];
        }
        return isTransparentColor(color) ? fallback : color;
    }

    function markContextColumn(table, headers) {
        Array.prototype.forEach.call(table.querySelectorAll('.table-context-cell'), function (cell) {
            cell.classList.remove('table-context-cell');
        });

        const columnIndex = findContextColumn(table, headers);
        if (columnIndex < 0) return '';

        const header = headers[columnIndex];
        table.style.setProperty('--table-context-header-bg', getPaintedColor(header, 'backgroundColor', 'var(--primary)'));
        table.style.setProperty('--table-context-header-color', getPaintedColor(header, 'color', '#ffffff'));

        Array.prototype.forEach.call(table.rows, function (row) {
            const cell = row.cells[columnIndex];
            if (!cell) return;
            cell.classList.add('table-context-cell');
            if (cell.tagName === 'TD') {
                cell.style.setProperty('--table-context-row-bg', getPaintedColor(cell, 'backgroundColor', 'var(--card-bg)'));
            }
        });
        return (headers[columnIndex].textContent || '').replace(/\s+/g, ' ').trim();
    }

    function buildControls(table, host, contextLabel) {
        const controls = document.createElement('div');
        controls.className = 'table-scroll-tools';
        controls.dataset.tableScrollTools = 'true';

        const toolbar = document.createElement('div');
        toolbar.className = 'table-scroll-toolbar';

        const guidance = document.createElement('div');
        guidance.className = 'table-scroll-guidance';

        const hint = document.createElement('span');
        hint.className = 'table-scroll-hint';
        hint.innerHTML = '<span aria-hidden="true">↔</span><span>Desliza para ver todas las columnas</span>';
        guidance.appendChild(hint);

        if (contextLabel) {
            const context = document.createElement('span');
            context.className = 'table-scroll-context';
            context.title = 'Columna de referencia: ' + contextLabel;
            context.innerHTML = '<span aria-hidden="true">📌</span><span>Referencia: <strong></strong></span>';
            context.querySelector('strong').textContent = contextLabel;
            guidance.appendChild(context);
        }

        const actions = document.createElement('div');
        actions.className = 'table-scroll-actions';

        const progress = document.createElement('span');
        progress.className = 'table-scroll-progress';
        progress.setAttribute('aria-hidden', 'true');
        progress.textContent = 'Inicio';

        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'table-scroll-jump';
        button.innerHTML = '<span class="table-scroll-jump-label">Ir al final de la tabla</span><span aria-hidden="true">→</span>';

        actions.appendChild(progress);
        actions.appendChild(button);
        toolbar.appendChild(guidance);
        toolbar.appendChild(actions);

        const topScroll = document.createElement('div');
        topScroll.className = 'table-scrollbar-top';
        topScroll.tabIndex = 0;
        topScroll.setAttribute('role', 'scrollbar');
        topScroll.setAttribute('aria-orientation', 'horizontal');
        topScroll.setAttribute('aria-label', 'Desplazamiento horizontal superior de la tabla');

        const topScrollInner = document.createElement('div');
        topScrollInner.className = 'table-scrollbar-top-inner';
        topScroll.appendChild(topScrollInner);

        controls.appendChild(toolbar);
        controls.appendChild(topScroll);
        host.insertBefore(controls, table);

        return {
            controls: controls,
            topScroll: topScroll,
            topScrollInner: topScrollInner,
            progress: progress,
            button: button,
            buttonLabel: button.querySelector('.table-scroll-jump-label')
        };
    }

    function enhanceTable(table) {
        if (enhancedTables.has(table) || table.closest('[data-table-navigation="off"]')) return;

        const host = findScrollHost(table);
        if (host.dataset.tableNavigationOwner && host.dataset.tableNavigationOwner !== table.id) return;

        enhancedTables.add(table);
        tableSequence += 1;
        if (!table.id) table.id = 'econotec-table-' + tableSequence;

        host.dataset.tableNavigationOwner = table.id;
        host.classList.add('table-scroll-viewport');
        host.setAttribute('role', 'region');
        host.setAttribute('aria-label', table.getAttribute('aria-label') || 'Tabla con desplazamiento horizontal');

        const headers = getHeaders(table);
        const contextLabel = markContextColumn(table, headers);
        const ui = buildControls(table, host, contextLabel);
        ui.button.setAttribute('aria-controls', table.id);
        ui.topScroll.setAttribute('aria-controls', table.id);

        let syncSource = '';
        let resizeFrame = null;
        let contextPinStart = Number.POSITIVE_INFINITY;
        const contextHeaderCell = table.querySelector('th.table-context-cell');

        function getMaximumScroll() {
            return Math.max(0, table.scrollWidth - host.clientWidth);
        }

        function updateContextGutter(contextPinned) {
            let safeGutter = 0;

            if (contextPinned && contextHeaderCell) {
                const contextRight = contextHeaderCell.getBoundingClientRect().right;
                let nearestTextLeft = Number.POSITIVE_INFINITY;

                headers.forEach(function (header) {
                    if (header === contextHeaderCell) return;

                    const rect = header.getBoundingClientRect();
                    const paddingLeft = parseFloat(window.getComputedStyle(header).paddingLeft) || 0;
                    const textLeft = rect.left + paddingLeft;
                    if (rect.right > contextRight && textLeft > contextRight) {
                        nearestTextLeft = Math.min(nearestTextLeft, textLeft);
                    }
                });

                if (Number.isFinite(nearestTextLeft)) {
                    safeGutter = Math.max(0, Math.floor(nearestTextLeft - contextRight - 3));
                }
            }

            host.style.setProperty('--table-context-gutter', safeGutter + 'px');
        }

        function updatePosition() {
            const maximum = getMaximumScroll();
            const current = Math.min(maximum, Math.max(0, host.scrollLeft));
            const atEnd = maximum > 0 && current >= maximum - 4;
            const percentage = maximum > 0 ? Math.round((current / maximum) * 100) : 0;
            const contextPinned = maximum > 0 && current >= contextPinStart - 2;

            host.dataset.contextPinned = contextPinned ? 'true' : 'false';
            updateContextGutter(contextPinned);
            ui.progress.textContent = atEnd ? 'Final' : (current <= 4 ? 'Inicio' : percentage + '%');
            ui.button.dataset.direction = atEnd ? 'start' : 'end';
            ui.buttonLabel.textContent = atEnd ? 'Volver al inicio' : 'Ir al final de la tabla';
            ui.button.querySelector('[aria-hidden="true"]').textContent = atEnd ? '←' : '→';
            ui.button.setAttribute('aria-label', atEnd ? 'Volver al inicio de la tabla' : 'Ir al final de la tabla horizontalmente');
            ui.topScroll.setAttribute('aria-valuemin', '0');
            ui.topScroll.setAttribute('aria-valuemax', String(Math.round(maximum)));
            ui.topScroll.setAttribute('aria-valuenow', String(Math.round(current)));
            ui.topScroll.setAttribute('aria-valuetext', atEnd ? 'Final' : (current <= 4 ? 'Inicio' : percentage + ' por ciento'));
        }

        function measure() {
            resizeFrame = null;
            const hostWidth = host.clientWidth;
            const tableWidth = table.scrollWidth;
            const hasOverflow = hostWidth > 0 && tableWidth > hostWidth + 4;
            contextPinStart = contextHeaderCell ? contextHeaderCell.offsetLeft : Number.POSITIVE_INFINITY;

            host.dataset.tableOverflow = hasOverflow ? 'true' : 'false';
            host.dataset.mobileScroll = hasOverflow ? 'true' : 'false';
            host.tabIndex = hasOverflow ? 0 : -1;
            ui.topScrollInner.style.width = Math.max(hostWidth, tableWidth) + 'px';

            if (!hasOverflow) {
                host.scrollLeft = 0;
                ui.topScroll.scrollLeft = 0;
            }
            updatePosition();
        }

        function requestMeasure() {
            if (resizeFrame !== null) return;
            resizeFrame = window.requestAnimationFrame(measure);
        }

        host.addEventListener('scroll', function () {
            if (syncSource !== 'top') {
                syncSource = 'host';
                ui.topScroll.scrollLeft = host.scrollLeft;
                window.requestAnimationFrame(function () { syncSource = ''; });
            }
            updatePosition();
        }, { passive: true });

        ui.topScroll.addEventListener('scroll', function () {
            if (syncSource !== 'host') {
                syncSource = 'top';
                host.scrollLeft = ui.topScroll.scrollLeft;
                window.requestAnimationFrame(function () { syncSource = ''; });
            }
            updatePosition();
        }, { passive: true });

        ui.button.addEventListener('click', function () {
            const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
            const target = ui.button.dataset.direction === 'start' ? 0 : getMaximumScroll();
            host.scrollTo({ left: target, behavior: reduceMotion ? 'auto' : 'smooth' });
        });

        if ('ResizeObserver' in window) {
            const observer = new ResizeObserver(requestMeasure);
            observer.observe(host);
            observer.observe(table);
            resizeObservers.set(table, observer);
        }

        tableRefreshers.push(requestMeasure);
        refreshersByTable.set(table, requestMeasure);
        Array.prototype.forEach.call(table.querySelectorAll('img'), function (image) {
            if (!image.complete) image.addEventListener('load', requestMeasure, { once: true });
        });
        window.addEventListener('load', requestMeasure, { once: true });
        requestMeasure();
    }

    function enhanceWithin(root) {
        if (!root || root.nodeType !== 1 && root.nodeType !== 9) return;
        if (root.matches && root.matches(TABLE_SELECTOR)) enhanceTable(root);
        Array.prototype.forEach.call(root.querySelectorAll(TABLE_SELECTOR), enhanceTable);
    }

    function start() {
        enhanceWithin(document);

        let windowResizeTimer = null;
        window.addEventListener('resize', function () {
            window.clearTimeout(windowResizeTimer);
            windowResizeTimer = window.setTimeout(function () {
                tableRefreshers.forEach(function (refresh) { refresh(); });
            }, 120);
        });

        if ('MutationObserver' in window) {
            const observer = new MutationObserver(function (mutations) {
                mutations.forEach(function (mutation) {
                    Array.prototype.forEach.call(mutation.addedNodes, function (node) {
                        if (node.nodeType !== 1) return;
                        enhanceWithin(node);

                        const owningTable = node.closest && node.closest('table');
                        if (owningTable && enhancedTables.has(owningTable)) {
                            markContextColumn(owningTable, getHeaders(owningTable));
                            const refresh = refreshersByTable.get(owningTable);
                            if (refresh) refresh();
                        }
                    });
                });
            });
            observer.observe(document.body, { childList: true, subtree: true });
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start, { once: true });
    } else {
        start();
    }
})();
