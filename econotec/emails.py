"""Correos transaccionales enviados por el sistema Econotec."""

import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from .models import IngresoEquipo
from .views_print import generar_ingreso_pdf_bytes


logger = logging.getLogger(__name__)


CONTACTO_SEDES = {
    'guayaquil': {
        'nombre': 'Guayaquil',
        'direccion': 'Sauces 8, Mz. 462, Solar 6, piso 2, oficina 2',
    },
    'quito': {
        'nombre': 'Quito',
        'direccion': 'Av. Amazonas y 18 de Septiembre, piso 2, oficina 102',
    },
}


def _nombre_usuario(usuario):
    if not usuario:
        return '—'
    return (usuario.get_full_name() or usuario.username).strip()


def _contexto_correo_ingreso(ingreso, *, adjunto_incluido):
    sede = CONTACTO_SEDES.get(ingreso.sede, {
        'nombre': ingreso.get_sede_display(),
        'direccion': '',
    })
    return {
        'ingreso': ingreso,
        'cliente': ingreso.cliente,
        'sede': sede,
        'tecnico_nombre': ingreso.tecnico_encargado_nombre or 'Por asignar',
        'registrado_por_nombre': _nombre_usuario(ingreso.registrado_por),
        'adjunto_incluido': adjunto_incluido,
        'whatsapps_econotec': '096 328 9727 · 098 075 8747',
        'sitio_econotec': 'www.econotec.ec.com',
    }


def enviar_correo_ingreso(ingreso):
    """Envía al cliente la confirmación de ingreso y su PDF oficial."""
    destino = (ingreso.cliente.correo or '').strip()
    if not destino:
        return False

    adjuntar_pdf = getattr(settings, 'INGRESO_EMAIL_ADJUNTAR_PDF', True)
    pdf = generar_ingreso_pdf_bytes(ingreso) if adjuntar_pdf else None
    contexto = _contexto_correo_ingreso(
        ingreso,
        adjunto_incluido=bool(pdf),
    )
    asunto = f'Confirmación de ingreso {ingreso.codigo_equipo} | Econotec'
    texto = render_to_string('emails/ingreso_registrado.txt', contexto)
    html = render_to_string('emails/ingreso_registrado.html', contexto)

    opciones = {}
    reply_to = (getattr(settings, 'ECONOTEC_REPLY_TO', '') or '').strip()
    if reply_to:
        opciones['reply_to'] = [reply_to]

    correo = EmailMultiAlternatives(
        subject=asunto,
        body=texto,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[destino],
        **opciones,
    )
    correo.attach_alternative(html, 'text/html')
    if pdf:
        correo.attach(
            f'Solicitud_de_ingreso_{ingreso.codigo_equipo}.pdf',
            pdf,
            'application/pdf',
        )
    return bool(correo.send(fail_silently=False))


def enviar_correo_ingreso_seguro(ingreso_pk):
    """Envía después del commit sin permitir que un fallo afecte el registro."""
    try:
        ingreso = IngresoEquipo.objects.select_related(
            'cliente',
            'tecnico_encargado',
            'registrado_por',
        ).get(pk=ingreso_pk)
        return enviar_correo_ingreso(ingreso)
    except Exception:
        logger.exception(
            'No se pudo enviar el correo automático del ingreso pk=%s.',
            ingreso_pk,
        )
        return False
