"""API v1 router aggregation."""

from fastapi import APIRouter

from app.api.v1.routers import (
    auth,
    business,
    contacts,
    credit,
    imports,
    notifications,
    platform_admin,
    products,
    public,
    purchases,
    reports,
    sales,
    shop,
    stock,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(business.router)
api_router.include_router(products.router)
api_router.include_router(stock.router)
api_router.include_router(sales.router)
api_router.include_router(purchases.router)
api_router.include_router(contacts.router)
api_router.include_router(credit.router)
api_router.include_router(shop.router)
api_router.include_router(reports.router)
api_router.include_router(imports.router)
api_router.include_router(notifications.router)
api_router.include_router(public.router)
api_router.include_router(platform_admin.router)

__all__ = ["api_router"]
