from django.db import models
from django.utils.text import slugify


class Category(models.Model):
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='children',
    )
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=160, unique=True, blank=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'categories'
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['parent', 'name'],
                name='unique_category_name_per_parent',
            ),
        ]

    def __str__(self):
        return self.get_breadcrumb()

    @property
    def is_root(self):
        return self.parent_id is None

    @property
    def depth(self):
        depth = 0
        node = self.parent
        while node:
            depth += 1
            node = node.parent
        return depth

    def get_ancestors(self):
        ancestors = []
        node = self.parent
        while node:
            ancestors.insert(0, node)
            node = node.parent
        return ancestors

    def get_breadcrumb(self):
        return ' › '.join(category.name for category in self.get_ancestors() + [self])

    def get_indented_name(self):
        if self.depth == 0:
            return self.name
        return f"{'— ' * self.depth}{self.name}"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._generate_unique_slug()
        super().save(*args, **kwargs)

    def _slug_parts(self):
        parts = [slugify(ancestor.name) or 'category' for ancestor in self.get_ancestors()]
        parts.append(slugify(self.name) or 'category')
        return parts

    def _generate_unique_slug(self):
        base_slug = '-'.join(part for part in self._slug_parts() if part)
        slug = base_slug
        counter = 1
        while Category.objects.filter(slug=slug).exclude(pk=self.pk).exists():
            slug = f'{base_slug}-{counter}'
            counter += 1
        return slug


class Product(models.Model):
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name='products',
    )
    supplier = models.ForeignKey(
        'Supplier',
        on_delete=models.PROTECT,
        related_name='products',
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    description = models.TextField(blank=True)
    is_special_class = models.BooleanField(
        default=False,
        help_text='Special goods use a higher air freight rate per kg.',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._generate_unique_slug()
        super().save(*args, **kwargs)

    def _generate_unique_slug(self):
        base_slug = slugify(self.name) or 'product'
        slug = base_slug
        counter = 1
        while Product.objects.filter(slug=slug).exclude(pk=self.pk).exists():
            slug = f'{base_slug}-{counter}'
            counter += 1
        return slug

    @property
    def product_files(self):
        return self.files.filter(variation__isnull=True)

    @property
    def primary_file(self):
        primary = self.product_files.filter(is_primary=True).first()
        if primary:
            return primary
        return self.product_files.first()

    @property
    def primary_image(self):
        primary = self.primary_file
        if primary and primary.is_image:
            return primary
        return self.product_files.filter(media_type=ProductFile.MediaType.IMAGE).first()

    @property
    def product_attributes(self):
        return self.attributes.filter(variation__isnull=True)

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse('product_detail', kwargs={'slug': self.slug})

    @property
    def active_variations(self):
        return self.variations.filter(is_active=True).prefetch_related(
            'option_values__option'
        )

    @property
    def min_price(self):
        from django.db.models import Min
        return self.active_variations.aggregate(min_price=Min('price'))['min_price']

    @property
    def active_group_buy(self):
        cached = getattr(self, 'active_group_buys_list', None)
        if cached is not None:
            return cached[0] if cached else None
        from core.group_buy import GroupBuy
        return self.group_buys.filter(
            status__in=[GroupBuy.Status.OPEN, GroupBuy.Status.MOQ_REACHED],
        ).order_by('-created_at').first()


from core.product_attribute import ProductAttribute  # noqa: E402, F401
from core.product_file import ProductFile  # noqa: E402, F401
from core.product_variation import (  # noqa: E402, F401
    ProductOption,
    ProductOptionValue,
    ProductVariation,
)
from core.group_buy import GroupBuy, GroupBuyEntry  # noqa: E402, F401
from core.cart import Cart, CartItem  # noqa: E402, F401
from core.wishlist import WishlistItem  # noqa: E402, F401
from core.order import Order, OrderItem  # noqa: E402, F401
from core.payment import Payment  # noqa: E402, F401
from core.complaint import Complaint, ComplaintMessage  # noqa: E402, F401
from core.user_preference import UserCategoryPreference  # noqa: E402, F401
from core.user_preference import UserCategoryViewStat, UserProductView  # noqa: E402, F401

