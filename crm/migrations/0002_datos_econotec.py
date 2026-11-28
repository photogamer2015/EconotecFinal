"""Datos de inicio del CRM con las líneas de servicio, etiquetas y mensajes de Econotec.
Todo se puede editar después en el CRM (Ajustes de WhatsApp y Etiquetas)."""
from django.db import migrations

# (nombre, lo que responde el bot, palabras clave)
CATEGORIAS = [
    ("Reparación de laptops",
     "Reparamos laptops de todas las marcas: no prende, pantalla, teclado, bisagras, batería, cargador, "
     "sobrecalentamiento, cambio a disco sólido y formateo. El diagnóstico lo hace un técnico.",
     "laptop, portatil, notebook, macbook, bisagra, teclado, pantalla rota, cargador, bateria"),
    ("Reparación de PC y CPU",
     "Reparación y mantenimiento de computadoras de escritorio y CPU: fuente, placa, memoria, disco, "
     "limpieza, formateo e instalación de programas.",
     "pc, cpu, computadora, computador, escritorio, desktop, torre, formateo, formatear, windows, virus, lento"),
    ("Impresoras",
     "Reparación y mantenimiento de impresoras de tinta continua, láser y multifunción: atascos, cabezales, "
     "limpieza, almohadillas y errores de la impresora.",
     "impresora, imprimir, multifuncion, tinta, toner, cabezal, almohadilla, atasco, epson, canon, brother"),
    ("Celulares y tablets",
     "Reparación de celulares y tablets: pantalla, pin de carga, batería, cámara, software y desbloqueo de cuentas.",
     "celular, telefono, iphone, samsung, xiaomi, tablet, ipad, pin de carga, display"),
    ("Consolas y mandos",
     "Reparación de consolas y mandos: PlayStation, Xbox, Nintendo. Drift de joystick, HDMI, sobrecalentamiento y limpieza.",
     "consola, play, playstation, ps4, ps5, xbox, nintendo, switch, mando, control, joystick, drift"),
    ("Monitores",
     "Reparación de monitores y pantallas: no da imagen, rayas, retroiluminación y fuente.",
     "monitor, pantalla, no da imagen, rayas, televisor"),
    ("Máquinas de coser",
     "Mantenimiento y reparación de máquinas de coser domésticas e industriales.",
     "maquina de coser, coser, costura, overlock, recta"),
    ("Venta de productos y accesorios",
     "Venta de repuestos, accesorios, cargadores, discos sólidos, memorias y equipos disponibles en inventario.",
     "comprar, venta, venden, accesorio, repuesto, disco solido, ssd, memoria ram, mouse, cargador original"),
    ("Equipos reacondicionados",
     "Equipos reacondicionados revisados por nuestros técnicos, listos para usar y con garantía.",
     "reacondicionado, reacondicionada, segunda mano, usado, usada, economico"),
    ("Servicio a domicilio",
     "Vamos a tu casa u oficina para retirar el equipo o hacer el mantenimiento en sitio.",
     "domicilio, a domicilio, retiren, retirar, vengan, visita tecnica, en sitio"),
]

