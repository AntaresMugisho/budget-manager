from django.contrib import admin

from .models import Account, Budget, Category, Transaction, UserSettings


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "type", "currency", "initial_balance", "is_active")
    list_filter = ("type", "currency", "is_active")


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "kind", "color")
    list_filter = ("kind",)


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ("date", "user", "kind", "account", "category", "amount", "currency", "amount_cdf")
    list_filter = ("kind", "currency", "date")
    search_fields = ("description",)
    readonly_fields = ("currency", "exchange_rate", "amount_cdf")


@admin.register(Budget)
class BudgetAdmin(admin.ModelAdmin):
    list_display = ("category", "user", "month", "amount", "currency")


@admin.register(UserSettings)
class UserSettingsAdmin(admin.ModelAdmin):
    list_display = ("user", "usd_rate", "rate_updated_at")
