from django import forms
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.forms import inlineformset_factory

from .category_utils import build_category_tree
from .address import Address
from .fulfillment import Fulfillment
from .group_buy import GroupBuy, GroupBuyEntry
from .import_batch import ImportBatch
from .refund import Refund
from .supplier import Supplier
from .models import Category, Product
from .product_attribute import ProductAttribute
from .product_file import ProductFile
from .product_variation import ProductOption, ProductOptionValue, ProductVariation


class CategoryForm(forms.ModelForm):
    parent = forms.ModelChoiceField(
        queryset=Category.objects.none(),
        required=False,
        empty_label='— Top-level category —',
        widget=forms.Select(attrs={'class': 'form-input form-select'}),
    )

    class Meta:
        model = Category
        fields = ('parent', 'name', 'description', 'is_active')
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'e.g. Consumer Electronics',
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-input form-textarea',
                'placeholder': 'Optional description for this category',
                'rows': 4,
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-checkbox',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        categories = list(Category.objects.select_related('parent').all())
        category_tree = build_category_tree(categories)
        self.fields['parent'].queryset = Category.objects.filter(
            pk__in=[category.id for category, _ in category_tree]
        )
        self.fields['parent'].choices = [('', '— Top-level category —')] + [
            (category.id, f"{'— ' * depth}{category.name}")
            for category, depth in category_tree
        ]
        self.fields['parent'].label = 'Parent category'
        self.fields['name'].label = 'Category name'
        self.fields['description'].label = 'Description'
        self.fields['is_active'].label = 'Active (visible on the platform)'

    def clean(self):
        cleaned = super().clean()
        parent = cleaned.get('parent')
        name = cleaned.get('name')

        if parent and name:
            duplicate = Category.objects.filter(parent=parent, name__iexact=name)
            if self.instance.pk:
                duplicate = duplicate.exclude(pk=self.instance.pk)
            if duplicate.exists():
                self.add_error(
                    'name',
                    f'A subcategory named "{name}" already exists under {parent.name}.',
                )

        return cleaned


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ('category', 'supplier', 'name', 'description', 'is_active')
        widgets = {
            'category': forms.Select(attrs={'class': 'form-input form-select'}),
            'supplier': forms.Select(attrs={'class': 'form-input form-select'}),
            'name': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'e.g. Wireless Earbuds Pro',
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-input form-textarea',
                'placeholder': 'Describe the product for buyers',
                'rows': 5,
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-checkbox',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        categories = list(Category.objects.filter(is_active=True).select_related('parent'))
        category_tree = build_category_tree(categories)
        self.fields['category'].queryset = Category.objects.filter(
            pk__in=[category.id for category, _ in category_tree]
        )
        self.fields['category'].choices = [
            (category.id, f"{'— ' * depth}{category.get_breadcrumb()}")
            for category, depth in category_tree
        ]
        self.fields['category'].label = 'Category'
        self.fields['supplier'].queryset = Supplier.objects.filter(is_active=True).order_by('name')
        self.fields['supplier'].label = 'Supplier'
        self.fields['supplier'].empty_label = '— Select supplier —'
        self.fields['name'].label = 'Product name'
        self.fields['description'].label = 'Description'
        self.fields['is_active'].label = 'Active (visible on the platform)'


class ProductFileForm(forms.ModelForm):
    class Meta:
        model = ProductFile
        fields = ('file', 'media_type', 'caption', 'sort_order', 'is_primary')
        widgets = {
            'file': forms.ClearableFileInput(attrs={
                'class': 'form-input form-file',
                'accept': 'image/*,video/*',
            }),
            'media_type': forms.Select(attrs={'class': 'form-input form-select'}),
            'caption': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Optional caption',
            }),
            'sort_order': forms.NumberInput(attrs={
                'class': 'form-input',
                'min': 0,
            }),
            'is_primary': forms.CheckboxInput(attrs={
                'class': 'form-checkbox',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['file'].label = 'Image or video'
        self.fields['media_type'].label = 'Media type'
        self.fields['media_type'].required = False
        self.fields['media_type'].help_text = 'Leave blank to auto-detect from the file.'
        self.fields['caption'].label = 'Caption'
        self.fields['sort_order'].label = 'Sort order'
        self.fields['is_primary'].label = 'Primary media'

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('DELETE'):
            return cleaned
        if not cleaned.get('file') and not self.instance.pk:
            return cleaned
        if not cleaned.get('file'):
            self.add_error('file', 'Please choose a file to upload.')
        return cleaned


class BaseProductFileFormSet(forms.BaseInlineFormSet):
    def get_queryset(self):
        return super().get_queryset().filter(variation__isnull=True)


ProductFileFormSet = inlineformset_factory(
    Product,
    ProductFile,
    form=ProductFileForm,
    formset=BaseProductFileFormSet,
    extra=2,
    can_delete=True,
)


class ProductVariationFileForm(forms.ModelForm):
    class Meta:
        model = ProductFile
        fields = ('file', 'media_type', 'caption', 'sort_order', 'is_primary')
        widgets = {
            'file': forms.ClearableFileInput(attrs={
                'class': 'form-input form-file',
                'accept': 'image/*,video/*',
            }),
            'media_type': forms.Select(attrs={'class': 'form-input form-select'}),
            'caption': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Optional caption',
            }),
            'sort_order': forms.NumberInput(attrs={
                'class': 'form-input',
                'min': 0,
            }),
            'is_primary': forms.CheckboxInput(attrs={
                'class': 'form-checkbox',
            }),
        }

    def __init__(self, *args, product=None, variation=None, **kwargs):
        self.product = product
        self.variation = variation
        super().__init__(*args, **kwargs)
        self.fields['file'].label = 'Image or video'
        self.fields['media_type'].label = 'Media type'
        self.fields['media_type'].required = False
        self.fields['caption'].label = 'Caption'
        self.fields['sort_order'].label = 'Sort order'
        self.fields['is_primary'].label = 'Primary media'

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('DELETE'):
            return cleaned
        if not cleaned.get('file') and not self.instance.pk:
            return cleaned
        if not cleaned.get('file'):
            self.add_error('file', 'Please choose a file to upload.')
        return cleaned

    def save(self, commit=True):
        product_file = super().save(commit=False)
        product_file.product = self.product
        product_file.variation = self.variation
        if commit:
            product_file.save()
        return product_file


