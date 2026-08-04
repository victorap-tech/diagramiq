import re

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from app import models
from app.database import get_db
from app.services.pdf_service import (
    REFERENCE_PATTERN, analyze_context_text, extract_references,
    is_valid_component_reference, normalize_reference, normalize_search_term,
)

router = APIRouter(prefix="/search", tags=["Búsqueda"])


LIST_PAGE_KEYWORDS = (
    "LISTA DE CABLE", "LISTADO DE CABLE", "CABLE LIST", "WIRE LIST",
    "LISTA DE HILOS", "LISTA DE CONEXIONES", "LISTA DE MATERIALES",
    "BORNERA", "BORNEROS", "TERMINAL PLAN", "TABLA DE CABLE",
    "INDICE", "ÍNDICE", "DIRECTORIO DE PAGINAS", "DIRECTORIO DE PÁGINAS",
)

SCHEMATIC_KEYWORDS = (
    "ESQUEMA ELECTRICO", "ESQUEMA ELÉCTRICO", "PLANO ELECTRICO",
    "PLANO ELÉCTRICO", "ACCIONAMIENTO", "ALIMENTACION", "ALIMENTACIÓN",
    "AVISO", "ENTRADA", "SALIDA", "CONTACTO", "BOBINA", "MOTOR",
    "SENSOR", "MODULO", "MÓDULO", "SIEMENS", "PLC",
)


def reference_family(reference: str) -> str:
    value = normalize_reference(reference)
    # KE1.6 -> KE1; FC011 -> FC; 401_A1+ -> 401_A1
    match = re.match(r"([A-Z]+\d+)", value)
    if match:
        return match.group(1)
    match = re.match(r"([A-Z]+)", value)
    if match:
        return match.group(1)
    return value.split(".", 1)[0]


def score_reference_result(item: models.ComponentReference, searched_reference: str) -> tuple[int, dict]:
    """Prioriza páginas de esquema/componente y deja tablas/listados al final."""
    page = item.document_page
    page_text = (page.text_content or "").upper()
    row_text = (item.row_text or "").upper()
    normalized = normalize_reference(searched_reference)
    family = reference_family(normalized)

    score = 100
    reasons: list[str] = []

    if item.x is not None and item.y is not None:
        score += 20
        reasons.append("coordenadas")
    else:
        score -= 25

    if getattr(item, "catalog_confidence", 0):
        score += min(22, round(item.catalog_confidence / 5))
        reasons.append("validado_por_lista")
    if getattr(item, "source_kind", "") == "component_list":
        score -= 65
        reasons.append("fuente_lista")

    if item.detected_type:
        score += 16
        reasons.append("tipo_detectado")
    if item.model:
        score += 10
        reasons.append("modelo_detectado")
    if item.description and normalize_reference(item.description) != normalized:
        score += 8

    keyword_hits = sum(1 for keyword in SCHEMATIC_KEYWORDS if keyword in page_text)
    if keyword_hits:
        score += min(24, keyword_hits * 4)
        reasons.append("pagina_esquema")

    list_hits = sum(1 for keyword in LIST_PAGE_KEYWORDS if keyword in page_text)
    if list_hits:
        score -= min(70, list_hits * 22)
        reasons.append("pagina_listado")

    # Una página con muchas designaciones de la misma familia suele ser una
    # vista general, índice de PLC o lista de cables, no el componente concreto.
    all_refs = extract_references(page_text)
    same_family = [ref for ref in all_refs if reference_family(ref) == family]
    if len(same_family) >= 10:
        score -= 55
        reasons.append("familia_muy_repetida")
    elif len(same_family) >= 6:
        score -= 38
    elif len(same_family) >= 3:
        score -= 14
    else:
        score += 12
        reasons.append("referencia_aislada")

    if len(all_refs) >= 80:
        score -= 35
    elif len(all_refs) >= 45:
        score -= 22
    elif len(all_refs) >= 25:
        score -= 10

    # En una página de componente normalmente hay texto descriptivo junto a
    # la etiqueta; en listados la fila suele contener casi sólo referencias.
    row_refs = extract_references(row_text)
    non_ref_text = REFERENCE_PATTERN.sub(" ", row_text)
    non_ref_text = re.sub(r"[^A-ZÁÉÍÓÚÜÑ]+", " ", non_ref_text).strip()
    if len(non_ref_text) >= 12:
        score += 18
        reasons.append("descripcion_cercana")
    if len(row_refs) >= 5:
        score -= 18

    # Desempate estable: una coincidencia visual pequeña y concreta suele ser
    # mejor que una entrada genérica sin contexto.
    area = (item.width or 0) * (item.height or 0)
    if 0 < area < 12000:
        score += 3

    return score, {
        "score": score,
        "page_kind": "component" if score >= 105 else ("list" if score < 70 else "possible_component"),
        "ranking_reasons": reasons,
    }


