"""Reporte del día de EconoBot: los equipos que el usuario registró hoy.

Cuenta el día calendario de Ecuador (TIME_ZONE del proyecto): a medianoche
vuelve a cero. Solo entran los ingresos de equipo cuyo «registrado por» es el
usuario y que se crearon hoy, con su estado actual.
"""
from django.utils import timezone

from ..models import IngresoEquipo, SEDES_EQUIPOS
from .equipos import descripcion_equipo
from .respuesta import enlace, opcion, respuesta

MAX_LINEAS_CHAT = 15
DIAS = ('lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo')


def hoy():
    return timezone.localdate()


def fecha_larga(fecha):
    return f'{DIAS[fecha.weekday()]} {fecha:%d/%m/%Y}'


def nombre_corto(user):
    nombre = (user.first_name or '').strip() or user.username
    return nombre.split()[0] if nombre.split() else nombre


def registrados_hoy(user, fecha=None):
    """Ingresos de equipo que el usuario registró en el día (hora de Ecuador)."""
    fecha = fecha or hoy()
    return list(
        IngresoEquipo.objects
        .filter(sede__in=SEDES_EQUIPOS, registrado_por=user, creado__date=fecha)
        .select_related('cliente', 'salida')
        .order_by('creado', 'pk')
    )


def estado_texto(ingreso):
    """Estado como lo ve el sistema, con su detalle si lo tiene."""
    estado = ingreso.estado_visual_display
    detalle = ingreso.subestado_visual_display
    if detalle and detalle.lower() != estado.lower():
        return f'{estado} ({detalle})'
    return estado


def hora_registro(ingreso):
    return f'{timezone.localtime(ingreso.creado):%H:%M}'


def resumen(user, saludo=True, presentar=False):
    """Mensaje del chat con el reporte del día y el enlace al PDF.

    presentar=True agrega quién es EconoBot (chat vacío, primera vez).
    """
    fecha = hoy()
    ingresos = registrados_hoy(user, fecha)
    lineas = []
    if saludo:
        lineas.append(f'Hola, ¿qué tal, {nombre_corto(user)}? 👋')
    if presentar:
        lineas.append('Soy EconoBot, tu asistente de Econotec. Escribe lo que necesitas o un código como G1031.')
    lineas.append(f'📋 Tu reporte de hoy ({fecha_larga(fecha)}):')
    if not ingresos:
        lineas.append('Todavía no has registrado equipos hoy. Cuando registres uno, aparecerá aquí con su estado.')
        return respuesta('\n'.join(lineas), opciones=[opcion('📥 Registrar equipo', 'registrar equipo')])

    total = len(ingresos)
    lineas.append(f'Registraste {total} equipo{"s" if total != 1 else ""}:')
    for ingreso in ingresos[:MAX_LINEAS_CHAT]:
        lineas.append(f'• {ingreso.codigo_equipo} — {descripcion_equipo(ingreso)} · {ingreso.cliente.nombres}'
                      f' · {estado_texto(ingreso)} · {hora_registro(ingreso)}')
    if total > MAX_LINEAS_CHAT:
        restantes = total - MAX_LINEAS_CHAT
        lineas.append(f'… y {restantes} más. El PDF los muestra todos.')
    return respuesta(
        '\n'.join(lineas),
        [enlace('📄 Ver reporte del día en PDF', 'econobot_reporte_dia_pdf', tipo='nueva')],
        [opcion(f'Ver {i.codigo_equipo}', f'ver {i.codigo_equipo}') for i in ingresos[:6]],
    )
