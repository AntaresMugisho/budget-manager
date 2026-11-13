from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.paginator import Paginator
from django.db.models import Count, ProtectedError, Q, Sum
from django.db.models.functions import TruncMonth
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import json_script
from django.views.decorators.http import require_POST

from .forms import (
    AccountForm,
    BudgetForm,
    CategoryForm,
    FrenchPasswordChangeForm,
    LoginForm,
    SettingsForm,
    TransactionForm,
)
from .models import Account, Budget, Category, Currency, Kind, Transaction, UserSettings
from .utils import add_months, date_fr, first_of_month, money, month_label, parse_month, percent

PER_PAGE = 20


def page(request, template, context=None, status=200):
    """Rend un gabarit PyBlade (le moteur Django passe en premier dans TEMPLATES, pour l'admin)."""
    return render(request, template, context or {}, using="pyblade", status=status)


class FrenchLoginView(LoginView):
    template_name = "auth/login.html"
    template_engine = "pyblade"
    authentication_form = LoginForm
    redirect_authenticated_user = True


# ---------------------------------------------------------------------------
# Lignes prêtes à afficher (les expressions PyBlade n'appellent pas de méthodes)
# ---------------------------------------------------------------------------


def transaction_row(tx):
    return {
        "id": tx.id,
        "date": date_fr(tx.date),
        "description": tx.description or tx.category.name,
        "has_description": bool(tx.description),
        "category": tx.category.name,
        "color": tx.category.color,
        "account": tx.account.name,
        "is_income": tx.is_income,
        "amount": money(tx.amount, tx.currency),
        "amount_cdf": money(tx.amount_cdf, "CDF"),
        "is_usd": tx.currency == Currency.USD,
        "rate": money(tx.exchange_rate, "CDF", 2),
        "edit_url": reverse("transaction_edit", args=[tx.id]),
        "delete_url": reverse("transaction_delete", args=[tx.id]),
    }


def sum_by_kind(queryset):
    totals = queryset.aggregate(
        income=Sum("amount_cdf", filter=Q(kind=Kind.INCOME)),
        expense=Sum("amount_cdf", filter=Q(kind=Kind.EXPENSE)),
    )
    return totals["income"] or Decimal(0), totals["expense"] or Decimal(0)


def month_totals(user, start):
    return sum_by_kind(Transaction.objects.filter(user=user, date__gte=start, date__lt=add_months(start, 1)))


def monthly_series(queryset):
    """{premier jour du mois: (revenus, dépenses)} en CDF."""
    rows = (
        queryset.annotate(month=TruncMonth("date"))
        .values("month")
        .annotate(
            income=Sum("amount_cdf", filter=Q(kind=Kind.INCOME)),
            expense=Sum("amount_cdf", filter=Q(kind=Kind.EXPENSE)),
        )
    )
    series = {}
    for row in rows:
        key = row["month"].date() if hasattr(row["month"], "date") else row["month"]
        series[key] = (float(row["income"] or 0), float(row["expense"] or 0))
    return series


def variation(current, previous):
    if not previous:
        return None
    return round(float((Decimal(current) - Decimal(previous)) / Decimal(previous) * 100), 1)


def budget_rows(user, settings, month):
    end = add_months(month, 1)
    budgets = Budget.objects.filter(user=user, month=month).select_related("category")
    spent_by_category = dict(
        Transaction.objects.filter(user=user, kind=Kind.EXPENSE, date__gte=month, date__lt=end)
        .values("category")
        .annotate(total=Sum("amount_cdf"))
        .values_list("category", "total")
    )
    rows, planned_total, spent_total = [], Decimal(0), Decimal(0)
    for budget in budgets:
        planned = settings.to_cdf(budget.amount, budget.currency)
        spent = spent_by_category.get(budget.category_id, Decimal(0))
        ratio = percent(spent, planned)
        planned_total += planned
        spent_total += spent
        if ratio >= 100:
            status, status_label = "over", "Dépassé"
        elif ratio >= 80:
            status, status_label = "warn", "Attention"
        else:
            status, status_label = "ok", "Dans le budget"
        rows.append(
            {
                "id": budget.id,
                "category": budget.category.name,
                "color": budget.category.color,
                "planned": money(budget.amount, budget.currency),
                "planned_cdf": money(planned, "CDF"),
                "planned_raw": float(planned),
                "spent_raw": float(spent),
                "is_usd": budget.currency == Currency.USD,
                "spent": money(spent, "CDF"),
                "remaining": money(planned - spent, "CDF"),
                "overrun": money(spent - planned, "CDF"),
                "is_over": spent > planned,
                "ratio": ratio,
                "bar": min(ratio, 100),
                "status": status,
                "status_label": status_label,
                "edit_url": reverse("budget_edit", args=[budget.id]),
                "delete_url": reverse("budget_delete", args=[budget.id]),
            }
        )
    return rows, planned_total, spent_total


