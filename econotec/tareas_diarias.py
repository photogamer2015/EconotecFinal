"""
Tareas diarias automáticas (las corre el cron con `manage.py tareas_diarias`).

1. Resumen diario al admin: un correo a cada superusuario activo con correo,
   con lo mismo que ve en su inicio:
   - equipos sin diagnosticar hace 4 días o más,
   - equipos con 10 días o más en reparación / espera de cliente / repuesto,
   - equipos con bodegaje vencido,
   - Equipos de prueba con 5 días o más.
2. Recordatorio al técnico: un correo a cada técnico activo con correo,
   solo con SUS equipos sin diagnosticar (4+ días) o en reparación (5+ días).

Si no hay nada que avisar, no se envía correo. Los equipos en "No molestar"
no se incluyen, igual que en el inicio.
"""
import logging
from datetime import date

from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse

from .alertas import (
    UMBRAL_DIAS_BODEGAJE,
    UMBRAL_DIAS_DIAGNOSTICO,
    UMBRAL_DIAS_REPARACION_ADMIN,
    UMBRAL_DIAS_REPARACION_TECNICO,
    dias_desde_inicio_bodegaje,
    dias_en_estado_reparacion,
    dias_en_taller,
    equipos_demorados_qs,
    equipos_reparacion_demorada_qs,
    salidas_bodegaje_qs,
)
from .avisos_revision import DIAS_ALERTA_EQUIPO_PRUEBA, dias_en_subestado, equipos_prueba_demorados_qs
from .permisos import GRUPOS_TECNICO


logger = logging.getLogger(__name__)


def _url(nombre, *args):
    base = (getattr(settings, 'SISTEMA_URL', '') or '').rstrip('/')
    if not base:
        return ''
    return base + reverse(nombre, args=args)


def _nombre(user):
    return (f'{user.first_name} {user.last_name}'.strip()) or user.username


def _estado_reparacion(ingreso):
    return ingreso.subestado_visual_display or ingreso.estado_visual_display


def _items_diagnostico(qs, hoy):
    return [
        {'ingreso': ing, 'dias': dias_en_taller(ing, hoy=hoy), 'url': _url('econotec:ingreso_detalle', ing.pk)}
        for ing in qs
    ]


def _items_reparacion(qs, hoy):
    return [
        {
            'ingreso': ing,
            'dias': dias_en_estado_reparacion(ing, hoy=hoy),
            'estado': _estado_reparacion(ing),
            'url': _url('econotec:ingreso_detalle', ing.pk),
        }
        for ing in qs
    ]


def datos_resumen_admin(hoy=None):
    hoy = hoy or date.today()
    bodegajes = []
    for sal in salidas_bodegaje_qs(usuario=None):
        bod = sal.calcular_bodegaje(hoy=hoy)
        bodegajes.append({
            'salida': sal,
            'ingreso': sal.ingreso,
            'dias': dias_desde_inicio_bodegaje(sal, hoy=hoy),
            'monto': bod['monto'],
            'url': _url('econotec:ingreso_detalle', sal.ingreso.pk),
        })
    prueba = [
        {
            'salida': sal,
            'ingreso': sal.ingreso,
            'dias': dias_en_subestado(sal, hoy),
            'url': _url('econotec:ingreso_detalle', sal.ingreso.pk),
        }
        for sal in equipos_prueba_demorados_qs(hoy)
    ]
    return {
        'hoy': hoy,
        'diagnostico': _items_diagnostico(equipos_demorados_qs(usuario=None), hoy),
        'reparacion': _items_reparacion(
            equipos_reparacion_demorada_qs(usuario=None, umbral_dias=UMBRAL_DIAS_REPARACION_ADMIN), hoy,
        ),
        'bodegaje': bodegajes,
        'prueba': prueba,
        'titulos': {
            'diagnostico': f'Sin diagnosticar hace {UMBRAL_DIAS_DIAGNOSTICO} días o más',
            'reparacion': f'En reparación hace {UMBRAL_DIAS_REPARACION_ADMIN} días o más',
            'bodegaje': f'Bodegaje vencido (más de {UMBRAL_DIAS_BODEGAJE} días sin retirar)',
            'prueba': f'Equipos de prueba con {DIAS_ALERTA_EQUIPO_PRUEBA} días o más',
        },
        'url_inicio': _url('econotec:bienvenida'),
    }


def datos_recordatorio_tecnico(tecnico, hoy=None):
    hoy = hoy or date.today()
    return {
        'hoy': hoy,
        'tecnico_nombre': _nombre(tecnico),
        'diagnostico': _items_diagnostico(equipos_demorados_qs(usuario=tecnico), hoy),
        'reparacion': _items_reparacion(
            equipos_reparacion_demorada_qs(usuario=tecnico, umbral_dias=UMBRAL_DIAS_REPARACION_TECNICO), hoy,
        ),
        'titulos': {
            'diagnostico': f'Sin diagnosticar hace {UMBRAL_DIAS_DIAGNOSTICO} días o más',
            'reparacion': f'En reparación hace {UMBRAL_DIAS_REPARACION_TECNICO} días o más',
        },
        'url_inicio': _url('econotec:bienvenida'),
    }


def _enviar(destinos, asunto, plantilla, contexto):
    texto = render_to_string(f'emails/{plantilla}.txt', contexto)
    html = render_to_string(f'emails/{plantilla}.html', contexto)
    correo = EmailMultiAlternatives(
        subject=asunto, body=texto, from_email=settings.DEFAULT_FROM_EMAIL, to=destinos,
    )
    correo.attach_alternative(html, 'text/html')
    return bool(correo.send(fail_silently=False))


def admins_con_correo():
    return User.objects.filter(is_superuser=True, is_active=True).exclude(email='').order_by('pk')


def tecnicos_con_correo():
    return (
        User.objects
        .filter(is_active=True, is_superuser=False, groups__name__in=GRUPOS_TECNICO)
        .exclude(email='')
        .distinct()
        .order_by('pk')
    )


def enviar_resumen_admin(hoy=None):
    """Devuelve cuántos correos se enviaron (0 si no hay nada que avisar)."""
    datos = datos_resumen_admin(hoy)
    total = sum(len(datos[k]) for k in ('diagnostico', 'reparacion', 'bodegaje', 'prueba'))
    if not total:
        return 0
    asunto = f'Resumen diario Econotec {datos["hoy"]:%d/%m/%Y}: {total} equipo{"s" if total != 1 else ""} por revisar'
    enviados = 0
    for admin in admins_con_correo():
        try:
            if _enviar([admin.email.strip()], asunto, 'resumen_diario_admin',
                       {**datos, 'total': total, 'destinatario': _nombre(admin)}):
                enviados += 1
        except Exception:
            logger.exception('No se pudo enviar el resumen diario a %s', admin.username)
    return enviados


def enviar_recordatorios_tecnicos(hoy=None):
    """Devuelve cuántos correos se enviaron."""
    enviados = 0
    for tecnico in tecnicos_con_correo():
        datos = datos_recordatorio_tecnico(tecnico, hoy)
        total = len(datos['diagnostico']) + len(datos['reparacion'])
        if not total:
            continue
        asunto = f'Tienes {total} equipo{"s" if total != 1 else ""} atrasado{"s" if total != 1 else ""} | Econotec'
        try:
            if _enviar([tecnico.email.strip()], asunto, 'recordatorio_tecnico', {**datos, 'total': total}):
                enviados += 1
        except Exception:
            logger.exception('No se pudo enviar el recordatorio al técnico %s', tecnico.username)
    return enviados
