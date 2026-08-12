"""
Modelos del sistema Econotec — Gestión de reparación de tecnología.

Mapea fielmente la hoja "SOLICITUD DE INGRESO" de Econotec:
- Datos del cliente (nombres, cédula, WhatsApp, correo, sector)
- Datos del equipo (tipo, marca, modelo, accesorios)
- Problema reportado / Reporte del técnico
- Diagnóstico / Valores / Abono / Diferencia
- Y suma una "Salida de equipo" con estado del trabajo realizado
"""
from datetime import date, time
from decimal import Decimal, ROUND_HALF_UP
import uuid

from django.db import models
from django.utils import timezone


# Helper común para normalizar Decimal a 2 decimales y evitar que se vea
# como "$234,970000000000" en plantillas / Excel / WhatsApp.
def _q2(valor):
    """Cuantiza cualquier Decimal/None a 2 decimales fijos."""
    if valor is None:
        return Decimal('0.00')
    try:
        return Decimal(valor).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal('0.00')


# ─────────────────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────────────────

TIPOS_EQUIPO = [
    ('impresora', 'Impresora'),
    ('laptop', 'Laptop'),
    ('pc', 'PC'),
    ('monitor', 'Monitor'),
    ('cpu', 'CPU'),
    ('celular', 'Celular'),
    ('tablet', 'Tablet'),
    ('consola', 'Consola'),
    ('mando', 'Mando'),
    ('maquina_coser', 'Máquina de Coser'),
    ('otro', 'Otros equipos'),
]

SECTORES = [
    ('norte', 'Norte'),
    ('sur', 'Sur'),
    ('centro', 'Centro'),
    ('este', 'Este'),
    ('oeste', 'Oeste'),
    ('otro', 'Otro'),
]

DIAGNOSTICO_INMEDIATO = [
    ('si', 'Sí'),
    ('no', 'No'),
]

# Sedes de Econotec.
# El "prefijo" se usa al imprimir el código del equipo: G1, G2, U1, U2...
SEDES = [
    ('guayaquil', 'Guayaquil'),
    ('quito', 'Quito'),
    ('ventas', 'Venta de Productos'),
]
SEDES_EQUIPOS = ('guayaquil', 'quito')
SEDE_PREFIJOS = {
    'guayaquil': 'G',
    'quito': 'U',
    'ventas': 'P',
}

SUBESTADO_EN_REPARACION = [
    ('', '— Ninguno —'),
    ('en_reparacion', 'En reparación'),
    ('espera_cliente', 'En reparación - Cliente'),
    ('espera_repuesto', 'En reparación - Repuestos'),
]

SUBESTADO_ENTREGADO = [
    ('', '— Ninguno —'),
    ('con_solucion', 'Con solución'),
    ('sin_solucion', 'Sin solución'),
    ('no_quiso_reparar', 'No quiso repararlo'),
    ('pendiente_retiro', 'Pendiente de retiro'),
    ('revision', 'Revisión'),
]


# ─────────────────────────────────────────────────────────
# Cliente
# ─────────────────────────────────────────────────────────

class Cliente(models.Model):
    """
    Cliente que entrega un equipo para reparar.
    Datos tomados directamente de la hoja Solicitud de Ingreso.
    """
    cedula = models.CharField(
        max_length=20, unique=True,
        verbose_name='Cédula o RUC',
        help_text='Cédula o RUC para emisión de la factura.'
    )
    nombres = models.CharField(
        max_length=150,
        verbose_name='Nombres del cliente',
    )
    whatsapp = models.CharField(
        max_length=20, blank=True,
        verbose_name='WhatsApp',
    )
    correo = models.EmailField(
        blank=True,
        verbose_name='Correo',
    )
    sector = models.CharField(
        max_length=20, choices=SECTORES, blank=True,
        verbose_name='Sector',
    )
    sector_otro = models.CharField(
        max_length=100, blank=True,
        verbose_name='Sector (especificar)',
        help_text='Si seleccionaste "Otro", indica cuál.'
    )
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Cliente'
        verbose_name_plural = 'Clientes'
        ordering = ['nombres']

    @property
    def sector_display(self):
        if self.sector == 'otro' and self.sector_otro:
            return self.sector_otro
        return self.get_sector_display() or '—'

    def __str__(self):
        return f'{self.cedula} — {self.nombres}'


# ─────────────────────────────────────────────────────────
# Inventario
# ─────────────────────────────────────────────────────────

class InventarioItem(models.Model):
    """Producto o pieza registrada dentro del inventario por sede y tipo."""

    ESTADOS = [
        ('disponible', 'Disponible'),
        ('no_disponible', 'No disponible'),
    ]

    CAUSAS_NO_DISPONIBLE = [
        ('', '—'),
        ('bajo_pedido', 'Bajo pedido'),
        ('defectuoso', 'Defectuoso'),
        ('agotado', 'Agotado'),
        ('obsoleto', 'Obsoleto'),
    ]

    UBICACIONES = [
        ('guayaquil_norte', 'Guayaquil Norte'),
        ('guayaquil_centro', 'Guayaquil Centro'),
        ('quito', 'Quito'),
    ]

    sede = models.CharField(max_length=20, choices=SEDES, verbose_name='Sede')
    categoria = models.CharField(max_length=40, verbose_name='Categoría')
    tipo = models.CharField(max_length=60, verbose_name='Tipo')
    codigo = models.CharField(max_length=40, unique=True, editable=False, verbose_name='Código QR')
    producto = models.CharField(max_length=160, verbose_name='Producto')
    marca = models.CharField(max_length=100, verbose_name='Marca')
    modelo = models.CharField(max_length=100, verbose_name='Modelo')
    serie = models.CharField(max_length=120, blank=True, verbose_name='Serie')
    estado = models.CharField(max_length=20, choices=ESTADOS, default='disponible', verbose_name='Estado')
    causa_no_disponible = models.CharField(
        max_length=30,
        choices=CAUSAS_NO_DISPONIBLE,
        blank=True,
        default='',
        verbose_name='Causa de no disponibilidad',
    )
    cantidad = models.PositiveIntegerField(default=1, verbose_name='Cantidad')
    costo = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        blank=True,
        verbose_name='Costo (USD)',
    )
    ubicacion = models.CharField(max_length=30, choices=UBICACIONES, verbose_name='Ubicación')
    observacion = models.TextField(
        blank=True,
        verbose_name='Observación',
        help_text='Nota interna opcional sobre el producto o pieza en inventario.',
    )
    registrado_por = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inventario_registrado',
        verbose_name='Registrado por',
    )
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Item de inventario'
        verbose_name_plural = 'Items de inventario'
        ordering = ['-creado']
        indexes = [
            models.Index(fields=['sede', 'categoria', 'tipo']),
            models.Index(fields=['codigo']),
        ]

    def _generar_codigo_unico(self):
        sede_prefijo = {
            'guayaquil': 'GYE',
            'quito': 'UIO',
        }.get(self.sede, 'INV')
        tipo_prefijo = ''.join(ch for ch in (self.tipo or self.categoria or 'item').upper() if ch.isalnum())[:4]
        for _ in range(20):
            codigo = f'INV-{sede_prefijo}-{tipo_prefijo}-{uuid.uuid4().hex[:6].upper()}'
            if not type(self).objects.filter(codigo=codigo).exists():
                return codigo
        return f'INV-{uuid.uuid4().hex[:12].upper()}'

    def save(self, *args, **kwargs):
        if not self.codigo:
            self.codigo = self._generar_codigo_unico()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.codigo} — {self.producto}'


class NotificacionInventarioAdmin(models.Model):
    """Aviso interno para que el administrador revise productos con stock crítico."""

    inventario_item = models.ForeignKey(
        InventarioItem,
        on_delete=models.CASCADE,
        related_name='notificaciones_admin',
        verbose_name='Producto de inventario',
    )
    creado_por = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='notificaciones_inventario_creadas',
        verbose_name='Notificado por',
    )
    mensaje = models.TextField(
        blank=True,
        verbose_name='Mensaje para administración',
    )
    leida = models.BooleanField(
        default=False,
        verbose_name='Vista por administración',
    )
    leida_en = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Vista el',
    )
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Notificación de inventario para admin'
        verbose_name_plural = 'Notificaciones de inventario para admin'
        ordering = ['-creado']
        constraints = [
            models.UniqueConstraint(
                fields=['inventario_item'],
                condition=models.Q(leida=False),
                name='uniq_notificacion_inventario_pendiente',
            ),
        ]

    def marcar_vista(self):
        if not self.leida:
            self.leida = True
            self.leida_en = timezone.now()
            self.save(update_fields=['leida', 'leida_en', 'actualizado'])

    def __str__(self):
        return f'Stock crítico — {self.inventario_item.codigo}'


# ─────────────────────────────────────────────────────────
# Ingreso de equipo (la "Solicitud de Ingreso")
# ─────────────────────────────────────────────────────────