RESPUESTAS_BOT = [
    ("Saludo", "hola, holi, buenas, buenos dias, buenas tardes, buenas noches, que tal, saludos, hey",
     "¡Hola {nombre}! 👋 Gracias por escribir a *Econotec*, reparación de tecnología. ¿En qué te podemos ayudar?\n\n{menu}"),
    ("Información y servicios", "informacion, info, servicios, que hacen, que reparan, que ofrecen",
     "En *Econotec* reparamos laptops, PC, impresoras, celulares, tablets, consolas, monitores y máquinas de coser. "
     "También vendemos accesorios y equipos reacondicionados.\n\n{menu}"),
    ("Precio y diagnóstico", "precio, costo, cuanto cuesta, cuanto vale, cuanto cobran, cotizacion, cotizar, presupuesto, diagnostico",
     "El valor depende del equipo y de la falla. Primero el técnico hace el *diagnóstico* y te enviamos la cotización "
     "antes de reparar: tú decides si se repara.\n\n{menu}"),
    ("Horario y ubicación", "horario, hora de atencion, atienden, abren, direccion, ubicacion, donde estan, oficina, sucursal",
     "Atendemos {horario}, en nuestras oficinas de *Guayaquil* y *Quito*. Escribe *asesor* y te enviamos la ubicación exacta.\n\n{menu}"),
    ("Estado de mi equipo", "mi equipo, estado, ya esta listo, esta listo, ya repararon, como va, avance, codigo",
     "Para revisar el estado de tu equipo escríbenos el *código* que está en tu hoja de ingreso (por ejemplo G125). "
     "Una asesora te responde enseguida."),
    ("Garantía", "garantia, volvio a fallar, sigue fallando, reclamo",
     "Las reparaciones tienen garantía según el trabajo realizado (indicada en tu hoja de salida). "
     "Escríbenos tu *código* de equipo y lo revisamos."),
    ("Formas de pago", "forma de pago, formas de pago, pagar, transferencia, tarjeta, efectivo, deuna, factura",
     "Aceptamos *efectivo*, *transferencia bancaria* y *tarjeta de crédito o débito*. Emitimos factura."),
    ("Gracias y despedida", "gracias, muchas gracias, chao, adios, hasta luego",
     "¡Gracias por escribir a Econotec, {nombre}! Si necesitas algo más, aquí estamos."),
]

# Mensajes predeterminados (sin palabras clave): se usan con el botón «Enviar por WhatsApp».
PLANTILLAS = [
    ("Saludo de la asesora", True,
     "Hola {nombre}, le saluda {asesor} de *Econotec*. Recibimos su consulta sobre *{servicio}*. "
     "¿Me indica marca y modelo del equipo y qué falla presenta?"),
    ("Invitar a traer el equipo", False,
     "Hola {nombre}, puede traer {equipo} a nuestra oficina ({horario}). El técnico hace el diagnóstico y le enviamos "
     "la cotización antes de reparar. Saludos, {asesor}."),
    ("Envío de cotización", False,
     "Hola {nombre}, le comparto la cotización de la reparación de {equipo}. Si está de acuerdo, procedemos. "
     "Quedo atenta a sus comentarios."),
    ("Seguimiento de cotización", False,
     "Hola {nombre}, ¿pudo revisar la cotización de {equipo}? Si tiene dudas, con gusto las resolvemos por aquí."),
    ("Servicio a domicilio", False,
     "Hola {nombre}, le confirmamos el servicio a domicilio. ¿Nos comparte la dirección y una hora en la que podamos ir? "
     "Saludos, {asesor}."),
    ("Agradecimiento", False,
     "Hola {nombre}, gracias por confiar en *Econotec*. Cualquier novedad de su equipo le escribo por aquí. Saludos, {asesor}."),
]

ETIQUETAS = [
    ("Urgente", "rojo"), ("Cliente frecuente", "verde"), ("Garantía", "ambar"), ("A domicilio", "turquesa"),
    ("Requiere factura", "azul"), ("Espera de repuesto", "morado"), ("Empresa", "gris"), ("Referido", "rosa"),
]


def cargar(apps, schema_editor):
    Categoria = apps.get_model("crm", "Categoria")
    Respuesta = apps.get_model("crm", "Respuesta")
    Etiqueta = apps.get_model("crm", "Etiqueta")
    Configuracion = apps.get_model("crm", "Configuracion")
    for i, (nombre, desc, pal) in enumerate(CATEGORIAS, start=1):
        Categoria.objects.get_or_create(nombre=nombre, defaults={"descripcion": desc, "palabras_clave": pal, "orden": i})
    if not Respuesta.objects.exists():
        for i, (titulo, pal, texto) in enumerate(RESPUESTAS_BOT, start=1):
            Respuesta.objects.create(titulo=titulo, palabras_clave=pal, texto=texto, orden=i * 10)
        for i, (titulo, pred, texto) in enumerate(PLANTILLAS, start=1):
            Respuesta.objects.create(titulo=titulo, palabras_clave="", texto=texto, predeterminada=pred, orden=i)
    for nombre, color in ETIQUETAS:
        Etiqueta.objects.get_or_create(nombre=nombre, defaults={"color": color})
    Configuracion.objects.get_or_create(pk=1)


class Migration(migrations.Migration):
    dependencies = [("crm", "0001_inicial")]
    operations = [migrations.RunPython(cargar, migrations.RunPython.noop)]
