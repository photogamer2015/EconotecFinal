from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('econotec', '0031_ingresoequipo_serie_alter_ingresoequipo_modelo_serie'),
    ]

    operations = [
        migrations.AddField(
            model_name='ingresoequipo',
            name='valor_pendiente_reporte',
            field=models.TextField(
                blank=True,
                help_text='Motivo indicado por el técnico cuando el valor acordado aún está pendiente.',
                verbose_name='Reporte de valor acordado pendiente',
            ),
        ),
        migrations.AddField(
            model_name='ingresoequipo',
            name='valor_pendiente_reporte_actualizado',
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name='Reporte de valor pendiente actualizado el',
            ),
        ),
        migrations.AddField(
            model_name='ingresoequipo',
            name='valor_pendiente_reporte_por',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='reportes_valor_pendiente',
                to=settings.AUTH_USER_MODEL,
                verbose_name='Reporte de valor pendiente hecho por',
            ),
        ),
    ]
