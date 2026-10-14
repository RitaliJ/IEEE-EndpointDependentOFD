import csv
import folium

pairs = set()
with open("data/cq_d_busiest_day.csv") as f:
    reader = csv.DictReader(f)
    for row in reader:
        pairs.add((float(row["accept_gps_lat"]), float(row["accept_gps_lng"])))

pairs = list(pairs)
center_lat = sum(p[0] for p in pairs) / len(pairs)
center_lng = sum(p[1] for p in pairs) / len(pairs)

m = folium.Map(location=[center_lat, center_lng], zoom_start=10)
for lat, lng in pairs:
    folium.CircleMarker(
        location=[lat, lng],
        radius=6,
        color="red",
        fill=True,
        fill_opacity=0.8,
        tooltip=f"({lat}, {lng})",
    ).add_to(m)

out = "data/restaurants_map.html"
m.save(out)
print(f"Saved {len(pairs)} restaurants to {out}")
