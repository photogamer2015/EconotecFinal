"""
Tareas diarias automáticas de Econotec.

El cron lo ejecuta cada hora (lo instala scripts/aws_update.sh al desplegar):

    0 * * * * cd /ruta/al/proyecto && .venv/bin/python manage.py tareas_diarias

Solo trabaja cuando en Guayaquil es la hora TAREAS_DIARIAS_HORA (7 por
defecto) o CIERRE_DIA_HORA (18 por defecto, el cierre del día de cada
usuario). Así da igual en qué zona horaria esté el servidor.

Uso manual (sin esperar a la hora):

    python manage.py tareas_diarias --forzar   # resumen, recordatorios y bodegaje
    python manage.py tareas_diarias --cierre   # cierre del día de cada usuario
"""
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from econotec.tareas_diarias import (
    enviar_avisos_bodegaje_clientes,
    enviar_cierres_del_dia,
    enviar_recordatorios_tecnicos,
    enviar_resumen_admin,
)


class Command(BaseCommand):
    help = (
        'Envía el resumen diario al admin, el recordatorio de equipos atrasados a cada técnico '
        'y el aviso de bodegaje vencido a los clientes; a la hora del cierre, el reporte del día '
        'a cada usuario.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--forzar', action='store_true',
            help='Envía ahora aunque no sea la hora configurada.',
        )
        parser.add_argument(
            '--cierre', action='store_true',
            help='Envía ahora el cierre del día (reporte de cada usuario).',
        )

    def handle(self, *args, **options):
        hora = settings.TAREAS_DIARIAS_HORA
        hora_cierre = settings.CIERRE_DIA_HORA
        ahora = timezone.localtime()
        manual = options['forzar'] or options['cierre']
        manana = options['forzar'] or (not manual and ahora.hour == hora)
        cierre = options['cierre'] or (
            not manual and settings.CIERRE_DIA_AUTOMATICO and ahora.hour == hora_cierre
        )
        if not manana and not cierre:
            self.stdout.write(
                f'No es la hora de las tareas diarias ({hora}:00) ni del cierre del día ({hora_cierre}:00); '
                'no se envía nada.'
            )
            return

        hoy = ahora.date()
        if manana:
            admins = enviar_resumen_admin(hoy)
            tecnicos = enviar_recordatorios_tecnicos(hoy)
            clientes = enviar_avisos_bodegaje_clientes(hoy)
            self.stdout.write(self.style.SUCCESS(
                f'{ahora:%Y-%m-%d %H:%M} · Resumen diario: {admins} correo(s) a admins · '
                f'Recordatorios: {tecnicos} correo(s) a técnicos · '
                f'Bodegaje: {clientes} aviso(s) a clientes.'
            ))
        if cierre:
            correos, notificaciones = enviar_cierres_del_dia(hoy)
            self.stdout.write(self.style.SUCCESS(
                f'{ahora:%Y-%m-%d %H:%M} · Cierre del día: {correos} correo(s) · '
                f'{notificaciones} notificación(es).'
            ))