def account_rows(user, settings, include_inactive=False):
    accounts = Account.objects.filter(user=user).annotate(tx_count=Count("transactions"))
    if not include_inactive:
        accounts = accounts.filter(is_active=True)
    rows, total = [], Decimal(0)
    for account in accounts:
        balance = account.balance
        balance_cdf = settings.to_cdf(balance, account.currency)
        if account.is_active:
            total += balance_cdf
        rows.append(
            {
                "id": account.id,
                "name": account.name,
                "type": account.type_label,
                "currency": account.currency,
                "is_usd": account.currency == Currency.USD,
                "is_active": account.is_active,
                "initial": money(account.initial_balance, account.currency),
                "balance": money(balance, account.currency),
                "balance_cdf": money(balance_cdf, "CDF"),
                "is_negative": balance < 0,
                "tx_count": account.tx_count,
                "edit_url": reverse("account_edit", args=[account.id]),
                "delete_url": reverse("account_delete", args=[account.id]),
                "transactions_url": f"{reverse('transaction_list')}?compte={account.id}",
            }
        )
    return rows, total


def selected_month(request):
    return parse_month(request.GET.get("mois")) or first_of_month(timezone.localdate())


# ---------------------------------------------------------------------------
# Tableau de bord
# ---------------------------------------------------------------------------


@login_required
def dashboard(request):
    user = request.user
    settings = UserSettings.for_user(user)
    month = selected_month(request)
    next_month = add_months(month, 1)
    previous_month = add_months(month, -1)
    transactions = Transaction.objects.filter(user=user)

    income, expense = month_totals(user, month)
    prev_income, prev_expense = month_totals(user, previous_month)
    net = income - expense

    accounts, total_balance = account_rows(user, settings)
    budgets, planned_total, budget_spent = budget_rows(user, settings, month)

    # Revenus et dépenses sur les 12 derniers mois
    start = add_months(month, -11)
    months = [add_months(start, i) for i in range(12)]
    series = monthly_series(transactions.filter(date__gte=start, date__lt=next_month))

    # Évolution estimée du solde global (comptes actifs) en fin de mois
    active = transactions.filter(account__is_active=True)
    initial_cdf = sum(
        (settings.to_cdf(a.initial_balance, a.currency) for a in Account.objects.filter(user=user, is_active=True)),
        Decimal(0),
    )
    before_income, before_expense = sum_by_kind(active.filter(date__lt=start))
    running = float(initial_cdf + before_income - before_expense)
    active_series = monthly_series(active.filter(date__gte=start, date__lt=next_month))
    net_worth = []
    for m in months:
        inc, exp = active_series.get(m, (0.0, 0.0))
        running += inc - exp
        net_worth.append(round(running, 2))

    # Dépenses du mois par catégorie
    by_category = list(
        transactions.filter(kind=Kind.EXPENSE, date__gte=month, date__lt=next_month)
        .values("category__name", "category__color")
        .annotate(total=Sum("amount_cdf"))
        .order_by("-total")
    )
    category_rows = [
        {
            "name": row["category__name"],
            "color": row["category__color"],
            "total": money(row["total"], "CDF"),
            "share": percent(row["total"], expense),
        }
        for row in by_category[:6]
    ]

    chart_data = {
        "months": [month_label(m, short=True) for m in months],
        "income": [series.get(m, (0.0, 0.0))[0] for m in months],
        "expense": [series.get(m, (0.0, 0.0))[1] for m in months],
        "netWorth": net_worth,
        "categories": {
            "labels": [row["category__name"] for row in by_category],
            "values": [float(row["total"]) for row in by_category],
            "colors": [row["category__color"] for row in by_category],
        },
        "budgets": {
            "labels": [row["category"] for row in budgets],
            "planned": [row["planned_raw"] for row in budgets],
            "spent": [row["spent_raw"] for row in budgets],
        },
    }

    recent = transactions.select_related("account", "category")[:8]
    budget_ratio = percent(budget_spent, planned_total)

    context = {
        "page_title": "Tableau de bord",
        "month_label": month_label(month),
        "month_value": month.strftime("%Y-%m"),
        "prev_url": f"?mois={previous_month:%Y-%m}",
        "next_url": f"?mois={next_month:%Y-%m}",
        "is_current_month": month == first_of_month(timezone.localdate()),
        "show_usd": settings.show_usd,
        "rate": money(settings.usd_rate, "CDF", 2),
        "kpi": {
            "balance": money(total_balance, "CDF"),
            "balance_usd": money(settings.to_usd(total_balance), "USD"),
            "balance_negative": total_balance < 0,
            "income": money(income, "CDF"),
            "income_usd": money(settings.to_usd(income), "USD"),
            "income_change": variation(income, prev_income),
            "expense": money(expense, "CDF"),
            "expense_usd": money(settings.to_usd(expense), "USD"),
            "expense_change": variation(expense, prev_expense),
            "net": money(net, "CDF"),
            "net_usd": money(settings.to_usd(net), "USD"),
            "net_negative": net < 0,
            "savings_rate": percent(net, income),
            "budget_planned": money(planned_total, "CDF"),
            "budget_spent": money(budget_spent, "CDF"),
            "budget_ratio": budget_ratio,
            "budget_bar": min(budget_ratio, 100),
            "budget_over": budget_ratio >= 100,
            "has_budget": planned_total > 0,
        },
        "accounts": accounts,
        "budgets": budgets,
        "category_rows": category_rows,
        "recent": [transaction_row(tx) for tx in recent],
        "has_data": transactions.exists(),
        "has_accounts": Account.objects.filter(user=user).exists(),
        "has_categories": Category.objects.filter(user=user).exists(),
        "chart_json": json_script(chart_data, "chart-data"),
    }
    return page(request, "budget/dashboard.html", context)


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------


