from .models import UserSettings
from .utils import money


def budget(request):
    """Variables communes à toutes les pages PyBlade : taux du jour et navigation."""
    context = {"app_name": "Albatros Budget", "nav_rate": ""}
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        context["nav_rate"] = money(UserSettings.for_user(user).usd_rate, "CDF", 2)
        context["user_initial"] = (user.get_full_name() or user.get_username())[:1].upper()
        context["user_display"] = user.get_full_name() or user.get_username()
    return context
