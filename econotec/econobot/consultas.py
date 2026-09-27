"""Consultas de solo lectura: equipos, clientes, listas y alertas.

Usan los mismos filtros que las páginas del sistema y nunca modifican datos.
"""
from datetime import date

from django.db.models import Count, Q

from ..alertas import (
    UMBRAL_DIAS_REPARACION_ADMIN, UMBRAL_DIAS_REPARACION_TECNICO, dias_desde_salida,
    dias_en_estado_reparacion, dias_en_taller, equipos_demorados_qs, equipos_reparacion_demorada_qs,
    salidas_bodegaje_qs, whatsapp_link_equipo_listo,
)
from ..busqueda import filtrar_objetos_normalizado, texto_cliente_busqueda, texto_ingreso_busqueda
from ..models import Cliente, IngresoEquipo, SalidaEquipo, SEDES_EQUIPOS
from ..permisos import es_admin, es_tecnico
from ..qr_utils import token_para_ingreso
from ..views_pagos import _puede_editar_valor_acordado_en_pagos
from . import texto as tx
from .equipos import descripcion_equipo
from .respuesta import enlace, enlace_url, opcion, respuesta

MAX_LISTA = 10


def _ingresos_operativos():
    return (IngresoEquipo.objects.filter(sede__in=SEDES_EQUIPOS)
            .exclude(estado__in=('donado', 'equipo_a_comprar')))


def sede_pedida(request, mensaje):
    """Sede mencionada en el mensaje; si no, la de la sesión. '' = todas."""
    t = tx.limpiar(mensaje)
    if 'todas' in t.split() or 'todos' in t.split() or 'ambas' in t.split():
        return ''
    if 'quito' in t:
        return 'quito'
    if 'guayaquil' in t:
        return 'guayaquil'
    sede = (request.session.get('sede_actual') or '').strip().lower()
    return sede if sede in ('guayaquil', 'quito') else ''


def _texto_sede(sede):
    return {'guayaquil': ' de Guayaquil', 'quito': ' de Quito'}.get(sede, ' (todas las sedes)')


def _linea_ingreso(ingreso, extra=''):
    estado = ingreso.estado_visual_display
    if ingreso.subestado_visual_display and ingreso.estado == 'en_reparacion':
        estado = ingreso.subestado_visual_display
    return (f'• {ingreso.codigo_equipo} — {descripcion_equipo(ingreso)} · {ingreso.cliente.nombres} · {estado}'
            + (f' · {extra}' if extra else ''))


def _chips_equipos(ingresos, verbo='Ver'):
    return [opcion(f'{verbo} {i.codigo_equipo}', f'{verbo.lower()} {i.codigo_equipo}') for i in ingresos[:6]]


# ─────────────────────────────────────────────────────────────────────
# Ficha de un equipo
# ─────────────────────────────────────────────────────────────────────

