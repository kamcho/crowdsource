from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.currency import convert_usd_to_kes, format_money, format_money_range
from core.category_utils import build_category_nav_tree
from core.models import Category, Product
from core.product_attribute import ProductAttribute
from core.shipping import ShippingRate
from core.shipping_services import (
    calculate_shipping_estimate,
    get_estimated_arrival,
    extract_package_specs,
    get_product_package_specs,
)

from core.payment import Payment
from core.textsms import TextSmsAPIError, normalize_kenyan_mobile, send_sms
from core.mpesa import normalize_mpesa_phone, parse_stk_callback
from core.payment_services import usd_to_kes


class TextSmsNormalizeTests(TestCase):
    def test_normalizes_local_format(self):
        self.assertEqual(normalize_kenyan_mobile('0712345678'), '254712345678')

    def test_normalizes_international_format(self):
        self.assertEqual(normalize_kenyan_mobile('+254712345678'), '254712345678')

    def test_rejects_invalid_number(self):
        with self.assertRaises(ValueError):
            normalize_kenyan_mobile('123')


@override_settings(
    TEXTSMS_API_KEY='test-key',
    TEXTSMS_PARTNER_ID='99',
    TEXTSMS_SHORTCODE='CrowdSource',
)
class TextSmsSendTests(TestCase):
    @patch('core.textsms.requests.post')
    def test_send_sms_success(self, mock_post):
        mock_post.return_value.json.return_value = {
            'responses': [{
                'respose-code': '200',
                'response-description': 'Success',
                'messageid': 'abc123',
                'mobile': '254712345678',
            }],
        }
        mock_post.return_value.raise_for_status.return_value = None

        result = send_sms(mobile='0712345678', message='Hello')

        self.assertEqual(result['message_id'], 'abc123')
        payload = mock_post.call_args.kwargs['json']
        self.assertEqual(payload['mobile'], '254712345678')
        self.assertEqual(payload['apikey'], 'test-key')
        self.assertEqual(payload['partnerID'], '99')
        self.assertEqual(payload['shortcode'], 'CrowdSource')

    @patch('core.textsms.requests.post')
    def test_send_sms_api_error(self, mock_post):
        mock_post.return_value.json.return_value = {
            'responses': [{
                'respose-code': '400',
                'response-description': 'Insufficient credits',
            }],
        }
        mock_post.return_value.raise_for_status.return_value = None

        with self.assertRaises(TextSmsAPIError):
            send_sms(mobile='0712345678', message='Hello')


class MpesaTests(TestCase):
    def test_normalize_mpesa_phone(self):
        self.assertEqual(normalize_mpesa_phone('0712345678'), '254712345678')

    def test_parse_stk_callback_success(self):
        payload = {
            'Body': {
                'stkCallback': {
                    'MerchantRequestID': 'm1',
                    'CheckoutRequestID': 'c1',
                    'ResultCode': 0,
                    'ResultDesc': 'Success',
                    'CallbackMetadata': {
                        'Item': [
                            {'Name': 'Amount', 'Value': 1300},
                            {'Name': 'MpesaReceiptNumber', 'Value': 'ABC123'},
                            {'Name': 'PhoneNumber', 'Value': 254712345678},
                        ],
                    },
                },
            },
        }
        parsed = parse_stk_callback(payload)
        self.assertEqual(parsed['mpesa_receipt_number'], 'ABC123')
        self.assertEqual(parsed['result_code'], 0)

    @override_settings(USD_TO_KES_RATE='130')
    def test_usd_to_kes(self):
        self.assertEqual(usd_to_kes('10'), 1300)


class ClearPledgesTests(TestCase):
    def test_clear_user_pledges_for_group_buy(self):
        from core.commerce_services import clear_user_pledges_for_group_buy
        from core.group_buy import GroupBuy, GroupBuyEntry
        from core.models import Category, Product
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user = User.objects.create_user(phone='+254712345678', password='pass')
        category = Category.objects.create(name='Test', slug='test-cat')
        product = Product.objects.create(
            name='Test Product', slug='test-product', category=category,
            is_active=True,
        )
        group_buy = GroupBuy.objects.create(
            product=product, moq=10, unit_price='2.00',
            closes_at=timezone.now() + timedelta(days=30),
        )
        GroupBuyEntry.objects.create(group_buy=group_buy, user=user, quantity=2)
        self.assertEqual(group_buy.entries.filter(user=user).count(), 1)
        clear_user_pledges_for_group_buy(user, group_buy)
        self.assertEqual(group_buy.entries.filter(user=user).count(), 0)