class IngresoEquipo(models.Model):
    """
    Cada equipo entrante con su Solicitud de Ingreso.
    Es el documento principal del flujo de Econotec: equivale a la hoja
    física que se firma al recibir el equipo.
    """

    # ── Identificación ───────────────────────────────────
    sede = models.CharField(
        max_length=20, choices=SEDES, default='guayaquil',
        verbose_name='Sede',
        help_text='Sede en la que se registró el equipo. Cada sede lleva su propia numeración.'
    )
    numero_equipo = models.PositiveIntegerField(
        verbose_name='Equipo N°',
        help_text='Número correlativo del equipo dentro de su sede. Se asigna automáticamente.'
    )
    numero_factura = models.CharField(
        max_length=20, blank=True,
        verbose_name='Factura N°',
    )

    # ── Personal Econotec ────────────────────────────────
    asesor_comercial = models.CharField(
        max_length=100, blank=True,
        verbose_name='Asesora Comercial',
    )
    tecnico_encargado = models.ForeignKey(
        'auth.User', on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='ingresos_como_tecnico',
        limit_choices_to={'is_active': True},
        verbose_name='Técnico asignado al ingreso',
        help_text='Técnico responsable asignado cuando el equipo ingresa. '
                  'Este dato no define quién realizó la reparación.',
    )
    fecha_ingreso = models.DateField(
        verbose_name='Fecha de Ingreso',
    )

    # ── Cliente ──────────────────────────────────────────
    cliente = models.ForeignKey(
        Cliente, on_delete=models.PROTECT,
        related_name='ingresos',
        verbose_name='Cliente',
    )

    # ── Detalles del equipo ──────────────────────────────
    tipo_equipo = models.CharField(
        max_length=20, choices=TIPOS_EQUIPO,
        verbose_name='Tipo de equipo',
    )
    tipo_equipo_otro = models.CharField(
        max_length=100, blank=True,
        verbose_name='Tipo de equipo (especificar)',
        help_text='Si seleccionaste "Otros equipos", indica cuál.'
    )
    marca = models.CharField(
        max_length=100,
        verbose_name='Marca',
    )
    modelo_serie = models.CharField(
        max_length=200,
        verbose_name='Modelo',
    )
    serie = models.CharField(
        max_length=200, blank=True,
        verbose_name='Serie',
    )
    accesorios_entregados = models.TextField(
        blank=True,
        verbose_name='Accesorios entregados',
        help_text='Cargador, cable, funda, etc.'
    )

    # ── Problema y reporte ───────────────────────────────
    problema_reportado = models.TextField(
        verbose_name='Problema reportado',
        help_text='Lo que indica el cliente al recibir el equipo.'
    )
    firma_cliente = models.BooleanField(
        default=False,
        verbose_name='Firma del cliente',
        help_text='Indica si el cliente firmó digitalmente la solicitud de ingreso.',
    )
    firma_cliente_imagen = models.TextField(
        blank=True,
        verbose_name='Imagen de firma del cliente',
        help_text='Firma digital capturada en formato PNG/base64.',
    )
    reporte_tecnico = models.TextField(
        blank=True,
        verbose_name='Reporte del técnico — detallar lo que se le realizó al equipo',
    )
    reporte_por = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='reportes_redactados',
        verbose_name='Reporte hecho por',
        help_text='Técnico que escribió o actualizó el reporte por última vez '
                  '(p. ej. desde el celular al escanear el QR).',
    )
    reporte_actualizado = models.DateTimeField(
        null=True, blank=True,
        verbose_name='Reporte actualizado el',
        help_text='Fecha y hora de la última edición del reporte del técnico.',
    )
    valor_pendiente_reporte = models.TextField(
        blank=True,
        verbose_name='Reporte de valor acordado pendiente',
        help_text='Motivo indicado por el técnico cuando el valor acordado aún está pendiente.',
    )
    valor_pendiente_reporte_por = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='reportes_valor_pendiente',
        verbose_name='Reporte de valor pendiente hecho por',
    )
    valor_pendiente_reporte_actualizado = models.DateTimeField(
        null=True, blank=True,
        verbose_name='Reporte de valor pendiente actualizado el',
    )

    # ── Diagnóstico ──────────────────────────────────────
    diagnostico_inmediato = models.CharField(
        max_length=2, choices=DIAGNOSTICO_INMEDIATO, default='no',
        verbose_name='Diagnóstico inmediato',
    )
    valor_diagnostico = models.DecimalField(
        max_digits=10, decimal_places=2,
        default=Decimal('0.00'),
        verbose_name='Valor del diagnóstico (USD)',
    )

    # ── Valores ──────────────────────────────────────────
    valor_acordado = models.DecimalField(
        max_digits=10, decimal_places=2,
        null=True, blank=True,
        verbose_name='Valor acordado (USD)',
        help_text='Costo total acordado de la reparación. Déjelo vacío si aún no se cotiza.'
    )

    # ── Datos de compra interna (solo cuando el estado es Equipo a comprar) ──
    COMPRA_METODOS_PAGO = [
        ('efectivo', 'Efectivo'),
        ('transferencia', 'Transferencia bancaria'),
        ('tarjeta', 'Tarjeta de crédito / Débito'),
        ('mixto', 'Pago mixto (2 métodos)'),
    ]
    COMPRA_BANCOS = [
        ('pichincha', 'Banco Pichincha'),
        ('guayaquil', 'Banco Guayaquil'),
        ('produbanco', 'Produbanco'),
        ('pacifico', 'Banco Pacífico'),
        ('interbancaria', 'Interbancaria'),
        ('otro', 'Otro banco'),
    ]
    COMPRA_TARJETAS_APPS = [
        ('payphone', 'Payphone'),
        ('deuna', 'Deuna'),
    ]
    compra_metodo_pago = models.CharField(
        max_length=20, choices=COMPRA_METODOS_PAGO, default='efectivo',
        verbose_name='Método de pago de compra',
    )
    compra_banco = models.CharField(
        max_length=20, choices=COMPRA_BANCOS, blank=True,
        verbose_name='Banco de compra',
    )
    compra_banco_otro = models.CharField(
        max_length=100, blank=True, verbose_name='Banco de compra (otro)',
    )
    compra_tarjeta_app = models.CharField(
        max_length=20, choices=COMPRA_TARJETAS_APPS, blank=True,
        verbose_name='Tarjeta / App de compra',
    )
    compra_comprobante_url = models.URLField(
        blank=True, verbose_name='Comprobante de compra',
    )
    compra_monto_1 = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        verbose_name='Monto de compra 1',
    )
    compra_metodo_1 = models.CharField(
        max_length=20, choices=COMPRA_METODOS_PAGO, blank=True,
        verbose_name='Método de compra 1',
    )
    compra_banco_1 = models.CharField(
        max_length=20, choices=COMPRA_BANCOS, blank=True,
        verbose_name='Banco de compra 1',
    )
    compra_banco_otro_1 = models.CharField(
        max_length=100, blank=True, verbose_name='Banco de compra 1 (otro)',
    )
    compra_tarjeta_app_1 = models.CharField(
        max_length=20, choices=COMPRA_TARJETAS_APPS, blank=True,
        verbose_name='Tarjeta / App de compra 1',
    )
    compra_monto_2 = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        verbose_name='Monto de compra 2',
    )
    compra_metodo_2 = models.CharField(
        max_length=20, choices=COMPRA_METODOS_PAGO, blank=True,
        verbose_name='Método de compra 2',
    )
    compra_banco_2 = models.CharField(
        max_length=20, choices=COMPRA_BANCOS, blank=True,
        verbose_name='Banco de compra 2',
    )
    compra_banco_otro_2 = models.CharField(
        max_length=100, blank=True, verbose_name='Banco de compra 2 (otro)',
    )
    compra_tarjeta_app_2 = models.CharField(
        max_length=20, choices=COMPRA_TARJETAS_APPS, blank=True,
        verbose_name='Tarjeta / App de compra 2',
    )
    abono_anticipo = models.DecimalField(
        max_digits=10, decimal_places=2,
        default=Decimal('0.00'),
        verbose_name='Abono / Anticipo (USD)',
        help_text='Pago inicial. Se complementa con abonos posteriores en el módulo Pagos.'
    )

    METODOS_PAGO = [
        ('efectivo', 'Efectivo'),
        ('transferencia', 'Transferencia bancaria'),
        ('tarjeta', 'Tarjeta de crédito / Débito'),
        ('mixto', 'Pago Mixto'),
    ]
    BANCOS = [
        ('pichincha', 'Banco Pichincha'),
        ('guayaquil', 'Banco Guayaquil'),
        ('produbanco', 'Produbanco'),
        ('pacifico', 'Banco Pacífico'),
        ('interbancaria', 'Interbancaria'),
        ('otro', 'Otro banco'),
    ]
    TARJETAS_APPS = [
        ('payphone', 'Payphone'),
        ('deuna', 'Deuna'),
    ]
    FACTURA_OPCIONES = [
        ('no', 'No'),
        ('si', 'Sí'),
    ]

    # ── Métodos de Pago Inicial (Anticipo / Diagnóstico) ──
    anticipo_metodo = models.CharField(
        max_length=20, choices=METODOS_PAGO, default='efectivo',
        verbose_name='Método de pago (inicial)',
    )
    anticipo_banco = models.CharField(
        max_length=20, choices=BANCOS, blank=True,
        verbose_name='Banco',
    )
    anticipo_banco_otro = models.CharField(
        max_length=100, blank=True,
        verbose_name='Banco (otro)',
        help_text='Completar solo si elegiste "Otro banco".',
    )
    anticipo_tarjeta_app = models.CharField(
        max_length=20, choices=TARJETAS_APPS, blank=True,
        verbose_name='Tarjeta / App',
        help_text='Solo cuando el método es Tarjeta o Payphone.',
    )
    anticipo_comprobante_url = models.URLField(
        blank=True,
        verbose_name='Link del comprobante',
        help_text='URL de la imagen/pdf del comprobante de pago inicial.',
    )

    # ── Método de Pago del Diagnóstico ───────────────────
    diagnostico_metodo = models.CharField(
        max_length=20, choices=METODOS_PAGO, default='efectivo',
        verbose_name='Método de pago del diagnóstico',
    )
    diagnostico_banco = models.CharField(
        max_length=20, choices=BANCOS, blank=True,
        verbose_name='Banco del diagnóstico',
    )
    diagnostico_banco_otro = models.CharField(
        max_length=100, blank=True,
        verbose_name='Banco del diagnóstico (otro)',
        help_text='Completar solo si elegiste "Otro banco".',
    )
    diagnostico_tarjeta_app = models.CharField(
        max_length=20, choices=TARJETAS_APPS, blank=True,
        verbose_name='Tarjeta / App del diagnóstico',
        help_text='Solo cuando el método es Tarjeta o Payphone.',
    )
    diagnostico_comprobante_url = models.URLField(
        blank=True,
        verbose_name='Link del comprobante del diagnóstico',
        help_text='URL de la imagen/pdf del comprobante de pago del diagnóstico.',
    )
    diagnostico_monto_1 = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        verbose_name='Monto diagnóstico 1'
    )
    diagnostico_metodo_1 = models.CharField(
        max_length=20, choices=METODOS_PAGO, blank=True,
        verbose_name='Método diagnóstico 1'
    )
    diagnostico_banco_1 = models.CharField(
        max_length=20, choices=BANCOS, blank=True,
        verbose_name='Banco diagnóstico 1'
    )
    diagnostico_monto_2 = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        verbose_name='Monto diagnóstico 2'
    )
    diagnostico_metodo_2 = models.CharField(
        max_length=20, choices=METODOS_PAGO, blank=True,
        verbose_name='Método diagnóstico 2'
    )
    diagnostico_banco_2 = models.CharField(
        max_length=20, choices=BANCOS, blank=True,
        verbose_name='Banco diagnóstico 2'
    )

    # Campos para Pago Mixto (cuando anticipo_metodo == 'mixto')
    anticipo_monto_1 = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        verbose_name='Monto 1'
    )
    anticipo_metodo_1 = models.CharField(
        max_length=20, choices=METODOS_PAGO, blank=True,
        verbose_name='Método de pago 1'
    )
    anticipo_banco_1 = models.CharField(
        max_length=20, choices=BANCOS, blank=True,
        verbose_name='Banco 1'
    )

    anticipo_monto_2 = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        verbose_name='Monto 2'
    )
    anticipo_metodo_2 = models.CharField(
        max_length=20, choices=METODOS_PAGO, blank=True,
        verbose_name='Método de pago 2'
    )
    anticipo_banco_2 = models.CharField(
        max_length=20, choices=BANCOS, blank=True,
        verbose_name='Banco 2'
    )

    # ── Factura asociada al pago inicial / ventas de producto ──
    factura_realizada = models.CharField(
        max_length=2, choices=FACTURA_OPCIONES, default='no',
        verbose_name='¿Factura realizada?',
    )
    factura_nombres = models.CharField(
        max_length=100, blank=True, verbose_name='Nombres (factura)',
    )
    factura_cedula = models.CharField(
        max_length=20, blank=True, verbose_name='Cédula / RUC (factura)',
    )
    factura_correo = models.EmailField(
        blank=True, verbose_name='Correo electrónico (factura)',
    )

    # ── Estado del flujo ─────────────────────────────────
    ESTADO_FLUJO = [
        ('ingresado', 'Ingresado / En diagnóstico'),
        ('en_reparacion', 'En reparación'),
        ('entregado', 'Entregado al cliente'),
        ('garantia', 'Garantía'),
        ('cortesia', 'Cortesía'),
        ('donado', 'Donado'),
        ('equipo_a_comprar', 'Equipo a comprar'),
    ]
    estado = models.CharField(
        max_length=30, choices=ESTADO_FLUJO, default='ingresado',
        verbose_name='Estado del equipo',
    )
    equipo_garantia = models.ForeignKey(
        'self', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='garantias_aplicadas',
        verbose_name='Aplica garantía a equipo',
    )
    equipo_garantia_manual = models.CharField(
        max_length=200, blank=True, null=True,
        verbose_name='Equipo de Garantía (Manual)'
    )
    motivo_garantia = models.TextField(
        blank=True,
        verbose_name='Motivo de la garantía',
    )
    subestado_reparacion = models.CharField(
        max_length=20, choices=SUBESTADO_EN_REPARACION, blank=True, default='',
        verbose_name='Detalle (En reparación)',
        help_text='Solo aplica cuando el estado es "En reparación".'
    )
    subestado_entregado = models.CharField(
        max_length=20, choices=SUBESTADO_ENTREGADO, blank=True, default='',
        verbose_name='Detalle (Entregado)',
        help_text='Solo aplica cuando el estado es "Entregado al cliente".'
    )

    # ── Auditoría ────────────────────────────────────────
    registrado_por = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='ingresos_registrados',
        verbose_name='Registrado por',
    )
    diagnostico_silenciado = models.BooleanField(
        default=False,
        verbose_name='🔕 Alerta de diagnóstico silenciada',
        help_text='Si está activo, este equipo no aparecerá en la alerta de '
                  '"equipos pendientes de diagnóstico" del dashboard. Se '
                  'reactiva automáticamente cuando el estado cambia.',
    )
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Ingreso de equipo'
        verbose_name_plural = 'Ingresos de equipos'
        ordering = ['-numero_equipo']
        constraints = [
            models.UniqueConstraint(
                fields=['sede', 'numero_equipo'],
                name='unique_numero_por_sede',
            ),
        ]

    # ── Helpers ──────────────────────────────────────────

    @classmethod
    def siguiente_numero_equipo(cls, sede):
        """
        Retorna el siguiente número disponible para la sede dada.
        Para Guayaquil y Quito empieza en 1000.
        Para Ventas empieza en 1.
        """
        ultimo = cls.objects.filter(sede=sede).order_by('-numero_equipo').first()
        if ultimo:
            return ultimo.numero_equipo + 1
        return 1 if sede == 'ventas' else 1000

    @property
    def codigo_equipo(self):
        """Retorna el código completo, p.ej. G1024 o U1025 o P001"""
        if self.sede == 'ventas':
            return f"P{self.numero_equipo:03d}"
        prefijo = SEDE_PREFIJOS.get(self.sede, '?')
        return f"{prefijo}{self.numero_equipo}"

    @property
    def sede_display_corto(self):
        """Etiqueta visual corta de la sede para badges/cabeceras."""
        if self.sede == 'guayaquil':
            return 'Guayaquil'
        if self.sede == 'quito':
            return 'Quito'
        return self.get_sede_display()

    def _salida_relacionada(self):
        try:
            return self.salida
        except AttributeError:
            return None

    @property
    def pendiente_retiro_visual(self):
        salida = self._salida_relacionada()
        if salida is not None:
            return salida.estado_reparacion == 'pendiente_retiro'
        return self.estado == 'entregado' and self.subestado_entregado == 'pendiente_retiro'

    @property
    def estado_visual_key(self):
        if self.pendiente_retiro_visual:
            return 'pendiente_retiro'
        salida = self._salida_relacionada()
        if salida is not None:
            if salida.estado_reparacion == 'no_reparable':
                return 'no_reparable'
            if salida.estado_reparacion == 'cliente_no_acepta':
                return 'cliente_no_acepta'
            if salida.estado_reparacion == 'revision':
                return 'revision'
        if self.estado == 'entregado':
            if self.subestado_entregado == 'sin_solucion':
                return 'no_reparable'
            if self.subestado_entregado == 'no_quiso_reparar':
                return 'cliente_no_acepta'
        return self.estado

    @property
    def estado_visual_display(self):
        if self.pendiente_retiro_visual:
            return 'Pendiente de retiro'
        salida = self._salida_relacionada()
        if salida is not None and salida.estado_reparacion == 'revision':
            return 'Revisión'
        return self.get_estado_display()

    @property
    def compra_pago_mixto_partes(self):
        """Desglose de los dos métodos usados en una compra mixta."""
        if self.compra_metodo_pago != 'mixto':
            return []
        metodos = dict(self.COMPRA_METODOS_PAGO)
        bancos = dict(self.COMPRA_BANCOS)
        tarjetas = dict(self.COMPRA_TARJETAS_APPS)
        partes = []
        for numero, monto, metodo, banco, banco_otro, tarjeta_app in (
            (
                1, self.compra_monto_1, self.compra_metodo_1,
                self.compra_banco_1, self.compra_banco_otro_1,
                self.compra_tarjeta_app_1,
            ),
            (
                2, self.compra_monto_2, self.compra_metodo_2,
                self.compra_banco_2, self.compra_banco_otro_2,
                self.compra_tarjeta_app_2,
            ),
        ):
            if not monto and not metodo:
                continue
            detalle = metodos.get(metodo, metodo or '—')
            if metodo == 'transferencia' and banco:
                detalle = f'{detalle} ({banco_otro if banco == "otro" and banco_otro else bancos.get(banco, banco)})'
            elif metodo == 'tarjeta' and tarjeta_app:
                detalle = f'{detalle} ({tarjetas.get(tarjeta_app, tarjeta_app)})'
            partes.append({'monto': _q2(monto), 'detalle': detalle, 'numero': numero})
        return partes

    @property
    def subestado_visual_display(self):
        if self.pendiente_retiro_visual:
            return 'Reparado - pendiente de retiro'
        salida = self._salida_relacionada()
        if salida is not None and salida.estado_reparacion == 'revision':
            return 'Revisión pendiente de pago'
        if self.estado == 'en_reparacion' and self.subestado_reparacion:
            return self.get_subestado_reparacion_display()
        if self.estado == 'entregado' and self.subestado_entregado:
            return self.get_subestado_entregado_display()
        return ''

    @property
    def tipo_equipo_display(self):
        if self.tipo_equipo == 'otro' and self.tipo_equipo_otro:
            return self.tipo_equipo_otro
        return self.get_tipo_equipo_display()

    @property
    def modelo_serie_detalle(self):
        if self.serie:
            return f'{self.modelo_serie} — Serie: {self.serie}'
        return self.modelo_serie

    @property
    def tecnico_encargado_nombre(self):
        """Nombre del técnico encargado para mostrar en plantillas e impresiones."""
        u = self.tecnico_encargado
        if not u:
            return ''
        return (f'{u.first_name} {u.last_name}'.strip()) or u.username

    @property
    def reporte_por_nombre(self):
        """Nombre de quién escribió el reporte del técnico (para mostrar)."""
        u = self.reporte_por
        if not u:
            return ''
        return (f'{u.first_name} {u.last_name}'.strip()) or u.username

    @property
    def valor_pendiente_reporte_por_nombre(self):
        """Nombre de quién reportó por qué el valor acordado está pendiente."""
        u = self.valor_pendiente_reporte_por
        if not u:
            return ''
        return (f'{u.first_name} {u.last_name}'.strip()) or u.username

    @property
    def total_abonado(self):
        """Suma del anticipo + abonos parciales + pago final de salida."""
        from django.db.models import Sum
        suma_abonos = self.abonos.aggregate(s=Sum('monto'))['s'] or Decimal('0.00')
        total = (self.abono_anticipo or Decimal('0.00')) + suma_abonos
        if hasattr(self, 'salida') and self.salida and self.salida.valor_final_cobrado:
            total += self.salida.valor_final_cobrado
        return _q2(total)

    @property
    def anticipo_mixto_partes(self):
        """Desglose legible de las dos partes del pago inicial mixto."""
        if self.anticipo_metodo != 'mixto':
            return []

        bancos = dict(self.BANCOS)
        metodos = dict(self.METODOS_PAGO)

        def armar_parte(numero, monto, metodo, banco):
            if not monto and not metodo:
                return None

            metodo_texto = metodos.get(metodo, metodo or '—')
            banco_texto = ''
            detalle = metodo_texto

            if metodo == 'transferencia':
                banco_texto = bancos.get(banco, banco or '')
                detalle = f'{metodo_texto} - {banco_texto}' if banco_texto else metodo_texto

            return {
                'numero': numero,
                'monto': _q2(monto or Decimal('0.00')),
                'metodo': metodo_texto,
                'banco': banco_texto,
                'detalle': detalle,
            }

        partes = [
            armar_parte(1, self.anticipo_monto_1, self.anticipo_metodo_1, self.anticipo_banco_1),
            armar_parte(2, self.anticipo_monto_2, self.anticipo_metodo_2, self.anticipo_banco_2),
        ]
        return [p for p in partes if p]

    @property
    def diagnostico_mixto_partes(self):
        """Desglose legible de las dos partes del pago del diagnóstico."""
        if self.diagnostico_metodo != 'mixto':
            return []

        bancos = dict(self.BANCOS)
        metodos = dict(self.METODOS_PAGO)

        def armar_parte(numero, monto, metodo, banco):
            if not monto and not metodo:
                return None

            metodo_texto = metodos.get(metodo, metodo or '—')
            banco_texto = ''
            detalle = metodo_texto

            if metodo == 'transferencia':
                banco_texto = bancos.get(banco, banco or '')
                detalle = f'{metodo_texto} - {banco_texto}' if banco_texto else metodo_texto

            return {
                'numero': numero,
                'monto': _q2(monto or Decimal('0.00')),
                'metodo': metodo_texto,
                'banco': banco_texto,
                'detalle': detalle,
            }

        partes = [
            armar_parte(1, self.diagnostico_monto_1, self.diagnostico_metodo_1, self.diagnostico_banco_1),
            armar_parte(2, self.diagnostico_monto_2, self.diagnostico_metodo_2, self.diagnostico_banco_2),
        ]
        return [p for p in partes if p]

    @property
    def resumen_metodos_pago(self):
        """Devuelve un string con los métodos de pago usados en los abonos y cierre detallados."""
        if self.estado == 'cortesia':
            return 'Cortesía / sin cobro'

        metodos = []

        if self.diagnostico_inmediato == 'si' and self.valor_diagnostico and self.valor_diagnostico > 0:
            m = self.get_diagnostico_metodo_display()
            if m:
                if self.diagnostico_metodo == 'mixto':
                    partes = ', '.join(
                        f"${parte['monto']} {parte['detalle']}"
                        for parte in self.diagnostico_mixto_partes
                    )
                    metodos.append(f"Diagnóstico: Pago Mixto ({partes})" if partes else "Diagnóstico: Pago Mixto")
                else:
                    if self.diagnostico_metodo == 'transferencia':
                        banco = self.diagnostico_banco_otro if self.diagnostico_banco == 'otro' else self.get_diagnostico_banco_display()
                        if banco:
                            m = f"{m} ({banco})"
                    elif self.diagnostico_metodo == 'tarjeta':
                        if self.diagnostico_tarjeta_app:
                            m = f"{m} ({self.get_diagnostico_tarjeta_app_display()})"
                    metodos.append(f"Diagnóstico: {m}")
        
        # 1. Pago inicial (anticipo)
        if self.abono_anticipo and self.abono_anticipo > 0:
            m = self.get_anticipo_metodo_display()
            if m:
                if self.anticipo_metodo == 'mixto':
                    partes = ', '.join(
                        f"${parte['monto']} {parte['detalle']}"
                        for parte in self.anticipo_mixto_partes
                    )
                    metodos.append(f"Pago Mixto ({partes})" if partes else "Pago Mixto")
                else:
                    if self.anticipo_metodo == 'transferencia':
                        banco = self.anticipo_banco_otro if self.anticipo_banco == 'otro' else self.get_anticipo_banco_display()
                        if banco: m = f"{m} ({banco})"
                    elif self.anticipo_metodo == 'tarjeta':
                        if self.anticipo_tarjeta_app: m = f"{m} ({self.get_anticipo_tarjeta_app_display()})"
                    metodos.append(m)

        for a in self.abonos.all():
            m = a.get_metodo_display()
            if not m: continue
            if a.metodo == 'transferencia':
                banco = a.banco_otro if a.banco == 'otro' else a.get_banco_display()
                if banco: m = f"{m} ({banco})"
            elif a.metodo == 'tarjeta':
                if a.tarjeta_app: m = f"{m} ({a.tarjeta_app})"
            metodos.append(m)
            
        if hasattr(self, 'salida') and self.salida and getattr(self.salida, 'metodo_pago_final', None):
            if self.salida.valor_final_cobrado and self.salida.valor_final_cobrado > 0:
                s = self.salida
                m = s.get_metodo_pago_final_display()
                if s.metodo_pago_final == 'transferencia':
                    banco = s.banco_otro if s.banco == 'otro' else s.get_banco_display()
                    if banco: m = f"{m} ({banco})"
                elif s.metodo_pago_final == 'tarjeta':
                    if s.tarjeta_app: m = f"{m} ({s.tarjeta_app})"
                elif s.metodo_pago_final == 'mixto':
                    partes = ', '.join(
                        f"${parte['monto']} {parte['detalle']}"
                        for parte in s.pago_mixto_partes
                    )
                    m = f"{m} ({partes})" if partes else m
                metodos.append(m)
                
        # Evitar duplicados manteniendo orden visual
        vistos = set()
        unicos = []
        for m in metodos:
            if m not in vistos:
                vistos.add(m)
                unicos.append(m)
        return " / ".join(unicos) if unicos else ""

    @property
    def reparacion_cancelada(self):
        """
        ¿La reparación fue cancelada o cerrada por revisión?
        En estos estados el valor acordado original ya no aplica como deuda.
        """
        if hasattr(self, 'salida') and self.salida:
            return self.salida.estado_reparacion in ('cliente_no_acepta', 'no_reparable', 'revision')
        return False

    @property
    def valor_efectivo_a_cobrar(self):
        """
        Valor que realmente se le cobra al cliente por la REPARACIÓN / SALIDA:
        - Si salió por Revisión: el valor acordado propio de esa salida.
        - Si la reparación fue cancelada: solo el valor del diagnóstico (si no lo pagó al inicio).
        - Si no: el valor acordado completo.
        """
        if self.estado == 'cortesia':
            return Decimal('0.00')

        salida = self.salida if hasattr(self, 'salida') else None
        if salida and salida.estado_reparacion == 'revision':
            return _q2(salida.valor_acordado_revision or Decimal('0.00'))

        if self.reparacion_cancelada:
            if salida:
                revision_pendiente = (
                    salida.notificaciones_asesora
                    .filter(tipo='revision_pendiente')
                    .order_by('-creado')
                    .first()
                )
                if revision_pendiente:
                    return _q2(revision_pendiente.valor_acordado)
            if self.diagnostico_inmediato == 'si':
                # Si el diagnóstico fue inmediato, ya se cobró como valor adicional, no debe nada en la salida.
                return Decimal('0.00')
            # Si se le cobró un valor final al salir, ese es el costo real de revisión
            if salida and salida.valor_final_cobrado is not None:
                return _q2(salida.valor_final_cobrado)
            
            # NUEVO: Si no se pudo reparar, no se cobra diagnóstico (es gratuito).
            if salida and salida.estado_reparacion == 'no_reparable':
                return Decimal('0.00')

            return _q2(self.valor_diagnostico or Decimal('0.00'))
        valor_reparacion = self.valor_acordado or Decimal('0.00')
        if salida and salida.tiene_valor_acordado_adicional:
            valor_reparacion += salida.valor_acordado_adicional
        return _q2(valor_reparacion)

    @property
    def diferencia(self):
        """
        Saldo pendiente.
        Si el cliente no quiso reparar o no se pudo reparar, el saldo se calcula
        sobre el valor del diagnóstico, no sobre el valor acordado original.
        """
        return _q2(self.valor_efectivo_a_cobrar - self.total_abonado)

    @property
    def bodegaje_pendiente(self):
        """
        Bodegaje acumulado del equipo que aún NO tiene una decisión tomada.
        Devuelve Decimal('0.00') si no aplica o si ya se decidió (cobrar/perdonar).

        Se calcula al vuelo: día a día crece mientras el cliente no venga.
        Una vez que se congela (bodegaje_dias_congelado is not None), ya se
        tomó la decisión y deja de mostrarse como pendiente — aunque el
        cliente todavía no haya retirado físicamente, o ya lo haya hecho.
        """
        if not self.tiene_salida:
            return Decimal('0.00')
        salida = self.salida
        # Si ya se decidió (cobrar o perdonar), el bodegaje está cerrado.
        if salida.bodegaje_dias_congelado is not None:
            return Decimal('0.00')
        # Si el cliente ya retiró pero NO se congeló el bodegaje, todavía
        # queda pendiente decidir qué hacer con él (cobrarlo o perdonarlo),
        # así que lo seguimos mostrando como pendiente.
        bod = salida.calcular_bodegaje()
        if not bod['aplica']:
            return Decimal('0.00')
        return _q2(bod['monto'])

    @property
    def bodegaje_dias_pendiente(self):
        """
        Días de bodegaje cobrable acumulados (al vuelo). Igual lógica que
        `bodegaje_pendiente` pero devuelve los días en lugar del monto.
        Útil para mostrar '$X (N días)' en los diálogos de retiro.
        """
        if not self.tiene_salida:
            return 0
        salida = self.salida
        if salida.bodegaje_dias_congelado is not None:
            return 0
        bod = salida.calcular_bodegaje()
        if not bod['aplica']:
            return 0
        return bod['dias']

    @property
    def diferencia_con_bodegaje(self):
        """
        Saldo del cliente incluyendo el bodegaje acumulado.
        Esto es lo que se le cobraría hoy si decide retirar el equipo
        y se aplica el bodegaje. Útil en el listado de Pagos.
        """
        return _q2(self.diferencia + self.bodegaje_pendiente)

    @property
    def estado_pago(self):
        if self.estado == 'cortesia':
            return 'Cortesía'

        # Si aún no hay valor acordado (es nulo) y la reparación no fue cancelada
        if self.valor_acordado is None and not self.reparacion_cancelada:
            return 'Pendiente'

        base = self.valor_efectivo_a_cobrar
        if base <= 0:
            return 'Pagado'
        if self.diferencia <= 0:
            return 'Pagado'
        if self.total_abonado > 0:
            return 'Parcial'
        return 'Pendiente'

    @property
    def tiene_salida(self):
        return hasattr(self, 'salida')

    @property
    def retirado_por_cliente(self):
        salida = self._salida_relacionada()
        if salida is None:
            return False
        return salida.cliente_ya_retiro or salida.estado_reparacion == 'retirado'

    @property
    def equipo_garantia_referencia(self):
        if self.equipo_garantia_id and self.equipo_garantia:
            return self.equipo_garantia.codigo_equipo
        return (self.equipo_garantia_manual or '').strip()

    def save(self, *args, **kwargs):
        if not self.numero_equipo:
            self.numero_equipo = IngresoEquipo.siguiente_numero_equipo(self.sede)
        if self.estado == 'cortesia':
            self.valor_acordado = Decimal('0.00')
            self.diagnostico_inmediato = 'no'
            self.valor_diagnostico = Decimal('0.00')
            self.abono_anticipo = Decimal('0.00')

            update_fields = kwargs.get('update_fields')
            if update_fields is not None:
                kwargs['update_fields'] = set(update_fields) | {
                    'valor_acordado',
                    'diagnostico_inmediato',
                    'valor_diagnostico',
                    'abono_anticipo',
                }
        # Si el equipo ya no está en estado "ingresado", reactivamos la alerta
        # (el silenciado solo tiene sentido mientras el equipo está pendiente).
        if self.estado != 'ingresado' and self.diagnostico_silenciado:
            self.diagnostico_silenciado = False
        super().save(*args, **kwargs)

    def __str__(self):
        return f'Equipo {self.codigo_equipo} — {self.cliente.nombres} ({self.tipo_equipo_display})'


