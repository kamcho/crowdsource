"""Site backup creation (database + media) and retention."""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.utils import timezone

logger = logging.getLogger('crowdsource.backup')

BACKUP_FILENAME_RE = re.compile(
    r'^crowdsource-backup-\d{8}-\d{6}-[a-zA-Z0-9_-]+\.zip$',
)


@dataclass(frozen=True)
class BackupRecord:
    filename: str
    label: str
    size_bytes: int
    created_at: str
    db_engine: str
    include_media: bool
    created_by: str = ''

    @property
    def size_display(self) -> str:
        size = float(self.size_bytes)
        for unit in ('B', 'KB', 'MB', 'GB'):
            if size < 1024 or unit == 'GB':
                if unit == 'B':
                    return f'{int(size)} {unit}'
                return f'{size:.1f} {unit}'
            size /= 1024
        return f'{self.size_bytes} B'


def get_backup_root() -> Path:
    root = Path(getattr(settings, 'BACKUP_ROOT', settings.BASE_DIR / 'backups'))
    root.mkdir(parents=True, exist_ok=True)
    return root


def is_safe_backup_filename(filename: str) -> bool:
    return bool(BACKUP_FILENAME_RE.match(filename or ''))


def backup_zip_path(filename: str) -> Path:
    if not is_safe_backup_filename(filename):
        raise ValueError('Invalid backup filename.')
    path = get_backup_root() / filename
    if not path.is_file():
        raise FileNotFoundError(filename)
    return path


def _meta_path(zip_path: Path) -> Path:
    return zip_path.with_suffix('.meta.json')


def _write_meta(zip_path: Path, record: BackupRecord):
    meta = {
        'filename': record.filename,
        'label': record.label,
        'size_bytes': record.size_bytes,
        'created_at': record.created_at,
        'db_engine': record.db_engine,
        'include_media': record.include_media,
        'created_by': record.created_by,
    }
    _meta_path(zip_path).write_text(json.dumps(meta, indent=2), encoding='utf-8')


