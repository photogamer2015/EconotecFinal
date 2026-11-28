"""
WhatsApp Business API oficial (Meta · Cloud API) — lista para conectar.

Mientras no se configuren las claves, el CRM sigue funcionando sin API:
  • enlaces wa.me (la asesora abre el chat con el mensaje listo y toca Enviar), y
  • el puente por código QR (carpeta whatsapp_qr/), si está activo.

Para conectarla (en .env del servidor):
    WA_API_TOKEN=<token permanente del usuario del sistema en Meta Business>
    WA_API_PHONE_ID=<Phone number ID del número de WhatsApp Business>
    WA_API_VERIFY_TOKEN=<clave que tú inventas para verificar el webhook>
    WA_API_APP_SECRET=<App secret de la app de Meta, para firmar el webhook> (recomendado)

Y en Meta for Developers → WhatsApp → Configuración → Webhook:
    URL:            https://econosystem.cc/crm/api/whatsapp/webhook/
    Verify token:   el mismo WA_API_VERIFY_TOKEN
    Suscribirse a:  messages

Con la API activa:
  • Mensaje que llega → se registra el cliente/oportunidad y responde el bot (si está activo).
  • La asesora responde desde «Chats de WhatsApp» o la ficha → sale solo por la API, sin abrir WhatsApp.
"""
import json
import logging
import urllib.error
import urllib.request

from django.conf import settings

log = logging.getLogger(__name__)

GRAPH_URL = "https://graph.facebook.com/v21.0"


def activo():
    return bool(getattr(settings, "WA_API_TOKEN", "") and getattr(settings, "WA_API_PHONE_ID", ""))


def estado():
    """Para la pantalla de Integraciones: qué falta configurar."""
    faltan = [
        nombre for nombre in ("WA_API_TOKEN", "WA_API_PHONE_ID", "WA_API_VERIFY_TOKEN")
        if not getattr(settings, nombre, "")
    ]
    return {"activo": activo(), "faltan": faltan, "webhook_listo": bool(getattr(settings, "WA_API_VERIFY_TOKEN", ""))}


def enviar(numero, texto):
    """Envía un mensaje de texto por la API oficial. Devuelve (ok, estado)."""
    if not activo():
        return False, "API de WhatsApp sin conectar"
    from .services import normalizar_telefono

    cuerpo = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": normalizar_telefono(numero),
        "type": "text",
        "text": {"preview_url": True, "body": texto[:4096]},
    }
    req = urllib.request.Request(
        f"{GRAPH_URL}/{settings.WA_API_PHONE_ID}/messages",
        data=json.dumps(cuerpo).encode(),
        method="POST",
        headers={"Authorization": f"Bearer {settings.WA_API_TOKEN}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            datos = json.loads(r.read() or b"{}")
        return (True, "enviado por la API de WhatsApp") if datos.get("messages") else (False, "error: sin confirmación")
    except urllib.error.HTTPError as e:
        try:
            detalle = json.loads(e.read() or b"{}").get("error", {}).get("message", "")
        except Exception:
            detalle = ""
        log.warning("WhatsApp API %s: %s", e.code, detalle)
        return False, f"error {e.code} de la API"[:40]
    except Exception as e:
        log.warning("WhatsApp API sin conexión: %s", e)
        return False, "error: API sin conexión"


def mensajes_entrantes(payload):
    """Extrae del webhook de Meta los mensajes: [{'numero', 'nombre', 'texto', 'id'}]."""
    salida = []
    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            valor = change.get("value", {}) or {}
            nombres = {c.get("wa_id"): (c.get("profile") or {}).get("name", "") for c in valor.get("contacts", []) or []}
            for m in valor.get("messages", []) or []:
                tipo = m.get("type")
                if tipo == "text":
                    texto = (m.get("text") or {}).get("body", "")
                elif tipo == "button":
                    texto = (m.get("button") or {}).get("text", "")
                elif tipo == "interactive":
                    inter = m.get("interactive") or {}
                    texto = (inter.get("button_reply") or inter.get("list_reply") or {}).get("title", "")
                else:
                    nombre_tipo = {"audio": "nota de voz", "image": "imagen", "video": "video",
                                   "document": "documento", "sticker": "sticker", "location": "ubicación"}.get(tipo, tipo)
                    texto = f"[{nombre_tipo} recibido]"
                numero = m.get("from", "")
                if numero and texto:
                    salida.append({"numero": numero, "nombre": nombres.get(numero, ""), "texto": texto, "id": m.get("id")})
    return salida