# ─────────────────────────────────────────────────────────
# Productos de inventario incluidos en una venta
# ─────────────────────────────────────────────────────────

class VentaInventarioItem(models.Model):
    """Relación entre una venta y las unidades descontadas del inventario."""

    venta = models.ForeignKey(
        IngresoEquipo,
        on_delete=models.CASCADE,
        related_name='productos_inventario',
        verbose_name='Venta',
    )
    inventario_item = models.ForeignKey(
        InventarioItem,
        on_delete=models.PROTECT,
        related_name='ventas_asociadas',
        verbose_name='Producto de inventario',
    )
    cantidad = models.PositiveIntegerField(verbose_name='Cantidad vendida')
    observacion = models.TextField(
        blank=True,
        verbose_name='Observación',
        help_text='Nota opcional de este producto dentro de la venta.',
    )
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Producto de inventario vendido'
        verbose_name_plural = 'Productos de inventario vendidos'
        ordering = ['creado', 'pk']
        constraints = [
            models.UniqueConstraint(
                fields=['venta', 'inventario_item'],
                name='uniq_producto_inventario_por_venta',
            ),
        ]

    def __str__(self):
        return f'{self.venta.codigo_equipo} — {self.inventario_item.producto} x {self.cantidad}'


# ─────────────────────────────────────────────────────────
# Abonos parciales (pagos por reparación)
# ─────────────────────────────────────────────────────────

