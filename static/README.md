# Carpeta static

Coloca aquí archivos estáticos (logo.png, imágenes, CSS adicional, etc.).

El sistema usa el círculo naranja con "O" generado por CSS por defecto. Si quieres reemplazarlo con tu logo real, coloca tu archivo `logo.png` aquí y modifica el `templates/base.html`:

Reemplazar:
```html
<div class="logo-circle">O</div>
```

Por:
```html
{% load static %}
<img src="{% static 'logo.png' %}" alt="Econotec" class="logo-circle">
```
