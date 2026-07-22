from django.urls import path

from . import views

app_name = 'core'

urlpatterns = [
    path('dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('suppliers/', views.supplier_list, name='supplier_list'),
    path('suppliers/create/', views.supplier_create, name='supplier_create'),
    path('suppliers/<int:supplier_id>/edit/', views.supplier_edit, name='supplier_edit'),
    path('categories/', views.category_list, name='category_list'),
    path('categories/create/', views.category_create, name='category_create'),
    path('products/', views.product_list, name='product_list'),
    path('products/create/', views.product_create, name='product_create'),
    path('products/<int:product_id>/options/', views.product_option_list, name='product_option_list'),
    path('products/<int:product_id>/options/create/', views.product_option_create, name='product_option_create'),
    path('options/<int:option_id>/values/', views.product_option_value_list, name='product_option_value_list'),
    path('options/<int:option_id>/values/create/', views.product_option_value_create, name='product_option_value_create'),
    path('products/<int:product_id>/variations/', views.product_variation_list, name='product_variation_list'),
    path('products/<int:product_id>/variations/create/', views.product_variation_create, name='product_variation_create'),
    path('products/<int:product_id>/variations/<int:variation_id>/files/', views.product_variation_files, name='product_variation_files'),
    path('products/<int:product_id>/attributes/', views.product_attribute_list, name='product_attribute_list'),
    path('products/<int:product_id>/attributes/create/', views.product_attribute_create, name='product_attribute_create'),
    path('group-buys/', views.group_buy_list, name='group_buy_list'),
    path('group-buys/create/', views.group_buy_create, name='group_buy_create'),
    path('group-buys/<int:group_buy_id>/', views.group_buy_manage, name='group_buy_manage'),
    path('refunds/', views.refund_list, name='refund_list'),
]
