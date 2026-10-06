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

    def test_homepage_renders(self):
        response = self.client.get(reverse('home:landing'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Kenya Imports')

    def test_homepage_seo_meta_and_structured_data(self):
        response = self.client.get(reverse('home:landing'))

        self.assertContains(response, 'rel="canonical"')
        self.assertContains(response, 'application/ld+json')
        self.assertContains(response, '"@type": "WebSite"')
        self.assertContains(response, '<h1>Factory-direct group buys</h1>')

    def test_product_browse_category_seo_title(self):
        response = self.client.get(
            reverse('home:product_browse'),
            {'category': self.category.slug},
        )

        self.assertContains(response, f'{self.category.name} Group Buys')
        self.assertContains(response, 'application/ld+json')
        self.assertContains(response, '"@type": "ItemList"')

    def test_product_detail_seo_and_product_schema(self):
        response = self.client.get(self.product.get_absolute_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '"@type": "Product"')
        self.assertContains(response, '"@type": "BreadcrumbList"')
        self.assertContains(response, '"@type": "Offer"')
        self.assertContains(response, self.product.name)

    def test_product_browse_query_count_stays_flat(self):
        from datetime import timedelta
        from django.utils import timezone

        from core.group_buy import GroupBuy, GroupBuyEntry
        from core.product_file import ProductFile
        from core.product_variation import ProductVariation
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.create_user(phone='+254711000111', password='pass')
        for index in range(3):
            product = Product.objects.create(
                category=self.category,
                name=f'Browse item {index}',
                is_active=True,
            )
            ProductFile.objects.create(
                product=product,
                file=f'products/{index}.jpg',
                media_type=ProductFile.MediaType.IMAGE,
                is_primary=True,
            )
            variation = ProductVariation.objects.create(product=product, sku=f'SKU-{index}', price='4.00')
            group_buy = GroupBuy.objects.create(
                product=product,
                moq=10,
                unit_price='4.00',
                closes_at=timezone.now() + timedelta(days=7),
            )
            GroupBuyEntry.objects.create(
                group_buy=group_buy,
                user=user,
                variation=variation,
                quantity=2,
            )

        with self.assertNumQueries(7):
            response = self.client.get(reverse('home:product_browse'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Browse item 0')

    def test_keyword_search_matches_each_word_and_ranks_name(self):
        bags = Category.objects.create(name='Bags', parent=self.category)
        exact = Product.objects.create(
            category=bags,
            name='Laptop Bag',
            description='Padded sleeve',
            is_active=True,
        )
        split = Product.objects.create(
            category=bags,
            name='Laptop Shoulder Bag',
            description='Fits a 15 inch laptop',
            is_active=True,
        )
        description_only = Product.objects.create(
            category=self.category,
            name='Travel Organiser',
            description='Use it as a laptop bag in a backpack',
            is_active=True,
        )
        Product.objects.create(
            category=bags,
            name='Canvas Tote',
            description='Everyday bag',
            is_active=True,
        )

        response = self.client.get(reverse('home:product_browse'), {'q': 'laptop bag'})

        self.assertEqual(response.status_code, 200)
        names = [product.name for product in response.context['products']]
        self.assertEqual(names, [exact.name, split.name, description_only.name])

        with self.assertNumQueries(7):
            self.client.get(reverse('home:product_browse'), {'q': 'bag for laptop'})


@override_settings(DEBUG=True, FRIENDLY_ERRORS=True)
class FriendlyErrorPageTests(TestCase):
    def test_unknown_url_shows_friendly_404(self):
        response = self.client.get('/tickets/')

        self.assertContains(response, 'This page does not exist', status_code=404)
        self.assertContains(response, 'Back to homepage', status_code=404)
        self.assertNotContains(response, 'Django tried these URL patterns', status_code=404)

    def test_unknown_url_includes_requested_path(self):
        response = self.client.get('/some/missing/path/')

        self.assertContains(response, '/some/missing/path/', status_code=404)
