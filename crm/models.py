from django.conf import settings
from django.db import models
from django.utils import timezone

User = settings.AUTH_USER_MODEL


class Rol(models.TextChoices):
    ADMIN = "admin", "Administrador"
    GERENTE = "gerente", "Supervisora comercial"
    EJECUTIVO = "ejecutivo", "Asesora comercial"


class Canal(models.TextChoices):
    WHATSAPP = "whatsapp", "WhatsApp"
    LLAMADA = "llamada", "Llamada telefónica"
    CORREO = "correo", "Correo"
    WEB = "web", "Página web"
    REDES = "redes", "Redes sociales"
    REFERIDO = "referido", "Referido"
    VISITA = "visita", "Visita a la oficina"
    CHAT = "chat", "Chat web"
    MANUAL = "manual", "Otro"


SEDES_CRM = [("guayaquil", "Guayaquil"), ("quito", "Quito")]


class Perfil(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="crm_perfil")
    rol = models.CharField(max_length=12, choices=Rol.choices, default=Rol.EJECUTIVO)
    telefono = models.CharField(max_length=30, blank=True)
    recibe_leads = models.BooleanField(
        default=True, help_text="Si está activo entra en la rotación automática de leads."
    )

    class Meta:
        verbose_name = "perfil CRM"
        verbose_name_plural = "perfiles CRM"

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} ({self.get_rol_display()})"


class Contacto(models.Model):
    nombre = models.CharField(max_length=150)
    empresa = models.CharField(max_length=150, blank=True)
    ruc = models.CharField("cédula / RUC", max_length=20, blank=True)
    cargo = models.CharField(max_length=100, blank=True)
    telefono = models.CharField(max_length=30, blank=True, db_index=True)
    email = models.EmailField(blank=True, db_index=True)
    ciudad = models.CharField(max_length=80, blank=True)
    direccion = models.CharField("dirección", max_length=200, blank=True)
    cliente_econotec = models.ForeignKey(
        "econotec.Cliente", null=True, blank=True, on_delete=models.SET_NULL, related_name="crm_contactos",
        verbose_name="cliente en Econotec",
        help_text="Se enlaza solo cuando la cédula o el WhatsApp coinciden con un cliente del sistema.",
    )
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nombre"]

    def __str__(self):
        return f"{self.nombre} · {self.empresa}" if self.empresa else self.nombre

    @property
    def iniciales(self):
        partes = [p for p in self.nombre.split() if p]
        return "".join(p[0] for p in partes[:2]).upper() or "?"


def lista_palabras(texto):
    """'hola, buenas tardes ,info' -> ['hola', 'buenas tardes', 'info'] (sin tildes, en minúsculas)."""
    import unicodedata

    t = unicodedata.normalize("NFKD", (texto or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return [p.strip() for p in t.replace(";", ",").replace("\n", ",").split(",") if p.strip()]


class Categoria(models.Model):
    """Línea de negocio. Cada categoría es un pipeline y una opción del menú del bot."""

    nombre = models.CharField(max_length=120, unique=True)
    descripcion = models.TextField(
        "descripción", blank=True, help_text="Lo que responde el bot cuando el cliente elige esta categoría."
    )
    palabras_clave = models.CharField(
        max_length=400, blank=True, help_text="Separadas por coma. Ej.: laptop, portatil, no prende"
    )
    orden = models.PositiveSmallIntegerField(default=0)
    activa = models.BooleanField(default=True)

    class Meta:
        ordering = ["orden", "nombre"]
        verbose_name = "categoría"

    def __str__(self):
        return self.nombre

    @property
    def palabras(self):
        return lista_palabras(self.palabras_clave)


class Etiqueta(models.Model):
    class Color(models.TextChoices):
        AZUL = "azul", "Azul"
        VERDE = "verde", "Verde"
        AMBAR = "ambar", "Ámbar"
        ROJO = "rojo", "Rojo"
        MORADO = "morado", "Morado"
        ROSA = "rosa", "Rosa"
        TURQUESA = "turquesa", "Turquesa"
        GRIS = "gris", "Gris"

    nombre = models.CharField(max_length=40, unique=True)
    color = models.CharField(max_length=10, choices=Color.choices, default=Color.AZUL)
    creado_por = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Oportunidad(models.Model):
    class Etapa(models.TextChoices):
        NUEVO = "nuevo", "Nuevo"
        CONTACTADO = "contactado", "Contactado"
        PROPUESTA = "propuesta", "Cotizado"
        NEGOCIACION = "negociacion", "Por ingresar equipo"
        GANADO = "ganado", "Equipo ingresado"
        PERDIDO = "perdido", "Perdido"

    ETAPAS_ABIERTAS = ["nuevo", "contactado", "propuesta", "negociacion"]

    contacto = models.ForeignKey(Contacto, on_delete=models.CASCADE, related_name="oportunidades")
    servicio = models.CharField(max_length=120, default="Por definir")
    canal = models.CharField(max_length=10, choices=Canal.choices, default=Canal.MANUAL)
    valor = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cantidad = models.PositiveIntegerField("cantidad de equipos", null=True, blank=True)
    equipo = models.CharField("equipo (marca / modelo)", max_length=150, blank=True)
    sede = models.CharField(max_length=12, choices=SEDES_CRM, default="guayaquil", db_index=True)
    etapa = models.CharField(max_length=12, choices=Etapa.choices, default=Etapa.NUEVO, db_index=True)
    responsable = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="crm_oportunidades"
    )
    notas = models.TextField(blank=True)
    etiquetas = models.ManyToManyField(Etiqueta, blank=True, related_name="oportunidades")
    motivo_perdida = models.CharField(max_length=200, blank=True)
    creado = models.DateTimeField(default=timezone.now, db_index=True)
    actualizado = models.DateTimeField(auto_now=True)
    fecha_cierre = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-creado"]
        verbose_name_plural = "oportunidades"

    def __str__(self):
        return f"{self.contacto.empresa or self.contacto.nombre} — {self.servicio}"

    @property
    def abierta(self):
        return self.etapa in self.ETAPAS_ABIERTAS


class Conversacion(models.Model):
    contacto = models.ForeignKey(Contacto, on_delete=models.CASCADE, related_name="conversaciones")
    canal = models.CharField(max_length=10, choices=Canal.choices)
    no_leidos = models.PositiveIntegerField(default=0)
    bot_activo = models.BooleanField(
        default=True, help_text="El bot responde automáticamente hasta que un asesor toma la conversación."
    )
    bot_estado = models.CharField(max_length=12, blank=True, help_text="Paso pendiente del bot: detalle o llamada.")
    token = models.CharField(
        max_length=40, null=True, blank=True, unique=True, help_text="Identifica al visitante del chat web."
    )
    ultimo_mensaje = models.DateTimeField(default=timezone.now, db_index=True)
    asignado = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="crm_conversaciones",
        help_text="Asesora que atiende este chat (sin asignar si está vacío).",
    )
    seguimiento = models.BooleanField(default=False, help_text="Marcado con estrella para darle seguimiento.")

    class Meta:
        ordering = ["-ultimo_mensaje"]
        unique_together = [("contacto", "canal")]
        verbose_name_plural = "conversaciones"

    def __str__(self):
        return f"{self.contacto} vía {self.get_canal_display()}"


