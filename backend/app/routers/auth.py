import secrets

from fastapi import APIRouter, Depends, HTTPException, Response

from app.deps import SESSION_COOKIE, AppContext, current_account, get_ctx, session_cookie
from app.mock_db import MockAccount
from app.models import Account, DemoAccount, Error, GoogleLoginRequest, LoginRequest

router = APIRouter()

GOOGLE_TOKEN_PREFIX = "demo-google:"


def mock_verify_google_token(id_token: str) -> str | None:
    """Stand-in for verifying a Google ID token: accepts `demo-google:<email>`, returns the email."""
    if id_token.startswith(GOOGLE_TOKEN_PREFIX):
        return id_token.removeprefix(GOOGLE_TOKEN_PREFIX) or None
    return None


def to_account(account: MockAccount) -> Account:
    return Account(
        id=account.id, role=account.role, student_id=account.student_id, external_id=account.external_id
    )


def start_session(response: Response, ctx: AppContext, account: MockAccount) -> Account:
    token = ctx.sessions.create(account.id)
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", path="/")
    return to_account(account)


def same(a: str, b: str) -> bool:
    return secrets.compare_digest(a.encode(), b.encode())


@router.post(
    "/auth/login",
    tags=["Auth"],
    operation_id="login",
    summary="Sign in with a teacher-created account",
    response_model=Account,
    responses={401: {"model": Error, "description": "Wrong email or password."}},
)
def login(body: LoginRequest, response: Response, ctx: AppContext = Depends(get_ctx)):
    for account in ctx.accounts():
        if account.email.casefold() == body.email.casefold() and same(account.password, body.password):
            return start_session(response, ctx, account)
    raise HTTPException(status_code=401, detail="Incorrect email or password.")


@router.post(
    "/auth/google",
    tags=["Auth"],
    operation_id="loginWithGoogle",
    summary="Sign in with Google",
    response_model=Account,
    responses={
        401: {"model": Error, "description": "The token is not valid."},
        403: {"model": Error, "description": "The email is not on the roster."},
    },
)
def login_with_google(body: GoogleLoginRequest, response: Response, ctx: AppContext = Depends(get_ctx)):
    email = ctx.verify_google_token(body.id_token)
    if email is None:
        raise HTTPException(status_code=401, detail="That Google sign-in is not valid.")
    account = next((a for a in ctx.accounts() if a.email.casefold() == email.casefold()), None)
    if account is None:
        raise HTTPException(status_code=403, detail="That email is not on the class roster.")
    return start_session(response, ctx, account)


@router.get(
    "/auth/me",
    tags=["Auth"],
    operation_id="getCurrentAccount",
    summary="The signed-in account",
    response_model=Account,
    responses={401: {"model": Error, "description": "No valid session."}},
)
def get_current_account(account: MockAccount = Depends(current_account)):
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
    account: MockAccount = Depends(current_account),
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
    summary="Demo accounts (demo data only)",
    response_model=list[DemoAccount],
    responses={404: {"model": Error, "description": "The active data source is not demo data."}},
)
def list_demo_accounts(ctx: AppContext = Depends(get_ctx)):
    if ctx.db.kind != "toy":
        raise HTTPException(status_code=404, detail="Demo accounts are only available with demo data.")
    return [DemoAccount(**to_account(a).model_dump(), email=a.email, password=a.password) for a in ctx.accounts()]
