"""
Lee los correos no leídos de la bandeja comercial (IMAP) y los registra como leads/mensajes.
Programar con cron cada 5 minutos:
    */5 * * * * cd /ruta/econotec && venv/bin/python manage.py leer_correos
"""
import email
import imaplib
from email.header import decode_header, make_header
from email.utils import parseaddr

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from crm import services
from crm.models import Canal


def _texto(msg):
    if msg.is_multipart():
        for parte in msg.walk():
            if parte.get_content_type() == "text/plain" and "attachment" not in str(parte.get("Content-Disposition")):
                return parte.get_payload(decode=True).decode(parte.get_content_charset() or "utf-8", "replace")
        return "[Correo sin texto plano]"
    return msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", "replace")


class Command(BaseCommand):
    help = "Importa correos no leídos de la bandeja comercial al CRM."

    def add_arguments(self, p):
        p.add_argument("--carpeta", default="INBOX")

    def handle(self, *a, **o):
        if not (settings.IMAP_HOST and settings.IMAP_USER and settings.IMAP_PASSWORD):
            raise CommandError("Configura IMAP_HOST, IMAP_USER e IMAP_PASSWORD en .env")
        propio = settings.IMAP_USER.lower()
        n = 0
        with imaplib.IMAP4_SSL(settings.IMAP_HOST) as imap:
            imap.login(settings.IMAP_USER, settings.IMAP_PASSWORD)
            imap.select(o["carpeta"])
            _, ids = imap.search(None, "UNSEEN")
            for num in ids[0].split():
                _, data = imap.fetch(num, "(RFC822)")
                msg = email.message_from_bytes(data[0][1])
                nombre, remitente = parseaddr(str(make_header(decode_header(msg.get("From", "")))))
                if not remitente or remitente.lower() == propio:
                    continue
                asunto = str(make_header(decode_header(msg.get("Subject", "(sin asunto)"))))
                cuerpo = _texto(msg).strip()
                services.registrar_entrante(
                    canal=Canal.CORREO,
                    nombre=nombre or remitente,
                    email=remitente,
                    texto=f"Asunto: {asunto}\n\n{cuerpo[:4000]}",
                    externo_id=(msg.get("Message-ID") or "")[:200] or None,
                )
                n += 1
        self.stdout.write(f"Correos importados: {n}")
