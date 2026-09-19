"""SQLAlchemy models.

Importing this package registers every mapper, which Alembic autogeneration and
``Base.metadata.create_all`` both rely on.
"""

from app.models.access import (  # noqa: F401
    BranchAssignment,
    Role,
    RolePermission,
    TenantMembership,
    User,
    UserPermissionGrant,
)
from app.models.catalogue import (  # noqa: F401
    Category,
    PricingBasis,
    PricingRule,
    Product,
    ProductVariant,
)
from app.models.commerce import (  # noqa: F401
    CustomerEnquiry,
    EnquiryStatus,
    OnlineStore,
    Quotation,
    QuotationLine,
    QuotationStatus,
)
from app.models.contacts import Customer, Supplier  # noqa: F401
from app.models.credit import (  # noqa: F401
    CreditKind,
    CreditStatus,
    CreditTransaction,
    FollowUpActivity,
    Reminder,
    ReminderChannel,
    ReminderKind,
    ReminderStatus,
)
from app.models.inventory import (  # noqa: F401
    MovementReason,
    StockBalance,
    StockCount,
    StockCountLine,
    StockMovement,
    StockTransfer,
    StockTransferLine,
    TransferStatus,
)
from app.models.organisation import Branch, StockLocation  # noqa: F401
from app.models.platform import (  # noqa: F401
    AuditEvent,
    FeatureFlag,
    PlatformAdmin,
    Subscription,
    SubscriptionPlan,
    SubscriptionStatus,
    Tenant,
    TenantStatus,
)
from app.models.purchasing import Purchase, PurchaseLine, PurchaseStatus  # noqa: F401
from app.models.sales import (  # noqa: F401
    Payment,
    PaymentDirection,
    PaymentMethod,
    Sale,
    SaleLine,
    SaleStatus,
)
from app.models.system import (  # noqa: F401
    FileAsset,
    ImportJob,
    ImportJobStatus,
    ImportRowError,
    Notification,
)

__all__ = [name for name in dir() if not name.startswith("_")]
