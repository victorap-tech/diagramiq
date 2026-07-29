from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import Base, engine, get_db


# Crea las tablas definidas en models.py al iniciar la aplicación.
Base.metadata.create_all(bind=engine)


app = FastAPI(
    title="DiagramIQ API",
    description="Asistente inteligente para mantenimiento industrial",
    version="0.2.0",
)


@app.get("/")
def root():
    return {
        "name": "DiagramIQ",
        "version": "0.2.0",
        "status": "online",
        "message": "API de DiagramIQ funcionando correctamente",
    }


@app.get("/health")
def health():
    return {
        "status": "healthy",
    }


@app.post(
    "/organizations",
    response_model=schemas.OrganizationResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Empresas"],
)
def create_organization(
    organization: schemas.OrganizationCreate,
    db: Session = Depends(get_db),
):
    new_organization = models.Organization(
        name=organization.name.strip(),
        description=organization.description,
    )

    if not new_organization.name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El nombre de la empresa es obligatorio",
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


@app.get(
    "/organizations",
    response_model=list[schemas.OrganizationResponse],
    tags=["Empresas"],
)
def list_organizations(
    db: Session = Depends(get_db),
):
    return (
        db.query(models.Organization)
        .order_by(models.Organization.name.asc())
        .all()
    )


@app.get(
    "/organizations/{organization_id}",
    response_model=schemas.OrganizationResponse,
    tags=["Empresas"],
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


@app.delete(
    "/organizations/{organization_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Empresas"],
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

    db.delete(organization)
    db.commit()

    return None
