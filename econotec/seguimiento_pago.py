"""
Seguimiento de pago: hoja semanal con lo que se cobró de los equipos.

- La hoja va de lunes 00:00 a domingo 23:59, hora de Ecuador. El lunes a las
  00:00 empieza una hoja nueva y las semanas anteriores quedan como pestañas.
- Cada pago cuenta en la semana de su fecha, igual que en el Registro
  Administrativo: anticipo y diagnóstico inmediato (fecha de ingreso), abonos
  (fecha del abono) y el pago al finalizar (fecha de finalización).
- Solo equipos del taller (Guayaquil y Quito): no incluye ventas de producto,
  donados ni equipos a comprar, que no son cobros a clientes.
- Una fila por equipo, con sus pagos de la semana y el saldo que el cliente
  todavía debe hoy (el mismo de Pagos).
- Los pagos mixtos se separan en sus dos métodos para los totales de arriba.
"""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Prefetch, Q
from django.urls import reverse
from django.utils import timezone

from .models import SEDES_EQUIPOS, Abono, IngresoEquipo, SalidaEquipo

CERO = Decimal('0.00')

# Estados administrativos: no son cobros a clientes.
ESTADOS_SIN_COBRO = ('donado', 'equipo_a_comprar')

# Tarjetas del resumen, en el orden en que se muestran.
METODOS_RESUMEN = (
    ('transferencia', 'Transferencia bancaria'),
    ('efectivo', 'Efectivo'),
    ('tarjeta', 'Tarjeta de crédito / Payphone'),
)
OTROS = 'otros'

BANCOS = dict(IngresoEquipo.BANCOS)
TARJETAS_APPS = dict(IngresoEquipo.TARJETAS_APPS)
METODOS = {**dict(SalidaEquipo.METODOS_PAGO_FINAL), **dict(Abono.METODOS_PAGO)}

DIAS = ('lun', 'mar', 'mié', 'jue', 'vie', 'sáb', 'dom')
DIAS_LARGOS = ('lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo')
MESES = (
    'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio',
    'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre',
)


def inicio_semana(dia):
    """Lunes de la semana de `dia`: ahí empieza su hoja."""
    return dia - timedelta(days=dia.weekday())


def fin_semana(lunes):
    # La última semana del calendario termina antes del domingo.
    if (date.max - lunes).days < 6:
        return date.max
    return lunes + timedelta(days=6)


def etiqueta_semana(lunes):
    """«12 – 18 oct», «28 sep – 4 oct» o «29 dic 2025 – 4 ene 2026»."""
    domingo = fin_semana(lunes)
    if lunes.year != domingo.year:
        return (
            f'{lunes.day} {MESES[lunes.month - 1][:3]} {lunes.year} – '
            f'{domingo.day} {MESES[domingo.month - 1][:3]} {domingo.year}'
        )
    if lunes.month != domingo.month:
        return f'{lunes.day} {MESES[lunes.month - 1][:3]} – {domingo.day} {MESES[domingo.month - 1][:3]}'
    return f'{lunes.day} – {domingo.day} {MESES[domingo.month - 1][:3]}'


def titulo_semana(lunes):
    """«del lunes 12 al domingo 18 de octubre de 2026»."""
    domingo = fin_semana(lunes)
    final = f'domingo {domingo.day} de {MESES[domingo.month - 1]} de {domingo.year}'
    if lunes.year != domingo.year:
        return f'del lunes {lunes.day} de {MESES[lunes.month - 1]} de {lunes.year} al {final}'
    if lunes.month != domingo.month:
        return f'del lunes {lunes.day} de {MESES[lunes.month - 1]} al {final}'
    return f'del lunes {lunes.day} al {final}'


def fecha_larga(dia):
    """«lunes 19 de octubre»."""
    return f'{DIAS_LARGOS[dia.weekday()]} {dia.day} de {MESES[dia.month - 1]}'


def nombre_usuario(user):
    if not user:
        return ''
    return user.get_full_name() or user.username


def ingresos_de_seguimiento(sede=''):
    """Equipos del taller que cuentan en el seguimiento, de una sede o de las dos."""
    qs = IngresoEquipo.objects.filter(sede__in=SEDES_EQUIPOS).exclude(estado__in=ESTADOS_SIN_COBRO)
    if sede:
        qs = qs.filter(sede=sede)
    return qs


# ─────────────────────────────────────────────────────────
# Partes de un pago (método, detalle y monto)
# ─────────────────────────────────────────────────────────

