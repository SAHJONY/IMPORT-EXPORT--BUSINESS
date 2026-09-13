"""Evidence-first matching. Scores prioritize research; they never approve a deal."""
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import re, unicodedata


def normalize(value):
    return re.sub(r'[^a-z0-9 ]', ' ', unicodedata.normalize('NFKD',str(value or '')).encode('ascii','ignore').decode().lower())

# Matches use observed activity, never province names or unrelated page navigation.
RULES = [
    (r'\b(solar\w*|fotovoltaic\w*|renovable\w*)\b', ['longi'], 'Módulos solares'),
    (r'\b(gelato|helado\w*|lacteo\w*|pasteler\w*)\b', ['fonterra'], 'Ingredientes lácteos'),
    (r'\b(alimento\w*|gastronom\w*|catering|restaurante\w*|panader\w*)\b', ['arcor','olam-india','graincorp'], 'Alimentos e ingredientes'),
    (r'\b(bombeo|riego|bomba\w*)\b', ['grundfos','weg'], 'Bombeo y motores'),
    (r'\b(construccion|metalic\w*|acero|estructura\w*)\b', ['tata-steel'], 'Acero para fabricación / construcción'),
    (r'\b(electric\w*|automatiz\w*)\b', ['abb','weg'], 'Equipamiento eléctrico'),
    (r'\b(fertiliz\w*|agricol\w*|agropecuari\w*)\b', ['ocp','indorama'], 'Insumos agrícolas'),
]


def enrich(prospect):
    p=dict(prospect);text=normalize(p.get('observed_activity'))
    ids=list(p.get('supplier_ids') or []);reasons=[]
    for pattern,suppliers,reason in RULES:
        if re.search(pattern,text): ids.extend(suppliers);reasons.append(reason)
    p['supplier_ids']=list(dict.fromkeys(ids))
    p['match_basis']='CATEGORY_INFERENCE'
    p['proposal']=p.get('proposal') or ('Explorar: '+', '.join(reasons)+'. Confirmar necesidad real con el comprador.' if reasons else 'Confirmar necesidades de importación antes de proponer proveedores.')
    p['next_step']=p.get('next_step') or 'Confirmar comprador autorizado, necesidad, especificación, cantidad, presupuesto, origen y fecha de entrega.'
    p['blockers']=['BUYER_DEMAND_UNCONFIRMED','CURRENT_SUPPLIER_QUOTE_MISSING','DELIVERED_COST_INCOMPLETE','COUNTERPARTY_REVIEW_PENDING']
    p['ready_to_quote']=False
    p['estimated_profit']=None
    p['priority_score']=(25 if p.get('public_emails') or p.get('public_phones') else 0)+(15 if ids else 0)+(10 if p.get('published_interest') else 0)
    p['priority_basis']='Contactability and product relevance; not close probability'
    return p


def compare_prices(offer, competitor, today=None):
    """Only a fully specified equivalent offer earns a price advantage claim."""
    today=today or datetime.now(timezone.utc).date()
    fields=('product_spec','currency','unit','quantity','destination','incoterm','included_costs','payment_terms')
    blockers=[]
    for field in fields:
        if offer.get(field) in (None,'',[]) or competitor.get(field) in (None,'',[]): blockers.append('MISSING_'+field.upper())
        elif offer[field]!=competitor[field]: blockers.append('DIFFERENT_'+field.upper())
    for label,row in [('OFFER',offer),('COMPETITOR',competitor)]:
        try:
            if date.fromisoformat(row.get('valid_until',''))<today: blockers.append(label+'_EXPIRED')
        except (ValueError,TypeError):blockers.append(label+'_VALIDITY_MISSING')
        if not row.get('source_url'):blockers.append(label+'_SOURCE_MISSING')
        if row.get('landed_cost_complete') is not True:blockers.append(label+'_LANDED_COST_INCOMPLETE')
    try:
        a=Decimal(str(offer.get('price')));b=Decimal(str(competitor.get('price')))
        if not a.is_finite() or not b.is_finite() or a<=0 or b<=0:raise ValueError()
    except (InvalidOperation,ValueError):blockers.append('INVALID_PRICE');a=b=Decimal(0)
    if blockers:return {'comparable':False,'cheaper':None,'savings':None,'blockers':blockers}
    return {'comparable':True,'cheaper':a<b,'savings':float(b-a),'blockers':[]}
