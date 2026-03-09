from functools import lru_cache

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.deps import (
    get_authorized_greenhouse,
    get_authorized_plant,
    get_current_user,
    get_db,
)
from app.models.greenhouse import Greenhouse
from app.models.plant import Plant, PlantCreate, PlantRead, PlantType, PlantUpdate
from app.models.user import User

router = APIRouter(prefix="/greenhouses/{greenhouse_id}/plants", tags=["plants"])


class ResponseOK(BaseModel):
    ok: bool = True


@lru_cache()
def get_cached_plant_types():
    return [plant for plant in PlantType]


@router.get("/plant-types", response_model=list[PlantType])
def get_plant_types(current_user: User = Depends(get_current_user)):
    """Return a list of all available plant types."""
    return get_cached_plant_types()


@router.post("", response_model=PlantRead, status_code=status.HTTP_201_CREATED)
def create_plant(
    plant_data: PlantCreate,
    greenhouse: Greenhouse = Depends(get_authorized_greenhouse),
    db: Session = Depends(get_db),
):
    """Create a new plant."""
    db_plant = Plant(
        greenhouse_id=greenhouse.id,
        name=plant_data.name,
        type=plant_data.type,
        variety=plant_data.variety,
    )
    db.add(db_plant)
    db.commit()
    db.refresh(db_plant)
    return PlantRead.model_validate(db_plant)


@router.get("", response_model=list[PlantRead])
def list_plants(
    greenhouse: Greenhouse = Depends(get_authorized_greenhouse),
    db: Session = Depends(get_db),
) -> list[PlantRead]:
    """List all plants of greenhouse."""

    statement = select(Plant).where(Plant.greenhouse_id == greenhouse.id)
    plants: list[Plant] = db.exec(statement).all()

    read_greenhouses = [PlantRead.model_validate(g) for g in plants]
    return read_greenhouses


@router.get("/{plant_id}", response_model=PlantRead)
def get_plant(
    plant: Plant = Depends(get_authorized_plant),
    db: Session = Depends(get_db),
):
    return PlantRead.model_validate(plant, context={"session": db})


@router.patch("/{plant_id}", response_model=PlantRead)
def edit_plant(
    plant_update: PlantUpdate,
    plant: Plant = Depends(get_authorized_plant),
    db: Session = Depends(get_db),
):
    update_data = plant_update.model_dump(exclude_unset=True)

    for key, value in update_data.items():
        setattr(plant, key, value)

    db.add(plant)
    db.commit()
    db.refresh(plant)

    return plant


@router.delete("/{plant_id}", response_model=ResponseOK)
def delete_plant(
    plant: Plant = Depends(get_authorized_plant),
    db: Session = Depends(get_db),
):
    db.delete(plant)
    db.commit()
    return {"ok": True}
