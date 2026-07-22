from django.contrib import admin
from django.utils.html import format_html

from .group_buy import GroupBuy, GroupBuyEntry
from .address import Address
from .cart import Cart, CartItem
from .fulfillment import Fulfillment
from .order import Order, OrderItem
from .payment import Payment
from .refund import Refund
from .notification import NotificationLog
from .import_batch import ImportBatch
from .supplier import Supplier
from .models import Category, Product
from .product_attribute import ProductAttribute
from .product_file import ProductFile
from .product_variation import ProductOption, ProductOptionValue, ProductVariation


class ProductFileInline(admin.TabularInline):
    model = ProductFile
    extra = 1
    fields = ('file', 'variation', 'media_type', 'caption', 'sort_order', 'is_primary')
    autocomplete_fields = ('variation',)

    def get_queryset(self, request):
        return super().get_queryset(request).filter(variation__isnull=True)


class ProductAttributeInline(admin.TabularInline):
    model = ProductAttribute
    extra = 1
    fields = ('variation', 'title', 'description', 'sort_order')
    autocomplete_fields = ('variation',)

    def get_queryset(self, request):
        return super().get_queryset(request).filter(variation__isnull=True)


class ProductOptionInline(admin.TabularInline):
    model = ProductOption
    extra = 1
    fields = ('name', 'sort_order')


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('indented_name', 'parent', 'slug', 'is_active', 'created_at')
    list_filter = ('is_active', 'parent')
    search_fields = ('name', 'slug', 'description')
    autocomplete_fields = ('parent',)
    readonly_fields = ('created_at', 'updated_at')
    ordering = ('parent__name', 'name')

    @admin.display(description='Name')
    def indented_name(self, obj):
        return obj.get_indented_name()


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('name', 'contact_name', 'country', 'phone', 'wechat_id', 'is_active', 'created_at')
    list_filter = ('is_active', 'country')
    search_fields = ('name', 'contact_name', 'email', 'phone', 'wechat_id')


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'supplier', 'slug', 'is_active', 'file_count', 'variation_count', 'created_at')
    list_filter = ('is_active', 'category', 'supplier')
    search_fields = ('name', 'slug', 'description')
    prepopulated_fields = {'slug': ('name',)}
    autocomplete_fields = ('category', 'supplier')
    readonly_fields = ('created_at', 'updated_at')
    inlines = (ProductFileInline, ProductOptionInline, ProductAttributeInline)

    @admin.display(description='Files')
    def file_count(self, obj):
        return obj.files.count()

    @admin.display(description='Variations')
    def variation_count(self, obj):
        return obj.variations.count()


@admin.register(ProductFile)
class ProductFileAdmin(admin.ModelAdmin):
    list_display = ('product', 'variation', 'media_type', 'preview', 'is_primary', 'sort_order', 'created_at')
    list_filter = ('media_type', 'is_primary')
    search_fields = ('product__name', 'variation__sku', 'caption')
    autocomplete_fields = ('product', 'variation')

    @admin.display(description='Preview')
    def preview(self, obj):
        if not obj.file:
            return '—'
        if obj.is_image:
            return format_html(
                '<img src="{}" alt="" style="max-height:48px;border-radius:4px;">',
                obj.file.url,
            )
        return obj.file.name


class ProductOptionValueInline(admin.TabularInline):
    model = ProductOptionValue
    extra = 1
    fields = ('value', 'sort_order')


@admin.register(ProductOption)
class ProductOptionAdmin(admin.ModelAdmin):
    list_display = ('name', 'product', 'value_count', 'sort_order', 'created_at')
    search_fields = ('name', 'product__name')
    autocomplete_fields = ('product',)
    inlines = (ProductOptionValueInline,)

    @admin.display(description='Values')
    def value_count(self, obj):
        return obj.values.count()


@admin.register(ProductOptionValue)
class ProductOptionValueAdmin(admin.ModelAdmin):
    list_display = ('value', 'option', 'product_name', 'sort_order', 'created_at')
    search_fields = ('value', 'option__name', 'option__product__name')
    autocomplete_fields = ('option',)

    @admin.display(description='Product')
    def product_name(self, obj):
        return obj.option.product.name


