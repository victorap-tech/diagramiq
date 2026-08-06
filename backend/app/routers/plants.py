from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db


router = APIRouter(
    prefix="/plants",
    tags=["Plantas"],
)


@router.post(
    "",
    response_model=schemas.PlantResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_plant(
    plant: schemas.PlantCreate,
    db: Session = Depends(get_db),
):
    organization = (
        db.query(models.Organization)
        .filter(models.Organization.id == plant.organization_id)
        .first()
    )

    # Un despliegue o una recreación de la base puede cambiar los IDs.
    # El frontend también envía el nombre visible para recuperar la empresa
    # correcta sin obligar al usuario a volver a crearla.
    if organization is None and plant.organization_name:
        normalized_name = plant.organization_name.strip().lower()
        organization = (
            db.query(models.Organization)
            .filter(models.Organization.name.ilike(normalized_name))
            .first()
        )

    if organization is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "Empresa no encontrada. Actualizá la lista de empresas y "
                "volvé a seleccionarla."
            ),
        )

    name = plant.name.strip()

    if not name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El nombre de la planta es obligatorio",
        )

    existing = (
        db.query(models.Plant)
        .filter(
            models.Plant.organization_id == organization.id,
            func.lower(models.Plant.name) == name.lower(),
        )
        .first()
    )
    if existing is not None:
        return existing

    new_plant = models.Plant(
        name=name,
        location=plant.location,
        organization_id=organization.id,
    )

    db.add(new_plant)
    try:
        db.commit()
        db.refresh(new_plant)
    except IntegrityError:
        db.rollback()
        existing = (
            db.query(models.Plant)
            .filter(
                models.Plant.organization_id == organization.id,
                func.lower(models.Plant.name) == name.lower(),
            )
            .first()
        )
        if existing is not None:
            return existing
        raise

    return new_plant


@router.get(
    "",
    response_model=list[schemas.PlantResponse],
)
def list_plants(
    organization_id: int | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(models.Plant)

    if organization_id is not None:
        query = query.filter(
            models.Plant.organization_id == organization_id
        )

    return query.order_by(models.Plant.name.asc()).all()


@router.get(
    "/{plant_id}",
    response_model=schemas.PlantResponse,
)
def get_plant(
    plant_id: int,
    db: Session = Depends(get_db),
):
    plant = (
        db.query(models.Plant)
        .filter(models.Plant.id == plant_id)
        .first()
    )

    if plant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Planta no encontrada",
        )

    return plant


@router.put(
    "/{plant_id}",
    response_model=schemas.PlantResponse,
)
def update_plant(
    plant_id: int,
    plant_data: schemas.PlantCreate,
    db: Session = Depends(get_db),
):
    plant = db.query(models.Plant).filter(models.Plant.id == plant_id).first()
    if plant is None:
        raise HTTPException(status_code=404, detail="Planta no encontrada")
    organization = db.query(models.Organization).filter(models.Organization.id == plant_data.organization_id).first()
    if organization is None:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    name = plant_data.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="El nombre de la planta es obligatorio")
    duplicate = (db.query(models.Plant).filter(
        models.Plant.id != plant_id,
        models.Plant.organization_id == organization.id,
        func.lower(models.Plant.name) == name.lower(),
    ).first())
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="Ya existe otra planta con ese nombre en la empresa")
    plant.name = name
    plant.location = plant_data.location
    plant.organization_id = organization.id
    db.commit()
    db.refresh(plant)
    return plant


@router.get("/{plant_id}/stats")
def plant_stats(plant_id: int, db: Session = Depends(get_db)):
    plant = db.query(models.Plant).filter(models.Plant.id == plant_id).first()
    if plant is None:
        raise HTTPException(status_code=404, detail="Planta no encontrada")
    sector_count = db.query(models.Sector).filter(models.Sector.plant_id == plant_id).count()
    document_count = (db.query(models.Document).join(models.Sector).filter(models.Sector.plant_id == plant_id).count())
    return {"id": plant.id, "name": plant.name, "child_count": sector_count, "document_count": document_count}


@router.delete(
    "/{plant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_plant(
    plant_id: int,
    db: Session = Depends(get_db),
):
    plant = (
        db.query(models.Plant)
        .filter(models.Plant.id == plant_id)
        .first()
    )

    if plant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Planta no encontrada",
        )

    document_count = (
        db.query(models.Document)
        .join(models.Sector, models.Document.sector_id == models.Sector.id)
        .filter(models.Sector.plant_id == plant_id)
        .count()
    )
    if document_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"No se puede eliminar la planta: contiene {document_count} documento(s). Movelos o eliminá los documentos primero.",
        )
    db.delete(plant)
    db.commit()

    return None
