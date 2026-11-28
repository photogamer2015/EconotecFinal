"""
EconoBot de WhatsApp: bot por palabras clave del CRM de Econotec.

Dónde actúa:
  • WhatsApp API oficial (cuando se conecte) o WhatsApp vinculado por código QR (carpeta whatsapp_qr/).
  • Chat web (botón de la página), si se vuelve a activar.

Todo se edita en el CRM → «WhatsApp y respuestas»: categorías (menú), respuestas por palabra clave,
bienvenida, mensaje de «no entendí» y de «pide asesor».

Cómo decide, en este orden:
  1. «asesor», «humano», «una persona»…      → pasa la conversación a un asesor y el bot se calla.
  2. Paso pendiente:
       - después de elegir categoría, lo que cuente del equipo («HP, no prende») → lo anota.
       - después de anotar, «sí» → agenda una llamada el siguiente día hábil a las 10:00.
  3. Número del menú (1, 2, 3…)              → categoría.
  4. Palabras clave: si coincide una categoría, gana la categoría porque registra el interés
     («hola, ¿cuánto cuesta arreglar mi impresora?» → Impresoras); entre categorías gana la palabra más larga. Una respuesta solo le gana si su palabra clave es más
     específica y contiene la de la categoría («garantía extendida» > «garantía»).
  5. Primer mensaje                          → bienvenida + menú.
  6. Nada de lo anterior                     → «no te entendí» + menú.
"""
import unicodedata
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from . import notificaciones as notif
from .models import Actividad, Categoria, Configuracion, Mensaje, Respuesta, Seguimiento, lista_palabras

PIDE_ASESOR = lista_palabras("asesor, humano, una persona, agente, vendedor, llamenme, llamame, hablar con alguien")
SI = {"si", "claro", "dale", "ok", "okay", "listo", "bueno", "por favor", "de acuerdo"}


def _norm(texto):
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    for ch in "¿?¡!,.;:()\"'*_":
        t = t.replace(ch, " ")
    return " ".join(t.split())


def _coincide(t, palabra):
    """Frases de varias palabras: dentro del texto. Palabras sueltas: alguna palabra empieza con ella
    (así «impresora» encuentra «impresoras» pero «pc» no encuentra «capacitación»)."""
    if " " in palabra:
        return f" {palabra}" in f" {t}"
    return any(w.startswith(palabra) for w in t.split())


def _clave(t, palabras):
    """La palabra clave más larga que aparece en el texto ("" si ninguna)."""
    return max((p for p in palabras if _coincide(t, p)), key=len, default="")


def _mejor(t, palabras):
    """Largo de la palabra clave más larga que aparece en el texto (0 si ninguna)."""
    return max((len(p) for p in palabras if _coincide(t, p)), default=0)


def _siguiente_dia_habil_10am():
    d = timezone.localtime() + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d.replace(hour=10, minute=0, second=0, microsecond=0)


def analizar(texto, estado="", primera_vez=False):
    """Decide qué hacer con un mensaje. No guarda nada: sirve para responder y para sugerir."""
    t = _norm(texto)
    pal = set(t.split())
    cats = list(Categoria.objects.filter(activa=True))

    if _mejor(t, PIDE_ASESOR):
        return {"accion": "asesor"}

    es_numero_menu = t.isdigit() and 1 <= int(t) <= len(cats)
    if estado in ("detalle", "llamada") and (t in SI or pal & {"si", "claro", "dale"}):
        return {"accion": "llamada"}

    if es_numero_menu:
        return {"accion": "categoria", "categoria": cats[int(t) - 1]}
    for c in cats:  # tocó el botón con el nombre de la categoría
        if t == _norm(c.nombre):
            return {"accion": "categoria", "categoria": c}

    # Categoría vs. respuesta: gana la categoría (registra el interés), salvo que la respuesta tenga una
    # palabra clave más específica que la contenga («garantia extendida» le gana a «garantia»).
    cat, kw_cat = None, ""
    for c in cats:
        k = _clave(t, c.palabras)
        if len(k) > len(kw_cat):
            cat, kw_cat = c, k
    resp, kw_resp = None, ""
    for r in Respuesta.objects.filter(activa=True).exclude(palabras_clave=""):
        k = _clave(t, r.palabras)
        if len(k) > len(kw_resp):
            resp, kw_resp = r, k
    # Después de elegir categoría, lo que el cliente cuente del equipo se anota (salvo que pregunte otra cosa).
    if estado == "detalle" and not resp and len(t) >= 3:
        return {"accion": "detalle"}
    if cat and not (resp and kw_cat in kw_resp and len(kw_resp) > len(kw_cat)):
        return {"accion": "categoria", "categoria": cat}
    if resp:
        return {"accion": "respuesta", "respuesta": resp}
    if primera_vez:
        return {"accion": "bienvenida"}
    return {"accion": "no_entendi"}


