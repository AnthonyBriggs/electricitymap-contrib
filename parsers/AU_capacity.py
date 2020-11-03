#!/usr/bin/env python3

"""Standalone script to generate new Australian capacities for pasting into config/zones.json.

Currently this is just printed; skipping automatically updating capacities for now
    (it'll only need to be done every once in a while, not every five minutes)"""

from collections import defaultdict
import datetime as dt
import decimal
import json
import os
import requests


DEBUG = False
def debug(*strings):
    if DEBUG:
        print(*strings)

# 'AUS-NSW': 'NSW1' --> 'NSW1': 'AUS-NSW'
PRICE_MAPPING_DICTIONARY = {
    'AUS-NSW': 'NSW1',
    'AUS-QLD': 'QLD1',
    'AUS-SA': 'SA1',
    'AUS-TAS': 'TAS1',
    'AUS-VIC': 'VIC1',
    'AUS-WA': 'WA1'
}
zone_map = {v: k for k, v in PRICE_MAPPING_DICTIONARY.items()}

# Rounded to 4 decimal places; 12-14 seemed excessive?
STATE_BOUNDING_BOXES = {
    'NSW1': [[148.2695, -36.4196], [149.9044, -34.6395]],
    'NT1': [[128.5001, -26.4999], [138.5002, -10.4684]],
    'QLD1': [[137.5002, -29.6706], [154.0488, -8.7402]],
    'SA1': [[128.5001, -38.5706], [141.5001, -25.4999]],
    'TAS1': [[143.3372, -44.1413], [148.9845, -39.0715]],
    'VIC1': [[140.4671, -39.645], [150.4721, -33.4865]],
    'WA1': [[112.4194, -35.6379], [129.5001, -13.2236]],
}

# This is common data across all zones
ZONE_BOILERPLATE = {
    "contributors": [
        "https://github.com/brandongalbraith",
        "https://github.com/jarek",
        "https://github.com/corradio",
        "https://github.com/AnthonyBriggs"],
    "flag_file_name": "au.png",
    "parsers": {
        "price": "AU.fetch_price",
        "production": "AU.fetch_production"
    },
    # Looks like we're expecting datetimes to be in UTC
    "timezone": None
}

class OpenNEMZone:
    def __init__(self, zone):
        self.zone = zone
        self.bounding_box = [[None, None], [None, None]]  # SW, NE box
        self.capacity = defaultdict(decimal.Decimal)  # {"solar": 1234, ...}

    def __repr__(self):
        return f"<OpenNEMZone name='{self.zone}'>"

    def update_from_facility_data(self, data):
        """ """
        debug(f"Adding facility {data['station_id']}")
        self.update_capacity(data['duid_data'])
        # I don't think we want to do this automatically
        # I suspect it's actually geographical info for the map UI
        #self.update_bounds(data['location'])

    def update_bounds(self, location_data):
        """Expand our bounds if the facility lies outside them."""
        debug(location_data)
        # latitude is N/S, longitude is E/W
        latitude = location_data['latitude']
        if latitude is not None:
            if self.bounding_box[0][1] is None or latitude < self.bounding_box[0][1]:
                self.bounding_box[0][1] = latitude
            if self.bounding_box[1][1] is None or latitude > self.bounding_box[1][1]:
                self.bounding_box[1][1] = latitude
        
        longitude = location_data['longitude']
        if longitude is not None:
            if self.bounding_box[0][0] is None or longitude < self.bounding_box[0][0]:
                self.bounding_box[0][0] = longitude
            if self.bounding_box[1][0] is None or longitude > self.bounding_box[1][0]:
                self.bounding_box[1][0] = longitude

    def update_capacity(self, duid_data):
        """DUID data is a list of generators at a site, there can be more than one
        eg. 
            {'SHGEN': {'fuel_tech': 'hydro', 'registered_capacity': 240.0},
             'SHPUMP': {'fuel_tech': 'pumps', 'registered_capacity': 240.0}}
         OR {'HPRG1': {'fuel_tech': 'battery_discharging', 'registered_capacity': 100.0}, 
             'HPRL1': {'fuel_tech': 'battery_charging', 'registered_capacity': 120.0}}"""
        debug(duid_data)
        for gen_code, gen_info in duid_data.items():
            gen_type = gen_info.get('fuel_tech', None)
            if gen_type is None:
                # No fuel tech at some sites, just an empty {}
                continue
            if gen_type == 'battery_charging' or gen_type == 'pumps':
                # power consumer, not generator
                continue
            if gen_type.startswith('gas_'): # opennem has ocgt, ccgt, etc.
                gen_type = 'gas'
            if gen_type == 'battery_discharging':
                gen_type = 'battery storage'
            if gen_type.startswith('bioenergy_'):   # bioenergy_biomass and bioenergy_biogas
                gen_type = 'biomass'
            if gen_type == 'distillate':
                gen_type = 'oil'
            self.capacity[gen_type] += decimal.Decimal(gen_info['registered_capacity'])
            debug(f"    Added {gen_info['registered_capacity']} MW of {gen_type} from {gen_code}")

    def output(self):
        """Output all our data as a dictionary ready for conversion to json format."""
        output = {}
        output['bounding_box'] = STATE_BOUNDING_BOXES[self.zone]
        output['capacity'] = {k: round(float(v), 2) for k, v in self.capacity.items()}
        output.update(ZONE_BOILERPLATE)
        return output


# TODO: put this stuff in a function, eg. read_generator_cache, refresh_generator_cache
CACHE_FILE = "AU_opennem_facilities.json"
facility_data = None
facility_request = None

# Try and load from cache
if os.path.exists(CACHE_FILE):
    mod_time = os.stat(CACHE_FILE).st_mtime
    now = dt.datetime.now()
    then = dt.datetime.fromtimestamp(mod_time)
    if now - then < dt.timedelta(days=7):
        # cache file is still relatively fresh, < 7 days old
        facility_data = open(CACHE_FILE).read()
        try:
            facilities = json.loads(facility_data)
        except json.decoder.JSONDecodeError:
            facility_data = None

# We don't have cached data, or the data is old or invalid, so refresh it
if not facility_data:
    facility_request = requests.get("https://data.opennem.org.au/facility/facility_registry.json")
    facility_data = facility_request.text
    debug(facility_request)
    debug(">", facility_data[:50], "<")
    open(CACHE_FILE, 'w').write(facility_data)

facilities = json.loads(facility_data)
debug("Loaded facility data.\n", json.dumps(facilities, indent=3)[:100])

zones = {zone: OpenNEMZone(zone) for zone in zone_map.keys()}

# Iterate through facilities and add each one to the relevant zone, 
# which totals up capacity by state and fuel type
for facility_code, facility in facilities.items():
    debug(facility_code, facility['duid_data'])
    if facility['status']['state'] == 'Commissioned':
        zone = zones[facility['region_id']]
        zone.update_from_facility_data(facility)
    else:
        debug(f"{facility_code} ({facility['region_id']}) is currently {facility['status']['state']}")

# Output zone info
json_zones = {zone_map[z.zone]: z.output() for z in zones.values()}
print("\nAustralian zone JSON data:")
print(json.dumps(json_zones, sort_keys=True, indent=4))
