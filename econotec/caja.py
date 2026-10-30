"""
Caja y cuadres del Ranking de Técnicos (solo para el administrador).

- La Caja se calcula siempre de los pagos reales; no se guarda en ninguna tabla,
  así que corregir un pago corrige el mes y nunca hay dinero duplicado.
- Cada pago cuenta en el mes de su fecha, como en el Seguimiento de pago:
  anticipo y diagnóstico inmediato (fecha de ingreso), abonos (fecha del abono)
  y pago al finalizar (fecha de finalización).
- Entran reparaciones, ventas de producto, diagnósticos inmediatos y bodegaje
  cobrado; los egresos restan.
- El bodegaje cobrado viene dentro de los abonos: se muestra aparte y se resta
  de las reparaciones para no contarlo dos veces.
- Los cuadres comparan estas cifras con Pagos. Si algo no coincide se muestra
  la diferencia y su causa; no se ajusta ningún número para que cuadre.
"""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format

from .date_filters import _month_bounds, _parse_date
from .models import Abono, Egreso, IngresoEquipo, SalidaEquipo
from .seguimiento_pago import (
    METODOS_RESUMEN,
    OTROS,
    _partes,
    _partes_anticipo,
    _partes_diagnostico,
    _partes_salida,
)
from .templatetags.econotec_extras import dinero_signo

CERO = Decimal('0.00')

# Estados de cada cuadre. «aviso» no descuadra nada, pero el admin debe saberlo.
OK = 'ok'
DIFERENCIA = 'diferencia'
AVISO = 'aviso'


# ─────────────────────────────────────────────────────────
# Dinero de un equipo finalizado
# ─────────────────────────────────────────────────────────

def _estado_bodegaje(cobrado, pendiente, perdonado, decision_perdon):
    """Qué pasó con el bodegaje del equipo, para la tabla del técnico."""
    if cobrado > 0:
        return 'cobrado'
    if pendiente > 0:
        return 'pendiente'
    if perdonado > 0 or decision_perdon:
        return 'perdonado'
    return 'sin'


def cobrado_sin_bodegaje(ingreso):
    """Lo que el cliente pagó por el servicio; el bodegaje cobrado va aparte."""
    return ingreso.total_abonado - ingreso.bodegaje_cobrado_en_abonos


def dinero_de_salida(salida):
    """
    Dinero de un equipo finalizado con las mismas propiedades que usa Pagos.

    Cobrado no incluye el bodegaje: es un plus que se muestra aparte, así que
    cobrarlo o no nunca cambia acordado, cobrado ni por cobrar.
    Bodegaje pendiente sigue creciendo hasta que se cobre o se perdone.
    """
    ingreso = salida.ingreso
    abonos = list(ingreso.abonos.all())
    bodegaje_cobrado = ingreso.bodegaje_cobrado_en_abonos
    bodegaje_pendiente = ingreso.bodegaje_pendiente
    bodegaje_perdonado = CERO
    if (
        salida.bodegaje_dias_congelado is not None
        and not salida.bodegaje_aplicado_al_pago
    ):
        bodegaje_perdonado = salida.bodegaje_monto_congelado or CERO
    pagado = ingreso.total_abonado
    saldo = ingreso.diferencia
    return {
        'ingreso_id': ingreso.pk,
        'codigo': ingreso.codigo_equipo,
        'cliente': ingreso.cliente.nombres,
        'url_pagos': reverse('econotec:ingreso_abonos', args=[ingreso.pk]),
        'acordado': ingreso.valor_servicio_a_cobrar,
        'domicilio': ingreso.valor_domicilio_aplicable,
        'a_cobrar': ingreso.valor_efectivo_a_cobrar,
        'pagado': pagado,
        'cobrado': cobrado_sin_bodegaje(ingreso),
        'por_cobrar': max(saldo, CERO),
        'a_favor': max(-saldo, CERO),
        'diagnostico': (
            ingreso.valor_diagnostico or CERO
            if ingreso.diagnostico_inmediato == 'si' else CERO
        ),
        'bodegaje_cobrado': bodegaje_cobrado,
        'bodegaje_pendiente': bodegaje_pendiente,
        'bodegaje_perdonado': bodegaje_perdonado,
        'bodegaje_dias': (
            ingreso.bodegaje_dias_pendiente
            if bodegaje_pendiente > 0 else (salida.bodegaje_dias_congelado or 0)
        ),
        'bodegaje_estado': _estado_bodegaje(
            bodegaje_cobrado,
            bodegaje_pendiente,
            bodegaje_perdonado,
            any(abono.bodegaje_decision == 'no' for abono in abonos),
        ),
        # Lo que la salida dice que se cobró; se compara con los abonos.
        'bodegaje_registrado': (
            salida.bodegaje_monto_congelado or CERO
            if salida.bodegaje_aplicado_al_pago else CERO
        ),
        'bodegaje_recibos': [
            abono.numero_recibo for abono in sorted(abonos, key=lambda abono: abono.pk)
            if abono.bodegaje_decision == 'si'
        ],
    }


