#!/usr/bin/env python3
"""INV-REF-02 — Relasi SSOT: destinasi booking ERP WAJIB dari master `destinations`.

Kelas bug yang ditutup (RC-E, keluhan user 2026-08-29, BUG-0135): field yang seharusnya
RELASI antar-collection diisi lewat input teks bebas. Untuk `bookings.destination` akibatnya
nyata: "Bromo" vs "Gunung Bromo" vs "bromo " dihitung sebagai 3 destinasi berbeda di laporan,
dan paket/penawaran (yang sudah relasional via `destination_id`) tidak pernah bisa dicocokkan
dengan booking.

Yang dikunci:
  STATIK : (1) `services/refs.py` punya `destination_or_400` (validator satu pintu),
           (2) `routers/bookings.py` memanggilnya di jalur BUAT, ROMBONGAN, dan UBAH,
           (3) endpoint pilihan `GET /bookings/destination-options` tersedia utk FE.
  RUNTIME: POST /bookings dgn destinasi di luar master → WAJIB 400 dengan alasan destinasi
           (bukan alasan lain = hijau-palsu). Bila server malah MENERIMA (2xx), dokumen uji
           dibersihkan via purge_guard_bookings() dan dilaporkan sebagai pelanggaran.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))
from _common import BACKEND, Guard, purge_guard_bookings  # noqa: E402

BASE = "http://localhost:8001/api"
REFS = BACKEND / "services" / "refs.py"
BOOKINGS = BACKEND / "routers" / "bookings.py"


def req(method, path, token=None, body=None, timeout=30):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return -1, str(e)


def jreq(method, path, token=None, body=None):
    st, txt = req(method, path, token, body)
    try:
        return st, json.loads(txt)
    except Exception:  # noqa: BLE001
        return st, {}


def login():
    st, data = jreq("POST", "/auth/login",
                    body={"email": "owner@demo.local", "password": "demo12345"})
    return data.get("token") if st == 200 else None


def read(p):
    return p.read_text(encoding="utf-8", errors="ignore") if p.exists() else ""


def static_checks(g: Guard):
    refs = read(REFS)
    g.bump()
    if "async def destination_or_400" not in refs:
        g.add("services/refs.py: validator `destination_or_400` HILANG — destinasi kembali teks bebas.")
    src = read(BOOKINGS)
    g.bump()
    if src.count("destination_or_400(") < 3:
        g.add("routers/bookings.py: `destination_or_400` harus dipanggil di 3 jalur "
              "(create, group, update) — ada jalur tulis destinasi yang lolos validasi master.")
    g.bump()
    if "/bookings/destination-options" not in src:
        g.add("routers/bookings.py: endpoint `GET /bookings/destination-options` hilang — "
              "FE tak punya sumber pilihan, ops akan kembali mengetik bebas.")


def runtime_checks(g: Guard, tok: str):
    _, cust = jreq("GET", "/customers?limit=1", tok)
    _, veh = jreq("GET", "/vehicles?limit=1", tok)
    if not (isinstance(cust, list) and cust and isinstance(veh, list) and veh):
        g.bump()
        g.add("Runtime: tidak bisa mengambil customer/vehicle demo untuk probe (seed rusak?).")
        return
    start = (datetime.now(timezone.utc) + timedelta(days=400)).replace(microsecond=0)
    end = start + timedelta(days=1)
    body = {"customer_id": cust[0]["id"], "vehicle_id": veh[0]["id"],
            "origin": "Bandung", "destination": "NgawurLand Penjaga INV-REF-02",
            "start_datetime": start.isoformat(), "end_datetime": end.isoformat(),
            "base_price": 1000000}
    st, data = jreq("POST", "/bookings", tok, body)
    g.bump()
    if st == 400:
        detail = str((data or {}).get("detail") or "").lower()
        if "destinasi" not in detail and "master" not in detail:
            g.add(f"Runtime: destinasi ngawur ditolak tetapi karena alasan LAIN ('{detail[:80]}') "
                  f"— hijau-palsu; validasi master tidak terbukti bekerja.")
    elif 200 <= st < 300:
        g.add("Runtime: POST /bookings MENERIMA destinasi di luar master (INV-REF-02 dilanggar) "
              "— dokumen uji dibersihkan.")
    else:
        g.add(f"Runtime: respons tak terduga HTTP {st} untuk destinasi ngawur (harus 400).")
    g.bump()
    st2, opts = jreq("GET", "/bookings/destination-options", tok)
    if st2 != 200 or not isinstance(opts, list) or not opts:
        g.add(f"Runtime: GET /bookings/destination-options gagal (HTTP {st2}) atau kosong — "
              f"selector FE tak punya pilihan.")


def main() -> int:
    g = Guard("INV-REF-02", "Destinasi booking = relasi ke master destinations (bukan teks bebas)")
    static_checks(g)
    tok = login()
    if not tok:
        g.bump()
        g.add("Runtime: gagal login akun demo — probe runtime tidak berjalan (bukan skip senyap).")
    else:
        try:
            runtime_checks(g, tok)
        finally:
            purge_guard_bookings()
    return g.finish()


if __name__ == "__main__":
    sys.exit(main())
