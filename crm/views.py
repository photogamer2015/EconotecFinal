"""Vistas del CRM comercial: Resultados, Bandeja, Oportunidades, Bitácora y Seguimientos."""
import calendar
import csv
import json
from datetime import datetime, timedelta

from django.contrib import messages
from .roles import crm_requerido
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import services
from . import notificaciones as notif
from .forms import ActividadForm, ClienteForm, ContactoForm, OportunidadEditarForm, SeguimientoForm
from .models import SEDES_CRM, Actividad, Canal, Categoria, Conversacion, Etiqueta, Oportunidad
from .roles import (
    actividades_visibles,
    conversaciones_visibles,
    es_supervisor,
    oportunidades_visibles,
    puede_ver_oportunidad,
    seguimientos_visibles,
)

ETAPAS_TABLERO = ["nuevo", "contactado", "propuesta", "negociacion", "ganado", "perdido"]
NT = notif.Tipo


def _emp(op_o_contacto):
    c = getattr(op_o_contacto, "contacto", op_o_contacto)
    return c.empresa or c.nombre


# ------------------------------------------------------------------ Resultados
@crm_requerido
def dashboard(request):
    ops = oportunidades_visibles(request.user)
    m = services.metricas(ops)
    pendientes = seguimientos_visibles(request.user).filter(completado=False)
    ctx = {
        "m": m,
        "pendientes": pendientes.count(),
        "vencidos": pendientes.filter(fecha_hora__lt=timezone.now()).count(),
        "proximos": pendientes.select_related("oportunidad__contacto")[:5],
        "ultimas": actividades_visibles(request.user).select_related("contacto", "usuario")[:6],
        "equipo": services.desempeno_ejecutivos() if es_supervisor(request.user) else None,
        "graficos": {"serie": m["serie"], "embudo": m["embudo"], "canal": m["por_canal"]},
    }
    return render(request, "crm/dashboard.html", ctx)


# ------------------------------------------------------------------ Oportunidades
@crm_requerido
def oportunidades(request):
    base = oportunidades_visibles(request.user)
    ops = base.select_related("contacto", "responsable").prefetch_related("etiquetas")
    q = request.GET.get("q", "").strip()
    if q:
        ops = ops.filter(
            Q(contacto__nombre__icontains=q) | Q(contacto__empresa__icontains=q) | Q(servicio__icontains=q)
        )
    # Pipelines: uno por categoría (Ventas de laptops, Alquiler…) + «Todos»
    cats = list(Categoria.objects.filter(activa=True))
    abiertas = dict(
        base.filter(etapa__in=Oportunidad.ETAPAS_ABIERTAS).values_list("servicio").annotate(n=Count("id"))
    )
    pipelines = [{"clave": "", "nombre": "Todos", "n": sum(abiertas.values())}]
    pipelines += [{"clave": str(c.pk), "nombre": c.nombre, "n": abiertas.get(c.nombre, 0)} for c in cats]
    if abiertas.get("Por definir"):
        pipelines.append({"clave": "sin", "nombre": "Sin categoría", "n": abiertas["Por definir"]})
    pipeline = request.GET.get("pipeline", "")
    actual = next((p for p in pipelines if p["clave"] == pipeline), pipelines[0])
    if pipeline == "sin":
        ops = ops.filter(servicio="Por definir")
    elif pipeline.isdigit():
        cat = next((c for c in cats if str(c.pk) == pipeline), None)
        ops = ops.filter(servicio=cat.nombre) if cat else ops
    etiqueta = request.GET.get("etiqueta", "")
    if etiqueta.isdigit():
        ops = ops.filter(etiquetas=int(etiqueta))
    ops = list(ops)
    columnas = []
    for e in ETAPAS_TABLERO:
        items = [o for o in ops if o.etapa == e]
        columnas.append(
            {
                "clave": e,
                "nombre": Oportunidad.Etapa(e).label,
                "items": items,
                "total": sum(o.valor for o in items),
            }
        )
    return render(
        request,
        "crm/oportunidades.html",
        {
            "columnas": columnas, "q": q, "etapas": Oportunidad.Etapa.choices, "pipelines": pipelines,
            "pipeline": actual, "etiquetas": Etiqueta.objects.all(), "etiqueta": etiqueta,
        },
    )