class BaseProductVariationFileFormSet(forms.BaseModelFormSet):
    def __init__(self, *args, product=None, variation=None, **kwargs):
        self.product = product
        self.variation = variation
        super().__init__(*args, **kwargs)

    def _construct_form(self, i, **kwargs):
        kwargs['product'] = self.product
        kwargs['variation'] = self.variation
        return super()._construct_form(i, **kwargs)


def get_variation_file_formset(variation, data=None):
    FormSet = forms.modelformset_factory(
        ProductFile,
        form=ProductVariationFileForm,
        formset=BaseProductVariationFileFormSet,
        extra=1,
        can_delete=True,
    )
    queryset = ProductFile.objects.filter(variation=variation)
    if data is not None:
        return FormSet(data, queryset=queryset, product=variation.product, variation=variation)
    return FormSet(queryset=queryset, product=variation.product, variation=variation)


class ProductAttributeForm(forms.ModelForm):
    class Meta:
        model = ProductAttribute
        fields = ('variation', 'title', 'description', 'sort_order')
        widgets = {
            'variation': forms.Select(attrs={'class': 'form-input form-select'}),
            'title': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'e.g. Material, Battery Life',
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-input form-textarea',
                'placeholder': 'Attribute value or details',
                'rows': 3,
            }),
            'sort_order': forms.NumberInput(attrs={
                'class': 'form-input',
                'min': 0,
            }),
        }

    def __init__(self, *args, product=None, **kwargs):
        self.product = product
        super().__init__(*args, **kwargs)
        self.fields['variation'].required = False
        self.fields['variation'].empty_label = '— Product-level attribute —'
        self.fields['variation'].label = 'Applies to'
        self.fields['title'].label = 'Title'
        self.fields['description'].label = 'Description'
        self.fields['sort_order'].label = 'Sort order'
        if product:
            self.fields['variation'].queryset = product.variations.filter(is_active=True)

    def clean(self):
        cleaned = super().clean()
        variation = cleaned.get('variation')
        title = cleaned.get('title')
        if not self.product or not title:
            return cleaned

        duplicate = ProductAttribute.objects.filter(product=self.product, title__iexact=title)
        if variation:
            duplicate = duplicate.filter(variation=variation)
        else:
            duplicate = duplicate.filter(variation__isnull=True)
        if self.instance.pk:
            duplicate = duplicate.exclude(pk=self.instance.pk)
        if duplicate.exists():
            scope = variation.sku if variation else 'this product'
            self.add_error('title', f'An attribute titled "{title}" already exists for {scope}.')
        return cleaned

    def save(self, commit=True):
        attribute = super().save(commit=False)
        attribute.product = self.product
        if commit:
            attribute.save()
        return attribute


