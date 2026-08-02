from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('econotec', '0056_aclarar_tecnico_asignado_ingreso'),
    ]

    operations = [
        migrations.AlterField(
            model_name='salidaequipo',
            name='tecnico_reparo',
            field=models.ForeignKey(
                blank=True,
                help_text='Técnico responsable de la reparación. Este dato define quién recibe el resultado positivo o negativo de la salida.',
                limit_choices_to={'is_active': True},
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='salidas_como_tecnico',
                to=settings.AUTH_USER_MODEL,
                verbose_name='Técnico que reparó',
            ),
        ),
    ]