def ficha_equipo(request, ingreso):
    ingreso = (IngresoEquipo.objects
               .select_related('cliente', 'tecnico_encargado', 'registrado_por', 'reporte_por')
               .get(pk=ingreso.pk))
    salida = getattr(ingreso, 'salida', None)
    cliente = ingreso.cliente
    hoy = date.today()

    lineas = [f'🔎 {ingreso.codigo_equipo} — {descripcion_equipo(ingreso)}'
              + (f' · Serie {ingreso.serie}' if ingreso.serie else '')]
    lineas.append(f'Cliente: {cliente.nombres} · Cédula {cliente.cedula}'
                  + (f' · WhatsApp {cliente.whatsapp}' if cliente.whatsapp else ''))
    estado = ingreso.estado_visual_display
    if ingreso.subestado_visual_display:
        estado += f' — {ingreso.subestado_visual_display}'
    lineas.append(f'Estado: {estado}')
    lineas.append(f'Ingresó el {ingreso.fecha_ingreso:%d/%m/%Y} ({dias_en_taller(ingreso, hoy)} días) · '
                  f'Sede {ingreso.sede_display_corto}')
    lineas.append(f'Técnico que recibió: {ingreso.tecnico_encargado_nombre or "—"} · '
                  f'Asesora: {ingreso.asesor_comercial or "—"}')
    lineas.append(f'Problema: {ingreso.problema_reportado}')
    if ingreso.accesorios_entregados:
        lineas.append(f'Accesorios: {ingreso.accesorios_entregados}')
    if (ingreso.reporte_tecnico or '').strip():
        autor = f' ({ingreso.reporte_por_nombre})' if ingreso.reporte_por_nombre else ''
        lineas.append(f'Reporte del técnico{autor}: {ingreso.reporte_tecnico.strip()[:300]}')
    if ingreso.estado == 'garantia' and ingreso.motivo_garantia:
        referencia = ingreso.equipo_garantia_referencia
        lineas.append(f'Garantía: {ingreso.motivo_garantia}' + (f' (equipo anterior {referencia})' if referencia else ''))

    # Dinero
    pagado = tx.dinero_legible(ingreso.total_abonado)
    if ingreso.estado == 'cortesia':
        lineas.append('💵 Equipo de cortesía: no genera cobros.')
    elif ingreso.valor_acordado is None and not ingreso.reparacion_cancelada:
        lineas.append(f'💵 Valor acordado: pendiente · Pagado hasta ahora: {pagado}')
        if (ingreso.valor_pendiente_reporte or '').strip():
            lineas.append(f'Motivo del valor pendiente: {ingreso.valor_pendiente_reporte.strip()[:200]}')
    else:
        lineas.append(f'💵 Valor a cobrar: {tx.dinero_legible(ingreso.valor_efectivo_a_cobrar)} · Pagado: {pagado} · '
                      f'Saldo: {tx.dinero_legible(max(ingreso.diferencia, 0))} ({ingreso.estado_pago})')

    if salida is not None:
        lineas.append(f'✅ Finalizado el {salida.fecha_salida:%d/%m/%Y}: {salida.get_estado_reparacion_display()}'
                      + (f' · Técnico que reparó: {salida.tecnico_reparo_nombre}' if salida.tecnico_reparo_nombre else ''))
        if salida.cliente_ya_retiro:
            lineas.append(f'🚚 Salió de la oficina el {salida.fecha_retiro_real:%d/%m/%Y}.')
        else:
            lineas.append(f'📦 Sigue en la oficina ({dias_desde_salida(salida, hoy)} días desde que se finalizó).')
            if ingreso.bodegaje_pendiente > 0:
                lineas.append(f'Bodegaje acumulado: {tx.dinero_legible(ingreso.bodegaje_pendiente)} '
                              f'({ingreso.bodegaje_dias_pendiente} días).')

    enlaces = [enlace('Abrir equipo', 'ingreso_detalle', pk=ingreso.pk)]
    opciones = []
    if ingreso.sede in SEDES_EQUIPOS:
        enlaces.append(enlace('Hoja del técnico', 'tecnico_hoja', token=token_para_ingreso(ingreso.pk)))
        enlaces.append(enlace('Pagos del equipo', 'ingreso_abonos', pk=ingreso.pk))
        enlaces.append(enlace('Imprimir hoja', 'ingreso_imprimir', pk=ingreso.pk, tipo='nueva'))
    if salida is None:
        if ingreso.estado in ('ingresado', 'en_reparacion'):
            opciones += [
                opcion('🔧 Cambiar estado', f'cambiar estado {ingreso.codigo_equipo}'),
                opcion('📝 Escribir reporte', f'reporte {ingreso.codigo_equipo}'),
            ]
        if ingreso.sede in SEDES_EQUIPOS and ingreso.estado not in ('donado', 'equipo_a_comprar'):
            opciones.append(opcion('✅ Finalizar equipo', f'finalizar {ingreso.codigo_equipo}'))
        if ingreso.valor_acordado is None and _puede_editar_valor_acordado_en_pagos(ingreso):
            opciones.append(opcion('💲 Poner valor acordado', f'valor acordado {ingreso.codigo_equipo}'))
    else:
        enlaces.append(enlace('Acta de finalización (PDF)', 'salida_pdf', pk=salida.pk, tipo='nueva'))
        if not salida.cliente_ya_retiro:
            enlaces.append(enlace_url('Avisar por WhatsApp que está listo', whatsapp_link_equipo_listo(salida)))
            if ingreso.diferencia <= 0:
                opciones.append(opcion('🚚 Confirmar salida física', f'confirmar salida {ingreso.codigo_equipo}'))
            else:
                enlaces.append(enlace('Registrar pago', 'abono_crear', ingreso_pk=ingreso.pk))
    opciones.append(opcion('👤 Ver cliente', f'cliente {cliente.cedula}'))
    return respuesta('\n'.join(lineas), enlaces, opciones, ultimo_equipo=ingreso.pk)


