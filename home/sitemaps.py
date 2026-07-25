from django.conf import settings
from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from core.models import Category, Product


class SiteAwareSitemap(Sitemap):
    protocol = settings.SITE_PROTOCOL

    def get_domain(self, site=None):
        return settings.SITE_DOMAIN


class StaticPageSitemap(SiteAwareSitemap):
    changefreq = 'daily'
    priority = 1.0

    def items(self):
        return ['home:landing', 'home:product_browse', 'home:privacy_policy']

    def location(self, item):
        return reverse(item)


class ProductSitemap(SiteAwareSitemap):
    changefreq = 'weekly'
    priority = 0.8

    def items(self):
        return Product.objects.filter(is_active=True).order_by('-updated_at')

    def lastmod(self, obj):
        return obj.updated_at


class CategoryBrowseSitemap(SiteAwareSitemap):
    changefreq = 'weekly'
    priority = 0.6

    def items(self):
        return Category.objects.filter(is_active=True).order_by('name')

    def location(self, obj):
        return f"{reverse('home:product_browse')}?category={obj.slug}"
