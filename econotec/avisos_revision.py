"""
Avisos al admin sobre equipos en Revisión (campanita 🔎 de la barra superior):

- cuando se aplica una subcategoría (Equipo de prueba, No se pudo reparar o
  Cliente no quiso reparar),
- cuando se escribe una observación en un equipo que sigue en Revisión,
- cuando un Equipo de prueba lleva DIAS_ALERTA_EQUIPO_PRUEBA días o más.
"""
from datetime import timedelta

from django.utils import timezone

from .models import NotificacionRevisionAdmin, SalidaEquipo

DIAS_ALERTA_EQUIPO_PRUEBA = 5


def _nombre(user):
    if not user:
        return 'Alguien'
    return (f'{user.first_name} {user.last_name}'.strip()) or user.username


def salida_en_revision(ingreso):
    """La salida del equipo si sigue en Revisión dentro de la oficina."""
    salida = getattr(ingreso, 'salida', None)
    if salida is not None and salida.en_revision:
        return salida
    return None


def avisar_subcategoria(salida, user):
    if salida.estado_reparacion != 'revision' or not salida.subestado_revision:
        return None
    ingreso = salida.ingreso
    return NotificacionRevisionAdmin.objects.create(
        salida=salida,
        tipo=NotificacionRevisionAdmin.TIPO_SUBCATEGORIA,
        creado_por=user,
        mensaje=(
            f'{_nombre(user)} puso el equipo {ingreso.codigo_equipo} '
            f'({ingreso.cliente.nombres}) en Revisión — {salida.subestado_revision_texto}.'
        ),
    )


def avisar_observacion(observacion):
    salida = salida_en_revision(observacion.ingreso)
    if salida is None:
        return None
    return NotificacionRevisionAdmin.objects.create(
        salida=salida,
        tipo=NotificacionRevisionAdmin.TIPO_OBSERVACION,
        creado_por=observacion.autor,
        mensaje=observacion.texto,
    )


def dias_en_subestado(salida, hoy=None):
    if not salida.fecha_subestado_revision:
        return 0
    hoy = hoy or timezone.localdate()
    return (hoy - timezone.localdate(salida.fecha_subestado_revision)).days


def equipos_prueba_demorados_qs(hoy=None):
    """Equipos de prueba que siguen en la oficina 5 días o más después de
    ponerlos en esa subcategoría, del más antiguo al más nuevo."""
    hoy = hoy or timezone.localdate()
    return (
        SalidaEquipo.objects
        .select_related('ingreso', 'ingreso__cliente', 'tecnico_reparo')
        .filter(
            estado_reparacion='revision',
            subestado_revision='equipo_prueba',
            fecha_retiro_real__isnull=True,
            fecha_subestado_revision__date__lte=hoy - timedelta(days=DIAS_ALERTA_EQUIPO_PRUEBA),
        )
        .order_by('fecha_subestado_revision', 'pk')
    )


def generar_avisos_prueba_demorada(hoy=None):
    """Un aviso por cada vez que un equipo entra a Equipo de prueba y llega a
    los 5 días; si sale y vuelve a entrar, cuenta de nuevo."""
    demorados = list(equipos_prueba_demorados_qs(hoy))
    if not demorados:
        return 0
    claves = {
        f'prueba:{salida.pk}:{salida.fecha_subestado_revision:%Y%m%d%H%M%S}': salida
        for salida in demorados
    }
    existentes = set(
        NotificacionRevisionAdmin.objects
        .filter(dedupe_key__in=claves)
        .values_list('dedupe_key', flat=True)
    )
    nuevos = [
        NotificacionRevisionAdmin(
            salida=salida,
            tipo=NotificacionRevisionAdmin.TIPO_PRUEBA_DEMORADA,
            dedupe_key=clave,
            mensaje=(
                f'El equipo {salida.ingreso.codigo_equipo} ({salida.ingreso.cliente.nombres}) '
                f'lleva {dias_en_subestado(salida, hoy)} días como Equipo de prueba.'
            ),
        )
        for clave, salida in claves.items()
        if clave not in existentes
    ]
    NotificacionRevisionAdmin.objects.bulk_create(nuevos)
    return len(nuevos)