# ─────────────────────────────────────────────────────────
# Libro de pagos: una entrada por cada pago real
# ─────────────────────────────────────────────────────────

def movimientos_de_dinero():
    """Todos los pagos de todos los equipos y ventas, con su fecha."""
    movimientos = []

    def agregar(ingreso, origen, fecha, monto, partes, bodegaje=CERO):
        if monto:
            movimientos.append({
                'ingreso_id': ingreso.pk,
                'origen': origen,
                'fecha': fecha,
                'monto': monto,
                'bodegaje': bodegaje,
                'partes': partes,
            })

    ingresos = (
        IngresoEquipo.objects
        .select_related('salida')
        .prefetch_related('abonos')
    )
    for ingreso in ingresos:
        origen = 'venta' if ingreso.sede == 'ventas' else 'reparacion'
        if ingreso.diagnostico_inmediato == 'si' and ingreso.valor_diagnostico:
            agregar(
                ingreso, 'diagnostico', ingreso.fecha_ingreso,
                ingreso.valor_diagnostico, _partes_diagnostico(ingreso),
            )
        if ingreso.abono_anticipo:
            agregar(
                ingreso, origen, ingreso.fecha_ingreso,
                ingreso.abono_anticipo, _partes_anticipo(ingreso),
            )
        for abono in ingreso.abonos.all():
            agregar(
                ingreso, origen, abono.fecha, abono.monto,
                _partes(abono.monto, abono.metodo, abono.banco, abono.banco_otro, abono.tarjeta_app),
                bodegaje=(
                    abono.bodegaje_monto_aplicado or CERO
                    if abono.bodegaje_decision == 'si' else CERO
                ),
            )
        salida = getattr(ingreso, 'salida', None)
        if salida is not None and salida.valor_final_cobrado:
            agregar(
                ingreso, origen, salida.fecha_salida,
                salida.valor_final_cobrado, _partes_salida(salida),
            )
    return movimientos


def _en_periodo(fecha, inicio, fin):
    return (inicio is None or fecha >= inicio) and (fin is None or fecha <= fin)


def _meses_entre(inicio, fin):
    """Primer día de cada mes desde el de `inicio` hasta el de `fin`."""
    mes = inicio.replace(day=1)
    while mes <= fin:
        yield mes
        mes = (mes + timedelta(days=32)).replace(day=1)


def _egresos():
    return list(Egreso.objects.values_list('fecha', 'monto'))


def _sumar_metodos(movimientos):
    """Cómo entró el dinero. Con los pagos mixtos separados en sus dos métodos."""
    nombres = dict(METODOS_RESUMEN)
    nombres[OTROS] = 'Otros métodos'
    totales = {clave: CERO for clave in nombres}
    for movimiento in movimientos:
        for parte in movimiento['partes']:
            clave = parte['metodo'] if parte['metodo'] in totales else OTROS
            totales[clave] += parte['monto']
    return [
        {'clave': clave, 'nombre': nombre, 'monto': totales[clave]}
        for clave, nombre in nombres.items()
        if clave != OTROS or totales[OTROS]
    ]