def score_term_result(item: models.PageSearchTerm, searched_text: str) -> tuple[int, dict]:
    """Aplica la misma prioridad aunque el PDF todavía no haya sido reprocesado."""
    page_text = (item.document_page.text_content or "").upper()
    row_text = (item.row_text or "").upper()
    normalized = normalize_reference(searched_text) or normalize_search_term(searched_text)
    family = reference_family(normalized)
    score = 100
    reasons: list[str] = []

    if item.x is not None and item.y is not None:
        score += 20
        reasons.append("coordenadas")

    list_hits = sum(1 for keyword in LIST_PAGE_KEYWORDS if keyword in page_text)
    if list_hits:
        score -= min(70, list_hits * 22)
        reasons.append("pagina_listado")

    schematic_hits = sum(1 for keyword in SCHEMATIC_KEYWORDS if keyword in page_text)
    if schematic_hits:
        score += min(24, schematic_hits * 4)
        reasons.append("pagina_esquema")

    all_refs = extract_references(page_text)
    same_family = [ref for ref in all_refs if reference_family(ref) == family]
    if len(same_family) >= 10:
        score -= 55
        reasons.append("familia_muy_repetida")
    elif len(same_family) >= 6:
        score -= 38
    elif len(same_family) >= 3:
        score -= 14
    else:
        score += 12
        reasons.append("referencia_aislada")

    if len(all_refs) >= 80:
        score -= 35
    elif len(all_refs) >= 45:
        score -= 22
    elif len(all_refs) >= 25:
        score -= 10

    row_refs = extract_references(row_text)
    non_ref_text = REFERENCE_PATTERN.sub(" ", row_text)
    non_ref_text = re.sub(r"[^A-ZÁÉÍÓÚÜÑ]+", " ", non_ref_text).strip()
    if len(non_ref_text) >= 12:
        score += 18
        reasons.append("descripcion_cercana")
    if len(row_refs) >= 5:
        score -= 18

    return score, {
        "score": score,
        "page_kind": "component" if score >= 105 else ("list" if score < 70 else "possible_component"),
        "ranking_reasons": reasons,
    }



def add_relative_visual_score(
    ranked_items: list[tuple[int, int, int, models.ComponentReference, dict]],
) -> list[tuple[int, int, int, models.ComponentReference, dict]]:
    """Ajusta el ranking dentro de cada página usando el tamaño visual relativo.

    En planos EPLAN la designación principal del componente suele imprimirse
    más grande que una referencia de cable o continuidad. Este ajuste se hace
    sobre el índice ya guardado, por lo que no abre el PDF ni ralentiza la
    búsqueda.
    """
    by_page: dict[int, list[tuple[int, int, int, models.ComponentReference, dict]]] = {}
    for row in ranked_items:
        by_page.setdefault(row[3].document_page_id, []).append(row)

    adjusted = []
    for page_rows in by_page.values():
        heights = [max(0, r[3].height or 0) for r in page_rows]
        widths = [max(0, r[3].width or 0) for r in page_rows]
        max_height = max(heights, default=0)
        max_width = max(widths, default=0)

        for score, page_number, item_id, item, ranking in page_rows:
            visual_bonus = 0
            h = max(0, item.height or 0)
            w = max(0, item.width or 0)
            reasons = list(ranking.get("ranking_reasons") or [])

            if max_height and h >= max_height * 0.9:
                visual_bonus += 24
                reasons.append("texto_principal_mas_alto")
            elif max_height and h <= max_height * 0.65:
                visual_bonus -= 18
                reasons.append("texto_pequeno_de_cable")

            if max_width and w >= max_width * 0.9:
                visual_bonus += 8
            elif max_width and w <= max_width * 0.55:
                visual_bonus -= 5

            # Una designación próxima al tercio superior/central del plano es
            # más probable que sea el rótulo del símbolo que una nota de borde.
            if item.y is not None and item.y > 20:
                visual_bonus += 2

            final_score = score + visual_bonus
            new_ranking = dict(ranking)
            new_ranking.update({
                "score": final_score,
                "ranking_reasons": reasons,
                "visual_priority": visual_bonus,
            })
            adjusted.append((final_score, page_number, item_id, item, new_ranking))

    return adjusted


