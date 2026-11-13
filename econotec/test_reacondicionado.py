"""Reacondicionar equipos e Inventario reacondicionado.

- Chatarrización (Bodegaje) → botón «Reacondicionar equipo» con su ventana.
- Donados y Compras → «Cambiar estado»: Chatarrizar o Reacondicionar, sin tocar
  el estado original, el valor pagado ni el egreso de la compra.
- Inventario → elegir Inventario de producto o Inventario reacondicionado.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from .models import (
    Cliente, Egreso, IngresoEquipo, InventarioItem, NotificacionCambioAdmin, SalidaEquipo,
    VentaInventarioItem,
)
from .views import CEDULA_CONSUMIDOR_FINAL, _sincronizar_egreso_compra


class ReacondicionadoBase(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(username='RootAdmin', email='a@example.com', password='x')
        self.tecnico = User.objects.create_user(username='yandri', first_name='Yandri')
        self.tecnico.groups.add(Group.objects.create(name='Tecnicos'))
        self.cliente = Cliente.objects.create(cedula='0912345678', nombres='Osmar Perez')
        self.client.force_login(self.admin)

    def crear_ingreso(self, **extra):
        datos = {
            'sede': 'guayaquil',
            'fecha_ingreso': date.today() - timedelta(days=40),
            'cliente': self.cliente,
            'tipo_equipo': 'impresora',
            'marca': 'Epson',
            'modelo_serie': 'L4160',
            'serie': 'X123',
            'problema_reportado': 'No imprime',
            'registrado_por': self.admin,
            'estado': 'entregado',
        }
        datos.update(extra)
        return IngresoEquipo.objects.create(**datos)

    def crear_chatarrizado(self, **extra):
        ingreso = self.crear_ingreso(**extra)
        SalidaEquipo.objects.create(
            ingreso=ingreso,
            fecha_salida=date.today() - timedelta(days=35),
            estado_reparacion='chatarrerizacion',
            fecha_retiro_real=date.today(),
            tecnico_reparo=self.tecnico,
            valor_final_cobrado=Decimal('0.00'),
            metodo_pago_final='sin_pago',
            registrado_por=self.admin,
        )
        return ingreso

    def datos_reacondicionar(self, **extra):
        datos = {
            'sede': 'guayaquil',
            'ubicacion': 'guayaquil_centro',
            'categoria': 'impresora',
            'marca': 'Epson',
            'modelo': 'L4160',
            'serie': 'X123',
            'observacion': 'Cabezal cambiado, probado.',
            'tecnico_responsable': str(self.tecnico.pk),
            'next': reverse('econotec:admin_activos_bodegaje'),
        }
        datos.update(extra)
        return datos


class InventarioDosLineasTests(ReacondicionadoBase):
    def test_inventario_pregunta_que_inventario_abrir(self):
        inicio = self.client.get(reverse('econotec:inventario_menu'))
        self.assertContains(inicio, 'Inventario de producto')
        self.assertContains(inicio, 'Inventario reacondicionado')
        self.assertContains(inicio, f'href="{reverse("econotec:inventario_producto")}"')
        self.assertContains(inicio, f'href="{reverse("econotec:inventario_reacondicionado")}"')

        rea = self.client.get(reverse('econotec:inventario_reacondicionado'))
        self.assertContains(rea, 'Inventario reacondicionado')
        self.assertContains(rea, 'data-sede="guayaquil"')
        self.assertContains(rea, 'data-sede="quito"')
        self.assertContains(rea, reverse('econotec:inventario_reacondicionado_categoria', kwargs={
            'sede': '__sede__', 'categoria': 'otros-equipos-materiales',
        }))

    def test_rutas_del_inventario_de_producto_no_cambian(self):
        self.assertEqual(
            reverse('econotec:inventario_tabla', kwargs={
                'sede': 'guayaquil', 'categoria': 'impresora', 'tipo': 'impresora-laser',
            }),
            '/inventario/guayaquil/impresora/impresora-laser/',
        )
        self.assertEqual(
            reverse('econotec:inventario_reacondicionado_tabla', kwargs={
                'sede': 'guayaquil', 'categoria': 'impresora', 'tipo': 'impresora',
            }),
            '/inventario/reacondicionado/guayaquil/impresora/impresora/',
        )

    def test_cada_inventario_muestra_solo_sus_equipos(self):
        kwargs = {'sede': 'guayaquil', 'categoria': 'impresora', 'tipo': 'impresora-laser'}
        kwargs_rea = {'sede': 'guayaquil', 'categoria': 'impresora', 'tipo': 'impresora'}
        InventarioItem.objects.create(
            sede='guayaquil', categoria='impresora', tipo='impresora-laser',
            producto='Tóner producto', marca='HP', modelo='85A', ubicacion='guayaquil_norte',
        )
        respuesta = self.client.post(
            reverse('econotec:inventario_reacondicionado_registrar', kwargs=kwargs_rea),
            {
                'producto': 'Impresora reacondicionada', 'marca': 'HP', 'modelo': 'M404',
                'serie': '', 'estado': 'disponible', 'causa_no_disponible': '',
                'cantidad': '1', 'costo': '80.00', 'ubicacion': 'guayaquil_norte', 'observacion': '',
            },
        )
        rea = InventarioItem.objects.get(producto='Impresora reacondicionada')
        self.assertEqual(rea.linea, 'reacondicionado')
        self.assertTrue(rea.codigo.startswith('REA-GYE-'))
        self.assertRedirects(respuesta, reverse('econotec:inventario_reacondicionado_tabla', kwargs=kwargs_rea))

        tabla_producto = self.client.get(reverse('econotec:inventario_tabla', kwargs=kwargs))
        self.assertContains(tabla_producto, 'Tóner producto')
        self.assertNotContains(tabla_producto, 'Impresora reacondicionada')

        tabla_rea = self.client.get(reverse('econotec:inventario_reacondicionado_tabla', kwargs=kwargs_rea))
        self.assertContains(tabla_rea, 'Impresora reacondicionada')
        self.assertNotContains(tabla_rea, 'Tóner producto')
        self.assertContains(tabla_rea, 'INVENTARIO REACONDICIONADO')
        self.assertContains(tabla_rea, reverse('econotec:inventario_reacondicionado_export', kwargs=kwargs_rea))

        detalle = self.client.get(reverse('econotec:inventario_detalle_item', kwargs={'codigo': rea.codigo}))
        self.assertContains(detalle, f'href="{reverse("econotec:inventario_reacondicionado")}"')
        self.assertContains(detalle, reverse('econotec:inventario_reacondicionado_tabla', kwargs=kwargs_rea))

    def test_ventas_solo_ofrecen_el_inventario_de_producto(self):
        InventarioItem.objects.create(
            sede='guayaquil', categoria='impresora', tipo='impresora-laser',
            producto='Tóner producto', marca='HP', modelo='85A', ubicacion='guayaquil_norte',
        )
        InventarioItem.objects.create(
            linea='reacondicionado', sede='guayaquil', categoria='impresora', tipo='impresora',
            producto='Impresora reacondicionada', marca='HP', modelo='M404', ubicacion='guayaquil_norte',
        )
        datos = self.client.get(reverse('econotec:venta_inventario_catalogo')).json()
        productos = [item['producto'] for item in datos['items']]
        self.assertIn('Tóner producto', productos)
        self.assertNotIn('Impresora reacondicionada', productos)


class ReacondicionarDesdeChatarrizacionTests(ReacondicionadoBase):
    def test_boton_y_ventana_para_todos_los_roles(self):
        asesora = get_user_model().objects.create_user(username='Kimberly')
        asesora.groups.add(Group.objects.create(name='Asesores Comerciales'))
        sin_rol = get_user_model().objects.create_user(username='SinRol')
        uno, dos = self.crear_chatarrizado(), self.crear_chatarrizado(marca='HP')

        for usuario, ingreso in ((self.tecnico, uno), (asesora, dos)):
            with self.subTest(usuario=usuario.username):
                url = reverse('econotec:equipo_reacondicionar', kwargs={'pk': ingreso.pk})
                self.client.force_login(usuario)
                pagina = self.client.get(reverse('econotec:admin_activos_bodegaje'))
                self.assertContains(pagina, '🔧 Reacondicionar equipo')
                self.assertContains(pagina, f'data-rea-url="{url}"')
                self.assertContains(pagina, 'id="rea-modal"')

                self.client.post(url, self.datos_reacondicionar(marca=ingreso.marca))
                self.assertTrue(InventarioItem.objects.filter(ingreso_origen=ingreso).exists())

        # Un usuario sin rol no puede reacondicionar.
        tres = self.crear_chatarrizado(marca='Canon')
        self.client.force_login(sin_rol)
        respuesta = self.client.post(
            reverse('econotec:equipo_reacondicionar', kwargs={'pk': tres.pk}), self.datos_reacondicionar(),
        )
        self.assertRedirects(respuesta, reverse('econotec:bienvenida'), fetch_redirect_response=False)
        self.assertFalse(InventarioItem.objects.filter(ingreso_origen=tres).exists())

    def test_reacondicionar_crea_la_ficha_y_marca_la_fila(self):
        ingreso = self.crear_chatarrizado()
        url = reverse('econotec:equipo_reacondicionar', kwargs={'pk': ingreso.pk})

        respuesta = self.client.post(url, self.datos_reacondicionar())
        self.assertRedirects(respuesta, reverse('econotec:admin_activos_bodegaje'))

        item = InventarioItem.objects.get()
        self.assertEqual(item.linea, 'reacondicionado')
        self.assertEqual(item.ingreso_origen, ingreso)
        self.assertEqual((item.sede, item.ubicacion), ('guayaquil', 'guayaquil_centro'))
        self.assertEqual((item.categoria, item.tipo), ('impresora', 'impresora'))
        self.assertEqual((item.marca, item.modelo, item.serie), ('Epson', 'L4160', 'X123'))
        self.assertEqual(item.producto, 'Impresora Epson L4160')
        self.assertEqual(item.cantidad, 1)
        self.assertEqual(item.observacion, 'Cabezal cambiado, probado.')

        pagina = self.client.get(reverse('econotec:admin_activos_bodegaje'))
        self.assertContains(pagina, '✅ Reacondicionado')
        self.assertContains(pagina, reverse('econotec:inventario_detalle_item', kwargs={'codigo': item.codigo}))
        self.assertNotContains(pagina, f'data-rea-url="{url}"')
        self.assertEqual(pagina.context['count_chatarrerizacion'], 1)

        # No se puede reacondicionar dos veces.
        self.client.post(url, self.datos_reacondicionar())
        self.assertEqual(InventarioItem.objects.count(), 1)

    def test_valida_ubicacion_tipo_y_sede(self):
        ingreso = self.crear_chatarrizado()
        url = reverse('econotec:equipo_reacondicionar', kwargs={'pk': ingreso.pk})

        self.client.post(url, self.datos_reacondicionar(ubicacion=''))
        self.client.post(url, self.datos_reacondicionar(categoria='impresora-laser'))
        self.client.post(url, self.datos_reacondicionar(sede='ventas'))
        self.client.post(url, self.datos_reacondicionar(marca='  '))
        self.assertFalse(InventarioItem.objects.exists())

        # Quito tiene una sola ubicación: se pone sola.
        self.client.post(url, self.datos_reacondicionar(sede='quito', ubicacion='guayaquil_norte'))
        item = InventarioItem.objects.get()
        self.assertEqual((item.sede, item.ubicacion), ('quito', 'quito'))
        self.assertTrue(item.codigo.startswith('REA-UIO-'))

    def test_no_reacondiciona_equipos_que_no_estan_chatarrizados(self):
        ingreso = self.crear_ingreso(estado='en_reparacion', subestado_reparacion='en_reparacion')
        self.client.post(
            reverse('econotec:equipo_reacondicionar', kwargs={'pk': ingreso.pk}),
            self.datos_reacondicionar(),
        )
        self.assertFalse(InventarioItem.objects.exists())


class DonadosComprasCambiarEstadoTests(ReacondicionadoBase):
    def crear_compra(self):
        compra = self.crear_ingreso(
            estado='equipo_a_comprar',
            tipo_equipo='laptop',
            marca='Lenovo',
            modelo_serie='ThinkPad',
            valor_acordado=Decimal('30.00'),
            compra_metodo_pago='efectivo',
        )
        _sincronizar_egreso_compra(compra, self.admin)
        return compra

    def test_lista_admin_muestra_cambiar_estado(self):
        donado = self.crear_ingreso(estado='donado')
        pagina = self.client.get(reverse('econotec:admin_equipos_administrativos'))
        self.assertContains(pagina, '🔄 Cambiar estado')
        self.assertContains(pagina, reverse('econotec:equipo_administrativo_chatarrizar', kwargs={'pk': donado.pk}))
        self.assertContains(pagina, 'id="rea-modal"')

        # Cualquier rol ve el apartado y puede cambiar el estado.
        self.client.force_login(self.tecnico)
        general = self.client.get(reverse('econotec:equipos_administrativos_general'))
        self.assertContains(general, donado.codigo_equipo)
        self.assertContains(general, '🔄 Cambiar estado')
        self.assertContains(general, 'id="rea-modal"')
        self.assertContains(general, 'data-avisa-admin="no"')

    def test_valor_de_la_compra_se_muestra_como_egreso(self):
        self.crear_compra()
        lista = self.client.get(reverse('econotec:admin_equipos_administrativos'))
        self.assertContains(lista, 'class="es-egreso"')
        self.assertContains(lista, '−$30,00')

    def test_otro_rol_cambia_compra_y_se_avisa_al_admin(self):
        compra = self.crear_compra()
        self.client.force_login(self.tecnico)
        general = self.client.get(reverse('econotec:equipos_administrativos_general'))
        self.assertContains(general, 'data-avisa-admin="si"')

        self.client.post(
            reverse('econotec:equipo_administrativo_chatarrizar', kwargs={'pk': compra.pk}),
            {'next': reverse('econotec:equipos_administrativos_general')},
        )
        compra.refresh_from_db()
        self.assertIsNotNone(compra.fecha_chatarrizacion)
        self.assertEqual(compra.estado, 'equipo_a_comprar')
        aviso = NotificacionCambioAdmin.objects.get(tipo='compra_estado')
        self.assertEqual(aviso.ingreso, compra)
        self.assertEqual(aviso.creado_por, self.tecnico)
        self.assertIn('Envió a chatarrización', aviso.mensaje)
        self.assertIn('$30,00', aviso.mensaje)

        self.client.post(
            reverse('econotec:equipo_reacondicionar', kwargs={'pk': compra.pk}),
            self.datos_reacondicionar(categoria='computadora'),
        )
        self.assertTrue(InventarioItem.objects.filter(ingreso_origen=compra).exists())
        avisos = NotificacionCambioAdmin.objects.filter(tipo='compra_estado')
        self.assertEqual(avisos.count(), 2)
        self.assertTrue(any('Reacondicionó' in a.mensaje for a in avisos))

    def test_donado_y_admin_no_generan_aviso(self):
        donado = self.crear_ingreso(estado='donado')
        compra = self.crear_compra()
        # El admin cambia una compra: no se avisa a sí mismo.
        self.client.post(reverse('econotec:equipo_administrativo_chatarrizar', kwargs={'pk': compra.pk}))
        # Un técnico cambia un donado: no hubo pago, no hay aviso.
        self.client.force_login(self.tecnico)
        self.client.post(reverse('econotec:equipo_administrativo_chatarrizar', kwargs={'pk': donado.pk}))
        donado.refresh_from_db()
        self.assertIsNotNone(donado.fecha_chatarrizacion)
        self.assertFalse(NotificacionCambioAdmin.objects.filter(tipo='compra_estado').exists())

    def test_chatarrizar_compra_no_toca_estado_ni_egreso(self):
        compra = self.crear_compra()
        egreso = Egreso.objects.get(ingreso_compra=compra)

        respuesta = self.client.post(
            reverse('econotec:equipo_administrativo_chatarrizar', kwargs={'pk': compra.pk}),
            {'next': reverse('econotec:admin_equipos_administrativos')},
        )
        self.assertRedirects(respuesta, reverse('econotec:admin_equipos_administrativos'))

        compra.refresh_from_db()
        self.assertEqual(compra.estado, 'equipo_a_comprar')
        self.assertEqual(compra.valor_acordado, Decimal('30.00'))
        self.assertIsNotNone(compra.fecha_chatarrizacion)
        egreso.refresh_from_db()
        self.assertEqual(egreso.monto, Decimal('30.00'))
        self.assertEqual(egreso.ingreso_compra_id, compra.pk)

        lista = self.client.get(reverse('econotec:admin_equipos_administrativos'))
        self.assertContains(lista, '♻️ Chatarrizado')
        self.assertContains(lista, 'Era: Equipo a comprar')
        self.assertContains(lista, 'data-chatarrizado="si"')
        self.assertEqual(lista.context['resumen']['compras'], 1)

        # Aparece en «Equipos en Chatarrización» y desde ahí se puede reacondicionar.
        bodegaje = self.client.get(reverse('econotec:admin_activos_bodegaje'))
        self.assertContains(bodegaje, 'Equipo comprado')
        self.assertContains(bodegaje, reverse('econotec:equipo_reacondicionar', kwargs={'pk': compra.pk}))

        # Chatarrizar dos veces no cambia nada.
        fecha = compra.fecha_chatarrizacion
        self.client.post(reverse('econotec:equipo_administrativo_chatarrizar', kwargs={'pk': compra.pk}))
        compra.refresh_from_db()
        self.assertEqual(compra.fecha_chatarrizacion, fecha)

    def test_reacondicionar_donado_directo(self):
        donado = self.crear_ingreso(estado='donado', tipo_equipo='celular', marca='Samsung', modelo_serie='A10')
        self.client.post(
            reverse('econotec:equipo_reacondicionar', kwargs={'pk': donado.pk}),
            self.datos_reacondicionar(
                categoria='celular', marca='Samsung', modelo='A10',
                next=reverse('econotec:admin_equipos_administrativos'),
            ),
        )
        item = InventarioItem.objects.get(ingreso_origen=donado)
        self.assertEqual((item.categoria, item.tipo, item.linea), ('celular', 'celular', 'reacondicionado'))
        donado.refresh_from_db()
        self.assertEqual(donado.estado, 'donado')

        lista = self.client.get(reverse('econotec:admin_equipos_administrativos'))
        self.assertContains(lista, '🔧 Reacondicionado')
        self.assertContains(lista, 'Era: Donado')
        self.assertNotContains(lista, '🔄 Cambiar estado')

    def test_tarjeta_del_inicio_para_todos_los_roles(self):
        asesora = get_user_model().objects.create_user(username='Kimberly')
        asesora.groups.add(Group.objects.create(name='Asesores Comerciales'))
        general = reverse('econotec:equipos_administrativos_general')
        for usuario in (self.tecnico, asesora):
            with self.subTest(usuario=usuario.username):
                self.client.force_login(usuario)
                inicio = self.client.get(reverse('econotec:bienvenida'))
                self.assertContains(inicio, 'Donados / Equipos a comprar')
                self.assertContains(inicio, f'href="{general}"')
                self.assertEqual(self.client.get(general).status_code, 200)
        self.client.force_login(self.admin)
        inicio = self.client.get(reverse('econotec:bienvenida'))
        self.assertContains(inicio, f'href="{reverse("econotec:admin_equipos_administrativos")}" class="card-box"')

    def test_no_chatarriza_equipos_de_reparacion(self):
        ingreso = self.crear_ingreso(estado='en_reparacion', subestado_reparacion='en_reparacion')
        self.client.post(reverse('econotec:equipo_administrativo_chatarrizar', kwargs={'pk': ingreso.pk}))
        ingreso.refresh_from_db()
        self.assertIsNone(ingreso.fecha_chatarrizacion)


class VentaReacondicionadoYClienteOpcionalTests(ReacondicionadoBase):
    def setUp(self):
        super().setUp()
        self.producto = InventarioItem.objects.create(
            sede='guayaquil', categoria='impresora', tipo='impresora-laser',
            producto='Tóner producto', marca='HP', modelo='85A', ubicacion='guayaquil_norte',
            cantidad=5, costo=Decimal('20.00'),
        )
        self.equipo = InventarioItem.objects.create(
            linea='reacondicionado', sede='guayaquil', categoria='impresora', tipo='impresora',
            producto='Impresora reacondicionada', marca='HP', modelo='M404', ubicacion='guayaquil_norte',
            cantidad=1, costo=Decimal('80.00'),
        )
        asesora = get_user_model().objects.create_user(username='Kimberly')
        asesora.groups.add(Group.objects.create(name='Asesores Comerciales'))

    def datos_venta(self, item, **extra):
        import json
        datos = {
            'ing-fecha_ingreso': date.today().isoformat(),
            'ing-tecnico_encargado': str(self.tecnico.pk),
            'ing-asesor_comercial': 'Kimberly',
            'ing-tipo_equipo': 'otro',
            'ing-tipo_equipo_otro': 'Venta',
            'ing-marca': 'N/A',
            'ing-modelo_serie': 'N/A',
            'ing-accesorios_entregados': 'Ninguno',
            'ing-problema_reportado': 'Venta de mostrador',
            'ing-valor_acordado': '80.00',
            'ing-diagnostico_inmediato': 'no',
            'ing-estado': 'entregado',
            'ing-subestado_entregado': 'con_solucion',
            'ing-firma_cliente_opcion': 'no',
            'venta_tipo_pago': 'completo',
            'venta_metodo_pago': 'efectivo',
            'inventario_seleccionado': json.dumps([{'item_id': item.pk, 'cantidad': 1, 'observacion': ''}]),
            'cli-cedula': '0911111111',
            'cli-nombres': 'Ana Ruiz',
            'cli-sector': 'norte',
        }
        datos.update(extra)
        return datos

    def test_menu_ofrece_producto_o_equipo_reacondicionado(self):
        menu = self.client.get(reverse('econotec:venta_menu'))
        self.assertContains(menu, 'Vender producto')
        self.assertContains(menu, 'Vender equipo reacondicionado')
        self.assertContains(menu, reverse('econotec:venta_registrar_reacondicionado'))

        formulario = self.client.get(reverse('econotec:venta_registrar_reacondicionado'))
        self.assertContains(formulario, 'Nueva Venta de Equipo Reacondicionado')
        self.assertContains(formulario, 'params.set(\'linea\', "reacondicionado")')
        self.assertContains(formulario, '¿Aplica dato del cliente?')
        producto = self.client.get(reverse('econotec:venta_registrar'))
        self.assertContains(producto, 'params.set(\'linea\', "producto")')

    def test_catalogo_separa_por_inventario(self):
        url = reverse('econotec:venta_inventario_catalogo')
        rea = [i['producto'] for i in self.client.get(url, {'linea': 'reacondicionado'}).json()['items']]
        self.assertEqual(rea, ['Impresora reacondicionada'])
        prod = [i['producto'] for i in self.client.get(url).json()['items']]
        self.assertEqual(prod, ['Tóner producto'])

    def test_vender_reacondicionado_descuenta_su_inventario(self):
        respuesta = self.client.post(
            reverse('econotec:venta_registrar_reacondicionado'), self.datos_venta(self.equipo),
        )
        self.assertEqual(respuesta.status_code, 302, respuesta.context and respuesta.context['ing_form'].errors)
        venta = IngresoEquipo.objects.get(sede='ventas')
        self.assertEqual(venta.cliente.nombres, 'Ana Ruiz')
        self.equipo.refresh_from_db()
        self.producto.refresh_from_db()
        self.assertEqual(self.equipo.cantidad, 0)
        self.assertEqual(self.producto.cantidad, 5)
        self.assertEqual(VentaInventarioItem.objects.get(venta=venta).inventario_item, self.equipo)

        editar = self.client.get(reverse('econotec:venta_editar', kwargs={'pk': venta.pk}))
        self.assertContains(editar, 'params.set(\'linea\', "reacondicionado")')

    def test_no_mezcla_inventarios(self):
        respuesta = self.client.post(
            reverse('econotec:venta_registrar_reacondicionado'), self.datos_venta(self.producto),
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(IngresoEquipo.objects.filter(sede='ventas').exists())
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.cantidad, 5)

    def test_venta_sin_datos_del_cliente_va_a_consumidor_final(self):
        datos = self.datos_venta(self.producto, venta_aplica_cliente='no')
        for campo in ('cli-cedula', 'cli-nombres', 'cli-sector'):
            datos.pop(campo)
        respuesta = self.client.post(reverse('econotec:venta_registrar'), datos)
        self.assertEqual(respuesta.status_code, 302, respuesta.context and respuesta.context['ing_form'].errors)
        venta = IngresoEquipo.objects.get(sede='ventas')
        self.assertEqual(venta.cliente.cedula, CEDULA_CONSUMIDOR_FINAL)
        self.assertEqual(venta.cliente.nombres, 'Consumidor final')

        editar = self.client.get(reverse('econotec:venta_editar', kwargs={'pk': venta.pk}))
        self.assertContains(editar, 'name="venta_aplica_cliente" value="no" checked')

        # Al editar y poner datos, se usa el cliente real y «Consumidor final» no se toca.
        datos_editar = self.datos_venta(self.producto, venta_aplica_cliente='si')
        self.client.post(reverse('econotec:venta_editar', kwargs={'pk': venta.pk}), datos_editar)
        venta.refresh_from_db()
        self.assertEqual(venta.cliente.nombres, 'Ana Ruiz')
        self.assertEqual(Cliente.objects.get(cedula=CEDULA_CONSUMIDOR_FINAL).nombres, 'Consumidor final')

    def test_con_si_el_cliente_sigue_siendo_obligatorio(self):
        datos = self.datos_venta(self.producto, venta_aplica_cliente='si')
        datos['cli-cedula'] = ''
        respuesta = self.client.post(reverse('econotec:venta_registrar'), datos)
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(IngresoEquipo.objects.filter(sede='ventas').exists())


class ReacondicionadoSinSubtiposTests(ReacondicionadoBase):
    """El inventario reacondicionado no se divide en láser/inyección ni PC/laptops."""

    def test_categoria_va_directo_a_una_sola_tabla(self):
        for categoria in ('impresora', 'computadora', 'consola'):
            respuesta = self.client.get(reverse('econotec:inventario_reacondicionado_categoria', kwargs={
                'sede': 'guayaquil', 'categoria': categoria,
            }))
            self.assertRedirects(respuesta, reverse('econotec:inventario_reacondicionado_tabla', kwargs={
                'sede': 'guayaquil', 'categoria': categoria, 'tipo': categoria,
            }))
        tabla = self.client.get(reverse('econotec:inventario_reacondicionado_tabla', kwargs={
            'sede': 'guayaquil', 'categoria': 'impresora', 'tipo': 'impresora',
        }))
        self.assertNotContains(tabla, 'Ver tipos')
        self.assertNotContains(tabla, 'Impresora Laser')
        # Los subtipos ya no existen en el reacondicionado.
        vieja = self.client.get(reverse('econotec:inventario_reacondicionado_tabla', kwargs={
            'sede': 'guayaquil', 'categoria': 'impresora', 'tipo': 'impresora-laser',
        }))
        self.assertEqual(vieja.status_code, 302)

    def test_inventario_de_producto_sigue_dividido(self):
        respuesta = self.client.get(reverse('econotec:inventario_categoria', kwargs={
            'sede': 'guayaquil', 'categoria': 'impresora',
        }))
        self.assertContains(respuesta, 'Impresora Laser')
        self.assertContains(respuesta, 'Impresora Inyección')

    def test_ventana_pide_categoria_y_laser_e_inyeccion_caen_juntas(self):
        uno = self.crear_chatarrizado()
        dos = self.crear_chatarrizado(marca='HP', modelo_serie='M404')
        pagina = self.client.get(reverse('econotec:admin_activos_bodegaje'))
        self.assertContains(pagina, 'name="categoria"')
        self.assertNotContains(pagina, 'Impresora Inyección')
        for ingreso in (uno, dos):
            self.client.post(
                reverse('econotec:equipo_reacondicionar', kwargs={'pk': ingreso.pk}),
                self.datos_reacondicionar(marca=ingreso.marca, modelo=ingreso.modelo_serie),
            )
        tabla = self.client.get(reverse('econotec:inventario_reacondicionado_tabla', kwargs={
            'sede': 'guayaquil', 'categoria': 'impresora', 'tipo': 'impresora',
        }))
        self.assertEqual(tabla.context['total_general'], 2)

    def test_venta_de_reacondicionado_no_pide_subtipo(self):
        formulario = self.client.get(reverse('econotec:venta_registrar_reacondicionado'))
        categorias = {c['slug']: c for c in formulario.context['venta_inventario_categorias_json']}
        self.assertEqual(categorias['impresora']['tipos'], [{'slug': 'impresora', 'nombre': 'Impresora'}])
        producto = self.client.get(reverse('econotec:venta_registrar'))
        categorias = {c['slug']: c for c in producto.context['venta_inventario_categorias_json']}
        self.assertEqual(len(categorias['impresora']['tipos']), 2)

    def test_migracion_une_los_subtipos_ya_guardados(self):
        from importlib import import_module
        from django.apps import apps
        viejo = InventarioItem.objects.create(
            linea='reacondicionado', sede='guayaquil', categoria='impresora', tipo='impresora-laser',
            producto='Impresora vieja', marca='Epson', modelo='L4160', ubicacion='guayaquil_norte',
        )
        producto = InventarioItem.objects.create(
            sede='guayaquil', categoria='impresora', tipo='impresora-laser',
            producto='Tóner', marca='HP', modelo='85A', ubicacion='guayaquil_norte',
        )
        import_module('econotec.migrations.0083_reacondicionado_sin_subtipos').unir_subtipos(apps, None)
        viejo.refresh_from_db()
        producto.refresh_from_db()
        self.assertEqual(viejo.tipo, 'impresora')
        self.assertEqual(producto.tipo, 'impresora-laser')


class PuntosReacondicionadoTests(ReacondicionadoBase):
    """El botón «Reacondicionar» da +3 puntos al técnico responsable elegido en su ventana."""

    def setUp(self):
        super().setUp()
        self.otro = get_user_model().objects.create_user(
            username='carlos', first_name='Carlos', last_name='Mora',
        )
        self.otro.groups.add(Group.objects.get(name='Tecnicos'))

    def reacondicionar(self, ingreso, tecnico=None, **extra):
        datos = self.datos_reacondicionar(**extra)
        if tecnico is not None:
            datos['tecnico_responsable'] = str(tecnico.pk)
        return self.client.post(
            reverse('econotec:equipo_reacondicionar', kwargs={'pk': ingreso.pk}), datos, follow=True,
        )

    def puntos(self, usuario):
        from .views import puntaje_tecnico
        return puntaje_tecnico(usuario)

    def ranking_del_mes(self):
        hoy = date.today()
        respuesta = self.client.get(reverse('econotec:salida_totales'), {
            'desde': hoy.replace(day=1).isoformat(), 'hasta': hoy.isoformat(),
        })
        return {fila['tecnico_id']: fila for fila in respuesta.context['ranking']}

    def test_ventana_pide_el_tecnico_responsable(self):
        self.crear_chatarrizado()
        pagina = self.client.get(reverse('econotec:admin_activos_bodegaje'))
        self.assertContains(pagina, 'name="tecnico_responsable"')
        self.assertContains(pagina, 'Técnico responsable de la reparación')
        self.assertContains(pagina, f'<option value="{self.otro.pk}">Carlos Mora</option>', html=True)
        self.assertContains(pagina, '+3 puntos en el Ranking de Técnicos')

    def test_sin_tecnico_valido_no_reacondiciona(self):
        ingreso = self.crear_chatarrizado()
        respuesta = self.reacondicionar(ingreso, tecnico_responsable='')
        self.assertContains(respuesta, 'Elige el técnico responsable de reparar el equipo.')
        # Un usuario que no es técnico, un número que no existe o un texto tampoco valen.
        for valor in (str(self.admin.pk), '999999', 'abc', '١'):
            self.reacondicionar(ingreso, tecnico_responsable=valor)
        self.assertFalse(InventarioItem.objects.exists())
        ingreso.refresh_from_db()
        self.assertIsNone(ingreso.tecnico_reacondicionado)
        self.assertIsNone(ingreso.fecha_reacondicionado)

    def test_da_3_puntos_al_tecnico_elegido(self):
        # El que reparó en la salida (chatarrización = 0) no es el que reacondicionó.
        ingreso = self.crear_chatarrizado()
        self.assertEqual(self.puntos(self.otro)['total'], 0)

        respuesta = self.reacondicionar(ingreso, tecnico=self.otro)

        self.assertContains(respuesta, '+3 puntos para Carlos Mora.')
        ingreso.refresh_from_db()
        self.assertEqual(ingreso.tecnico_reacondicionado, self.otro)
        self.assertIsNotNone(ingreso.fecha_reacondicionado)
        self.assertEqual(ingreso.estado, 'entregado')
        perfil = self.puntos(self.otro)
        self.assertEqual((perfil['total'], perfil['reacondicionados']), (3, 1))
        self.assertEqual(self.puntos(self.tecnico)['total'], 0)

    def test_donados_y_compras_tambien_dan_puntos(self):
        donado = self.crear_ingreso(estado='donado')
        self.client.force_login(self.tecnico)
        self.reacondicionar(donado, tecnico=self.tecnico, next=reverse('econotec:admin_equipos_administrativos'))
        self.assertTrue(InventarioItem.objects.filter(ingreso_origen=donado).exists())
        self.assertEqual(self.puntos(self.tecnico)['total'], 3)

    def test_ranking_suma_y_explica_los_puntos(self):
        # El técnico ya tiene un reparado (+3) en el mes; el reacondicionado suma otros 3.
        reparado = self.crear_ingreso(estado='entregado')
        SalidaEquipo.objects.create(
            ingreso=reparado, fecha_salida=date.today(), estado_reparacion='retirado',
            tecnico_reparo=self.otro, valor_final_cobrado=Decimal('0.00'),
            metodo_pago_final='sin_pago', registrado_por=self.admin,
        )
        self.reacondicionar(self.crear_chatarrizado(), tecnico=self.otro)

        fila = self.ranking_del_mes()[self.otro.pk]
        self.assertEqual(fila['puntos'], 6)
        self.assertEqual(fila['reacondicionados'], 1)
        self.assertIn(
            {'etiqueta': 'Equipo reacondicionado (cuenta como reparado)', 'cantidad': 1, 'unitario': 3, 'subtotal': 3},
            fila['puntos_detalle'],
        )
        # El reacondicionado cuenta como un equipo reparado más (sin duplicar puntos).
        self.assertEqual((fila['reparados'], fila['num_equipos'], fila['salidas_positivas']), (2, 2, 2))
        self.assertEqual(fila['efectividad'], 100.0)

        from .views import ranking_con_dinero
        hoy = date.today()
        _registros, filas, _resumen = ranking_con_dinero(hoy.replace(day=1).isoformat(), hoy.isoformat())
        self.assertEqual({f['tecnico_id']: f['puntos'] for f in filas}[self.otro.pk], 6)

    def test_tecnico_solo_con_reacondicionados_aparece_en_el_ranking(self):
        self.reacondicionar(self.crear_chatarrizado(), tecnico=self.otro)
        fila = self.ranking_del_mes()[self.otro.pk]
        # Cuenta como 1 equipo reparado, sin salida de la oficina.
        self.assertEqual((fila['nombre'], fila['puntos'], fila['num_equipos']), ('Carlos Mora', 3, 1))
        self.assertEqual((fila['reparados'], fila['entregados'], fila['pendientes']), (1, 0, 0))
        self.assertIsNotNone(fila['puesto'])

    def test_reacondicionado_cuenta_como_reparado_en_tarjetas_perfil_y_cuadres(self):
        reparado = self.crear_ingreso(estado='entregado')
        SalidaEquipo.objects.create(
            ingreso=reparado, fecha_salida=date.today(), estado_reparacion='retirado',
            fecha_retiro_real=date.today(), tecnico_reparo=self.otro,
            valor_final_cobrado=Decimal('0.00'), metodo_pago_final='sin_pago', registrado_por=self.admin,
        )
        self.reacondicionar(self.crear_chatarrizado(), tecnico=self.otro)
        hoy = date.today()
        respuesta = self.client.get(reverse('econotec:salida_totales'), {
            'desde': hoy.replace(day=1).isoformat(), 'hasta': hoy.isoformat(),
        })
        resumen = respuesta.context['resumen_salidas']
        # 1 reparado con salida + 1 reacondicionado (el chatarrizado del equipo no suma ni resta).
        self.assertEqual(resumen['resultados']['reparado'], 2)
        self.assertEqual(resumen['reparados_extra'], 1)
        # Todas las cuentas de la Guía de los totales siguen cuadrando.
        self.assertEqual(
            [c['titulo'] for c in respuesta.context['comprobaciones'] if not c['cuadra']], [],
        )
        # Mi perfil: 2 equipos buenos; puntos 3 + 3 (sin duplicar).
        perfil = self.puntos(self.otro)
        self.assertEqual((perfil['salidas_buenas'], perfil['total']), (2, 6))

    def test_cuenta_en_el_mes_en_que_se_reacondiciono(self):
        ingreso = self.crear_chatarrizado()
        self.reacondicionar(ingreso, tecnico=self.otro)
        from django.utils import timezone
        IngresoEquipo.objects.filter(pk=ingreso.pk).update(
            fecha_reacondicionado=timezone.now() - timedelta(days=60),
        )
        self.assertNotIn(self.otro.pk, self.ranking_del_mes())
        # Mi perfil cuenta todo el historial.
        self.assertEqual(self.puntos(self.otro)['total'], 3)

    def test_volver_a_reacondicionar_no_duplica_los_puntos(self):
        ingreso = self.crear_chatarrizado()
        self.reacondicionar(ingreso, tecnico=self.tecnico)
        # Se borra la ficha por error y se reacondiciona otra vez con otro técnico.
        InventarioItem.objects.filter(ingreso_origen=ingreso).delete()
        self.reacondicionar(ingreso, tecnico=self.otro)
        self.assertEqual(InventarioItem.objects.filter(ingreso_origen=ingreso).count(), 1)
        self.assertEqual(self.puntos(self.tecnico)['total'], 0)
        self.assertEqual(self.puntos(self.otro)['total'], 3)

    def test_vender_o_borrar_la_ficha_no_quita_los_puntos(self):
        ingreso = self.crear_chatarrizado()
        self.reacondicionar(ingreso, tecnico=self.otro)
        item = InventarioItem.objects.get(ingreso_origen=ingreso)
        InventarioItem.objects.filter(pk=item.pk).update(cantidad=0)
        self.assertEqual(self.puntos(self.otro)['total'], 3)
        item.delete()
        self.assertEqual(self.puntos(self.otro)['total'], 3)

    def test_registrar_un_reacondicionado_a_mano_no_da_puntos(self):
        # Solo el botón «Reacondicionar» da puntos; una ficha creada en el
        # inventario no tiene técnico responsable.
        InventarioItem.objects.create(
            linea='reacondicionado', sede='guayaquil', categoria='impresora', tipo='impresora',
            producto='Impresora', marca='HP', modelo='M404', ubicacion='guayaquil_norte',
            registrado_por=self.tecnico,
        )
        self.assertEqual(self.puntos(self.tecnico)['total'], 0)
        self.assertNotIn(self.tecnico.pk, self.ranking_del_mes())

    def test_reiniciar_el_perfil_deja_fuera_los_anteriores(self):
        from django.utils import timezone
        from .models import UsuarioActividad
        self.reacondicionar(self.crear_chatarrizado(), tecnico=self.otro)
        UsuarioActividad.objects.update_or_create(
            user=self.otro, defaults={'fecha_reinicio_perfil': timezone.now()},
        )
        self.otro.refresh_from_db()
        self.assertEqual(self.puntos(self.otro)['total'], 0)
        self.reacondicionar(self.crear_chatarrizado(marca='HP'), tecnico=self.otro)
        self.otro.refresh_from_db()
        self.assertEqual(self.puntos(self.otro)['total'], 3)
