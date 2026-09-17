"""Remove all products and related commerce data (orders, group buys, carts, etc.)."""

import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from core.cart import CartItem
from core.complaint import Complaint
from core.fulfillment import Fulfillment
from core.group_buy import GroupBuy, GroupBuyEntry
from core.import_batch import ImportBatch
from core.import_cost import ImportBatchAdditionalCost
from core.models import Product
from core.order import Order, OrderItem
from core.payment import Payment
from core.product_import import ProductImportDraft, ProductImportMedia
from core.refund import Refund
from core.user_preference import UserProductView
from core.wishlist import WishlistItem


class Command(BaseCommand):
    help = (
        'Delete every product and dependent records (group buys, orders, payments, '
        'import batches, wishlists, etc.). Categories, suppliers, and users are kept.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--yes',
            action='store_true',
            help='Confirm destructive delete (required).',
        )
        parser.add_argument(
            '--purge-media',
            action='store_true',
            default=True,
            help='Remove uploaded files under media/products/ (default: on).',
        )
        parser.add_argument(
            '--keep-import-drafts',
            action='store_true',
            help='Keep AI import drafts; only clear their product link.',
        )

    def handle(self, *args, **options):
        if not options['yes']:
            self.stderr.write(self.style.ERROR('Aborted. Re-run with --yes to confirm.'))
            return

        product_count = Product.objects.count()
        if product_count == 0:
            self.stdout.write('No products in the database.')
            return

        with transaction.atomic():
            deleted = {}
            deleted['refunds'] = Refund.objects.count()
            Refund.objects.all().delete()

            deleted['fulfillments'] = Fulfillment.objects.count()
            Fulfillment.objects.all().delete()

            deleted['order_items'] = OrderItem.objects.count()
            OrderItem.objects.all().delete()

            deleted['complaints'] = Complaint.objects.count()
            Complaint.objects.all().delete()

            deleted['payments'] = Payment.objects.count()
            Payment.objects.all().delete()

            deleted['orders'] = Order.objects.count()
            Order.objects.all().delete()

            deleted['cart_items'] = CartItem.objects.count()
            CartItem.objects.all().delete()

            deleted['group_buy_entries'] = GroupBuyEntry.objects.count()
            GroupBuyEntry.objects.all().delete()

            deleted['import_cost_lines'] = ImportBatchAdditionalCost.objects.count()
            ImportBatchAdditionalCost.objects.all().delete()

            deleted['import_batches'] = ImportBatch.objects.count()
            ImportBatch.objects.all().delete()

            deleted['group_buys'] = GroupBuy.objects.count()
            GroupBuy.objects.all().delete()

            if options['keep_import_drafts']:
                updated = ProductImportDraft.objects.filter(product__isnull=False).update(product=None)
                deleted['import_drafts_unlinked'] = updated
            else:
                deleted['import_draft_media'] = ProductImportMedia.objects.count()
                ProductImportMedia.objects.all().delete()
                deleted['import_drafts'] = ProductImportDraft.objects.count()
                ProductImportDraft.objects.all().delete()

            deleted['wishlist_items'] = WishlistItem.objects.count()
            WishlistItem.objects.all().delete()

            deleted['product_views'] = UserProductView.objects.count()
            UserProductView.objects.all().delete()

            deleted['products'] = product_count
            Product.objects.all().delete()

        for label, count in deleted.items():
            self.stdout.write(f'  {label}: {count}')

        if options['purge_media']:
            media_products = Path(settings.MEDIA_ROOT) / 'products'
            if media_products.exists():
                shutil.rmtree(media_products)
                media_products.mkdir(parents=True, exist_ok=True)
                self.stdout.write(self.style.WARNING(f'Removed files under {media_products}'))

        self.stdout.write(self.style.SUCCESS(f'Deleted {product_count} product(s). Catalog is empty.'))
