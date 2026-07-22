from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from core.currency import convert_usd_to_kes, format_money, format_money_range
from core.category_utils import build_category_nav_tree
from core.models import Category

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
        self.assertEqual(format_money('12.50', 'USD'), '$12.50')

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
