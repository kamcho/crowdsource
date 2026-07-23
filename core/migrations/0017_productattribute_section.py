from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0016_remove_order_unique_per_group_buy'),
    ]

    operations = [
        migrations.AddField(
            model_name='productattribute',
            name='section',
            field=models.CharField(
                choices=[
                    ('key', 'Key attributes'),
                    ('packaging', 'Packaging and delivery'),
                ],
                default='key',
                max_length=20,
            ),
        ),
    ]
