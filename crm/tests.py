"""Pruebas del CRM integrado en Econotec: acceso por rol, pantallas, pipeline, etiquetas y WhatsApp."""
import json
from unittest import mock

from django.contrib.auth.models import Group, User
from django.test import TestCase, override_settings
from django.urls import reverse

from econotec.models import Cliente

from . import bot, services
from .models import Canal, Categoria, Contacto, Conversacion, Etiqueta, Oportunidad, Perfil, Rol
from .roles import rol_de


class BaseCRM(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("jefe", "jefe@x.com", "clave-larga-123", first_name="Jefe")
        cls.asesora = User.objects.create_user("ana", "ana@x.com", "clave-larga-123", first_name="Ana")
        cls.asesora.groups.add(Group.objects.get_or_create(name="Asesores")[0])
        cls.asesora2 = User.objects.create_user("bea", "bea@x.com", "clave-larga-123", first_name="Bea")
        cls.asesora2.groups.add(Group.objects.get_or_create(name="Asesora - Asistente de caja")[0])
        cls.tecnico = User.objects.create_user("tito", "tito@x.com", "clave-larga-123", first_name="Tito")
        cls.tecnico.groups.add(Group.objects.get_or_create(name="Tecnicos")[0])

    def entrar(self, user):
        self.client.force_login(user)


class RolesTests(BaseCRM):
    def test_roles_salen_de_econotec(self):
        self.assertEqual(rol_de(self.admin), Rol.ADMIN)
        self.assertEqual(rol_de(self.asesora), Rol.EJECUTIVO)
        self.assertEqual(rol_de(self.asesora2), Rol.EJECUTIVO)
        self.assertIsNone(rol_de(self.tecnico))

    def test_supervisora(self):
        Perfil.objects.filter(user=self.asesora).update(rol=Rol.GERENTE)
        self.asesora.refresh_from_db()
        self.assertEqual(rol_de(User.objects.get(pk=self.asesora.pk)), Rol.GERENTE)

    def test_tecnico_no_entra(self):
        self.entrar(self.tecnico)
        self.assertEqual(self.client.get(reverse("crm:dashboard")).status_code, 403)

    def test_sin_sesion_va_al_login(self):
        r = self.client.get(reverse("crm:clientes"))
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login/", r["Location"])


class PantallasTests(BaseCRM):
    def test_todas_las_pantallas_admin(self):
        self.entrar(self.admin)
        op = services.registrar_entrante(Canal.WHATSAPP, "Carlos Pérez", "Hola, mi laptop no prende", telefono="0991234567")[1]
        for nombre in ["dashboard", "clientes", "cliente_nuevo", "oportunidades", "bitacora", "actividad_nueva",
                       "seguimientos", "seguimiento_nuevo", "etiquetas", "whatsapp", "notificaciones",
                       "usuarios", "integraciones", "bandeja"]:
            r = self.client.get(reverse(f"crm:{nombre}"))
            self.assertIn(r.status_code, (200, 302), nombre)
        r = self.client.get(reverse("crm:oportunidad", args=[op.pk]))
        self.assertContains(r, "Equipo ingresado")
        self.assertContains(r, "En Econotec")
        self.assertNotContains(self.client.get(reverse("crm:integraciones")), "Power BI")

    def test_asesora_solo_ve_lo_suyo(self):
        Perfil.objects.filter(user=self.asesora2).update(recibe_leads=False)
        _, op, _ = services.registrar_entrante(Canal.WEB, "Luis", "Consulta", telefono="0990000001")
        self.assertEqual(op.responsable, self.asesora)
        self.entrar(self.asesora2)
        self.assertEqual(self.client.get(reverse("crm:oportunidad", args=[op.pk])).status_code, 403)
        self.entrar(self.asesora)
        self.assertEqual(self.client.get(reverse("crm:oportunidad", args=[op.pk])).status_code, 200)

    def test_boton_crm_en_bienvenida(self):
        self.entrar(self.asesora)
        r = self.client.get(reverse("econotec:bienvenida"))
        self.assertContains(r, 'class="dashboard-crm-btn"')
        self.entrar(self.tecnico)
        r = self.client.get(reverse("econotec:bienvenida"))
        self.assertNotContains(r, 'class="dashboard-crm-btn"')


class RegistroTests(BaseCRM):
    def test_registrar_cliente_y_enlazar_con_econotec(self):
        Cliente.objects.create(cedula="0912345678", nombres="María López", whatsapp="0987654321")
        self.entrar(self.asesora)
        cat = Categoria.objects.get(nombre="Reparación de laptops")
        r = self.client.post(reverse("crm:cliente_nuevo"), {
            "canal": "whatsapp", "nombre": "María López", "telefono": "0987654321", "ruc": "",
            "sede": "quito", "servicio": cat.nombre, "equipo": "HP Pavilion", "etapa": "nuevo",
            "valor": "0", "cantidad": "1", "etiquetas": [Etiqueta.objects.get(nombre="Urgente").pk],
            "seguimiento_tipo": "llamada",
        })
        self.assertEqual(r.status_code, 302)
        op = Oportunidad.objects.get()
        self.assertEqual((op.sede, op.equipo, op.responsable), ("quito", "HP Pavilion", self.asesora))
        self.assertEqual(op.contacto.cliente_econotec.cedula, "0912345678")
        self.assertEqual(list(op.etiquetas.values_list("nombre", flat=True)), ["Urgente"])

    def test_mover_en_el_pipeline(self):
        self.entrar(self.admin)
        _, op, _ = services.registrar_entrante(Canal.LLAMADA, "Pedro", "Llamó", telefono="0991111111")
        r = self.client.post(reverse("crm:oportunidad_mover", args=[op.pk]), json.dumps({"etapa": "ganado"}),
                             content_type="application/json")
        self.assertEqual(r.json()["etapa"], "Equipo ingresado")


class WhatsAppTests(BaseCRM):
    def test_bot_categoria_y_detalle(self):
        _, op, _ = services.registrar_entrante(Canal.WHATSAPP, "Rosa", "hola", telefono="0992222222")
        conv = Conversacion.objects.get()
        r1 = bot.responder(conv, "mi impresora no imprime", op)
        self.assertIn("Impresoras", r1)
        op.refresh_from_db()
        self.assertEqual(op.servicio, "Impresoras")
        r2 = bot.responder(conv, "Epson L3250, sale manchada", op)
        self.assertIn("Anotado", r2)

    def test_webhook_api_sin_conectar(self):
        r = self.client.post(reverse("crm:api_whatsapp_webhook"), "{}", content_type="application/json")
        self.assertEqual(r.status_code, 404)

    @override_settings(WA_API_TOKEN="t", WA_API_PHONE_ID="123", WA_API_VERIFY_TOKEN="v", WA_API_APP_SECRET="")
    def test_webhook_api_conectada(self):
        r = self.client.get(reverse("crm:api_whatsapp_webhook"),
                            {"hub.mode": "subscribe", "hub.verify_token": "v", "hub.challenge": "42"})
        self.assertEqual(r.content, b"42")
        payload = {"entry": [{"changes": [{"value": {
            "contacts": [{"wa_id": "593993333333", "profile": {"name": "Jorge"}}],
            "messages": [{"from": "593993333333", "id": "wamid.1", "type": "text", "text": {"body": "hola"}}],
        }}]}]}
        with mock.patch("crm.whatsapp_api.enviar", return_value=(True, "enviado por la API de WhatsApp")) as env:
            r = self.client.post(reverse("crm:api_whatsapp_webhook"), json.dumps(payload), content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(Contacto.objects.filter(telefono="593993333333", nombre="Jorge").exists())
        env.assert_called_once()