class RepeatPledgeCheckoutTests(TestCase):
    def test_can_confirm_after_paid_order_when_new_pledges_exist(self):
        from core.commerce_services import can_confirm_pledge_order
        from core.fulfillment_services import create_fulfillment_for_order
        from core.group_buy import GroupBuy, GroupBuyEntry
        from core.models import Category, Product
        from core.order import Order
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user = User.objects.create_user(phone='+254712345678', password='pass')
        category = Category.objects.create(name='Test', slug='test-cat-repeat')
        product = Product.objects.create(
            name='Repeat Product', slug='repeat-product', category=category,
            is_active=True,
        )
        group_buy = GroupBuy.objects.create(
            product=product, moq=10, unit_price='2.00',
            closes_at=timezone.now() + timedelta(days=30),
        )
        paid_order = Order.objects.create(
            group_buy=group_buy,
            user=user,
            status=Order.Status.PAID,
            total_amount='4.00',
        )
        create_fulfillment_for_order(paid_order)
        GroupBuyEntry.objects.create(group_buy=group_buy, user=user, quantity=3)

        self.assertTrue(can_confirm_pledge_order(user, group_buy))


class FailedMpesaRetryTests(TestCase):
    def test_prepare_checkout_after_failed_payment_creates_new_payment(self):
        from core.address import Address
        from core.commerce_services import get_user_pledge_entries
        from core.group_buy import GroupBuy, GroupBuyEntry
        from core.models import Category, Product
        from core.order import Order
        from core.payment_services import fail_payment, prepare_checkout_order
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user = User.objects.create_user(phone='+254712345678', password='pass')
        category = Category.objects.create(name='Test', slug='test-cat-mpesa-retry')
        product = Product.objects.create(
            name='Retry Product', slug='retry-product', category=category,
            is_active=True,
        )
        group_buy = GroupBuy.objects.create(
            product=product, moq=10, unit_price=Decimal('2.00'),
            closes_at=timezone.now() + timedelta(days=30),
        )
        GroupBuyEntry.objects.create(group_buy=group_buy, user=user, quantity=2)
        address = Address.objects.create(
            user=user,
            recipient_name='Buyer',
            phone='+254712345678',
            county='Nairobi',
            area='Westlands',
            street_address='Example Road',
        )
        order = Order.objects.create(
            group_buy=group_buy,
            user=user,
            status=Order.Status.PENDING_PAYMENT,
            total_amount='4.00',
        )
        failed_payment = Payment.objects.create(
            group_buy=group_buy,
            user=user,
            order=order,
            amount='4.00',
            amount_kes=520,
            status=Payment.Status.PENDING,
            provider='mpesa',
        )
        fail_payment(failed_payment, result_code=1037, result_description='Timed out.')
        failed_payment.refresh_from_db()
        self.assertIsNone(failed_payment.order_id)

        order, payment = prepare_checkout_order(user, group_buy, address)
        self.assertNotEqual(payment.pk, failed_payment.pk)
        self.assertEqual(payment.order_id, order.pk)
        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertEqual(len(get_user_pledge_entries(user, group_buy)), 1)


class EnsureMpesaStkPushTests(TestCase):
    @patch('core.payment_services.initiate_mpesa_stk_push')
    def test_skips_when_stk_already_sent(self, mock_initiate):
        from core.payment_services import ensure_mpesa_stk_push

        payment = Payment(
            status=Payment.Status.PENDING,
            checkout_request_id='existing-checkout-id',
        )
        result = ensure_mpesa_stk_push(payment, '0712345678')
        mock_initiate.assert_not_called()
        self.assertEqual(result, payment)

    @patch('core.payment_services.initiate_mpesa_stk_push')
    def test_initiates_when_not_sent(self, mock_initiate):
        from core.payment_services import ensure_mpesa_stk_push

        payment = Payment(status=Payment.Status.PENDING, checkout_request_id='')
        mock_initiate.return_value = payment
        ensure_mpesa_stk_push(payment, '0712345678')
        mock_initiate.assert_called_once_with(payment, '0712345678')


class CategoryNavTreeTests(TestCase):
    def test_build_category_nav_tree(self):
        root = Category.objects.create(name='Electronics')
        mid = Category.objects.create(name='Audio', parent=root)
        Category.objects.create(name='Earphones', parent=mid)

        tree = build_category_nav_tree(Category.objects.filter(is_active=True))

        self.assertEqual(len(tree), 1)
        self.assertEqual(tree[0]['name'], 'Electronics')
        self.assertEqual(len(tree[0]['children']), 1)
        self.assertEqual(tree[0]['children'][0]['name'], 'Audio')
        self.assertEqual(tree[0]['children'][0]['children'][0]['name'], 'Earphones')


