from fastapi import APIRouter, Depends, HTTPException, Response

from app.deps import SESSION_COOKIE, AppContext, current_account, get_ctx, session_cookie
from app.models import Account, DemoAccount, Error, LoginRequest
from app.store import StoredAccount

router = APIRouter()


def to_account(account: StoredAccount) -> Account:
    return Account(
        id=account.id, role=account.role, student_id=account.student_id, external_id=account.external_id
    )


@router.post(
    "/auth/login",
    tags=["Auth"],
    operation_id="login",
    summary="Sign in with an access code or the instructor passcode",
    response_model=Account,
    responses={401: {"model": Error, "description": "The code is not valid."}},
)
def login(body: LoginRequest, response: Response, ctx: AppContext = Depends(get_ctx)):
    account = ctx.identity.authenticate(body.code)
    if account is None:
        raise HTTPException(status_code=401, detail="That code is not valid.")
    token = ctx.sessions.create(account.id)
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", path="/")
    return to_account(account)


@router.get(
    "/auth/me",
    tags=["Auth"],
    operation_id="getCurrentAccount",
    summary="The signed-in account",
    response_model=Account,
    responses={401: {"model": Error, "description": "No valid session."}},
)
def get_current_account(account: StoredAccount = Depends(current_account)):
    return to_account(account)


@router.post(
    "/auth/logout",
    tags=["Auth"],
    operation_id="logout",
    summary="End the session",
    status_code=204,
    response_class=Response,
    responses={401: {"model": Error, "description": "No valid session."}},
)
def logout(
    token: str | None = Depends(session_cookie),
    account: StoredAccount = Depends(current_account),
    ctx: AppContext = Depends(get_ctx),
):
    ctx.sessions.destroy(token)
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get(
    "/demo/accounts",
    tags=["Auth"],
    operation_id="listDemoAccounts",
    summary="Demo accounts and their codes (demo data only)",
    response_model=list[DemoAccount],
    responses={404: {"model": Error, "description": "The active data source is not demo data."}},
)
def list_demo_accounts(ctx: AppContext = Depends(get_ctx)):
    if ctx.db.kind != "toy":
        raise HTTPException(status_code=404, detail="Demo accounts are only available with demo data.")
    return ctx.demo_accounts
