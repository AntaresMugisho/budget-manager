"""Crée un utilisateur de démonstration avec des comptes, catégories, budgets et 6 mois de transactions."""

import random
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction as db_transaction

from budget.models import Account, Budget, Category, Kind, Transaction, UserSettings
from budget.utils import add_months, first_of_month

EXPENSES = [
    ("Alimentation", "#e76f51", 450_000),
    ("Transport", "#f4a261", 160_000),
    ("Loyer", "#264653", 700_000),
    ("Électricité & eau", "#2a9d8f", 90_000),
    ("Santé", "#8ab17d", 80_000),
    ("Scolarité", "#6d597a", 300_000),
    ("Communication", "#b56576", 60_000),
    ("Loisirs", "#e9c46a", 120_000),
]
INCOMES = [("Salaire", "#0b7d62"), ("Activités secondaires", "#3a86ff")]


class Command(BaseCommand):
    help = "Crée des données de démonstration (utilisateur « demo », mot de passe « demo12345 »)."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="demo")
        parser.add_argument("--password", default="demo12345")
        parser.add_argument("--reset", action="store_true", help="Supprime d'abord les données de cet utilisateur.")

    @db_transaction.atomic
    def handle(self, *args, username, password, reset, **options):
        random.seed(42)
        User = get_user_model()
        user, created = User.objects.get_or_create(username=username, defaults={"first_name": "Démo"})
        if created:
            user.set_password(password)
            user.save()
        if reset:
            Transaction.objects.filter(user=user).delete()
            Budget.objects.filter(user=user).delete()
            Category.objects.filter(user=user).delete()
            Account.objects.filter(user=user).delete()
        elif Account.objects.filter(user=user).exists():
            self.stdout.write(self.style.WARNING("Des données existent déjà (utilisez --reset)."))
            return

        today = date.today()
        settings = UserSettings.for_user(user)
        rate = settings.usd_rate

        cash = Account.objects.create(user=user, name="Caisse maison", type=Account.Type.CASH, initial_balance=250_000)
        mpesa = Account.objects.create(user=user, name="M-Pesa", type=Account.Type.MOBILE, initial_balance=120_000)
        bank = Account.objects.create(
            user=user, name="Banque Equity", type=Account.Type.BANK, currency="USD", initial_balance=850
        )

        expense_cats = {
            name: Category.objects.create(user=user, name=name, kind=Kind.EXPENSE, color=color)
            for name, color, _ in EXPENSES
        }
        salary, side = (
            Category.objects.create(user=user, name=name, kind=Kind.INCOME, color=color) for name, color in INCOMES
        )

        def add(kind, account, category, amount, day, description=""):
            if day > today:
                return
            tx = Transaction(
                user=user, kind=kind, account=account, category=category,
                amount=Decimal(amount).quantize(Decimal("0.01")), date=day, description=description,
            )
            tx.apply_rate(rate * Decimal(random.uniform(0.97, 1.0)).quantize(Decimal("0.01")))
            tx.save()

        this_month = first_of_month(today)
        for offset in range(-5, 1):
            month = add_months(this_month, offset)
            last_day = min(today, add_months(month, 1) - timedelta(days=1))
            add(Kind.INCOME, mpesa, salary, random.randint(1_550, 1_700) * 1000, month, "Salaire mensuel")
            add(Kind.INCOME, bank, side, random.choice([250, 300, 400]), month + timedelta(days=10), "Consultance")
            add(Kind.INCOME, cash, side, random.randint(550, 750) * 1000, month + timedelta(days=14), "Prestation")
            for name, _, monthly in EXPENSES:
                parts = 1 if name in ("Loyer", "Scolarité", "Électricité & eau") else random.randint(3, 7)
                for _ in range(parts):
                    day = month + timedelta(days=random.randint(0, max((last_day - month).days, 0)))
                    amount = monthly / parts * random.uniform(0.6, 1.35)
                    account = cash if name in ("Alimentation", "Transport") else mpesa
                    if name == "Loyer":
                        add(Kind.EXPENSE, bank, expense_cats[name], round(amount / float(rate), 2), day, "Loyer")
                    else:
                        add(Kind.EXPENSE, account, expense_cats[name], round(amount, -2), day)
            add(Kind.EXPENSE, bank, expense_cats["Alimentation"], 40, month + timedelta(days=3), "Supermarché (carte)")

            for name, _, monthly in EXPENSES:
                Budget.objects.get_or_create(
                    user=user, category=expense_cats[name], month=month, defaults={"amount": round(monthly * 1.15, -4)}
                )

        self.stdout.write(self.style.SUCCESS(f"Données de démonstration créées pour « {username} » (mot de passe : {password})."))