def _texto_categoria(cat):
    return (
        f"Te ayudamos con *{cat.nombre}*. {cat.descripcion}\n\n"
        "Cuéntanos *marca y modelo* del equipo y *qué le pasa*. O escribe *asesor* para hablar con una persona."
    ).replace(". .", ".").replace("  ", " ")


def _texto(decision, texto, vars_, cfg):
    from .services import render

    a = decision["accion"]
    if a == "asesor":
        return render(cfg.pide_asesor, vars_)
    if a == "llamada":
        cuando = _siguiente_dia_habil_10am()
        dia = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"][cuando.weekday()]
        return (f"Listo, agendamos una llamada para el *{dia} a las 10:00*. Te llamaremos al número que nos dejaste. "
                "¿Algo más? Escribe *asesor* si prefieres hablar ya con una persona.")
    if a == "detalle":
        return (f"Anotado: _{texto.strip()}_. Con eso el técnico prepara tu diagnóstico y cotización.\n\n"
                f"Puedes traer el equipo a nuestra oficina ({vars_.get('horario', '')}). ¿Deseas que te llamemos? "
                "Responde *SÍ* para agendar una llamada o *asesor* para hablar con una persona ahora.")
    if a == "categoria":
        return render(_texto_categoria(decision["categoria"]), vars_)
    if a == "respuesta":
        return render(decision["respuesta"].texto, vars_)
    if a == "bienvenida":
        return render(cfg.bienvenida, vars_)
    return render(cfg.no_entendi, vars_)


def sugerir(conv, texto, op=None):
    """Respuesta sugerida para un mensaje de WhatsApp registrado a mano (no cambia nada)."""
    from .services import variables

    cfg = Configuracion.actual()
    primera = not conv.mensajes.filter(entrante=False).exists()
    d = analizar(texto, conv.bot_estado, primera)
    titulo = {
        "asesor": "Pide un asesor", "llamada": "Confirma llamada", "detalle": "Detalle del equipo",
        "categoria": f"Categoría: {d['categoria'].nombre}" if d.get("categoria") else "",
        "respuesta": d["respuesta"].titulo if d.get("respuesta") else "",
        "bienvenida": "Bienvenida", "no_entendi": "Sin coincidencia",
    }[d["accion"]]
    return {"titulo": titulo, "texto": _texto(d, texto, variables(conv.contacto, op, cfg=cfg), cfg),
            "accion": d["accion"], "categoria": d.get("categoria")}


def _enviar(conv, texto, estado="bot"):
    Mensaje.objects.create(conversacion=conv, entrante=False, texto=texto, bot=True, estado_envio=estado)
    conv.ultimo_mensaje = timezone.now()
    conv.save(update_fields=["ultimo_mensaje", "bot_estado", "bot_activo"])
    return texto


