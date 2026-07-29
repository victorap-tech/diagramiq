from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db


router = APIRouter(
    prefix="/organizations",
    tags=["Empresas"],
)


@router.post(
    "",
    response_model=schemas.OrganizationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_organization(
    organization: schemas.OrganizationCreate,
    db: Session = Depends(get_db),
):
    name = organization.name.strip()

    if not name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El nombre de la empresa es obligatorio",
        )

    new_organization = models.Organization(
        name=name,
        description=organization.description,
    )

    db.add(new_organization)

    try:
        db.commit()
        db.refresh(new_organization)

    except IntegrityError:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe una empresa con ese nombre",
        )

    return new_organization


@router.get(
    "",
    response_model=list[schemas.OrganizationResponse],
)
def list_organizations(
    db: Session = Depends(get_db),
):
    organizations = (
        db.query(models.Organization)
        .order_by(models.Organization.name.asc())
        .all()
    )

    return organizations


@router.get(
    "/{organization_id}",
    response_model=schemas.OrganizationResponse,
)
def get_organization(
    organization_id: int,
    db: Session = Depends(get_db),
):
    organization = (
        db.query(models.Organization)
        .filter(models.Organization.id == organization_id)
        .first()
    )

    if organization is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Empresa no encontrada",
        )

    return organization


@router.put(
    "/{organization_id}",
    response_model=schemas.OrganizationResponse,
)
def update_organization(
    organization_id: int,
    organization_data: schemas.OrganizationCreate,
    db: Session = Depends(get_db),
):
    organization = (
        db.query(models.Organization)
        .filter(models.Organization.id == organization_id)
        .first()
    )

    if organization is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Empresa no encontrada",
        )

    name = organization_data.name.strip()

    if not name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El nombre de la empresa es obligatorio",
        )

    organization.name = name
    organization.description = organization_data.description

    try:
        db.commit()
        db.refresh(organization)

    except IntegrityError:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe otra empresa con ese nombre",
        )

    return organization


@router.delete(
    "/{organization_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_organization(
    organization_id: int,
    db: Session = Depends(get_db),
):
    organization = (
        db.query(models.Organization)
        .filter(models.Organization.id == organization_id)
        .first()
    )

    if organization is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Empresa no encontrada",
        )

    try:
        db.delete(organization)
        db.commit()

    except IntegrityError:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "No se puede eliminar la empresa porque tiene "
                "plantas asociadas"
            ),
        )

    return None
