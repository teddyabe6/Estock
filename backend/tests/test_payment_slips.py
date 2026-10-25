"""Proof of payment a buyer sends a seller (PRD 13).

There is no payment gateway, and that is the design. An Ethiopian buyer
transfers by telebirr, CBE Birr or a bank deposit and then sends the seller
the screenshot; the seller checks their own account and confirms. These tests
pin what that means:

* A slip is a **claim**, not money. Sending one changes nothing about what the
  shop is owed or owns — otherwise a stranger with a share link could write to
  a shop's ledger by uploading a picture.
* It can only be sent against a proforma that has a price, because there is
  nothing to pay before that.
* The file is private. It is somebody's banking document, so it is served
  through the shop's own session and never on a public link.
* Accepting it is a judgement the seller makes, recorded with their name, and
  it still posts nothing: the money reaches the books through the one existing
  payment path.
"""

from __future__ import annotations

import io
from datetime import date
from decimal import Decimal

import pytest

from app.core.errors import ConflictError, ValidationError
from app.models.commerce import PaymentSlip, PaymentSlipStatus, QuotationStatus
from app.models.system import FileAsset, Notification, NotificationKind
from app.services.commerce import (
    MAX_SLIPS_PER_QUOTATION,
    PaymentSlipInput,
    attach_payment_slip,
)

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _slip(**kwargs) -> PaymentSlipInput:
    return PaymentSlipInput(
        filename=kwargs.pop("filename", "telebirr.png"),
        content_type=kwargs.pop("content_type", "image/png"),
        content=kwargs.pop("content", PNG),
        **kwargs,
    )


@pytest.fixture()
def sent_proforma(db, business):
    """A proforma the seller has priced and sent, which is what can be paid."""
    from app.models.commerce import OnlineStore
    from app.services.commerce import (
        BasketItem,
        get_public_store,
        request_quotation,
        send_quotation,
    )

    shopfront = db.query(OnlineStore).filter_by(tenant_id=business.tenant.id).one()
    shopfront.is_published = True
    db.flush()

    product = business.add_product(
        "Berbere 1kg", selling_price="450", opening_stock="20", is_published=True
    )
    store, tenant = get_public_store(db, shopfront.slug)
    quotation = request_quotation(
        db,
        store,
        tenant,
        items=[BasketItem(product.default_variant.id, Decimal("2"))],
        contact_name="Abebe Kebede",
        contact_phone="0911223344",
    )
    send_quotation(db, business.ctx, quotation.id)
    db.flush()
    assert quotation.status == QuotationStatus.SENT
    return quotation


# --------------------------------------------------------------------------- #
# Sending one
# --------------------------------------------------------------------------- #


def test_a_buyer_can_send_proof_without_an_account(db, business, sent_proforma):
    """They have a share link and nothing else — that is the whole point."""
    slip = attach_payment_slip(
        db,
        sent_proforma.share_token,
        _slip(
            amount_claimed=Decimal("900.00"),
            method="telebirr",
            reference="TB-55512345",
            paid_on=date(2026, 6, 1),
            sender_name="Abebe Kebede",
            sender_phone="0911223344",
        ),
    )

    assert slip.status == PaymentSlipStatus.SUBMITTED
    assert slip.amount_claimed == Decimal("900.00")
    assert slip.reference == "TB-55512345"
    assert slip.sender_name == "Abebe Kebede"
    assert slip.tenant_id == business.tenant.id


def test_sending_proof_moves_no_money(db, business, sent_proforma):
    """The claim must not touch the ledger, or a picture would be payment."""
    from app.models.sales import Payment

    before = db.query(Payment).count()
    attach_payment_slip(
        db, sent_proforma.share_token, _slip(amount_claimed=Decimal("900.00"))
    )

    assert db.query(Payment).count() == before, "no payment was posted"
    assert sent_proforma.status == QuotationStatus.SENT, "the proforma is unchanged"


def test_proof_cannot_be_sent_before_the_seller_has_quoted(db, business, sent_proforma):
    """Nothing is owed yet, so there is nothing to pay.

    A basket request arrives as REQUESTED and only becomes something to pay
    once the seller has priced it and sent it.
    """
    sent_proforma.status = QuotationStatus.REQUESTED
    db.flush()

    with pytest.raises(ConflictError) as raised:
        attach_payment_slip(db, sent_proforma.share_token, _slip())
    assert "not sent a price" in str(raised.value).lower()


@pytest.mark.parametrize(
    "content_type", ["text/html", "application/zip", "application/x-msdownload"]
)
def test_only_a_picture_or_a_pdf_is_accepted(db, sent_proforma, content_type):
    with pytest.raises(ValidationError) as raised:
        attach_payment_slip(
            db, sent_proforma.share_token, _slip(content_type=content_type)
        )
    assert "image/png" in str(raised.value.details["allowed"])


