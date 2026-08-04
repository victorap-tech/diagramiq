/* =========================================================
   DiagramIQ Frontend
   app/static/app.js
   ========================================================= */

"use strict";

/* =========================================================
   CONFIGURACIÓN
   ========================================================= */

const API = {
    health: "/",
    organizations: "/organizations",
    plants: "/plants",
    sectors: "/sectors",
    documents: "/documents",
    search: "/search",
    cableTagRecognize: "/cable-tags/recognize",
    componentRecognize: "/components/recognize",
    visionAnalyze: "/vision/analyze",
    componentCatalog: "/component-catalog",
    componentRelations: "/component-relations",
};


/* =========================================================
   REFERENCIAS A ELEMENTOS HTML
   ========================================================= */

const elements = {
    statusIndicator: document.getElementById("statusIndicator"),
    statusText: document.getElementById("statusText"),

    navButtons: document.querySelectorAll(".nav-button"),
    appSections: document.querySelectorAll(".app-section"),

    organizationForm: document.getElementById("organizationForm"),
    organizationName: document.getElementById("organizationName"),
    organizationDescription: document.getElementById("organizationDescription"),
    organizationSubmitButton: document.getElementById("organizationSubmitButton"),
    organizationMessage: document.getElementById("organizationMessage"),
    organizationsList: document.getElementById("organizationsList"),
    refreshOrganizationsButton: document.getElementById("refreshOrganizationsButton"),

    searchOrganization: document.getElementById("searchOrganization"),
    searchPlant: document.getElementById("searchPlant"),
    searchSector: document.getElementById("searchSector"),
    searchForm: document.getElementById("searchForm"),
    searchInput: document.getElementById("searchInput"),
    searchButton: document.getElementById("searchButton"),
    detectedReferences: document.getElementById("detectedReferences"),
    searchMessage: document.getElementById("searchMessage"),
    searchLoading: document.getElementById("searchLoading"),
    searchResults: document.getElementById("searchResults"),
    cableTagPhoto: document.getElementById("cableTagPhoto"),
    cableTagStatus: document.getElementById("cableTagStatus"),
    componentPhoto: document.getElementById("componentPhoto"),
    componentPhotoStatus: document.getElementById("componentPhotoStatus"),
    visionPhoto: document.getElementById("visionPhoto"),
    visionStatus: document.getElementById("visionStatus"),
    visionResult: document.getElementById("visionResult"),
    visionResultTitle: document.getElementById("visionResultTitle"),
    visionResultDetails: document.getElementById("visionResultDetails"),
    visionSearchButton: document.getElementById("visionSearchButton"),
    visionCircuitButton: document.getElementById("visionCircuitButton"),
    visionRetryButton: document.getElementById("visionRetryButton"),

    componentOrganization: document.getElementById("componentOrganization"),
    componentPlant: document.getElementById("componentPlant"),
    componentSector: document.getElementById("componentSector"),
    componentType: document.getElementById("componentType"),
    componentQuery: document.getElementById("componentQuery"),
    componentSummary: document.getElementById("componentSummary"),
    componentsMessage: document.getElementById("componentsMessage"),
    componentsLoading: document.getElementById("componentsLoading"),
    componentsList: document.getElementById("componentsList"),
    refreshComponentsButton: document.getElementById("refreshComponentsButton"),

    uploadOrganization: document.getElementById("uploadOrganization"),
    uploadPlant: document.getElementById("uploadPlant"),
    newPlantName: document.getElementById("newPlantName"),
    uploadSector: document.getElementById("uploadSector"),
    newSectorName: document.getElementById("newSectorName"),
    uploadForm: document.getElementById("uploadForm"),
    documentTitle: document.getElementById("documentTitle"),
    documentDescription: document.getElementById("documentDescription"),
    documentType: document.getElementById("documentType"),
    equipmentId: document.getElementById("equipmentId"),
    pdfFile: document.getElementById("pdfFile"),
    fileDropArea: document.getElementById("fileDropArea"),
    selectedFileName: document.getElementById("selectedFileName"),
    uploadButton: document.getElementById("uploadButton"),
    uploadProgress: document.getElementById("uploadProgress"),
    uploadProgressBar: document.getElementById("uploadProgressBar"),
    uploadProgressText: document.getElementById("uploadProgressText"),
    uploadMessage: document.getElementById("uploadMessage"),

    refreshDocumentsButton: document.getElementById("refreshDocumentsButton"),
    cleanupDocumentsButton: document.getElementById("cleanupDocumentsButton"),
    documentsMessage: document.getElementById("documentsMessage"),
    documentsLoading: document.getElementById("documentsLoading"),
    documentsList: document.getElementById("documentsList"),

    viewerModal: document.getElementById("viewerModal"),
    viewerTitle: document.getElementById("viewerTitle"),
    viewerSubtitle: document.getElementById("viewerSubtitle"),
    viewerContext: document.getElementById("viewerContext"),
    viewerPreviousButton: document.getElementById("viewerPreviousButton"),
    viewerNextButton: document.getElementById("viewerNextButton"),
    viewerPosition: document.getElementById("viewerPosition"),
    viewerCanvas: document.getElementById("viewerCanvas"),
    viewerImage: document.getElementById("viewerImage"),
    referenceHighlight: document.getElementById("referenceHighlight"),
    closeViewerButton: document.getElementById("closeViewerButton"),
    modalOverlay: document.querySelector(".modal-overlay"),
};


/* =========================================================
   ESTADO INTERNO
   ========================================================= */

const state = {
    organizations: [],
    plants: [],
    sectors: [],
    documents: [],
    componentCatalog: [],

    search: {
        organizationId: null,
        plantId: null,
        sectorId: null,
        results: [],
    },

    upload: {
        organizationId: null,
        plantId: null,
        sectorId: null,
    },

    viewer: {
        result: null,
        resultIndex: -1,
        coordinates: null,
        scale: 1,
    },
};


/* =========================================================
   FUNCIONES GENERALES
   ========================================================= */

function toArray(value) {
    if (Array.isArray(value)) return value;
    if (value && Array.isArray(value.items)) return value.items;
    if (value && Array.isArray(value.results)) return value.results;
    if (value && Array.isArray(value.data)) return value.data;
    return [];
}


function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}


function normalizeId(value) {
    if (value === null || value === undefined || value === "") return null;

    const numberValue = Number(value);
    return Number.isNaN(numberValue) ? value : numberValue;
}


function getObjectId(item) {
    return (
        item?.id ??
        item?.organization_id ??
        item?.plant_id ??
        item?.sector_id ??
        item?.document_id ??
        null
    );
}


function getObjectName(item) {
    return (
        item?.name ??
        item?.title ??
        item?.description ??
        `Elemento ${getObjectId(item) ?? ""}`
    );
}


function buildQuery(params = {}) {
    const searchParams = new URLSearchParams();

    Object.entries(params).forEach(([key, value]) => {
        if (value !== null && value !== undefined && value !== "") {
            searchParams.append(key, value);
        }
    });

    const queryString = searchParams.toString();
    return queryString ? `?${queryString}` : "";
}


async function apiRequest(url, options = {}) {
    const config = {
        method: options.method || "GET",
        headers: {
            Accept: "application/json",
            ...(options.headers || {}),
        },
        body: options.body,
    };

    if (
        config.body &&
        !(config.body instanceof FormData) &&
        typeof config.body !== "string"
    ) {
        config.headers["Content-Type"] = "application/json";
        config.body = JSON.stringify(config.body);
    }

    let response;

    try {
        response = await fetch(url, config);
    } catch {
        throw new Error("No se pudo conectar con el servidor.");
    }

    let responseData = null;
    const contentType = response.headers.get("content-type") || "";

    try {
        responseData = contentType.includes("application/json")
            ? await response.json()
            : await response.text();
    } catch {
        responseData = null;
    }

    if (!response.ok) {
        let detail =
            responseData?.detail ??
            responseData?.message ??
            responseData?.error ??
            null;

        if (Array.isArray(detail)) {
            detail = detail
                .map((item) => item?.msg || JSON.stringify(item))
                .join(". ");
        }

        if (!detail && typeof responseData === "string") {
            detail = responseData;
        }

        throw new Error(detail || `Error del servidor: ${response.status}`);
    }

    return responseData;
}


/* =========================================================
   MENSAJES
   ========================================================= */

function showMessage(element, text, type = "info") {
    if (!element) return;

    element.textContent = text;
    element.classList.remove("hidden", "success", "error", "info");
    element.classList.add(type);
}


function hideMessage(element) {
    if (!element) return;

    element.textContent = "";
    element.classList.add("hidden");
    element.classList.remove("success", "error", "info");
}


/* =========================================================
   SELECTORES
   ========================================================= */

function resetSelect(selectElement, placeholder, disabled = true) {
    if (!selectElement) return;

    selectElement.innerHTML = `
        <option value="">${escapeHtml(placeholder)}</option>
    `;
    selectElement.value = "";
    selectElement.disabled = disabled;
}


function fillSelect(selectElement, items, placeholder, selectedValue = "") {
    if (!selectElement) return;

    const options = items
        .map((item) => {
            const id = getObjectId(item);
            const name = getObjectName(item);

            return `
                <option value="${escapeHtml(id)}">
                    ${escapeHtml(name)}
                </option>
            `;
        })
        .join("");

    selectElement.innerHTML = `
        <option value="">${escapeHtml(placeholder)}</option>
        ${options}
    `;

    selectElement.disabled = false;

    if (selectedValue !== null && selectedValue !== undefined) {
        selectElement.value = String(selectedValue);
    }
}


