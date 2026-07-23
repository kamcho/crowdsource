import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('core', '0020_cart_product_level_item'),
    ]

    operations = [
        migrations.CreateModel(
            name='Complaint',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('reference', models.CharField(editable=False, max_length=40, unique=True)),
                ('category', models.CharField(choices=[('delivery', 'Delivery issue'), ('product_quality', 'Product quality'), ('payment', 'Payment issue'), ('wrong_item', 'Wrong item received'), ('missing_item', 'Missing item'), ('other', 'Other')], max_length=30)),
                ('subject', models.CharField(max_length=200)),
                ('description', models.TextField()),
                ('status', models.CharField(choices=[('open', 'Open'), ('in_progress', 'In progress'), ('resolved', 'Resolved'), ('closed', 'Closed')], default='open', max_length=20)),
                ('staff_notes', models.TextField(blank=True, help_text='Internal notes for ops — not shown to the customer.')),
                ('resolved_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('order', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='complaints', to='core.order')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='complaints', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='ComplaintMessage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('body', models.TextField()),
                ('is_staff_reply', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('author', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='complaint_messages', to=settings.AUTH_USER_MODEL)),
                ('complaint', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='messages', to='core.complaint')),
            ],
            options={
                'ordering': ['created_at'],
            },
        ),
    ]
