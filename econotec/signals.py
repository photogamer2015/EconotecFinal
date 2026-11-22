"""Al crearse un aviso de campanita, se envía también como notificación push."""
from django.contrib.auth.signals import user_logged_out
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from . import push
from .models import (
    NotificacionAsesora,
    NotificacionCambioAdmin,
    NotificacionInventarioAdmin,
    NotificacionRevisionAdmin,
    NotificacionTecnico,
)


@receiver(post_save, sender=NotificacionCambioAdmin)
def _push_cambio(sender, instance, created, raw=False, **kwargs):
    if created and not raw:
        push.push_cambio_admin(instance)


@receiver(post_save, sender=NotificacionRevisionAdmin)
def _push_revision(sender, instance, created, raw=False, **kwargs):
    if created and not raw:
        push.push_revision_admin(instance)


@receiver(post_save, sender=NotificacionInventarioAdmin)
def _push_inventario(sender, instance, created, raw=False, **kwargs):
    if created and not raw:
        push.push_inventario_admin(instance)


@receiver(post_save, sender=NotificacionTecnico)
def _push_tecnico(sender, instance, created, raw=False, **kwargs):
    if created and not raw:
        push.push_tecnico(instance)


@receiver(pre_save, sender=NotificacionAsesora)
def _asesora_antes(sender, instance, raw=False, **kwargs):
    instance._push_antes = None
    if instance.pk and not raw:
        instance._push_antes = (
            sender.objects.filter(pk=instance.pk).values('leida', 'asesora_id').first()
        )


@receiver(post_save, sender=NotificacionAsesora)
def _push_asesora(sender, instance, created, raw=False, **kwargs):
    # Al editar la salida el aviso se vuelve a guardar: solo se avisa si es
    # nuevo, si ya se había visto y vuelve a quedar pendiente, o si cambió de asesora.
    if raw or instance.leida:
        return
    antes = getattr(instance, '_push_antes', None)
    if created or antes is None or antes['leida'] or antes['asesora_id'] != instance.asesora_id:
        push.push_asesora(instance)


@receiver(user_logged_out)
def _quitar_push_al_salir(sender, request, user, **kwargs):
    # Si cierra sesión, este dispositivo deja de recibir sus avisos.
    endpoint = request.session.get('push_endpoint') if request is not None else None
    if endpoint and user is not None:
        from .models import SuscripcionPush
        SuscripcionPush.objects.filter(endpoint=endpoint, usuario=user).delete()
