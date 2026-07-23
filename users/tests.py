import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

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
                'password1': '5678abcd',
                'password2': '5678abcd',
            },
            HTTP_X_CSRFTOKEN=self.client.cookies['csrftoken'].value,
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.client.session.get('_auth_user_id'))
        user = User.objects.get(google_id='google-sub-new')
        self.assertEqual(str(user.phone), '+254711223344')
        self.assertTrue(user.check_password('5678abcd'))

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
