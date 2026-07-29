from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    plants = relationship(
        "Plant",
        back_populates="organization",
        cascade="all, delete-orphan",
    )


class Plant(Base):
    __tablename__ = "plants"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    location = Column(String(200), nullable=True)
    organization_id = Column(
        Integer,
        ForeignKey("organizations.id"),
        nullable=False,
    )
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    organization = relationship(
        "Organization",
        back_populates="plants",
    )

    sectors = relationship(
        "Sector",
        back_populates="plant",
        cascade="all, delete-orphan",
    )


class Sector(Base):
    __tablename__ = "sectors"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    description = Column(Text, nullable=True)
    plant_id = Column(
        Integer,
        ForeignKey("plants.id"),
        nullable=False,
    )
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    plant = relationship(
        "Plant",
        back_populates="sectors",
    )

    equipments = relationship(
        "Equipment",
        back_populates="sector",
        cascade="all, delete-orphan",
    )


class Equipment(Base):
    __tablename__ = "equipments"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    code = Column(String(100), nullable=True)
    description = Column(Text, nullable=True)
    sector_id = Column(
        Integer,
        ForeignKey("sectors.id"),
        nullable=False,
    )
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    sector = relationship(
        "Sector",
        back_populates="equipments",
    )
    documents = relationship(
        "Document",
        back_populates="equipment",
        cascade="all, delete-orphan",
    )
class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    document_type = Column(String(100), nullable=True)
    page_count = Column(Integer, nullable=True)
    processing_status = Column(
        String(50),
        nullable=False,
        default="uploaded",
    )
    equipment_id = Column(
        Integer,
        ForeignKey("equipments.id"),
        nullable=False,
    )
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    equipment = relationship(
        "Equipment",
        back_populates="documents",
    )

    pages = relationship(
        "DocumentPage",
        back_populates="document",
        cascade="all, delete-orphan",
    )

class DocumentPage(Base):
    __tablename__ = "document_pages"

    id = Column(Integer, primary_key=True, index=True)

    page_number = Column(
        Integer,
        nullable=False,
    )

    text_content = Column(
        Text,
        nullable=True,
    )

    image_path = Column(
        String(500),
        nullable=True,
    )

    document_id = Column(
        Integer,
        ForeignKey("documents.id"),
        nullable=False,
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    document = relationship(
        "Document",
        back_populates="pages",
    )
