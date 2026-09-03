from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('econotec', '0060_corregir_salidas_confirmadas_pendientes'),
    ]

    operations = [
        migrations.AlterField(
            model_name='salidaequipo',
            name='aplica_valor_acordado_adicional',
            field=models.CharField(
                choices=[('si', 'Sí'), ('no', 'No')],
                default='no',
                help_text='Aplica a equipos pendientes de retiro y a cierres sin reparación.',
                max_length=2,
                verbose_name='¿Aplica un valor acordado adicional?',
            ),
        ),
        migrations.AlterField(
            model_name='salidaequipo',
            name='valor_acordado_adicional',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('0.00'),
                help_text='Cobro adicional opcional acordado al finalizar el equipo.',
                max_digits=10,
                verbose_name='Valor acordado adicional (USD)',
            ),
        ),
        migrations.AlterField(
            model_name='notificacionasesora',
            name='tipo',
            field=models.CharField(
                choices=[
                    ('fallos_adicionales', 'Garantía con fallos adicionales'),
                    ('revision_pendiente', 'Revisión pendiente de pago'),
                    ('saldo_retiro', 'Equipo listo con saldo pendiente'),
                    ('cobro_adicional', 'Cobro adicional pendiente'),
                ],
                default='fallos_adicionales',
                max_length=30,
                verbose_name='Tipo de notificación',
            ),
        ),
    ]
