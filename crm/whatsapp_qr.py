"""
Conexión con el puente de WhatsApp por código QR (carpeta whatsapp_qr/, Node.js + whatsapp-web.js).

No es la API oficial de Meta: el puente se vincula al número como WhatsApp Web.
  • Mensaje que llega  → el puente lo envía a /api/whatsapp/qr/entrante/ y manda la respuesta del bot.
  • Asesor responde    → el CRM llama a enviar() y el puente lo entrega por WhatsApp.
"""
import json
import logging
import urllib.error
import urllib.request

from django.conf import settings

log = logging.getLogger(__name__)


def activo():
    return bool(getattr(settings, "WA_QR_ACTIVO", False) and getattr(settings, "WA_QR_TOKEN", ""))


def _pedir(ruta, datos=None, timeout=4):
    url = settings.WA_QR_URL.rstrip("/") + ruta
    body = json.dumps(datos).encode() if datos is not None else None
    req = urllib.request.Request(
        url, data=body, method="POST" if body else "GET",
        headers={"Content-Type": "application/json", "X-Bridge-Token": settings.WA_QR_TOKEN},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def estado():
    """{'estado': 'conectado'|'esperando_qr'|'iniciando'|'desconectado'|'apagado', 'qr': dataURL|None, 'numero': ...}"""
    if not activo():
        return {"estado": "apagado", "qr": None, "numero": ""}
    try:
        return _pedir("/estado", timeout=2)
    except Exception as e:  # el programa del QR no está abierto
        log.info("Puente WhatsApp QR no responde: %s", e)
        return {"estado": "sin_conexion", "qr": None, "numero": ""}


def enviar(numero, texto):
    """Envía un mensaje por el WhatsApp vinculado. Devuelve (ok, estado)."""
    if not activo():
        return False, "WhatsApp por QR desactivado"
    try:
        r = _pedir("/enviar", {"numero": numero, "texto": texto}, timeout=20)
        return (True, "enviado por WhatsApp") if r.get("ok") else (False, f"error: {r.get('error', 'no enviado')}"[:40])
    except urllib.error.HTTPError as e:
        return False, f"error {e.code} del puente"
    except Exception:
        return False, "error: WhatsApp no conectado"
