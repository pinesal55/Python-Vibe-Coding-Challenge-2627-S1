import streamlit as st
import pandas as pd
from datetime import datetime
import io

if "nhl_teams" not in st.session_state:
    st.session_state.nhl_teams = [
        "Anaheim", "Boston", "Buffalo", "Calgary", "Carolina", "Chicago",
        "Colorado", "Columbus", "Dallas", "Detroit", "Edmonton", "Florida",
        "Los Angeles", "Minnesota", "Montreal", "Nashville", "New Jersey",
        "New York Islanders", "New York Rangers", "Ottawa", "Philadelphia",
        "Pittsburgh", "San Jose", "Seattle", "St. Louis", "Tampa Bay",
        "Toronto", "Utah", "Vancouver", "Vegas", "Washington", "Winnipeg"
    ]

st.set_page_config(page_title="Expansion GM Toolkit", page_icon="🏒", layout="wide")

# ---------- Session State Initialization ----------
if "players" not in st.session_state:
    st.session_state.players = []

if "team_needs" not in st.session_state:
    st.session_state.team_needs = ["Two-Way Center", "Play-Driving Winger", "Offensive Defenseman", "Shutdown Defenseman"]

if "expansion_slots" not in st.session_state:
    st.session_state.expansion_slots = 30  
if "team_style" not in st.session_state:
    st.session_state.team_style = "Speed"

if "position_targets" not in st.session_state:
    st.session_state.position_targets = {"C": 4, "LW": 4, "RW": 4, "D": 8, "G": 2}

# ---------- Analytics & Scoring Functions ----------
def age_factor(age):
    """Age curve modifier: Peak 24-28."""
    if age <= 22:
        return 1.15
    elif 23 <= age <= 28:
        return 1.0
    elif 29 <= age <= 31:
        return 0.85
    else:
        return 0.65

def calculate_skater_4yr_avg(stats_history):
    """
    Weighted 4-year average giving more weight to recent seasons:
    Y1 (most recent): 40%, Y2: 30%, Y3: 20%, Y4: 10%
    """
    weights = [0.4, 0.3, 0.2, 0.1]
    total_pts_weighted = 0
    total_gp_weighted = 0
    
    for i, s in enumerate(stats_history):
        w = weights[i]
        total_pts_weighted += (s.get("g", 0) + s.get("a", 0)) * w
        total_gp_weighted += max(s.get("gp", 1), 1) * w

    avg_ppg = total_pts_weighted / total_gp_weighted if total_gp_weighted > 0 else 0
    return round(avg_ppg * 82, 1)  # 82-game pace equivalent

def calculate_value_score_skater(pts_82_pace, age, aav):
    if aav <= 0:
        aav = 0.5
    return round((pts_82_pace * age_factor(age)) / (aav * 10), 2)

def calculate_value_score_goalie(sv_avg, gaa_avg, gsae_avg, age, aav):
    """
    Goalie value incorporating Save %, GAA, and Goals Saved Above Expected (GSAE).
    """
    if aav <= 0:
        aav = 0.5
    
    # Baseline 0.905 SV%, 2.75 GAA
    sv_impact = (sv_avg - 0.905) * 500  # +5 pts for .915
    gaa_impact = (2.75 - gaa_avg) * 2   # Positive if GAA below 2.75
    gsae_impact = gsae_avg * 0.5        # Raw GSAE weighting
    
    raw_performance = max(1.0, 5.0 + sv_impact + gaa_impact + gsae_impact)
    return round((raw_performance * age_factor(age)) / aav, 2)

def calculate_gem_score(position, age, performance_metric, underlying, aav):
    gem = 0
    if age <= 25:
        gem += 3
    if underlying >= 7.0:
        gem += 4
    if aav <= 2.5:
        gem += 3
    return min(gem, 10)

def calculate_fit_score(archetype, age, aav, needs):
    fit = 0
    if archetype in needs:
        fit += 5
    if age <= 27:
        fit += 2
    if aav <= 4.0:
        fit += 2
    if aav <= 2.5:
        fit += 1
    return min(fit, 10)

def players_to_df(players):
    return pd.DataFrame(players)

def roster_counts():
    counts = {"C": 0, "LW": 0, "RW": 0, "D": 0, "G": 0}
    claimed = [p for p in st.session_state.players if p.get("status") == "claimed"]
    for p in claimed:
        if p["position"] in counts:
            counts[p["position"]] += 1
    return counts