def _parte(metodo, monto, banco='', banco_otro='', tarjeta_app=''):
    """Una parte de un pago.

    `etiqueta` es lo que se lee en la tabla y `detalle` agrupa dentro de su
    tarjeta de arriba (el banco de la transferencia o la app de la tarjeta).
    """
    if metodo == 'transferencia':
        if banco == 'otro':
            banco_txt = (banco_otro or '').strip() or BANCOS['otro']
        else:
            banco_txt = BANCOS.get(banco, '')
        etiqueta = f'Transferencia · {banco_txt}' if banco_txt else 'Transferencia'
        return {'metodo': 'transferencia', 'etiqueta': etiqueta, 'detalle': banco_txt or 'Sin banco', 'monto': monto}
    if metodo == 'efectivo':
        return {'metodo': 'efectivo', 'etiqueta': 'Efectivo', 'detalle': '', 'monto': monto}
    if metodo == 'tarjeta':
        app = TARJETAS_APPS.get(tarjeta_app, '')
        etiqueta = f'Tarjeta · {app}' if app else 'Tarjeta de crédito / débito'
        return {'metodo': 'tarjeta', 'etiqueta': etiqueta, 'detalle': app or 'Tarjeta', 'monto': monto}
    nombre = METODOS.get(metodo) or 'Sin método'
    return {'metodo': OTROS, 'etiqueta': nombre, 'detalle': nombre, 'monto': monto}


def _partes(total, metodo, banco='', banco_otro='', tarjeta_app='', mixto=()):
    """Partes de un pago; el mixto se separa en sus dos métodos.

    `mixto` son las tuplas (monto, método, banco) de cada parte. Si las partes
    no suman el total, el pago se cuenta entero en «Otros» para que las
    tarjetas de arriba sigan sumando el total de la semana.
    """
    if metodo != 'mixto':
        return [_parte(metodo, total, banco, banco_otro, tarjeta_app)]
    partes = [_parte(m, monto, b) for monto, m, b in mixto if monto]
    if partes and sum((p['monto'] for p in partes), CERO) == total:
        return partes
    return [{'metodo': OTROS, 'etiqueta': 'Pago mixto', 'detalle': 'Pago mixto', 'monto': total}]


def _partes_diagnostico(ingreso):
    return _partes(
        ingreso.valor_diagnostico, ingreso.diagnostico_metodo,
        ingreso.diagnostico_banco, ingreso.diagnostico_banco_otro, ingreso.diagnostico_tarjeta_app,
        mixto=(
            (ingreso.diagnostico_monto_1, ingreso.diagnostico_metodo_1, ingreso.diagnostico_banco_1),
            (ingreso.diagnostico_monto_2, ingreso.diagnostico_metodo_2, ingreso.diagnostico_banco_2),
        ),
    )


def _partes_anticipo(ingreso):
    return _partes(
        ingreso.abono_anticipo, ingreso.anticipo_metodo,
        ingreso.anticipo_banco, ingreso.anticipo_banco_otro, ingreso.anticipo_tarjeta_app,
        mixto=(
            (ingreso.anticipo_monto_1, ingreso.anticipo_metodo_1, ingreso.anticipo_banco_1),
            (ingreso.anticipo_monto_2, ingreso.anticipo_metodo_2, ingreso.anticipo_banco_2),
        ),
    )


def _partes_salida(salida):
    return _partes(
        salida.valor_final_cobrado, salida.metodo_pago_final,
        salida.banco, salida.banco_otro, salida.tarjeta_app,
        mixto=(
            (salida.monto_1, salida.metodo_1, salida.banco_1),
            (salida.monto_2, salida.metodo_2, salida.banco_2),
        ),
    )


# ─────────────────────────────────────────────────────────
# Pagos de un equipo dentro de la semana
# ─────────────────────────────────────────────────────────

def _cobro(concepto, fecha, creado, monto, partes, recibo=''):
    momento = timezone.localtime(creado) if creado else None
    return {
        'concepto': concepto,
        'fecha': fecha,
        'dia': f'{DIAS[fecha.weekday()]} {fecha:%d/%m}',
        # La hora solo cuando el registro se hizo el mismo día del pago.
        'hora': momento if momento and momento.date() == fecha else None,
        'orden': (fecha, momento.timestamp() if momento else 0.0),
        'monto': monto,
        'partes': partes,
        'recibo': recibo or '',
    }


