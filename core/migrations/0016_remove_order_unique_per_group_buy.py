from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0015_payment_mpesa_fields'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='order',
            name='unique_order_per_user_group_buy',
        ),
    ]