@login_required
def transaction_list(request):
    user = request.user
    qs = Transaction.objects.filter(user=user).select_related("account", "category")

    filters = {
        "q": request.GET.get("q", "").strip(),
        "type": request.GET.get("type", ""),
        "compte": request.GET.get("compte", ""),
        "categorie": request.GET.get("categorie", ""),
        "mois": request.GET.get("mois", ""),
    }
    if filters["q"]:
        qs = qs.filter(Q(description__icontains=filters["q"]) | Q(category__name__icontains=filters["q"]))
    if filters["type"] in Kind.values:
        qs = qs.filter(kind=filters["type"])
    if filters["compte"].isdigit():
        qs = qs.filter(account_id=int(filters["compte"]))
    if filters["categorie"].isdigit():
        qs = qs.filter(category_id=int(filters["categorie"]))
    month = parse_month(filters["mois"]) if filters["mois"] else None
    if month:
        qs = qs.filter(date__gte=month, date__lt=add_months(month, 1))

    income, expense = sum_by_kind(qs)

    paginator = Paginator(qs, PER_PAGE)
    page_obj = paginator.get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    base = params.urlencode()

    def page_url(number):
        return f"?{base}&page={number}" if base else f"?page={number}"

    context = {
        "page_title": "Transactions",
        "rows": [transaction_row(tx) for tx in page_obj],
        "filters": filters,
        "type_options": [
            {"value": "", "label": "Tous les types", "selected": filters["type"] == ""},
            {"value": Kind.INCOME, "label": "Revenus", "selected": filters["type"] == Kind.INCOME},
            {"value": Kind.EXPENSE, "label": "Dépenses", "selected": filters["type"] == Kind.EXPENSE},
        ],
        "accounts": [
            {"id": str(a.id), "name": a.name, "selected": str(a.id) == filters["compte"]}
            for a in Account.objects.filter(user=user)
        ],
        "categories": [
            {"id": str(c.id), "name": f"{c.name} ({c.kind_label.lower()})", "selected": str(c.id) == filters["categorie"]}
            for c in Category.objects.filter(user=user)
        ],
        "is_filtered": any(filters.values()),
        "count": paginator.count,
        "income": money(income, "CDF"),
        "expense": money(expense, "CDF"),
        "net": money(income - expense, "CDF"),
        "net_negative": income < expense,
        "pagination": {
            "show": paginator.num_pages > 1,
            "number": page_obj.number,
            "pages": paginator.num_pages,
            "prev_url": page_url(page_obj.previous_page_number()) if page_obj.has_previous() else "",
            "next_url": page_url(page_obj.next_page_number()) if page_obj.has_next() else "",
        },
    }
    return page(request, "budget/transactions.html", context)


