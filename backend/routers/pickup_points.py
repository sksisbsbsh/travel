"""routers/pickup_points.py — Master Data referensi (INV-REF-02): TITIK JEMPUT + DESTINASI (ops).

`bookings.origin` & destinasi (booking/lead/penawaran) bukan teks bebas — nilainya wajib dari
master di file ini / koleksi `destinations`. Halaman kelola: /app/masterdata (section `masterdata`,
owner + ops_admin). RENAME di sini CASCADE ke dokumen pemakai (booking/lead/penawaran) supaya
nama kanonik tidak pernah bercabang; NONAKTIF menyembunyikan dari selector & menolak pemakaian
BARU tanpa merusak data lama.
"""
from fastapi import APIRouter, Depends, HTTPException

from core_utils import new_id, now_iso, safe_doc
from db import get_db
from dependencies import require_section
from schemas import MasterDestinationUpdate, PickupPointCreate, PickupPointUpdate
from services.audit import record

router = APIRouter(prefix="/api", tags=["master-data"])
BOOKINGS = require_section("bookings")
MASTER = require_section("masterdata")


def _clean(name: str) -> str:
    return str(name or "").strip()


async def _name_taken(coll, name: str, exclude_id: str = "") -> bool:
    async for d in coll.find({"deleted": {"$ne": True}}, {"_id": 0, "id": 1, "name": 1}):
        if d.get("id") != exclude_id and _clean(d.get("name")).lower() == name.lower():
            return True
    return False


@router.get("/pickup-points")
async def list_pickup_points(user=Depends(BOOKINGS)):
    """Utk selector form (hanya yang AKTIF). Kelola lengkap: GET /master/pickup-points."""
    rows = await get_db().pickup_points.find(
        {"deleted": {"$ne": True}, "active": {"$ne": False}},
        {"_id": 0}).sort("name", 1).to_list(500)
    return safe_doc(rows)


@router.post("/pickup-points")
async def create_pickup_point(body: PickupPointCreate, user=Depends(BOOKINGS)):
    """Quick-add master. Idempotent: nama yang sudah ada (case-insensitive) dikembalikan, bukan duplikat."""
    db = get_db()
    name = body.name.strip()
    async for p in db.pickup_points.find({"deleted": {"$ne": True}}, {"_id": 0}):
        if _clean(p.get("name")).lower() == name.lower():
            if p.get("active") is False:
                await db.pickup_points.update_one({"id": p["id"]}, {"$set": {"active": True}})
                p["active"] = True
            return safe_doc(p)
    doc = {"id": new_id("pkp"), "name": name, "active": True, "created_at": now_iso()}
    await db.pickup_points.insert_one(dict(doc))
    await record(db, actor=user, action="create", entity_type="pickup_point",
                 entity_id=doc["id"], summary=f"Titik jemput baru: {name}")
    return doc


@router.get("/master/pickup-points")
async def master_pickup_points(user=Depends(MASTER)):
    """Kelola master: semua baris (termasuk nonaktif) + jumlah pemakaian di booking."""
    db = get_db()
    rows = await db.pickup_points.find({"deleted": {"$ne": True}}, {"_id": 0}).sort("name", 1).to_list(500)
    out = []
    for r in rows:
        used = await db.bookings.count_documents({"origin": r.get("name")})
        out.append({**r, "active": r.get("active") is not False, "used_by_bookings": used})
    return safe_doc(out)