class ProductOptionForm(forms.ModelForm):
    class Meta:
        model = ProductOption
        fields = ('name', 'sort_order')
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'e.g. Color, Size, Storage',
            }),
            'sort_order': forms.NumberInput(attrs={
                'class': 'form-input',
                'min': 0,
            }),
        }

    def __init__(self, *args, product=None, **kwargs):
        self.product = product
        super().__init__(*args, **kwargs)
        self.fields['name'].label = 'Option name'
        self.fields['sort_order'].label = 'Sort order'

    def clean_name(self):
        name = self.cleaned_data.get('name')
        if self.product and name:
            duplicate = ProductOption.objects.filter(product=self.product, name__iexact=name)
            if self.instance.pk:
                duplicate = duplicate.exclude(pk=self.instance.pk)
            if duplicate.exists():
                raise forms.ValidationError(
                    f'An option named "{name}" already exists for this product.'
                )
        return name

    def save(self, commit=True):
        option = super().save(commit=False)
        if self.product:
            option.product = self.product
        if commit:
            option.save()
        return option


class ProductOptionValueForm(forms.ModelForm):
    class Meta:
        model = ProductOptionValue
        fields = ('value', 'sort_order')
        widgets = {
            'value': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'e.g. Red, XL, 128GB',
            }),
            'sort_order': forms.NumberInput(attrs={
                'class': 'form-input',
                'min': 0,
            }),
        }

    def __init__(self, *args, option=None, **kwargs):
        self.option = option
        super().__init__(*args, **kwargs)
        self.fields['value'].label = 'Value'
        self.fields['sort_order'].label = 'Sort order'

    def clean_value(self):
        value = self.cleaned_data.get('value')
        if self.option and value:
            duplicate = ProductOptionValue.objects.filter(option=self.option, value__iexact=value)
            if self.instance.pk:
                duplicate = duplicate.exclude(pk=self.instance.pk)
            if duplicate.exists():
                raise forms.ValidationError(
                    f'"{value}" already exists for {self.option.name}.'
                )
        return value

    def save(self, commit=True):
        option_value = super().save(commit=False)
        if self.option:
            option_value.option = self.option
        if commit:
            option_value.save()
        return option_value