class Abono(models.Model):
    """
    Cada pago parcial que hace el cliente para su reparación.
    El primer pago suele estar en `IngresoEquipo.abono_anticipo`;
    luego se registran aquí los pagos posteriores.
    """

    METODOS_PAGO = [
        ('efectivo', 'Efectivo'),
        ('transferencia', 'Transferencia bancaria'),
        ('tarjeta', 'Tarjeta de crédito / Débito'),
        ('mixto', 'Pago Mixto'),
    ]

    BANCOS = [
        ('pichincha', 'Banco Pichincha'),
        ('guayaquil', 'Banco Guayaquil'),
        ('produbanco', 'Produbanco'),
        ('pacifico', 'Banco Pacífico'),
        ('interbancaria', 'Interbancaria'),
        ('otro', 'Otro banco'),
    ]

    TARJETAS_APPS = [
        ('payphone', 'Payphone'),
        ('deuna', 'Deuna'),
    ]

    FACTURA_OPCIONES = [
        ('no', 'No'),
        ('si', 'Sí'),
    ]

    BODEGAJE_DECISION = [
        ('na', 'No aplica (sin bodegaje pendiente)'),
        ('si', 'Sí — aplicar bodegaje (sumar al monto)'),
        ('no', 'No — perdonar bodegaje'),
    ]

    ingreso = models.ForeignKey(
        IngresoEquipo, on_delete=models.CASCADE,
        related_name='abonos',
        verbose_name='Equipo / Ingreso',
    )
    fecha = models.DateField(
        verbose_name='Fecha del abono',
    )
    monto = models.DecimalField(
        max_digits=10, decimal_places=2,
        verbose_name='Monto (USD)',
    )
    metodo = models.CharField(
        max_length=20, choices=METODOS_PAGO, default='efectivo',
        verbose_name='Método de pago',
    )
    banco = models.CharField(
        max_length=20, choices=BANCOS, blank=True,
        verbose_name='Banco',
    )
    banco_otro = models.CharField(
        max_length=100, blank=True,
        verbose_name='Banco (otro)',
        help_text='Completar solo si elegiste "Otro banco".',
    )
    tarjeta_app = models.CharField(
        max_length=20, choices=TARJETAS_APPS, blank=True,
        verbose_name='Tarjeta / App',
        help_text='Solo cuando el método es Tarjeta o Payphone.',
    )
    comprobante_url = models.URLField(
        blank=True,
        verbose_name='Link del comprobante',
        help_text='URL del comprobante de transferencia (Google Drive, WhatsApp, etc.).',
    )
    numero_recibo = models.CharField(
        max_length=30, unique=True, blank=True,
        verbose_name='Número de recibo',
        help_text='Si se deja vacío, se genera automáticamente (REC-0001, REC-0002…).'
    )
    observaciones = models.TextField(blank=True)
    # ── Factura ──────────────────────────────────────────
    factura_realizada = models.CharField(
        max_length=2, choices=FACTURA_OPCIONES, default='no',
        verbose_name='¿Factura realizada?',
    )
    factura_nombres = models.CharField(
        max_length=100, blank=True, verbose_name='Nombres (factura)',
    )
    factura_apellidos = models.CharField(
        max_length=100, blank=True, verbose_name='Apellidos (factura)',
    )
    factura_cedula = models.CharField(
        max_length=20, blank=True, verbose_name='Cédula / RUC (factura)',
    )
    factura_correo = models.EmailField(
        blank=True, verbose_name='Correo electrónico (factura)',
    )

    # ── Decisión sobre el bodegaje al momento del abono ──
    # Si el equipo tiene bodegaje pendiente, en cada abono se puede:
    #   - Aplicar (cobrar): el cliente paga también el bodegaje.
    #   - Perdonar: la empresa decide no cobrarlo y se cierra a 0.
    bodegaje_decision = models.CharField(
        max_length=2, choices=BODEGAJE_DECISION, default='na',
        verbose_name='Decisión de bodegaje',
        help_text='Si el equipo tenía bodegaje pendiente al momento del abono.',
    )
    bodegaje_monto_aplicado = models.DecimalField(
        max_digits=10, decimal_places=2,
        default=Decimal('0.00'),
        verbose_name='Monto de bodegaje aplicado (USD)',
        help_text='Monto del bodegaje incluido en este abono (si decisión = "si").',
    )

    registrado_por = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='abonos_registrados',
    )
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Abono'
        verbose_name_plural = 'Abonos'
        ordering = ['-fecha', '-creado']

    @staticmethod
    def generar_numero_recibo():
        """Genera el siguiente número de recibo correlativo: REC-0001, REC-0002…"""
        ultimo = Abono.objects.filter(
            numero_recibo__startswith='REC-'
        ).order_by('-numero_recibo').first()
        if ultimo and ultimo.numero_recibo[4:].isdigit():
            siguiente = int(ultimo.numero_recibo[4:]) + 1
        else:
            siguiente = 1
        return f'REC-{siguiente:04d}'

    def save(self, *args, **kwargs):
        if not self.numero_recibo:
            self.numero_recibo = Abono.generar_numero_recibo()
        super().save(*args, **kwargs)
        # Si en este abono se decidió aplicar o perdonar el bodegaje,
        # cerramos el bodegaje en la salida del equipo para que ya no
        # siga acumulando ni se vuelva a mostrar como pendiente.
        self._cerrar_bodegaje_si_corresponde()

    def _cerrar_bodegaje_si_corresponde(self):
        """
        Si la decisión sobre bodegaje fue tomada en este abono ('si' o 'no'),
        congela el bodegaje en la salida del equipo:
          - bodegaje_decision='si' → bodegaje marcado como cobrado (aplicado).
          - bodegaje_decision='no' → bodegaje perdonado (no cobrado, monto=0).
        En ambos casos el bodegaje deja de acumularse día a día.
        NO marca al equipo como "retirado": eso es una acción separada.
        """
        if self.bodegaje_decision not in ('si', 'no'):
            return
        ingreso = self.ingreso
        if not ingreso or not getattr(ingreso, 'salida', None):
            return
        salida = ingreso.salida

        if self.bodegaje_decision == 'si':
            # Cobrado: marcar como aplicado y registrar el monto cobrado.
            # Si el cliente AÚN no retiró, calculamos los días al vuelo.
            # Si YA retiró, conservamos los días que ya quedaron congelados
            # (no se recalculan) y solo sincronizamos el monto y el flag,
            # para que la lista de salidas muestre "cobrado" correctamente.
            if not salida.cliente_ya_retiro:
                salida.bodegaje_dias_congelado = salida.calcular_bodegaje().get('dias', 0)
            elif salida.bodegaje_dias_congelado is None:
                salida.bodegaje_dias_congelado = 0
            salida.bodegaje_monto_congelado = self.bodegaje_monto_aplicado or Decimal('0.00')
            salida.bodegaje_aplicado_al_pago = True
        else:
            # Perdonado: congelar a 0 días / 0 monto, no aplicado.
            salida.bodegaje_dias_congelado = 0
            salida.bodegaje_monto_congelado = Decimal('0.00')
            salida.bodegaje_aplicado_al_pago = False

        salida.save(update_fields=[
            'bodegaje_dias_congelado',
            'bodegaje_monto_congelado',
            'bodegaje_aplicado_al_pago',
            'actualizado',
        ])

    def __str__(self):
        return f'{self.numero_recibo} — ${self.monto} ({self.fecha})'


