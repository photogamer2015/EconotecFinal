from datetime import timedelta

from django import forms
from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import SEDES_CRM, Actividad, Canal, Categoria, Configuracion, Contacto, Etiqueta, Oportunidad, Respuesta, Rol, Seguimiento

User = get_user_model()


def opciones_servicio(actual=None):
    """Las categorías activas (y la actual aunque esté desactivada) + «Por definir»."""
    nombres = list(Categoria.objects.filter(activa=True).values_list("nombre", flat=True))
    if actual and actual not in nombres and actual != "Por definir":
        nombres.append(actual)
    return [(n, n) for n in nombres + ["Por definir"]]


class EtiquetasField(forms.ModelMultipleChoiceField):
    widget = forms.CheckboxSelectMultiple

    def __init__(self, **kw):
        kw.setdefault("queryset", Etiqueta.objects.all())
        kw.setdefault("required", False)
        kw.setdefault("label", "Etiquetas")
        super().__init__(**kw)

    def label_from_instance(self, e):
        return e.nombre


def _ejecutivos():
    from .roles import usuarios_crm

    return usuarios_crm()


class UserChoice(forms.ModelChoiceField):
    def label_from_instance(self, u):
        return u.get_full_name() or u.username


class OportunidadForm(forms.Form):
    nombre = forms.CharField(label="Contacto", max_length=150)
    empresa = forms.CharField(label="Empresa", max_length=150, required=False)
    telefono = forms.CharField(label="Teléfono / WhatsApp", max_length=30, required=False)
    email = forms.EmailField(label="Correo", required=False)
    servicio = forms.ChoiceField(label="Categoría / pipeline")
    canal = forms.ChoiceField(label="Canal de origen", choices=Canal.choices, initial=Canal.MANUAL)
    valor = forms.DecimalField(label="Valor estimado (USD)", min_value=0, initial=0, decimal_places=2)
    responsable = UserChoice(label="Responsable", queryset=User.objects.none(), required=False)
    etiquetas = EtiquetasField()
    notas = forms.CharField(label="Notas", widget=forms.Textarea(attrs={"rows": 3}), required=False)

    def __init__(self, *args, puede_asignar=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["servicio"].choices = opciones_servicio()
        if puede_asignar:
            self.fields["responsable"].queryset = _ejecutivos()
        else:
            del self.fields["responsable"]

    def clean(self):
        d = super().clean()
        if not d.get("telefono") and not d.get("email"):
            raise forms.ValidationError("Ingresa al menos un teléfono o un correo.")
        return d


class OportunidadEditarForm(forms.ModelForm):
    responsable = UserChoice(queryset=User.objects.none(), required=False, label="Responsable")
    servicio = forms.ChoiceField(label="Categoría / pipeline")

    class Meta:
        model = Oportunidad
        fields = ["servicio", "equipo", "valor", "cantidad", "sede", "etapa", "responsable", "notas", "motivo_perdida"]
        widgets = {"notas": forms.Textarea(attrs={"rows": 3})}
        labels = {"valor": "Valor estimado (USD)", "motivo_perdida": "Motivo de pérdida",
                  "notas": "¿Qué le pasa al equipo? / notas", "equipo": "Equipo (marca / modelo)"}

    def __init__(self, *args, puede_asignar=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["servicio"].choices = opciones_servicio(self.instance.servicio if self.instance else None)
        if puede_asignar:
            self.fields["responsable"].queryset = _ejecutivos()
        else:
            del self.fields["responsable"]


class ActividadForm(forms.ModelForm):
    class Meta:
        model = Actividad
        fields = ["oportunidad", "tipo", "detalle", "resultado"]
        widgets = {"detalle": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, oportunidades=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["oportunidad"].queryset = oportunidades if oportunidades is not None else Oportunidad.objects.none()
        self.fields["oportunidad"].label = "Empresa / oportunidad"
        self.fields["tipo"].choices = [
            c for c in Actividad.Tipo.choices if c[0] not in ("cambio_etapa", "sistema")
        ]


class SeguimientoForm(forms.ModelForm):
    fecha_hora = forms.DateTimeField(
        label="Fecha y hora",
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        input_formats=["%Y-%m-%dT%H:%M"],
    )
    responsable = UserChoice(queryset=User.objects.none(), required=False, label="Responsable")

    class Meta:
        model = Seguimiento
        fields = ["oportunidad", "titulo", "tipo", "fecha_hora", "responsable", "recordatorio_correo"]
        labels = {"titulo": "Acción", "recordatorio_correo": "Enviar recordatorio por correo"}

    def __init__(self, *args, oportunidades=None, puede_asignar=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["oportunidad"].queryset = oportunidades if oportunidades is not None else Oportunidad.objects.none()
        self.fields["oportunidad"].required = False
        self.fields["oportunidad"].label = "Oportunidad"
        if puede_asignar:
            self.fields["responsable"].queryset = _ejecutivos()
        else:
            del self.fields["responsable"]
        if not self.initial.get("fecha_hora") and not self.is_bound:
            self.initial["fecha_hora"] = (timezone.localtime() + timedelta(days=1)).replace(
                hour=10, minute=0, second=0, microsecond=0
            ).strftime("%Y-%m-%dT%H:%M")


class UsuarioEditarForm(forms.Form):
    """Los usuarios se crean en Econotec; aquí solo se ajusta su papel dentro del CRM."""

    rol = forms.ChoiceField(
        label="Rol en el CRM",
        choices=[(Rol.EJECUTIVO, "Asesora comercial (solo sus clientes)"), (Rol.GERENTE, "Supervisora comercial (ve a todo el equipo)")],
    )
    recibe_leads = forms.BooleanField(label="Recibe clientes automáticos (WhatsApp, página web, correo)", required=False)


# ---------------------------------------------------------------- WhatsApp sin API, bot y etiquetas
CANALES_REGISTRO = [c for c in Canal.choices if c[0] != Canal.CHAT]
CANALES_CON_TELEFONO = (Canal.WHATSAPP, Canal.LLAMADA)


class ClienteForm(forms.Form):
    """Registro completo de un cliente y su oportunidad (con los mismos datos del ingreso de equipos de Econotec)."""

    canal = forms.ChoiceField(label="¿Por dónde llegó?", choices=CANALES_REGISTRO, initial=Canal.WHATSAPP,
                              widget=forms.RadioSelect)
    # Cliente
    nombre = forms.CharField(label="Nombres del cliente", max_length=150)
    ruc = forms.CharField(label="Cédula o RUC", max_length=20, required=False)
    empresa = forms.CharField(label="Empresa (si aplica)", max_length=150, required=False)
    cargo = forms.CharField(label="Cargo", max_length=100, required=False)
    telefono = forms.CharField(label="WhatsApp / teléfono", max_length=30, required=False,
                               widget=forms.TextInput(attrs={"inputmode": "tel", "placeholder": "09XXXXXXXX"}))
    email = forms.EmailField(label="Correo", required=False)
    ciudad = forms.CharField(label="Ciudad", max_length=80, required=False, initial="Guayaquil")
    direccion = forms.CharField(label="Dirección / sector", max_length=200, required=False)
    # Oportunidad
    sede = forms.ChoiceField(label="Sede", choices=SEDES_CRM, initial="guayaquil")
    servicio = forms.ChoiceField(label="Categoría / pipeline")
    equipo = forms.CharField(label="Equipo (marca / modelo)", max_length=150, required=False,
                             widget=forms.TextInput(attrs={"placeholder": "Ej.: HP Pavilion 15, Epson L3250"}))
    etapa = forms.ChoiceField(label="Etapa", choices=Oportunidad.Etapa.choices, initial=Oportunidad.Etapa.NUEVO)
    valor = forms.DecimalField(label="Valor estimado (USD)", min_value=0, initial=0, decimal_places=2, required=False)
    cantidad = forms.IntegerField(label="Cantidad de equipos", min_value=1, required=False, initial=1)
    responsable = UserChoice(label="Responsable", queryset=User.objects.none(), required=False,
                             empty_label="Asignar automáticamente")
    etiquetas = EtiquetasField()
    notas = forms.CharField(label="¿Qué le pasa al equipo? / ¿Qué necesita?", required=False,
                            widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Ej.: La laptop no prende y se calienta. Quiere saber el costo del diagnóstico."}))
    motivo_perdida = forms.CharField(label="Motivo de pérdida", max_length=200, required=False)
    # Seguimiento opcional
    seguimiento = forms.DateTimeField(
        label="Próximo seguimiento (opcional)", required=False, input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
    )
    seguimiento_tipo = forms.ChoiceField(label="Tipo", choices=Seguimiento.Tipo.choices, initial="llamada", required=False)
    # Lo llena el botón «Guardar y abrir WhatsApp» con el texto que se abrió
    wa_texto = forms.CharField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, puede_asignar=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["servicio"].choices = opciones_servicio()
        if puede_asignar:
            self.fields["responsable"].queryset = _ejecutivos()
        else:
            del self.fields["responsable"]

    def clean_telefono(self):
        from .services import normalizar_telefono

        t = normalizar_telefono(self.cleaned_data.get("telefono", ""))
        if t and len(t) < 7:
            raise forms.ValidationError("Número no válido.")
        return t

    def clean(self):
        d = super().clean()
        canal = d.get("canal")
        if canal in CANALES_CON_TELEFONO and not d.get("telefono"):
            self.add_error("telefono", f"Obligatorio cuando el cliente llega por {Canal(canal).label}: con este número se abre el chat.")
        elif not d.get("telefono") and not d.get("email"):
            raise forms.ValidationError("Ingresa al menos un teléfono o un correo.")
        if d.get("etapa") == Oportunidad.Etapa.PERDIDO and not d.get("motivo_perdida"):
            self.add_error("motivo_perdida", "Indica por qué se perdió.")
        return d


class ContactoForm(forms.ModelForm):
    class Meta:
        model = Contacto
        fields = ["nombre", "ruc", "empresa", "cargo", "telefono", "email", "ciudad", "direccion"]
        labels = {"nombre": "Nombres del cliente", "ruc": "Cédula o RUC", "telefono": "WhatsApp / teléfono",
                  "email": "Correo", "direccion": "Dirección / sector"}

    def clean_telefono(self):
        from .services import normalizar_telefono

        return normalizar_telefono(self.cleaned_data.get("telefono", ""))


class EtiquetaForm(forms.ModelForm):
    class Meta:
        model = Etiqueta
        fields = ["nombre", "color"]
        widgets = {"color": forms.RadioSelect}

    def clean_nombre(self):
        n = self.cleaned_data["nombre"].strip()
        if Etiqueta.objects.filter(nombre__iexact=n).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Ya existe una etiqueta con ese nombre.")
        return n


class RespuestaForm(forms.ModelForm):
    class Meta:
        model = Respuesta
        fields = ["titulo", "texto", "palabras_clave", "predeterminada", "orden", "activa"]
        widgets = {"texto": forms.Textarea(attrs={"rows": 5}), "palabras_clave": forms.TextInput()}
        labels = {"titulo": "Nombre del mensaje", "orden": "Orden (menor = primero)", "activa": "Activo",
                  "palabras_clave": "Palabras clave del bot (opcional)",
                  "predeterminada": "Mensaje predeterminado (se carga al abrir el chat de un cliente)"}
        help_texts = {"texto": "Variables: {nombre} {empresa} {servicio} {equipo} {asesor} {horario}. *negrita* y _cursiva_ como en WhatsApp."}


class CategoriaForm(forms.ModelForm):
    class Meta:
        model = Categoria
        fields = ["nombre", "descripcion", "palabras_clave", "orden", "activa"]
        widgets = {"descripcion": forms.Textarea(attrs={"rows": 3}), "palabras_clave": forms.TextInput()}
        labels = {"activa": "Activa (aparece como pipeline)", "descripcion": "Lo que responde el bot al elegir esta categoría"}


class ConfiguracionForm(forms.ModelForm):
    class Meta:
        model = Configuracion
        fields = ["numero_whatsapp", "mensaje_boton", "horario", "bot_activo", "bienvenida", "no_entendi"]
        widgets = {"mensaje_boton": forms.Textarea(attrs={"rows": 2}), "bienvenida": forms.Textarea(attrs={"rows": 3}),
                   "no_entendi": forms.Textarea(attrs={"rows": 2})}
        labels = {"horario": "Horario de atención", "mensaje_boton": "Mensaje del botón de la página web",
                  "bot_activo": "Bot de WhatsApp activo (responde solo en el WhatsApp vinculado por QR)",
                  "bienvenida": "Bot: mensaje de bienvenida", "no_entendi": "Bot: cuando no entiende"}
        help_texts = {"horario": "Se usa en los mensajes con la variable {horario}.",
                      "bienvenida": "Variables: {nombre} {menu} {horario}. {menu} muestra las categorías numeradas."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in ("bienvenida", "no_entendi"):  # vacío = se mantiene el texto actual
            self.fields[f].required = False

    def clean_bienvenida(self):
        return self.cleaned_data.get("bienvenida") or self.instance.bienvenida

    def clean_no_entendi(self):
        return self.cleaned_data.get("no_entendi") or self.instance.no_entendi

    def clean_numero_whatsapp(self):
        from .services import normalizar_telefono

        n = normalizar_telefono(self.cleaned_data["numero_whatsapp"])
        if n and len(n) < 10:
            raise forms.ValidationError("Escribe el número con código de país, p. ej. 593987654321.")
        return n


class AvisoForm(forms.Form):
    texto = forms.CharField(label="Aviso para todo el equipo", max_length=400, widget=forms.Textarea(attrs={"rows": 2}))
