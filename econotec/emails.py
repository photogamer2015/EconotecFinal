"""Correos transaccionales enviados por el sistema Econotec."""

import logging
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from .alertas import COSTO_BODEGAJE_DIA, UMBRAL_DIAS_BODEGAJE
from .models import Abono, IngresoEquipo, SalidaEquipo
from .views_print import (
    _pagos_detallados_ingreso,
    _pagos_detallados_salida,
    generar_ingreso_pdf_bytes,
    generar_salida_pdf_bytes,
)


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


def _dinero_es(valor):
    """Formatea importes incluidos dentro de textos libres del correo."""
    return f'${Decimal(valor or 0):.2f}'.replace('.', ',')


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


def _contexto_bodegaje(salida):
    """Describe la regla y la situación actual sin alterar ningún cálculo."""
    if salida is None:
        return {
            'dias_gracia': UMBRAL_DIAS_BODEGAJE,
            'costo_dia': COSTO_BODEGAJE_DIA,
            'fecha_inicio': None,
            'dias_actuales': 0,
            'monto_actual': Decimal('0.00'),
            'estado': 'La regla inicia cuando el equipo sea finalizado y quede pendiente de retiro',
            'detalle_actual': '',
        }

    ingreso = salida.ingreso
    calculo = salida.calcular_bodegaje()
    if salida.bodegaje_dias_congelado is not None:
        if salida.bodegaje_aplicado_al_pago:
            estado = 'Cobrado y cerrado'
        elif (salida.bodegaje_monto_congelado or Decimal('0.00')) > Decimal('0.00'):
            estado = 'Perdonado y cerrado'
        else:
            estado = 'Cerrado sin cargos'
    elif ingreso.bodegaje_pendiente > Decimal('0.00'):
        estado = 'Pendiente de decisión'
    else:
        estado = 'Dentro del período de gracia'

    detalle_actual = ''
    if calculo['aplica'] and calculo['monto'] > Decimal('0.00'):
        if salida.bodegaje_dias_congelado is not None:
            concepto = 'Monto cobrado' if salida.bodegaje_aplicado_al_pago else 'Monto perdonado'
        else:
            concepto = 'Acumulado actual'
        detalle_actual = (
            f"{calculo['dias']} día(s) · {concepto}: {_dinero_es(calculo['monto'])}"
        )

    return {
        'dias_gracia': UMBRAL_DIAS_BODEGAJE,
        'costo_dia': COSTO_BODEGAJE_DIA,
        'fecha_inicio': salida.fecha_salida,
        'dias_actuales': calculo['dias'] if calculo['aplica'] else 0,
        'monto_actual': calculo['monto'] if calculo['aplica'] else Decimal('0.00'),
        'estado': estado,
        'detalle_actual': detalle_actual,
    }


def _detalle_abono(abono):
    detalle = []
    if abono.metodo == 'transferencia':
        banco = abono.banco_otro if abono.banco == 'otro' else abono.get_banco_display()
        if banco:
            detalle.append(banco)
    elif abono.metodo == 'tarjeta' and abono.tarjeta_app:
        detalle.append(abono.get_tarjeta_app_display())
    if abono.numero_recibo:
        detalle.append(f'Recibo {abono.numero_recibo}')
    if abono.bodegaje_decision == 'si':
        detalle.append(f'Incluye {_dinero_es(abono.bodegaje_monto_aplicado)} de bodegaje')
    elif abono.bodegaje_decision == 'no':
        detalle.append('Bodegaje perdonado')
    return ' · '.join(detalle) or '—'


