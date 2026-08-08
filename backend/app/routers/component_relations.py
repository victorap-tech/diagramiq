import re
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app import models
from app.database import get_db
from app.routers.component_catalog import infer_type, is_nonphysical_reference, normalize_term

router = APIRouter(prefix="/component-relations", tags=["Relaciones entre componentes"])

PREFIX_ROLE = {
    "interruptor": "protección/alimentación",
    "seccionador": "aislamiento/alimentación",
    "guardamotor": "protección de motor",
    "contactor": "maniobra",
    "relé": "mando",
    "relé térmico": "protección térmica",
    "fusible": "protección",
    "variador": "control de motor",
    "arrancador suave": "arranque/control de motor",
    "PLC": "control lógico",
    "módulo de entradas": "entrada de control",
    "módulo de salidas": "salida de control",
    "módulo analógico": "señal analógica",
    "motor": "carga",
    "sensor": "señal de campo",
    "bornera": "interconexión",
    "pulsador": "mando manual",
    "piloto": "señalización",
    "transformador": "alimentación",
}


def _distance(a, b):
    if None in (a.x, a.y, b.x, b.y):
        return None
    ax = a.x + (a.width or 0) / 2
    ay = a.y + (a.height or 0) / 2
    bx = b.x + (b.width or 0) / 2
    by = b.y + (b.height or 0) / 2
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


def _relation_hint(source_type: str, target_type: str) -> str:
    pair = (source_type, target_type)
    known = {
        ("interruptor", "contactor"): "posible alimentación/protección",
        ("guardamotor", "motor"): "posible protección del motor",
        ("contactor", "motor"): "posible maniobra del motor",
        ("relé térmico", "motor"): "posible protección térmica",
        ("variador", "motor"): "posible control del motor",
        ("arrancador suave", "motor"): "posible arranque suave del motor",
        ("PLC", "módulo de salidas"): "posible vínculo de control",
        ("módulo de salidas", "contactor"): "posible salida hacia bobina",
        ("sensor", "módulo de entradas"): "posible señal de entrada",
        ("bornera", "motor"): "posible interconexión de campo",
    }
    return known.get(pair) or known.get((target_type, source_type)) or "posible relación por proximidad"



MOTOR_RELATED_PRIORITY = {
    "arrancador suave": 0,
    "variador": 1,
    "guardamotor": 2,
    "contactor": 3,
    "relé térmico": 4,
    "interruptor": 5,
    "fusible": 6,
    "bornera": 7,
    "módulo de salidas": 8,
    "PLC": 9,
}



TEXT_DEVICE_RULES = (
    (re.compile(r"\b(3RW[0-9A-Z-]{4,})\b", re.IGNORECASE), "arrancador suave", "Siemens", "arranque/control de motor"),
    (re.compile(r"\b(3RV[0-9A-Z-]{4,})\b", re.IGNORECASE), "guardamotor", "Siemens", "protección de motor"),
    (re.compile(r"\b(3RT[0-9A-Z-]{4,})\b", re.IGNORECASE), "contactor", "Siemens", "maniobra de motor"),
    (re.compile(r"\b(ATV[0-9A-Z-]{2,}|ALTIVAR[0-9A-Z-]*)\b", re.IGNORECASE), "variador", "Schneider Electric", "control de motor"),
    (re.compile(r"\b(6SL[0-9A-Z-]{5,})\b", re.IGNORECASE), "variador", "Siemens", "control de motor"),
    (re.compile(r"\b(VLT[- ]?[0-9A-Z-]+|FC[- ]?[0-9]{2,4}[A-Z0-9-]*)\b", re.IGNORECASE), "variador", "Danfoss", "control de motor"),
    (re.compile(r"\b(ACS[0-9A-Z-]{2,})\b", re.IGNORECASE), "variador", "ABB", "control de motor"),
    (re.compile(r"\b(GV2[A-Z0-9-]+)\b", re.IGNORECASE), "guardamotor", "Schneider Electric", "protección de motor"),
)