@admin.register(ProductVariation)
class ProductVariationAdmin(admin.ModelAdmin):
    list_display = ('sku', 'product', 'display_name', 'price', 'file_count', 'is_active', 'created_at')
    list_filter = ('is_active', 'product')
    search_fields = ('sku', 'product__name')
    autocomplete_fields = ('product',)
    filter_horizontal = ('option_values',)
    inlines = ()

    @admin.display(description='Combination')
    def display_name(self, obj):
        return obj.display_name

    @admin.display(description='Images')
    def file_count(self, obj):
        return obj.files.count()


class ProductVariationFileInline(admin.TabularInline):
    model = ProductFile
    fk_name = 'variation'
    extra = 1
    fields = ('file', 'media_type', 'caption', 'sort_order', 'is_primary')
    verbose_name = 'Variation media'
    verbose_name_plural = 'Variation media'


ProductVariationAdmin.inlines = (ProductVariationFileInline,)


@admin.register(ProductAttribute)
class ProductAttributeAdmin(admin.ModelAdmin):
    list_display = ('title', 'product', 'variation', 'sort_order', 'created_at')
    list_filter = ('product__category',)
    search_fields = ('title', 'description', 'product__name', 'variation__sku')
    autocomplete_fields = ('product', 'variation')


class GroupBuyEntryInline(admin.TabularInline):
    model = GroupBuyEntry
    extra = 0
    autocomplete_fields = ('user', 'variation')
    readonly_fields = ('created_at',)


class ImportBatchInline(admin.StackedInline):
    model = ImportBatch
    extra = 0
    max_num = 1
    fields = (
        'supplier', 'status', 'supplier_reference', 'estimated_arrival',
        'arrived_at', 'notes', 'created_at', 'updated_at',
    )
    autocomplete_fields = ('supplier',)
    readonly_fields = ('arrived_at', 'created_at', 'updated_at')


@admin.register(ImportBatch)
class ImportBatchAdmin(admin.ModelAdmin):
    list_display = (
        'pk', 'group_buy', 'product_name', 'supplier', 'status',
        'supplier_reference', 'estimated_arrival', 'arrived_at', 'created_at',
    )
    list_filter = ('status', 'supplier', 'group_buy__product__category')
    search_fields = (
        'supplier_reference', 'supplier__name', 'group_buy__product__name', 'notes',
    )
    autocomplete_fields = ('group_buy', 'supplier')
    readonly_fields = ('arrived_at', 'created_at', 'updated_at')
    actions = ('mark_in_transit', 'mark_customs', 'mark_received')

    @admin.display(description='Product')
    def product_name(self, obj):
        return obj.group_buy.product.name

    @admin.action(description='Mark selected as in transit')
    def mark_in_transit(self, request, queryset):
        from core.import_services import advance_import_batch

        for batch in queryset.select_related('group_buy'):
            advance_import_batch(batch, ImportBatch.Status.IN_TRANSIT)
        self.message_user(request, f'Updated {queryset.count()} batch(es) to in transit.')

    @admin.action(description='Mark selected as in customs')
    def mark_customs(self, request, queryset):
        from core.import_services import advance_import_batch

        for batch in queryset.select_related('group_buy'):
            advance_import_batch(batch, ImportBatch.Status.CUSTOMS)
        self.message_user(request, f'Updated {queryset.count()} batch(es) to customs.')

    @admin.action(description='Mark selected as received')
    def mark_received(self, request, queryset):
        from core.import_services import advance_import_batch

        for batch in queryset.select_related('group_buy'):
            advance_import_batch(batch, ImportBatch.Status.RECEIVED)
        self.message_user(request, f'Updated {queryset.count()} batch(es) to received.')


@admin.register(GroupBuy)
class GroupBuyAdmin(admin.ModelAdmin):
    list_display = (
        'product', 'moq', 'pledged_units_display', 'unit_price',
        'status', 'import_batch_status', 'closes_at', 'created_at',
    )
    list_filter = ('status', 'product__category')
    search_fields = ('product__name',)
    autocomplete_fields = ('product',)
    readonly_fields = ('created_at', 'updated_at', 'pledged_units_display')
    inlines = (GroupBuyEntryInline, ImportBatchInline)
    actions = ('create_import_batches',)

    @admin.display(description='Pledged')
    def pledged_units_display(self, obj):
        return f'{obj.pledged_units} / {obj.moq}'

    @admin.display(description='Import')
    def import_batch_status(self, obj):
        try:
            return obj.import_batch.get_status_display()
        except ImportBatch.DoesNotExist:
            return '—'

    @admin.action(description='Create import batches for selected group buys')
    def create_import_batches(self, request, queryset):
        from core.import_services import create_import_batch

        created = 0
        skipped = 0
        for group_buy in queryset:
            if ImportBatch.objects.filter(group_buy=group_buy).exists():
                skipped += 1
                continue
            try:
                create_import_batch(group_buy)
                created += 1
            except Exception:
                skipped += 1
        self.message_user(request, f'Created {created} import batch(es). Skipped {skipped}.')


