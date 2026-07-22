from django.utils import timezone

from .models import HorarioTecnico
from .permisos import es_tecnico


def registrar_entrada_laboral(user):
    """
    Marca que un técnico entró al sistema según su horario laboral.

    Devuelve el horario si se generó un aviso nuevo para hoy; si no aplica o
    ya se notificó hoy para ese tipo de entrada, devuelve None.
    """
    if not user or not user.is_authenticated or not es_tecnico(user):
        return None

    horario, _ = HorarioTecnico.objects.get_or_create(tecnico=user)
    if not horario.activo:
        return None

    hoy = timezone.localdate()
    ahora = timezone.now()
    es_dia = horario.es_dia_laboral(hoy)
    en_horario = horario.esta_en_horario(ahora)

    if es_dia and en_horario:
        if horario.ultima_notificacion_laboral:
            ultimo_dia = timezone.localdate(horario.ultima_notificacion_laboral)
            if ultimo_dia == hoy:
                return None

        horario.ultima_notificacion_laboral = ahora
        horario.save(update_fields=['ultima_notificacion_laboral', 'actualizado'])
        return horario

    if horario.ultima_notificacion_fuera_laboral:
        ultimo_dia = timezone.localdate(horario.ultima_notificacion_fuera_laboral)
        if ultimo_dia == hoy:
            return None

    horario.ultima_notificacion_fuera_laboral = ahora
    horario.ultima_notificacion_fuera_motivo = 'dia' if not es_dia else 'hora'
    horario.save(update_fields=[
        'ultima_notificacion_fuera_laboral',
        'ultima_notificacion_fuera_motivo',
        'actualizado',
    ])
    return horario
