"""Lógica de negocio: entrada de leads por canal, asignación, respuestas, WhatsApp sin API y métricas."""
import logging
import re
from datetime import timedelta
from decimal import Decimal
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Count, F, Q, Sum
from django.urls import reverse
from django.utils import timezone

from . import notificaciones as notif
from .models import Actividad, Canal, Categoria, Configuracion, Contacto, Conversacion, Mensaje, Oportunidad, Rol

log = logging.getLogger(__name__)
User = get_user_model()
NT = notif.Tipo

CANAL_A_TIPO = {
    Canal.WEB: Actividad.Tipo.WEB,
    Canal.CHAT: Actividad.Tipo.WEB,
    Canal.WHATSAPP: Actividad.Tipo.WHATSAPP,
    Canal.CORREO: Actividad.Tipo.CORREO,
    Canal.MANUAL: Actividad.Tipo.NOTA,
}


def normalizar_telefono(tel):
    digitos = "".join(c for c in (tel or "") if c.isdigit())
    if digitos.startswith("0") and len(digitos) == 10:  # 09XXXXXXXX -> 5939XXXXXXXX (Ecuador)
        digitos = "593" + digitos[1:]
    return digitos


def empresa_o_nombre(contacto):
    return contacto.empresa or contacto.nombre


# ---------------------------------------------------------------- WhatsApp sin API (enlaces wa.me)
def wa_link(numero, texto=""):
    """Enlace oficial «clic para chatear»: abre WhatsApp con el mensaje ya escrito. No necesita API."""
    numero = normalizar_telefono(numero)
    base = f"https://wa.me/{numero}" if numero else "https://wa.me/"
    return base + (f"?text={quote(texto)}" if texto else "")


def menu_texto():
    cats = list(Categoria.objects.filter(activa=True))
    if not cats:
        return "Escribe *asesor* para hablar con una persona."
    filas = "\n".join(f"*{i}.* {c.nombre}" for i, c in enumerate(cats, start=1))
    return f"Responde con el número de lo que necesitas:\n{filas}\nEscribe *asesor* para hablar con una persona."


def primer_nombre(contacto):
    n = (contacto.nombre or "").strip() if contacto else ""
    return "" if not n or n.replace("+", "").isdigit() else n.split()[0]


def variables(contacto=None, op=None, usuario=None, cfg=None):
    cfg = cfg or Configuracion.actual()
    asesor = usuario or (op.responsable if op else None)
    servicio = op.servicio if op and op.servicio and op.servicio != "Por definir" else "nuestros servicios"
    return {
        "nombre": primer_nombre(contacto),
        "empresa": (contacto.empresa if contacto and contacto.empresa else "su empresa"),
        "servicio": servicio,
        "equipo": (op.equipo if op and op.equipo else "su equipo"),
        "asesor": notif.nombre(asesor) if asesor else "Un asesor",
        "horario": cfg.horario,
        "menu": menu_texto(),
    }


def render(texto, vars_):
    """Reemplaza {variables}; las desconocidas se dejan tal cual. Limpia «Hola ,» cuando falta el nombre."""
    out = re.sub(r"\{(\w+)\}", lambda m: str(vars_.get(m.group(1), m.group(0))), texto or "")
    out = re.sub(r"[ \t]+([,!.?])", r"\1", out)
    return re.sub(r"[ \t]{2,}", " ", out).strip()


def plantillas_activas():
    """Mensajes predeterminados (sin palabras clave; las de palabras clave son del bot, hoy apagado)."""
    from .models import Respuesta

    return Respuesta.objects.filter(activa=True, palabras_clave="")


def plantillas_para(contacto, op=None, usuario=None):
    """Mensajes predeterminados ya armados para este cliente. El primero es el predeterminado."""
    cfg = Configuracion.actual()
    v = variables(contacto, op, usuario, cfg)
    return [{"id": r.pk, "titulo": r.titulo, "texto": render(r.texto, v), "predeterminada": r.predeterminada}
            for r in plantillas_activas()]