class ProductVariationForm(forms.ModelForm):
    class Meta:
        model = ProductVariation
        fields = ('sku', 'price', 'is_active')
        widgets = {
            'sku': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'e.g. EARBUDS-BLK-PRO',
            }),
            'price': forms.NumberInput(attrs={
                'class': 'form-input',
                'min': 0,
                'step': '0.01',
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-checkbox',
            }),
        }

    def __init__(self, *args, product=None, **kwargs):
        self.product = product
        super().__init__(*args, **kwargs)
        self.fields['sku'].label = 'SKU'
        self.fields['price'].label = 'Unit price (USD)'
        self.fields['is_active'].label = 'Active'

        if product:
            for option in product.options.prefetch_related('values').all():
                self.fields[f'option_{option.pk}'] = forms.ModelChoiceField(
                    queryset=option.values.all(),
                    label=option.name,
                    widget=forms.Select(attrs={'class': 'form-input form-select'}),
                    required=True,
                )

    def clean(self):
        cleaned = super().clean()
        if not self.product:
            return cleaned

        selected_values = []
        for option in self.product.options.all():
            field_name = f'option_{option.pk}'
            option_value = cleaned.get(field_name)
            if not option_value:
                self.add_error(field_name, f'Select a value for {option.name}.')
            else:
                selected_values.append(option_value)

        if len(selected_values) != self.product.options.count():
            return cleaned

        if self.product.options.exists() and not selected_values:
            raise forms.ValidationError('Add product options before creating variations.')

        selected_ids = {value.pk for value in selected_values}
        for variation in self.product.variations.prefetch_related('option_values'):
            if self.instance.pk and variation.pk == self.instance.pk:
                continue
            other_ids = set(variation.option_values.values_list('id', flat=True))
            if other_ids == selected_ids:
                raise forms.ValidationError('A variation with this option combination already exists.')

        cleaned['selected_values'] = selected_values
        return cleaned

    def save(self, commit=True):
        variation = super().save(commit=False)
        if self.product:
            variation.product = self.product
        if commit:
            variation.save()
            selected_values = self.cleaned_data.get('selected_values', [])
            if selected_values:
                variation.option_values.set(selected_values)
                variation.validate()
        return variation


class JoinGroupBuyLineForm(forms.ModelForm):
    class Meta:
        model = GroupBuyEntry
        fields = ('variation', 'quantity')
        widgets = {
            'quantity': forms.NumberInput(attrs={
                'class': 'form-input',
                'min': 1,
                'step': 1,
                'placeholder': 'Qty',
            }),
            'variation': forms.Select(attrs={'class': 'form-input form-select'}),
        }

    def __init__(self, *args, group_buy=None, user=None, excluded_variation_ids=None, **kwargs):
        self.group_buy = group_buy
        self.user = user
        self.excluded_variation_ids = set(excluded_variation_ids or [])
        super().__init__(*args, **kwargs)

        if group_buy:
            variations = group_buy.product.variations.filter(is_active=True)
            if variations.exists():
                self._all_variations = variations
                self._set_variation_queryset()
                self.fields['variation'].required = False
                self.fields['variation'].empty_label = 'Select variation'
                self.fields['variation'].label = 'Variation'
            else:
                self.fields.pop('variation')

        self.fields['quantity'].label = 'Qty'
        self.fields['quantity'].required = False

    def _set_variation_queryset(self):
        if 'variation' not in self.fields:
            return
        variations = self._all_variations
        current_variation_id = self._current_variation_id()
        allowed_ids = set(variations.values_list('pk', flat=True))
        allowed_ids -= self.excluded_variation_ids
        if current_variation_id:
            allowed_ids.add(current_variation_id)
        self.fields['variation'].queryset = variations.filter(pk__in=allowed_ids).order_by('sku')

    def apply_variation_exclusions(self, excluded_variation_ids):
        self.excluded_variation_ids = set(excluded_variation_ids or [])
        self._set_variation_queryset()

    def _current_variation_id(self):
        if not self.is_bound and self.instance.pk and self.instance.variation_id:
            return self.instance.variation_id
        if self.is_bound:
            raw = self.data.get(self.add_prefix('variation'), '')
            if raw:
                try:
                    return int(raw)
                except (TypeError, ValueError):
                    return None
        return None

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('DELETE'):
            return cleaned

        quantity = cleaned.get('quantity')
        variation = cleaned.get('variation')
        has_variation_field = 'variation' in self.fields

        if not quantity and not self.instance.pk:
            return cleaned

        if not quantity:
            if self.instance.pk:
                raise ValidationError('Quantity must be at least 1, or remove this line.')
            return cleaned

        if quantity < 1:
            raise ValidationError({'quantity': 'Quantity must be at least 1.'})

        if has_variation_field and not variation:
            raise ValidationError({'variation': 'Select a variation for this line.'})

        if self.group_buy and not self.group_buy.is_joinable and not self.instance.pk:
            raise ValidationError('This group buy is no longer accepting pledges.')

        return cleaned

    def save(self, commit=True):
        entry = super().save(commit=False)
        entry.group_buy = self.group_buy
        entry.user = self.user
        if commit:
            entry.save()
        return entry


