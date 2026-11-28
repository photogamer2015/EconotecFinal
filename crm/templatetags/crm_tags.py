from decimal import Decimal, InvalidOperation

from django import template
from django.utils.safestring import mark_safe

register = template.Library()

ICONOS = {
    "home": '<path d="M3 3v18h18"/><path d="m7 15 4-4 3 3 5-6"/>',
    "inbox": '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
    "pipe": '<rect x="3" y="4" width="5" height="16" rx="1"/><rect x="10" y="4" width="5" height="11" rx="1"/><rect x="17" y="4" width="4" height="7" rx="1"/>',
    "log": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M8 13h8M8 17h5"/>',
    "cal": '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
    "users": '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
    "plug": '<path d="M9 2v6M15 2v6M6 8h12v4a6 6 0 0 1-12 0z"/><path d="M12 18v4"/>',
    "chart": '<rect x="3" y="12" width="4" height="9"/><rect x="10" y="7" width="4" height="14"/><rect x="17" y="3" width="4" height="18"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "download": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/>',
    "bolt": '<path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z"/>',
    "edit": '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
    "bell": '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>',
    "moon": '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9z"/>',
    "monitor": '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>',
    "tag": '<path d="M12.6 2.6A2 2 0 0 0 11.2 2H4a2 2 0 0 0-2 2v7.2a2 2 0 0 0 .6 1.4l8.7 8.7a2.4 2.4 0 0 0 3.4 0l6.6-6.6a2.4 2.4 0 0 0 0-3.4z"/><circle cx="7.5" cy="7.5" r=".5" fill="currentColor"/>',
    "chat": '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    "robot": '<rect x="4" y="8" width="16" height="12" rx="2"/><path d="M12 8V4M8 4h8M9 13v2M15 13v2"/>',
    "trash": '<path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
    "user-plus": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M19 8v6M22 11h-6"/>',
    "eye": '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
}

WA_PATH = (
    "M17.47 14.38c-.3-.15-1.75-.86-2.02-.96-.27-.1-.47-.15-.67.15-.2.3-.77.96-.94 1.16-.17.2-.35.22-.64.07-.3-.15-1.25-.46-2.38-1.47"
    "-.88-.79-1.47-1.76-1.65-2.06-.17-.3-.02-.46.13-.6.13-.14.3-.35.45-.52.15-.17.2-.3.3-.5.1-.2.05-.37-.03-.52-.07-.15-.67-1.6-.92-2.2"
    "-.24-.58-.49-.5-.67-.51h-.57c-.2 0-.52.07-.79.37-.27.3-1.04 1.02-1.04 2.48s1.07 2.88 1.21 3.08c.15.2 2.1 3.2 5.08 4.49.71.31 1.26.49"
    " 1.7.63.71.23 1.36.2 1.87.12.57-.09 1.75-.72 2-1.41.25-.69.25-1.29.17-1.41-.07-.12-.27-.2-.57-.35zM12.04 21.5h-.01a9.43 9.43 0 0 1"
    "-4.8-1.31l-.35-.2-3.57.93.95-3.48-.22-.36a9.4 9.4 0 0 1-1.44-5.02c0-5.2 4.24-9.43 9.45-9.43a9.38 9.38 0 0 1 6.68 2.77 9.37 9.37 0 0 1"
    " 2.76 6.67c0 5.2-4.24 9.43-9.45 9.43zm8.04-17.47A11.3 11.3 0 0 0 12.04.7C5.77.7.67 5.8.67 12.06c0 2 .52 3.96 1.52 5.68L.57 23.5l5.9"
    "-1.55a11.33 11.33 0 0 0 5.57 1.42h.01c6.26 0 11.36-5.1 11.36-11.36 0-3.03-1.18-5.89-3.33-8.03z"
)


@register.simple_tag
def wa_ico():
    return mark_safe(f'<svg class="ico wa-ico" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="{WA_PATH}"/></svg>')


@register.simple_tag
def ico(nombre):
    return mark_safe(f'<svg class="ico" viewBox="0 0 24 24" aria-hidden="true">{ICONOS.get(nombre, "")}</svg>')


@register.filter
def dinero(valor):
    """$12.500 (formato Ecuador, sin decimales si son cero)."""
    try:
        v = Decimal(valor or 0)
    except (InvalidOperation, TypeError):
        return valor
    entero = int(v)
    txt = f"{entero:,}".replace(",", ".")
    cent = int((abs(v) - abs(entero)) * 100)
    return f"${txt},{cent:02d}" if cent else f"${txt}"


@register.filter
def iniciales(user):
    if not user:
        return "?"
    nombre = (user.get_full_name() or user.username).split()
    return "".join(p[0] for p in nombre[:2]).upper()


@register.filter
def nombre(user):
    if not user:
        return "Sistema"
    return user.get_full_name() or user.username


@register.filter
def pct(n, total):
    try:
        return round(n / total * 100) if total else 0
    except (TypeError, ZeroDivisionError):
        return 0


@register.filter
def tiene(conjunto, valor):
    try:
        return valor in conjunto
    except TypeError:
        return False


@register.filter
def clase_resultado(r):
    return {"ganado": "ok", "perdido": "bad", "nuevo": "", "interesado": "ok"}.get(r, "warn")


@register.filter
def tel_wa(numero):
    """Número listo para wa.me (593…)."""
    from crm.services import normalizar_telefono

    return normalizar_telefono(numero)


@register.filter
def tel(numero):
    """+593987654321 para mostrar."""
    n = tel_wa(numero)
    return f"+{n}" if n else ""
