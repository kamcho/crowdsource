from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import Category, Product
from core.product_variation import ProductOption, ProductOptionValue, ProductVariation
from .context import reset_current_tenant, set_current_tenant
from .models import Tenant, TenantMembership
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

    def test_default_tenant_admin_can_open_management_page(self):
        response = self.client.get(reverse('core:tenant_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Tenants')
        self.assertContains(response, reverse('core:tenant_create'))

    def test_admin_can_create_and_edit_tenant(self):
        response = self.client.post(
            reverse('core:tenant_create'),
            {'name': 'Nairobi Wholesale', 'slug': 'nairobi-wholesale', 'is_active': 'on'},
        )

        tenant = Tenant.objects.get(slug='nairobi-wholesale')
        self.assertRedirects(
            response,
            reverse('core:tenant_edit', kwargs={'tenant_id': tenant.pk}),
        )
        self.assertContains(
            self.client.get(reverse('core:tenant_edit', kwargs={'tenant_id': tenant.pk})),
            'nairobi-wholesale.localhost',
        )

    def test_admin_can_assign_and_remove_tenant_admin(self):
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