/* =========================================================
   NAVEGACIÓN
   ========================================================= */

function activateSection(sectionId) {
    elements.navButtons.forEach((button) => {
        button.classList.toggle(
            "active",
            button.dataset.section === sectionId
        );
    });

    elements.appSections.forEach((section) => {
        section.classList.toggle("active", section.id === sectionId);
    });

    if (sectionId === "documentsSection") {
        loadDocuments();
    }
}


function initializeNavigation() {
    elements.navButtons.forEach((button) => {
        button.addEventListener("click", () => {
            activateSection(button.dataset.section);
        });
    });
}


/* =========================================================
   ESTADO DE LA API
   ========================================================= */

function setApiStatus(isOnline, text) {
    elements.statusIndicator?.classList.remove("online", "offline");
    elements.statusIndicator?.classList.add(isOnline ? "online" : "offline");

    if (elements.statusText) {
        elements.statusText.textContent = text;
    }
}


async function checkApiStatus() {
    try {
        await apiRequest(API.health);
        setApiStatus(true, "Servidor conectado");
    } catch {
        try {
            await apiRequest(API.organizations);
            setApiStatus(true, "Servidor conectado");
        } catch {
            setApiStatus(false, "Servidor sin conexión");
        }
    }
}


/* =========================================================
   ORGANIZACIONES, PLANTAS Y SECTORES
   ========================================================= */

async function loadOrganizations() {
    try {
        const response = await apiRequest(API.organizations);
        state.organizations = toArray(response);
        renderOrganizations();

        fillSelect(
            elements.searchOrganization,
            state.organizations,
            "Seleccionar empresa"
        );

        fillSelect(
            elements.uploadOrganization,
            state.organizations,
            "Seleccionar empresa"
        );

        resetSelect(elements.searchPlant, "Seleccionar planta");
        resetSelect(elements.searchSector, "Seleccionar sector");
        resetSelect(elements.uploadPlant, "Seleccionar planta");
        resetSelect(elements.uploadSector, "Seleccionar sector");
    } catch (error) {
        console.error("Error cargando organizaciones:", error);

        showMessage(
            elements.searchMessage,
            `No se pudieron cargar las empresas: ${error.message}`,
            "error"
        );

        showMessage(
            elements.uploadMessage,
            `No se pudieron cargar las empresas: ${error.message}`,
            "error"
        );
    }
}



function renderOrganizations() {
    if (!elements.organizationsList) return;

    if (!state.organizations.length) {
        elements.organizationsList.innerHTML = `
            <div class="empty-state">
                Todavía no hay empresas cargadas.
            </div>
        `;
        return;
    }

    elements.organizationsList.innerHTML = state.organizations
        .map((organization) => `
            <article class="entity-card">
                <div class="entity-avatar">
                    ${escapeHtml((organization.name || "E").charAt(0).toUpperCase())}
                </div>
                <div class="entity-content">
                    <h4>${escapeHtml(organization.name)}</h4>
                    <p>${escapeHtml(organization.description || "Sin descripción")}</p>
                </div>
                <button
                    class="danger-button organization-delete-button"
                    type="button"
                    data-organization-id="${escapeHtml(getObjectId(organization))}"
                    data-organization-name="${escapeHtml(organization.name)}"
                    aria-label="Eliminar empresa ${escapeHtml(organization.name)}"
                >
                    Eliminar
                </button>
            </article>
        `)
        .join("");
}

async function deleteOrganization(organizationId, organizationName, button) {
    const confirmed = window.confirm(
        `¿Eliminar la empresa “${organizationName}”?\n\n` +
        "También se eliminarán sus plantas, sectores, equipos y documentos asociados."
    );

    if (!confirmed) return;

    hideMessage(elements.organizationMessage);

    const originalText = button?.textContent || "Eliminar";
    if (button) {
        button.disabled = true;
        button.textContent = "Eliminando...";
    }

    try {
        await apiRequest(`${API.organizations}/${organizationId}`, {
            method: "DELETE",
        });

        await loadOrganizations();
    syncComponentOrganizations();
    await loadComponentCatalog();

        showMessage(
            elements.organizationMessage,
            `Empresa “${organizationName}” eliminada correctamente.`,
            "success"
        );
    } catch (error) {
        showMessage(
            elements.organizationMessage,
            `No se pudo eliminar la empresa: ${error.message}`,
            "error"
        );

        if (button) {
            button.disabled = false;
            button.textContent = originalText;
        }
    }
}


function handleOrganizationsListClick(event) {
    const button = event.target.closest(".organization-delete-button");
    if (!button) return;

    const organizationId = button.dataset.organizationId;
    const organizationName = button.dataset.organizationName || "Empresa";

    if (!organizationId) {
        showMessage(
            elements.organizationMessage,
            "No se pudo identificar la empresa seleccionada.",
            "error"
        );
        return;
    }

    deleteOrganization(organizationId, organizationName, button);
}


async function createOrganization(event) {
    event.preventDefault();
    hideMessage(elements.organizationMessage);

    const name = elements.organizationName?.value.trim() || "";
    const description = elements.organizationDescription?.value.trim() || "";

    if (!name) {
        showMessage(
            elements.organizationMessage,
            "Ingresá el nombre de la empresa.",
            "error"
        );
        elements.organizationName?.focus();
        return;
    }

    const button = elements.organizationSubmitButton;
    if (button) {
        button.disabled = true;
        button.textContent = "Guardando...";
    }

    try {
        const created = await apiRequest(API.organizations, {
            method: "POST",
            body: {
                name,
                description: description || null,
            },
        });

        elements.organizationForm?.reset();
        await loadOrganizations();

        showMessage(
            elements.organizationMessage,
            `Empresa “${created.name}” guardada correctamente.`,
            "success"
        );
        elements.organizationName?.focus();
    } catch (error) {
        showMessage(
            elements.organizationMessage,
            `No se pudo guardar la empresa: ${error.message}`,
            "error"
        );
    } finally {
        if (button) {
            button.disabled = false;
            button.textContent = "Guardar empresa";
        }
    }
}

function initializeOrganizationEvents() {
    elements.organizationForm?.addEventListener("submit", createOrganization);
    elements.refreshOrganizationsButton?.addEventListener("click", loadOrganizations);
    elements.organizationsList?.addEventListener("click", handleOrganizationsListClick);
}

async function fetchPlantsByOrganization(organizationId) {
    if (!organizationId) return [];

    const response = await apiRequest(
        `${API.plants}${buildQuery({ organization_id: organizationId })}`
    );

    return toArray(response).filter((plant) => {
        const plantOrganizationId =
            plant.organization_id ??
            plant.organization?.id ??
            null;

        return (
            plantOrganizationId === null ||
            String(plantOrganizationId) === String(organizationId)
        );
    });
}


async function fetchSectorsByPlant(plantId) {
    if (!plantId) return [];

    const response = await apiRequest(
        `${API.sectors}${buildQuery({ plant_id: plantId })}`
    );

    return toArray(response).filter((sector) => {
        const sectorPlantId =
            sector.plant_id ??
            sector.plant?.id ??
            null;

        return (
            sectorPlantId === null ||
            String(sectorPlantId) === String(plantId)
        );
    });
}


async function loadSearchPlants(organizationId) {
    resetSelect(elements.searchPlant, "Cargando plantas...");
    resetSelect(elements.searchSector, "Seleccionar sector");

    state.search.organizationId = normalizeId(organizationId);
    state.search.plantId = null;
    state.search.sectorId = null;

    if (!organizationId) {
        resetSelect(elements.searchPlant, "Seleccionar planta");
        return;
    }

    try {
        const plants = await fetchPlantsByOrganization(organizationId);
        state.plants = plants;

        fillSelect(
            elements.searchPlant,
            plants,
            plants.length ? "Seleccionar planta" : "No hay plantas"
        );
    } catch (error) {
        resetSelect(elements.searchPlant, "Error al cargar plantas");

        showMessage(
            elements.searchMessage,
            `No se pudieron cargar las plantas: ${error.message}`,
            "error"
        );
    }
}


async function loadUploadPlants(organizationId) {
    resetSelect(elements.uploadPlant, "Cargando plantas...");
    resetSelect(elements.uploadSector, "Seleccionar sector");

    state.upload.organizationId = normalizeId(organizationId);
    state.upload.plantId = null;
    state.upload.sectorId = null;

    if (!organizationId) {
        resetSelect(elements.uploadPlant, "Seleccionar planta");
        return;
    }

    try {
        const plants = await fetchPlantsByOrganization(organizationId);
        state.plants = plants;

        fillSelect(
            elements.uploadPlant,
            plants,
            plants.length ? "Seleccionar planta" : "No hay plantas"
        );
    } catch (error) {
        resetSelect(elements.uploadPlant, "Error al cargar plantas");

        showMessage(
            elements.uploadMessage,
            `No se pudieron cargar las plantas: ${error.message}`,
            "error"
        );
    }
}


