"""Optimal growing conditions reference for each plant type.

Used by the AI system prompt to provide plant-specific recommendations
and by the auto-settings feature to suggest sensor thresholds.
"""

from app.models.plant import PlantType

# Format: {PlantType: {sensor: (min, max)}}
# temperature (°C), humidity (%), moisture (%), light (0-100%), air/co2 (ppm)
PLANT_CONDITIONS: dict[PlantType, dict[str, tuple[int, int]]] = {
    PlantType.tomato: {"temperature": (18, 28), "humidity": (50, 70), "moisture": (40, 70), "light": (60, 90), "air": (400, 1000)},
    PlantType.cucumber: {"temperature": (20, 30), "humidity": (60, 80), "moisture": (50, 80), "light": (50, 80), "air": (400, 1000)},
    PlantType.lettuce: {"temperature": (15, 22), "humidity": (50, 70), "moisture": (40, 65), "light": (30, 60), "air": (400, 800)},
    PlantType.pepper: {"temperature": (20, 30), "humidity": (50, 70), "moisture": (40, 70), "light": (60, 90), "air": (400, 1000)},
    PlantType.spinach: {"temperature": (10, 20), "humidity": (40, 60), "moisture": (40, 65), "light": (30, 60), "air": (400, 800)},
    PlantType.kale: {"temperature": (10, 22), "humidity": (40, 60), "moisture": (40, 65), "light": (40, 70), "air": (400, 800)},
    PlantType.eggplant: {"temperature": (21, 30), "humidity": (50, 70), "moisture": (45, 70), "light": (60, 90), "air": (400, 1000)},
    PlantType.zucchini: {"temperature": (18, 28), "humidity": (50, 70), "moisture": (45, 75), "light": (60, 85), "air": (400, 1000)},
    PlantType.broccoli: {"temperature": (15, 22), "humidity": (50, 70), "moisture": (45, 70), "light": (40, 70), "air": (400, 800)},
    PlantType.cauliflower: {"temperature": (15, 22), "humidity": (50, 70), "moisture": (45, 70), "light": (40, 70), "air": (400, 800)},
    PlantType.strawberry: {"temperature": (15, 25), "humidity": (50, 70), "moisture": (40, 65), "light": (50, 80), "air": (400, 800)},
    PlantType.blueberry: {"temperature": (15, 25), "humidity": (50, 70), "moisture": (45, 70), "light": (50, 80), "air": (400, 800)},
    PlantType.raspberry: {"temperature": (15, 25), "humidity": (50, 65), "moisture": (40, 65), "light": (50, 80), "air": (400, 800)},
    PlantType.melon: {"temperature": (22, 32), "humidity": (50, 70), "moisture": (45, 70), "light": (70, 95), "air": (400, 1000)},
    PlantType.watermelon: {"temperature": (22, 32), "humidity": (50, 70), "moisture": (45, 70), "light": (70, 95), "air": (400, 1000)},
    PlantType.basil: {"temperature": (20, 28), "humidity": (40, 60), "moisture": (35, 60), "light": (50, 80), "air": (400, 800)},
    PlantType.mint: {"temperature": (15, 25), "humidity": (50, 70), "moisture": (45, 70), "light": (30, 60), "air": (400, 800)},
    PlantType.parsley: {"temperature": (15, 25), "humidity": (50, 70), "moisture": (40, 65), "light": (30, 60), "air": (400, 800)},
    PlantType.cilantro: {"temperature": (15, 25), "humidity": (40, 60), "moisture": (35, 60), "light": (30, 60), "air": (400, 800)},
    PlantType.rosemary: {"temperature": (15, 28), "humidity": (30, 50), "moisture": (25, 45), "light": (60, 90), "air": (400, 800)},
    PlantType.thyme: {"temperature": (15, 28), "humidity": (30, 50), "moisture": (25, 45), "light": (60, 90), "air": (400, 800)},
    PlantType.oregano: {"temperature": (15, 28), "humidity": (30, 50), "moisture": (25, 45), "light": (60, 90), "air": (400, 800)},
    PlantType.arugula: {"temperature": (10, 20), "humidity": (40, 60), "moisture": (40, 65), "light": (30, 60), "air": (400, 800)},
    PlantType.bok_choy: {"temperature": (15, 22), "humidity": (50, 70), "moisture": (45, 70), "light": (30, 60), "air": (400, 800)},
    PlantType.microgreens: {"temperature": (18, 24), "humidity": (50, 70), "moisture": (50, 75), "light": (40, 70), "air": (400, 800)},
    PlantType.rose: {"temperature": (15, 25), "humidity": (50, 70), "moisture": (40, 65), "light": (60, 90), "air": (400, 800)},
    PlantType.tulip: {"temperature": (12, 20), "humidity": (50, 70), "moisture": (40, 60), "light": (50, 80), "air": (400, 800)},
    PlantType.orchid: {"temperature": (18, 28), "humidity": (60, 80), "moisture": (30, 50), "light": (30, 60), "air": (400, 800)},
    PlantType.sunflower: {"temperature": (18, 28), "humidity": (40, 60), "moisture": (40, 65), "light": (70, 95), "air": (400, 1000)},
    PlantType.mushroom: {"temperature": (15, 22), "humidity": (80, 95), "moisture": (60, 85), "light": (5, 20), "air": (800, 1500)},
    PlantType.chili: {"temperature": (20, 32), "humidity": (50, 70), "moisture": (40, 65), "light": (60, 90), "air": (400, 1000)},
    PlantType.ginger: {"temperature": (22, 30), "humidity": (60, 80), "moisture": (50, 75), "light": (30, 60), "air": (400, 1000)},
    PlantType.turmeric: {"temperature": (22, 30), "humidity": (60, 80), "moisture": (50, 75), "light": (30, 60), "air": (400, 1000)},
}


def get_optimal_conditions(plant_type: PlantType) -> dict[str, tuple[int, int]] | None:
    return PLANT_CONDITIONS.get(plant_type)


def conditions_summary_for_plants(plants: list) -> str | None:
    """Build a human-readable summary of optimal conditions for a list of plants."""
    if not plants:
        return None

    lines: list[str] = []
    for plant in plants:
        conditions = PLANT_CONDITIONS.get(plant.type)
        if conditions is None:
            continue
        temp = conditions["temperature"]
        hum = conditions["humidity"]
        moist = conditions["moisture"]
        light = conditions["light"]
        lines.append(
            f"- {plant.name or plant.type.value} ({plant.type.value}): "
            f"T={temp[0]}-{temp[1]}°C, H={hum[0]}-{hum[1]}%, "
            f"M={moist[0]}-{moist[1]}%, L={light[0]}-{light[1]}%"
        )

    return "\n".join(lines) if lines else None
