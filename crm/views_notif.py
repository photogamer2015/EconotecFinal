"""Centro de notificaciones: cambios del equipo, leads nuevos y avisos generales."""
from django.contrib import messages
from .roles import crm_requerido
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import notificaciones as notif
from .forms import AvisoForm
from .models import Notificacion
from .roles import es_supervisor


@crm_requerido
def notificaciones(request):
    qs = Notificacion.objects.filter(destinatario=request.user).select_related("actor")
    f = {"estado": request.GET.get("estado", ""), "tipo": request.GET.get("tipo", "")}
    if f["estado"] == "sin_leer":
        qs = qs.filter(leida=False)
    if f["tipo"] in Notificacion.Tipo.values:
        qs = qs.filter(tipo=f["tipo"])
    pagina = Paginator(qs, 30).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "crm/notificaciones.html", {
        "pagina": pagina, "f": f, "tipos": Notificacion.Tipo.choices, "params": params.urlencode(),
        "aviso_form": AvisoForm() if es_supervisor(request.user) else None,
        "sin_leer": notif.no_leidas(request.user).count(),
    })


@crm_requerido
def notificacion_ir(request, pk):
    """Marca como leída y lleva a la pantalla relacionada."""
    n = get_object_or_404(Notificacion, pk=pk, destinatario=request.user)
    if not n.leida:
        n.leida = True
        n.save(update_fields=["leida"])
    if n.url and url_has_allowed_host_and_scheme(n.url, allowed_hosts={request.get_host()}):
        return redirect(n.url)
    return redirect("crm:notificaciones")


@crm_requerido
@require_POST
def notificaciones_leidas(request):
    n = notif.no_leidas(request.user).update(leida=True)
    if request.headers.get("x-requested-with") == "fetch":
        return JsonResponse({"ok": True, "marcadas": n})
    messages.success(request, "Todas las notificaciones quedaron como leídas.")
    return redirect(request.POST.get("next") or "crm:notificaciones")


@crm_requerido
def notificaciones_estado(request):
    """Para la campana: cuántas sin leer y las últimas (se consulta cada 20 s)."""
    qs = Notificacion.objects.filter(destinatario=request.user).select_related("actor")[:8]
    return JsonResponse({
        "sin_leer": notif.no_leidas(request.user).count(),
        "ultimas": [
            {
                "id": n.id, "texto": n.texto, "tipo": n.tipo, "tipo_nombre": n.get_tipo_display(), "leida": n.leida,
                "fecha": timezone.localtime(n.fecha).strftime("%d/%m %H:%M"), "url": reverse("crm:notificacion_ir", args=[n.id]),
            }
            for n in qs
        ],
    })


@crm_requerido
@require_POST
def aviso_general(request):
    if not es_supervisor(request.user):
        return redirect("crm:notificaciones")
    form = AvisoForm(request.POST)
    if form.is_valid():
        n = notif.aviso_general(request.user, f"📢 {notif.nombre(request.user)}: {form.cleaned_data['texto']}")
        messages.success(request, f"Aviso enviado a {n} personas del equipo.")
    else:
        messages.error(request, "Escribe el aviso (máx. 400 caracteres).")
    return redirect("crm:notificaciones")