def _best_term_for_model(db: Session, page_id: int, model: str):
    wanted = normalize_term(model)
    rows = (
        db.query(models.PageSearchTerm)
        .filter(models.PageSearchTerm.document_page_id == page_id)
        .all()
    )
    exact = []
    contextual = []
    for term in rows:
        values = [term.term or "", term.display_text or "", term.row_text or ""]
        norms = [normalize_term(v) for v in values]
        if any(n == wanted for n in norms[:2]):
            exact.append(term)
        elif any(wanted and wanted in n for n in norms):
            contextual.append(term)
    candidates = exact or contextual
    if not candidates:
        return None
    candidates.sort(key=lambda t: (0 if t.x is not None and t.y is not None else 1, len(t.row_text or "")))
    return candidates[0]

def _text_power_relations(source, db: Session):
    """Detecta equipos de potencia/protección aunque no hayan quedado catalogados como ComponentReference.

    Esto evita que Ver relacionados dependa exclusivamente del catálogo: si el plano de un motor
    contiene un 3RW/3RV/variador, se devuelve como relación verificable desde el propio texto indexado.
    """
    page = source.document_page
    if not page:
        return []
    source_ref = normalize_term(source.reference)
    source_type = infer_type(source.reference, source.detected_type, source.component_type, source.model, source.description or source.row_text)
    doc_id = page.document_id
    # Página actual primero y una página a cada lado como respaldo para circuitos partidos.
    pages = (
        db.query(models.DocumentPage)
        .filter(models.DocumentPage.document_id == doc_id)
        .filter(models.DocumentPage.page_number >= max(1, page.page_number - 1))
        .filter(models.DocumentPage.page_number <= page.page_number + 1)
        .order_by(models.DocumentPage.page_number.asc())
        .all()
    )
    found = []
    seen = set()
    for candidate_page in pages:
        text = candidate_page.text_content or ""
        if not text:
            continue
        upper = text.upper()
        # Si es página vecina, exigimos que también aparezca la referencia del motor.
        if candidate_page.id != page.id and source_ref not in normalize_term(text):
            continue
        for pattern, ctype, manufacturer, relation in TEXT_DEVICE_RULES:
            for match in pattern.finditer(upper):
                model = match.group(1).strip().replace(" ", "-")
                key = (ctype, normalize_term(model), candidate_page.id)
                if key in seen:
                    continue
                seen.add(key)
                term = _best_term_for_model(db, candidate_page.id, model)
                row_text = (term.row_text if term else "") or ""
                evidence = f"{model} {row_text} {upper[max(0, match.start()-180):match.end()+180]}"
                # Refuerza la certeza cuando el texto declara explícitamente Softstarter/variador/guardamotor.
                confidence = 88
                if ctype == "arrancador suave" and re.search(r"SOFTSTART|ARRANCADOR\s+SUAVE|SANFTSTART", evidence, re.IGNORECASE):
                    confidence = 98
                elif ctype == "variador" and re.search(r"VARIADOR|INVERTER|FREQUEN", evidence, re.IGNORECASE):
                    confidence = 96
                elif ctype == "guardamotor" and re.search(r"GUARDAMOTOR|MOTOR\s+PROTECT", evidence, re.IGNORECASE):
                    confidence = 96
                reason = f"{manufacturer} {model} detectado en la misma página del circuito" if candidate_page.id == page.id else f"{manufacturer} {model} detectado en página eléctrica contigua"
                functional_relation = relation
                if source_type == "guardamotor" and ctype in {"variador", "arrancador suave"}:
                    functional_relation = "equipo de accionamiento alimentado/protegido por el guardamotor"
                found.append({
                    "id": None,
                    "reference": model,
                    "component_type": ctype,
                    "model": model,
                    "manufacturer": manufacturer,
                    "description": row_text,
                    "distance": None,
                    "confidence": confidence,
                    "relation": functional_relation,
                    "reason": reason,
                    "x": term.x if term else None,
                    "y": term.y if term else None,
                    "width": term.width if term else None,
                    "height": term.height if term else None,
                    "page_id": candidate_page.id,
                    "page_number": candidate_page.page_number,
                    "document_id": candidate_page.document_id,
                })
    found.sort(key=lambda item: _relation_priority(source_type, item["component_type"], item["confidence"]))
    return found

def _merge_relations(primary, extra):
    merged = []
    seen = set()
    for item in list(primary) + list(extra):
        key = (normalize_term(item.get("reference")), item.get("component_type"), item.get("page_number"))
        if not key[0] or key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged

GENERIC_RELATED = {
    "N", "PE", "L", "L1", "L2", "L3", "L+", "L-", "M", "0V", "24V", "+24V",
    "U", "V", "W", "U1", "V1", "W1", "13", "14", "21", "22",
}

def _is_junk_related(ref) -> bool:
    value = (ref.reference or "").strip()
    normalized = normalize_term(value)
    if not normalized:
        return True
    if is_nonphysical_reference(value) or normalized in {normalize_term(v) for v in GENERIC_RELATED}:
        return True
    if re.fullmatch(r"\d{1,2}", normalized):
        return True
    return False

def _relation_priority(source_type: str, target_type: str, confidence: int | float = 0) -> tuple:
    """Para motores, primero equipos de potencia/protección; después control/señales."""
    if source_type == "motor":
        return (MOTOR_RELATED_PRIORITY.get(target_type, 50), -int(confidence or 0))
    return (0, -int(confidence or 0))

def _indexed_edges(reference_id: int, db: Session):
    rows = (
        db.query(models.ComponentConnection)
        .filter(
            (models.ComponentConnection.source_reference_id == reference_id)
            | (models.ComponentConnection.target_reference_id == reference_id)
        )
        .order_by(models.ComponentConnection.confidence.desc())
        .all()
    )
    result = []
    for row in rows:
        target_id = row.target_reference_id if row.source_reference_id == reference_id else row.source_reference_id
        target = db.query(models.ComponentReference).filter(models.ComponentReference.id == target_id).first()
        if target is not None:
            result.append((row, target))
    return result