def _contexto_correo_actualizacion(ingreso, *, tipo, abonos_evento, adjunto_incluido):
    salida = getattr(ingreso, 'salida', None)
    saldo = max(ingreso.diferencia, Decimal('0.00'))
    monto_evento = sum((abono.monto for abono in abonos_evento), Decimal('0.00'))
    if tipo == 'finalizacion':
        etiqueta = 'Equipo finalizado'
        titulo = 'Tu equipo está listo'
        introduccion = (
            'El trabajo técnico de tu equipo fue finalizado. '
            'A continuación encontrarás el estado, los valores y el historial registrado.'
        )
    elif tipo == 'salida':
        etiqueta = 'Salida física confirmada'
        titulo = 'Tu equipo salió de la oficina'
        if abonos_evento:
            introduccion = (
                'Registramos correctamente el pago indicado y confirmamos la entrega '
                'física de tu equipo. Adjuntamos el acta de salida actualizada como respaldo.'
            )
        else:
            introduccion = (
                'Confirmamos la entrega física de tu equipo y su salida de nuestras '
                'instalaciones. Adjuntamos el acta de salida actualizada como respaldo.'
            )
    else:
        etiqueta = 'Abono registrado'
        titulo = 'Recibimos tu abono'
        introduccion = (
            'Registramos correctamente tu abono. '
            'Aquí puedes revisar el valor recibido, todo el historial y el saldo restante.'
        )

    sede = CONTACTO_SEDES.get(ingreso.sede, {
        'nombre': ingreso.get_sede_display(),
        'direccion': '',
    })
    pagos = (
        _pagos_detallados_salida(salida)
        if salida
        else _pagos_detallados_ingreso(ingreso)
    )
    return {
        'tipo': tipo,
        'etiqueta': etiqueta,
        'titulo': titulo,
        'introduccion': introduccion,
        'ingreso': ingreso,
        'salida': salida,
        'cliente': ingreso.cliente,
        'sede': sede,
        'monto_evento': monto_evento,
        'abonos_evento': [
            {
                'fecha': abono.fecha,
                'monto': abono.monto,
                'metodo': abono.get_metodo_display(),
                'detalle': _detalle_abono(abono),
            }
            for abono in abonos_evento
        ],
        'valor_total': ingreso.valor_efectivo_a_cobrar,
        'total_pagado': ingreso.total_abonado,
        'saldo_pendiente': saldo,
        'pagos': pagos,
        'bodegaje': _contexto_bodegaje(salida),
        'adjunto_incluido': adjunto_incluido,
        'whatsapps_econotec': '096 328 9727 · 098 075 8747',
        'sitio_econotec': 'www.econotec.ec.com',
    }


def _enviar_correo_actualizacion(ingreso, *, tipo, abonos_evento=()):
    destino = (ingreso.cliente.correo or '').strip()
    if not destino:
        return False

    salida = getattr(ingreso, 'salida', None)
    adjuntar_pdf = getattr(settings, 'EQUIPO_EMAIL_ADJUNTAR_PDF', True)
    pdf = None
    nombre_pdf = ''
    if adjuntar_pdf:
        if salida:
            pdf = generar_salida_pdf_bytes(salida)
            if tipo == 'salida':
                nombre_pdf = f'Acta_salida_oficina_{ingreso.codigo_equipo}.pdf'
            else:
                nombre_pdf = f'Acta_equipo_finalizado_{ingreso.codigo_equipo}.pdf'
        else:
            pdf = generar_ingreso_pdf_bytes(ingreso)
            nombre_pdf = f'Hoja_equipo_{ingreso.codigo_equipo}.pdf'

    contexto = _contexto_correo_actualizacion(
        ingreso,
        tipo=tipo,
        abonos_evento=abonos_evento,
        adjunto_incluido=bool(pdf),
    )
    if tipo == 'finalizacion':
        asunto = f'Equipo {ingreso.codigo_equipo} finalizado | Econotec'
    elif tipo == 'salida':
        asunto = f'Salida de la oficina confirmada {ingreso.codigo_equipo} | Econotec'
    else:
        asunto = f'Abono registrado {ingreso.codigo_equipo} | Econotec'

    texto = render_to_string('emails/equipo_actualizacion.txt', contexto)
    html = render_to_string('emails/equipo_actualizacion.html', contexto)
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
        correo.attach(nombre_pdf, pdf, 'application/pdf')
    return bool(correo.send(fail_silently=False))


def enviar_correo_finalizacion_seguro(salida_pk):
    """Envía el acta final después de la confirmación del usuario."""
    try:
        salida = SalidaEquipo.objects.select_related(
            'ingreso',
            'ingreso__cliente',
            'tecnico_reparo',
            'registrado_por',
        ).prefetch_related('ingreso__abonos').get(pk=salida_pk)
        return _enviar_correo_actualizacion(
            salida.ingreso,
            tipo='finalizacion',
        )
    except Exception:
        logger.exception(
            'No se pudo enviar el correo de finalización para salida pk=%s.',
            salida_pk,
        )
        return False