def mensaje_predeterminado(contacto, op=None, usuario=None):
    """Texto con el que se abre el chat de WhatsApp del cliente (o vacío si no hay plantilla)."""
    r = plantillas_activas().first()
    return (r.pk, render(r.texto, variables(contacto, op, usuario))) if r else (None, "")


# ---------------------------------------------------------------- asignación
def asignar_responsable():
    """Rotación por carga: la asesora activa con menos oportunidades abiertas
    (se puede excluir a alguien en CRM → Usuarios y roles → «Recibe clientes automáticos»)."""
    from .roles import asesoras_qs

    candidatos = (
        User.objects.filter(pk__in=asesoras_qs().values("pk"))
        .exclude(crm_perfil__recibe_leads=False)
        .annotate(
            abiertas=Count(
                "crm_oportunidades",
                filter=Q(crm_oportunidades__etapa__in=Oportunidad.ETAPAS_ABIERTAS),
            )
        )
        .order_by("abiertas", "id")
    )
    return candidatos.first()


def enlazar_cliente_econotec(contacto):
    """Busca al contacto entre los clientes de Econotec (por cédula o WhatsApp) y lo enlaza."""
    from econotec.models import Cliente

    if contacto.cliente_econotec_id:
        return contacto.cliente_econotec
    cliente = None
    if contacto.ruc:
        cliente = Cliente.objects.filter(cedula=contacto.ruc.strip()).first()
    if cliente is None and contacto.telefono:
        local = contacto.telefono[3:] if contacto.telefono.startswith("593") else contacto.telefono
        variantes = {contacto.telefono, "0" + local, local, "+" + contacto.telefono}
        cliente = Cliente.objects.filter(whatsapp__in=variantes).first()
    if cliente is not None:
        contacto.cliente_econotec = cliente
        contacto.save(update_fields=["cliente_econotec"])
    return cliente


def buscar_o_crear_contacto(nombre, telefono="", email="", empresa=""):
    telefono = normalizar_telefono(telefono)
    email = (email or "").strip().lower()
    contacto = None
    if telefono:
        contacto = Contacto.objects.filter(telefono=telefono).first()
    if contacto is None and email:
        contacto = Contacto.objects.filter(email=email).first()
    if contacto is None:
        return Contacto.objects.create(
            nombre=(nombre or telefono or email or "Sin nombre")[:150],
            empresa=(empresa or "")[:150],
            telefono=telefono,
            email=email,
        )
    cambios = False
    if empresa and not contacto.empresa:
        contacto.empresa, cambios = empresa[:150], True
    if email and not contacto.email:
        contacto.email, cambios = email, True
    if telefono and not contacto.telefono:
        contacto.telefono, cambios = telefono, True
    if nombre and contacto.nombre.replace("+", "").isdigit() and not nombre.isdigit():
        contacto.nombre, cambios = nombre[:150], True
    if cambios:
        contacto.save()
    return contacto


