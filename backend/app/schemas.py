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

class DocumentResponse(BaseModel):
    id: int
    title: str
    filename: str
    document_type: str | None = None
    page_count: int | None = None
    processing_status: str
    equipment_id: int

    model_config = ConfigDict(from_attributes=True)

class DocumentPageResponse(BaseModel):
    id: int
    page_number: int
    text_content: str | None = None
    image_path: str | None = None
    document_id: int

    model_config = ConfigDict(from_attributes=True)


class DocumentProcessResponse(BaseModel):
    document_id: int
    processing_status: str
    processed_pages: int
    message: str

class ComponentReferenceResponse(BaseModel):
    id: int
    reference: str
    component_type: str | None = None
    document_page_id: int

    model_config = ConfigDict(from_attributes=True)