# ─────────────────────────────────────────────────────────
# Salida de equipo
# ─────────────────────────────────────────────────────────

class SalidaEquipo(models.Model):
    """
    Documento de salida del equipo cuando se entrega al cliente.

    El técnico NO necesita rellenar todo el formulario otra vez: la mayoría
    de la información ya está en el IngresoEquipo. Aquí solo se marca el
    estado final (retiro positivo, no reparable, etc.) y se completan los
    datos del cierre.
    """

    ESTADO_REPARACION = [
        ('pendiente_retiro', '⏳ Reparado — pendiente de retiro'),
        ('revision', '🔎 Revisión'),
        ('cliente_no_acepta', '🚫 Cliente no quiso reparar'),
        ('no_reparable', '❌ No se pudo reparar'),
        ('garantia', '🛡 Garantía finalizada'),
        ('garantia_fallos_adicionales', '🛡 Garantía finalizada + fallos adicionales'),
        ('cortesia', 'Equipo de cortesía finalizado'),
        ('retirado', '✅ Salió de la oficina'),
        ('chatarrerizacion', '♻️ Chatarrerización'),
    ]

    SI_NO = [
        ('si', 'Sí'),
        ('no', 'No'),
    ]

    METODOS_PAGO_FINAL = [
        ('efectivo', 'Efectivo'),
        ('transferencia', 'Transferencia bancaria'),
        ('tarjeta', 'Tarjeta de crédito/débito'),
        ('mixto', 'Pago mixto (2 métodos)'),
        ('cortesia', 'Cortesía / sin cobro'),
        ('sin_pago', 'Sin pago (no aplica)'),
    ]

    ingreso = models.OneToOneField(
        IngresoEquipo, on_delete=models.PROTECT,
        related_name='salida',
        verbose_name='Equipo finalizado',
    )

    # ── Fechas ───────────────────────────────────────────
    fecha_salida = models.DateField(
        verbose_name='Fecha de finalización',
    )

    # ── Estado del trabajo (LO MÁS IMPORTANTE) ───────────
    estado_reparacion = models.CharField(
        max_length=30, choices=ESTADO_REPARACION,
        verbose_name='Resultado final del equipo',
        help_text='¿Cómo termina este equipo? La opción más común es "Reparado — pendiente de retiro".'
    )

    # ── Técnico que REPARÓ el equipo (se declara en la salida) ───────────
    # Es el responsable real de la reparación: el técnico seleccionado en la
    # salida asume el resultado. Este técnico —NO el que hizo el
    # ingreso— es el que suma/resta puntos y sube de nivel según el resultado
    # (salida buena = suma, salida mala = resta). Es obligatorio en el
    # formulario; se deja nullable a nivel de BD solo para no romper salidas
    # antiguas y para la hoja móvil (donde se toma automáticamente al técnico
    # que la marca desde su celular).
    tecnico_reparo = models.ForeignKey(
        'auth.User', on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='salidas_como_tecnico',
        limit_choices_to={'is_active': True},
        verbose_name='Técnico que reparó',
        help_text='Técnico responsable de la reparación. Este dato define quién '
                  'recibe el resultado positivo o negativo de la finalización.',
    )

    # ── Observaciones (opcionales, casi siempre vacío en retiros normales)
    observaciones = models.TextField(
        blank=True,
        verbose_name='Observaciones del cierre',
        help_text='Solo si necesitas anotar algo sobre la entrega. '
                  'En retiros normales puedes dejarlo vacío.',
    )

    # ── Garantía y cobro final ───────────────────────────
    garantia_dias = models.PositiveIntegerField(
        default=0,
        verbose_name='Garantía (días)',
        help_text='Días de garantía sobre el trabajo realizado.'
    )
    valor_final_cobrado = models.DecimalField(
        max_digits=10, decimal_places=2,
        default=Decimal('0.00'),
        verbose_name='Valor cobrado al finalizar (USD)',
        help_text='Si ya está totalmente pagado, puedes dejar 0.'
    )
    valor_acordado_revision = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='Valor acordado por revisión (USD)',
        help_text='Solo aplica cuando el estado de salida es Revisión.',
    )
    aplica_valor_acordado_adicional = models.CharField(
        max_length=2,
        choices=SI_NO,
        default='no',
        verbose_name='¿Aplica un valor acordado adicional?',
        help_text='Solo aplica cuando el equipo queda reparado y pendiente de retiro.',
    )
    valor_acordado_adicional = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name='Valor acordado adicional (USD)',
        help_text='Valor adicional pendiente de pago acordado al finalizar la reparación.',
    )
    motivo_valor_acordado_adicional = models.TextField(
        blank=True,
        verbose_name='Motivo del valor acordado adicional',
        help_text='Explicación del motivo por el que se acordó el valor adicional.',
    )
    metodo_pago_final = models.CharField(
        max_length=20, choices=METODOS_PAGO_FINAL, default='efectivo',
        verbose_name='Método de pago del saldo final',
    )
    banco = models.CharField(
        max_length=20, choices=[
            ('pichincha', 'Banco Pichincha'),
            ('guayaquil', 'Banco Guayaquil'),
            ('produbanco', 'Produbanco'),
            ('pacifico', 'Banco Pacífico'),
            ('interbancaria', 'Interbancaria'),
            ('otro', 'Otro banco'),
        ], blank=True,
        verbose_name='Banco',
    )
    banco_otro = models.CharField(
        max_length=100, blank=True,
        verbose_name='Banco (otro)',
        help_text='Completar solo si elegiste "Otro banco".',
    )
    tarjeta_app = models.CharField(
        max_length=20, choices=[
            ('payphone', 'Payphone'),
            ('deuna', 'Deuna'),
        ], blank=True,
        verbose_name='Tarjeta / App',
        help_text='Solo cuando el método es Tarjeta o Payphone.',
    )
    comprobante_url = models.URLField(
        blank=True,
        verbose_name='Link del comprobante',
        help_text='URL del comprobante de transferencia (Google Drive, WhatsApp, etc.).',
    )
    numero_recibo = models.CharField(
        max_length=30, blank=True,
        verbose_name='Número de recibo',
        help_text='Si se deja vacío y hay un cobro, se genera automáticamente.'
    )

    # ── Pago mixto (aplica si metodo_pago_final es 'mixto') ─────────────
    monto_1 = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        verbose_name='Monto 1'
    )
    metodo_1 = models.CharField(
        max_length=20, choices=METODOS_PAGO_FINAL, blank=True,
        verbose_name='Método 1'
    )
    banco_1 = models.CharField(
        max_length=20, choices=[
            ('pichincha', 'Banco Pichincha'),
            ('guayaquil', 'Banco Guayaquil'),
            ('produbanco', 'Produbanco'),
            ('pacifico', 'Banco Pacífico'),
            ('interbancaria', 'Interbancaria'),
            ('otro', 'Otro banco'),
        ], blank=True,
        verbose_name='Banco 1'
    )

    monto_2 = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        verbose_name='Monto 2'
    )
    metodo_2 = models.CharField(
        max_length=20, choices=METODOS_PAGO_FINAL, blank=True,
        verbose_name='Método 2'
    )
    banco_2 = models.CharField(
        max_length=20, choices=[
            ('pichincha', 'Banco Pichincha'),
            ('guayaquil', 'Banco Guayaquil'),
            ('produbanco', 'Produbanco'),
            ('pacifico', 'Banco Pacífico'),
            ('interbancaria', 'Interbancaria'),
            ('otro', 'Otro banco'),
        ], blank=True,
        verbose_name='Banco 2'
    )

    # ── Factura ──────────────────────────────────────────
    factura_realizada = models.CharField(
        max_length=2, choices=SI_NO, default='no',
        verbose_name='¿Factura realizada?',
    )
    factura_nombres = models.CharField(
        max_length=100, blank=True, verbose_name='Nombres (factura)',
    )
    factura_apellidos = models.CharField(
        max_length=100, blank=True, verbose_name='Apellidos (factura)',
    )
    factura_cedula = models.CharField(
        max_length=20, blank=True, verbose_name='Cédula / RUC (factura)',
    )
    factura_correo = models.EmailField(
        blank=True, verbose_name='Correo electrónico',
    )

    # ── Conformidad del cliente ──────────────────────────
    cliente_recibe_conforme = models.CharField(
        max_length=2, choices=SI_NO, default='si',
        verbose_name='Cliente recibe conforme',
    )

    # ── Cierre de bodegaje (cuando el cliente realmente viene a retirar) ──
    # Cuando se registra la salida, el equipo queda "entregado" en sistema,
    # pero puede que el cliente físicamente NO haya venido a retirarlo todavía.
    # Esto se confirma con "Cliente ya retiró" (botón aparte).
    fecha_retiro_real = models.DateField(
        null=True, blank=True,
        verbose_name='Fecha real en que el cliente retiró',
        help_text='Se llena cuando se confirma que el cliente ya vino. '
                  'Si está vacío, se sigue acumulando bodegaje día a día.',
    )
    bodegaje_dias_congelado = models.PositiveIntegerField(
        null=True, blank=True,
        verbose_name='Días de bodegaje al cerrar',
    )
    bodegaje_monto_congelado = models.DecimalField(
        max_digits=10, decimal_places=2,
        null=True, blank=True,
        verbose_name='Monto de bodegaje al cerrar (USD)',
    )
    bodegaje_aplicado_al_pago = models.BooleanField(
        default=False,
        verbose_name='Bodegaje cobrado al cliente',
        help_text='Si está marcado, el monto de bodegaje fue sumado al total cobrado.',
    )
    bodegaje_silenciado = models.BooleanField(
        default=False,
        verbose_name='🔕 Alerta de bodegaje silenciada',
        help_text='Si está activo, este equipo no aparecerá en la alerta de bodegaje '
                  'del dashboard (pero el bodegaje sigue acumulándose).',
    )

    # ── Auditoría ────────────────────────────────────────
    registrado_por = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='salidas_registradas',
        verbose_name='Registrado por',
    )
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Equipo finalizado'
        verbose_name_plural = 'Equipos finalizados'
        ordering = ['-fecha_salida', '-creado']

    @property
    def pago_mixto_partes(self):
        """Desglose legible de las dos partes del pago final mixto."""
        if self.metodo_pago_final != 'mixto':
            return []

        bancos = dict(self._meta.get_field('banco_1').choices)
        metodos = dict(self.METODOS_PAGO_FINAL)

        def armar_parte(numero, monto, metodo, banco):
            if not monto and not metodo:
                return None

            metodo_texto = metodos.get(metodo, metodo or '—')
            banco_texto = ''
            detalle = metodo_texto

            if metodo == 'transferencia':
                banco_texto = bancos.get(banco, banco or '')
                detalle = f'{metodo_texto} - {banco_texto}' if banco_texto else metodo_texto

            return {
                'numero': numero,
                'monto': _q2(monto or Decimal('0.00')),
                'metodo': metodo_texto,
                'banco': banco_texto,
                'detalle': detalle,
            }

        partes = [
            armar_parte(1, self.monto_1, self.metodo_1, self.banco_1),
            armar_parte(2, self.monto_2, self.metodo_2, self.banco_2),
        ]
        return [p for p in partes if p]

    @property
    def es_positivo(self):
        """¿La salida es positiva (cliente se llevó equipo reparado)?"""
        return self.estado_reparacion in (
            'garantia',
            'garantia_fallos_adicionales',
            'cortesia',
            'pendiente_retiro',
            'retirado',
        )

    @property
    def pendiente_de_retiro_fisico(self):
        """¿Está esperando que el cliente venga a retirar (cualquier resultado)?"""
        return self.estado_reparacion in (
            'garantia',
            'garantia_fallos_adicionales',
            'cortesia',
            'pendiente_retiro',
            'retirado',
            'cliente_no_acepta',
            'no_reparable',
            'revision',
        )

    @property
    def cliente_ya_retiro(self):
        """¿El cliente ya vino físicamente a retirar el equipo?"""
        return self.fecha_retiro_real is not None

    @property
    def tecnico_reparo_nombre(self):
        """Nombre del técnico responsable registrado en la salida."""
        u = self.tecnico_reparo
        if not u:
            return ''
        return (f'{u.first_name} {u.last_name}'.strip()) or u.username

    @property
    def tiene_valor_acordado_adicional(self):
        """Indica si esta salida conserva un cargo adicional válido."""
        return (
            self.aplica_valor_acordado_adicional == 'si'
            and (self.valor_acordado_adicional or Decimal('0.00')) > 0
        )

    def calcular_bodegaje(self, hoy=None, umbral=None, costo_dia=None):
        """
        Calcula el bodegaje acumulado al día de hoy (o al día indicado).

        Reglas:
          - Solo aplica a salidas POSITIVAS (cliente se llevaba equipo).
          - Solo aplica si el cliente NO ha venido a retirar todavía.
          - Empieza a cobrar pasados `umbral` días desde fecha_salida.
          - Cobra `costo_dia` USD por día acumulado.

        Si la salida ya está cerrada (fecha_retiro_real != None),
        devuelve el monto congelado al momento del cierre.

        Devuelve un dict con: {'aplica', 'dias', 'monto'}.
        """
        from decimal import Decimal as D
        # Importar config local para evitar import circular
        from .alertas import COSTO_BODEGAJE_DIA, UMBRAL_DIAS_BODEGAJE

        if self.estado_reparacion == 'cortesia' or self.ingreso.estado == 'cortesia':
            return {'aplica': False, 'dias': 0, 'monto': D('0.00'), 'cerrado': False}
        
        if costo_dia is None:
            costo_dia = COSTO_BODEGAJE_DIA
        if umbral is None:
            umbral = UMBRAL_DIAS_BODEGAJE

        # Si ya se decidió y congeló el bodegaje, devolver lo congelado.
        if self.bodegaje_dias_congelado is not None:
            return {
                'aplica': True,
                'dias': self.bodegaje_dias_congelado or 0,
                'monto': self.bodegaje_monto_congelado or D('0.00'),
                'cerrado': True,
            }

        # Si el cliente ya retiró pero NO se congeló el bodegaje, calculamos
        # los días reales hasta la fecha de retiro (no hasta hoy), para no
        # seguir acumulando después de que físicamente se llevó el equipo.
        hoy_calc = hoy
        if self.cliente_ya_retiro and self.fecha_retiro_real:
            hoy_calc = self.fecha_retiro_real

        # Si no está esperando retiro (y no retiró), no aplica bodegaje
        if not self.pendiente_de_retiro_fisico and not self.cliente_ya_retiro:
            return {'aplica': False, 'dias': 0, 'monto': D('0.00'), 'cerrado': False}

        if hoy_calc is None:
            hoy_calc = date.today()
        if not self.fecha_salida:
            return {'aplica': False, 'dias': 0, 'monto': D('0.00'), 'cerrado': False}

        dias_pasados = (hoy_calc - self.fecha_salida).days
        if dias_pasados < umbral:
            return {'aplica': False, 'dias': 0, 'monto': D('0.00'), 'cerrado': False}

        dias_cobro = dias_pasados - umbral + 1   # día 5 → 1 día, día 6 → 2, etc.
        monto = D(str(costo_dia)) * dias_cobro
        return {
            'aplica': True,
            'dias': dias_cobro,
            'monto': _q2(monto),
            'cerrado': False,
        }

    @classmethod
    def generar_numero_recibo(cls):
        ultimo = cls.objects.filter(numero_recibo__startswith='RECS-').order_by('-numero_recibo').first()
        if ultimo and ultimo.numero_recibo:
            try:
                siguiente = int(ultimo.numero_recibo[5:]) + 1
            except ValueError:
                siguiente = 1
        else:
            siguiente = 1
        return f'RECS-{siguiente:04d}'

    def save(self, *args, **kwargs):
        es_cortesia = (
            self.estado_reparacion == 'cortesia'
            or (self.ingreso_id and self.ingreso.estado == 'cortesia')
        )
        if es_cortesia:
            self.estado_reparacion = 'cortesia'
            self.valor_final_cobrado = Decimal('0.00')
            self.valor_acordado_revision = None
            self.metodo_pago_final = 'cortesia'
            self.numero_recibo = ''
            self.banco = ''
            self.banco_otro = ''
            self.tarjeta_app = ''
            self.comprobante_url = ''
            self.monto_1 = None
            self.metodo_1 = ''
            self.banco_1 = ''
            self.monto_2 = None
            self.metodo_2 = ''
            self.banco_2 = ''
            self.factura_realizada = 'no'
            self.factura_nombres = ''
            self.factura_apellidos = ''
            self.factura_cedula = ''
            self.factura_correo = ''

            update_fields = kwargs.get('update_fields')
            if update_fields is not None:
                kwargs['update_fields'] = set(update_fields) | {
                    'estado_reparacion',
                    'valor_final_cobrado',
                    'valor_acordado_revision',
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
                    'factura_apellidos',
                    'factura_cedula',
                    'factura_correo',
                }

        if self.valor_final_cobrado and self.valor_final_cobrado > 0 and not self.numero_recibo:
            self.numero_recibo = SalidaEquipo.generar_numero_recibo()
        # Sincronizar estado del ingreso al guardar la salida
        if self.ingreso_id:
            if self.estado_reparacion == 'cortesia':
                self.ingreso.estado = 'cortesia'
                self.ingreso.subestado_reparacion = ''
                self.ingreso.subestado_entregado = ''
            elif self.estado_reparacion in ('garantia', 'garantia_fallos_adicionales'):
                self.ingreso.estado = 'garantia'
            else:
                self.ingreso.estado = 'entregado'
                if self.estado_reparacion == 'cliente_no_acepta':
                    self.ingreso.subestado_entregado = 'no_quiso_reparar'
                elif self.estado_reparacion == 'retirado':
                    self.ingreso.subestado_entregado = 'con_solucion'
                elif self.estado_reparacion == 'no_reparable':
                    self.ingreso.subestado_entregado = 'sin_solucion'
                elif self.estado_reparacion == 'pendiente_retiro':
                    self.ingreso.subestado_entregado = 'pendiente_retiro'
                elif self.estado_reparacion == 'revision':
                    self.ingreso.subestado_entregado = 'revision'
            self.ingreso.save()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'Salida Equipo {self.ingreso.codigo_equipo} — {self.get_estado_reparacion_display()}'


