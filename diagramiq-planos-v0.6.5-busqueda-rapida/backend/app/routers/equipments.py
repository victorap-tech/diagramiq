from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db

router = APIRouter(
    prefix="/equipments",
    tags=["Equipos"],
)


@router.post(
    "",
    response_model=schemas.EquipmentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_equipment(
    equipment: schemas.EquipmentCreate,
    db: Session = Depends(get_db),
):
    sector = (
        db.query(models.Sector)
        .filter(models.Sector.id == equipment.sector_id)
        .first()
    )

    if sector is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sector no encontrado",
        )

    new_equipment = models.Equipment(
        name=equipment.name.strip(),
        code=equipment.code,
        description=equipment.description,
        sector_id=equipment.sector_id,
    )

    db.add(new_equipment)
    db.commit()
    db.refresh(new_equipment)

    return new_equipment


@router.get(
    "",
    response_model=list[schemas.EquipmentResponse],
)
def list_equipments(
    sector_id: int | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(models.Equipment)

    if sector_id is not None:
        query = query.filter(
            models.Equipment.sector_id == sector_id
        )

    return query.order_by(models.Equipment.name.asc()).all()


@router.get(
    "/{equipment_id}",
    response_model=schemas.EquipmentResponse,
)
def get_equipment(
    equipment_id: int,
    db: Session = Depends(get_db),
):
    equipment = (
        db.query(models.Equipment)
        .filter(models.Equipment.id == equipment_id)
        .first()
    )

    if equipment is None:
        raise HTTPException(
            status_code=404,
            detail="Equipo no encontrado",
        )

    return equipment


@router.put(
    "/{equipment_id}",
    response_model=schemas.EquipmentResponse,
)
def update_equipment(
    equipment_id: int,
    equipment_data: schemas.EquipmentCreate,
    db: Session = Depends(get_db),
):
    equipment = (
        db.query(models.Equipment)
        .filter(models.Equipment.id == equipment_id)
        .first()
    )

    if equipment is None:
        raise HTTPException(
            status_code=404,
            detail="Equipo no encontrado",
        )

    sector = (
        db.query(models.Sector)
        .filter(models.Sector.id == equipment_data.sector_id)
        .first()
    )

    if sector is None:
        raise HTTPException(
            status_code=404,
            detail="Sector no encontrado",
        )

    equipment.name = equipment_data.name.strip()
    equipment.code = equipment_data.code
    equipment.description = equipment_data.description
    equipment.sector_id = equipment_data.sector_id

    db.commit()
    db.refresh(equipment)

    return equipment


@router.delete(
    "/{equipment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_equipment(
    equipment_id: int,
    db: Session = Depends(get_db),
):
    equipment = (
        db.query(models.Equipment)
        .filter(models.Equipment.id == equipment_id)
        .first()
    )

    if equipment is None:
        raise HTTPException(
            status_code=404,
            detail="Equipo no encontrado",
        )

    db.delete(equipment)
    db.commit()

    return None

