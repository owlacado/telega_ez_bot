from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from hub.audit.service import audit
from hub.core.database import session
from hub.expenses import service
from hub.expenses.models import TechnicianExpense
from hub.expenses.schemas import ExpenseForm, ExpenseInput, ExpenseList, ExpenseRead, ExpenseReceipt
from hub.technicians.service import require_technician
from hub.work_reports.models import TechnicianFormSession
from hub.work_reports.router import capability

router = APIRouter(tags=["expenses"])
FORM_PATHS = {"/api/technician-forms/expense", "/api/technician-forms/expense/submit"}


@router.post("/api/technician-forms/expense", response_model=ExpenseForm)
async def open_form(request: Request):
    return await service.open_form(request.app.state.session_factory, capability(request))


@router.post("/api/technician-forms/expense/submit", response_model=ExpenseReceipt)
async def submit(payload: ExpenseInput, request: Request):
    return await service.submit(request.app.state.session_factory, capability(request), payload)


@router.get("/api/technicians/{technician_id}/expenses", response_model=ExpenseList)
async def expenses(
    technician_id: UUID, limit: int = Query(20, ge=1, le=100), db: AsyncSession = Depends(session)
):
    tech = await require_technician(db, technician_id)
    return await service.list_expenses(db, tech, limit)


@router.get("/api/expenses/{expense_id}", response_model=ExpenseRead)
async def expense(expense_id: UUID, db: AsyncSession = Depends(session)):
    row = (
        await db.execute(service.current_expenses().where(TechnicianExpense.id == expense_id))
    ).first()
    if not row:
        raise HTTPException(404, "Expense not found.")
    return service.expense_view(*row)


@router.post(
    "/api/technicians/{technician_id}/expense-sessions/{session_id}/revoke", status_code=204
)
async def revoke(
    technician_id: UUID, session_id: UUID, request: Request, db: AsyncSession = Depends(session)
):
    await require_technician(db, technician_id, lock=True)
    value = await db.get(TechnicianFormSession, session_id, with_for_update=True)
    if not value or value.technician_id != technician_id or value.purpose != "EXPENSE":
        raise HTTPException(404, "Form not found.")
    if value.status == "OPEN":
        value.status = "REVOKED"
        audit(db, "expense.session_revoked", value.id, actor_id=request.state.manager_id)
    await db.commit()
    return Response(status_code=204)
