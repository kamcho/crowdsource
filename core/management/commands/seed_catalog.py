from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.group_buy import GroupBuy, GroupBuyEntry
from core.import_batch import ImportBatch
from core.import_services import create_import_batch
from core.cart import Cart, CartItem
from core.order import Order, OrderItem
from core.payment import Payment
from core.models import Category, Product
from core.supplier import Supplier
from core.product_attribute import ProductAttribute
from core.product_file import ProductFile
from core.product_variation import ProductOption, ProductOptionValue, ProductVariation
from users.models import User

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / 'fixtures' / 'seed_images'

CATEGORY_TREE = [
    {
        'name': 'Electronics',
        'description': 'Consumer electronics, gadgets, and office tech.',
        'children': [
            {
                'name': 'Consumer Electronics',
                'children': [
                    {'name': 'Earphones & Headphones'},
                    {'name': 'Smart Watches'},
                ],
            },
            {
                'name': 'Computer & Office',
                'children': [
                    {'name': 'Laptop Accessories'},
                ],
            },
        ],
    },
    {
        'name': 'Home & Garden',
        'description': 'Kitchen, dining, decor, and household essentials.',
        'children': [
            {
                'name': 'Kitchen & Dining',
                'children': [
                    {'name': 'Drinkware'},
                ],
            },
            {
                'name': 'Home Decor',
                'children': [
                    {'name': 'Lighting'},
                ],
            },
        ],
    },
    {
        'name': 'Apparel & Accessories',
        'description': 'Bags, fashion accessories, and everyday carry.',
        'children': [
            {
                'name': 'Bags & Accessories',
                'children': [
                    {'name': 'Tote Bags'},
                ],
            },
        ],
    },
]

SUPPLIERS = [
    {
        'name': 'Shenzhen AudioTech Co.',
        'contact_name': 'Li Wei',
        'phone': '+86 755 1234 5678',
        'wechat_id': 'audiotech_li',
        'country': 'China',
        'notes': 'Primary electronics factory partner.',
    },
    {
        'name': 'Guangzhou HomeGoods Trading',
        'contact_name': 'Chen Mei',
        'phone': '+86 20 8765 4321',
        'wechat_id': 'homegoods_chen',
        'country': 'China',
    },
    {
        'name': 'Yiwu Fashion Export Ltd.',
        'contact_name': 'Zhang Min',
        'wechat_id': 'yiwu_zhang',
        'country': 'China',
    },
]

PRODUCT_SUPPLIER_MAP = {
    'Wireless Earbuds Pro': 'Shenzhen AudioTech Co.',
    'Smart Fitness Watch': 'Shenzhen AudioTech Co.',
    'USB-C Hub 7-in-1': 'Shenzhen AudioTech Co.',
    'Insulated Steel Water Bottle': 'Guangzhou HomeGoods Trading',
    'Minimal LED Desk Lamp': 'Guangzhou HomeGoods Trading',
    'Canvas Tote Bag': 'Yiwu Fashion Export Ltd.',
}

