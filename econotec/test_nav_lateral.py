"""Barra lateral de apartados (tipo CRM) en pantallas anchas.

- En toda página interna aparece una barra lateral para saltar entre
  apartados sin volver al Inicio; cada rol ve solo sus enlaces.
- El Inicio (bienvenida) queda igual que siempre, sin barra.
- El apartado abierto se marca como activo.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from .permisos import GRUPO_ASISTENTE_CAJA


def enlace_activo(seccion):
    return f'class="nav-lateral-item activa" data-seccion="{seccion}"'


class NavLateralTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(username='RootAdmin', email='a@example.com', password='x')
        self.tecnico = User.objects.create_user(username='yandri', first_name='Yandri')
        self.tecnico.groups.add(Group.objects.get_or_create(name='Tecnicos')[0])
        self.asesora = User.objects.create_user(username='Kimberly')
        self.asesora.groups.add(Group.objects.get_or_create(name='Asesores Comerciales')[0])
        self.caja = User.objects.create_user(username='Melanie')
        # El grupo de la asistente de caja lo crea la migración 0080.
        self.caja.groups.add(Group.objects.get(name=GRUPO_ASISTENTE_CAJA))
        self.sin_rol = User.objects.create_user(username='SinRol')

    def test_tecnico_ve_sus_apartados_y_no_los_del_admin(self):
        self.client.force_login(self.tecnico)
        pagina = self.client.get(reverse('econotec:ingreso_menu'))

        self.assertContains(pagina, 'class="con-nav-lateral"')
        for seccion in ('inicio', 'ingresos', 'ventas', 'listos', 'clientes', 'pagos',
                        'bodegaje', 'donados', 'inventario', 'ranking', 'ayuda'):
            self.assertContains(pagina, f'data-seccion="{seccion}"')
        for nombre in ('venta_menu', 'salida_menu', 'cliente_lista', 'pagos_lista',
                       'admin_activos_bodegaje', 'equipos_administrativos_general',
                       'inventario_menu', 'salida_totales', 'ayuda'):
            self.assertContains(pagina, f'href="{reverse(f"econotec:{nombre}")}"')
        # Lo que su rol no tiene: salidas físicas, seguimiento y Registro Administrativo.
        for seccion in ('salidas-fisicas', 'seguimiento', 'registro'):
            self.assertNotContains(pagina, f'data-seccion="{seccion}"')
        self.assertNotContains(pagina, f'href="{reverse("econotec:admin_dashboard")}"')
        self.assertNotContains(pagina, f'href="{reverse("econotec:seguimiento_pago")}"')
        self.assertNotContains(pagina, f'href="{reverse("econotec:salida_retiros_lista")}"')

    def test_asesora_admin_y_asistente_ven_lo_suyo(self):
        self.client.force_login(self.asesora)
        pagina = self.client.get(reverse('econotec:cliente_lista'))
        self.assertContains(pagina, f'href="{reverse("econotec:salida_retiros_lista")}"')
        self.assertNotContains(pagina, 'data-seccion="registro"')
        self.assertNotContains(pagina, 'data-seccion="seguimiento"')

        self.client.force_login(self.caja)
        pagina = self.client.get(reverse('econotec:cliente_lista'))
        self.assertContains(pagina, f'href="{reverse("econotec:seguimiento_pago")}"')
        self.assertNotContains(pagina, 'data-seccion="registro"')

        self.client.force_login(self.admin)
        pagina = self.client.get(reverse('econotec:cliente_lista'))
        for nombre in ('admin_dashboard', 'admin_equipos_administrativos',
                       'seguimiento_pago', 'salida_retiros_lista'):
            self.assertContains(pagina, f'href="{reverse(f"econotec:{nombre}")}"')
        self.assertNotContains(pagina, f'href="{reverse("econotec:equipos_administrativos_general")}"')

    def test_el_inicio_queda_igual_sin_barra_lateral(self):
        self.client.force_login(self.tecnico)
        inicio = self.client.get(reverse('econotec:bienvenida'))
        self.assertNotContains(inicio, 'nav-lateral')
        self.assertNotContains(inicio, 'con-nav-lateral')

    def test_marca_el_apartado_abierto(self):
        self.client.force_login(self.admin)

        self.assertContains(self.client.get(reverse('econotec:venta_menu')), enlace_activo('ventas'))
        self.assertContains(self.client.get(reverse('econotec:salida_totales')), enlace_activo('ranking'))
        self.assertContains(self.client.get(reverse('econotec:salida_menu')), enlace_activo('listos'))
        self.assertContains(
            self.client.get(reverse('econotec:admin_activos_bodegaje')), enlace_activo('bodegaje'),
        )

        # Seguimiento vive bajo /pagos/, pero marca su propio apartado, no Pagos.
        seguimiento = self.client.get(reverse('econotec:seguimiento_pago'))
        self.assertContains(seguimiento, enlace_activo('seguimiento'))
        self.assertNotContains(seguimiento, enlace_activo('pagos'))

        # El Ranking vive bajo /salidas/, pero no marca Equipos listos.
        ranking = self.client.get(reverse('econotec:salida_totales'))
        self.assertNotContains(ranking, enlace_activo('listos'))

    def test_sin_rol_solo_inicio_e_inventario(self):
        self.client.force_login(self.sin_rol)
        pagina = self.client.get(reverse('econotec:inventario_menu'))
        self.assertContains(pagina, 'data-seccion="inicio"')
        self.assertContains(pagina, enlace_activo('inventario'))
        for seccion in ('ingresos', 'ventas', 'pagos', 'ranking', 'registro', 'ayuda'):
            self.assertNotContains(pagina, f'data-seccion="{seccion}"')

    def test_boton_apartados_para_celular_y_tablet(self):
        self.client.force_login(self.tecnico)
        pagina = self.client.get(reverse('econotec:venta_menu'))
        self.assertContains(pagina, 'id="nav-lateral-abrir"')
        self.assertContains(pagina, 'id="nav-lateral-fondo"')
        # En el Inicio no hay barra ni botón.
        self.assertNotContains(self.client.get(reverse('econotec:bienvenida')), 'nav-lateral-abrir')