def test_an_empty_file_is_refused(db, sent_proforma):
    with pytest.raises(ValidationError):
        attach_payment_slip(db, sent_proforma.share_token, _slip(content=b""))


def test_there_is_a_ceiling_on_slips_per_proforma(db, sent_proforma):
    """Otherwise one link is a way to fill a shop's storage."""
    for _ in range(MAX_SLIPS_PER_QUOTATION):
        attach_payment_slip(db, sent_proforma.share_token, _slip())

    with pytest.raises(ConflictError) as raised:
        attach_payment_slip(db, sent_proforma.share_token, _slip())
    assert "already several slips" in str(raised.value).lower()


def test_a_cancelled_proforma_takes_no_proof(db, sent_proforma):
    from app.core.errors import NotFoundError

    sent_proforma.status = QuotationStatus.CANCELLED
    db.flush()
    with pytest.raises(NotFoundError):
        attach_payment_slip(db, sent_proforma.share_token, _slip())


def test_the_shop_is_told_so_a_slip_does_not_sit_unseen(db, business, sent_proforma):
    attach_payment_slip(
        db,
        sent_proforma.share_token,
        _slip(amount_claimed=Decimal("900.00"), sender_name="Abebe"),
    )

    notices = (
        db.query(Notification)
        .filter(Notification.kind == NotificationKind.PAYMENT_SLIP)
        .all()
    )
    assert notices, "somebody at the shop is told"
    assert sent_proforma.number in notices[0].title
    assert "Abebe" in notices[0].body


def test_sending_proof_is_audited_against_the_shop(db, business, sent_proforma):
    from app.models.platform import AuditEvent

    attach_payment_slip(
        db, sent_proforma.share_token, _slip(sender_name="Abebe", reference="TB-77")
    )
    event = (
        db.query(AuditEvent)
        .filter(AuditEvent.action == "payment_slip.submitted")
        .one()
    )
    assert "Abebe" in (event.actor_label or "")
    assert sent_proforma.number in (event.summary or "")
    assert "TB-77" in (event.payload_json or "")


# --------------------------------------------------------------------------- #
# The file is private
# --------------------------------------------------------------------------- #


def test_the_slip_file_is_not_public(db, business, sent_proforma):
    """Somebody's banking document has no business on a public URL."""
    slip = attach_payment_slip(db, sent_proforma.share_token, _slip())
    asset = db.get(FileAsset, slip.file_asset_id)

    assert asset.is_public is False
    assert asset.tenant_id == business.tenant.id


def test_the_public_file_route_refuses_a_slip(client, db, business, sent_proforma):
    slip = attach_payment_slip(db, sent_proforma.share_token, _slip())
    db.flush()
    response = client.get(f"/api/v1/public/files/{slip.file_asset_id}")
    assert response.status_code == 404