# ─────────────────────────────────────────────────────────
# Registro Administrativo: Egresos (gastos del taller)
# ─────────────────────────────────────────────────────────

class CategoriaEgreso(models.Model):
    """Categoría de gasto del taller (sueldos, repuestos, alquiler, etc.)"""
    COLORES = [
        ('#c62828', 'Rojo'),
        ('#f0ad4e', 'Naranja'),
        ('#1a237e', 'Azul'),
        ('#2e7d32', 'Verde'),
        ('#6a1b9a', 'Morado'),
        ('#00838f', 'Cian'),
        ('#5d4037', 'Marrón'),
        ('#455a64', 'Gris'),
    ]

    nombre = models.CharField(max_length=80, unique=True)
    descripcion = models.TextField(blank=True)
    color = models.CharField(max_length=7, choices=COLORES, default='#f0ad4e')
    icono = models.CharField(
        max_length=4, blank=True,
        help_text='Emoji corto (ej.: 🔧, 🏠, 💡, 📦).'
    )
    orden = models.PositiveIntegerField(default=0)
    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Categoría de egreso'
        verbose_name_plural = 'Categorías de egresos'
        ordering = ['orden', 'nombre']

    def __str__(self):
        return self.nombre


class Egreso(models.Model):
    """Cada gasto del taller (sueldos, repuestos, alquiler, etc.)"""

    METODOS_PAGO = [
        ('efectivo', 'Efectivo'),
        ('transferencia', 'Transferencia bancaria'),
        ('tarjeta', 'Tarjeta de crédito / Débito'),
        ('mixto', 'Pago mixto (2 métodos)'),
    ]

    fecha = models.DateField(
        help_text='Fecha en que se efectuó el gasto.'
    )
    categoria = models.ForeignKey(
        CategoriaEgreso, on_delete=models.PROTECT,
        related_name='egresos',
    )
    concepto = models.CharField(
        max_length=200,
        help_text='Descripción corta del gasto (ej.: "Compra de repuestos PS3").'
    )
    monto = models.DecimalField(
        max_digits=12, decimal_places=2,
        help_text='Monto del gasto en USD.'
    )
    notas = models.TextField(blank=True)

    # ── Método de pago ─────────────────────────────────────
    metodo = models.CharField(
        max_length=20, choices=METODOS_PAGO, default='efectivo',
        verbose_name='Método de pago',
    )
    banco = models.CharField(
        max_length=20, choices=[
            ('pichincha', 'Banco Pichincha'),
            ('guayaquil', 'Banco Guayaquil'),
            ('produbanco', 'Produbanco'),
            ('pacifico', 'Banco Pacífico'),
            ('interbancaria', 'Interbancaria'),
            ('otro', 'Otro banco'),
        ], blank=True,
        verbose_name='Banco',
    )
    banco_otro = models.CharField(
        max_length=100, blank=True,
        verbose_name='Banco (otro)',
        help_text='Completar solo si elegiste "Otro banco".',
    )
    tarjeta_app = models.CharField(
        max_length=20, choices=[
            ('payphone', 'Payphone'),
            ('deuna', 'Deuna'),
        ], blank=True,
        verbose_name='Tarjeta / App',
    )
    comprobante_url = models.URLField(
        blank=True,
        verbose_name='Link del comprobante',
        help_text='URL del comprobante de transferencia.',
    )
    numero_recibo = models.CharField(
        max_length=30, unique=True, blank=True, null=True,
        verbose_name='Número de recibo',
    )

    # Origen automático para compras registradas desde Ingreso de Equipo.
    # La relación única evita duplicar el egreso si se edita el ingreso.
    ingreso_compra = models.OneToOneField(
        'IngresoEquipo', on_delete=models.PROTECT,
        null=True, blank=True, related_name='egreso_compra',
        verbose_name='Ingreso de equipo comprado',
    )
    monto_1 = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        verbose_name='Monto mixto 1',
    )
    metodo_1 = models.CharField(
        max_length=20, choices=METODOS_PAGO, blank=True,
        verbose_name='Método mixto 1',
    )
    banco_1 = models.CharField(
        max_length=20, blank=True, verbose_name='Banco mixto 1',
    )
    banco_otro_1 = models.CharField(
        max_length=100, blank=True, verbose_name='Banco mixto 1 (otro)',
    )
    tarjeta_app_1 = models.CharField(
        max_length=20, blank=True, verbose_name='Tarjeta / App mixta 1',
    )
    monto_2 = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        verbose_name='Monto mixto 2',
    )
    metodo_2 = models.CharField(
        max_length=20, choices=METODOS_PAGO, blank=True,
        verbose_name='Método mixto 2',
    )
    banco_2 = models.CharField(
        max_length=20, blank=True, verbose_name='Banco mixto 2',
    )
    banco_otro_2 = models.CharField(
        max_length=100, blank=True, verbose_name='Banco mixto 2 (otro)',
    )
    tarjeta_app_2 = models.CharField(
        max_length=20, blank=True, verbose_name='Tarjeta / App mixta 2',
    )

    # ── Factura ──────────────────────────────────────────
    factura_realizada = models.CharField(
        max_length=2, choices=[('no', 'No'), ('si', 'Sí')], default='no',
        verbose_name='¿Factura realizada?',
    )
    factura_nombres = models.CharField(
        max_length=100, blank=True, verbose_name='Nombres (factura)',
    )
    factura_apellidos = models.CharField(
        max_length=100, blank=True, verbose_name='Apellidos (factura)',
    )
    factura_cedula = models.CharField(
        max_length=20, blank=True, verbose_name='Cédula / RUC (factura)',
    )
    factura_correo = models.EmailField(
        blank=True, verbose_name='Correo electrónico (factura)',
    )

    registrado_por = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='egresos_registrados',
    )
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Egreso'
        verbose_name_plural = 'Egresos'
        ordering = ['-fecha', '-creado']

    @property
    def pago_mixto_partes(self):
        """Desglose legible del egreso cuando fue pagado con dos métodos."""
        if self.metodo != 'mixto':
            return []
        metodos = dict(self.METODOS_PAGO)
        bancos = dict(IngresoEquipo.COMPRA_BANCOS)
        partes = []
        for numero, monto, metodo, banco, banco_otro, tarjeta_app in (
            (1, self.monto_1, self.metodo_1, self.banco_1, self.banco_otro_1, self.tarjeta_app_1),
            (2, self.monto_2, self.metodo_2, self.banco_2, self.banco_otro_2, self.tarjeta_app_2),
        ):
            if not monto and not metodo:
                continue
            detalle = metodos.get(metodo, metodo or '—')
            if metodo == 'transferencia' and banco:
                nombre_banco = banco_otro if banco == 'otro' and banco_otro else bancos.get(banco, banco)
                detalle = f'{detalle} ({nombre_banco})'
            elif metodo == 'tarjeta' and tarjeta_app:
                detalle = f'{detalle} ({tarjeta_app.title()})'
            partes.append({'numero': numero, 'monto': _q2(monto), 'detalle': detalle})
        return partes

    def __str__(self):
        return f'{self.fecha.strftime("%d/%m/%Y")} — {self.concepto} (${self.monto})'