async function loadSearchSectors(plantId) {
    resetSelect(elements.searchSector, "Cargando sectores...");

    state.search.plantId = normalizeId(plantId);
    state.search.sectorId = null;

    if (!plantId) {
        resetSelect(elements.searchSector, "Seleccionar sector");
        return;
    }

    try {
        const sectors = await fetchSectorsByPlant(plantId);
        state.sectors = sectors;

        fillSelect(
            elements.searchSector,
            sectors,
            sectors.length ? "Seleccionar sector" : "No hay sectores"
        );
    } catch (error) {
        resetSelect(elements.searchSector, "Error al cargar sectores");

        showMessage(
            elements.searchMessage,
            `No se pudieron cargar los sectores: ${error.message}`,
            "error"
        );
    }
}


async function loadUploadSectors(plantId) {
    resetSelect(elements.uploadSector, "Cargando sectores...");

    state.upload.plantId = normalizeId(plantId);
    state.upload.sectorId = null;

    if (!plantId) {
        resetSelect(elements.uploadSector, "Seleccionar sector");
        return;
    }

    try {
        const sectors = await fetchSectorsByPlant(plantId);
        state.sectors = sectors;

        fillSelect(
            elements.uploadSector,
            sectors,
            sectors.length ? "Seleccionar sector" : "No hay sectores"
        );
    } catch (error) {
        resetSelect(elements.uploadSector, "Error al cargar sectores");

        showMessage(
            elements.uploadMessage,
            `No se pudieron cargar los sectores: ${error.message}`,
            "error"
        );
    }
}


function initializeHierarchyEvents() {
    elements.searchOrganization?.addEventListener("change", async (event) => {
        hideMessage(elements.searchMessage);
        await loadSearchPlants(event.target.value);
    });

    elements.searchPlant?.addEventListener("change", async (event) => {
        hideMessage(elements.searchMessage);
        await loadSearchSectors(event.target.value);
    });

    elements.searchSector?.addEventListener("change", (event) => {
        state.search.sectorId = normalizeId(event.target.value);
    });

    elements.uploadOrganization?.addEventListener("change", async (event) => {
        hideMessage(elements.uploadMessage);
        await loadUploadPlants(event.target.value);
    });

    elements.uploadPlant?.addEventListener("change", async (event) => {
        hideMessage(elements.uploadMessage);

        if (event.target.value && elements.newPlantName) {
            elements.newPlantName.value = "";
        }

        await loadUploadSectors(event.target.value);
    });

    elements.newPlantName?.addEventListener("input", (event) => {
        if (event.target.value.trim() && elements.uploadPlant) {
            elements.uploadPlant.value = "";
            state.upload.plantId = null;
            resetSelect(elements.uploadSector, "El sector se creará en la planta nueva");
        } else if (elements.uploadOrganization?.value) {
            resetSelect(elements.uploadSector, "Seleccionar sector");
        }
    });

    elements.uploadSector?.addEventListener("change", (event) => {
        state.upload.sectorId = normalizeId(event.target.value);

        if (event.target.value && elements.newSectorName) {
            elements.newSectorName.value = "";
        }
    });

    elements.newSectorName?.addEventListener("input", (event) => {
        if (event.target.value.trim() && elements.uploadSector) {
            elements.uploadSector.value = "";
            state.upload.sectorId = null;
        }
    });
}


/* =========================================================
   BÚSQUEDA
   ========================================================= */

function clearSearchResults() {
    if (elements.searchResults) {
        elements.searchResults.innerHTML = "";
    }

    if (elements.detectedReferences) {
        elements.detectedReferences.innerHTML = "";
        elements.detectedReferences.classList.add("hidden");
    }
}


function setSearchLoading(isLoading) {
    elements.searchLoading?.classList.toggle("hidden", !isLoading);

    if (elements.searchButton) {
        elements.searchButton.disabled = isLoading;
        elements.searchButton.textContent = isLoading
            ? "Buscando..."
            : "Buscar";
    }
}


function getDetectedReferences(response) {
    const references =
        response?.detected_references ??
        response?.references ??
        response?.detectedReferences ??
        [];

    if (!Array.isArray(references)) return [];

    return references
        .map((reference) => {
            if (typeof reference === "string") return reference;

            return (
                reference?.reference ??
                reference?.normalized_reference ??
                reference?.name ??
                ""
            );
        })
        .filter(Boolean);
}


function getSearchResults(response) {
    if (Array.isArray(response)) return response;

    return toArray(
        response?.results ??
        response?.items ??
        response?.data ??
        []
    );
}


function renderDetectedReferences(references) {
    if (!elements.detectedReferences || references.length === 0) {
        elements.detectedReferences?.classList.add("hidden");
        return;
    }

    const uniqueReferences = [
        ...new Set(references.map((reference) => String(reference).trim())),
    ];

    elements.detectedReferences.innerHTML = `
        <strong>Referencias detectadas:</strong>
        ${uniqueReferences
            .map(
                (reference) => `
                    <span class="reference-chip">
                        ${escapeHtml(reference)}
                    </span>
                `
            )
            .join("")}
    `;

    elements.detectedReferences.classList.remove("hidden");
}


function getResultDocumentTitle(result) {
    return (
        result?.document_title ??
        result?.document?.title ??
        result?.title ??
        "Documento sin título"
    );
}


function getResultPageNumber(result) {
    return (
        result?.page_number ??
        result?.page?.page_number ??
        result?.page ??
        result?.number ??
        null
    );
}


function getResultReference(result) {
    return (
        result?.reference ??
        result?.normalized_reference ??
        result?.component_reference ??
        result?.tag ??
        ""
    );
}


function getResultText(result) {
    return (
        result?.text_fragment ??
        result?.fragment ??
        result?.matched_text ??
        result?.text ??
        result?.content ??
        ""
    );
}


function getResultImageUrl(result) {
    return (
        result?.image_url ??
        result?.page_image_url ??
        result?.page?.image_url ??
        result?.page_image ??
        result?.image_path ??
        result?.page?.image_path ??
        null
    );
}


function normalizeImageUrl(imageUrl) {
    if (!imageUrl) return null;

    if (
        imageUrl.startsWith("http://") ||
        imageUrl.startsWith("https://") ||
        imageUrl.startsWith("/")
    ) {
        return imageUrl;
    }

    return `/${imageUrl}`;
}


function getResultCoordinates(result) {
    const coordinates =
        result?.coordinates ??
        result?.bounding_box ??
        result?.bbox ??
        {};

    const x = coordinates?.x ?? result?.x ?? null;
    const y = coordinates?.y ?? result?.y ?? null;
    const width = coordinates?.width ?? result?.width ?? null;
    const height = coordinates?.height ?? result?.height ?? null;

    if ([x, y, width, height].some((value) => value === null)) {
        return null;
    }

    return {
        x: Number(x),
        y: Number(y),
        width: Number(width),
        height: Number(height),
    };
}


function getResultDocumentId(result) {
    return result?.document_id ?? result?.document?.id ?? null;
}


function getResultPageId(result) {
    return result?.page_id ?? result?.page?.id ?? null;
}


function buildFallbackPageImageUrl(result) {
    const documentId = getResultDocumentId(result);
    const pageId = getResultPageId(result);
    const pageNumber = getResultPageNumber(result);

    if (pageId) return `${API.documents}/pages/${pageId}/image`;

    if (documentId && pageNumber) {
        return `/documents/${documentId}/pages/${pageNumber}/image`;
    }

    return null;
}


function createOpenViewerButton(result, index) {
    const imageUrl =
        normalizeImageUrl(getResultImageUrl(result)) ??
        buildFallbackPageImageUrl(result);

    if (!imageUrl) {
        return `
            <button class="secondary-button" type="button" disabled>
                Sin imagen
            </button>
        `;
    }

    return `
        <button
            class="primary-button open-viewer-button"
            type="button"
            data-result-index="${index}"
        >
            Abrir plano
        </button>
    `;
}