def test_the_shop_can_open_the_slip_through_its_own_session(
    client, db, business, sent_proforma
):
    slip = attach_payment_slip(db, sent_proforma.share_token, _slip())
    db.flush()

    response = client.get(
        f"/api/v1/shop/payment-slips/{slip.id}/file", headers=business.headers()
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("image/png")
    assert response.content == PNG


def test_another_shop_cannot_open_the_slip(
    client, db, business, other_business, sent_proforma
):
    slip = attach_payment_slip(db, sent_proforma.share_token, _slip())
    db.flush()

    response = client.get(
        f"/api/v1/shop/payment-slips/{slip.id}/file", headers=other_business.headers()
    )
    assert response.status_code == 404, "a foreign row is not found, not forbidden"


# --------------------------------------------------------------------------- #
# The seller's judgement
# --------------------------------------------------------------------------- #


def test_the_seller_accepts_a_slip_and_it_still_posts_nothing(
    client, db, business, sent_proforma
):
    from app.models.sales import Payment

    slip = attach_payment_slip(db, sent_proforma.share_token, _slip())
    db.flush()
    before = db.query(Payment).count()

    response = client.post(
        f"/api/v1/shop/payment-slips/{slip.id}/review",
        json={"accept": True, "note": "Found it in the telebirr statement"},
        headers=business.headers(),
    )
    assert response.status_code == 200, response.json()
    assert response.json()["status"] == "accepted"
    assert response.json()["review_note"] == "Found it in the telebirr statement"

    db.refresh(slip)
    assert slip.reviewed_at is not None
    assert slip.reviewed_by_id is not None
    assert db.query(Payment).count() == before, "accepting is not posting"


def test_the_seller_can_reject_a_slip(client, db, business, sent_proforma):
    slip = attach_payment_slip(db, sent_proforma.share_token, _slip())
    db.flush()

    response = client.post(
        f"/api/v1/shop/payment-slips/{slip.id}/review",
        json={"accept": False, "note": "Nothing arrived"},
        headers=business.headers(),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"


def test_reviewing_is_audited_with_the_person_who_did_it(
    client, db, business, sent_proforma
):
    from app.models.platform import AuditEvent

    slip = attach_payment_slip(db, sent_proforma.share_token, _slip())
    db.flush()
    client.post(
        f"/api/v1/shop/payment-slips/{slip.id}/review",
        json={"accept": True},
        headers=business.headers(),
    ).raise_for_status()

    event = (
        db.query(AuditEvent)
        .filter(AuditEvent.action == "payment_slip.reviewed")
        .one()
    )
    assert event.actor_user_id is not None
    assert "accepted" in (event.summary or "")


def test_a_salesperson_without_quotation_manage_cannot_review(
    client, db, business, sent_proforma
):
    from app.core.permissions import RoleName

    slip = attach_payment_slip(db, sent_proforma.share_token, _slip())
    db.flush()
    user, _ = business.add_user(RoleName.STOCK_USER)

    response = client.post(
        f"/api/v1/shop/payment-slips/{slip.id}/review",
        json={"accept": True},
        headers=business.headers(user),
    )
    assert response.status_code == 403


def test_a_shop_lists_the_slips_against_one_proforma(
    client, db, business, sent_proforma
):
    attach_payment_slip(
        db, sent_proforma.share_token, _slip(reference="FIRST", method="telebirr")
    )
    attach_payment_slip(
        db, sent_proforma.share_token, _slip(reference="SECOND", method="cbe_birr")
    )
    db.flush()

    response = client.get(
        f"/api/v1/shop/quotations/{sent_proforma.id}/payment-slips",
        headers=business.headers(),
    )
    assert response.status_code == 200, response.json()
    items = response.json()["items"]
    assert [item["reference"] for item in items] == ["FIRST", "SECOND"]
    assert all(item["file_asset_id"] for item in items)


def test_one_shop_cannot_see_another_shops_slips(
    client, db, business, other_business, sent_proforma
):
    attach_payment_slip(db, sent_proforma.share_token, _slip())
    db.flush()
    response = client.get(
        f"/api/v1/shop/quotations/{sent_proforma.id}/payment-slips",
        headers=other_business.headers(),
    )
    assert response.status_code == 404


# --------------------------------------------------------------------------- #
# Through the API, the way a buyer's browser does it
# --------------------------------------------------------------------------- #


def test_a_buyer_uploads_a_slip_over_http(client, db, business, sent_proforma):
    response = client.post(
        f"/api/v1/public/quotations/{sent_proforma.share_token}/payment-slip",
        files={"file": ("telebirr.png", io.BytesIO(PNG), "image/png")},
        data={
            "amount": "900.00",
            "method": "telebirr",
            "reference": "TB-90210",
            "sender_name": "Abebe Kebede",
            "sender_phone": "0911223344",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "submitted"
    assert body["amount_claimed"] == "900.00"
    assert body["reference"] == "TB-90210"
    assert "check their account" in body["message"]
    # The buyer is never handed a link to the file they just uploaded.
    assert "file_asset_id" not in body

    assert db.query(PaymentSlip).count() == 1


def test_the_screen_is_told_when_there_is_nothing_to_pay_yet(
    client, db, business, sent_proforma
):
    """The page asks the server rather than working it out again.

    A shop that shows prices to visitors makes amounts visible on an unpriced
    request too, so "there is an amount on screen" is not the same question as
    "is there anything to pay" — which is how the form came to be offered for
    something the server would refuse.
    """
    priced = client.get(f"/api/v1/public/quotations/{sent_proforma.share_token}")
    assert priced.json()["can_send_payment"] is True

    sent_proforma.status = QuotationStatus.REQUESTED
    db.flush()
    unpriced = client.get(f"/api/v1/public/quotations/{sent_proforma.share_token}")
    body = unpriced.json()
    assert body["can_send_payment"] is False
    assert body["amounts_visible"] is True, "the shop shows prices, so amounts show"

    refused = client.post(
        f"/api/v1/public/quotations/{sent_proforma.share_token}/payment-slip",
        files={"file": ("slip.png", io.BytesIO(PNG), "image/png")},
    )
    assert refused.status_code == 409, "and the server refuses, as the flag said"


def test_an_unknown_token_takes_no_upload(client):
    response = client.post(
        "/api/v1/public/quotations/not-a-real-token/payment-slip",
        files={"file": ("slip.png", io.BytesIO(PNG), "image/png")},
    )
    assert response.status_code == 404
