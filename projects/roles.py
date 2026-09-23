from functools import wraps
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from .models import Account


def user_role(user):
    if not user.is_authenticated:
        return None
    return Account.objects.filter(user=user).values_list('role', flat=True).first()


def role_required(role):
    def decorator(view):
        @login_required
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if user_role(request.user) != role:
                return HttpResponseForbidden('Это действие недоступно для вашего типа пользователя.')
            return view(request, *args, **kwargs)
        return wrapped
    return decorator


def role_context(request):
    role = user_role(request.user)
    return {'is_business': role == Account.Role.BUSINESS, 'is_student': role == Account.Role.STUDENT, 'account_role_label': dict(Account.Role.choices).get(role, 'Тип не назначен')}
