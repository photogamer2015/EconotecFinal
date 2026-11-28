"""Administración: usuarios y roles, estado de integraciones."""
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import services, whatsapp_api, whatsapp_qr
from . import notificaciones as notif
from .forms import UsuarioEditarForm
from .models import Canal, Configuracion, Oportunidad, Perfil, Rol
from .roles import rol_de, rol_requerido, usuarios_crm

User = get_user_model()

PERMISOS = [
    ("Ver todas las oportunidades del equipo", True, True, False),
    ("Registrar clientes y gestionar sus oportunidades", True, True, True),
    ("Reasignar clientes", True, True, False),
    ("Registrar actividades y seguimientos", True, True, True),
    ("Ver métricas del equipo", True, True, False),
    ("Crear y asignar etiquetas", True, True, True),
    ("Editar y borrar etiquetas", True, True, False),
    ("Configurar WhatsApp, mensajes predeterminados y categorías", True, True, False),
    ("Enviar avisos generales al equipo", True, True, False),
    ("Recibir aviso de todos los cambios del equipo", True, False, False),
    ("Configurar integraciones", True, False, False),
    ("Asignar roles del CRM", True, False, False),
    ("Exportar bitácora", True, True, True),
]


@rol_requerido(Rol.ADMIN)
def usuarios(request):
    """Las cuentas se crean en Econotec (Admin → Usuarios); aquí se ve quién usa el CRM y con qué rol."""
    lista = list(usuarios_crm().select_related("crm_perfil"))
    for u in lista:
        u.rol_crm = rol_de(u)
        u.rol_crm_nombre = Rol(u.rol_crm).label if u.rol_crm else "Sin acceso"
        perfil = getattr(u, "crm_perfil", None)
        u.recibe = u.rol_crm == Rol.EJECUTIVO and (perfil is None or perfil.recibe_leads)
        u.abiertas = u.crm_oportunidades.filter(etapa__in=Oportunidad.ETAPAS_ABIERTAS).count()
    return render(request, "crm/usuarios.html", {"lista": lista, "permisos": PERMISOS})


@rol_requerido(Rol.ADMIN)
def usuario_editar(request, pk):
    u = get_object_or_404(usuarios_crm().exclude(is_superuser=True), pk=pk)
    perfil, _ = Perfil.objects.get_or_create(user=u)
    form = UsuarioEditarForm(
        request.POST or None,
        initial={"rol": perfil.rol if perfil.rol == Rol.GERENTE else Rol.EJECUTIVO, "recibe_leads": perfil.recibe_leads},
    )
    if request.method == "POST" and form.is_valid():
        cambios = []
        if perfil.rol != form.cleaned_data["rol"]:
            cambios.append(f"rol {perfil.get_rol_display()} → {Rol(form.cleaned_data['rol']).label}")
        if perfil.recibe_leads != form.cleaned_data["recibe_leads"]:
            cambios.append("recibe clientes automáticos: " + ("sí" if form.cleaned_data["recibe_leads"] else "no"))
        perfil.rol = form.cleaned_data["rol"]
        perfil.recibe_leads = form.cleaned_data["recibe_leads"]
        perfil.save()
        if cambios:
            notif.notificar(request.user, notif.Tipo.USUARIO,
                            f"{notif.nombre(request.user)} cambió a {notif.nombre(u)}: {', '.join(cambios)}.",
                            reverse("crm:usuarios"), tambien=[u])
        messages.success(request, "Usuario actualizado.")
        return redirect("crm:usuarios")
    return render(request, "crm/form.html", {
        "form": form, "titulo": f"Rol en el CRM · {u.get_full_name() or u.username}", "volver": "crm:usuarios",
        "intro": "La cuenta, la contraseña y la sede se manejan en Econotec. Aquí solo se define qué ve en el CRM.",
    })


