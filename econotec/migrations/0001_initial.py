"""
Migración inicial del sistema Econotec.

Crea todas las tablas: Cliente, IngresoEquipo, Abono, SalidaEquipo,
CategoriaEgreso, Egreso.

Esta migración incluye desde el inicio:
- Sub-estados de reparación y entrega.
- `tecnico_encargado` como ForeignKey al usuario.
- Campo `sede` y numeración correlativa independiente por sede.
"""
from decimal import Decimal

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ── Cliente ──────────────────────────────────────────
        migrations.CreateModel(
            name='Cliente',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('cedula', models.CharField(help_text='Cédula o RUC para emisión de la factura.', max_length=20, unique=True, verbose_name='Cédula o RUC')),
                ('nombres', models.CharField(max_length=150, verbose_name='Nombres del cliente')),
                ('whatsapp', models.CharField(blank=True, max_length=20, verbose_name='WhatsApp')),
                ('correo', models.EmailField(blank=True, max_length=254, verbose_name='Correo')),
                ('sector', models.CharField(blank=True, choices=[('norte', 'Norte'), ('sur', 'Sur'), ('centro', 'Centro'), ('este', 'Este'), ('oeste', 'Oeste'), ('via_costa', 'Vía a la Costa'), ('samborondon', 'Samborondón'), ('duran', 'Durán'), ('otro', 'Otro')], max_length=20, verbose_name='Sector')),
                ('sector_otro', models.CharField(blank=True, help_text='Si seleccionaste "Otro", indica cuál.', max_length=100, verbose_name='Sector (especificar)')),
                ('creado', models.DateTimeField(auto_now_add=True)),
                ('actualizado', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Cliente',
                'verbose_name_plural': 'Clientes',
                'ordering': ['nombres'],
            },
        ),

        # ── CategoriaEgreso ──────────────────────────────────
        migrations.CreateModel(
            name='CategoriaEgreso',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nombre', models.CharField(max_length=80, unique=True)),
                ('descripcion', models.TextField(blank=True)),
                ('color', models.CharField(choices=[('#c62828', 'Rojo'), ('#f0ad4e', 'Naranja'), ('#1a237e', 'Azul'), ('#2e7d32', 'Verde'), ('#6a1b9a', 'Morado'), ('#00838f', 'Cian'), ('#5d4037', 'Marrón'), ('#455a64', 'Gris')], default='#f0ad4e', max_length=7)),
                ('icono', models.CharField(blank=True, help_text='Emoji corto (ej.: 🔧, 🏠, 💡, 📦).', max_length=4)),
                ('orden', models.PositiveIntegerField(default=0)),
                ('activo', models.BooleanField(default=True)),
                ('creado', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'verbose_name': 'Categoría de egreso',
                'verbose_name_plural': 'Categorías de egresos',
                'ordering': ['orden', 'nombre'],
            },
        ),

        # ── IngresoEquipo ────────────────────────────────────
        migrations.CreateModel(
            name='IngresoEquipo',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sede', models.CharField(choices=[('guayaquil', 'Guayaquil'), ('quito', 'Quito')], default='guayaquil', help_text='Sede en la que se registró el equipo. Cada sede lleva su propia numeración.', max_length=20, verbose_name='Sede')),
                ('numero_equipo', models.PositiveIntegerField(help_text='Número correlativo del equipo dentro de su sede. Se asigna automáticamente.', verbose_name='Equipo N°')),
                ('numero_factura', models.CharField(blank=True, max_length=20, verbose_name='Factura N°')),
                ('asesor_comercial', models.CharField(blank=True, max_length=100, verbose_name='Asesora Comercial')),
                ('fecha_ingreso', models.DateField(verbose_name='Fecha de Ingreso')),
                ('tipo_equipo', models.CharField(choices=[('impresora', 'Impresora'), ('laptop', 'Laptop'), ('pc', 'PC'), ('monitor', 'Monitor'), ('cpu', 'CPU'), ('celular', 'Celular'), ('tablet', 'Tablet'), ('consola', 'Consola'), ('otro', 'Otros equipos')], max_length=20, verbose_name='Tipo de equipo')),
                ('tipo_equipo_otro', models.CharField(blank=True, help_text='Si seleccionaste "Otros equipos", indica cuál.', max_length=100, verbose_name='Tipo de equipo (especificar)')),
                ('marca', models.CharField(max_length=100, verbose_name='Marca')),
                ('modelo_serie', models.CharField(blank=True, max_length=200, verbose_name='Modelo / Serie')),
                ('accesorios_entregados', models.TextField(blank=True, help_text='Cargador, cable, funda, etc.', verbose_name='Accesorios entregados')),
                ('problema_reportado', models.TextField(help_text='Lo que indica el cliente al recibir el equipo.', verbose_name='Problema reportado')),
                ('reporte_tecnico', models.TextField(blank=True, verbose_name='Reporte del técnico — detallar lo que se le realizó al equipo')),
                ('diagnostico_inmediato', models.CharField(choices=[('si', 'Sí'), ('no', 'No')], default='no', max_length=2, verbose_name='Diagnóstico inmediato')),
                ('valor_diagnostico', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=10, verbose_name='Valor del diagnóstico (USD)')),
                ('valor_acordado', models.DecimalField(decimal_places=2, default=Decimal('0.00'), help_text='Costo total acordado de la reparación.', max_digits=10, verbose_name='Valor acordado (USD)')),
                ('abono_anticipo', models.DecimalField(decimal_places=2, default=Decimal('0.00'), help_text='Pago inicial. Se complementa con abonos posteriores en el módulo Pagos.', max_digits=10, verbose_name='Abono / Anticipo (USD)')),
                ('estado', models.CharField(choices=[('ingresado', 'Ingresado / En diagnóstico'), ('en_reparacion', 'En reparación'), ('reparado_pendiente_retiro', 'Reparado — pendiente de retiro'), ('entregado', 'Entregado al cliente')], default='ingresado', max_length=30, verbose_name='Estado del equipo')),
                ('subestado_reparacion', models.CharField(blank=True, choices=[('', '— Ninguno —'), ('espera_cliente', 'Espera de cliente'), ('espera_repuesto', 'Espera de repuesto')], default='', help_text='Solo aplica cuando el estado es "En reparación".', max_length=20, verbose_name='Detalle (En reparación)')),
                ('subestado_entregado', models.CharField(blank=True, choices=[('', '— Ninguno —'), ('con_solucion', 'Con solución'), ('sin_solucion', 'Sin solución')], default='', help_text='Solo aplica cuando el estado es "Entregado al cliente".', max_length=20, verbose_name='Detalle (Entregado)')),
                ('creado', models.DateTimeField(auto_now_add=True)),
                ('actualizado', models.DateTimeField(auto_now=True)),
                ('cliente', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='ingresos', to='econotec.cliente', verbose_name='Cliente')),
                ('registrado_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='ingresos_registrados', to=settings.AUTH_USER_MODEL, verbose_name='Registrado por')),
                ('tecnico_encargado', models.ForeignKey(blank=True, help_text='Técnico responsable de este equipo. Cuenta para su ranking de productividad.', limit_choices_to={'is_active': True}, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='ingresos_como_tecnico', to=settings.AUTH_USER_MODEL, verbose_name='Técnico Encargado')),
            ],
            options={
                'verbose_name': 'Ingreso de equipo',
                'verbose_name_plural': 'Ingresos de equipos',
                'ordering': ['-numero_equipo'],
            },
        ),
        migrations.AddConstraint(
            model_name='ingresoequipo',
            constraint=models.UniqueConstraint(fields=('sede', 'numero_equipo'), name='unique_numero_por_sede'),
        ),

        # ── Abono ────────────────────────────────────────────
        migrations.CreateModel(
            name='Abono',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('fecha', models.DateField(verbose_name='Fecha del abono')),
                ('monto', models.DecimalField(decimal_places=2, max_digits=10, verbose_name='Monto (USD)')),
                ('metodo', models.CharField(choices=[('efectivo', 'Efectivo'), ('transferencia', 'Transferencia bancaria'), ('tarjeta', 'Tarjeta de crédito/débito'), ('payphone', 'Payphone / Deuna')], default='efectivo', max_length=20, verbose_name='Método de pago')),
                ('banco', models.CharField(blank=True, choices=[('pichincha', 'Banco Pichincha'), ('guayaquil', 'Banco Guayaquil'), ('produbanco', 'Produbanco'), ('pacifico', 'Banco Pacífico'), ('payphone', 'Payphone'), ('interbancaria', 'Interbancaria')], max_length=20, verbose_name='Banco')),
                ('numero_recibo', models.CharField(blank=True, help_text='Si se deja vacío, se genera automáticamente (REC-0001, REC-0002…).', max_length=30, unique=True, verbose_name='Número de recibo')),
                ('observaciones', models.TextField(blank=True)),
                ('creado', models.DateTimeField(auto_now_add=True)),
                ('actualizado', models.DateTimeField(auto_now=True)),
                ('ingreso', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='abonos', to='econotec.ingresoequipo', verbose_name='Equipo / Ingreso')),
                ('registrado_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='abonos_registrados', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Abono',
                'verbose_name_plural': 'Abonos',
                'ordering': ['-fecha', '-creado'],
            },
        ),

        # ── SalidaEquipo ─────────────────────────────────────
        migrations.CreateModel(
            name='SalidaEquipo',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('fecha_salida', models.DateField(verbose_name='Fecha de entrega al cliente')),
                ('estado_reparacion', models.CharField(choices=[('retirado', '✅ Retirado / Entregado conforme'), ('cliente_no_acepta', '🚫 Cliente no quiso reparar'), ('no_reparable', '❌ No se pudo reparar'), ('reparado_parcial', '⚠️ Reparado parcialmente'), ('garantia', '🛡 Salida por garantía')], help_text='¿Cómo termina este equipo? La opción más común es "Retirado / Entregado conforme".', max_length=30, verbose_name='Estado de la salida')),
                ('observaciones', models.TextField(blank=True, help_text='Solo si necesitas anotar algo sobre la entrega. En retiros normales puedes dejarlo vacío.', verbose_name='Observaciones del cierre')),
                ('garantia_dias', models.PositiveIntegerField(default=0, help_text='Días de garantía sobre el trabajo realizado.', verbose_name='Garantía (días)')),
                ('valor_final_cobrado', models.DecimalField(decimal_places=2, default=Decimal('0.00'), help_text='Si ya está totalmente pagado, puedes dejar 0.', max_digits=10, verbose_name='Valor cobrado en esta salida (USD)')),
                ('metodo_pago_final', models.CharField(choices=[('efectivo', 'Efectivo'), ('transferencia', 'Transferencia bancaria'), ('tarjeta', 'Tarjeta de crédito/débito'), ('payphone', 'Payphone / Deuna'), ('cortesia', 'Cortesía / sin cobro'), ('sin_pago', 'Sin pago (no aplica)')], default='efectivo', max_length=20, verbose_name='Método de pago del saldo final')),
                ('cliente_recibe_conforme', models.CharField(choices=[('si', 'Sí'), ('no', 'No')], default='si', max_length=2, verbose_name='Cliente recibe conforme')),
                ('creado', models.DateTimeField(auto_now_add=True)),
                ('actualizado', models.DateTimeField(auto_now=True)),
                ('ingreso', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name='salida', to='econotec.ingresoequipo', verbose_name='Equipo entregado')),
                ('registrado_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='salidas_registradas', to=settings.AUTH_USER_MODEL, verbose_name='Registrado por')),
            ],
            options={
                'verbose_name': 'Salida de equipo',
                'verbose_name_plural': 'Salidas de equipos',
                'ordering': ['-fecha_salida', '-creado'],
            },
        ),

        # ── Egreso ───────────────────────────────────────────
        migrations.CreateModel(
            name='Egreso',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('fecha', models.DateField(help_text='Fecha en que se efectuó el gasto.')),
                ('concepto', models.CharField(help_text='Descripción corta del gasto (ej.: "Compra de repuestos PS3").', max_length=200)),
                ('monto', models.DecimalField(decimal_places=2, help_text='Monto del gasto en USD.', max_digits=12)),
                ('notas', models.TextField(blank=True)),
                ('creado', models.DateTimeField(auto_now_add=True)),
                ('actualizado', models.DateTimeField(auto_now=True)),
                ('categoria', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='egresos', to='econotec.categoriaegreso')),
                ('registrado_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='egresos_registrados', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Egreso',
                'verbose_name_plural': 'Egresos',
                'ordering': ['-fecha', '-creado'],
            },
        ),
    ]