# ---------------------------------------------------------------- entrada
@transaction.atomic
def registrar_entrante(
    canal, nombre, texto, telefono="", email="", empresa="", servicio="", externo_id=None, usuario=None, avisar=True
):
    """
    Punto único de entrada: formulario web, chat web, WhatsApp registrado a mano y correo.
    Crea o reutiliza contacto y conversación, guarda el mensaje y, si el contacto
    no tiene una oportunidad abierta, crea una nueva y la asigna por rotación.
    `usuario`: quien registró el mensaje a mano (None si llegó solo).
    `avisar`: si es False no se avisa al responsable de cada mensaje (p. ej. mientras el bot atiende el chat).
    Devuelve (conversacion, oportunidad, creada).
    """
    if externo_id and Mensaje.objects.filter(externo_id=externo_id).exists():
        msg = Mensaje.objects.get(externo_id=externo_id)
        conv = msg.conversacion
        return conv, conv.contacto.oportunidades.first(), False

    contacto = buscar_o_crear_contacto(nombre, telefono, email, empresa)
    enlazar_cliente_econotec(contacto)
    ahora = timezone.now()
    conv, _ = Conversacion.objects.get_or_create(contacto=contacto, canal=canal)
    if usuario is None:
        conv.no_leidos += 1
    conv.ultimo_mensaje = ahora
    conv.save(update_fields=["no_leidos", "ultimo_mensaje"])
    Mensaje.objects.create(conversacion=conv, entrante=True, texto=texto, fecha=ahora, externo_id=externo_id)

    op = contacto.oportunidades.filter(etapa__in=Oportunidad.ETAPAS_ABIERTAS).first()
    creada = False
    if op is None:
        responsable = asignar_responsable()
        if usuario is not None and rol_de_usuario(usuario) == Rol.EJECUTIVO:
            responsable = usuario  # el ejecutivo que lo registró se queda con su cliente
        op = Oportunidad.objects.create(
            contacto=contacto,
            servicio=servicio or "Por definir",
            canal=canal,
            responsable=responsable,
        )
        url_conv = reverse("crm:oportunidad", args=[op.pk])
        creada = True
        quien = notif.nombre(responsable) if responsable else "nadie (sin ejecutivos activos)"
        Actividad.objects.create(
            oportunidad=op,
            usuario=usuario,
            tipo=CANAL_A_TIPO.get(canal, Actividad.Tipo.SISTEMA),
            resultado=Actividad.Resultado.NUEVO,
            detalle=f"Lead creado desde {Canal(canal).label}. Asignado a {quien}.",
        )
        notif.notificar(
            usuario, NT.LEAD,
            f"Nuevo lead por {Canal(canal).label}: {empresa_o_nombre(contacto)} ({op.servicio}). Asignado a {quien}.",
            url_conv, tambien=[responsable],
        )
    else:
        url_conv = reverse("crm:oportunidad", args=[op.pk])
        Actividad.objects.create(
            oportunidad=op,
            usuario=usuario,
            tipo=CANAL_A_TIPO.get(canal, Actividad.Tipo.SISTEMA),
            resultado=Actividad.Resultado.EN_CURSO,
            detalle=f"Mensaje {'registrado' if usuario else 'entrante'}: {texto[:300]}",
        )
        if usuario is None and avisar:
            notif.notificar_usuarios(
                [op.responsable], None, NT.MENSAJE,
                f"{empresa_o_nombre(contacto)} escribió por {Canal(canal).label}: {texto[:120]}", url_conv,
            )
    return conv, op, creada


def rol_de_usuario(u):
    from .roles import rol_de

    return rol_de(u)


# ---------------------------------------------------------------- salida
def enviar_correo(destino, asunto, texto):
    try:
        send_mail(asunto, texto, settings.DEFAULT_FROM_EMAIL, [destino], fail_silently=False)
        return True, "enviado"
    except Exception as e:
        log.warning("Correo error: %s", e)
        return False, "error al enviar"