function renderSearchResults(results) {
    if (!elements.searchResults) return;

    if (results.length === 0) {
        showMessage(
            elements.searchMessage,
            "No se encontraron coincidencias en los documentos del sector seleccionado.",
            "info"
        );

        elements.searchResults.innerHTML = "";
        return;
    }

    elements.searchResults.innerHTML = results
        .map((result, index) => {
            const title = getResultDocumentTitle(result);
            const pageNumber = getResultPageNumber(result);
            const reference = getResultReference(result);
            const fragment = getResultText(result);

            return `
                <article class="result-card">
                    <div class="result-main">
                        <h3>${escapeHtml(title)}</h3>

                        <div class="result-meta">
                            ${
                                pageNumber !== null
                                    ? `<span>Página ${escapeHtml(pageNumber)}</span>`
                                    : ""
                            }

                            ${
                                result?.document_type
                                    ? `<span>${escapeHtml(result.document_type)}</span>`
                                    : ""
                            }

                            ${
                                result?.sector_name
                                    ? `<span>Sector: ${escapeHtml(result.sector_name)}</span>`
                                    : ""
                            }
                        </div>

                        ${(() => {
                            if (result?.result_role === "primary" && result?.page_kind !== "list") {
                                return `<span class="result-priority-badge primary">Componente principal</span>`;
                            }
                            if (result?.page_kind === "list" || result?.result_role === "list") {
                                return `<span class="result-priority-badge list">Aparición en listado</span>`;
                            }
                            if (result?.result_role === "secondary_occurrence") {
                                return `<span class="result-priority-badge secondary">Otra aparición en la página</span>`;
                            }
                            return "";
                        })()}

                        ${
                            reference
                                ? `<span class="result-reference">${escapeHtml(reference)}</span>`
                                : ""
                        }

                        ${
                            fragment
                                ? `<p class="result-fragment">${escapeHtml(fragment)}</p>`
                                : ""
                        }

                        ${(() => {
                            const related = result?.related_references ?? [];
                            if (!related.length) return "";
                            return `<div class="related-references"><strong>Relacionados:</strong> ${related.map((ref) => `<button type="button" class="reference-chip related-reference-button" data-reference="${escapeHtml(ref)}">${escapeHtml(ref)}</button>`).join(" ")}</div>`;
                        })()}

                        ${(() => {
                            const context = result?.context ?? {};
                            const type = context.detected_type;
                            const model = context.model;
                            const description = context.description;
                            if (!type && !model && !description) return "";
                            return `<div class="result-context">
                                ${type ? `<div><strong>Tipo:</strong> ${escapeHtml(type)}</div>` : ""}
                                ${model ? `<div><strong>Modelo:</strong> ${escapeHtml(model)}</div>` : ""}
                                ${description ? `<div><strong>Información del plano:</strong> ${escapeHtml(description)}</div>` : ""}
                            </div>`;
                        })()}
                    </div>

                    <div class="result-actions">
                        ${createOpenViewerButton(result, index)}
                    </div>
                </article>
            `;
        })
        .join("");

    state.search.results = results;
    initializeViewerButtons();
    document.querySelectorAll(".related-reference-button").forEach((button) => {
        button.addEventListener("click", () => {
            if (elements.searchInput) elements.searchInput.value = button.dataset.reference || "";
            elements.searchForm?.requestSubmit();
        });
    });
}


async function handleSearchSubmit(event) {
    event.preventDefault();

    hideMessage(elements.searchMessage);
    clearSearchResults();

    const query = elements.searchInput?.value.trim() ?? "";
    const sectorId =
        elements.searchSector?.value ??
        state.search.sectorId;

    if (!sectorId) {
        showMessage(
            elements.searchMessage,
            "Seleccioná un sector antes de buscar.",
            "error"
        );
        return;
    }

    if (query.length < 2) {
        showMessage(
            elements.searchMessage,
            "Ingresá una referencia, TAG o texto de alarma.",
            "error"
        );
        return;
    }

    state.search.sectorId = normalizeId(sectorId);
    setSearchLoading(true);

    try {
        const response = await apiRequest(
            `${API.search}${buildQuery({
                q: query,
                sector_id: sectorId,
            })}`
        );

        const references = getDetectedReferences(response);
        const results = getSearchResults(response);

        renderDetectedReferences(references);
        renderSearchResults(results);

        if (results.length > 0) {
            showMessage(
                elements.searchMessage,
                `Se encontraron ${results.length} coincidencia${
                    results.length === 1 ? "" : "s"
                }.`,
                "success"
            );
        }
    } catch (error) {
        console.error("Error en búsqueda:", error);

        showMessage(
            elements.searchMessage,
            `No se pudo realizar la búsqueda: ${error.message}`,
            "error"
        );
    } finally {
        setSearchLoading(false);
    }
}


async function handleCableTagPhoto(event) {
    const file = event.target.files?.[0];
    if (!file) return;

    if (elements.cableTagStatus) {
        elements.cableTagStatus.textContent = "Leyendo TAG...";
        elements.cableTagStatus.classList.remove("success", "error");
    }

    const formData = new FormData();
    formData.append("image", file);

    try {
        const response = await apiRequest(API.cableTagRecognize, {
            method: "POST",
            body: formData,
        });

        const tag = String(response?.tag || "").trim();
        if (!tag) {
            throw new Error(response?.message || "No se pudo reconocer el TAG.");
        }

        elements.searchInput.value = tag;
        if (elements.cableTagStatus) {
            const confidence = Number(response?.confidence || 0);
            const confidenceText = confidence > 0
                ? ` (${Math.round(confidence * 100)}% de confianza)`
                : "";
            elements.cableTagStatus.textContent = `TAG leído: ${tag}${confidenceText}`;
            elements.cableTagStatus.classList.add("success");
        }
        elements.searchForm?.requestSubmit();
    } catch (error) {
        if (elements.cableTagStatus) {
            elements.cableTagStatus.textContent = error.message;
            elements.cableTagStatus.classList.add("error");
        }
    } finally {
        event.target.value = "";
    }
}


async function handleComponentPhoto(event) {
    const file = event.target.files?.[0];
    if (!file) return;

    const statusElement = elements.componentPhotoStatus;
    if (statusElement) {
        statusElement.textContent = "Analizando componente...";
        statusElement.classList.remove("success", "error");
    }

    const formData = new FormData();
    formData.append("image", file);

    try {
        const response = await apiRequest(API.componentRecognize, {
            method: "POST",
            body: formData,
        });
        const query = String(response?.search_query || "").trim();
        if (!query) {
            throw new Error(response?.message || "No se pudo identificar el componente.");
        }

        elements.searchInput.value = query;
        const details = [
            response?.component_type,
            response?.brand,
            response?.model,
            response?.reference,
        ].filter(Boolean).join(" · ");
        const confidence = Number(response?.confidence || 0);
        const confidenceText = confidence > 0 ? ` (${Math.round(confidence * 100)}%)` : "";
        if (statusElement) {
            statusElement.textContent = `Identificado: ${details || query}${confidenceText}. Buscando en los planos...`;
            statusElement.classList.add("success");
        }
        elements.searchForm?.requestSubmit();
    } catch (error) {
        if (statusElement) {
            statusElement.textContent = error.message;
            statusElement.classList.add("error");
        }
    } finally {
        event.target.value = "";
    }
}

let lastVisionQuery = "";
let lastVisionResult = null;

function visionKindLabel(kind) {
    return ({ cable_tag: "TAG de cable", component: "Componente", document: "Plano o documento", unknown: "Elemento" })[kind] || "Elemento";
}

async function handleVisionPhoto(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    lastVisionQuery = "";
    lastVisionResult = null;
    if (elements.visionCircuitButton) elements.visionCircuitButton.disabled = true;
    elements.visionResult?.classList.add("hidden");
    if (elements.visionStatus) {
        elements.visionStatus.textContent = "Analizando foto...";
        elements.visionStatus.className = "vision-status loading";
    }
    const formData = new FormData();
    formData.append("image", file);
    try {
        const response = await apiRequest(API.visionAnalyze, { method: "POST", body: formData });
        lastVisionQuery = String(response?.search_query || "").trim();
        lastVisionResult = response;
        const confidence = Number(response?.confidence || 0);
        const titleParts = [visionKindLabel(response?.detected_kind), response?.component_type].filter(Boolean);
        if (elements.visionResultTitle) {
            elements.visionResultTitle.textContent = `${titleParts.join(" · ") || "Resultado"}${confidence ? ` · ${Math.round(confidence * 100)}%` : ""}`;
        }
        const rows = [
            ["TAG", response?.cable_tag], ["Referencia", response?.reference],
            ["Marca", response?.brand], ["Modelo", response?.model],
            ["Descripción", response?.description],
        ].filter(([, value]) => String(value || "").trim());
        if (elements.visionResultDetails) {
            elements.visionResultDetails.innerHTML = rows.map(([label, value]) =>
                `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(String(value))}</strong></div>`
            ).join("") || `<div><strong>${escapeHtml(response?.message || "No se pudo leer información suficiente.")}</strong></div>`;
        }
        if (elements.visionStatus) {
            elements.visionStatus.textContent = lastVisionQuery ? `Listo para buscar: ${lastVisionQuery}` : (response?.message || "Acercá la cámara y probá otra vez.");
            elements.visionStatus.className = `vision-status ${lastVisionQuery ? "success" : "error"}`;
        }
        if (elements.visionSearchButton) elements.visionSearchButton.disabled = !lastVisionQuery;
        const canFollowCircuit = response?.detected_kind === "component" && Boolean(String(response?.reference || response?.model || "").trim());
        if (elements.visionCircuitButton) elements.visionCircuitButton.disabled = !canFollowCircuit;
        elements.visionResult?.classList.remove("hidden");
    } catch (error) {
        if (elements.visionStatus) {
            elements.visionStatus.textContent = error.message;
            elements.visionStatus.className = "vision-status error";
        }
    } finally {
        event.target.value = "";
    }
}

function searchLastVisionResult() {
    if (!lastVisionQuery) return;
    elements.searchInput.value = lastVisionQuery;
    elements.searchForm?.requestSubmit();
}

