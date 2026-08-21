import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import { useApp, useLink } from "../state/app";
import type { Bucket, CustomerRow } from "../api/types";
import { BUCKET_FA, BucketPill, Empty, RFMCell, Skeleton } from "../components/bits";

type SortKey = "signals" | "open_loops" | "customer_id" | "rfm_cell";

/** The whole book arrives in one call — 526 rows, no server paging (API.md §157). */
export default function CustomersPage() {
  const { asOf } = useApp();
  const link = useLink();
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();

  const bucket = (params.get("bucket") as Bucket | null) ?? "";
  const [segment, setSegment] = useState("");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<SortKey>("signals");
  const [desc, setDesc] = useState(true);

  const list = useQuery({
    queryKey: ["customers", asOf],
    queryFn: () => api.customers(asOf, { limit: 1000 }),
  });

  const segments = useMemo(() => {
    const s = new Set<string>();
    list.data?.customers.forEach((c) => c.segment && s.add(c.segment));
    return [...s].sort();
  }, [list.data]);

  const rows = useMemo(() => {
    let r = list.data?.customers ?? [];
    if (bucket) r = r.filter((c) => c.bucket === bucket);
    if (segment) r = r.filter((c) => c.segment === segment);
    if (q.trim()) {
      const needle = q.trim().toLowerCase();
      r = r.filter(
        (c) =>
          c.customer_id.toLowerCase().includes(needle) ||
          (c.rfm_segment_fa ?? "").includes(needle) ||
          (c.rfm_cell ?? "").includes(needle),
      );
    }
    const dir = desc ? -1 : 1;
    return [...r].sort((a, b) => {
      const av = a[sort] ?? 0;
      const bv = b[sort] ?? 0;
      if (typeof av === "number" && typeof bv === "number") return (av - bv) * dir;
      return String(av).localeCompare(String(bv)) * dir;
    });
  }, [list.data, bucket, segment, q, sort, desc]);

  const setBucket = (b: string) => {
    const next = new URLSearchParams(params);
    if (b) next.set("bucket", b);
    else next.delete("bucket");
    setParams(next, { replace: true });
  };

  const th = (key: SortKey, label: string) => (
    <th
      className="sortable"
      onClick={() => {
        if (sort === key) setDesc(!desc);
        else {
          setSort(key);
          setDesc(true);
        }
      }}
    >
      {label} {sort === key ? (desc ? "▾" : "▴") : ""}
    </th>
  );

  return (
    <div className="wrap">
      <div className="pagehead">
        <div>
          <h1>مشتریان</h1>
          <div className="sub">
            {list.data ? (
              <>
                <b className="num">{rows.length}</b> از <b className="num">{list.data.total}</b> مشتری
                {" · "}تاریخ مبنا <span className="mono">{asOf}</span>
              </>
            ) : (
              "در حال بارگذاری دفتر…"
            )}
          </div>
        </div>
      </div>

      <div className="filters">
        <select value={bucket} onChange={(e) => setBucket(e.target.value)}>
          <option value="">همهٔ سطل‌ها</option>
          {(["grow", "protect", "fix", "reduce"] as Bucket[]).map((b) => (
            <option key={b} value={b}>{BUCKET_FA[b]}</option>
          ))}
        </select>
        <select value={segment} onChange={(e) => setSegment(e.target.value)}>
          <option value="">همهٔ بخش‌ها</option>
          {segments.map((s) => (
            <option key={s} value={s}>بخش {s}</option>
          ))}
        </select>
        <input
          type="search"
          placeholder="جست‌وجوی شناسه یا بخش RFM…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          style={{ minWidth: 240 }}
        />
        {(bucket || segment || q) && (
          <button className="ghost sm" onClick={() => { setBucket(""); setSegment(""); setQ(""); }}>
            پاک‌کردن فیلترها
          </button>
        )}
      </div>

      {list.isLoading && <Skeleton h={340} />}
      {list.isError && <div className="notice bad">{(list.error as ApiError).fa}</div>}

      {list.data && rows.length === 0 && <Empty>هیچ مشتری با این فیلترها پیدا نشد.</Empty>}

      {rows.length > 0 && (
        <div className="tablewrap" style={{ maxHeight: "68vh", overflowY: "auto" }}>
          <table>
            <thead>
              <tr>
                {th("customer_id", "شناسه")}
                <th>سطل</th>
                <th>بخش</th>
                {th("rfm_cell", "RFM")}
                {th("open_loops", "حلقهٔ باز")}
                {th("signals", "سیگنال")}
              </tr>
            </thead>
            <tbody>
              {rows.map((c: CustomerRow) => (
                <tr key={c.customer_id} className="click" onClick={() => nav(link(`/customers/${c.customer_id}`))}>
                  <td className="mono">{c.customer_id}</td>
                  <td><BucketPill bucket={c.bucket} title /></td>
                  <td className="muted">{c.segment ?? "—"}</td>
                  <td><RFMCell cell={c.rfm_cell} segment={c.rfm_segment_fa} /></td>
                  <td className="num">{c.open_loops ?? 0}</td>
                  <td className="num">{c.signals}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
