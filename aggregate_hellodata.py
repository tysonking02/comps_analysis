import requests
import pandas as pd
import warnings
import streamlit as st

warnings.filterwarnings("ignore", category=pd.errors.SettingWithCopyWarning)

## Initialize Hello Data API

api_key = "f3898958-b76a-4a47-816f-0294f0c5103d"

BASE_URL = "https://api.hellodata.ai"

HEADERS = {
    "x-api-key": api_key
}

dimasset = pd.read_csv('data/DimAsset.csv')
factunitlatest = pd.read_csv('data/FactUnitLatest_filtered.csv')

# region Helper Functions

def find_lat_lon(property):
    """Function to get latitude and longitude for a given property."""
    matches = dimasset[dimasset['AssetName'].str.contains(property, case=False, regex=False)].dropna(subset=['Latitude', 'Longitude'])

    if matches.empty:
        raise ValueError(f"No match found for property: {property}")

    lat, lon = matches[['Latitude', 'Longitude']].iloc[0]

    if pd.isna(lat) or pd.isna(lon):
        raise ValueError(f"Latitude or Longitude missing for property: {property}")

    return lat, lon


def fetch_property_data(property, lat=None, lon=None, zip_code=None):
    """Function to fetch property data using lat/lon or zip code.
       For Cortland assets, use lat/lon, else use zip code"""
    
    # Create the querystring dictionary
    querystring = {"q": property}
    
    # Only add lat and lon if they are provided
    if lat is not None and lon is not None:
        querystring["lat"] = lat
        querystring["lon"] = lon
        querystring["max_distance"] = 0.1

    if zip_code is not None:
        querystring['zip_code'] = zip_code
    
    # Make the API request
    response = requests.get(f"{BASE_URL}/property/search", headers=HEADERS, params=querystring)
    if response.status_code != 200:
        raise ValueError(f"HTTP request failed with status code {response.status_code}: {response.text}")

    try:
        return response.json()
    except ValueError as e:
        raise ValueError(f"Error parsing JSON response from property search: {e}")
    
def fetch_property_details(property_id):
    """Function to fetch details for a specific property."""
    url = f"{BASE_URL}/property/{property_id}"

    response = requests.get(url, headers=HEADERS)
    if response.status_code != 200:
        raise ValueError(f"HTTP request failed with status code {response.status_code}: {response.text}")

    try:
        return response.json()
    except ValueError as e:
        raise ValueError(f"Error parsing JSON response from property details: {e}")

def fetch_comparables(property_details):
    """Function to fetch HelloData comparables for a given property."""
    url = f"{BASE_URL}/property/comparables"
    payload = {"subject": property_details}

    try:
        response = requests.post(url, json=payload, headers=HEADERS)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"HTTP request error while fetching comparables: {e}")
        return None
    except ValueError:
        print("Error parsing JSON response from comparables.")
        return None

def get_comp_details(property):
    """Final function to get the comparables data for a property."""
    try:
        lat, lon = find_lat_lon(property)
    except ValueError as e:
        raise ValueError(f"Error in find_lat_lon: {e}")

    # Fetch property data
    property_data = fetch_property_data(property, lat, lon)
    if not property_data or not isinstance(property_data, list):
        raise ValueError(f"Unexpected response format from property search: {property_data}")

    try:
        property_id = property_data[0].get("id")
        if not property_id:
            raise KeyError("Missing 'id' in property response.")
    except (IndexError, KeyError) as e:
        raise ValueError(f"Error extracting property ID: {e}")

    # Fetch property details
    property_details = fetch_property_details(property_id)
    if not property_details:
        raise ValueError("Failed to fetch property details.")

    # Fetch comparables
    response_data = fetch_comparables(property_details)
    if not response_data or 'comparables' not in response_data or not isinstance(response_data['comparables'], list):
        raise ValueError(f"Unexpected response format for comparables: {response_data}")

    try:
        comps = pd.json_normalize(response_data['comparables'])
    except Exception as e:
        raise ValueError(f"Error normalizing comparables data: {e}")

    return comps