def _cobros_del_equipo(ingreso, lunes, domingo):
    """Pagos del equipo con fecha dentro de la semana, del más antiguo al más nuevo."""
    cobros = []
    if lunes <= ingreso.fecha_ingreso <= domingo:
        if ingreso.diagnostico_inmediato == 'si' and (ingreso.valor_diagnostico or CERO) > 0:
            cobros.append(_cobro(
                'Diagnóstico', ingreso.fecha_ingreso, ingreso.creado, ingreso.valor_diagnostico,
                _partes_diagnostico(ingreso),
            ))
        if (ingreso.abono_anticipo or CERO) > 0:
            cobros.append(_cobro(
                'Anticipo', ingreso.fecha_ingreso, ingreso.creado, ingreso.abono_anticipo,
                _partes_anticipo(ingreso),
            ))
    for abono in ingreso.abonos.all():
        if lunes <= abono.fecha <= domingo and abono.monto > 0:
            cobros.append(_cobro(
                'Abono', abono.fecha, abono.creado, abono.monto,
                _partes(abono.monto, abono.metodo, abono.banco, abono.banco_otro, abono.tarjeta_app),
                abono.numero_recibo,
            ))
    salida = getattr(ingreso, 'salida', None)
    if (
        salida is not None
        and (salida.valor_final_cobrado or CERO) > 0
        and lunes <= salida.fecha_salida <= domingo
    ):
        cobros.append(_cobro(
            'Pago al finalizar', salida.fecha_salida, salida.creado, salida.valor_final_cobrado,
            _partes_salida(salida), salida.numero_recibo,
        ))
    cobros.sort(key=lambda cobro: cobro['orden'])
    return cobros


def _saldo(ingreso):
    """(estado, monto) de lo que el cliente todavía debe hoy, como en Pagos."""
    if ingreso.estado == 'cortesia' and not ingreso.valor_domicilio_aplicable:
        return 'cortesia', CERO
    if ingreso.valor_acordado is None and not ingreso.reparacion_cancelada:
        # Sin valor acordado todavía no se sabe cuánto debe.
        return 'sin_valor', CERO
    saldo = ingreso.diferencia
    return ('debe' if saldo > 0 else 'pagado'), saldo


def _tecnicos(ingreso, salida):
    """El técnico que reparó (si ya se finalizó) y el asignado al ingreso."""
    tecnicos = []
    reparo = salida.tecnico_reparo if salida is not None else None
    if reparo:
        tecnicos.append({'nombre': nombre_usuario(reparo), 'rol': 'Reparó'})
    asignado = ingreso.tecnico_encargado
    if asignado and (reparo is None or asignado.pk != reparo.pk):
        tecnicos.append({'nombre': nombre_usuario(asignado), 'rol': 'Asignado'})
    return tecnicos


def _fila(ingreso, cobros):
    salida = getattr(ingreso, 'salida', None)
    saldo_estado, saldo = _saldo(ingreso)
    equipo = ' '.join(filter(None, [ingreso.marca, ingreso.modelo_serie]))
    return {
        'pk': ingreso.pk,
        'codigo': ingreso.codigo_equipo,
        'tipo_equipo': ingreso.tipo_equipo_display,
        'equipo': equipo,
        'cliente': ingreso.cliente.nombres,
        'cedula': ingreso.cliente.cedula,
        'cobros': cobros,
        'monto': sum((cobro['monto'] for cobro in cobros), CERO),
        'saldo_estado': saldo_estado,
        'saldo': saldo,
        # Si pagó de más, el saldo queda a su favor.
        'a_favor': -saldo if saldo < 0 else CERO,
        'bodegaje': ingreso.bodegaje_pendiente if saldo_estado != 'cortesia' else CERO,
        'fecha_ingreso': ingreso.fecha_ingreso,
        'registra': nombre_usuario(ingreso.registrado_por),
        'registrado_en': timezone.localtime(ingreso.creado) if ingreso.creado else None,
        'tecnicos': _tecnicos(ingreso, salida),
        'url_pagos': reverse('econotec:ingreso_abonos', args=[ingreso.pk]),
    }


# ─────────────────────────────────────────────────────────
# Hoja de una semana
# ─────────────────────────────────────────────────────────

def _resumen_metodos(filas):
    """Tarjetas de arriba: Transferencia, Efectivo, Tarjeta/Payphone y, si hay, Otros."""
    tarjetas = {
        clave: {'clave': clave, 'nombre': nombre, 'monto': CERO, 'pagos': 0, 'detalle': defaultdict(Decimal)}
        for clave, nombre in (*METODOS_RESUMEN, (OTROS, 'Otros métodos'))
    }
    for fila in filas:
        for cobro in fila['cobros']:
            for parte in cobro['partes']:
                tarjeta = tarjetas.get(parte['metodo'], tarjetas[OTROS])
                tarjeta['monto'] += parte['monto']
                tarjeta['pagos'] += 1
                if parte['detalle']:
                    tarjeta['detalle'][parte['detalle']] += parte['monto']
    resumen = [tarjetas[clave] for clave, _ in METODOS_RESUMEN]
    if tarjetas[OTROS]['pagos']:
        resumen.append(tarjetas[OTROS])
    for tarjeta in resumen:
        tarjeta['detalle'] = sorted(tarjeta['detalle'].items(), key=lambda item: (-item[1], item[0]))
    return resumen


