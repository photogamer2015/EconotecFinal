from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, Client
from django.urls import reverse
from .models import PerfilSocial


class PerfilesTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='persona')
        self.other = get_user_model().objects.create_user(username='admin', is_superuser=True)
        self.client.force_login(self.user)

    def test_all_roles_can_access_and_search(self):
        for group in [None, 'Tecnicos', 'Asesores Comerciales']:
            self.user.groups.clear()
            if group:
                self.user.groups.add(Group.objects.get_or_create(name=group)[0])
            self.assertContains(self.client.get(reverse('econotec:mi_perfil')), 'Mi espacio personal')
        self.client.force_login(self.other)
        self.assertContains(self.client.get(reverse('econotec:mi_perfil')), 'Administrador')
        self.assertContains(self.client.get(reverse('econotec:comunidad'), {'q': 'persona'}), '@persona')

    def test_save_and_reject_foreign_edits_and_invalid_avatar(self):
        data = dict(seccion='datos', avatar='master-chief.webp', portada='bosque', biografia='Hola', musica='Rock, Salsa', hobbies='Leer', cancion='Mi canción')
        self.assertEqual(self.client.post(reverse('econotec:mi_perfil'), data).status_code, 302)
        self.client.post(reverse('econotec:mi_perfil'), {'seccion': 'avatar', 'avatar': 'master-chief.webp'})
        p = PerfilSocial.objects.get(usuario=self.user)
        self.assertEqual(p.musicas, ['Rock', 'Salsa'])
        url = reverse('econotec:perfil_social', args=[self.other.pk])
        self.assertEqual(self.client.post(url, data).status_code, 403)
        self.assertEqual(PerfilSocial.objects.get(usuario=self.other).biografia, '')
        data['seccion'] = 'avatar'
        data['avatar'] = '../../invalid'
        response = self.client.post(reverse('econotec:mi_perfil'), data)
        self.assertTrue(response.context['form'].errors)
        p.refresh_from_db()
        self.assertEqual(p.avatar, 'master-chief.webp')

    def test_friendship_and_likes_are_idempotent_and_reversible(self):
        url = reverse('econotec:perfil_reaccion', args=[self.other.pk])
        for _ in range(2):
            self.client.post(url, {'accion': 'amigo'})
            self.client.post(url, {'accion': 'like'})
        p = PerfilSocial.objects.get(usuario=self.user)
        other = PerfilSocial.objects.get(usuario=self.other)
        self.assertEqual(p.amigos.count(), 1)
        self.assertTrue(other.amigos.filter(pk=p.pk).exists())
        self.assertEqual(other.me_gusta.count(), 1)
        self.assertContains(self.client.get(reverse('econotec:perfil_social', args=[self.other.pk])), 'Te gusta')
        self.client.post(url, {'accion': 'quitar_amigo'})
        self.client.post(url, {'accion': 'unlike'})
        self.assertEqual(other.amigos.count(), 0)
        self.assertEqual(other.me_gusta.count(), 0)
        self.assertEqual(self.client.get(url).status_code, 405)

    def test_auth_csrf_and_private_account_data(self):
        url = reverse('econotec:mi_perfil')
        self.assertEqual(Client().get(url).status_code, 302)
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.user)
        self.assertEqual(c.post(url, {'biografia': 'No'}).status_code, 403)
        self.other.email = 'private@example.com'
        self.other.save()
        response = self.client.get(reverse('econotec:perfil_social', args=[self.other.pk]))
        self.assertNotContains(response, self.other.email)

    def test_separate_editors_preserve_other_fields_and_show_navigation_avatar(self):
        p = PerfilSocial.objects.create(usuario=self.user, avatar='heisenberg.jpg', portada='bosque', biografia='Mi historia', musica='Rock')
        url = reverse('econotec:mi_perfil')
        self.client.post(url, {'seccion': 'avatar', 'avatar': 'econotec.webp', 'biografia': 'No cambiar'})
        p.refresh_from_db()
        self.assertEqual((p.avatar, p.portada, p.biografia), ('econotec.webp', 'bosque', 'Mi historia'))
        self.client.post(url, {'seccion': 'portada', 'portada': 'ciudad', 'avatar': ''})
        p.refresh_from_db()
        self.assertEqual((p.avatar, p.portada, p.musica), ('econotec.webp', 'ciudad', 'Rock'))
        self.assertContains(self.client.get(url), 'alt="Mi avatar"')
        self.assertContains(self.client.get(url), 'social-editor-portada')
        self.assertEqual(self.client.post(url, {'seccion': 'invalid'}).status_code, 400)

    def test_unified_profile_uses_same_level_as_api_and_owner_actions(self):
        response = self.client.get(reverse('econotec:mi_perfil'))
        api = self.client.get(reverse('econotec:api_perfil')).json()
        self.assertEqual(response.context['operativo']['nivel'], api['nivel'])
        self.assertContains(response, 'Nivel: Novato')
        self.assertContains(response, 'Ver mis equipos recibidos')
        self.assertContains(response, 'Ver mis equipos reparados')
        self.assertContains(response, 'id="btn-bitacora"', count=1)
        self.assertNotContains(response, 'id="perfil-modal"')
        self.assertNotContains(response, 'data-perfil-trigger')

    def test_other_profile_shows_level_but_never_owner_actions_or_email(self):
        self.other.email = 'owner-only@example.com'
        self.other.save()
        response = self.client.get(reverse('econotec:perfil_social', args=[self.other.pk]))
        self.assertContains(response, 'Nivel: Novato')
        for private in ['owner-only@example.com', 'Ver mis equipos recibidos',
                        'Ver mis equipos reparados', 'id="btn-bitacora"', 'data-edit-profile=']:
            self.assertNotContains(response, private)
        self.assertEqual(response.context['operativo']['email'], '')

    def test_private_apis_ignore_foreign_user_parameters(self):
        response = self.client.get(reverse('econotec:api_perfil'), {'usuario_id': self.other.pk})
        self.assertEqual(response.json()['username'], self.user.username)
        from unittest.mock import patch
        with patch('econotec.views.construir_bitacora_usuario', return_value={'total': 0}) as report:
            self.client.get(reverse('econotec:api_bitacora_hoy'), {'usuario_id': self.other.pk})
            report.assert_called_once_with(self.user)

    def test_logout_requires_post_csrf_and_invalidates_old_cookie(self):
        from django.conf import settings
        url = reverse('logout')
        self.assertEqual(self.client.get(url).status_code, 405)
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.user)
        self.assertEqual(strict.post(url).status_code, 403)
        old_cookie = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('no-store', response.headers['Cache-Control'])
        self.client.cookies[settings.SESSION_COOKIE_NAME] = old_cookie
        for name in ['mi_perfil', 'api_perfil', 'api_bitacora_hoy']:
            self.assertEqual(self.client.get(reverse('econotec:' + name)).status_code, 302)

    def test_private_pages_and_apis_are_not_cacheable(self):
        for name in ['mi_perfil', 'api_perfil', 'api_bitacora_hoy']:
            response = self.client.get(reverse('econotec:' + name))
            self.assertIn('no-store', response.headers['Cache-Control'])
            self.assertIn('private', response.headers['Cache-Control'])

    def test_no_role_cannot_modify_operational_alerts(self):
        from unittest.mock import patch
        for name in ['salida_bodegaje_silenciar', 'ingreso_diagnostico_silenciar']:
            with patch('econotec.views.get_object_or_404') as lookup:
                response = self.client.post(reverse('econotec:' + name, args=[123]))
                self.assertEqual(response.status_code, 302)
                lookup.assert_not_called()

    def test_alert_redirects_reject_external_and_preserve_local_targets(self):
        from unittest.mock import patch, MagicMock
        self.user.groups.add(Group.objects.get_or_create(name='Tecnicos')[0])
        for name in ['salida_bodegaje_silenciar', 'ingreso_diagnostico_silenciar']:
            for target, expected in [('https://evil.example/phishing', reverse('econotec:bienvenida')),
                                     ('//evil.example/', reverse('econotec:bienvenida')),
                                     ('/mi-perfil/', '/mi-perfil/')]:
                with patch('econotec.views.get_object_or_404', return_value=MagicMock()):
                    response = self.client.post(reverse('econotec:' + name, args=[123]), {'next': target})
                    self.assertEqual(response.url, expected)

    def test_absolute_session_expiry_denies_access_even_with_valid_cookie(self):
        from django.utils import timezone
        session = self.client.session
        session['_econotec_session_deadline'] = timezone.now().timestamp() - 1
        session.save()
        response = self.client.get(reverse('econotec:api_perfil'))
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_authentication_limits_are_shared_between_sessions_and_expire(self):
        from .seguridad import consumir_intento
        from .models import LimiteAcceso
        from unittest.mock import patch
        from django.utils import timezone
        from datetime import timedelta
        self.assertTrue(consumir_intento('test-limit', 2))
        self.assertTrue(consumir_intento('test-limit', 2))
        self.assertFalse(consumir_intento('test-limit', 2))
        with patch('econotec.seguridad.timezone.now', return_value=timezone.now() + timedelta(minutes=16)):
            self.assertTrue(consumir_intento('test-limit', 2))
        self.assertEqual(LimiteAcceso.objects.count(), 1)
        for _ in range(20):
            response = Client().post(reverse('login'), {'username': 'target'})
            self.assertNotEqual(response.status_code, 429)
        response = Client().post(reverse('login'), {'username': 'target'})
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers['Retry-After'], '900')
        self.assertIn('no-store', response.headers['Cache-Control'])

    def test_admin_login_uses_same_two_factor_flow(self):
        from django.urls import resolve
        from .views_auth import login_con_sede
        self.assertIs(resolve('/admin/login/').func, login_con_sede)
        response = Client().get('/admin/login/')
        self.assertContains(response, 'captcha_respuesta')

    def test_advisor_color_rejects_wrong_json_types(self):
        self.user.groups.add(Group.objects.get_or_create(name='Asesores')[0])
        url = reverse('econotec:api_perfil_color')
        for payload in ['[]', 'null', '{"color":123}', '{"color":[]}']:
            self.assertEqual(self.client.post(url, data=payload, content_type='application/json').status_code, 400)
