import re
from sqlalchemy.orm import Session

from app import models
from app.routers.component_catalog import infer_type

def _cancel_requested(document_id: int, db: Session) -> bool:
    db.expire_all()
    status_value = db.query(models.Document.processing_status).filter(
        models.Document.id == document_id
    ).scalar()
    return (status_value or "").lower() == "cancel_requested"


def _cancel_connections(document_id: int, db: Session) -> None:
    db.query(models.ComponentConnection).filter(
        models.ComponentConnection.document_id == document_id
    ).delete(synchronize_session=False)
    document = db.query(models.Document).filter(models.Document.id == document_id).first()
    if document is not None:
        document.connection_count = 0
        document.connection_status = "cancelled"
    db.commit()


# Relaciones físicamente plausibles. La proximidad por sí sola nunca alcanza.
COMPATIBLE_PAIRS = {
    frozenset(("interruptor", "contactor")),
    frozenset(("interruptor", "variador")),
    frozenset(("interruptor", "motor")),
    frozenset(("fusible", "contactor")),
    frozenset(("fusible", "variador")),
    frozenset(("guardamotor", "contactor")),
    frozenset(("guardamotor", "motor")),
    frozenset(("contactor", "relé térmico")),
    frozenset(("contactor", "variador")),
    frozenset(("contactor", "motor")),
    frozenset(("relé térmico", "motor")),
    frozenset(("variador", "motor")),
    frozenset(("PLC", "módulo de salidas")),
    frozenset(("módulo de salidas", "contactor")),
    frozenset(("sensor", "módulo de entradas")),
    frozenset(("bornera", "motor")),
    frozenset(("bornera", "sensor")),
    frozenset(("bornera", "contactor")),
}

VALID_REFERENCE = re.compile(r"^[A-Z]{1,5}[-_.:]?[A-Z0-9]{1,12}$")


def _distance(a, b):
    if None in (a.x, a.y, b.x, b.y):
        return None
    ax = a.x + (a.width or 0) / 2
    ay = a.y + (a.height or 0) / 2
    bx = b.x + (b.width or 0) / 2
    by = b.y + (b.height or 0) / 2
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


def _relation_hint(source_type: str, target_type: str) -> str:
    known = {
        ("interruptor", "contactor"): "posible alimentación/protección",
        ("interruptor", "variador"): "posible alimentación del variador",
        ("guardamotor", "contactor"): "posible protección de la maniobra",
        ("guardamotor", "motor"): "posible protección del motor",
        ("contactor", "relé térmico"): "posible maniobra con protección térmica",
        ("contactor", "motor"): "posible maniobra del motor",
        ("relé térmico", "motor"): "posible protección térmica",
        ("variador", "motor"): "posible control del motor",
        ("PLC", "módulo de salidas"): "posible vínculo de control",
        ("módulo de salidas", "contactor"): "posible salida hacia bobina",
        ("sensor", "módulo de entradas"): "posible señal de entrada",
        ("bornera", "motor"): "posible interconexión de campo",
        ("bornera", "sensor"): "posible interconexión de campo",
    }
    return known.get((source_type, target_type)) or known.get((target_type, source_type)) or "posible relación eléctrica"


def _flow_direction(source_type: str, target_type: str) -> str:
    rank = {
        "transformador": 0, "interruptor": 1, "fusible": 1, "guardamotor": 2,
        "contactor": 3, "relé térmico": 4, "variador": 5, "motor": 6,
        "PLC": 2, "módulo de salidas": 3, "bornera": 4,
        "sensor": 1, "módulo de entradas": 2,
    }
    a = rank.get(source_type)
    b = rank.get(target_type)
    if a is None or b is None or a == b:
        return "unknown"
    return "downstream" if a < b else "upstream"


def _is_valid_component(ref) -> bool:
    value = (ref.normalized_reference or ref.reference or "").strip().upper()
    ctype = infer_type(ref.reference, ref.detected_type, ref.component_type)
    return bool(value and VALID_REFERENCE.match(value) and ctype != "otro")