# ─────────────────────────────────────────────────────────────────────
# Clientes
# ─────────────────────────────────────────────────────────────────────

def ficha_cliente(cliente):
    ingresos = list(cliente.ingresos.select_related('cliente').order_by('-fecha_ingreso', '-numero_equipo'))
    lineas = [f'👤 {cliente.nombres}', f'Cédula / RUC: {cliente.cedula}']
    lineas.append(f'WhatsApp: {cliente.whatsapp or "—"} · Correo: {cliente.correo or "—"} · Sector: {cliente.sector_display}')
    lineas.append(f'Cliente desde el {cliente.creado:%d/%m/%Y} · {len(ingresos)} registro{"s" if len(ingresos) != 1 else ""}')
    if ingresos:
        lineas.append('Equipos (más recientes primero):')
        for ingreso in ingresos[:MAX_LISTA]:
            lineas.append(_linea_ingreso(ingreso, f'{ingreso.fecha_ingreso:%d/%m/%Y}'))
        if len(ingresos) > MAX_LISTA:
            lineas.append(f'… y {len(ingresos) - MAX_LISTA} más en la ficha del cliente.')
    enlaces = [enlace('Abrir ficha del cliente', 'cliente_detalle', pk=cliente.pk)]
    opciones = _chips_equipos(ingresos)
    opciones.append(opcion('➕ Registrar equipo a este cliente', f'registrar equipo {cliente.cedula}'))
    return respuesta('\n'.join(lineas), enlaces, opciones)


def buscar_cliente(termino):
    termino = (termino or '').strip()
    if not termino:
        return respuesta('¿Qué cliente busco? Escribe su cédula, nombre, WhatsApp o correo.',
                         [enlace('Ver todos los clientes', 'cliente_lista')], esperar='cliente')
    cedula = tx.cedula_en(termino) or (tx.solo_digitos(termino) if tx.solo_digitos(termino) == termino.replace(' ', '') else '')
    if cedula:
        cliente = Cliente.objects.filter(cedula=cedula).first()
        if cliente:
            return ficha_cliente(cliente)
    encontrados = filtrar_objetos_normalizado(
        Cliente.objects.annotate(equipos_total=Count('ingresos')).order_by('nombres'),
        termino, texto_cliente_busqueda,
    )
    if not encontrados:
        return respuesta(f'No encontré clientes con «{termino}».',
                         [enlace('Buscar en Clientes', 'cliente_lista')],
                         [opcion('➕ Registrar equipo', 'registrar equipo')])
    if len(encontrados) == 1:
        return ficha_cliente(encontrados[0])
    lineas = [f'Encontré {len(encontrados)} clientes con «{termino}»:']
    for cliente in encontrados[:MAX_LISTA]:
        lineas.append(f'• {cliente.nombres} — {cliente.cedula} · {cliente.equipos_total} equipo'
                      f'{"s" if cliente.equipos_total != 1 else ""}')
    if len(encontrados) > MAX_LISTA:
        lineas.append('Escribe más datos (apellido o cédula) para afinar la búsqueda.')
    return respuesta('\n'.join(lineas), [enlace('Abrir Clientes', 'cliente_lista')],
                     [opcion(c.nombres[:28], f'cliente {c.cedula}') for c in encontrados[:6]])


# ─────────────────────────────────────────────────────────────────────
# Listas
# ─────────────────────────────────────────────────────────────────────