async function followLastVisionCircuit() {
    const reference = String(lastVisionResult?.reference || lastVisionResult?.model || lastVisionQuery || "").trim();
    if (!reference) return;
    const button = elements.visionCircuitButton;
    const previousText = button?.textContent;
    if (button) { button.disabled = true; button.textContent = "Buscando componente…"; }
    try {
        const params = new URLSearchParams({ q: reference, limit: "50" });
        if (elements.searchOrganization?.value) params.set("organization_id", elements.searchOrganization.value);
        if (elements.searchPlant?.value) params.set("plant_id", elements.searchPlant.value);
        if (elements.searchSector?.value) params.set("sector_id", elements.searchSector.value);
        const response = await apiRequest(`${API.componentCatalog}?${params.toString()}`);
        const items = response?.items || [];
        const normalized = reference.toUpperCase().replace(/\s+/g, "");
        const exact = items.find(item => String(item.reference || "").toUpperCase().replace(/\s+/g, "") === normalized);
        const selected = exact || items[0];
        if (!selected) throw new Error(`No se encontró ${reference} en el catálogo de componentes. Primero procesá el plano o usá Buscar en planos.`);
        await showComponentGraph(selected);
    } catch (error) {
        if (elements.visionStatus) {
            elements.visionStatus.textContent = error.message;
            elements.visionStatus.className = "vision-status error";
        }
    } finally {
        if (button) { button.disabled = false; button.textContent = previousText || "🔄 Seguir circuito"; }
    }
}

function retryVisionPhoto() {
    elements.visionPhoto?.click();
}

function initializeSearchEvents() {
    elements.searchForm?.addEventListener("submit", handleSearchSubmit);
    elements.cableTagPhoto?.addEventListener("change", handleCableTagPhoto);
    elements.componentPhoto?.addEventListener("change", handleComponentPhoto);
    elements.visionPhoto?.addEventListener("change", handleVisionPhoto);
    elements.visionSearchButton?.addEventListener("click", searchLastVisionResult);
    elements.visionCircuitButton?.addEventListener("click", followLastVisionCircuit);
    elements.visionRetryButton?.addEventListener("click", retryVisionPhoto);
}




/* =========================================================
   CATÁLOGO DE COMPONENTES v0.9.7
   ========================================================= */

const COMPONENT_TYPES = ["interruptor","seccionador","guardamotor","contactor","relé","relé térmico","fusible","variador","PLC","módulo de entradas","módulo de salidas","módulo analógico","motor","sensor","bornera","pulsador","piloto","transformador","otro"];

function populateComponentTypeOptions() {
    if (!elements.componentType) return;
    elements.componentType.innerHTML = '<option value="">Todos</option>' + COMPONENT_TYPES.map(t => `<option value="${escapeHtml(t)}">${escapeHtml(t)}</option>`).join('');
}

function syncComponentOrganizations() {
    if (!elements.componentOrganization) return;
    const selected = elements.componentOrganization.value;
    elements.componentOrganization.innerHTML = '<option value="">Todas</option>' + state.organizations.map(o => `<option value="${o.id}">${escapeHtml(o.name)}</option>`).join('');
    elements.componentOrganization.value = selected;
}

async function loadComponentPlants() {
    const orgId = elements.componentOrganization?.value;
    elements.componentPlant.innerHTML = '<option value="">Todas</option>';
    elements.componentSector.innerHTML = '<option value="">Todos</option>';
    elements.componentPlant.disabled = !orgId;
    elements.componentSector.disabled = true;
    if (!orgId) return loadComponentCatalog();
    try {
        const plants = await apiRequest(`${API.plants}?organization_id=${encodeURIComponent(orgId)}`);
        elements.componentPlant.innerHTML += plants.map(p => `<option value="${p.id}">${escapeHtml(p.name)}</option>`).join('');
    } catch (_) {}
    loadComponentCatalog();
}

async function loadComponentSectors() {
    const plantId = elements.componentPlant?.value;
    elements.componentSector.innerHTML = '<option value="">Todos</option>';
    elements.componentSector.disabled = !plantId;
    if (plantId) {
        try {
            const sectors = await apiRequest(`${API.sectors}?plant_id=${encodeURIComponent(plantId)}`);
            elements.componentSector.innerHTML += sectors.map(x => `<option value="${x.id}">${escapeHtml(x.name)}</option>`).join('');
        } catch (_) {}
    }
    loadComponentCatalog();
}

function renderComponentSummary(counts) {
    if (!elements.componentSummary) return;
    elements.componentSummary.innerHTML = Object.entries(counts || {}).map(([type,count]) => `<button type="button" class="component-chip" data-component-type="${escapeHtml(type)}">${escapeHtml(type)} · ${count}</button>`).join('');
    elements.componentSummary.querySelectorAll('[data-component-type]').forEach(btn => btn.addEventListener('click', () => {
        elements.componentType.value = btn.dataset.componentType;
        loadComponentCatalog();
    }));
}

function openComponentInSearch(item) {
    document.querySelector('[data-section="searchSection"]')?.click();
    elements.searchInput.value = item.reference || item.model || '';
    elements.searchOrganization.value = String(item.organization_id || '');
    elements.searchOrganization.dispatchEvent(new Event('change'));
    setTimeout(() => {
        elements.searchPlant.value = String(item.plant_id || '');
        elements.searchPlant.dispatchEvent(new Event('change'));
        setTimeout(() => {
            elements.searchSector.value = String(item.sector_id || '');
            elements.searchForm?.requestSubmit();
        }, 350);
    }, 350);
}

function renderComponentCatalog(items) {
    state.componentCatalog = items || [];
    if (!elements.componentsList) return;
    if (!items?.length) {
        elements.componentsList.innerHTML = '<div class="empty-state"><strong>No se encontraron componentes.</strong><p>Procesá un plano o cambiá los filtros.</p></div>';
        return;
    }
    elements.componentsList.innerHTML = items.map((item,index) => `
        <article class="component-catalog-card">
            <div class="component-catalog-type">${escapeHtml(item.component_type || 'otro')}</div>
            <h3>${escapeHtml(item.reference || item.model || 'Sin referencia')}</h3>
            <div class="component-catalog-meta">
                ${item.model ? `<strong>Modelo:</strong> ${escapeHtml(item.model)}<br>` : ''}
                ${escapeHtml(item.organization_name)} · ${escapeHtml(item.plant_name)} · ${escapeHtml(item.sector_name)}<br>
                ${escapeHtml(item.document_title)} · página ${item.page_number}
            </div>
            <div class="component-catalog-actions">
                <button type="button" class="primary-button" data-open-component="${index}">Ver en plano</button>
                <button type="button" class="secondary-button" data-relations-component="${index}">Ver relaciones</button>
                <button type="button" class="secondary-button" data-graph-component="${index}">Seguir circuito</button>
            </div>
        </article>`).join('');
    elements.componentsList.querySelectorAll('[data-open-component]').forEach(btn => btn.addEventListener('click', () => openComponentInSearch(state.componentCatalog[Number(btn.dataset.openComponent)])));
    elements.componentsList.querySelectorAll('[data-relations-component]').forEach(btn => btn.addEventListener('click', () => showComponentRelations(state.componentCatalog[Number(btn.dataset.relationsComponent)])));
    elements.componentsList.querySelectorAll('[data-graph-component]').forEach(btn => btn.addEventListener('click', () => showComponentGraph(state.componentCatalog[Number(btn.dataset.graphComponent)])));
}


async function showComponentGraph(item) {
    if (!item?.id) return;
    document.getElementById('componentGraphDialog')?.remove();
    const dialog = document.createElement('dialog');
    dialog.id = 'componentGraphDialog';
    dialog.className = 'relations-dialog graph-dialog';
    dialog.innerHTML = `<div class="relations-dialog-body"><div class="relations-dialog-header"><div><small>Siguiendo circuito</small><h2>${escapeHtml(item.reference || 'Componente')}</h2></div><button type="button" class="icon-button" data-close-graph>✕</button></div><div class="loading-state">Buscando el origen y el destino del circuito…</div></div>`;
    document.body.appendChild(dialog);
    dialog.querySelector('[data-close-graph]').addEventListener('click', () => dialog.close());
    dialog.addEventListener('close', () => dialog.remove());
    dialog.showModal();
    try {
        const response = await apiRequest(`${API.componentRelations}/${item.id}/graph?depth=2`);
        const nodes = response.nodes || [];
        const edges = response.edges || [];
        const byId = Object.fromEntries(nodes.map(n => [String(n.id), n]));
        const connected = new Set([String(response.root_id)]);
        edges.forEach(e => { connected.add(String(e.source)); connected.add(String(e.target)); });
        dialog.querySelector('.relations-dialog-body').innerHTML = `
            <div class="relations-dialog-header"><div><small>Seguir circuito · ${nodes.length} componentes</small><h2>${escapeHtml(item.reference || '')}</h2></div><button type="button" class="icon-button" data-close-graph>✕</button></div>
            <p class="relations-note">${escapeHtml(response.note || '')}</p>
            <div class="circuit-root"><small>Componente seleccionado</small><strong>${escapeHtml(byId[String(response.root_id)]?.reference || item.reference || '')}</strong></div>
            <div class="circuit-columns">
                <section><h3>Origen / alimentación</h3><div class="graph-edge-list">${edges.filter(e => String(e.target) === String(response.root_id) || e.direction === 'upstream').length ? edges.filter(e => String(e.target) === String(response.root_id) || e.direction === 'upstream').map((e) => { const a=byId[String(e.source)]||{}; const b=byId[String(e.target)]||{}; return `<article class="graph-edge-card"><div class="graph-path"><button type="button" data-graph-node="${a.id}">${escapeHtml(a.reference || '')}</button><span>→</span><button type="button" data-graph-node="${b.id}">${escapeHtml(b.reference || '')}</button></div><p>${escapeHtml(e.relation || '')}</p><small>${escapeHtml(e.reason || '')} · confianza ${e.confidence}%${e.cross_page ? ' · entre páginas' : ''}</small></article>`; }).join('') : '<div class="empty-state compact">Sin origen confirmado.</div>'}</div></section>
                <section><h3>Destino / carga</h3><div class="graph-edge-list">${edges.filter(e => String(e.source) === String(response.root_id) || e.direction === 'downstream').length ? edges.filter(e => String(e.source) === String(response.root_id) || e.direction === 'downstream').map((e) => { const a=byId[String(e.source)]||{}; const b=byId[String(e.target)]||{}; return `<article class="graph-edge-card"><div class="graph-path"><button type="button" data-graph-node="${a.id}">${escapeHtml(a.reference || '')}</button><span>→</span><button type="button" data-graph-node="${b.id}">${escapeHtml(b.reference || '')}</button></div><p>${escapeHtml(e.relation || '')}</p><small>${escapeHtml(e.reason || '')} · confianza ${e.confidence}%${e.cross_page ? ' · entre páginas' : ''}</small></article>`; }).join('') : '<div class="empty-state compact">Sin destino confirmado.</div>'}</div></section>
            </div>`;
        dialog.querySelector('[data-close-graph]').addEventListener('click', () => dialog.close());
        dialog.querySelectorAll('[data-graph-node]').forEach(btn => btn.addEventListener('click', () => {
            const node = byId[String(btn.dataset.graphNode)];
            if (!node) return;
            dialog.close();
            openComponentInSearch({...item, reference: node.reference, model: node.model});
        }));
    } catch (error) {
        dialog.querySelector('.relations-dialog-body').innerHTML = `<div class="relations-dialog-header"><h2>No se pudo seguir el circuito</h2><button type="button" class="icon-button" data-close-graph>✕</button></div><p>${escapeHtml(error.message)}</p>`;
        dialog.querySelector('[data-close-graph]').addEventListener('click', () => dialog.close());
    }
}

