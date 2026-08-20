"""Opportunity detectors #21–#22 (PLAN §3.4).

These two are the ``grow`` side of the strategy: fewer customers, higher and
steadier margin means the growth energy has to be aimed at accounts that are
already profitable and demonstrably under-bought — not spread across the book.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ...io import schema as S
from ...metrics.base import MetricContext, money, num, pct, span_ref
from ..base import BaseDetector, Signal, annual_revenue, register, scale


@register
class WalletHeadroom(BaseDetector):
    """#21 — buys well below comparable peers, and is profitable while doing it.

    At the demo anchor the ``سهم_سبد`` sheet is not yet visible, so headroom
    comes from the peer-capacity estimate. That is a *lead*, not a measurement,
    and the evidence it cites says so (confidence 0.5).
    """

    name = "wallet_headroom"
    category = "opportunity"
    requires = ["wallet", "economics"]

    def eligible(self, ctx: MetricContext) -> pd.Index:
        w = ctx.table("wallet")
        return w.index[w["headroom_value"].notna()].intersection(ctx.population)

    def detect(self, ctx: MetricContext) -> list[Signal]:
        st = ctx.settings
        df = self.frame(ctx)
        hits = df.loc[
            (df["headroom_value"] > 0)
            & (df["capacity_gap_ratio"] < st.wallet_headroom_share_max)
            & (df["margin_rate"] > st.wallet_headroom_margin_min)
        ]
        out = []
        for cid, r in hits.iterrows():
            estimated = r.headroom_source == "peer_capacity_estimate"
            out.append(self.signal(
                ctx, cid,
                severity=scale(1.0 - float(r.capacity_gap_ratio), 0.5, 1.0, floor=20.0),
                direction="static",
                headline_fa=(
                    f"این مشتری با حاشیه سود {pct(r.margin_rate)} درصد تنها "
                    f"{pct(r.capacity_gap_ratio, 0)} درصد سطح خرید همتایان هم‌بخش خود را "
                    f"دارد — ظرفیت رشد {money(r.headroom_value, st)} ریال."
                ),
                evidence_ids=ctx.ev(cid, "headroom", "margin", "revenue", "wallet-share"),
                value_at_stake=float(r.headroom_value or 0.0),
                suggested_bucket="grow",
                estimated=estimated,
                capacity_gap_ratio=float(r.capacity_gap_ratio),
            ))
        return out


@register
class CrossSellPeerGap(BaseDetector):
    """#22 — buys family X; customers with a similar profile also buy family Y.

    Similarity is deliberately simple and auditable: same segment, same dominant
    family. The gap is a family that ≥60% of those peers buy and this customer
    never has. No model, no embedding — a claim the sales manager can check.
    """

    name = "cross_sell_peer_gap"
    category = "opportunity"
    requires = ["economics", "mix"]

    def eligible(self, ctx: MetricContext) -> pd.Index:
        mix = ctx.table("mix")
        return mix.index[mix["dominant_family"].notna()].intersection(ctx.population)

    def detect(self, ctx: MetricContext) -> list[Signal]:
        st = ctx.settings
        lines = ctx.spine.lines
        bought = (
            lines.groupby([S.CUSTOMER_ID, S.P_FAMILY])[S.D_REVENUE].sum().unstack(fill_value=0.0)
        )
        df = self.frame(ctx)
        window = (lines[S.F_DATE].min().date(), ctx.as_of)
        out = []
        for (segment, family), group in df.groupby(["segment", "dominant_family"]):
            members = [c for c in group.index if c in bought.index]
            if len(members) < st.cross_sell_min_peers:
                continue
            adoption = (bought.loc[members] > 0).mean()
            for cid in members:
                mine = bought.loc[cid]
                gaps = [
                    fam for fam in adoption.index
                    if adoption[fam] >= st.cross_sell_peer_adoption
                    and mine.get(fam, 0.0) == 0.0
                ]
                if not gaps:
                    continue
                row = df.loc[cid]
                if not (row.get("margin_rate", 0) or 0) > 0:
                    continue
                # value the gap at what peers spend on those families, per peer
                peer_spend = float(
                    bought.loc[members, gaps].sum().sum() / max(len(members), 1)
                )
                ev = ctx.emit(
                    cid, "crosssell",
                    f"{num(len(gaps))} خانواده کالا که دست‌کم "
                    f"{pct(st.cross_sell_peer_adoption, 0)} درصد مشتریان هم‌بخش و "
                    f"هم‌پروفایل می‌خرند، هرگز به این مشتری فروخته نشده است: "
                    f"{', '.join(gaps)}.",
                    float(len(gaps)), unit="خانواده", kind="comparison", window=window,
                    source_rows=span_ref(S.S_SALES, cid, window,
                                         int(row.get("lines_total", 0) or 0)),
                    formula=(f"families with ≥{st.cross_sell_peer_adoption:.0%} adoption "
                             "among same-segment, same-dominant-family peers and zero "
                             "revenue here"),
                    peer_count=len(members), gaps=gaps,
                )
                out.append(self.signal(
                    ctx, cid,
                    severity=scale(len(gaps), 1, 4, floor=20.0),
                    direction="static",
                    headline_fa=(
                        f"فرصت فروش متقابل: همتایان هم‌بخش این مشتری "
                        f"{', '.join(gaps)} می‌خرند، اما این مشتری هرگز نخریده است."
                    ),
                    evidence_ids=[ev.id] + ctx.ev(cid, "margin", "revenue"),
                    value_at_stake=peer_spend,
                    suggested_bucket="grow",
                    gaps=gaps, peer_count=len(members),
                ))
        return out