def _score_pair(source, target):
    source_type = infer_type(source.reference, source.detected_type, source.component_type)
    target_type = infer_type(target.reference, target.detected_type, target.component_type)
    source_text = " ".join(filter(None, [source.row_text, source.description])).upper()
    target_text = " ".join(filter(None, [target.row_text, target.description])).upper()

    mentioned = bool(target.reference and re.search(rf"(?<![A-Z0-9]){re.escape(target.reference.upper())}(?![A-Z0-9])", source_text))
    reverse = bool(source.reference and re.search(rf"(?<![A-Z0-9]){re.escape(source.reference.upper())}(?![A-Z0-9])", target_text))
    explicit = mentioned or reverse
    compatible = frozenset((source_type, target_type)) in COMPATIBLE_PAIRS
    dist = _distance(source, target)

    # Una referencia cruzada explícita es evidencia fuerte.
    if explicit:
        score = 82
        reasons = ["referencia cruzada explícita"]
        if compatible:
            score += 10
            reasons.append("tipos compatibles")
        if dist is not None and dist <= 260:
            score += 5
            reasons.append("proximidad visual")
        return min(score, 99), ", ".join(reasons), _relation_hint(source_type, target_type), _flow_direction(source_type, target_type)

    # Sin referencia explícita, solo aceptamos pares eléctricos compatibles y muy cercanos.
    if not compatible or dist is None or dist > 220:
        return 0, "sin evidencia suficiente", "", "unknown"

    score = 58 if dist <= 110 else 50
    reason = "tipos compatibles y muy próximos" if dist <= 110 else "tipos compatibles y próximos"
    return score, reason, _relation_hint(source_type, target_type), _flow_direction(source_type, target_type)


def rebuild_document_connections(document_id: int, db: Session) -> int:
    """Precalcula solo relaciones con evidencia eléctrica útil."""
    document = db.query(models.Document).filter(models.Document.id == document_id).first()
    if document is None:
        return 0

    document.connection_status = "processing"
    document.connection_count = 0
    db.query(models.ComponentConnection).filter(
        models.ComponentConnection.document_id == document_id
    ).delete(synchronize_session=False)
    db.commit()

    pages = (
        db.query(models.DocumentPage)
        .filter(models.DocumentPage.document_id == document_id)
        .order_by(models.DocumentPage.page_number.asc())
        .all()
    )
    count = 0
    seen = set()

    for page_index, page in enumerate(pages):
        if page_index % 10 == 0 and _cancel_requested(document_id, db):
            _cancel_connections(document_id, db)
            return 0
        refs = [ref for ref in page.references if _is_valid_component(ref)]
        for i, source in enumerate(refs):
            candidates = []
            for target in refs[i + 1:]:
                # La misma referencia repetida en una página suele ser documentación, no conexión.
                if (source.normalized_reference or source.reference or "").upper() == (target.normalized_reference or target.reference or "").upper():
                    continue
                score, reason, relation, direction = _score_pair(source, target)
                if score >= 50:
                    candidates.append((target, score, reason, relation, direction))
            candidates.sort(key=lambda row: -row[1])
            # Máximo cuatro relaciones fuertes por aparición de componente.
            for target, score, reason, relation, direction in candidates[:4]:
                key = (min(source.id, target.id), max(source.id, target.id), False)
                if key in seen:
                    continue
                seen.add(key)
                db.add(models.ComponentConnection(
                    document_id=document_id,
                    source_reference_id=source.id,
                    target_reference_id=target.id,
                    relation_type=relation,
                    direction=direction,
                    confidence=score,
                    reason=reason,
                    cross_page=0,
                ))
                count += 1
                if count % 200 == 0:
                    document.connection_count = count
                    db.commit()

    # Continuidad entre páginas: solo referencias técnicas válidas y con una cantidad razonable
    # de apariciones. Esto evita enlazar miles de menciones provenientes de listados/BOM.
    refs = (
        db.query(models.ComponentReference)
        .join(models.DocumentPage, models.ComponentReference.document_page_id == models.DocumentPage.id)
        .filter(models.DocumentPage.document_id == document_id)
        .order_by(models.ComponentReference.normalized_reference.asc(), models.DocumentPage.page_number.asc())
        .all()
    )
    groups = {}
    for ref in refs:
        if not _is_valid_component(ref):
            continue
        normalized = (ref.normalized_reference or ref.reference or "").strip().upper()
        groups.setdefault(normalized, []).append(ref)

    for group_index, group in enumerate(groups.values()):
        if group_index % 50 == 0 and _cancel_requested(document_id, db):
            _cancel_connections(document_id, db)
            return 0
        # Una referencia que aparece decenas de veces suele pertenecer a tablas/listados.
        if len(group) < 2 or len(group) > 20:
            continue
        for source, target in zip(group, group[1:]):
            if source.document_page_id == target.document_page_id:
                continue
            key = (min(source.id, target.id), max(source.id, target.id), True)
            if key in seen:
                continue
            seen.add(key)
            db.add(models.ComponentConnection(
                document_id=document_id,
                source_reference_id=source.id,
                target_reference_id=target.id,
                relation_type="misma referencia en otra página",
                direction="unknown",
                confidence=95,
                reason="continuidad por referencia exacta",
                cross_page=1,
            ))
            count += 1
            if count % 200 == 0:
                document.connection_count = count
                db.commit()

    document.connection_count = count
    document.connection_status = "completed"
    db.commit()
    return count
