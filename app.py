"""SeatSense - KCET college predictor. Streamlit app, run with:
    streamlit run app.py
"""

import html

import streamlit as st

from seatsense.data import (
    available_bases,
    compose_category,
    branch_options,
    load_data,
    predict,
    RESULTS_PER_TIER,
    ROUND_NO_DATA,
    SUBCAT_LABELS,
    TIER_ROUNDS,
)
from seatsense.branch_labels import branch_display_labels, expand_branch_label

st.set_page_config(page_title="SeatSense", page_icon="🎓", layout="centered")

TIER_STYLE = {
    "Strong Chance": {"bg": "#e6f4ea", "border": "#2e7d32", "text": "#1b5e20"},
    "Possible": {"bg": "#fff8e1", "border": "#c9a227", "text": "#8a6d00"},
    "Unlikely": {"bg": "#fdecea", "border": "#c62828", "text": "#8e1e1e"},
}

TIER_BLURB = {
    "Strong Chance": "realistically allotted in Round 1 itself",
    "Possible": "not likely in Round 1, but realistic by Round 2",
    "Unlikely": "only realistic by Round 3, if at all",
}


@st.cache_data
def get_data():
    return load_data()


def _fmt_rank(value):
    return f"{value:,.1f}" if value % 1 else f"{value:,.0f}"


def _explanation(result, rank):
    tier = result["tier"]
    round_n = result["round"]
    cutoff_str = _fmt_rank(result["cutoff_rank"])
    rank_str = f"{rank:,}"
    prior_round = result["prior_round"]

    if prior_round is None:
        # Strong Chance - no earlier round to explain
        return f"{tier} — Round {round_n} cutoff was rank {cutoff_str}, you are at rank {rank_str}."

    if result["prior_round_status"] == ROUND_NO_DATA:
        return (
            f"{tier} — No Round {prior_round} allotment data for this branch, "
            f"Round {round_n} cutoff was rank {cutoff_str}, you are at rank {rank_str}."
        )

    prior_cutoff_str = _fmt_rank(result["prior_round_cutoff"])
    return (
        f"{tier} — Round {prior_round} cutoff was rank {prior_cutoff_str}, "
        f"Round {round_n} cutoff was rank {cutoff_str}, you are at rank {rank_str}."
    )


def render_card(result, rank):
    tier = result["tier"]
    style = TIER_STYLE[tier]
    college = html.escape(result["college_name"])
    branch = html.escape(expand_branch_label(result["branch_name"]))
    explanation = html.escape(_explanation(result, rank))

    st.markdown(
        f"""
<div style="border:1px solid {style['border']}; background:{style['bg']};
            border-radius:10px; padding:14px 18px; margin-bottom:12px;">
  <div style="display:flex; justify-content:space-between; align-items:center; gap:12px;">
    <div style="font-size:1.05rem; font-weight:600; color:#111;">{college}</div>
    <div style="background:{style['border']}; color:white; padding:3px 12px;
                border-radius:999px; font-size:0.85rem; font-weight:600; white-space:nowrap;">
      {tier}
    </div>
  </div>
  <div style="color:#444; margin-top:4px;">{branch}</div>
  <div style="color:{style['text']}; margin-top:6px; font-size:0.92rem;">
    {explanation}
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


def main():
    st.title("🎓 SeatSense")
    st.caption("Find engineering colleges in Karnataka that fit your KCET rank.")

    df = get_data()

    # Outside the form (not inside st.form) so it reruns the page the moment
    # it's toggled - the Category options below depend on it (Kalyana
    # Karnataka and Rest of Karnataka use different category codes), and
    # st.form only applies widget changes on submit, which would leave the
    # Category list one step stale if the toggle lived inside the form.
    is_hk = st.toggle(
        "I am eligible for the Hyderabad-Karnataka (371J) reservation",
        value=False,
    )

    with st.form("seatsense_form"):
        rank = st.number_input(
            "Your KCET Rank",
            min_value=1,
            step=1,
            value=None,
            placeholder="e.g. 15000",
        )

        col1, col2 = st.columns(2)
        with col1:
            base_options = available_bases(df, is_hk)
            base = st.selectbox(
                "Category",
                options=[code for code, _ in base_options],
                format_func=lambda code: dict(base_options)[code],
            )
        with col2:
            subcat = st.selectbox(
                "Sub-category",
                options=[code for code, _ in SUBCAT_LABELS],
                format_func=lambda code: dict(SUBCAT_LABELS)[code],
            )

        branches = branch_options(df)
        branch_labels = branch_display_labels(branches)
        branch_name = st.selectbox(
            "Preferred Course / Branch",
            options=branches,
            format_func=lambda name: branch_labels[name],
        )

        submitted = st.form_submit_button("Find My Colleges", use_container_width=True)

    if not submitted:
        st.info(
            f"Fill in your rank and preferences above, then tap **Find My Colleges**.\n\n"
            f"**How we rate your chances:** we compare your rank against each college's "
            f"actual Round 1, Round 2 and Round 3 cutoffs. If your rank clears Round 1, "
            f"that's a **Strong Chance** - realistically allotted right away. If it only "
            f"clears Round 2, that's **Possible**. If it only clears Round 3, that's "
            f"**Unlikely**. We show the 2 closest-matching colleges in each tier "
            f"(6 total)."
        )
        return

    if not rank:
        st.warning("Please enter your KCET rank.")
        return

    category_code = compose_category(df, base, subcat, is_hk)
    if category_code is None:
        st.error(
            "That combination of category, sub-category and HK-region status "
            "isn't in our data. Please try a different combination."
        )
        return

    tiers, year = predict(df, int(rank), category_code, branch_name, is_hk)
    seat_type = "Kalyana Karnataka" if is_hk else "Rest of Karnataka"

    st.caption(
        f"Comparing your rank against Round 1, 2 and 3 cutoffs for "
        f"{html.escape(expand_branch_label(branch_name))} under category "
        f"**{category_code}** ({seat_type} seats), from KCET {year} (the "
        f"most recent year with a full Round 1-3 dataset)."
    )

    total_results = sum(len(v) for v in tiers.values())
    if total_results == 0:
        st.warning(
            "No colleges offered this branch under this category in any round "
            f"of {year}. Try a different branch or category."
        )
        return

    for tier_name, round_n in TIER_ROUNDS:
        results = tiers[tier_name]
        st.subheader(tier_name)
        st.caption(f"Round {round_n} comparison - {TIER_BLURB[tier_name]}.")
        if not results:
            st.markdown(
                f"_No colleges found for this tier yet "
                f"(no Round {round_n} match, or fewer than "
                f"{RESULTS_PER_TIER} available)._"
            )
            continue
        for result in results:
            render_card(result, int(rank))


if __name__ == "__main__":
    main()