def select_primary_per_page(
    ranked_items: list[tuple[int, int, int, models.ComponentReference, dict]],
) -> list[tuple[int, int, int, models.ComponentReference, dict]]:
    """Devuelve primero una sola aparición principal por página.

    Las otras apariciones se conservan como secundarias para no perder
    información, pero no interfieren con el recorrido principal del visor.
    """
    ranked_items = add_relative_visual_score(ranked_items)
    ranked_items.sort(key=lambda value: (-value[0], value[1], value[2]))

    primary = []
    secondary = []
    seen_pages: set[int] = set()
    for row in ranked_items:
        score, page_number, item_id, item, ranking = row
        ranking = dict(ranking)
        if item.document_page_id not in seen_pages:
            seen_pages.add(item.document_page_id)
            ranking["is_primary_component"] = ranking.get("page_kind") != "list"
            ranking["result_role"] = "primary" if ranking.get("page_kind") != "list" else "list"
            primary.append((score, page_number, item_id, item, ranking))
        else:
            ranking["is_primary_component"] = False
            ranking["result_role"] = "secondary_occurrence"
            secondary.append((score, page_number, item_id, item, ranking))

    # Primero componentes posibles/reales; luego listados y por último las
    # repeticiones secundarias dentro de una página.
    primary.sort(key=lambda r: (r[4].get("page_kind") == "list", -r[0], r[1], r[2]))
    secondary.sort(key=lambda r: (-r[0], r[1], r[2]))
    return primary + secondary


def expanded_component_coordinates(item: models.ComponentReference, ranking: dict) -> dict:
    """Amplía el rectángulo del rótulo para incluir el símbolo cercano."""
    if None in (item.x, item.y, item.width, item.height):
        return {"x": item.x, "y": item.y, "width": item.width, "height": item.height}

    if ranking.get("result_role") != "primary":
        return {"x": item.x, "y": item.y, "width": item.width, "height": item.height}

    # En la mayoría de esquemas la referencia está encima o al costado del
    # símbolo. El visor centra esta zona ampliada sin ocultar la etiqueta.
    left = max(0, item.x - max(45, item.width * 2))
    top = max(0, item.y - max(35, item.height * 2))
    width = max(110, item.width * 5)
    height = max(105, item.height * 7)
    return {"x": left, "y": top, "width": width, "height": height}

def extract_search_references(query: str) -> list[str]:
    matches = REFERENCE_PATTERN.findall((query or "").upper())
    return sorted({normalize_reference(m) for m in matches if normalize_reference(m)})


def build_fragment(text: str | None, query: str, before: int = 100, after: int = 180) -> str:
    if not text:
        return ""
    lower = text.lower()
    pos = lower.find(query.lower())
    if pos < 0:
        return text[: before + after].strip()
    return text[max(0, pos-before): min(len(text), pos+len(query)+after)].strip()


def base_result(page: models.DocumentPage, query: str) -> dict:
    document = page.document
    sector = document.sector
    plant = sector.plant if sector else None
    return {
        "query": query,
        "document_id": document.id,
        "title": document.title,
        "filename": document.filename,
        "document_type": document.document_type,
        "processing_status": document.processing_status,
        "sector_id": document.sector_id,
        "sector_name": sector.name if sector else None,
        "plant_id": plant.id if plant else None,
        "plant_name": plant.name if plant else None,
        "page_id": page.id,
        "page_number": page.page_number,
        "page": page.page_number,
        "image_path": f"/documents/{document.id}/pages/{page.page_number}/image",
    }


def serialize_reference(item: models.ComponentReference, query: str, ranking: dict | None = None) -> dict:
    page = item.document_page
    result = base_result(page, query)
    context = {
        "row_text": item.row_text,
        "description": item.description,
        "detected_type": item.detected_type,
        "model": item.model,
        "manufacturer": getattr(item, "manufacturer", None),
        "source_kind": getattr(item, "source_kind", None),
        "catalog_confidence": getattr(item, "catalog_confidence", 0),
    }
    related = [
        ref for ref in extract_references(item.row_text or "")
        if is_valid_component_reference(ref)
        and normalize_reference(ref) != normalize_reference(item.reference)
    ]
    result.update({
        "match_type": "reference",
        "reference": item.reference,
        "normalized_reference": item.normalized_reference or normalize_reference(item.reference),
        "component_type": item.detected_type or item.component_type,
        "fragment": item.row_text or build_fragment(page.text_content, item.reference),
        "coordinates": expanded_component_coordinates(item, ranking or {}),
        "label_coordinates": {"x": item.x, "y": item.y, "width": item.width, "height": item.height},
        "context": context,
        "related_references": related[:12],
    })
    return result


