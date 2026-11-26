"""Reporte del día de EconoBot.

Cuenta el día calendario de Ecuador (TIME_ZONE del proyecto): a medianoche
vuelve a cero. Para cada usuario junta lo que hizo ese día:

- Equipos que registró: ingresos con «registrado por» = el usuario, creados ese día.
- Equipos que finalizó: salidas con «técnico que reparó» = el usuario y fecha
  de finalización ese día.
- Cobros que registró: anticipos y diagnósticos inmediatos de los ingresos que
  registró, abonos y pagos al finalizar que registró, con la fecha de cada pago.
  Son las mismas reglas y los mismos montos que Seguimiento de pago.

El reporte del personal (solo admin) junta lo mismo de todos los que hicieron
algo ese día.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from ..models import SEDES_EQUIPOS, Abono, IngresoEquipo, SalidaEquipo
from ..seguimiento_pago import (
    METODOS_RESUMEN, OTROS, TOTAL, _concepto_anticipo, _partes, _partes_anticipo, _partes_diagnostico,
    _partes_salida, ingresos_de_seguimiento,
)
from .equipos import descripcion_equipo
from .respuesta import enlace_url, opcion, respuesta

CERO = Decimal('0.00')
MAX_LINEAS_CHAT = 15
MAX_LINEAS_SECCION = 10
DIAS = ('lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo')
NOMBRES_METODO = {**dict(METODOS_RESUMEN), OTROS: 'Otros métodos'}
NOMBRES_METODO_CORTOS = {'transferencia': 'Transferencia', 'efectivo': 'Efectivo', 'tarjeta': 'Tarjeta', OTROS: 'Otros'}


# ─────────────────────────────────────────────────────────────────────
# Fechas y nombres
# ─────────────────────────────────────────────────────────────────────

def hoy():
    return timezone.localdate()


def fecha_larga(fecha):
    return f'{DIAS[fecha.weekday()]} {fecha:%d/%m/%Y}'


def fecha_de_texto(valor):
    """«2026-11-26» → date; vacía, inválida o futura → hoy."""
    actual = hoy()
    try:
        fecha = date.fromisoformat((valor or '').strip())
    except ValueError:
        return actual
    return fecha if fecha <= actual else actual


def nombre_corto(user):
    nombre = (user.first_name or '').strip() or user.username
    return nombre.split()[0] if nombre.split() else nombre


def nombre_completo(user):
    return (f'{user.first_name} {user.last_name}'.strip()) or user.username


def dinero(valor):
    return f'${valor:,.2f}'


# ─────────────────────────────────────────────────────────────────────
# Datos del día
# ─────────────────────────────────────────────────────────────────────

def registrados_hoy(user, fecha=None):
    """Ingresos de equipo que el usuario registró en el día (hora de Ecuador)."""
    fecha = fecha or hoy()
    return list(
        IngresoEquipo.objects
        .filter(sede__in=SEDES_EQUIPOS, registrado_por=user, creado__date=fecha)
        .select_related('cliente', 'salida')
        .order_by('creado', 'pk')
    )


def finalizados(user, fecha=None):
    """Equipos que el usuario finalizó ese día como técnico que reparó."""
    fecha = fecha or hoy()
    return [
        salida.ingreso for salida in
        SalidaEquipo.objects
        .filter(tecnico_reparo=user, fecha_salida=fecha, ingreso__sede__in=SEDES_EQUIPOS)
        .select_related('ingreso', 'ingreso__cliente')
        .order_by('creado', 'pk')
    ]


def _hora(creado, fecha):
    momento = timezone.localtime(creado) if creado else None
    return f'{momento:%H:%M}' if momento and momento.date() == fecha else ''


def _cobro(ingreso, concepto, monto, partes, creado, fecha):
    return {
        'codigo': ingreso.codigo_equipo,
        'cliente': ingreso.cliente.nombres,
        'concepto': concepto,
        'monto': monto,
        'partes': partes,
        'metodo': ' + '.join(parte['etiqueta'] for parte in partes),
        'hora': _hora(creado, fecha),
        'orden': timezone.localtime(creado).timestamp() if creado else 0.0,
    }


def cobros(user, fecha=None):
    """Pagos que el usuario registró ese día, como los cuenta Seguimiento de pago."""
    fecha = fecha or hoy()
    base = ingresos_de_seguimiento(tipo=TOTAL)
    lista = []
    for ingreso in (base.filter(registrado_por=user, fecha_ingreso=fecha)
                    .select_related('cliente').prefetch_related('abonos')):
        if ingreso.diagnostico_inmediato == 'si' and (ingreso.valor_diagnostico or CERO) > 0:
            lista.append(_cobro(ingreso, 'Diagnóstico', ingreso.valor_diagnostico,
                                _partes_diagnostico(ingreso), ingreso.creado, fecha))
        if (ingreso.abono_anticipo or CERO) > 0:
            lista.append(_cobro(ingreso, _concepto_anticipo(ingreso), ingreso.abono_anticipo,
                                _partes_anticipo(ingreso), ingreso.creado, fecha))
    for abono in (Abono.objects.filter(registrado_por=user, fecha=fecha, monto__gt=0, ingreso__in=base)
                  .select_related('ingreso', 'ingreso__cliente')):
        partes = _partes(abono.monto, abono.metodo, abono.banco, abono.banco_otro, abono.tarjeta_app)
        lista.append(_cobro(abono.ingreso, 'Abono', abono.monto, partes, abono.creado, fecha))
    for salida in (SalidaEquipo.objects
                   .filter(registrado_por=user, fecha_salida=fecha, valor_final_cobrado__gt=0, ingreso__in=base)
                   .select_related('ingreso', 'ingreso__cliente')):
        lista.append(_cobro(salida.ingreso, 'Pago al finalizar', salida.valor_final_cobrado,
                            _partes_salida(salida), salida.creado, fecha))
    lista.sort(key=lambda cobro: cobro['orden'])
    return lista


def por_metodo(lista_cobros):
    """[(clave, nombre, monto)] de lo cobrado por método, sin los que quedan en cero."""
    totales = {clave: CERO for clave in NOMBRES_METODO}
    for cobro in lista_cobros:
        for parte in cobro['partes']:
            clave = parte['metodo'] if parte['metodo'] in totales else OTROS
            totales[clave] += parte['monto']
    return [(clave, NOMBRES_METODO[clave], monto) for clave, monto in totales.items() if monto]


def datos_dia(user, fecha=None):
    fecha = fecha or hoy()
    lista_cobros = cobros(user, fecha)
    return {
        'usuario': user,
        'fecha': fecha,
        'registrados': registrados_hoy(user, fecha),
        'finalizados': finalizados(user, fecha),
        'cobros': lista_cobros,
        'total_cobrado': sum((c['monto'] for c in lista_cobros), CERO),
        'por_metodo': por_metodo(lista_cobros),
    }


def tiene_movimientos(datos):
    return bool(datos['registrados'] or datos['finalizados'] or datos['cobros'])


def usuarios_del_dia(fecha):
    """Usuarios que registraron, finalizaron o cobraron algo ese día."""
    base = ingresos_de_seguimiento(tipo=TOTAL)
    ids = set(IngresoEquipo.objects.filter(sede__in=SEDES_EQUIPOS, creado__date=fecha)
              .values_list('registrado_por', flat=True))
    ids |= set(SalidaEquipo.objects.filter(fecha_salida=fecha, ingreso__sede__in=SEDES_EQUIPOS)
               .values_list('tecnico_reparo', flat=True))
    ids |= set(base.filter(fecha_ingreso=fecha).values_list('registrado_por', flat=True))
    ids |= set(Abono.objects.filter(fecha=fecha, monto__gt=0, ingreso__in=base)
               .values_list('registrado_por', flat=True))
    ids |= set(SalidaEquipo.objects.filter(fecha_salida=fecha, valor_final_cobrado__gt=0, ingreso__in=base)
               .values_list('registrado_por', flat=True))
    ids.discard(None)
    return list(get_user_model().objects.filter(pk__in=ids).order_by('first_name', 'username'))


def datos_personal(fecha):
    """Lo de cada persona que hizo algo ese día, con los totales del día."""
    personas = [d for d in (datos_dia(u, fecha) for u in usuarios_del_dia(fecha)) if tiene_movimientos(d)]
    todos_los_cobros = [c for d in personas for c in d['cobros']]
    return {
        'fecha': fecha,
        'personas': personas,
        'registrados': sum(len(d['registrados']) for d in personas),
        'finalizados': sum(len(d['finalizados']) for d in personas),
        'cobros': len(todos_los_cobros),
        'total_cobrado': sum((c['monto'] for c in todos_los_cobros), CERO),
        'por_metodo': por_metodo(todos_los_cobros),
    }


# ─────────────────────────────────────────────────────────────────────
# Textos
# ─────────────────────────────────────────────────────────────────────

def estado_texto(ingreso):
    """Estado como lo ve el sistema, con su detalle si lo tiene."""
    estado = ingreso.estado_visual_display
    detalle = ingreso.subestado_visual_display
    if detalle and detalle.lower() != estado.lower():
        return f'{estado} ({detalle})'
    return estado


def hora_registro(ingreso):
    return f'{timezone.localtime(ingreso.creado):%H:%M}'


def _plural(cantidad, palabra):
    return f'{cantidad} {palabra}{"s" if cantidad != 1 else ""}'


def texto_metodos(lista):
    return ' · '.join(f'{NOMBRES_METODO_CORTOS.get(clave, nombre)} {dinero(monto)}' for clave, nombre, monto in lista)


def texto_corto(datos):
    """«Registraste 2 equipos · finalizaste 1 equipo · cobraste $85.00 (3 cobros)»."""
    partes = []
    if datos['registrados']:
        partes.append(f'registraste {_plural(len(datos["registrados"]), "equipo")}')
    if datos['finalizados']:
        partes.append(f'finalizaste {_plural(len(datos["finalizados"]), "equipo")}')
    if datos['cobros']:
        partes.append(f'cobraste {dinero(datos["total_cobrado"])} ({_plural(len(datos["cobros"]), "cobro")})')
    texto = ' · '.join(partes)
    return texto[:1].upper() + texto[1:]


def _recortar(lineas, total, maximo):
    if total > maximo:
        lineas.append(f'  … y {total - maximo} más. El PDF los muestra todos.')


def url_pdf_dia(fecha):
    return f'{reverse("econotec:econobot_reporte_dia_pdf")}?fecha={fecha.isoformat()}'


def url_pdf_personal(fecha):
    return f'{reverse("econotec:econobot_reporte_personal_pdf")}?fecha={fecha.isoformat()}'


def _titulo_dia(fecha):
    if fecha == hoy():
        return f'📋 Tu reporte de hoy ({fecha_larga(fecha)}):'
    return f'📋 Tu reporte del {fecha_larga(fecha)}:'


def resumen(user, saludo=True, presentar=False, fecha=None):
    """Mensaje del chat con el reporte del día y el enlace al PDF.

    presentar=True agrega quién es EconoBot (chat vacío, primera vez).
    """
    fecha = fecha or hoy()
    datos = datos_dia(user, fecha)
    lineas = []
    if saludo:
        lineas.append(f'Hola, ¿qué tal, {nombre_corto(user)}? 👋')
    if presentar:
        lineas.append('Soy EconoBot, tu asistente de Econotec. Escribe lo que necesitas o un código como G1031.')
    lineas.append(_titulo_dia(fecha))
    if not tiene_movimientos(datos):
        if fecha == hoy():
            lineas.append('Todavía no tienes nada hoy: ni equipos registrados, ni finalizados, ni cobros. '
                          'Cuando hagas algo, aparecerá aquí con su estado.')
        else:
            lineas.append('Ese día no registraste equipos, ni finalizaste, ni cobraste.')
        return respuesta('\n'.join(lineas), opciones=[opcion('📥 Registrar equipo', 'registrar equipo')])

    registrados = datos['registrados']
    if registrados:
        lineas.append(f'📥 Registraste {_plural(len(registrados), "equipo")}:')
        for ingreso in registrados[:MAX_LINEAS_CHAT]:
            lineas.append(f'• {ingreso.codigo_equipo} — {descripcion_equipo(ingreso)} · {ingreso.cliente.nombres}'
                          f' · {estado_texto(ingreso)} · {hora_registro(ingreso)}')
        _recortar(lineas, len(registrados), MAX_LINEAS_CHAT)
    if datos['finalizados']:
        lineas.append(f'🔧 Finalizaste {_plural(len(datos["finalizados"]), "equipo")}:')
        for ingreso in datos['finalizados'][:MAX_LINEAS_SECCION]:
            lineas.append(f'• {ingreso.codigo_equipo} — {descripcion_equipo(ingreso)} · {ingreso.cliente.nombres}'
                          f' · {estado_texto(ingreso)}')
        _recortar(lineas, len(datos['finalizados']), MAX_LINEAS_SECCION)
    if datos['cobros']:
        lineas.append(f'💵 Registraste {_plural(len(datos["cobros"]), "cobro")} por {dinero(datos["total_cobrado"])}:')
        for cobro in datos['cobros'][:MAX_LINEAS_SECCION]:
            lineas.append(f'• {cobro["codigo"]} · {cobro["concepto"]} · {dinero(cobro["monto"])} · {cobro["metodo"]}'
                          + (f' · {cobro["hora"]}' if cobro['hora'] else ''))
        _recortar(lineas, len(datos['cobros']), MAX_LINEAS_SECCION)
        lineas.append(f'Por método: {texto_metodos(datos["por_metodo"])}')

    codigos = list(dict.fromkeys(i.codigo_equipo for i in registrados + datos['finalizados']))
    return respuesta(
        '\n'.join(lineas),
        [enlace_url('📄 Ver reporte del día en PDF', url_pdf_dia(fecha), tipo='nueva')],
        [opcion(f'Ver {codigo}', f'ver {codigo}') for codigo in codigos[:6]],
    )


def resumen_personal(fecha=None):
    """Reporte del personal para el admin: una línea por persona y los totales."""
    fecha = fecha or hoy()
    datos = datos_personal(fecha)
    if fecha == hoy():
        lineas = [f'👥 Reporte del personal de hoy ({fecha_larga(fecha)}):']
    else:
        lineas = [f'👥 Reporte del personal del {fecha_larga(fecha)}:']
    opciones = [opcion('📅 Reporte del personal de ayer', 'reporte del personal de ayer')] if fecha == hoy() else [
        opcion('📅 Reporte del personal de hoy', 'reporte del personal')]
    if not datos['personas']:
        lineas.append('Nadie registró, finalizó ni cobró equipos ese día.')
        return respuesta('\n'.join(lineas), opciones=opciones)
    for persona in datos['personas']:
        partes = [f'registró {len(persona["registrados"])}', f'finalizó {len(persona["finalizados"])}']
        if persona['cobros']:
            partes.append(f'cobró {dinero(persona["total_cobrado"])} ({_plural(len(persona["cobros"]), "cobro")})')
        else:
            partes.append('sin cobros')
        lineas.append(f'• {nombre_completo(persona["usuario"])}: ' + ' · '.join(partes))
    lineas.append(f'Total: {_plural(datos["registrados"], "registrado")} · {_plural(datos["finalizados"], "finalizado")}'
                  f' · {dinero(datos["total_cobrado"])} cobrados')
    if datos['por_metodo']:
        lineas.append(f'Por método: {texto_metodos(datos["por_metodo"])}')
    return respuesta(
        '\n'.join(lineas),
        [enlace_url('📄 Ver reporte del personal en PDF', url_pdf_personal(fecha), tipo='nueva')],
        opciones,
    )


def ayer():
    return hoy() - timedelta(days=1)
