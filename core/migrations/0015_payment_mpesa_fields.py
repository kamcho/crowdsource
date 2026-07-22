import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0014_notificationlog'),
    ]

    operations = [
        migrations.AddField(
            model_name='payment',
            name='amount_kes',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='payment',
            name='callback_payload',
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='payment',
            name='checkout_request_id',
            field=models.CharField(blank=True, db_index=True, max_length=64),
        ),
        migrations.AddField(
            model_name='payment',
            name='merchant_request_id',
            field=models.CharField(blank=True, db_index=True, max_length=64),
        ),
        migrations.AddField(
            model_name='payment',
            name='mpesa_receipt_number',
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AddField(
            model_name='payment',
            name='phone_number',
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name='payment',
            name='result_code',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='payment',
            name='result_description',
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
