"""
Migración: agrega campos de cierre de bodegaje a SalidaEquipo.

Esto permite registrar:
  - cuándo el cliente vino físicamente a retirar (fecha_retiro_real)
  - cuántos días/dinero de bodegaje se acumularon al cerrar
  - si el bodegaje se cobró o no al cliente
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('econotec', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='salidaequipo',
            name='fecha_retiro_real',
            field=models.DateField(
                blank=True, null=True,
                help_text='Se llena cuando se confirma que el cliente ya vino. '
                          'Si está vacío, se sigue acumulando bodegaje día a día.',
                verbose_name='Fecha real en que el cliente retiró',
            ),
        ),
        migrations.AddField(
            model_name='salidaequipo',
            name='bodegaje_dias_congelado',
            field=models.PositiveIntegerField(
                blank=True, null=True,
                verbose_name='Días de bodegaje al cerrar',
            ),
        ),
        migrations.AddField(
            model_name='salidaequipo',
            name='bodegaje_monto_congelado',
            field=models.DecimalField(
                blank=True, null=True,
                decimal_places=2, max_digits=10,
                verbose_name='Monto de bodegaje al cerrar (USD)',
            ),
        ),
        migrations.AddField(
            model_name='salidaequipo',
            name='bodegaje_aplicado_al_pago',
            field=models.BooleanField(
                default=False,
                help_text='Si está marcado, el monto de bodegaje fue sumado al total cobrado.',
                verbose_name='Bodegaje cobrado al cliente',
            ),
        ),
    ]
