import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import { useApp } from "../state/app";
import { CATEGORY_FA, Empty, Skeleton } from "../components/bits";

const STATUS_FA: Record<string, string> = {
  ok: "متعادل",
  too_broad: "بیش از حد گسترده",
  too_narrow: "بیش از حد باریک",
  insufficient: "داده ناکافی",
};
const STATUS_CLS: Record<string, string> = {
  ok: "ok", too_broad: "danger", too_narrow: "fix", insufficient: "neutral",
};

export default function SystemPage() {
  const { asOf } = useApp();
  const calib = useQuery({ queryKey: ["calibration", asOf], queryFn: () => api.calibration(asOf) });
  const fb = useQuery({ queryKey: ["feedback"], queryFn: api.feedbackStats });
  const tools = useQuery({ queryKey: ["tools"], queryFn: api.tools, staleTime: Infinity });
  const agents = useQuery({ queryKey: ["agents"], queryFn: api.agents, staleTime: Infinity });

  return (
    <div className="wrap">
      <div className="pagehead">
        <div>
          <h1>سلامت سیستم</h1>
          <div className="sub">برای مدیر محصول و تیم داده — نه مدیر فروش.</div>
        </div>
      </div>

      {calib.data?.failures?.length ? (
        <div className="notice bad" style={{ marginBottom: 14 }}>
          <strong>{calib.data.failures.length} آشکارساز کالیبراسیون را رد کرده‌اند:</strong>{" "}
          {calib.data.failures.join("، ")}
        </div>
      ) : null}

      <h2 style={{ margin: "18px 0 10px" }}>کالیبراسیون آشکارسازها</h2>
      {calib.isLoading && <Skeleton h={280} />}
      {calib.isError && <div className="notice bad">{(calib.error as ApiError).fa}</div>}
      {calib.data && (
        <>
          <p className="small muted" style={{ marginBottom: 10 }}>
            جمعیت <b className="num">{calib.data.population}</b> مشتری. آشکارسازی که روی بیش از ۶۰٪ شلیک کند
            یک بدیهیات است و زیر ۲٪ تزیین.
          </p>
          <div className="tablewrap">
            <table>
              <thead>
                <tr>
                  <th>آشکارساز</th><th>دسته</th><th>شلیک</th><th>واجد شرایط</th>
                  <th style={{ minWidth: 160 }}>نرخ</th><th>وضعیت</th>
                </tr>
              </thead>
              <tbody>
                {[...calib.data.rows].sort((a, b) => b.fire_rate - a.fire_rate).map((r) => (
                  <tr key={r.detector}>
                    <td className="mono">{r.detector}</td>
                    <td><span className={`pill ${r.category}`}>{CATEGORY_FA[r.category]}</span></td>
                    <td className="num">{r.fired}</td>
                    <td className="num">{r.eligible}</td>
                    <td>
                      <span className="rowsplit" style={{ gap: 8 }}>
                        <span className="sevbar" style={{ width: 90 }}>
                          <i className={r.category} style={{ width: `${Math.min(100, r.fire_rate * 100)}%` }} />
                        </span>
                        <span className="num tiny">{(r.fire_rate * 100).toFixed(1)}٪</span>
                      </span>
                    </td>
                    <td>
                      <span className={`pill ${STATUS_CLS[r.status] ?? "neutral"}`}>{STATUS_FA[r.status] ?? r.status}</span>
                      {r.rare_by_design && <span className="tag" style={{ marginInlineStart: 4 }}>کمیاب عمدی</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <h2 style={{ margin: "26px 0 10px" }}>یادگیری از بازخورد</h2>
      {fb.isLoading && <Skeleton h={90} />}
      {fb.data && fb.data.events === 0 && (
        <Empty>هنوز هیچ بازخوردی ثبت نشده است. وزن همهٔ آشکارسازها ۱٫۰ است.</Empty>
      )}
      {fb.data && fb.data.events > 0 && (
        <div className="tablewrap">
          <table>
            <thead>
              <tr><th>آشکارساز</th><th>رأی</th><th>انجام</th><th>رد</th><th>تعویق</th><th>اشتباه</th><th>وزن</th></tr>
            </thead>
            <tbody>
              {fb.data.detector_stats.map((s) => (
                <tr key={s.detector} style={{ background: s.weight < 0.8 ? "var(--crit-soft)" : undefined }}>
                  <td className="mono">{s.detector}</td>
                  <td className="num">{s.events}</td>
                  <td className="num">{s.done}</td>
                  <td className="num">{s.dismissed}</td>
                  <td className="num">{s.snoozed}</td>
                  <td className="num">{s.wrong}</td>
                  <td className="num"><b>{s.weight?.toFixed(2)}</b></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="grid2" style={{ marginTop: 26 }}>
        <div>
          <h2 style={{ marginBottom: 10 }}>ابزارها ({tools.data?.tools.length ?? "…"})</h2>
          <div className="stack">
            {tools.data?.tools.map((t) => (
              <div key={t.name} className="card">
                <div className="mono small" style={{ fontWeight: 600 }}>{t.name}</div>
                <p className="small dim" style={{ margin: "6px 0 0" }}>{t.description_fa}</p>
              </div>
            ))}
          </div>
        </div>
        <div>
          <h2 style={{ marginBottom: 10 }}>تحلیل‌گرها ({agents.data?.agents.length ?? "…"})</h2>
          <div className="stack">
            {agents.data?.agents.map((a) => (
              <div key={a.name} className="card">
                <strong className="small">{a.question_fa}</strong>
                <div className="rowsplit" style={{ gap: 5, marginTop: 8 }}>
                  {a.tools.map((t) => <span key={t} className="tag">{t}</span>)}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
