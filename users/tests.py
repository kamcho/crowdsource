import json
from unittest.mock import patch

import pyotp
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from tenants.models import Tenant, TenantMembership
from users.two_factor import activate_totp, generate_totp_secret, verify_user_totp

User = get_user_model()

GOOGLE_SETTINGS = {
    'GOOGLE_CLIENT_ID': 'test-client-id.apps.googleusercontent.com',
}


class GoogleAuthTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.client.get(reverse('users:signin'))
        self.token_payload = {
            'sub': 'google-sub-123',
            'email': 'buyer@gmail.com',
            'email_verified': True,
            'given_name': 'Jane',
            'family_name': 'Doe',
            'aud': 'test-client-id.apps.googleusercontent.com',
        }

    def _post_google_credential(self, credential='fake-token', next_url=''):
        return self.client.post(
            reverse('users:google_auth'),
            data=json.dumps({'credential': credential, 'next': next_url}),
            content_type='application/json',
            HTTP_X_CSRFTOKEN=self.client.cookies['csrftoken'].value,
        )

    @override_settings(**GOOGLE_SETTINGS)
    @patch('users.views.verify_google_credential')
    def test_google_sign_in_creates_customer_and_requires_phone_link(self, verify):
        verify.return_value = self.token_payload
        response = self._post_google_credential()
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['redirect'], reverse('users:complete_profile'))
        user = User.objects.get(google_id='google-sub-123')
        self.assertEqual(user.role, User.Role.CUSTOMER)
        self.assertIsNone(user.phone)
        self.assertEqual(user.signup_tenant, Tenant.objects.get(is_default=True))
        self.assertEqual(self.client.session['_auth_user_id'], str(user.pk))

    @override_settings(**GOOGLE_SETTINGS)
    @patch('users.views.verify_google_credential')
    def test_google_sign_in_existing_user_redirects_to_profile(self, verify):
        user = User.objects.create_user(
            phone='0712345678',
            password='1234',
            email='buyer@gmail.com',
            google_id='google-sub-123',
            first_name='Jane',
            last_name='Doe',
        )
        verify.return_value = self.token_payload
        response = self._post_google_credential()
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['redirect'], reverse('users:profile'))
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)
        user.refresh_from_db()
        self.assertIsNone(user.signup_tenant)

    @override_settings(**GOOGLE_SETTINGS)
    @patch('users.views.verify_google_credential')
    def test_google_sign_in_links_email_only_account(self, verify):
        user = User.objects.create_user(
            phone='0798765432',
            password='1234',
            email='buyer@gmail.com',
            first_name='Jane',
            last_name='Doe',
        )
        verify.return_value = self.token_payload
        response = self._post_google_credential()
        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertEqual(user.google_id, 'google-sub-123')

    @override_settings(**GOOGLE_SETTINGS)
    @patch('users.views.verify_google_credential')
    def test_complete_profile_keeps_user_logged_in(self, verify):
        verify.return_value = {
            **self.token_payload,
            'sub': 'google-sub-new',
            'email': 'newbuyer@gmail.com',
        }
        response = self._post_google_credential()
        self.assertTrue(response.json()['ok'])

        self.client.get(reverse('users:complete_profile'))
        response = self.client.post(
            reverse('users:complete_profile'),
            {
                'phone': '0711223344',
            },
            HTTP_X_CSRFTOKEN=self.client.cookies['csrftoken'].value,
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.client.session.get('_auth_user_id'))
        user = User.objects.get(google_id='google-sub-new')
        self.assertEqual(str(user.phone), '+254711223344')
        self.assertFalse(user.has_usable_password())

    @override_settings(**GOOGLE_SETTINGS)
    def test_sign_in_google_only_account_prompts_google(self):
        user = User(
            google_id='google-only',
            email='googleonly@gmail.com',
            first_name='G',
            last_name='User',
        )
        user.set_unusable_password()
        user.save()
        self.client.get(reverse('users:signin'))
        response = self.client.post(
            reverse('users:signin'),
            {
                'login': 'googleonly@gmail.com',
                'password': 'wrong-password',
            },
            HTTP_X_CSRFTOKEN=self.client.cookies['csrftoken'].value,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Continue with Google')
        self.assertContains(response, 'googleonly@gmail.com')
        self.assertNotContains(response, 'This account uses Google Sign-In. Use the Google button below')
        self.assertNotIn('_auth_user_id', self.client.session)

    @override_settings(GOOGLE_CLIENT_ID='')
    def test_google_sign_in_not_configured(self):
        response = self._post_google_credential()
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['ok'])
        self.assertIn('not configured', response.json()['error'].lower())

    @override_settings(**GOOGLE_SETTINGS)
    def test_google_sign_in_missing_credential(self):
        response = self.client.post(
            reverse('users:google_auth'),
            data=json.dumps({}),
            content_type='application/json',
            HTTP_X_CSRFTOKEN=self.client.cookies['csrftoken'].value,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('Missing Google credential', response.json()['error'])


class TwoFactorAuthTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client(enforce_csrf_checks=True)
        self.user = User.objects.create_user(
            phone='0711223344',
            password='testpass123',
            first_name='Two',
            last_name='Factor',
        )
        self.secret = generate_totp_secret()
        activate_totp(self.user, self.secret)
        self.user.refresh_from_db()

    def _sign_in_start(self):
        return self.client.post(
            reverse('users:signin'),
            {'phone': '0711223344', 'password': 'testpass123'},
            HTTP_X_CSRFTOKEN=self.client.cookies['csrftoken'].value,
        )

    def test_sign_in_without_2fa_logs_in_directly(self):
        deactivate = User.objects.get(pk=self.user.pk)
        deactivate.two_factor_enabled = False
        deactivate.totp_secret = ''
        deactivate.save(update_fields=['two_factor_enabled', 'totp_secret'])
        self.client.get(reverse('users:signin'))
        response = self._sign_in_start()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)

    def test_sign_in_with_2fa_redirects_to_verify(self):
        self.client.get(reverse('users:signin'))
        response = self._sign_in_start()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('users:two_factor_verify'))
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(self.client.session['pending_2fa_user_id'], str(self.user.pk))

    def test_verify_2fa_completes_login(self):
        self.client.get(reverse('users:signin'))
        self._sign_in_start()
        code = pyotp.TOTP(self.secret).now()
        response = self.client.post(
            reverse('users:two_factor_verify'),
            {'code': code},
            HTTP_X_CSRFTOKEN=self.client.cookies['csrftoken'].value,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)

    def test_verify_totp_rejects_wrong_code(self):
        ok, _ = verify_user_totp(self.user, '000000', purpose='login')
        self.assertFalse(ok)

    def test_enable_2fa_after_code_confirmation(self):
        user = User.objects.create_user(
            phone='0799001122',
            password='testpass123',
            first_name='New',
            last_name='User',
        )
        setup_secret = generate_totp_secret()
        self.client.force_login(user)
        self.client.get(reverse('users:two_factor_settings'))
        session = self.client.session
        session['2fa_setup_secret'] = setup_secret
        session['2fa_pending_enable'] = str(user.pk)
        session.save()
        code = pyotp.TOTP(setup_secret).now()
        response = self.client.post(
            reverse('users:two_factor_settings'),
            {'action': 'confirm_enable', 'code': code},
            HTTP_X_CSRFTOKEN=self.client.cookies['csrftoken'].value,
        )
        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        self.assertTrue(user.two_factor_enabled)
        self.assertEqual(user.totp_secret, setup_secret)


