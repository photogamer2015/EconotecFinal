"""Entradas externas: formulario web, botón de WhatsApp para la página, WhatsApp por QR y WhatsApp API oficial."""
import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt

from . import services
from .models import Canal, Categoria, Configuracion

log = logging.getLogger(__name__)


def _cors(request, resp):
    origen = request.headers.get("Origin", "")
    if origen and origen in settings.CORS_FORM_ORIGINS:
        resp["Access-Control-Allow-Origin"] = origen
        resp["Access-Control-Allow-Headers"] = "Content-Type, X-CRM-Token"
        resp["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp


@csrf_exempt
def entrante_web(request):
    """POST desde el formulario de la página web (JSON o form-data)."""
    if request.method == "OPTIONS":
        return _cors(request, HttpResponse())
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Usa POST"}, status=405)
    token = request.headers.get("X-CRM-Token") or request.POST.get("token", "")
    if not settings.WEB_FORM_TOKEN or not hmac.compare_digest(token, settings.WEB_FORM_TOKEN):
        return _cors(request, JsonResponse({"ok": False, "error": "Token inválido"}, status=403))
    if request.content_type == "application/json":
        try:
            d = json.loads(request.body or "{}")
        except json.JSONDecodeError:
            return _cors(request, JsonResponse({"ok": False, "error": "JSON inválido"}, status=400))
    else:
        d = request.POST
    if request.POST.get("website") or (isinstance(d, dict) and d.get("website")):
        return _cors(request, JsonResponse({"ok": True}))  # honeypot anti-spam
    nombre = (d.get("nombre") or "").strip()
    telefono, email = (d.get("telefono") or "").strip(), (d.get("email") or "").strip()
    if not nombre or not (telefono or email):
        return _cors(request, JsonResponse({"ok": False, "error": "Nombre y teléfono o correo son obligatorios"}, status=400))
    texto = (d.get("mensaje") or "").strip()
    servicio = (d.get("servicio") or "").strip()
    resumen = f"[Formulario web] Servicio: {servicio or 'no indicado'}. {texto}".strip()
    conv, op, creada = services.registrar_entrante(
        canal=Canal.WEB, nombre=nombre, texto=resumen, telefono=telefono, email=email,
        empresa=(d.get("empresa") or "").strip(), servicio=servicio,
    )
    return _cors(request, JsonResponse({"ok": True, "lead": op.pk if op else None, "nuevo": creada}))


# ------------------------------------------------------------------ Botón de WhatsApp para la página web
def _datos(request):
    ct = request.content_type or ""
    if ct.startswith("application/json") or ct.startswith("text/plain"):
        try:
            d = json.loads(request.body or "{}")
            return d if isinstance(d, dict) else {}
        except json.JSONDecodeError:
            return {}
    return request.POST


def _limite(request, clave, maximo, segundos=3600):
    """Freno simple contra abuso del endpoint público: máximo N por IP en la ventana."""
    ip = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() or request.META.get("REMOTE_ADDR", "")
    k = f"lim:{clave}:{ip}"
    n = cache.get(k, 0)
    if n >= maximo:
        return True
    cache.set(k, n + 1, segundos)
    return False


def widget_js(request):
    """Botón de WhatsApp para pegar en la página web: <script src=".../widget.js" defer></script>"""
    base = request.build_absolute_uri("/").rstrip("/")
    resp = render(request, "crm/widget.js", {"base": base}, content_type="application/javascript; charset=utf-8")
    resp["Cache-Control"] = "public, max-age=300"
    return resp


@csrf_exempt
def boton_config(request):
    if request.method == "OPTIONS":
        return _cors(request, HttpResponse())
    cfg = Configuracion.actual()
    return _cors(request, JsonResponse({
        "ok": True,
        "numero": services.normalizar_telefono(cfg.numero_whatsapp),
        "mensaje_boton": cfg.mensaje_boton,
        "categorias": list(Categoria.objects.filter(activa=True).values_list("nombre", flat=True)),
    }))


@csrf_exempt
def boton_registrar(request):
    """El visitante deja nombre y WhatsApp antes de abrir WhatsApp: queda como cliente en el CRM."""
    if request.method == "OPTIONS":
        return _cors(request, HttpResponse())
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Usa POST"}, status=405)
    d = _datos(request)
    if d.get("website"):
        return _cors(request, JsonResponse({"ok": True}))  # honeypot anti-spam
    nombre = (d.get("nombre") or "").strip()[:150]
    telefono = services.normalizar_telefono(d.get("telefono") or "")
    if not nombre or len(telefono) < 7:
        return _cors(request, JsonResponse({"ok": False, "error": "Escribe tu nombre y un número de WhatsApp válido."}, status=400))
    if _limite(request, "boton", 30):
        return _cors(request, JsonResponse({"ok": False, "error": "Demasiados intentos. Prueba más tarde."}, status=429))
    servicio = (d.get("servicio") or "").strip()
    if servicio and not Categoria.objects.filter(nombre=servicio, activa=True).exists():
        servicio = ""
    texto = "Tocó «Abrir WhatsApp» en la página web." + (f" Interés: {servicio}." if servicio else "")
    conv, op, creada = services.registrar_entrante(
        canal=Canal.WHATSAPP, nombre=nombre, texto=texto, telefono=telefono, servicio=servicio,
    )
    if servicio and op and op.servicio == "Por definir":
        op.servicio = servicio
        op.save(update_fields=["servicio", "actualizado"])
    return _cors(request, JsonResponse({"ok": True, "nuevo": creada}))


# ---------------------------------------------------------------- WhatsApp por código QR (sin API de Meta)
@csrf_exempt
def whatsapp_qr_entrante(request):
    """
    El puente de WhatsApp (whatsapp_qr/index.js) envía aquí cada mensaje que llega al número vinculado.
    Se registra en el CRM y se devuelve la respuesta del bot para que el puente la mande por WhatsApp.
    """
    from . import whatsapp_qr

    if not whatsapp_qr.activo():
        return JsonResponse({"ok": False, "error": "WhatsApp por QR desactivado"}, status=404)
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Usa POST"}, status=405)
    token = request.headers.get("X-Bridge-Token", "")
    if not hmac.compare_digest(token, settings.WA_QR_TOKEN):
        return JsonResponse({"ok": False, "error": "Token inválido"}, status=403)
    try:
        d = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "JSON inválido"}, status=400)

    numero = services.normalizar_telefono(d.get("numero", ""))
    texto = (d.get("texto") or "").strip()[:4000]
    if not numero or not texto:
        return JsonResponse({"ok": False, "error": "Faltan número o texto"}, status=400)
    r = procesar_whatsapp_entrante(numero, d.get("nombre"), texto, (d.get("id") or "")[:200] or None, "enviado por WhatsApp")
    return JsonResponse({"ok": True, **r})