@crm_requerido
def oportunidad_nueva(request):
    return redirect("crm:cliente_nuevo")


# ------------------------------------------------------------------ Clientes (registro)
@crm_requerido
def clientes(request):
    """Lista de clientes registrados: cada fila es una oportunidad con su etapa en el pipeline."""
    base = oportunidades_visibles(request.user)
    ops = base.select_related("contacto", "responsable").prefetch_related("etiquetas").order_by("-creado")
    f = {k: request.GET.get(k, "").strip() for k in ("q", "canal", "etapa", "categoria", "etiqueta", "sede")}
    if f["q"]:
        ops = ops.filter(
            Q(contacto__nombre__icontains=f["q"]) | Q(contacto__empresa__icontains=f["q"])
            | Q(contacto__telefono__icontains=f["q"]) | Q(contacto__email__icontains=f["q"])
            | Q(contacto__ruc__icontains=f["q"])
            | (Q(pk=int(f["q"].lstrip("#"))) if f["q"].lstrip("#").isdigit() else Q(pk__in=[]))
        )
    if f["canal"] in Canal.values:
        ops = ops.filter(canal=f["canal"])
    if f["categoria"]:
        ops = ops.filter(servicio=f["categoria"])
    if f["etiqueta"].isdigit():
        ops = ops.filter(etiquetas=int(f["etiqueta"]))
    if f["sede"] in dict(SEDES_CRM):
        ops = ops.filter(sede=f["sede"])
    por_etapa = dict(ops.order_by().values_list("etapa").annotate(n=Count("id")))
    if f["etapa"] in Oportunidad.Etapa.values:
        ops = ops.filter(etapa=f["etapa"])
    pagina = Paginator(ops, 25).get_page(request.GET.get("page"))
    for o in pagina:
        o.wa_id, o.wa_texto = services.mensaje_predeterminado(o.contacto, o, request.user)
    params = request.GET.copy()
    params.pop("page", None)
    sin_etapa = request.GET.copy()
    sin_etapa.pop("etapa", None)
    sin_etapa.pop("page", None)
    return render(request, "crm/clientes.html", {
        "pagina": pagina, "f": f, "params": params.urlencode(), "params_sin_etapa": sin_etapa.urlencode(),
        "etapas": [(v, n, por_etapa.get(v, 0)) for v, n in Oportunidad.Etapa.choices],
        "total": sum(por_etapa.values()),
        "canales": [c for c in Canal.choices if c[0] != Canal.CHAT],
        "categorias": Categoria.objects.filter(activa=True), "etiquetas": Etiqueta.objects.all(),
        "sedes": SEDES_CRM,
    })