def finalizados_en_oficina(request, mensaje=''):
    """Equipos finalizados que siguen en la oficina (lista «Equipos finalizados»)."""
    sede = sede_pedida(request, mensaje)
    qs = (SalidaEquipo.objects.select_related('ingreso', 'ingreso__cliente', 'tecnico_reparo')
          .filter(fecha_retiro_real__isnull=True, ingreso__sede__in=SEDES_EQUIPOS)
          .order_by('-fecha_salida', '-creado'))
    if sede:
        qs = qs.filter(ingreso__sede=sede)
    total = qs.count()
    if not total:
        return respuesta(f'No hay equipos finalizados esperando en la oficina{_texto_sede(sede)}.',
                         [enlace('Abrir Equipos finalizados', 'salida_lista')])
    lineas = [f'📦 {total} equipo{"s" if total != 1 else ""} finalizado{"s" if total != 1 else ""} '
              f'en la oficina{_texto_sede(sede)} (más recientes primero):']
    salidas = list(qs[:MAX_LISTA])
    for salida in salidas:
        ingreso = salida.ingreso
        saldo = ingreso.diferencia
        extra = f'{salida.get_estado_reparacion_display()} · {salida.fecha_salida:%d/%m/%Y}'
        extra += f' · Saldo {tx.dinero_legible(saldo)}' if saldo > 0 else ' · Sin saldo'
        lineas.append(f'• {ingreso.codigo_equipo} — {descripcion_equipo(ingreso)} · {ingreso.cliente.nombres} · {extra}')
    if total > MAX_LISTA:
        lineas.append(f'… y {total - MAX_LISTA} más en la lista completa.')
    return respuesta('\n'.join(lineas), [enlace('Abrir Equipos finalizados', 'salida_lista')],
                     _chips_equipos([s.ingreso for s in salidas]))


def salidas_fisicas(request, mensaje=''):
    sede = sede_pedida(request, mensaje)
    qs = (SalidaEquipo.objects.select_related('ingreso', 'ingreso__cliente')
          .filter(fecha_retiro_real__isnull=False, ingreso__sede__in=SEDES_EQUIPOS)
          .order_by('-fecha_retiro_real', '-fecha_salida', '-creado'))
    if sede:
        qs = qs.filter(ingreso__sede=sede)
    total = qs.count()
    if not total:
        return respuesta(f'Aún no hay salidas físicas confirmadas{_texto_sede(sede)}.',
                         [enlace('Abrir Salidas físicas confirmadas', 'salida_retiros_lista')])
    hoy = date.today()
    de_hoy = qs.filter(fecha_retiro_real=hoy).count()
    lineas = [f'🚚 {total} salidas físicas confirmadas{_texto_sede(sede)} · {de_hoy} hoy. Últimas:']
    salidas = list(qs[:MAX_LISTA])
    for salida in salidas:
        ingreso = salida.ingreso
        lineas.append(f'• {ingreso.codigo_equipo} — {descripcion_equipo(ingreso)} · {ingreso.cliente.nombres} · '
                      f'salió el {salida.fecha_retiro_real:%d/%m/%Y}')
    return respuesta('\n'.join(lineas), [enlace('Abrir Salidas físicas confirmadas', 'salida_retiros_lista')],
                     _chips_equipos([s.ingreso for s in salidas]))


