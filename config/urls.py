"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from core import commerce_views as commerce_views
from core import mpesa_views
from core import views as core_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('home.urls')),
    path('products/<slug:slug>/', core_views.product_detail, name='product_detail'),
    path('cart/', commerce_views.cart_detail, name='cart_detail'),
    path('cart/add/', commerce_views.cart_add, name='cart_add'),
    path('cart/remove/<int:item_id>/', commerce_views.cart_remove, name='cart_remove'),
    path('pledges/', commerce_views.pledge_list, name='pledge_list'),
    path('pledges/<int:group_buy_id>/confirm/', commerce_views.confirm_order_checkout, name='confirm_order_checkout'),
    path('pledges/<int:group_buy_id>/pay/', commerce_views.confirm_order_pay, name='confirm_order_pay'),
    path('payments/<int:payment_id>/pending/', mpesa_views.payment_pending, name='payment_pending'),
    path('payments/<int:payment_id>/status/', mpesa_views.payment_status, name='payment_status'),
    path('payments/mpesa/callback/', mpesa_views.mpesa_callback, name='mpesa_callback'),
    path('orders/', commerce_views.order_list, name='order_list'),
    path('orders/<int:order_id>/', commerce_views.order_detail, name='order_detail'),
    path('addresses/', commerce_views.address_list, name='address_list'),
    path('addresses/create/', commerce_views.address_create, name='address_create'),
    path('addresses/<int:address_id>/edit/', commerce_views.address_edit, name='address_edit'),
    path('addresses/<int:address_id>/delete/', commerce_views.address_delete, name='address_delete'),
    path('addresses/<int:address_id>/default/', commerce_views.address_set_default, name='address_set_default'),
    path('currency/', commerce_views.set_currency, name='set_currency'),
    path('core/', include('core.urls')),
    path('users/', include('users.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