# endregion    

# region Create and Expand Unit History from API

def get_unit_history(property_details):
    try:
        if not isinstance(property_details, dict):
            raise TypeError(f"Expected dictionary for property_details, got {type(property_details)}")

        history_df = pd.DataFrame()

        building_name = property_details.get('building_name')
        availability = property_details.get('building_availability', [])
        num_units = property_details.get('number_units', 0)

        for unit_id, cur_availability in enumerate(availability):
            if not isinstance(cur_availability, dict):
                print(f"Skipping invalid unit data at index {unit_id}: {type(cur_availability)}")
                continue

            try:
                unit_name = cur_availability.get('unit_name')
                unit_group = f"{cur_availability.get('bed', 0)}x{cur_availability.get('bath', 0)}"

                half_baths = cur_availability.get('partial_bath', 0)
                if half_baths == 1:
                    unit_group += ".5"

                sqft = cur_availability.get('sqft')

                for pricing_id, cur_history in enumerate(cur_availability.get('history', [])):
                    if not isinstance(cur_history, dict):
                        print(f"Skipping invalid history data at index {pricing_id}: {type(cur_history)}")
                        continue

                    try:
                        effective_price = cur_history.get('effective_price')
                        from_date = cur_history.get('from_date')
                        to_date = cur_history.get('to_date')

                        cur_history_df = pd.DataFrame(
                            {"building_name": building_name,
                             "unit_name": unit_name,
                             "unit_group": unit_group,
                             "sqft": sqft,
                             "effective_price": effective_price,
                             "from_date": from_date,
                             "to_date": to_date}, index=[0]
                        )

                        history_df = pd.concat([history_df, cur_history_df])

                    except Exception as e:
                        print(f"Error processing history at index {pricing_id}: {e}")

            except Exception as e:
                print(f"Error processing unit at index {unit_id}: {e}")

        # Convert dates and handle invalid dates
        history_df["from_date"] = pd.to_datetime(history_df["from_date"], errors='coerce')
        history_df["to_date"] = pd.to_datetime(history_df["to_date"], errors='coerce')

        # Sort and calculate leased rate
        history_df.sort_values(by=["unit_name", "from_date"], inplace=True)
        history_df["next_from_date"] = history_df.groupby("unit_name")["from_date"].shift(-1)
        history_df["leased_rate"] = (history_df["to_date"] + pd.Timedelta(days=1) < history_df["next_from_date"]) | (history_df['next_from_date'].isna())

        # Expand rows for each date in range
        expanded_history = []
        for _, row in history_df.iterrows():
            try:
                date_range = pd.date_range(row["from_date"], row["to_date"])
                for single_date in date_range:
                    expanded_history.append({
                        "building_name": row["building_name"],
                        "unit_name": row["unit_name"],
                        "unit_group": row["unit_group"],
                        "sqft": row['sqft'],
                        "effective_price": row["effective_price"],
                        "date": single_date.strftime("%m/%d/%Y"),
                        "leased_rate": row["leased_rate"] if single_date == row["to_date"] else False
                    })
            except Exception as e:
                print(f"Error expanding history for row {row['unit_name']}: {e}")

        # Create new DataFrame
        expanded_history_df = pd.DataFrame(expanded_history)

        return expanded_history_df, num_units
    
    except Exception as e:
        print(f"Error processing property details: {e}")
        return pd.DataFrame(), 0

# endregion

# region Calculate Net Leased

def get_net_leased(history_df, num_units):
    history_df = history_df.copy()
    history_df['date'] = pd.to_datetime(history_df['date'])

    if history_df['building_name'].nunique() != 1:
        raise ValueError("History DataFrame must contain exactly one unique building_name")

    building = history_df['building_name'].unique()[0]

    first_date = history_df['date'].min()
    last_date = history_df['date'].max()
    date_range = pd.date_range(first_date, last_date)

    net_leased_df = pd.DataFrame()

    for date in date_range:
        num_vacancies = len(history_df[history_df['date'] == date])

        vacancy_rate = num_vacancies / num_units

        net_leased_df = pd.concat([
            net_leased_df,
            pd.DataFrame({"property": building, "date": date, "net_leased": 1 - vacancy_rate}, index=[0])
        ])

    return net_leased_df

