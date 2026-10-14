import pandas as pd
import folium

COURIER_ID = 73
DATA_PATH = "data/cq_d_busiest_day.csv"
OUTPUT_PATH = f"courier_{COURIER_ID}_map.html"

df = pd.read_csv(DATA_PATH)
stops = df[df["courier_id"] == COURIER_ID][["lng", "lat", "order_id", "delivery_time"]].dropna()
stops = stops.sort_values("delivery_time").reset_index(drop=True)

center_lat = stops["lat"].mean()
center_lng = stops["lng"].mean()

m = folium.Map(location=[center_lat, center_lng], zoom_start=13, tiles="OpenStreetMap")

coords = list(zip(stops["lat"], stops["lng"]))
folium.PolyLine(coords, color="blue", weight=2, opacity=0.6, tooltip="Route").add_to(m)

for i, row in stops.iterrows():
    folium.Marker(
        location=[row["lat"], row["lng"]],
        popup=f"Stop {i+1}<br>Order: {row['order_id']}<br>Time: {row['delivery_time']}",
        tooltip=f"Stop {i+1}",
        icon=folium.DivIcon(
            html=f'<div style="background:steelblue;color:white;border-radius:50%;width:22px;height:22px;text-align:center;line-height:22px;font-size:11px;font-weight:bold;border:2px solid white">{i+1}</div>',
            icon_size=(22, 22),
            icon_anchor=(11, 11),
        ),
    ).add_to(m)

m.save(OUTPUT_PATH)
print(f"Map saved to {OUTPUT_PATH} — {len(stops)} stops for courier {COURIER_ID}")
