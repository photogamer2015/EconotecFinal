"""
Context processor que expone roles y contadores de alertas en TODOS los templates.

Variables disponibles:
    {% if es_admin %}, {% if es_tecnico %}, {% if es_asesor %}, {% if es_asesor_comercial %}
    {{ rol_actual }}, {{ sede_actual_display }}

    {{ alertas_demora_count }}            # equipos demorados (diagnóstico) del usuario
    {{ alertas_demora_count_global }}     # global, solo admin
    {{ alertas_bodegaje_count }}          # salidas con bodegaje del usuario
    {{ alertas_bodegaje_count_global }}   # global, solo admin
    {{ alertas_total_count }}             # suma de las dos (la que vea el usuario)
"""
from .permisos import (
    es_admin as _es_admin,
    es_tecnico as _es_tecnico,
    es_asesor as _es_asesor,
    puede_gestionar_equipos as _puede_gestionar_equipos,
    puede_gestionar_pagos as _puede_gestionar_pagos,
    puede_ver_ranking as _puede_ver_ranking,
)


def roles(request):
    user = getattr(request, 'user', None)

    session = getattr(request, 'session', None)
    sede_actual = (session.get('sede_actual') if session is not None else '') or ''
    if sede_actual == 'guayaquil':
        sede_actual_display = 'Guayaquil'
    elif sede_actual == 'quito':
        sede_actual_display = 'Quito'
    else:
        sede_actual_display = ''

    if user is None or not user.is_authenticated:
        return {
            'es_admin': False,
            'es_tecnico': False,
            'es_asesor': False,
            'es_asesor_comercial': False,
            'puede_gestionar_equipos': False,
            'puede_gestionar_pagos': False,
            'puede_ver_ranking': False,
            'rol_actual': '',
            'sede_actual': sede_actual,
            'sede_actual_display': sede_actual_display,
            'alertas_demora_count': 0,
            'alertas_demora_count_global': 0,
            'alertas_bodegaje_count': 0,
            'alertas_bodegaje_count_global': 0,
            'alertas_total_count': 0,
            'notificaciones_asesora_count': 0,
            'notificaciones_asesora_preview': [],
        }

    es_a = _es_admin(user)
    es_t = _es_tecnico(user)
    es_as = _es_asesor(user)

    if es_a:
        rol_actual = 'Administrador'
    elif es_t:
        rol_actual = 'Técnico'
    elif es_as:
        rol_actual = 'Asesor Comercial'
    else:
        rol_actual = 'Usuario'

    # ── Conteo de alertas (importamos acá para evitar import circular) ─
    demora_count = 0
    demora_count_global = 0
    bodegaje_count = 0
    bodegaje_count_global = 0
    try:
        from .alertas import equipos_demorados_qs, salidas_bodegaje_qs
        demora_count = equipos_demorados_qs(usuario=user).count()
        bodegaje_count = salidas_bodegaje_qs(usuario=user).count()
        if es_a:
            demora_count_global = equipos_demorados_qs(usuario=None).count()
            bodegaje_count_global = salidas_bodegaje_qs(usuario=None).count()
    except Exception:
        pass

    # Total visible para el usuario actual: si es admin → globales, sino → personales
    if es_a:
        total = demora_count_global + bodegaje_count_global
    else:
        total = demora_count + bodegaje_count

    # ── Avisos del panel vigentes hoy (se muestran en el inicio) ──
    avisos_vigentes = []
    try:
        from .models import AvisoPanel
        avisos_vigentes = list(AvisoPanel.vigentes_hoy())
    except Exception:
        pass

    notificaciones_asesora_count = 0
    notificaciones_asesora_preview = []
    try:
        from .models import NotificacionAsesora
        qs_notificaciones = (
            NotificacionAsesora.objects
            .select_related('ingreso', 'ingreso__cliente', 'salida', 'asesora')
            .filter(leida=False)
        )
        if not es_a:
            qs_notificaciones = qs_notificaciones.filter(asesora=user)
        if es_a or es_as:
            notificaciones_asesora_count = qs_notificaciones.count()
            notificaciones_asesora_preview = list(qs_notificaciones[:3])
    except Exception:
        pass

    return {
        'es_admin': es_a,
        'es_tecnico': es_t,
        'es_asesor': es_as,
        'es_asesor_comercial': es_as,
        'puede_gestionar_equipos': _puede_gestionar_equipos(user),
        'puede_gestionar_pagos': _puede_gestionar_pagos(user),
        'puede_ver_ranking': _puede_ver_ranking(user),
        'rol_actual': rol_actual,
        'sede_actual': sede_actual,
        'sede_actual_display': sede_actual_display,
        'alertas_demora_count': demora_count,
        'alertas_demora_count_global': demora_count_global,
        'alertas_bodegaje_count': bodegaje_count,
        'alertas_bodegaje_count_global': bodegaje_count_global,
        'alertas_total_count': total,
        'avisos_vigentes': avisos_vigentes,
        'notificaciones_asesora_count': notificaciones_asesora_count,
        'notificaciones_asesora_preview': notificaciones_asesora_preview,
    }