def serialize_term(item: models.PageSearchTerm, query: str) -> dict:
    page = item.document_page
    result = base_result(page, query)
    context = analyze_context_text(item.row_text, item.display_text)
    result.update({
        "match_type": "text",
        "reference": None,
        "normalized_reference": None,
        "component_type": context.get("detected_type"),
        "fragment": item.row_text or build_fragment(page.text_content, query),
        "coordinates": {"x": item.x, "y": item.y, "width": item.width, "height": item.height},
        "context": context,
    })
    return result


def with_relations(query):
    return query.options(
        joinedload(models.PageSearchTerm.document_page)
        .joinedload(models.DocumentPage.document)
        .joinedload(models.Document.sector)
        .joinedload(models.Sector.plant)
    )


@router.get("")
def search_documents(
    q: str,
    sector_id: int | None = None,
    document_id: int | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Busca exclusivamente en el índice persistente; nunca abre el PDF."""
    clean_query = q.strip()
    if not clean_query:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Debe ingresar un término de búsqueda")

    extracted_references = extract_search_references(clean_query)
    results: list[dict] = []
    total = 0

    if extracted_references:
        query = (
            db.query(models.ComponentReference)
            .options(
                joinedload(models.ComponentReference.document_page)
                .joinedload(models.DocumentPage.document)
                .joinedload(models.Document.sector)
                .joinedload(models.Sector.plant)
            )
            .join(models.DocumentPage)
            .join(models.Document)
        )
        filters = []
        for reference in extracted_references:
            filters.extend([
                models.ComponentReference.normalized_reference == reference,
                models.ComponentReference.reference.ilike(reference),
            ])
        query = query.filter(or_(*filters))
        if sector_id is not None:
            query = query.filter(models.Document.sector_id == sector_id)
        if document_id is not None:
            query = query.filter(models.Document.id == document_id)
        items = query.order_by(models.Document.id, models.DocumentPage.page_number, models.ComponentReference.id).all()
        ranked_items = []
        primary_reference = extracted_references[0]
        for item in items:
            # Compatibilidad con índices antiguos: descartar falsos positivos
            # como palabras de borde que fueron clasificadas como DI/DO.
            if not is_valid_component_reference(item.reference):
                continue
            ranking_score, ranking = score_reference_result(item, primary_reference)
            ranked_items.append((ranking_score, item.document_page.page_number, item.id, item, ranking))

        ranked_items = select_primary_per_page(ranked_items)
        total = len(ranked_items)
        selected = ranked_items[offset: offset + limit]
        results = []
        for _score, _page_number, _item_id, item, ranking in selected:
            serialized = serialize_reference(item, clean_query, ranking)
            serialized.update(ranking)
            results.append(serialized)
    else:
        # Para frases se usa la palabra más específica/larga como acceso al índice.
        tokens = [normalize_search_term(x) for x in re.split(r"\s+", clean_query)]
        tokens = [x for x in tokens if len(x) >= 2]
        if not tokens:
            return {"query": clean_query, "detected_references": extracted_references, "results": [], "count": 0, "total": 0, "limit": limit, "offset": offset, "has_more": False, "search_mode": "index"}
        indexed_term = max(tokens, key=len)
        query = (
            db.query(models.PageSearchTerm)
            .options(
                joinedload(models.PageSearchTerm.document_page)
                .joinedload(models.DocumentPage.document)
                .joinedload(models.Document.sector)
                .joinedload(models.Sector.plant)
            )
            .join(models.DocumentPage)
            .join(models.Document)
            .filter(models.PageSearchTerm.term == indexed_term)
        )
        if sector_id is not None:
            query = query.filter(models.Document.sector_id == sector_id)
        if document_id is not None:
            query = query.filter(models.Document.id == document_id)
        items = query.order_by(models.Document.id, models.DocumentPage.page_number, models.PageSearchTerm.id).all()
        ranked_items = []
        for item in items:
            ranking_score, ranking = score_term_result(item, clean_query)
            ranked_items.append((ranking_score, item.document_page.page_number, item.id, item, ranking))
        ranked_items.sort(key=lambda value: (-value[0], value[1], value[2]))
        total = len(ranked_items)
        selected = ranked_items[offset: offset + limit]
        results = []
        for _score, _page_number, _item_id, item, ranking in selected:
            serialized = serialize_term(item, clean_query)
            serialized.update(ranking)
            results.append(serialized)

    return {
        "query": clean_query,
        "detected_references": extracted_references,
        "sector_id": sector_id,
        "document_id": document_id,
        "results": results,
        "count": len(results),
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(results) < total,
        "search_mode": "persistent_database_index",
    }
