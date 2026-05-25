
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.contrib.auth import login, authenticate
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
 
from .forms import UserRegisterForm, UserUpdateForm
from movies.models import Movie, Booking
 
 
def home(request):
    try:
        movies = Movie.objects.prefetch_related('genres', 'languages').order_by('-created_at')[:8]
    except Exception as e:
        # Database not ready or table doesn't exist yet
        movies = []
    return render(request, 'home.html', {'movies': movies})
 
 
def register(request):
    if request.method == 'POST':
        form = UserRegisterForm(request.POST)
        if form.is_valid():
            form.save()
            user = authenticate(
                username=form.cleaned_data['username'],
                password=form.cleaned_data['password1'],
            )
            login(request, user)
            return redirect('profile')
    else:
        form = UserRegisterForm()
    return render(request, 'users/register.html', {'form': form})
 
 
def login_view(request):
    next_url = request.GET.get('next', '/')
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            login(request, form.get_user())
            return redirect(request.POST.get('next', next_url))
    else:
        form = AuthenticationForm()
    return render(request, 'users/login.html', {'form': form, 'next': next_url})
 
 
@login_required
def profile(request):
    from movies.models import Payment
    from django.db.models import Sum
    try:
        bookings = (
            Booking.objects.filter(user=request.user)
            .select_related('movie', 'theater', 'seat')
            .order_by('-booked_at')
        )
        # Calculate total spent from confirmed payments at DB level
        total_spent_paise = (
            Payment.objects.filter(user=request.user, status='paid')
            .aggregate(total=Sum('amount_paise'))['total'] or 0
        )
    except Exception as e:
        bookings = []
        total_spent_paise = 0
    
    if request.method == 'POST':
        u_form = UserUpdateForm(request.POST, instance=request.user)
        if u_form.is_valid():
            u_form.save()
            return redirect('profile')
    else:
        u_form = UserUpdateForm(instance=request.user)
    return render(request, 'users/profile.html', {
        'u_form': u_form,
        'bookings': bookings,
        'total_spent': total_spent_paise / 100,
    })
 
 
@login_required
def reset_password(request):
    if request.method == 'POST':
        form = PasswordChangeForm(user=request.user, data=request.POST)
        if form.is_valid():
            form.save()
            return redirect('login')
    else:
        form = PasswordChangeForm(user=request.user)
    return render(request, 'users/reset_password.html', {'form': form})