@crm_requerido
def cliente_nuevo(request):
    sup = es_supervisor(request.user)
    sede_inicial = request.session.get("sede_actual") if request.session.get("sede_actual") in dict(SEDES_CRM) else "guayaquil"
    form = ClienteForm(request.POST or None, puede_asignar=sup, initial={"sede": sede_inicial})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        contacto = services.buscar_o_crear_contacto(d["nombre"], d["telefono"], d["email"], d["empresa"])
        previas = contacto.oportunidades.count()
        for campo in ("ruc", "cargo", "ciudad", "direccion"):
            if d.get(campo) and not getattr(contacto, campo):
                setattr(contacto, campo, d[campo])
        contacto.save()
        services.enlazar_cliente_econotec(contacto)
        responsable = d.get("responsable") if sup else request.user
        if sup and not responsable:
            responsable = services.asignar_responsable() or request.user
        op = Oportunidad.objects.create(
            contacto=contacto, servicio=d["servicio"], canal=d["canal"], valor=d["valor"] or 0,
            cantidad=d["cantidad"], equipo=d["equipo"], sede=d["sede"], responsable=responsable, notas=d["notas"],
        )
        op.etiquetas.set(d["etiquetas"])
        Actividad.objects.create(
            oportunidad=op, usuario=request.user, tipo=services.CANAL_A_TIPO.get(d["canal"], Actividad.Tipo.NOTA),
            resultado=Actividad.Resultado.NUEVO,
            detalle=f"Cliente registrado (llegó por {Canal(d['canal']).label})." + (f" Necesita: {d['notas'][:200]}" if d["notas"] else ""),
        )
        notif.notificar(
            request.user, NT.LEAD,
            f"{notif.nombre(request.user)} registró a {_emp(op)} ({op.servicio}) por {Canal(d['canal']).label}, "
            f"responsable {notif.nombre(op.responsable)}.",
            reverse("crm:oportunidad", args=[op.pk]), tambien=[op.responsable],
        )
        if d["etapa"] != Oportunidad.Etapa.NUEVO:
            services.cambiar_etapa(op, d["etapa"], request.user, d.get("motivo_perdida", ""))
        if d.get("seguimiento"):
            from .models import Seguimiento

            Seguimiento.objects.create(
                oportunidad=op, responsable=op.responsable or request.user, creado_por=request.user,
                titulo=f"{dict(Seguimiento.Tipo.choices).get(d['seguimiento_tipo'] or 'llamada')} con {contacto.nombre} ({_emp(op)})",
                tipo=d["seguimiento_tipo"] or "llamada", fecha_hora=d["seguimiento"],
            )
        if d.get("wa_texto") and contacto.telefono:
            conv, _ = Conversacion.objects.get_or_create(contacto=contacto, canal=Canal.WHATSAPP)
            services.responder_conversacion(conv, request.user, d["wa_texto"][:4000])
            messages.success(request, "Cliente registrado. Se abrió WhatsApp con el mensaje predeterminado: solo toca Enviar.")
        else:
            messages.success(request, "Cliente registrado.")
        if previas:
            messages.info(request, f"Este contacto ya tenía {previas} oportunidad(es) registrada(s); se creó una nueva.")
        return redirect("crm:oportunidad", pk=op.pk)
    pred = services.plantillas_activas().first()
    return render(request, "crm/cliente_form.html", {
        "form": form,
        "plantilla_raw": pred.texto if pred else "",
        "asesor": notif.nombre(request.user),
        "horario": services.Configuracion.actual().horario,
    })


@crm_requerido
def cliente_editar(request, pk):
    """Editar los datos del contacto desde la ficha de una oportunidad."""
    op = get_object_or_404(Oportunidad.objects.select_related("contacto"), pk=pk)
    if not puede_ver_oportunidad(request.user, op):
        raise PermissionDenied
    form = ContactoForm(request.POST or None, instance=op.contacto)
    if request.method == "POST" and form.is_valid():
        contacto = form.save()
        services.enlazar_cliente_econotec(contacto)
        if form.changed_data:
            nombres = ", ".join(str(form.fields[c].label).lower() for c in form.changed_data)
            Actividad.objects.create(oportunidad=op, usuario=request.user, tipo=Actividad.Tipo.SISTEMA,
                                     detalle=f"Datos del cliente actualizados: {nombres}.")
            notif.notificar(request.user, NT.OPORTUNIDAD, f"{notif.nombre(request.user)} editó los datos de {_emp(op)}: {nombres}.",
                            reverse("crm:oportunidad", args=[op.pk]), tambien=[op.responsable])
        messages.success(request, "Datos del cliente guardados.")
        return redirect("crm:oportunidad", pk=op.pk)
    return render(request, "crm/form.html", {"form": form, "titulo": f"Editar cliente · {_emp(op)}", "volver": "crm:clientes"})


CAMPOS = {"servicio": "categoría", "valor": "valor", "cantidad": "cantidad", "equipo": "equipo", "sede": "sede",
          "responsable": "responsable",
          "notas": "notas", "motivo_perdida": "motivo de pérdida"}


