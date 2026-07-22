import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('core', '0013_refund'),
    ]

    operations = [
        migrations.CreateModel(
            name='NotificationLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event', models.CharField(db_index=True, max_length=64)),
                ('channel', models.CharField(choices=[('sms', 'SMS'), ('email', 'Email')], max_length=10)),
                ('recipient', models.CharField(max_length=255)),
                ('subject', models.CharField(blank=True, max_length=255)),
                ('body', models.TextField()),
                ('status', models.CharField(choices=[('sent', 'Sent'), ('skipped', 'Skipped'), ('failed', 'Failed')], max_length=10)),
                ('error_message', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='notification_logs', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