async function showComponentRelations(item) {
    if (!item?.id) return;
    const old = document.getElementById('componentRelationsDialog');
    old?.remove();
    const dialog = document.createElement('dialog');
    dialog.id = 'componentRelationsDialog';
    dialog.className = 'relations-dialog';
    dialog.innerHTML = `<div class="relations-dialog-body"><div class="relations-dialog-header"><div><small>Analizando relaciones</small><h2>${escapeHtml(item.reference || 'Componente')}</h2></div><button type="button" class="icon-button" data-close-relations>✕</button></div><div class="loading-state">Buscando componentes relacionados en la misma página…</div></div>`;
    document.body.appendChild(dialog);
    dialog.querySelector('[data-close-relations]').addEventListener('click', () => dialog.close());
    dialog.addEventListener('close', () => dialog.remove());
    dialog.showModal();
    try {
        const response = await apiRequest(`${API.componentRelations}/${item.id}`);
        const rows = response.relations || [];
        dialog.querySelector('.relations-dialog-body').innerHTML = `
            <div class="relations-dialog-header"><div><small>${escapeHtml(response.source?.component_type || 'componente')} · página ${response.source?.page_number || ''}</small><h2>${escapeHtml(response.source?.reference || item.reference || '')}</h2></div><button type="button" class="icon-button" data-close-relations>✕</button></div>
            <p class="relations-note">${escapeHtml(response.note || '')}</p>
            <div class="relations-list">${rows.length ? rows.map((r, i) => `<article class="relation-card"><div><strong>${escapeHtml(r.reference || 'Sin referencia')}</strong><span>${escapeHtml(r.component_type || 'otro')}</span></div><p>${escapeHtml(r.relation)} · ${escapeHtml(r.reason)}</p><small>Confianza preliminar: ${r.confidence}%</small><button type="button" class="secondary-button" data-open-related="${i}">Buscar en planos</button></article>`).join('') : '<div class="empty-state"><strong>No se detectaron relaciones suficientes.</strong><p>En esta etapa se analizan referencias cruzadas y proximidad dentro de la misma página.</p></div>'}</div>`;
        dialog.querySelector('[data-close-relations]').addEventListener('click', () => dialog.close());
        dialog.querySelectorAll('[data-open-related]').forEach(btn => btn.addEventListener('click', () => {
            const rel = rows[Number(btn.dataset.openRelated)];
            dialog.close();
            openComponentInSearch({...item, reference: rel.reference, model: rel.model});
        }));
    } catch (error) {
        dialog.querySelector('.relations-dialog-body').innerHTML = `<div class="relations-dialog-header"><h2>No se pudieron cargar las relaciones</h2><button type="button" class="icon-button" data-close-relations>✕</button></div><p>${escapeHtml(error.message)}</p>`;
        dialog.querySelector('[data-close-relations]').addEventListener('click', () => dialog.close());
    }
}

async function loadComponentCatalog() {
    if (!elements.componentsList) return;
    elements.componentsLoading?.classList.remove('hidden');
    elements.componentsMessage?.classList.add('hidden');
    const params = new URLSearchParams();
    if (elements.componentOrganization?.value) params.set('organization_id', elements.componentOrganization.value);
    if (elements.componentPlant?.value) params.set('plant_id', elements.componentPlant.value);
    if (elements.componentSector?.value) params.set('sector_id', elements.componentSector.value);
    if (elements.componentType?.value) params.set('component_type', elements.componentType.value);
    if (elements.componentQuery?.value.trim()) params.set('q', elements.componentQuery.value.trim());
    try {
        const response = await apiRequest(`${API.componentCatalog}?${params.toString()}`);
        renderComponentSummary(response.counts);
        renderComponentCatalog(response.items);
    } catch (error) {
        elements.componentsList.innerHTML = '';
        showMessage(elements.componentsMessage, error.message, 'error');
    } finally {
        elements.componentsLoading?.classList.add('hidden');
    }
}

function initializeComponentCatalogEvents() {
    populateComponentTypeOptions();
    syncComponentOrganizations();
    elements.componentOrganization?.addEventListener('change', loadComponentPlants);
    elements.componentPlant?.addEventListener('change', loadComponentSectors);
    elements.componentSector?.addEventListener('change', loadComponentCatalog);
    elements.componentType?.addEventListener('change', loadComponentCatalog);
    elements.refreshComponentsButton?.addEventListener('click', loadComponentCatalog);
    let timer;
    elements.componentQuery?.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(loadComponentCatalog, 350); });
}


/* =========================================================
   VISOR DE PLANOS Y ZOOM
   ========================================================= */

function getViewerResultByIndex(index) {
    return state.search.results[index] ?? null;
}


function hideReferenceHighlight() {
    if (!elements.referenceHighlight) return;

    elements.referenceHighlight.classList.add("hidden");
    elements.referenceHighlight.style.left = "0px";
    elements.referenceHighlight.style.top = "0px";
    elements.referenceHighlight.style.width = "0px";
    elements.referenceHighlight.style.height = "0px";
}


function positionReferenceHighlight(coordinates) {
    if (
        !coordinates ||
        !elements.referenceHighlight ||
        !elements.viewerImage?.naturalWidth ||
        !elements.viewerImage?.naturalHeight
    ) {
        hideReferenceHighlight();
        return;
    }

    const scale = state.viewer.scale;

    elements.referenceHighlight.style.left =
        `${coordinates.x * scale}px`;
    elements.referenceHighlight.style.top =
        `${coordinates.y * scale}px`;
    elements.referenceHighlight.style.width =
        `${Math.max(coordinates.width * scale, 18)}px`;
    elements.referenceHighlight.style.height =
        `${Math.max(coordinates.height * scale, 18)}px`;

    elements.referenceHighlight.classList.remove("hidden");
}


function resetViewerZoom() {
    state.viewer.scale = 1;

    if (elements.viewerImage) {
        elements.viewerImage.style.transform = "scale(1)";
        elements.viewerImage.style.transformOrigin = "top left";
    }

    const wrapper = elements.viewerImage?.parentElement;

    if (wrapper) {
        wrapper.style.width = "";
        wrapper.style.height = "";
    }
}


function applyViewerZoom() {
    const image = elements.viewerImage;
    if (!image?.naturalWidth || !image?.naturalHeight) return;

    image.style.transformOrigin = "top left";
    image.style.transform = `scale(${state.viewer.scale})`;

    const wrapper = image.parentElement;

    if (wrapper) {
        wrapper.style.width =
            `${image.naturalWidth * state.viewer.scale}px`;
        wrapper.style.height =
            `${image.naturalHeight * state.viewer.scale}px`;
    }

    positionReferenceHighlight(state.viewer.coordinates);
}


function scrollHighlightIntoView() {
    if (
        !elements.referenceHighlight ||
        elements.referenceHighlight.classList.contains("hidden")
    ) {
        return;
    }

    setTimeout(() => {
        elements.referenceHighlight.scrollIntoView({
            behavior: "smooth",
            block: "center",
            inline: "center",
        });
    }, 120);
}


function updateViewerNavigation() {
    const total = state.search.results.length;
    const index = state.viewer.resultIndex;

    if (elements.viewerPosition) {
        elements.viewerPosition.textContent = total > 0 && index >= 0
            ? `${index + 1} de ${total}`
            : "0 de 0";
    }

    if (elements.viewerPreviousButton) {
        elements.viewerPreviousButton.disabled = index <= 0;
    }

    if (elements.viewerNextButton) {
        elements.viewerNextButton.disabled = index < 0 || index >= total - 1;
    }
}