def responder_conversacion(conv, usuario, texto, respuesta_id=None, enviar_qr=True):
    """
    Responde y lo registra en la bitácora.
    - WhatsApp API oficial (cuando se conecte): sale sola por la API de Meta.
    - WhatsApp vinculado por QR: sale solo por el puente (whatsapp_qr/).
    - WhatsApp sin QR: el navegador del asesor abre WhatsApp con el texto (wa.me) y aquí queda el registro.
    - Chat web: el mensaje aparece en el chat de la página del cliente.
    - Correo / formulario web: se envía por correo.
    """
    from . import whatsapp_api, whatsapp_qr

    contacto = conv.contacto
    if conv.canal == Canal.WHATSAPP and enviar_qr and whatsapp_api.activo():
        ok, estado = whatsapp_api.enviar(contacto.telefono, texto)  # API oficial de WhatsApp (Meta)
    elif conv.canal == Canal.WHATSAPP and enviar_qr and whatsapp_qr.activo():
        ok, estado = whatsapp_qr.enviar(contacto.telefono, texto)  # sale solo por el WhatsApp vinculado con QR
    elif conv.canal == Canal.WHATSAPP:
        ok, estado = True, "abierto en WhatsApp"
    elif conv.canal == Canal.CHAT:
        ok, estado = True, "entregado en el chat web"
    elif conv.canal in (Canal.CORREO, Canal.WEB) and contacto.email:
        ok, estado = enviar_correo(contacto.email, "Econotec — respuesta a su consulta", texto)
    elif conv.canal == Canal.WEB and contacto.telefono:
        ok, estado = True, "abierto en WhatsApp"
    else:
        ok, estado = False, "sin dato de contacto para este canal"
    Mensaje.objects.create(conversacion=conv, entrante=False, texto=texto, autor=usuario, estado_envio=estado)
    conv.ultimo_mensaje = timezone.now()
    conv.bot_activo = False  # un asesor tomó la conversación: el bot deja de responder
    conv.bot_estado = ""
    conv.save(update_fields=["ultimo_mensaje", "bot_activo", "bot_estado"])
    if respuesta_id:
        from .models import Respuesta

        Respuesta.objects.filter(pk=respuesta_id).update(usos=F("usos") + 1)
    op = contacto.oportunidades.filter(etapa__in=Oportunidad.ETAPAS_ABIERTAS).first()
    via = "WhatsApp" if estado in ("abierto en WhatsApp", "enviado por WhatsApp", "enviado por la API de WhatsApp") else Canal(conv.canal).label
    Actividad.objects.create(
        oportunidad=op,
        contacto=contacto,
        usuario=usuario,
        tipo=Actividad.Tipo.WHATSAPP if via == "WhatsApp" else CANAL_A_TIPO.get(conv.canal, Actividad.Tipo.NOTA),
        detalle=f"Respuesta enviada por {via}: {texto[:300]}",
    )
    notif.notificar(
        usuario, NT.MENSAJE, f"{notif.nombre(usuario)} respondió a {empresa_o_nombre(contacto)} por {via}.",
        reverse("crm:oportunidad", args=[op.pk]) if op else "",
    )
    return ok, estado


def cambiar_etapa(op, etapa, usuario, motivo=""):
    if op.etapa == etapa:
        return False
    anterior = op.get_etapa_display()
    op.etapa = etapa
    if etapa in (Oportunidad.Etapa.GANADO, Oportunidad.Etapa.PERDIDO):
        op.fecha_cierre = timezone.now()
        if motivo:
            op.motivo_perdida = motivo[:200]
    else:
        op.fecha_cierre = None
    op.save()
    resultado = {
        "ganado": Actividad.Resultado.GANADO,
        "perdido": Actividad.Resultado.PERDIDO,
    }.get(etapa, Actividad.Resultado.EN_CURSO)
    Actividad.objects.create(
        oportunidad=op,
        usuario=usuario,
        tipo=Actividad.Tipo.CAMBIO_ETAPA,
        resultado=resultado,
        detalle=f"De {anterior} a {op.get_etapa_display()}." + (f" Motivo: {motivo}" if motivo else ""),
    )
    quien = notif.nombre(usuario) if usuario else "El bot"
    notif.notificar(
        usuario, NT.ETAPA,
        f"{quien} movió {empresa_o_nombre(op.contacto)} de {anterior} a {op.get_etapa_display()}."
        + (f" Motivo: {motivo}" if motivo else ""),
        reverse("crm:oportunidad", args=[op.pk]),
        tambien=[op.responsable] if usuario and op.responsable_id != usuario.pk else [],
    )
    return True


# ---------------------------------------------------------------- métricas
MESES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


def _inicio_mes(dt, atras=0):
    y, m = dt.year, dt.month - atras
    while m <= 0:
        m += 12
        y -= 1
    return dt.replace(year=y, month=m, day=1, hour=0, minute=0, second=0, microsecond=0)