PRODUCTS = [
    {
        'name': 'Wireless Earbuds Pro',
        'category_path': ['Electronics', 'Consumer Electronics', 'Earphones & Headphones'],
        'description': (
            'Premium noise-cancelling wireless earbuds with charging case. '
            'Factory-direct pricing for crowd buys.'
        ),
        'image_name': 'wireless-earbuds-pro.jpg',
    },
    {
        'name': 'Smart Fitness Watch',
        'category_path': ['Electronics', 'Consumer Electronics', 'Smart Watches'],
        'description': (
            'Heart-rate monitoring, GPS tracking, and 7-day battery life. '
            'Ideal for bulk import orders.'
        ),
        'image_name': 'smart-fitness-watch.jpg',
    },
    {
        'name': 'USB-C Hub 7-in-1',
        'category_path': ['Electronics', 'Computer & Office', 'Laptop Accessories'],
        'description': (
            'HDMI, USB 3.0, SD card reader, and 100W PD charging in one compact hub.'
        ),
        'image_name': 'usb-c-hub.jpg',
    },
    {
        'name': 'Insulated Steel Water Bottle',
        'category_path': ['Home & Garden', 'Kitchen & Dining', 'Drinkware'],
        'description': (
            'Double-wall vacuum insulated bottle. Keeps drinks cold 24h or hot 12h. '
            'Custom logo available at MOQ.'
        ),
        'image_name': 'steel-water-bottle.jpg',
    },
    {
        'name': 'Minimal LED Desk Lamp',
        'category_path': ['Home & Garden', 'Home Decor', 'Lighting'],
        'description': (
            'Adjustable brightness and color temperature. USB-C powered with touch controls.'
        ),
        'image_name': 'led-desk-lamp.jpg',
    },
    {
        'name': 'Canvas Tote Bag',
        'category_path': ['Apparel & Accessories', 'Bags & Accessories', 'Tote Bags'],
        'description': (
            'Heavy-duty cotton canvas tote with reinforced handles. '
            'Multiple colors available for bulk orders.'
        ),
        'image_name': 'canvas-tote-bag.jpg',
    },
]

PRODUCT_VARIATIONS = {
    'Wireless Earbuds Pro': {
        'options': [
            {'name': 'Color', 'sort_order': 0, 'values': ['Black', 'White']},
            {'name': 'Version', 'sort_order': 1, 'values': ['Standard', 'Pro ANC']},
        ],
        'variations': [
            {'sku': 'WEBP-BLK-STD', 'price': '12.50', 'Color': 'Black', 'Version': 'Standard'},
            {'sku': 'WEBP-BLK-ANC', 'price': '15.00', 'Color': 'Black', 'Version': 'Pro ANC'},
            {'sku': 'WEBP-WHT-STD', 'price': '12.50', 'Color': 'White', 'Version': 'Standard'},
            {'sku': 'WEBP-WHT-ANC', 'price': '15.00', 'Color': 'White', 'Version': 'Pro ANC'},
        ],
    },
    'Smart Fitness Watch': {
        'options': [
            {'name': 'Color', 'sort_order': 0, 'values': ['Black', 'Silver', 'Rose Gold']},
            {'name': 'Band Size', 'sort_order': 1, 'values': ['S/M', 'L/XL']},
        ],
        'variations': [
            {'sku': 'SFW-BLK-SM', 'price': '18.90', 'Color': 'Black', 'Band Size': 'S/M'},
            {'sku': 'SFW-BLK-LX', 'price': '18.90', 'Color': 'Black', 'Band Size': 'L/XL'},
            {'sku': 'SFW-SLV-SM', 'price': '19.50', 'Color': 'Silver', 'Band Size': 'S/M'},
            {'sku': 'SFW-SLV-LX', 'price': '19.50', 'Color': 'Silver', 'Band Size': 'L/XL'},
            {'sku': 'SFW-RGD-SM', 'price': '20.00', 'Color': 'Rose Gold', 'Band Size': 'S/M'},
            {'sku': 'SFW-RGD-LX', 'price': '20.00', 'Color': 'Rose Gold', 'Band Size': 'L/XL'},
        ],
    },
    'USB-C Hub 7-in-1': {
        'options': [
            {'name': 'Finish', 'sort_order': 0, 'values': ['Space Gray', 'Silver']},
        ],
        'variations': [
            {'sku': 'HUB7-SG', 'price': '9.80', 'Finish': 'Space Gray'},
            {'sku': 'HUB7-SL', 'price': '9.80', 'Finish': 'Silver'},
        ],
    },
    'Insulated Steel Water Bottle': {
        'options': [
            {'name': 'Capacity', 'sort_order': 0, 'values': ['500ml', '750ml', '1L']},
            {'name': 'Color', 'sort_order': 1, 'values': ['Matte Black', 'White', 'Navy']},
        ],
        'variations': [
            {'sku': 'BTL-500-BLK', 'price': '4.20', 'Capacity': '500ml', 'Color': 'Matte Black'},
            {'sku': 'BTL-500-WHT', 'price': '4.20', 'Capacity': '500ml', 'Color': 'White'},
            {'sku': 'BTL-500-NVY', 'price': '4.40', 'Capacity': '500ml', 'Color': 'Navy'},
            {'sku': 'BTL-750-BLK', 'price': '4.80', 'Capacity': '750ml', 'Color': 'Matte Black'},
            {'sku': 'BTL-750-WHT', 'price': '4.80', 'Capacity': '750ml', 'Color': 'White'},
            {'sku': 'BTL-1L-BLK', 'price': '5.20', 'Capacity': '1L', 'Color': 'Matte Black'},
        ],
    },
    'Minimal LED Desk Lamp': {
        'options': [
            {'name': 'Color', 'sort_order': 0, 'values': ['White', 'Black']},
            {'name': 'Model', 'sort_order': 1, 'values': ['Standard', 'Touch Pro']},
        ],
        'variations': [
            {'sku': 'LMP-WHT-STD', 'price': '8.20', 'Color': 'White', 'Model': 'Standard'},
            {'sku': 'LMP-WHT-PRO', 'price': '10.50', 'Color': 'White', 'Model': 'Touch Pro'},
            {'sku': 'LMP-BLK-STD', 'price': '8.20', 'Color': 'Black', 'Model': 'Standard'},
            {'sku': 'LMP-BLK-PRO', 'price': '10.50', 'Color': 'Black', 'Model': 'Touch Pro'},
        ],
    },
    'Canvas Tote Bag': {
        'options': [
            {'name': 'Color', 'sort_order': 0, 'values': ['Natural', 'Black', 'Navy']},
            {'name': 'Size', 'sort_order': 1, 'values': ['Medium', 'Large']},
        ],
        'variations': [
            {'sku': 'TOTE-NAT-M', 'price': '2.10', 'Color': 'Natural', 'Size': 'Medium'},
            {'sku': 'TOTE-NAT-L', 'price': '2.40', 'Color': 'Natural', 'Size': 'Large'},
            {'sku': 'TOTE-BLK-M', 'price': '2.20', 'Color': 'Black', 'Size': 'Medium'},
            {'sku': 'TOTE-BLK-L', 'price': '2.50', 'Color': 'Black', 'Size': 'Large'},
            {'sku': 'TOTE-NVY-M', 'price': '2.20', 'Color': 'Navy', 'Size': 'Medium'},
            {'sku': 'TOTE-NVY-L', 'price': '2.50', 'Color': 'Navy', 'Size': 'Large'},
        ],
    },
}