@router.patch("/master/pickup-points/{point_id}")
async def update_pickup_point(point_id: str, body: PickupPointUpdate, user=Depends(MASTER)):
    """Rename (CASCADE ke bookings.origin) dan/atau aktif/nonaktif."""
    db = get_db()
    point = await db.pickup_points.find_one({"id": point_id, "deleted": {"$ne": True}}, {"_id": 0})
    if not point:
        raise HTTPException(status_code=404, detail="Titik jemput tidak ditemukan")
    updates, cascaded = {}, 0
    new_name = _clean(body.name) if body.name is not None else ""
    old_name = _clean(point.get("name"))
    if new_name and new_name != old_name:
        if await _name_taken(db.pickup_points, new_name, exclude_id=point_id):
            raise HTTPException(status_code=400, detail=f"Nama '{new_name}' sudah dipakai baris master lain")
        updates["name"] = new_name
        res = await db.bookings.update_many({"origin": old_name}, {"$set": {"origin": new_name}})
        cascaded = res.modified_count
    if body.active is not None:
        updates["active"] = bool(body.active)
    if not updates:
        return {**point, "cascaded_bookings": 0}
    await db.pickup_points.update_one({"id": point_id}, {"$set": updates})
    await record(db, actor=user, action="update", entity_type="pickup_point", entity_id=point_id,
                 summary=f"Master titik jemput: {old_name} → {updates.get('name', old_name)}"
                         f"{' (nonaktif)' if updates.get('active') is False else ''}"
                         f" · cascade {cascaded} booking")
    return {**point, **updates, "cascaded_bookings": cascaded}


@router.get("/master/destinations")
async def master_destinations(user=Depends(MASTER)):
    """Kelola master destinasi dari sisi OPS: nama, status ops (aktif utk selector), pemakaian."""
    db = get_db()
    rows = await db.destinations.find(
        {"deleted": {"$ne": True}},
        {"_id": 0, "id": 1, "name": 1, "slug": 1, "status": 1, "source": 1, "ops_active": 1},
    ).sort("name", 1).to_list(500)
    out = []
    for r in rows:
        nm = r.get("name")
        used_b = await db.bookings.count_documents({"destination": nm})
        used_l = await db.leads.count_documents({"destination": nm})
        out.append({**r, "ops_active": r.get("ops_active") is not False,
                    "used_by_bookings": used_b, "used_by_leads": used_l})
    return safe_doc(out)


@router.patch("/master/destinations/{dest_id}")
async def update_master_destination(dest_id: str, body: MasterDestinationUpdate, user=Depends(MASTER)):
    """Rename destinasi (CASCADE ke bookings/leads/quotations yang memakai nama lama) +
    toggle `ops_active` (nonaktif = hilang dari selector & ditolak utk pemakaian baru;
    halaman web publik TIDAK berubah — slug tetap)."""
    db = get_db()
    dest = await db.destinations.find_one({"id": dest_id, "deleted": {"$ne": True}}, {"_id": 0})
    if not dest:
        raise HTTPException(status_code=404, detail="Destinasi tidak ditemukan")
    updates, cascade = {}, {"bookings": 0, "leads": 0, "quotations": 0}
    new_name = _clean(body.name) if body.name is not None else ""
    old_name = _clean(dest.get("name"))
    if new_name and new_name != old_name:
        if await _name_taken(db.destinations, new_name, exclude_id=dest_id):
            raise HTTPException(status_code=400, detail=f"Nama '{new_name}' sudah dipakai destinasi lain")
        updates["name"] = new_name
        for coll in ("bookings", "leads", "quotations"):
            res = await db[coll].update_many({"destination": old_name},
                                             {"$set": {"destination": new_name}})
            cascade[coll] = res.modified_count
    if body.ops_active is not None:
        updates["ops_active"] = bool(body.ops_active)
    if not updates:
        return {**dest, "cascade": cascade}
    updates["updated_at"] = now_iso()
    await db.destinations.update_one({"id": dest_id}, {"$set": updates})
    await record(db, actor=user, action="update", entity_type="destination", entity_id=dest_id,
                 summary=f"Master destinasi: {old_name} → {updates.get('name', old_name)}"
                         f"{' (ops nonaktif)' if updates.get('ops_active') is False else ''}"
                         f" · cascade {sum(cascade.values())} dokumen")
    return {**dest, **updates, "cascade": cascade}
