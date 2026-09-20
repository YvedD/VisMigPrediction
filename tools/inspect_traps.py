from bsi.weather_service import WeatherManagerUtils
print('Loaded 16-traps intervals:')
for item in WeatherManagerUtils._load_16_traps_mapping():
    print(item)
# Also test some degree samples
tests = [285, 300, 304, 309, 316, 324]
print('\nTest mapping:')
for t in tests:
    print(t, '->', WeatherManagerUtils.deg_to_16_wind_label(t))
