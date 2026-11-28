"""
Envía por correo los seguimientos que vencen en los próximos N minutos.
Programar con cron cada 15 minutos:
    */15 * * * * cd /ruta/econotec && venv/bin/python manage.py enviar_recordatorios
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from crm import services


class Command(BaseCommand):
    help = "Envía recordatorios por correo de seguimientos próximos."

    def add_arguments(self, p):
        p.add_argument("--minutos", type=int, default=60)

    def handle(self, *a, **o):
        enviados = 0
        for s in services.seguimientos_por_notificar(o["minutos"]):
            if not s.responsable.email:
                continue
            cliente = s.oportunidad.contacto if s.oportunidad else None
            cuerpo = (
                f"Hola {s.responsable.first_name or s.responsable.username},\n\n"
                f"Tienes un seguimiento programado:\n\n"
                f"• {s.titulo}\n• {s.get_tipo_display()} — {timezone.localtime(s.fecha_hora):%d/%m/%Y %H:%M}\n"
                + (f"• Cliente: {cliente.nombre} ({cliente.empresa}) {cliente.telefono} {cliente.email}\n" if cliente else "")
                + "\nCRM Econotec"
            )
            ok, _ = services.enviar_correo(s.responsable.email, f"Recordatorio: {s.titulo}", cuerpo)
            if ok:
                s.notificado = True
                s.save(update_fields=["notificado"])
                enviados += 1
        self.stdout.write(f"Recordatorios enviados: {enviados}")