class Mensaje(models.Model):
    conversacion = models.ForeignKey(Conversacion, on_delete=models.CASCADE, related_name="mensajes")
    entrante = models.BooleanField(default=True)
    texto = models.TextField()
    fecha = models.DateTimeField(default=timezone.now)
    autor = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="crm_mensajes")
    externo_id = models.CharField(max_length=200, null=True, blank=True, unique=True)
    estado_envio = models.CharField(max_length=40, blank=True)
    bot = models.BooleanField(default=False, help_text="Mensaje enviado por el bot automático.")

    class Meta:
        ordering = ["fecha"]


class Actividad(models.Model):
    """Bitácora: todo lo que pasa con un cliente queda registrado aquí."""

    class Tipo(models.TextChoices):
        LLAMADA = "llamada", "Llamada"
        REUNION = "reunion", "Reunión"
        CORREO = "correo", "Correo"
        WHATSAPP = "whatsapp", "WhatsApp"
        WEB = "web", "Página web"
        VISITA = "visita", "Visita"
        NOTA = "nota", "Nota"
        CAMBIO_ETAPA = "cambio_etapa", "Cambio de etapa"
        SISTEMA = "sistema", "Sistema"

    class Resultado(models.TextChoices):
        NUEVO = "nuevo", "Nuevo"
        EN_CURSO = "en_curso", "En curso"
        INTERESADO = "interesado", "Interesado"
        GANADO = "ganado", "Ganado"
        PERDIDO = "perdido", "Perdido"

    oportunidad = models.ForeignKey(
        Oportunidad, null=True, blank=True, on_delete=models.CASCADE, related_name="actividades"
    )
    contacto = models.ForeignKey(
        Contacto, null=True, blank=True, on_delete=models.CASCADE, related_name="actividades"
    )
    usuario = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="crm_actividades")
    tipo = models.CharField(max_length=14, choices=Tipo.choices, default=Tipo.NOTA)
    detalle = models.TextField()
    resultado = models.CharField(max_length=12, choices=Resultado.choices, default=Resultado.EN_CURSO)
    fecha = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-fecha"]
        verbose_name_plural = "actividades"

    def save(self, *args, **kwargs):
        if self.oportunidad_id and not self.contacto_id:
            self.contacto_id = self.oportunidad.contacto_id
        super().save(*args, **kwargs)


class Seguimiento(models.Model):
    class Tipo(models.TextChoices):
        LLAMADA = "llamada", "Llamada"
        REUNION = "reunion", "Reunión"
        CORREO = "correo", "Correo"

    oportunidad = models.ForeignKey(
        Oportunidad, null=True, blank=True, on_delete=models.CASCADE, related_name="seguimientos"
    )
    responsable = models.ForeignKey(User, on_delete=models.CASCADE, related_name="crm_seguimientos")
    titulo = models.CharField(max_length=200)
    tipo = models.CharField(max_length=10, choices=Tipo.choices, default=Tipo.LLAMADA)
    fecha_hora = models.DateTimeField(db_index=True)
    completado = models.BooleanField(default=False)
    recordatorio_correo = models.BooleanField(default=True)
    notificado = models.BooleanField(default=False)
    creado_por = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="crm_seguimientos_creados"
    )
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["completado", "fecha_hora"]

    def __str__(self):
        return self.titulo

    @property
    def vencido(self):
        return not self.completado and self.fecha_hora < timezone.now()


