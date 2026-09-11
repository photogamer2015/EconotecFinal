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
