"""Finalizar un equipo a domicilio.

Si el ingreso es «A domicilio: Sí», Finalizar equipo ofrece:
- Reparado — equipo finalizado (a domicilio): valor acordado + domicilio.
- No se pudo / No quiso reparar (a domicilio): solo el valor a domicilio (editable).
- Equipo llevarlo a la oficina: los estados de siempre, con la lógica de siempre.
En los tres a domicilio se elige Pago ahora o Pago después; el equipo queda con
el cliente (sin pendiente de retiro ni bodegaje). El PDF y el WhatsApp dicen
«a domicilio» y muestran lo pagado y el saldo.
"""
from datetime import date
from decimal import Decimal
from urllib.parse import unquote

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from .alertas import whatsapp_link_equipo_listo
from .forms import SalidaEquipoForm
from .models import Cliente, IngresoEquipo, NotificacionAsesora, SalidaEquipo
from .views_print import generar_salida_pdf_bytes


class SalidaDomicilioTests(TestCase):

    def setUp(self):
        User = get_user_model()
        tecnicos = Group.objects.create(name='Tecnicos')
        asesores = Group.objects.create(name='Asesores')
        self.tecnico = User.objects.create_user(username='yandri', first_name='Yandri')
        self.tecnico.groups.add(tecnicos)
        self.asesora = User.objects.create_user(username='kimberly', first_name='Kimberly')
        self.asesora.groups.add(asesores)
        self.cliente = Cliente.objects.create(
            cedula='0912345678', nombres='Ana Domicilio', whatsapp='0991234567',
            correo='ana@example.com', sector='norte',
        )
        self.client.force_login(self.tecnico)

    def crear_ingreso(self, valor=Decimal('40.00'), a_domicilio='si', anticipo=Decimal('0.00')):
        return IngresoEquipo.objects.create(
            sede='guayaquil', asesor_comercial='Kimberly', fecha_ingreso=date.today(),
            cliente=self.cliente, tipo_equipo='laptop', marca='HP', modelo_serie='Elitebook',
            problema_reportado='No enciende', valor_acordado=valor,
            a_domicilio=a_domicilio, valor_domicilio=Decimal('10.00'),
            abono_anticipo=anticipo, anticipo_metodo='efectivo' if anticipo else '',
            tecnico_encargado=self.tecnico, estado='en_reparacion',
            subestado_reparacion='en_reparacion', registrado_por=self.tecnico,
        )

    def datos(self, estado, **extra):
        datos = {
            'fecha_salida': date.today().isoformat(),
            'estado_reparacion': estado,
            'tecnico_reparo': str(self.tecnico.pk),
            'reporte_tecnico': 'Se cambió el cargador.',
            'observaciones': '',
            'aplica_valor_acordado_adicional': 'no',
            'valor_final_cobrado': '0',
            'metodo_pago_final': 'sin_pago',
            'numero_recibo': '', 'banco': '', 'banco_otro': '', 'tarjeta_app': '',
            'comprobante_url': '',
            'monto_1': '', 'metodo_1': '', 'banco_1': '',
            'monto_2': '', 'metodo_2': '', 'banco_2': '',
            'factura_realizada': 'no', 'factura_nombres': '', 'factura_cedula': '',
            'factura_correo': '',
            'asesora_notificacion': '', 'mensaje_notificacion': '',
            'valor_domicilio_cobro': '10.00',
        }
        datos.update(extra)
        return datos

    def registrar(self, ingreso, estado, **extra):
        return self.client.post(
            reverse('econotec:salida_registrar', kwargs={'ingreso_pk': ingreso.pk}),
            self.datos(estado, **extra),
        )

    def mensaje_whatsapp(self, salida):
        return unquote(whatsapp_link_equipo_listo(salida).split('text=', 1)[1])

    # ── Lista de estados ──────────────────────────────────────────────
    def test_a_domicilio_muestra_estados_a_domicilio_y_los_de_la_oficina(self):
        ingreso = self.crear_ingreso()

        respuesta = self.client.get(
            reverse('econotec:salida_registrar', kwargs={'ingreso_pk': ingreso.pk}),
        )

        self.assertContains(respuesta, 'Reparado — equipo finalizado (a domicilio)')
        self.assertContains(respuesta, 'No se pudo reparar (a domicilio)')
        self.assertContains(respuesta, 'No quiso reparar (a domicilio)')
        self.assertContains(respuesta, 'label="🏢 Equipo llevarlo a la oficina"')
        self.assertContains(respuesta, '🏢 Oficina: Reparado — pendiente de retiro')
        self.assertContains(respuesta, 'value="domicilio:reparado" selected')
        self.assertContains(respuesta, 'Pago después')

    def test_sin_domicilio_la_lista_no_cambia(self):
        ingreso = self.crear_ingreso(a_domicilio='no')

        respuesta = self.client.get(
            reverse('econotec:salida_registrar', kwargs={'ingreso_pk': ingreso.pk}),
        )

        self.assertNotContains(respuesta, '(a domicilio)')
        self.assertNotContains(respuesta, 'Equipo llevarlo a la oficina')
        self.assertContains(respuesta, '⏳ Reparado — pendiente de retiro')

    def test_otros_formularios_no_ofrecen_estados_a_domicilio(self):
        """EconoBot y la finalización desde la hoja de ingreso siguen igual."""
        ingreso = self.crear_ingreso()
        formulario = SalidaEquipoForm(instance=SalidaEquipo(ingreso=ingreso))

        valores = [valor for valor, _etiqueta in formulario.fields['estado_reparacion'].choices]
        self.assertNotIn('domicilio:reparado', valores)

    # ── Reparado a domicilio ──────────────────────────────────────────
    def test_reparado_pago_ahora_completo_queda_sin_saldo_y_fuera_de_oficina(self):
        ingreso = self.crear_ingreso()

        respuesta = self.registrar(
            ingreso, 'domicilio:reparado',
            pago_domicilio='ahora', valor_final_cobrado='50.00', metodo_pago_final='efectivo',
        )

        salida = SalidaEquipo.objects.get(ingreso=ingreso)
        self.assertRedirects(respuesta, reverse('econotec:salida_listo_aviso', kwargs={'pk': salida.pk}))
        ingreso.refresh_from_db()
        self.assertTrue(salida.finalizado_a_domicilio)
        self.assertEqual(salida.estado_reparacion, 'retirado')
        self.assertEqual(salida.get_estado_reparacion_display(), '✅ Reparado — equipo finalizado (a domicilio)')
        self.assertEqual(salida.estado_operativo_display, '✅ Reparado — equipo finalizado (a domicilio)')
        self.assertEqual(salida.fecha_retiro_real, salida.fecha_salida)
        self.assertTrue(salida.cliente_ya_retiro)
        self.assertEqual(salida.valor_final_cobrado, Decimal('50.00'))
        self.assertTrue(salida.numero_recibo)
        self.assertEqual(ingreso.valor_efectivo_a_cobrar, Decimal('50.00'))
        self.assertEqual(ingreso.diferencia, Decimal('0.00'))
        self.assertEqual(ingreso.bodegaje_pendiente, Decimal('0.00'))
        self.assertFalse(NotificacionAsesora.objects.filter(salida=salida).exists())

        mensaje = self.mensaje_whatsapp(salida)
        self.assertIn('a domicilio', mensaje)
        self.assertIn('Valor pagado: $50,00', mensaje)
        self.assertIn('Ningún saldo pendiente', mensaje)
        self.assertNotIn('bodegaje', mensaje.lower())

        aviso = self.client.get(reverse('econotec:salida_listo_aviso', kwargs={'pk': salida.pk}))
        self.assertContains(aviso, '¡Equipo finalizado a domicilio!')
        self.assertContains(aviso, '1. Descargar PDF')

    def test_reparado_pago_ahora_parcial_deja_el_resto_pendiente(self):
        ingreso = self.crear_ingreso()

        self.registrar(
            ingreso, 'domicilio:reparado',
            pago_domicilio='ahora', valor_final_cobrado='30.00', metodo_pago_final='efectivo',
        )

        salida = SalidaEquipo.objects.get(ingreso=ingreso)
        ingreso.refresh_from_db()
        self.assertEqual(ingreso.diferencia, Decimal('20.00'))
        mensaje = self.mensaje_whatsapp(salida)
        self.assertIn('Valor pagado: $30,00', mensaje)
        self.assertIn('Saldo pendiente:* $20,00', mensaje)

    def test_reparado_pago_despues_no_muestra_valor_pagado(self):
        ingreso = self.crear_ingreso()

        self.registrar(ingreso, 'domicilio:reparado', pago_domicilio='despues', valor_final_cobrado='50.00')

        salida = SalidaEquipo.objects.get(ingreso=ingreso)
        ingreso.refresh_from_db()
        self.assertEqual(salida.valor_final_cobrado, Decimal('0.00'))
        self.assertEqual(salida.metodo_pago_final, 'sin_pago')
        self.assertTrue(salida.cliente_ya_retiro)
        self.assertEqual(ingreso.diferencia, Decimal('50.00'))
        mensaje = self.mensaje_whatsapp(salida)
        self.assertNotIn('Valor pagado', mensaje)
        self.assertIn('Saldo pendiente:* $50,00', mensaje)

    def test_reparado_con_anticipo_cobra_solo_lo_que_falta(self):
        ingreso = self.crear_ingreso(anticipo=Decimal('15.00'))

        respuesta = self.registrar(
            ingreso, 'domicilio:reparado',
            pago_domicilio='ahora', valor_final_cobrado='36.00', metodo_pago_final='efectivo',
        )
        self.assertContains(respuesta, 'no puede superar el saldo pendiente ($35.00)')

        self.registrar(
            ingreso, 'domicilio:reparado',
            pago_domicilio='ahora', valor_final_cobrado='35.00', metodo_pago_final='efectivo',
        )
        ingreso.refresh_from_db()
        self.assertEqual(ingreso.diferencia, Decimal('0.00'))
        self.assertIn('Valor pagado: $50,00', self.mensaje_whatsapp(ingreso.salida))

    def test_pago_ahora_pide_el_metodo_y_hay_que_elegir_cuando_paga(self):
        ingreso = self.crear_ingreso()

        sin_metodo = self.registrar(
            ingreso, 'domicilio:reparado', pago_domicilio='ahora', valor_final_cobrado='50.00',
        )
        self.assertContains(sin_metodo, 'Selecciona cómo pagó el cliente')
        sin_eleccion = self.registrar(ingreso, 'domicilio:reparado')
        self.assertContains(sin_eleccion, 'Elige Pago ahora o Pago después.')
        self.assertFalse(SalidaEquipo.objects.filter(ingreso=ingreso).exists())

    # ── No se pudo / No quiso reparar a domicilio ─────────────────────
    def test_no_se_pudo_reparar_cobra_solo_el_domicilio_editable(self):
        ingreso = self.crear_ingreso()

        self.registrar(
            ingreso, 'domicilio:no_reparable', valor_domicilio_cobro='15.00',
            pago_domicilio='ahora', valor_final_cobrado='15.00', metodo_pago_final='transferencia',
            banco='pichincha',
        )

        salida = SalidaEquipo.objects.get(ingreso=ingreso)
        ingreso.refresh_from_db()
        self.assertEqual(salida.estado_reparacion, 'no_reparable')
        self.assertEqual(salida.get_estado_reparacion_display(), '❌ No se pudo reparar (a domicilio)')
        self.assertEqual(ingreso.valor_domicilio, Decimal('15.00'))
        self.assertEqual(ingreso.valor_servicio_a_cobrar, Decimal('0.00'))
        self.assertEqual(ingreso.valor_efectivo_a_cobrar, Decimal('15.00'))
        self.assertEqual(ingreso.diferencia, Decimal('0.00'))
        self.assertEqual(ingreso.subestado_entregado, 'sin_solucion')
        self.assertFalse(salida.sin_reparar_por_retirar)

    def test_no_quiso_reparar_pago_despues_deja_el_domicilio_pendiente(self):
        ingreso = self.crear_ingreso()

        self.registrar(ingreso, 'domicilio:cliente_no_acepta', pago_domicilio='despues')

        salida = SalidaEquipo.objects.get(ingreso=ingreso)
        ingreso.refresh_from_db()
        self.assertEqual(salida.estado_reparacion, 'cliente_no_acepta')
        self.assertEqual(salida.get_estado_reparacion_display(), '🚫 No quiso reparar (a domicilio)')
        self.assertEqual(ingreso.diferencia, Decimal('10.00'))
        self.assertEqual(ingreso.subestado_entregado, 'no_quiso_reparar')
        mensaje = self.mensaje_whatsapp(salida)
        self.assertIn('Solo se cobra el valor de la visita a domicilio', mensaje)
        self.assertIn('Saldo pendiente:* $10,00', mensaje)

    # ── Equipo llevarlo a la oficina: lo de siempre ───────────────────
    def test_llevarlo_a_la_oficina_sigue_la_logica_de_siempre(self):
        ingreso = self.crear_ingreso()

        sin_asesora = self.registrar(ingreso, 'pendiente_retiro')
        self.assertContains(sin_asesora, 'Selecciona la asesora que recibirá esta notificación.')

        self.registrar(ingreso, 'pendiente_retiro', asesora_notificacion=str(self.asesora.pk))

        salida = SalidaEquipo.objects.get(ingreso=ingreso)
        ingreso.refresh_from_db()
        self.assertFalse(salida.finalizado_a_domicilio)
        self.assertEqual(salida.estado_reparacion, 'pendiente_retiro')
        self.assertIsNone(salida.fecha_retiro_real)
        self.assertEqual(salida.get_estado_reparacion_display(), '⏳ Reparado — pendiente de retiro')
        # Se sigue cobrando el valor a domicilio, como hoy.
        self.assertEqual(ingreso.diferencia, Decimal('50.00'))
        self.assertTrue(NotificacionAsesora.objects.filter(salida=salida).exists())

    # ── Editar ────────────────────────────────────────────────────────
    def test_editar_cambia_entre_estados_a_domicilio_y_puede_llevarlo_a_la_oficina(self):
        ingreso = self.crear_ingreso()
        self.registrar(ingreso, 'domicilio:reparado', pago_domicilio='despues')
        salida = SalidaEquipo.objects.get(ingreso=ingreso)
        url = reverse('econotec:salida_editar', kwargs={'pk': salida.pk})

        edicion = self.client.get(url)
        self.assertContains(edicion, 'value="domicilio:reparado" selected')
        self.assertNotContains(edicion, 'La salida de la oficina ya fue confirmada')

        self.client.post(url, self.datos('domicilio:no_reparable', pago_domicilio='despues'))
        salida.refresh_from_db()
        self.assertEqual(salida.estado_reparacion, 'no_reparable')
        self.assertTrue(salida.finalizado_a_domicilio)
        self.assertEqual(salida.ingreso.diferencia, Decimal('10.00'))

        self.client.post(url, self.datos('pendiente_retiro', asesora_notificacion=str(self.asesora.pk)))
        salida.refresh_from_db()
        self.assertFalse(salida.finalizado_a_domicilio)
        self.assertEqual(salida.estado_reparacion, 'pendiente_retiro')
        self.assertIsNone(salida.fecha_retiro_real)
        self.assertIsNone(salida.bodegaje_dias_congelado)

    # ── Listas separadas ──────────────────────────────────────────────
    def test_lista_de_equipos_separa_los_de_a_domicilio(self):
        normal = self.crear_ingreso(a_domicilio='no')
        domicilio = self.crear_ingreso()
        url = reverse('econotec:ingreso_lista')

        lista = self.client.get(url, {'sede': 'todas'})
        self.assertEqual(list(lista.context['ingresos']), [normal])
        lista_domicilio = self.client.get(url, {'sede': 'todas', 'alcance': 'domicilio'})
        self.assertEqual(list(lista_domicilio.context['ingresos']), [domicilio])
        self.assertContains(lista_domicilio, 'Equipos <span class="accent">a Domicilio</span>', html=False)
        self.assertContains(lista_domicilio, '<input type="hidden" name="alcance" value="domicilio">', html=True)
        # Los enlaces del ranking y perfiles abren todos, para cuadrar con sus números.
        todos = self.client.get(url, {'sede': 'todas', 'alcance': 'todos'})
        self.assertEqual(set(todos.context['ingresos']), {normal, domicilio})
        self.assertContains(todos, '🏠 A domicilio</span>')

        menu = self.client.get(reverse('econotec:ingreso_menu'))
        self.assertEqual(menu.context['total'], 1)
        self.assertEqual(menu.context['total_domicilio'], 1)
        self.assertContains(menu, 'Lista de Equipos a Domicilio')
        self.assertContains(menu, '?alcance=domicilio')

    def test_estado_en_la_lista_dice_a_domicilio_y_no_salio_de_la_oficina(self):
        casos = (
            ('domicilio:reparado', 'Finalizado a domicilio', 'Equipo finalizado en el domicilio del cliente'),
            ('domicilio:no_reparable', 'No se pudo reparar', 'Atendido en el domicilio del cliente'),
            ('domicilio:cliente_no_acepta', 'No quiso repararlo', 'Atendido en el domicilio del cliente'),
        )
        for estado, titulo, detalle in casos:
            with self.subTest(estado=estado):
                ingreso = self.crear_ingreso()
                self.registrar(ingreso, estado, pago_domicilio='despues')
                ingreso = IngresoEquipo.objects.get(pk=ingreso.pk)
                self.assertEqual(ingreso.estado_visual_display, titulo)
                self.assertEqual(ingreso.subestado_visual_display, detalle)

        lista = self.client.get(reverse('econotec:ingreso_lista'), {'sede': 'todas', 'alcance': 'domicilio'})
        self.assertContains(lista, 'Equipo finalizado en el domicilio del cliente')
        self.assertNotContains(lista, 'Salió de la oficina')
        self.assertNotContains(lista, 'Salida de la oficina confirmada')

    def test_salida_de_la_oficina_sigue_igual_fuera_de_domicilio(self):
        ingreso = self.crear_ingreso(a_domicilio='no')
        self.registrar(ingreso, 'pendiente_retiro', asesora_notificacion=str(self.asesora.pk))
        SalidaEquipo.objects.filter(ingreso=ingreso).update(fecha_retiro_real=date.today())

        ingreso = IngresoEquipo.objects.get(pk=ingreso.pk)
        self.assertEqual(ingreso.estado_visual_display, 'Salió de la oficina')
        self.assertEqual(ingreso.subestado_visual_display, 'Salida de la oficina confirmada')

    def test_equipos_finalizados_separa_los_de_a_domicilio(self):
        normal = self.crear_ingreso(a_domicilio='no')
        en_casa = self.crear_ingreso()
        a_oficina = self.crear_ingreso()
        self.registrar(normal, 'pendiente_retiro', asesora_notificacion=str(self.asesora.pk))
        self.registrar(en_casa, 'domicilio:reparado', pago_domicilio='despues')
        self.registrar(a_oficina, 'pendiente_retiro', asesora_notificacion=str(self.asesora.pk))
        url = reverse('econotec:salida_lista')

        oficina = self.client.get(url)
        self.assertEqual([s.ingreso for s in oficina.context['salidas']], [normal])
        domicilio = self.client.get(url, {'alcance': 'domicilio'})
        self.assertEqual(
            {s.ingreso for s in domicilio.context['salidas']}, {en_casa, a_oficina},
        )
        self.assertContains(domicilio, 'Equipos finalizados <span class="accent">a domicilio</span>', html=False)
        solo_oficina = self.client.get(url, {'alcance': 'domicilio', 'estado': 'oficina'})
        self.assertEqual([s.ingreso for s in solo_oficina.context['salidas']], [a_oficina])
        solo_reparados = self.client.get(url, {'alcance': 'domicilio', 'estado': 'domicilio:reparado'})
        self.assertEqual([s.ingreso for s in solo_reparados.context['salidas']], [en_casa])

        menu = self.client.get(reverse('econotec:salida_menu'))
        self.assertEqual(menu.context['total'], 1)
        self.assertEqual(menu.context['total_domicilio'], 2)
        self.assertEqual(menu.context['domicilio_en_oficina'], 1)

    def test_salidas_fisicas_no_muestran_a_domicilio_salvo_desde_el_ranking(self):
        User = get_user_model()
        admin = User.objects.create_superuser(username='admin', email='a@example.com', password='x')
        en_casa = self.crear_ingreso()
        self.registrar(en_casa, 'domicilio:reparado', pago_domicilio='despues')
        self.client.force_login(admin)
        url = reverse('econotec:salida_retiros_lista')

        self.assertEqual(list(self.client.get(url).context['salidas']), [])
        ranking = self.client.get(url, {
            'alcance': 'todos', 'tecnico_salida': self.tecnico.pk, 'fecha_por': 'finalizacion',
        })
        self.assertEqual([s.ingreso for s in ranking.context['salidas']], [en_casa])
        self.assertRedirects(
            self.client.get(url, {'alcance': 'domicilio'}),
            reverse('econotec:salida_lista') + '?alcance=domicilio',
        )

    # ── Puntos y ranking del técnico ──────────────────────────────────
    def test_puntos_y_ranking_cuentan_igual_que_en_la_oficina(self):
        """Reparado a domicilio suma como reparado (+3), No quiso reparar
        suma (+1) y No se pudo reparar resta (−1), para el técnico que reparó."""
        from .views import _registros_salidas_ranking, _resumir_salidas, puntaje_tecnico

        for estado, extra in (
            ('domicilio:reparado', {'pago_domicilio': 'ahora', 'valor_final_cobrado': '50.00',
                                    'metodo_pago_final': 'efectivo'}),
            ('domicilio:reparado', {'pago_domicilio': 'despues'}),
            ('domicilio:cliente_no_acepta', {'pago_domicilio': 'despues'}),
            ('domicilio:no_reparable', {'pago_domicilio': 'despues'}),
        ):
            self.registrar(self.crear_ingreso(), estado, **extra)

        puntaje = puntaje_tecnico(self.tecnico)
        self.assertEqual(puntaje['total'], 3 + 3 + 1 - 1)
        self.assertEqual(puntaje['conteo'].get('retirado'), 2)
        self.assertEqual(puntaje['salidas_buenas'], 3)   # 2 reparados + 1 no quiso
        self.assertEqual(puntaje['salidas_malas'], 1)    # 1 no se pudo reparar
        registros = [
            r for r in _registros_salidas_ranking(None, None, False)
            if r['tecnico_id'] == self.tecnico.pk
        ]
        self.assertEqual(
            sorted(r['resultado'] for r in registros),
            ['cliente_no_acepta', 'no_reparable', 'reparado', 'reparado'],
        )
        resumen = _resumir_salidas(registros, False)
        self.assertEqual(resumen['puntos'], 6)

    def test_ubicacion_del_ranking_separa_equipo_a_domicilio(self):
        """Fuera de oficina + En oficina + A domicilio = equipos finalizados."""
        from .views import _registros_salidas_ranking, _resumir_salidas

        normal_en_oficina = self.crear_ingreso(a_domicilio='no')
        self.registrar(normal_en_oficina, 'pendiente_retiro', asesora_notificacion=str(self.asesora.pk))
        normal_fuera = self.crear_ingreso(a_domicilio='no', valor=Decimal('0.00'))
        self.registrar(normal_fuera, 'pendiente_retiro')
        SalidaEquipo.objects.filter(ingreso=normal_fuera).update(
            fecha_retiro_real=date.today(), estado_reparacion='retirado',
        )
        self.registrar(self.crear_ingreso(), 'domicilio:reparado', pago_domicilio='despues')
        self.registrar(self.crear_ingreso(), 'pendiente_retiro', asesora_notificacion=str(self.asesora.pk))

        resumen = _resumir_salidas(_registros_salidas_ranking(None, None, False), False)
        self.assertEqual(resumen['num_equipos'], 4)
        self.assertEqual(resumen['entregados'], 1)
        self.assertEqual(resumen['pendientes'], 1)
        self.assertEqual(resumen['a_domicilio'], 2)

        totales = self.client.get(reverse('econotec:salida_totales'))
        self.assertContains(totales, 'Equipo a domicilio')
        self.assertContains(
            totales,
            f'?alcance=domicilio&tecnico_salida={self.tecnico.pk}',
        )

    # ── Lo que no se debe poder hacer ─────────────────────────────────
    def test_editar_a_domicilio_no_ofrece_salio_de_la_oficina_ni_repite_estados(self):
        ingreso = self.crear_ingreso()
        self.registrar(ingreso, 'domicilio:no_reparable', pago_domicilio='despues')
        salida = SalidaEquipo.objects.get(ingreso=ingreso)

        formulario = SalidaEquipoForm(instance=salida, estados_domicilio=True)
        oficina = dict(formulario.fields['estado_reparacion'].choices)[SalidaEquipoForm.GRUPO_OFICINA]
        valores = [valor for valor, _etiqueta in oficina]
        self.assertNotIn('retirado', valores)
        self.assertNotIn('no_reparable', valores)
        self.assertNotIn('cliente_no_acepta', valores)
        self.assertIn('pendiente_retiro', valores)

    def test_no_se_pierde_el_pago_a_domicilio_al_llevarlo_a_la_oficina(self):
        ingreso = self.crear_ingreso()
        self.registrar(
            ingreso, 'domicilio:reparado',
            pago_domicilio='ahora', valor_final_cobrado='50.00', metodo_pago_final='efectivo',
        )
        salida = SalidaEquipo.objects.get(ingreso=ingreso)
        url = reverse('econotec:salida_editar', kwargs={'pk': salida.pk})

        respuesta = self.client.post(url, self.datos('revision:equipo_prueba', asesora_notificacion=str(self.asesora.pk)))

        self.assertContains(respuesta, 'tiene un pago de $50.00 cobrado a domicilio')
        salida.refresh_from_db()
        self.assertTrue(salida.finalizado_a_domicilio)
        self.assertEqual(salida.valor_final_cobrado, Decimal('50.00'))
        self.assertEqual(salida.ingreso.diferencia, Decimal('0.00'))

    def test_admin_no_deshace_una_salida_a_domicilio(self):
        User = get_user_model()
        admin = User.objects.create_superuser(username='admin', email='a@example.com', password='x')
        ingreso = self.crear_ingreso()
        self.registrar(ingreso, 'domicilio:reparado', pago_domicilio='despues')
        salida = SalidaEquipo.objects.get(ingreso=ingreso)
        self.client.force_login(admin)

        self.client.post(reverse('econotec:salida_deshacer_retiro', kwargs={'pk': salida.pk}))

        salida.refresh_from_db()
        self.assertEqual(salida.fecha_retiro_real, salida.fecha_salida)
        self.assertEqual(salida.estado_reparacion, 'retirado')
        self.assertEqual(
            self.client.get(reverse('econotec:ranking_asesoras_salidas')).context['sin_registro'], 0,
        )

    def test_factura_si_sin_asesora_vuelve_al_formulario_sin_caerse(self):
        ingreso = self.crear_ingreso()
        respuesta = self.registrar(
            ingreso, 'domicilio:cliente_no_acepta',
            pago_domicilio='ahora', valor_final_cobrado='10.00', metodo_pago_final='efectivo',
            factura_realizada='si', factura_nombres='Ana', factura_cedula='0912345678',
            factura_correo='ana@example.com',
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('asesora_factura', respuesta.context['form'].errors)
        self.assertFalse(SalidaEquipo.objects.filter(ingreso=ingreso).exists())

    # ── PDF ───────────────────────────────────────────────────────────
    def test_pdf_a_domicilio_se_genera_para_cada_estado(self):
        for estado, extra in (
            ('domicilio:reparado', {'pago_domicilio': 'ahora', 'valor_final_cobrado': '20.00',
                                    'metodo_pago_final': 'efectivo'}),
            ('domicilio:no_reparable', {'pago_domicilio': 'despues'}),
            ('domicilio:cliente_no_acepta', {'pago_domicilio': 'ahora', 'valor_final_cobrado': '10.00',
                                             'metodo_pago_final': 'efectivo', 'factura_realizada': 'si',
                                             'factura_nombres': 'Ana', 'factura_cedula': '0912345678',
                                             'factura_correo': 'ana@example.com',
                                             'asesora_factura': str(self.asesora.pk)}),
        ):
            with self.subTest(estado=estado):
                ingreso = self.crear_ingreso()
                self.registrar(ingreso, estado, **extra)
                salida = SalidaEquipo.objects.get(ingreso=ingreso)

                self.assertTrue(generar_salida_pdf_bytes(salida).startswith(b'%PDF'))
                respuesta = self.client.get(reverse('econotec:salida_pdf', kwargs={'pk': salida.pk}))
                self.assertEqual(respuesta.status_code, 200)
                self.assertIn('equipo_finalizado_a_domicilio_', respuesta['Content-Disposition'])
