from django.urls import path

from . import views

app_name = 'users'

urlpatterns = [
    path('signup/', views.signup_view, name='signup'),
    path('signin/', views.signin_view, name='signin'),
    path('password-reset/', views.AccountPasswordResetView.as_view(), name='password_reset'),
    path(
        'password-reset/done/',
        views.AccountPasswordResetDoneView.as_view(),
        name='password_reset_done',
    ),
    path(
        'reset/<uidb64>/<token>/',
        views.AccountPasswordResetConfirmView.as_view(),
        name='password_reset_confirm',
    ),
    path(
        'reset/complete/',
        views.AccountPasswordResetCompleteView.as_view(),
        name='password_reset_complete',
    ),
    path(
        'password-change/',
        views.AccountPasswordChangeView.as_view(),
        name='password_change',
    ),
    path(
        'password-change/done/',
        views.AccountPasswordChangeDoneView.as_view(),
        name='password_change_done',
    ),
    path('signout/', views.signout_view, name='signout'),
    path('auth/google/', views.google_auth_view, name='google_auth'),
    path('complete-profile/', views.complete_profile_view, name='complete_profile'),
    path('profile/', views.profile_view, name='profile'),
    path('security/2fa/', views.two_factor_settings_view, name='two_factor_settings'),
    path('signin/verify-2fa/', views.two_factor_verify_view, name='two_factor_verify'),
    path('preferences/categories/', views.category_preferences_view, name='category_preferences'),
]
