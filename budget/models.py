from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q, Sum
from django.utils import timezone

DEFAULT_USD_RATE = Decimal("2850.00")


class Currency(models.TextChoices):
    CDF = "CDF", "Franc congolais (CDF)"
    USD = "USD", "Dollar américain (USD)"


class Kind(models.TextChoices):
    INCOME = "income", "Revenu"
    EXPENSE = "expense", "Dépense"


def quantize(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class UserSettings(models.Model):
    """Préférences d'un utilisateur, dont le taux de change USD → CDF."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="budget_settings")
    usd_rate = models.DecimalField(
        "Taux de change (1 USD en CDF)",
        max_digits=12,
        decimal_places=2,
        default=DEFAULT_USD_RATE,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    rate_updated_at = models.DateTimeField("Taux mis à jour le", default=timezone.now)
    show_usd = models.BooleanField("Afficher l'équivalent en USD sur le tableau de bord", default=True)

    class Meta:
        verbose_name = "Paramètres"
        verbose_name_plural = "Paramètres"

    def __str__(self):
        return f"Paramètres de {self.user}"

    @classmethod
    def for_user(cls, user):
        obj, _ = cls.objects.get_or_create(user=user)
        return obj

    def to_cdf(self, amount, currency):
        amount = Decimal(amount or 0)
        return amount * self.usd_rate if currency == Currency.USD else amount

    def to_usd(self, amount_cdf):
        return Decimal(amount_cdf or 0) / self.usd_rate


class Account(models.Model):
    class Type(models.TextChoices):
        CASH = "cash", "Espèces"
        MOBILE = "mobile", "Mobile money"
        BANK = "bank", "Banque"
        SAVINGS = "savings", "Épargne"
        OTHER = "other", "Autre"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="accounts")
    name = models.CharField("Nom", max_length=80)
    type = models.CharField("Type", max_length=20, choices=Type.choices, default=Type.CASH)
    currency = models.CharField("Devise", max_length=3, choices=Currency.choices, default=Currency.CDF)
    initial_balance = models.DecimalField("Solde initial", max_digits=16, decimal_places=2, default=0)
    is_active = models.BooleanField("Actif", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Compte"
        constraints = [models.UniqueConstraint(fields=["user", "name"], name="unique_account_name_per_user")]

    def __str__(self):
        return f"{self.name} ({self.currency})"

    @property
    def type_label(self):
        return self.get_type_display()

    @property
    def balance(self):
        totals = self.transactions.aggregate(
            income=Sum("amount", filter=Q(kind=Kind.INCOME)),
            expense=Sum("amount", filter=Q(kind=Kind.EXPENSE)),
        )
        return self.initial_balance + (totals["income"] or 0) - (totals["expense"] or 0)


class Category(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="categories")
    name = models.CharField("Nom", max_length=80)
    kind = models.CharField("Type", max_length=10, choices=Kind.choices, default=Kind.EXPENSE)
    color = models.CharField("Couleur", max_length=7, default="#0f766e")

    class Meta:
        ordering = ["kind", "name"]
        verbose_name = "Catégorie"
        constraints = [
            models.UniqueConstraint(fields=["user", "name", "kind"], name="unique_category_per_user_kind")
        ]

    def __str__(self):
        return self.name

    @property
    def kind_label(self):
        return self.get_kind_display()

    @property
    def is_income(self):
        return self.kind == Kind.INCOME


class Transaction(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="transactions")
    kind = models.CharField("Type", max_length=10, choices=Kind.choices, default=Kind.EXPENSE)
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="transactions", verbose_name="Compte")
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name="transactions", verbose_name="Catégorie"
    )
    amount = models.DecimalField(
        "Montant", max_digits=16, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )
    # Devise du compte et taux au moment de la saisie : changer le taux plus tard ne réécrit pas l'historique.
    currency = models.CharField("Devise", max_length=3, choices=Currency.choices, editable=False)
    exchange_rate = models.DecimalField("Taux appliqué", max_digits=12, decimal_places=2, editable=False)
    amount_cdf = models.DecimalField("Montant en CDF", max_digits=18, decimal_places=2, editable=False)
    date = models.DateField("Date", default=timezone.localdate)
    description = models.CharField("Description", max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]
        verbose_name = "Transaction"
        indexes = [models.Index(fields=["user", "date"])]

    def __str__(self):
        return f"{self.get_kind_display()} {self.amount} {self.currency} — {self.date}"

    @property
    def kind_label(self):
        return self.get_kind_display()

    @property
    def is_income(self):
        return self.kind == Kind.INCOME

    def apply_rate(self, rate):
        """Fige la devise du compte et le taux du jour, et calcule l'équivalent en CDF."""
        self.currency = self.account.currency
        self.exchange_rate = rate
        self.amount_cdf = quantize(self.amount * rate if self.currency == Currency.USD else self.amount)


class Budget(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="budgets")
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="budgets", verbose_name="Catégorie")
    month = models.DateField("Mois", help_text="Le premier jour du mois concerné.")
    amount = models.DecimalField(
        "Montant prévu", max_digits=16, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )
    currency = models.CharField("Devise", max_length=3, choices=Currency.choices, default=Currency.CDF)

    class Meta:
        ordering = ["-month", "category__name"]
        verbose_name = "Budget"
        constraints = [
            models.UniqueConstraint(fields=["user", "category", "month"], name="unique_budget_per_category_month")
        ]

    def __str__(self):
        return f"{self.category} — {self.month:%m/%Y}"
