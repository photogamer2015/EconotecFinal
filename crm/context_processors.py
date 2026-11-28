from django.db.models import Sum
from django.utils import timezone

from . import whatsapp_api, whatsapp_qr
from .models import Notificacion
from .roles import conversaciones_visibles, es_admin, es_supervisor, puede_entrar, rol_de, seguimientos_visibles


def crm_global(request):
    """Datos del CRM. Fuera de /crm/ solo expone `crm_acceso` (perezoso) para el botón de la bienvenida."""
    u = getattr(request, "user", None)
    if not u or not u.is_authenticated:
        return {}
    if not request.path.startswith("/crm/"):
        return {"crm_acceso": lambda: puede_entrar(u)}
    rol = rol_de(u)
    if rol is None:
        return {"crm_acceso": False}
    fin_dia = timezone.localtime().replace(hour=23, minute=59, second=59)
    return {
        "crm_acceso": True,
        "rol": rol,
        "es_admin": es_admin(u),
        "es_supervisor": es_supervisor(u),
        "nav_pendientes": seguimientos_visibles(u).filter(completado=False, fecha_hora__lte=fin_dia).count(),
        "nav_notif": Notificacion.objects.filter(destinatario=u, leida=False).count(),
        "nav_chats": conversaciones_visibles(u).filter(canal="whatsapp").aggregate(s=Sum("no_leidos"))["s"] or 0,
        "wa_qr_activo": whatsapp_qr.activo(),
        "wa_api_activo": whatsapp_api.activo(),
        "wa_chats_activo": whatsapp_qr.activo() or whatsapp_api.activo(),
        # Mensajes salen solos desde el CRM (API oficial, o QR vinculado y conectado); si no, se abre wa.me.
        "wa_envio_directo": lambda: whatsapp_api.activo() or (
            whatsapp_qr.activo() and whatsapp_qr.estado().get("estado") == "conectado"
        ),
    }
