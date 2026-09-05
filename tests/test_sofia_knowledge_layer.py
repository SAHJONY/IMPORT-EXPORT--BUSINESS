import asyncio
import sofia_knowledge_layer as k

def test_cuba_inventory_keeps_stage_distinctions(monkeypatch):
    async def snap(): return {'verified':True,'record_count':11753,'target':15600,'remaining_shortfall':3847}
    async def rows(table,limit=10000):
        if table=='external_trade_prospects': return [{'business_name':'Empresa Cuba','country':'CU','lead_type':'BUYER','product_need_or_offer':'food importer'}]
        return []
    monkeypatch.setattr(k,'_cuba_snapshot',snap); monkeypatch.setattr(k,'_cached_select',rows)
    out=asyncio.run(k.build_business_knowledge('Que tenemos de las MIPYMES de Cuba?'))
    assert out['cuba_private_sector']['record_count']==11753
    assert out['stage_semantics']['prospect'].startswith('research record')
    assert out['relevant_records'][0]['record']['business_name']=='Empresa Cuba'

def test_unavailable_is_not_zero(monkeypatch):
    async def snap(): return {'verified':False,'reason':'TimeoutError'}
    async def rows(table,limit=10000): return []
    monkeypatch.setattr(k,'_cuba_snapshot',snap); monkeypatch.setattr(k,'_cached_select',rows)
    out=asyncio.run(k.build_business_knowledge('hay leads en Cuba?'))
    assert out['cuba_private_sector']['verified'] is False
    assert any('unavailable' in x.lower() for x in out['truth_rules'])
