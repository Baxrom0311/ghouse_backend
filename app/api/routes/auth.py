import time
from collections import defaultdict
from datetime import timedelta
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, field_validator
from sqlmodel import Session, select

from app.api.deps import get_current_user, get_db
from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    get_password_hash,
    verify_password,
)
from app.models.user import (
    User,
    UserCreate,
    UserLogin,
    UserRead,
    UserUpdate,
    validate_password_strength,
)
from app.services.tenant_service import ensure_personal_tenant

try:
    import redis
    from redis import Redis
except ImportError:  # pragma: no cover - optional runtime dependency
    redis = None
    Redis = None  # type: ignore[assignment]

router = APIRouter(prefix="/auth", tags=["auth"])
REFRESH_COOKIE_NAME = "agroai_refresh_token"
logger = logging.getLogger(__name__)

# --- In-memory rate limiter ---
_AUTH_RATE_LIMIT_MAX = 10  # max attempts
_AUTH_RATE_LIMIT_WINDOW = 60  # seconds
_auth_attempts: dict[str, list[float]] = defaultdict(list)
_redis_client: Redis | None = None
_redis_unavailable_logged = False


def _get_redis_client() -> Redis | None:
    global _redis_client, _redis_unavailable_logged
    if settings.APP_ENV == "test":
        return None
    if not settings.REDIS_URL or redis is None:
        return None
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=0.2,
            socket_timeout=0.2,
        )
    try:
        _redis_client.ping()
    except redis.RedisError as exc:
        if settings.is_production:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Rate limiter is unavailable",
            ) from exc
        if not _redis_unavailable_logged:
            logger.warning("Redis rate limiter unavailable; using in-memory fallback")
            _redis_unavailable_logged = True
        return None
    return _redis_client


def _check_rate_limit(request: Request) -> None:
    if settings.APP_ENV == "test":
        return
    client_ip = request.client.host if request.client else "unknown"
    redis_client = _get_redis_client()
    if redis_client is not None:
        key = f"rate-limit:auth:{client_ip}"
        attempts = redis_client.incr(key)
        if attempts == 1:
            redis_client.expire(key, _AUTH_RATE_LIMIT_WINDOW)
        if attempts > _AUTH_RATE_LIMIT_MAX:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many attempts. Please try again later.",
            )
        return

    now = time.monotonic()
    window_start = now - _AUTH_RATE_LIMIT_WINDOW
    attempts = _auth_attempts[client_ip]
    # Remove expired entries
    _auth_attempts[client_ip] = [t for t in attempts if t > window_start]
    if len(_auth_attempts[client_ip]) >= _AUTH_RATE_LIMIT_MAX:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Please try again later.",
        )
    _auth_attempts[client_ip].append(now)


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserRead


class TokenRefreshRequest(BaseModel):
    refresh_token: str | None = None


class TokenRefreshResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def new_password_is_strong(cls, password: str) -> str:
        return validate_password_strength(password)


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        path="/api/auth",
    )


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(request: Request, user_data: UserCreate, db: Session = Depends(get_db)):
    """Register a new user."""
    _check_rate_limit(request)
    # Check if email already exists
    statement = select(User).where(User.email == user_data.email)
    existing_user = db.exec(statement).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered"
        )

    # Create new user
    hashed_password = get_password_hash(user_data.password)
    db_user = User(
        email=user_data.email,
        first_name=user_data.first_name,
        last_name=user_data.last_name,
        hashed_password=hashed_password,
    )
    db.add(db_user)
    db.flush()
    ensure_personal_tenant(db, db_user)
    db.commit()
    db.refresh(db_user)

    return db_user


@router.post("/login", response_model=LoginResponse)
def login(
    request: Request,
    response: Response,
    credentials: UserLogin,
    db: Session = Depends(get_db),
):
    """Login and get an access token."""
    _check_rate_limit(request)
    statement = select(User).where(User.email == credentials.email)
    user = db.exec(statement).first()

    if not user or not verify_password(credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user"
        )

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        subject=user.id, expires_delta=access_token_expires
    )
    refresh_token = create_refresh_token(
        subject=user.id,
        expires_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )
    _set_refresh_cookie(response, refresh_token)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": UserRead.model_validate(user),
    }


@router.post("/refresh", response_model=TokenRefreshResponse)
def refresh_token(
    request: Request,
    response: Response,
    token_request: TokenRefreshRequest | None = None,
    db: Session = Depends(get_db),
):
    raw_refresh_token = (
        token_request.refresh_token
        if token_request and token_request.refresh_token
        else request.cookies.get(REFRESH_COOKIE_NAME)
    )
    payload = decode_refresh_token(raw_refresh_token or "")
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    next_refresh_token = create_refresh_token(
        subject=user.id,
        expires_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )
    _set_refresh_cookie(response, next_refresh_token)

    return {
        "access_token": create_access_token(
            subject=user.id,
            expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        ),
        "refresh_token": next_refresh_token,
        "token_type": "bearer",
    }


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response):
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path="/api/auth",
        secure=settings.is_production,
        samesite="lax",
    )


@router.get("/whoami", response_model=UserRead)
def whoami(current_user: User = Depends(get_current_user)):
    """Get current User."""
    return UserRead.model_validate(current_user)


@router.patch("/profile/edit", response_model=UserRead)
def edit_profile(
    user_in: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Edit user profile."""
    update_data = user_in.model_dump(exclude_unset=True)

    for key, value in update_data.items():
        setattr(current_user, key, value)

    db.add(current_user)
    db.commit()
    db.refresh(current_user)

    return UserRead.model_validate(current_user)


@router.post("/password/change", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    password_change: PasswordChangeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(
        password_change.current_password, current_user.hashed_password
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    current_user.hashed_password = get_password_hash(password_change.new_password)
    db.add(current_user)
    db.commit()
