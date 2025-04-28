import pandas as pd
import os

comp_metrics_locs = os.listdir('data/HelloData/comp_metrics')

dimasset = pd.read_csv('data/DimAsset.csv')
assetdetailactive = pd.read_csv('data/vw_AssetDetailActive.csv', usecols=['AssetCode', 'ParentAssetName', 'EmpRevenueManager'])

dimasset = dimasset.merge(assetdetailactive, on='AssetCode')

factunitlatest = pd.read_csv('data/FactUnitLatest.csv')

factaccountgrouptotal = pd.read_csv('data/FactGLAccountGroupTotal.csv')
factaccountgrouptotal['date'] = pd.to_datetime(factaccountgrouptotal['MonthID'].astype(str) + '01', format='%Y%m%d')

markets = pd.read_csv('data/markets.csv')
market_list = sorted(markets['market'].unique())

rm_inputs = pd.read_csv('data/baseline_rent_rm_input.csv')

comp_metrics = pd.DataFrame()

for i in range(len(comp_metrics_locs)):

    file = comp_metrics_locs[i]
    property_name = file.removesuffix(' Comp Metrics.csv')
    
    selected_asset_code = dimasset[dimasset['ParentAssetName'] == property_name]['AssetCode'].iloc[0]

    path = f"data/HelloData/comp_metrics/{comp_metrics_locs[i]}"
    
    cur_comp_metrics = pd.read_csv(path)
    cur_comp_metrics['ref_property'] = property_name
    cur_comp_metrics['date'] = pd.to_datetime(cur_comp_metrics['date'])

    cur_comp_metrics = cur_comp_metrics[cur_comp_metrics['date'] >= pd.to_datetime('2024-01-01')]

    valid_props = cur_comp_metrics['property'].value_counts()
    valid_props = valid_props[valid_props >= 120].index
    cur_comp_metrics = cur_comp_metrics[cur_comp_metrics['property'].isin(valid_props)]

    mean_metrics = cur_comp_metrics.groupby('date').agg(rev_pasf_avg=('rev_pasf', 'mean')).reset_index()

    cur_comp_metrics = pd.merge(cur_comp_metrics, mean_metrics, on="date")

    mean_metrics['property'] = 'Mean'

    mean_metrics = mean_metrics.rename(columns={"rev_pasf_avg": "rev_pasf"})

    cur_comp_metrics = pd.concat([cur_comp_metrics, mean_metrics])
        
    # Get unique property list
    properties = cur_comp_metrics['property'].unique().tolist()

    income_metrics = factaccountgrouptotal[factaccountgrouptotal['AssetCode'] == selected_asset_code]

    cur_comp_metrics['period'] = cur_comp_metrics['date'].dt.to_period('M').dt.to_timestamp()
    cur_comp_metrics['Time Period'] = cur_comp_metrics['period'].dt.strftime('%b %Y')

    # Get the first date of each period
    avg_metrics = cur_comp_metrics.sort_values('date').groupby(['property', 'period', 'Time Period']).agg({
        "rev_pasf": "mean",
        "rev_pasf_avg": "mean",
    }).reset_index()

    avg_metrics['period'] = pd.to_datetime(avg_metrics['period'])

    avg_metrics = pd.merge(avg_metrics, income_metrics, left_on='period', right_on='date')

    avg_metrics['rev_pasf_rank'] = avg_metrics.groupby(['period', 'Time Period'])['rev_pasf'].rank(method='dense', ascending=False)

    avg_metrics['prev_rank'] = avg_metrics['rev_pasf_rank'].shift(1)

    avg_metrics['rev_pasf_vs_avg'] = avg_metrics['rev_pasf'] - avg_metrics['rev_pasf_avg']
    avg_metrics['prev_rev_pasf_vs_avg'] = avg_metrics['rev_pasf_vs_avg'].shift(1)

    def classify_quality(row):
        if pd.isna(row['prev_rank']):
            return None
        if row['rev_pasf_rank'] < row['prev_rank']:
            return 'Good'
        elif row['rev_pasf_rank'] > row['prev_rank']:
            return 'Poor'
        else:
            if row['rev_pasf_vs_avg'] > row['prev_rev_pasf_vs_avg'] * 1.05:
                return 'Good'
            elif row['rev_pasf_vs_avg'] < row['prev_rev_pasf_vs_avg'] * .95:
                return 'Poor'
            return 'Neutral'

    avg_metrics['period_quality'] = avg_metrics.apply(classify_quality, axis=1)

    rm_name = dimasset[dimasset['ParentAssetName'] == property_name]['EmpRevenueManager'].iloc[0]
    avg_metrics['Revenue Manager'] = rm_name

    avg_metrics = avg_metrics.sort_values('period')[['property', 'Revenue Manager', 'Time Period', 'rev_pasf_rank', 'prev_rank', 'rev_pasf', 'rev_pasf_vs_avg', 'period_quality', 'ActualAmount', 'BudgetAmount']]
    avg_metrics.rename(columns={"property": "Property", "Time Period": "Month", "rev_pasf": "RevPASF", "rev_pasf_vs_avg": "RevPASF vs Avg.", "rev_pasf_rank": "Rank", "prev_rank": "T1 Rank", "period_quality": "Quality"}, inplace=True)
    avg_metrics['Ref Property'] = property_name

    avg_metrics = avg_metrics[avg_metrics['Property'] != 'Mean']

    comp_metrics = pd.concat([comp_metrics, avg_metrics])

