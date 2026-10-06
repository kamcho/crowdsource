from django.core.management.base import BaseCommand, CommandError

from core.backup_services import BackupRecord, create_site_backup


class Command(BaseCommand):
    help = 'Create a zip backup of the database and uploaded media.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--label',
            default='auto',
            help='Short label embedded in the backup filename (default: auto).',
        )
        parser.add_argument(
            '--no-media',
            action='store_true',
            help='Skip media files (database only).',
        )

    def handle(self, *args, **options):
        label = (options['label'] or 'auto').strip()
        try:
            record: BackupRecord = create_site_backup(
                label=label,
                include_media=not options['no_media'],
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(f'Backup created: {record.filename} ({record.size_display})'),
        )
