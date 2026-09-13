# Generated manually for import costing

from decimal import Decimal

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0025_category_go_together_links'),
    ]

    operations = [
        migrations.CreateModel(
            name='ImportShipment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=120)),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddField(
            model_name='importbatch',
            name='shipment',
            field=models.ForeignKey(
                blank=True,
                help_text='Physical shipment batch when several group buys travel together.',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='import_batches',
                to='core.importshipment',
            ),
        ),
        migrations.AddField(
            model_name='importbatch',
            name='supplier_unit_cost',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='What you paid the supplier per unit (USD).',
                max_digits=12,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='importbatch',
            name='target_margin_percent',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('16.00'),
                help_text='Suggested markup on landed cost (%).',
                max_digits=5,
            ),
        ),
        migrations.AddField(
            model_name='importbatch',
            name='units_imported',
            field=models.PositiveIntegerField(
                blank=True,
                help_text='Units in this import run (defaults to pledged units if empty).',
                null=True,
            ),
        ),
        migrations.CreateModel(
            name='ImportBatchAdditionalCost',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('cost_type', models.CharField(
                    choices=[
                        ('china_warehouse', 'China → warehouse'),
                        ('international_freight', 'Freight to Kenya'),
                        ('customs', 'Customs & clearance'),
                        ('inland', 'Inland transport (e.g. Nakuru)'),
                        ('other', 'Other'),
                    ],
                    max_length=32,
                )),
                ('description', models.CharField(blank=True, max_length=255)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=12)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('import_batch', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='additional_costs',
                    to='core.importbatch',
                )),
            ],
            options={
                'ordering': ['created_at'],
            },
        ),
        migrations.CreateModel(
            name='ImportShipmentSharedCost',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('cost_type', models.CharField(
                    choices=[
                        ('china_warehouse', 'China → warehouse'),
                        ('international_freight', 'Freight to Kenya'),
                        ('customs', 'Customs & clearance'),
                        ('inland', 'Inland transport (e.g. Nakuru)'),
                        ('other', 'Other'),
                    ],
                    max_length=32,
                )),
                ('description', models.CharField(blank=True, max_length=255)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=12)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('shipment', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='shared_costs',
                    to='core.importshipment',
                )),
            ],
            options={
                'ordering': ['created_at'],
            },
        ),
    ]
