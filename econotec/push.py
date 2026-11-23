"""
Notificaciones push al celular o computadora.

Cada usuario (admin, técnico o asesora) activa los avisos desde el navegador:
el navegador entrega una suscripción (SuscripcionPush) y aquí se le envían los
mismos avisos que aparecen en sus campanitas:

- Admins: cambios 🔔, revisión 🔎 e inventario 📦.
- Técnico: los equipos que una asesora le pide revisar.
- Asesora: los cobros pendientes que le asignan.

Las claves VAPID se crean solas la primera vez y se guardan en la base de datos
(ClavesPush). Si se definen VAPID_PUBLIC_KEY y VAPID_PRIVATE_KEY en el .env,
se usan esas.

El envío se hace en un hilo aparte después de guardar en la base de datos, así
la página no espera al servicio push.
"""
import base64
import json
import logging
import threading

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

logger = logging.getLogger(__name__)

TTL_SEGUNDOS = 60 * 60 * 24  # si el celular está apagado, el aviso espera hasta 1 día


# ── Claves VAPID ─────────────────────────────────────────

def _b64url(datos):
    return base64.urlsafe_b64encode(datos).rstrip(b'=').decode('ascii')


def _clave_publica_de_vapid(vapid):
    from cryptography.hazmat.primitives import serialization
    return _b64url(vapid.public_key.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    ))


def claves_vapid():
    """Devuelve (clave_publica, clave_privada_pem)."""
    publica = getattr(settings, 'VAPID_PUBLIC_KEY', '')
    privada = getattr(settings, 'VAPID_PRIVATE_KEY', '')
    if publica and privada:
        return publica, privada.replace('\\n', '\n')

    from py_vapid import Vapid
    from .models import ClavesPush

    claves = ClavesPush.objects.order_by('pk').first()
    if claves is None:
        vapid = Vapid()
        vapid.generate_keys()
        claves = ClavesPush.objects.create(
            clave_publica=_clave_publica_de_vapid(vapid),
            clave_privada=vapid.private_pem().decode('ascii'),
        )
    return claves.clave_publica, claves.clave_privada


def clave_publica():
    return claves_vapid()[0]


# ── Destinatarios ────────────────────────────────────────

def admins_ids():
    return list(
        get_user_model().objects
        .filter(is_superuser=True, is_active=True)
        .values_list('pk', flat=True)
    )


# ── Envío ────────────────────────────────────────────────

def _enviar_a_suscripcion(suscripcion, datos, vapid):
    from pywebpush import WebPushException, webpush

    from .models import SuscripcionPush

    try:
        webpush(
            subscription_info={
                'endpoint': suscripcion.endpoint,
                'keys': {'p256dh': suscripcion.p256dh, 'auth': suscripcion.auth},
            },
            data=json.dumps(datos),
            vapid_private_key=vapid,
            vapid_claims={'sub': getattr(settings, 'SISTEMA_URL', '') or 'https://econosystem.cc'},
            ttl=TTL_SEGUNDOS,
            headers={'Urgency': 'high'},
            timeout=10,
        )
    except WebPushException as exc:
        estado = getattr(exc, 'status_code', None) or getattr(getattr(exc, 'response', None), 'status_code', None)
        if estado in (404, 410):
            # El usuario desactivó los avisos o desinstaló la app: ya no sirve.
            SuscripcionPush.objects.filter(pk=suscripcion.pk).delete()
        else:
            logger.warning('Push falló (%s) para %s: %s', estado, suscripcion.usuario_id, exc)
        return False
    except Exception:
        logger.exception('Push falló para el usuario %s', suscripcion.usuario_id)
        return False
    SuscripcionPush.objects.filter(pk=suscripcion.pk).update(ultimo_envio=timezone.now())
    return True


