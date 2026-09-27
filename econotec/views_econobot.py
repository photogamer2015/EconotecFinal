"""Endpoints del chat EconoBot.

- POST /econobot/mensaje/ recibe {message, signature?, request_id} y responde JSON.
- GET  /econobot/estado/  indica si hay un registro en curso para retomarlo.

Solo lo usan personas con acceso a equipos o pagos. Cada mensaje corre en una
transacción: si algo falla, no queda nada guardado a medias.
"""
import json
import logging

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404, JsonResponse
from django.views.decorators.http import require_GET, require_POST

from .econobot.motor import estado_actual, responder
from .permisos import puede_gestionar_equipos, puede_gestionar_pagos

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