def metricas(ops_qs):
    ahora = timezone.localtime()
    mes = _inicio_mes(ahora)
    mes_ant = _inicio_mes(ahora, 1)

    abiertas = ops_qs.filter(etapa__in=Oportunidad.ETAPAS_ABIERTAS)
    del_mes = ops_qs.filter(creado__gte=mes)
    cerradas_mes = ops_qs.filter(fecha_cierre__gte=mes)
    ganadas_mes = cerradas_mes.filter(etapa=Oportunidad.Etapa.GANADO).count()
    perdidas_mes = cerradas_mes.filter(etapa=Oportunidad.Etapa.PERDIDO).count()
    total_cerradas = ganadas_mes + perdidas_mes
    efectividad = round(ganadas_mes / total_cerradas * 100) if total_cerradas else 0
    leads_mes = del_mes.count()
    leads_ant = ops_qs.filter(creado__gte=mes_ant, creado__lt=mes).count()
    variacion = round((leads_mes - leads_ant) / leads_ant * 100) if leads_ant else None

    serie = []
    for i in range(5, -1, -1):
        ini = _inicio_mes(ahora, i)
        fin = _inicio_mes(ahora, i - 1) if i else None
        rango = Q(creado__gte=ini) & (Q(creado__lt=fin) if fin else Q())
        rango_c = Q(fecha_cierre__gte=ini) & (Q(fecha_cierre__lt=fin) if fin else Q())
        serie.append(
            {
                "mes": MESES[ini.month - 1],
                "leads": ops_qs.filter(rango).count(),
                "ganados": ops_qs.filter(rango_c, etapa=Oportunidad.Etapa.GANADO).count(),
            }
        )

    orden = ["nuevo", "contactado", "propuesta", "negociacion", "ganado"]
    conteo = dict(ops_qs.exclude(etapa="perdido").values_list("etapa").annotate(n=Count("id")))
    embudo = []
    for i, e in enumerate(orden):
        embudo.append({"etapa": Oportunidad.Etapa(e).label, "n": sum(conteo.get(x, 0) for x in orden[i:])})

    por_canal = [
        {"canal": Canal(c).label, "clave": c, "n": n}
        for c, n in ops_qs.values_list("canal").annotate(n=Count("id")).order_by("-n")
    ]

    return {
        "leads_activos": abiertas.count(),
        "pipeline": abiertas.aggregate(s=Sum("valor"))["s"] or Decimal("0"),
        "efectividad": efectividad,
        "ganadas_mes": ganadas_mes,
        "cerradas_mes": total_cerradas,
        "leads_mes": leads_mes,
        "variacion": variacion,
        "serie": serie,
        "embudo": embudo,
        "por_canal": por_canal,
    }


def desempeno_ejecutivos():
    ahora = timezone.localtime()
    mes = _inicio_mes(ahora)
    filas = []
    from .roles import asesoras_qs

    for u in asesoras_qs():
        ops = u.crm_oportunidades.all()
        g = ops.filter(etapa="ganado", fecha_cierre__gte=mes)
        cerr = ops.filter(fecha_cierre__gte=mes).count()
        filas.append(
            {
                "usuario": u,
                "abiertas": ops.filter(etapa__in=Oportunidad.ETAPAS_ABIERTAS).count(),
                "ganadas": g.count(),
                "efectividad": round(g.count() / cerr * 100) if cerr else 0,
                "monto": g.aggregate(s=Sum("valor"))["s"] or Decimal("0"),
                "actividades": u.crm_actividades.filter(fecha__gte=mes).count(),
            }
        )
    return filas


def seguimientos_por_notificar(minutos=60):
    from .models import Seguimiento

    limite = timezone.now() + timedelta(minutes=minutos)
    return Seguimiento.objects.filter(
        completado=False, notificado=False, recordatorio_correo=True, fecha_hora__lte=limite
    ).select_related("responsable", "oportunidad__contacto")
