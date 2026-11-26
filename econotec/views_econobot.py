"""Endpoints del chat EconoBot.

- POST /econobot/mensaje/ recibe {message, signature?, request_id} y responde JSON.
- GET  /econobot/estado/  indica si hay un registro en curso para retomarlo.
- GET  /econobot/reporte-dia/ saludo con los equipos que el usuario registró hoy.
- GET  /econobot/reporte-dia/pdf/ el mismo reporte en PDF (?fecha= para otro día).
- GET  /econobot/reporte-personal/pdf/ reporte de todo el personal (solo admin).

Solo lo usan personas con acceso a equipos o pagos. Cada mensaje corre en una
transacción: si algo falla, no queda nada guardado a medias.
"""
import json
import logging

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.contrib.auth.views import redirect_to_login
from django.http import Http404, HttpResponse, JsonResponse
from django.views.decorators.http import require_GET, require_POST

from .econobot import reporte_dia
from .econobot.motor import estado_actual, responder
from .permisos import es_admin, puede_gestionar_equipos, puede_gestionar_pagos

logger = logging.getLogger(__name__)

MAX_MENSAJE = 2000
MAX_FIRMA = 700_000 + len('data:image/png;base64,')
MAX_REQUEST_ID = 100
ULTIMA_RESPUESTA = 'econobot_ultima_respuesta'


def _autorizado(user):
    return user.is_authenticated and (puede_gestionar_equipos(user) or puede_gestionar_pagos(user))


def _negado(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Tu sesión terminó. Vuelve a iniciar sesión para usar EconoBot.'}, status=401)
    return JsonResponse({'error': 'No tienes permiso para usar EconoBot.'}, status=403)


def _recargar_sesion(request):
    """Vuelve a leer la sesión: descarta cambios a medias o toma los de otra pestaña."""
    clave = request.session.session_key
    if clave:
        request.session = request.session.__class__(session_key=clave)


@require_POST
def econobot_mensaje(request):
    if not _autorizado(request.user):
        return _negado(request)
    try:
        datos = json.loads(request.body or b'{}')
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'error': 'Solicitud inválida.'}, status=400)
    if not isinstance(datos, dict):
        return JsonResponse({'error': 'Solicitud inválida.'}, status=400)

    mensaje = datos.get('message', '')
    firma = datos.get('signature')
    request_id = datos.get('request_id') or ''
    if not isinstance(mensaje, str) or not isinstance(request_id, str):
        return JsonResponse({'error': 'Solicitud inválida.'}, status=400)
    mensaje = mensaje.strip()
    if len(mensaje) > MAX_MENSAJE:
        return JsonResponse({'error': f'El mensaje es muy largo (máximo {MAX_MENSAJE} caracteres).'}, status=400)
    if len(request_id) > MAX_REQUEST_ID:
        return JsonResponse({'error': 'Solicitud inválida.'}, status=400)
    if firma is not None:
        if (not isinstance(firma, str) or not firma.startswith('data:image/png;base64,')
                or len(firma) > MAX_FIRMA):
            return JsonResponse({'error': 'La firma no es válida o es demasiado grande. Vuelve a firmar.'}, status=400)
    if not mensaje and firma is None:
        return JsonResponse({'error': 'Escribe un mensaje.'}, status=400)

    try:
        with transaction.atomic():
            # Un mensaje a la vez por usuario (doble clic o dos pestañas).
            get_user_model().objects.select_for_update().filter(pk=request.user.pk).first()
            _recargar_sesion(request)
            anterior = request.session.get(ULTIMA_RESPUESTA)
            if request_id and isinstance(anterior, dict) and anterior.get('id') == request_id:
                return JsonResponse(anterior.get('result') or {})
            resultado = responder(request, mensaje, firma=firma)
            if request_id:
                request.session[ULTIMA_RESPUESTA] = {'id': request_id, 'result': resultado}
            return JsonResponse(resultado)
    except (Http404, PermissionDenied):
        _recargar_sesion(request)
        return JsonResponse({'reply': 'No encontré ese registro o no tienes acceso a él. No se guardó nada.',
                             'links': [], 'options': []})
    except Exception:
        logger.exception('Error en EconoBot')
        _recargar_sesion(request)
        return JsonResponse(
            {'error': 'Ocurrió un error inesperado y no se guardó nada. Intenta de nuevo en un momento.'},
            status=500,
        )


@require_GET
def econobot_estado(request):
    if not _autorizado(request.user):
        return _negado(request)
    return JsonResponse(estado_actual(request))


@require_GET
def econobot_reporte_dia(request):
    """Saludo del día: lo pide el chat la primera vez que se abre cada día."""
    if not _autorizado(request.user):
        return _negado(request)
    datos = reporte_dia.resumen(request.user, presentar=request.GET.get('presentar') == '1')
    datos['date'] = reporte_dia.hoy().isoformat()
    return JsonResponse(datos)


def _pdf(contenido, nombre):
    response = HttpResponse(contenido, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="{nombre}"'
    response['Cache-Control'] = 'no-store'
    return response


@require_GET
def econobot_reporte_dia_pdf(request):
    """PDF con lo que el usuario hizo en el día (hoy o ?fecha=AAAA-MM-DD): solo sus propios datos."""
    from .views_print import generar_reporte_dia_pdf_bytes

    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    if not _autorizado(request.user):
        raise PermissionDenied
    fecha = reporte_dia.fecha_de_texto(request.GET.get('fecha'))
    pdf = generar_reporte_dia_pdf_bytes(reporte_dia.datos_dia(request.user, fecha))
    return _pdf(pdf, f'reporte_del_dia_{fecha:%Y-%m-%d}.pdf')


@require_GET
def econobot_reporte_personal_pdf(request):
    """PDF del reporte del personal del día (solo admin)."""
    from .views_print import generar_reporte_personal_pdf_bytes

    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    if not es_admin(request.user):
        raise PermissionDenied
    fecha = reporte_dia.fecha_de_texto(request.GET.get('fecha'))
    pdf = generar_reporte_personal_pdf_bytes(reporte_dia.datos_personal(fecha))
    return _pdf(pdf, f'reporte_del_personal_{fecha:%Y-%m-%d}.pdf')
