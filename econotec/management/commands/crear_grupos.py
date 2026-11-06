"""
Management command: crea los grupos de roles de Econotec si no existen.

Uso:
    python manage.py crear_grupos

Grupos creados:
  - Administradores   → acceso total
  - Tecnicos          → Ingresos, Salidas, Clientes, Historial, Pagos, Ranking
  - Asesores Comerciales → Ingresos, Salidas, Clientes, Historial, Pagos (SIN Ranking)
  - Asesora - Asistente de caja → lo de la asesora + Seguimiento de pago, egresos e inventario
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group


GRUPOS = [
    'Administradores',
    'Tecnicos',
    'Asesores Comerciales',
    'Asesora - Asistente de caja',
]


class Command(BaseCommand):
    help = 'Crea los grupos de roles de Econotec (Administradores, Tecnicos, Asesores Comerciales, Asesora - Asistente de caja)'

    def handle(self, *args, **options):
        for nombre in GRUPOS:
            grupo, creado = Group.objects.get_or_create(name=nombre)
            if creado:
                self.stdout.write(self.style.SUCCESS(f'✅ Grupo creado: {nombre}'))
            else:
                self.stdout.write(self.style.WARNING(f'⚠️  Ya existe: {nombre}'))
        self.stdout.write(self.style.SUCCESS('\n✓ Listo. Ahora asigna usuarios desde /admin/auth/group/'))
