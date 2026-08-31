from django.db import migrations


def corregir_salidas_confirmadas(apps, schema_editor):
    SalidaEquipo = apps.get_model('econotec', 'SalidaEquipo')
    IngresoEquipo = apps.get_model('econotec', 'IngresoEquipo')
    salidas_inconsistentes = SalidaEquipo.objects.filter(
        fecha_retiro_real__isnull=False,
        estado_reparacion='pendiente_retiro',
    )
    ingresos_ids = list(salidas_inconsistentes.values_list('ingreso_id', flat=True))
    salidas_inconsistentes.update(estado_reparacion='retirado')
    IngresoEquipo.objects.filter(pk__in=ingresos_ids).update(
        estado='entregado',
        subestado_reparacion='',
        subestado_entregado='con_solucion',
    )


class Migration(migrations.Migration):

    dependencies = [
        ('econotec', '0059_usuarioactividad_ocultar_guia_saldo_pendiente'),
    ]

    operations = [
        migrations.RunPython(
            corregir_salidas_confirmadas,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