@rol_requerido(Rol.ADMIN, Rol.GERENTE)
def integraciones(request):
    base = request.build_absolute_uri("/").rstrip("/")
    estado = [
        {
            "clave": "web", "nombre": "Página web",
            "ok": bool(settings.WEB_FORM_TOKEN),
            "detalle": "Formulario de contacto del sitio. Cada envío crea un lead con origen “Página web”.",
            "url": base + reverse("crm:api_web"),
            "falta": "Define WEB_FORM_TOKEN en .env",
        },
        {
            "clave": "correo", "nombre": "Correo oficial",
            "ok": bool(settings.EMAIL_HOST and settings.IMAP_HOST),
            "detalle": "SMTP para enviar respuestas y recordatorios; IMAP para leer la bandeja comercial (comando leer_correos).",
            "url": "",
            "falta": "Define EMAIL_HOST, IMAP_HOST y credenciales en .env",
        },
        {
            "clave": "whatsapp", "nombre": "WhatsApp (sin API)",
            "ok": bool(Configuracion.actual().numero_whatsapp),
            "detalle": "Funciona ya, sin API: las asesoras abren el chat de cada cliente con un clic y el mensaje listo. "
                       "Botón para la página web: el cliente deja nombre y número (queda registrado) y se abre WhatsApp.",
            "url": base + reverse("crm:widget_js"),
            "falta": "Escribe el número de WhatsApp de la empresa en «Ajustes de WhatsApp».",
            "config": reverse("crm:whatsapp"),
        },
        {
            "clave": "whatsapp", "nombre": "Bot de WhatsApp (código QR)",
            "ok": whatsapp_qr.estado().get("estado") == "conectado",
            "detalle": "El número se vincula escaneando un QR, como WhatsApp Web. Los mensajes llegan solos a «Chats de WhatsApp» "
                       "y el bot responde. No usa la API de Meta: pensado para pocos mensajes.",
            "url": "",
            "falta": "Pon WA_QR_ACTIVO=True y WA_QR_TOKEN en .env, arranca whatsapp_qr/ (npm start) y escanea el QR en «Conexión»."
                     if not whatsapp_qr.activo() else "Escanea el QR en «Conexión» (o abre Iniciar Demo si el programa no está corriendo).",
            "config": reverse("crm:whatsapp_conexion"),
        },
        {
            "clave": "whatsapp", "nombre": "WhatsApp Business API (oficial)",
            "ok": whatsapp_api.activo(),
            "pendiente": not whatsapp_api.activo(),
            "detalle": "API oficial de Meta: los mensajes llegan solos a «Chats de WhatsApp», el bot responde y las asesoras "
                       "contestan desde el CRM sin abrir WhatsApp. Ya está lista en el sistema: solo falta poner las claves.",
            "url": base + reverse("crm:api_whatsapp_webhook"),
            "falta": "Pendiente de conectar: define " + ", ".join(whatsapp_api.estado()["faltan"] or ["las claves"])
                     + " en .env y registra el webhook en Meta for Developers.",
        },
    ]
    from .models import Categoria

    return render(request, "crm/integraciones.html", {
        "estado": estado, "base": base,
        "categorias": Categoria.objects.filter(activa=True).values_list("nombre", flat=True),
    })


@rol_requerido(Rol.ADMIN, Rol.GERENTE)
@require_POST
def simular_entrante(request):
    """Crea un lead de prueba para verificar el flujo sin depender de los canales reales."""
    canal = request.POST.get("canal", Canal.WEB)
    if canal not in (Canal.WEB, Canal.WHATSAPP, Canal.CORREO):
        canal = Canal.WEB
    import random

    n = random.randint(100, 999)
    conv, op, creada = services.registrar_entrante(
        canal=canal,
        nombre=f"Cliente de prueba {n}",
        telefono=f"09{random.randint(10000000, 99999999)}",
        email=f"prueba{n}@ejemplo.com",
        servicio="Reparación de laptops",
        texto="Hola, mi laptop no prende. ¿Cuánto cuesta el diagnóstico?",
    )
    quien = notif.nombre(op.responsable) if op and op.responsable else "nadie (no hay asesoras activas)"
    messages.success(request, f"Cliente de prueba creado por {Canal(canal).label} y asignado a {quien}.")
    return redirect("crm:oportunidad", pk=op.pk)
