"""
Migración: agrega campos para decisión de bodegaje al momento del abono
y separa Payphone como método de pago independiente.
"""
from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('econotec', '0003_abono_banco_otro_abono_comprobante_url_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='abono',
            name='bodegaje_decision',
            field=models.CharField(
                choices=[
                    ('na', 'No aplica (sin bodegaje pendiente)'),
                    ('si', 'Sí — aplicar bodegaje (sumar al monto)'),
                    ('no', 'No — perdonar bodegaje'),
                ],
                default='na',
                help_text='Si el equipo tenía bodegaje pendiente al momento del abono.',
                max_length=2,
                verbose_name='Decisión de bodegaje',
            ),
        ),
        migrations.AddField(
            model_name='abono',
            name='bodegaje_monto_aplicado',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('0.00'),
                help_text='Monto del bodegaje incluido en este abono (si decisión = "si").',
                max_digits=10,
                verbose_name='Monto de bodegaje aplicado (USD)',
            ),
        ),
        migrations.AlterField(
            model_name='abono',
            name='metodo',
            field=models.CharField(
                choices=[
                    ('efectivo', 'Efectivo'),
                    ('transferencia', 'Transferencia bancaria'),
                    ('tarjeta', 'Tarjeta de crédito / Débito'),
                    ('payphone', 'Payphone / Deuna'),
                ],
                default='efectivo',
                max_length=20,
                verbose_name='Método de pago',
            ),
        ),
    ]
