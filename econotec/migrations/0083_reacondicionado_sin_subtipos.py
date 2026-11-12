from django.db import migrations
from django.db.models import F


def unir_subtipos(apps, schema_editor):
    """El inventario reacondicionado ya no se divide por tipo: el tipo es la categoría."""
    InventarioItem = apps.get_model('econotec', 'InventarioItem')
    InventarioItem.objects.filter(linea='reacondicionado').update(tipo=F('categoria'))


class Migration(migrations.Migration):

    dependencies = [
        ('econotec', '0082_inventario_reacondicionado'),
    ]

    operations = [
        # No hay vuelta atrás automática: no se guarda si era láser o inyección.
        migrations.RunPython(unir_subtipos, migrations.RunPython.noop),
    ]