class Respuesta(models.Model):
    """Respuesta automática por palabras clave y/o plantilla para enviar por WhatsApp con un clic."""

    titulo = models.CharField("título", max_length=80)
    palabras_clave = models.CharField(
        max_length=400, blank=True,
        help_text="Separadas por coma. Si el mensaje del cliente contiene alguna, el bot responde con este texto. "
        "Déjalo vacío para usarla solo como plantilla.",
    )
    texto = models.TextField(
        help_text="Variables: {nombre} {empresa} {servicio} {equipo} {asesor} {menu} {horario}. "
        "*negrita* y _cursiva_ como en WhatsApp."
    )
    orden = models.PositiveSmallIntegerField(default=0)
    activa = models.BooleanField(default=True)
    predeterminada = models.BooleanField(
        default=False, help_text="Es el mensaje que se carga al abrir el chat de WhatsApp de un cliente."
    )
    usos = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-predeterminada", "orden", "titulo"]
        verbose_name = "respuesta automática"
        verbose_name_plural = "respuestas automáticas"

    def __str__(self):
        return self.titulo

    @property
    def palabras(self):
        return lista_palabras(self.palabras_clave)


class Configuracion(models.Model):
    """Ajustes del botón de WhatsApp y del bot (una sola fila)."""

    numero_whatsapp = models.CharField(
        "número de WhatsApp de la empresa", max_length=20, blank=True,
        help_text="Con código de país, solo números. Ej.: 593987654321",
    )
    mensaje_boton = models.TextField(
        "mensaje predeterminado del botón",
        default="Hola Econotec, soy {nombre}. Necesito ayuda con: {servicio}. ¿Me pueden ayudar?",
        help_text="Lo que aparece escrito cuando el cliente toca el botón de WhatsApp de la página. "
        "Variables: {nombre} {servicio} {empresa}",
    )
    bot_activo = models.BooleanField("bot de WhatsApp activo", default=True)
    bienvenida = models.TextField(
        default="¡Hola {nombre}! 👋 Bienvenido a *Econotec*, reparación de tecnología: laptops, PC, impresoras, celulares, consolas y más.\n\n{menu}"
    )
    no_entendi = models.TextField(
        "cuando no entiende", default="Disculpa, no te entendí. {menu}"
    )
    pide_asesor = models.TextField(
        "cuando piden un asesor",
        default="Perfecto {nombre}. *{asesor}* de Econotec te atenderá en breve. "
        "Si prefieres, toca el botón *WhatsApp* para escribirnos directo.",
    )
    horario = models.CharField(max_length=120, default="lunes a sábado de 09:00 a 18:00")
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "configuración"
        verbose_name_plural = "configuración"

    def __str__(self):
        return "Configuración de WhatsApp y bot"

    @classmethod
    def actual(cls):
        from django.conf import settings

        obj, creado = cls.objects.get_or_create(pk=1)
        if creado or (not obj.numero_whatsapp and getattr(settings, "WHATSAPP_NUMERO", "")):
            numero = "".join(c for c in getattr(settings, "WHATSAPP_NUMERO", "") if c.isdigit())
            if numero.startswith("0") and len(numero) == 10:
                numero = "593" + numero[1:]
            if numero and not obj.numero_whatsapp:
                obj.numero_whatsapp = numero
                obj.save(update_fields=["numero_whatsapp"])
        return obj


class Notificacion(models.Model):
    class Tipo(models.TextChoices):
        LEAD = "lead", "Nuevo lead"
        OPORTUNIDAD = "oportunidad", "Oportunidad"
        ETAPA = "etapa", "Cambio de etapa"
        ASIGNACION = "asignacion", "Asignación"
        ETIQUETA = "etiqueta", "Etiquetas"
        ACTIVIDAD = "actividad", "Actividad"
        SEGUIMIENTO = "seguimiento", "Seguimiento"
        MENSAJE = "mensaje", "Mensaje"
        USUARIO = "usuario", "Usuarios"
        CONFIG = "config", "Configuración"
        AVISO = "aviso", "Aviso general"

    destinatario = models.ForeignKey(User, on_delete=models.CASCADE, related_name="crm_notificaciones")
    actor = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    tipo = models.CharField(max_length=12, choices=Tipo.choices, default=Tipo.OPORTUNIDAD, db_index=True)
    texto = models.CharField(max_length=400)
    url = models.CharField(max_length=300, blank=True)
    leida = models.BooleanField(default=False, db_index=True)
    fecha = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-fecha", "-id"]
        verbose_name = "notificación"
        verbose_name_plural = "notificaciones"

    def __str__(self):
        return self.texto
