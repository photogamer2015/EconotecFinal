from django.contrib import admin
from django.urls import path, include
from econotec import views as econotec_views
from econotec import views_auth

admin.site.site_header = 'Econotec — Reparación de Tecnología'
admin.site.site_title = 'Econotec Admin'
admin.site.index_title = 'Panel de administración'

urlpatterns = [
    # Login personalizado: pide usuario, contraseña Y sede
    path('login/', views_auth.login_con_sede, name='login'),
    path('login/registrar-correo/', views_auth.registrar_correo_doble_factor, name='login_registrar_correo'),
    path('login/verificar-codigo/', views_auth.verificar_doble_factor, name='login_2fa'),
    path('logout/', views_auth.logout_view, name='logout'),

    path('', econotec_views.home, name='home'),

    path('admin/', admin.site.urls),

    path('', include('econotec.urls')),
]
