from __future__ import annotations

import asyncio
import hashlib
import re
import time
import xml.etree.ElementTree as ET
from io import BytesIO
from zipfile import ZipFile
from datetime import UTC, datetime, timedelta
from html import unescape
from typing import Any
from urllib.parse import quote_plus
from urllib.parse import urljoin

import httpx

from app.intel_models import BusinessLead
from app.intel_models import EthicsRule
from app.intel_models import IntelSource
from app.intel_models import NewsSignal
from app.intel_models import OrganizationProfile
from app.intel_models import PermitSignal
from app.intel_models import PublicContact
from app.intel_models import RegionBrief
from app.intel_models import RegionId
from app.intel_models import RegionProfile
from app.intel_models import RegionalIntelSnapshot
from app.intel_models import SourceHealth
from app.config import get_settings
from app.services.regional_history_store import RegionalIntelHistoryStore
from app.utils import clean_text, utc_now_iso


# Transient errors that warrant a retry. httpx.TimeoutException is a subclass of
# OSError-adjacent NetworkError; we list the bare-Python types explicitly so the
# helper still works under tests that raise asyncio.TimeoutError directly.
_TRANSIENT_RETRY_EXCEPTIONS: tuple[type[BaseException], ...] = (
    asyncio.TimeoutError,
    TimeoutError,
    ConnectionError,
    OSError,
    httpx.TimeoutException,
    httpx.NetworkError,
    httpx.RemoteProtocolError,
)


GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
AUSTIN_PERMITS_URL = "https://data.austintexas.gov/resource/3syk-w9eu.json"
HAYS_PERMITS_URL = "https://www.hayscountypermits.com/api/v1/permits/datatables/list/public"
WILCO_PERMITS_URL = "https://www.wilcopermits.com/api/v1/permits/datatables/list/public"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
AUSTIN_CONTACTS_URL = "https://www.austintexas.gov/economic-development/divisions/small-business-division"
AUSTIN_RALLY_URL = "https://www.austintexas.gov/economic-development/news/council-approves-global-genomics-company-expansion-austin-81m-investment"
HOUSTON_ECODEV_CONTACT_URL = "https://www.houstontx.gov/ecodev/contactus.html"
HOUSTON_INNOVATION_URL = "https://innovation.houstontx.gov/"
HOUSTON_DEV_REPORTS_URL = "https://www.houstontx.gov/planning/DevelopRegs/dev_reports.html"
GUNNISON_COMMUNITY_DEV_URL = "https://www.gunnisoncounty.org/144/Community-and-Economic-Development"
GUNNISON_PERMIT_DATABASE_URL = "https://www.gunnisoncounty.org/436/Permit-Database"
CRESTED_BUTTE_PERMITTING_URL = "https://townofcrestedbutte.colorado.gov/planning-permitting/licensing-permitting"

ADDRESS_RE = re.compile(
    r"\b\d{1,6}\s+[a-z0-9#.\- ]+?\s(?:st|street|ave|avenue|blvd|boulevard|rd|road|dr|drive|ln|lane|way|pkwy|parkway|hwy|highway|trl|trail|rr)\b",
    re.IGNORECASE,
)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?:\(\d{3}\)\s*\d{3}-\d{4}|\d{3}[-.\s]\d{3}[-.\s]\d{4})")


ETHICS_RULES = [
    EthicsRule(
        key="public_sources_only",
        title="Public Sources Only",
        description="Only collect from public open-data APIs, public RSS/news indexes, public HTML pages, and open-licensed map data.",
    ),
    EthicsRule(
        key="no_login_or_paywall_bypass",
        title="No Login or Paywall Bypass",
        description="Do not authenticate, bypass paywalls, solve gates, or scrape behind credentials. Subscription sources stay manual-reference only.",
    ),
    EthicsRule(
        key="professional_contact_scope",
        title="Professional Contact Scope",
        description="Only collect organization-level and clearly public professional contact points such as websites, public phones, and public business emails.",
    ),
    EthicsRule(
        key="provenance_required",
        title="Provenance Required",
        description="Every item must keep its source name and source URL so a human can verify it before acting.",
    ),
]


REGIONS: list[RegionProfile] = [
    RegionProfile(
        id="austin_tx",
        name="Austin, Texas",
        summary="Central Texas growth intelligence across Austin and the nearby development corridor.",
        bbox=[30.05, -98.10, 30.65, -97.40],
        focus_keywords=["Austin", "Round Rock", "Pflugerville", "Cedar Park", "South Austin", "Domain"],
        notes=[
            "Permit coverage is live for Austin Open Data plus public Hays and Williamson permit portals.",
            "Subscription local business outlets remain manual-reference only.",
        ],
        source_keys=[
            "community_impact_austin",
            "austin_monitor",
            "austin_open_data_permits",
            "hays_public_permits",
            "williamson_public_permits",
            "osm_business_contacts",
            "austin_economic_development_contacts",
        ],
    ),
    RegionProfile(
        id="houston_tx",
        name="Houston, Texas",
        summary="Houston metro business and development intelligence with public news and open business discovery.",
        bbox=[29.50, -95.90, 30.20, -95.00],
        focus_keywords=["Houston", "The Heights", "Sugar Land", "Katy", "The Woodlands", "Midtown Houston"],
        notes=[
            "Houston official development activity is live through public planning agenda spreadsheets.",
            "The general Houston permitting portal stays in the source catalog, but live extraction is limited to anonymous public planning artifacts for now.",
            "Business discovery is live through OpenStreetMap public data.",
        ],
        source_keys=[
            "community_impact_houston",
            "axios_houston",
            "houston_public_media",
            "houston_plat_activity_reports",
            "houston_permitting_center_manual",
            "osm_business_contacts",
            "houston_economic_development_contacts",
            "houston_innovation_contacts",
        ],
    ),
    RegionProfile(
        id="gunnison_valley_co",
        name="Gunnison / Crested Butte Valley, Colorado",
        summary="Mountain valley business, permitting, and local development intelligence for Gunnison and Crested Butte.",
        bbox=[38.55, -107.15, 39.05, -106.75],
        focus_keywords=["Gunnison", "Crested Butte", "Mt. Crested Butte", "Gunnison Valley"],
        notes=[
            "Official Gunnison County and Town of Crested Butte permit/business pages are in scope.",
            "Live permit extraction for Gunnison/Crested Butte still needs a public-access adapter.",
        ],
        source_keys=[
            "crested_butte_news",
            "kbut",
            "gunnison_county_permit_database_manual",
            "crested_butte_licensing_permitting_manual",
            "osm_business_contacts",
            "gunnison_community_development_contacts",
            "crested_butte_permitting_contacts",
        ],
    ),
]


