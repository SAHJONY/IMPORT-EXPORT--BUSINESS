export type GlobeProviderId='reference'|'cesium-ion'|'google-photorealistic';
export type GlobeCapability='3d-globe'|'terrain'|'photorealistic-tiles'|'place-search'|'entity-overlay';

export type GlobeProviderDescriptor={
  id:GlobeProviderId;
  label:string;
  commercialPolicy:'internal-safe'|'provider-terms-required';
  browserCredential:'none'|'public-restricted-token';
  capabilities:GlobeCapability[];
  notes:string;
};

export const globeProviders:GlobeProviderDescriptor[]=[
  {
    id:'reference',
    label:'SAHJONY Reference Globe',
    commercialPolicy:'internal-safe',
    browserCredential:'none',
    capabilities:['3d-globe','entity-overlay'],
    notes:'Zero-key fallback. Displays only SAHJONY-controlled reference geometry and governed business overlays.'
  },
  {
    id:'cesium-ion',
    label:'Cesium ion',
    commercialPolicy:'provider-terms-required',
    browserCredential:'public-restricted-token',
    capabilities:['3d-globe','terrain','photorealistic-tiles','entity-overlay'],
    notes:'Enable only after commercial terms, quotas, attribution and browser-token restrictions are approved.'
  },
  {
    id:'google-photorealistic',
    label:'Google Photorealistic 3D Tiles',
    commercialPolicy:'provider-terms-required',
    browserCredential:'public-restricted-token',
    capabilities:['3d-globe','photorealistic-tiles','place-search','entity-overlay'],
    notes:'Metered provider. Requires approved billing, API restrictions, attribution and commercial-use review.'
  }
];

export type GlobeRuntimeState={
  provider:GlobeProviderId;
  ready:boolean;
  mode:'reference'|'provider';
  reason:string;
  capabilities:GlobeCapability[];
};

const allowed=new Set<GlobeProviderId>(globeProviders.map(p=>p.id));

export function resolveGlobeRuntime(env:Record<string,string|boolean|undefined>):GlobeRuntimeState{
  const requested=String(env.VITE_SAHJONY_GLOBE_PROVIDER||'reference') as GlobeProviderId;
  const provider=allowed.has(requested)?requested:'reference';
  const descriptor=globeProviders.find(p=>p.id===provider)!;
  if(provider==='reference')return{provider,ready:true,mode:'reference',reason:'Commercial-safe zero-key fallback active.',capabilities:descriptor.capabilities};

  const tokenPresent=Boolean(env.VITE_CESIUM_ION_TOKEN||env.VITE_GOOGLE_MAPS_API_KEY);
  if(!tokenPresent)return{provider,ready:false,mode:'provider',reason:'Provider selected but no browser-restricted public token is configured.',capabilities:descriptor.capabilities};
  return{provider,ready:true,mode:'provider',reason:'Provider configuration detected. Runtime adapter may initialize after terms and attribution gates pass.',capabilities:descriptor.capabilities};
}

export function providerDescriptor(id:GlobeProviderId){return globeProviders.find(item=>item.id===id)??globeProviders[0]}