function renderViewerContext(result) {
    if (!elements.viewerContext) return;
    const context = result?.context ?? {};
    const items = [];

    if (context.detected_type) {
        items.push(`<span class="context-chip">${escapeHtml(context.detected_type)}</span>`);
    }
    if (context.model) {
        items.push(`<span class="context-chip">Modelo ${escapeHtml(context.model)}</span>`);
    }
    if (context.description) {
        items.push(`<div class="context-description">${escapeHtml(context.description)}</div>`);
    } else if (context.row_text) {
        items.push(`<div class="context-description">${escapeHtml(context.row_text)}</div>`);
    }

    elements.viewerContext.innerHTML = items.join("");
}

function navigateViewer(step) {
    const nextIndex = state.viewer.resultIndex + step;
    if (nextIndex < 0 || nextIndex >= state.search.results.length) return;
    openViewer(state.search.results[nextIndex], nextIndex);
}

function openViewer(result, resultIndex = null) {
    if (!result || !elements.viewerModal) return;

    const imageUrl =
        normalizeImageUrl(getResultImageUrl(result)) ??
        buildFallbackPageImageUrl(result);

    if (!imageUrl) {
        showMessage(
            elements.searchMessage,
            "No se encontró una imagen disponible para esta página.",
            "error"
        );
        return;
    }

    resetViewerZoom();

    state.viewer.result = result;
    state.viewer.resultIndex = resultIndex !== null
        ? resultIndex
        : state.search.results.indexOf(result);
    state.viewer.coordinates = getResultCoordinates(result);

    const documentTitle = getResultDocumentTitle(result);
    const pageNumber = getResultPageNumber(result);
    const reference = getResultReference(result);

    if (elements.viewerTitle) {
        elements.viewerTitle.textContent = documentTitle;
    }

    if (elements.viewerSubtitle) {
        const subtitle = [];

        if (pageNumber !== null) subtitle.push(`Página ${pageNumber}`);
        if (reference) subtitle.push(`Referencia ${reference}`);

        elements.viewerSubtitle.textContent = subtitle.join(" · ");
    }

    renderViewerContext(result);
    updateViewerNavigation();
    hideReferenceHighlight();

    elements.viewerModal.classList.remove("hidden");
    elements.viewerModal.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";

    if (elements.viewerCanvas) {
        elements.viewerCanvas.scrollTop = 0;
        elements.viewerCanvas.scrollLeft = 0;
    }

    elements.viewerImage.style.opacity = "0.45";

    elements.viewerImage.onload = () => {
        elements.viewerImage.style.opacity = "1";
        applyViewerZoom();
        scrollHighlightIntoView();
    };

    elements.viewerImage.onerror = () => {
        closeViewer();

        showMessage(
            elements.searchMessage,
            "No se pudo cargar la imagen de la página.",
            "error"
        );
    };

    elements.viewerImage.src = imageUrl;
    elements.viewerImage.alt =
        `${documentTitle} - Página ${pageNumber ?? ""}`;
}


function closeViewer() {
    if (!elements.viewerModal) return;

    elements.viewerModal.classList.add("hidden");
    elements.viewerModal.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";

    if (elements.viewerImage) {
        elements.viewerImage.onload = null;
        elements.viewerImage.onerror = null;
        elements.viewerImage.src = "";
    }

    hideReferenceHighlight();

    state.viewer.result = null;
    state.viewer.resultIndex = -1;
    state.viewer.coordinates = null;
    resetViewerZoom();
}


function initializeViewerButtons() {
    document
        .querySelectorAll(".open-viewer-button")
        .forEach((button) => {
            button.addEventListener("click", () => {
                const result = getViewerResultByIndex(
                    Number(button.dataset.resultIndex)
                );

                openViewer(result, Number(button.dataset.resultIndex));
            });
        });
}


function initializeViewerEvents() {
    elements.closeViewerButton?.addEventListener("click", closeViewer);
    elements.modalOverlay?.addEventListener("click", closeViewer);
    elements.viewerPreviousButton?.addEventListener("click", () => navigateViewer(-1));
    elements.viewerNextButton?.addEventListener("click", () => navigateViewer(1));

    document.addEventListener("keydown", (event) => {
        const viewerOpen = !elements.viewerModal?.classList.contains("hidden");
        if (event.key === "Escape" && viewerOpen) {
            closeViewer();
        } else if (event.key === "ArrowRight" && viewerOpen) {
            navigateViewer(1);
        } else if (event.key === "ArrowLeft" && viewerOpen) {
            navigateViewer(-1);
        }
    });

    elements.viewerCanvas?.addEventListener(
        "wheel",
        (event) => {
            if (!event.ctrlKey) return;

            event.preventDefault();

            const step = 0.15;

            state.viewer.scale =
                event.deltaY < 0
                    ? Math.min(3, state.viewer.scale + step)
                    : Math.max(0.5, state.viewer.scale - step);

            applyViewerZoom();
        },
        { passive: false }
    );
}


/* =========================================================
   CARGA DE DOCUMENTOS
   ========================================================= */

function setUploadLoading(isLoading) {
    if (elements.uploadButton) {
        elements.uploadButton.disabled = isLoading;
        elements.uploadButton.textContent = isLoading
            ? "Cargando..."
            : "Cargar documento";
    }

    elements.uploadProgress?.classList.toggle("hidden", !isLoading);

    if (!isLoading && elements.uploadProgressBar) {
        elements.uploadProgressBar.style.width = "0%";
    }
}


function updateUploadProgress(percent, text) {
    if (elements.uploadProgressBar) {
        elements.uploadProgressBar.style.width = `${percent}%`;
    }

    if (elements.uploadProgressText) {
        elements.uploadProgressText.textContent = text;
    }
}


function getSelectedOrganizationName() {
    const option = elements.uploadOrganization?.selectedOptions?.[0];
    if (!option || !option.value) return null;
    return option.textContent?.trim() || null;
}


async function createPlantIfNeeded(organizationId, plantName) {
    const trimmedName = plantName.trim();

    if (!trimmedName) return null;

    if (!organizationId) {
        throw new Error("Seleccioná una empresa antes de crear la planta.");
    }

    const existingPlants = await fetchPlantsByOrganization(organizationId);
    const existing = existingPlants.find(
        (plant) =>
            getObjectName(plant).trim().toLowerCase() ===
            trimmedName.toLowerCase()
    );

    if (existing) {
        return getObjectId(existing);
    }

    const response = await apiRequest(API.plants, {
        method: "POST",
        body: {
            name: trimmedName,
            organization_id: normalizeId(organizationId),
            organization_name: getSelectedOrganizationName(),
        },
    });

    return getObjectId(response);
}


async function createSectorIfNeeded(plantId, sectorName) {
    const trimmedName = sectorName.trim();

    if (!trimmedName) return null;

    const existingSectors = await fetchSectorsByPlant(plantId);

    const existing = existingSectors.find(
        (sector) =>
            getObjectName(sector).trim().toLowerCase() ===
            trimmedName.toLowerCase()
    );

    if (existing) {
        return getObjectId(existing);
    }

    const response = await apiRequest(API.sectors, {
        method: "POST",
        body: {
            name: trimmedName,
            plant_id: normalizeId(plantId),
        },
    });

    return getObjectId(response);
}


function validatePdfFile(file) {
    if (!file) {
        throw new Error("Seleccioná un archivo PDF.");
    }

    const isPdf =
        file.type === "application/pdf" ||
        file.name.toLowerCase().endsWith(".pdf");

    if (!isPdf) {
        throw new Error("El archivo seleccionado debe ser PDF.");
    }

    return true;
}


async function handleUploadSubmit(event) {
    event.preventDefault();
    hideMessage(elements.uploadMessage);

    const organizationId = elements.uploadOrganization?.value;
    let plantId = elements.uploadPlant?.value;
    const newPlantName = elements.newPlantName?.value.trim() ?? "";
    let sectorId = elements.uploadSector?.value;
    const newSectorName = elements.newSectorName?.value.trim() ?? "";
    const file = elements.pdfFile?.files?.[0];

    try {
        if (!organizationId) {
            throw new Error("Seleccioná una empresa.");
        }

        if (!plantId && !newPlantName) {
            throw new Error("Seleccioná una planta existente o escribí una nueva.");
        }

        if (!sectorId && !newSectorName) {
            throw new Error("Seleccioná un sector o escribí uno nuevo.");
        }

        validatePdfFile(file);

        setUploadLoading(true);
        updateUploadProgress(10, "Preparando documento...");

        if (!plantId && newPlantName) {
            updateUploadProgress(20, "Creando planta...");
            plantId = await createPlantIfNeeded(organizationId, newPlantName);
        }

        if (!plantId) {
            throw new Error("No se pudo obtener la planta.");
        }

        if (!sectorId && newSectorName) {
            updateUploadProgress(35, "Creando sector...");
            sectorId = await createSectorIfNeeded(plantId, newSectorName);
        }

        if (!sectorId) {
            throw new Error("No se pudo obtener el sector.");
        }

        const formData = new FormData();

        formData.append("file", file);
        formData.append(
            "title",
            elements.documentTitle?.value.trim() || file.name
        );
        formData.append(
            "description",
            elements.documentDescription?.value.trim() || ""
        );
        formData.append(
            "document_type",
            elements.documentType?.value || "plano_electrico"
        );
        formData.append("sector_id", sectorId);

        const equipmentId = elements.equipmentId?.value;

        if (equipmentId) {
            formData.append("equipment_id", equipmentId);
        }

        updateUploadProgress(55, "Subiendo archivo...");

        const response = await apiRequest(`${API.documents}/upload`, {
            method: "POST",
            body: formData,
        });

        updateUploadProgress(100, "Documento cargado.");

        showMessage(
            elements.uploadMessage,
            response?.message ||
                "Documento cargado correctamente. El procesamiento puede demorar unos minutos.",
            "success"
        );

        elements.uploadForm?.reset();

        if (elements.selectedFileName) {
            elements.selectedFileName.textContent =
                "Ningún archivo seleccionado";
        }

        state.upload.sectorId = null;

        resetSelect(elements.uploadPlant, "Seleccionar planta");
        resetSelect(elements.uploadSector, "Seleccionar sector");

        await loadOrganizations();
    } catch (error) {
        console.error("Error al cargar documento:", error);

        showMessage(
            elements.uploadMessage,
            `No se pudo cargar el documento: ${error.message}`,
            "error"
        );
    } finally {
        setTimeout(() => setUploadLoading(false), 500);
    }
}


