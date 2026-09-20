from bsi.period_computer import periodize_hours

samples = [
    {'time':'2026-09-14T06:00','wind_deg':324,'wind_speed':8.0,'temp':12,'cloud_cover':20,'precip_mm':0,'precip_prob':0},
    {'time':'2026-09-14T08:00','wind_deg':316,'wind_speed':8.5,'temp':13,'cloud_cover':22,'precip_mm':0,'precip_prob':0},
    {'time':'2026-09-14T10:00','wind_deg':309,'wind_speed':8.0,'temp':14,'cloud_cover':25,'precip_mm':0,'precip_prob':0},
    {'time':'2026-09-14T12:00','wind_deg':304,'wind_speed':8.0,'temp':15,'cloud_cover':30,'precip_mm':0,'precip_prob':0},
    {'time':'2026-09-14T14:00','wind_deg':300,'wind_speed':8.0,'temp':16,'cloud_cover':35,'precip_mm':0,'precip_prob':0},
    {'time':'2026-09-14T16:00','wind_deg':287,'wind_speed':8.0,'temp':17,'cloud_cover':40,'precip_mm':0,'precip_prob':0},
    {'time':'2026-09-14T18:00','wind_deg':283,'wind_speed':6.0,'temp':15,'cloud_cover':45,'precip_mm':0,'precip_prob':0},
]
per = periodize_hours(samples,start_hour=6,end_hour=20)
import pprint
pprint.pprint(per)
