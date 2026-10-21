from django import forms
from django.core.exceptions import ValidationError
from phonenumber_field.formfields import PhoneNumberField

from users.models import User

from .models import Tenant, TenantMembership


class TenantForm(forms.ModelForm):
    class Meta:
        model = Tenant
        fields = ('name', 'slug', 'is_active')
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'e.g. Nairobi Wholesale',
            }),
            'slug': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'e.g. nairobi-wholesale',
            }),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
        }

    def clean_is_active(self):
        is_active = self.cleaned_data['is_active']
        if self.instance.pk and self.instance.is_default and not is_active:
            raise ValidationError('The default tenant must remain active.')
        return is_active


class TenantMembershipForm(forms.Form):
    phone = PhoneNumberField(
        region='KE',
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'type': 'tel',
            'placeholder': 'e.g. 0712345678',
            'autocomplete': 'tel',
        }),
        help_text='The user must already have an account.',
    )
    role = forms.ChoiceField(
        choices=(
            (TenantMembership.Role.ADMIN, 'Tenant admin'),
            (TenantMembership.Role.STAFF, 'Staff'),
        ),
        widget=forms.Select(attrs={'class': 'form-input form-select'}),
    )

    def clean_phone(self):
        phone = self.cleaned_data['phone']
        user = User.objects.filter(phone=phone, is_active=True).first()
        if user is None:
            raise ValidationError(
                'No active account was found for this phone number. '
                'Ask the user to sign up first.',
            )
        self.cleaned_data['user'] = user
        return phone