SOURCES: list[IntelSource] = [
    IntelSource(
        source_key="community_impact_austin",
        region_ids=["austin_tx"],
        category="news",
        name="Community Impact Austin",
        collection_mode="public_rss_index",
        access="public",
        live_pull=True,
        url="https://communityimpact.com",
        notes="Preferred Austin source for business, dining, traffic, vacancy, and opening signals.",
    ),
    IntelSource(
        source_key="austin_monitor",
        region_ids=["austin_tx"],
        category="news",
        name="Austin Monitor",
        collection_mode="public_rss_index",
        access="public",
        live_pull=True,
        url="https://www.austinmonitor.com",
        notes="Public local outlet for policy, development, and city business context.",
    ),
    IntelSource(
        source_key="community_impact_houston",
        region_ids=["houston_tx"],
        category="news",
        name="Community Impact Houston",
        collection_mode="public_rss_index",
        access="public",
        live_pull=True,
        url="https://communityimpact.com",
        notes="Preferred Houston-area source for openings, closures, development, and local business changes.",
    ),
    IntelSource(
        source_key="axios_houston",
        region_ids=["houston_tx"],
        category="news",
        name="Axios Houston",
        collection_mode="public_rss_index",
        access="public",
        live_pull=True,
        url="https://www.axios.com/local/houston",
        notes="Public local business and city-change coverage.",
    ),
    IntelSource(
        source_key="houston_public_media",
        region_ids=["houston_tx"],
        category="news",
        name="Houston Public Media",
        collection_mode="public_rss_index",
        access="public",
        live_pull=True,
        url="https://www.houstonpublicmedia.org",
        notes="Public local newsroom with civic and development coverage.",
    ),
    IntelSource(
        source_key="crested_butte_news",
        region_ids=["gunnison_valley_co"],
        category="news",
        name="Crested Butte News",
        collection_mode="public_rss_index",
        access="public",
        live_pull=True,
        url="https://crestedbuttenews.com",
        notes="Local valley publication for development, business, and community signals.",
    ),
    IntelSource(
        source_key="kbut",
        region_ids=["gunnison_valley_co"],
        category="news",
        name="KBUT",
        collection_mode="public_rss_index",
        access="public",
        live_pull=True,
        url="https://kbut.org",
        notes="Public local radio/news source for Gunnison Valley.",
    ),
    IntelSource(
        source_key="austin_open_data_permits",
        region_ids=["austin_tx"],
        category="permit",
        name="City of Austin Open Data Permits",
        collection_mode="public_api",
        access="public",
        live_pull=True,
        url="https://data.austintexas.gov/Building-and-Development/Issued-Construction-Permits/3syk-w9eu",
        notes="Official open-data API for Austin permit activity.",
    ),
    IntelSource(
        source_key="hays_public_permits",
        region_ids=["austin_tx"],
        category="permit",
        name="Hays County Public Permits",
        collection_mode="public_api_endpoint",
        access="public",
        live_pull=True,
        url="https://www.hayscountypermits.com/public/permits/list",
        notes="Public DataTables endpoint discovered from page source.",
    ),
    IntelSource(
        source_key="williamson_public_permits",
        region_ids=["austin_tx"],
        category="permit",
        name="Williamson County Public Permits",
        collection_mode="public_api_endpoint",
        access="public",
        live_pull=True,
        url="https://www.wilcopermits.com/public/permits/list",
        notes="Public DataTables endpoint discovered from page source.",
    ),
    IntelSource(
        source_key="houston_plat_activity_reports",
        region_ids=["houston_tx"],
        category="permit",
        name="Houston Planning Plat Activity Reports",
        collection_mode="public_xlsx_reports",
        access="public",
        live_pull=True,
        url=HOUSTON_DEV_REPORTS_URL,
        notes="Official Houston Planning & Development agenda spreadsheets with current subdivision and development activity.",
    ),
    IntelSource(
        source_key="houston_permitting_center_manual",
        region_ids=["houston_tx"],
        category="permit",
        name="Houston Permitting Center",
        collection_mode="public_portal_manual_adapter_pending",
        access="public",
        live_pull=False,
        url="https://www.houstontx.gov/ara/platting/permitting.html",
        notes="Official Houston permitting source; live public adapter still pending.",
    ),
    IntelSource(
        source_key="gunnison_county_permit_database_manual",
        region_ids=["gunnison_valley_co"],
        category="permit",
        name="Gunnison County Permit Database",
        collection_mode="public_portal_manual_adapter_pending",
        access="public",
        live_pull=False,
        url="https://www.gunnisoncounty.org/436/Permit-Database",
        notes="Official Gunnison permit database; public access path is confirmed but adapter is still pending.",
    ),
    IntelSource(
        source_key="crested_butte_licensing_permitting_manual",
        region_ids=["gunnison_valley_co"],
        category="permit",
        name="Town of Crested Butte Licensing & Permitting",
        collection_mode="public_official_page_manual_reference",
        access="public",
        live_pull=False,
        url="https://townofcrestedbutte.colorado.gov/planning-permitting/licensing-permitting",
        notes="Official page with licensing, permitting, and business registration links.",
    ),
    IntelSource(
        source_key="austin_economic_development_contacts",
        region_ids=["austin_tx"],
        category="contacts",
        name="Austin Economic Development Contacts",
        collection_mode="public_official_page",
        access="public",
        live_pull=True,
        url=AUSTIN_CONTACTS_URL,
        notes="Public Austin Economic Development / Small Business Division page plus official Austin economic development article context.",
    ),
    IntelSource(
        source_key="houston_economic_development_contacts",
        region_ids=["houston_tx"],
        category="contacts",
        name="Houston Economic Development Contacts",
        collection_mode="public_official_page",
        access="public",
        live_pull=True,
        url=HOUSTON_ECODEV_CONTACT_URL,
        notes="Public City of Houston economic development office contact page.",
    ),
    IntelSource(
        source_key="houston_innovation_contacts",
        region_ids=["houston_tx"],
        category="contacts",
        name="Houston Innovation Contacts",
        collection_mode="public_official_page",
        access="public",
        live_pull=True,
        url=HOUSTON_INNOVATION_URL,
        notes="Public Mayor's Office of Innovation and Performance page with public-facing staff/office contact context.",
    ),
    IntelSource(
        source_key="gunnison_community_development_contacts",
        region_ids=["gunnison_valley_co"],
        category="contacts",
        name="Gunnison Community & Economic Development Contacts",
        collection_mode="public_official_page",
        access="public",
        live_pull=True,
        url=GUNNISON_COMMUNITY_DEV_URL,
        notes="Public Gunnison County Community & Economic Development office page and permit database contacts.",
    ),
    IntelSource(
        source_key="crested_butte_permitting_contacts",
        region_ids=["gunnison_valley_co"],
        category="contacts",
        name="Crested Butte Permitting Contacts",
        collection_mode="public_official_page",
        access="public",
        live_pull=True,
        url=CRESTED_BUTTE_PERMITTING_URL,
        notes="Public Town of Crested Butte permitting and licensing page with professional contact channels.",
    ),
    IntelSource(
        source_key="osm_business_contacts",
        region_ids=["austin_tx", "houston_tx", "gunnison_valley_co"],
        category="business",
        name="OpenStreetMap / Overpass",
        collection_mode="open_licensed_api",
        access="public",
        live_pull=True,
        url="https://overpass-api.de/api/interpreter",
        notes="Open map/business data for public-facing organizations and public contact channels.",
    ),
]


REGION_PUBLICATIONS: dict[RegionId, list[str]] = {
    "austin_tx": ["Community Impact", "Austin Monitor"],
    "houston_tx": ["Community Impact", "Axios", "Houston Public Media"],
    "gunnison_valley_co": ["Crested Butte News", "KBUT", "Gunnison Country Times"],
}


REGION_NEWS_QUERIES: dict[RegionId, list[str]] = {
    "austin_tx": [
        "Austin retail vacancy",
        "Austin new restaurant opening",
        "Austin business expansion",
        "Austin new construction retail",
    ],
    "houston_tx": [
        "Houston retail vacancy",
        "Houston new restaurant opening",
        "Houston business expansion",
        "Houston new construction retail",
    ],
    "gunnison_valley_co": [
        "Gunnison Valley business opening",
        "Crested Butte restaurant opening",
        "Gunnison construction permit",
        "Crested Butte business closure",
    ],
}


def _stable_id(*parts: str) -> str:
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()
    return digest[:16]


def _now_utc() -> datetime:
    return datetime.now(tz=UTC)


def _parse_isoish(value: str | None) -> str:
    if not value:
        return utc_now_iso()
    text = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).astimezone(UTC).isoformat()
    except ValueError:
        return utc_now_iso()


def _parse_pubdate(value: str | None) -> str:
    if not value:
        return utc_now_iso()
    text = clean_text(value)
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            parsed = datetime.strptime(text, fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC).isoformat()
        except ValueError:
            continue
    return utc_now_iso()


def _extract_address_hint(text: str) -> str | None:
    match = ADDRESS_RE.search(text or "")
    if not match:
        return None
    return " ".join(match.group(0).split())


def _signal_type_from_text(text: str) -> str:
    lowered = clean_text(text).lower()
    if any(term in lowered for term in ["vacant", "vacate", "vacated", "closure", "closing", "closed"]):
        return "vacancy_or_closure"
    if any(term in lowered for term in ["opening", "opens", "opened", "grand opening", "new location"]):
        return "opening"
    if any(term in lowered for term in ["construction", "groundbreaking", "build", "building permit", "site prep"]):
        return "construction"
    if any(term in lowered for term in ["expands", "expansion", "headquarters", "hq", "relocate", "relocation"]):
        return "expansion"
    if any(term in lowered for term in ["hiring", "layoff", "job", "jobs"]):
        return "employment"
    return "general_business"


def _possible_orgs_from_title(title: str) -> list[str]:
    lowered = title.lower()
    verbs = [" opens ", " opening ", " opened ", " closes ", " closing ", " expands ", " expansion ", " builds ", " plans "]
    candidates: list[str] = []
    for verb in verbs:
        idx = lowered.find(verb)
        if idx > 0:
            candidate = title[:idx].strip(" :-,")
            if 1 <= len(candidate.split()) <= 6:
                candidates.append(candidate)
    deduped: list[str] = []
    seen: set[str] = set()
    for value in candidates:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped


def _extract_source_label(item: ET.Element) -> str:
    source = item.find("source")
    if source is not None and source.text:
        return clean_text(source.text)
    title = clean_text(item.findtext("title", default=""))
    if " - " in title:
        tail = title.rsplit(" - ", 1)[-1]
        if tail:
            return tail
    return "Unknown publication"


def _extract_link(item: ET.Element) -> str:
    link = clean_text(item.findtext("link", default=""))
    return link


def _extract_summary(item: ET.Element) -> str:
    return clean_text(item.findtext("description", default="") or item.findtext("summary", default=""))


