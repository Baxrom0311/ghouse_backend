from pydantic import EmailStr, field_validator
from sqlmodel import Field, SQLModel


def validate_password_strength(password: str) -> str:
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters long")
    if len(password) > 128:
        raise ValueError("Password must be at most 128 characters long")
    if not any(char.isalpha() for char in password):
        raise ValueError("Password must contain at least one letter")
    if not any(char.isdigit() for char in password):
        raise ValueError("Password must contain at least one number")
    return password


class UserBase(SQLModel):
    email: str = Field(unique=True, index=True)
    first_name: str
    last_name: str | None = None
    is_active: bool = True


class User(UserBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    hashed_password: str
    token_version: int = Field(default=0)


class UserCreate(SQLModel):
    email: EmailStr
    password: str
    first_name: str
    last_name: str | None = None

    @field_validator("password")
    @classmethod
    def password_is_strong(cls, password: str) -> str:
        return validate_password_strength(password)


class UserRead(UserBase):
    id: int


class UserUpdate(SQLModel):
    first_name: str | None = None
    last_name: str | None = None


class UserLogin(SQLModel):
    email: EmailStr
    password: str
