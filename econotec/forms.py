"""
Formularios de Econotec.
"""
from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q
from decimal import Decimal, InvalidOperation
from .models import (
    Cliente, IngresoEquipo, Abono, SalidaEquipo,
    CategoriaEgreso, Egreso, AvisoPanel,
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
                'title': 'Por favor ingrese solo números.',
                'oninvalid': 'this.setCustomValidity("Por favor ingrese solo valores numéricos para Cédula o RUC.")',
                'oninput': 'this.setCustomValidity("")',
            }),
            'nombres': forms.TextInput(attrs={
                'class': 'form-input', 'placeholder': 'Ej.: David Guevara',
            }),
            'whatsapp': forms.TextInput(attrs={
                'class': 'form-input', 'placeholder': 'Ej.:0996345364',
                'pattern': '[0-9]+',
                'title': 'Por favor ingrese solo números.',
                'oninvalid': 'this.setCustomValidity("Por favor ingrese solo números para el WhatsApp.")',
                'oninput': 'this.setCustomValidity("")',
            }),
            'correo': forms.EmailInput(attrs={
                'class': 'form-input', 'placeholder': 'Ej.: cliente@correo.com',
                'title': 'Por favor ingrese un correo válido.',
                'oninvalid': 'this.setCustomValidity("Por favor incluya un signo @ y el dominio en la dirección de correo.")',
                'oninput': 'this.setCustomValidity("")',
            }),
            'sector': forms.Select(attrs={'class': 'form-input'}),
            'sector_otro': forms.TextInput(attrs={
                'class': 'form-input', 'placeholder': 'Especificar sector si elegiste "Otro"',
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
    VALOR_ACORDADO_ESTADOS = [
        ('si', 'Sí'),
        ('no', 'No / pendiente de valor'),
    ]

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
            'problema_reportado',
            'diagnostico_inmediato', 'valor_diagnostico',
            'valor_acordado', 'abono_anticipo',
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
            'numero_factura': forms.TextInput(attrs={'class': 'form-input', 'placeholder': '(opcional)'}),
            'asesor_comercial': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Ej.: Kimberly'}),
            'tecnico_encargado': forms.Select(attrs={'class': 'form-input'}),
            'fecha_ingreso': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}, format='%Y-%m-%d'),
            'tipo_equipo': forms.Select(attrs={'class': 'form-input', 'id': 'id_tipo_equipo'}),
            'tipo_equipo_otro': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Solo si elegiste "Otros equipos"',
            }),
            'marca': forms.TextInput(attrs={
                'class': 'form-input', 'placeholder': 'Ej.: BlackBerry',
            }),
            'modelo_serie': forms.TextInput(attrs={
                'class': 'form-input', 'placeholder': 'Ej.: Curve 9320',
            }),
            'serie': forms.TextInput(attrs={
                'class': 'form-input', 'placeholder': 'Ej.: SN123456 (opcional)',
            }),
            'accesorios_entregados': forms.Textarea(attrs={
                'class': 'form-input', 'rows': 2,
                'placeholder': 'Cargador, cable HDMI, control, etc.',
            }),
            'problema_reportado': forms.Textarea(attrs={
                'class': 'form-input', 'rows': 3,
                'placeholder': 'Describa el problema reportado por el cliente...',
            }),
            'diagnostico_inmediato': forms.Select(attrs={'class': 'form-input'}),
            'valor_diagnostico': forms.NumberInput(attrs={
                'class': 'form-input', 'step': '0.01', 'min': '0',
            }),
            'abono_anticipo': forms.NumberInput(attrs={
                'class': 'form-input', 'step': '0.01', 'min': '0',
            }),
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
        
        # Hacer obligatorios los campos de personal
        self.fields['tecnico_encargado'].required = True
        self.fields['modelo_serie'].required = True
        self.fields['serie'].required = False
        self.fields['equipo_garantia'].required = False
        self.fields['equipo_garantia_manual'].required = False
        self.fields['valor_acordado_estado'] = forms.ChoiceField(
            choices=self.VALOR_ACORDADO_ESTADOS,
            required=False,
            initial=self._valor_acordado_estado_inicial(),
            widget=forms.RadioSelect(attrs={'class': 'valor-acordado-radio'}),
            label='¿El técnico ya tiene el valor acordado?'
        )
        
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

        # Quitar la opción "entregado" del campo estado
        if 'estado' in self.fields:
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

    def clean_valor_acordado(self):
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
        try:
            return Decimal(val.replace(',', '.'))
        except InvalidOperation:
            raise forms.ValidationError("Ingrese un monto válido o marca No / Pendiente si aún no hay valor acordado.")

    def clean(self):
        """
        Limpia los sub-estados cuando no aplican según el estado padre.
        Así se evita que queden datos colgados si el usuario cambia el estado.
        """
        cleaned = super().clean()
        estado = cleaned.get('estado')
        valor_acordado_estado = cleaned.get('valor_acordado_estado')

        if valor_acordado_estado in ('no', 'pendiente'):
            cleaned['valor_acordado'] = None
        elif valor_acordado_estado == 'si' and cleaned.get('valor_acordado') is None:
            self.add_error(
                'valor_acordado',
                'Ingresa el valor acordado o marca No / pendiente de valor.'
            )
        
        if estado == 'en_reparacion':
            if not cleaned.get('subestado_reparacion'):
                self.add_error('subestado_reparacion', 'Debe seleccionar un detalle obligatorio para la reparación.')
        else:
            cleaned['subestado_reparacion'] = ''
            
        if estado == 'entregado':
            if not cleaned.get('subestado_entregado'):
                self.add_error('subestado_entregado', 'Debe seleccionar cómo se entregó el equipo.')
        else:
            cleaned['subestado_entregado'] = ''
            
        if estado == 'garantia':
            motivo = cleaned.get('motivo_garantia')
            if not motivo or not motivo.strip():
                self.add_error('motivo_garantia', 'Debe indicar obligatoriamente el motivo de la garantía.')
        else:
            cleaned['equipo_garantia'] = None
            cleaned['equipo_garantia_manual'] = ''
            cleaned['motivo_garantia'] = ''

        diagnostico_activo = cleaned.get('diagnostico_inmediato') == 'si'
        diagnostico = cleaned.get('valor_diagnostico') or Decimal('0.00')
        if diagnostico_activo and diagnostico > 0 and cleaned.get('diagnostico_metodo') == 'mixto':
            monto_1 = cleaned.get('diagnostico_monto_1') or Decimal('0.00')
            monto_2 = cleaned.get('diagnostico_monto_2') or Decimal('0.00')

            if (monto_1 + monto_2) != diagnostico:
                self.add_error(
                    'diagnostico_monto_2',
                    f'La suma del pago mixto debe ser igual al total del diagnóstico: ${diagnostico:.2f}.'
                )

        if cleaned.get('anticipo_metodo') == 'mixto':
            abono = cleaned.get('abono_anticipo') or Decimal('0.00')
            monto_1 = cleaned.get('anticipo_monto_1') or Decimal('0.00')
            monto_2 = cleaned.get('anticipo_monto_2') or Decimal('0.00')

            if abono > 0 and (monto_1 + monto_2) != abono:
                self.add_error(
                    'anticipo_monto_2',
                    f'La suma del pago mixto debe ser igual al total del abono / anticipo: ${abono:.2f}.'
                )
        
            
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
    reporte_tecnico = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-input', 'rows': 3,
            'placeholder': '(Se completa luego, durante o después del diagnóstico)',
        }),
        required=False,
        label='Reporte del técnico (lo que se le realizó al equipo)',
        help_text='(Se completa aquí al registrar la salida)'
    )

    class Meta:
        model = SalidaEquipo
        fields = [
            'fecha_salida', 'estado_reparacion', 'tecnico_reparo',
            'observaciones',
            'valor_final_cobrado', 'metodo_pago_final', 'numero_recibo',
            'banco', 'banco_otro', 'tarjeta_app', 'comprobante_url',
            'monto_1', 'metodo_1', 'banco_1',
            'monto_2', 'metodo_2', 'banco_2',
            'factura_realizada', 'factura_nombres',
            'factura_cedula', 'factura_correo',
            'cliente_recibe_conforme',
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
            'cliente_recibe_conforme': forms.Select(attrs={'class': 'form-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.instance and hasattr(self.instance, 'ingreso') and self.instance.ingreso:
            self.fields['reporte_tecnico'].initial = self.instance.ingreso.reporte_tecnico

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
                # Si el ingreso ES por garantía, solo permitir la salida por garantía
                choices = [c for c in choices if c[0] == 'garantia']
            else:
                # Si el ingreso NO ES por garantía, ocultar la opción de salida por garantía
                choices = [c for c in choices if c[0] != 'garantia']
                
        self.fields['estado_reparacion'].choices = choices

    def clean(self):
        cleaned = super().clean()
        estado_reparacion = cleaned.get('estado_reparacion')
        
        # Validar que no se pueda marcar como retirado si hay saldo pendiente
        if estado_reparacion == 'retirado' and self.instance and self.instance.ingreso:
            if self.instance.ingreso.diferencia > 0:
                self.add_error('estado_reparacion', f'No se puede marcar como retirado porque hay un saldo pendiente de ${self.instance.ingreso.diferencia}. El cliente debe pagar todo primero.')
                
        metodo = cleaned.get('metodo_pago_final')
        valor = cleaned.get('valor_final_cobrado') or Decimal('0.00')
        banco = cleaned.get('banco')
        banco_otro = cleaned.get('banco_otro')
        tarjeta_app = cleaned.get('tarjeta_app')

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
        reporte = self.cleaned_data.get('reporte_tecnico')
        
        if hasattr(salida, 'ingreso') and salida.ingreso:
            salida.ingreso.reporte_tecnico = reporte
            if commit:
                salida.ingreso.save(update_fields=['reporte_tecnico'])
                
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
