from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Perfil, Rol


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def crear_perfil(sender, instance, created, **kwargs):
    """Cada usuario de Econotec tiene su perfil del CRM (rol y si recibe clientes automáticos)."""
    if created and not kwargs.get("raw"):
        Perfil.objects.get_or_create(
            user=instance, defaults={"rol": Rol.ADMIN if instance.is_superuser else Rol.EJECUTIVO}
        )
