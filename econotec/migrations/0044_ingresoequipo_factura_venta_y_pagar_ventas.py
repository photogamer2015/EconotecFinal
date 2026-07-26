from decimal import Decimal

from django.db import migrations, models
from django.db.models import Sum


def marcar_ventas_como_pagadas(apps, schema_editor):
    IngresoEquipo = apps.get_model('econotec', 'IngresoEquipo')
    Abono = apps.get_model('econotec', 'Abono')

    ventas = IngresoEquipo.objects.filter(
        sede='ventas',
        valor_acordado__isnull=False,
    )
    for venta in ventas:
        total_abonos = (
            Abono.objects
            .filter(ingreso_id=venta.pk)
            .aggregate(total=Sum('monto'))['total']
            or Decimal('0.00')
        )
        valor = venta.valor_acordado or Decimal('0.00')
        anticipo_necesario = valor - total_abonos
        if anticipo_necesario < Decimal('0.00'):
            anticipo_necesario = Decimal('0.00')

        update_fields = []
        if venta.abono_anticipo != anticipo_necesario:
            venta.abono_anticipo = anticipo_necesario
            update_fields.append('abono_anticipo')
        if not venta.anticipo_metodo:
            venta.anticipo_metodo = 'efectivo'
            update_fields.append('anticipo_metodo')
        if update_fields:
            venta.save(update_fields=update_fields)


class Migration(migrations.Migration):

    dependencies = [
        ('econotec', '0043_ventainventarioitem'),
    ]

    operations = [
        migrations.AddField(
            model_name='ingresoequipo',
            name='factura_realizada',
            field=models.CharField(
                choices=[('no', 'No'), ('si', 'Sí')],
                default='no',
                max_length=2,
                verbose_name='¿Factura realizada?',
            ),
        ),
        migrations.AddField(
            model_name='ingresoequipo',
            name='factura_nombres',
            field=models.CharField(
                blank=True,
                max_length=100,
                verbose_name='Nombres (factura)',
            ),
        ),
        migrations.AddField(
            model_name='ingresoequipo',
            name='factura_cedula',
            field=models.CharField(
                blank=True,
                max_length=20,
                verbose_name='Cédula / RUC (factura)',
            ),
        ),
        migrations.AddField(
            model_name='ingresoequipo',
            name='factura_correo',
            field=models.EmailField(
                blank=True,
                max_length=254,
                verbose_name='Correo electrónico (factura)',
            ),
        ),
        migrations.RunPython(marcar_ventas_como_pagadas, migrations.RunPython.noop),
    ]