def caja_del_periodo(desde, hasta, movimientos=None, hoy=None):
    """
    Lo que entró, lo que salió y lo que queda guardado, mes a mes.

    `saldo_inicial` es lo guardado antes del período y `saldo_final` lo guardado
    al terminar; siempre se cumple saldo_inicial + entró − egresos = saldo_final.
    """
    hoy = hoy or timezone.localdate()
    inicio = _parse_date(desde) if desde else None
    fin = _parse_date(hasta) if hasta else None
    movimientos = movimientos_de_dinero() if movimientos is None else movimientos
    egresos = _egresos()

    saldo_inicial = CERO
    if inicio:
        saldo_inicial = (
            sum((m['monto'] for m in movimientos if m['fecha'] < inicio), CERO)
            - sum((monto for fecha, monto in egresos if fecha < inicio), CERO)
        )

    del_periodo = [m for m in movimientos if _en_periodo(m['fecha'], inicio, fin)]
    egresos_periodo = [(f, m) for f, m in egresos if _en_periodo(f, inicio, fin)]

    fechas = [m['fecha'] for m in del_periodo] + [f for f, _monto in egresos_periodo]
    primer_mes = min(fechas) if fechas else inicio
    ultimo_mes = max(fechas) if fechas else fin
    # Sin datos no se dibujan meses que todavía no llegan.
    if not fechas and ultimo_mes and primer_mes and ultimo_mes > hoy >= primer_mes:
        ultimo_mes = hoy

    filas = {}
    if primer_mes and ultimo_mes:
        for mes in _meses_entre(primer_mes, ultimo_mes):
            filas[(mes.year, mes.month)] = {
                'mes': mes,
                'etiqueta': date_format(mes, 'F Y'),
                'reparaciones': CERO,
                'bodegaje': CERO,
                'diagnostico': CERO,
                'ventas': CERO,
                'entro': CERO,
                'egresos': CERO,
            }
    for movimiento in del_periodo:
        fila = filas[(movimiento['fecha'].year, movimiento['fecha'].month)]
        fila['entro'] += movimiento['monto']
        if movimiento['origen'] == 'diagnostico':
            fila['diagnostico'] += movimiento['monto']
        elif movimiento['origen'] == 'venta':
            fila['ventas'] += movimiento['monto']
        else:
            fila['reparaciones'] += movimiento['monto'] - movimiento['bodegaje']
            fila['bodegaje'] += movimiento['bodegaje']
    for fecha, monto in egresos_periodo:
        filas[(fecha.year, fecha.month)]['egresos'] += monto

    meses = []
    guardado = saldo_inicial
    for clave in sorted(filas):
        fila = filas[clave]
        fila['neto'] = fila['entro'] - fila['egresos']
        guardado += fila['neto']
        fila['guardado'] = guardado
        primer_dia, ultimo_dia = _month_bounds(fila['mes'])
        fila['parcial'] = bool(
            (inicio and inicio > primer_dia) or (fin and fin < ultimo_dia)
        )
        meses.append(fila)

    def total(clave):
        return sum((fila[clave] for fila in meses), CERO)

    entro = total('entro')
    egresos_total = total('egresos')
    return {
        'meses': meses,
        'saldo_inicial': saldo_inicial,
        'reparaciones': total('reparaciones'),
        'bodegaje': total('bodegaje'),
        'diagnostico': total('diagnostico'),
        'ventas': total('ventas'),
        'entro': entro,
        'egresos': egresos_total,
        'neto': entro - egresos_total,
        'saldo_final': saldo_inicial + entro - egresos_total,
        'metodos': _sumar_metodos(del_periodo),
    }


# ─────────────────────────────────────────────────────────
# Cuadres contra Pagos
# ─────────────────────────────────────────────────────────

def totales_de_pagos(ingresos):
    """Los totales de la pantalla de Pagos para esos equipos, con su misma fórmula."""
    ingresos = list(ingresos)
    a_cobrar = sum((i.valor_efectivo_a_cobrar for i in ingresos), CERO)
    pagado = sum((i.total_abonado for i in ingresos), CERO)
    return {
        'a_cobrar': a_cobrar,
        'pagado': pagado,
        'pendiente': a_cobrar - pagado,
        'diagnostico': sum(
            ((i.valor_diagnostico or CERO) for i in ingresos if i.diagnostico_inmediato == 'si'),
            CERO,
        ),
    }


def _pagos_por_fecha(ingresos, inicio, fin):
    """Pagos de esos equipos con fecha en el período, sumados directo en la base."""
    def rango(campo):
        filtros = {}
        if inicio:
            filtros[f'{campo}__gte'] = inicio
        if fin:
            filtros[f'{campo}__lte'] = fin
        return filtros

    anticipos = ingresos.filter(**rango('fecha_ingreso')).aggregate(
        s=Sum('abono_anticipo'),
    )['s'] or CERO
    abonos = Abono.objects.filter(ingreso__in=ingresos, **rango('fecha')).aggregate(
        s=Sum('monto'),
    )['s'] or CERO
    finales = SalidaEquipo.objects.filter(ingreso__in=ingresos, **rango('fecha_salida')).aggregate(
        s=Sum('valor_final_cobrado'),
    )['s'] or CERO
    return anticipos + abonos + finales


