from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm

from .models import Account, Budget, Category, Kind, Transaction, UserSettings
from .utils import first_of_month

INPUT_CLASS = (
    "block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm "
    "placeholder:text-slate-400 focus:border-emerald-600 focus:outline-none focus:ring-2 focus:ring-emerald-600/20"
)
CHECKBOX_CLASS = "h-4 w-4 rounded border-slate-300 text-emerald-700 focus:ring-emerald-600"
COLOR_CLASS = "h-10 w-20 cursor-pointer rounded-lg border border-slate-300 bg-white p-1"


class StyledFormMixin:
    """Ajoute les classes Tailwind aux widgets, pour que les gabarits restent simples."""

    @property
    def field_list(self):
        """Les champs liés, en liste : la boucle @for de PyBlade a besoin de len()."""
        return list(self)

    def style_fields(self):
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", CHECKBOX_CLASS)
            elif getattr(widget, "input_type", None) == "color":
                widget.attrs.setdefault("class", COLOR_CLASS)
            else:
                widget.attrs.setdefault("class", INPUT_CLASS)


class LoginForm(StyledFormMixin, AuthenticationForm):
    error_messages = {
        "invalid_login": "Nom d'utilisateur ou mot de passe incorrect.",
        "inactive": "Ce compte est désactivé.",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Nom d'utilisateur"
        self.fields["username"].widget.attrs.update(placeholder="Votre identifiant", autofocus=True)
        self.fields["password"].label = "Mot de passe"
        self.fields["password"].widget.attrs.update(placeholder="••••••••")
        self.style_fields()


class FrenchPasswordChangeForm(StyledFormMixin, PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["old_password"].label = "Mot de passe actuel"
        self.fields["old_password"].widget.attrs.pop("autofocus", None)
        self.fields["new_password1"].label = "Nouveau mot de passe"
        self.fields["new_password1"].help_text = "Au moins 8 caractères, pas uniquement des chiffres."
        self.fields["new_password2"].label = "Confirmer le nouveau mot de passe"
        self.style_fields()


class UserScopedForm(StyledFormMixin, forms.ModelForm):
    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self.style_fields()

    def save(self, commit=True):
        self.instance.user = self.user
        return super().save(commit)


class AccountForm(UserScopedForm):
    class Meta:
        model = Account
        fields = ["name", "type", "currency", "initial_balance", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "ex. : M-Pesa, Caisse maison, Equity BCDC"}),
            "initial_balance": forms.NumberInput(attrs={"step": "0.01"}),
        }
        help_texts = {
            "currency": "La devise ne peut plus être changée une fois que le compte a des transactions.",
            "initial_balance": "Le solde du compte au moment où vous commencez le suivi.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and self.instance.transactions.exists():
            self.fields["currency"].disabled = True

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        duplicates = Account.objects.filter(user=self.user, name__iexact=name).exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise forms.ValidationError("Vous avez déjà un compte portant ce nom.")
        return name


class CategoryForm(UserScopedForm):
    class Meta:
        model = Category
        fields = ["name", "kind", "color"]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "ex. : Alimentation, Salaire, Transport"}),
            "color": forms.TextInput(attrs={"type": "color"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["color"].widget.input_type = "color"
        self.fields["color"].widget.attrs["class"] = COLOR_CLASS
        if self.instance.pk and self.instance.transactions.exists():
            self.fields["kind"].disabled = True
            self.fields["kind"].help_text = "Le type ne peut plus changer : des transactions utilisent cette catégorie."

    def clean(self):
        cleaned = super().clean()
        name, kind = cleaned.get("name"), cleaned.get("kind")
        if name and kind:
            duplicates = Category.objects.filter(user=self.user, name__iexact=name.strip(), kind=kind)
            if duplicates.exclude(pk=self.instance.pk).exists():
                raise forms.ValidationError("Une catégorie de ce type porte déjà ce nom.")
        return cleaned


class TransactionForm(UserScopedForm):
    class Meta:
        model = Transaction
        fields = ["kind", "date", "account", "category", "amount", "description"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "amount": forms.NumberInput(attrs={"step": "0.01", "min": "0.01", "placeholder": "0,00"}),
            "description": forms.TextInput(attrs={"placeholder": "ex. : Courses au marché"}),
            "kind": forms.RadioSelect,
        }
        help_texts = {"amount": "Dans la devise du compte choisi."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        accounts = Account.objects.filter(user=self.user)
        if not self.instance.pk:
            accounts = accounts.filter(is_active=True)
        self.fields["account"].queryset = accounts
        self.fields["account"].empty_label = "Choisir un compte"
        self.fields["category"].queryset = Category.objects.filter(user=self.user)
        self.fields["category"].empty_label = "Choisir une catégorie"
        self.fields["kind"].widget.attrs = {}

    def clean(self):
        cleaned = super().clean()
        kind, category = cleaned.get("kind"), cleaned.get("category")
        if kind and category and category.kind != kind:
            label = "revenu" if kind == Kind.INCOME else "dépense"
            self.add_error("category", f"Choisissez une catégorie de {label}.")
        return cleaned


class BudgetForm(UserScopedForm):
    month = forms.DateField(
        label="Mois",
        input_formats=["%Y-%m"],
        widget=forms.DateInput(attrs={"type": "month"}, format="%Y-%m"),
    )

    class Meta:
        model = Budget
        fields = ["category", "month", "amount", "currency"]
        widgets = {"amount": forms.NumberInput(attrs={"step": "0.01", "min": "0.01"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = Category.objects.filter(user=self.user, kind=Kind.EXPENSE)
        self.fields["category"].empty_label = "Choisir une catégorie de dépense"
        self.fields["month"].widget.attrs["class"] = INPUT_CLASS

    def clean_month(self):
        return first_of_month(self.cleaned_data["month"])

    def clean(self):
        cleaned = super().clean()
        category, month = cleaned.get("category"), cleaned.get("month")
        if category and month:
            duplicates = Budget.objects.filter(user=self.user, category=category, month=month)
            if duplicates.exclude(pk=self.instance.pk).exists():
                raise forms.ValidationError("Un budget existe déjà pour cette catégorie et ce mois.")
        return cleaned


class SettingsForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = UserSettings
        fields = ["usd_rate", "show_usd"]
        widgets = {"usd_rate": forms.NumberInput(attrs={"step": "0.01", "min": "0.01"})}
        help_texts = {
            "usd_rate": "Combien de francs congolais pour 1 dollar. Utilisé pour les nouvelles transactions, "
            "les soldes des comptes en USD et les budgets.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.style_fields()