class BaseJoinGroupBuyFormSet(forms.BaseModelFormSet):
    def __init__(self, *args, group_buy=None, user=None, **kwargs):
        self.group_buy = group_buy
        self.user = user
        super().__init__(*args, **kwargs)
        self._apply_variation_exclusions()

    def _construct_form(self, i, **kwargs):
        kwargs['group_buy'] = self.group_buy
        kwargs['user'] = self.user
        return super()._construct_form(i, **kwargs)

    def _variation_id_for_form(self, form):
        if 'variation' not in form.fields:
            return None
        if form.is_bound:
            raw = form.data.get(form.add_prefix('variation'), '')
            if raw:
                try:
                    return int(raw)
                except (TypeError, ValueError):
                    return None
            return None
        if form.instance.pk and form.instance.variation_id:
            return form.instance.variation_id
        return None

    def _apply_variation_exclusions(self):
        if not self.forms:
            return

        selected_ids = [self._variation_id_for_form(form) for form in self.forms]
        for index, form in enumerate(self.forms):
            if 'variation' not in form.fields:
                continue
            excluded = {
                variation_id
                for row_index, variation_id in enumerate(selected_ids)
                if row_index != index and variation_id
            }
            form.apply_variation_exclusions(excluded)

    def clean(self):
        super().clean()
        if any(form.errors for form in self.forms):
            return

        active_forms = [
            form for form in self.forms
            if form.cleaned_data
            and not form.cleaned_data.get('DELETE')
            and form.cleaned_data.get('quantity')
        ]
        if not active_forms:
            raise ValidationError('Add at least one variation and quantity to your pledge.')

        if not self.group_buy.is_joinable:
            new_lines = [form for form in active_forms if not form.instance.pk]
            if new_lines:
                raise ValidationError('This group buy is no longer accepting new pledges.')

        seen_variations = []
        for form in active_forms:
            variation = form.cleaned_data.get('variation')
            key = variation.pk if variation else None
            if key in seen_variations:
                label = variation.display_name if variation else 'Standard'
                raise ValidationError(f'Duplicate line for "{label}". Combine quantities into one row.')
            seen_variations.append(key)

    def save(self):
        saved_entries = []
        for form in self.forms:
            if not form.cleaned_data:
                continue
            if form.cleaned_data.get('DELETE'):
                if form.instance.pk:
                    form.instance.delete()
                continue
            if not form.cleaned_data.get('quantity'):
                continue
            saved_entries.append(form.save())
        return saved_entries


JoinGroupBuyFormSet = forms.modelformset_factory(
    GroupBuyEntry,
    form=JoinGroupBuyLineForm,
    formset=BaseJoinGroupBuyFormSet,
    extra=0,
    can_delete=True,
)


def get_pledge_formset(group_buy, user, data=None):
    has_variations = group_buy.product.variations.filter(is_active=True).exists()
    queryset = GroupBuyEntry.objects.filter(group_buy=group_buy, user=user)
    extra = 2 if has_variations else (0 if queryset.exists() else 1)

    FormSet = forms.modelformset_factory(
        GroupBuyEntry,
        form=JoinGroupBuyLineForm,
        formset=BaseJoinGroupBuyFormSet,
        extra=extra,
        can_delete=True,
    )

    if data is not None:
        return FormSet(data, queryset=queryset, group_buy=group_buy, user=user)
    return FormSet(queryset=queryset, group_buy=group_buy, user=user)


DATETIME_LOCAL_FORMAT = '%Y-%m-%dT%H:%M'