def _cuadre(titulo, cuenta, valor, esperado, causa=''):
    """Compara dos cifras: si no coinciden queda la diferencia y su causa a la vista."""
    diferencia = valor - esperado
    return {
        'titulo': titulo,
        'cuenta': cuenta,
        'estado': OK if diferencia == 0 else DIFERENCIA,
        'diferencia': diferencia,
        'causa': causa if diferencia else '',
    }


def _cuadres_de_pagos(desde, hasta, resumen, caja, movimientos):
    """Las tarjetas y la Caja contra la fórmula y los pagos de la pantalla de Pagos."""
    inicio = _parse_date(desde) if desde else None
    fin = _parse_date(hasta) if hasta else None
    cuadres = []

    filtros = {}
    if inicio:
        filtros['salida__fecha_salida__gte'] = inicio
    if fin:
        filtros['salida__fecha_salida__lte'] = fin
    pagos = totales_de_pagos(
        IngresoEquipo.objects.filter(salida__isnull=False, **filtros).prefetch_related('abonos'),
    )
    ranking_a_cobrar = resumen['total_acordado'] + resumen['total_domicilio']
    cuadres.append(_cuadre(
        'Total a cobrar = Pagos',
        f"Acordado {dinero_signo(resumen['total_acordado'])} + Domicilio "
        f"{dinero_signo(resumen['total_domicilio'])} = {dinero_signo(ranking_a_cobrar)} · "
        f"Pagos: {dinero_signo(pagos['a_cobrar'])}",
        ranking_a_cobrar,
        pagos['a_cobrar'],
        'Un equipo finalizado no se está leyendo igual en el Ranking y en Pagos.',
    ))
    ranking_pagado = resumen['total_recaudado'] + resumen['total_bodegaje_cobrado']
    cuadres.append(_cuadre(
        'Total pagado = Pagos',
        f"Recaudado {dinero_signo(resumen['total_recaudado'])} + Bodegaje cobrado "
        f"{dinero_signo(resumen['total_bodegaje_cobrado'])} = {dinero_signo(ranking_pagado)} · "
        f"Pagos: {dinero_signo(pagos['pagado'])}",
        ranking_pagado,
        pagos['pagado'],
        'Algún pago de un equipo finalizado no llega al total de Pagos.',
    ))
    # Pagos descuenta del pendiente lo pagado de más y el bodegaje cobrado.
    ranking_pendiente = (
        resumen['total_por_cobrar']
        - resumen['total_a_favor']
        - resumen['total_bodegaje_cobrado']
    )
    cuadres.append(_cuadre(
        'Por cobrar = Pagos',
        f"Por cobrar {dinero_signo(resumen['total_por_cobrar'])} − A favor "
        f"{dinero_signo(resumen['total_a_favor'])} − Bodegaje cobrado "
        f"{dinero_signo(resumen['total_bodegaje_cobrado'])} = {dinero_signo(ranking_pendiente)} · "
        f"Pagos, pendiente: {dinero_signo(pagos['pendiente'])}",
        ranking_pendiente,
        pagos['pendiente'],
        'El saldo de algún equipo finalizado no coincide con el de Pagos.',
    ))

    # La Caja del período contra lo que suma la base por fechas.
    reparaciones = IngresoEquipo.objects.exclude(sede='ventas')
    ventas = IngresoEquipo.objects.filter(sede='ventas')
    caja_reparaciones = caja['reparaciones'] + caja['bodegaje']
    base_reparaciones = _pagos_por_fecha(reparaciones, inicio, fin)
    cuadres.append(_cuadre(
        'Caja: reparaciones y bodegaje = pagos del período',
        f"Caja: {dinero_signo(caja_reparaciones)} · Pagos por fecha: {dinero_signo(base_reparaciones)}",
        caja_reparaciones,
        base_reparaciones,
        'Hay un pago de reparación en la base que la Caja no está leyendo.',
    ))
    base_ventas = _pagos_por_fecha(ventas, inicio, fin)
    cuadres.append(_cuadre(
        'Caja: ventas = pagos de ventas del período',
        f"Caja: {dinero_signo(caja['ventas'])} · Pagos por fecha: {dinero_signo(base_ventas)}",
        caja['ventas'],
        base_ventas,
        'Hay un pago de venta en la base que la Caja no está leyendo.',
    ))

    # Pagos no tiene filtro de fechas: su total es de todo el historial.
    historial = {
        origen: sum((m['monto'] for m in movimientos if m['origen'] == origen), CERO)
        for origen in ('reparacion', 'venta', 'diagnostico')
    }
    pagos_reparaciones = totales_de_pagos(reparaciones.prefetch_related('abonos'))
    pagos_ventas = totales_de_pagos(ventas.prefetch_related('abonos'))
    for titulo, valor, esperado in (
        (
            'Historial: reparaciones = Total pagado de Pagos',
            historial['reparacion'],
            pagos_reparaciones['pagado'],
        ),
        (
            'Historial: ventas = Total pagado de Pagos · Ventas',
            historial['venta'],
            pagos_ventas['pagado'],
        ),
        (
            'Historial: diagnósticos inmediatos = Diagnóstico de Pagos',
            historial['diagnostico'],
            pagos_reparaciones['diagnostico'] + pagos_ventas['diagnostico'],
        ),
    ):
        cuadres.append(_cuadre(
            titulo,
            f'Caja: {dinero_signo(valor)} · Pagos: {dinero_signo(esperado)}',
            valor,
            esperado,
            'Hay un pago registrado que la Caja y Pagos leen distinto.',
        ))
    return cuadres


