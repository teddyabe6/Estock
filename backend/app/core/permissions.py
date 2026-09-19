"""Granular permissions and the default role bundles.

Application code checks *permissions*, never roles, so custom role bundles can be
added later without rewriting call sites (PRD section 5.1).
"""

from __future__ import annotations

from enum import StrEnum


class Permission(StrEnum):
    # Business administration
    BUSINESS_VIEW = "business:view"
    BUSINESS_MANAGE = "business:manage"
    BRANCH_VIEW = "branch:view"
    BRANCH_MANAGE = "branch:manage"
    USER_VIEW = "user:view"
    USER_MANAGE = "user:manage"
    SETTINGS_MANAGE = "settings:manage"
    AUDIT_VIEW = "audit:view"

    # Catalogue
    PRODUCT_VIEW = "product:view"
    PRODUCT_MANAGE = "product:manage"
    PRODUCT_IMPORT = "product:import"
    COST_VIEW = "cost:view"
    PRICING_MANAGE = "pricing:manage"

    # Inventory
    STOCK_VIEW = "stock:view"
    STOCK_RECEIVE = "stock:receive"
    STOCK_TRANSFER = "stock:transfer"
    STOCK_ADJUST = "stock:adjust"
    STOCK_COUNT = "stock:count"

    # Sales
    SALE_VIEW = "sale:view"
    SALE_CREATE = "sale:create"
    SALE_VOID = "sale:void"
    DISCOUNT_APPROVE = "discount:approve"

    # Purchasing
    PURCHASE_VIEW = "purchase:view"
    PURCHASE_CREATE = "purchase:create"

    # Contacts
    CUSTOMER_VIEW = "customer:view"
    CUSTOMER_MANAGE = "customer:manage"
    SUPPLIER_VIEW = "supplier:view"
    SUPPLIER_MANAGE = "supplier:manage"

    # Credit
    CREDIT_VIEW = "credit:view"
    CREDIT_CREATE = "credit:create"
    CREDIT_PAYMENT_RECORD = "credit:payment"
    CREDIT_DUEDATE_CHANGE = "credit:duedate"
    CREDIT_CANCEL = "credit:cancel"
    CREDIT_LIMIT_OVERRIDE = "credit:limit_override"
    CREDIT_FOLLOWUP = "credit:followup"

    # Online shop
    SHOP_VIEW = "shop:view"
    SHOP_MANAGE = "shop:manage"
    ENQUIRY_VIEW = "enquiry:view"
    ENQUIRY_MANAGE = "enquiry:manage"
    QUOTATION_VIEW = "quotation:view"
    QUOTATION_MANAGE = "quotation:manage"

    # Reporting
    REPORT_SALES = "report:sales"
    REPORT_PROFIT = "report:profit"
    REPORT_INVENTORY = "report:inventory"
    REPORT_CREDIT = "report:credit"
    REPORT_BRANCH_COMPARE = "report:branch_compare"


class RoleName(StrEnum):
    OWNER = "owner"
    MANAGER = "manager"
    SALESPERSON = "salesperson"
    STOCK_USER = "stock_user"


ALL_PERMISSIONS: frozenset[Permission] = frozenset(Permission)

_MANAGER_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.BUSINESS_VIEW,
        Permission.BRANCH_VIEW,
        Permission.USER_VIEW,
        Permission.PRODUCT_VIEW,
        Permission.PRODUCT_MANAGE,
        Permission.PRODUCT_IMPORT,
        Permission.COST_VIEW,
        Permission.PRICING_MANAGE,
        Permission.STOCK_VIEW,
        Permission.STOCK_RECEIVE,
        Permission.STOCK_TRANSFER,
        Permission.STOCK_ADJUST,
        Permission.STOCK_COUNT,
        Permission.SALE_VIEW,
        Permission.SALE_CREATE,
        Permission.SALE_VOID,
        Permission.DISCOUNT_APPROVE,
        Permission.PURCHASE_VIEW,
        Permission.PURCHASE_CREATE,
        Permission.CUSTOMER_VIEW,
        Permission.CUSTOMER_MANAGE,
        Permission.SUPPLIER_VIEW,
        Permission.SUPPLIER_MANAGE,
        Permission.CREDIT_VIEW,
        Permission.CREDIT_CREATE,
        Permission.CREDIT_PAYMENT_RECORD,
        Permission.CREDIT_DUEDATE_CHANGE,
        Permission.CREDIT_FOLLOWUP,
        Permission.SHOP_VIEW,
        Permission.SHOP_MANAGE,
        Permission.ENQUIRY_VIEW,
        Permission.ENQUIRY_MANAGE,
        Permission.QUOTATION_VIEW,
        Permission.QUOTATION_MANAGE,
        Permission.REPORT_SALES,
        Permission.REPORT_PROFIT,
        Permission.REPORT_INVENTORY,
        Permission.REPORT_CREDIT,
        # Safe for a manager: the report only ever returns branches the caller
        # is assigned to (PRD 15 — no unauthorised cross-branch visibility).
        Permission.REPORT_BRANCH_COMPARE,
    }
)

#: Salesperson: sales and customer workflows.  No cost, profit or business-wide
#: reporting unless a permission is granted explicitly (PRD 5.1).
_SALESPERSON_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.PRODUCT_VIEW,
        Permission.STOCK_VIEW,
        Permission.SALE_VIEW,
        Permission.SALE_CREATE,
        Permission.CUSTOMER_VIEW,
        Permission.CUSTOMER_MANAGE,
        Permission.CREDIT_VIEW,
        Permission.CREDIT_CREATE,
        Permission.CREDIT_PAYMENT_RECORD,
        Permission.CREDIT_FOLLOWUP,
        Permission.QUOTATION_VIEW,
        Permission.QUOTATION_MANAGE,
        Permission.ENQUIRY_VIEW,
    }
)

#: Stock user: receiving, transfers, counts and adjustments.  Cost and margin
#: visibility is withheld by default (PRD 5.1).
_STOCK_USER_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.PRODUCT_VIEW,
        Permission.STOCK_VIEW,
        Permission.STOCK_RECEIVE,
        Permission.STOCK_TRANSFER,
        Permission.STOCK_ADJUST,
        Permission.STOCK_COUNT,
        Permission.SUPPLIER_VIEW,
        Permission.REPORT_INVENTORY,
    }
)

DEFAULT_ROLE_PERMISSIONS: dict[RoleName, frozenset[Permission]] = {
    RoleName.OWNER: ALL_PERMISSIONS,
    RoleName.MANAGER: _MANAGER_PERMISSIONS,
    RoleName.SALESPERSON: _SALESPERSON_PERMISSIONS,
    RoleName.STOCK_USER: _STOCK_USER_PERMISSIONS,
}

ROLE_DESCRIPTIONS: dict[RoleName, str] = {
    RoleName.OWNER: "Full authority over the business, its branches, users and settings.",
    RoleName.MANAGER: "Operational access for assigned branches, including reports.",
    RoleName.SALESPERSON: "Sales and customer workflows without cost or profit visibility.",
    RoleName.STOCK_USER: "Receiving, transfers, counts and adjustments.",
}


def permissions_for_role(role: RoleName | str) -> frozenset[Permission]:
    return DEFAULT_ROLE_PERMISSIONS.get(RoleName(role), frozenset())
