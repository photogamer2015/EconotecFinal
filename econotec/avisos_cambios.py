"""
Avisos al admin (campanita 🔔) de lo que hacen técnicos y asesoras.

Todo lo que entra a la bitácora llega aquí solo (ver bitacora.registrar_bitacora).
Las acciones que no pasan por la bitácora (observaciones, inventario, productos
de una venta, salida física y alertas silenciadas) llaman a avisar_cambio.
No se avisa lo que hace un administrador ni los inicios y cierres de sesión.
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
