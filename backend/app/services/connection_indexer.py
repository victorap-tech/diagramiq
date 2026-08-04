import re
from sqlalchemy.orm import Session

from app import models
from app.routers.component_catalog import infer_type


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
        ("guardamotor", "motor"): "posible protección del motor",
        ("contactor", "motor"): "posible maniobra del motor",
        ("relé térmico", "motor"): "posible protección térmica",
        ("variador", "motor"): "posible control del motor",
        ("PLC", "módulo de salidas"): "posible vínculo de control",
        ("módulo de salidas", "contactor"): "posible salida hacia bobina",
        ("sensor", "módulo de entradas"): "posible señal de entrada",
        ("bornera", "motor"): "posible interconexión de campo",
    }
    return known.get((source_type, target_type)) or known.get((target_type, source_type)) or "posible relación por proximidad"


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


def _score_pair(source, target):
    source_type = infer_type(source.reference, source.detected_type, source.component_type)
    target_type = infer_type(target.reference, target.detected_type, target.component_type)
    source_text = " ".join(filter(None, [source.row_text, source.description])).upper()
    target_text = " ".join(filter(None, [target.row_text, target.description])).upper()

    mentioned = bool(target.reference and re.search(rf"(?<![A-Z0-9]){re.escape(target.reference.upper())}(?![A-Z0-9])", source_text))
    reverse = bool(source.reference and re.search(rf"(?<![A-Z0-9]){re.escape(source.reference.upper())}(?![A-Z0-9])", target_text))
    dist = _distance(source, target)
    score = 0
    reasons = []
    if mentioned or reverse:
        score += 70
        reasons.append("referencia cruzada")
    if dist is not None:
        if dist <= 180:
            score += 35
            reasons.append("muy próximo")
        elif dist <= 400:
            score += 20
            reasons.append("próximo")
        elif dist <= 800:
            score += 8
    if source_type != "otro" and target_type != "otro":
        score += 5
    return min(score, 99), ", ".join(reasons) or "misma página", _relation_hint(source_type, target_type), _flow_direction(source_type, target_type)


def rebuild_document_connections(document_id: int, db: Session) -> int:
    """Precalcula relaciones del documento sin afectar las búsquedas normales."""
    document = db.query(models.Document).filter(models.Document.id == document_id).first()
    if document is None:
        return 0

    document.connection_status = "processing"
    db.query(models.ComponentConnection).filter(models.ComponentConnection.document_id == document_id).delete(synchronize_session=False)
    db.flush()

    pages = (
        db.query(models.DocumentPage)
        .filter(models.DocumentPage.document_id == document_id)
        .order_by(models.DocumentPage.page_number.asc())
        .all()
    )
    count = 0
    seen = set()

    for page in pages:
        refs = list(page.references)
        for i, source in enumerate(refs):
            candidates = []
            for target in refs[i + 1:]:
                score, reason, relation, direction = _score_pair(source, target)
                if score >= 20:
                    candidates.append((target, score, reason, relation, direction))
            candidates.sort(key=lambda row: -row[1])
            for target, score, reason, relation, direction in candidates[:8]:
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
                # Libera periódicamente el bloqueo de escritura de SQLite.
                if count % 250 == 0:
                    document.connection_count = count
                    db.commit()

    # La misma referencia en distintas páginas representa continuidad fuerte.
    refs = (
        db.query(models.ComponentReference)
        .join(models.DocumentPage, models.ComponentReference.document_page_id == models.DocumentPage.id)
        .filter(models.DocumentPage.document_id == document_id)
        .order_by(models.ComponentReference.normalized_reference.asc(), models.DocumentPage.page_number.asc())
        .all()
    )
    groups = {}
    for ref in refs:
        normalized = (ref.normalized_reference or ref.reference or "").strip().upper()
        if normalized:
            groups.setdefault(normalized, []).append(ref)
    for group in groups.values():
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
            if count % 250 == 0:
                document.connection_count = count
                db.commit()

    document.connection_count = count
    document.connection_status = "completed"
    db.commit()
    return count