class GroupBuyForm(forms.ModelForm):
    class Meta:
        model = GroupBuy
        fields = ('product', 'moq', 'unit_price', 'status', 'closes_at')
        widgets = {
            'product': forms.Select(attrs={'class': 'form-input form-select'}),
            'moq': forms.NumberInput(attrs={
                'class': 'form-input',
                'min': 1,
                'placeholder': 'e.g. 100',
            }),
            'unit_price': forms.NumberInput(attrs={
                'class': 'form-input',
                'step': '0.01',
                'min': '0.01',
                'placeholder': 'e.g. 12.99',
            }),
            'status': forms.Select(attrs={'class': 'form-input form-select'}),
            'closes_at': forms.DateTimeInput(
                attrs={'class': 'form-input', 'type': 'datetime-local'},
                format=DATETIME_LOCAL_FORMAT,
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['product'].queryset = Product.objects.filter(
            is_active=True,
        ).select_related('category').order_by('name')
        self.fields['product'].label = 'Product'
        self.fields['moq'].label = 'Minimum order quantity (MOQ)'
        self.fields['unit_price'].label = 'Bulk unit price (USD)'
        self.fields['status'].label = 'Status'
        self.fields['closes_at'].label = 'Closes at'
        self.fields['closes_at'].input_formats = [
            DATETIME_LOCAL_FORMAT,
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%d %H:%M',
        ]
        if self.instance.pk:
            self.fields['product'].disabled = True

    def clean_product(self):
        if self.instance.pk:
            return self.instance.product
        return self.cleaned_data.get('product')

    def clean_moq(self):
        moq = self.cleaned_data.get('moq')
        if moq is not None and moq < 1:
            raise ValidationError('MOQ must be at least 1.')
        return moq


class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = (
            'name', 'contact_name', 'email', 'phone', 'wechat_id',
            'alibaba_url', 'country', 'notes', 'is_active',
        )
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Factory or trading company name'}),
            'contact_name': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Sales contact'}),
            'email': forms.EmailInput(attrs={'class': 'form-input'}),
            'phone': forms.TextInput(attrs={'class': 'form-input', 'placeholder': '+86 ...'}),
            'wechat_id': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'WeChat ID'}),
            'alibaba_url': forms.URLInput(attrs={'class': 'form-input', 'placeholder': 'https://...'}),
            'country': forms.TextInput(attrs={'class': 'form-input'}),
            'notes': forms.Textarea(attrs={'class': 'form-input form-textarea', 'rows': 4}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].label = 'Supplier name'
        self.fields['contact_name'].label = 'Contact person'
        self.fields['wechat_id'].label = 'WeChat ID'
        self.fields['alibaba_url'].label = 'Alibaba / storefront URL'
        self.fields['is_active'].label = 'Active'


def _active_supplier_queryset():
    return Supplier.objects.filter(is_active=True).order_by('name')


class ImportBatchForm(forms.ModelForm):
    class Meta:
        model = ImportBatch
        fields = ('supplier', 'status', 'supplier_reference', 'estimated_arrival', 'notes')
        widgets = {
            'supplier': forms.Select(attrs={'class': 'form-input form-select'}),
            'status': forms.Select(attrs={'class': 'form-input form-select'}),
            'supplier_reference': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'e.g. SUP-2026-001',
            }),
            'estimated_arrival': forms.DateInput(attrs={
                'class': 'form-input',
                'type': 'date',
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-input form-textarea',
                'rows': 3,
                'placeholder': 'Internal notes for this import run',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['supplier'].queryset = _active_supplier_queryset()
        self.fields['supplier'].label = 'Supplier'
        self.fields['supplier'].empty_label = '— Select supplier —'
        self.fields['status'].label = 'Import status'
        self.fields['supplier_reference'].label = 'Factory order reference'
        self.fields['estimated_arrival'].label = 'Estimated arrival'
        self.fields['notes'].label = 'Notes'


class ImportBatchCreateForm(forms.Form):
    supplier = forms.ModelChoiceField(
        queryset=Supplier.objects.none(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-input form-select'}),
    )
    supplier_reference = forms.CharField(
        required=False,
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': 'e.g. PO-2026-001',
        }),
    )
    estimated_arrival = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-input form-textarea',
            'rows': 3,
        }),
    )

    def __init__(self, *args, **kwargs):
        product_supplier = kwargs.pop('product_supplier', None)
        super().__init__(*args, **kwargs)
        self.fields['supplier'].queryset = _active_supplier_queryset()
        self.fields['supplier'].label = 'Supplier'
        self.fields['supplier'].empty_label = '— Select supplier —'
        self.fields['supplier_reference'].label = 'Factory order reference'
        self.fields['estimated_arrival'].label = 'Estimated arrival'
        self.fields['notes'].label = 'Notes'
        if product_supplier and not self.initial.get('supplier'):
            self.initial['supplier'] = product_supplier.pk