def en_taller(request, mensaje='', solo_mios=False):
    sede = sede_pedida(request, mensaje)
    qs = (_ingresos_operativos().select_related('cliente', 'tecnico_encargado')
          .filter(estado__in=('ingresado', 'en_reparacion', 'garantia', 'cortesia'), salida__isnull=True)
          .order_by('fecha_ingreso', 'numero_equipo'))
    if sede:
        qs = qs.filter(sede=sede)
    if solo_mios:
        qs = qs.filter(tecnico_encargado=request.user)
    total = qs.count()
    quien = ' asignados a ti' if solo_mios else ''
    if not total:
        return respuesta(f'No hay equipos{quien} en el taller{_texto_sede(sede)}. 🎉',
                         [enlace('Abrir Equipos ingresados', 'ingreso_lista')])
    diagnostico = qs.filter(estado='ingresado').count()
    reparacion = qs.filter(estado='en_reparacion').count()
    otros = total - diagnostico - reparacion
    lineas = [f'🔧 {total} equipo{"s" if total != 1 else ""}{quien} en el taller{_texto_sede(sede)}: '
              f'{diagnostico} en diagnóstico, {reparacion} en reparación'
              + (f', {otros} de garantía/cortesía' if otros else '') + '. Los que llevan más tiempo:']
    hoy = date.today()
    ingresos = list(qs[:MAX_LISTA])
    for ingreso in ingresos:
        lineas.append(_linea_ingreso(ingreso, f'{dias_en_taller(ingreso, hoy)} días'))
    if total > MAX_LISTA:
        lineas.append(f'… y {total - MAX_LISTA} más.')
    return respuesta('\n'.join(lineas), [enlace('Abrir Equipos ingresados', 'ingreso_lista')],
                     _chips_equipos(ingresos))


def sin_valor_acordado(request, mensaje=''):
    sede = sede_pedida(request, mensaje)
    qs = (_ingresos_operativos().select_related('cliente')
          .filter(valor_acordado__isnull=True).exclude(estado='entregado')
          .order_by('fecha_ingreso', 'numero_equipo'))
    if sede:
        qs = qs.filter(sede=sede)
    total = qs.count()
    if not total:
        return respuesta(f'Todos los equipos{_texto_sede(sede)} tienen valor acordado. ✅')
    lineas = [f'💲 {total} equipo{"s" if total != 1 else ""} sin valor acordado{_texto_sede(sede)}:']
    ingresos = list(qs[:MAX_LISTA])
    for ingreso in ingresos:
        lineas.append(_linea_ingreso(ingreso))
    if total > MAX_LISTA:
        lineas.append(f'… y {total - MAX_LISTA} más.')
    url = enlace('Abrir la lista filtrada', 'ingreso_lista')
    url['url'] += '?valor=pendiente' + (f'&sede={sede}' if sede else '&sede=todas')
    return respuesta('\n'.join(lineas), [url],
                     [opcion(f'Valor {i.codigo_equipo}', f'valor acordado {i.codigo_equipo}') for i in ingresos[:6]])


def saldos_pendientes(request, mensaje=''):
    """Equipos finalizados en la oficina con saldo por cobrar."""
    sede = sede_pedida(request, mensaje)
    qs = (SalidaEquipo.objects.select_related('ingreso', 'ingreso__cliente')
          .filter(fecha_retiro_real__isnull=True, ingreso__sede__in=SEDES_EQUIPOS)
          .order_by('fecha_salida'))
    if sede:
        qs = qs.filter(ingreso__sede=sede)
    con_saldo = [(s, s.ingreso.diferencia) for s in qs]
    con_saldo = [(s, saldo) for s, saldo in con_saldo if saldo > 0]
    if not con_saldo:
        return respuesta(f'No hay equipos finalizados con saldo pendiente{_texto_sede(sede)}. ✅',
                         [enlace('Abrir Pagos', 'pagos_lista')])
    total = sum((saldo for _s, saldo in con_saldo), 0)
    lineas = [f'💰 {len(con_saldo)} equipo{"s" if len(con_saldo) != 1 else ""} finalizado{"s" if len(con_saldo) != 1 else ""} '
              f'con saldo por cobrar{_texto_sede(sede)} · Total {tx.dinero_legible(total)}:']
    for salida, saldo in con_saldo[:MAX_LISTA]:
        ingreso = salida.ingreso
        lineas.append(f'• {ingreso.codigo_equipo} — {ingreso.cliente.nombres} · saldo {tx.dinero_legible(saldo)} · '
                      f'listo desde {salida.fecha_salida:%d/%m/%Y}')
    return respuesta('\n'.join(lineas), [enlace('Abrir Pagos', 'pagos_lista')],
                     _chips_equipos([s.ingreso for s, _ in con_saldo]))