def procesar_whatsapp_entrante(numero, nombre, texto, externo_id, estado):
    """Registra un mensaje de WhatsApp que llegó solo (QR o API) y devuelve la respuesta del bot."""
    from . import bot
    from .models import Conversacion, Mensaje

    if externo_id and Mensaje.objects.filter(externo_id=externo_id).exists():
        return {"respuestas": [], "repetido": True}
    # Mientras el bot atiende, no se avisa a la asesora de cada mensaje (solo cuando pide un asesor).
    cfg = Configuracion.actual()
    previa = Conversacion.objects.filter(canal=Canal.WHATSAPP, contacto__telefono=numero).first()
    bot_atiende = cfg.bot_activo and (previa is None or previa.bot_activo)
    conv, op, _ = services.registrar_entrante(
        canal=Canal.WHATSAPP,
        nombre=(nombre or "").strip()[:150] or numero,
        telefono=numero,
        texto=texto,
        externo_id=externo_id,
        avisar=not bot_atiende,
    )
    respuesta = bot.responder(conv, texto, op, estado=estado)
    return {"respuestas": [respuesta] if respuesta else [], "conversacion": conv.pk}


# ---------------------------------------------------------------- WhatsApp Business API oficial (Meta)
@csrf_exempt
def whatsapp_api_webhook(request):
    """
    Webhook de la API oficial de WhatsApp (Meta Cloud API).
    GET: verificación de Meta (hub.challenge). POST: mensajes entrantes.
    Mientras WA_API_TOKEN / WA_API_PHONE_ID no estén en .env, responde 404 (sin conectar).
    """
    from . import whatsapp_api

    verify = getattr(settings, "WA_API_VERIFY_TOKEN", "")
    if request.method == "GET":
        if (
            verify and request.GET.get("hub.mode") == "subscribe"
            and hmac.compare_digest(request.GET.get("hub.verify_token", ""), verify)
        ):
            return HttpResponse(request.GET.get("hub.challenge", ""), content_type="text/plain")
        return HttpResponse("Verificación inválida", status=403)
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Usa POST"}, status=405)
    if not whatsapp_api.activo():
        return JsonResponse({"ok": False, "error": "API de WhatsApp sin conectar"}, status=404)
    secreto = getattr(settings, "WA_API_APP_SECRET", "")
    if secreto:
        firma = request.headers.get("X-Hub-Signature-256", "")
        esperada = "sha256=" + hmac.new(secreto.encode(), request.body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(firma, esperada):
            return JsonResponse({"ok": False, "error": "Firma inválida"}, status=403)
    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "JSON inválido"}, status=400)
    for m in whatsapp_api.mensajes_entrantes(payload):
        numero = services.normalizar_telefono(m["numero"])
        r = procesar_whatsapp_entrante(numero, m["nombre"], m["texto"][:4000], (m["id"] or "")[:200] or None,
                                       "enviado por la API de WhatsApp")
        for respuesta in r.get("respuestas", []):
            whatsapp_api.enviar(numero, respuesta)
    return JsonResponse({"ok": True})
