"""Read-through identity lookup over the existing authoritative SVI county source."""

import asyncio
import hashlib
import json
import time
from datetime import UTC, datetime
from typing import Literal

import httpx
from pydantic import ValidationError

from atlas_lyme_mcp.tools.geography_contracts import (
    Geography,
    GeographyArguments,
    GeographyResult,
    GeographyResults,
    Reference,
)

SOURCE = (
    "https://services3.arcgis.com/ZvidGQkLaDJxRSJ2/arcgis/rest/services/"
    "CDC_ATSDR_Social_Vulnerability_Index_2022_USA/FeatureServer/1"
)
VERSION = "CDC_ATSDR_SVI_2022_USA:county"
MAX_SOURCE_BYTES = 1024 * 1024


def normalized(value: str) -> str:
    return " ".join(value.split()).casefold()


def county_key(value: str) -> str:
    value = normalized(value)
    # Only the source's County suffix is optional. City/borough/parish identities
    # are distinct and must use their full canonical names.
    return value.removesuffix(" county")


class ReferenceUnavailable(Exception):
    pass


class GeographyResolver:
    """Bounded publisher reader, with a one-hour memory cache and no stale fallback."""

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.transport = transport
        self.lock = asyncio.Lock()
        self.cached: tuple[list[Geography], Reference] | None = None
        self.expires = 0.0
        self.retry_at = 0.0

    async def reference(self) -> tuple[list[Geography], Reference]:
        async with self.lock:
            if self.cached is not None and time.monotonic() < self.expires:
                return self.cached
            if time.monotonic() < self.retry_at:
                raise ReferenceUnavailable
            try:
                async with asyncio.timeout(12):
                    value = await self.fetch()
            except (httpx.HTTPError, TimeoutError, ValueError, KeyError, TypeError):
                self.retry_at = time.monotonic() + 30
                raise ReferenceUnavailable from None
            self.cached = value
            self.expires = time.monotonic() + 3600
            return value

    async def fetch(self) -> tuple[list[Geography], Reference]:
        rows: list[Geography] = []
        total = 0
        async with httpx.AsyncClient(
            transport=self.transport, timeout=5, follow_redirects=False
        ) as client:
            # The existing source definition pages at 2,000. Two pages cover
            # its 3,144-county scope; incomplete or changed scope fails closed.
            for offset in (0, 2000):
                async with client.stream(
                    "GET",
                    SOURCE + "/query",
                    params={
                        "where": "1=1",
                        "outFields": "STCNTY,STATE,ST_ABBR,COUNTY",
                        "returnGeometry": "false",
                        "orderByFields": "STCNTY",
                        "resultOffset": offset,
                        "resultRecordCount": 2000,
                        "f": "json",
                    },
                ) as response:
                    response.raise_for_status()
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > MAX_SOURCE_BYTES:
                            raise ValueError("Reference too large")
                        body.extend(chunk)
                page = json.loads(body)
                features = page["features"]
                if not isinstance(features, list) or len(features) > 2000:
                    raise ValueError("Invalid reference page")
                for feature in features:
                    attributes = feature["attributes"]
                    fips = attributes["STCNTY"]
                    rows.append(
                        Geography(
                            county_fips=fips,
                            county_name=attributes["COUNTY"],
                            state_name=attributes["STATE"],
                            state_abbreviation=attributes["ST_ABBR"],
                            state_fips=fips[:2],
                        )
                    )
                if offset == 0 and (
                    len(features) != 2000 or page.get("exceededTransferLimit") is not True
                ):
                    raise ValueError("Incomplete reference")
                if offset == 2000 and page.get("exceededTransferLimit", False):
                    raise ValueError("Unbounded reference")
        if len(rows) != 3144 or len({row.county_fips for row in rows}) != 3144:
            raise ValueError("Changed or incomplete reference scope")
        states: dict[str, tuple[str, str]] = {}
        for row in rows:
            identity = (row.state_name, row.state_abbreviation)
            if row.state_fips in states and states[row.state_fips] != identity:
                raise ValueError("Inconsistent state identity")
            states[row.state_fips] = identity
        if len(states) != 51:
            raise ValueError("Changed state scope")
        rows.sort(key=lambda row: row.county_fips)
        canonical = json.dumps([row.model_dump() for row in rows], sort_keys=True).encode()
        return rows, Reference(
            source=SOURCE,
            version=VERSION,
            sha256=hashlib.sha256(canonical).hexdigest(),
            retrieved_at=datetime.now(UTC).isoformat(),
        )

    async def resolve(self, request: GeographyArguments) -> GeographyResults:
        try:
            rows, reference = await self.reference()
        except (ReferenceUnavailable, ValidationError):
            return GeographyResults(
                results=[
                    GeographyResult(
                        input_index=index,
                        requested=item,
                        status="unavailable",
                        reason="REFERENCE_UNAVAILABLE",
                    )
                    for index, item in enumerate(request.geographies)
                ],
                reference=None,
            )
        results = []
        for index, item in enumerate(request.geographies):
            if item.county_fips is not None:
                matches = [row for row in rows if row.county_fips == item.county_fips]
            else:
                assert item.county is not None and item.state is not None
                matches = [
                    row
                    for row in rows
                    if normalized(item.state)
                    in {normalized(row.state_name), normalized(row.state_abbreviation)}
                    and county_key(item.county) == county_key(row.county_name)
                ]
            status: Literal["resolved", "ambiguous", "not_found"] = (
                "resolved" if len(matches) == 1 else "ambiguous" if matches else "not_found"
            )
            results.append(
                GeographyResult(
                    input_index=index,
                    requested=item,
                    status=status,
                    geography=matches[0] if status == "resolved" else None,
                    candidates=matches[:4] if status == "ambiguous" else [],
                    reason=None
                    if status == "resolved"
                    else "AMBIGUOUS"
                    if matches
                    else "NOT_FOUND",
                )
            )
        return GeographyResults(results=results, reference=reference)