@crm_requerido
def oportunidad_detalle(request, pk):
    op = get_object_or_404(Oportunidad.objects.select_related("contacto", "responsable"), pk=pk)
    if not puede_ver_oportunidad(request.user, op):
        raise PermissionDenied
    sup = es_supervisor(request.user)
    url = reverse("crm:oportunidad", args=[op.pk])

    if request.method == "POST" and request.POST.get("accion") == "etiquetas":
        antes = set(op.etiquetas.values_list("nombre", flat=True))
        ids = [int(i) for i in request.POST.getlist("etiquetas") if i.isdigit()]
        nueva = request.POST.get("nueva", "").strip()[:40]
        if nueva:
            e = Etiqueta.objects.filter(nombre__iexact=nueva).first() or Etiqueta.objects.create(
                nombre=nueva, color=request.POST.get("color") or "azul", creado_por=request.user
            )
            ids.append(e.pk)
        op.etiquetas.set(Etiqueta.objects.filter(pk__in=ids))
        despues = set(op.etiquetas.values_list("nombre", flat=True))
        if antes != despues:
            cambio = ", ".join([f"+{n}" for n in sorted(despues - antes)] + [f"−{n}" for n in sorted(antes - despues)])
            Actividad.objects.create(oportunidad=op, usuario=request.user, tipo=Actividad.Tipo.SISTEMA,
                                     detalle=f"Etiquetas: {cambio}.")
            notif.notificar(request.user, NT.ETIQUETA, f"{notif.nombre(request.user)} cambió etiquetas de {_emp(op)}: {cambio}.",
                            url, tambien=[op.responsable])
            messages.success(request, "Etiquetas actualizadas.")
        return redirect(url)

    etapa_antes = op.etapa
    resp_antes = op.responsable
    form = OportunidadEditarForm(request.POST or None, instance=op, puede_asignar=sup)
    if request.method == "POST" and form.is_valid():
        nueva_etapa = form.cleaned_data["etapa"]
        obj = form.save(commit=False)
        obj.etapa = etapa_antes
        obj.save()
        if nueva_etapa != etapa_antes:
            services.cambiar_etapa(obj, nueva_etapa, request.user, form.cleaned_data.get("motivo_perdida", ""))
        cambiados = [CAMPOS[c] for c in form.changed_data if c in CAMPOS]
        if sup and "responsable" in form.changed_data:
            Actividad.objects.create(
                oportunidad=obj,
                usuario=request.user,
                tipo=Actividad.Tipo.SISTEMA,
                detalle=f"Reasignada a {notif.nombre(obj.responsable) if obj.responsable else 'nadie'}.",
            )
            notif.notificar(request.user, NT.ASIGNACION,
                            f"{notif.nombre(request.user)} reasignó {_emp(obj)} de {notif.nombre(resp_antes)} a {notif.nombre(obj.responsable)}.",
                            url, tambien=[obj.responsable, resp_antes])
            cambiados.remove("responsable")
        if cambiados:
            notif.notificar(request.user, NT.OPORTUNIDAD,
                            f"{notif.nombre(request.user)} editó {_emp(obj)}: {', '.join(cambiados)}.",
                            url, tambien=[obj.responsable])
        messages.success(request, "Oportunidad actualizada.")
        return redirect("crm:oportunidad", pk=op.pk)
    cliente_eco = services.enlazar_cliente_econotec(op.contacto)
    equipos_eco = (
        cliente_eco.ingresos.order_by("-fecha_ingreso", "-id")[:6] if cliente_eco else []
    )
    return render(
        request,
        "crm/oportunidad_detalle.html",
        {
            "op": op,
            "cliente_eco": cliente_eco,
            "equipos_eco": equipos_eco,
            "form": form,
            "actividades": op.actividades.select_related("usuario")[:50],
            "seguimientos": op.seguimientos.select_related("responsable"),
            "etapas_flujo": [(v, n) for v, n in Oportunidad.Etapa.choices if v not in ("ganado", "perdido")],
            "orden_etapa": ETAPAS_TABLERO.index(op.etapa),
            "etiquetas_todas": Etiqueta.objects.all(),
            "etiquetas_op": set(op.etiquetas.values_list("pk", flat=True)),
            "colores": Etiqueta.Color.choices,
            "plantillas": services.plantillas_para(op.contacto, op, request.user),
            "wa_numero": services.normalizar_telefono(op.contacto.telefono),
        },
    )


