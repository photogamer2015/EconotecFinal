"""
Crea los grupos de permisos del sistema Econotec:

- Administradores: acceso TOTAL al sistema (incluye Reg. Administrativo)
- Tecnicos: ingresos, salidas, clientes e historial
- Asesores: solo gestión de pagos

También crea las categorías de egreso por defecto.

Ejecutar:  python manage.py setup_roles
"""
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand


GRUPOS = ['Administradores', 'Tecnicos', 'Asesores']


class Command(BaseCommand):
    help = 'Crea los grupos Administradores, Tecnicos y Asesores en Econotec.'

    def handle(self, *args, **kwargs):
        for nombre in GRUPOS:
            grupo, created = Group.objects.get_or_create(name=nombre)
            if created:
                self.stdout.write(self.style.SUCCESS(f'  ✓ Grupo "{nombre}" creado.'))
            else:
                self.stdout.write(f'  → Grupo "{nombre}" ya existía.')

        # Crea categorías de egreso por defecto
        from econotec.models import CategoriaEgreso
        defaults = [
            ('Repuestos', '🔧', '#f0ad4e', 1),
            ('Sueldos', '💰', '#1a237e', 2),
            ('Alquiler', '🏠', '#2e7d32', 3),
            ('Servicios básicos', '💡', '#00838f', 4),
            ('Herramientas', '🛠️', '#5d4037', 5),
            ('Marketing', '📣', '#6a1b9a', 6),
            ('Otros', '📦', '#455a64', 99),
        ]
        for nombre, icono, color, orden in defaults:
            cat, created = CategoriaEgreso.objects.get_or_create(
                nombre=nombre,
                defaults={'icono': icono, 'color': color, 'orden': orden},
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f'  ✓ Categoría de egreso "{nombre}" creada.'))

        self.stdout.write(self.style.SUCCESS('\n✅ Roles y datos iniciales listos.'))
        self.stdout.write('')
        self.stdout.write('═══════════════════════════════════════════════════════════════')
        self.stdout.write('  ROLES DEL SISTEMA:')
        self.stdout.write('═══════════════════════════════════════════════════════════════')
        self.stdout.write('  • Administradores → acceso TOTAL al sistema')
        self.stdout.write('  • Tecnicos        → ingresos, salidas, clientes, historial')
        self.stdout.write('  • Asesores        → solo módulo de pagos')
        self.stdout.write('═══════════════════════════════════════════════════════════════')
        self.stdout.write('')
        self.stdout.write(
            'Para asignar usuarios: ve a /admin/auth/user/ → selecciona usuario → '
            'campo "Groups" → añade el grupo correspondiente.'
        )
