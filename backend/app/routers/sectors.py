from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db


router = APIRouter(
    prefix="/sectors",
    tags=["Sectores"],
)


@router.post(
    "",
    response_model=schemas.SectorResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_sector(
    sector: schemas.SectorCreate,
    db: Session = Depends(get_db),
):
    plant = (
        db.query(models.Plant)
        .filter(models.Plant.id == sector.plant_id)
        .first()
    )

    if plant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Planta no encontrada",
        )

    name = sector.name.strip()

    if not name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El nombre del sector es obligatorio",
        )

    existing = (
        db.query(models.Sector)
        .filter(
            models.Sector.plant_id == sector.plant_id,
            func.lower(models.Sector.name) == name.lower(),
        )
        .first()
    )
    if existing is not None:
        return existing

    new_sector = models.Sector(
        name=name,
        description=sector.description,
        plant_id=sector.plant_id,
    )

    db.add(new_sector)
    try:
        db.commit()
        db.refresh(new_sector)
    except IntegrityError:
        db.rollback()
        existing = (
            db.query(models.Sector)
            .filter(
                models.Sector.plant_id == sector.plant_id,
                func.lower(models.Sector.name) == name.lower(),
            )
            .first()
        )
        if existing is not None:
            return existing
        raise

    return new_sector


@router.get(
    "",
    response_model=list[schemas.SectorResponse],
)
def list_sectors(
    plant_id: int | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(models.Sector)

    if plant_id is not None:
        query = query.filter(
            models.Sector.plant_id == plant_id
        )

    return query.order_by(models.Sector.name.asc()).all()


@router.get(
    "/{sector_id}",
    response_model=schemas.SectorResponse,
)
def get_sector(
    sector_id: int,
    db: Session = Depends(get_db),
):
    sector = (
        db.query(models.Sector)
        .filter(models.Sector.id == sector_id)
        .first()
    )

    if sector is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sector no encontrado",
        )

    return sector


@router.put(
    "/{sector_id}",
    response_model=schemas.SectorResponse,
)
def update_sector(
    sector_id: int,
    sector_data: schemas.SectorCreate,
    db: Session = Depends(get_db),
):
    sector = (
        db.query(models.Sector)
        .filter(models.Sector.id == sector_id)
        .first()
    )

    if sector is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sector no encontrado",
        )

    plant = (
        db.query(models.Plant)
        .filter(models.Plant.id == sector_data.plant_id)
        .first()
    )

    if plant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Planta no encontrada",
        )

    name = sector_data.name.strip()

    if not name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El nombre del sector es obligatorio",
        )

    sector.name = name
    sector.description = sector_data.description
    sector.plant_id = sector_data.plant_id

    db.commit()
    db.refresh(sector)

    return sector


@router.delete(
    "/{sector_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_sector(
    sector_id: int,
    db: Session = Depends(get_db),
):
    sector = (
        db.query(models.Sector)
        .filter(models.Sector.id == sector_id)
        .first()
    )

    if sector is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sector no encontrado",
        )

    db.delete(sector)
    db.commit()

    return None