def alertas(request):
    user = request.user
    hoy = date.today()
    lineas = ['🔔 Alertas del sistema:']
    enlaces = []
    chips = []

    demorados = equipos_demorados_qs(usuario=None)
    total = demorados.count()
    if total:
        lineas.append(f'⏱️ {total} equipo{"s" if total != 1 else ""} con 4 o más días esperando diagnóstico:')
        for ingreso in demorados[:5]:
            lineas.append(_linea_ingreso(ingreso, f'{dias_en_taller(ingreso, hoy)} días'))
            chips.append(ingreso)
        enlaces.append(enlace('Ver demoras de diagnóstico', 'alertas_demora'))
    else:
        lineas.append('⏱️ Diagnóstico: ningún equipo demorado.')

    reparacion = IngresoEquipo.objects.none()
    umbral = None
    if es_admin(user):
        reparacion, umbral = equipos_reparacion_demorada_qs(None, UMBRAL_DIAS_REPARACION_ADMIN), UMBRAL_DIAS_REPARACION_ADMIN
    elif es_tecnico(user):
        reparacion, umbral = equipos_reparacion_demorada_qs(user, UMBRAL_DIAS_REPARACION_TECNICO), UMBRAL_DIAS_REPARACION_TECNICO
    if umbral is not None:
        total = reparacion.count()
        if total:
            lineas.append(f'🔧 {total} equipo{"s" if total != 1 else ""} detenido{"s" if total != 1 else ""} '
                          f'en reparación {umbral} o más días:')
            for ingreso in reparacion[:5]:
                lineas.append(_linea_ingreso(ingreso, f'{dias_en_estado_reparacion(ingreso, hoy)} días en ese estado'))
                chips.append(ingreso)
        else:
            lineas.append(f'🔧 Reparación: ningún equipo detenido {umbral} o más días.')

    bodegajes = salidas_bodegaje_qs(usuario=None)
    total = bodegajes.count()
    if total:
        lineas.append(f'📦 {total} equipo{"s" if total != 1 else ""} con bodegaje (5 o más días sin retirar):')
        for salida in bodegajes[:5]:
            bod = salida.calcular_bodegaje(hoy=hoy)
            lineas.append(f'• {salida.ingreso.codigo_equipo} — {salida.ingreso.cliente.nombres} · '
                          f'{dias_desde_salida(salida, hoy)} días · bodegaje {tx.dinero_legible(bod["monto"])}')
            chips.append(salida.ingreso)
        enlaces.append(enlace('Ver alertas de bodegaje', 'alertas_bodegaje'))
    else:
        lineas.append('📦 Bodegaje: ningún equipo acumulando.')
    return respuesta('\n'.join(lineas), enlaces, _chips_equipos(chips))


def estadisticas(request):
    hoy = date.today()
    ingresos = IngresoEquipo.objects.filter(sede__in=SEDES_EQUIPOS)
    salidas = SalidaEquipo.objects.filter(ingreso__sede__in=SEDES_EQUIPOS)
    en_taller_total = ingresos.filter(estado__in=['ingresado', 'en_reparacion'], salida__isnull=True).count()
    en_oficina = salidas.filter(fecha_retiro_real__isnull=True).count()
    lineas = [
        f'📊 Resumen de Econotec al {hoy:%d/%m/%Y}:',
        f'• Equipos ingresados este mes: {ingresos.filter(fecha_ingreso__year=hoy.year, fecha_ingreso__month=hoy.month).count()}'
        f' (total histórico {ingresos.count()})',
        f'• Finalizados este mes: {salidas.filter(fecha_salida__year=hoy.year, fecha_salida__month=hoy.month).count()}',
        f'• Ingresados hoy: {ingresos.filter(fecha_ingreso=hoy).count()} · Finalizados hoy: {salidas.filter(fecha_salida=hoy).count()}'
        f' · Salidas físicas hoy: {salidas.filter(fecha_retiro_real=hoy).count()}',
        f'• En el taller (diagnóstico o reparación): {en_taller_total}',
        f'• Finalizados esperando en la oficina: {en_oficina}',
        f'• Salidas físicas confirmadas: {salidas.filter(fecha_retiro_real__isnull=False).count()}',
        f'• Clientes registrados: {Cliente.objects.count()}',
    ]
    por_sede = dict(ingresos.filter(estado__in=['ingresado', 'en_reparacion'], salida__isnull=True)
                    .values('sede').annotate(n=Count('id')).values_list('sede', 'n'))
    if por_sede:
        lineas.append(f'• En taller por sede: Guayaquil {por_sede.get("guayaquil", 0)} · Quito {por_sede.get("quito", 0)}')
    return respuesta('\n'.join(lineas), [enlace('Ir al panel principal', 'bienvenida')], [
        opcion('🔧 Equipos en taller', 'equipos en taller'),
        opcion('📦 Finalizados en oficina', 'equipos finalizados'),
        opcion('🔔 Alertas', 'alertas'),
    ])


