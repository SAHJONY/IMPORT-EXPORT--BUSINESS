from __future__ import annotations

import secrets
from datetime import datetime, timezone

from insforge_backend import get_backend
from lead_scout_api import LeadScoutIn, fingerprint, opportunity_score, priority


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


WORLDWIDE_TRADE_COUNTERPARTIES = [
    {
        "scout_name":"SAHJONY CEO Worldwide Buyer Book","business_name":"Sinograin","country":"CN","deal_side":"BUYER","lead_type":"BUYER",
        "product_need_or_offer":"Chinese state grain stockpiler and current large buyer of U.S. soybeans; Reuters reported Sinograin among state firms behind roughly one million tons of new-crop U.S. soybean purchases in early August 2026.",
        "source_url":"https://www.reuters.com/world/china/china-adds-13-us-soybean-cargoes-new-crop-buying-push-sources-say-2026-08-03/","source_description":"Reuters current soybean buying report","evidence_urls":["https://www.reuters.com/world/china/china-adds-13-us-soybean-cargoes-new-crop-buying-push-sources-say-2026-08-03/"],
        "notes":"AGRICULTURE_FOOD; SOYBEAN_BUYER. State counterparty; formal procurement/approved counterparty channel required."
    },
    {
        "scout_name":"SAHJONY CEO Worldwide Buyer Book","business_name":"COFCO Corporation","country":"CN","deal_side":"BUYER","lead_type":"BUYER",
        "product_need_or_offer":"Major Chinese state agricultural trader and recurring importer of soybeans and grains; identified alongside state buyers participating in accelerated U.S. soybean procurement in 2026.",
        "source_url":"https://www.reuters.com/world/china/china-adds-13-us-soybean-cargoes-new-crop-buying-push-sources-say-2026-08-03/","source_description":"Reuters current soybean procurement context","evidence_urls":["https://www.reuters.com/world/china/china-adds-13-us-soybean-cargoes-new-crop-buying-push-sources-say-2026-08-03/"],
        "notes":"AGRICULTURE_FOOD; GRAINS_OILSEEDS_BUYER. Verify current procurement desk and tender requirements."
    },
    {
        "scout_name":"SAHJONY CEO Worldwide Buyer Book","business_name":"Mostakbal Misr / Future of Egypt for Sustainable Development","country":"EG","deal_side":"BUYER","lead_type":"BUYER",
        "product_need_or_offer":"Egyptian state strategic-commodities buyer responsible for large wheat and food imports; current market conditions leave Egypt structurally dependent on imported wheat and alternative origins.",
        "source_url":"https://www.reuters.com/world/asia-pacific/global-wheat-buyers-brace-supply-squeeze-amid-black-sea-attacks-2026-08-20/","source_description":"Reuters current wheat-import market report and procurement-system context","evidence_urls":["https://www.reuters.com/world/asia-pacific/global-wheat-buyers-brace-supply-squeeze-amid-black-sea-attacks-2026-08-20/","https://www.reuters.com/world/africa/delayed-payments-broken-deals-put-egypts-state-grains-buyer-under-scrutiny-2025-11-13/"],
        "notes":"AGRICULTURE_FOOD; WHEAT_BUYER; GOVERNMENT_COUNTERPARTY. Formal procurement only; elevated payment/performance diligence."
    },
    {
        "scout_name":"SAHJONY CEO Worldwide Seller Book","business_name":"Al Dahra","country":"AE","deal_side":"SELLER","lead_type":"SUPPLIER",
        "product_need_or_offer":"UAE agribusiness supplying wheat under a 2026 Egypt import arrangement supported by Abu Dhabi financing; relevant institutional grains supplier/trader.",
        "source_url":"https://www.tradingview.com/news/reuters.com%2C2026%3Anewsml_L6N44D03E%3A0-egypt-signs-wheat-import-deal-with-uae-s-al-dahra-under-500-million-abu-dhabi-financing/","source_description":"Reuters-syndicated report on Egypt-Al Dahra wheat import deal","evidence_urls":["https://www.tradingview.com/news/reuters.com%2C2026%3Anewsml_L6N44D03E%3A0-egypt-signs-wheat-import-deal-with-uae-s-al-dahra-under-500-million-abu-dhabi-financing/"],
        "notes":"AGRICULTURE_FOOD; WHEAT_SUPPLIER. Verify current export availability and authorized sales channel."
    },
    {
        "scout_name":"SAHJONY CEO Worldwide Buyer Book","business_name":"China Mineral Resources Group (CMRG)","country":"CN","deal_side":"BUYER","lead_type":"BUYER",
        "product_need_or_offer":"China's centralized state iron-ore buyer negotiating annual supply terms with BHP, Rio Tinto and Fortescue and exercising purchasing control for domestic steel mills.",
        "source_url":"https://www.reuters.com/world/china/fortescue-hopes-swift-return-normal-china-trade-conditions-2026-08-20/","source_description":"Reuters current iron-ore term-contract negotiations","evidence_urls":["https://www.reuters.com/world/china/fortescue-hopes-swift-return-normal-china-trade-conditions-2026-08-20/"],
        "notes":"METALS_MINING; IRON_ORE_BUYER. Strategic state buyer; formal institutional route only."
    },
    {
        "scout_name":"SAHJONY CEO Worldwide Seller Book","business_name":"Fortescue Ltd","country":"AU","deal_side":"SELLER","lead_type":"SUPPLIER",
        "product_need_or_offer":"World-scale iron-ore producer shipping roughly 200 million tonnes annually and actively negotiating supply terms with China's central buyer CMRG.",
        "source_url":"https://www.reuters.com/world/china/fortescue-hopes-swift-return-normal-china-trade-conditions-2026-08-20/","source_description":"Reuters current Fortescue/CMRG trade report","evidence_urls":["https://www.reuters.com/world/china/fortescue-hopes-swift-return-normal-china-trade-conditions-2026-08-20/"],
        "notes":"METALS_MINING; IRON_ORE_SUPPLIER. Institutional offtake/sales desk required."
    },
    {
        "scout_name":"SAHJONY CEO Worldwide Seller Book","business_name":"BHP Group","country":"AU","deal_side":"SELLER","lead_type":"SUPPLIER",
        "product_need_or_offer":"Global mining major and iron-ore/copper supplier with a current China iron-ore supply agreement after negotiations with CMRG; large strategic minerals counterparty.",
        "source_url":"https://www.ft.com/content/3f83c4be-3b32-418f-92f9-b5f69c8357ab","source_description":"Current report on BHP-CMRG iron-ore supply agreement","evidence_urls":["https://www.ft.com/content/3f83c4be-3b32-418f-92f9-b5f69c8357ab"],
        "notes":"METALS_MINING; IRON_ORE_COPPER_SUPPLIER. Direct institutional sales/offtake route required."
    },
    {
        "scout_name":"SAHJONY CEO Worldwide Seller Book","business_name":"Rio Tinto","country":"AU","deal_side":"SELLER","lead_type":"SUPPLIER",
        "product_need_or_offer":"Top global iron-ore producer engaged in 2026 annual supply negotiations with China Mineral Resources Group; major iron ore, aluminum and copper supplier.",
        "source_url":"https://www.marketscreener.com/news/china-s-cmrg-tells-some-steel-mills-to-halt-talks-with-rio-tinto-for-shipments-from-september-sourc-ce7f50dcd089f623","source_description":"Reuters-syndicated current Rio Tinto/CMRG supply negotiations","evidence_urls":["https://www.marketscreener.com/news/china-s-cmrg-tells-some-steel-mills-to-halt-talks-with-rio-tinto-for-shipments-from-september-sourc-ce7f50dcd089f623"],
        "notes":"METALS_MINING; IRON_ORE_SUPPLIER. No open allocation implied."
    },
    {
        "scout_name":"SAHJONY CEO Worldwide Seller Book","business_name":"OCP Group","country":"MA","deal_side":"SELLER","lead_type":"SUPPLIER",
        "product_need_or_offer":"World-leading phosphate fertilizer producer with global export operations; 2026 market remains supply-constrained and OCP resumed phosphate shipments into the United States after duty suspension.",
        "source_url":"https://www.ocpgroup.ma/sites/default/files/2026-05/CP_OCP%20Q1%202026_vUK.pdf","source_description":"OCP official Q1 2026 market and export update","evidence_urls":["https://www.ocpgroup.ma/sites/default/files/2026-05/CP_OCP%20Q1%202026_vUK.pdf","https://www.dtnpf.com/agriculture/web/ag/crops/article/2026/07/17/duty-free-moroccan-phosphate-arrive"],
        "notes":"CHEMICALS_FERTILIZER; PHOSPHATE_FERTILIZER_SUPPLIER. Institutional sales channel required."
    },
    {
        "scout_name":"SAHJONY CEO Worldwide Buyer Book","business_name":"Petrovietnam Gas (PV GAS)","country":"VN","deal_side":"BUYER","lead_type":"BUYER",
        "product_need_or_offer":"Vietnamese state-controlled gas company sounding suppliers for a potential five-year LNG contract of roughly 250,000-450,000 tonnes annually for Thi Vai Terminal starting 2027 or later.",
        "source_url":"https://www.reuters.com/business/energy/vietnam-considers-second-lng-term-contract-after-deal-with-shell-document-shows-2026-08-12/","source_description":"Reuters current PV GAS market sounding","evidence_urls":["https://www.reuters.com/business/energy/vietnam-considers-second-lng-term-contract-after-deal-with-shell-document-shows-2026-08-12/"],
        "notes":"NATURAL_GAS; LNG_BUYER; HIGH_PRIORITY. Market sounding is not yet a published tender; qualify supplier-registration route."
    },
    {
        "scout_name":"SAHJONY CEO Worldwide Seller Book","business_name":"Sonatrach","country":"DZ","deal_side":"SELLER","lead_type":"SUPPLIER",
        "product_need_or_offer":"Algerian national energy company supplying LPG internationally; Indian Oil finalized a 2027 term deal for monthly 45,000-55,000 tonne propane-butane cargoes FOB.",
        "source_url":"https://www.reuters.com/business/energy/indian-oil-close-signing-lpg-import-deal-with-algerias-sonatrach-2027-sources-2026-08-20/","source_description":"Reuters current LPG supply contract report","evidence_urls":["https://www.reuters.com/business/energy/indian-oil-close-signing-lpg-import-deal-with-algerias-sonatrach-2027-sources-2026-08-20/"],
        "notes":"NATURAL_GAS; LPG_SUPPLIER. State counterparty; institutional sales/term-contract route only."
    },
    {
        "scout_name":"SAHJONY CEO Worldwide Buyer Book","business_name":"Indian Oil Corporation LPG Procurement","country":"IN","deal_side":"BUYER","lead_type":"BUYER",
        "product_need_or_offer":"IndianOil is diversifying LPG imports and has finalized monthly Algerian term liftings while India plans to source up to one quarter of LPG imports from the United States in 2027.",
        "source_url":"https://www.reuters.com/business/energy/indian-oil-close-signing-lpg-import-deal-with-algerias-sonatrach-2027-sources-2026-08-20/","source_description":"Reuters current LPG procurement report","evidence_urls":["https://www.reuters.com/business/energy/indian-oil-close-signing-lpg-import-deal-with-algerias-sonatrach-2027-sources-2026-08-20/"],
        "notes":"NATURAL_GAS; LPG_BUYER. Keep separate from IndianOil crude buyer record by product desk."
    },
    {
        "scout_name":"SAHJONY CEO Worldwide Seller Book","business_name":"Cargill","country":"US","deal_side":"SELLER","lead_type":"SUPPLIER",
        "product_need_or_offer":"Global agricultural commodity merchant and exporter across grains, oilseeds, food ingredients and feed; strategic supply counterparty for worldwide agriculture corridors.",
        "source_url":"https://www.cargill.com/food-beverage","source_description":"Cargill official global food and agriculture business information","evidence_urls":["https://www.cargill.com/food-beverage"],
        "notes":"AGRICULTURE_FOOD; GLOBAL_COMMODITY_SUPPLIER. Product/origin availability must be qualified by desk."
    },
    {
        "scout_name":"SAHJONY CEO Worldwide Seller Book","business_name":"ADM","country":"US","deal_side":"SELLER","lead_type":"SUPPLIER",
        "product_need_or_offer":"Global agricultural processor and commodity supplier across grains, oilseeds, feed and food ingredients; major institutional sourcing counterparty.",
        "source_url":"https://www.adm.com/en-us/products-services/","source_description":"ADM official products and services","evidence_urls":["https://www.adm.com/en-us/products-services/"],
        "notes":"AGRICULTURE_FOOD; GLOBAL_COMMODITY_SUPPLIER. Direct commercial onboarding required."
    },
    {
        "scout_name":"SAHJONY CEO Worldwide Seller Book","business_name":"Bunge Global SA","country":"CH","deal_side":"SELLER","lead_type":"SUPPLIER",
        "product_need_or_offer":"Global agribusiness and oilseed/grain merchant with worldwide origination, processing and distribution capabilities.",
        "source_url":"https://www.bunge.com/","source_description":"Bunge official global agribusiness information","evidence_urls":["https://www.bunge.com/"],
        "notes":"AGRICULTURE_FOOD; GRAINS_OILSEEDS_SUPPLIER. Institutional trading relationship required."
    },
    {
        "scout_name":"SAHJONY CEO Worldwide Seller Book","business_name":"Louis Dreyfus Company","country":"NL","deal_side":"SELLER","lead_type":"SUPPLIER",
        "product_need_or_offer":"Global merchant and processor of agricultural goods with major grains, oilseeds, sugar, coffee and cotton trading operations.",
        "source_url":"https://www.ldc.com/","source_description":"Louis Dreyfus Company official global commodity business information","evidence_urls":["https://www.ldc.com/"],
        "notes":"AGRICULTURE_FOOD; GLOBAL_COMMODITY_SUPPLIER. Direct desk onboarding required."
    },
]