def enviar_push_ahora(usuarios_ids, titulo, cuerpo, url='', etiqueta=''):
    """Envía ya (sin hilo). Devuelve cuántos dispositivos lo recibieron."""
    if not getattr(settings, 'PUSH_ACTIVO', True):
        return 0
    from .models import SuscripcionPush

    suscripciones = list(
        SuscripcionPush.objects
        .filter(usuario_id__in=set(usuarios_ids), usuario__is_active=True)
    )
    if not suscripciones:
        return 0

    from py_vapid import Vapid
    vapid = Vapid.from_pem(claves_vapid()[1].encode('ascii'))
    datos = {
        'titulo': titulo[:120],
        'cuerpo': (cuerpo or '')[:400],
        'url': url or reverse('econotec:bienvenida'),
        'etiqueta': etiqueta,
    }
    return sum(1 for s in suscripciones if _enviar_a_suscripcion(s, datos, vapid))


def _en_hilo(*args, **kwargs):
    try:
        enviar_push_ahora(*args, **kwargs)
    except Exception:
        logger.exception('Error enviando notificaciones push')
    finally:
        from django.db import connection
        connection.close()


def enviar_push(usuarios_ids, titulo, cuerpo, url='', etiqueta=''):
    """Programa el envío para cuando se confirme el guardado en la base de datos."""
    usuarios_ids = [pk for pk in set(usuarios_ids) if pk]
    if not usuarios_ids or not getattr(settings, 'PUSH_ACTIVO', True):
        return

    def lanzar():
        if getattr(settings, 'PUSH_SINCRONO', False):
            enviar_push_ahora(usuarios_ids, titulo, cuerpo, url, etiqueta)
        else:
            threading.Thread(
                target=_en_hilo,
                args=(usuarios_ids, titulo, cuerpo, url, etiqueta),
                daemon=True,
            ).start()

    transaction.on_commit(lanzar)


# ── Avisos de cada campanita ─────────────────────────────

def _nombre(usuario):
    if not usuario:
        return ''
    return usuario.get_full_name() or usuario.username


def push_cambio_admin(aviso):
    destinos = [pk for pk in admins_ids() if pk != aviso.creado_por_id]
    titulo = f'🔔 {aviso.usuario_nombre or "Cambio"}'
    if aviso.codigo:
        titulo += f' · {aviso.codigo}'
    enviar_push(
        destinos, titulo, aviso.mensaje,
        url=reverse('econotec:notificacion_cambio_admin_ver', args=[aviso.pk]),
        etiqueta=f'cambio-{aviso.pk}',
    )


def push_revision_admin(aviso):
    destinos = [pk for pk in admins_ids() if pk != aviso.creado_por_id]
    codigo = aviso.salida.ingreso.codigo_equipo
    enviar_push(
        destinos, f'🔎 {aviso.get_tipo_display()} · {codigo}', aviso.mensaje,
        url=reverse('econotec:notificacion_revision_admin_ver', args=[aviso.pk]),
        etiqueta=f'revision-{aviso.pk}',
    )


def push_inventario_admin(aviso):
    destinos = [pk for pk in admins_ids() if pk != aviso.creado_por_id]
    enviar_push(
        destinos, '📦 Inventario con stock crítico', aviso.mensaje,
        url=reverse('econotec:notificacion_inventario_admin_ver', args=[aviso.pk]),
        etiqueta=f'inventario-{aviso.pk}',
    )


def push_tecnico(aviso):
    quien = _nombre(aviso.creado_por) or 'Una asesora'
    enviar_push(
        [aviso.tecnico_id], f'🔔 {quien} te pide revisar {aviso.ingreso.codigo_equipo}', aviso.mensaje,
        url=reverse('econotec:notificaciones_tecnico'),
        etiqueta=f'tecnico-{aviso.pk}',
    )


def push_asesora(aviso):
    icono = '🧾' if aviso.tipo == aviso.TIPO_FACTURA else '🔔'
    enviar_push(
        [aviso.asesora_id], f'{icono} {aviso.get_tipo_display()} · {aviso.ingreso.codigo_equipo}', aviso.mensaje,
        url=reverse('econotec:notificaciones_asesora'),
        etiqueta=f'asesora-{aviso.salida_id}-{aviso.tipo}',
    )