def calculate_draft_score(player):
    return round(
        player.get("value_score", 0) * 0.5
        + player.get("gem_score", 0)
        + (player.get("fit_score", 0) * 2),
        2
    )

# ---------- Sidebar ----------
st.sidebar.title("🏒 Expansion GM Toolkit")
st.sidebar.caption("Houston 2028-29 Portfolio Project")
st.sidebar.markdown("---")
st.sidebar.subheader("Team Needs (Archetypes)")
needs_input = st.sidebar.text_area(
    "Preferred archetypes (one per line)",
    value="\n".join(st.session_state.team_needs),
    height=120,
)
if st.sidebar.button("Update Needs"):
    st.session_state.team_needs = [line.strip() for line in needs_input.split("\n") if line.strip()]
    st.sidebar.success("Needs updated!")

st.sidebar.number_input("Expansion Draft Slots", min_value=15, max_value=40, value=st.session_state.expansion_slots, key="slots_input")
if st.sidebar.button("Set Slots"):
    st.session_state.expansion_slots = st.sidebar.slots_input
    st.sidebar.success("Slots updated!")

st.sidebar.markdown("---")
st.sidebar.subheader("Houston Identity")
st.session_state.team_style = st.sidebar.selectbox("Team Style", ["Speed", "Skill", "Defensive", "Physical", "Possession"])

# ---------- Main Tabs ----------
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📋 Roster & Players",
    "🔍 Player Evaluator",
    "🔄 Trade Analyzer",
    "📥 Expansion Draft",
    "💾 Data"
])

