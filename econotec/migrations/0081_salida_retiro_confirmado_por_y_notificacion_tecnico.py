"""Quién confirmó la salida de la oficina + avisos de la asesora al técnico."""
from decimal import Decimal

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def rellenar_quien_confirmo(apps, schema_editor):
    """Recupera quién confirmó las salidas ya hechas desde el aviso 🔔 guardado.

    Solo quedó registro de las confirmadas por técnicos y asesoras (las de un
    administrador no generaban aviso): esas se quedan sin nombre.
    """
    SalidaEquipo = apps.get_model('econotec', 'SalidaEquipo')
    Aviso = apps.get_model('econotec', 'NotificacionCambioAdmin')
    ultimo_por_ingreso = {}
    avisos = (
        Aviso.objects
        .filter(tipo='salida_fisica', ingreso__isnull=False, creado_por__isnull=False)
        .order_by('creado', 'pk')
        .values_list('ingreso_id', 'creado_por_id')
    )
    for ingreso_id, usuario_id in avisos:
        ultimo_por_ingreso[ingreso_id] = usuario_id
    for ingreso_id, usuario_id in ultimo_por_ingreso.items():
        SalidaEquipo.objects.filter(
            ingreso_id=ingreso_id,
            fecha_retiro_real__isnull=False,
            retiro_confirmado_por__isnull=True,
        ).update(retiro_confirmado_por_id=usuario_id)


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('econotec', '0080_grupo_asistente_caja'),
    ]

    operations = [
        migrations.AddField(
            model_name='salidaequipo',
            name='retiro_confirmado_por',
            field=models.ForeignKey(
                blank=True, null=True,
                help_text='Asesora elegida al confirmar la salida de la oficina (salida de retiro).',
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='retiros_confirmados',
                to=settings.AUTH_USER_MODEL,
                verbose_name='Asesora a quien pertenece la salida',
            ),
        ),
        migrations.CreateModel(
            name='NotificacionTecnico',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('saldo_pendiente', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=10, verbose_name='Saldo pendiente al notificar')),
                ('mensaje', models.TextField(blank=True, verbose_name='Mensaje para el técnico')),
                ('leida', models.BooleanField(default=False, verbose_name='Vista por el técnico')),
                ('leida_en', models.DateTimeField(blank=True, null=True, verbose_name='Vista el')),
                ('creado', models.DateTimeField(auto_now_add=True)),
                ('creado_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='notificaciones_tecnico_creadas', to=settings.AUTH_USER_MODEL, verbose_name='Notificado por')),
                ('ingreso', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='notificaciones_tecnico', to='econotec.ingresoequipo', verbose_name='Equipo')),
                ('salida', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='notificaciones_tecnico', to='econotec.salidaequipo', verbose_name='Salida relacionada')),
                ('tecnico', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='notificaciones_tecnico', to=settings.AUTH_USER_MODEL, verbose_name='Técnico notificado')),
            ],
            options={
                'verbose_name': 'Notificación de técnico',
                'verbose_name_plural': 'Notificaciones de técnicos',
                'ordering': ['leida', '-creado'],
            },
        ),
        migrations.RunPython(rellenar_quien_confirmo, migrations.RunPython.noop),
    ]
