"""
Formularios de Econotec.
"""
import base64
import binascii
import unicodedata

from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q
from decimal import Decimal, InvalidOperation
from .models import (
    Cliente, IngresoEquipo, Abono, SalidaEquipo,
    CategoriaEgreso, Egreso, AvisoPanel, NotificacionAsesora, InventarioItem,
)
from .permisos import GRUPOS_TECNICO, GRUPOS_ADMIN, GRUPOS_ASESOR_COMERCIAL


User = get_user_model()


def _queryset_tecnicos():
    """
    Usuarios que pueden aparecer como "Técnico encargado" en el menú:
    - Pertenecen al grupo "Tecnicos" o "Tecnico".
    Solo usuarios activos. Se ordenan por nombre.
    """
    nombres_grupos = GRUPOS_TECNICO
    return (
        User.objects.filter(is_active=True)
        .filter(groups__name__in=nombres_grupos)
        .distinct()
        .order_by('first_name', 'username')
    )


def _queryset_asesores():
    """
    Usuarios que pueden aparecer como "Asesor Comercial" en el menú:
    - Pertenecen a los nombres de grupo listados en GRUPOS_ASESOR_COMERCIAL, O
    - Pertenecen a los grupos de admin, O
    - Son superusuarios.
    Solo usuarios activos. Se ordenan por nombre.
    """
    # Sólo los usuarios que pertenecen a alguno de los nombres de grupo
    # listados en GRUPOS_ASESOR_COMERCIAL. NO incluimos admins ni superusuarios.
    nombres_grupos = GRUPOS_ASESOR_COMERCIAL
    return (
        User.objects.filter(is_active=True)
        .filter(groups__name__in=nombres_grupos)
        .distinct()
        .order_by('first_name', 'username')
    )


# ─────────────────────────────────────────────────────────
# Inventario
# ─────────────────────────────────────────────────────────

def _normalizar_identidad_inventario(valor):
    """Compara nombres/modelos sin depender de mayúsculas, acentos o espacios."""
    texto = ' '.join(str(valor or '').strip().casefold().split())
    texto = unicodedata.normalize('NFD', texto)
    return ''.join(
        caracter
        for caracter in texto
        if unicodedata.category(caracter) != 'Mn'
    )


