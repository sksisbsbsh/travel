"""routers/pickup_points.py — Master TITIK JEMPUT (INV-REF-02 batch 2).

`bookings.origin` bukan lagi teks bebas: nilai wajib dari master ini
(validator `services.refs.origin_or_400`). Quick-add dari form booking menulis ke master
(satu pintu), bukan menyelundupkan teks bebas ke booking.
"""
from fastapi import APIRouter, Depends

from core_utils import new_id, now_iso, safe_doc
from db import get_db
from dependencies import require_section
from schemas import PickupPointCreate
from services.audit import record

router = APIRouter(prefix="/api", tags=["pickup-points"])
BOOKINGS = require_section("bookings")


@router.get("/pickup-points")
async def list_pickup_points(user=Depends(BOOKINGS)):
    rows = await get_db().pickup_points.find(
        {"deleted": {"$ne": True}}, {"_id": 0}).sort("name", 1).to_list(500)
    return safe_doc(rows)


@router.post("/pickup-points")
async def create_pickup_point(body: PickupPointCreate, user=Depends(BOOKINGS)):
    """Quick-add master. Idempotent: nama yang sudah ada (case-insensitive) dikembalikan, bukan duplikat."""
    db = get_db()
    name = body.name.strip()
    async for p in db.pickup_points.find({"deleted": {"$ne": True}}, {"_id": 0}):
        if str(p.get("name", "")).strip().lower() == name.lower():
            return safe_doc(p)
    doc = {"id": new_id("pkp"), "name": name, "created_at": now_iso()}
    await db.pickup_points.insert_one(dict(doc))
    await record(db, actor=user, action="create", entity_type="pickup_point",
                 entity_id=doc["id"], summary=f"Titik jemput baru: {name}")
    return doc
