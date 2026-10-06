from django.conf import settings
from django.contrib import messages
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from core.backup_services import backup_zip_path, create_site_backup, list_backups
from core.decorators import admin_required


@admin_required
@require_http_methods(['GET', 'POST'])
def backup_list(request):
    if request.method == 'POST':
        try:
            record = create_site_backup(
                label='manual',
                created_by=request.user.get_full_name() or str(request.user.pk),
            )
            messages.success(
                request,
                f'Backup created: {record.filename} ({record.size_display}).',
            )
        except Exception as exc:
            messages.error(request, f'Backup failed: {exc}')
        return redirect('core:backup_list')

    return render(request, 'core/backups/list.html', {
        'backups': list_backups(),
        'schedule_hour': getattr(settings, 'BACKUP_SCHEDULE_HOUR', 6),
        'retention_days': getattr(settings, 'BACKUP_RETENTION_DAYS', 30),
    })


@admin_required
@require_GET
def backup_download(request, filename):
    try:
        path = backup_zip_path(filename)
    except (ValueError, FileNotFoundError):
        raise Http404('Backup not found.') from None
    return FileResponse(
        path.open('rb'),
        as_attachment=True,
        filename=filename,
        content_type='application/zip',
    )