class InventarioItemForm(forms.ModelForm):
    class Meta:
        model = InventarioItem
        fields = [
            'producto', 'marca', 'modelo', 'serie', 'estado',
            'causa_no_disponible', 'cantidad', 'costo', 'ubicacion',
            'observacion',
        ]
        widgets = {
            'producto': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Ej.: Tarjeta lógica, laptop, impresora completa',
                'autocomplete': 'off',
            }),
            'marca': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Ej.: HP, Epson, Lenovo',
                'autocomplete': 'off',
            }),
            'modelo': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Ej.: LaserJet Pro M404, ThinkPad T480',
                'autocomplete': 'off',
            }),
            'serie': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Serie si aplica',
                'autocomplete': 'off',
            }),
            'estado': forms.Select(attrs={'class': 'form-input'}),
            'causa_no_disponible': forms.Select(attrs={'class': 'form-input'}),
            'cantidad': forms.NumberInput(attrs={
                'class': 'form-input',
                'min': '0',
                'inputmode': 'numeric',
                'placeholder': '1',
            }),
            'costo': forms.NumberInput(attrs={
                'class': 'form-input',
                'min': '0',
                'step': '0.01',
                'inputmode': 'decimal',
                'placeholder': '0.00',
            }),
            'ubicacion': forms.Select(attrs={'class': 'form-input'}),
            'observacion': forms.Textarea(attrs={
                'class': 'form-input',
                'rows': 3,
                'placeholder': 'Observación opcional del inventario',
            }),
        }

    def __init__(
        self,
        *args,
        sede_slug='',
        categoria_slug='',
        tipo_slug='',
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.sede_slug = sede_slug or getattr(self.instance, 'sede', '')
        self.categoria_slug = categoria_slug or getattr(self.instance, 'categoria', '')
        self.tipo_slug = tipo_slug or getattr(self.instance, 'tipo', '')
        self.fields['serie'].required = False
        self.fields['observacion'].required = False
        for field_name, field in self.fields.items():
            if field_name not in {'serie', 'causa_no_disponible', 'observacion'}:
                field.required = True
        self.fields['causa_no_disponible'].required = False
        if sede_slug == 'guayaquil':
            self.fields['ubicacion'].choices = [
                ('guayaquil_norte', 'Guayaquil Norte'),
                ('guayaquil_centro', 'Guayaquil Centro'),
            ]
        elif sede_slug == 'quito':
            self.fields['ubicacion'].choices = [
                ('quito', 'Quito'),
            ]
            self.fields['ubicacion'].initial = 'quito'

    def clean_cantidad(self):
        cantidad = self.cleaned_data.get('cantidad') or 0
        if cantidad < 0:
            raise forms.ValidationError('La cantidad no puede ser negativa.')
        return cantidad

    def clean_costo(self):
        costo = self.cleaned_data.get('costo') or 0
        if costo < 0:
            raise forms.ValidationError('El costo no puede ser negativo.')
        return costo

    def clean(self):
        cleaned_data = super().clean()
        estado = cleaned_data.get('estado')
        causa = cleaned_data.get('causa_no_disponible')
        if estado == 'no_disponible':
            if not causa:
                self.add_error(
                    'causa_no_disponible',
                    'Indica la causa por la que este producto no está disponible.',
                )
        else:
            cleaned_data['causa_no_disponible'] = ''

        producto = cleaned_data.get('producto')
        modelo = cleaned_data.get('modelo')
        producto_normalizado = _normalizar_identidad_inventario(producto)
        modelo_normalizado = _normalizar_identidad_inventario(modelo)
        if (
            producto_normalizado
            and modelo_normalizado
            and self.sede_slug
            and self.categoria_slug
            and self.tipo_slug
        ):
            candidatos = InventarioItem.objects.filter(
                sede=self.sede_slug,
                categoria=self.categoria_slug,
                tipo=self.tipo_slug,
            ).only('pk', 'codigo', 'producto', 'modelo', 'ubicacion')
            if self.instance and self.instance.pk:
                candidatos = candidatos.exclude(pk=self.instance.pk)

            duplicado = next((
                item
                for item in candidatos
                if (
                    _normalizar_identidad_inventario(item.producto) == producto_normalizado
                    and _normalizar_identidad_inventario(item.modelo) == modelo_normalizado
                )
            ), None)
            if duplicado:
                self.add_error(
                    'modelo',
                    (
                        'Este producto ya está registrado con el mismo modelo '
                        f'como {duplicado.codigo} en {duplicado.get_ubicacion_display()}. '
                        'Edita ese registro o actualiza su cantidad.'
                    ),
                )
        return cleaned_data


# ─────────────────────────────────────────────────────────
# Cliente
# ─────────────────────────────────────────────────────────

class ClienteForm(forms.ModelForm):
    class Meta:
        model = Cliente
        fields = ['cedula', 'nombres', 'whatsapp', 'correo', 'sector', 'sector_otro']
        widgets = {
            'cedula': forms.TextInput(attrs={
                'class': 'form-input', 'placeholder': 'Ej.:0919254458',
                'pattern': '[0-9]+',
                'inputmode': 'numeric',
                'autocomplete': 'off',
                'autocapitalize': 'off',
                'spellcheck': 'false',
                'title': 'Por favor ingrese solo números.',
                'oninvalid': 'this.setCustomValidity("Por favor ingrese solo valores numéricos para Cédula o RUC.")',
                'oninput': 'this.setCustomValidity("")',
            }),
            'nombres': forms.TextInput(attrs={
                'class': 'form-input', 'placeholder': 'Ej.: David Guevara',
                'autocomplete': 'name',
                'autocapitalize': 'words',
            }),
            'whatsapp': forms.TextInput(attrs={
                'class': 'form-input', 'placeholder': 'Ej.:0996345364',
                'pattern': '[0-9]+',
                'inputmode': 'tel',
                'autocomplete': 'tel',
                'autocapitalize': 'off',
                'spellcheck': 'false',
                'title': 'Por favor ingrese solo números.',
                'oninvalid': 'this.setCustomValidity("Por favor ingrese solo números para el WhatsApp.")',
                'oninput': 'this.setCustomValidity("")',
            }),
            'correo': forms.EmailInput(attrs={
                'class': 'form-input', 'placeholder': 'Ej.: cliente@correo.com',
                'inputmode': 'email',
                'autocomplete': 'email',
                'autocapitalize': 'off',
                'spellcheck': 'false',
                'title': 'Por favor ingrese un correo válido.',
                'oninvalid': 'this.setCustomValidity("Por favor incluya un signo @ y el dominio en la dirección de correo.")',
                'oninput': 'this.setCustomValidity("")',
            }),
            'sector': forms.Select(attrs={'class': 'form-input'}),
            'sector_otro': forms.TextInput(attrs={
                'class': 'form-input', 'placeholder': 'Especificar sector si elegiste "Otro"',
                'autocomplete': 'off',
            }),
        }


# ─────────────────────────────────────────────────────────
# Ingreso de equipo
# ─────────────────────────────────────────────────────────

class IngresoEquipoForm(forms.ModelForm):
    """
    Formulario que replica fielmente la hoja "Solicitud de Ingreso" de Econotec.
    El cliente NO se incluye aquí; se maneja aparte (ClienteForm) en la vista.
    """
    CAMPOS_DIAGNOSTICO = [
        'diagnostico_inmediato',
        'valor_diagnostico',
        'diagnostico_metodo',
        'diagnostico_banco',
        'diagnostico_banco_otro',
        'diagnostico_tarjeta_app',
        'diagnostico_comprobante_url',
        'diagnostico_monto_1',
        'diagnostico_metodo_1',
        'diagnostico_banco_1',
        'diagnostico_monto_2',
        'diagnostico_metodo_2',
        'diagnostico_banco_2',
    ]

    VALOR_ACORDADO_ESTADOS = [
        ('si', 'Sí'),
        ('no', 'No / pendiente de valor'),
    ]
    VALOR_ACORDADO_MINIMO = Decimal('1.00')
    VALOR_ACORDADO_ERROR_MINIMO = 'El valor debe ser igual o mayor a $1.00.'

    FIRMA_CLIENTE_OPCIONES = [
        ('si', 'Sí'),
        ('no', 'No firma'),
    ]

    firma_cliente_opcion = forms.ChoiceField(
        choices=FIRMA_CLIENTE_OPCIONES,
        required=False,
        widget=forms.RadioSelect(attrs={'class': 'firma-cliente-radio'}),
        label='Firma del cliente'
    )

    valor_acordado = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-input', 
            'placeholder': 'Ej.: 25.00',
            'inputmode': 'decimal',
            'autocomplete': 'off',
        }),
        label='Valor acordado (USD)'
    )


    class Meta:
        model = IngresoEquipo
        fields = [
            'numero_factura',
            'asesor_comercial', 'tecnico_encargado', 'fecha_ingreso',
            'tipo_equipo', 'tipo_equipo_otro',
            'marca', 'modelo_serie', 'serie', 'accesorios_entregados',
            'problema_reportado', 'firma_cliente', 'firma_cliente_imagen',
            'diagnostico_inmediato', 'valor_diagnostico',
            'valor_acordado', 'abono_anticipo',
            'compra_metodo_pago', 'compra_banco', 'compra_banco_otro',
            'compra_tarjeta_app', 'compra_comprobante_url',
            'compra_monto_1', 'compra_metodo_1', 'compra_banco_1', 'compra_banco_otro_1', 'compra_tarjeta_app_1',
            'compra_monto_2', 'compra_metodo_2', 'compra_banco_2', 'compra_banco_otro_2', 'compra_tarjeta_app_2',
            'diagnostico_metodo', 'diagnostico_banco', 'diagnostico_banco_otro',
            'diagnostico_tarjeta_app', 'diagnostico_comprobante_url',
            'diagnostico_monto_1', 'diagnostico_metodo_1', 'diagnostico_banco_1',
            'diagnostico_monto_2', 'diagnostico_metodo_2', 'diagnostico_banco_2',
            'anticipo_metodo', 'anticipo_banco', 'anticipo_banco_otro',
            'anticipo_tarjeta_app', 'anticipo_comprobante_url',
            'anticipo_monto_1', 'anticipo_metodo_1', 'anticipo_banco_1',
            'anticipo_monto_2', 'anticipo_metodo_2', 'anticipo_banco_2',
            'estado', 'subestado_reparacion', 'subestado_entregado',
            'equipo_garantia', 'equipo_garantia_manual', 'motivo_garantia',
        ]
        widgets = {
            'numero_factura': forms.TextInput(attrs={
                'class': 'form-input', 'placeholder': '(opcional)',
                'autocomplete': 'off', 'autocapitalize': 'characters',
            }),
            'asesor_comercial': forms.TextInput(attrs={
                'class': 'form-input', 'placeholder': 'Ej.: Kimberly',
                'autocomplete': 'off', 'autocapitalize': 'words',
            }),
            'tecnico_encargado': forms.Select(attrs={'class': 'form-input'}),
            'fecha_ingreso': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}, format='%Y-%m-%d'),
            'tipo_equipo': forms.Select(attrs={'class': 'form-input', 'id': 'id_tipo_equipo'}),
            'tipo_equipo_otro': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Solo si elegiste "Otros equipos"',
                'autocomplete': 'off',
                'autocapitalize': 'words',
            }),
            'marca': forms.TextInput(attrs={
                'class': 'form-input', 'placeholder': 'Ej.: BlackBerry',
                'autocomplete': 'off',
                'autocapitalize': 'words',
                'spellcheck': 'false',
            }),
            'modelo_serie': forms.TextInput(attrs={
                'class': 'form-input', 'placeholder': 'Ej.: Curve 9320',
                'autocomplete': 'off',
                'autocapitalize': 'characters',
                'spellcheck': 'false',
            }),
            'serie': forms.TextInput(attrs={
                'class': 'form-input', 'placeholder': 'Ej.: SN123456 (opcional)',
                'autocomplete': 'off',
                'autocapitalize': 'characters',
                'spellcheck': 'false',
            }),
            'accesorios_entregados': forms.Textarea(attrs={
                'class': 'form-input', 'rows': 2,
                'placeholder': 'Cargador, cable HDMI, control, etc.',
            }),
            'problema_reportado': forms.Textarea(attrs={
                'class': 'form-input', 'rows': 3,
                'placeholder': 'Describa el problema reportado por el cliente...',
            }),
            'firma_cliente': forms.HiddenInput(attrs={
                'id': 'id_firma_cliente_check',
            }),
            'firma_cliente_imagen': forms.HiddenInput(attrs={
                'id': 'id_firma_cliente_imagen',
            }),
            'diagnostico_inmediato': forms.Select(attrs={'class': 'form-input'}),
            'valor_diagnostico': forms.NumberInput(attrs={
                'class': 'form-input', 'step': '0.01', 'min': '0',
            }),
            'abono_anticipo': forms.NumberInput(attrs={
                'class': 'form-input', 'step': '0.01', 'min': '0',
            }),
            'compra_metodo_pago': forms.Select(attrs={'class': 'form-input', 'id': 'id_compra_metodo_pago'}),
            'compra_banco': forms.Select(attrs={'class': 'form-input', 'id': 'id_compra_banco'}),
            'compra_banco_otro': forms.TextInput(attrs={'class': 'form-input', 'id': 'id_compra_banco_otro', 'placeholder': 'Especificar banco'}),
            'compra_tarjeta_app': forms.Select(attrs={'class': 'form-input', 'id': 'id_compra_tarjeta_app'}),
            'compra_comprobante_url': forms.URLInput(attrs={'class': 'form-input', 'id': 'id_compra_comprobante_url', 'placeholder': 'Link del comprobante'}),
            'compra_monto_1': forms.NumberInput(attrs={'class': 'form-input', 'step': '0.01', 'min': '0', 'id': 'id_compra_monto_1'}),
            'compra_metodo_1': forms.Select(attrs={'class': 'form-input', 'id': 'id_compra_metodo_1'}),
            'compra_banco_1': forms.Select(attrs={'class': 'form-input', 'id': 'id_compra_banco_1'}),
            'compra_banco_otro_1': forms.TextInput(attrs={'class': 'form-input', 'id': 'id_compra_banco_otro_1', 'placeholder': 'Otro banco'}),
            'compra_tarjeta_app_1': forms.Select(attrs={'class': 'form-input', 'id': 'id_compra_tarjeta_app_1'}),
            'compra_monto_2': forms.NumberInput(attrs={'class': 'form-input', 'step': '0.01', 'min': '0', 'id': 'id_compra_monto_2'}),
            'compra_metodo_2': forms.Select(attrs={'class': 'form-input', 'id': 'id_compra_metodo_2'}),
            'compra_banco_2': forms.Select(attrs={'class': 'form-input', 'id': 'id_compra_banco_2'}),
            'compra_banco_otro_2': forms.TextInput(attrs={'class': 'form-input', 'id': 'id_compra_banco_otro_2', 'placeholder': 'Otro banco'}),
            'compra_tarjeta_app_2': forms.Select(attrs={'class': 'form-input', 'id': 'id_compra_tarjeta_app_2'}),
            'diagnostico_metodo': forms.Select(attrs={'class': 'form-input', 'id': 'id_diagnostico_metodo'}),
            'diagnostico_banco': forms.Select(attrs={'class': 'form-input', 'id': 'id_diagnostico_banco'}),
            'diagnostico_banco_otro': forms.TextInput(attrs={'class': 'form-input', 'id': 'id_diagnostico_banco_otro', 'placeholder': 'Especificar banco'}),
            'diagnostico_tarjeta_app': forms.Select(attrs={'class': 'form-input', 'id': 'id_diagnostico_tarjeta_app'}),
            'diagnostico_comprobante_url': forms.URLInput(attrs={'class': 'form-input', 'id': 'id_diagnostico_comprobante_url', 'placeholder': 'Link a la imagen'}),
            'diagnostico_monto_1': forms.NumberInput(attrs={'class': 'form-input', 'step': '0.01', 'min': '0', 'id': 'id_diagnostico_monto_1'}),
            'diagnostico_metodo_1': forms.Select(attrs={'class': 'form-input', 'id': 'id_diagnostico_metodo_1'}),
            'diagnostico_banco_1': forms.Select(attrs={'class': 'form-input', 'id': 'id_diagnostico_banco_1'}),
            'diagnostico_monto_2': forms.NumberInput(attrs={'class': 'form-input', 'step': '0.01', 'min': '0', 'id': 'id_diagnostico_monto_2'}),
            'diagnostico_metodo_2': forms.Select(attrs={'class': 'form-input', 'id': 'id_diagnostico_metodo_2'}),
            'diagnostico_banco_2': forms.Select(attrs={'class': 'form-input', 'id': 'id_diagnostico_banco_2'}),
            'anticipo_metodo': forms.Select(attrs={'class': 'form-input', 'id': 'id_anticipo_metodo'}),
            'anticipo_banco': forms.Select(attrs={'class': 'form-input', 'id': 'id_anticipo_banco'}),
            'anticipo_banco_otro': forms.TextInput(attrs={'class': 'form-input', 'id': 'id_anticipo_banco_otro', 'placeholder': 'Especificar banco'}),
            'anticipo_tarjeta_app': forms.Select(attrs={'class': 'form-input', 'id': 'id_anticipo_tarjeta_app'}),
            'anticipo_comprobante_url': forms.URLInput(attrs={'class': 'form-input', 'id': 'id_anticipo_comprobante_url', 'placeholder': 'Link a la imagen'}),
            'anticipo_monto_1': forms.NumberInput(attrs={'class': 'form-input', 'step': '0.01', 'min': '0', 'id': 'id_anticipo_monto_1'}),
            'anticipo_metodo_1': forms.Select(attrs={'class': 'form-input', 'id': 'id_anticipo_metodo_1'}),
            'anticipo_banco_1': forms.Select(attrs={'class': 'form-input', 'id': 'id_anticipo_banco_1'}),
            'anticipo_monto_2': forms.NumberInput(attrs={'class': 'form-input', 'step': '0.01', 'min': '0', 'id': 'id_anticipo_monto_2'}),
            'anticipo_metodo_2': forms.Select(attrs={'class': 'form-input', 'id': 'id_anticipo_metodo_2'}),
            'anticipo_banco_2': forms.Select(attrs={'class': 'form-input', 'id': 'id_anticipo_banco_2'}),
            'estado': forms.Select(attrs={'class': 'form-input', 'id': 'id_estado_equipo'}),
            'subestado_reparacion': forms.Select(attrs={'class': 'form-input'}),
            'subestado_entregado': forms.Select(attrs={'class': 'form-input'}),
            'equipo_garantia': forms.Select(attrs={'class': 'form-input', 'id': 'id_equipo_garantia'}),
            'equipo_garantia_manual': forms.TextInput(attrs={
                'class': 'form-input',
                'id': 'id_equipo_garantia_manual',
                'placeholder': 'Ej: G1000 — Epson L29302 (Manual)'
            }),
            'motivo_garantia': forms.Textarea(attrs={'class': 'form-input', 'rows': 2, 'id': 'id_motivo_garantia'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.salida_registrada = None
        self.estado_bloqueado_por_salida = False
        self.estado_bloqueado_valor = None
        self.subestado_bloqueado_valor = ''
        if self.instance and self.instance.pk:
            try:
                self.salida_registrada = self.instance.salida
            except IngresoEquipo.salida.RelatedObjectDoesNotExist:
                self.salida_registrada = None
            self.estado_bloqueado_por_salida = self.salida_registrada is not None
            if self.estado_bloqueado_por_salida:
                self.estado_bloqueado_valor = (
                    'cortesia'
                    if self.salida_registrada.estado_reparacion == 'cortesia'
                    else (
                        'garantia'
                        if self.salida_registrada.estado_reparacion in ('garantia', 'garantia_fallos_adicionales')
                        else 'entregado'
                    )
                )
                self.subestado_bloqueado_valor = {
                    'pendiente_retiro': 'pendiente_retiro',
                    'retirado': 'con_solucion',
                    'cliente_no_acepta': 'no_quiso_reparar',
                    'no_reparable': 'sin_solucion',
                }.get(self.salida_registrada.estado_reparacion, '')
                self.initial['estado'] = self.estado_bloqueado_valor
                self.initial['subestado_reparacion'] = ''
                self.initial['subestado_entregado'] = self.subestado_bloqueado_valor
        
        # Hacer obligatorios los campos de personal
        self.fields['tecnico_encargado'].required = True
        self.fields['modelo_serie'].required = True
        self.fields['serie'].required = False
        self.fields['equipo_garantia'].required = False
        self.fields['equipo_garantia_manual'].required = False
        self.fields['firma_cliente'].required = False
        self.fields['firma_cliente_imagen'].required = False
        # Solo es obligatorio para el estado "Equipo a comprar"; el resto del
        # formulario (incluidas ventas y reparaciones normales) no lo usa.
        self.fields['compra_metodo_pago'].required = False
        if not self.is_bound:
            self.fields['compra_metodo_pago'].initial = 'efectivo'
        self.fields['firma_cliente_opcion'].initial = self._firma_cliente_opcion_inicial()
        self.fields['valor_acordado_estado'] = forms.ChoiceField(
            choices=self.VALOR_ACORDADO_ESTADOS,
            required=False,
            initial=self._valor_acordado_estado_inicial(),
            widget=forms.RadioSelect(attrs={'class': 'valor-acordado-radio'}),
            label='¿El técnico ya tiene el valor acordado?'
        )
        if self.estado_bloqueado_por_salida:
            self.initial['valor_acordado_estado'] = 'si' if self.instance.valor_acordado is not None else 'no'
            self.initial['valor_acordado'] = (
                f'{self.instance.valor_acordado:.2f}'
                if self.instance.valor_acordado is not None
                else ''
            )
            self.fields['valor_acordado_estado'].disabled = True
            self.fields['valor_acordado_estado'].required = False
            self.fields['valor_acordado'].disabled = True
            self.fields['valor_acordado'].required = False
            self.fields['valor_acordado'].widget.attrs.update({
                'class': 'form-input estado-lock-input',
                'aria-describedby': 'valor-salida-lock',
            })
            for nombre in self.CAMPOS_DIAGNOSTICO:
                self.fields[nombre].disabled = True
                self.fields[nombre].required = False
                self.fields[nombre].widget.attrs.update({
                    'class': 'form-input estado-lock-input',
                    'aria-describedby': 'diagnostico-salida-lock',
                })
        
        # Limita los técnicos disponibles a los del grupo "Tecnicos" + admins activos
        self.fields['tecnico_encargado'].queryset = _queryset_tecnicos()
        self.fields['tecnico_encargado'].empty_label = '— Selecciona un técnico —'
        # Mostrar el nombre completo en el menú (no el username)
        self.fields['tecnico_encargado'].label_from_instance = (
            lambda u: (
                f'{u.first_name} {u.last_name}'.strip()
                or u.username
            )
        )
        if not self.is_bound and self.instance and self.instance.pk and self.instance.valor_acordado is None:
            self.initial['valor_acordado'] = ''
        # Convertir el campo asesor_comercial (modelo CharField) a un ChoiceField
        # poblado con los usuarios del grupo de asesores (y admins), mostrando
        # el nombre completo como etiqueta y guardando el nombre como valor.
        asesores_qs = _queryset_asesores()
        choices = [('', '— Selecciona un asesor —')] + [
            ((f'{u.first_name} {u.last_name}'.strip() or u.username),
             (f'{u.first_name} {u.last_name}'.strip() or u.username))
            for u in asesores_qs
        ]
        # Asegura que el valor actual (en modo edición) esté entre las opciones
        try:
            actual = (self.instance.asesor_comercial or '').strip()
        except Exception:
            actual = ''
        if actual and not any(str(actual) == str(ch[0]) for ch in choices):
            choices.insert(1, (actual, actual))

        # Reemplaza el campo por un ChoiceField con widget Select
        self.fields['asesor_comercial'] = forms.ChoiceField(
            choices=choices,
            required=True,
            widget=forms.Select(attrs={'class': 'form-input'})
        )
        
        if self.is_bound and 'cli-cedula' in self.data:
            cedula = self.data.get('cli-cedula', '').strip()
            cliente = Cliente.objects.filter(cedula=cedula).first()
            if cliente:
                self.fields['equipo_garantia'].queryset = IngresoEquipo.objects.filter(cliente=cliente).order_by('-creado')
                self.fields['equipo_garantia'].empty_label = '— Selecciona un equipo anterior —'
            else:
                self.fields['equipo_garantia'].queryset = IngresoEquipo.objects.none()
                self.fields['equipo_garantia'].empty_label = '— Sin equipo registrado —'
        elif self.instance and self.instance.pk and self.instance.cliente_id:
            self.fields['equipo_garantia'].queryset = IngresoEquipo.objects.filter(cliente_id=self.instance.cliente_id).order_by('-creado')
            self.fields['equipo_garantia'].empty_label = '— Selecciona un equipo anterior —'
        else:
            self.fields['equipo_garantia'].queryset = IngresoEquipo.objects.none()
            self.fields['equipo_garantia'].empty_label = '— Sin equipo registrado —'

        self.fields['equipo_garantia'].label_from_instance = lambda eq: f"{eq.codigo_equipo} — {eq.marca} {eq.modelo_serie_detalle} ({eq.creado.strftime('%d/%m/%Y')})"

        # En ingresos normales no se escoge "Entregado" desde este formulario.
        # Cuando ya existe una salida, el estado queda bloqueado y se muestra el
        # estado visual derivado de la salida para no caer en "Ingresado".
        if 'estado' in self.fields:
            if self.estado_bloqueado_por_salida:
                self.fields['estado'].choices = [
                    (self.estado_bloqueado_valor, self.instance.estado_visual_display)
                ]
                self.fields['estado'].disabled = True
                self.fields['estado'].required = False
                self.fields['estado'].widget.attrs.update({
                    'class': 'form-input estado-lock-input',
                    'aria-describedby': 'estado-salida-lock',
                })
                for nombre in ('subestado_reparacion', 'subestado_entregado'):
                    self.fields[nombre].disabled = True
                    self.fields[nombre].required = False
                    self.fields[nombre].widget.attrs.update({
                        'class': 'form-input estado-lock-input',
                    })
            else:
                self.fields['estado'].choices = [
                    choice for choice in self.fields['estado'].choices
                    if choice[0] != 'entregado'
                ]

    def _valor_acordado_estado_inicial(self):
        if self.is_bound:
            return None
        if self.instance and self.instance.pk:
            return 'si' if self.instance.valor_acordado is not None else 'no'

        valor = self.initial.get('valor_acordado')
        if valor in (None, ''):
            return 'no'
        valor = str(valor).strip()
        if valor in ['.', '-', '—', '_', ',']:
            return 'no'
        return 'si'

    def _firma_cliente_opcion_inicial(self):
        if self.is_bound:
            return None

        valor = self.initial.get('firma_cliente_opcion')
        if valor in ('si', 'no'):
            return valor

        if self.instance and self.instance.pk:
            return 'si' if self.instance.firma_cliente and self.instance.firma_cliente_imagen else 'no'

        return None

    def clean_valor_acordado(self):
        if self.estado_bloqueado_por_salida:
            return self.instance.valor_acordado

        estado_equipo = ''
        if self.is_bound:
            estado_equipo = (self.data.get(self.add_prefix('estado')) or '').strip()
        if estado_equipo in ('garantia', 'cortesia'):
            return Decimal('0.00')
        if estado_equipo == 'donado':
            return Decimal('0.00')

        estado = ''
        if self.is_bound:
            estado = (self.data.get(self.add_prefix('valor_acordado_estado')) or '').strip()
        if estado in ('no', 'pendiente'):
            return None

        val = self.cleaned_data.get('valor_acordado')
        if not val:
            return None
        val = str(val).strip()
        if val in ['.', '-', '—', '_', ',']:
            return None
        normalizado = val.replace(',', '.')
        partes = normalizado.split('.', 1)
        entero = partes[0]
        decimales = partes[1] if len(partes) == 2 else ''
        if (
            normalizado.count('.') > 1
            or not entero
            or not entero.isdigit()
            or (len(partes) == 2 and (not decimales or not decimales.isdigit()))
            or len(decimales) > 2
        ):
            raise forms.ValidationError("Ingrese un monto válido o marca No / Pendiente si aún no hay valor acordado.")
        if len(entero) > 1 and entero.startswith('0'):
            raise forms.ValidationError(self.VALOR_ACORDADO_ERROR_MINIMO)
        try:
            valor = Decimal(normalizado)
        except InvalidOperation:
            raise forms.ValidationError("Ingrese un monto válido o marca No / Pendiente si aún no hay valor acordado.")
        if valor < self.VALOR_ACORDADO_MINIMO:
            raise forms.ValidationError(self.VALOR_ACORDADO_ERROR_MINIMO)
        return valor

    def clean_firma_cliente_imagen(self):
        valor = (self.cleaned_data.get('firma_cliente_imagen') or '').strip()
        if not valor:
            return ''

        prefijo = 'data:image/png;base64,'
        if not valor.startswith(prefijo):
            raise forms.ValidationError('La firma debe ser una imagen PNG válida.')

        payload = valor[len(prefijo):]
        if len(payload) > 700000:
            raise forms.ValidationError('La firma es demasiado grande. Vuelve a firmar.')

        try:
            base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError):
            raise forms.ValidationError('La firma no se pudo leer. Vuelve a firmar.')

        return valor

    def clean(self):
        """
        Limpia los sub-estados cuando no aplican según el estado padre.
        Así se evita que queden datos colgados si el usuario cambia el estado.
        """
        cleaned = super().clean()
        estado = cleaned.get('estado')
        estado_administrativo = estado in ('donado', 'equipo_a_comprar')
        valor_acordado_estado = cleaned.get('valor_acordado_estado')
        firma_cliente_opcion = cleaned.get('firma_cliente_opcion')
        firma_cliente_imagen = cleaned.get('firma_cliente_imagen')
        if estado_administrativo:
            cleaned['firma_cliente'] = False
            cleaned['firma_cliente_imagen'] = ''
            cleaned['firma_cliente_opcion'] = 'no'
        elif firma_cliente_opcion == 'si':
            if not firma_cliente_imagen:
                self.add_error('firma_cliente_opcion', 'Captura la firma del cliente o selecciona No firma.')
            cleaned['firma_cliente'] = bool(firma_cliente_imagen)
        elif firma_cliente_opcion == 'no':
            cleaned['firma_cliente'] = False
            cleaned['firma_cliente_imagen'] = ''
        else:
            self.add_error('firma_cliente_opcion', 'Selecciona Sí o No firma para continuar.')

        if self.estado_bloqueado_por_salida:
            cleaned['valor_acordado'] = self.instance.valor_acordado
        elif estado in ('garantia', 'cortesia'):
            cleaned['valor_acordado'] = Decimal('0.00')
        elif valor_acordado_estado in ('no', 'pendiente'):
            cleaned['valor_acordado'] = None
        elif valor_acordado_estado == 'si' and cleaned.get('valor_acordado') is None:
            self.add_error(
                'valor_acordado',
                'Ingresa el valor acordado o marca No / pendiente de valor.'
            )
        
        if self.estado_bloqueado_por_salida:
            cleaned['estado'] = self.estado_bloqueado_valor
            cleaned['subestado_reparacion'] = ''
            cleaned['subestado_entregado'] = self.subestado_bloqueado_valor
        elif estado == 'en_reparacion':
            if not cleaned.get('subestado_reparacion'):
                self.add_error('subestado_reparacion', 'Debe seleccionar un detalle obligatorio para la reparación.')
            cleaned['subestado_entregado'] = ''
        elif estado == 'entregado':
            if not cleaned.get('subestado_entregado'):
                self.add_error('subestado_entregado', 'Debe seleccionar cómo se entregó el equipo.')
            cleaned['subestado_reparacion'] = ''
        else:
            cleaned['subestado_reparacion'] = ''
            cleaned['subestado_entregado'] = ''

        if self.estado_bloqueado_por_salida:
            cleaned['equipo_garantia'] = self.instance.equipo_garantia
            cleaned['equipo_garantia_manual'] = self.instance.equipo_garantia_manual or ''
            cleaned['motivo_garantia'] = self.instance.motivo_garantia or ''
        elif estado == 'garantia':
            motivo = cleaned.get('motivo_garantia')
            if not motivo or not motivo.strip():
                self.add_error('motivo_garantia', 'Debe indicar obligatoriamente el motivo de la garantía.')
        else:
            cleaned['equipo_garantia'] = None
            cleaned['equipo_garantia_manual'] = ''
            cleaned['motivo_garantia'] = ''

        if self.estado_bloqueado_por_salida:
            for nombre in self.CAMPOS_DIAGNOSTICO:
                cleaned[nombre] = getattr(self.instance, nombre)
        elif estado in ('garantia', 'cortesia', 'donado', 'equipo_a_comprar'):
            cleaned['diagnostico_inmediato'] = 'no'
            cleaned['valor_diagnostico'] = Decimal('0.00')
            cleaned['diagnostico_metodo'] = 'efectivo'
            cleaned['diagnostico_banco'] = ''
            cleaned['diagnostico_banco_otro'] = ''
            cleaned['diagnostico_tarjeta_app'] = ''
            cleaned['diagnostico_comprobante_url'] = ''
            cleaned['diagnostico_monto_1'] = None
            cleaned['diagnostico_metodo_1'] = ''
            cleaned['diagnostico_banco_1'] = ''
            cleaned['diagnostico_monto_2'] = None
            cleaned['diagnostico_metodo_2'] = ''
            cleaned['diagnostico_banco_2'] = ''

        diagnostico_activo = cleaned.get('diagnostico_inmediato') == 'si'
        diagnostico = cleaned.get('valor_diagnostico') or Decimal('0.00')
        if (
            not self.estado_bloqueado_por_salida
            and diagnostico_activo
            and diagnostico > 0
            and cleaned.get('diagnostico_metodo') == 'mixto'
        ):
            monto_1 = cleaned.get('diagnostico_monto_1') or Decimal('0.00')
            monto_2 = cleaned.get('diagnostico_monto_2') or Decimal('0.00')

            if (monto_1 + monto_2) != diagnostico:
                self.add_error(
                    'diagnostico_monto_2',
                    f'La suma del pago mixto debe ser igual al total del diagnóstico: ${diagnostico:.2f}.'
                )

        if estado_administrativo or estado == 'cortesia':
            cleaned['abono_anticipo'] = Decimal('0.00')
            cleaned['anticipo_metodo'] = 'efectivo'
            cleaned['anticipo_banco'] = ''
            cleaned['anticipo_banco_otro'] = ''
            cleaned['anticipo_tarjeta_app'] = ''
            cleaned['anticipo_comprobante_url'] = ''
            cleaned['anticipo_monto_1'] = None
            cleaned['anticipo_metodo_1'] = ''
            cleaned['anticipo_banco_1'] = ''
            cleaned['anticipo_monto_2'] = None
            cleaned['anticipo_metodo_2'] = ''
            cleaned['anticipo_banco_2'] = ''
        elif cleaned.get('anticipo_metodo') == 'mixto':
            abono = cleaned.get('abono_anticipo') or Decimal('0.00')
            monto_1 = cleaned.get('anticipo_monto_1') or Decimal('0.00')
            monto_2 = cleaned.get('anticipo_monto_2') or Decimal('0.00')

            if abono > 0 and (monto_1 + monto_2) != abono:
                self.add_error(
                    'anticipo_monto_2',
                    f'La suma del pago mixto debe ser igual al total del abono / anticipo: ${abono:.2f}.'
                )

        # Donado no tiene salida ni valor a pagar. Equipo a comprar usa el
        # valor acordado como valor de compra y se sincroniza con Egresos.
        campos_compra = (
            'compra_metodo_pago', 'compra_banco', 'compra_banco_otro',
            'compra_tarjeta_app', 'compra_comprobante_url',
            'compra_monto_1', 'compra_metodo_1', 'compra_banco_1',
            'compra_banco_otro_1', 'compra_tarjeta_app_1', 'compra_monto_2', 'compra_metodo_2',
            'compra_banco_2', 'compra_banco_otro_2', 'compra_tarjeta_app_2',
        )
        if estado == 'donado':
            cleaned['valor_acordado'] = Decimal('0.00')
            for nombre in campos_compra:
                if nombre in cleaned:
                    cleaned[nombre] = None if 'monto' in nombre else ''
        elif estado == 'equipo_a_comprar':
            valor_compra = cleaned.get('valor_acordado') or Decimal('0.00')
            cleaned['compra_metodo_pago'] = cleaned.get('compra_metodo_pago') or 'efectivo'
            if valor_compra <= 0:
                self.add_error('valor_acordado', 'Ingresa el valor a pagar por la compra del equipo.')

            metodo = cleaned.get('compra_metodo_pago') or 'efectivo'
            banco = cleaned.get('compra_banco') or ''
            if metodo == 'transferencia':
                if not banco:
                    self.add_error('compra_banco', 'Indica el banco usado para la compra.')
                if banco == 'otro' and not (cleaned.get('compra_banco_otro') or '').strip():
                    self.add_error('compra_banco_otro', 'Especifica el nombre del banco.')
            elif metodo == 'tarjeta' and not cleaned.get('compra_tarjeta_app'):
                self.add_error('compra_tarjeta_app', 'Selecciona la tarjeta o aplicación usada.')
            elif metodo == 'mixto':
                monto_1 = cleaned.get('compra_monto_1') or Decimal('0.00')
                monto_2 = cleaned.get('compra_monto_2') or Decimal('0.00')
                metodo_1 = cleaned.get('compra_metodo_1') or ''
                metodo_2 = cleaned.get('compra_metodo_2') or ''
                if monto_1 <= 0:
                    self.add_error('compra_monto_1', 'Ingresa el primer monto de la compra.')
                if monto_2 <= 0:
                    self.add_error('compra_monto_2', 'Ingresa el segundo monto de la compra.')
                if not metodo_1:
                    self.add_error('compra_metodo_1', 'Selecciona el primer método.')
                elif metodo_1 == 'mixto':
                    self.add_error('compra_metodo_1', 'Selecciona un método individual para la primera parte.')
                if not metodo_2:
                    self.add_error('compra_metodo_2', 'Selecciona el segundo método.')
                elif metodo_2 == 'mixto':
                    self.add_error('compra_metodo_2', 'Selecciona un método individual para la segunda parte.')
                if metodo_1 == 'transferencia' and not cleaned.get('compra_banco_1'):
                    self.add_error('compra_banco_1', 'Selecciona el banco del primer pago.')
                if metodo_2 == 'transferencia' and not cleaned.get('compra_banco_2'):
                    self.add_error('compra_banco_2', 'Selecciona el banco del segundo pago.')
                if metodo_1 == 'transferencia' and cleaned.get('compra_banco_1') == 'otro' and not cleaned.get('compra_banco_otro_1'):
                    self.add_error('compra_banco_otro_1', 'Especifica el banco del primer pago.')
                if metodo_2 == 'transferencia' and cleaned.get('compra_banco_2') == 'otro' and not cleaned.get('compra_banco_otro_2'):
                    self.add_error('compra_banco_otro_2', 'Especifica el banco del segundo pago.')
                if metodo_1 == 'tarjeta' and not cleaned.get('compra_tarjeta_app_1'):
                    self.add_error('compra_tarjeta_app_1', 'Selecciona la tarjeta o app del primer pago.')
                if metodo_2 == 'tarjeta' and not cleaned.get('compra_tarjeta_app_2'):
                    self.add_error('compra_tarjeta_app_2', 'Selecciona la tarjeta o app del segundo pago.')
                if monto_1 + monto_2 != valor_compra:
                    self.add_error(
                        'compra_monto_2',
                        f'La suma de la compra mixta debe ser igual al valor a pagar: ${valor_compra:.2f}.'
                    )
        else:
            for nombre in campos_compra:
                if nombre in cleaned:
                    cleaned[nombre] = None if 'monto' in nombre else ''
        
            
        return cleaned


# ─────────────────────────────────────────────────────────
# Abono
# ─────────────────────────────────────────────────────────

class AbonoForm(forms.ModelForm):
    class Meta:
        model = Abono
        fields = [
            'fecha', 'monto', 'metodo',
            'banco', 'banco_otro', 'tarjeta_app', 'comprobante_url',
            'numero_recibo', 'observaciones',
            # Factura
            'factura_realizada',
            'factura_nombres',
            'factura_cedula', 'factura_correo',
            # Bodegaje
            'bodegaje_decision', 'bodegaje_monto_aplicado',
        ]
        widgets = {
            'fecha': forms.DateInput(
                attrs={'class': 'form-input', 'type': 'date'},
                format='%Y-%m-%d',
            ),
            'monto': forms.NumberInput(attrs={
                'class': 'form-input', 'step': '0.01', 'min': '0.01',
                'id': 'id_monto',
            }),
            'metodo': forms.Select(attrs={'class': 'form-input', 'id': 'id_metodo'}),
            'banco': forms.Select(attrs={'class': 'form-input', 'id': 'id_banco'}),
            'banco_otro': forms.TextInput(attrs={
                'class': 'form-input', 'id': 'id_banco_otro',
                'placeholder': 'Escribe el nombre del banco',
            }),
            'tarjeta_app': forms.Select(attrs={
                'class': 'form-input', 'id': 'id_tarjeta_app',
            }),
            'comprobante_url': forms.URLInput(attrs={
                'class': 'form-input', 'id': 'id_comprobante_url',
                'placeholder': 'https://... (Drive, WhatsApp, etc.)',
            }),
            'numero_recibo': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Se genera automáticamente si lo dejas vacío',
            }),
            'observaciones': forms.Textarea(attrs={'class': 'form-input', 'rows': 2}),
            # Factura
            'factura_realizada': forms.Select(attrs={
                'class': 'form-input', 'id': 'id_factura_realizada',
            }),
            'factura_nombres': forms.TextInput(attrs={
                'class': 'form-input', 'id': 'id_factura_nombres',
                'placeholder': 'Nombres del titular de factura',
            }),
            'factura_cedula': forms.TextInput(attrs={
                'class': 'form-input', 'id': 'id_factura_cedula',
                'pattern': '[0-9]+',
                'title': 'Por favor ingrese solo números.',
                'oninvalid': 'this.setCustomValidity("Por favor ingrese solo valores numéricos para Cédula o RUC.")',
                'oninput': 'this.setCustomValidity("")',
                'placeholder': 'Cédula / RUC',
            }),
            'factura_correo': forms.EmailInput(attrs={
                'class': 'form-input', 'id': 'id_factura_correo',
                'title': 'Por favor ingrese un correo válido.',
                'oninvalid': 'this.setCustomValidity("Por favor incluya un signo @ y el dominio en la dirección de correo.")',
                'oninput': 'this.setCustomValidity("")',
                'placeholder': 'correo@ejemplo.com',
            }),
            # Bodegaje
            'bodegaje_decision': forms.Select(attrs={
                'class': 'form-input', 'id': 'id_bodegaje_decision',
            }),
            'bodegaje_monto_aplicado': forms.HiddenInput(attrs={
                'id': 'id_bodegaje_monto_aplicado',
            }),
        }

    def __init__(self, *args, **kwargs):
        # `ingreso` se pasa desde la vista para que el form sepa si hay bodegaje pendiente
        self.ingreso = kwargs.pop('ingreso', None)
        super().__init__(*args, **kwargs)

        # bodegaje_monto_aplicado es un campo oculto: nunca lo escribe el usuario,
        # se rellena automáticamente en clean() según la decisión.
        self.fields['bodegaje_monto_aplicado'].required = False

        # Placeholder para el select de bancos (sólo se muestra si método=transferencia)
        self.fields['banco'].choices = [
            ('', '— Selecciona un banco —')
        ] + list(self.fields['banco'].choices)[1:]  # quitar el blank default

        # Campo histórico: ya no se muestra como método de pago independiente.
        self.fields['tarjeta_app'].choices = [
            ('', '— Selecciona una opción —')
        ] + list(self.fields['tarjeta_app'].choices)[1:]

        # ¿Hay bodegaje que el usuario pueda decidir cobrar/perdonar?
        # Solo si está PENDIENTE (acumulando al vuelo). Si ya se cerró
        # (cliente retiró o se decidió en un abono previo), no se vuelve a
        # ofrecer aquí para evitar inconsistencias: para reabrir esa decisión
        # se usa el botón de "deshacer retiro" en la lista de salidas.
        bodegaje_pend = Decimal('0.00')
        if self.ingreso is not None:
            try:
                bodegaje_pend = Decimal(self.ingreso.bodegaje_pendiente or 0)
            except Exception:
                bodegaje_pend = Decimal('0.00')

        if bodegaje_pend <= 0:
            # No hay bodegaje pendiente: dejar solo "No aplica" para no confundir.
            self.fields['bodegaje_decision'].choices = [
                ('na', 'No aplica (sin bodegaje pendiente)'),
            ]
            self.fields['bodegaje_decision'].initial = 'na'
        else:
            # Hay bodegaje pendiente: mostrar solo las dos opciones reales y obligar a decidir.
            self.fields['bodegaje_decision'].choices = [
                ('', '— Selecciona una opción —'),
                ('si', 'Sí — aplicar bodegaje (sumar al monto)'),
                ('no', 'No — perdonar bodegaje'),
            ]
            self.fields['bodegaje_decision'].required = True

        # Guardamos el monto de bodegaje que se mostró en el formulario.
        # Esto sirve para que, si el usuario eligió "Sí" pero el bodegaje
        # ya quedó cerrado/congelado entre que abrió y envió el formulario,
        # se respete su decisión y se cobre el monto correcto igualmente.
        self._bodegaje_pend_inicial = bodegaje_pend

    def clean(self):
        cleaned = super().clean()
        metodo = cleaned.get('metodo')
        banco = cleaned.get('banco')
        banco_otro = (cleaned.get('banco_otro') or '').strip()
        tarjeta_app = cleaned.get('tarjeta_app')
        comprobante_url = (cleaned.get('comprobante_url') or '').strip()

        # ── Validación: si es transferencia, banco obligatorio (comprobante es opcional) ──
        if metodo == 'transferencia':
            if not banco:
                self.add_error('banco', 'Indica el banco usado para la transferencia.')
            if banco == 'otro' and not banco_otro:
                self.add_error('banco_otro', 'Escribe el nombre del banco.')
            # comprobante_url es opcional — no se valida
            # Limpiar tarjeta_app: las apps externas ya no son método del formulario.
            cleaned['tarjeta_app'] = ''

        # ── Tarjeta: solicita la aplicación (Payphone/Deuna) ──
        elif metodo == 'tarjeta':
            # Limpiar campos de transferencia
            cleaned['banco'] = ''
            cleaned['banco_otro'] = ''
            cleaned['comprobante_url'] = ''
            if not tarjeta_app:
                self.add_error('tarjeta_app', 'Selecciona la aplicación o tarjeta usada para el pago.')

        # ── Efectivo: limpiar todo lo demás ──
        elif metodo == 'efectivo':
            cleaned['banco'] = ''
            cleaned['banco_otro'] = ''
            cleaned['comprobante_url'] = ''
            cleaned['tarjeta_app'] = ''

        # ── Validación: factura realizada = Sí → datos obligatorios ──
        factura_realizada = cleaned.get('factura_realizada')
        if factura_realizada == 'si':
            for campo, etiqueta in [
                ('factura_nombres', 'Nombres'),
                ('factura_cedula', 'Número de cédula / RUC'),
                ('factura_correo', 'Correo electrónico'),
            ]:
                valor = (cleaned.get(campo) or '').strip() if isinstance(cleaned.get(campo), str) else cleaned.get(campo)
                if not valor:
                    self.add_error(campo, f'{etiqueta} es obligatorio si la factura fue realizada.')
        else:
            cleaned['factura_nombres'] = ''
            cleaned['factura_cedula'] = ''
            cleaned['factura_correo'] = ''

        # ── Validación: bodegaje ──
        bodegaje_pend = Decimal('0.00')
        if self.ingreso is not None:
            try:
                bodegaje_pend = Decimal(self.ingreso.bodegaje_pendiente or 0)
            except Exception:
                bodegaje_pend = Decimal('0.00')

        # Monto de bodegaje que se mostró al usuario cuando abrió el formulario.
        # Puede ser > 0 aunque ahora bodegaje_pend sea 0 (p. ej. si el equipo
        # ya fue marcado como retirado mientras el formulario estaba abierto).
        bodegaje_mostrado = getattr(self, '_bodegaje_pend_inicial', Decimal('0.00')) or Decimal('0.00')

        decision = cleaned.get('bodegaje_decision')
        if decision == 'si':
            # El usuario decidió COBRAR el bodegaje: respetamos su decisión.
            # Usamos el monto pendiente actual y, si ya es 0 (caso cerrado),
            # caemos al monto que se le mostró en el formulario.
            monto_bod = bodegaje_pend if bodegaje_pend > 0 else bodegaje_mostrado
            cleaned['bodegaje_decision'] = 'si'
            cleaned['bodegaje_monto_aplicado'] = monto_bod
        elif decision == 'no':
            # Perdonar explícitamente.
            cleaned['bodegaje_decision'] = 'no'
            cleaned['bodegaje_monto_aplicado'] = Decimal('0.00')
        elif bodegaje_pend > 0:
            # Hay bodegaje pendiente pero no se eligió ninguna opción → error.
            self.add_error(
                'bodegaje_decision',
                'Indica si se aplica o se perdona el bodegaje acumulado.'
            )
        else:
            # No hay bodegaje pendiente y no se decidió nada → no aplica.
            cleaned['bodegaje_decision'] = 'na'
            cleaned['bodegaje_monto_aplicado'] = Decimal('0.00')

        return cleaned


