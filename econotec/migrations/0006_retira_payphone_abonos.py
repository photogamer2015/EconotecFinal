from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('econotec', '0005_tarjeta_app_y_bodegaje_silenciado'),
    ]

    operations = [
        migrations.AlterField(
            model_name='abono',
            name='metodo',
            field=models.CharField(
                choices=[
                    ('efectivo', 'Efectivo'),
                    ('transferencia', 'Transferencia bancaria'),
                    ('tarjeta', 'Tarjeta de crédito / Débito'),
                ],
                default='efectivo',
                max_length=20,
                verbose_name='Método de pago',
            ),
        ),
    ]
