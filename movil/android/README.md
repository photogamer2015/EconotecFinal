# App de Econotec para Android

Abre https://econosystem.cc/bienvenida/ a pantalla completa con Chrome
(Trusted Web Activity): ícono propio y notificaciones push del sistema.

## Generar el APK

```bash
cd movil/android
export JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home"
gradle assembleRelease
```

Sale en `app/build/outputs/apk/release/app-release.apk`.
Para una actualización, sube `versionCode` en `app/build.gradle`.

## Firma (muy importante)

`econotec-release.keystore` y `keystore.properties` **no se suben a GitHub**.
Guarda una copia de los dos en un lugar seguro: sin ellos no se puede
publicar una actualización que se instale encima de la app actual.

La huella SHA-256 de esa firma está en `ANDROID_APP_SHA256`
(`core/settings.py`) y el sistema la publica en
`/.well-known/assetlinks.json`. Así Android sabe que la app es de
econosystem.cc y la abre sin la barra de dirección.