def transaction_form_page(request, form, title, instance=None):
    settings = UserSettings.for_user(request.user)
    user = request.user
    return page(
        request,
        "budget/transaction_form.html",
        {
            "page_title": title,
            "form": form,
            "is_edit": instance is not None,
            "current_kind": form["kind"].value() or Kind.EXPENSE,
            "rate": money(settings.usd_rate, "CDF", 2),
            "rate_raw": float(settings.usd_rate),
            "frozen_rate": money(instance.exchange_rate, "CDF", 2) if instance else "",
            "frozen_rate_raw": float(instance.exchange_rate) if instance else 0,
            "is_usd_tx": bool(instance and instance.currency == Currency.USD),
            "meta_json": json_script(
                {
                    "categories": {str(c.id): c.kind for c in Category.objects.filter(user=user)},
                    "accounts": {str(a.id): a.currency for a in Account.objects.filter(user=user)},
                },
                "form-meta",
            ),
            "missing_setup": not Account.objects.filter(user=user, is_active=True).exists()
            or not Category.objects.filter(user=user).exists(),
        },
    )


@login_required
def transaction_create(request):
    settings = UserSettings.for_user(request.user)
    kind = request.GET.get("type")
    initial = {"kind": kind if kind in Kind.values else Kind.EXPENSE}
    form = TransactionForm(request.POST or None, user=request.user, initial=initial)
    if request.method == "POST" and form.is_valid():
        tx = form.save(commit=False)
        tx.user = request.user
        tx.apply_rate(settings.usd_rate)
        tx.save()
        messages.success(request, "Transaction enregistrée.")
        if "save_and_new" in request.POST:
            return redirect(f"{reverse('transaction_create')}?type={tx.kind}")
        return redirect("transaction_list")
    return transaction_form_page(request, form, "Nouvelle transaction")


@login_required
def transaction_edit(request, pk):
    tx = get_object_or_404(Transaction, pk=pk, user=request.user)
    original_currency, original_rate = tx.currency, tx.exchange_rate
    form = TransactionForm(request.POST or None, instance=tx, user=request.user)
    if request.method == "POST" and form.is_valid():
        tx = form.save(commit=False)
        # Le taux d'origine est conservé, sauf si le nouveau compte n'a pas la même devise.
        rate = original_rate
        if tx.account.currency != original_currency:
            rate = UserSettings.for_user(request.user).usd_rate
        tx.apply_rate(rate)
        tx.save()
        messages.success(request, "Transaction mise à jour.")
        return redirect("transaction_list")
    return transaction_form_page(request, form, "Modifier la transaction", instance=tx)


# ---------------------------------------------------------------------------
# Suppression générique (page de confirmation, sans boîte de dialogue JS)
# ---------------------------------------------------------------------------


def confirm_delete(request, obj, label, back_url, success_url, success_message, warning=""):
    if request.method == "POST":
        name = str(obj)
        try:
            obj.delete()
        except ProtectedError:
            messages.error(
                request,
                f"Impossible de supprimer « {name} » : des transactions y sont liées. "
                "Supprimez-les ou réaffectez-les d'abord.",
            )
            return redirect(back_url)
        messages.success(request, success_message)
        return redirect(success_url)
    return page(
        request,
        "budget/confirm_delete.html",
        {
            "page_title": "Confirmer la suppression",
            "label": label,
            "object_name": str(obj),
            "back_url": back_url,
            "warning": warning,
        },
    )


@login_required
def transaction_delete(request, pk):
    tx = get_object_or_404(Transaction, pk=pk, user=request.user)
    back = reverse("transaction_list")
    return confirm_delete(request, tx, "cette transaction", back, back, "Transaction supprimée.")


# ---------------------------------------------------------------------------
# Comptes
# ---------------------------------------------------------------------------


@login_required
def account_list(request):
    settings = UserSettings.for_user(request.user)
    rows, total = account_rows(request.user, settings, include_inactive=True)
    return page(
        request,
        "budget/accounts.html",
        {
            "page_title": "Comptes",
            "rows": rows,
            "total": money(total, "CDF"),
            "total_usd": money(settings.to_usd(total), "USD"),
            "rate": money(settings.usd_rate, "CDF", 2),
        },
    )


