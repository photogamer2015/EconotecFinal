"""Crea el grupo «Asesora - Asistente de caja» para asignarlo desde el admin de usuarios."""
from django.db import migrations

GRUPO = 'Asesora - Asistente de caja'


def crear_grupo(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.get_or_create(name=GRUPO)


class Migration(migrations.Migration):

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
        ('econotec', '0079_egreso_repuesto_compra'),
    ]

    # Al revertir no se borra el grupo: podría tener usuarias asignadas.
    operations = [
        migrations.RunPython(crear_grupo, migrations.RunPython.noop),
    ]
