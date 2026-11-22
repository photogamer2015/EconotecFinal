"""
Tareas diarias automáticas de Econotec.

El cron lo ejecuta cada hora (lo instala scripts/aws_update.sh al desplegar):

    0 * * * * cd /ruta/al/proyecto && .venv/bin/python manage.py tareas_diarias

Solo trabaja cuando en Guayaquil es la hora TAREAS_DIARIAS_HORA (7 por
defecto). Así da igual en qué zona horaria esté el servidor.

Uso manual (sin esperar a la hora):

    python manage.py tareas_diarias --forzar
"""
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from econotec.tareas_diarias import (
    enviar_avisos_bodegaje_clientes,
    enviar_recordatorios_tecnicos,
    enviar_resumen_admin,
)


class Command(BaseCommand):
    help = (
        'Envía el resumen diario al admin, el recordatorio de equipos atrasados a cada técnico '
        'y el aviso de bodegaje vencido a los clientes.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--forzar', action='store_true',
            help='Envía ahora aunque no sea la hora configurada.',
        )

    def handle(self, *args, **options):
        hora = settings.TAREAS_DIARIAS_HORA
        ahora = timezone.localtime()
        if not options['forzar'] and ahora.hour != hora:
            self.stdout.write(f'No es la hora de las tareas diarias ({hora}:00); no se envía nada.')
            return

        hoy = ahora.date()
        admins = enviar_resumen_admin(hoy)
        tecnicos = enviar_recordatorios_tecnicos(hoy)
        clientes = enviar_avisos_bodegaje_clientes(hoy)
        self.stdout.write(self.style.SUCCESS(
            f'{ahora:%Y-%m-%d %H:%M} · Resumen diario: {admins} correo(s) a admins · '
            f'Recordatorios: {tecnicos} correo(s) a técnicos · '
            f'Bodegaje: {clientes} aviso(s) a clientes.'
        ))