PRODUCT_ATTRIBUTES = {
    'Wireless Earbuds Pro': [
        {'title': 'Bluetooth', 'description': 'Bluetooth 5.3 with multipoint pairing', 'sort_order': 0},
        {'title': 'Battery', 'description': 'Up to 8 hours playback per charge', 'sort_order': 1},
        {'title': 'Water resistance', 'description': 'IPX5 sweat and splash resistant', 'sort_order': 2},
    ],
    'Smart Fitness Watch': [
        {'title': 'Display', 'description': '1.4" AMOLED always-on display', 'sort_order': 0},
        {'title': 'Sensors', 'description': 'Heart rate, SpO2, and GPS tracking', 'sort_order': 1},
    ],
    'Insulated Steel Water Bottle': [
        {'title': 'Material', 'description': '18/8 stainless steel, BPA-free lid', 'sort_order': 0},
        {'title': 'Insulation', 'description': 'Double-wall vacuum insulation', 'sort_order': 1},
    ],
}

VARIATION_ATTRIBUTES = {
    'WEBP-BLK-ANC': [
        {'title': 'Noise cancellation', 'description': 'Hybrid ANC up to 35dB', 'sort_order': 0},
    ],
    'WEBP-WHT-ANC': [
        {'title': 'Noise cancellation', 'description': 'Hybrid ANC up to 35dB', 'sort_order': 0},
    ],
    'SFW-RGD-SM': [
        {'title': 'Finish', 'description': 'Rose gold aluminum case with silicone band', 'sort_order': 0},
    ],
}