@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = ('recipient_name', 'user', 'county', 'area', 'phone', 'is_default', 'updated_at')
    list_filter = ('is_default', 'county')
    search_fields = ('recipient_name', 'user__phone', 'user__email', 'area', 'street_address')
    autocomplete_fields = ('user',)


@admin.register(Fulfillment)
class FulfillmentAdmin(admin.ModelAdmin):
    list_display = (
        'order', 'buyer_name', 'status', 'tracking_reference',
        'import_batch', 'shipped_at', 'delivered_at',
    )
    list_filter = ('status',)
    search_fields = ('order__user__phone', 'tracking_reference', 'order__pk')
    autocomplete_fields = ('order', 'import_batch')
    readonly_fields = ('shipped_at', 'delivered_at', 'created_at', 'updated_at')

    @admin.display(description='Buyer')
    def buyer_name(self, obj):
        return obj.order.user.get_full_name()


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    list_display = ('event', 'channel', 'recipient', 'status', 'user', 'created_at')
    list_filter = ('event', 'channel', 'status')
    search_fields = ('recipient', 'body', 'user__phone', 'user__email')
    readonly_fields = (
        'user', 'event', 'channel', 'recipient', 'subject', 'body',
        'status', 'error_message', 'created_at',
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Refund)
class RefundAdmin(admin.ModelAdmin):
    list_display = (
        'reference', 'order', 'amount', 'refund_type', 'status',
        'created_by', 'completed_at', 'created_at',
    )
    list_filter = ('status', 'refund_type')
    search_fields = ('reference', 'order__pk', 'reason', 'order__user__phone')
    autocomplete_fields = ('payment', 'order', 'created_by')
    readonly_fields = ('reference', 'completed_at', 'created_at', 'updated_at')


@admin.register(GroupBuyEntry)
class GroupBuyEntryAdmin(admin.ModelAdmin):
    list_display = ('group_buy', 'user', 'variation', 'quantity', 'created_at')
    list_filter = ('group_buy__status',)
    search_fields = ('group_buy__product__name', 'user__phone', 'user__email')
    autocomplete_fields = ('group_buy', 'user', 'variation')


class CartItemInline(admin.TabularInline):
    model = CartItem
    extra = 0
    autocomplete_fields = ('group_buy', 'variation')


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ('user', 'item_count_display', 'updated_at')
    search_fields = ('user__phone', 'user__email')
    autocomplete_fields = ('user',)
    inlines = (CartItemInline,)

    @admin.display(description='Items')
    def item_count_display(self, obj):
        return obj.item_count


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    autocomplete_fields = ('variation',)
    readonly_fields = ('line_total_display',)

    @admin.display(description='Line total')
    def line_total_display(self, obj):
        if obj.pk:
            return obj.line_total
        return '—'


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('pk', 'user', 'group_buy', 'status', 'total_amount', 'delivery_area_display', 'created_at')
    list_filter = ('status', 'group_buy__product__category')
    search_fields = ('user__phone', 'user__email', 'group_buy__product__name', 'delivery_recipient_name')
    autocomplete_fields = ('group_buy', 'user', 'delivery_address')
    inlines = (OrderItemInline,)
    readonly_fields = (
        'delivery_recipient_name', 'delivery_phone', 'delivery_county',
        'delivery_area', 'delivery_street', 'delivery_notes',
    )

    @admin.display(description='Delivery area')
    def delivery_area_display(self, obj):
        return obj.delivery_area or '—'


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        'reference', 'user', 'group_buy', 'amount', 'amount_kes',
        'status', 'provider', 'mpesa_receipt_number', 'completed_at',
    )
    list_filter = ('status', 'provider')
    search_fields = (
        'reference', 'mpesa_receipt_number', 'checkout_request_id',
        'user__phone', 'user__email', 'group_buy__product__name',
    )
    autocomplete_fields = ('group_buy', 'user', 'order')
    readonly_fields = (
        'reference', 'merchant_request_id', 'checkout_request_id',
        'callback_payload', 'created_at', 'completed_at',
    )