def get_comp_net_leased(property, streamlit=False, status=None):
    lat, lon = find_lat_lon(property=property)
    property_data = fetch_property_data(property=property, lat=lat, lon=lon)

    if streamlit:
        status.text(f"Finding net leased for {property}...")
    else:
        print(f"Finding net leased for {property}...")

    if not property_data:
        raise RuntimeError(f"No property data found for {property}")

    comps = get_comp_details(property=property)

    property_id = property_data[0].get("id")
    property_details = fetch_property_details(property_id)

    history_df, num_units = get_unit_history(property_details)
    
    net_leased_df = get_net_leased(history_df, num_units)

    for i in range(len(comps)):
        building_name = comps['building_name'][i]
        zip_code = comps['zip_code'][i]

        if streamlit:
            status.text(f"Finding net leased for {building_name}...")
        else:
            print(f"Finding net leased for {building_name}...")

        property_data = fetch_property_data(property=building_name, zip_code=zip_code)
        if not property_data:
            raise RuntimeError(f"No property data found for comp {building_name}")

        property_id = property_data[0].get("id")
        property_details = fetch_property_details(property_id=property_id)

        history_df, num_units = get_unit_history(property_details=property_details)

        if len(history_df) == 0:
            next 

        net_leased_df = pd.concat([
            net_leased_df,
            get_net_leased(history_df=history_df, num_units=num_units)
        ])

    net_leased_df = net_leased_df[net_leased_df['date'] >= '2024-01-01']
    
    return net_leased_df

# endregion

# region Predict Unit Mix

def predict_unit_mix(history_df):

    unit_mix = history_df.groupby('unit_group').agg(
        average_sqft=('sqft', 'mean'),
        count=('unit_name', 'nunique'),
    ).reset_index()

    unit_mix['prop'] = unit_mix['count'] / sum(unit_mix['count'])

    return(unit_mix)

# endregion

# region Get Cortland Unit Mix

def get_cortland_mix(AssetCode):

    unique_units = factunitlatest[factunitlatest['AssetCode'] == AssetCode]

    unit_mix = unique_units.groupby('unit_group').agg(
        count=('osl_UnitNumber', 'nunique'),
    ).reset_index()

    unit_mix['prop'] = unit_mix['count'] / sum(unit_mix['count'])

    return(unit_mix)


# endregion

# region Aggregate Rolling Rent Roll Estimates

def get_rolling_rates(unit_history, building_name, cortland_mix):
    signed_leases = unit_history[unit_history['leased_rate'] == True]

    signed_leases['date'] = pd.to_datetime(signed_leases['date'])

    rolling_rates = pd.DataFrame()

    cortland_mix_dict = cortland_mix.set_index('unit_group')['prop'].to_dict()
    comp_mix_dict = predict_unit_mix(unit_history).set_index('unit_group')['prop'].to_dict()

    first_date = signed_leases['date'].min()
    last_date = signed_leases['date'].max()

    date_range = pd.date_range(first_date, last_date)

    for i in date_range:
        applicable_leases = (
            signed_leases[
                (signed_leases['date'] <= i)
            ]
            .dropna(subset=['effective_price'])
            .groupby(["unit_name", "unit_group"], as_index=False)
            .last()
        )

        if not applicable_leases.empty:
            applicable_leases['cortland_prop'] = applicable_leases['unit_group'].map(cortland_mix_dict)
            applicable_leases['comp_prop'] = applicable_leases['unit_group'].map(comp_mix_dict)

            applicable_leases['adj_effective_price'] = (applicable_leases['effective_price'] * applicable_leases['cortland_prop']) / (applicable_leases['comp_prop'])

            sqft_sum = applicable_leases['sqft'].sum()
            adj_avg_rent_per_sqft = applicable_leases['adj_effective_price'].sum() / sqft_sum if sqft_sum > 0 else None

            cur_rolling_rates = pd.DataFrame({
                'property': [building_name],
                'date': [i],
                'avg_rent_roll': [applicable_leases['effective_price'].mean()],
                'avg_rent_per_sqft': [adj_avg_rent_per_sqft]
            })

            rolling_rates = pd.concat([rolling_rates, cur_rolling_rates], ignore_index=True)

    if len(rolling_rates) == 0:
        return pd.DataFrame()

    return rolling_rates.sort_values(by="date", ascending=True).reset_index(drop=True)

