import { useCallback, useEffect, useState } from "react";
import { MapPin, Landmark, Loader2, Pencil, Check, X, Power } from "lucide-react";
import { toast } from "sonner";
import apiClient from "@/services/apiClient";
import { Input } from "@/components/ui/input";
import { LoadingState, ErrorState } from "@/components/shared/DataStates";

// Master Data referensi (INV-REF-02): SATU tempat kelola titik jemput & destinasi (sisi ops).
// Rename di sini CASCADE ke booking/lead/penawaran; nonaktif = hilang dari selector form.

function Row({ row, kind, busy, onRename, onToggle }) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(row.name || "");
  const active = kind === "pickup" ? row.active : row.ops_active;
  const usage = kind === "pickup"
    ? `${row.used_by_bookings} booking`
    : `${row.used_by_bookings} booking · ${row.used_by_leads} lead`;
  const save = () => { if (name.trim().length >= 2 && name.trim() !== row.name) onRename(row, name.trim()); setEditing(false); };
  return (
    <div className={`flex flex-wrap items-center gap-2 border-b border-[#F2F2F5] px-3 py-2.5 last:border-0 ${active ? "" : "opacity-55"}`}
      data-testid={`md-row-${row.id}`}>
      <div className="min-w-[200px] flex-1">
        {editing ? (
          <div className="flex items-center gap-1.5">
            <Input className="!h-8 max-w-[260px] text-[13px]" value={name} onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && save()} autoFocus data-testid={`md-rename-input-${row.id}`} />
            <button className="icon-button !h-8 !w-8" onClick={save} data-testid={`md-rename-save-${row.id}`}><Check size={14} /></button>
            <button className="icon-button !h-8 !w-8" onClick={() => { setEditing(false); setName(row.name); }}><X size={14} /></button>
          </div>
        ) : (
          <>
            <span className="text-[13.5px] font-semibold text-[#1C1C1E]" data-testid={`md-name-${row.id}`}>{row.name}</span>
            {kind === "dest" && row.status === "draft" ? (
              <span className="ml-2 rounded-full bg-[#F2F2F5] px-2 py-0.5 text-[10.5px] font-semibold text-[#6B6B73]">ops / draft</span>
            ) : null}
            <span className="block text-[11px] text-[#8E8E93]">Dipakai: {usage}</span>
          </>
        )}
      </div>
      {!active ? <span className="rounded-full bg-[#FF3B30]/10 px-2 py-0.5 text-[11px] font-semibold text-[#A8221A]">Nonaktif</span> : null}
      <button className="secondary-button !h-8 !px-2.5 !text-[11.5px]" disabled={busy || editing}
        onClick={() => setEditing(true)} data-testid={`md-rename-${row.id}`}><Pencil size={12} /> Ganti Nama</button>
      <button className="secondary-button !h-8 !px-2.5 !text-[11.5px]" disabled={busy}
        onClick={() => onToggle(row, !active)} data-testid={`md-toggle-${row.id}`}>
        <Power size={12} /> {active ? "Nonaktifkan" : "Aktifkan"}
      </button>
    </div>
  );
}

function Panel({ icon: Icon, title, desc, kind, rows, busy, onRename, onToggle, testId }) {
  return (
    <section className="rounded-[14px] border border-[#EFF0F2] bg-white shadow-sm" data-testid={testId}>
      <div className="border-b border-[#EFF0F2] px-4 py-3">
        <h2 className="flex items-center gap-2 text-[14px] font-bold text-[#1C1C1E]" style={{ fontFamily: "Outfit, sans-serif" }}>
          <Icon size={15} className="text-[#007AFF]" /> {title}
          <span className="rounded-full bg-[#EAF2FF] px-2 py-0.5 text-[11px] font-semibold text-[#0058CC]">{rows.length}</span>
        </h2>
        <p className="mt-0.5 text-[12px] text-[#6B6B73]">{desc}</p>
      </div>
      <div>
        {rows.map((r) => <Row key={r.id} row={r} kind={kind} busy={busy} onRename={onRename} onToggle={onToggle} />)}
        {rows.length === 0 ? <p className="px-4 py-5 text-[12.5px] text-[#8E8E93]">Belum ada data.</p> : null}
      </div>
    </section>
  );
}

export default function MasterData() {
  const [pickups, setPickups] = useState([]);
  const [dests, setDests] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const [p, d] = await Promise.all([
        apiClient.get("/master/pickup-points"),
        apiClient.get("/master/destinations"),
      ]);
      setPickups(Array.isArray(p.data) ? p.data : []);
      setDests(Array.isArray(d.data) ? d.data : []);
    } catch (e) {
      setError(e?.response?.data?.detail || "Gagal memuat master data");
    } finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const act = async (fn, okMsg) => {
    setBusy(true);
    try { const extra = await fn(); toast.success(okMsg + (extra || "")); await load(); }
    catch (e) { toast.error(e?.response?.data?.detail || "Gagal menyimpan"); }
    finally { setBusy(false); }
  };
  const renamePickup = (row, name) => act(async () => {
    const { data } = await apiClient.patch(`/master/pickup-points/${row.id}`, { name });
    return data.cascaded_bookings ? ` · ${data.cascaded_bookings} booking ikut diperbarui` : "";
  }, `Titik jemput → "${name}"`);
  const togglePickup = (row, active) => act(async () => {
    await apiClient.patch(`/master/pickup-points/${row.id}`, { active });
  }, active ? `"${row.name}" diaktifkan` : `"${row.name}" dinonaktifkan`);
  const renameDest = (row, name) => act(async () => {
    const { data } = await apiClient.patch(`/master/destinations/${row.id}`, { name });
    const n = Object.values(data.cascade || {}).reduce((a, b) => a + b, 0);
    return n ? ` · ${n} dokumen ikut diperbarui` : "";
  }, `Destinasi → "${name}"`);
  const toggleDest = (row, ops_active) => act(async () => {
    await apiClient.patch(`/master/destinations/${row.id}`, { ops_active });
  }, ops_active ? `"${row.name}" diaktifkan` : `"${row.name}" dinonaktifkan`);

  if (loading) return <LoadingState testId="masterdata-loading" />;
  if (error) return <ErrorState message={error} onRetry={load} />;

  return (
    <div className="space-y-5" data-testid="masterdata-page">
      <p className="text-[13px] text-[#6B6B73]">
        Satu pintu referensi form (SSOT). <b>Ganti nama</b> otomatis memperbarui booking/lead/penawaran
        yang memakai nama lama; <b>Nonaktifkan</b> menyembunyikan dari pilihan form tanpa mengubah data lama.
      </p>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Panel icon={MapPin} title="Titik Jemput" kind="pickup" rows={pickups} busy={busy}
          desc="Dipakai field 'Titik Jemput' pada booking. Tambah cepat tersedia langsung di form booking."
          onRename={renamePickup} onToggle={togglePickup} testId="md-pickup-panel" />
        <Panel icon={Landmark} title="Destinasi (sisi ops)" kind="dest" rows={dests} busy={busy}
          desc="Dipakai booking, lead CRM, penawaran & form web. Konten halaman web dikelola di Konten Web; nonaktif di sini tidak menurunkan halaman publik."
          onRename={renameDest} onToggle={toggleDest} testId="md-dest-panel" />
      </div>
    </div>
  );
}
