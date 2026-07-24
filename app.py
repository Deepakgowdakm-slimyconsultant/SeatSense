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
    SUBCAT_LABELS,
    STRONG_BUFFER,
    POSSIBLE_BUFFER,
)

st.set_page_config(page_title="SeatSense", page_icon="🎓", layout="centered")

TIER_STYLE = {
    "Strong Chance": {"bg": "#e6f4ea", "border": "#2e7d32", "text": "#1b5e20"},
    "Possible": {"bg": "#fff8e1", "border": "#c9a227", "text": "#8a6d00"},
    "Unlikely": {"bg": "#fdecea", "border": "#c62828", "text": "#8e1e1e"},
}


@st.cache_data
def get_data():
    return load_data()


def render_card(result, rank):
    tier = result["tier"]
    style = TIER_STYLE[tier]
    college = html.escape(result["college_name"])
    branch = html.escape(result["branch_name"])
    cutoff = result["cutoff_rank"]
    cutoff_str = f"{cutoff:,.1f}" if cutoff % 1 else f"{cutoff:,.0f}"
    rank_str = f"{rank:,}"

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
    Last round's cutoff rank was {cutoff_str} &mdash; your rank is {rank_str}.
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


def main():
    st.title("🎓 SeatSense")
    st.caption("Find engineering colleges in Karnataka that fit your KCET rank.")

    df = get_data()

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
            base_options = available_bases(df)
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

        is_hk = st.toggle(
            "I am eligible for the Hyderabad-Karnataka (371J) reservation",
            value=False,
        )

        branch_name = st.selectbox("Preferred Course / Branch", options=branch_options(df))

        top_n_label = st.radio(
            "How many results to show?",
            options=["Top 5", "Top 10", "Top 15"],
            horizontal=True,
        )
        top_n = int(top_n_label.split()[1])

        submitted = st.form_submit_button("Find My Colleges", use_container_width=True)

    if not submitted:
        st.info(
            f"Fill in your rank and preferences above, then tap **Find My Colleges**.\n\n"
            f"**How we rate your chances:** we compare your rank to each college's most "
            f"recent round cutoff. If your rank is at least {int(STRONG_BUFFER*100)}% better "
            f"(lower) than the cutoff, that's a **Strong Chance**. Within "
            f"{int(POSSIBLE_BUFFER*100)}% either side of the cutoff is **Possible**. "
            f"Well above the cutoff is **Unlikely**."
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

    results, year, round_ = predict(df, int(rank), category_code, branch_name, top_n)

    st.caption(
        f"Based on {html.escape(branch_name)} cutoffs for category **{category_code}** "
        f"from KCET {year} Round {round_} (the most recent round in our data)."
    )

    if not results:
        st.warning(
            "No colleges offered this branch under this category in the latest round. "
            "Try a different branch or category."
        )
        return

    for result in results:
        render_card(result, int(rank))


if __name__ == "__main__":
    main()
