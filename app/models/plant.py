from datetime import datetime, timezone
from enum import Enum

from sqlmodel import Field, Relationship, SQLModel


class PlantType(str, Enum):
    tomato = "tomato"
    cucumber = "cucumber"
    lettuce = "lettuce"
    pepper = "pepper"
    spinach = "spinach"
    kale = "kale"
    eggplant = "eggplant"
    zucchini = "zucchini"
    broccoli = "broccoli"
    cauliflower = "cauliflower"
    strawberry = "strawberry"
    blueberry = "blueberry"
    raspberry = "raspberry"
    melon = "melon"
    watermelon = "watermelon"
    basil = "basil"
    mint = "mint"
    parsley = "parsley"
    cilantro = "cilantro"
    rosemary = "rosemary"
    thyme = "thyme"
    oregano = "oregano"
    arugula = "arugula"
    bok_choy = "bok_choy"
    microgreens = "microgreens"
    rose = "rose"
    tulip = "tulip"
    orchid = "orchid"
    sunflower = "sunflower"
    mushroom = "mushroom"
    chili = "chili"
    ginger = "ginger"
    turmeric = "turmeric"


class PlantBase(SQLModel):
    name: str | None
    type: PlantType
    variety: str | None = None


class Plant(PlantBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    greenhouse_id: int = Field(foreign_key="greenhouse.id")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )

    # Relationships
    greenhouse: "Greenhouse" = Relationship(back_populates="plants")


class PlantCreate(PlantBase):
    pass


class PlantRead(PlantBase):
    id: int | None
    greenhouse_id: int


class PlantUpdate(SQLModel):
    name: str | None = None
    type: PlantType | None = None
    variety: str | None = None
