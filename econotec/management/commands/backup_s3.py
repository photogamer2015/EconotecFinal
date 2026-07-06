"""
Backup automático de la base de datos a AWS S3.

Este comando es 100% DE SOLO LECTURA: nunca modifica ni daña la base de datos.
Solo copia el archivo, lo comprime y lo sube al bucket S3 configurado.

Uso manual:
    python manage.py backup_s3

Uso con cron (automático a las 3:00 AM todos los días):
    0 3 * * * cd /ruta/al/proyecto && python manage.py backup_s3

Requisitos en el archivo .env:
    AWS_ACCESS_KEY_ID=tu_access_key
    AWS_SECRET_ACCESS_KEY=tu_secret_key
    AWS_S3_BUCKET_NAME=nombre-de-tu-bucket
    AWS_S3_REGION=us-east-1  (opcional, por defecto us-east-1)
"""
import gzip
import os
import sqlite3
import tempfile
from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        'Crea un backup seguro de la base de datos y lo sube a AWS S3. '
        'Este comando es de SOLO LECTURA: no modifica la base de datos.'
    )

    # ──────────────────────────────────────────────────────────
    # 1. COPIA SEGURA DE SQLite (usando la API oficial de backup)
    # ──────────────────────────────────────────────────────────
    def _crear_copia_sqlite(self, db_path, destino):
        """
        Crea una copia consistente del archivo SQLite usando la API
        oficial de backup de Python. Esto garantiza que la copia
        sea válida incluso si alguien está usando el sistema en
        ese momento. NO TOCA la base de datos original.
        """
        origen = sqlite3.connect(db_path)
        copia = sqlite3.connect(destino)
        origen.backup(copia)
        copia.close()
        origen.close()

    # ──────────────────────────────────────────────────────────
    # 2. COMPRIMIR CON GZIP
    # ──────────────────────────────────────────────────────────
    def _comprimir(self, archivo_origen, archivo_destino):
        """Comprime el archivo .sqlite3 en .gz para ahorrar espacio."""
        with open(archivo_origen, 'rb') as f_in:
            with gzip.open(archivo_destino, 'wb') as f_out:
                f_out.writelines(f_in)

    # ──────────────────────────────────────────────────────────
    # 3. SUBIR A S3
    # ──────────────────────────────────────────────────────────
    def _subir_a_s3(self, archivo_local, s3_key, bucket, region,
                    access_key, secret_key):
        """Sube el archivo comprimido al bucket S3."""
        try:
            import boto3
        except ImportError:
            self.stderr.write(self.style.ERROR(
                '❌ La librería boto3 no está instalada.\n'
                '   Instálala con:  pip install boto3'
            ))
            return False

        try:
            s3 = boto3.client(
                's3',
                region_name=region,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
            )
            s3.upload_file(archivo_local, bucket, s3_key)
            return True
        except Exception as e:
            self.stderr.write(self.style.ERROR(f'❌ Error al subir a S3: {e}'))
            return False

    # ──────────────────────────────────────────────────────────
    # HANDLE PRINCIPAL
    # ──────────────────────────────────────────────────────────
    def handle(self, *args, **options):
        self.stdout.write('')
        self.stdout.write('═' * 60)
        self.stdout.write('  BACKUP AUTOMÁTICO ECONOTEC → AWS S3')
        self.stdout.write('  (Solo lectura — no modifica la base de datos)')
        self.stdout.write('═' * 60)

        # ── Verificar credenciales ────────────────────────────
        access_key = getattr(settings, 'AWS_ACCESS_KEY_ID', '')
        secret_key = getattr(settings, 'AWS_SECRET_ACCESS_KEY', '')
        bucket = getattr(settings, 'AWS_S3_BUCKET_NAME', '')
        region = getattr(settings, 'AWS_S3_REGION', 'us-east-1')

        if not access_key or not secret_key or not bucket:
            self.stderr.write(self.style.ERROR(
                '\n❌ Faltan credenciales de AWS en el archivo .env\n'
                '   Agrega estas líneas a tu archivo .env:\n\n'
                '   AWS_ACCESS_KEY_ID=tu_access_key\n'
                '   AWS_SECRET_ACCESS_KEY=tu_secret_key\n'
                '   AWS_S3_BUCKET_NAME=nombre-de-tu-bucket\n'
                '   AWS_S3_REGION=us-east-1\n'
            ))
            return

        # ── Detectar la base de datos ─────────────────────────
        db_config = settings.DATABASES['default']
        engine = db_config['ENGINE']

        if 'sqlite3' in engine:
            db_path = str(db_config['NAME'])
            if not os.path.exists(db_path):
                self.stderr.write(self.style.ERROR(
                    f'❌ No se encontró la base de datos en: {db_path}'
                ))
                return
            self.stdout.write(f'\n📂 Base de datos: {db_path}')
        else:
            self.stderr.write(self.style.ERROR(
                '❌ Este comando actualmente solo soporta SQLite.\n'
                '   Para MySQL, usa el script bash de backup con mysqldump.'
            ))
            return

        # ── Crear copia segura ────────────────────────────────
        ahora = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        nombre_backup = f'econotec_backup_{ahora}.sqlite3'
        nombre_gz = f'{nombre_backup}.gz'

        tmp_dir = tempfile.mkdtemp(prefix='econotec_backup_')
        ruta_copia = os.path.join(tmp_dir, nombre_backup)
        ruta_gz = os.path.join(tmp_dir, nombre_gz)

        try:
            self.stdout.write('📋 Creando copia segura de la base de datos...')
            self._crear_copia_sqlite(db_path, ruta_copia)
            self.stdout.write(self.style.SUCCESS('   ✅ Copia creada correctamente.'))

            # ── Comprimir ─────────────────────────────────────
            self.stdout.write('📦 Comprimiendo backup...')
            self._comprimir(ruta_copia, ruta_gz)

            tamano_original = os.path.getsize(ruta_copia)
            tamano_gz = os.path.getsize(ruta_gz)
            self.stdout.write(self.style.SUCCESS(
                f'   ✅ Comprimido: {tamano_original:,} bytes → {tamano_gz:,} bytes '
                f'({100 - (tamano_gz * 100 // tamano_original)}% reducción)'
            ))

            # ── Subir a S3 ────────────────────────────────────
            s3_key = f'backup-auto/{nombre_gz}'
            self.stdout.write(f'☁️  Subiendo a s3://{bucket}/{s3_key} ...')

            exito = self._subir_a_s3(
                ruta_gz, s3_key, bucket, region, access_key, secret_key
            )

            if exito:
                self.stdout.write(self.style.SUCCESS(
                    f'   ✅ Backup subido exitosamente a AWS S3.'
                ))
                self.stdout.write('')
                self.stdout.write(self.style.SUCCESS(
                    '═' * 60 + '\n'
                    '  ✅ BACKUP COMPLETADO CON ÉXITO\n'
                    f'  📅 Fecha: {ahora}\n'
                    f'  ☁️  Destino: s3://{bucket}/{s3_key}\n'
                    '═' * 60
                ))
        finally:
            # ── Limpiar archivos temporales ───────────────────
            for f in [ruta_copia, ruta_gz]:
                if os.path.exists(f):
                    os.remove(f)
            if os.path.exists(tmp_dir):
                os.rmdir(tmp_dir)
            self.stdout.write('🧹 Archivos temporales eliminados.')
