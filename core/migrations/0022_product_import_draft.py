# Generated migration for product import wizard

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('core', '0021_complaint'),
    ]

    operations = [
        migrations.CreateModel(
            name='ProductImportDraft',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source_url', models.URLField(blank=True)),
                ('raw_paste', models.TextField(blank=True)),
                ('draft_data', models.JSONField(blank=True, default=dict)),
                ('current_step', models.CharField(choices=[('basics', 'Product details'), ('attributes', 'Specifications'), ('variations', 'Variations & pricing'), ('product_media', 'Product images'), ('variation_media', 'Variation images'), ('review', 'Review & publish')], default='basics', max_length=30)),
                ('status', models.CharField(choices=[('parsing', 'Parsing'), ('in_progress', 'In progress'), ('completed', 'Completed'), ('failed', 'Failed'), ('discarded', 'Discarded')], default='parsing', max_length=20)),
                ('parse_error', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='product_import_drafts', to=settings.AUTH_USER_MODEL)),
                ('product', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='import_drafts', to='core.product')),
            ],
            options={
                'ordering': ['-updated_at'],
            },
        ),
        migrations.CreateModel(
            name='ProductImportMedia',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('variation_sku', models.CharField(blank=True, help_text='Blank for product-level media.', max_length=80)),
                ('file', models.FileField(upload_to='import_drafts/%Y/%m/')),
                ('is_primary', models.BooleanField(default=False)),
                ('sort_order', models.PositiveIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('draft', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='media_files', to='core.productimportdraft')),
            ],
            options={
                'ordering': ['variation_sku', 'sort_order', 'id'],
            },
        ),
    ]