# ─────────────────────────────────────────────────────────
# Salida de equipo
# ─────────────────────────────────────────────────────────

class SalidaEquipoForm(forms.ModelForm):
    ESTADOS_REVISION_PENDIENTE = ('cliente_no_acepta', 'no_reparable')
    ESTADO_REVISION = 'revision'

    reporte_tecnico = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-input', 'rows': 3,
            'placeholder': '(Se completa luego, durante o después del diagnóstico)',
        }),
        required=False,
        label='Reporte del técnico (lo que se le realizó al equipo)',
        help_text='(Se completa aquí al registrar la salida)'
    )
    asesora_notificacion = forms.ModelChoiceField(
        queryset=User.objects.none(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-input'}),
        label='Notificar a asesora',
        empty_label='— Selecciona una asesora —',
    )
    mensaje_notificacion = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-input',
            'rows': 2,
            'placeholder': 'Detalle breve para la asesora (opcional)',
        }),
        label='Mensaje para la asesora',
    )

    class Meta:
        model = SalidaEquipo
        fields = [
            'fecha_salida', 'estado_reparacion', 'tecnico_reparo',
            'observaciones',
            'valor_acordado_revision',
            'aplica_valor_acordado_adicional',
            'valor_acordado_adicional',
            'motivo_valor_acordado_adicional',
            'valor_final_cobrado', 'metodo_pago_final', 'numero_recibo',
            'banco', 'banco_otro', 'tarjeta_app', 'comprobante_url',
            'monto_1', 'metodo_1', 'banco_1',
            'monto_2', 'metodo_2', 'banco_2',
            'factura_realizada', 'factura_nombres',
            'factura_cedula', 'factura_correo',
        ]
        widgets = {
            'fecha_salida': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}, format='%Y-%m-%d'),
            'estado_reparacion': forms.Select(attrs={'class': 'form-input'}),
            'tecnico_reparo': forms.Select(attrs={'class': 'form-input'}),
            'numero_recibo': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Se genera automáticamente si lo dejas vacío',
            }),
            'observaciones': forms.Textarea(attrs={
                'class': 'form-input', 'rows': 3,
                'placeholder': 'Opcional. Solo si necesitas anotar algo del cierre.',
            }),
            'valor_final_cobrado': forms.NumberInput(attrs={
                'class': 'form-input', 'step': '0.01', 'min': '0',
            }),
            'valor_acordado_revision': forms.NumberInput(attrs={
                'class': 'form-input',
                'step': '0.01',
                'min': '0',
                'placeholder': 'Ej.: 20.00',
            }),
            'aplica_valor_acordado_adicional': forms.Select(attrs={
                'class': 'form-input',
            }),
            'valor_acordado_adicional': forms.NumberInput(attrs={
                'class': 'form-input',
                'step': '0.01',
                'placeholder': 'Ej.: 0.10',
                'inputmode': 'decimal',
            }),
            'motivo_valor_acordado_adicional': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Ej.: Repuesto adicional autorizado por el cliente',
                'maxlength': '500',
            }),
            'metodo_pago_final': forms.Select(attrs={'class': 'form-input'}),
            'banco': forms.Select(attrs={'class': 'form-input', 'id': 'id_banco'}),
            'banco_otro': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Especificar...', 'id': 'id_banco_otro'}),
            'tarjeta_app': forms.Select(attrs={'class': 'form-input', 'id': 'id_tarjeta_app'}),
            'comprobante_url': forms.URLInput(attrs={'class': 'form-input', 'placeholder': 'https://...', 'id': 'id_comprobante_url'}),
            'monto_1': forms.NumberInput(attrs={'class': 'form-input', 'step': '0.01', 'min': '0', 'id': 'id_monto_1'}),
            'metodo_1': forms.Select(attrs={'class': 'form-input', 'id': 'id_metodo_1'}),
            'banco_1': forms.Select(attrs={'class': 'form-input', 'id': 'id_banco_1'}),
            'monto_2': forms.NumberInput(attrs={'class': 'form-input', 'step': '0.01', 'min': '0', 'id': 'id_monto_2'}),
            'metodo_2': forms.Select(attrs={'class': 'form-input', 'id': 'id_metodo_2'}),
            'banco_2': forms.Select(attrs={'class': 'form-input', 'id': 'id_banco_2'}),
            'factura_realizada': forms.Select(attrs={'class': 'form-input'}),
            'factura_nombres': forms.TextInput(attrs={'class': 'form-input'}),
            'factura_cedula': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Cédula / RUC',
                'pattern': '[0-9]+',
                'title': 'Por favor ingrese solo números.',
                'oninvalid': 'this.setCustomValidity("Por favor ingrese solo valores numéricos para Cédula o RUC.")',
                'oninput': 'this.setCustomValidity("")',
            }),
            'factura_correo': forms.EmailInput(attrs={
                'class': 'form-input',
                'placeholder': 'Correo electrónico',
                'title': 'Por favor ingrese un correo válido.',
                'oninvalid': 'this.setCustomValidity("Por favor incluya un signo @ y el dominio en la dirección de correo.")',
                'oninput': 'this.setCustomValidity("")',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.notificacion_asesora_tipo = None
        self.notificacion_asesora_valor = Decimal('0.00')
        self.notificacion_asesora_mensaje_default = ''
        self.fields['aplica_valor_acordado_adicional'].required = False
        self.fields['valor_acordado_adicional'].required = False
        self.fields['aplica_valor_acordado_adicional'].choices = [
            ('no', 'No'),
            ('si', 'Sí'),
        ]
        if not self.is_bound and not (self.instance and self.instance.pk):
            self.initial['aplica_valor_acordado_adicional'] = 'no'

        if self.instance and hasattr(self.instance, 'ingreso') and self.instance.ingreso:
            self.fields['reporte_tecnico'].initial = self.instance.ingreso.reporte_tecnico
            if self.instance.pk:
                if self.instance.estado_reparacion == 'garantia_fallos_adicionales':
                    self.initial['valor_final_cobrado'] = self.instance.ingreso.valor_acordado or Decimal('0.00')
                    self.initial['metodo_pago_final'] = 'sin_pago'
                    notificacion = (
                        self.instance.notificaciones_asesora
                        .filter(tipo=NotificacionAsesora.TIPO_FALLOS_ADICIONALES)
                        .select_related('asesora')
                        .first()
                    )
                else:
                    notificacion = (
                        self.instance.notificaciones_asesora
                        .filter(tipo__in=[
                            NotificacionAsesora.TIPO_REVISION_PENDIENTE,
                            NotificacionAsesora.TIPO_SALDO_RETIRO,
                        ])
                        .select_related('asesora')
                        .first()
                    )
                    if (
                        notificacion
                        and self.instance.estado_reparacion in self.ESTADOS_REVISION_PENDIENTE
                        and notificacion.tipo == NotificacionAsesora.TIPO_REVISION_PENDIENTE
                    ):
                        self.initial['valor_final_cobrado'] = notificacion.valor_acordado
                        self.initial['metodo_pago_final'] = 'sin_pago'
                    elif (
                        notificacion
                        and self.instance.estado_reparacion == self.ESTADO_REVISION
                        and notificacion.tipo == NotificacionAsesora.TIPO_REVISION_PENDIENTE
                        and not self.instance.valor_acordado_revision
                    ):
                        self.initial['valor_acordado_revision'] = notificacion.valor_acordado
                if notificacion:
                    self.initial['asesora_notificacion'] = notificacion.asesora_id
                    self.initial['mensaje_notificacion'] = notificacion.mensaje

        # ── Técnico que reparó: OBLIGATORIO ──────────────────────────
        # El responsable de la reparación se declara aquí, en la salida.
        # Solo usuarios activos pertenecientes al grupo Tecnicos.
        tecnicos_qs = _queryset_tecnicos()
        # Si por configuración no hay grupos aún, no dejamos la lista vacía.
        if not tecnicos_qs.exists():
            tecnicos_qs = User.objects.filter(is_active=True).order_by('first_name', 'username')
        self.fields['tecnico_reparo'].queryset = tecnicos_qs
        self.fields['tecnico_reparo'].label_from_instance = (
            lambda u: (
                f'{u.first_name} {u.last_name}'.strip()
                or u.username
            )
        )
        self.fields['tecnico_reparo'].required = True
        self.fields['tecnico_reparo'].label = 'Técnico que reparó el equipo'
        self.fields['tecnico_reparo'].empty_label = '— Selecciona el técnico —'
        self.fields['asesora_notificacion'].queryset = _queryset_asesores()
        self.fields['asesora_notificacion'].label_from_instance = (
            lambda u: (
                f'{u.first_name} {u.last_name}'.strip()
                or u.username
            )
        )

        choices = list(self.fields['estado_reparacion'].choices)
        
        # Ocultar la opción de chatarrerización del formulario normal.
        if not (self.instance and self.instance.pk and self.instance.estado_reparacion == 'chatarrerizacion'):
            choices = [c for c in choices if c[0] != 'chatarrerizacion']

        # Ocultar la opción 'retirado' del formulario normal (se maneja aparte para bodegaje)
        if not (self.instance and self.instance.pk and self.instance.estado_reparacion == 'retirado'):
            choices = [c for c in choices if c[0] != 'retirado']
            
        # Validar si el ingreso es o no es de garantía
        if self.instance and hasattr(self.instance, 'ingreso') and self.instance.ingreso:
            es_garantia = (self.instance.ingreso.estado == 'garantia' or 
                           self.instance.ingreso.equipo_garantia or 
                           self.instance.ingreso.equipo_garantia_manual)
            
            if es_garantia:
                # Si el ingreso ES por garantía, permitir garantía normal o garantía con valor adicional.
                choices = [
                    c for c in choices
                    if c[0] in ('garantia', 'garantia_fallos_adicionales')
                ]
            else:
                # Si el ingreso NO ES por garantía, ocultar la opción de salida por garantía
                choices = [
                    c for c in choices
                    if c[0] not in ('garantia', 'garantia_fallos_adicionales', 'cortesia')
                ]
                
        self.fields['estado_reparacion'].choices = choices

        es_cortesia = bool(
            self.instance
            and hasattr(self.instance, 'ingreso')
            and self.instance.ingreso
            and self.instance.ingreso.estado == 'cortesia'
        )
        if es_cortesia:
            self.fields['estado_reparacion'].choices = [
                ('cortesia', 'Salida de cortesía'),
            ]
            self.initial['estado_reparacion'] = 'cortesia'
            self.initial['valor_final_cobrado'] = Decimal('0.00')
            self.initial['metodo_pago_final'] = 'cortesia'
            for nombre in (
                'valor_acordado_revision',
                'aplica_valor_acordado_adicional',
                'valor_acordado_adicional',
                'motivo_valor_acordado_adicional',
                'valor_final_cobrado',
                'metodo_pago_final',
                'numero_recibo',
                'banco',
                'banco_otro',
                'tarjeta_app',
                'comprobante_url',
                'monto_1',
                'metodo_1',
                'banco_1',
                'monto_2',
                'metodo_2',
                'banco_2',
                'factura_realizada',
                'factura_nombres',
                'factura_cedula',
                'factura_correo',
                'asesora_notificacion',
                'mensaje_notificacion',
            ):
                self.fields[nombre].required = False

    def _limpiar_pago_pendiente(self, cleaned):
        cleaned['metodo_pago_final'] = 'sin_pago'
        cleaned['banco'] = ''
        cleaned['banco_otro'] = ''
        cleaned['tarjeta_app'] = ''
        cleaned['comprobante_url'] = ''
        cleaned['numero_recibo'] = ''
        cleaned['monto_1'] = None
        cleaned['metodo_1'] = ''
        cleaned['banco_1'] = ''
        cleaned['monto_2'] = None
        cleaned['metodo_2'] = ''
        cleaned['banco_2'] = ''

    def _limpiar_cortesia(self, cleaned):
        cleaned['estado_reparacion'] = 'cortesia'
        cleaned['valor_acordado_revision'] = None
        self._limpiar_valor_acordado_adicional(cleaned)
        cleaned['valor_final_cobrado'] = Decimal('0.00')
        self._limpiar_pago_pendiente(cleaned)
        cleaned['metodo_pago_final'] = 'cortesia'
        cleaned['factura_realizada'] = 'no'
        cleaned['factura_nombres'] = ''
        cleaned['factura_cedula'] = ''
        cleaned['factura_correo'] = ''
        cleaned['asesora_notificacion'] = None
        cleaned['mensaje_notificacion'] = ''

    def _limpiar_valor_acordado_adicional(self, cleaned):
        cleaned['aplica_valor_acordado_adicional'] = 'no'
        cleaned['valor_acordado_adicional'] = Decimal('0.00')
        cleaned['motivo_valor_acordado_adicional'] = ''

    def _registrar_notificacion_pendiente(self, tipo, valor, mensaje_default):
        self.notificacion_asesora_tipo = tipo
        self.notificacion_asesora_valor = valor
        self.notificacion_asesora_mensaje_default = mensaje_default

    def _saldo_pendiente_despues_de_pago(
        self,
        valor_pagado_ahora,
        valor_acordado_adicional=Decimal('0.00'),
    ):
        if not (self.instance and self.instance.ingreso):
            return Decimal('0.00')

        ingreso = self.instance.ingreso
        valor_total = (
            (ingreso.valor_acordado or Decimal('0.00'))
            + (valor_acordado_adicional or Decimal('0.00'))
        )
        abonado_previo = ingreso.total_abonado
        if self.instance and self.instance.pk and self.instance.valor_final_cobrado:
            abonado_previo -= self.instance.valor_final_cobrado
        pendiente = valor_total - abonado_previo - (valor_pagado_ahora or Decimal('0.00'))
        return pendiente if pendiente > 0 else Decimal('0.00')

    def clean(self):
        cleaned = super().clean()
        estado_reparacion = cleaned.get('estado_reparacion')
        self.notificacion_asesora_tipo = None
        self.notificacion_asesora_valor = Decimal('0.00')
        self.notificacion_asesora_mensaje_default = ''

        if self.instance and self.instance.ingreso and self.instance.ingreso.estado == 'cortesia':
            self._limpiar_cortesia(cleaned)
            return cleaned
        
        # Validar que no se pueda marcar como retirado si hay saldo pendiente
        if estado_reparacion == 'retirado':
            if self.instance and self.instance.ingreso and self.instance.ingreso.diferencia > 0:
                self.add_error('estado_reparacion', f'No se puede marcar como retirado porque hay un saldo pendiente de ${self.instance.ingreso.diferencia}. El cliente debe pagar todo primero.')
            # El cargo adicional forma parte del valor histórico del trabajo y
            # debe conservarse cuando el equipo pasa de pendiente a retirado.
            if self.instance and self.instance.pk:
                cleaned['aplica_valor_acordado_adicional'] = (
                    self.instance.aplica_valor_acordado_adicional
                )
                cleaned['valor_acordado_adicional'] = self.instance.valor_acordado_adicional
                cleaned['motivo_valor_acordado_adicional'] = (
                    self.instance.motivo_valor_acordado_adicional
                )
            cleaned['valor_final_cobrado'] = Decimal('0.00')
            cleaned['valor_acordado_revision'] = None
            self._limpiar_pago_pendiente(cleaned)
            return cleaned

        valor_adicional = Decimal('0.00')
        if estado_reparacion == 'pendiente_retiro':
            aplica_adicional = cleaned.get('aplica_valor_acordado_adicional') or 'no'
            if aplica_adicional == 'si':
                valor_adicional = cleaned.get('valor_acordado_adicional') or Decimal('0.00')
                motivo_adicional = (
                    cleaned.get('motivo_valor_acordado_adicional') or ''
                ).strip()
                if valor_adicional < Decimal('0.01'):
                    self.add_error(
                        'valor_acordado_adicional',
                        'Ingresa un valor adicional de al menos $0.01.',
                    )
                if not motivo_adicional:
                    self.add_error(
                        'motivo_valor_acordado_adicional',
                        'Explica por qué se aplica el valor acordado adicional.',
                    )
                cleaned['motivo_valor_acordado_adicional'] = motivo_adicional
            else:
                self._limpiar_valor_acordado_adicional(cleaned)
        else:
            self._limpiar_valor_acordado_adicional(cleaned)
                
        metodo = cleaned.get('metodo_pago_final')
        valor = cleaned.get('valor_final_cobrado') or Decimal('0.00')
        valor_revision = cleaned.get('valor_acordado_revision') or Decimal('0.00')
        banco = cleaned.get('banco')
        banco_otro = cleaned.get('banco_otro')
        tarjeta_app = cleaned.get('tarjeta_app')

        if estado_reparacion == self.ESTADO_REVISION:
            if valor_revision < Decimal('1.00'):
                self.add_error(
                    'valor_acordado_revision',
                    'Ingresa el valor acordado por revisión. Debe ser de $1.00 o más.'
                )
            if not cleaned.get('asesora_notificacion'):
                self.add_error(
                    'asesora_notificacion',
                    'Selecciona la asesora que recibirá esta notificación.'
                )
            self._registrar_notificacion_pendiente(
                NotificacionAsesora.TIPO_REVISION_PENDIENTE,
                valor_revision,
                (
                    'El equipo {codigo} salió en estado Revisión. '
                    'Valor acordado pendiente: ${valor:.2f}. No entregar hasta registrar el pago.'
                ),
            )
            cleaned['valor_final_cobrado'] = Decimal('0.00')
            self._limpiar_pago_pendiente(cleaned)
            return cleaned

        cleaned['valor_acordado_revision'] = None

        if estado_reparacion == 'garantia_fallos_adicionales':
            if valor <= 0:
                self.add_error(
                    'valor_final_cobrado',
                    'Ingresa el valor acordado por los fallos adicionales.'
                )
            if not cleaned.get('asesora_notificacion'):
                self.add_error(
                    'asesora_notificacion',
                    'Selecciona la asesora que recibirá esta notificación.'
                )
            self._registrar_notificacion_pendiente(
                NotificacionAsesora.TIPO_FALLOS_ADICIONALES,
                valor,
                (
                    'El equipo {codigo} salió por garantía con fallos adicionales. '
                    'Valor acordado pendiente: ${valor:.2f}.'
                ),
            )
            self._limpiar_pago_pendiente(cleaned)
            return cleaned

        if estado_reparacion in self.ESTADOS_REVISION_PENDIENTE and valor > 0:
            if valor < Decimal('1.00'):
                self.add_error(
                    'valor_final_cobrado',
                    'El valor pendiente debe ser de $1.00 o más.'
                )
            if not cleaned.get('asesora_notificacion'):
                self.add_error(
                    'asesora_notificacion',
                    'Selecciona la asesora que recibirá esta notificación.'
                )
            self._registrar_notificacion_pendiente(
                NotificacionAsesora.TIPO_REVISION_PENDIENTE,
                valor,
                (
                    'El equipo {codigo} salió con revisión pendiente de pago. '
                    'Valor pendiente: ${valor:.2f}. No entregar hasta registrar el pago.'
                ),
            )
            self._limpiar_pago_pendiente(cleaned)
            return cleaned

        if estado_reparacion == 'pendiente_retiro':
            if not (self.instance and self.instance.pk):
                valor = Decimal('0.00')
                cleaned['valor_final_cobrado'] = valor
                self._limpiar_pago_pendiente(cleaned)
                metodo = 'sin_pago'
                banco = ''
                banco_otro = ''
                tarjeta_app = ''
            saldo_pendiente = self._saldo_pendiente_despues_de_pago(
                valor,
                valor_adicional,
            )
            if saldo_pendiente > 0:
                if not cleaned.get('asesora_notificacion'):
                    self.add_error(
                        'asesora_notificacion',
                        'Selecciona la asesora que recibirá esta notificación.'
                    )
                self._registrar_notificacion_pendiente(
                    NotificacionAsesora.TIPO_SALDO_RETIRO,
                    saldo_pendiente,
                    (
                        'El equipo {codigo} ya está listo para retiro, pero mantiene '
                        'saldo pendiente de ${valor:.2f}. No entregar hasta registrar el pago.'
                    ),
                )

        if metodo == 'mixto':
            monto1 = cleaned.get('monto_1') or Decimal('0.00')
            metodo1 = cleaned.get('metodo_1')
            banco1 = cleaned.get('banco_1')
            monto2 = cleaned.get('monto_2') or Decimal('0.00')
            metodo2 = cleaned.get('metodo_2')
            banco2 = cleaned.get('banco_2')

            if not monto1 or monto1 <= 0:
                self.add_error('monto_1', 'Debe ingresar el primer monto.')
            if not metodo1:
                self.add_error('metodo_1', 'Debe seleccionar el primer método.')
            elif metodo1 == 'transferencia' and not banco1:
                self.add_error('banco_1', 'Debe seleccionar un banco para la transferencia.')

            if not monto2 or monto2 <= 0:
                self.add_error('monto_2', 'Debe ingresar el segundo monto.')
            if not metodo2:
                self.add_error('metodo_2', 'Debe seleccionar el segundo método.')
            elif metodo2 == 'transferencia' and not banco2:
                self.add_error('banco_2', 'Debe seleccionar un banco para la transferencia.')

            if (monto1 + monto2) != valor:
                self.add_error('metodo_pago_final', 'La suma de los montos mixtos debe ser igual al valor cobrado.')
        elif metodo == 'transferencia':
            if not banco:
                self.add_error('banco', 'Indica el banco usado para la transferencia.')
            if banco == 'otro' and not banco_otro:
                self.add_error('banco_otro', 'Escribe el nombre del banco.')
        elif metodo == 'tarjeta':
            if not tarjeta_app:
                self.add_error('tarjeta_app', 'Selecciona la aplicación o tarjeta usada para el pago.')

        return cleaned

    def save(self, commit=True):
        salida = super().save(commit=False)
        valor_fallos_adicionales = None
        if salida.estado_reparacion == 'garantia_fallos_adicionales':
            valor_fallos_adicionales = self.cleaned_data.get('valor_final_cobrado') or Decimal('0.00')
            salida.valor_final_cobrado = Decimal('0.00')
            salida.metodo_pago_final = 'sin_pago'
            salida.numero_recibo = ''
            salida.banco = ''
            salida.banco_otro = ''
            salida.tarjeta_app = ''
            salida.comprobante_url = ''
            salida.monto_1 = None
            salida.metodo_1 = ''
            salida.banco_1 = ''
            salida.monto_2 = None
            salida.metodo_2 = ''
            salida.banco_2 = ''
        elif salida.estado_reparacion == self.ESTADO_REVISION:
            salida.valor_acordado_revision = self.cleaned_data.get('valor_acordado_revision') or Decimal('0.00')
            salida.valor_final_cobrado = Decimal('0.00')
            salida.metodo_pago_final = 'sin_pago'
            salida.numero_recibo = ''
            salida.banco = ''
            salida.banco_otro = ''
            salida.tarjeta_app = ''
            salida.comprobante_url = ''
            salida.monto_1 = None
            salida.metodo_1 = ''
            salida.banco_1 = ''
            salida.monto_2 = None
            salida.metodo_2 = ''
            salida.banco_2 = ''
        elif (
            salida.estado_reparacion in self.ESTADOS_REVISION_PENDIENTE
            and self.notificacion_asesora_tipo == NotificacionAsesora.TIPO_REVISION_PENDIENTE
        ):
            salida.valor_final_cobrado = Decimal('0.00')
            salida.metodo_pago_final = 'sin_pago'
            salida.numero_recibo = ''
            salida.banco = ''
            salida.banco_otro = ''
            salida.tarjeta_app = ''
            salida.comprobante_url = ''
            salida.monto_1 = None
            salida.metodo_1 = ''
            salida.banco_1 = ''
            salida.monto_2 = None
            salida.metodo_2 = ''
            salida.banco_2 = ''
        else:
            salida.valor_acordado_revision = None

        salida.cliente_recibe_conforme = 'si' if salida.es_positivo else 'no'
        reporte = self.cleaned_data.get('reporte_tecnico')
        
        if hasattr(salida, 'ingreso') and salida.ingreso:
            salida.ingreso.reporte_tecnico = reporte
            if valor_fallos_adicionales is not None:
                salida.ingreso.valor_acordado = valor_fallos_adicionales
            if commit:
                update_fields = ['reporte_tecnico']
                if valor_fallos_adicionales is not None:
                    update_fields.append('valor_acordado')
                salida.ingreso.save(update_fields=update_fields)
                
        if commit:
            salida.save()
            self.save_m2m()
        return salida


# ─────────────────────────────────────────────────────────
# Egresos / Categorías de egreso
# ─────────────────────────────────────────────────────────

class CategoriaEgresoForm(forms.ModelForm):
    class Meta:
        model = CategoriaEgreso
        fields = ['nombre', 'descripcion', 'color', 'icono', 'orden', 'activo']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-input'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-input', 'rows': 2}),
            'color': forms.Select(attrs={'class': 'form-input'}),
            'icono': forms.TextInput(attrs={'class': 'form-input', 'placeholder': '🔧'}),
            'orden': forms.NumberInput(attrs={'class': 'form-input'}),
        }


