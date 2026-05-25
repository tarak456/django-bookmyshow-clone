from django.contrib import admin
from .models import Genre, Language, Movie, Theater, Seat, Booking, SeatReservation, Payment


@admin.register(Genre)
class GenreAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Language)
class LanguageAdmin(admin.ModelAdmin):
    list_display = ['name', 'code']


@admin.register(Movie)
class MovieAdmin(admin.ModelAdmin):
    list_display  = ['name', 'rating', 'trailer_url']
    filter_horizontal = ['genres', 'languages']
    search_fields = ['name', 'cast']
    list_filter   = ['genres', 'languages']


@admin.register(Theater)
class TheaterAdmin(admin.ModelAdmin):
    list_display = ['name', 'movie', 'time']
    list_select_related = ['movie']


@admin.register(Seat)
class SeatAdmin(admin.ModelAdmin):
    list_display = ['seat_number', 'theater', 'is_booked']
    list_filter  = ['is_booked']
    list_select_related = ['theater']


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ['user', 'movie', 'theater', 'seat', 'booked_at']
    list_select_related = ['user', 'movie', 'theater', 'seat']
    readonly_fields = ['booked_at']


@admin.register(SeatReservation)
class SeatReservationAdmin(admin.ModelAdmin):
    list_display = ['seat', 'user', 'theater', 'expires_at']
    list_select_related = ['seat', 'user', 'theater']


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display  = ['booking_ref', 'user', 'status', 'amount_inr_display', 'created_at']
    list_filter   = ['status']
    search_fields = ['razorpay_order_id', 'razorpay_payment_id']
    readonly_fields = ['booking_ref', 'created_at', 'updated_at', 'webhook_received_at']
    list_select_related = ['user', 'theater__movie']

    @admin.display(description='Amount (INR)')
    def amount_inr_display(self, obj):
        return f'₹{obj.amount_paise // 100}'