def enviar_correo_abono_seguro(ingreso_pk, abono_pks, *, salida_confirmada=False):
    """Envía el comprobante actualizado sin poner en riesgo el abono guardado."""
    try:
        ingreso = IngresoEquipo.objects.select_related(
            'cliente',
            'tecnico_encargado',
            'registrado_por',
            'salida',
            'salida__tecnico_reparo',
            'salida__registrado_por',
        ).prefetch_related('abonos').get(pk=ingreso_pk)
        abonos = list(
            Abono.objects.filter(pk__in=abono_pks, ingreso=ingreso).order_by('pk')
        )
        if not abonos:
            return False
        return _enviar_correo_actualizacion(
            ingreso,
            tipo='salida' if salida_confirmada else 'abono',
            abonos_evento=abonos,
        )
    except Exception:
        logger.exception(
            'No se pudo enviar el correo de abono para ingreso pk=%s, abonos=%s.',
            ingreso_pk,
            abono_pks,
        )
        return False


def enviar_correo_salida_fisica_seguro(salida_pk, abono_pks=()):
    """Envía el acta de salida actualizada sin comprometer el cierre guardado."""
    try:
        salida = SalidaEquipo.objects.select_related(
            'ingreso',
            'ingreso__cliente',
            'tecnico_reparo',
            'registrado_por',
        ).prefetch_related('ingreso__abonos').get(pk=salida_pk)
        abonos = list(
            Abono.objects.filter(
                pk__in=tuple(abono_pks),
                ingreso=salida.ingreso,
            ).order_by('pk')
        )
        return _enviar_correo_actualizacion(
            salida.ingreso,
            tipo='salida',
            abonos_evento=abonos,
        )
    except Exception:
        logger.exception(
            'No se pudo enviar el acta de salida física para salida pk=%s, abonos=%s.',
            salida_pk,
            abono_pks,
        )
        return False


def _contexto_correo_bodegaje(salida, *, adjunto_incluido):
    ingreso = salida.ingreso
    calculo = salida.calcular_bodegaje()
    saldo_reparacion = max(ingreso.diferencia, Decimal('0.00'))
    bodegaje_monto = calculo['monto'] if calculo['aplica'] else Decimal('0.00')
    sede = CONTACTO_SEDES.get(ingreso.sede, {
        'nombre': ingreso.get_sede_display(),
        'direccion': '',
    })
    return {
        'salida': salida,
        'ingreso': ingreso,
        'cliente': ingreso.cliente,
        'sede': sede,
        'dias_totales': max((date.today() - salida.fecha_salida).days, 0),
        'dias_bodegaje': calculo['dias'] if calculo['aplica'] else 0,
        'bodegaje_monto': bodegaje_monto,
        'saldo_reparacion': saldo_reparacion,
        'total_a_regularizar': saldo_reparacion + bodegaje_monto,
        'dias_gracia': UMBRAL_DIAS_BODEGAJE,
        'costo_dia': COSTO_BODEGAJE_DIA,
        'pagos': _pagos_detallados_salida(salida),
        'adjunto_incluido': adjunto_incluido,
        'whatsapps_econotec': '096 328 9727 · 098 075 8747',
        'sitio_econotec': 'www.econotec.ec.com',
    }


def enviar_correo_bodegaje(salida):
    """Envía un aviso formal de retiro, deuda, bodegaje y chatarrerización."""
    destino = (salida.ingreso.cliente.correo or '').strip()
    if not destino:
        return False

    adjuntar_pdf = getattr(settings, 'EQUIPO_EMAIL_ADJUNTAR_PDF', True)
    pdf = generar_salida_pdf_bytes(salida) if adjuntar_pdf else None
    contexto = _contexto_correo_bodegaje(
        salida,
        adjunto_incluido=bool(pdf),
    )
    ingreso = salida.ingreso
    asunto = f'Aviso importante de retiro y bodegaje {ingreso.codigo_equipo} | Econotec'
    texto = render_to_string('emails/bodegaje_recordatorio.txt', contexto)
    html = render_to_string('emails/bodegaje_recordatorio.html', contexto)

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
            f'Acta_actualizada_{ingreso.codigo_equipo}.pdf',
            pdf,
            'application/pdf',
        )
    return bool(correo.send(fail_silently=False))


def enviar_correo_bodegaje_seguro(salida_pk):
    """Envía el aviso sin permitir que una falla afecte el expediente."""
    try:
        salida = SalidaEquipo.objects.select_related(
            'ingreso',
            'ingreso__cliente',
            'tecnico_reparo',
            'registrado_por',
        ).prefetch_related('ingreso__abonos').get(pk=salida_pk)
        return enviar_correo_bodegaje(salida)
    except Exception:
        logger.exception(
            'No se pudo enviar el aviso de bodegaje para salida pk=%s.',
            salida_pk,
        )
        return False
