"""Ajustes de WhatsApp (número y mensajes predeterminados), categorías/pipelines y etiquetas."""
from django.contrib import messages
from .roles import crm_requerido
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import bot, services, whatsapp_qr
from . import notificaciones as notif
from .forms import CategoriaForm, ConfiguracionForm, EtiquetaForm, RespuestaForm
from .models import Categoria, Configuracion, Etiqueta, Oportunidad, Respuesta, Rol
from .roles import es_supervisor, rol_requerido

NT = notif.Tipo
SUP = (Rol.ADMIN, Rol.GERENTE)


# ------------------------------------------------------------------ WhatsApp y respuestas
@rol_requerido(*SUP)
def whatsapp(request):
    cfg = Configuracion.actual()
    form = ConfiguracionForm(request.POST or None, instance=cfg)
    if request.method == "POST" and form.is_valid():
        form.save()
        if form.changed_data:
            nombres = ", ".join(str(form.fields[c].label).lower() for c in form.changed_data)
            notif.notificar(request.user, NT.CONFIG, f"{notif.nombre(request.user)} cambió la configuración de WhatsApp: {nombres}.",
                            reverse("crm:whatsapp"))
        messages.success(request, "Configuración guardada.")
        return redirect("crm:whatsapp")

    base = request.build_absolute_uri("/").rstrip("/")
    ejemplo = services.render(cfg.mensaje_boton, {"nombre": "Ana", "servicio": "Venta de laptops y computadoras", "empresa": "ACME"})
    pred = services.plantillas_activas().first()
    ejemplo_cliente = services.render(pred.texto, {"nombre": "Ana", "servicio": "Venta de laptops y computadoras",
                                                   "empresa": "ACME", "asesor": notif.nombre(request.user),
                                                   "horario": cfg.horario}) if pred else ""
    return render(request, "crm/whatsapp.html", {
        "form": form,
        "cfg": cfg,
        "respuestas": Respuesta.objects.filter(palabras_clave=""),
        "respuestas_bot": Respuesta.objects.exclude(palabras_clave=""),
        "wa_activo": whatsapp_qr.activo(),
        "wa": whatsapp_qr.estado(),
        "prueba_bot": bot.probar(request.GET["probar"]) if request.GET.get("probar") else None,
        "categorias": Categoria.objects.all(),
        "base": base,
        "link_prueba": services.wa_link(cfg.numero_whatsapp, ejemplo) if cfg.numero_whatsapp else "",
        "ejemplo": ejemplo,
        "ejemplo_cliente": ejemplo_cliente,
    })


def _guardar(request, form, tipo, que, volver):
    obj = form.save()
    notif.notificar(request.user, tipo, f"{notif.nombre(request.user)} {que}: {obj}.", reverse(volver))
    messages.success(request, f"Guardado: {obj}.")
    return obj


@rol_requerido(*SUP)
def respuesta_editar(request, pk=None):
    obj = get_object_or_404(Respuesta, pk=pk) if pk else None
    form = RespuestaForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        r = _guardar(request, form, NT.CONFIG, "editó el mensaje predeterminado" if obj else "creó el mensaje predeterminado", "crm:whatsapp")
        if r.predeterminada:  # solo uno puede ser el predeterminado
            Respuesta.objects.exclude(pk=r.pk).update(predeterminada=False)
        return redirect(reverse("crm:whatsapp") + "#respuestas")
    return render(request, "crm/form.html", {
        "form": form, "titulo": "Editar mensaje" if obj else "Nuevo mensaje predeterminado", "volver": "crm:whatsapp",
        "intro": "Estos mensajes aparecen al tocar «Enviar por WhatsApp» en la ficha o en la lista de clientes. "
                 "El marcado como predeterminado es el que se carga primero al abrir el chat.",
        "borrar": reverse("crm:respuesta_borrar", args=[obj.pk]) if obj else "",
    })


@rol_requerido(*SUP)
@require_POST
def respuesta_borrar(request, pk):
    obj = get_object_or_404(Respuesta, pk=pk)
    nombre = str(obj)
    obj.delete()
    notif.notificar(request.user, NT.CONFIG, f"{notif.nombre(request.user)} eliminó el mensaje: {nombre}.",
                    reverse("crm:whatsapp"))
    messages.success(request, f"Mensaje «{nombre}» eliminado.")
    return redirect(reverse("crm:whatsapp") + "#respuestas")


@rol_requerido(*SUP)
def categoria_editar(request, pk=None):
    obj = get_object_or_404(Categoria, pk=pk) if pk else None
    nombre_antes = obj.nombre if obj else None
    form = CategoriaForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        cat = _guardar(request, form, NT.CONFIG, "editó la categoría" if obj else "creó la categoría", "crm:whatsapp")
        if nombre_antes and nombre_antes != cat.nombre:  # las oportunidades siguen en su pipeline
            Oportunidad.objects.filter(servicio=nombre_antes).update(servicio=cat.nombre)
        return redirect(reverse("crm:whatsapp") + "#categorias")
    return render(request, "crm/form.html", {
        "form": form, "titulo": f"Editar {obj}" if obj else "Nueva categoría", "volver": "crm:whatsapp",
        "intro": "Cada categoría es un pipeline (una pestaña en Pipelines) y una opción al registrar un cliente.",
    })


# ------------------------------------------------------------------ Etiquetas
@crm_requerido
def etiquetas(request):
    form = EtiquetaForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        e = form.save(commit=False)
        e.creado_por = request.user
        e.save()
        notif.notificar(request.user, NT.ETIQUETA, f"{notif.nombre(request.user)} creó la etiqueta «{e.nombre}».",
                        reverse("crm:etiquetas"))
        messages.success(request, f"Etiqueta «{e.nombre}» creada.")
        return redirect("crm:etiquetas")
    from django.db.models import Count, Q

    lista = Etiqueta.objects.annotate(
        n=Count("oportunidades", distinct=True),
        abiertas=Count("oportunidades", filter=Q(oportunidades__etapa__in=Oportunidad.ETAPAS_ABIERTAS), distinct=True),
    )
    return render(request, "crm/etiquetas.html", {"form": form, "lista": lista, "puede_editar": es_supervisor(request.user)})


@rol_requerido(*SUP)
def etiqueta_editar(request, pk):
    obj = get_object_or_404(Etiqueta, pk=pk)
    antes = obj.nombre
    form = EtiquetaForm(request.POST or None, instance=obj)
    if request.method == "POST":
        if request.POST.get("accion") == "borrar":
            n = obj.oportunidades.count()
            obj.delete()
            notif.notificar(request.user, NT.ETIQUETA,
                            f"{notif.nombre(request.user)} eliminó la etiqueta «{antes}» (estaba en {n} oportunidades).",
                            reverse("crm:etiquetas"))
            messages.success(request, f"Etiqueta «{antes}» eliminada.")
            return redirect("crm:etiquetas")
        if form.is_valid():
            e = form.save()
            notif.notificar(request.user, NT.ETIQUETA, f"{notif.nombre(request.user)} editó la etiqueta «{antes}» → «{e.nombre}».",
                            reverse("crm:etiquetas"))
            messages.success(request, "Etiqueta actualizada.")
            return redirect("crm:etiquetas")
    return render(request, "crm/form.html", {
        "form": form, "titulo": f"Editar etiqueta «{obj.nombre}»", "volver": "crm:etiquetas",
        "borrar": request.path,
    })