class EgresoForm(forms.ModelForm):
    class Meta:
        model = Egreso
        fields = [
            'fecha', 'categoria', 'concepto', 'monto', 'notas',
            'metodo', 'banco', 'banco_otro', 'tarjeta_app', 'comprobante_url', 'numero_recibo',
            'monto_1', 'metodo_1', 'banco_1', 'banco_otro_1', 'tarjeta_app_1',
            'monto_2', 'metodo_2', 'banco_2', 'banco_otro_2', 'tarjeta_app_2',
            'factura_realizada', 'factura_nombres', 'factura_cedula', 'factura_correo'
        ]
        widgets = {
            'fecha': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
            'categoria': forms.Select(attrs={'class': 'form-input'}),
            'concepto': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Ej.: Compra de repuestos PS3',
            }),
            'monto': forms.NumberInput(attrs={
                'class': 'form-input', 'step': '0.01', 'min': '0.01',
            }),
            'notas': forms.Textarea(attrs={'class': 'form-input', 'rows': 3}),
            'metodo': forms.Select(attrs={'class': 'form-input'}),
            'banco': forms.Select(attrs={'class': 'form-input'}),
            'banco_otro': forms.TextInput(attrs={'class': 'form-input'}),
            'tarjeta_app': forms.Select(attrs={'class': 'form-input'}),
            'comprobante_url': forms.URLInput(attrs={'class': 'form-input'}),
            'numero_recibo': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Se genera automáticamente si lo dejas vacío',
            }),
            'monto_1': forms.NumberInput(attrs={'class': 'form-input', 'step': '0.01', 'min': '0'}),
            'metodo_1': forms.Select(attrs={'class': 'form-input'}),
            'banco_1': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Banco si aplica'}),
            'banco_otro_1': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Otro banco si aplica'}),
            'tarjeta_app_1': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Tarjeta / App si aplica'}),
            'monto_2': forms.NumberInput(attrs={'class': 'form-input', 'step': '0.01', 'min': '0'}),
            'metodo_2': forms.Select(attrs={'class': 'form-input'}),
            'banco_2': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Banco si aplica'}),
            'banco_otro_2': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Otro banco si aplica'}),
            'tarjeta_app_2': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Tarjeta / App si aplica'}),
            'factura_realizada': forms.Select(attrs={'class': 'form-input'}),
            'factura_nombres': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Nombres del titular de factura'}),
            'factura_cedula': forms.TextInput(attrs={
                'class': 'form-input', 'placeholder': 'Cédula / RUC',
                'pattern': '[0-9]+',
                'title': 'Por favor ingrese solo números.',
                'oninvalid': 'this.setCustomValidity("Por favor ingrese solo valores numéricos para Cédula o RUC.")',
                'oninput': 'this.setCustomValidity("")',
            }),
            'factura_correo': forms.EmailInput(attrs={
                'class': 'form-input', 'placeholder': 'Correo electrónico',
                'title': 'Por favor ingrese un correo válido.',
                'oninvalid': 'this.setCustomValidity("Por favor incluya un signo @ y el dominio en la dirección de correo.")',
                'oninput': 'this.setCustomValidity("")',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['categoria'].queryset = CategoriaEgreso.objects.filter(activo=True)
        self.fields['categoria'].empty_label = '— Selecciona categoría —'

    def clean(self):
        cleaned = super().clean()
        metodo = cleaned.get('metodo')
        monto = cleaned.get('monto') or Decimal('0.00')
        if monto <= 0:
            self.add_error('monto', 'El monto debe ser mayor que cero.')
        if metodo == 'transferencia':
            banco = cleaned.get('banco') or ''
            if not banco:
                self.add_error('banco', 'Indica el banco usado para el egreso.')
            if banco == 'otro' and not (cleaned.get('banco_otro') or '').strip():
                self.add_error('banco_otro', 'Especifica el nombre del banco.')
        elif metodo == 'tarjeta' and not cleaned.get('tarjeta_app'):
            self.add_error('tarjeta_app', 'Selecciona la tarjeta o aplicación usada.')
        elif metodo == 'mixto':
            monto_1 = cleaned.get('monto_1') or Decimal('0.00')
            monto_2 = cleaned.get('monto_2') or Decimal('0.00')
            if monto_1 <= 0:
                self.add_error('monto_1', 'Ingresa el primer monto.')
            if monto_2 <= 0:
                self.add_error('monto_2', 'Ingresa el segundo monto.')
            if not cleaned.get('metodo_1'):
                self.add_error('metodo_1', 'Selecciona el primer método.')
            elif cleaned.get('metodo_1') == 'mixto':
                self.add_error('metodo_1', 'Selecciona un método individual para el primer pago.')
            if not cleaned.get('metodo_2'):
                self.add_error('metodo_2', 'Selecciona el segundo método.')
            elif cleaned.get('metodo_2') == 'mixto':
                self.add_error('metodo_2', 'Selecciona un método individual para el segundo pago.')
            if cleaned.get('metodo_1') == 'transferencia' and not cleaned.get('banco_1'):
                self.add_error('banco_1', 'Indica el banco del primer pago.')
            if cleaned.get('metodo_2') == 'transferencia' and not cleaned.get('banco_2'):
                self.add_error('banco_2', 'Indica el banco del segundo pago.')
            if cleaned.get('metodo_1') == 'transferencia' and cleaned.get('banco_1') == 'otro' and not cleaned.get('banco_otro_1'):
                self.add_error('banco_otro_1', 'Especifica el banco del primer pago.')
            if cleaned.get('metodo_2') == 'transferencia' and cleaned.get('banco_2') == 'otro' and not cleaned.get('banco_otro_2'):
                self.add_error('banco_otro_2', 'Especifica el banco del segundo pago.')
            if monto_1 + monto_2 != monto:
                self.add_error('monto_2', 'La suma de los pagos mixtos debe ser igual al monto del egreso.')
        return cleaned


# ─────────────────────────────────────────────────────────
# Avisos del panel principal (solo admin)
# ─────────────────────────────────────────────────────────

class AvisoPanelForm(forms.ModelForm):
    class Meta:
        model = AvisoPanel
        fields = ['titulo', 'mensaje', 'tipo', 'fecha_inicio', 'fecha_fin', 'activo']
        widgets = {
            'titulo': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Ej: Cerrado por feriado el 25/07',
            }),
            'mensaje': forms.Textarea(attrs={
                'class': 'form-input', 'rows': 4,
                'placeholder': 'Mensaje que verán todos en el inicio…',
            }),
            'tipo': forms.Select(attrs={'class': 'form-input'}),
            'fecha_inicio': forms.DateInput(
                attrs={'class': 'form-input', 'type': 'date'}, format='%Y-%m-%d'),
            'fecha_fin': forms.DateInput(
                attrs={'class': 'form-input', 'type': 'date'}, format='%Y-%m-%d'),
            'activo': forms.CheckboxInput(attrs={'class': 'form-check'}),
        }

    def clean(self):
        cleaned = super().clean()
        ini = cleaned.get('fecha_inicio')
        fin = cleaned.get('fecha_fin')
        if ini and fin and fin < ini:
            self.add_error('fecha_fin', 'La fecha final no puede ser anterior a la fecha de inicio.')
        return cleaned
