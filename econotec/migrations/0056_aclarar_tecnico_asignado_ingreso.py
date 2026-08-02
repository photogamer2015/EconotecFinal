from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('econotec', '0055_salidaequipo_valor_acordado_adicional'),
    ]

    operations = [
        migrations.AlterField(
            model_name='ingresoequipo',
            name='tecnico_encargado',
            field=models.ForeignKey(
                blank=True,
                help_text='Técnico responsable asignado cuando el equipo ingresa. Este dato no define quién realizó la reparación.',
                limit_choices_to={'is_active': True},
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='ingresos_como_tecnico',
                to=settings.AUTH_USER_MODEL,
                verbose_name='Técnico asignado al ingreso',
            ),
        ),
    ]