def _puente_ranking_caja(registros, resumen, caja, movimientos, inicio, fin):
    """
    Por qué lo cobrado de los equipos finalizados no es lo que entró a la Caja:
    el Ranking mira la fecha en que se finalizó y la Caja la fecha de cada pago.
    """
    finalizados = {registro['ingreso_id'] for registro in registros}
    de_otros_equipos = CERO
    fuera_del_periodo = CERO
    ventas = CERO
    diagnostico = CERO
    for movimiento in movimientos:
        dentro = _en_periodo(movimiento['fecha'], inicio, fin)
        if movimiento['origen'] == 'diagnostico':
            if dentro:
                diagnostico += movimiento['monto']
        elif movimiento['ingreso_id'] in finalizados:
            if not dentro:
                fuera_del_periodo += movimiento['monto']
        elif dentro:
            if movimiento['origen'] == 'venta':
                ventas += movimiento['monto']
            else:
                de_otros_equipos += movimiento['monto']

    base = resumen['total_recaudado'] + resumen['total_bodegaje_cobrado']
    calculado = base + ventas + diagnostico + de_otros_equipos - fuera_del_periodo
    return _cuadre(
        'Del Ranking a la Caja',
        f'Finalizados {dinero_signo(base)} + Ventas {dinero_signo(ventas)} + '
        f'Diagnósticos {dinero_signo(diagnostico)} + Pagos de equipos finalizados en otro período o '
        f'sin finalizar {dinero_signo(de_otros_equipos)} − Pagos de estos equipos con fecha '
        f'fuera del período {dinero_signo(fuera_del_periodo)} = {dinero_signo(calculado)} · '
        f"Entró a la Caja: {dinero_signo(caja['entro'])}",
        calculado,
        caja['entro'],
        'Hay un pago que no está ni en el Ranking ni en las otras líneas de la cuenta.',
    )


