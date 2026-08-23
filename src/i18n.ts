import i18n from 'i18next';
import {initReactI18next} from 'react-i18next';

const STORAGE='sahjony.locale';
const params=new URLSearchParams(window.location.search);
const requested=(params.get('lang')||params.get('locale')||'').toLowerCase();
const stored=localStorage.getItem(STORAGE)||'';
const browser=(navigator.language||'en').toLowerCase();
const initial=requested.startsWith('es')?'es':stored.startsWith('es')?'es':browser.startsWith('es')?'es':'en';

export const resources={
  en:{translation:{
    common:{language:'Language',english:'English',spanish:'Spanish',original:'Original',continue:'Continue',refresh:'Refresh',search:'Search SAHJONY',signOut:'Sign out',authenticated:'Authenticated',limited:'Limited access',accessRequired:'Access required',sessionActive:'Session active'},
    brand:{globalTrade:'GLOBAL TRADE',tradeOS:'TRADE OS'},
    nav:{solutions:'Solutions',howItWorks:'How It Works',cubaPrivate:'Cuba Private Sector',signIn:'Sign In',startRequest:'Start a Request'},
    public:{eyebrow:'GLOBAL TRADE INFRASTRUCTURE',titleA:'From business need to',titleB:'controlled delivery.',body:'SAHJONY coordinates supplier discovery, commercial terms, compliance, documentation, logistics, payments and reconciliation through one governed operating system.',startSourcing:'Start a sourcing request',seeHow:'See how it works',worldwideSourcing:'Worldwide sourcing',caseExecution:'Case-based execution',failClosed:'Fail-closed controls',ownerReleases:'Owner-governed releases',commercial:'COMMERCIAL',qualifyDemand:'Qualify demand',qualifyBody:'Capture need and commercial fit before committing sourcing resources.',supply:'SUPPLY',sourceWorldwide:'Source worldwide',sourceBody:'Compare suppliers, MOQ, lead time, terms and landed economics.',control:'CONTROL',releaseEvidence:'Release with evidence',releaseBody:'Compliance, documents, payment and logistics gates remain fail-closed.',execution:'EXECUTION',trackReconciliation:'Track to reconciliation',trackBody:'Coordinate delivery, exceptions and final transaction economics.',workflow:'ONE CONTROLLED WORKFLOW',workflowTitle:'Need → source → qualify → execute → deliver.',workflowBody:'Every qualified opportunity becomes a case with one source of truth across the trade lifecycle.'},
    route:{notFoundTitle:'Workspace not found',notFoundText:'The requested SAHJONY workspace does not exist or the link has changed.',forbiddenTitle:'Access not available',forbiddenText:'This workspace is outside the permissions of this role.'},
    roles:{owner:'Owner',employee:'Employee',customer:'Customer',ownerCommand:'OWNER COMMAND',employeeOps:'EMPLOYEE OPERATIONS',customerPortal:'CUSTOMER PORTAL'},
    groups:{command:'Command',commercial:'Commercial',trade:'Trade',operations:'Operations',risk:'Risk & Compliance',finance:'Finance',intelligence:'Intelligence',administration:'Administration',daily:'Daily Operations',tradeWork:'Trade Work',controls:'Controls',workspace:'Workspace',channels:'Channels'},
    modules:{dashboard:'Executive Dashboard',myWork:'My Work',home:'Home',crm:'CRM & Opportunities',qualificationQueue:'Qualification Queue',globalSourcing:'Global Sourcing',supplierResearch:'Supplier Research',managedTrade:'Managed Trade',tradeCases:'Trade Cases',usImport:'U.S. Import Desk',intermediary:'Intermediary Desk',documents:'Documents',shipments:'Shipments',communications:'Communications',messages:'Messages',compliance:'Compliance & Risk',tradeStatus:'Trade Status',countries:'Country Intelligence',finance:'Finance & P&L',ai:'AI Intelligence',readiness:'Launch Readiness',businessEmail:'Business Communications',telegram:'Telegram Control'},
    emergency:{title:'Global Trade Operating System',browserError:'A browser error interrupted the interface.',operationError:'A browser operation failed unexpectedly.',initError:'The application could not initialize.',businessSite:'Business site',startRequest:'Start sourcing request',ownerOS:'Owner OS'}
  }},
  es:{translation:{
    common:{language:'Idioma',english:'Inglés',spanish:'Español',original:'Original',continue:'Continuar',refresh:'Actualizar',search:'Buscar en SAHJONY',signOut:'Cerrar sesión',authenticated:'Autenticado',limited:'Acceso limitado',accessRequired:'Acceso requerido',sessionActive:'Sesión activa'},
    brand:{globalTrade:'COMERCIO GLOBAL',tradeOS:'SISTEMA DE COMERCIO'},
    nav:{solutions:'Soluciones',howItWorks:'Cómo funciona',cubaPrivate:'Sector privado de Cuba',signIn:'Iniciar sesión',startRequest:'Iniciar solicitud'},
    public:{eyebrow:'INFRAESTRUCTURA DE COMERCIO GLOBAL',titleA:'De la necesidad empresarial a la',titleB:'entrega controlada.',body:'SAHJONY coordina la búsqueda de proveedores, términos comerciales, cumplimiento, documentación, logística, pagos y conciliación mediante un sistema operativo gobernado.',startSourcing:'Iniciar solicitud de abastecimiento',seeHow:'Ver cómo funciona',worldwideSourcing:'Búsqueda mundial de proveedores',caseExecution:'Ejecución basada en casos',failClosed:'Controles con bloqueo preventivo',ownerReleases:'Liberaciones gobernadas por el propietario',commercial:'COMERCIAL',qualifyDemand:'Calificar demanda',qualifyBody:'Capturar la necesidad y el encaje comercial antes de comprometer recursos de abastecimiento.',supply:'SUMINISTRO',sourceWorldwide:'Buscar proveedores en todo el mundo',sourceBody:'Comparar proveedores, MOQ, plazo, términos y costo puesto en destino.',control:'CONTROL',releaseEvidence:'Liberar con evidencia',releaseBody:'Los controles de cumplimiento, documentos, pago y logística permanecen bloqueados hasta cumplir los requisitos.',execution:'EJECUCIÓN',trackReconciliation:'Seguimiento hasta conciliación',trackBody:'Coordinar entrega, excepciones y economía final de la transacción.',workflow:'UN FLUJO CONTROLADO',workflowTitle:'Necesidad → abastecimiento → calificación → ejecución → entrega.',workflowBody:'Cada oportunidad calificada se convierte en un caso con una sola fuente de verdad durante todo el ciclo comercial.'},
    route:{notFoundTitle:'Espacio de trabajo no encontrado',notFoundText:'El espacio de trabajo solicitado de SAHJONY no existe o el enlace ha cambiado.',forbiddenTitle:'Acceso no disponible',forbiddenText:'Este espacio de trabajo está fuera de los permisos de este rol.'},
    roles:{owner:'Propietario',employee:'Empleado',customer:'Cliente',ownerCommand:'CENTRO DE MANDO DEL PROPIETARIO',employeeOps:'OPERACIONES DEL EMPLEADO',customerPortal:'PORTAL DEL CLIENTE'},
    groups:{command:'Mando',commercial:'Comercial',trade:'Comercio',operations:'Operaciones',risk:'Riesgo y Cumplimiento',finance:'Finanzas',intelligence:'Inteligencia',administration:'Administración',daily:'Operaciones diarias',tradeWork:'Trabajo comercial',controls:'Controles',workspace:'Espacio de trabajo',channels:'Canales'},
    modules:{dashboard:'Panel Ejecutivo',myWork:'Mi Trabajo',home:'Inicio',crm:'CRM y Oportunidades',qualificationQueue:'Cola de Calificación',globalSourcing:'Abastecimiento Global',supplierResearch:'Investigación de Proveedores',managedTrade:'Comercio Gestionado',tradeCases:'Casos Comerciales',usImport:'Mesa de Importación de EE. UU.',intermediary:'Mesa de Intermediación',documents:'Documentos',shipments:'Envíos',communications:'Comunicaciones',messages:'Mensajes',compliance:'Cumplimiento y Riesgo',tradeStatus:'Estado Comercial',countries:'Inteligencia de Países',finance:'Finanzas y Pérdidas/Ganancias',ai:'Inteligencia de IA',readiness:'Preparación para Lanzamiento',businessEmail:'Comunicaciones Empresariales',telegram:'Control de Telegram'},
    emergency:{title:'Sistema Operativo de Comercio Global',browserError:'Un error del navegador interrumpió la interfaz.',operationError:'Una operación del navegador falló inesperadamente.',initError:'La aplicación no pudo inicializarse.',businessSite:'Sitio empresarial',startRequest:'Iniciar solicitud de abastecimiento',ownerOS:'Sistema del Propietario'}
  }}
} as const;

i18n.use(initReactI18next).init({resources,lng:initial,fallbackLng:'en',supportedLngs:['en','es'],interpolation:{escapeValue:false},returnNull:false});

i18n.on('languageChanged',(lng)=>{
  const normalized=lng.startsWith('es')?'es':'en';
  localStorage.setItem(STORAGE,normalized);
  document.documentElement.lang=normalized;
  document.documentElement.dir='ltr';
  const url=new URL(window.location.href);
  if(normalized==='es')url.searchParams.set('lang','es');else url.searchParams.delete('lang');
  history.replaceState(history.state,'',url.pathname+url.search+url.hash);
});

document.documentElement.lang=initial;

export default i18n;
