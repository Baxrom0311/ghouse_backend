from typing import Generator

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session, select

from app.core.db import get_session
from app.core.security import decode_access_token
from app.models.greenhouse import Greenhouse
from app.models.plant import Plant
from app.models.user import User
from app.core.context import ctx_user


security = HTTPBearer(auto_error=False)


def get_db() -> Generator[Session, None, None]:
    """Dependency to get database session."""
    yield from get_session()


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    if user_from_context := ctx_user.get():
        return user_from_context

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    payload = decode_access_token(token)

    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id: str = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.get(User, user_id)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def get_authorized_greenhouse(
    greenhouse_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Greenhouse:
    greenhouse = db.get(Greenhouse, greenhouse_id)
    if greenhouse:
        if greenhouse.owner_id == current_user.id:
            return greenhouse

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="Greenhouse not found"
    )


def get_authorized_plant(
    plant_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Plant:
    """
    Fetch a plant by ID, ensuring it belongs to a greenhouse
    owned by the current user.
    """
    statement = (
        select(Plant)
        .join(Greenhouse)
        .where(Plant.id == plant_id)
        .where(Greenhouse.owner_id == current_user.id)
    )
    plant = db.exec(statement).first()

    if not plant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Plant not found"
        )

    return plant


# def get_authorized_greenhouse_device(
#     device_id: int,
#     db: Session = Depends(get_db),
#     greenhouse: Greenhouse = Depends(get_authorized_greenhouse),
# ) -> Device:
#     device = db.get(Device, device_id)
#     if device:
#         if device.greenhouse_id == greenhouse.id:
#             return device

#     raise HTTPException(
#         status_code=status.HTTP_404_NOT_FOUND, detail="Device not found"
#     )