def _read_meta(zip_path: Path) -> BackupRecord | None:
    meta_file = _meta_path(zip_path)
    if meta_file.is_file():
        try:
            data = json.loads(meta_file.read_text(encoding='utf-8'))
            return BackupRecord(
                filename=data['filename'],
                label=data.get('label', ''),
                size_bytes=int(data.get('size_bytes', zip_path.stat().st_size)),
                created_at=data.get('created_at', ''),
                db_engine=data.get('db_engine', ''),
                include_media=bool(data.get('include_media', True)),
                created_by=data.get('created_by', ''),
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            logger.debug('Could not read backup meta for %s', zip_path.name, exc_info=True)
    stat = zip_path.stat()
    return BackupRecord(
        filename=zip_path.name,
        label='',
        size_bytes=stat.st_size,
        created_at=timezone.datetime.fromtimestamp(
            stat.st_mtime,
            tz=timezone.get_current_timezone(),
        ).isoformat(),
        db_engine='',
        include_media=True,
        created_by='',
    )


def list_backups() -> list[BackupRecord]:
    root = get_backup_root()
    records = []
    for zip_path in sorted(root.glob('crowdsource-backup-*.zip'), reverse=True):
        record = _read_meta(zip_path)
        if record:
            records.append(record)
    return records


def _db_engine_name() -> str:
    return connection.settings_dict['ENGINE'].rsplit('.', maxsplit=1)[-1]


def _sqlite_uses_memory_store() -> bool:
    name = str(connection.settings_dict.get('NAME', ''))
    return ':memory:' in name or 'mode=memory' in name


def _backup_database_dumpdata(work_dir: Path) -> Path:
    from io import StringIO

    from django.core.management import call_command

    buffer = StringIO()
    call_command(
        'dumpdata',
        exclude=['contenttypes', 'auth.permission'],
        stdout=buffer,
        verbosity=0,
    )
    dump_path = work_dir / 'database.json'
    dump_path.write_text(buffer.getvalue(), encoding='utf-8')
    return dump_path


def _backup_database(work_dir: Path) -> Path:
    engine = connection.settings_dict['ENGINE']
    if 'sqlite' in engine:
        if _sqlite_uses_memory_store():
            return _backup_database_dumpdata(work_dir)
        dest = work_dir / 'database.sqlite3'
        src_conn = connection.connection
        if src_conn is not None:
            dest_conn = sqlite3.connect(dest)
            try:
                src_conn.backup(dest_conn)
            finally:
                dest_conn.close()
            return dest
        db_path = Path(connection.settings_dict['NAME'])
        if not db_path.is_file():
            raise FileNotFoundError(f'SQLite database not found: {db_path}')
        src_conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
        try:
            dest_conn = sqlite3.connect(dest)
            try:
                src_conn.backup(dest_conn)
            finally:
                dest_conn.close()
        finally:
            src_conn.close()
        return dest

    if 'postgresql' in engine:
        dump_path = work_dir / 'database.sql'
        db = connection.settings_dict
        env = {}
        password = db.get('PASSWORD') or ''
        if password:
            env['PGPASSWORD'] = password
        cmd = [
            'pg_dump',
            '--no-owner',
            '--no-acl',
            '-h', str(db.get('HOST') or '127.0.0.1'),
            '-p', str(db.get('PORT') or '5432'),
            '-U', str(db.get('USER') or ''),
            '-d', str(db.get('NAME') or ''),
            '-f', str(dump_path),
        ]
        subprocess.run(cmd, check=True, env={**os.environ, **env})
        return dump_path

    raise RuntimeError(f'Unsupported database engine for backup: {engine}')


def _add_tree_to_zip(zf: zipfile.ZipFile, source: Path, arc_prefix: str):
    if not source.is_dir():
        return
    for path in source.rglob('*'):
        if path.is_file():
            zf.write(path, arcname=f'{arc_prefix}/{path.relative_to(source).as_posix()}')


def create_site_backup(
    *,
    label: str = 'manual',
    created_by: str = '',
    include_media: bool | None = None,
) -> BackupRecord:
    if include_media is None:
        include_media = getattr(settings, 'BACKUP_INCLUDE_MEDIA', True)

    safe_label = re.sub(r'[^a-zA-Z0-9_-]', '-', (label or 'manual').strip())[:32] or 'manual'
    timestamp = timezone.localtime().strftime('%Y%m%d-%H%M%S')
    filename = f'crowdsource-backup-{timestamp}-{safe_label}.zip'
    zip_path = get_backup_root() / filename

    manifest = {
        'created_at': timezone.now().isoformat(),
        'label': safe_label,
        'db_engine': _db_engine_name(),
        'include_media': include_media,
        'django_version': None,
    }
    try:
        import django
        manifest['django_version'] = django.get_version()
    except Exception:
        pass

    with tempfile.TemporaryDirectory(prefix='crowdsource-backup-') as tmp:
        work_dir = Path(tmp)
        db_file = _backup_database(work_dir)
        with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(db_file, arcname=f'database/{db_file.name}')
            manifest_path = work_dir / 'manifest.json'
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
            zf.write(manifest_path, arcname='manifest.json')
            if include_media:
                media_root = Path(settings.MEDIA_ROOT)
                _add_tree_to_zip(zf, media_root, 'media')

    size_bytes = zip_path.stat().st_size
    record = BackupRecord(
        filename=filename,
        label=safe_label,
        size_bytes=size_bytes,
        created_at=manifest['created_at'],
        db_engine=manifest['db_engine'],
        include_media=include_media,
        created_by=created_by,
    )
    _write_meta(zip_path, record)
    logger.info('Created site backup %s (%s bytes)', filename, size_bytes)
    prune_old_backups()
    return record


def prune_old_backups():
    retention_days = int(getattr(settings, 'BACKUP_RETENTION_DAYS', 30))
    if retention_days <= 0:
        return
    cutoff = timezone.now() - timedelta(days=retention_days)
    root = get_backup_root()
    for zip_path in root.glob('crowdsource-backup-*.zip'):
        record = _read_meta(zip_path)
        if not record or not record.created_at:
            continue
        try:
            created = timezone.datetime.fromisoformat(record.created_at)
            if timezone.is_naive(created):
                created = timezone.make_aware(created, timezone.get_current_timezone())
        except ValueError:
            continue
        if created < cutoff:
            zip_path.unlink(missing_ok=True)
            _meta_path(zip_path).unlink(missing_ok=True)
            logger.info('Pruned old backup %s', zip_path.name)
