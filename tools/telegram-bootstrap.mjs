import process from 'node:process';

const token = String(process.env.TELEGRAM_BOT_TOKEN || '').trim();
const channelId = String(process.env.TELEGRAM_CHANNEL_ID || '').trim();
const botUsername = String(process.env.TELEGRAM_BOT_USERNAME || 'SahjonyGlobalTradeBot').replace(/^@/, '');
const publicUrl = `https://t.me/${botUsername}`;
const businessPhoneDisplay = String(process.env.SAHJONY_BUSINESS_PHONE_DISPLAY || '+1 281-662-8581').trim();
const businessPhoneE164 = String(process.env.SAHJONY_BUSINESS_PHONE_E164 || '+12816628581').trim();
const voicePhoneDisplay = String(process.env.SAHJONY_VOICE_PHONE_DISPLAY || '+1 346-534-6545').trim();
const voicePhoneE164 = String(process.env.SAHJONY_VOICE_PHONE_E164 || '+13465346545').trim();
const whatsappUrl = `https://wa.me/${businessPhoneE164.replace(/\D/g, '')}`;
const callUrl = `tel:${voicePhoneE164}`;

if (!token) throw new Error('TELEGRAM_BOT_TOKEN is required');

async function call(method, payload = {}) {
  const response = await fetch(`https://api.telegram.org/bot${token}/${method}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok || !data.ok) throw new Error(`${method}: ${data.description || response.status}`);
  return data.result;
}

const commands = [
  { command: 'start', description: 'Abrir SAHJONY Sales OS y hablar con Sofía' },
  { command: 'cotizar', description: 'Solicitar una cotización' },
  { command: 'comprar', description: 'Necesito comprar o importar' },
  { command: 'vender', description: 'Quiero ofrecer productos o capacidad' },
  { command: 'carga', description: 'Carga consolidada y envíos' },
  { command: 'vehiculo', description: 'Envío marítimo de vehículos a Cuba' },
  { command: 'mipyme', description: 'Compras/importación/exportación para MIPYMES' },
  { command: 'proveedor', description: 'Registro y evaluación de proveedores' },
  { command: 'whatsapp', description: `WhatsApp oficial ${businessPhoneDisplay}` },
  { command: 'llamar', description: `Llamar a SAHJONY ${voicePhoneDisplay}` },
  { command: 'estado', description: 'Estado de una operación existente' },
  { command: 'ayuda', description: 'Opciones y contacto' },
];

await call('setMyCommands', { commands, language_code: 'es' });
await call('setMyShortDescription', {
  short_description: `Sofía Sales OS 24/7: cotizaciones, compras, carga, vehículos, MIPYMES y proveedores.`,
  language_code: 'es',
});
await call('setMyDescription', {
  description: `SAHJONY GLOBAL TRADING Autonomous Sales OS. Sofía atiende 24/7, captura requisitos, califica oportunidades con evidencia, coordina sourcing/logística/KYB/pricing y prepara el siguiente paso comercial. Telegram oficial: @${botUsername}. WhatsApp: ${businessPhoneDisplay}. Llamadas: ${voicePhoneDisplay}. Las cotizaciones formales requieren costos, ruta, compliance y disponibilidad verificados.`,
  language_code: 'es',
});
await call('setChatMenuButton', {
  menu_button: { type: 'web_app', text: 'SAHJONY', web_app: { url: 'https://www.sahjony.com/' } },
}).catch(async () => {
  await call('setChatMenuButton', { menu_button: { type: 'commands' } });
});

let launchMessageId = null;
if (channelId) {
  const launchText = [
    '🚀 SAHJONY GLOBAL TRADING — AUTONOMOUS SALES OS',
    '',
    `Telegram oficial: @${botUsername}`,
    'Sofía Smith opera este canal 24/7 para convertir necesidades comerciales reales en operaciones verificadas:',
    '',
    '• Cotizaciones y compras internacionales',
    '• Sourcing con proveedores mayoristas',
    '• Carga consolidada y logística',
    '• Vehículos por vía marítima',
    '• MIPYMES y sector privado cubano',
    '• Importación / exportación',
    '• Calificación de RFQs y seguimiento comercial',
    '',
    'Sofía captura requisitos, identifica datos faltantes y coordina pricing, logística, KYB y compliance antes de una propuesta formal.',
    '',
    `📱 WhatsApp: ${businessPhoneDisplay}`,
    `☎️ Llamadas: ${voicePhoneDisplay}`,
    'Telegram, WhatsApp, teléfono y email se tratan como una sola relación comercial en CRM, sin desconectar las sesiones independientes de cada canal.',
    '',
    '📩 Escribe lo que necesitas comprar, vender, enviar o cotizar. Incluye producto, cantidad y destino si ya los conoces.',
    '',
    'SAHJONY no inventa precios, demanda, capacidad ni certificaciones. Los compromisos vinculantes, pagos y contratos permanecen bajo sus gates de aprobación.',
    '',
    publicUrl,
    'www.sahjony.com',
  ].join('\n');

  const message = await call('sendMessage', {
    chat_id: channelId,
    text: launchText,
    disable_web_page_preview: false,
    reply_markup: {
      inline_keyboard: [
        [{ text: '💬 Hablar con Sofía', url: `${publicUrl}?start=sales` }],
        [{ text: '📱 WhatsApp oficial', url: whatsappUrl }],
        [{ text: '☎️ Llamar a SAHJONY', url: callUrl }],
        [{ text: '🌐 SAHJONY', url: 'https://www.sahjony.com/' }],
      ],
    },
  });
  launchMessageId = message.message_id;
  await call('pinChatMessage', {
    chat_id: channelId,
    message_id: launchMessageId,
    disable_notification: true,
  }).catch(() => null);
}

const me = await call('getMe');
console.log(JSON.stringify({
  ok: true,
  mode: 'autonomous_sales_os',
  expectedBot: botUsername,
  bot: me.username,
  identityMatches: String(me.username || '').toLowerCase() === botUsername.toLowerCase(),
  publicUrl,
  whatsapp: {
    phone: businessPhoneDisplay,
    url: whatsappUrl,
    connectionTouched: false,
  },
  voice: {
    phone: voicePhoneDisplay,
    url: callUrl,
  },
  channelConfigured: Boolean(channelId),
  launchMessageId,
  commandsConfigured: commands.length,
}, null, 2));
