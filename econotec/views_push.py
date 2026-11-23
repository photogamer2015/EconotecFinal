"""App instalable (manifest y service worker) y suscripción a notificaciones push."""
import json

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.views.decorators.http import require_POST

from .models import SuscripcionPush
from .permisos import es_admin, es_asesor, es_tecnico
from .push import clave_publica


def puede_recibir_push(user):
    return user.is_authenticated and (es_admin(user) or es_tecnico(user) or es_asesor(user))


def manifest(request):
    """Datos para instalar Econotec como app en el celular (público: el navegador
    lo pide sin la sesión)."""
    datos = {
        'name': 'Econotec — Reparación de Tecnología',
        'short_name': 'Econotec',
        'start_url': '/bienvenida/',
        'scope': '/',
        'display': 'standalone',
        'orientation': 'any',
        'background_color': '#202936',
        'theme_color': '#202936',
        'lang': 'es-EC',
        'icons': [
            {'src': static('pwa/icono-192.png'), 'sizes': '192x192', 'type': 'image/png'},
            {'src': static('pwa/icono-512.png'), 'sizes': '512x512', 'type': 'image/png'},
        ],
    }
    respuesta = HttpResponse(
        json.dumps(datos, ensure_ascii=False),
        content_type='application/manifest+json; charset=utf-8',
    )
    respuesta['Cache-Control'] = 'public, max-age=3600'
    return respuesta


def assetlinks(request):
    """Vincula la app de Android con econosystem.cc para que abra a pantalla
    completa (sin barra de dirección). Público: lo revisan Android y Chrome."""
    huellas = [h.strip() for h in settings.ANDROID_APP_SHA256.split(',') if h.strip()]
    datos = [{
        'relation': ['delegate_permission/common.handle_all_urls'],
        'target': {
            'namespace': 'android_app',
            'package_name': settings.ANDROID_APP_PAQUETE,
            'sha256_cert_fingerprints': huellas,
        },
    }]
    respuesta = JsonResponse(datos, safe=False)
    respuesta['Cache-Control'] = 'public, max-age=3600'
    return respuesta


def service_worker(request):
    """Recibe las notificaciones push y abre el aviso al tocarlas. Se sirve
    desde la raíz para que controle todo el sistema."""
    respuesta = render(
        request, 'pwa/service-worker.js',
        {'icono': static('pwa/icono-192.png')},
        content_type='application/javascript; charset=utf-8',
    )
    respuesta['Cache-Control'] = 'no-cache'
    return respuesta


def _json(request):
    try:
        return json.loads(request.body or b'{}')
    except (ValueError, UnicodeDecodeError):
        return None


@login_required
def push_clave(request):
    if not puede_recibir_push(request.user):
        return JsonResponse({'ok': False}, status=403)
    return JsonResponse({'ok': True, 'clave': clave_publica()})


@login_required
@require_POST
def push_suscribir(request):
    if not puede_recibir_push(request.user):
        return JsonResponse({'ok': False, 'mensaje': 'Tu usuario no recibe notificaciones.'}, status=403)
    datos = _json(request)
    if not isinstance(datos, dict):
        return JsonResponse({'ok': False, 'mensaje': 'Datos inválidos.'}, status=400)
    endpoint = str(datos.get('endpoint') or '').strip()
    claves = datos.get('keys') or {}
    p256dh = str(claves.get('p256dh') or '').strip() if isinstance(claves, dict) else ''
    auth = str(claves.get('auth') or '').strip() if isinstance(claves, dict) else ''
    if (
        not endpoint.startswith('https://') or len(endpoint) > 700
        or not p256dh or len(p256dh) > 200 or not auth or len(auth) > 100
    ):
        return JsonResponse({'ok': False, 'mensaje': 'Suscripción inválida.'}, status=400)

    SuscripcionPush.objects.update_or_create(
        endpoint=endpoint,
        defaults={
            'usuario': request.user,
            'p256dh': p256dh,
            'auth': auth,
            'dispositivo': (request.META.get('HTTP_USER_AGENT') or '')[:300],
        },
    )
    request.session['push_endpoint'] = endpoint
    return JsonResponse({'ok': True})


@login_required
@require_POST
def push_desuscribir(request):
    datos = _json(request) or {}
    endpoint = str(datos.get('endpoint') or '').strip() if isinstance(datos, dict) else ''
    if endpoint:
        SuscripcionPush.objects.filter(endpoint=endpoint, usuario=request.user).delete()
    request.session.pop('push_endpoint', None)
    return JsonResponse({'ok': True})


@login_required
@require_POST
def push_probar(request):
    """Envía una notificación de prueba a los dispositivos del usuario."""
    if not puede_recibir_push(request.user):
        return JsonResponse({'ok': False}, status=403)
    from .push import enviar_push_ahora
    enviados = enviar_push_ahora(
        [request.user.pk], '✅ Notificaciones activadas',
        'Así te llegarán los avisos de Econotec en este dispositivo.',
        etiqueta='prueba',
    )
    return JsonResponse({'ok': enviados > 0, 'enviados': enviados})
