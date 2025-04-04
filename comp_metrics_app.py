# streamlit run comp_metrics_app.py

import streamlit as st
import pandas as pd
import altair as alt
from pathlib import Path
import itertools
import os

dimasset = pd.read_csv('data/DimAsset.csv')
assetdetailactive = pd.read_csv('data/vw_AssetDetailActive.csv', usecols=['AssetCode', 'ParentAssetName'])

dimasset = dimasset.merge(assetdetailactive, on='AssetCode')

factunitlatest = pd.read_csv('data/FactUnitLatest_filtered.csv')

factaccountgrouptotal = pd.read_csv('data/FactGLAccountGroupTotal_filtered.csv')


st.header("Revenue Period Quality Analysis")

property_list = os.listdir('data/HelloData/comp_metrics')
property_list = [filename.replace(' Comp Metrics.csv', '') for filename in property_list]

selected_property = st.selectbox("Select Property", sorted(property_list))
selected_asset_code = dimasset[dimasset['ParentAssetName'] == selected_property]['AssetCode'].iloc[0]

time_frame = st.radio("Aggregation Time Frame", ["MoM", "QoQ"])

submit_button = st.button("Submit")

if submit_button:
    
    if Path(f'data/HelloData/comp_metrics/{selected_property} Comp Metrics.csv').is_file():
        metrics = pd.read_csv(f'data/HelloData/comp_metrics/{selected_property} Comp Metrics.csv')
    else:
        st.write(f"No data for {selected_property}")

    metrics['date'] = pd.to_datetime(metrics['date'])

    metrics = metrics[metrics['date'] >= pd.to_datetime('2024-01-01')]

    mean_metrics = metrics.groupby('date').agg(rev_pasf_avg=('rev_pasf', 'mean')).reset_index()

    metrics = pd.merge(metrics, mean_metrics, on="date")

    mean_metrics['property'] = 'Mean'

    mean_metrics = mean_metrics.rename(columns={"rev_pasf_avg": "rev_pasf"})

    metrics = pd.concat([metrics, mean_metrics])

    def custom_order(prop):
        if prop == selected_property:
            return (0, "")
        elif prop == "Mean":
            return (1, "")
        else:
            return (2, prop.lower())
        
    metrics['sort_order'] = metrics['property'].apply(custom_order)
    metrics = metrics.sort_values(by='sort_order').drop(columns='sort_order')

    st.subheader(f"{selected_property} vs. Comps")

    ymin = metrics['rev_pasf'].min() - 0.2
    ymax = metrics['rev_pasf'].max() + 0.2

    base_colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
                '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']

    # Get unique property list
    properties = metrics['property'].unique().tolist()

    # Build color mapping: use red for "Mean", black for selected_property, and cycle base_colors for others
    color_mapping = {}
    color_iter = itertools.cycle(base_colors)

    for prop in properties:
        if prop == "Mean":
            color_mapping[prop] = "red"
        elif prop == selected_property:
            color_mapping[prop] = "black"
        else:
            color_mapping[prop] = next(color_iter)

    # Create scale
    color_scale = alt.Scale(
        domain=list(color_mapping.keys()),
        range=list(color_mapping.values())
    )

    acquisition_date = dimasset[dimasset['AssetCode'] == selected_asset_code]['AcquisitionDate'].iloc[0]

    # Create the Altair chart with conditional encodings
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
            (alt.datum.property == selected_property) | (alt.datum.property == 'Mean'),
            alt.value(5),  # thicker line for selected property or Mean
            alt.value(1)   # normal thickness for others
        ),
        # If property is "Mean", use a dashed stroke, otherwise solid
        # strokeDash=alt.condition(
        #     (alt.datum.property == "Mean"),
        #     alt.value([5, 3]),  # dashed for "Mean"
        #     alt.value([0])      # solid for others
        # ),
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

    if acquisition_date >= "2024-01-01":
        label_data = pd.DataFrame({
            'date': [acquisition_date],
            'label': ['Acquisition Date'],
            'y_pos': [ymax - 0.1]
        })

        rule = alt.Chart(label_data).mark_rule(
            strokeDash=[6, 4], color='black'
        ).encode(
            x='date:T'
        )

        label = alt.Chart(label_data).mark_text(
            align='left',
            dx=6,
            angle=0,
            fontSize=12,
            fontWeight='bold'
        ).encode(
            x='date:T',
            y='y_pos:Q',
            text='label'
        )

        # Combine chart with rule and label
        chart = (chart + rule + label).interactive()

    st.altair_chart(chart, use_container_width=True)


    income_metrics = factaccountgrouptotal[factaccountgrouptotal['AssetCode'] == selected_asset_code]

    month_metrics = income_metrics
    month_metrics["month"] = pd.to_datetime(income_metrics["MonthID"], format='%Y%m')

    quarter_metrics = income_metrics
    income_metrics["quarter"] = income_metrics["month"].dt.to_period('Q').dt.to_timestamp()
    quarter_metrics = income_metrics.groupby('quarter').agg(
        Amount=('Amount', 'sum'),
        count=('month', 'count')
    ).reset_index()

    quarter_metrics = quarter_metrics[quarter_metrics['count'] == 3]

    metrics.sort_values('date', ascending=True, inplace=True)

    if time_frame == 'MoM':
        metrics['period'] = metrics['date'].dt.to_period('M').dt.to_timestamp()
        metrics = metrics.merge(month_metrics, left_on="period", right_on="month", how="left")
        metrics['Time Period'] = metrics['period'].dt.strftime('%b %Y')
    elif time_frame == 'QoQ':
        metrics['period'] = metrics['date'].dt.to_period('Q').dt.to_timestamp()
        metrics = metrics.merge(quarter_metrics, left_on="period", right_on="quarter", how="left")
        q = metrics['period'].dt.quarter
        y = metrics['period'].dt.year
        metrics['Time Period'] = ['Q' + str(qq) + ' ' + str(yy) for qq, yy in zip(q, y)]

    # Get the first date of each period
    avg_metrics = metrics.sort_values('date').groupby(['property', 'period', 'Time Period']).agg({
        "rev_pasf": "mean",
        "rev_pasf_avg": "mean",
        "Amount": "first"
    }).reset_index()


    avg_metrics['rev_pasf_rank'] = avg_metrics.groupby(['period', 'Time Period'])['rev_pasf'].rank(method='dense', ascending=False)

    avg_metrics['prev_rank'] = avg_metrics['rev_pasf_rank'].shift(1)

    avg_metrics['rev_pasf_vs_avg'] = avg_metrics['rev_pasf'] - avg_metrics['rev_pasf_avg']
    avg_metrics['prev_rev_pasf_vs_avg'] = avg_metrics['rev_pasf_vs_avg'].shift(1)

    avg_metrics['prev_income'] = avg_metrics['Amount'].shift(1)
    avg_metrics['income_growth'] = avg_metrics['Amount'] - avg_metrics['prev_income']

    avg_metrics = avg_metrics[avg_metrics['property'] == selected_property]

    def classify_quality(row):
        if pd.isna(row['prev_rank']):
            return None
        if row['rev_pasf_rank'] < row['prev_rank']:
            return 'Good'
        elif row['rev_pasf_rank'] > row['prev_rank']:
            return 'Poor'
        else:
            if row['rev_pasf_vs_avg'] < row['prev_rev_pasf_vs_avg']:
                return 'Good'
            elif row['rev_pasf_vs_avg'] > row['prev_rev_pasf_vs_avg']:
                return 'Poor'
            return 'Neutral'

    avg_metrics['period_quality'] = avg_metrics.apply(classify_quality, axis=1)

    avg_metrics = avg_metrics.sort_values('period')[['Time Period', 'rev_pasf_rank', 'prev_rank', 'rev_pasf', 'rev_pasf_vs_avg', 'period_quality', 'income_growth']]
    avg_metrics.rename(columns={"rev_pasf": "RevPASF", "rev_pasf_vs_avg": "RevPASF vs Avg.", "rev_pasf_rank": "Rank", "prev_rank": "T1 Rank", "period_quality": "Quality", "income_growth": "Rental Income Growth/Decline"}, inplace=True)

    def highlight_quality(val):
        if val == 'Good':
            return 'color: green; font-weight: bold'
        elif val == 'Poor':
            return 'color: red; font-weight: bold'
        else:
            return ''
        
    def highlight_growth(val):
        try:
            if val > 0:
                return 'color: green; font-weight: bold'
            elif val < 0:
                return 'color: red; font-weight: bold'
        except:
            pass
        return ''

    styled_df = (
        avg_metrics
        .style
        .format({
            'RevPASF': '${:.2f}',
            'RevPASF vs Avg.': '${:.2f}',
            'Rank': '{:.0f}',
            'T1 Rank': '{:.0f}',
            'Rental Income Growth/Decline': lambda x: f"${abs(x):,.0f}"
        })
        .applymap(highlight_quality, subset=['Quality'])
        .applymap(highlight_growth, subset=['Rental Income Growth/Decline'])
    )

    st.subheader(f"{time_frame} Rev / Avail Sqft. Rank for {selected_property}")
    st.dataframe(styled_df)

    with st.expander("Period Quality Breakdown"):
        st.markdown(f"""
        - **Rank Improves (e.g., 2 → 1):**  
        Period quality is **Good**

        - **Rank Declines (e.g., 1 → 2):**  
        Period quality is **Bad**

        - **Rank Stays the Same:**  
        Compare the **RevPASf {time_frame} change** to the **Comp Set Mean**:
            - If RevPASf increased relative to the Comp Mean → **Good**  
            - If RevPASf decreased relative to the Comp Mean → **Bad**
        """)