def hoja_semana(lunes, sede=''):
    """Filas y totales por método de la semana que empieza en `lunes`."""
    domingo = fin_semana(lunes)
    base = ingresos_de_seguimiento(sede)

    ids = set(
        base.filter(fecha_ingreso__range=(lunes, domingo))
        .filter(Q(abono_anticipo__gt=0) | Q(diagnostico_inmediato='si', valor_diagnostico__gt=0))
        .values_list('pk', flat=True)
    )
    ids.update(
        Abono.objects.filter(ingreso__in=base, fecha__range=(lunes, domingo), monto__gt=0)
        .values_list('ingreso_id', flat=True)
    )
    ids.update(
        SalidaEquipo.objects.filter(
            ingreso__in=base, fecha_salida__range=(lunes, domingo), valor_final_cobrado__gt=0,
        ).values_list('ingreso_id', flat=True)
    )

    ingresos = (
        IngresoEquipo.objects.filter(pk__in=ids)
        .select_related('cliente', 'registrado_por', 'tecnico_encargado', 'salida', 'salida__tecnico_reparo')
        .prefetch_related(Prefetch('abonos', queryset=Abono.objects.order_by('fecha', 'creado', 'pk')))
    )
    filas = []
    for ingreso in ingresos:
        cobros = _cobros_del_equipo(ingreso, lunes, domingo)
        if cobros:
            filas.append(_fila(ingreso, cobros))
    filas.sort(key=lambda fila: (*fila['cobros'][0]['orden'], fila['pk']))
    for numero, fila in enumerate(filas, 1):
        fila['numero'] = numero

    return {
        'lunes': lunes,
        'domingo': domingo,
        'filas': filas,
        'total': sum((fila['monto'] for fila in filas), CERO),
        'cantidad': len(filas),
        'pagos': sum(len(fila['cobros']) for fila in filas),
        'saldo_total': sum((fila['saldo'] for fila in filas if fila['saldo_estado'] == 'debe'), CERO),
        'metodos': _resumen_metodos(filas),
    }


# ─────────────────────────────────────────────────────────
# Pestañas: una hoja por semana
# ─────────────────────────────────────────────────────────

def totales_por_semana(sede=''):
    """{lunes: {'cantidad': equipos con pagos, 'total': monto}} de todas las semanas.

    Usa las mismas reglas que `hoja_semana`, así el total de cada pestaña es el
    mismo que se ve al abrirla.
    """
    semanas = defaultdict(lambda: {'equipos': set(), 'total': CERO})

    def sumar(ingreso_id, fecha, monto):
        if fecha and monto and monto > 0:
            semana = semanas[inicio_semana(fecha)]
            semana['equipos'].add(ingreso_id)
            semana['total'] += monto

    base = ingresos_de_seguimiento(sede)
    for pk, fecha, anticipo, inmediato, diagnostico in base.values_list(
        'pk', 'fecha_ingreso', 'abono_anticipo', 'diagnostico_inmediato', 'valor_diagnostico',
    ):
        sumar(pk, fecha, anticipo)
        if inmediato == 'si':
            sumar(pk, fecha, diagnostico)
    for ingreso_id, fecha, monto in Abono.objects.filter(ingreso__in=base).values_list(
        'ingreso_id', 'fecha', 'monto',
    ):
        sumar(ingreso_id, fecha, monto)
    for ingreso_id, fecha, monto in SalidaEquipo.objects.filter(
        ingreso__in=base, valor_final_cobrado__gt=0,
    ).values_list('ingreso_id', 'fecha_salida', 'valor_final_cobrado'):
        sumar(ingreso_id, fecha, monto)

    return {
        lunes: {'cantidad': len(datos['equipos']), 'total': datos['total']}
        for lunes, datos in semanas.items()
    }


def pestanas_semanas(totales, actual, seleccionada):
    """Una pestaña por semana con pagos (más la actual y la abierta), de la más
    nueva a la más antigua, y las mismas agrupadas por mes para el menú."""
    semanas = dict(totales)
    for lunes in (actual, seleccionada):
        semanas.setdefault(lunes, {'cantidad': 0, 'total': CERO})
    pestanas = [
        {
            'lunes': lunes,
            'iso': lunes.isoformat(),
            'etiqueta': etiqueta_semana(lunes),
            'titulo': titulo_semana(lunes),
            'cantidad': datos['cantidad'],
            'total': datos['total'],
            'activa': lunes == seleccionada,
            'actual': lunes == actual,
            'futura': lunes > actual,
        }
        for lunes, datos in sorted(semanas.items(), reverse=True)
    ]
    meses = []
    for pestana in pestanas:
        mes = pestana['lunes'].replace(day=1)
        if not meses or meses[-1]['mes'] != mes:
            meses.append({
                'mes': mes,
                'nombre': f'{MESES[mes.month - 1].capitalize()} {mes.year}',
                'pestanas': [],
            })
        meses[-1]['pestanas'].append(pestana)
    return pestanas, meses