# ─────────────────────────────────────────────────────────
# Actividad de Usuario
# ─────────────────────────────────────────────────────────

class UsuarioActividad(models.Model):
    """
    Rastrea la última vez que el usuario hizo alguna acción en el sistema
    para poder mostrar si está 'En línea' o no.
    """
    user = models.OneToOneField('auth.User', on_delete=models.CASCADE, related_name='actividad')
    ultima_conexion = models.DateTimeField(auto_now=True)
    fecha_reinicio_perfil = models.DateTimeField(null=True, blank=True)
    perfil_color_asesor = models.CharField(max_length=7, default='#0d47a1')
    ocultar_guia_saldo_pendiente = models.BooleanField(
        default=False,
        verbose_name='No volver a mostrar la guía de saldo pendiente',
    )

    def __str__(self):
        return f'Actividad de {self.user.username}'


class HorarioTecnico(models.Model):
    """
    Horario laboral configurable por técnico.

    El dashboard administrativo usa este registro para mostrar el horario y
    para avisar cuando el técnico entra al sistema en un día laboral.
    """
    tecnico = models.OneToOneField(
        'auth.User',
        on_delete=models.CASCADE,
        related_name='horario_laboral',
    )
    activo = models.BooleanField(default=True)
    lunes = models.BooleanField(default=True)
    martes = models.BooleanField(default=True)
    miercoles = models.BooleanField(default=True)
    jueves = models.BooleanField(default=True)
    viernes = models.BooleanField(default=True)
    hora_inicio = models.TimeField(default=time(9, 0))
    hora_fin = models.TimeField(default=time(18, 0))
    ultima_notificacion_laboral = models.DateTimeField(null=True, blank=True)
    ultima_notificacion_fuera_laboral = models.DateTimeField(null=True, blank=True)
    ultima_notificacion_fuera_motivo = models.CharField(max_length=20, blank=True)
    actualizado = models.DateTimeField(auto_now=True)

    DIAS = [
        ('lunes', 'Lunes'),
        ('martes', 'Martes'),
        ('miercoles', 'Miércoles'),
        ('jueves', 'Jueves'),
        ('viernes', 'Viernes'),
    ]

    class Meta:
        verbose_name = 'Horario de técnico'
        verbose_name_plural = 'Horarios de técnicos'
        ordering = ['tecnico__first_name', 'tecnico__username']

    def __str__(self):
        return f'Horario de {self.nombre_tecnico}'

    @property
    def nombre_tecnico(self):
        return self.tecnico.get_full_name() or self.tecnico.username

    def es_dia_laboral(self, dia=None):
        if not self.activo:
            return False
        dia = dia or timezone.localdate()
        mapa = {
            0: self.lunes,
            1: self.martes,
            2: self.miercoles,
            3: self.jueves,
            4: self.viernes,
        }
        return bool(mapa.get(dia.weekday(), False))

    def esta_en_horario(self, momento=None):
        momento = timezone.localtime(momento or timezone.now())
        if not self.es_dia_laboral(momento.date()):
            return False
        hora = momento.time()
        return self.hora_inicio <= hora <= self.hora_fin

    @property
    def dias_display(self):
        activos = [label for campo, label in self.DIAS if getattr(self, campo)]
        return ', '.join(activos) if activos else 'Sin días asignados'