def responder(conv, texto, op=None, decision=None, estado="bot"):
    """Genera, guarda y devuelve la respuesta del bot. None si el bot está apagado o pausado en ese chat.
    `decision` fuerza una acción (p. ej. la bienvenida al abrir el chat)."""
    from . import services
    from .models import Canal

    cfg = Configuracion.actual()
    if not cfg.bot_activo or not conv.bot_activo:
        return None
    es_wa = conv.canal == Canal.WHATSAPP
    tipo = Actividad.Tipo.WHATSAPP if es_wa else Actividad.Tipo.WEB
    donde = "WhatsApp" if es_wa else "el chat web"
    primera = not conv.mensajes.filter(entrante=False, bot=True).exists()
    d = decision or analizar(texto, conv.bot_estado, primera)
    a = d["accion"]
    contacto = conv.contacto
    url = reverse("crm:bandeja_conv", args=[conv.pk])

    if a == "asesor":
        conv.bot_activo = False
        conv.bot_estado = ""
        if op and op.responsable:
            Seguimiento.objects.create(
                oportunidad=op, responsable=op.responsable, tipo=Seguimiento.Tipo.LLAMADA,
                titulo=f"Atender a {contacto.nombre} en {donde} (pidió un asesor)",
                fecha_hora=timezone.now() + timedelta(minutes=15),
            )
        Actividad.objects.create(
            oportunidad=op, contacto=contacto, tipo=tipo, resultado=Actividad.Resultado.INTERESADO,
            detalle="El cliente pidió hablar con un asesor. El bot se detuvo y se creó un seguimiento.",
        )
        notif.notificar(None, notif.Tipo.MENSAJE, f"{contacto.nombre} pidió hablar con un asesor en {donde}.",
                        url, tambien=[op.responsable] if op else [])

    elif a == "llamada":
        conv.bot_estado = ""
        cuando = _siguiente_dia_habil_10am()
        if op and op.responsable:
            Seguimiento.objects.create(
                oportunidad=op, responsable=op.responsable, tipo=Seguimiento.Tipo.LLAMADA,
                titulo=f"Llamar a {contacto.nombre} ({op.servicio}) — agendado por el bot", fecha_hora=cuando,
            )
        if op and op.etapa == "nuevo":
            services.cambiar_etapa(op, "contactado", None)

    elif a == "detalle":
        conv.bot_estado = "llamada"
        if op:
            op.notas = (op.notas + "\n" if op.notas else "") + f"Contó por {donde}: {texto.strip()}"
            op.save(update_fields=["notas", "actualizado"])
            Actividad.objects.create(
                oportunidad=op, tipo=tipo, resultado=Actividad.Resultado.INTERESADO,
                detalle=f"El cliente contó qué le pasa al equipo: {texto.strip()[:200]}",
            )

    elif a == "categoria":
        cat = d["categoria"]
        conv.bot_estado = "detalle"
        if op and op.servicio != cat.nombre:
            op.servicio = cat.nombre
            op.save(update_fields=["servicio", "actualizado"])
            Actividad.objects.create(
                oportunidad=op, tipo=tipo, resultado=Actividad.Resultado.INTERESADO,
                detalle=f"El bot registró interés en: {cat.nombre}.",
            )

    elif a == "respuesta":
        Respuesta.objects.filter(pk=d["respuesta"].pk).update(usos=d["respuesta"].usos + 1)

    vars_ = services.variables(contacto, op, cfg=cfg)
    respuesta = _texto(d, texto, vars_, cfg)
    if es_wa and a == "asesor":  # en WhatsApp no hay «botón de WhatsApp»: el asesor sigue en este mismo chat
        respuesta = services.render("Perfecto {nombre}. *{asesor}* de Econotec te atenderá por aquí en breve.", vars_)
    if es_wa and a == "llamada":
        respuesta = respuesta.replace("al número que nos dejaste", "a este mismo número")
    return _enviar(conv, respuesta, estado)


def probar(texto):
    """Para la pantalla de configuración: qué respondería el bot a un mensaje de ejemplo."""
    from .services import variables

    cfg = Configuracion.actual()
    d = analizar(texto, "", False)
    v = variables(None, None, None, cfg)
    v.update({"nombre": "Ana", "empresa": "su empresa", "asesor": "Tu asesora"})
    motivo = {
        "asesor": "Pide un asesor: el bot se detiene y avisa al responsable.",
        "categoria": f"Categoría «{d['categoria'].nombre}»: se guarda el interés en la oportunidad." if d.get("categoria") else "",
        "respuesta": f"Respuesta automática «{d['respuesta'].titulo}»." if d.get("respuesta") else "",
        "no_entendi": "Ninguna palabra clave coincide: responde «no te entendí».",
    }.get(d["accion"], "")
    return {"motivo": motivo, "texto": _texto(d, texto, v, cfg)}