class UserProfileTests(TestCase):
    def test_profile_renders_when_user_has_no_cart(self):
        user = User.objects.create_user(
            phone='0722334455',
            password='testpass123',
            first_name='New',
            last_name='Buyer',
        )
        self.client.force_login(user)

        response = self.client.get(reverse('users:profile'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['user_stats']['cart_items'], 0)
        self.assertContains(response, reverse('users:password_change'))

    def test_tenant_staff_sees_shop_management_links_in_account_sidebar(self):
        staff_user = User.objects.create_user(
            phone='0722334456',
            password='testpass123',
            first_name='Shop',
            last_name='Staff',
        )
        tenant = Tenant.objects.get(is_default=True)
        TenantMembership.objects.update_or_create(
            tenant=tenant,
            user=staff_user,
            defaults={'role': TenantMembership.Role.STAFF},
        )
        self.client.force_login(staff_user)

        response = self.client.get(reverse('users:profile'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Shop management')
        self.assertContains(response, reverse('core:admin_dashboard'))
        self.assertContains(response, reverse('core:admin_order_list'))
        self.assertContains(response, reverse('core:customer_list'))
        self.assertContains(response, reverse('core:group_buy_list'))
        self.assertContains(response, reverse('core:import_shipment_list'))
        self.assertNotContains(response, reverse('core:product_list'))
        self.assertNotContains(response, 'Shop settings &amp; staff')

    def test_tenant_admin_sidebar_also_links_to_shop_settings(self):
        tenant_admin = User.objects.create_user(
            phone='0722334457',
            password='testpass123',
        )
        tenant = Tenant.objects.get(is_default=True)
        TenantMembership.objects.update_or_create(
            tenant=tenant,
            user=tenant_admin,
            defaults={'role': TenantMembership.Role.ADMIN},
        )
        self.client.force_login(tenant_admin)

        response = self.client.get(reverse('users:profile'))

        self.assertContains(response, reverse('core:product_list'))
        self.assertContains(
            response,
            reverse('core:tenant_edit', kwargs={'tenant_id': tenant.pk}),
        )

    def test_password_reset_email_completes_password_reset(self):
        user = User.objects.create_user(
            phone='0722334458',
            password='old-password-456!',
            email='reset@example.com',
        )

        response = self.client.post(
            reverse('users:password_reset'),
            {'email': 'reset@example.com'},
        )

        self.assertRedirects(response, reverse('users:password_reset_done'))
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(len(mail.outbox), 1)
        reset_url = next(
            line for line in mail.outbox[0].body.splitlines()
            if '/users/reset/' in line
        )
        response = self.client.get(reset_url, follow=True)
        self.assertEqual(response.status_code, 200)
        response = self.client.post(response.request['PATH_INFO'], {
            'new_password1': 'Better-new-password-456!',
            'new_password2': 'Better-new-password-456!',
        })

        self.assertRedirects(
            response,
            reverse('users:password_reset_complete'),
        )
        user.refresh_from_db()
        self.assertTrue(user.check_password('Better-new-password-456!'))
        self.assertFalse(user.check_password('old-password-456!'))

    def test_password_reset_response_does_not_disclose_unknown_email(self):
        response = self.client.post(
            reverse('users:password_reset'),
            {'email': 'not-registered@example.com'},
        )

        self.assertRedirects(response, reverse('users:password_reset_done'))
        self.assertContains(
            self.client.get(response.url),
            'If an active account uses that email address',
        )
        self.assertEqual(len(mail.outbox), 0)

    def test_google_account_can_set_password_using_email_reset(self):
        user = User.objects.create_user(
            phone='0722334459',
            password='temporary-password-123!',
            email='google-reset@example.com',
            google_id='google-password-reset',
        )
        user.set_unusable_password()
        user.save(update_fields=['password'])

        response = self.client.post(
            reverse('users:password_reset'),
            {'email': user.email},
        )

        self.assertRedirects(response, reverse('users:password_reset_done'))
        self.assertEqual(len(mail.outbox), 1)

    def test_signed_in_user_can_change_password_without_logging_out(self):
        user = User.objects.create_user(
            phone='0722334460',
            password='old-password-789!',
        )
        self.client.force_login(user)

        response = self.client.post(
            reverse('users:password_change'),
            {
                'old_password': 'old-password-789!',
                'new_password1': 'Brand-new-password-789!',
                'new_password2': 'Brand-new-password-789!',
            },
        )

        self.assertRedirects(
            response,
            reverse('users:password_change_done'),
        )
        user.refresh_from_db()
        self.assertTrue(user.check_password('Brand-new-password-789!'))
        self.assertEqual(
            self.client.get(reverse('users:profile')).status_code,
            200,
        )


class SignupTenantAttributionTests(TestCase):
    @override_settings(
        TENANT_BASE_DOMAIN='example.test',
        ALLOWED_HOSTS=['testserver', '.example.test'],
    )
    def test_phone_signup_records_subdomain_tenant(self):
        tenant = Tenant.objects.create(name='Beta Imports', slug='beta')
        response = self.client.post(
            reverse('users:signup'),
            {
                'phone': '0712345678',
                'first_name': 'New',
                'last_name': 'Buyer',
                'password1': 'Secure-pass-123!',
                'password2': 'Secure-pass-123!',
            },
            HTTP_HOST='beta.example.test',
        )

        self.assertEqual(response.status_code, 302)
        user = User.objects.get(phone='+254712345678')
        self.assertEqual(user.signup_tenant, tenant)

    @override_settings(
        TENANT_BASE_DOMAIN='example.test',
        ALLOWED_HOSTS=['testserver', '.example.test'],
        GOOGLE_CLIENT_ID='test-client-id.apps.googleusercontent.com',
    )
    @patch('users.views.verify_google_credential')
    def test_google_signup_records_subdomain_tenant(self, verify):
        tenant = Tenant.objects.create(name='Beta Imports', slug='beta')
        verify.return_value = {
            'sub': 'google-beta-signup',
            'email': 'beta-buyer@gmail.com',
            'email_verified': True,
            'given_name': 'Beta',
            'family_name': 'Buyer',
            'aud': 'test-client-id.apps.googleusercontent.com',
        }

        response = self.client.post(
            reverse('users:google_auth'),
            data=json.dumps({'credential': 'fake-token'}),
            content_type='application/json',
            HTTP_HOST='beta.example.test',
        )

        self.assertEqual(response.status_code, 200)
        user = User.objects.get(google_id='google-beta-signup')
        self.assertEqual(user.signup_tenant, tenant)
