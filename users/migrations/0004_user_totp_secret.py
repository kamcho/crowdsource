from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0003_user_two_factor_enabled'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='totp_secret',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Base32 secret for authenticator-app TOTP (internal).',
                max_length=64,
            ),
        ),
        migrations.AlterField(
            model_name='user',
            name='two_factor_enabled',
            field=models.BooleanField(
                default=False,
                help_text='Require an authenticator-app code when signing in.',
            ),
        ),
    ]