function initializeFileEvents() {
    elements.pdfFile?.addEventListener("change", () => {
        const file = elements.pdfFile.files?.[0];

        if (elements.selectedFileName) {
            elements.selectedFileName.textContent =
                file?.name || "Ningún archivo seleccionado";
        }
    });

    ["dragenter", "dragover"].forEach((eventName) => {
        elements.fileDropArea?.addEventListener(eventName, (event) => {
            event.preventDefault();
            elements.fileDropArea.classList.add("dragging");
        });
    });

    ["dragleave", "drop"].forEach((eventName) => {
        elements.fileDropArea?.addEventListener(eventName, (event) => {
            event.preventDefault();
            elements.fileDropArea.classList.remove("dragging");
        });
    });

    elements.fileDropArea?.addEventListener("drop", (event) => {
        const files = event.dataTransfer?.files;

        if (!files?.length || !elements.pdfFile) return;

        const dataTransfer = new DataTransfer();
        dataTransfer.items.add(files[0]);
        elements.pdfFile.files = dataTransfer.files;

        if (elements.selectedFileName) {
            elements.selectedFileName.textContent = files[0].name;
        }
    });

    elements.uploadForm?.addEventListener("submit", handleUploadSubmit);
}


/* =========================================================
   LISTADO DE DOCUMENTOS
   ========================================================= */

function getDocumentStatus(documentItem) {
    return (
        documentItem?.processing_status ??
        documentItem?.status ??
        "uploaded"
    );
}


function translateStatus(status) {
    const normalized = String(status).toLowerCase();

    const labels = {
        uploaded: "Cargado",
        pending: "Pendiente",
        processing: "Procesando",
        completed: "Procesado",
        processed: "Procesado",
        error: "Error",
        failed: "Error",
    };

    return labels[normalized] || status;
}


function statusClass(status) {
    const normalized = String(status).toLowerCase();

    if (["completed", "processed"].includes(normalized)) return "completed";
    if (["processing", "pending"].includes(normalized)) return "processing";
    if (["error", "failed"].includes(normalized)) return "error";

    return "uploaded";
}


function renderDocuments(documents) {
    if (!elements.documentsList) return;

    if (documents.length === 0) {
        elements.documentsList.innerHTML = "";

        showMessage(
            elements.documentsMessage,
            "Todavía no hay documentos cargados.",
            "info"
        );
        return;
    }

    hideMessage(elements.documentsMessage);

    elements.documentsList.innerHTML = documents
        .map((documentItem) => {
            const status = getDocumentStatus(documentItem);
            const title =
                documentItem?.title ??
                documentItem?.filename ??
                "Documento sin título";

            const sectorName =
                documentItem?.sector_name ??
                documentItem?.sector?.name ??
                null;

            const pages =
                documentItem?.page_count ??
                documentItem?.pages_count ??
                null;

            return `
                <article class="document-card">
                    <div>
                        <h3>${escapeHtml(title)}</h3>

                        <div class="document-meta">
                            ${
                                sectorName
                                    ? `<span>Sector: ${escapeHtml(sectorName)}</span>`
                                    : ""
                            }

                            ${
                                documentItem?.document_type
                                    ? `<span>${escapeHtml(documentItem.document_type)}</span>`
                                    : ""
                            }

                            ${
                                pages !== null
                                    ? `<span>${escapeHtml(pages)} páginas</span>`
                                    : ""
                            }

                            ${
                                documentItem?.created_at
                                    ? `<span>${escapeHtml(
                                        new Date(documentItem.created_at)
                                            .toLocaleString("es-AR")
                                    )}</span>`
                                    : ""
                            }
                        </div>
                    </div>

                    <div class="document-card-actions">
                        <span class="status-badge ${statusClass(status)}">
                            ${escapeHtml(translateStatus(status))}
                        </span>
                        <a
                            class="secondary-button document-open-button"
                            href="${API.documents}/${escapeHtml(documentItem.id)}/file"
                            target="_blank"
                            rel="noopener"
                        >Ver PDF</a>
                        ${statusClass(status) === "completed" ? "" : `
                        <button
                            class="secondary-button document-process-button"
                            type="button"
                            data-document-id="${escapeHtml(documentItem.id)}"
                        >Procesar</button>`}
                        <button
                            class="danger-button document-delete-button"
                            type="button"
                            data-document-id="${escapeHtml(documentItem.id)}"
                            data-document-title="${escapeHtml(title)}"
                        >Eliminar</button>
                    </div>
                </article>
            `;
        })
        .join("");
}


async function loadDocuments() {
    hideMessage(elements.documentsMessage);
    elements.documentsLoading?.classList.remove("hidden");

    try {
        const response = await apiRequest(API.documents);
        state.documents = toArray(response);
        renderDocuments(state.documents);
    } catch (error) {
        console.error("Error cargando documentos:", error);

        showMessage(
            elements.documentsMessage,
            `No se pudieron cargar los documentos: ${error.message}`,
            "error"
        );
    } finally {
        elements.documentsLoading?.classList.add("hidden");
    }
}


async function handleDocumentsListClick(event) {
    const processButton = event.target.closest(".document-process-button");
    if (processButton) {
        processButton.disabled = true;
        processButton.textContent = "Procesando...";
        try {
            const documentId = processButton.dataset.documentId;
            const response = await apiRequest(`${API.documents}/${documentId}/process`, { method: "POST" });
            showMessage(elements.documentsMessage, response?.message || "Documento procesado correctamente.", "success");
            await loadDocuments();
        } catch (error) {
            showMessage(elements.documentsMessage, `No se pudo procesar: ${error.message}`, "error");
            processButton.disabled = false;
            processButton.textContent = "Procesar";
        }
        return;
    }

    const button = event.target.closest(".document-delete-button");
    if (!button) return;

    const documentId = button.dataset.documentId;
    const documentTitle = button.dataset.documentTitle || "este documento";

    if (!confirm(`¿Eliminar “${documentTitle}”? Esta acción no se puede deshacer.`)) {
        return;
    }

    button.disabled = true;
    button.textContent = "Eliminando...";

    try {
        await apiRequest(`${API.documents}/${documentId}`, { method: "DELETE" });
        showMessage(elements.documentsMessage, "Documento eliminado correctamente.", "success");
        await loadDocuments();
    } catch (error) {
        showMessage(elements.documentsMessage, `No se pudo eliminar: ${error.message}`, "error");
        button.disabled = false;
        button.textContent = "Eliminar";
    }
}

async function cleanupDuplicateDocuments() {
    if (!confirm("¿Limpiar los PDF duplicados? Se conservará una sola copia procesada de cada archivo.")) {
        return;
    }

    const button = elements.cleanupDocumentsButton;
    if (button) {
        button.disabled = true;
        button.textContent = "Limpiando...";
    }

    try {
        const result = await apiRequest(`${API.documents}/cleanup-duplicates`, { method: "POST" });
        showMessage(elements.documentsMessage, result?.message || "Limpieza terminada.", "success");
        await loadDocuments();
    } catch (error) {
        showMessage(elements.documentsMessage, `No se pudo limpiar: ${error.message}`, "error");
    } finally {
        if (button) {
            button.disabled = false;
            button.textContent = "Limpiar duplicados";
        }
    }
}

function initializeDocumentEvents() {
    elements.refreshDocumentsButton?.addEventListener("click", loadDocuments);
    elements.cleanupDocumentsButton?.addEventListener("click", cleanupDuplicateDocuments);
    elements.documentsList?.addEventListener("click", handleDocumentsListClick);
}


/* =========================================================
   INICIALIZACIÓN
   ========================================================= */

async function initializeApplication() {
    initializeNavigation();
    initializeHierarchyEvents();
    initializeSearchEvents();
    initializeComponentCatalogEvents();
    initializeViewerEvents();
    initializeFileEvents();
    initializeDocumentEvents();
    initializeOrganizationEvents();

    await checkApiStatus();
    await loadOrganizations();
}


document.addEventListener("DOMContentLoaded", initializeApplication);
