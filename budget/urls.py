from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("transactions/", views.transaction_list, name="transaction_list"),
    path("transactions/nouvelle/", views.transaction_create, name="transaction_create"),
    path("transactions/<int:pk>/modifier/", views.transaction_edit, name="transaction_edit"),
    path("transactions/<int:pk>/supprimer/", views.transaction_delete, name="transaction_delete"),
    path("comptes/", views.account_list, name="account_list"),
    path("comptes/nouveau/", views.account_create, name="account_create"),
    path("comptes/<int:pk>/modifier/", views.account_edit, name="account_edit"),
    path("comptes/<int:pk>/supprimer/", views.account_delete, name="account_delete"),
    path("categories/", views.category_list, name="category_list"),
    path("categories/nouvelle/", views.category_create, name="category_create"),
    path("categories/<int:pk>/modifier/", views.category_edit, name="category_edit"),
    path("categories/<int:pk>/supprimer/", views.category_delete, name="category_delete"),
    path("budgets/", views.budget_list, name="budget_list"),
    path("budgets/nouveau/", views.budget_create, name="budget_create"),
    path("budgets/recopier/", views.budget_copy, name="budget_copy"),
    path("budgets/<int:pk>/modifier/", views.budget_edit, name="budget_edit"),
    path("budgets/<int:pk>/supprimer/", views.budget_delete, name="budget_delete"),
    path("parametres/", views.settings_view, name="settings"),
]
