import TradeOS from '../../components/TradeOS';

export default async function Page({params}:{params:Promise<{slug?:string[]}>}){
  const {slug=[]}=await params;
  return <TradeOS slug={slug}/>;
}
