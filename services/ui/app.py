import os
import requests
import streamlit as st

API_BASE = os.environ.get("API_BASE", "http://localhost:8000")
STRATEGY_NAME = os.environ.get("STRATEGY_NAME")
STRATEGY_VERSION = os.environ.get("STRATEGY_VERSION")

st.set_page_config(page_title="Pokemon Trader", layout="wide")
st.title("Pokemon Trader — Daily Review")

st.subheader("API health")
r = requests.get(f"{API_BASE}/api/health", timeout=10)
st.json(r.json())

st.divider()

def valuation_params() -> dict:
    params = {}
    if STRATEGY_NAME:
        params["strategy_name"] = STRATEGY_NAME
    if STRATEGY_VERSION:
        params["strategy_version"] = STRATEGY_VERSION
    return params


tab_market, tab_portfolio = st.tabs(["Market Opportunities", "Portfolio"])

with tab_market:
    if st.button("Seed demo proposals"):
        rr = requests.post(f"{API_BASE}/api/proposals/seed-demo", timeout=20)
        st.write(rr.json())
        st.rerun()

    cols = st.columns(2)
    with cols[0]:
        st.subheader("Top 10 undervalued")
        undervalued = requests.get(
            f"{API_BASE}/api/valuations/undervalued",
            params={**valuation_params(), "limit": 10},
            timeout=20,
        ).json()
        uv_rows = undervalued.get("valuations", [])
        if uv_rows:
            st.dataframe(
                uv_rows,
                use_container_width=True,
                column_config={
                    "gap_pct": st.column_config.NumberColumn(format="%.2f"),
                    "market_price": st.column_config.NumberColumn(format="%.2f"),
                    "forecast_price": st.column_config.NumberColumn(format="%.2f"),
                },
            )
        else:
            st.info("No undervalued cards yet.")

    with cols[1]:
        st.subheader("Top 10 overvalued")
        overvalued = requests.get(
            f"{API_BASE}/api/valuations/overvalued",
            params={**valuation_params(), "limit": 10},
            timeout=20,
        ).json()
        ov_rows = overvalued.get("valuations", [])
        if ov_rows:
            st.dataframe(
                ov_rows,
                use_container_width=True,
                column_config={
                    "gap_pct": st.column_config.NumberColumn(format="%.2f"),
                    "market_price": st.column_config.NumberColumn(format="%.2f"),
                    "forecast_price": st.column_config.NumberColumn(format="%.2f"),
                },
            )
        else:
            st.info("No overvalued cards yet.")

    st.divider()
    st.subheader("Today's proposals")
    resp = requests.get(f"{API_BASE}/api/proposals/today", timeout=20).json()
    proposals = resp.get("proposals", [])

    if not proposals:
        st.info("No proposals for today yet.")
    else:
        for p in proposals:
            with st.container(border=True):
                left, right = st.columns([3, 2])

                with left:
                    st.markdown(
                        f"**{p['action']}** — `{p['asset_id']}`  \n"
                        f"Qty: **{p['qty']}**, Target: **${p['target_price']}**, "
                        f"Confidence: **{p['confidence']}**  \n"
                        f"Status: **{p['status']}**"
                    )
                    st.caption("Explainability / rationale")
                    st.json(p.get("rationale", {}))

                with right:
                    if p["status"] == "PENDING":
                        if st.button("Approve", key=f"approve-{p['proposal_id']}"):
                            rr = requests.post(
                                f"{API_BASE}/api/proposals/{p['proposal_id']}/approve",
                                timeout=20,
                            )
                            st.write(rr.json())
                            st.rerun()

                        reason = st.text_input("Reject reason (optional)", key=f"reason-{p['proposal_id']}")
                        if st.button("Reject", key=f"reject-{p['proposal_id']}"):
                            rr = requests.post(
                                f"{API_BASE}/api/proposals/{p['proposal_id']}/reject",
                                json={"reason": reason},
                                timeout=20,
                            )
                            st.write(rr.json())
                            st.rerun()
                    else:
                        st.write(f"Decision: {p.get('decision')}")
                        if p.get("decision_reason"):
                            st.write(f"Reason: {p['decision_reason']}")

with tab_portfolio:
    st.subheader("Holdings valuation")
    holdings = requests.get(f"{API_BASE}/api/portfolio/valuations", timeout=20).json()
    rows = holdings.get("holdings", [])
    if rows:
        st.dataframe(
            rows,
            use_container_width=True,
            column_config={
                "gap_pct": st.column_config.NumberColumn(format="%.2f"),
                "avg_cost": st.column_config.NumberColumn(format="%.2f"),
                "market_price": st.column_config.NumberColumn(format="%.2f"),
                "forecast_price": st.column_config.NumberColumn(format="%.2f"),
            },
        )
    else:
        st.info("No holdings recorded yet.")