def _preferred_source(publication: str, allowed_fragments: list[str]) -> bool:
    if not allowed_fragments:
        return True
    candidate = publication.lower()
    return any(fragment.lower() in candidate for fragment in allowed_fragments)


def _austin_permit_signal_type(permit_type: str, description: str) -> str:
    text = f"{permit_type} {description}".lower()
    if any(term in text for term in ["restaurant", "driveway", "walkway", "shell", "foundation", "site work", "drive-thru"]):
        return "construction"
    if any(term in text for term in ["tenant", "fit-out", "interior"]):
        return "tenant_improvement"
    return "permit_activity"


def _county_portal_datatables_payload(*, start: int, length: int) -> dict[str, str]:
    payload: dict[str, str] = {
        "draw": "1",
        "start": str(max(0, start)),
        "length": str(max(1, min(100, length))),
        "search[value]": "",
        "search[regex]": "false",
        "order[0][column]": "6",
        "order[0][dir]": "desc",
    }
    columns = [
        ("propertyType", False),
        ("name", False),
        ("address", False),
        ("permitNumber", True),
        ("permitType", False),
        ("status", False),
        ("statusDate", True),
    ]
    for idx, (name, orderable) in enumerate(columns):
        payload[f"columns[{idx}][data]"] = name
        payload[f"columns[{idx}][name]"] = name
        payload[f"columns[{idx}][searchable]"] = "true"
        payload[f"columns[{idx}][orderable]"] = "true" if orderable else "false"
        payload[f"columns[{idx}][search][value]"] = ""
        payload[f"columns[{idx}][search][regex]"] = "false"
    return payload


def _col_letters_to_index(value: str) -> int:
    total = 0
    for char in value:
        if not char.isalpha():
            continue
        total = total * 26 + (ord(char.upper()) - 64)
    return max(total - 1, 0)


def _xlsx_rows(data: bytes) -> list[dict[str, str]]:
    ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with ZipFile(BytesIO(data)) as archive:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root.findall("a:si", ns):
                shared_strings.append("".join((node.text or "") for node in item.findall(".//a:t", ns)))

        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))

    def cell_value(cell: ET.Element) -> str:
        cell_type = cell.attrib.get("t")
        value_node = cell.find("a:v", ns)
        inline_node = cell.find("a:is", ns)
        if inline_node is not None:
            return clean_text("".join((node.text or "") for node in inline_node.findall(".//a:t", ns)))
        if value_node is None or value_node.text is None:
            return ""
        raw = value_node.text
        if cell_type == "s":
            try:
                return clean_text(shared_strings[int(raw)])
            except Exception:
                return ""
        return clean_text(raw)

    matrix: list[dict[int, str]] = []
    for row in sheet.findall("a:sheetData/a:row", ns):
        values: dict[int, str] = {}
        for cell in row.findall("a:c", ns):
            ref = clean_text(cell.attrib.get("r", ""))
            col_letters = re.sub(r"\d", "", ref)
            values[_col_letters_to_index(col_letters)] = cell_value(cell)
        if values:
            matrix.append(values)

    if not matrix:
        return []

    headers = {index: value for index, value in matrix[0].items() if value}
    rows: list[dict[str, str]] = []
    for row in matrix[1:]:
        mapped = {header: clean_text(row.get(index, "")) for index, header in headers.items()}
        if any(mapped.values()):
            rows.append(mapped)
    return rows


def _excel_serial_to_iso(value: str | None) -> str:
    if not value:
        return utc_now_iso()
    try:
        serial = float(value)
        parsed = datetime(1899, 12, 30, tzinfo=UTC) + timedelta(days=serial)
        return parsed.isoformat()
    except (TypeError, ValueError):
        return _parse_pubdate(value)


def _houston_development_signal_type(application_type: str, land_use: str, title: str) -> str:
    text = clean_text(f"{application_type} {land_use} {title}").lower()
    if "commercial" in text or "unrestricted" in text:
        return "commercial_development"
    if any(term in text for term in ["restaurant", "retail", "bank", "branch", "plaza", "yard", "diesel", "hotel", "office"]):
        return "commercial_development"
    if "single family" in text or "residential" in text:
        return "residential_development"
    return "development_agenda"


def _houston_location_label(row: dict[str, str]) -> str:
    candidates = [
        row.get("App Location", ""),
        row.get("Major Throughfare", ""),
        row.get("Subdivision Name", ""),
    ]
    cleaned: list[str] = []
    for value in candidates:
        text = clean_text(value)
        if not text:
            continue
        if re.match(r"^[A-Z]\.\s", text):
            continue
        cleaned.append(text)
    if not cleaned:
        cleaned.append(clean_text(row.get("Subdivision Name", "")) or clean_text(row.get("App No.", "")) or "Houston development item")
    zipcode = clean_text(row.get("Zipcode", ""))
    label = cleaned[0]
    if zipcode and zipcode not in label:
        label = f"{label} {zipcode}"
    return label


