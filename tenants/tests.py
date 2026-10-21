from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import Category, Product
from core.product_variation import ProductOption, ProductOptionValue, ProductVariation
from .context import reset_current_tenant, set_current_tenant
from .models import Tenant, TenantMembership, TenantPageView
from .permissions import user_is_tenant_admin


@override_settings(
    DEBUG=True,
    TENANT_BASE_DOMAIN='localhost',
    ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1', '.localhost'],
)
class TenantResolutionTests(TestCase):
    def setUp(self):
        self.default_tenant = Tenant.objects.get(is_default=True)
        self.alpha = Tenant.objects.create(name='Alpha Shop', slug='alpha')
        self.beta = Tenant.objects.create(name='Beta Shop', slug='beta')

    def _create_product(self, tenant, name):
        token = set_current_tenant(tenant)
        try:
            category = Category.objects.create(name='Catalog')
            return Product.objects.create(category=category, name=name)
        finally:
            reset_current_tenant(token)

    def test_subdomain_shows_only_its_tenant_catalog(self):
        alpha_product = self._create_product(self.alpha, 'Alpha product')
        beta_product = self._create_product(self.beta, 'Beta product')

        response = self.client.get(
            reverse('home:product_browse'),
            HTTP_HOST='alpha.localhost',
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Alpha Shop')
        self.assertContains(response, alpha_product.name)
        self.assertNotContains(response, beta_product.name)

    def test_primary_domain_resolves_default_tenant(self):
        response = self.client.get(
            reverse('home:landing'),
            HTTP_HOST='testserver',
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.default_tenant.name)

    @override_settings(
        SITE_CONTACT_PHONE='+254700111222',
        SITE_CONTACT_PHONE_DISPLAY='+254 700 111222',
    )
    def test_subdomain_uses_tenant_contact_number_in_site_footer(self):
        self.alpha.contact_phone = '+254711222333'
        self.alpha.contact_phone_display = '+254 711 222333'
        self.alpha.save(update_fields=['contact_phone', 'contact_phone_display'])

        response = self.client.get(
            reverse('home:landing'),
            HTTP_HOST='alpha.localhost',
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'WhatsApp +254 711 222333')
        self.assertContains(response, 'https://wa.me/254711222333')
        self.assertNotContains(response, 'WhatsApp +254 700 111222')

    @override_settings(
        SITE_CONTACT_PHONE='+254700111222',
        SITE_CONTACT_PHONE_DISPLAY='+254 700 111222',
    )
    def test_tenant_without_contact_uses_platform_contact_number(self):
        response = self.client.get(
            reverse('home:landing'),
            HTTP_HOST='alpha.localhost',
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'WhatsApp +254 700 111222')

    @override_settings(DEBUG=False)
    def test_testserver_resolves_default_tenant_when_debug_is_disabled(self):
        response = self.client.get(
            reverse('home:landing'),
            HTTP_HOST='testserver',
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.default_tenant.name)

    def test_unknown_tenant_subdomain_returns_not_found(self):
        response = self.client.get(
            reverse('home:landing'),
            HTTP_HOST='unknown.localhost',
        )

        self.assertEqual(response.status_code, 404)

    def test_cannot_attach_related_data_from_another_tenant(self):
        alpha_category = self._create_product(self.alpha, 'Alpha product').category
        token = set_current_tenant(self.beta)
        try:
            with self.assertRaises(ValidationError):
                Product.objects.create(category=alpha_category, name='Cross-tenant product')
        finally:
            reset_current_tenant(token)

    def test_unscoped_queries_default_to_the_default_tenant(self):
        alpha_product = self._create_product(self.alpha, 'Alpha product')
        default_product = self._create_product(
            self.default_tenant,
            'Default product',
        )

        self.assertFalse(Product.objects.filter(pk=alpha_product.pk).exists())
        self.assertTrue(Product.objects.filter(pk=default_product.pk).exists())

    def test_cannot_attach_option_values_from_another_tenant(self):
        alpha_product = self._create_product(self.alpha, 'Alpha product')
        token = set_current_tenant(self.alpha)
        try:
            alpha_option = ProductOption.objects.create(
                product=alpha_product,
                name='Color',
            )
            alpha_value = ProductOptionValue.objects.create(
                option=alpha_option,
                value='Red',
            )
        finally:
            reset_current_tenant(token)

        token = set_current_tenant(self.beta)
        try:
            beta_product = self._create_product(self.beta, 'Beta product')
            variation = ProductVariation.objects.create(
                product=beta_product,
                sku='BETA-RED',
            )
            with self.assertRaises(ValidationError):
                variation.option_values.add(alpha_value)
        finally:
            reset_current_tenant(token)

    def test_full_clean_assigns_default_tenant_before_custom_validation(self):
        product = Product(name='Validated product')

        product.full_clean(exclude=['category'])

        self.assertEqual(product.tenant, self.default_tenant)

    def test_new_users_join_the_current_tenant(self):
        from django.contrib.auth import get_user_model

        token = set_current_tenant(self.alpha)
        try:
            user = get_user_model().objects.create_user(
                phone='+254700000099',
                password='pass',
            )
        finally:
            reset_current_tenant(token)

        self.assertTrue(
            TenantMembership.objects.filter(
                tenant=self.alpha,
                user=user,
                role=TenantMembership.Role.CUSTOMER,
            ).exists(),
        )

    def test_admin_privileges_are_tenant_specific(self):
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.create_user(
            phone='+254700000098',
            password='pass',
        )
        TenantMembership.objects.create(
            tenant=self.alpha,
            user=user,
            role=TenantMembership.Role.ADMIN,
        )

        self.assertTrue(user_is_tenant_admin(user, self.alpha))
        self.assertFalse(user_is_tenant_admin(user, self.beta))


@override_settings(
    DEBUG=True,
    TENANT_BASE_DOMAIN='localhost',
    ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1', '.localhost'],
)
class TenantManagementTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        self.user_model = get_user_model()
        self.default_tenant = Tenant.objects.get(is_default=True)
        self.admin = self.user_model.objects.create_user(
            phone='+254700000097',
            password='test-pass-123',
        )
        TenantMembership.objects.filter(
            tenant=self.default_tenant,
            user=self.admin,
        ).update(role=TenantMembership.Role.ADMIN)
        self.client.force_login(self.admin)

    def test_tenant_admin_can_manage_own_shop_but_not_platform_tenants(self):
        response = self.client.get(reverse('core:tenant_list'))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('home:landing'))

        response = self.client.get(
            reverse('core:tenant_edit', kwargs={'tenant_id': self.default_tenant.pk}),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Tenant staff and admins')
        self.assertNotContains(response, 'name="is_active"')
        self.assertNotContains(response, 'name="slug"')

        other_tenant = Tenant.objects.create(name='Other Shop', slug='other-shop')
        response = self.client.get(
            reverse('core:tenant_edit', kwargs={'tenant_id': other_tenant.pk}),
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('home:landing'))

    def test_tenant_dashboard_shows_store_analytics_scoped_to_selected_tenant(self):
        tenant = Tenant.objects.create(name='Analytics Shop', slug='analytics-shop')
        other_tenant = Tenant.objects.create(name='Other Shop', slug='other-shop')
        token = set_current_tenant(tenant)
        try:
            category = Category.objects.create(name='Analytics category')
            Product.objects.create(category=category, name='Analytics product')
        finally:
            reset_current_tenant(token)
        token = set_current_tenant(other_tenant)
        try:
            category = Category.objects.create(name='Other category')
            Product.objects.create(category=category, name='Other product')
        finally:
            reset_current_tenant(token)

        TenantPageView.objects.create(
            tenant=tenant,
            path='/products/analytics-product/',
            ip_address='203.0.113.1',
        )
        TenantPageView.objects.create(
            tenant=other_tenant,
            path='/products/other-product/',
            ip_address='203.0.113.2',
        )
        platform_admin = self.user_model.objects.create_superuser(
            phone='+254700000089',
            password='test-pass-123',
        )
        self.client.force_login(platform_admin)

        response = self.client.get(
            reverse('core:tenant_edit', kwargs={'tenant_id': tenant.pk}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['analytics']['products_total'], 1)
        self.assertEqual(response.context['analytics']['views_30_days'], 1)
        self.assertContains(response, 'Shop analytics')
        self.assertContains(response, '203.0.113.1')
        self.assertNotContains(response, '203.0.113.2')
        self.assertContains(response, 'Manage products')
        self.assertContains(response, 'View orders')
        self.assertContains(
            response,
            'http://analytics-shop.localhost/core/products/',
        )

    def test_storefront_page_views_record_page_ip_and_logged_in_user(self):
        response = self.client.get(
            reverse('home:landing'),
            HTTP_HOST='testserver',
            HTTP_X_REAL_IP='203.0.113.10',
        )

        self.assertEqual(response.status_code, 200)
        page_view = TenantPageView.objects.get(path='/')
        self.assertEqual(page_view.tenant, self.default_tenant)
        self.assertEqual(page_view.ip_address, '203.0.113.10')
        self.assertEqual(page_view.user, self.admin)

    def test_dashboard_page_views_record_admin_url_and_ip(self):
        response = self.client.get(
            reverse('core:tenant_edit', kwargs={'tenant_id': self.default_tenant.pk}),
            HTTP_X_REAL_IP='203.0.113.11',
        )

        self.assertEqual(response.status_code, 200)
        page_view = TenantPageView.objects.get(
            path=reverse(
                'core:tenant_edit',
                kwargs={'tenant_id': self.default_tenant.pk},
            ),
        )
        self.assertEqual(page_view.tenant, self.default_tenant)
        self.assertEqual(page_view.ip_address, '203.0.113.11')
        self.assertEqual(page_view.user, self.admin)

    def test_admin_can_create_and_edit_tenant(self):
        platform_admin = self.user_model.objects.create_superuser(
            phone='+254700000094',
            password='test-pass-123',
        )
        self.client.force_login(platform_admin)
        response = self.client.post(
            reverse('core:tenant_create'),
            {
                'name': 'Nairobi Wholesale',
                'slug': 'nairobi-wholesale',
                'contact_phone': '0711222333',
                'contact_phone_display': '+254 711 222333',
                'is_active': 'on',
            },
        )

        tenant = Tenant.objects.get(slug='nairobi-wholesale')
        self.assertEqual(tenant.contact_phone, '+254711222333')
        self.assertEqual(tenant.contact_phone_display, '+254 711 222333')
        self.assertRedirects(
            response,
            reverse('core:tenant_edit', kwargs={'tenant_id': tenant.pk}),
        )
        self.assertContains(
            self.client.get(reverse('core:tenant_edit', kwargs={'tenant_id': tenant.pk})),
            'nairobi-wholesale.localhost',
        )

    def test_admin_can_assign_and_remove_tenant_admin(self):
        platform_admin = self.user_model.objects.create_superuser(
            phone='+254700000093',
            password='test-pass-123',
        )
        self.client.force_login(platform_admin)
        tenant = Tenant.objects.create(name='Alpha Shop', slug='alpha')
        manager = self.user_model.objects.create_user(
            phone='+254700000096',
            password='test-pass-123',
        )

        response = self.client.post(
            reverse('core:tenant_add_membership', kwargs={'tenant_id': tenant.pk}),
            {'phone': str(manager.phone), 'role': TenantMembership.Role.ADMIN},
        )

        membership = TenantMembership.objects.get(tenant=tenant, user=manager)
        self.assertEqual(membership.role, TenantMembership.Role.ADMIN)
        self.assertRedirects(
            response,
            reverse('core:tenant_edit', kwargs={'tenant_id': tenant.pk}),
        )
        response = self.client.post(
            reverse(
                'core:tenant_remove_membership',
                kwargs={'tenant_id': tenant.pk, 'membership_id': membership.pk},
            ),
        )

        self.assertFalse(TenantMembership.objects.filter(pk=membership.pk).exists())
        self.assertRedirects(
            response,
            reverse('core:tenant_edit', kwargs={'tenant_id': tenant.pk}),
        )

    def test_tenant_admin_can_manage_members_of_own_shop(self):
        manager = self.user_model.objects.create_user(
            phone='+254700000092',
            password='test-pass-123',
        )

        response = self.client.post(
            reverse(
                'core:tenant_add_membership',
                kwargs={'tenant_id': self.default_tenant.pk},
            ),
            {'phone': str(manager.phone), 'role': TenantMembership.Role.STAFF},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            TenantMembership.objects.get(
                tenant=self.default_tenant,
                user=manager,
            ).role,
            TenantMembership.Role.STAFF,
        )

        other_tenant = Tenant.objects.create(name='Other Shop', slug='other-shop')
        response = self.client.post(
            reverse(
                'core:tenant_add_membership',
                kwargs={'tenant_id': other_tenant.pk},
            ),
            {'phone': str(manager.phone), 'role': TenantMembership.Role.ADMIN},
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            TenantMembership.objects.filter(
                tenant=other_tenant,
                user=manager,
            ).exists(),
        )

    def test_tenant_admin_can_create_staff_account_with_arbitrary_password(self):
        phone = '+254700000091'
        password = '0712345678'

        response = self.client.post(
            reverse(
                'core:tenant_create_member',
                kwargs={'tenant_id': self.default_tenant.pk},
            ),
            {
                'phone': phone,
                'first_name': 'New',
                'last_name': 'Staff',
                'email': 'new.staff@example.com',
                'password': password,
                'role': TenantMembership.Role.STAFF,
            },
        )

        user = self.user_model.objects.get(phone=phone)
        membership = TenantMembership.objects.get(
            tenant=self.default_tenant,
            user=user,
        )
        self.assertRedirects(
            response,
            reverse('core:tenant_edit', kwargs={'tenant_id': self.default_tenant.pk}),
        )
        self.assertTrue(user.check_password(password))
        self.assertEqual(membership.role, TenantMembership.Role.STAFF)
        self.assertEqual(user.role, self.user_model.Role.CUSTOMER)
        self.assertFalse(
            TenantMembership.objects.filter(
                user=user,
            ).exclude(tenant=self.default_tenant).exists(),
        )

    def test_tenant_member_create_rejects_existing_phone(self):
        existing_user = self.user_model.objects.create_user(
            phone='+254700000090',
            password='existing-password',
        )

        response = self.client.post(
            reverse(
                'core:tenant_create_member',
                kwargs={'tenant_id': self.default_tenant.pk},
            ),
            {
                'phone': str(existing_user.phone),
                'first_name': 'Existing',
                'last_name': 'User',
                'password': 'any-password',
                'role': TenantMembership.Role.ADMIN,
            },
        )

        self.assertRedirects(
            response,
            reverse('core:tenant_edit', kwargs={'tenant_id': self.default_tenant.pk}),
        )
        self.assertFalse(
            TenantMembership.objects.filter(
                tenant=self.default_tenant,
                user=existing_user,
                role=TenantMembership.Role.ADMIN,
            ).exists(),
        )

    def test_other_tenant_admin_cannot_manage_platform_tenants(self):
        tenant = Tenant.objects.create(name='Alpha Shop', slug='alpha')
        other_admin = self.user_model.objects.create_user(
            phone='+254700000095',
            password='test-pass-123',
        )
        TenantMembership.objects.create(
            tenant=tenant,
            user=other_admin,
            role=TenantMembership.Role.ADMIN,
        )
        self.client.force_login(other_admin)

        response = self.client.get(reverse('core:tenant_list'))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('home:landing'))
