import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0001_initial'),
        ('users', '0004_user_totp_secret'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='signup_tenant',
            field=models.ForeignKey(
                blank=True,
                help_text='Tenant where this account was first created.',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='signup_users',
                to='tenants.tenant',
            ),
        ),
    ]
