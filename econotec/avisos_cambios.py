"""
Avisos al admin (campanita 🔔) de lo que hacen técnicos y asesoras.

Todo lo que entra a la bitácora llega aquí solo (ver bitacora.registrar_bitacora).
Las acciones que no pasan por la bitácora (observaciones, inventario, productos
de una venta, salida física y alertas silenciadas) llaman a avisar_cambio.
No se avisa lo que hace un administrador ni los inicios y cierres de sesión,
salvo los egresos registrados desde Seguimiento de pago (avisar_egreso), que
siempre llegan a la campanita.
"""
from .models import NotificacionCambioAdmin

TIPOS_SIN_AVISO = ('login', 'logout')


def avisar_cambio(user, tipo, mensaje, *, ingreso=None, codigo='', url=''):
    if not user or not user.is_authenticated or user.is_superuser or tipo in TIPOS_SIN_AVISO:
        return None
    return NotificacionCambioAdmin.objects.create(
        creado_por=user,
        usuario_nombre=user.get_full_name() or user.username,
        tipo=tipo,
        mensaje=mensaje,
        codigo=codigo or (ingreso.codigo_equipo if ingreso else ''),
        ingreso=ingreso,
        url=url,
    )


def avisar_egreso(user, egreso, saldo, url=''):
    """Aviso 🔔 de un egreso registrado desde Seguimiento de pago.

    Llega aunque lo registre un administrador: así queda constancia de cada
    salida de dinero. `saldo` es el de la semana ya con este egreso restado.
    """
    from .templatetags.econotec_extras import dinero_signo

    asesora = (egreso.asesora.get_full_name() or egreso.asesora.username) if egreso.asesora else '—'
    disponible = saldo['disponible']
    disponible_txt = f'−{dinero_signo(-disponible)}' if disponible < 0 else dinero_signo(disponible)
    return NotificacionCambioAdmin.objects.create(
        creado_por=user,
        usuario_nombre=(user.get_full_name() or user.username) if user else '',
        tipo='egreso_seguimiento',
        mensaje=(
            f'Registró un egreso de {dinero_signo(egreso.monto)}: {egreso.concepto} '
            f'({egreso.fecha:%d/%m/%Y}), aplicado por {asesora}. Categoría: {egreso.categoria.nombre}. '
            f'Saldo disponible de la semana {saldo["etiqueta"]}: {disponible_txt}.'
        ),
        codigo='Egreso',
        url=url,
    )