def _cuadres_de_bodegaje(registros, resumen, caja):
    cuadres = []
    equipos = [
        registro for registro in registros
        if registro['bodegaje_cobrado'] != registro['bodegaje_registrado']
    ]
    if equipos:
        registrado = sum((registro['bodegaje_registrado'] for registro in equipos), CERO)
        cobrado = sum((registro['bodegaje_cobrado'] for registro in equipos), CERO)
        causa = ' '.join(
            f"{registro['codigo']}: los abonos con bodegaje "
            f"({', '.join(registro['bodegaje_recibos']) or 'ninguno'}) suman "
            f"{dinero_signo(registro['bodegaje_cobrado'])} y la salida registra "
            f"{dinero_signo(registro['bodegaje_registrado'])}."
            for registro in equipos
        ) + ' Revisa si se cobró dos veces; pasa si se deshace y se vuelve a confirmar el retiro.'
        cuadres.append(_cuadre(
            'Bodegaje cobrado = bodegaje registrado en la salida',
            f'Abonos: {dinero_signo(cobrado)} · Salida: {dinero_signo(registrado)}',
            cobrado,
            registrado,
            causa,
        ))
    else:
        cuadres.append(_cuadre(
            'Bodegaje cobrado = bodegaje registrado en la salida',
            f"Abonos y salida: {dinero_signo(resumen['total_bodegaje_cobrado'])}",
            CERO,
            CERO,
        ))
    if resumen['total_bodegaje_cobrado'] != caja['bodegaje']:
        cuadres.append({
            'titulo': 'Bodegaje de los técnicos y bodegaje de la Caja',
            'cuenta': (
                f"Equipos finalizados en el período: {dinero_signo(resumen['total_bodegaje_cobrado'])} · "
                f"Cobrado con fecha en el período: {dinero_signo(caja['bodegaje'])}"
            ),
            'estado': AVISO,
            'diferencia': resumen['total_bodegaje_cobrado'] - caja['bodegaje'],
            'causa': (
                'No es un error: el técnico lo tiene por la fecha en que finalizó el equipo '
                'y la Caja por la fecha en que se cobró.'
            ),
        })
    return cuadres


def _aviso_saldo_a_favor(registros):
    equipos = [registro for registro in registros if registro['a_favor'] > 0]
    if not equipos:
        return []
    total = sum((registro['a_favor'] for registro in equipos), CERO)
    return [{
        'titulo': 'Clientes con saldo a favor',
        'cuenta': ' · '.join(
            f"{registro['codigo']}: {dinero_signo(registro['a_favor'])}" for registro in equipos
        ),
        'estado': AVISO,
        'diferencia': total,
        'causa': 'Pagaron más de lo que se les cobra. El dinero sí entró a la Caja.',
    }]


def _cuadres_registro_administrativo(caja):
    """Cada mes completo de la Caja contra el Registro Administrativo."""
    from .views_admin import _ingresos_dinero_mes

    cuadres = []
    for fila in caja['meses']:
        if fila['parcial']:
            continue
        registro = _ingresos_dinero_mes(fila['mes'].year, fila['mes'].month)
        cuadres.append(_cuadre(
            f"Registro Administrativo: {fila['etiqueta']}",
            f"Registro: {dinero_signo(registro['total'])} · Caja: {dinero_signo(fila['entro'])}",
            registro['total'],
            fila['entro'],
            'El Registro y la Caja no están leyendo igual los pagos de este mes.',
        ))
    return cuadres


def _cuadres_internos_caja(caja):
    return [
        _cuadre(
            'Caja: guardado antes + entró − egresos = guardado',
            f"{dinero_signo(caja['saldo_inicial'])} + {dinero_signo(caja['entro'])} − "
            f"{dinero_signo(caja['egresos'])} = {dinero_signo(caja['saldo_final'])}",
            caja['saldo_inicial'] + sum((fila['neto'] for fila in caja['meses']), CERO),
            caja['saldo_final'],
            'Los meses no suman el total de la Caja.',
        ),
        _cuadre(
            'Caja: los métodos de pago suman lo que entró',
            ' + '.join(f"{m['nombre']}: {dinero_signo(m['monto'])}" for m in caja['metodos'])
            + f" = {dinero_signo(caja['entro'])}",
            sum((m['monto'] for m in caja['metodos']), CERO),
            caja['entro'],
            'Hay un pago mixto cuyas partes no suman su total.',
        ),
    ]


def cuadres_del_periodo(desde, hasta, registros, resumen, caja, movimientos):
    """Todos los cuadres del período, primero los que necesitan atención."""
    inicio = _parse_date(desde) if desde else None
    fin = _parse_date(hasta) if hasta else None
    cuadres = [
        *_cuadres_de_pagos(desde, hasta, resumen, caja, movimientos),
        _puente_ranking_caja(registros, resumen, caja, movimientos, inicio, fin),
        *_cuadres_internos_caja(caja),
        *_cuadres_de_bodegaje(registros, resumen, caja),
        *_aviso_saldo_a_favor(registros),
        *_cuadres_registro_administrativo(caja),
    ]
    orden = {DIFERENCIA: 0, AVISO: 1, OK: 2}
    return sorted(cuadres, key=lambda cuadre: orden[cuadre['estado']])
