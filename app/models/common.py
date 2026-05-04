from pydantic import BaseModel


class ResponseOK(BaseModel):
    ok: bool = True
