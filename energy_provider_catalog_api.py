from __future__ import annotations

from fastapi import FastAPI

from energy_operations_api import app as energy_operations_app

app = FastAPI(title='SAHJONY Energy Provider Catalog', version='1.1.0', docs_url=None, redoc_url=None)

CATALOG = [
    {
        'id':'ofac_sls','kind':'SANCTIONS','provider':'U.S. Treasury OFAC Sanctions List Service','authority':'FIRST_PARTY_GOVERNMENT',
        'recommended':True,'credential_required':False,'coverage':'U.S. OFAC SDN and non-SDN sanctions lists',
        'base_url':'https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/',
        'documentation':'https://sanctionslist.ofac.treas.gov/',
        'notes':'Primary OFAC sanctions-data service. Use explicit User-Agent on automated downloads. Treat matches as compliance review/hold evidence, never autonomous legal clearance.',
        'suggested_env':{
            'ENERGY_SANCTIONS_PROVIDER':'OFAC SLS','ENERGY_SANCTIONS_API_URL':'https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/',
            'ENERGY_SANCTIONS_AUTH_MODE':'none'
        },
        'status':'READY_FOR_PUBLIC_SOURCE_ADAPTER'
    },
    {
        'id':'eia_open_data_price','kind':'PRICE','provider':'U.S. Energy Information Administration Open Data','authority':'FIRST_PARTY_GOVERNMENT',
        'recommended':True,'credential_required':True,'coverage':'Petroleum spot/futures/refiner acquisition/import cost and related U.S. price series',
        'base_url':'https://api.eia.gov/v2/','documentation':'https://www.eia.gov/opendata/',
        'notes':'Free EIA API key required for automated API use. Strong first-party U.S. benchmark and petroleum market source; not a replacement for licensed global price assessments.',
        'suggested_env':{
            'ENERGY_PRICE_PROVIDER':'EIA Open Data','ENERGY_PRICE_API_URL':'https://api.eia.gov/v2/','ENERGY_PRICE_AUTH_MODE':'query','ENERGY_PRICE_AUTH_QUERY':'api_key'
        },
        'status':'CREDENTIAL_REQUIRED'
    },
    {
        'id':'eia_refinery','kind':'REFINERY','provider':'U.S. Energy Information Administration','authority':'FIRST_PARTY_GOVERNMENT',
        'recommended':True,'credential_required':True,'coverage':'U.S. refinery capacity, utilization, crude inputs, processing and individual-refinery annual capacity data',
        'base_url':'https://api.eia.gov/v2/','documentation':'https://www.eia.gov/petroleum/refinerycapacity/',
        'notes':'Use EIA API for recurring normalized data and annual EIA-820 refinery capacity files for facility-level verification.',
        'suggested_env':{
            'ENERGY_REFINERY_PROVIDER':'EIA Open Data','ENERGY_REFINERY_API_URL':'https://api.eia.gov/v2/','ENERGY_REFINERY_AUTH_MODE':'query','ENERGY_REFINERY_AUTH_QUERY':'api_key'
        },
        'status':'CREDENTIAL_REQUIRED'
    },
    {
        'id':'premium_ais','kind':'AIS','provider':'Licensed commercial AIS provider','authority':'COMMERCIAL_LICENSED',
        'recommended':True,'credential_required':True,'coverage':'Global vessel position, port calls, ETA, voyage and vessel identity data',
        'base_url':None,'documentation':None,
        'notes':'Select a licensed provider with global terrestrial/satellite coverage, IMO identity, historical track, port-call and commercial-use rights. Keep vendor-neutral until contracted.',
        'suggested_env':{},'status':'PROVIDER_SELECTION_REQUIRED'
    },
    {
        'id':'premium_global_prices','kind':'PRICE','provider':'Licensed global crude price-assessment provider','authority':'COMMERCIAL_LICENSED',
        'recommended':False,'credential_required':True,'coverage':'Global crude grades, differentials and assessed physical-market benchmarks',
        'base_url':None,'documentation':None,
        'notes':'Add when licensed. Use alongside EIA for international grade-level commercial analysis; never scrape restricted benchmark content.',
        'suggested_env':{},'status':'OPTIONAL_PREMIUM_PROVIDER'
    }
]

@app.get('/energy-provider-catalog/health')
async def health():
    return {
        'status':'ok','service':'sahjony-energy-provider-catalog','provider_presets':len(CATALOG),
        'first_party_sources':3,'commercial_slots':2,'automatic_credentials':False,
        'energy_deal_operations_mounted':True,'fail_closed':True
    }

@app.get('/energy-provider-catalog')
async def catalog():
    return {
        'providers':CATALOG,
        'recommended_sequence':['ofac_sls','eia_open_data_price','eia_refinery','premium_ais','premium_global_prices'],
        'authority':'DISCOVERY_AND_CONFIGURATION_GUIDANCE_ONLY'
    }

app.include_router(energy_operations_app.router)
