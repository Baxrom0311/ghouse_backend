from pydantic import EmailStr
from sqlmodel import Field, SQLModel


class UserBase(SQLModel):
    email: str = Field(unique=True, index=True)
    first_name: str
    last_name: str | None = None
    is_active: bool = True


class User(UserBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    hashed_password: str


class UserCreate(SQLModel):
    email: EmailStr
    password: str
    first_name: str
    last_name: str | None = None


class UserRead(UserBase):
    id: int


class UserUpdate(SQLModel):
    first_name: str | None = None
    last_name: str | None = None


class UserLogin(SQLModel):
    email: EmailStr
    password: str