# ========== TAB 1: Roster & Players ==========
with tab1:
    st.header("Roster Management")
    st.caption("Input 4-year stats for skaters (G, A, GP) or goalies (SV%, GAA, GSAE).")

    with st.expander("➕ Add New Player", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            label = st.text_input("Player Name / Label", placeholder="e.g. McDavid / Goalie Target A")
            age = st.number_input("Age", 18, 40, 25)
            position = st.selectbox("Position", ["C", "LW", "RW", "D", "G"], key="add_pos")
            archetype = st.selectbox("Archetype", [
                "Two-Way Center", "Playmaking Center", "Physical Center",
                "Play-Driving Winger", "Sniper Winger", "Physical Winger",
                "Offensive Defenseman", "Shutdown Defenseman", "Puck-Moving D",
                "Starting Goalie", "Backup Goalie", "Other"
            ])
        with c2:
            aav = st.number_input("AAV ($M)", 0.0, 15.0, 3.0, step=0.25)
            years = st.number_input("Years Left", 0, 8, 2)
            underlying = st.slider("Underlying / Process Score (1-10)", 1, 10, 5)

        st.markdown("---")
        st.subheader("4-Year Statistical History")
        
        stat_cols = st.columns(4)
        history = []
        
        if position == "G":
            for idx, year_label in enumerate(["2025-26 (Latest)", "2024-25", "2023-24", "2022-23"]):
                with stat_cols[idx]:
                    st.caption(f"**{year_label}**")
                    sv = st.number_input(f"SV% Y{idx+1}", 0.850, 0.960, 0.910, step=0.001, format="%.3f", key=f"g_sv_{idx}")
                    gaa = st.number_input(f"GAA Y{idx+1}", 1.50, 5.00, 2.60, step=0.05, key=f"g_gaa_{idx}")
                    gsae = st.number_input(f"GSAE Y{idx+1}", -30.0, 50.0, 5.0, step=0.5, key=f"g_gsae_{idx}")
                    history.append({"sv": sv, "gaa": gaa, "gsae": gsae})
            
            avg_sv = sum(h["sv"] for h in history) / 4
            avg_gaa = sum(h["gaa"] for h in history) / 4
            avg_gsae = sum(h["gsae"] for h in history) / 4
            val_score = calculate_value_score_goalie(avg_sv, avg_gaa, avg_gsae, age, aav)
            pts_metric = f"{avg_sv:.3f} SV% / {avg_gaa:.2f} GAA"

        else:
            for idx, year_label in enumerate(["2025-26 (Latest)", "2024-25", "2023-24", "2022-23"]):
                with stat_cols[idx]:
                    st.caption(f"**{year_label}**")
                    gp = st.number_input(f"GP Y{idx+1}", 1, 82, 75, key=f"s_gp_{idx}")
                    g = st.number_input(f"G Y{idx+1}", 0, 70, 15, key=f"s_g_{idx}")
                    a = st.number_input(f"A Y{idx+1}", 0, 90, 25, key=f"s_a_{idx}")
                    history.append({"gp": gp, "g": g, "a": a})
            
            pace_82 = calculate_skater_4yr_avg(history)
            val_score = calculate_value_score_skater(pace_82, age, aav)
            pts_metric = f"82-Game Pace: {pace_82} Pts"

        if st.button("Add Player to Roster"):
            if label:
                player = {
                    "label": label,
                    "age": age,
                    "position": position,
                    "archetype": archetype,
                    "aav": aav,
                    "years": years,
                    "underlying": underlying,
                    "history": history,
                    "metric_summary": pts_metric,
                    "value_score": val_score,
                    "gem_score": calculate_gem_score(position, age, val_score, underlying, aav),
                    "fit_score": calculate_fit_score(archetype, age, aav, st.session_state.team_needs),
                    "added": datetime.now().strftime("%Y-%m-%d %H:%M"),
                }
                st.session_state.players.append(player)
                st.success(f"Added {label}")
                st.rerun()

    st.subheader("Current Roster")
    df = players_to_df(st.session_state.players)
    if not df.empty:
        display_df = df[["label", "position", "archetype", "age", "aav", "metric_summary", "value_score", "gem_score", "fit_score"]].copy()
        st.dataframe(display_df, use_container_width=True, hide_index=True)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Players", len(df))
        m2.metric("Avg Fit", round(df["fit_score"].mean(), 1))
        m3.metric("Avg Value", round(df["value_score"].mean(), 1))
        m4.metric("Total AAV", f"${df['aav'].sum():.1f}M")

        to_remove = st.selectbox("Remove player", ["—"] + [p["label"] for p in st.session_state.players])
        if to_remove != "—" and st.button("Remove"):
            st.session_state.players = [p for p in st.session_state.players if p["label"] != to_remove]
            st.rerun()

# ========== TAB 2: Player Evaluator ==========
with tab2:
    st.header("Quick Player Evaluator")
    st.caption("Evaluate skaters or goalies using 4-year statistical metrics.")

    e_pos = st.radio("Position Type", ["Skater (C/LW/RW/D)", "Goalie (G)"], horizontal=True)
    c1, c2 = st.columns(2)
    with c1:
        e_age = st.number_input("Age", 18, 40, 25, key="eval_age")
        e_aav = st.number_input("AAV ($M)", 0.0, 15.0, 3.0, step=0.25, key="eval_aav")
    with c2:
        e_arch = st.selectbox("Archetype", ["Two-Way Center", "Play-Driving Winger", "Offensive Defenseman", "Starting Goalie", "Backup Goalie"], key="eval_arch")
        e_under = st.slider("Underlying / Process Score", 1, 10, 6, key="eval_under")

    st.subheader("4-Year Performance Data")
    stat_cols = st.columns(4)
    eval_hist = []

    if "Goalie" in e_pos:
        for idx in range(4):
            with stat_cols[idx]:
                st.caption(f"Year {idx+1}")
                sv = st.number_input(f"SV%", 0.850, 0.960, 0.910, key=f"e_sv_{idx}")
                gaa = st.number_input(f"GAA", 1.50, 5.00, 2.50, key=f"e_gaa_{idx}")
                gsae = st.number_input(f"GSAE", -30.0, 50.0, 4.0, key=f"e_gsae_{idx}")
                eval_hist.append({"sv": sv, "gaa": gaa, "gsae": gsae})
        
        avg_sv = sum(h["sv"] for h in eval_hist)/4
        avg_gaa = sum(h["gaa"] for h in eval_hist)/4
        avg_gsae = sum(h["gsae"] for h in eval_hist)/4
        v_score = calculate_value_score_goalie(avg_sv, avg_gaa, avg_gsae, e_age, e_aav)
    else:
        for idx in range(4):
            with stat_cols[idx]:
                st.caption(f"Year {idx+1}")
                gp = st.number_input(f"GP", 1, 82, 70, key=f"e_gp_{idx}")
                g = st.number_input(f"G", 0, 70, 15, key=f"e_g_{idx}")
                a = st.number_input(f"A", 0, 90, 25, key=f"e_a_{idx}")
                eval_hist.append({"gp": gp, "g": g, "a": a})
        
        pace_82 = calculate_skater_4yr_avg(eval_hist)
        v_score = calculate_value_score_skater(pace_82, e_age, e_aav)

    if st.button("Evaluate Player Performance"):
        f_score = calculate_fit_score(e_arch, e_age, e_aav, st.session_state.team_needs)
        g_score = calculate_gem_score("G" if "Goalie" in e_pos else "S", e_age, v_score, e_under, e_aav)

        col1, col2, col3 = st.columns(3)
        col1.metric("4-Year Value Score", v_score)
        col2.metric("Gem Score", g_score, "/10")
        col3.metric("Roster Fit Score", f_score, "/10")

# ========== TAB 3: Trade Analyzer ==========
with tab3:
    st.header("Trade Analyzer")
    st.caption("Compare packages based on total calculated 4-year value scores.")

    for side in ["Side A", "Side B"]:
        st.subheader(side)
        count = st.number_input(f"Players on {side}", 1, 4, 1, key=f"count_{side}")
        for i in range(count):
            cols = st.columns(4)
            with cols[0]:
                is_g = st.checkbox(f"Is Goalie? (P{i+1})", key=f"{side}_g_{i}")
            with cols[1]:
                p_age = st.number_input(f"Age (P{i+1})", 18, 40, 26, key=f"{side}_age_{i}")
            with cols[2]:
                p_aav = st.number_input(f"AAV $M (P{i+1})", 0.5, 15.0, 3.0, key=f"{side}_aav_{i}")
            with cols[3]:
                if is_g:
                    p_val = calculate_value_score_goalie(0.912, 2.50, 6.0, p_age, p_aav)
                else:
                    p_val = calculate_value_score_skater(45, p_age, p_aav)
                st.metric("Estimated Val", p_val)

# ========== TAB 4: Expansion Draft ==========
with tab4:
    st.header("Expansion Draft Tracker")
    
    available = [p for p in st.session_state.players if p.get("status") == "available" or "status" not in p]
    for p in available:
        p["draft_score"] = calculate_draft_score(p)

    available = sorted(available, key=lambda x: x.get("draft_score", 0), reverse=True)
    claimed = [p for p in st.session_state.players if p.get("status") == "claimed"]

    if available:
        best = available[0]
        st.success(f"GM Recommendation: **{best['label']}** ({best['position']}) — Draft Score: {best['draft_score']}")

    st.subheader("Available Pool")
    if available:
        av_df = pd.DataFrame(available)[["team", "label", "position", "archetype", "age", "aav", "metric_summary", "value_score", "gem_score", "fit_score", "draft_score"]]
        st.dataframe(av_df, use_container_width=True, hide_index=True)

        claim_label = st.selectbox("Claim this player", ["—"] + [p["label"] for p in available], key="claim_player_selectbox")
        if claim_label != "—" and st.button("Claim for Houston"):
            for p in st.session_state.players:
                if p["label"] == claim_label:
                    p["status"] = "claimed"
            st.rerun()

    st.subheader("Your Claims")
    counts = roster_counts()
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Centers", f"{counts['C']}/4")
    c2.metric("LW", f"{counts['LW']}/4")
    c3.metric("RW", f"{counts['RW']}/4")
    c4.metric("Defense", f"{counts['D']}/8")
    c5.metric("Goalies", f"{counts['G']}/2")
    
    if claimed:
        cl_df = pd.DataFrame(claimed)[["label", "archetype", "age", "aav", "metric_summary", "value_score", "gem_score", "fit_score"]]
        st.dataframe(cl_df, use_container_width=True, hide_index=True)

# ========== TAB 5: Data ==========
with tab5:
    st.header("Save / Load Roster Data")
    df = players_to_df(st.session_state.players)
    if not df.empty:
        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button("Download Roster CSV", csv, "houston_roster.csv", "text/csv")

    uploaded = st.file_uploader("Upload previous CSV", type="csv")
    if uploaded and st.button("Load CSV"):
        new_df = pd.read_csv(uploaded)
        st.session_state.players = new_df.to_dict("records")
        st.success("Loaded!")
        st.rerun()

    if st.button("Clear All Players"):
        st.session_state.players = []
        st.rerun()