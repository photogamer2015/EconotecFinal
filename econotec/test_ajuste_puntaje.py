"""«Puntajes» del panel de administración: el admin suma o resta puntos a mano.

- Se registra en /admin/ (Puntajes → Añadir) con técnico, acción, puntos,
  motivo y fecha; queda guardado quién lo hizo.
- Cuenta en Mi perfil (puntos acumulados y nivel) y en el Ranking de
  Técnicos del período que incluye su fecha. Borrarlo deshace sus puntos.
"""
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import AjustePuntaje, UsuarioActividad
from .views import puntaje_tecnico, ranking_con_dinero

HOY = timezone.localdate()


class AjustePuntajeTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(username='RootAdmin', email='a@example.com', password='x')
        tecnicos = Group.objects.create(name='Tecnicos')
        self.tecnico = User.objects.create_user(username='yandri', first_name='Yandri', last_name='Guevara')
        self.tecnico.groups.add(tecnicos)
        self.asesora = User.objects.create_user(username='Kimberly')
        self.asesora.groups.add(Group.objects.create(name='Asesores Comerciales'))
        self.client.force_login(self.admin)

    def ajustar(self, tipo, puntos, fecha=HOY, motivo='Buen trabajo', tecnico=None, reparado=False):
        datos = {
            'tecnico': str((tecnico or self.tecnico).pk),
            'tipo': tipo,
            'puntos': str(puntos),
            'motivo': motivo,
            'fecha': fecha.isoformat(),
        }
        if reparado:
            datos['cuenta_como_reparado'] = 'on'
        return self.client.post(reverse('admin:econotec_ajustepuntaje_add'), datos)

    def total(self):
        self.tecnico.refresh_from_db()
        return puntaje_tecnico(self.tecnico)['total']

    def ranking_del_mes(self):
        respuesta = self.client.get(reverse('econotec:salida_totales'), {
            'desde': HOY.replace(day=1).isoformat(), 'hasta': HOY.isoformat(),
        })
        return {fila['tecnico_id']: fila for fila in respuesta.context['ranking']}

    def test_aparece_en_el_panel_de_administracion(self):
        inicio = self.client.get(reverse('admin:index'))
        self.assertContains(inicio, 'Puntajes')
        self.assertContains(inicio, reverse('admin:econotec_ajustepuntaje_add'))

        formulario = self.client.get(reverse('admin:econotec_ajustepuntaje_add'))
        self.assertContains(formulario, 'Sumar puntos')
        self.assertContains(formulario, 'Restar puntos')
        # Solo se ofrecen técnicos.
        self.assertContains(formulario, 'Yandri Guevara')
        self.assertNotContains(formulario, f'<option value="{self.asesora.pk}"')

    def test_sumar_y_restar_cambian_el_perfil(self):
        self.assertEqual(self.ajustar('sumar', 10).status_code, 302)
        ajuste = AjustePuntaje.objects.get()
        self.assertEqual((ajuste.tecnico, ajuste.creado_por, ajuste.puntos_con_signo), (self.tecnico, self.admin, 10))
        self.assertEqual(self.total(), 10)
        self.assertEqual(puntaje_tecnico(self.tecnico)['ajuste_manual'], 10)

        self.ajustar('restar', 4, motivo='Equipo mal cerrado')
        self.assertEqual(self.total(), 6)

        # El puntaje del perfil nunca baja de cero.
        self.ajustar('restar', 50)
        self.assertEqual(self.total(), 0)

    def test_valida_puntos_y_motivo(self):
        for datos in ({'puntos': 0}, {'puntos': -3}, {'puntos': 'abc'}, {'motivo': ''}):
            with self.subTest(datos=datos):
                respuesta = self.ajustar(
                    'sumar', datos.get('puntos', 5), motivo=datos.get('motivo', 'Motivo'),
                )
                self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(AjustePuntaje.objects.exists())

    def test_ranking_suma_el_ajuste_del_periodo(self):
        self.ajustar('sumar', 8, motivo='Ayudó con los equipos de Quito')
        self.ajustar('restar', 3, motivo='Llegó tarde')
        # Un ajuste de hace dos meses no cuenta en el mes actual.
        self.ajustar('sumar', 100, fecha=HOY - timedelta(days=70))

        fila = self.ranking_del_mes()[self.tecnico.pk]
        self.assertEqual((fila['puntos'], fila['ajuste_manual']), (5, 5))
        ajustes = [d for d in fila['puntos_detalle'] if d['unitario'] is None]
        self.assertEqual(
            [(d['etiqueta'], d['subtotal'], d['fecha'], d['motivo']) for d in ajustes],
            [
                ('Ajuste del administrador', 8, HOY, 'Ayudó con los equipos de Quito'),
                ('Ajuste del administrador', -3, HOY, 'Llegó tarde'),
            ],
        )
        _registros, filas, _resumen = ranking_con_dinero(HOY.replace(day=1).isoformat(), HOY.isoformat())
        self.assertEqual({f['tecnico_id']: f['puntos'] for f in filas}[self.tecnico.pk], 5)
        # Mi perfil cuenta todo el historial.
        self.assertEqual(self.total(), 105)

    def test_ranking_muestra_el_motivo_de_cada_ajuste(self):
        self.ajustar('sumar', 3, motivo='Reparó la impresora del cliente VIP\nsin costo extra')
        self.ajustar('restar', 1, motivo='<b>no cerró</b> el equipo')

        pagina = self.client.get(reverse('econotec:salida_totales'), {
            'desde': HOY.replace(day=1).isoformat(), 'hasta': HOY.isoformat(),
        })
        self.assertContains(pagina, f'Ajuste del administrador · {HOY:%d/%m/%Y}', count=2)
        self.assertContains(pagina, 'Reparó la impresora del cliente VIP<br>sin costo extra')
        self.assertContains(pagina, '<strong class="pos">+3</strong>', html=True)
        self.assertContains(pagina, '<strong class="neg">-1</strong>', html=True)
        # El motivo se muestra como texto, nunca como código de la página.
        self.assertContains(pagina, '&lt;b&gt;no cerró&lt;/b&gt; el equipo')
        self.assertNotContains(pagina, '<b>no cerró</b>')

    def test_borrar_el_ajuste_deshace_los_puntos(self):
        self.ajustar('sumar', 7)
        ajuste = AjustePuntaje.objects.get()
        self.client.post(reverse('admin:econotec_ajustepuntaje_delete', args=[ajuste.pk]), {'post': 'yes'})
        self.assertFalse(AjustePuntaje.objects.exists())
        self.assertEqual(self.total(), 0)

    def test_reiniciar_el_perfil_deja_fuera_los_ajustes_anteriores(self):
        self.ajustar('sumar', 9)
        UsuarioActividad.objects.update_or_create(
            user=self.tecnico, defaults={'fecha_reinicio_perfil': timezone.now()},
        )
        self.assertEqual(self.total(), 0)
        self.ajustar('sumar', 2)
        self.assertEqual(self.total(), 2)

    def test_lista_muestra_el_ajuste_y_el_puntaje_actual(self):
        self.ajustar('sumar', 12)
        lista = self.client.get(reverse('admin:econotec_ajustepuntaje_changelist'))
        self.assertContains(lista, '+12 pts')
        self.assertContains(lista, '12 pts · Novato')
        self.assertContains(lista, 'Yandri Guevara')

    def test_solo_el_administrador_entra(self):
        self.client.force_login(self.tecnico)
        respuesta = self.client.get(reverse('admin:econotec_ajustepuntaje_add'))
        self.assertEqual(respuesta.status_code, 302)
        self.assertFalse(AjustePuntaje.objects.exists())

    def test_casilla_cuenta_como_equipo_reparado(self):
        self.assertContains(self.client.get(reverse('admin:econotec_ajustepuntaje_add')), 'Cuenta como equipo reparado')

        self.ajustar('sumar', 3, motivo='Washington Garcia Troya - G1073', reparado=True)
        # Un ajuste sin la casilla da puntos pero no cuenta como reparado.
        self.ajustar('sumar', 2, motivo='Bono por puntualidad')

        fila = self.ranking_del_mes()[self.tecnico.pk]
        self.assertEqual(fila['puntos'], 5)
        self.assertEqual((fila['reparados'], fila['num_equipos'], fila['salidas_positivas']), (1, 1, 1))
        self.assertEqual(fila['efectividad'], 100.0)
        perfil = puntaje_tecnico(self.tecnico)
        self.assertEqual((perfil['salidas_buenas'], perfil['total']), (1, 5))

        pagina = self.client.get(reverse('econotec:salida_totales'), {
            'desde': HOY.replace(day=1).isoformat(), 'hasta': HOY.isoformat(),
        })
        self.assertContains(pagina, 'cuenta como reparado', count=1)
        lista = self.client.get(reverse('admin:econotec_ajustepuntaje_changelist'))
        self.assertContains(lista, '+3 pts · equipo reparado')

    def test_restar_no_puede_contar_como_reparado(self):
        respuesta = self.ajustar('restar', 3, reparado=True)
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Un equipo reparado suma puntos')
        self.assertFalse(AjustePuntaje.objects.exists())
