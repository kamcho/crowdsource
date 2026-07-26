from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError
from phonenumber_field.formfields import PhoneNumberField

from core.models import Category

from .models import User


class SignUpForm(UserCreationForm):
    phone = PhoneNumberField(
        region='KE',
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': 'e.g. 0712345678',
            'type': 'tel',
            'autocomplete': 'tel',
        }),
    )
    first_name = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': 'First name',
            'autocomplete': 'given-name',
        }),
    )
    last_name = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': 'Last name',
            'autocomplete': 'family-name',
        }),
    )

    class Meta:
        model = User
        fields = ('phone', 'first_name', 'last_name', 'password1', 'password2')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['password1'].widget.attrs.update({
            'class': 'form-input',
            'placeholder': 'Create a password',
            'autocomplete': 'new-password',
        })
        self.fields['password2'].widget.attrs.update({
            'class': 'form-input',
            'placeholder': 'Confirm password',
            'autocomplete': 'new-password',
        })
        self.fields['password1'].label = 'Password'
        self.fields['password2'].label = 'Confirm password'

    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        if phone and User.objects.filter(phone=phone).exists():
            raise ValidationError('A user with this phone number already exists.')
        return phone


class SignInForm(forms.Form):
    phone = PhoneNumberField(
        region='KE',
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': 'e.g. 0712345678',
            'type': 'tel',
            'autocomplete': 'tel',
        }),
    )
    password = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(attrs={
            'class': 'form-input',
            'placeholder': 'Enter your password',
            'autocomplete': 'current-password',
        }),
    )


class CompleteProfileForm(forms.Form):
    """Link phone and password after Google sign-in."""

    phone = PhoneNumberField(
        region='KE',
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': 'e.g. 0712345678',
            'type': 'tel',
        }),
    )
    password1 = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(attrs={
            'class': 'form-input',
            'placeholder': 'Create a password',
            'autocomplete': 'new-password',
        }),
    )
    password2 = forms.CharField(
        label='Confirm password',
        widget=forms.PasswordInput(attrs={
            'class': 'form-input',
            'placeholder': 'Confirm password',
            'autocomplete': 'new-password',
        }),
    )

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        if not phone:
            raise ValidationError('Phone number is required.')
        qs = User.objects.filter(phone=phone)
        if self.user:
            qs = qs.exclude(pk=self.user.pk)
        if qs.exists():
            raise ValidationError('This phone number is already registered.')
        return phone

    def clean(self):
        cleaned = super().clean()
        password1 = cleaned.get('password1')
        password2 = cleaned.get('password2')
        if password1 and password2 and password1 != password2:
            self.add_error('password2', 'Passwords do not match.')
        return cleaned


class CategoryPreferencesForm(forms.Form):
    categories = forms.ModelMultipleChoiceField(
        queryset=Category.objects.filter(is_active=True).order_by('name'),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label='Categories you are interested in',
    )

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        if user and user.is_authenticated:
            from core.preference_services import get_explicit_preferred_category_ids

            self.fields['categories'].initial = get_explicit_preferred_category_ids(user)
