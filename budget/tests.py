from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Account, Budget, Category, Kind, Transaction, UserSettings
from .utils import add_months, first_of_month, money


class UtilsTests(TestCase):
    def test_money_formats_french_style(self):
        self.assertEqual(money(Decimal("1234567.5"), "CDF"), "1 234 568 FC")
        self.assertEqual(money(Decimal("1234.5"), "USD"), "1 234,50 $")

    def test_add_months_wraps_years(self):
        self.assertEqual(add_months(date(2026, 11, 1), 3), date(2027, 2, 1))
        self.assertEqual(add_months(date(2026, 1, 1), -1), date(2025, 12, 1))


class BudgetAppTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user("alice", password="motdepasse-solide-1")
        self.other = User.objects.create_user("bob", password="motdepasse-solide-2")
        self.client.force_login(self.user)
        settings = UserSettings.for_user(self.user)
        settings.usd_rate = Decimal("2800")
        settings.save()
        self.cdf = Account.objects.create(user=self.user, name="Caisse", initial_balance=100_000)
        self.usd = Account.objects.create(user=self.user, name="Banque", currency="USD", initial_balance=100)
        self.food = Category.objects.create(user=self.user, name="Alimentation", kind=Kind.EXPENSE)
        self.salary = Category.objects.create(user=self.user, name="Salaire", kind=Kind.INCOME)

    def post_tx(self, **data):
        payload = {
            "kind": Kind.EXPENSE,
            "date": date.today().isoformat(),
            "account": self.cdf.id,
            "category": self.food.id,
            "amount": "5000",
            "description": "Test",
        }
        payload.update(data)
        return self.client.post(reverse("transaction_create"), payload)

    def test_login_required(self):
        self.client.logout()
        response = self.client.get(reverse("dashboard"))
        self.assertRedirects(response, f"{reverse('login')}?next=/")

    def test_login_page_and_login(self):
        self.client.logout()
        self.assertContains(self.client.get(reverse("login")), "Connexion")
        response = self.client.post(reverse("login"), {"username": "alice", "password": "motdepasse-solide-1"})
        self.assertRedirects(response, reverse("dashboard"))

    def test_usd_transaction_freezes_rate(self):
        self.post_tx(account=self.usd.id, amount="10")
        tx = Transaction.objects.get()
        self.assertEqual(tx.currency, "USD")
        self.assertEqual(tx.amount_cdf, Decimal("28000.00"))

        settings = UserSettings.for_user(self.user)
        settings.usd_rate = Decimal("3000")
        settings.save()
        tx.refresh_from_db()
        self.assertEqual(tx.amount_cdf, Decimal("28000.00"))

    def test_edit_keeps_original_rate(self):
        self.post_tx(account=self.usd.id, amount="10")
        tx = Transaction.objects.get()
        UserSettings.objects.filter(user=self.user).update(usd_rate=Decimal("3000"))
        self.client.post(
            reverse("transaction_edit", args=[tx.id]),
            {"kind": Kind.EXPENSE, "date": tx.date.isoformat(), "account": self.usd.id,
             "category": self.food.id, "amount": "20", "description": ""},
        )
        tx.refresh_from_db()
        self.assertEqual(tx.amount_cdf, Decimal("56000.00"))

    def test_category_must_match_kind(self):
        response = self.post_tx(kind=Kind.INCOME, category=self.food.id)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Choisissez une catégorie de revenu.")
        self.assertFalse(Transaction.objects.exists())

    def test_cannot_use_other_users_account(self):
        foreign = Account.objects.create(user=self.other, name="Autre")
        self.post_tx(account=foreign.id)
        self.assertFalse(Transaction.objects.exists())
        self.assertEqual(self.client.get(reverse("account_edit", args=[foreign.id])).status_code, 404)

    def test_balance_and_dashboard(self):
        self.post_tx(amount="25000")
        self.post_tx(kind=Kind.INCOME, category=self.salary.id, account=self.usd.id, amount="50")
        self.assertEqual(self.cdf.balance, Decimal("75000"))
        self.assertEqual(self.usd.balance, Decimal("150"))
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        # 75 000 FC + 150 $ × 2 800 = 495 000 FC
        self.assertContains(response, "495 000 FC")
        self.assertContains(response, 'id="chart-data"')

    def test_protected_account_delete(self):
        self.post_tx()
        response = self.client.post(reverse("account_delete", args=[self.cdf.id]))
        self.assertRedirects(response, reverse("account_list"))
        self.assertTrue(Account.objects.filter(pk=self.cdf.pk).exists())

    def test_budget_create_and_copy(self):
        month = first_of_month(date.today())
        previous = add_months(month, -1)
        response = self.client.post(
            reverse("budget_create"),
            {"category": self.food.id, "month": previous.strftime("%Y-%m"), "amount": "300000", "currency": "CDF"},
        )
        self.assertEqual(response.status_code, 302)
        self.client.post(reverse("budget_copy"), {"mois": month.strftime("%Y-%m")})
        self.assertTrue(Budget.objects.filter(user=self.user, month=month, category=self.food).exists())
        self.post_tx(amount="270000")
        self.assertContains(self.client.get(reverse("budget_list")), "Attention")

    def test_settings_update_rate(self):
        response = self.client.post(reverse("settings"), {"form": "settings", "usd_rate": "2900.50", "show_usd": "on"})
        self.assertRedirects(response, reverse("settings"))
        self.assertEqual(UserSettings.for_user(self.user).usd_rate, Decimal("2900.50"))

    def test_transaction_filters(self):
        self.post_tx(description="Marché Gambela")
        self.post_tx(description="Taxi")
        response = self.client.get(reverse("transaction_list"), {"q": "gambela"})
        self.assertContains(response, "Marché Gambela")
        self.assertNotContains(response, "Taxi")