def simple_form(request, form, title, back_url, subtitle=""):
    return page(
        request,
        "budget/simple_form.html",
        {"page_title": title, "subtitle": subtitle, "form": form, "back_url": back_url},
    )


@login_required
def account_create(request):
    form = AccountForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Compte créé.")
        return redirect("account_list")
    return simple_form(
        request, form, "Nouveau compte", reverse("account_list"), "Caisse, mobile money, banque… en CDF ou en USD."
    )


@login_required
def account_edit(request, pk):
    account = get_object_or_404(Account, pk=pk, user=request.user)
    form = AccountForm(request.POST or None, instance=account, user=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Compte mis à jour.")
        return redirect("account_list")
    return simple_form(request, form, f"Modifier « {account.name} »", reverse("account_list"))


@login_required
def account_delete(request, pk):
    account = get_object_or_404(Account, pk=pk, user=request.user)
    back = reverse("account_list")
    warning = ""
    if account.transactions.exists():
        warning = "Ce compte a des transactions : il ne pourra pas être supprimé. Désactivez-le plutôt."
    return confirm_delete(request, account, "ce compte", back, back, "Compte supprimé.", warning)


# ---------------------------------------------------------------------------
# Catégories
# ---------------------------------------------------------------------------


@login_required
def category_list(request):
    month = first_of_month(timezone.localdate())
    categories = Category.objects.filter(user=request.user).annotate(
        tx_count=Count("transactions"),
        month_total=Sum(
            "transactions__amount_cdf",
            filter=Q(transactions__date__gte=month, transactions__date__lt=add_months(month, 1)),
        ),
    )

    def rows(kind):
        return [
            {
                "id": c.id,
                "name": c.name,
                "color": c.color,
                "tx_count": c.tx_count,
                "month_total": money(c.month_total or 0, "CDF"),
                "edit_url": reverse("category_edit", args=[c.id]),
                "delete_url": reverse("category_delete", args=[c.id]),
                "transactions_url": f"{reverse('transaction_list')}?categorie={c.id}",
            }
            for c in categories
            if c.kind == kind
        ]

    return page(
        request,
        "budget/categories.html",
        {
            "page_title": "Catégories",
            "month_label": month_label(month),
            "groups": [
                {"title": "Dépenses", "rows": rows(Kind.EXPENSE), "is_income": False, "add_type": Kind.EXPENSE},
                {"title": "Revenus", "rows": rows(Kind.INCOME), "is_income": True, "add_type": Kind.INCOME},
            ],
        },
    )


@login_required
def category_create(request):
    kind = request.GET.get("type")
    initial = {"kind": kind} if kind in Kind.values else {}
    form = CategoryForm(request.POST or None, user=request.user, initial=initial)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Catégorie créée.")
        return redirect("category_list")
    return simple_form(request, form, "Nouvelle catégorie", reverse("category_list"))


@login_required
def category_edit(request, pk):
    category = get_object_or_404(Category, pk=pk, user=request.user)
    form = CategoryForm(request.POST or None, instance=category, user=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Catégorie mise à jour.")
        return redirect("category_list")
    return simple_form(request, form, f"Modifier « {category.name} »", reverse("category_list"))


@login_required
def category_delete(request, pk):
    category = get_object_or_404(Category, pk=pk, user=request.user)
    back = reverse("category_list")
    warning = ""
    if category.transactions.exists():
        warning = "Cette catégorie est utilisée par des transactions : elle ne pourra pas être supprimée."
    return confirm_delete(request, category, "cette catégorie", back, back, "Catégorie supprimée.", warning)


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------


@login_required
def budget_list(request):
    settings = UserSettings.for_user(request.user)
    month = selected_month(request)
    rows, planned, spent = budget_rows(request.user, settings, month)
    income, _ = month_totals(request.user, month)
    ratio = percent(spent, planned)
    return page(
        request,
        "budget/budgets.html",
        {
            "page_title": "Budgets",
            "rows": rows,
            "month_label": month_label(month),
            "month_value": month.strftime("%Y-%m"),
            "prev_url": f"?mois={add_months(month, -1):%Y-%m}",
            "next_url": f"?mois={add_months(month, 1):%Y-%m}",
            "planned": money(planned, "CDF"),
            "spent": money(spent, "CDF"),
            "remaining": money(planned - spent, "CDF"),
            "is_over": spent > planned,
            "ratio": ratio,
            "bar": min(ratio, 100),
            "income": money(income, "CDF"),
            "unallocated": money(income - planned, "CDF"),
            "unallocated_negative": income < planned,
            "add_url": f"{reverse('budget_create')}?mois={month:%Y-%m}",
            "copy_url": reverse("budget_copy"),
            "has_previous": Budget.objects.filter(user=request.user, month=add_months(month, -1)).exists(),
        },
    )


@login_required
def budget_create(request):
    month = selected_month(request)
    form = BudgetForm(request.POST or None, user=request.user, initial={"month": month})
    if request.method == "POST" and form.is_valid():
        budget = form.save()
        messages.success(request, "Budget enregistré.")
        return redirect(f"{reverse('budget_list')}?mois={budget.month:%Y-%m}")
    return simple_form(
        request,
        form,
        "Nouveau budget",
        f"{reverse('budget_list')}?mois={month:%Y-%m}",
        "Fixez un plafond de dépense mensuel pour une catégorie.",
    )


@login_required
def budget_edit(request, pk):
    budget = get_object_or_404(Budget, pk=pk, user=request.user)
    form = BudgetForm(request.POST or None, instance=budget, user=request.user)
    if request.method == "POST" and form.is_valid():
        budget = form.save()
        messages.success(request, "Budget mis à jour.")
        return redirect(f"{reverse('budget_list')}?mois={budget.month:%Y-%m}")
    return simple_form(
        request,
        form,
        f"Modifier le budget « {budget.category.name} »",
        f"{reverse('budget_list')}?mois={budget.month:%Y-%m}",
    )


@login_required
def budget_delete(request, pk):
    budget = get_object_or_404(Budget, pk=pk, user=request.user)
    back = f"{reverse('budget_list')}?mois={budget.month:%Y-%m}"
    return confirm_delete(request, budget, "ce budget", back, back, "Budget supprimé.")


@login_required
@require_POST
def budget_copy(request):
    """Recopie les budgets du mois précédent vers le mois affiché, sans écraser l'existant."""
    month = parse_month(request.POST.get("mois")) or first_of_month(timezone.localdate())
    previous = Budget.objects.filter(user=request.user, month=add_months(month, -1))
    existing = set(Budget.objects.filter(user=request.user, month=month).values_list("category_id", flat=True))
    created = 0
    for budget in previous:
        if budget.category_id not in existing:
            Budget.objects.create(
                user=request.user,
                category=budget.category,
                month=month,
                amount=budget.amount,
                currency=budget.currency,
            )
            created += 1
    if created:
        messages.success(request, f"{created} budget(s) recopié(s) depuis le mois précédent.")
    else:
        messages.info(request, "Aucun budget à recopier.")
    return redirect(f"{reverse('budget_list')}?mois={month:%Y-%m}")


# ---------------------------------------------------------------------------
# Paramètres
# ---------------------------------------------------------------------------


@login_required
def settings_view(request):
    settings = UserSettings.for_user(request.user)
    old_rate = settings.usd_rate
    settings_form = SettingsForm(instance=settings)
    password_form = FrenchPasswordChangeForm(request.user)

    if request.method == "POST" and request.POST.get("form") == "settings":
        settings_form = SettingsForm(request.POST, instance=settings)
        if settings_form.is_valid():
            obj = settings_form.save(commit=False)
            if obj.usd_rate != old_rate:
                obj.rate_updated_at = timezone.now()
            obj.save()
            messages.success(request, "Paramètres enregistrés.")
            return redirect("settings")
    elif request.method == "POST" and request.POST.get("form") == "password":
        password_form = FrenchPasswordChangeForm(request.user, request.POST)
        if password_form.is_valid():
            user = password_form.save()
            update_session_auth_hash(request, user)
            messages.success(request, "Mot de passe modifié.")
            return redirect("settings")

    settings.refresh_from_db()
    updated = timezone.localtime(settings.rate_updated_at)
    return page(
        request,
        "budget/settings.html",
        {
            "page_title": "Paramètres",
            "settings_form": settings_form,
            "password_form": password_form,
            "rate": money(settings.usd_rate, "CDF", 2),
            "rate_raw": float(settings.usd_rate),
            "rate_updated": f"{date_fr(updated)} à {updated:%H:%M}",
            "example_cdf": money(100 * settings.usd_rate, "CDF"),
        },
    )
