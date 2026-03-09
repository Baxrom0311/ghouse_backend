from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.deps import get_current_user, get_db
from app.core.config import settings
from app.core.security import (
    create_access_token,
    get_password_hash,
    verify_password,
)
from app.models.user import User, UserCreate, UserLogin, UserRead, UserUpdate

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


# @router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
@router.post("/register", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
def register(user_data: UserCreate, db: Session = Depends(get_db)):
    """Register a new user. **This endpoint is disabled temporarily!**"""
    # Disable the endpoint temporarily
    raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
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
    db.commit()
    db.refresh(db_user)

    return db_user


@router.post("/login", response_model=LoginResponse)
def login(credentials: UserLogin, db: Session = Depends(get_db)):
    """Login and get access token. Use `test1@example.com`, pass `test`"""
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

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": UserRead.model_validate(user),
    }


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
