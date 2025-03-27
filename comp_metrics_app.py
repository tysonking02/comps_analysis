# streamlit run comps_analysis/comp_metrics_app.py

from aggregate_hellodata import *
import streamlit as st
import pandas as pd
import altair as alt
from pathlib import Path
import itertools

dimasset = pd.read_csv('comps_analysis/data/DimAsset.csv')
factunitlatest = pd.read_csv('comps_analysis/data/FactUnitLatest_filtered.csv')

st.header("Revenue Period Quality Analysis")

selected_property = st.selectbox("Select Property", sorted(dimasset['AssetName'].unique()))

time_frame = st.radio("Aggregation Time Frame", ["MoM", "QoQ"])

submit_button = st.button("Submit")

if submit_button:
    
    if Path(f'comps_analysis/data/{selected_property} Comp Metrics.csv').is_file():
        metrics = pd.read_csv(f'comps_analysis/data/{selected_property} Comp Metrics.csv')
    else:
        metrics = get_comp_metrics(selected_property, streamlit=True)
        metrics.to_csv(f"comps_analysis/data/{selected_property} Comp Metrics.csv")

    metrics['date'] = pd.to_datetime(metrics['date'])

    st.subheader(f"{selected_property} vs. Comps")

    metrics_selected = metrics[metrics['property'] == selected_property]

    ymin = metrics['rev_pasf'].min() - 0.2
    ymax = metrics['rev_pasf'].max() + 0.2

    base_colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
               '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']

    # Get unique property list
    properties = metrics['property'].unique().tolist()

    # Build color mapping
    color_mapping = {}
    color_iter = itertools.cycle(base_colors)

    for prop in properties:
        if prop == selected_property:
            color_mapping[prop] = 'black'
        else:
            color_mapping[prop] = next(color_iter)

    # Create scale
    color_scale = alt.Scale(
        domain=list(color_mapping.keys()),
        range=list(color_mapping.values())
    )

    # Unified chart with visual emphasis
    chart = alt.Chart(metrics).mark_line().encode(
        x=alt.X(
            'date:T',
            title='Date',
            axis=alt.Axis(format='%b %Y', tickCount='month', labelAngle=-45)
        ),
        y=alt.Y(
            'rev_pasf:Q',
            scale=alt.Scale(domain=[ymin, ymax]),
            title='Rev PASF'
        ),
        color=alt.Color('property:N', scale=color_scale, legend=alt.Legend(title="Properties")),
        size=alt.condition(
            alt.datum.property == selected_property,
            alt.value(6),  # thicker line for selected
            alt.value(1)   # normal for others
        ),
        opacity=alt.condition(
            alt.datum.property == selected_property,
            alt.value(1.0),
            alt.value(0.8)
        ),
        tooltip=['date', 'property', 'rev_pasf', 'rev_pasf_rank']
    ).properties(
        width=800,
        height=400
    ).interactive()

    st.altair_chart(chart, use_container_width=True)


    metrics_selected.sort_values('date', ascending=True, inplace=True)

    if time_frame == 'MoM':
        metrics_selected['period'] = metrics_selected['date'].dt.to_period('M').dt.to_timestamp()
        metrics_selected['Time Period'] = metrics_selected['period'].dt.strftime('%b %Y')
    elif time_frame == 'QoQ':
        metrics_selected['period'] = metrics_selected['date'].dt.to_period('Q').dt.to_timestamp()
        q = metrics_selected['period'].dt.quarter
        y = metrics_selected['period'].dt.year
        metrics_selected['Time Period'] = ['Q' + str(qq) + ' ' + str(yy) for qq, yy in zip(q, y)]

    # Get the first date of each period
    first_day_df = metrics_selected.sort_values('date').groupby(['period', 'Time Period']).first().reset_index()

    first_day_df['prev_rank'] = first_day_df['rev_pasf_rank'].shift(1)

    def classify_quality(row):
        if pd.isna(row['prev_rank']):
            return None
        if row['rev_pasf_rank'] < row['prev_rank']:
            return 'Good'
        elif row['rev_pasf_rank'] > row['prev_rank']:
            return 'Poor'
        else:
            return 'Neutral'

    first_day_df['period_quality'] = first_day_df.apply(classify_quality, axis=1)

    first_day_df = first_day_df.sort_values('period')[['Time Period', 'rev_pasf_rank', 'prev_rank', 'period_quality']]
    first_day_df.rename(columns={"rev_pasf_rank": "Rev. Rank", "prev_rank": "Prev. Rev. Rank", "period_quality": "Quality"}, inplace=True)

    def highlight_quality(val):
        if val == 'Good':
            return 'color: green; font-weight: bold'
        elif val == 'Poor':
            return 'color: red; font-weight: bold'
        else:
            return ''

    styled_df = (
        first_day_df
        .style
        .format({'Rev. Rank': '{:.0f}', 'Prev. Rev. Rank': '{:.0f}'})
        .applymap(highlight_quality, subset=['Quality'])
    )

    st.subheader(f"{time_frame} Rev PASF Rank for {selected_property}")
    st.dataframe(styled_df)
