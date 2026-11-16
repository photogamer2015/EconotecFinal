"""Nueva categoría de egreso: Devolución.

Se crea aquí para que aparezca en el formulario de egresos de todas las
instalaciones ya existentes, sin tener que volver a correr `setup_roles`.
"""
from django.db import migrations


NOMBRE = 'Devolución'


def crear_categoria(apps, schema_editor):
    CategoriaEgreso = apps.get_model('econotec', 'CategoriaEgreso')
    CategoriaEgreso.objects.get_or_create(
        nombre=NOMBRE,
        defaults={'icono': '↩️', 'color': '#c62828', 'orden': 7, 'activo': True},
    )


def borrar_categoria(apps, schema_editor):
    CategoriaEgreso = apps.get_model('econotec', 'CategoriaEgreso')
    # Solo se elimina si nadie la usó: los egresos registrados mandan.
    categoria = CategoriaEgreso.objects.filter(nombre=NOMBRE).first()
    if categoria and not categoria.egresos.exists():
        categoria.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('econotec', '0086_ajuste_cuenta_como_reparado'),
    ]

    operations = [
        migrations.RunPython(crear_categoria, borrar_categoria),
    ]