@crm_requerido
@require_POST
def oportunidad_whatsapp(request, pk):
    """El asesor tocó «Enviar por WhatsApp»: el navegador abre wa.me y aquí queda el registro."""
    op = get_object_or_404(Oportunidad.objects.select_related("contacto"), pk=pk)
    if not puede_ver_oportunidad(request.user, op):
        return JsonResponse({"ok": False, "error": "Sin permiso"}, status=403)
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        data = request.POST
    texto = (data.get("texto") or "").strip()[:4000]
    if not texto:
        return JsonResponse({"ok": False, "error": "Mensaje vacío"}, status=400)
    conv, _ = Conversacion.objects.get_or_create(contacto=op.contacto, canal=Canal.WHATSAPP)
    rid = str(data.get("respuesta") or "")
    ok, estado = services.responder_conversacion(
        conv, request.user, texto, int(rid) if rid.isdigit() else None, enviar_qr=data.get("via") == "qr"
    )
    return JsonResponse({"ok": ok, "estado": estado})


@crm_requerido
@require_POST
def oportunidad_mover(request, pk):
    op = get_object_or_404(Oportunidad, pk=pk)
    if not puede_ver_oportunidad(request.user, op):
        return JsonResponse({"ok": False, "error": "Sin permiso"}, status=403)
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        data = request.POST
    etapa = data.get("etapa")
    if etapa not in Oportunidad.Etapa.values:
        return JsonResponse({"ok": False, "error": "Etapa no válida"}, status=400)
    services.cambiar_etapa(op, etapa, request.user, data.get("motivo", ""))
    return JsonResponse({"ok": True, "etapa": op.get_etapa_display()})