comp_metrics.to_csv('data/total_comp_metrics.csv')

comp_metrics = pd.read_csv('data/total_comp_metrics.csv')
comp_metrics.drop_duplicates(subset=['Property', 'Month'])

q4_2024_comp_metrics = comp_metrics[comp_metrics['Month'].isin(['Oct 2024', 'Nov 2024', 'Dec 2024'])]
q1_2025_comp_metrics = comp_metrics[comp_metrics['Month'].isin(['Jan 2025', 'Feb 2025', 'Mar 2025'])]

q4_aggregated = (
    q4_2024_comp_metrics
    .groupby(['Property', 'Revenue Manager', 'Ref Property'], as_index=False)
    .agg({
        'RevPASF': 'mean',
        'RevPASF vs Avg.': 'mean',
        'ActualAmount': 'sum',
        'BudgetAmount': 'sum'
    })
)

q4_aggregated['Rank'] = (
    q4_aggregated
    .groupby('Ref Property')['RevPASF']
    .rank(method='dense', ascending=False)
    .astype(int)
)

q1_aggregated = (
    q1_2025_comp_metrics
    .groupby(['Property', 'Revenue Manager', 'Ref Property'], as_index=False)
    .agg({
        'RevPASF': 'mean',
        'RevPASF vs Avg.': 'mean',
        'ActualAmount': 'sum',
        'BudgetAmount': 'sum'
    })
)

q1_aggregated['Rank'] = (
    q1_aggregated
    .groupby('Ref Property')['RevPASF']
    .rank(method='dense', ascending=False)
    .astype(int)
)

q1_merged = q1_aggregated.merge(
    q4_aggregated[['Property', 'Ref Property', 'Rank', 'RevPASF', 'RevPASF vs Avg.']],
    on=['Property', 'Ref Property'],
    how='left',
    suffixes=('', '_T1')
)

# Rename the Q4 rank column to T1 Rank
q1_merged = q1_merged.rename(columns={'Rank_T1': 'T1 Rank', 'RevPASF_T1': 'T1 RevPASF', 'RevPASF vs Avg._T1': 'T1 RevPASF vs Avg.'})

def determine_period_quality(row):
    if row['Rank'] < row['T1 Rank']:
        return 'Good'
    elif row['Rank'] > row['T1 Rank']:
        return 'Poor'
    else:  # Rank stayed the same
        if row['RevPASF vs Avg.'] > row['T1 RevPASF vs Avg.'] * 1.05:
            return 'Good'
        elif row['RevPASF vs Avg.'] < row['T1 RevPASF vs Avg.'] * 0.95:
            return 'Poor'
        else:
            return 'Neutral'
        
q1_merged['Q1 Performance'] = q1_merged.apply(determine_period_quality, axis=1)

q1_merged = q1_merged[q1_merged['Property'] == q1_merged['Ref Property']]

q1_merged['Rental Income vs. Budget'] = q1_merged['ActualAmount'] - q1_merged['BudgetAmount']

q1_merged = pd.merge(q1_merged, markets, left_on='Property', right_on='property')

q1_merged = q1_merged[['Property', 'market', 'Revenue Manager', 'Q1 Performance', 'Rank', 'T1 Rank', 'RevPASF', 'T1 RevPASF', 'RevPASF vs Avg.', 'T1 RevPASF vs Avg.', 'Rental Income vs. Budget']]

q1_merged.to_csv('data/q1_comp_metrics.csv')