def _permit_related_organizations(item: PermitSignal) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for note in item.notes:
        if ":" not in note:
            continue
        label, raw = note.split(":", 1)
        key = clean_text(label).lower()
        if key not in {"developer", "organization", "planning firm"}:
            continue
        value = clean_text(raw)
        if not value:
            continue
        normalized = _normalize_entity_name(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        output.append(value)
    return output


def _business_category(tags: dict[str, Any]) -> str:
    if tags.get("shop"):
        return f"shop:{tags['shop']}"
    if tags.get("office"):
        return f"office:{tags['office']}"
    if tags.get("amenity"):
        return f"amenity:{tags['amenity']}"
    if tags.get("tourism"):
        return f"tourism:{tags['tourism']}"
    return "business"


def _html_to_text(html: str) -> str:
    stripped = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
    stripped = re.sub(r"(?is)<style.*?>.*?</style>", " ", stripped)
    stripped = re.sub(r"(?s)<[^>]+>", " ", stripped)
    return clean_text(unescape(stripped))


def _extract_first_email(text: str) -> str | None:
    match = EMAIL_RE.search(text)
    return clean_text(match.group(0)) if match else None


def _extract_first_phone(text: str) -> str | None:
    match = PHONE_RE.search(text)
    return clean_text(match.group(0)) if match else None


def _normalize_entity_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", clean_text(value).lower())


def _derive_org_keywords(
    businesses: list[BusinessLead],
    contacts: list[PublicContact],
    permits: list[PermitSignal],
) -> dict[RegionId, list[str]]:
    keywords: dict[RegionId, list[str]] = {region.id: [] for region in REGIONS}
    for item in businesses:
        name = clean_text(item.name)
        if len(name) < 4:
            continue
        keywords[item.region_id].append(name)
    for item in contacts:
        for value in (item.organization, item.name):
            label = clean_text(value)
            if len(label) >= 4:
                keywords[item.region_id].append(label)
    for item in permits:
        for value in _permit_related_organizations(item):
            label = clean_text(value)
            if len(label) >= 4:
                keywords[item.region_id].append(label)
    output: dict[RegionId, list[str]] = {}
    for region_id, values in keywords.items():
        deduped: list[str] = []
        seen: set[str] = set()
        for value in sorted(values, key=len, reverse=True):
            key = value.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(value)
        output[region_id] = deduped[:120]
    return output


def _extract_organizations_from_text(text: str, candidates: list[str]) -> list[str]:
    lowered = clean_text(text).lower()
    output: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = candidate.lower()
        if len(key) < 4 or key in seen:
            continue
        if key in lowered:
            seen.add(key)
            output.append(candidate)
    return output[:6]


def _build_organization_profiles(
    *,
    news: list[NewsSignal],
    permits: list[PermitSignal],
    businesses: list[BusinessLead],
    contacts: list[PublicContact],
) -> list[OrganizationProfile]:
    profiles: dict[tuple[RegionId, str], OrganizationProfile] = {}

    def ensure_profile(region_id: RegionId, name: str) -> OrganizationProfile:
        key = (region_id, _normalize_entity_name(name))
        if key not in profiles:
            profiles[key] = OrganizationProfile(
                item_id=_stable_id(region_id, "organization", name),
                region_id=region_id,
                name=name,
            )
        return profiles[key]

    def touch_latest(profile: OrganizationProfile, timestamp: str | None) -> None:
        if not timestamp:
            return
        if profile.latest_activity_at is None or timestamp > profile.latest_activity_at:
            profile.latest_activity_at = timestamp

    for item in businesses:
        profile = ensure_profile(item.region_id, item.name)
        profile.business_lead_count += 1
        if item.category and item.category not in profile.categories:
            profile.categories.append(item.category)
        if item.address and item.address != "Address not provided" and not profile.address:
            profile.address = item.address
        if item.website and not profile.website:
            profile.website = item.website
        if item.phone and not profile.phone:
            profile.phone = item.phone
        if item.email and not profile.email:
            profile.email = item.email
        if item.source_name not in profile.source_names:
            profile.source_names.append(item.source_name)

    for item in contacts:
        profile = ensure_profile(item.region_id, item.organization)
        profile.contact_count += 1
        if item.title and item.title not in profile.categories:
            profile.categories.append(item.title)
        if item.address and not profile.address:
            profile.address = item.address
        if item.website and not profile.website:
            profile.website = item.website
        if item.phone and not profile.phone:
            profile.phone = item.phone
        if item.email and not profile.email:
            profile.email = item.email
        if item.source_name not in profile.source_names:
            profile.source_names.append(item.source_name)

    for item in permits:
        for org_name in _permit_related_organizations(item):
            profile = ensure_profile(item.region_id, org_name)
            profile.permit_signal_count += 1
            if item.signal_type and item.signal_type not in profile.categories:
                profile.categories.append(item.signal_type)
            if item.source_name not in profile.source_names:
                profile.source_names.append(item.source_name)
            touch_latest(profile, item.status_date)

    for item in news:
        for org in item.organizations:
            profile = ensure_profile(item.region_id, org)
            profile.news_signal_count += 1
            if item.signal_type and item.signal_type not in profile.categories:
                profile.categories.append(item.signal_type)
            if item.source_name not in profile.source_names:
                profile.source_names.append(item.source_name)
            touch_latest(profile, item.published_at)

    output = list(profiles.values())
    output.sort(
        key=lambda item: (
            item.region_id,
            -(item.business_lead_count + item.news_signal_count + item.contact_count + item.permit_signal_count),
            item.name.lower(),
        )
    )
    return output[:180]


def _hours_since(iso_string: str | None) -> float | None:
    if not iso_string:
        return None
    try:
        delta = _now_utc() - datetime.fromisoformat(iso_string.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None
    return max(delta.total_seconds() / 3600, 0.0)


def _news_signal_score(item: NewsSignal) -> float:
    score = 35.0
    weights = {
        "vacancy_or_closure": 34.0,
        "construction": 26.0,
        "opening": 22.0,
        "expansion": 18.0,
        "employment": 12.0,
    }
    score += weights.get(item.signal_type, 8.0)
    if item.actionable:
        score += 22.0
    if item.address_hint:
        score += 10.0
    if item.organizations:
        score += min(len(item.organizations) * 3.0, 12.0)
    age_hours = _hours_since(item.published_at)
    if age_hours is not None:
        score += max(18.0 - min(age_hours / 24.0, 18.0), 0.0)
    return round(score, 2)


def _permit_signal_score(item: PermitSignal) -> float:
    score = 42.0
    weights = {
        "construction": 26.0,
        "tenant_improvement": 18.0,
        "permit_activity": 12.0,
        "commercial_development": 22.0,
        "residential_development": 14.0,
        "development_agenda": 16.0,
        "general_business": 8.0,
    }
    score += weights.get(item.signal_type, 8.0)
    status = item.status.lower()
    if "approved" in status or "issued" in status:
        score += 14.0
    elif "review" in status:
        score += 8.0
    age_hours = _hours_since(item.status_date)
    if age_hours is not None:
        score += max(14.0 - min(age_hours / 72.0, 14.0), 0.0)
    return round(score, 2)


def _business_lead_score(item: BusinessLead) -> float:
    score = 28.0
    score += 18.0 if item.address and item.address != "Address not provided" else 0.0
    score += 12.0 if item.website else 0.0
    score += 10.0 if item.phone else 0.0
    score += 12.0 if item.email else 0.0
    if item.category.startswith("office:"):
        score += 10.0
    elif item.category.startswith("shop:"):
        score += 8.0
    elif item.category.startswith("amenity:"):
        score += 6.0
    return round(score, 2)


def _contact_score(item: PublicContact) -> float:
    score = 45.0
    score += 14.0 if item.email else 0.0
    score += 10.0 if item.phone else 0.0
    score += 8.0 if item.address else 0.0
    score += 6.0 if item.website else 0.0
    score += 8.0 if item.contact_type == "public_news_figure" else 0.0
    return round(score, 2)


def _organization_score(item: OrganizationProfile) -> float:
    score = 20.0
    score += item.business_lead_count * 8.0
    score += item.news_signal_count * 10.0
    score += item.contact_count * 12.0
    score += item.permit_signal_count * 9.0
    score += 10.0 if item.website else 0.0
    score += 8.0 if item.phone else 0.0
    score += 10.0 if item.email else 0.0
    return round(score, 2)


def _source_matches_name(source: IntelSource, candidate_name: str, candidate_url: str | None = None) -> bool:
    source_name = source.name.lower()
    candidate = clean_text(candidate_name).lower()
    if source_name in candidate or candidate in source_name:
        return True
    if candidate_url and source.url and source.url in candidate_url:
        return True
    if source.url and candidate_url and source.url.split("://", 1)[-1].split("/", 1)[0] in candidate_url:
        return True
    return False


def _build_source_health(
    snapshot: RegionalIntelSnapshot,
    failed_sources: dict[str, dict[str, Any]] | None = None,
) -> list[SourceHealth]:
    output: list[SourceHealth] = []
    failed = failed_sources or {}
    for source in snapshot.sources:
        last_seen_at: str | None = None
        item_count = 0
        if source.category == "news":
            matches = [item for item in snapshot.news if _source_matches_name(source, item.source_name, item.source_url)]
            item_count = len(matches)
            last_seen_at = matches[0].published_at if matches else None
        elif source.category == "permit":
            matches = [item for item in snapshot.permits if _source_matches_name(source, item.source_name, item.source_url)]
            item_count = len(matches)
            last_seen_at = matches[0].status_date if matches else None
        elif source.category == "business":
            matches = [item for item in snapshot.businesses if _source_matches_name(source, item.source_name, item.source_url)]
            item_count = len(matches)
            last_seen_at = snapshot.updated_at if matches else None
        else:
            matches = [item for item in snapshot.contacts if _source_matches_name(source, item.source_name, item.source_url)]
            item_count = len(matches)
            last_seen_at = snapshot.updated_at if matches else None

        status = "manual"
        notes: list[str] = []
        if source.live_pull:
            status = "live" if item_count > 0 else "empty"
            if item_count == 0:
                notes.append("No items observed in the latest snapshot.")
        else:
            notes.append("Manual-reference source; live adapter still pending.")
        # Overlay any recorded fetch failures matching this source.
        for label, record in failed.items():
            if (
                source.source_key == label
                or source.name == label
                or label.startswith(f"{source.source_key}:")
            ):
                status = "failed"
                notes.append(
                    f"Fetch failed after {record['attempts']} attempt(s): {record['error']}."
                )
        output.append(
            SourceHealth(
                source_key=source.source_key,
                name=source.name,
                category=source.category,
                region_ids=source.region_ids,
                live_pull=source.live_pull,
                status=status,
                item_count=item_count,
                last_seen_at=last_seen_at,
                notes=notes,
            )
        )
    return output


def _build_region_briefs(snapshot: RegionalIntelSnapshot) -> list[RegionBrief]:
    briefs: list[RegionBrief] = []
    for region in snapshot.regions:
        news = sorted([item for item in snapshot.news if item.region_id == region.id], key=lambda item: item.signal_score, reverse=True)
        permits = sorted([item for item in snapshot.permits if item.region_id == region.id], key=lambda item: item.signal_score, reverse=True)
        orgs = sorted([item for item in snapshot.organizations if item.region_id == region.id], key=lambda item: item.organization_score, reverse=True)
        contacts = sorted([item for item in snapshot.contacts if item.region_id == region.id], key=lambda item: item.contact_score, reverse=True)
        headline_bits = [
            f"{len(news)} news",
            f"{len(permits)} permits",
            f"{len(orgs)} organizations",
            f"{len(contacts)} contacts",
        ]
        notes: list[str] = []
        if news[:1]:
            notes.append(f"Top news signal: {news[0].title}")
        if permits[:1]:
            notes.append(f"Top permit signal: {permits[0].address} ({permits[0].permit_type})")
        if orgs[:1]:
            notes.append(f"Top organization watch: {orgs[0].name}")
        if contacts[:1]:
            notes.append(f"Best public contact lead: {contacts[0].name}")
        briefs.append(
            RegionBrief(
                region_id=region.id,
                headline=f"{region.name}: " + ", ".join(headline_bits),
                summary=(
                    f"{region.summary} Highest-signal items are ranked first, with actionable news and recent permits weighted above generic observations."
                ),
                top_news_ids=[item.item_id for item in news[:3]],
                top_permit_ids=[item.item_id for item in permits[:3]],
                top_organization_ids=[item.item_id for item in orgs[:3]],
                top_contact_ids=[item.item_id for item in contacts[:3]],
                notes=notes,
            )
        )
    return briefs


ALLOWED_AMENITIES = {
    "restaurant",
    "cafe",
    "fast_food",
    "bar",
    "pub",
    "biergarten",
    "bank",
    "pharmacy",
    "clinic",
    "dentist",
    "hospital",
    "veterinary",
    "marketplace",
    "ice_cream",
    "car_rental",
}
ALLOWED_TOURISM = {"hotel", "motel", "guest_house", "hostel", "museum", "gallery"}
ALLOWED_LEISURE = {"fitness_centre", "sports_centre"}
NOISE_NAME_RE = re.compile(
    r"\b(trail|campground|river|creek|station|road|loop|well|pass|spur|ditch|flume|highway|meteorological)\b",
    re.IGNORECASE,
)


def _is_useful_business(tags: dict[str, Any], name: str) -> bool:
    if tags.get("shop") or tags.get("office"):
        return True
    if tags.get("craft"):
        return True
    amenity = clean_text(str(tags.get("amenity") or "")).lower()
    if amenity in ALLOWED_AMENITIES:
        return True
    tourism = clean_text(str(tags.get("tourism") or "")).lower()
    if tourism in ALLOWED_TOURISM:
        return True
    leisure = clean_text(str(tags.get("leisure") or "")).lower()
    if leisure in ALLOWED_LEISURE:
        return True
    if NOISE_NAME_RE.search(name):
        return False
    return False


def _business_sort_key(item: BusinessLead) -> tuple[int, int, str]:
    contact_score = int(bool(item.email)) + int(bool(item.phone)) + int(bool(item.website))
    address_score = 0 if item.address == "Address not provided" else 1
    return (-contact_score, -address_score, item.name.lower())


def _business_query_for_bbox(south: float, west: float, north: float, east: float) -> str:
    return f"""
[out:json][timeout:25];
(
  node["name"]["shop"]({south},{west},{north},{east});
  node["name"]["office"]({south},{west},{north},{east});
  node["name"]["craft"]({south},{west},{north},{east});
  node["name"]["amenity"~"restaurant|cafe|fast_food|bar|pub|biergarten|bank|pharmacy|clinic|dentist|hospital|veterinary|marketplace|ice_cream|car_rental"]({south},{west},{north},{east});
  node["name"]["tourism"~"hotel|motel|guest_house|hostel|museum|gallery"]({south},{west},{north},{east});
  node["name"]["leisure"~"fitness_centre|sports_centre"]({south},{west},{north},{east});
  way["name"]["shop"]({south},{west},{north},{east});
  way["name"]["office"]({south},{west},{north},{east});
  way["name"]["craft"]({south},{west},{north},{east});
  way["name"]["amenity"~"restaurant|cafe|fast_food|bar|pub|biergarten|bank|pharmacy|clinic|dentist|hospital|veterinary|marketplace|ice_cream|car_rental"]({south},{west},{north},{east});
  way["name"]["tourism"~"hotel|motel|guest_house|hostel|museum|gallery"]({south},{west},{north},{east});
  way["name"]["leisure"~"fitness_centre|sports_centre"]({south},{west},{north},{east});
  relation["name"]["shop"]({south},{west},{north},{east});
  relation["name"]["office"]({south},{west},{north},{east});
  relation["name"]["craft"]({south},{west},{north},{east});
  relation["name"]["amenity"~"restaurant|cafe|fast_food|bar|pub|biergarten|bank|pharmacy|clinic|dentist|hospital|veterinary|marketplace|ice_cream|car_rental"]({south},{west},{north},{east});
  relation["name"]["tourism"~"hotel|motel|guest_house|hostel|museum|gallery"]({south},{west},{north},{east});
  relation["name"]["leisure"~"fitness_centre|sports_centre"]({south},{west},{north},{east});
);
out center 120;
"""


def _bbox_tiles(bbox: list[float]) -> list[tuple[float, float, float, float]]:
    south, west, north, east = bbox
    mid_lat = (south + north) / 2
    mid_lon = (west + east) / 2
    return [
        (south, west, mid_lat, mid_lon),
        (south, mid_lon, mid_lat, east),
        (mid_lat, west, north, mid_lon),
        (mid_lat, mid_lon, north, east),
    ]


class RegionalIntelService:
    def __init__(self, ttl_seconds: int = 900) -> None:
        self.ttl_seconds = ttl_seconds
        self.history_store = RegionalIntelHistoryStore()
        self._lock = asyncio.Lock()
        self._snapshot: RegionalIntelSnapshot | None = None
        self._expires_at = 0.0
        # Per-snapshot failure ledger keyed by source label. Cleared at the
        # start of each _build_snapshot so source-health reflects the latest
        # collection cycle only.
        self._failed_sources: dict[str, dict[str, Any]] = {}

    async def _retry_fetch(
        self,
        source_label: str,
        factory,
        *,
        retry_limit: int | None = None,
        backoff_base: float | None = None,
        sleep=None,
    ):
        """Run ``factory()`` with bounded retry on transient errors.

        ``factory`` must be a zero-argument callable returning an awaitable
        (so each retry gets a fresh coroutine). Returns the awaited value on
        success. On total failure (or non-transient exception) returns ``None``
        and records the failure under ``source_label`` in ``_failed_sources``
        so :func:`_build_source_health` can surface it.
        """
        settings = get_settings()
        attempts = retry_limit if retry_limit is not None else settings.regional_intel_retry_limit
        base = backoff_base if backoff_base is not None else settings.regional_intel_retry_backoff_base
        sleeper = sleep if sleep is not None else asyncio.sleep
        last_exc: BaseException | None = None
        # attempts is the number of retries; total tries == attempts + 1.
        for attempt in range(attempts + 1):
            try:
                return await factory()
            except _TRANSIENT_RETRY_EXCEPTIONS as exc:
                last_exc = exc
                if attempt >= attempts:
                    break
                # Bounded exponential backoff: base * 2**attempt, capped so the
                # tail of any retry chain cannot exceed the per-source timeout.
                cap = max(get_settings().regional_intel_source_timeout, base)
                delay = min(base * (2 ** attempt), cap)
                await sleeper(delay)
            except Exception as exc:  # non-transient: fail fast.
                self._record_source_failure(source_label, exc, transient=False, attempts=attempt + 1)
                return None
        self._record_source_failure(
            source_label,
            last_exc if last_exc is not None else RuntimeError("unknown failure"),
            transient=True,
            attempts=attempts + 1,
        )
        return None

    def _record_source_failure(
        self,
        source_label: str,
        exc: BaseException,
        *,
        transient: bool,
        attempts: int,
    ) -> None:
        self._failed_sources[source_label] = {
            "label": source_label,
            "error": f"{type(exc).__name__}: {exc}",
            "transient": transient,
            "attempts": attempts,
            "observed_at": utc_now_iso(),
        }

    async def get_snapshot(self, force_refresh: bool = False) -> RegionalIntelSnapshot:
        now = time.monotonic()
        if not force_refresh and self._snapshot is not None and now < self._expires_at:
            return self._snapshot
        if not force_refresh and self._snapshot is None:
            latest_record = self.history_store.load_latest_record()
            if latest_record:
                self._snapshot = RegionalIntelSnapshot(**latest_record)
                self._expires_at = time.monotonic() + min(self.ttl_seconds, 60)
                return self._snapshot
        async with self._lock:
            now = time.monotonic()
            if not force_refresh and self._snapshot is not None and now < self._expires_at:
                return self._snapshot
            snapshot = await self._build_snapshot(force_history_append=force_refresh)
            self._snapshot = snapshot
            self._expires_at = time.monotonic() + self.ttl_seconds
            return snapshot

    async def _build_snapshot(self, *, force_history_append: bool = False) -> RegionalIntelSnapshot:
        # Reset per-snapshot failure ledger so source-health only reflects this
        # collection cycle.
        self._failed_sources = {}
        timeout = get_settings().regional_intel_source_timeout
        async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": "regional-intel-bot/0.1"}) as client:
            news_task = asyncio.create_task(self._collect_news(client))
            permit_task = asyncio.create_task(self._collect_permits(client))
            business_task = asyncio.create_task(self._collect_businesses(client))
            contact_task = asyncio.create_task(self._collect_contacts(client))

            news, permits, businesses, contacts = await asyncio.gather(
                news_task,
                permit_task,
                business_task,
                contact_task,
            )

        history_records = self.history_store.load_records(lookback_days=7)
        notes: list[str] = [
            "This subsystem only ingests public open data, public RSS/news indexes, public permit portals, and open-licensed map data.",
            "Subscription/paywalled sources stay visible in the source catalog but are manual-reference only.",
            "Business leads are organization-level public contact points, not private personal dossiers.",
        ]
        if history_records:
            latest = history_records[-1]
            news, news_backfills = self._backfill_news(news, latest)
            permits, permit_backfills = self._backfill_permits(permits, latest)
            businesses, business_backfills = self._backfill_businesses(businesses, latest)
            contacts, contact_backfills = self._backfill_contacts(contacts, latest)
            if news_backfills or permit_backfills or business_backfills or contact_backfills:
                notes.append(
                    "One or more categories were backfilled from the last successful snapshot because a live public source returned empty data."
                )
                if news_backfills:
                    notes.append(f"News backfill applied for: {', '.join(news_backfills)}.")
                if permit_backfills:
                    notes.append(f"Permit backfill applied for: {', '.join(permit_backfills)}.")
                if business_backfills:
                    notes.append(f"Business lead backfill applied for: {', '.join(business_backfills)}.")
                if contact_backfills:
                    notes.append(f"Contact backfill applied for: {', '.join(contact_backfills)}.")

        organization_keywords = _derive_org_keywords(businesses, contacts, permits)
        for item in news:
            merged = list(item.organizations)
            seen = {value.lower() for value in merged}
            for candidate in _extract_organizations_from_text(
                f"{item.title} {item.summary} {' '.join(item.notes)}",
                organization_keywords.get(item.region_id, []),
            ):
                if candidate.lower() in seen:
                    continue
                seen.add(candidate.lower())
                merged.append(candidate)
            item.organizations = merged[:6]
            item.signal_score = _news_signal_score(item)
        news.sort(key=lambda item: (item.signal_score, item.published_at), reverse=True)

        organizations = _build_organization_profiles(news=news, permits=permits, businesses=businesses, contacts=contacts)
        for item in contacts:
            item.contact_score = _contact_score(item)
        for item in organizations:
            item.organization_score = _organization_score(item)
        organizations.sort(key=lambda item: (item.region_id, -item.organization_score, item.name.lower()))
        source_health = _build_source_health(
            RegionalIntelSnapshot(
                updated_at=utc_now_iso(),
                cache_ttl_seconds=self.ttl_seconds,
                regions=REGIONS,
                ethics_rules=ETHICS_RULES,
                sources=SOURCES,
                news=news,
                permits=permits,
                businesses=businesses,
                contacts=contacts,
                organizations=organizations,
            ),
            failed_sources=self._failed_sources,
        )
        if self._failed_sources:
            failure_labels = sorted(self._failed_sources.keys())
            notes.append(
                "One or more public sources failed during this collection: "
                + ", ".join(failure_labels)
                + ". See source_health for details."
            )
        briefs = _build_region_briefs(
            RegionalIntelSnapshot(
                updated_at=utc_now_iso(),
                cache_ttl_seconds=self.ttl_seconds,
                regions=REGIONS,
                ethics_rules=ETHICS_RULES,
                sources=SOURCES,
                news=news,
                permits=permits,
                businesses=businesses,
                contacts=contacts,
                organizations=organizations,
            )
        )

        snapshot = RegionalIntelSnapshot(
            updated_at=utc_now_iso(),
            cache_ttl_seconds=self.ttl_seconds,
            regions=REGIONS,
            ethics_rules=ETHICS_RULES,
            sources=SOURCES,
            news=news,
            permits=permits,
            businesses=businesses,
            contacts=contacts,
            organizations=organizations,
            source_health=source_health,
            briefs=briefs,
            notes=notes,
        )
        self.history_store.append_snapshot(snapshot, force=force_history_append)
        return snapshot

    async def _collect_news(self, client: httpx.AsyncClient) -> list[NewsSignal]:
        items: list[NewsSignal] = []
        seen: set[str] = set()
        for region in REGIONS:
            allowed_publications = REGION_PUBLICATIONS.get(region.id, [])
            for query in REGION_NEWS_QUERIES.get(region.id, []):
                url = GOOGLE_NEWS_RSS.format(query=quote_plus(query))

                async def _fetch(url=url):
                    response = await client.get(url)
                    response.raise_for_status()
                    return response

                response = await self._retry_fetch(
                    f"google_news_rss:{region.id}:{query}", _fetch
                )
                if response is None:
                    continue
                try:
                    root = ET.fromstring(response.text)
                except ET.ParseError:
                    continue
                for item in root.findall(".//item")[:8]:
                    title = clean_text(item.findtext("title", default=""))
                    if not title:
                        continue
                    publication = _extract_source_label(item)
                    if not _preferred_source(publication, allowed_publications):
                        continue
                    link = _extract_link(item)
                    if not link:
                        continue
                    item_key = _stable_id(region.id, link)
                    if item_key in seen:
                        continue
                    seen.add(item_key)
                    summary = _extract_summary(item)
                    signal_type = _signal_type_from_text(f"{title} {summary}")
                    address_hint = _extract_address_hint(f"{title} {summary}")
                    actionable = bool(address_hint and signal_type in {"vacancy_or_closure", "opening", "construction", "expansion"})
                    notes: list[str] = []
                    if not actionable and signal_type in {"vacancy_or_closure", "opening", "construction"}:
                        notes.append("Address missing; treat as research queue until linked.")
                    items.append(
                        NewsSignal(
                            item_id=item_key,
                            region_id=region.id,
                            title=title,
                            summary=summary,
                            source_name=publication,
                            source_url=link,
                            published_at=_parse_pubdate(item.findtext("pubDate", default="")),
                            publication=publication,
                            signal_type=signal_type,
                            address_hint=address_hint,
                            actionable=actionable,
                            organizations=_possible_orgs_from_title(title),
                            query=query,
                            notes=notes,
                        )
                    )
        items.sort(key=lambda item: item.published_at, reverse=True)
        return items[:120]

    async def _collect_permits(self, client: httpx.AsyncClient) -> list[PermitSignal]:
        permits: list[PermitSignal] = []
        permits.extend(await self._collect_austin_region_permits(client))
        permits.extend(await self._collect_houston_region_development_reports(client))
        for item in permits:
            item.signal_score = _permit_signal_score(item)
        return sorted(permits, key=lambda item: (item.signal_score, item.status_date), reverse=True)[:120]

    async def _collect_austin_region_permits(self, client: httpx.AsyncClient) -> list[PermitSignal]:
        output: list[PermitSignal] = []

        async def _fetch_austin():
            response = await client.get(
                AUSTIN_PERMITS_URL,
                params={"$order": "issue_date DESC", "$limit": "25"},
            )
            response.raise_for_status()
            return response.json()

        rows = await self._retry_fetch("austin_open_data_permits", _fetch_austin)
        if rows is None:
            rows = []

        for row in rows:
            if not isinstance(row, dict):
                continue
            address = clean_text(
                str(
                    row.get("original_address1")
                    or row.get("full_address")
                    or row.get("address")
                    or ""
                )
            )
            if not address:
                continue
            permit_type = clean_text(str(row.get("permit_class_mapped") or row.get("work_class") or "Permit"))
            description = clean_text(str(row.get("description") or ""))
            output.append(
                PermitSignal(
                    item_id=_stable_id("austin_tx", address, str(row.get("permit_number") or "")),
                    region_id="austin_tx",
                    county="Travis",
                    address=address,
                    permit_number=clean_text(str(row.get("permit_number") or row.get("permitnum") or "")),
                    permit_type=permit_type,
                    status=clean_text(str(row.get("status_current") or row.get("permit_status") or "Issued")),
                    status_date=_parse_isoish(str(row.get("issue_date") or row.get("issued_date") or "")),
                    source_name="City of Austin Open Data",
                    source_url="https://data.austintexas.gov/Building-and-Development/Issued-Construction-Permits/3syk-w9eu",
                    signal_type=_austin_permit_signal_type(permit_type, description),
                    notes=[description] if description else [],
                )
            )

        county_specs = [
            ("Hays", HAYS_PERMITS_URL),
            ("Williamson", WILCO_PERMITS_URL),
        ]
        for county, url in county_specs:

            async def _fetch_county(url=url):
                response = await client.post(url, data=_county_portal_datatables_payload(start=0, length=15))
                response.raise_for_status()
                return response.json()

            payload = await self._retry_fetch(f"county_public_permits:{county}", _fetch_county)
            if payload is None:
                rows = []
            else:
                rows = payload.get("data", []) if isinstance(payload, dict) else []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                address = clean_text(str(row.get("address") or ""))
                if not address:
                    continue
                permit_type = clean_text(str(row.get("permitType") or "Permit"))
                signal_type = _signal_type_from_text(f"{permit_type} {row.get('name') or ''}")
                output.append(
                    PermitSignal(
                        item_id=_stable_id("austin_tx", county, address, str(row.get("permitNumber") or "")),
                        region_id="austin_tx",
                        county=county,
                        address=address,
                        permit_number=clean_text(str(row.get("permitNumber") or "")),
                        permit_type=permit_type,
                        status=clean_text(str(row.get("status") or "")),
                        status_date=_parse_pubdate(str(row.get("statusDate") or "")),
                        source_name=f"{county} County Public Permits",
                        source_url=url.replace("/api/v1/permits/datatables/list/public", "/public/permits/list"),
                        signal_type=signal_type,
                        notes=[clean_text(str(row.get("name") or ""))] if clean_text(str(row.get("name") or "")) else [],
                    )
                )
        return output

    async def _collect_houston_region_development_reports(self, client: httpx.AsyncClient) -> list[PermitSignal]:
        async def _fetch_index():
            response = await client.get(HOUSTON_DEV_REPORTS_URL)
            response.raise_for_status()
            return response

        response = await self._retry_fetch("houston_planning_dev_reports", _fetch_index)
        if response is None:
            return []

        links = re.findall(r'href=["\']([^"\']+\.xlsx)["\']', response.text, re.IGNORECASE)
        seen_urls: set[str] = set()
        report_urls: list[str] = []
        for href in links:
            absolute = urljoin(HOUSTON_DEV_REPORTS_URL, href)
            if absolute in seen_urls:
                continue
            seen_urls.add(absolute)
            report_urls.append(absolute)
        report_urls = report_urls[:3]
        if not report_urls:
            return []

        output: list[PermitSignal] = []
        seen_rows: set[str] = set()
        for report_url in report_urls:

            async def _fetch_report(report_url=report_url):
                report_response = await client.get(report_url)
                report_response.raise_for_status()
                return report_response.content

            content = await self._retry_fetch(f"houston_planning_report:{report_url}", _fetch_report)
            if content is None:
                continue
            try:
                rows = _xlsx_rows(content)
            except Exception:
                continue
            for row in rows:
                subdivision_name = clean_text(row.get("Subdivision Name", ""))
                application_number = clean_text(row.get("App No.", ""))
                if not subdivision_name or not application_number:
                    continue
                item_key = _stable_id("houston_tx", report_url, application_number)
                if item_key in seen_rows:
                    continue
                seen_rows.add(item_key)
                application_type = clean_text(row.get("Application Type", "")) or "Planning agenda item"
                land_use = clean_text(row.get("Land Use", ""))
                location_label = _houston_location_label(row)
                major_throughfare = clean_text(row.get("Major Throughfare", ""))
                developer = clean_text(row.get("Developer Company Name", ""))
                organization = clean_text(row.get("Organization", ""))
                applicant = clean_text(row.get("Applicant Name", ""))
                office_phone = clean_text(row.get("Office Phone", ""))
                pdf_url = clean_text(row.get("Download Subdivision Plat PDF File", ""))
                notes: list[str] = []
                if developer:
                    notes.append(f"Developer: {developer}")
                if organization:
                    notes.append(f"Organization: {organization}")
                if applicant:
                    notes.append(f"Applicant: {applicant}")
                if office_phone:
                    notes.append(f"Office phone: {office_phone}")
                if land_use:
                    notes.append(f"Land use: {land_use}")
                if major_throughfare:
                    notes.append(f"Major thoroughfare: {major_throughfare}")
                if pdf_url:
                    notes.append(f"Plat PDF: {pdf_url}")
                actionable = bool(ADDRESS_RE.search(location_label))
                if not actionable:
                    notes.append("Street address not present in official report; treat as research queue until matched to a parcel or site.")
                output.append(
                    PermitSignal(
                        item_id=item_key,
                        region_id="houston_tx",
                        county=clean_text(row.get("County", "")) or "Harris",
                        address=location_label,
                        permit_number=application_number,
                        permit_type=application_type,
                        status="Agenda report",
                        status_date=_excel_serial_to_iso(row.get("Date Submitted") or row.get("PC Date (Cycle)") or ""),
                        source_name="Houston Planning Plat Activity Reports",
                        source_url=report_url,
                        signal_type=_houston_development_signal_type(application_type, land_use, subdivision_name),
                        actionable=actionable,
                        notes=notes,
                    )
                )
        return output

    async def _collect_businesses(self, client: httpx.AsyncClient) -> list[BusinessLead]:
        businesses: list[BusinessLead] = []
        for region in REGIONS:
            businesses.extend(await self._collect_region_businesses(client, region))
        businesses.sort(key=lambda item: (item.region_id, *_business_sort_key(item)))
        return businesses[:240]

    async def _collect_region_businesses(self, client: httpx.AsyncClient, region: RegionProfile) -> list[BusinessLead]:
        async def fetch_elements(bbox: tuple[float, float, float, float]) -> list[dict[str, Any]]:
            south, west, north, east = bbox

            async def _fetch_overpass():
                response = await client.post(OVERPASS_URL, content=_business_query_for_bbox(south, west, north, east).encode("utf-8"))
                response.raise_for_status()
                return response.json()

            payload = await self._retry_fetch(
                f"osm_overpass:{region.id}:{south:.3f},{west:.3f}", _fetch_overpass
            )
            if payload is None:
                return []
            raw = payload.get("elements", []) if isinstance(payload, dict) else []
            return [item for item in raw if isinstance(item, dict)]

        elements = await fetch_elements(tuple(region.bbox))
        if not elements:
            tiled: list[dict[str, Any]] = []
            for bbox in _bbox_tiles(region.bbox):
                tiled.extend(await fetch_elements(bbox))
            elements = tiled

        output: list[BusinessLead] = []
        seen: set[str] = set()
        for element in elements:
            if not isinstance(element, dict):
                continue
            tags = element.get("tags", {})
            if not isinstance(tags, dict):
                continue
            name = clean_text(str(tags.get("name") or ""))
            if not name:
                continue
            if not _is_useful_business(tags, name):
                continue
            key = _stable_id(region.id, name, str(element.get("id") or ""))
            if key in seen:
                continue
            seen.add(key)
            lat = element.get("lat")
            lon = element.get("lon")
            center = element.get("center") if isinstance(element.get("center"), dict) else {}
            lat_value = float(center.get("lat", lat)) if center.get("lat", lat) is not None else None
            lon_value = float(center.get("lon", lon)) if center.get("lon", lon) is not None else None
            website = clean_text(str(tags.get("website") or tags.get("contact:website") or "")) or None
            phone = clean_text(str(tags.get("phone") or tags.get("contact:phone") or "")) or None
            email = clean_text(str(tags.get("email") or tags.get("contact:email") or "")) or None
            housenumber = clean_text(str(tags.get("addr:housenumber") or ""))
            street = clean_text(str(tags.get("addr:street") or ""))
            city = clean_text(str(tags.get("addr:city") or ""))
            address = " ".join(part for part in [housenumber, street, city] if part)
            if not address:
                address = clean_text(str(tags.get("addr:full") or "")) or "Address not provided"
            lead = BusinessLead(
                    item_id=key,
                    region_id=region.id,
                    name=name,
                    category=_business_category(tags),
                    address=address,
                    website=website,
                    phone=phone,
                    email=email,
                    lat=lat_value,
                    lon=lon_value,
                    source_name="OpenStreetMap / Overpass",
                    source_url="https://overpass-api.de/api/interpreter",
                    tags={str(k): clean_text(str(v)) for k, v in tags.items() if str(v).strip()},
                    notes=["Public organization-level contact point from open map data."],
                )
            lead.lead_score = _business_lead_score(lead)
            output.append(lead)
        output.sort(key=_business_sort_key)
        return output[:80]

    async def _collect_contacts(self, client: httpx.AsyncClient) -> list[PublicContact]:
        contacts: list[PublicContact] = []
        contacts.extend(await self._collect_austin_contacts(client))
        contacts.extend(await self._collect_houston_contacts(client))
        contacts.extend(await self._collect_gunnison_contacts(client))
        deduped: dict[str, PublicContact] = {}
        for item in contacts:
            item.contact_score = _contact_score(item)
            deduped[item.item_id] = item
        return sorted(deduped.values(), key=lambda item: (item.region_id, -item.contact_score, item.organization.lower(), item.name.lower()))[:120]

    async def _collect_austin_contacts(self, client: httpx.AsyncClient) -> list[PublicContact]:
        contacts: list[PublicContact] = []

        async def _fetch_contacts():
            response = await client.get(AUSTIN_CONTACTS_URL)
            response.raise_for_status()
            return response

        response = await self._retry_fetch("austin_economic_development_contacts", _fetch_contacts)
        plain = _html_to_text(response.text) if response is not None else ""
        if plain:
            phone = _extract_first_phone(plain)
            contacts.append(
                PublicContact(
                    item_id=_stable_id("austin_tx", "Austin Economic Development"),
                    region_id="austin_tx",
                    name="Austin Economic Development",
                    title="Department contact",
                    organization="Austin Economic Development",
                    phone=phone,
                    website=AUSTIN_CONTACTS_URL,
                    source_name="Austin Economic Development",
                    source_url=AUSTIN_CONTACTS_URL,
                    notes=["Public department page for Austin small business and economic development programs."],
                )
            )
        async def _fetch_rally():
            response = await client.get(AUSTIN_RALLY_URL)
            response.raise_for_status()
            return response

        rally_response = await self._retry_fetch("austin_economic_development_news", _fetch_rally)
        if rally_response is not None:
            text = _html_to_text(rally_response.text)
            for name, title in [
                ("Anthony Segura", "Deputy Director, Austin Economic Development"),
                ("Changwon Keum", "CEO, 3billion"),
            ]:
                if name not in text:
                    continue
                contacts.append(
                    PublicContact(
                        item_id=_stable_id("austin_tx", name, title),
                        region_id="austin_tx",
                        name=name,
                        title=title,
                        organization="Austin Economic Development" if "Austin Economic Development" in title else "3billion",
                        address="13620 Ranch to Market Road 620, Austin, TX" if name == "Changwon Keum" else None,
                        website=AUSTIN_RALLY_URL,
                        source_name="Austin Economic Development News",
                        source_url=AUSTIN_RALLY_URL,
                        contact_type="public_news_figure",
                        notes=["Named in an official Austin Economic Development release."],
                    )
                )
        return contacts

    async def _collect_houston_contacts(self, client: httpx.AsyncClient) -> list[PublicContact]:
        contacts: list[PublicContact] = []

        async def _fetch_ecodev():
            response = await client.get(HOUSTON_ECODEV_CONTACT_URL)
            response.raise_for_status()
            return response

        eco_response = await self._retry_fetch("houston_economic_development", _fetch_ecodev)
        if eco_response is not None:
            plain = _html_to_text(eco_response.text)
            if "Mayor's Office of Economic Development" in plain:
                contacts.append(
                    PublicContact(
                        item_id=_stable_id("houston_tx", "Mayor's Office of Economic Development"),
                        region_id="houston_tx",
                        name="Mayor's Office of Economic Development",
                        title="Office contact",
                        organization="City of Houston",
                        address="City Hall, 901 Bagby, Houston, TX 77002",
                        website=HOUSTON_ECODEV_CONTACT_URL,
                        source_name="City of Houston Economic Development",
                        source_url=HOUSTON_ECODEV_CONTACT_URL,
                        notes=["Public office contact page for Houston economic development."],
                    )
                )

        async def _fetch_innovation():
            response = await client.get(HOUSTON_INNOVATION_URL)
            response.raise_for_status()
            return response

        inno_response = await self._retry_fetch("houston_innovation", _fetch_innovation)
        if inno_response is not None:
            plain = _html_to_text(inno_response.text)
            if "Jesse Bounds" in plain:
                contacts.append(
                    PublicContact(
                        item_id=_stable_id("houston_tx", "Jesse Bounds"),
                        region_id="houston_tx",
                        name="Jesse Bounds",
                        title="Director of Innovation",
                        organization="Mayor's Office of Innovation & Performance",
                        website=HOUSTON_INNOVATION_URL,
                        email=_extract_first_email(inno_response.text),
                        phone=_extract_first_phone(plain),
                        source_name="Mayor's Office of Innovation & Performance",
                        source_url=HOUSTON_INNOVATION_URL,
                        notes=["Public-facing innovation office leadership contact."],
                    )
                )
        return contacts

    async def _collect_gunnison_contacts(self, client: httpx.AsyncClient) -> list[PublicContact]:
        contacts: list[PublicContact] = []
        for source_name, url, org_name in [
            ("Gunnison County Community & Economic Development", GUNNISON_COMMUNITY_DEV_URL, "Gunnison County Community & Economic Development"),
            ("Gunnison County Permit Database", GUNNISON_PERMIT_DATABASE_URL, "Gunnison County Planning, Building, and Environmental Health"),
            ("Town of Crested Butte Permitting", CRESTED_BUTTE_PERMITTING_URL, "Town of Crested Butte Community Development"),
        ]:

            async def _fetch_gunnison(url=url):
                response = await client.get(url)
                response.raise_for_status()
                return response

            response = await self._retry_fetch(f"gunnison_valley_contacts:{source_name}", _fetch_gunnison)
            if response is None:
                continue
            plain = _html_to_text(response.text)
            email = _extract_first_email(response.text)
            phone = _extract_first_phone(plain)
            snippets = [
                ("Cathie Pagano", "Assistant County Manager for Community & Economic Development"),
                ("Eric Treadwell", "Building permit contact"),
            ]
            matched_named = False
            for name, title in snippets:
                if name not in plain:
                    continue
                matched_named = True
                contacts.append(
                    PublicContact(
                        item_id=_stable_id("gunnison_valley_co", name, org_name),
                        region_id="gunnison_valley_co",
                        name=name,
                        title=title,
                        organization=org_name,
                        phone=phone,
                        email=email,
                        website=url,
                        source_name=source_name,
                        source_url=url,
                        notes=["Named on an official Gunnison Valley public page."],
                    )
                )
            if not matched_named and (email or phone or org_name in plain):
                contacts.append(
                    PublicContact(
                        item_id=_stable_id("gunnison_valley_co", org_name, url),
                        region_id="gunnison_valley_co",
                        name=org_name,
                        title="Office contact",
                        organization=org_name,
                        phone=phone,
                        email=email,
                        website=url,
                        source_name=source_name,
                        source_url=url,
                        notes=["Public office contact collected from an official Gunnison Valley page."],
                    )
                )
        return contacts

    def source_catalog(self) -> list[IntelSource]:
        return SOURCES

    def region_catalog(self) -> list[RegionProfile]:
        return REGIONS

    def ethics_catalog(self) -> list[EthicsRule]:
        return ETHICS_RULES

    def _backfill_news(
        self,
        current: list[NewsSignal],
        previous: dict[str, Any],
    ) -> tuple[list[NewsSignal], list[str]]:
        previous_items = previous.get("news", []) if isinstance(previous, dict) else []
        current_regions = {item.region_id for item in current}
        applied: list[str] = []
        output = list(current)
        for region in REGIONS:
            if region.id in current_regions:
                continue
            backfill = [
                NewsSignal.model_validate(item)
                for item in previous_items
                if isinstance(item, dict) and item.get("region_id") == region.id
            ]
            if not backfill:
                continue
            for item in backfill:
                item.notes.append("Backfilled from previous successful snapshot.")
            output.extend(backfill)
            applied.append(region.name)
        output.sort(key=lambda item: item.published_at, reverse=True)
        return output[:120], applied

    def _backfill_permits(
        self,
        current: list[PermitSignal],
        previous: dict[str, Any],
    ) -> tuple[list[PermitSignal], list[str]]:
        previous_items = previous.get("permits", []) if isinstance(previous, dict) else []
        current_regions = {item.region_id for item in current}
        applied: list[str] = []
        output = list(current)
        for region in REGIONS:
            if region.id in current_regions:
                continue
            backfill = [
                PermitSignal.model_validate(item)
                for item in previous_items
                if isinstance(item, dict) and item.get("region_id") == region.id
            ]
            if not backfill:
                continue
            for item in backfill:
                item.notes.append("Backfilled from previous successful snapshot.")
            output.extend(backfill)
            applied.append(region.name)
        output.sort(key=lambda item: item.status_date, reverse=True)
        return output[:120], applied

    def _backfill_businesses(
        self,
        current: list[BusinessLead],
        previous: dict[str, Any],
    ) -> tuple[list[BusinessLead], list[str]]:
        previous_items = previous.get("businesses", []) if isinstance(previous, dict) else []
        current_regions = {item.region_id for item in current}
        applied: list[str] = []
        output = list(current)
        for region in REGIONS:
            if region.id in current_regions:
                continue
            backfill = [
                BusinessLead.model_validate(item)
                for item in previous_items
                if isinstance(item, dict) and item.get("region_id") == region.id
            ]
            if not backfill:
                continue
            for item in backfill:
                item.notes.append("Backfilled from previous successful snapshot.")
            output.extend(backfill)
            applied.append(region.name)
        output.sort(key=lambda item: (item.region_id, item.name.lower()))
        return output[:240], applied

    def _backfill_contacts(
        self,
        current: list[PublicContact],
        previous: dict[str, Any],
    ) -> tuple[list[PublicContact], list[str]]:
        previous_items = previous.get("contacts", []) if isinstance(previous, dict) else []
        current_regions = {item.region_id for item in current}
        applied: list[str] = []
        output = list(current)
        for region in REGIONS:
            if region.id in current_regions:
                continue
            backfill = [
                PublicContact.model_validate(item)
                for item in previous_items
                if isinstance(item, dict) and item.get("region_id") == region.id
            ]
            if not backfill:
                continue
            for item in backfill:
                item.notes.append("Backfilled from previous successful snapshot.")
            output.extend(backfill)
            applied.append(region.name)
        output.sort(key=lambda item: (item.region_id, item.organization.lower(), item.name.lower()))
        return output[:120], applied