class CurrencyFormattingTests(TestCase):
    @override_settings(USD_TO_KES_RATE='135')
    def test_format_money_usd(self):
        self.assertEqual(format_money('12.50', 'USD'), '$12.50 ≈ KES 1,688')

    @override_settings(USD_TO_KES_RATE='135')
    def test_format_money_kes(self):
        self.assertEqual(format_money('10.00', 'KES'), 'KES 1,350')

    @override_settings(USD_TO_KES_RATE='135')
    def test_convert_usd_to_kes(self):
        self.assertEqual(convert_usd_to_kes('2.00'), 270)

    @override_settings(USD_TO_KES_RATE='135')
    def test_format_money_range(self):
        self.assertEqual(
            format_money_range('2.00', '3.50', 'KES'),
            'KES 270 – KES 473',
        )

    @override_settings(USD_TO_KES_RATE='135')
    def test_set_currency_view(self):
        client = Client()
        response = client.get('/currency/?currency=KES&next=/products/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(client.session.get('currency'), 'KES')


class ShippingCalculatorTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name='Bags')
        self.product = Product.objects.create(
            category=self.category,
            name='Canvas Tote',
            slug='canvas-tote',
        )
        ProductAttribute.objects.create(
            product=self.product,
            title='Single package size',
            description='40X35X2 cm',
            section=ProductAttribute.Section.PACKAGING,
        )
        ProductAttribute.objects.create(
            product=self.product,
            title='Single gross weight',
            description='0.180 kg',
            section=ProductAttribute.Section.PACKAGING,
        )

    def test_extract_package_specs_from_attributes(self):
        specs = get_product_package_specs(self.product)
        self.assertEqual(specs.weight_kg, Decimal('0.180'))
        self.assertEqual(specs.length_cm, Decimal('40'))
        self.assertEqual(specs.width_cm, Decimal('35'))
        self.assertEqual(specs.height_cm, Decimal('2'))
        self.assertEqual(specs.cbm, Decimal('0.002800'))

    def test_air_shipping_estimate_for_normal_goods(self):
        result = calculate_shipping_estimate(
            self.product,
            mode=ShippingRate.Mode.AIR,
            quantity=100,
        )
        self.assertTrue(result['ok'])
        self.assertEqual(Decimal(result['total_usd']), Decimal('225.00'))
        self.assertEqual(result['goods_class'], ShippingRate.GoodsClass.NORMAL)

    def test_air_shipping_estimate_for_special_goods(self):
        self.product.is_special_class = True
        self.product.save(update_fields=['is_special_class'])
        result = calculate_shipping_estimate(
            self.product,
            mode=ShippingRate.Mode.AIR,
            quantity=100,
        )
        self.assertTrue(result['ok'])
        self.assertEqual(Decimal(result['total_usd']), Decimal('234.00'))

    def test_sea_shipping_estimate_uses_cbm(self):
        result = calculate_shipping_estimate(
            self.product,
            mode=ShippingRate.Mode.SEA,
            quantity=100,
        )
        self.assertTrue(result['ok'])
        self.assertEqual(result['total_kes'], 20440)
        self.assertEqual(result['rate']['currency'], 'KES')

    def test_air_estimate_requires_weight_attribute(self):
        product = Product.objects.create(
            category=self.category,
            name='No Weight Product',
            slug='no-weight-product',
        )
        ProductAttribute.objects.create(
            product=product,
            title='Single package size',
            description='40X35X2 cm',
            section=ProductAttribute.Section.PACKAGING,
        )
        result = calculate_shipping_estimate(product, mode=ShippingRate.Mode.AIR, quantity=1)
        self.assertFalse(result['ok'])
        self.assertIn('weight attribute', result['error'])

    def test_build_shipping_calculator_context_flags_missing_specs(self):
        from core.shipping_services import build_shipping_calculator_context

        product = Product.objects.create(
            category=self.category,
            name='Missing Specs Product',
            slug='missing-specs-product',
        )
        context = build_shipping_calculator_context(product)
        self.assertTrue(context['shipping_needs_weight'])
        self.assertTrue(context['shipping_needs_size'])

        full_context = build_shipping_calculator_context(self.product)
        self.assertFalse(full_context['shipping_needs_weight'])
        self.assertFalse(full_context['shipping_needs_size'])

    def test_estimated_arrival_windows(self):
        self.assertEqual(get_estimated_arrival(ShippingRate.Mode.AIR, False), '3–5 days')
        self.assertEqual(get_estimated_arrival(ShippingRate.Mode.AIR, True), '10–14 days')
        self.assertEqual(get_estimated_arrival(ShippingRate.Mode.SEA, False), '30–35 days')
        self.assertEqual(get_estimated_arrival(ShippingRate.Mode.SEA, True), '30–35 days')

    def test_successful_estimate_includes_arrival(self):
        result = calculate_shipping_estimate(
            self.product,
            mode=ShippingRate.Mode.AIR,
            quantity=100,
        )
        self.assertTrue(result['ok'])
        self.assertEqual(result['estimated_arrival'], '3–5 days')

    def test_extract_package_specs_parses_grams(self):
        attributes = [{'title': 'Net weight', 'description': '500 g'}]
        specs = extract_package_specs(attributes)
        self.assertEqual(specs.weight_kg, Decimal('0.5'))


class WishlistTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        self.user = User.objects.create_user(phone='+254711223344', password='pass')
        self.category = Category.objects.create(name='Gadgets', slug='gadgets-wishlist')
        self.product = Product.objects.create(
            name='Wishlist Product',
            slug='wishlist-product',
            category=self.category,
            is_active=True,
        )

    def test_toggle_wishlist_adds_and_removes(self):
        from core.wishlist_services import is_wishlisted, toggle_wishlist

        self.assertFalse(is_wishlisted(self.user, self.product))
        self.assertTrue(toggle_wishlist(self.user, self.product))
        self.assertTrue(is_wishlisted(self.user, self.product))
        self.assertFalse(toggle_wishlist(self.user, self.product))
        self.assertFalse(is_wishlisted(self.user, self.product))

    def test_wishlist_toggle_view_requires_login(self):
        response = self.client.post(
            reverse('wishlist_toggle'),
            {'product_id': self.product.pk},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn('/users/signin/', response.url)

    def test_wishlist_toggle_and_list(self):
        self.client.login(phone='+254711223344', password='pass')
        response = self.client.post(
            reverse('wishlist_toggle'),
            {'product_id': self.product.pk, 'next': reverse('wishlist_list')},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.product.name)
        self.assertContains(response, 'saved to your wishlist')
        self.assertContains(response, 'alert-success')

        response = self.client.post(
            reverse('wishlist_toggle'),
            {'product_id': self.product.pk, 'next': reverse('wishlist_list')},
            follow=True,
        )
        self.assertContains(response, 'removed from your wishlist')
        self.assertContains(response, 'alert-info')


class ProductDetailGroupBuyTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.category = Category.objects.create(name='Bags', slug='bags-detail-gb')
        self.product = Product.objects.create(
            name='Auto Group Buy Bag',
            slug='auto-group-buy-bag',
            category=self.category,
            is_active=True,
        )

    def test_product_detail_creates_group_buy_when_missing(self):
        from core.group_buy import GroupBuy

        self.assertFalse(self.product.group_buys.exists())
        response = self.client.get(reverse('product_detail', kwargs={'slug': self.product.slug}))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            GroupBuy.objects.filter(
                product=self.product,
                status=GroupBuy.Status.OPEN,
            ).exists()
        )
        self.assertContains(response, 'Sign in to join')
        self.assertContains(response, 'Group buy open')

    def test_product_detail_reuses_existing_open_group_buy(self):
        from core.group_buy import GroupBuy

        existing = GroupBuy.objects.create(
            product=self.product,
            moq=50,
            unit_price=Decimal('4.50'),
            closes_at=timezone.now() + timedelta(days=14),
            status=GroupBuy.Status.OPEN,
        )
        response = self.client.get(reverse('product_detail', kwargs={'slug': self.product.slug}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.product.group_buys.count(), 1)
        self.assertEqual(self.product.group_buys.first().pk, existing.pk)


class ComplaintTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        from core.group_buy import GroupBuy
        from core.models import Category, Product
        from core.order import Order

        User = get_user_model()
        self.user = User.objects.create_user(phone='+254711998877', password='pass')
        self.staff = User.objects.create_user(
            phone='+254711998878',
            password='pass',
            role='staff',
        )
        self.category = Category.objects.create(name='Home', slug='home-complaints')
        self.product = Product.objects.create(
            name='Complaint Product',
            slug='complaint-product',
            category=self.category,
            is_active=True,
        )
        self.group_buy = GroupBuy.objects.create(
            product=self.product,
            moq=10,
            unit_price=Decimal('12.00'),
            closes_at=timezone.now() + timedelta(days=7),
        )
        self.order = Order.objects.create(
            group_buy=self.group_buy,
            user=self.user,
            status=Order.Status.PAID,
            total_amount=Decimal('24.00'),
        )

    def test_create_complaint_linked_to_order(self):
        from core.complaint import Complaint
        from core.complaint_services import create_complaint

        complaint = create_complaint(
            user=self.user,
            order=self.order,
            category=Complaint.Category.DELIVERY,
            subject='Late delivery',
            description='My order has not arrived yet.',
        )
        self.assertTrue(complaint.reference.startswith('CP-'))
        self.assertEqual(complaint.order_id, self.order.pk)
        self.assertEqual(complaint.status, Complaint.Status.OPEN)

    def test_complaint_create_view(self):
        self.client.login(phone='+254711998877', password='pass')
        response = self.client.post(
            reverse('complaint_create'),
            {
                'order': self.order.pk,
                'category': 'delivery',
                'subject': 'Missing package',
                'description': 'The courier never called me.',
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Missing package')
        self.assertContains(response, 'CP-')

    def test_complaint_list_requires_login(self):
        response = self.client.get(reverse('complaint_list'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/users/signin/', response.url)

    def test_staff_reply_updates_status(self):
        from core.complaint import Complaint
        from core.complaint_services import add_complaint_message, create_complaint, update_complaint_status

        complaint = create_complaint(
            user=self.user,
            order=self.order,
            category=Complaint.Category.OTHER,
            subject='Help needed',
            description='Need assistance.',
        )
        add_complaint_message(
            complaint=complaint,
            author=self.staff,
            body='We are looking into this.',
            is_staff_reply=True,
        )
        update_complaint_status(
            complaint=complaint,
            status=Complaint.Status.RESOLVED,
            staff_notes='Resolved by phone.',
        )
        complaint.refresh_from_db()
        self.assertEqual(complaint.status, Complaint.Status.RESOLVED)
        self.assertEqual(complaint.messages.count(), 1)
        self.assertTrue(complaint.resolved_at)


class ProductImportTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        self.admin = User.objects.create_user(
            phone='+254700111222',
            password='pass',
            role='admin',
        )
        self.category = Category.objects.create(name='Bags', slug='bags-import')
        self.paste = """
        Canvas Tote Bag — Eco friendly shopping bag
        Material: 12oz cotton canvas. Size: 35x40x10cm. Weight: 220g
        MOQ: 500 pcs. Lead time: 15 days
        Variations:
        SKU CTB-BLK M — Black / Medium — $2.80
        SKU CTB-WHT M — White / Medium — $2.80
        SKU CTB-BLK L — Black / Large — $3.10
        """

    def test_normalize_parsed_draft(self):
        from core.openai_product_import import normalize_parsed_draft

        parsed = {
            'name': 'Canvas Tote Bag',
            'description': 'Eco friendly tote.',
            'category_slug': 'bags-import',
            'supplier': {
                'name': 'Guangzhou Bag Factory',
                'contact_name': 'Amy Chen',
                'email': 'amy@example.com',
                'phone': '+86 138 0000 0000',
                'wechat_id': 'amy_bags',
                'alibaba_url': 'https://gzbag.en.alibaba.com',
                'country': 'China',
                'notes': 'Reliable OEM partner',
            },
            'attributes': [
                {'title': 'Material', 'description': '12oz cotton', 'section': 'key'},
            ],
            'options': [
                {'name': 'Color', 'values': [{'value': 'Black'}, {'value': 'White'}]},
                {'name': 'Size', 'values': [{'value': 'M'}, {'value': 'L'}]},
            ],
            'variations': [
                {
                    'sku': 'CTB-BLK-M',
                    'price': '2.80',
                    'option_selections': {'Color': 'Black', 'Size': 'M'},
                },
            ],
        }
        draft = normalize_parsed_draft(
            parsed,
            categories=[{'id': self.category.pk, 'name': 'Bags', 'slug': 'bags-import'}],
            suppliers=[],
        )
        self.assertEqual(draft['name'], 'Canvas Tote Bag')
        self.assertEqual(draft['category_id'], self.category.pk)
        self.assertEqual(len(draft['attributes']), 1)
        self.assertEqual(len(draft['variations']), 1)
        self.assertTrue(draft['show_supplier_step'])
        self.assertEqual(draft['supplier']['name'], 'Guangzhou Bag Factory')
        self.assertEqual(draft['supplier']['wechat_id'], 'amy_bags')

    def test_normalize_parsed_draft_shows_category_step_for_missing_path(self):
        from core.openai_product_import import normalize_parsed_draft

        parsed = {
            'name': 'Canvas Tote Bag',
            'description': 'Eco friendly tote.',
            'category_slug': '',
            'category_path': ['Home & Garden', 'Kitchen', 'Storage Boxes'],
            'supplier': {},
            'attributes': [],
            'options': [],
            'variations': [],
        }
        draft = normalize_parsed_draft(
            parsed,
            categories=[{'id': self.category.pk, 'name': 'Bags', 'slug': 'bags-import'}],
            suppliers=[],
        )
        self.assertTrue(draft['show_category_step'])
        self.assertIsNone(draft['category_id'])
        self.assertEqual(len(draft['category_proposal']['segments']), 3)

    def test_normalize_parsed_draft_resolves_existing_category_path(self):
        from core.openai_product_import import normalize_parsed_draft
        from core.product_import_services import get_category_choices

        root = Category.objects.create(name='Electronics', slug='electronics-import')
        leaf = Category.objects.create(name='Earbuds', parent=root, slug='electronics-import-earbuds')
        parsed = {
            'name': 'Wireless Earbuds',
            'description': 'Bluetooth earbuds.',
            'category_slug': '',
            'category_path': ['Electronics', 'Earbuds'],
            'supplier': {},
            'attributes': [],
            'options': [],
            'variations': [],
        }
        draft = normalize_parsed_draft(
            parsed,
            categories=get_category_choices(),
            suppliers=[],
        )
        self.assertFalse(draft['show_category_step'])
        self.assertEqual(draft['category_id'], leaf.pk)

    def test_save_categories_from_import_creates_chain(self):
        from core.product_import import ProductImportDraft
        from core.product_import_services import save_categories_from_import

        draft = ProductImportDraft.objects.create(
            created_by=self.admin,
            draft_data={
                'name': 'Imported product',
                'show_category_step': True,
                'category_proposal': {
                    'segments': [
                        {'name': 'Home & Garden', 'existing_id': None},
                        {'name': 'Kitchen', 'existing_id': None},
                    ],
                },
            },
        )
        leaf = save_categories_from_import(
            draft,
            ['Home & Garden', 'Kitchen', 'Food Storage'],
        )
        self.assertEqual(leaf.name, 'Food Storage')
        self.assertEqual(leaf.parent.name, 'Kitchen')
        self.assertEqual(leaf.parent.parent.name, 'Home & Garden')
        draft.refresh_from_db()
        self.assertFalse(draft.draft_data['show_category_step'])
        self.assertEqual(draft.draft_data['category_id'], leaf.pk)

    def test_normalize_parsed_draft_matches_existing_supplier(self):
        from core.openai_product_import import normalize_parsed_draft
        from core.supplier import Supplier

        Supplier.objects.create(
            name='Guangzhou Bag Factory',
            alibaba_url='https://gzbag.en.alibaba.com',
        )
        parsed = {
            'name': 'Canvas Tote Bag',
            'description': 'Eco friendly tote.',
            'category_slug': 'bags-import',
            'supplier': {
                'name': 'Guangzhou Bag Factory',
                'alibaba_url': 'https://gzbag.en.alibaba.com/',
            },
            'attributes': [],
            'options': [],
            'variations': [],
        }
        draft = normalize_parsed_draft(
            parsed,
            categories=[{'id': self.category.pk, 'name': 'Bags', 'slug': 'bags-import'}],
            suppliers=list(
                Supplier.objects.values('id', 'name', 'alibaba_url')
            ),
        )
        self.assertFalse(draft['show_supplier_step'])
        self.assertIsNotNone(draft['supplier_id'])

    def test_save_supplier_from_import_creates_supplier(self):
        from core.product_import import ProductImportDraft
        from core.product_import_services import save_supplier_from_import
        from core.supplier import Supplier

        draft = ProductImportDraft.objects.create(
            created_by=self.admin,
            draft_data={
                'name': 'Imported Bag',
                'show_supplier_step': True,
                'supplier': {'name': 'New Factory Co'},
            },
        )
        supplier, created = save_supplier_from_import(
            draft,
            name='New Factory Co',
            contact_name='Li Wei',
            alibaba_url='https://newfactory.en.alibaba.com',
        )
        self.assertTrue(created)
        self.assertEqual(Supplier.objects.filter(name='New Factory Co').count(), 1)
        draft.refresh_from_db()
        self.assertEqual(draft.draft_data['supplier_id'], supplier.pk)
        self.assertFalse(draft.draft_data['show_supplier_step'])

    def test_sync_variations_from_options_generates_all_combinations(self):
        from core.product_import_services import sync_variations_from_options

        options = [
            {
                'name': 'Color',
                'values': [{'value': 'Black'}, {'value': 'White'}, {'value': 'Pink'}],
            },
            {
                'name': 'Size',
                'values': [{'value': 'M'}, {'value': 'L'}],
            },
        ]
        variations = sync_variations_from_options(
            options,
            [],
            sku_prefix='CTB',
            default_price='2.80',
        )
        self.assertEqual(len(variations), 6)
        self.assertEqual(
            variations[0]['option_selections'],
            {'Color': 'Black', 'Size': 'M'},
        )
        self.assertTrue(all(variation['sku'].startswith('CTB-') for variation in variations))
        self.assertTrue(all(variation['price'] == '2.80' for variation in variations))

    def test_sync_variations_from_options_preserves_existing_rows(self):
        from core.product_import_services import sync_variations_from_options

        options = [
            {'name': 'Color', 'values': [{'value': 'Black'}, {'value': 'White'}]},
        ]
        existing = [{
            'sku': 'CUSTOM-BLK',
            'price': '4.50',
            'is_active': True,
            'option_selections': {'Color': 'Black'},
        }]
        variations = sync_variations_from_options(options, existing, sku_prefix='BAG')
        self.assertEqual(len(variations), 2)
        black = next(v for v in variations if v['option_selections']['Color'] == 'Black')
        white = next(v for v in variations if v['option_selections']['Color'] == 'White')
        self.assertEqual(black['sku'], 'CUSTOM-BLK')
        self.assertEqual(black['price'], '4.50')
        self.assertEqual(white['sku'], 'BAG-WHI')

    def test_sku_prefix_from_product_name(self):
        from core.product_import_services import sku_prefix_from_product_name

        self.assertEqual(sku_prefix_from_product_name('Canvas Tote Bag'), 'CTB')
        self.assertEqual(sku_prefix_from_product_name(''), 'IMPORT')

    def test_publish_import_draft(self):
        from core.group_buy import GroupBuy
        from core.openai_product_import import normalize_parsed_draft
        from core.product_import import ProductImportDraft
        from core.product_import_services import publish_product_import_draft

        draft_data = normalize_parsed_draft(
            {
                'name': 'Imported Bag',
                'description': 'Test bag',
                'category_slug': 'bags-import',
                'attributes': [{'title': 'Material', 'description': 'Cotton', 'section': 'key'}],
                'options': [{'name': 'Color', 'values': [{'value': 'Black'}]}],
                'variations': [{
                    'sku': 'BAG-BLK',
                    'price': '3.00',
                    'option_selections': {'Color': 'Black'},
                }],
            },
            categories=[{'id': self.category.pk, 'name': 'Bags', 'slug': 'bags-import'}],
            suppliers=[],
        )
        draft = ProductImportDraft.objects.create(
            created_by=self.admin,
            draft_data=draft_data,
            status=ProductImportDraft.Status.IN_PROGRESS,
            current_step=ProductImportDraft.Step.REVIEW,
        )
        product = publish_product_import_draft(draft)
        self.assertEqual(product.name, 'Imported Bag')
        self.assertEqual(product.variations.count(), 1)
        self.assertEqual(product.attributes.count(), 1)
        self.assertTrue(product.group_buys.filter(status=GroupBuy.Status.OPEN).exists())

    def test_publish_import_draft_copies_all_product_images(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from core.openai_product_import import normalize_parsed_draft
        from core.product_import import ProductImportDraft, ProductImportMedia
        from core.product_import_services import publish_product_import_draft

        draft_data = normalize_parsed_draft(
            {
                'name': 'Imported Bag',
                'description': 'Test bag',
                'category_slug': 'bags-import',
                'attributes': [],
                'options': [{'name': 'Color', 'values': [{'value': 'Black'}]}],
                'variations': [{
                    'sku': 'BAG-BLK',
                    'price': '3.00',
                    'option_selections': {'Color': 'Black'},
                }],
            },
            categories=[{'id': self.category.pk, 'name': 'Bags', 'slug': 'bags-import'}],
            suppliers=[],
        )
        draft = ProductImportDraft.objects.create(
            created_by=self.admin,
            draft_data=draft_data,
            status=ProductImportDraft.Status.IN_PROGRESS,
            current_step=ProductImportDraft.Step.REVIEW,
        )
        for index in range(3):
            ProductImportMedia.objects.create(
                draft=draft,
                file=SimpleUploadedFile(
                    f'product-{index}.jpg',
                    b'product-image-' + str(index).encode() * 200,
                    content_type='image/jpeg',
                ),
                is_primary=index == 0,
                sort_order=index,
            )
        ProductImportMedia.objects.create(
            draft=draft,
            variation_sku='BAG-BLK',
            file=SimpleUploadedFile(
                'variation.jpg',
                b'variation-image-' * 200,
                content_type='image/jpeg',
            ),
            is_primary=True,
            sort_order=0,
        )

        product = publish_product_import_draft(draft)

        self.assertEqual(product.product_files.count(), 3)
        self.assertEqual(product.files.filter(variation__isnull=False).count(), 1)
        self.assertEqual(
            set(product.product_files.values_list('sort_order', flat=True)),
            {0, 1, 2},
        )

    def test_set_product_import_media_primary(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from core.product_import import ProductImportDraft, ProductImportMedia
        from core.product_import_services import set_product_import_media_primary

        draft = ProductImportDraft.objects.create(
            created_by=self.admin,
            draft_data={'name': 'Imported Bag'},
        )
        first = ProductImportMedia.objects.create(
            draft=draft,
            file=SimpleUploadedFile('one.jpg', b'one' * 300, content_type='image/jpeg'),
            is_primary=True,
            sort_order=0,
        )
        second = ProductImportMedia.objects.create(
            draft=draft,
            file=SimpleUploadedFile('two.jpg', b'two' * 300, content_type='image/jpeg'),
            is_primary=False,
            sort_order=1,
        )

        set_product_import_media_primary(draft, second.pk)

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(first.is_primary)
        self.assertTrue(second.is_primary)


class ListingImageFetcherTests(TestCase):
    SAMPLE_HTML = """
    <html><body>
    <script>
    window.detailData = {"imageUrlList": [
        "https://s.alicdn.com/@img/ibank/O1CN01abc_main.jpg_350x350.jpg",
        "https://s.alicdn.com/@img/ibank/O1CN01def_side.jpg"
    ]};
    </script>
    <img src="https://s.alicdn.com/@img/ibank/logo.png">
    </body></html>
    """

    def test_is_alibaba_listing_url(self):
        from core.listing_image_fetcher import is_alibaba_listing_url

        self.assertTrue(
            is_alibaba_listing_url(
                'https://www.alibaba.com/product-detail/Widget_1234567890.html'
            )
        )
        self.assertFalse(is_alibaba_listing_url('https://www.amazon.com/dp/B123'))

    def test_extract_listing_image_urls(self):
        from core.listing_image_fetcher import extract_listing_image_urls

        urls = extract_listing_image_urls(self.SAMPLE_HTML)
        self.assertEqual(len(urls), 2)
        self.assertTrue(all('alicdn.com' in url for url in urls))
        self.assertTrue(all('logo' not in url for url in urls))
        self.assertIn('main.jpg', urls[0])

    def test_download_listing_image_retries_on_timeout(self):
        from unittest.mock import patch

        import requests

        from core.listing_image_fetcher import download_listing_image

        url = 'https://img.alicdn.com/@img/ibank/O1CN01abc_main.jpg'
        attempts = {'count': 0}

        class FakeResponse:
            headers = {'content-type': 'image/jpeg'}

            @staticmethod
            def raise_for_status():
                return None

            @staticmethod
            def iter_content(chunk_size=65536):
                yield b'fake-image-bytes' * 200

        def fake_get(*args, **kwargs):
            attempts['count'] += 1
            if attempts['count'] == 1:
                raise requests.ReadTimeout('Read timed out.')
            return FakeResponse()

        with patch('core.listing_image_fetcher.time.sleep'), patch(
            'requests.Session.get',
            side_effect=fake_get,
        ):
            content_file = download_listing_image(url)

        self.assertEqual(attempts['count'], 2)
        self.assertGreater(len(content_file.read()), 1024)

    def test_fetch_listing_images_for_draft(self):
        from unittest.mock import patch

        from django.contrib.auth import get_user_model
        from django.core.files.base import ContentFile

        from core.listing_image_fetcher import ListingImageFetchError
        from core.product_import import ProductImportDraft
        from core.product_import_services import fetch_listing_images_for_draft

        User = get_user_model()
        admin = User.objects.create_user(
            phone='+254700333444',
            password='pass',
            role='admin',
        )
        draft = ProductImportDraft.objects.create(
            created_by=admin,
            source_url='https://www.alibaba.com/product-detail/Test_1234567890.html',
            draft_data={'name': 'Test product'},
        )

        fake_image = ContentFile(b'fake-image-bytes' * 200, name='test.jpg')

        with patch(
            'core.listing_image_fetcher.fetch_listing_page_html',
            return_value=self.SAMPLE_HTML,
        ), patch(
            'core.listing_image_fetcher.download_listing_image',
            return_value=fake_image,
        ):
            result = fetch_listing_images_for_draft(draft)

        self.assertEqual(result['downloaded'], 2)
        self.assertEqual(draft.media_files.filter(variation_sku='').count(), 2)
        self.assertTrue(draft.media_files.filter(variation_sku='', is_primary=True).exists())

    def test_fetch_listing_images_requires_url(self):
        from django.contrib.auth import get_user_model

        from core.product_import import ProductImportDraft
        from core.product_import_services import fetch_listing_images_for_draft

        User = get_user_model()
        admin = User.objects.create_user(
            phone='+254700555666',
            password='pass',
            role='admin',
        )
        draft = ProductImportDraft.objects.create(
            created_by=admin,
            draft_data={'name': 'No URL product'},
        )

        with self.assertRaises(ValidationError):
            fetch_listing_images_for_draft(draft)


class SupplierAdminTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        self.admin = User.objects.create_user(
            phone='+254700777888',
            password='pass',
            role='admin',
        )
        self.client.login(phone='+254700777888', password='pass')
        from core.supplier import Supplier

        self.supplier = Supplier.objects.create(
            name='Shenzhen Widget Co',
            contact_name='Amy Chen',
            email='amy@widgets.cn',
            phone='+86 138 0000 0000',
            alibaba_url='https://widgetco.en.alibaba.com',
            country='China',
        )

    def test_supplier_list_requires_admin(self):
        self.client.logout()
        response = self.client.get(reverse('core:supplier_list'))
        self.assertEqual(response.status_code, 302)

    def test_supplier_list_shows_suppliers(self):
        response = self.client.get(reverse('core:supplier_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Shenzhen Widget Co')

    def test_supplier_list_search(self):
        response = self.client.get(reverse('core:supplier_list'), {'q': 'Amy', 'status': 'all'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Shenzhen Widget Co')

        response = self.client.get(reverse('core:supplier_list'), {'q': 'missing', 'status': 'all'})
        self.assertNotContains(response, 'Shenzhen Widget Co')

    def test_supplier_manage_page(self):
        response = self.client.get(
            reverse('core:supplier_manage', kwargs={'supplier_id': self.supplier.pk})
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Shenzhen Widget Co')
        self.assertContains(response, 'amy@widgets.cn')

    def test_supplier_create_redirects_to_manage(self):
        response = self.client.post(
            reverse('core:supplier_create'),
            {
                'name': 'Guangzhou Bag Factory',
                'contact_name': 'Li Wei',
                'email': '',
                'phone': '',
                'wechat_id': '',
                'alibaba_url': '',
                'country': 'China',
                'notes': '',
                'is_active': 'on',
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn('/suppliers/', response.url)
        self.assertContains(
            self.client.get(response.url),
            'Guangzhou Bag Factory',
        )