class BitacoraTecnico(models.Model):
    """
    Registro permanente de acciones hechas por cada usuario en el sistema.

    La bitacora diaria se genera desde esta tabla para que no dependa de textos
    editables en pantalla ni se pierda cuando se cierre el modal.
    """
    TIPO_ACCION = [
        ('login', 'Inicio de sesión'),
        ('logout', 'Cierre de sesión'),
        ('ingreso', 'Ingreso de equipo'),
        ('ingreso_editado', 'Edición de equipo'),
        ('estado', 'Cambio de estado'),
        ('reporte', 'Reporte técnico'),
        ('valor_pendiente', 'Valor acordado pendiente'),
        ('salida', 'Salida de equipo'),
        ('salida_editada', 'Edición de salida'),
        ('venta_producto', 'Venta de producto'),
        ('venta_editada', 'Edición de venta'),
        ('abono', 'Abono'),
        ('abono_editado', 'Edición de abono'),
        ('eliminacion', 'Eliminación'),
        ('otro', 'Otra acción'),
    ]

    user = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='bitacora_tecnico',
    )
    usuario_nombre = models.CharField(max_length=150, blank=True)
    momento = models.DateTimeField(default=timezone.now, db_index=True)
    tipo = models.CharField(max_length=40, choices=TIPO_ACCION, default='otro')
    texto = models.TextField()
    codigo = models.CharField(max_length=30, blank=True)
    ingreso = models.ForeignKey(
        IngresoEquipo,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='eventos_bitacora',
    )
    salida = models.ForeignKey(
        SalidaEquipo,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='eventos_bitacora',
    )
    abono = models.ForeignKey(
        Abono,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='eventos_bitacora',
    )
    dedupe_key = models.CharField(max_length=200, unique=True, null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Bitácora de técnico'
        verbose_name_plural = 'Bitácora de técnicos'
        ordering = ['momento', 'pk']
        indexes = [
            models.Index(fields=['user', 'momento']),
            models.Index(fields=['tipo', 'momento']),
            models.Index(fields=['codigo']),
        ]

    def __str__(self):
        usuario = self.usuario_nombre or (self.user.username if self.user_id else 'Usuario')
        local = timezone.localtime(self.momento)
        return f'{local.strftime("%d/%m/%Y %H:%M")} — {usuario}: {self.texto[:80]}'


# ─────────────────────────────────────────────────────────
# Avisos del panel principal (banners de inicio)
# ─────────────────────────────────────────────────────────

class AvisoPanel(models.Model):
    """
    Aviso/anuncio que el administrador publica y que ven TODOS los usuarios
    en la pantalla de inicio (bienvenida), mientras esté vigente.

    Vigencia: un aviso se muestra si está activo y la fecha de hoy está dentro
    del rango [fecha_inicio, fecha_fin] (ambas inclusive). Solo el administrador
    puede crear, editar o eliminar avisos.
    """

    TIPOS = [
        ('info', 'Información (azul)'),
        ('exito', 'Éxito / positivo (verde)'),
        ('alerta', 'Alerta / atención (naranja)'),
        ('urgente', 'Urgente (rojo)'),
    ]

    titulo = models.CharField(
        max_length=140,
        verbose_name='Título del aviso',
    )
    mensaje = models.TextField(
        verbose_name='Mensaje',
        help_text='Texto que verán todos los usuarios en el inicio.',
    )
    tipo = models.CharField(
        max_length=10, choices=TIPOS, default='info',
        verbose_name='Tipo / color del aviso',
    )
    fecha_inicio = models.DateField(
        verbose_name='Fecha de inicio',
        help_text='Desde cuándo se muestra el aviso (inclusive).',
    )
    fecha_fin = models.DateField(
        verbose_name='Fecha final',
        help_text='Hasta cuándo se muestra el aviso (inclusive).',
    )
    activo = models.BooleanField(
        default=True,
        verbose_name='Activo',
        help_text='Desmárcalo para ocultar el aviso sin borrarlo.',
    )
    creado_por = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='avisos_creados',
        verbose_name='Creado por',
    )
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Aviso del panel'
        verbose_name_plural = 'Avisos del panel'
        ordering = ['-fecha_inicio', '-creado']

    @property
    def vigente(self):
        """¿El aviso debe mostrarse hoy?"""
        if not self.activo:
            return False
        hoy = date.today()
        return self.fecha_inicio <= hoy <= self.fecha_fin

    @property
    def estado_texto(self):
        """Etiqueta legible del estado de vigencia (para la lista admin)."""
        hoy = date.today()
        if not self.activo:
            return 'Inactivo'
        if hoy < self.fecha_inicio:
            return 'Programado'
        if hoy > self.fecha_fin:
            return 'Expirado'
        return 'Vigente'

    @classmethod
    def vigentes_hoy(cls):
        """Avisos que deben mostrarse hoy en el inicio."""
        hoy = date.today()
        return cls.objects.filter(
            activo=True, fecha_inicio__lte=hoy, fecha_fin__gte=hoy,
        ).order_by('-fecha_inicio', '-creado')

    def __str__(self):
        return f'{self.titulo} ({self.estado_texto})'


# ─────────────────────────────────────────────────────────
# Notificaciones internas para asesoras
# ─────────────────────────────────────────────────────────

class NotificacionAsesora(models.Model):
    """Aviso interno para que una asesora gestione cobros especiales."""

    TIPO_FALLOS_ADICIONALES = 'fallos_adicionales'
    TIPO_REVISION_PENDIENTE = 'revision_pendiente'
    TIPO_SALDO_RETIRO = 'saldo_retiro'
    TIPOS = [
        (TIPO_FALLOS_ADICIONALES, 'Garantía con fallos adicionales'),
        (TIPO_REVISION_PENDIENTE, 'Revisión pendiente de pago'),
        (TIPO_SALDO_RETIRO, 'Equipo listo con saldo pendiente'),
    ]

    tipo = models.CharField(
        max_length=30,
        choices=TIPOS,
        default=TIPO_FALLOS_ADICIONALES,
        verbose_name='Tipo de notificación',
    )
    salida = models.ForeignKey(
        SalidaEquipo,
        on_delete=models.CASCADE,
        related_name='notificaciones_asesora',
        verbose_name='Salida relacionada',
    )
    ingreso = models.ForeignKey(
        IngresoEquipo,
        on_delete=models.CASCADE,
        related_name='notificaciones_asesora',
        verbose_name='Ingreso relacionado',
    )
    asesora = models.ForeignKey(
        'auth.User',
        on_delete=models.CASCADE,
        related_name='notificaciones_asesora',
        verbose_name='Asesora notificada',
    )
    creado_por = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='notificaciones_asesora_creadas',
        verbose_name='Notificado por',
    )
    valor_acordado = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name='Valor acordado por fallos adicionales',
    )
    mensaje = models.TextField(
        blank=True,
        verbose_name='Mensaje para la asesora',
    )
    leida = models.BooleanField(
        default=False,
        verbose_name='Vista por la asesora',
    )
    leida_en = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Vista el',
    )
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Notificación de asesora'
        verbose_name_plural = 'Notificaciones de asesoras'
        ordering = ['leida', '-creado']
        constraints = [
            models.UniqueConstraint(
                fields=['salida', 'tipo'],
                name='uniq_notificacion_asesora_salida_tipo',
            )
        ]

    def __str__(self):
        return f'{self.get_tipo_display()} — {self.ingreso.codigo_equipo} — {self.asesora}'