def get_comp_rolling_rates(property, streamlit=False, status=None):

    asset_code = dimasset[dimasset['AssetName'].str.contains(property, case=False, regex=False)]['AssetCode'].iloc[0]
    cortland_mix = get_cortland_mix(asset_code)

    comps = get_comp_details(property)
    rolling_rates_df = pd.DataFrame()

    building_name = property
    lat, lon = find_lat_lon(building_name)

    if streamlit:
        status.text(f"Finding rates for {property}...")
    else:
        print(f"Finding rates for {property}...")

    try:
        property_data = fetch_property_data(building_name, lat=lat, lon=lon)

        if not property_data:
            raise RuntimeError(f"Failed to fetch property data for {building_name}")

        property_id = property_data[0].get("id")
        property_details = fetch_property_details(property_id)
        unit_history, num_units = get_unit_history(property_details)

        cur_rolling_rates = get_rolling_rates(unit_history, building_name, cortland_mix)
        rolling_rates_df = pd.concat([rolling_rates_df, cur_rolling_rates])

    except Exception as e:
        raise RuntimeError(f"Error getting details for property {building_name}: {e}")

    for i in range(len(comps)):
        building_name = comps['building_name'][i]
        zip_code = comps['zip_code'][i]

        if streamlit:
            status.text(f"Finding rates for {building_name}...")
        else:
            print(f"Finding rates for {building_name}...")

        try:
            property_data = fetch_property_data(building_name, zip_code=zip_code)

            if not property_data:
                raise RuntimeError(f"Failed to fetch property data for {building_name}")

            property_id = property_data[0].get("id")
            property_details = fetch_property_details(property_id)
            unit_history, num_units = get_unit_history(property_details)

            cur_rolling_rates = get_rolling_rates(unit_history, building_name, cortland_mix)

            rolling_rates_df = pd.concat([rolling_rates_df, cur_rolling_rates])

        except Exception as e:
            raise RuntimeError(f"Error getting rates for {building_name}: {e}")

    return rolling_rates_df

# endregion

# region Aggregate Metrics from Net Leased and Rent Roll

def get_comp_metrics(property, streamlit=False, status=None):

    if streamlit:
        status = st.empty()

    rolling_rates = get_comp_rolling_rates(property, streamlit, status)
    print("")
    net_leased = get_comp_net_leased(property, streamlit, status)

    metrics = pd.merge(left=rolling_rates, right=net_leased, on=['property', 'date'])
    metrics = metrics[['property', 'date', 'avg_rent_per_sqft', 'net_leased']]

    metrics['rev_pasf'] = metrics['avg_rent_per_sqft'] * metrics['net_leased']

    metrics['rev_pasf_rank'] = metrics.groupby('date')['rev_pasf'].rank(method='dense', ascending=False)
    
    metrics['year_month'] = metrics['date'].dt.to_period('M').astype(str)
    metrics['quarter'] = 'Q' + metrics['date'].dt.quarter.astype(str) + ' ' + metrics['date'].dt.year.astype(str)

    return metrics

# endregion

def main():

    property = "1000 Spalding"

    metrics = get_comp_metrics(property)

    metrics.to_csv(f"data/{property} Comp Metrics.csv")


if __name__ == "__main__":
    main()