def buscar_equipos(request, termino):
    termino = (termino or '').strip()
    if len(termino) < 2:
        return respuesta('¿Qué equipo busco? Escribe el código (G1031), la cédula, el nombre del cliente o la marca/modelo.',
                         esperar='buscar')
    qs = (IngresoEquipo.objects.filter(sede__in=SEDES_EQUIPOS)
          .select_related('cliente', 'tecnico_encargado', 'registrado_por', 'salida')
          .order_by('-fecha_ingreso', '-numero_equipo'))
    encontrados = filtrar_objetos_normalizado(qs, termino, texto_ingreso_busqueda)
    if not encontrados:
        return respuesta(f'No encontré equipos con «{termino}».', [enlace('Abrir Equipos ingresados', 'ingreso_lista')],
                         [opcion('Buscar cliente', f'cliente {termino}')])
    if len(encontrados) == 1:
        return ficha_equipo(request, encontrados[0])
    lineas = [f'Encontré {len(encontrados)} equipos con «{termino}» (más recientes primero):']
    for ingreso in encontrados[:MAX_LISTA]:
        lineas.append(_linea_ingreso(ingreso, f'{ingreso.fecha_ingreso:%d/%m/%Y}'))
    if len(encontrados) > MAX_LISTA:
        lineas.append('Escribe más datos para afinar la búsqueda.')
    return respuesta('\n'.join(lineas), [enlace('Abrir Equipos ingresados', 'ingreso_lista')],
                     _chips_equipos(encontrados))


def ultimos_ingresos(request, mensaje=''):
    sede = sede_pedida(request, mensaje)
    qs = (_ingresos_operativos().select_related('cliente')
          .order_by('-fecha_ingreso', '-numero_equipo'))
    if sede:
        qs = qs.filter(sede=sede)
    hoy = date.today()
    de_hoy = qs.filter(fecha_ingreso=hoy).count()
    ingresos = list(qs[:MAX_LISTA])
    if not ingresos:
        return respuesta(f'No hay equipos registrados{_texto_sede(sede)}.')
    lineas = [f'🆕 Últimos equipos ingresados{_texto_sede(sede)} · {de_hoy} hoy:']
    for ingreso in ingresos:
        lineas.append(_linea_ingreso(ingreso, f'{ingreso.fecha_ingreso:%d/%m/%Y}'))
    return respuesta('\n'.join(lineas), [enlace('Abrir Equipos ingresados', 'ingreso_lista')],
                     _chips_equipos(ingresos))


def top_clientes():
    filas = (Cliente.objects
             .annotate(total=Count('ingresos', filter=Q(ingresos__sede__in=SEDES_EQUIPOS)))
             .filter(total__gt=0).order_by('-total', 'nombres')[:MAX_LISTA])
    if not filas:
        return respuesta('Todavía no hay clientes con equipos registrados.')
    lineas = ['🏆 Clientes que más equipos han traído:']
    for posicion, cliente in enumerate(filas, 1):
        lineas.append(f'{posicion}. {cliente.nombres} — {cliente.total} equipo{"s" if cliente.total != 1 else ""}')
    return respuesta('\n'.join(lineas), [enlace('Abrir Top clientes', 'cliente_top_recurrentes')],
                     [opcion(c.nombres[:28], f'cliente {c.cedula}') for c in filas[:6]])
