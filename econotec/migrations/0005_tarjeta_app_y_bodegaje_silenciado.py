from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('econotec', '0004_abono_bodegaje_decision_payphone'),
    ]

    operations = [
        migrations.AddField(
            model_name='abono',
            name='tarjeta_app',
            field=models.CharField(
                blank=True,
                choices=[('payphone', 'Payphone'), ('deuna', 'Deuna')],
                help_text='Solo cuando el método es Tarjeta o Payphone.',
                max_length=20,
                verbose_name='Tarjeta / App',
            ),
        ),
        migrations.AddField(
            model_name='salidaequipo',
            name='bodegaje_silenciado',
            field=models.BooleanField(
                default=False,
                help_text='Si está activo, este equipo no aparecerá en la alerta de bodegaje '
                          'del dashboard (pero el bodegaje sigue acumulándose).',
                verbose_name='🔕 Alerta de bodegaje silenciada',
            ),
        ),
        migrations.AddField(
            model_name='ingresoequipo',
            name='diagnostico_silenciado',
            field=models.BooleanField(
                default=False,
                help_text='Si está activo, este equipo no aparecerá en la alerta de '
                          '"equipos pendientes de diagnóstico" del dashboard. Se '
                          'reactiva automáticamente cuando el estado cambia.',
                verbose_name='🔕 Alerta de diagnóstico silenciada',
            ),
        ),
    ]