GROUP_BUYS = {
    'Wireless Earbuds Pro': {'moq': 500, 'unit_price': '12.50', 'pledged': 342, 'days': 4},
    'Smart Fitness Watch': {'moq': 300, 'unit_price': '18.90', 'pledged': 187, 'days': 7},
    'USB-C Hub 7-in-1': {'moq': 400, 'unit_price': '9.80', 'pledged': 256, 'days': 5},
    'Insulated Steel Water Bottle': {'moq': 1000, 'unit_price': '4.80', 'pledged': 1000, 'days': 2, 'moq_reached': True},
    'Minimal LED Desk Lamp': {'moq': 300, 'unit_price': '8.20', 'pledged': 145, 'days': 10},
    'Canvas Tote Bag': {'moq': 2000, 'unit_price': '2.10', 'pledged': 1450, 'days': 6},
}


class Command(BaseCommand):
    help = 'Seed Alibaba-style categories, products, images, and variation data.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Remove existing categories and products before seeding.',
        )
        parser.add_argument(
            '--group-buys',
            action='store_true',
            help='Seed or refresh group buys for existing products.',
        )
        parser.add_argument(
            '--variations',
            action='store_true',
            help='Seed or refresh product options, variations, attributes, and variation media.',
        )

    def handle(self, *args, **options):
        with transaction.atomic():
            if options['clear']:
                self.stdout.write('Clearing existing catalog data…')
                GroupBuyEntry.objects.all().delete()
                GroupBuy.objects.all().delete()
                OrderItem.objects.all().delete()
                Order.objects.all().delete()
                Payment.objects.all().delete()
                CartItem.objects.all().delete()
                Cart.objects.all().delete()
                ProductAttribute.objects.all().delete()
                ProductVariation.objects.all().delete()
                ProductOptionValue.objects.all().delete()
                ProductOption.objects.all().delete()
                ProductFile.objects.all().delete()
                Product.objects.all().delete()
                Supplier.objects.all().delete()
                Category.objects.all().delete()

            if options['group_buys']:
                self._seed_group_buys()
                return

            if options['variations']:
                self._seed_variations()
                return

            if Category.objects.exists():
                self.stdout.write(self.style.WARNING(
                    'Catalog data already exists. Use --clear to replace it, or --variations to add SKUs.'
                ))
                return

            category_map = self._create_categories(CATEGORY_TREE)
            supplier_map = self._seed_suppliers()
            self._create_products(category_map, supplier_map)
            self._seed_variations()
            self._seed_group_buys()

        self.stdout.write(self.style.SUCCESS(
            f'Seeded {Category.objects.count()} categories, '
            f'{Product.objects.count()} products, and '
            f'{GroupBuy.objects.count()} group buys.'
        ))

    def _create_categories(self, tree, parent=None, path=None):
        path = path or []
        category_map = {}

        for node in tree:
            current_path = path + [node['name']]
            category, _ = Category.objects.get_or_create(
                parent=parent,
                name=node['name'],
                defaults={'description': node.get('description', '')},
            )
            category_map[tuple(current_path)] = category
            self.stdout.write(f'  Category: {category.get_breadcrumb()}')

            for child in node.get('children', []):
                if 'children' in child:
                    category_map.update(
                        self._create_categories([child], parent=category, path=current_path)
                    )
                else:
                    leaf_path = current_path + [child['name']]
                    leaf, _ = Category.objects.get_or_create(
                        parent=category,
                        name=child['name'],
                        defaults={'description': child.get('description', '')},
                    )
                    category_map[tuple(leaf_path)] = leaf
                    self.stdout.write(f'  Category: {leaf.get_breadcrumb()}')

        return category_map

    def _seed_suppliers(self):
        supplier_map = {}
        for data in SUPPLIERS:
            supplier, _ = Supplier.objects.update_or_create(
                name=data['name'],
                defaults=data,
            )
            supplier_map[data['name']] = supplier
            self.stdout.write(f'  Supplier: {supplier.name}')
        return supplier_map

    def _create_products(self, category_map, supplier_map):
        for item in PRODUCTS:
            category = category_map[tuple(item['category_path'])]
            supplier_name = PRODUCT_SUPPLIER_MAP.get(item['name'])
            supplier = supplier_map.get(supplier_name) if supplier_name else None
            product, created = Product.objects.get_or_create(
                name=item['name'],
                defaults={
                    'category': category,
                    'supplier': supplier,
                    'description': item['description'],
                },
            )
            if not created:
                product.category = category
                product.supplier = supplier
                product.description = item['description']
                product.save()

            self.stdout.write(f'  Product: {product.name}')

            if product.files.exists():
                continue

            image_data = self._load_image(item['image_name'])
            if image_data:
                product_file = ProductFile(
                    product=product,
                    media_type=ProductFile.MediaType.IMAGE,
                    caption=item['name'],
                    sort_order=0,
                    is_primary=True,
                )
                product_file.file.save(item['image_name'], ContentFile(image_data), save=True)
                self.stdout.write(f'    Image: {product_file.file.name}')
            else:
                self.stdout.write(self.style.WARNING(f'    Missing image: {item["image_name"]}'))

    def _seed_variations(self):
        total_variations = 0
        for product_name, config in PRODUCT_VARIATIONS.items():
            product = Product.objects.filter(name=product_name).first()
            if not product:
                self.stdout.write(self.style.WARNING(f'  Skipped variations — product not found: {product_name}'))
                continue

            GroupBuyEntry.objects.filter(group_buy__product=product).delete()
            ProductVariation.objects.filter(product=product).delete()
            ProductOption.objects.filter(product=product).delete()

            value_lookup = {}
            for option_config in config['options']:
                option = ProductOption.objects.create(
                    product=product,
                    name=option_config['name'],
                    sort_order=option_config['sort_order'],
                )
                for sort_order, value_label in enumerate(option_config['values']):
                    option_value = ProductOptionValue.objects.create(
                        option=option,
                        value=value_label,
                        sort_order=sort_order,
                    )
                    value_lookup[(option.name, value_label)] = option_value
                self.stdout.write(f'  Option: {product.name} — {option.name} ({option.values.count()} values)')

            for variation_config in config['variations']:
                option_values = []
                for option_config in config['options']:
                    option_name = option_config['name']
                    value_label = variation_config[option_name]
                    option_values.append(value_lookup[(option_name, value_label)])

                variation = ProductVariation.objects.create(
                    product=product,
                    sku=variation_config['sku'],
                    price=Decimal(variation_config['price']),
                    is_active=True,
                )
                variation.option_values.set(option_values)
                total_variations += 1

            self.stdout.write(f'  Variations: {product.name} ({len(config["variations"])} SKUs)')

        self._seed_attributes_and_variation_media()

        self.stdout.write(self.style.SUCCESS(
            f'Seeded {ProductOption.objects.count()} options, '
            f'{ProductOptionValue.objects.count()} values, and '
            f'{total_variations} variations.'
        ))

    def _seed_group_buys(self):
        demo_user, _ = User.objects.get_or_create(
            phone='+254700000001',
            defaults={
                'first_name': 'Demo',
                'last_name': 'Buyer',
                'email': 'demo@crowdsource.local',
            },
        )
        if not demo_user.has_usable_password():
            demo_user.set_password('demo-pass-123')
            demo_user.save()

        for product_name, config in GROUP_BUYS.items():
            product = Product.objects.filter(name=product_name).first()
            if not product:
                continue

            status = GroupBuy.Status.MOQ_REACHED if config.get('moq_reached') else GroupBuy.Status.OPEN
            group_buy, _ = GroupBuy.objects.update_or_create(
                product=product,
                defaults={
                    'moq': config['moq'],
                    'unit_price': Decimal(config['unit_price']),
                    'closes_at': timezone.now() + timedelta(days=config['days']),
                    'status': GroupBuy.Status.OPEN,
                },
            )

            GroupBuyEntry.objects.filter(group_buy=group_buy).delete()
            pledged = config.get('pledged', 0)
            if pledged > 0:
                variation = product.variations.filter(is_active=True).first()
                GroupBuyEntry.objects.create(
                    group_buy=group_buy,
                    user=demo_user,
                    variation=variation,
                    quantity=pledged,
                )

            if status == GroupBuy.Status.MOQ_REACHED:
                group_buy.status = GroupBuy.Status.MOQ_REACHED
                group_buy.save(update_fields=['status', 'updated_at'])
            else:
                group_buy.refresh_status()

            self.stdout.write(
                f'  Group buy: {product.name} — '
                f'{group_buy.pledged_units}/{group_buy.moq} ({group_buy.get_status_display()})'
            )

        self._seed_import_batches()

    def _seed_import_batches(self):
        moq_reached = list(
            GroupBuy.objects.filter(status=GroupBuy.Status.MOQ_REACHED)
            .select_related('product')
            .order_by('id')
        )
        if not moq_reached:
            return

        ImportBatch.objects.all().delete()

        demo_batch = moq_reached[0]
        create_import_batch(
            demo_batch,
            supplier=demo_batch.product.supplier,
            supplier_reference='PO-2026-001',
            estimated_arrival=(timezone.now() + timedelta(days=21)).date(),
            notes='Demo import batch for seeded catalog.',
        )
        batch = demo_batch.import_batch
        batch.status = ImportBatch.Status.IN_TRANSIT
        batch.save(update_fields=['status', 'updated_at'])

        supplier_label = batch.supplier.name if batch.supplier_id else 'No supplier'
        self.stdout.write(
            self.style.SUCCESS(
                f'  Import batch: {demo_batch.product.name} — {supplier_label} — in transit (PO-2026-001)'
            )
        )

    def _seed_attributes_and_variation_media(self):
        ProductAttribute.objects.all().delete()
        ProductFile.objects.filter(variation__isnull=False).delete()

        for product_name, attributes in PRODUCT_ATTRIBUTES.items():
            product = Product.objects.filter(name=product_name).first()
            if not product:
                continue
            for attribute_data in attributes:
                ProductAttribute.objects.create(product=product, **attribute_data)
            self.stdout.write(f'  Attributes: {product.name} ({len(attributes)} product-level)')

        for sku, attributes in VARIATION_ATTRIBUTES.items():
            variation = ProductVariation.objects.filter(sku=sku).select_related('product').first()
            if not variation:
                continue
            for attribute_data in attributes:
                ProductAttribute.objects.create(
                    product=variation.product,
                    variation=variation,
                    **attribute_data,
                )

        for product in Product.objects.prefetch_related('variations__option_values__option', 'files'):
            source_file = product.files.filter(
                variation__isnull=True,
                media_type=ProductFile.MediaType.IMAGE,
            ).first()
            if not source_file:
                continue

            with source_file.file.open('rb') as handle:
                image_bytes = handle.read()

            seeded_colors = set()
            for variation in product.variations.filter(is_active=True):
                color_value = next(
                    (
                        option_value.value
                        for option_value in variation.option_values.all()
                        if option_value.option.name.lower() == 'color'
                    ),
                    None,
                )
                seed_key = color_value or variation.sku
                if seed_key in seeded_colors:
                    continue
                seeded_colors.add(seed_key)

                product_file = ProductFile(
                    product=product,
                    variation=variation,
                    media_type=ProductFile.MediaType.IMAGE,
                    caption=f'{variation.display_name}',
                    sort_order=0,
                    is_primary=True,
                )
                filename = f'{variation.sku}.jpg'
                product_file.file.save(filename, ContentFile(image_bytes), save=True)

            media_count = ProductFile.objects.filter(product=product, variation__isnull=False).count()
            if media_count:
                self.stdout.write(f'  Variation media: {product.name} ({media_count} images)')

    def _load_image(self, filename):
        local_path = FIXTURES_DIR / filename
        if local_path.exists():
            return local_path.read_bytes()

        self.stdout.write(self.style.WARNING(f'    Local image not found: {local_path}'))
        return None
