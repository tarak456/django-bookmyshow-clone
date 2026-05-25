from django.urls import path
from . import views

urlpatterns = [
    path('', views.movie_list, name='movie_list'),
    path('<int:movie_id>/theaters', views.theater_list, name='theater_list'),

    # Phase 1 — seat map
    path('theater/<int:theater_id>/seats/book/', views.book_seats, name='book_seats'),

    # Phase 2 — atomic 2-min reservation
    path('theater/<int:theater_id>/seats/reserve/', views.reserve_seats, name='reserve_seats'),

    # Phase 3 — payment flow
    path('theater/<int:theater_id>/seats/confirm/', views.confirm_booking, name='confirm_booking'),
    path('theater/<int:theater_id>/payment/create/', views.create_payment, name='create_payment'),
    path('theater/<int:theater_id>/payment/callback/', views.payment_callback, name='payment_callback'),
    path('theater/<int:theater_id>/seats/release/', views.release_seats, name='release_seats'),

    # Payment results
    path('payment/success/', views.payment_success, name='payment_success'),
    path('payment/failed/', views.payment_failed, name='payment_failed'),

    # Razorpay webhook (no login required — verified by HMAC signature)
    path('webhooks/razorpay/', views.payment_webhook, name='payment_webhook'),

    # Task 4: Admin analytics dashboard (staff only)
    path('admin/analytics/', views.analytics_dashboard, name='analytics_dashboard'),
    path('admin/analytics/api/', views.analytics_api, name='analytics_api'),
]