@router.get("/{reference_id}")
def get_component_relations(reference_id: int, db: Session = Depends(get_db)):
    source = db.query(models.ComponentReference).filter(models.ComponentReference.id == reference_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Componente no encontrado")

    page = source.document_page
    source_type = infer_type(source.reference, source.detected_type, source.component_type)
    indexed = _indexed_edges(source.id, db)
    if indexed:
        doc = page.document
        relations = []
        for edge, ref in indexed:
            if _is_junk_related(ref):
                continue
            target_type = infer_type(ref.reference, ref.detected_type, ref.component_type, ref.model, ref.description or ref.row_text)
            # Si el origen es motor, no ensuciar con señales genéricas: priorizar potencia/protección.
            if source_type == "motor" and target_type not in MOTOR_RELATED_PRIORITY:
                continue
            relations.append({
                "id": ref.id,
                "reference": ref.reference,
                "component_type": target_type,
                "model": ref.model or "",
                "description": ref.description or ref.row_text or "",
                "distance": _distance(source, ref),
                "confidence": edge.confidence,
                "relation": edge.relation_type,
                "reason": edge.reason or "relación indexada",
                "x": ref.x, "y": ref.y, "width": ref.width, "height": ref.height,
                "page_id": ref.document_page_id,
                "page_number": ref.document_page.page_number if ref.document_page else None,
                "document_id": ref.document_page.document_id if ref.document_page else None,
            })
        if source_type in {"motor", "guardamotor", "interruptor", "fusible"}:
            relations = _merge_relations(relations, _text_power_relations(source, db))
        relations.sort(key=lambda item: _relation_priority(source_type, item["component_type"], item["confidence"]))
        return {
            "source": {
                "id": source.id, "reference": source.reference,
                "component_type": source_type, "model": source.model or "",
                "role": PREFIX_ROLE.get(source_type, "componente"),
                "document_id": doc.id, "document_title": doc.title,
                "page_number": page.page_number,
            },
            "relations": relations[:20],
            "indexed": True,
            "note": "Relaciones verificables obtenidas del índice y del texto eléctrico de la página. Para motores se priorizan arrancador suave, variador, guardamotor y maniobra/protección.",
        }
    refs = (
        db.query(models.ComponentReference)
        .filter(models.ComponentReference.document_page_id == source.document_page_id)
        .filter(models.ComponentReference.id != source.id)
        .all()
    )

    source_text = " ".join(filter(None, [source.row_text, source.description])).upper()
    relations = []
    for ref in refs:
        if _is_junk_related(ref):
            continue
        target_type = infer_type(ref.reference, ref.detected_type, ref.component_type, ref.model, ref.description or ref.row_text)
        if source_type == "motor" and target_type not in MOTOR_RELATED_PRIORITY:
            continue
        dist = _distance(source, ref)
        mentioned = bool(ref.reference and re.search(rf"(?<![A-Z0-9]){re.escape(ref.reference.upper())}(?![A-Z0-9])", source_text))
        reverse_text = " ".join(filter(None, [ref.row_text, ref.description])).upper()
        reverse_mentioned = bool(source.reference and re.search(rf"(?<![A-Z0-9]){re.escape(source.reference.upper())}(?![A-Z0-9])", reverse_text))

        score = 0
        reasons = []
        if mentioned or reverse_mentioned:
            score += 70
            reasons.append("referencia cruzada en el texto")
        if dist is not None:
            if dist <= 180:
                score += 35
                reasons.append("muy próximo en el plano")
            elif dist <= 400:
                score += 20
                reasons.append("próximo en el plano")
            elif dist <= 800:
                score += 8
        if source_type != "otro" and target_type != "otro":
            score += 5
        if score < 10:
            continue
        relations.append({
            "id": ref.id,
            "reference": ref.reference,
            "component_type": target_type,
            "model": ref.model or "",
            "description": ref.description or ref.row_text or "",
            "distance": round(dist, 1) if dist is not None else None,
            "confidence": min(score, 99),
            "relation": _relation_hint(source_type, target_type),
            "reason": ", ".join(reasons) or "misma página",
            "x": ref.x, "y": ref.y, "width": ref.width, "height": ref.height,
        })

    if source_type in {"motor", "guardamotor", "interruptor", "fusible"}:
        relations = _merge_relations(relations, _text_power_relations(source, db))
    relations.sort(key=lambda item: (_relation_priority(source_type, item["component_type"], item["confidence"]), item["distance"] if item.get("distance") is not None else 999999))
    doc = page.document
    return {
        "source": {
            "id": source.id,
            "reference": source.reference,
            "component_type": source_type,
            "model": source.model or "",
            "role": PREFIX_ROLE.get(source_type, "componente"),
            "document_id": doc.id,
            "document_title": doc.title,
            "page_number": page.page_number,
        },
        "relations": relations[:20],
        "note": "Relaciones obtenidas por referencias cruzadas, proximidad y reconocimiento de equipos de potencia/protección en el texto del plano.",
    }


def _node_payload(ref):
    page = ref.document_page
    doc = page.document
    ref_type = infer_type(ref.reference, ref.detected_type, ref.component_type)
    return {
        "id": ref.id,
        "reference": ref.reference or ref.model or f"Componente {ref.id}",
        "component_type": ref_type,
        "model": ref.model or "",
        "document_id": doc.id,
        "document_title": doc.title,
        "page_number": page.page_number,
        "x": ref.x,
        "y": ref.y,
        "width": ref.width,
        "height": ref.height,
    }


def _candidate_edges(source, db: Session):
    source_type = infer_type(source.reference, source.detected_type, source.component_type)
    source_text = " ".join(filter(None, [source.row_text, source.description])).upper()
    refs = (
        db.query(models.ComponentReference)
        .filter(models.ComponentReference.document_page_id == source.document_page_id)
        .filter(models.ComponentReference.id != source.id)
        .all()
    )
    edges = []
    for ref in refs:
        if _is_junk_related(ref):
            continue
        target_type = infer_type(ref.reference, ref.detected_type, ref.component_type, ref.model, ref.description or ref.row_text)
        if source_type == "motor" and target_type not in MOTOR_RELATED_PRIORITY:
            continue
        dist = _distance(source, ref)
        mentioned = bool(ref.reference and re.search(rf"(?<![A-Z0-9]){re.escape(ref.reference.upper())}(?![A-Z0-9])", source_text))
        reverse_text = " ".join(filter(None, [ref.row_text, ref.description])).upper()
        reverse_mentioned = bool(source.reference and re.search(rf"(?<![A-Z0-9]){re.escape(source.reference.upper())}(?![A-Z0-9])", reverse_text))
        score = 0
        reasons = []
        if mentioned or reverse_mentioned:
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
        if score >= 20:
            edges.append((ref, min(score, 99), _relation_hint(source_type, target_type), ", ".join(reasons) or "misma página"))
    edges.sort(key=lambda row: -row[1])
    return edges[:8]



def _flow_direction(source_type: str, target_type: str) -> str:
    """Inferencia preliminar del sentido funcional del circuito."""
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

@router.get("/{reference_id}/graph")
def get_component_graph(reference_id: int, depth: int = 2, db: Session = Depends(get_db)):
    """Construye un grafo preliminar navegable desde un componente.

    Recorre relaciones fuertes en la misma página y une apariciones de la misma
    referencia en otras páginas del mismo documento. depth se limita a 1..3.
    """
    depth = max(1, min(depth, 3))
    root = db.query(models.ComponentReference).filter(models.ComponentReference.id == reference_id).first()
    if not root:
        raise HTTPException(status_code=404, detail="Componente no encontrado")

    indexed_root = _indexed_edges(root.id, db)
    if indexed_root:
        nodes = {root.id: _node_payload(root)}
        edges = []
        queue = [(root.id, 0)]
        visited = set()
        while queue:
            current_id, level = queue.pop(0)
            if current_id in visited or level >= depth:
                continue
            visited.add(current_id)
            for edge, target in _indexed_edges(current_id, db):
                nodes.setdefault(target.id, _node_payload(target))
                actual_direction = edge.direction
                if edge.target_reference_id == current_id:
                    actual_direction = "upstream" if edge.direction == "downstream" else "downstream" if edge.direction == "upstream" else "unknown"
                edges.append({
                    "source": current_id, "target": target.id,
                    "direction": actual_direction, "confidence": edge.confidence,
                    "relation": edge.relation_type, "reason": edge.reason or "relación indexada",
                    "cross_page": bool(edge.cross_page),
                })
                if edge.confidence >= 40:
                    queue.append((target.id, level + 1))
        return {
            "root_id": root.id, "depth": depth,
            "nodes": list(nodes.values()), "edges": edges,
            "indexed": True,
            "note": "Seguimiento servido desde el índice de conexiones precalculado.",
        }

    nodes = {root.id: _node_payload(root)}
    edges = []
    queue = [(root, 0)]
    visited = set()

    while queue:
        current, level = queue.pop(0)
        if current.id in visited or level >= depth:
            continue
        visited.add(current.id)

        for target, confidence, relation, reason in _candidate_edges(current, db):
            nodes.setdefault(target.id, _node_payload(target))
            current_type = infer_type(current.reference, current.detected_type, current.component_type)
            target_type = infer_type(target.reference, target.detected_type, target.component_type)
            edges.append({
                "source": current.id,
                "target": target.id,
                "direction": _flow_direction(current_type, target_type),
                "confidence": confidence,
                "relation": relation,
                "reason": reason,
                "cross_page": False,
            })
            if confidence >= 40:
                queue.append((target, level + 1))

        normalized = (current.normalized_reference or current.reference or "").strip().upper()
        if normalized:
            page = current.document_page
            same_refs = (
                db.query(models.ComponentReference)
                .join(models.DocumentPage, models.ComponentReference.document_page_id == models.DocumentPage.id)
                .filter(models.DocumentPage.document_id == page.document_id)
                .filter(models.ComponentReference.id != current.id)
                .filter(models.ComponentReference.normalized_reference == normalized)
                .limit(6)
                .all()
            )
            for target in same_refs:
                nodes.setdefault(target.id, _node_payload(target))
                if not any(e["source"] == current.id and e["target"] == target.id for e in edges):
                    edges.append({
                        "source": current.id,
                        "target": target.id,
                        "direction": "unknown",
                        "confidence": 95,
                        "relation": "misma referencia en otra página",
                        "reason": "continuidad por referencia exacta",
                        "cross_page": True,
                    })
                    queue.append((target, level + 1))

    return {
        "root_id": root.id,
        "depth": depth,
        "nodes": list(nodes.values()),
        "edges": edges,
        "note": "Seguimiento preliminar generado por referencias exactas, referencias cruzadas y proximidad. El sentido origen/destino es inferido y debe confirmarse sobre el plano.",
    }
