from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import Category, Product


@override_settings(SITE_DOMAIN='testserver', SITE_PROTOCOL='http')
class SeoViewsTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name='Electronics')
        self.product = Product.objects.create(
            category=self.category,
            name='Test Widget',
            description='A useful widget for testing.',
            is_active=True,
        )

    def test_robots_txt_lists_sitemap_and_blocks_private_paths(self):
        response = self.client.get(reverse('robots_txt'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/plain; charset=utf-8')
        body = response.content.decode()
        self.assertIn('Sitemap: http://testserver/sitemap.xml', body)
        self.assertIn('Disallow: /admin/', body)
        self.assertIn('Disallow: /core/', body)
        self.assertIn('Disallow: /users/', body)

    def test_sitemap_includes_public_pages_and_products(self):
        response = self.client.get(reverse('sitemap'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/xml')
        body = response.content.decode()
        self.assertIn('<loc>http://testserver/</loc>', body)
        self.assertIn('<loc>http://testserver/products/</loc>', body)
        self.assertIn('<loc>http://testserver/privacy/</loc>', body)
        self.assertIn(f'<loc>http://testserver{self.product.get_absolute_url()}</loc>', body)
        self.assertIn(
            f'<loc>http://testserver/products/?category={self.category.slug}</loc>',
            body,
        )

    def test_privacy_policy_page_renders(self):
        response = self.client.get(reverse('home:privacy_policy'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Privacy Policy')
        self.assertContains(response, 'do not sell, rent, or share your personal data with third parties')
