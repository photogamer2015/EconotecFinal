"""Arqueo del efectivo de una oficina al cerrar el día.

El efectivo esperado es lo cobrado en efectivo ese día en la oficina, con las
mismas reglas de Seguimiento de pago: anticipo y diagnóstico inmediato con la
fecha de ingreso, abonos con su fecha y pago al finalizar con la fecha de
finalización. Entran los equipos de la sede y las ventas que salieron de su
bodega. Los pagos mixtos cuentan solo su parte en efectivo.

Al efectivo cobrado se le restan los egresos de ese día pagados en efectivo
desde la oficina (en mixto, solo su parte en efectivo). Los egresos «General»
o sin oficina (los viejos) no salen de ninguna caja y no se restan.
"""
from decimal import Decimal

from django.db.models import Q

from .models import Egreso
from .seguimiento_pago import TOTAL, _cobros_del_equipo, ingresos_de_seguimiento

CERO = Decimal('0.00')
NOMBRES_METODO = {
    'efectivo': 'Efectivo',
    'transferencia': 'Transferencia',
    'tarjeta': 'Tarjeta / Payphone',
    'otros': 'Otros métodos',
}


def cobros_del_dia(fecha, sede):
    """Cada pago del día en la oficina, con su parte en efectivo."""
    base = ingresos_de_seguimiento(sede, TOTAL)
    ingresos = (
        base.filter(Q(fecha_ingreso=fecha) | Q(abonos__fecha=fecha) | Q(salida__fecha_salida=fecha))
        .distinct()
        .select_related('cliente', 'salida')
        .prefetch_related('abonos')
    )
    filas = []
    for ingreso in ingresos:
        for cobro in _cobros_del_equipo(ingreso, fecha, fecha):
            efectivo = sum((p['monto'] for p in cobro['partes'] if p['metodo'] == 'efectivo'), CERO)
            filas.append({
                'codigo': ingreso.codigo_equipo,
                'cliente': ingreso.cliente.nombres,
                'concepto': cobro['concepto'],
                'hora': cobro['hora'],
                'monto': cobro['monto'],
                'efectivo': efectivo,
                'partes': cobro['partes'],
                'metodo': ' + '.join(p['etiqueta'] for p in cobro['partes']),
                'orden': cobro['orden'],
            })
    filas.sort(key=lambda fila: fila['orden'])
    return filas


def egresos_efectivo_del_dia(fecha, sede):
    """Egresos del día de la oficina con alguna parte pagada en efectivo."""
    egresos = (
        Egreso.objects.filter(fecha=fecha, sede=sede, metodo__in=('efectivo', 'mixto'))
        .select_related('categoria')
        .order_by('creado')
    )
    return [egreso for egreso in egresos if egreso.monto_efectivo > 0]


def efectivo_del_dia(fecha, sede):
    """Efectivo que debería haber en la caja de la oficina ese día.

    'efectivo' es lo cobrado en efectivo menos los egresos en efectivo;
    'cobrado' y 'egresos_total' son las dos partes por separado.
    """
    filas = cobros_del_dia(fecha, sede)
    egresos = egresos_efectivo_del_dia(fecha, sede)
    egresos_total = sum((egreso.monto_efectivo for egreso in egresos), CERO)
    por_metodo = {clave: CERO for clave in NOMBRES_METODO}
    for fila in filas:
        for parte in fila['partes']:
            clave = parte['metodo'] if parte['metodo'] in por_metodo else 'otros'
            por_metodo[clave] += parte['monto']
    return {
        'efectivo': por_metodo['efectivo'] - egresos_total,
        'cobrado': por_metodo['efectivo'],
        'egresos': egresos,
        'egresos_total': egresos_total,
        'cobros_efectivo': [fila for fila in filas if fila['efectivo'] > 0],
        'por_metodo': [
            {'clave': clave, 'nombre': nombre, 'monto': por_metodo[clave]}
            for clave, nombre in NOMBRES_METODO.items()
            if clave != 'otros' or por_metodo[clave]
        ],
        'total': sum((fila['monto'] for fila in filas), CERO),
        'cobros': len(filas),
    }
