"""Spreadsheet product import (PRD 8.3)."""

from __future__ import annotations

import io
import uuid

from fastapi import APIRouter, File, Form, UploadFile, status
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from pydantic import BaseModel

from app.core.deps import Ctx, DbSession, WritableCtx
from app.core.permissions import Permission
from app.core.tenancy import get_tenant_object
from app.models.system import ImportJob
from app.services.imports import (
    IMPORTABLE_FIELDS,
    commit_import,
    start_import,
    template_columns,
    validate_import,
)

router = APIRouter(prefix="/imports", tags=["import"])


class MappingIn(BaseModel):
    """``{"Column header in the file": "field_name"}``."""

    mapping: dict[str, str]


class CommitIn(BaseModel):
    skip_rows_with_errors: bool = True
    branch_id: uuid.UUID | None = None


@router.get("/fields")
def importable_fields(ctx: Ctx) -> list[dict]:
    ctx.require(Permission.PRODUCT_IMPORT)
    return template_columns()


@router.get("/template")
def download_template(ctx: Ctx):
    """The downloadable spreadsheet template (PRD 8.3)."""
    ctx.require(Permission.PRODUCT_IMPORT)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Products"
    headers = [spec["label"] for spec in IMPORTABLE_FIELDS.values()]
    sheet.append(headers)
    sheet.append(
        ["Sample product", "SKU-001", "1234567890123", "Drinks", "", "pcs", "", "100", "10", "0", "150", "12", "3", "5"]
    )
    for index, _ in enumerate(headers, start=1):
        sheet.column_dimensions[sheet.cell(row=1, column=index).column_letter].width = 20

    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="estock-product-template.xlsx"'},
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload(
    ctx: WritableCtx,
    db: DbSession,
    file: UploadFile = File(...),
    branch_id: uuid.UUID | None = Form(None),
) -> dict:
    """Step 1: upload the file and get the detected headers and a suggested mapping."""
    content = await file.read()
    job, headers, mapping = start_import(
        db,
        ctx,
        filename=file.filename or "upload.xlsx",
        content_type=file.content_type or "application/octet-stream",
        content=content,
        branch_id=branch_id,
    )
    return {
        "job_id": str(job.id),
        "filename": job.original_filename,
        "total_rows": job.total_rows,
        "detected_headers": headers,
        "suggested_mapping": mapping,
        "available_fields": template_columns(),
    }


@router.post("/{job_id}/validate")
def validate(job_id: uuid.UUID, payload: MappingIn, ctx: WritableCtx, db: DbSession) -> dict:
    """Step 2: confirm the mapping and preview what will happen."""
    preview = validate_import(db, ctx, job_id, payload.mapping)
    return {
        "job_id": str(preview.job_id),
        "total_rows": preview.total_rows,
        "valid_rows": preview.valid_rows,
        "error_rows": preview.error_rows,
        "duplicate_rows": preview.duplicate_rows,
        "sample": preview.sample,
        "issues": [
            {
                "row_number": issue.row_number,
                "column": issue.column,
                "code": issue.code,
                "message": issue.message,
                "value": issue.raw_value,
            }
            for issue in preview.issues[:200]
        ],
    }


@router.post("/{job_id}/commit")
def commit(job_id: uuid.UUID, payload: CommitIn, ctx: WritableCtx, db: DbSession) -> dict:
    """Step 3: write the valid rows and report exactly what happened."""
    job = commit_import(
        db,
        ctx,
        job_id,
        skip_rows_with_errors=payload.skip_rows_with_errors,
        branch_id=payload.branch_id,
    )
    return {
        "job_id": str(job.id),
        "status": str(job.status),
        "total_rows": job.total_rows,
        "created_products": job.created_products,
        "skipped_rows": job.skipped_rows,
        "error_rows": job.error_rows,
    }


@router.get("/{job_id}")
def get_job(job_id: uuid.UUID, ctx: Ctx, db: DbSession) -> dict:
    ctx.require(Permission.PRODUCT_IMPORT)
    job = get_tenant_object(db, ImportJob, job_id, ctx.tenant_id, label="Import job")
    return {
        "job_id": str(job.id),
        "status": str(job.status),
        "filename": job.original_filename,
        "total_rows": job.total_rows,
        "valid_rows": job.valid_rows,
        "error_rows": job.error_rows,
        "created_products": job.created_products,
        "skipped_rows": job.skipped_rows,
        "errors": [
            {
                "row_number": error.row_number,
                "column": error.column_name,
                "code": error.code,
                "message": error.message,
            }
            for error in job.row_errors[:200]
        ],
    }
