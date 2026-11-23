"""
Aviso a la asesora para que realice la factura de un equipo finalizado.

- En «Finalizar equipo» / «Editar finalización», con «¿Factura realizada? = Sí»,
  se elige la asesora (obligatorio) y se le avisa en ese momento.
- Después, desde la tabla de finalizados, la campanita 🔔 vuelve a avisar a la
  misma asesora, una vez cada 24 horas.
- El aviso aparece en la campanita de la asesora (NotificacionAsesora de tipo
  «Factura por realizar») y le llega como notificación push.
"""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import NotificacionAsesora, SalidaEquipo

TIPO = NotificacionAsesora.TIPO_FACTURA


def nombre_usuario(usuario):
    if not usuario:
        return ''
    return usuario.get_full_name() or usuario.username


def _valor_factura(salida):
    if salida.tiene_retencion:
        return salida.valor_con_retencion or Decimal('0.00')
    return Decimal('0.00')


def mensaje_factura(salida):
    ingreso = salida.ingreso
    partes = [
        f'Realizar la factura del equipo {ingreso.codigo_equipo} '
        f'({ingreso.tipo_equipo_display} — {ingreso.marca}) del cliente {ingreso.cliente.nombres}.',
    ]
    datos = []
    if salida.factura_nombres:
        datos.append(f'Nombres / Razón social: {salida.factura_nombres}')
    if salida.factura_cedula:
        datos.append(f'Cédula / RUC: {salida.factura_cedula}')
    if salida.factura_correo:
        datos.append(f'Correo: {salida.factura_correo}')
    if salida.tiene_retencion:
        datos.append(f'Con retención · Total factura: ${salida.valor_con_retencion:.2f}')
    if datos:
        partes.append(' · '.join(datos) + '.')
    return ' '.join(partes)


def _avisar(salida, asesora, usuario):
    """Deja el aviso nuevo en la campanita de la asesora (y le llega el push)."""
    ahora = timezone.now()
    # Se reemplaza el aviso anterior: así vuelve a quedar pendiente, sale
    # primero en su lista y se envía el push como aviso nuevo.
    NotificacionAsesora.objects.filter(salida=salida, tipo=TIPO).delete()
    NotificacionAsesora.objects.create(
        salida=salida,
        ingreso=salida.ingreso,
        tipo=TIPO,
        asesora=asesora,
        creado_por=usuario,
        valor_acordado=_valor_factura(salida),
        mensaje=mensaje_factura(salida),
    )
    SalidaEquipo.objects.filter(pk=salida.pk).update(
        factura_asesora=asesora, factura_notificada_en=ahora,
    )
    salida.factura_asesora = asesora
    salida.factura_notificada_en = ahora


def sincronizar_desde_formulario(salida, asesora, usuario):
    """Después de guardar la finalización. Devuelve True si se avisó a la asesora.

    - Factura «No»: se quita el aviso pendiente y la asesora asignada.
    - Asesora nueva (o nunca avisada): se le avisa ahora.
    - Misma asesora ya avisada: no se repite (para eso está la campanita
      cada 24 horas); solo se actualizan los datos del aviso.
    """
    if salida.factura_realizada != 'si':
        if salida.factura_asesora_id or salida.factura_notificada_en:
            NotificacionAsesora.objects.filter(salida=salida, tipo=TIPO).delete()
            SalidaEquipo.objects.filter(pk=salida.pk).update(
                factura_asesora=None, factura_notificada_en=None,
            )
            salida.factura_asesora = None
            salida.factura_notificada_en = None
        return False

    if asesora is None:
        return False

    if salida.factura_asesora_id == asesora.pk and salida.factura_notificada_en:
        NotificacionAsesora.objects.filter(salida=salida, tipo=TIPO).update(
            mensaje=mensaje_factura(salida),
            valor_acordado=_valor_factura(salida),
        )
        return False

    _avisar(salida, asesora, usuario)
    return True


def reavisar(salida_pk, usuario):
    """Campanita de la tabla. Devuelve (ok, mensaje)."""
    with transaction.atomic():
        salida = (
            SalidaEquipo.objects
            .select_for_update()
            .select_related('ingreso', 'ingreso__cliente', 'factura_asesora')
            .get(pk=salida_pk)
        )
        codigo = salida.ingreso.codigo_equipo
        if salida.factura_realizada != 'si':
            return False, f'El equipo {codigo} no tiene factura «Sí».'
        asesora = salida.factura_asesora
        if asesora is None:
            return False, f'Elige la asesora de la factura en «Editar finalización» del equipo {codigo}.'
        if not asesora.is_active:
            return False, (
                f'{nombre_usuario(asesora)} ya no está activa. '
                f'Elige otra asesora en «Editar finalización» del equipo {codigo}.'
            )
        if not salida.puede_reavisar_factura:
            disponible = timezone.localtime(salida.aviso_factura_disponible_en)
            return False, (
                f'A {nombre_usuario(asesora)} ya se le avisó de la factura del equipo {codigo}. '
                f'Podrás volver a avisarle desde el {disponible:%d/%m/%Y a las %H:%M}.'
            )
        _avisar(salida, asesora, usuario)
    return True, f'Se volvió a avisar a {nombre_usuario(asesora)} de la factura del equipo {codigo}.'