# ------------------------------------------------------------------ Bitácora
@crm_requerido
def bitacora(request):
    qs = actividades_visibles(request.user).select_related("contacto", "usuario", "oportunidad")
    f = {k: request.GET.get(k, "").strip() for k in ("q", "tipo", "desde", "hasta")}
    if f["q"]:
        qs = qs.filter(
            Q(detalle__icontains=f["q"]) | Q(contacto__empresa__icontains=f["q"]) | Q(contacto__nombre__icontains=f["q"])
        )
    if f["tipo"]:
        qs = qs.filter(tipo=f["tipo"])
    if f["desde"]:
        qs = qs.filter(fecha__date__gte=f["desde"])
    if f["hasta"]:
        qs = qs.filter(fecha__date__lte=f["hasta"])

    if request.GET.get("exportar") == "csv":
        resp = HttpResponse(content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="bitacora_crm_econotec.csv"'
        resp.write("﻿")
        w = csv.writer(resp)
        w.writerow(["Fecha", "Tipo", "Empresa", "Contacto", "Detalle", "Responsable", "Resultado"])
        for a in qs[:5000]:
            w.writerow(
                [
                    timezone.localtime(a.fecha).strftime("%Y-%m-%d %H:%M"),
                    a.get_tipo_display(),
                    a.contacto.empresa if a.contacto else "",
                    a.contacto.nombre if a.contacto else "",
                    a.detalle,
                    notif.nombre(a.usuario) if a.usuario else "Sistema",
                    a.get_resultado_display(),
                ]
            )
        return resp

    pagina = Paginator(qs, 25).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return render(
        request,
        "crm/bitacora.html",
        {"pagina": pagina, "f": f, "tipos": Actividad.Tipo.choices, "params": params.urlencode()},
    )


@crm_requerido
def actividad_nueva(request):
    ops = oportunidades_visibles(request.user).select_related("contacto")
    inicial = {}
    if request.GET.get("op"):
        inicial["oportunidad"] = request.GET["op"]
    form = ActividadForm(request.POST or None, oportunidades=ops, initial=inicial)
    if request.method == "POST" and form.is_valid():
        a = form.save(commit=False)
        a.usuario = request.user
        a.save()
        notif.notificar(
            request.user, NT.ACTIVIDAD,
            f"{notif.nombre(request.user)} registró {a.get_tipo_display().lower()} con "
            f"{_emp(a.oportunidad) if a.oportunidad else 'un cliente'}: {a.detalle[:120]}",
            reverse("crm:oportunidad", args=[a.oportunidad_id]) if a.oportunidad_id else reverse("crm:bitacora"),
        )
        messages.success(request, "Actividad registrada.")
        if a.oportunidad_id and request.GET.get("op"):
            return redirect("crm:oportunidad", pk=a.oportunidad_id)
        return redirect("crm:bitacora")
    return render(request, "crm/form.html", {"form": form, "titulo": "Registrar actividad", "volver": "crm:bitacora"})


# ------------------------------------------------------------------ Seguimientos
@crm_requerido
def seguimientos(request):
    hoy = timezone.localdate()
    try:
        anio = int(request.GET.get("anio", hoy.year))
        mes = int(request.GET.get("mes", hoy.month))
        datetime(anio, mes, 1)
    except (ValueError, TypeError):
        anio, mes = hoy.year, hoy.month
    qs = seguimientos_visibles(request.user).select_related("responsable", "oportunidad__contacto")
    del_mes = qs.filter(fecha_hora__year=anio, fecha_hora__month=mes)
    por_dia = {}
    for s in del_mes:
        por_dia.setdefault(timezone.localtime(s.fecha_hora).day, []).append(s)
    cal = calendar.Calendar(firstweekday=0)
    semanas = [
        [{"dia": d, "items": por_dia.get(d, []), "hoy": (anio, mes, d) == (hoy.year, hoy.month, hoy.day)} for d in sem]
        for sem in cal.monthdayscalendar(anio, mes)
    ]
    prev = (datetime(anio, mes, 1) - timedelta(days=1))
    nxt = (datetime(anio, mes, 28) + timedelta(days=5))
    return render(
        request,
        "crm/seguimientos.html",
        {
            "semanas": semanas,
            "titulo_mes": f"{services.MESES[mes - 1]} {anio}",
            "prev": {"anio": prev.year, "mes": prev.month},
            "next": {"anio": nxt.year, "mes": nxt.month},
            "pendientes": qs.filter(completado=False)[:40],
            "hechos": qs.filter(completado=True).order_by("-fecha_hora")[:10],
            "ahora": timezone.now(),
        },
    )


@crm_requerido
def seguimiento_nuevo(request):
    sup = es_supervisor(request.user)
    ops = oportunidades_visibles(request.user).filter(etapa__in=Oportunidad.ETAPAS_ABIERTAS).select_related("contacto")
    inicial = {}
    if request.GET.get("op"):
        inicial["oportunidad"] = request.GET["op"]
        op = ops.filter(pk=request.GET["op"]).first()
        if op:
            inicial["titulo"] = f"Llamar a {op.contacto.nombre}"
    form = SeguimientoForm(request.POST or None, oportunidades=ops, puede_asignar=sup, initial=inicial)
    if request.method == "POST" and form.is_valid():
        s = form.save(commit=False)
        s.creado_por = request.user
        if not sup or not form.cleaned_data.get("responsable"):
            s.responsable = (s.oportunidad.responsable if s.oportunidad and s.oportunidad.responsable else request.user) if sup else request.user
        s.save()
        Actividad.objects.create(
            oportunidad=s.oportunidad,
            usuario=request.user,
            tipo=Actividad.Tipo.NOTA,
            detalle=f"Seguimiento agendado: {s.titulo} ({timezone.localtime(s.fecha_hora):%d/%m/%Y %H:%M}).",
        )
        notif.notificar(
            request.user, NT.SEGUIMIENTO,
            f"{notif.nombre(request.user)} agendó «{s.titulo}» para {timezone.localtime(s.fecha_hora):%d/%m %H:%M}"
            f" (responsable {notif.nombre(s.responsable)}).",
            reverse("crm:seguimientos"), tambien=[s.responsable],
        )
        messages.success(request, "Seguimiento agendado.")
        return redirect(request.GET.get("next") or "crm:seguimientos")
    return render(request, "crm/form.html", {"form": form, "titulo": "Agendar seguimiento", "volver": "crm:seguimientos"})


@crm_requerido
@require_POST
def seguimiento_completar(request, pk):
    s = get_object_or_404(seguimientos_visibles(request.user), pk=pk)
    s.completado = not s.completado
    s.save(update_fields=["completado"])
    if s.completado:
        Actividad.objects.create(
            oportunidad=s.oportunidad, usuario=request.user, tipo=Actividad.Tipo.NOTA,
            detalle=f"Seguimiento completado: {s.titulo}.",
        )
    notif.notificar(request.user, NT.SEGUIMIENTO,
                    f"{notif.nombre(request.user)} marcó «{s.titulo}» como {'hecho' if s.completado else 'pendiente'}.",
                    reverse("crm:seguimientos"))
    if request.headers.get("x-requested-with") == "fetch":
        return JsonResponse({"ok": True, "completado": s.completado})
    return redirect(request.POST.get("next") or "crm:seguimientos")


# ------------------------------------------------------------------ util
def pipeline_total(user):
    return oportunidades_visibles(user).filter(etapa__in=Oportunidad.ETAPAS_ABIERTAS).aggregate(s=Sum("valor"))["s"] or 0


# ------------------------------------------------------------------ Chats de WhatsApp (vinculado por QR)
def _ultimo_mensaje_id(user):
    from .models import Mensaje

    return (
        Mensaje.objects.filter(conversacion__in=conversaciones_visibles(user).filter(canal=Canal.WHATSAPP))
        .order_by("-id").values_list("id", flat=True).first()
    ) or 0


@crm_requerido
def bandeja(request, pk=None):
    """Conversaciones de WhatsApp: lo que escribe el cliente, lo que respondió el bot y la asesora."""
    from . import whatsapp_api, whatsapp_qr

    convs = conversaciones_visibles(request.user).filter(canal=Canal.WHATSAPP).select_related("contacto")
    activa = None
    if pk:
        activa = convs.filter(pk=pk).first()
        if activa is None:
            return redirect("crm:bandeja")
    else:
        activa = convs.first()
    if activa and activa.no_leidos:
        activa.no_leidos = 0
        activa.save(update_fields=["no_leidos"])

    if request.method == "POST" and activa:
        texto = request.POST.get("texto", "").strip()
        if texto:
            ok, estado = services.responder_conversacion(activa, request.user, texto)
            if ok:
                messages.success(request, "Mensaje enviado por WhatsApp. El bot quedó pausado en este chat.")
            else:
                messages.warning(request, f"Quedó en el historial, pero no se envió: {estado}.")
        return redirect("crm:bandeja_conv", pk=activa.pk)

    op = activa.contacto.oportunidades.filter(etapa__in=Oportunidad.ETAPAS_ABIERTAS).first() if activa else None
    return render(request, "crm/bandeja.html", {
        "convs": convs[:100],
        "activa": activa,
        "mensajes_conv": activa.mensajes.select_related("autor") if activa else [],
        "op": op,
        "ultimo_id": _ultimo_mensaje_id(request.user),
        "wa": ({"estado": "conectado", "numero": "API oficial"} if whatsapp_api.activo()
               else whatsapp_qr.estado() if whatsapp_qr.activo() else {"estado": "apagado"}),
        "plantillas": services.plantillas_para(activa.contacto, op, request.user) if activa else [],
    })


@crm_requerido
@require_POST
def bandeja_bot(request, pk):
    """Activa o pausa el bot en una conversación."""
    conv = get_object_or_404(conversaciones_visibles(request.user), pk=pk)
    conv.bot_activo = not conv.bot_activo
    conv.bot_estado = ""
    conv.save(update_fields=["bot_activo", "bot_estado"])
    messages.success(request, "Bot activado: responderá los próximos mensajes." if conv.bot_activo
                     else "Bot pausado: este chat lo atiende un asesor.")
    return redirect("crm:bandeja_conv", pk=conv.pk)


@crm_requerido
def bandeja_estado(request):
    """Último mensaje visible: la pantalla de chats se actualiza sola cuando cambia."""
    return JsonResponse({"ultimo": _ultimo_mensaje_id(request.user)})


@crm_requerido
def whatsapp_conexion(request):
    """Vincular el número escaneando el QR (como WhatsApp Web)."""
    from . import whatsapp_qr
    from .roles import es_supervisor as _sup

    if not _sup(request.user):
        raise PermissionDenied
    return render(request, "crm/whatsapp_conexion.html", {
        "activo": whatsapp_qr.activo(),
        "wa": whatsapp_qr.estado(),
    })


@crm_requerido
def whatsapp_conexion_estado(request):
    from . import whatsapp_qr
    from .roles import es_supervisor as _sup

    if not _sup(request.user):
        raise PermissionDenied
    return JsonResponse(whatsapp_qr.estado())
