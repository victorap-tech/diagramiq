from pydantic import BaseModel, ConfigDict


class OrganizationCreate(BaseModel):
    name: str
    description: str | None = None


class OrganizationResponse(BaseModel):
    id: int
    name: str
    description: str | None = None

    model_config = ConfigDict(from_attributes=True)


class PlantCreate(BaseModel):
    name: str
    location: str | None = None
    organization_id: int


class PlantResponse(BaseModel):
    id: int
    name: str
    location: str | None = None
    organization_id: int

    model_config = ConfigDict(from_attributes=True)


class SectorCreate(BaseModel):
    name: str
    description: str | None = None
    plant_id: int


class SectorResponse(BaseModel):
    id: int
    name: str
    description: str | None = None
    plant_id: int

    model_config = ConfigDict(from_attributes=True)


class EquipmentCreate(BaseModel):
    name: str
    code: str | None = None
    description: str | None = None
    sector_id: int


class EquipmentResponse(BaseModel):
    id: int
    name: str
    code: str | None = None
    description: str | None = None
    sector_id: int

    model_config = ConfigDict(from_attributes=True)