class RefundCreateForm(forms.Form):
    refund_type = forms.ChoiceField(
        choices=Refund.RefundType.choices,
        widget=forms.Select(attrs={'class': 'form-input form-select'}),
    )
    amount = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal('0.01'),
        widget=forms.NumberInput(attrs={
            'class': 'form-input',
            'step': '0.01',
            'min': '0.01',
        }),
    )
    reason = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': 'e.g. Group buy cancelled, import failed',
        }),
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-input form-textarea',
            'rows': 2,
        }),
    )

    def __init__(self, *args, **kwargs):
        self.refundable_amount = kwargs.pop('refundable_amount', Decimal('0.00'))
        super().__init__(*args, **kwargs)
        self.fields['refund_type'].label = 'Refund type'
        self.fields['amount'].label = 'Amount (USD)'
        self.fields['reason'].label = 'Reason'
        self.fields['notes'].label = 'Internal notes'

    def clean(self):
        cleaned = super().clean()
        amount = cleaned.get('amount')
        refund_type = cleaned.get('refund_type')
        if amount is None or refund_type is None:
            return cleaned
        if refund_type == Refund.RefundType.FULL:
            cleaned['amount'] = self.refundable_amount
        elif amount > self.refundable_amount:
            self.add_error('amount', f'Cannot exceed ${self.refundable_amount} refundable.')
        return cleaned


class AddressForm(forms.ModelForm):
    class Meta:
        model = Address
        fields = (
            'label', 'recipient_name', 'phone', 'county', 'area',
            'street_address', 'delivery_notes', 'is_default',
        )
        widgets = {
            'label': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Home, Office, etc.',
            }),
            'recipient_name': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Full name for delivery',
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': '0712345678',
            }),
            'county': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'e.g. Nairobi',
            }),
            'area': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'e.g. Westlands',
            }),
            'street_address': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Building, street, landmarks',
            }),
            'delivery_notes': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Optional gate code or directions',
            }),
            'is_default': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        self.fields['label'].label = 'Label'
        self.fields['recipient_name'].label = 'Recipient name'
        self.fields['phone'].label = 'Phone number'
        self.fields['county'].label = 'County'
        self.fields['area'].label = 'Area / estate'
        self.fields['street_address'].label = 'Street address'
        self.fields['delivery_notes'].label = 'Delivery notes'
        self.fields['is_default'].label = 'Set as default address'

    def save(self, commit=True):
        address = super().save(commit=False)
        if self.user:
            address.user = self.user
        if commit:
            address.save()
            self.save_m2m()
        return address


class FulfillmentForm(forms.ModelForm):
    class Meta:
        model = Fulfillment
        fields = ('status', 'tracking_reference', 'notes')
        widgets = {
            'status': forms.Select(attrs={'class': 'form-input form-select'}),
            'tracking_reference': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Courier tracking ID',
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-input form-textarea',
                'rows': 2,
            }),
        }

    def save(self, commit=True):
        fulfillment = super().save(commit=False)
        if commit:
            from core.fulfillment_services import update_fulfillment
            update_fulfillment(
                fulfillment,
                status=fulfillment.status,
                tracking_reference=fulfillment.tracking_reference,
                notes=fulfillment.notes,
            )
        return fulfillment

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['status'].label = 'Delivery status'
        self.fields['tracking_reference'].label = 'Tracking reference'
        self.fields['notes'].label = 'Internal notes'