async def ensure_worldwide_trade_counterparty_seed() -> dict:
    backend=get_backend(); inserted=0; already_present=0; failures=[]
    for raw in WORLDWIDE_TRADE_COUNTERPARTIES:
        try:
            payload=LeadScoutIn(**raw, consent_to_business_contact=False); fp=fingerprint(payload); existing=await backend.select('lead_scout_leads', params={'fingerprint':f'eq.{fp}','limit':'1'}) or []
            if existing: already_present+=1; continue
            score=opportunity_score(payload); ts=now(); lead_id=f'lsl_{secrets.token_urlsafe(10)}'; row={'lead_id':lead_id,'fingerprint':fp,'scout_name':payload.scout_name.strip(),'scout_code':'CEO-WORLDWIDE-TRADE','scout_contact':None,'business_name':payload.business_name.strip(),'contact_name':(payload.contact_name or '').strip() or None,'email':payload.email,'phone':(payload.phone or '').strip() or None,'country':payload.country.strip(),'city_region':(payload.city_region or '').strip() or None,'deal_side':payload.deal_side,'lead_type':payload.lead_type,'product_need_or_offer':payload.product_need_or_offer.strip(),'estimated_deal_value':payload.estimated_deal_value,'currency':payload.currency,'source_url':(payload.source_url or '').strip() or None,'source_description':(payload.source_description or '').strip() or None,'evidence_urls':payload.evidence_urls,'notes':(payload.notes or '').strip() or None,'consent_to_business_contact':False,'opportunity_score':score,'qualification_priority':priority(score),'status':'NEW','duplicate_candidate':False,'duplicate_of_lead_id':None,'referral_credit_status':'NOT_APPLICABLE','commission_status':'NOT_APPLICABLE','created_at':ts,'updated_at':ts}
            await backend.insert('lead_scout_leads',row); await backend.insert('lead_scout_audit',{'event_id':f'lsa_{secrets.token_urlsafe(10)}','lead_id':lead_id,'event_type':'ceo_worldwide_counterparty_ingested','summary':'CEO worldwide buyer/seller prospect ingested into CRM','payload':{'score':score,'priority':priority(score),'deal_side':payload.deal_side,'lead_type':payload.lead_type,'source_url':payload.source_url,'automatic_promotion':False},'created_at':ts}); inserted+=1
        except Exception as exc: failures.append({'business_name':raw.get('business_name'),'error':type(exc).__name__})
    return {'status':'ok' if not failures else 'partial','expected':len(WORLDWIDE_TRADE_COUNTERPARTIES),'inserted':inserted,'already_present':already_present,'failed':len(failures),'failures':failures,'automatic_deal_promotion':False,'automatic_outreach_authority':False}
